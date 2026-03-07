# -*- coding: utf-8 -*-
"""
VDC Thermal Module
==================
Handles pressure, cooling, and the plasma-to-structure transition.

Physical model:
    Early universe: hot plasma, high pressure resists compression.
    As the wave energy disperses and matter thins out, temperature
    drops. Pressure falls. Gravity can now win over pressure and
    matter begins to clump into filaments and nodes.

    This is the Jeans instability - the competition between
    gravity (attractive, grows clumps) and pressure (repulsive,
    resists clumps). When temperature drops enough that gravity
    wins, structure formation begins.

    Temperature is set by the kernel's epoch system.
    This module reads state.temperature and applies pressure
    accordingly. It does not set the temperature - that's
    the kernel's job (cooling curve in config).

Pressure model:
    P = K * T * rho^gamma
    
    Where:
    - K     is pressure coefficient
    - T     is temperature (from epoch)
    - rho   is local density
    - gamma is adiabatic index (1.4 for diatomic ideal gas,
            we use this as a reasonable approximation)

    Pressure gradient creates a force that pushes matter
    from high-density (high-pressure) to low-density regions.
    This is what prevents all matter from collapsing to a point.

Advection:
    Matter moves with the velocity field.
    Trilinear interpolation on the torus.
    This is the actual fluid transport - without this
    nothing physically moves despite having velocities.
    Velocity damping (friction) prevents runaway speeds.
"""

import numpy as np
from vdc_kernel import VDCModule


class ThermalModule(VDCModule):
    name = "thermal"

    def initialize(self, state, cfg):
        self.pressure_k  = cfg.float('pressure_k',   0.10)
        self.gamma       = cfg.float('gamma',         1.4)
        self.press_frac  = cfg.float('press_frac',    0.40)
        self.v_cap       = cfg.float('v_cap',         2.0)
        self.v_damp      = cfg.float('v_damp',        0.97)
        self.diff_str    = cfg.float('diffusion',     0.025)

    def _grad(self, g):
        return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
                (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
                (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

    def _blur(self, g, s):
        """Diffusion step - smooths sharp gradients"""
        return (g*(1-6*s) +
                s*(np.roll(g,1,axis=0)+np.roll(g,-1,axis=0)+
                   np.roll(g,1,axis=1)+np.roll(g,-1,axis=1)+
                   np.roll(g,1,axis=2)+np.roll(g,-1,axis=2)))

    def _advect(self, f, vx, vy, vz, dt=0.28):
        """
        Trilinear interpolation advection on torus.
        Moves field f along velocity (vx,vy,vz).
        Semi-Lagrangian: trace backwards from each cell,
        interpolate what was there.
        Periodic boundary handled by modulo.
        """
        N = f.shape[0]
        sx = (np.arange(N)[:,None,None] - vx*dt) % N
        sy = (np.arange(N)[None,:,None] - vy*dt) % N
        sz = (np.arange(N)[None,None,:] - vz*dt) % N
        ix=sx.astype(int); fx=sx-ix
        iy=sy.astype(int); fy=sy-iy
        iz=sz.astype(int); fz=sz-iz
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

        # ---------------------------------------------------------- #
        # 1. PRESSURE FORCE
        # High density = high pressure = pushes matter outward.
        # Scaled by temperature: hot plasma pushes hard,
        # cold matter pushes weakly.
        # Only applied where substrate is intact.
        # ---------------------------------------------------------- #
        pressure = self.pressure_k * T * (state.grid ** self.gamma)
        pgx, pgy, pgz = self._grad(pressure)
        state.vx[intact] -= (pgx * self.press_frac)[intact]
        state.vy[intact] -= (pgy * self.press_frac)[intact]
        state.vz[intact] -= (pgz * self.press_frac)[intact]

        # ---------------------------------------------------------- #
        # 2. VELOCITY CAP
        # Hard limit on speed to prevent numerical instability.
        # Physical meaning: nothing moves faster than v_cap
        # in substrate units. Not enforced in true void.
        # ---------------------------------------------------------- #
        speed = np.sqrt(state.vx**2 + state.vy**2 + state.vz**2)
        too_fast = (speed > self.v_cap) & intact
        state.vx[too_fast] *= self.v_cap / speed[too_fast]
        state.vy[too_fast] *= self.v_cap / speed[too_fast]
        state.vz[too_fast] *= self.v_cap / speed[too_fast]

        # ---------------------------------------------------------- #
        # 3. ADVECTION - matter and velocity move together
        # This is the actual fluid transport.
        # Semi-Lagrangian scheme: stable at large timesteps.
        # ---------------------------------------------------------- #
        state.grid = self._advect(state.grid, state.vx,
                                  state.vy,   state.vz)
        state.vx   = self._advect(state.vx,   state.vx,
                                  state.vy,   state.vz)
        state.vy   = self._advect(state.vy,   state.vx,
                                  state.vy,   state.vz)
        state.vz   = self._advect(state.vz,   state.vx,
                                  state.vy,   state.vz)

        # ---------------------------------------------------------- #
        # 4. VELOCITY DAMPING (friction)
        # Small energy loss per step.
        # Prevents velocity from accumulating indefinitely.
        # Physical meaning: substrate has slight viscosity.
        # ---------------------------------------------------------- #
        state.vx *= self.v_damp
        state.vy *= self.v_damp
        state.vz *= self.v_damp

        # ---------------------------------------------------------- #
        # 5. DIFFUSION
        # Smooth sharp density gradients slightly each step.
        # Prevents numerical artifacts at sharp boundaries.
        # Physical meaning: thermal diffusion in the plasma.
        # ---------------------------------------------------------- #
        state.grid = self._blur(state.grid, self.diff_str)
        state.grid = np.maximum(state.grid, 0)

        # ---------------------------------------------------------- #
        # METRICS
        # ---------------------------------------------------------- #
        mean_p  = pressure.mean()
        max_p   = pressure.max()
        max_v   = speed.max()

        return {
            'pressure_mean': float(mean_p),
            'pressure_max':  float(max_p),
            'max_speed':     float(max_v),
        }

    def health_check(self, state):
        if state.grid.max() > 1e7:
            return f"Density runaway in thermal: {state.grid.max():.2e}"
        if not np.isfinite(state.grid).all():
            return "grid NaN after advection"
        return None
