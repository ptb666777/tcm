# -*- coding: utf-8 -*-
"""
VDC Vortex Module v2 - Epoch gated
Magnus force only active from CONFINEMENT onward.
Full vortex structures only from RECOMBINATION.
Pre-confinement: no stable rotation possible.
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import epoch_at_least, CONFINEMENT, RECOMBINATION


class VortexModule(VDCModule):
    name = "vortex"

    def initialize(self, state, cfg):
        self.magnus_str     = cfg.float('magnus_str',          0.014)
        self.magnus_weak    = cfg.float('magnus_weak',         0.002)
        self.outflow_str    = cfg.float('outflow_str',         0.012)
        self.outflow_pctile = cfg.float('outflow_percentile',  98.0)

    def _curl(self, vx, vy, vz):
        wx=((np.roll(vz,-1,axis=1)-np.roll(vz,1,axis=1))/2-
            (np.roll(vy,-1,axis=2)-np.roll(vy,1,axis=2))/2)
        wy=((np.roll(vx,-1,axis=2)-np.roll(vx,1,axis=2))/2-
            (np.roll(vz,-1,axis=0)-np.roll(vz,1,axis=0))/2)
        wz=((np.roll(vy,-1,axis=0)-np.roll(vy,1,axis=0))/2-
            (np.roll(vx,-1,axis=1)-np.roll(vx,1,axis=1))/2)
        return wx, wy, wz

    def _grad(self, g):
        return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
                (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
                (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

    def step(self, state, cfg):
        if not epoch_at_least(state.epoch, CONFINEMENT):
            return {'vortex_active': 0, 'vort_mean': 0.0}

        intact = state.intact()
        wx, wy, wz = self._curl(state.vx, state.vy, state.vz)

        # Magnus strength scales with epoch
        m_str = (self.magnus_str if epoch_at_least(state.epoch, RECOMBINATION)
                 else self.magnus_weak)

        rho = state.grid
        state.vx[intact] += (m_str*rho*(wy*state.vz-wz*state.vy))[intact]
        state.vy[intact] += (m_str*rho*(wz*state.vx-wx*state.vz))[intact]
        state.vz[intact] += (m_str*rho*(wx*state.vy-wy*state.vx))[intact]

        # Peak outflow only post-recombination (stellar winds need stars)
        if (epoch_at_least(state.epoch, RECOMBINATION) and
                state.grid.max() > 0):
            thresh = np.percentile(state.grid, self.outflow_pctile)
            hot = state.grid > thresh
            if hot.any():
                hgx,hgy,hgz = self._grad(hot.astype(float))
                state.vx[intact] -= (self.outflow_str*hgx)[intact]
                state.vy[intact] -= (self.outflow_str*hgy)[intact]
                state.vz[intact] -= (self.outflow_str*hgz)[intact]

        omega_mag = np.sqrt(wx**2+wy**2+wz**2)
        state.fields['vorticity_mag'] = omega_mag
        state.fields['omega_z'] = wz

        # Chirality check
        N = state.N; h = N//2
        signs = [int(np.sign(wz[i,j,k].mean())) if wz[i,j,k].mean()!=0 else 0
                 for i in [slice(0,h),slice(h,N)]
                 for j in [slice(0,h),slice(h,N)]
                 for k in [slice(0,h),slice(h,N)]]
        mixed = len(set(s for s in signs if s!=0)) > 1

        return {
            'vortex_active':   1,
            'vort_mean':       float(omega_mag.mean()),
            'vort_max':        float(omega_mag.max()),
            'chirality_mixed': int(mixed),
        }

    def health_check(self, state):
        if 'vorticity_mag' in state.fields:
            if state.fields['vorticity_mag'].max() > 1000:
                return f"Vorticity runaway"
        return None
