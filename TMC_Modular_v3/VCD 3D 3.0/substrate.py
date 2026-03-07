# -*- coding: utf-8 -*-
"""
VDC Substrate Module
====================
The substrate is the layer beneath observable reality.
It is the medium from which reality precipitated at the bang.
It is what quantum particles are pinned to.
It is what black holes drain into.

Physical model:
    - Observable reality is a membrane on the substrate surface
    - The membrane has surface tension that resists deformation
    - Where matter is present: tension is maintained (thick, stable)
    - Where matter is absent long enough: tension degrades
    - When tension reaches zero: TRUE VOID forms
      True void is not empty space - it is the complete absence
      of the membrane. No fields, no forces, no light.
      It is the substrate showing through where reality failed.
    - True void boundary is where white hole eruptions can occur
      (handled by CycleModule - substrate just tracks the void)

Surface tension dual role:
    The same restoring force governs both:
    1. Wave amplitude limiting (large waves snap back)
    2. Void formation resistance (matter absence degrades tension)
    This is intentional - one mechanism, two scales.
    As subway pressure builds it lowers the tear threshold,
    making void formation easier (pressure pushing up from below).

Initial conditions:
    TRUE to the theory - reality starts from NOTHING.
    Not a noisy uniform soup. Actual zero.
    The bang is an eruption through the boundary at t=0.
    Matter precipitates FROM the wave front as it propagates.
    The grid starts empty. The bang fills it.
"""

import numpy as np
from vdc_kernel import VDCModule


