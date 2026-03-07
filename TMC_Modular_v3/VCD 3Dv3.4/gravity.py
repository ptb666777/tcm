# -*- coding: utf-8 -*-
"""
VDC Gravity Module v3 - Tidal force from vortex complexity
============================================================
Gravity is not a fundamental force in VDC.
It is the tidal effect of vortex structures on surrounding substrate.

Key principles:
- No stable matter = no gravity
- Gravity strength scales with local matter_phase (vortex complexity)
- Simple vortex (hadron) = weak tidal pull
- Complex vortex (atom) = stronger tidal pull
- Jeans instability emerges naturally from this scaling:
  denser regions -> more complex matter -> stronger gravity ->
  more matter -> more complex matter -> runaway

Gravity gates on matter_phase > 0, not on epoch or temperature.
The tidal force is local - each cell's contribution scales with
its own vortex complexity.
"""

import numpy as np
from vdc_kernel import VDCModule


class GravityModule(VDCModule):
    name = "gravity"

    def initialize(self, state, cfg):
        N = self.N = state.N

        # Base tidal strength - scales with matter complexity
        self.grav_str         = cfg.float('grav_str',        0.012)
        # Complexity exponent - how much does complexity amplify gravity
        # 1.0 = linear, 2.0 = quadratic with matter phase
        self.complexity_exp   = cfg.float('complexity_exp',  1.5)
        self.jeans_cells      = cfg.float('jeans_length',    10.0)

        # Precompute Green's function for FFT Poisson solver
        kx = np.fft.fftfreq(N) * 2 * np.pi
        ky = np.fft.fftfreq(N) * 2 * np.pi
        kz = np.fft.fftfreq(N) * 2 * np.pi
        KX, KY, KZ = np.meshgrid(kx, ky, kz, indexing='ij')

        K2 = (2*(np.cos(KX)-1) +
               2*(np.cos(KY)-1) +
               2*(np.cos(KZ)-1))
        K2[0,0,0] = 1.0
        self._green    = -1.0 / K2
        self._green[0,0,0] = 0.0
        self._KX, self._KY, self._KZ = KX, KY, KZ

        # Jeans filter
        k_jeans = 2 * np.pi / self.jeans_cells
        K_mag   = np.sqrt(KX**2 + KY**2 + KZ**2)
        self._jeans_filter = 1.0 / (1.0 + (K_mag/(k_jeans+1e-10))**4)

    def _solve(self, density):
        rho_k = np.fft.fftn(density)
        phi_k = rho_k * self._green * self._jeans_filter
        phi   = np.fft.ifftn(phi_k).real
        phi_k2 = np.fft.fftn(phi)
        fx = np.fft.ifftn(1j * self._KX * phi_k2).real
        fy = np.fft.ifftn(1j * self._KY * phi_k2).real
        fz = np.fft.ifftn(1j * self._KZ * phi_k2).real
        return fx, fy, fz

    def step(self, state, cfg):
        # Gravity only where matter has formed
        phase = state.fields.get('matter_phase',
                np.zeros(state.grid.shape))

        # No stable matter anywhere = no gravity at all
        if phase.max() == 0:
            return {'grav_active': 0, 'force_mean': 0.0}

        intact = state.intact()

        # Effective density for gravity = density * complexity_factor
        # Complexity factor scales with matter_phase^complexity_exp
        # This means: simple vortex = weak gravity, complex = strong
        complexity = (phase / max(phase.max(), 1.0)) ** self.complexity_exp
        effective_density = state.grid * complexity

        fx, fy, fz = self._solve(effective_density)

        # Apply tidal force scaled by local complexity
        # Matter that is more complex both pulls and is pulled more strongly
        local_scale = self.grav_str * complexity
        state.vx[intact] -= (local_scale * fx)[intact]
        state.vy[intact] -= (local_scale * fy)[intact]
        state.vz[intact] -= (local_scale * fz)[intact]

        force_mag = np.sqrt(fx**2 + fy**2 + fz**2)
        active_cells = (phase > 0).sum()

        return {
            'grav_active':    1,
            'force_mean':     float(force_mag.mean()),
            'force_max':      float(force_mag.max()),
            'active_cells':   int(active_cells),
            'complexity_mean':float(complexity[phase>0].mean())
                              if active_cells > 0 else 0.0,
        }

    def health_check(self, state):
        if not np.isfinite(state.vx).all():
            return "vx NaN after gravity"
        return None
