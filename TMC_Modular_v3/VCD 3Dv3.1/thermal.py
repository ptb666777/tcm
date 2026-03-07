# -*- coding: utf-8 -*-
"""
VDC Thermal Module v2 - Epoch aware
Pressure and viscosity scale with epoch.
Advection always active (matter always moves with velocity).
Pre-confinement: high pressure, superfluid viscosity from matter_state.
Post-recombination: low pressure, gas viscosity.
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import epoch_at_least, CONFINEMENT, RECOMBINATION


class ThermalModule(VDCModule):
    name = "thermal"

    def initialize(self, state, cfg):
        self.pressure_k = cfg.float('pressure_k',  0.10)
        self.gamma      = cfg.float('gamma',        1.4)
        self.press_frac = cfg.float('press_frac',   0.40)
        self.v_cap      = cfg.float('v_cap',        2.0)
        self.diff_str   = cfg.float('diffusion',    0.025)

    def _grad(self, g):
        return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
                (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
                (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

    def _blur(self, g, s):
        return (g*(1-6*s)+s*(
            np.roll(g,1,axis=0)+np.roll(g,-1,axis=0)+
            np.roll(g,1,axis=1)+np.roll(g,-1,axis=1)+
            np.roll(g,1,axis=2)+np.roll(g,-1,axis=2)))

    def _advect(self, f, vx, vy, vz, dt=0.28):
        N = f.shape[0]
        sx=(np.arange(N)[:,None,None]-vx*dt)%N
        sy=(np.arange(N)[None,:,None]-vy*dt)%N
        sz=(np.arange(N)[None,None,:]-vz*dt)%N
        ix=sx.astype(int);fx=sx-ix
        iy=sy.astype(int);fy=sy-iy
        iz=sz.astype(int);fz=sz-iz
        return ((1-fx)*(1-fy)*(1-fz)*f[ix%N,iy%N,iz%N]+
                fx*(1-fy)*(1-fz)*f[(ix+1)%N,iy%N,iz%N]+
                (1-fx)*fy*(1-fz)*f[ix%N,(iy+1)%N,iz%N]+
                (1-fx)*(1-fy)*fz*f[ix%N,iy%N,(iz+1)%N]+
                fx*fy*(1-fz)*f[(ix+1)%N,(iy+1)%N,iz%N]+
                fx*(1-fy)*fz*f[(ix+1)%N,iy%N,(iz+1)%N]+
                (1-fx)*fy*fz*f[ix%N,(iy+1)%N,(iz+1)%N]+
                fx*fy*fz*f[(ix+1)%N,(iy+1)%N,(iz+1)%N])

    def step(self, state, cfg):
        intact = state.intact()
        T = state.temperature

        # Pressure scales with temperature
        # Hot plasma: high pressure resists compression strongly
        # Cold gas: low pressure, gravity can win
        pressure = self.pressure_k * T * (state.grid**self.gamma)
        pgx,pgy,pgz = self._grad(pressure)
        state.vx[intact] -= (pgx*self.press_frac)[intact]
        state.vy[intact] -= (pgy*self.press_frac)[intact]
        state.vz[intact] -= (pgz*self.press_frac)[intact]

        # Velocity cap
        speed = np.sqrt(state.vx**2+state.vy**2+state.vz**2)
        too_fast = (speed > self.v_cap) & intact
        if too_fast.any():
            state.vx[too_fast] *= self.v_cap/speed[too_fast]
            state.vy[too_fast] *= self.v_cap/speed[too_fast]
            state.vz[too_fast] *= self.v_cap/speed[too_fast]

        # Advection - matter moves with velocity field
        state.grid = self._advect(state.grid,state.vx,state.vy,state.vz)
        state.vx   = self._advect(state.vx,  state.vx,state.vy,state.vz)
        state.vy   = self._advect(state.vy,  state.vx,state.vy,state.vz)
        state.vz   = self._advect(state.vz,  state.vx,state.vy,state.vz)

        # Viscosity from matter_state module
        visc = state.fields.get('viscosity',
               np.full(state.grid.shape, 0.97))
        # Convert viscosity field to damping factor
        # Higher viscosity = more damping
        damp = 1.0 - visc
        damp = np.clip(damp, 0.90, 0.999)
        state.vx *= damp
        state.vy *= damp
        state.vz *= damp

        # Diffusion
        state.grid = self._blur(state.grid, self.diff_str)
        state.grid = np.maximum(state.grid, 0)

        return {
            'pressure_mean': float(pressure.mean()),
            'pressure_max':  float(pressure.max()),
            'max_speed':     float(speed.max()),
        }

    def health_check(self, state):
        if not np.isfinite(state.grid).all():
            return "grid NaN after advection"
        return None