class SubstrateModule(VDCModule):
    name = "substrate"

    def initialize(self, state, cfg):
        N = state.N

        # Read parameters
        self.tension_decay   = cfg.float('tension_decay',   0.018)
        self.tension_repair  = cfg.float('tension_repair',  0.014)
        self.tension_thresh  = cfg.float('tension_active',  0.3)
        self.void_threshold  = cfg.float('void_threshold',  0.05)
        self.base_thin       = cfg.float('base_thin_density', 0.008)
        self.subway_press_k  = cfg.float('subway_press_coeff', 0.00002)
        self.tear_max        = cfg.float('tear_thresh_max',  0.05)
        self.spill_frac      = cfg.float('void_spill_frac',  0.9)
        self.void_loss_frac  = cfg.float('void_loss_frac',   0.1)

        # Surface tension wave limiter parameters
        # Same tension mechanism, wave scale
        self.surf_tension    = cfg.float('surf_tension',    0.015)
        self.surf_limit      = cfg.float('surf_limit',      8.0)

        # Bang parameters
        # The bang is NOT a central point explosion.
        # It is a boundary eruption - matter precipitates FROM
        # a wave front that propagates from the boundary plane.
        # The boundary plane is at z=0 (one face of the torus).
        self.bang_energy     = cfg.float('bang_energy',     120.0)
        self.bang_thickness  = cfg.float('bang_thickness',  2.0)
        self.bang_noise      = cfg.float('bang_noise',      0.0001)

        # True void tracking
        state.void_age  = np.zeros((N, N, N))
        state.seal_str  = np.zeros((N, N, N))

        # Initialize state - TRUE VOID everywhere to start
        # Reality does not exist yet
        state.grid    = np.zeros((N, N, N))
        state.tension = np.zeros((N, N, N))  # no membrane yet
        state.wave    = np.zeros((N, N, N))
        state.wave_v  = np.zeros((N, N, N))
        state.subway  = 0.0

        # THE BANG
        # A wave front erupts from the z=0 boundary plane.
        # It carries the initial matter-forming energy.
        # Matter will precipitate from this wave as it propagates.
        # The wave moves in the +z direction initially,
        # then wraps the torus and interferes with itself.
        # This interference pattern becomes the cosmic web scaffold.
        #
        # Small asymmetry (random noise on the boundary plane)
        # seeds the density perturbations that become structure.
        # This is the quantum noise of the substrate at the moment
        # of eruption - the seeds of all future galaxies.
        xx, yy, zz = np.meshgrid(
            np.arange(N), np.arange(N), np.arange(N), indexing='ij')

        # Bang erupts from z=0 plane with small random perturbations
        np.random.seed(cfg.int('random_seed', 42)
                       if cfg.int('random_seed', 42) != 0 else None)

        # Wave front: thin shell at z=0 propagating in +z
        # Gaussian profile centered on z=0 plane
        bang_profile = np.exp(-zz**2 / (2 * self.bang_thickness**2))

        # Add tiny random perturbations - these seed all future structure
        # Without perturbations: perfectly uniform, no structure ever forms
        # With perturbations: Jeans instability grows them into filaments
        perturbation = np.random.exponential(
            self.bang_noise, (N, N, N))

        state.wave   = self.bang_energy * (bang_profile + perturbation)
        state.wave_v = self.bang_energy * 0.3 * bang_profile  # outward

        # Tension initializes along the wave front
        # Reality precipitates where the wave is strong
        state.tension = np.clip(bang_profile * 2.0, 0, 1)

        # Small amount of matter precipitates immediately at the front
        # (the rest precipitates as the wave propagates - handled each step)
        state.grid = self.bang_energy * 0.002 * bang_profile

        # Store coordinate grids for reuse
        self._xx = xx
        self._yy = yy
        self._zz = zz

    def step(self, state, cfg):
        N = state.N

        # ---------------------------------------------------------- #
        # 1. WAVE SURFACE TENSION (amplitude limiting)
        # The substrate resists extreme deformation.
        # Small waves propagate freely.
        # Large waves are pulled back toward equilibrium.
        # Restoring force scales with amplitude squared:
        #   F_restore = -sigma * w * |w| / L^2
        # This is the rubber band mechanism.
        # Same physics as surface tension in real fluids.
        # ---------------------------------------------------------- #
        wave_restore = (self.surf_tension
                        * state.wave
                        * np.abs(state.wave)
                        / self.surf_limit**2)
        state.wave_v -= wave_restore
        state.wave    = np.clip(state.wave,
                                -self.surf_limit * 3,
                                 self.surf_limit * 3)

        # ---------------------------------------------------------- #
        # 2. MATTER PRECIPITATION FROM WAVE
        # As the wave propagates through the substrate,
        # matter precipitates from it into observable reality.
        # Rate proportional to wave amplitude and temperature.
        # This is how thin hot plasma forms from the bang wave.
        # At high temperature (early): fast precipitation, hot plasma
        # At low temperature (late): slow precipitation, cold matter
        # ---------------------------------------------------------- #
        precip_rate = cfg.float('precip_rate', 0.0003)
        precipitation = (precip_rate
                         * state.temperature
                         * np.abs(state.wave)
                         * (state.tension < 0.5).astype(float))
        # Matter comes from the wave energy
        wave_energy_before = 0.5 * (state.wave**2 + state.wave_v**2)
        state.grid  += precipitation
        state.wave  -= precipitation * 0.1  # wave loses energy to matter
        state.grid   = np.maximum(state.grid, 0)

        # ---------------------------------------------------------- #
        # 3. TENSION DYNAMICS
        # Where matter is present: tension is maintained and repairs
        # Where matter is absent: tension degrades
        # Subway pressure lowers the tear threshold:
        #   high subway = more pressure pushing up = easier to tear
        # This couples the subway cycle to void formation naturally.
        # ---------------------------------------------------------- #
        dynamic_thin = min(
            self.base_thin + state.subway * self.subway_press_k,
            self.tear_max)

        matter_present = state.grid > dynamic_thin
        state.tension[matter_present]  += self.tension_repair
        state.tension[~matter_present] -= self.tension_decay
        state.tension = np.clip(state.tension, 0, 1)

        # ---------------------------------------------------------- #
        # 4. TRUE VOID FORMATION AND TRACKING
        # When tension reaches zero: true void forms.
        # True void is NOT empty space - it is the absence of reality.
        # Matter in true void cells spills to neighbors
        # (it can't exist where there's no membrane to sit on).
        # A fraction is lost to the subway (matter untied from reality).
        # ---------------------------------------------------------- #
        true_void = state.tension < self.void_threshold

        # Age the voids (older voids are more stable - harder to heal)
        state.void_age[true_void]  += 1
        state.void_age[~true_void]  = np.maximum(
            0, state.void_age[~true_void] - 3)

        # Spill matter from true void cells to neighbors
        void_matter = state.grid * true_void
        if void_matter.sum() > 0:
            spill = void_matter * self.spill_frac
            state.grid -= spill

            # Redistribute evenly to 6 face neighbors (conserved)
            per_neighbor = spill / 6.0
            state.grid += (
                np.roll(per_neighbor,  1, axis=0) +
                np.roll(per_neighbor, -1, axis=0) +
                np.roll(per_neighbor,  1, axis=1) +
                np.roll(per_neighbor, -1, axis=1) +
                np.roll(per_neighbor,  1, axis=2) +
                np.roll(per_neighbor, -1, axis=2))

            # Remaining fraction lost to subway
            # Matter untied from reality returns to substrate
            lost = void_matter * self.void_loss_frac
            state.subway += lost.sum()
            state.grid   -= lost

        state.grid = np.maximum(state.grid, 0)

        # ---------------------------------------------------------- #
        # 5. TENSION RESTORATION AT VOID BOUNDARIES
        # Seal strength builds at void edges over time.
        # Old stable voids resist healing.
        # Young fresh voids can be re-seeded by neighboring matter.
        # ---------------------------------------------------------- #
        # Void boundary: true void cells adjacent to matter
        boundary = true_void & (
            (np.roll(state.tension, 1,  axis=0) > self.void_threshold) |
            (np.roll(state.tension, -1, axis=0) > self.void_threshold) |
            (np.roll(state.tension, 1,  axis=1) > self.void_threshold) |
            (np.roll(state.tension, -1, axis=1) > self.void_threshold) |
            (np.roll(state.tension, 1,  axis=2) > self.void_threshold) |
            (np.roll(state.tension, -1, axis=2) > self.void_threshold))

        # Young boundary voids can heal if matter flows back
        young_boundary = boundary & (state.void_age < 5)
        state.tension[young_boundary] += self.tension_repair * 2

        # Update seal strength (used by CycleModule for eruption timing)
        state.seal_str[true_void]  = np.maximum(
            0, state.seal_str[true_void] - 0.1)
        state.seal_str[~true_void] += 0.1
        state.seal_str = np.clip(state.seal_str, 0, 5)

        # ---------------------------------------------------------- #
        # METRICS
        # Return values the kernel will log each step
        # ---------------------------------------------------------- #
        void_frac    = true_void.mean()
        tension_mean = state.tension.mean()
        precip_total = precipitation.sum()

        return {
            'void_frac':    float(void_frac),
            'tension_mean': float(tension_mean),
            'precip_total': float(precip_total),
            'dynamic_thin': float(dynamic_thin),
        }

    def health_check(self, state):
        if state.tension.min() < -0.01:
            return f"Tension below zero: {state.tension.min():.4f}"
        if state.void_age.max() > 1e6:
            return f"Void age overflow: {state.void_age.max():.0f}"
        return None
