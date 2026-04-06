# -*- coding: utf-8 -*-
"""
VDC Vortex Module v4 - Circulation Conservation
================================================
Key change from v3:
- Circulation (curl of velocity) is now conserved with a floor.
- If vorticity drops below circ_floor, a restoring injection
  nudges velocity to rebuild it. This prevents the bleed-to-zero
  problem where structure flatlines because circulation decays
  faster than any force can rebuild it.
- Magnus force unchanged.
- Chirality detection unchanged.
- Update order: this module now runs BEFORE thermal so Magnus
  force acts on velocity before advection smooths it.
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
        # Circulation conservation
        self.circ_floor      = cfg.float('circ_floor',         0.001)
        self.circ_restore    = cfg.float('circ_restore',       0.003)

    def _curl(self, vx, vy, vz):
        wx = ((np.roll(vz,-1,axis=1)-np.roll(vz,1,axis=1))/2 -
              (np.roll(vy,-1,axis=2)-np.roll(vy,1,axis=2))/2)
        wy = ((np.roll(vx,-1,axis=2)-np.roll(vx,1,axis=2))/2 -
              (np.roll(vz,-1,axis=0)-np.roll(vz,1,axis=0))/2)
        wz = ((np.roll(vy,-1,axis=0)-np.roll(vy,1,axis=0))/2 -
              (np.roll(vx,-1,axis=1)-np.roll(vx,1,axis=1))/2)
        return wx, wy, wz

    def _grad(self, g):
        return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
                (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
                (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

    def _restore_circulation(self, state, omega_mag, intact):
        """
        Where vorticity has dropped below the floor, inject a small
        restoring velocity kick sourced from the local density gradient.
        This models the superfluid property that circulation is quantized
        and cannot simply bleed away - it must be explicitly annihilated.
        """
        low = (omega_mag < self.circ_floor) & intact
        if not low.any():
            return

        # Kick direction: cross of density gradient with local omega
        # Falls back to density gradient if omega is near zero
        gx, gy, gz = self._grad(state.grid)
        grad_mag = np.sqrt(gx**2 + gy**2 + gz**2) + 1e-10

        # Normalise gradient and apply small restoring kick
        state.vx[low] += (self.circ_restore * gy / grad_mag)[low]
        state.vy[low] += (self.circ_restore * gz / grad_mag)[low]
        state.vz[low] += (self.circ_restore * gx / grad_mag)[low]

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

        # Circulation conservation - restore where vorticity bled out
        self._restore_circulation(state, omega_mag, intact)

        # Recompute after restoration
        wx, wy, wz = self._curl(state.vx, state.vy, state.vz)
        omega_mag  = np.sqrt(wx**2 + wy**2 + wz**2)
        state.fields['vorticity_mag'] = omega_mag
        state.fields['omega_z']       = wz

        # Complexity scaling - more complex matter = stronger Magnus
        complexity = (phase / max(phase.max(), 1.0)) ** self.complexity_exp

        rho   = state.grid
        m_str = self.magnus_str * complexity

        state.vx[intact] += (m_str*rho*(wy*state.vz - wz*state.vy))[intact]
        state.vy[intact] += (m_str*rho*(wz*state.vx - wx*state.vz))[intact]
        state.vz[intact] += (m_str*rho*(wx*state.vy - wy*state.vx))[intact]

        # Peak outflow where matter is most complex and dense
        matter_cells = phase > 0
        if matter_cells.any() and state.grid.max() > 0:
            thresh = np.percentile(state.grid[matter_cells],
                                   self.outflow_pctile)
            hot = (state.grid > thresh) & matter_cells
            if hot.any():
                hgx, hgy, hgz = self._grad(hot.astype(float))
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
            'circ_restored':   int(((omega_mag < self.circ_floor) & intact).sum()),
        }

    def health_check(self, state):
        if 'vorticity_mag' in state.fields:
            if state.fields['vorticity_mag'].max() > 1000:
                return "Vorticity runaway"
        return None
