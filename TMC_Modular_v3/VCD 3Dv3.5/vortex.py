# -*- coding: utf-8 -*-
"""
VDC Vortex Module v3 - Matter-phase gated
==========================================
No stable matter = no stable vortex.
Vortex strength scales with matter_phase complexity.
Magnus force only where matter has formed.
"""

import numpy as np
from vdc_kernel import VDCModule


class VortexModule(VDCModule):
    name = "vortex"

    def initialize(self, state, cfg):
        self.magnus_str      = cfg.float('magnus_str',         0.014)
        self.outflow_str     = cfg.float('outflow_str',        0.012)
        self.outflow_pctile  = cfg.float('outflow_percentile', 98.0)
        self.complexity_exp  = cfg.float('complexity_exp',     1.5)

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
        phase = state.fields.get('matter_phase',
                np.zeros(state.grid.shape))

        # Always compute vorticity - needed by wave module for pin detection
        wx, wy, wz = self._curl(state.vx, state.vy, state.vz)
        omega_mag  = np.sqrt(wx**2 + wy**2 + wz**2)
        state.fields['vorticity_mag'] = omega_mag
        state.fields['omega_z']       = wz

        # Magnus force only where matter exists
        if phase.max() == 0:
            return {
                'vortex_active':   0,
                'vort_mean':       float(omega_mag.mean()),
                'vort_max':        float(omega_mag.max()),
                'chirality_mixed': 0,
            }

        intact = state.intact()

        # Complexity scaling - more complex matter = stronger Magnus
        complexity = (phase / max(phase.max(), 1.0)) ** self.complexity_exp

        rho = state.grid
        m_str = self.magnus_str * complexity

        state.vx[intact] += (m_str*rho*(wy*state.vz-wz*state.vy))[intact]
        state.vy[intact] += (m_str*rho*(wz*state.vx-wx*state.vz))[intact]
        state.vz[intact] += (m_str*rho*(wx*state.vy-wy*state.vx))[intact]

        # Peak outflow where matter is most complex and dense
        matter_cells = phase > 0
        if matter_cells.any() and state.grid.max() > 0:
            thresh = np.percentile(state.grid[matter_cells],
                                   self.outflow_pctile)
            hot = (state.grid > thresh) & matter_cells
            if hot.any():
                hgx,hgy,hgz = self._grad(hot.astype(float))
                state.vx[intact] -= (self.outflow_str*hgx)[intact]
                state.vy[intact] -= (self.outflow_str*hgy)[intact]
                state.vz[intact] -= (self.outflow_str*hgz)[intact]

        # Chirality check
        N = state.N; h = N//2
        signs = []
        for i in [slice(0,h), slice(h,N)]:
            for j in [slice(0,h), slice(h,N)]:
                for k in [slice(0,h), slice(h,N)]:
                    v = wz[i,j,k].mean()
                    if v != 0: signs.append(int(np.sign(v)))
        mixed = len(set(signs)) > 1

        return {
            'vortex_active':   1,
            'vort_mean':       float(omega_mag.mean()),
            'vort_max':        float(omega_mag.max()),
            'chirality_mixed': int(mixed),
            'complexity_mean': float(complexity[phase>0].mean()),
        }

    def health_check(self, state):
        if 'vorticity_mag' in state.fields:
            if state.fields['vorticity_mag'].max() > 1000:
                return "Vorticity runaway"
        return None
