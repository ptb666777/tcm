# -*- coding: utf-8 -*-
"""
VDC Angular Momentum Module
============================
The missing runaway mechanism for gravitational collapse.

The problem it solves:
    In VDC v14, gravity is too weak to collapse alone because
    it has no feedback. It pulls matter inward but loses to
    pressure + diffusion + Magnus at every step.
    
    Real collapse has angular momentum conservation as the
    runaway loop:
        matter contracts -> spins faster -> vortex intensifies
        -> Magnus concentrates matter further -> contracts more
    
    Without this, you just get gentle smearing.

What this module does:
    1. Tracks total angular momentum in each local region
    2. When gravity pulls matter inward (density rising),
       enforces L_conservation: omega scales as 1/r^2
    3. The resulting spin-up feeds directly into vorticity
    4. Higher vorticity -> stronger Magnus -> more concentration
    
The runaway loop (once seeded by EM):
    EM seeds clumps -> gravity contracts clumps ->
    L_conservation spins them up -> vorticity amplifies ->
    Magnus concentrates further -> Jeans collapse triggers ->
    star / BH possible

Angular momentum is CONSERVED locally, not globally.
The universe does not have net angular momentum, but
local regions do (from the initial bang perturbations).

Implementation:
    We don't track L as a vector field explicitly - that would
    require solving tensor equations. Instead we use the
    physically correct scalar approximation:
    
    When a region's density increases by factor f,
    its angular velocity increases by f (for uniform collapse
    from radius r to r/sqrt(f), conserving L = I*omega
    where I ~ r^2 for a disk).
    
    omega_new = omega_old * (rho_new / rho_old)
    
    We apply this as a fractional spin-up to the vorticity field.
    The vortex module then uses the amplified vorticity for Magnus.

Fields written:
    'ang_mom_density'  : local angular momentum density
    'spin_amplification': how much spin has been amplified by collapse
    'collapse_rate'    : local rate of density increase (collapse signal)

Epoch gating:
    L_conservation is always true (it's not a force, it's geometry)
    but the EFFECT is only significant when:
    - Matter phase exists (CONFINEMENT+)
    - Local collapse is occurring (density rising, detected by dRho/dt)
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import epoch_at_least, CONFINEMENT, RECOMBINATION


class AngularMomentumModule(VDCModule):
    name = "angular_momentum"

    def initialize(self, state, cfg):
        N = self.N = state.N

        # Spin amplification coupling to vorticity
        # How much of the L_conservation spin-up feeds into
        # actual vorticity that Magnus can use
        # 0.0 = no coupling (no runaway)
        # 1.0 = full coupling (might be too strong)
        self.L_couple       = cfg.float('L_couple',          0.18)

        # Collapse detection sensitivity
        # dRho/dt above this threshold triggers spin-up
        # Too low: noise triggers false spin-ups
        # Too high: misses real collapse
        self.collapse_thresh = cfg.float('L_collapse_thresh', 0.002)

        # Maximum spin amplification per step
        # Prevents numerical runaway in fast collapse
        self.max_spin_amp   = cfg.float('L_max_spin_amp',    0.08)

        # Smoothing radius for angular momentum calculation (cells)
        # L is computed over local neighborhoods, not per-cell
        self.L_smooth_radius = cfg.int('L_smooth_radius',    3)

        # L dissipation - angular momentum slowly transfers to
        # translational KE through collisions (viscous coupling)
        self.L_dissipation  = cfg.float('L_dissipation',     0.015)

        # Storage for density history (to compute dRho/dt)
        self._prev_rho    = None
        self._prev_rho2   = None  # Two steps ago for smoothed derivative

        # Fields
        state.fields['ang_mom_density']   = np.zeros((N, N, N))
        state.fields['spin_amplification']= np.zeros((N, N, N))
        state.fields['collapse_rate']     = np.zeros((N, N, N))

        print(f"  AngularMomentum: initialized | L_couple={self.L_couple}")
        print(f"  Collapse detection threshold: {self.collapse_thresh}")

    def _smooth(self, field, radius=1):
        """Simple box blur for local averaging"""
        result = field.copy()
        for _ in range(radius):
            result = (result +
                      np.roll(result,  1, axis=0) + np.roll(result, -1, axis=0) +
                      np.roll(result,  1, axis=1) + np.roll(result, -1, axis=1) +
                      np.roll(result,  1, axis=2) + np.roll(result, -1, axis=2)) / 7.0
        return result

    def _compute_local_angular_momentum(self, state):
        """
        Local angular momentum density.
        L = rho * r_perp * v_tangential
        
        In 3D discretized form, we use the z-component of L
        as the primary (others computed similarly):
        Lz = rho * (x * vy - y * vx)
        
        We use cell indices as coordinates (centered at grid center).
        """
        N = state.N
        # Coordinates centered at grid center
        coords = np.arange(N) - N // 2
        X, Y, Z = np.meshgrid(coords, coords, coords, indexing='ij')

        # Angular momentum density components
        # Lx = rho * (y*vz - z*vy)
        # Ly = rho * (z*vx - x*vz)
        # Lz = rho * (x*vy - y*vx)
        rho = state.grid

        Lz = rho * (X * state.vy - Y * state.vx)
        Ly = rho * (Z * state.vx - X * state.vz)
        Lx = rho * (Y * state.vz - Z * state.vy)

        L_mag = np.sqrt(Lx**2 + Ly**2 + Lz**2)
        return L_mag, Lz

    def _detect_collapse(self, rho_now):
        """
        Detect regions where density is actively increasing.
        These are collapsing regions where spin-up should occur.
        Returns fractional density change (positive = collapsing).
        """
        if self._prev_rho is None:
            return np.zeros_like(rho_now)

        # Smoothed derivative to reduce noise
        drho = rho_now - self._prev_rho
        if self._prev_rho2 is not None:
            # Second order: average of last two steps
            drho2 = self._prev_rho - self._prev_rho2
            drho = (drho + drho2) * 0.5

        # Fractional change: dRho/Rho
        # Normalized by density to detect relative collapse
        mean_rho = max(rho_now.mean(), 1e-10)
        drho_frac = drho / (rho_now + mean_rho * 0.1)

        # Only return positive (collapsing) regions
        return np.maximum(drho_frac, 0.0)

    def step(self, state, cfg):
        # Angular momentum conservation is physically always true
        # but only has significant effect when matter has formed
        phase = state.fields.get('matter_phase',
                                  np.zeros(state.grid.shape))
        if phase.max() == 0:
            self._prev_rho2 = self._prev_rho
            self._prev_rho  = state.grid.copy()
            return {
                'L_active':        0,
                'L_mean':          0.0,
                'spin_amp_mean':   0.0,
                'collapse_cells':  0,
            }

        # Compute local angular momentum
        L_mag, Lz = self._compute_local_angular_momentum(state)
        L_smooth = self._smooth(L_mag, self.L_smooth_radius)
        state.fields['ang_mom_density'] = L_smooth

        # Detect collapsing regions
        collapse_rate = self._detect_collapse(state.grid)
        # Smooth to avoid sharp gradients
        collapse_rate = self._smooth(collapse_rate, 1)
        state.fields['collapse_rate'] = collapse_rate

        # Threshold: only respond to real collapse, not noise
        real_collapse = collapse_rate > self.collapse_thresh
        collapse_cells = int(real_collapse.sum())

        # SPIN-UP: L conservation in collapsing regions
        # omega_new/omega_old = rho_new/rho_old
        # We apply this as a fractional spin-up to the vorticity
        # by adding to the velocity field in the tangential direction
        
        if collapse_cells > 0 and epoch_at_least(state.epoch, CONFINEMENT):
            # Spin amplification factor: proportional to collapse rate
            # Capped to prevent runaway
            spin_amp = np.minimum(
                collapse_rate * self.L_couple,
                self.max_spin_amp)
            spin_amp[~real_collapse] = 0.0
            state.fields['spin_amplification'] = spin_amp

            # Apply spin-up to velocity field
            # In collapsing regions, add tangential velocity
            # proportional to existing tangential velocity
            # v_tangential -> v_tangential * (1 + spin_amp)
            # We approximate this by amplifying the vortex contribution
            # to velocity (the curl component)
            
            intact = state.intact()

            # The vorticity field (from VortexModule)
            omega_z = state.fields.get('omega_z', np.zeros_like(state.grid))

            # Spin-up: amplify the rotational component of velocity
            # Using the omega_z field as proxy for rotation axis
            N = state.N
            coords = np.arange(N) - N // 2
            X, Y, _ = np.meshgrid(coords, coords, coords, indexing='ij')
            R = np.sqrt(X**2 + Y**2) + 1e-3

            # Tangential velocity addition from spin-up
            # dv_tangential = spin_amp * omega_z * R
            # Direction: perpendicular to R in xy-plane
            dvx = -spin_amp * omega_z * (Y / R)
            dvy =  spin_amp * omega_z * (X / R)

            # Scale by matter phase (only where matter is)
            phase_frac = phase / max(phase.max(), 1.0)
            dvx *= phase_frac
            dvy *= phase_frac

            state.vx[intact] += dvx[intact]
            state.vy[intact] += dvy[intact]
            # vz is not directly affected by Lz conservation
            # (Lz conserved through vx, vy changes)

            # L dissipation: some spin converts to translational KE
            # This represents viscous coupling / angular momentum transport
            if epoch_at_least(state.epoch, RECOMBINATION):
                # After recombination, collisions transfer L to bulk flow
                # This HELPS collapse: spin energy -> radial velocity
                radial_v = (state.vx * X + state.vy * Y) / R
                diss_scale = self.L_dissipation * phase_frac
                state.vx[intact] += (diss_scale * radial_v *
                                      (-X/R))[intact]
                state.vy[intact] += (diss_scale * radial_v *
                                      (-Y/R))[intact]

        else:
            state.fields['spin_amplification'] = np.zeros_like(state.grid)

        # Update density history
        self._prev_rho2 = self._prev_rho
        self._prev_rho  = state.grid.copy()

        return {
            'L_active':       1,
            'L_mean':         float(L_smooth.mean()),
            'L_max':          float(L_smooth.max()),
            'spin_amp_mean':  float(state.fields['spin_amplification'].mean()),
            'collapse_cells': collapse_cells,
            'collapse_max':   float(collapse_rate.max()),
        }

    def health_check(self, state):
        if 'ang_mom_density' in state.fields:
            if state.fields['ang_mom_density'].max() > 1e8:
                return f"Angular momentum runaway: {state.fields['ang_mom_density'].max():.2e}"
        return None
