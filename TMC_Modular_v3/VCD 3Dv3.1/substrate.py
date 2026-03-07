# -*- coding: utf-8 -*-
"""
VDC Substrate Module v2
=======================
Rebuilt with correct initial conditions and epoch-gated mechanics.

What changed from v1:
    - Bang fills uniformly, no preferred direction
    - No void mechanics until STRUCTURE epoch
    - No tension degradation until matter has had time to move
    - Precipitation from wave energy (pre-confinement only)
    - Pin stabilization at confinement
    - Chladni pattern seeding at confinement (membrane oscillation)
    - Void formation only after RECOMBINATION when matter has left

The bang:
    Reality fills instantly and uniformly with energy.
    No preferred direction. No wave yet.
    The wave starts at CONFINEMENT when pins lock and
    the membrane has stable attachment points to oscillate from.
    Tiny random perturbations seed future structure -
    these are quantum fluctuations in the substrate at bang moment.

Surface tension dual role (same as v1, timing is different):
    1. Wave amplitude limiting (active from confinement)
    2. Void formation resistance (active from structure epoch)
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import (epoch_at_least, CONFINEMENT,
                          RECOMBINATION, STRUCTURE)


class SubstrateModule(VDCModule):
    name = "substrate"

    def initialize(self, state, cfg):
        N = state.N

        # Surface tension parameters
        self.surf_tension   = cfg.float('surf_tension',      0.015)
        self.surf_limit     = cfg.float('surf_limit',        8.0)

        # Void / tension parameters (late game only)
        self.tension_decay  = cfg.float('tension_decay',     0.018)
        self.tension_repair = cfg.float('tension_repair',    0.014)
        self.base_thin      = cfg.float('base_thin_density', 0.008)
        self.subway_press_k = cfg.float('subway_press_coeff',0.00002)
        self.tear_max       = cfg.float('tear_thresh_max',   0.05)
        self.spill_frac     = cfg.float('void_spill_frac',   0.9)
        self.void_loss_frac = cfg.float('void_loss_frac',    0.1)
        self.void_threshold = cfg.float('void_threshold',    0.05)

        # Confinement wave parameters
        # At confinement, pins lock and membrane starts oscillating.
        # This is the first wave - it creates the Chladni pattern.
        self.confinement_wave_E = cfg.float('confinement_wave_E', 80.0)
        self._confinement_wave_seeded = False

        # Bang parameters
        self.bang_energy  = cfg.float('bang_energy',   120.0)
        self.bang_noise   = cfg.float('bang_noise',    0.0001)

        # ---------------------------------------------------------- #
        # INITIAL CONDITIONS - THE BANG
        # Reality fills uniformly with energy.
        # No preferred direction. No structure. No void.
        # Tiny random perturbations seed future structure.
        # These are quantum fluctuations - genuinely random,
        # not placed by us.
        # ---------------------------------------------------------- #
        np.random.seed(cfg.int('random_seed', 42)
                       if cfg.int('random_seed', 42) != 0 else None)

        # Uniform energy fill with tiny perturbations
        # Mean density = bang_energy / N^3 (spread evenly)
        mean_density = self.bang_energy / (N**3)
        perturbation = np.random.exponential(self.bang_noise, (N, N, N))

        # Grid holds matter/energy density
        state.grid    = np.full((N, N, N), mean_density) + perturbation

        # No wave yet - membrane has no stable attachment points
        # Wave starts at confinement
        state.wave    = np.zeros((N, N, N))
        state.wave_v  = np.zeros((N, N, N))

        # Tension starts at 1.0 everywhere - reality is fully intact
        # at the bang. No void possible yet.
        state.tension = np.ones((N, N, N))

        # Void tracking initialized but inactive
        state.void_age  = np.zeros((N, N, N))
        state.seal_str  = np.zeros((N, N, N))
        state.subway    = 0.0

        print(f"  Substrate: bang fill complete")
        print(f"  Mean density: {state.grid.mean():.6f}")
        print(f"  Perturbation max: {perturbation.max():.6f}")
        print(f"  Wave: silent (waiting for confinement)")

    def _seed_confinement_wave(self, state):
        """
        At confinement, pins lock through the boundary.
        The membrane now has stable attachment points and
        begins to oscillate. This is the first wave.
        It propagates through the uniform matter field and
        creates the Chladni interference pattern that becomes
        the cosmic web scaffold.
        The wave is seeded by the density perturbations -
        slightly denser regions pin more strongly and
        oscillate with slightly more energy.
        No preferred direction - the pattern emerges from
        the perturbations themselves.
        """
        N = state.N
        # Wave amplitude proportional to local density perturbation
        # above the mean - denser pins oscillate more
        mean_rho = state.grid.mean()
        excess   = np.maximum(state.grid - mean_rho, 0)

        # Normalize and scale to confinement wave energy
        if excess.max() > 0:
            state.wave   = (excess / excess.max()) * self.confinement_wave_E
            state.wave_v = state.wave * 0.1  # small initial velocity
        else:
            # Fallback: pure noise wave if perfectly uniform
            state.wave   = np.random.normal(0, self.confinement_wave_E * 0.01,
                                           (N, N, N))
            state.wave_v = np.zeros((N, N, N))

        self._confinement_wave_seeded = True
        print(f"  [step {state.step}] Substrate: confinement wave seeded")
        print(f"  Wave max: {state.wave.max():.3f}")

    def step(self, state, cfg):
        # ---------------------------------------------------------- #
        # CONFINEMENT WAVE SEEDING
        # First time we reach confinement epoch: seed the wave.
        # ---------------------------------------------------------- #
        if (epoch_at_least(state.epoch, CONFINEMENT) and
                not self._confinement_wave_seeded):
            self._seed_confinement_wave(state)

        # ---------------------------------------------------------- #
        # SURFACE TENSION (wave amplitude limiting)
        # Active from confinement onward - needs pins to exist.
        # Same restoring force, wave scale.
        # ---------------------------------------------------------- #
        if epoch_at_least(state.epoch, CONFINEMENT):
            wave_restore = (self.surf_tension
                           * state.wave
                           * np.abs(state.wave)
                           / self.surf_limit**2)
            state.wave_v -= wave_restore
            state.wave    = np.clip(state.wave,
                                   -self.surf_limit * 3,
                                    self.surf_limit * 3)

        # ---------------------------------------------------------- #
        # TENSION / VOID MECHANICS
        # Only active from STRUCTURE epoch.
        # Voids form because matter LEFT - they are the result
        # of gravitational collapse pulling matter away,
        # not a primary mechanic running from the start.
        # ---------------------------------------------------------- #
        step_void_loss = 0.0
        if epoch_at_least(state.epoch, STRUCTURE):
            dynamic_thin = min(
                self.base_thin + state.subway * self.subway_press_k,
                self.tear_max)

            matter_present = state.grid > dynamic_thin
            state.tension[matter_present]  += self.tension_repair
            state.tension[~matter_present] -= self.tension_decay
            state.tension = np.clip(state.tension, 0, 1)

            true_void = state.tension < self.void_threshold
            state.void_age[true_void]  += 1
            state.void_age[~true_void]  = np.maximum(
                0, state.void_age[~true_void] - 3)

            # Matter in true void spills to neighbors
            void_matter = state.grid * true_void
            if void_matter.sum() > 0:
                spill = void_matter * self.spill_frac
                state.grid -= spill
                per_neighbor = spill / 6.0
                state.grid += (
                    np.roll(per_neighbor,  1, axis=0) +
                    np.roll(per_neighbor, -1, axis=0) +
                    np.roll(per_neighbor,  1, axis=1) +
                    np.roll(per_neighbor, -1, axis=1) +
                    np.roll(per_neighbor,  1, axis=2) +
                    np.roll(per_neighbor, -1, axis=2))
                lost = void_matter * self.void_loss_frac
                state.subway += lost.sum()
                step_void_loss = lost.sum()
                state.grid -= lost

            state.grid = np.maximum(state.grid, 0)

        # ---------------------------------------------------------- #
        # METRICS
        # ---------------------------------------------------------- #
        true_void_frac = (state.tension < self.void_threshold).mean()
        return {
            'void_frac':    float(true_void_frac),
            'tension_mean': float(state.tension.mean()),
            'void_loss':    float(step_void_loss),
            'wave_seeded':  int(self._confinement_wave_seeded),
        }

    def health_check(self, state):
        if state.grid.min() < -0.01:
            return f"Negative density: {state.grid.min():.4f}"
        return None
