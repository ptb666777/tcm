# -*- coding: utf-8 -*-
"""
VDC Wave Module
===============
Handles substrate wave propagation on a 3-torus.

Physical model:
    The substrate supports waves - disturbances that propagate
    through it at a characteristic speed. These are not sound waves
    or light waves. They are deformation waves in the substrate membrane.

    On a torus, waves wrap around. A wave from any point will
    eventually return to that point from the opposite direction.
    When it does, it interferes with itself and with waves from
    other sources. Constructive interference nodes become the
    scaffolding for matter accumulation - the cosmic web.

    This module handles:
    1. Wave propagation (standard wave equation on torus)
    2. Wave-to-matter coupling (wave gradient nudges matter velocity)
    3. Torus boundary conditions (periodic wrap - handled by np.roll)

    Surface tension restoring force lives in substrate.py
    because it is a property of the membrane, not the wave.
    The wave module just propagates. Substrate limits amplitude.

Wave equation:
    d²w/dt² = c² * ∇²w
    
    Where:
    - w is wave displacement field
    - c is wave speed (must be < 0.5 for numerical stability)
    - ∇²w is the discrete Laplacian on the torus grid

    Discretized:
    wave_v += c² * laplacian(wave)   [acceleration]
    wave   += wave_v                  [displacement update]

Stability condition (Courant):
    c * dt / dx < 1/sqrt(3) in 3D
    With dt=1, dx=1: c < 0.577
    We use c=0.45 for safety margin.

Wave-matter coupling:
    The wave gradient tells matter which way to flow.
    Matter velocity is nudged in the direction of the wave gradient.
    One-directional: wave affects matter, matter does not feed back
    into wave (prevents runaway feedback loops).
"""

import numpy as np
from vdc_kernel import VDCModule


class WaveModule(VDCModule):
    name = "wave"

    def initialize(self, state, cfg):
        self.wave_speed  = cfg.float('wave_speed',  0.45)
        self.wave_couple = cfg.float('wave_couple', 0.008)

        # Validate Courant condition
        # In 3D with 6-point stencil: c < 1/sqrt(3) ~ 0.577
        courant_limit = 1.0 / np.sqrt(3.0)
        if self.wave_speed >= courant_limit:
            print(f"WARNING: wave_speed={self.wave_speed} exceeds "
                  f"Courant limit {courant_limit:.3f}")
            print(f"         Simulation may be unstable.")
            print(f"         Recommended: wave_speed < 0.50")

    def _laplacian(self, g):
        """
        6-point discrete Laplacian on 3-torus.
        np.roll handles periodic boundary conditions automatically.
        No special edge treatment needed - torus wraps naturally.
        """
        return (np.roll(g,  1, axis=0) + np.roll(g, -1, axis=0) +
                np.roll(g,  1, axis=1) + np.roll(g, -1, axis=1) +
                np.roll(g,  1, axis=2) + np.roll(g, -1, axis=2) - 6*g)

    def _grad(self, g):
        """
        Central difference gradient on torus.
        Returns (gx, gy, gz) tuple.
        """
        gx = (np.roll(g, -1, axis=0) - np.roll(g, 1, axis=0)) / 2.0
        gy = (np.roll(g, -1, axis=1) - np.roll(g, 1, axis=1)) / 2.0
        gz = (np.roll(g, -1, axis=2) - np.roll(g, 1, axis=2)) / 2.0
        return gx, gy, gz

    def step(self, state, cfg):
        # ---------------------------------------------------------- #
        # 1. WAVE PROPAGATION
        # Standard second-order wave equation, leapfrog integration.
        # Leapfrog: update velocity first, then position.
        # This conserves energy better than Euler integration.
        # ---------------------------------------------------------- #
        c2 = self.wave_speed ** 2
        wave_accel = c2 * self._laplacian(state.wave)
        state.wave_v += wave_accel
        state.wave   += state.wave_v

        # ---------------------------------------------------------- #
        # 2. WAVE-TO-MATTER COUPLING
        # Wave gradient creates a pressure on matter.
        # Matter flows away from wave compression,
        # toward wave rarefaction.
        # This is how the wave interference pattern seeds
        # the density field - matter accumulates at the
        # nodes where waves cancel (rarefaction zones).
        #
        # Only applied where substrate is intact.
        # True void regions don't transmit the coupling
        # because there's no membrane to carry it.
        # ---------------------------------------------------------- #
        wgx, wgy, wgz = self._grad(state.wave)
        intact = state.intact()

        state.vx[intact] -= (self.wave_couple * wgx)[intact]
        state.vy[intact] -= (self.wave_couple * wgy)[intact]
        state.vz[intact] -= (self.wave_couple * wgz)[intact]

        # ---------------------------------------------------------- #
        # METRICS
        # ---------------------------------------------------------- #
        wave_E    = 0.5 * (state.wave**2 + state.wave_v**2).sum()
        wave_max  = np.abs(state.wave).max()
        wave_mean = np.abs(state.wave).mean()

        return {
            'wave_E':    float(wave_E),
            'wave_max':  float(wave_max),
            'wave_mean': float(wave_mean),
        }

    def health_check(self, state):
        wave_E = 0.5 * (state.wave**2 + state.wave_v**2).sum()
        if wave_E > 1e10:
            return f"Wave energy runaway: {wave_E:.2e}"
        if np.abs(state.wave_v).max() > 1000:
            return f"Wave velocity runaway: {np.abs(state.wave_v).max():.2f}"
        return None
