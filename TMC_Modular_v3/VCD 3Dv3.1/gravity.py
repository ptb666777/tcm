# -*- coding: utf-8 -*-
"""
VDC Gravity Module v2 - Epoch gated
Only active from CONFINEMENT onward (weak) and
full strength from RECOMBINATION onward.

Pre-confinement: gravity as we know it doesn't exist yet.
At confinement: weak proto-gravity emerges with pinning.
At recombination: pressure drops, full Jeans gravity active.
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import epoch_at_least, CONFINEMENT, RECOMBINATION


class GravityModule(VDCModule):
    name = "gravity"

    def initialize(self, state, cfg):
        N = state.N
        self.N            = N
        self.grav_str     = cfg.float('grav_str',      0.012)
        self.grav_weak    = cfg.float('grav_weak',     0.002)
        self.jeans_cells  = cfg.float('jeans_length',  10.0)

        # Precompute Green's function and Jeans filter
        kx = np.fft.fftfreq(N) * 2 * np.pi
        ky = np.fft.fftfreq(N) * 2 * np.pi
        kz = np.fft.fftfreq(N) * 2 * np.pi
        KX, KY, KZ = np.meshgrid(kx, ky, kz, indexing='ij')

        K2 = (2*(np.cos(KX)-1) +
               2*(np.cos(KY)-1) +
               2*(np.cos(KZ)-1))
        K2[0,0,0] = 1.0
        self._green = -1.0 / K2
        self._green[0,0,0] = 0.0

        k_jeans = 2*np.pi / self.jeans_cells
        K_mag   = np.sqrt(KX**2 + KY**2 + KZ**2)
        self._jeans_filter = 1.0/(1.0+(K_mag/(k_jeans+1e-10))**4)
        self._KX = KX
        self._KY = KY
        self._KZ = KZ

    def _solve(self, density, jeans_scale=1.0):
        rho_k = np.fft.fftn(density)
        # Adjust Jeans filter based on epoch
        # Pre-recombination: stronger Jeans suppression
        # Post-recombination: standard
        jf = self._jeans_filter ** (1.0 / max(jeans_scale, 0.1))
        phi_k = rho_k * self._green * jf
        phi   = np.fft.ifftn(phi_k).real
        phi_k2 = np.fft.fftn(phi)
        fx = np.fft.ifftn(1j * self._KX * phi_k2).real
        fy = np.fft.ifftn(1j * self._KY * phi_k2).real
        fz = np.fft.ifftn(1j * self._KZ * phi_k2).real
        return fx, fy, fz

    def step(self, state, cfg):
        # Gravity is off before confinement
        if not epoch_at_least(state.epoch, CONFINEMENT):
            return {'grav_active': 0, 'force_mean': 0.0}

        intact = state.intact()

        # Gravity strength depends on epoch
        if epoch_at_least(state.epoch, RECOMBINATION):
            # Full gravity - pressure has dropped, Jeans instability possible
            g_str = self.grav_str
            jeans_scale = 1.0
        else:
            # Weak proto-gravity at confinement
            # Pressure still high, strongly Jeans suppressed
            g_str = self.grav_weak
            jeans_scale = 0.3  # stronger Jeans suppression

        fx, fy, fz = self._solve(state.grid, jeans_scale)

        state.vx[intact] -= (g_str * fx)[intact]
        state.vy[intact] -= (g_str * fy)[intact]
        state.vz[intact] -= (g_str * fz)[intact]

        force_mag = np.sqrt(fx**2 + fy**2 + fz**2)
        return {
            'grav_active': 1,
            'force_mean':  float(force_mag.mean()),
            'force_max':   float(force_mag.max()),
            'grav_str':    float(g_str),
        }

    def health_check(self, state):
        if not np.isfinite(state.vx).all():
            return "vx NaN after gravity"
        return None
