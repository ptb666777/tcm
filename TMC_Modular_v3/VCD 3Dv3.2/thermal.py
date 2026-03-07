# -*- coding: utf-8 -*-
"""
VDC Thermal Module v3 - Photon Decoupling
==========================================
Key change: at recombination, photon pressure switches off suddenly.
Before recombination: baryons + photons act as one fluid, high pressure
After recombination:  photons stream away freely, pressure drops ~6000x
This is not a tweak - it's the actual physics of photon decoupling.
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import epoch_at_least, RECOMBINATION


class ThermalModule(VDCModule):
    name = "thermal"

    def initialize(self, state, cfg):
        # Pre-decoupling: full baryon-photon fluid pressure
        self.pressure_k       = cfg.float('pressure_k',        0.10)
        # Post-decoupling: baryon-only pressure (photons gone)
        # Real physics: drops ~6000x at recombination
        self.pressure_k_bary  = cfg.float('pressure_k_bary',   0.000016)
        self.gamma            = cfg.float('gamma',              1.4)
        self.press_frac       = cfg.float('press_frac',         0.40)
        self.v_cap            = cfg.float('v_cap',              2.0)
        self.diff_str         = cfg.float('diffusion',          0.025)

        self._decoupled = False

    def _grad(self, g):
        return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
                (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
                (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

    def _blur(self, g, s):
        return (g*(1-6*s)+s*(
            np.roll(g, 1,axis=0)+np.roll(g,-1,axis=0)+
            np.roll(g, 1,axis=1)+np.roll(g,-1,axis=1)+
            np.roll(g, 1,axis=2)+np.roll(g,-1,axis=2)))

    def _advect_all(self, fields, vx, vy, vz, dt=0.28):
        """
        Advect multiple fields simultaneously.
        Computes trilinear interpolation weights ONCE and reuses for all fields.
        4x faster than calling advect separately for each field.
        """
        N = fields[0].shape[0]
        sx = (np.arange(N)[:,None,None] - vx*dt) % N
        sy = (np.arange(N)[None,:,None] - vy*dt) % N
        sz = (np.arange(N)[None,None,:] - vz*dt) % N
        ix=sx.astype(int); fx=sx-ix
        iy=sy.astype(int); fy=sy-iy
        iz=sz.astype(int); fz=sz-iz
        # Compute all 8 weights once
        w000=(1-fx)*(1-fy)*(1-fz); w100=fx*(1-fy)*(1-fz)
        w010=(1-fx)*fy*(1-fz);     w001=(1-fx)*(1-fy)*fz
        w110=fx*fy*(1-fz);         w101=fx*(1-fy)*fz
        w011=(1-fx)*fy*fz;         w111=fx*fy*fz
        ix1=(ix+1)%N; iy1=(iy+1)%N; iz1=(iz+1)%N
        out = []
        for f in fields:
            out.append(
                w000*f[ix, iy, iz] + w100*f[ix1,iy, iz] +
                w010*f[ix, iy1,iz] + w001*f[ix, iy, iz1]+
                w110*f[ix1,iy1,iz] + w101*f[ix1,iy, iz1]+
                w011*f[ix, iy1,iz1]+ w111*f[ix1,iy1,iz1])
        return out

    def step(self, state, cfg):
        intact = state.intact()

        # Photon decoupling - happens once at recombination
        # Pressure drops suddenly as photons stream away freely
        if epoch_at_least(state.epoch, RECOMBINATION) and not self._decoupled:
            self._decoupled = True
            print(f"  [step {state.step}] Thermal: PHOTON DECOUPLING - "
                  f"pressure_k {self.pressure_k} -> {self.pressure_k_bary} "
                  f"({self.pressure_k/self.pressure_k_bary:.0f}x drop)")

        P_k = self.pressure_k_bary if self._decoupled else self.pressure_k

        # Pressure force - resists compression
        pressure = P_k * state.temperature * (state.grid ** self.gamma)
        pgx, pgy, pgz = self._grad(pressure)
        state.vx[intact] -= (pgx * self.press_frac)[intact]
        state.vy[intact] -= (pgy * self.press_frac)[intact]
        state.vz[intact] -= (pgz * self.press_frac)[intact]

        # Velocity cap
        speed = np.sqrt(state.vx**2 + state.vy**2 + state.vz**2)
        too_fast = (speed > self.v_cap) & intact
        if too_fast.any():
            state.vx[too_fast] *= self.v_cap / speed[too_fast]
            state.vy[too_fast] *= self.v_cap / speed[too_fast]
            state.vz[too_fast] *= self.v_cap / speed[too_fast]

        # Advection - matter moves with velocity field
        # All 4 fields advected together, weights computed once (4x faster)
        state.grid, state.vx, state.vy, state.vz = self._advect_all(
            [state.grid, state.vx, state.vy, state.vz],
            state.vx, state.vy, state.vz)

        # Viscosity from matter_state module
        visc = state.fields.get('viscosity', np.full(state.grid.shape, 0.97))
        damp = np.clip(1.0 - visc, 0.90, 0.999)
        state.vx *= damp
        state.vy *= damp
        state.vz *= damp

        # Diffusion
        state.grid = self._blur(state.grid, self.diff_str)
        state.grid = np.maximum(state.grid, 0)

        return {
            'pressure_k':    float(P_k),
            'pressure_mean': float(pressure.mean()),
            'pressure_max':  float(pressure.max()),
            'max_speed':     float(speed.max()),
            'decoupled':     int(self._decoupled),
        }

    def health_check(self, state):
        if not np.isfinite(state.grid).all():
            return "grid NaN after advection"
        return None
