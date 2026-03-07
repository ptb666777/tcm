# -*- coding: utf-8 -*-
"""
VDC Wave Module v2 - Epoch gated
Wave propagation only active from CONFINEMENT onward.
Pre-confinement: no stable pins, no membrane oscillation.
At confinement: Chladni pattern begins forming.
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import epoch_at_least, CONFINEMENT


class WaveModule(VDCModule):
    name = "wave"

    def initialize(self, state, cfg):
        self.wave_speed  = cfg.float('wave_speed',  0.45)
        self.wave_couple = cfg.float('wave_couple', 0.008)
        courant = 1.0 / np.sqrt(3.0)
        if self.wave_speed >= courant:
            print(f"WARNING: wave_speed={self.wave_speed} near "
                  f"Courant limit {courant:.3f}")

    def _laplacian(self, g):
        return (np.roll(g, 1,axis=0)+np.roll(g,-1,axis=0)+
                np.roll(g, 1,axis=1)+np.roll(g,-1,axis=1)+
                np.roll(g, 1,axis=2)+np.roll(g,-1,axis=2)-6*g)

    def _grad(self, g):
        return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
                (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
                (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

    def step(self, state, cfg):
        # No wave before confinement - no stable pins yet
        if not epoch_at_least(state.epoch, CONFINEMENT):
            return {'wave_active': 0, 'wave_E': 0.0}

        # Wave propagation
        c2 = self.wave_speed**2
        state.wave_v += c2 * self._laplacian(state.wave)
        state.wave   += state.wave_v

        # Wave-matter coupling (Chladni effect)
        # Matter nudged toward wave nodes (low amplitude regions)
        wgx, wgy, wgz = self._grad(state.wave)
        intact = state.intact()
        state.vx[intact] -= (self.wave_couple * wgx)[intact]
        state.vy[intact] -= (self.wave_couple * wgy)[intact]
        state.vz[intact] -= (self.wave_couple * wgz)[intact]

        wave_E = 0.5*(state.wave**2 + state.wave_v**2).sum()
        return {
            'wave_active': 1,
            'wave_E':      float(wave_E),
            'wave_max':    float(np.abs(state.wave).max()),
        }

    def health_check(self, state):
        wave_E = 0.5*(state.wave**2+state.wave_v**2).sum()
        if wave_E > 1e10:
            return f"Wave energy runaway: {wave_E:.2e}"
        return None
