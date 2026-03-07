# -*- coding: utf-8 -*-
"""
VDC Vortex Module
=================
Magnus force, angular momentum, position-dependent chirality.

Physical model:
    In a rotating fluid, a moving object experiences a force
    perpendicular to both its velocity and the local rotation axis.
    This is the Magnus effect - the same force that makes a
    spinning ball curve in flight.

    In VDC, the substrate is a fluid. Matter moving through it
    experiences Magnus force from local vorticity (curl of velocity).
    This creates:
    - Spiral structure in dense regions (galaxies)
    - Position-dependent handedness (chirality)
    - Angular momentum that persists and grows

    Position-dependent chirality:
    The initial wave from the bang is slightly asymmetric
    (off-center boom, or random perturbations on the boundary).
    This asymmetry means different regions of the torus have
    slightly different vorticity signs after the wave wraps.
    Magnus force amplifies these differences over time.
    Result: some regions spin clockwise, others counterclockwise.
    This matches observation - galaxy spin handedness is not uniform.

    Connection to electromagnetism (flagged for future development):
    Vorticity in a fluid = magnetic field in EM.
    Magnus force = Lorentz force.
    The formal bridge (vorticity conservation -> gauge symmetry)
    is not yet built. This module captures the behavior without
    the full mathematical connection.

    Outflow from dense cores (stellar wind proxy):
    Extreme density peaks create outward pressure that pushes
    surrounding matter into halos and feeds filaments.
    Not targeted - emerges wherever density is extreme.
"""

import numpy as np
from vdc_kernel import VDCModule


class VortexModule(VDCModule):
    name = "vortex"

    def initialize(self, state, cfg):
        self.magnus_str    = cfg.float('magnus_str',       0.014)
        self.outflow_str   = cfg.float('outflow_str',      0.012)
        self.outflow_pctile= cfg.float('outflow_percentile', 98.0)

    def _curl(self, vx, vy, vz):
        """
        Vorticity vector field: omega = curl(v)
        omega_x = dVz/dy - dVy/dz
        omega_y = dVx/dz - dVz/dx
        omega_z = dVy/dx - dVx/dy
        """
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

    def step(self, state, cfg):
        intact = state.intact()

        # ---------------------------------------------------------- #
        # 1. MAGNUS FORCE
        # F = rho * (omega x v)
        # omega x v = (wy*vz - wz*vy,
        #              wz*vx - wx*vz,
        #              wx*vy - wy*vx)
        # Scaled by local density - denser matter feels more force.
        # Only where substrate is intact.
        # ---------------------------------------------------------- #
        wx, wy, wz = self._curl(state.vx, state.vy, state.vz)

        rho = state.grid
        fx_magnus = self.magnus_str * rho * (wy*state.vz - wz*state.vy)
        fy_magnus = self.magnus_str * rho * (wz*state.vx - wx*state.vz)
        fz_magnus = self.magnus_str * rho * (wx*state.vy - wy*state.vx)

        state.vx[intact] += fx_magnus[intact]
        state.vy[intact] += fy_magnus[intact]
        state.vz[intact] += fz_magnus[intact]

        # ---------------------------------------------------------- #
        # 2. PEAK OUTFLOW (dense core radiation/wind pressure)
        # Where density is extreme, matter pushes outward.
        # Creates halos around dense cores, feeds filaments.
        # Emerges wherever density exceeds threshold -
        # not pre-targeted at specific locations.
        # ---------------------------------------------------------- #
        if state.grid.max() > 0:
            thresh = np.percentile(state.grid, self.outflow_pctile)
            hot = state.grid > thresh
            if hot.any():
                hgx, hgy, hgz = self._grad(hot.astype(float))
                state.vx[intact] -= (self.outflow_str * hgx)[intact]
                state.vy[intact] -= (self.outflow_str * hgy)[intact]
                state.vz[intact] -= (self.outflow_str * hgz)[intact]

        # Store vorticity magnitude in state fields for logging
        omega_mag = np.sqrt(wx**2 + wy**2 + wz**2)
        state.fields['vorticity_mag'] = omega_mag
        state.fields['omega_z'] = wz

        # ---------------------------------------------------------- #
        # METRICS - octant chirality check
        # Divide grid into 8 octants, measure mean z-vorticity.
        # Mixed signs = emergent position-dependent chirality.
        # ---------------------------------------------------------- #
        N = state.N
        h = N // 2
        signs = []
        for i in [slice(0,h), slice(h,N)]:
            for j in [slice(0,h), slice(h,N)]:
                for k in [slice(0,h), slice(h,N)]:
                    v = wz[i,j,k].mean()
                    signs.append(int(np.sign(v)) if v != 0 else 0)

        mixed = len(set(s for s in signs if s != 0)) > 1

        return {
            'vort_mean':    float(omega_mag.mean()),
            'vort_max':     float(omega_mag.max()),
            'chirality_mixed': int(mixed),
        }

    def health_check(self, state):
        if 'vorticity_mag' in state.fields:
            vm = state.fields['vorticity_mag'].max()
            if vm > 1000:
                return f"Vorticity runaway: {vm:.2f}"
        return None
