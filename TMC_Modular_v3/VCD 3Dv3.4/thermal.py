# -*- coding: utf-8 -*-
"""
VDC Thermal Module v4 - Phase-gated diffusion and damping
===========================================================
Hot plasma: no drag, no diffusion. Energy moves freely.
             Pressure variations are the only force.
             Density contrast from bang must SURVIVE to recombination.

Post-pinning: damping emerges from matter interactions.
              Diffusion emerges from collisions between formed particles.
              Both scale with matter_phase - more matter = more drag.

Photon decoupling: pressure drops ~6000x at recombination.
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import epoch_at_least, RECOMBINATION


class ThermalModule(VDCModule):
    name = "thermal"

    def initialize(self, state, cfg):
        self.pressure_k      = cfg.float('pressure_k',       0.10)
        self.pressure_k_bary = cfg.float('pressure_k_bary',  0.000016)
        self.gamma           = cfg.float('gamma',             1.4)
        self.press_frac      = cfg.float('press_frac',        0.40)
        self.v_cap           = cfg.float('v_cap',             2.0)

        # Diffusion and damping scale with matter_phase
        # Pure plasma: effectively zero (no collisions, no drag)
        # Formed matter: increases with complexity
        self.diff_plasma     = cfg.float('diff_plasma',       0.0)
        self.diff_matter     = cfg.float('diff_matter',       0.020)
        self.damp_plasma     = cfg.float('damp_plasma',       0.0)
        self.damp_matter     = cfg.float('damp_matter',       0.025)

        self._decoupled = False

    def _grad(self, g):
        return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
                (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
                (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

    def _blur(self, g, s):
        # s may be an array (per-cell diffusion) - use weighted blend
        s = np.asarray(s)
        if s.max() <= 0: return g
        return (g*(1-6*s)+s*(
            np.roll(g, 1,axis=0)+np.roll(g,-1,axis=0)+
            np.roll(g, 1,axis=1)+np.roll(g,-1,axis=1)+
            np.roll(g, 1,axis=2)+np.roll(g,-1,axis=2)))

    def _advect_all(self, fields, vx, vy, vz, dt=0.28):
        N = fields[0].shape[0]
        sx = (np.arange(N)[:,None,None] - vx*dt) % N
        sy = (np.arange(N)[None,:,None] - vy*dt) % N
        sz = (np.arange(N)[None,None,:] - vz*dt) % N
        ix=sx.astype(int); fx=sx-ix
        iy=sy.astype(int); fy=sy-iy
        iz=sz.astype(int); fz=sz-iz
        w000=(1-fx)*(1-fy)*(1-fz); w100=fx*(1-fy)*(1-fz)
        w010=(1-fx)*fy*(1-fz);     w001=(1-fx)*(1-fy)*fz
        w110=fx*fy*(1-fz);         w101=fx*(1-fy)*fz
        w011=(1-fx)*fy*fz;         w111=fx*fy*fz
        ix1=(ix+1)%N; iy1=(iy+1)%N; iz1=(iz+1)%N
        out = []
        for f in fields:
            out.append(
                w000*f[ix,iy,iz]+w100*f[ix1,iy,iz]+
                w010*f[ix,iy1,iz]+w001*f[ix,iy,iz1]+
                w110*f[ix1,iy1,iz]+w101*f[ix1,iy,iz1]+
                w011*f[ix,iy1,iz1]+w111*f[ix1,iy1,iz1])
        return out

    def step(self, state, cfg):
        intact = state.intact()
        T      = state.temperature

        # Photon decoupling
        if epoch_at_least(state.epoch, RECOMBINATION) and not self._decoupled:
            self._decoupled = True
            print(f"  [step {state.step}] Thermal: PHOTON DECOUPLING - "
                  f"pressure {self.pressure_k} -> {self.pressure_k_bary}")

        P_k = self.pressure_k_bary if self._decoupled else self.pressure_k

        # Pressure force
        pressure = P_k * T * (state.grid ** self.gamma)
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

        # Advection always - matter always moves with velocity
        state.grid, state.vx, state.vy, state.vz = self._advect_all(
            [state.grid, state.vx, state.vy, state.vz],
            state.vx, state.vy, state.vz)

        # Diffusion and damping scale with matter_phase
        # Pure plasma: zero. Formed matter: scales with complexity.
        phase     = state.fields.get('matter_phase',
                    np.zeros(state.grid.shape))
        phase_max = max(phase.max(), 1.0)
        phase_frac = phase / phase_max  # 0 to 1

        # Mean phase fraction determines effective diffusion/damping
        mean_phase = float(phase_frac.mean())

        diff = self.diff_plasma + (self.diff_matter - self.diff_plasma) * mean_phase
        damp = self.damp_plasma + (self.damp_matter - self.damp_plasma) * mean_phase

        # Diffusion - only where matter exists
        if diff > 0:
            state.grid = self._blur(state.grid, diff * phase_frac
                                    + diff * 0.001)  # tiny floor

        # Damping from matter drag
        if damp > 0:
            state.vx *= (1.0 - damp * phase_frac)
            state.vy *= (1.0 - damp * phase_frac)
            state.vz *= (1.0 - damp * phase_frac)

        state.grid = np.maximum(state.grid, 0)

        return {
            'pressure_k':    float(P_k),
            'pressure_mean': float(pressure.mean()),
            'max_speed':     float(speed.max()),
            'decoupled':     int(self._decoupled),
            'diff_active':   float(diff),
            'damp_active':   float(damp),
        }

    def health_check(self, state):
        if not np.isfinite(state.grid).all():
            return "grid NaN after advection"
        return None
