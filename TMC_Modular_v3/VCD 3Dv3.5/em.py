# -*- coding: utf-8 -*-
"""
VDC Electromagnetic Module
===========================
EM in VDC is not classical electromagnetism.
It is the CHARGE SEPARATION that emerges when vortex structures
form - the distinction between vortex core (positive/proton-like)
and surrounding substrate (negative/electron-like).

Physical model:
    When matter_phase > 0, local density variations represent
    charge separation. Dense vortex cores are 'positive'.
    Rarefied regions between cores are 'negative'.
    The EM force is the binding force between these - it pulls
    matter back toward existing dense structures BEFORE gravity
    is strong enough to do so alone.

    This is why EM matters for collapse:
    - Gravity alone at recombination: weak, slow, fights pressure
    - EM pre-concentrates matter into clumps at confinement
    - Those clumps become Jeans-unstable seeds
    - Gravity then collapses the seeds, not raw uniform density

    The key coupling: EM strength scales with LOCAL density contrast,
    not mean density. A region 3x denser than neighbors feels 9x
    stronger EM pull (quadratic). This creates the runaway seeding
    that makes structure formation possible.

Angular momentum note:
    EM and angular momentum coupling are linked here because
    charge separation is driven by vortex rotation.
    Faster-spinning vortex = stronger charge separation = stronger EM.
    This creates the EM <-> vortex feedback loop.

Epoch gating:
    CONFINEMENT: EM awakens as quarks lock into hadrons (charge defined)
    NUCLEOSYNTHESIS: EM binding strengthens as nuclei form
    RECOMBINATION: EM weakens locally (neutralization) but structure seeded
    STRUCTURE+: EM operates at galactic/stellar scale (residual)

Fields written to state.fields:
    'charge_density'  : signed charge field (+ = dense core, - = rarefied)
    'em_potential'    : scalar EM potential (FFT solved)
    'em_force_mag'    : magnitude of EM force (for diagnostics)
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import (epoch_at_least,
                          CONFINEMENT, NUCLEOSYNTHESIS,
                          RECOMBINATION, STRUCTURE)


class EMModule(VDCModule):
    name = "em"

    def initialize(self, state, cfg):
        N = self.N = state.N

        # Base EM coupling strength
        # Stronger than gravity but shorter effective range
        # (screened by charge neutrality at large scales)
        self.em_str         = cfg.float('em_str',          0.025)

        # Charge separation threshold
        # Cells above mean*(1+thresh) are 'positive cores'
        # Cells below mean*(1-thresh) are 'negative voids'
        self.charge_thresh  = cfg.float('em_charge_thresh', 0.15)

        # Screening length (cells) - EM is screened at large scales
        # by overall charge neutrality of the universe
        # Shorter than Jeans length: EM seeds, gravity collapses
        self.screen_length  = cfg.float('em_screen_length', 6.0)

        # EM-vortex coupling: faster spin -> stronger charge separation
        # This is the angular momentum -> EM feedback
        self.vort_em_couple = cfg.float('em_vort_couple',   0.35)

        # Epoch scaling factors
        self.em_scale_confinement     = cfg.float('em_scale_confinement',     0.3)
        self.em_scale_nucleosynthesis = cfg.float('em_scale_nucleosynthesis', 0.7)
        self.em_scale_recombination   = cfg.float('em_scale_recombination',   0.4)
        self.em_scale_structure       = cfg.float('em_scale_structure',       0.15)

        # Precompute FFT kernel for EM potential (screened Coulomb / Yukawa)
        kx = np.fft.fftfreq(N) * 2 * np.pi
        ky = np.fft.fftfreq(N) * 2 * np.pi
        kz = np.fft.fftfreq(N) * 2 * np.pi
        KX, KY, KZ = np.meshgrid(kx, ky, kz, indexing='ij')
        K2 = KX**2 + KY**2 + KZ**2

        # Yukawa screening: 1/(k^2 + lambda^-2)
        # lambda = screen_length -> suppresses long-range EM
        lam_inv2 = (1.0 / self.screen_length) ** 2
        K2_screen = K2 + lam_inv2
        K2_screen[0, 0, 0] = 1.0  # avoid div by zero
        self._em_green = -1.0 / K2_screen
        self._em_green[0, 0, 0] = 0.0  # zero mean potential
        self._KX = KX
        self._KY = KY
        self._KZ = KZ

        # Initialize fields
        state.fields['charge_density'] = np.zeros((N, N, N))
        state.fields['em_potential']   = np.zeros((N, N, N))
        state.fields['em_force_mag']   = np.zeros((N, N, N))

        print(f"  EM: initialized | screen_length={self.screen_length} cells")
        print(f"  EM: vortex coupling active | vort_em_couple={self.vort_em_couple}")

    def _epoch_scale(self, state):
        """EM strength varies by epoch - peaks at nucleosynthesis"""
        if epoch_at_least(state.epoch, STRUCTURE):
            return self.em_scale_structure
        if epoch_at_least(state.epoch, RECOMBINATION):
            return self.em_scale_recombination
        if epoch_at_least(state.epoch, NUCLEOSYNTHESIS):
            return self.em_scale_nucleosynthesis
        if epoch_at_least(state.epoch, CONFINEMENT):
            return self.em_scale_confinement
        return 0.0  # No EM before confinement - no defined charge

    def _compute_charge(self, state):
        """
        Charge density = deviation from local mean.
        Dense cores are positive, rarefied regions are negative.
        
        Vortex-EM coupling: local vorticity amplifies charge separation.
        Faster spin -> more centrifugal separation of 'charges'.
        This is the angular momentum -> EM link.
        """
        rho = state.grid
        mean_rho = rho.mean()

        if mean_rho < 1e-10:
            return np.zeros_like(rho)

        # Fractional density excess = charge separation
        charge = (rho - mean_rho) / (mean_rho + 1e-10)

        # Only strong separations generate significant charge
        # Weak fluctuations are screened (approximately neutral)
        charge = np.where(np.abs(charge) > self.charge_thresh,
                          charge, charge * 0.1)

        # Vortex amplification: spinning matter separates charge
        # omega_z is the local rotation rate
        omega = state.fields.get('vorticity_mag',
                                  np.zeros_like(rho))
        # Normalize omega to [0,1] range
        omega_max = omega.max()
        if omega_max > 1e-10:
            omega_norm = omega / omega_max
            # Vortex spins amplify charge separation
            charge = charge * (1.0 + self.vort_em_couple * omega_norm)

        return charge

    def _solve_em(self, charge):
        """
        Solve screened Poisson (Yukawa) equation for EM potential.
        phi_k = charge_k * green_k
        Force = -grad(phi)
        """
        charge_k = np.fft.fftn(charge)
        phi_k = charge_k * self._em_green
        phi = np.fft.ifftn(phi_k).real

        # Force = -grad(phi)
        phi_k2 = np.fft.fftn(phi)
        fx = -np.fft.ifftn(1j * self._KX * phi_k2).real
        fy = -np.fft.ifftn(1j * self._KY * phi_k2).real
        fz = -np.fft.ifftn(1j * self._KZ * phi_k2).real

        return phi, fx, fy, fz

    def step(self, state, cfg):
        scale = self._epoch_scale(state)

        if scale == 0.0:
            return {
                'em_active': 0,
                'em_scale':  0.0,
                'charge_rms': 0.0,
                'em_force_mean': 0.0,
            }

        # Get matter phase - EM only where matter has formed
        phase = state.fields.get('matter_phase',
                                  np.zeros(state.grid.shape))
        if phase.max() == 0:
            return {
                'em_active': 0,
                'em_scale':  float(scale),
                'charge_rms': 0.0,
                'em_force_mean': 0.0,
            }

        intact = state.intact()

        # Compute charge separation
        charge = self._compute_charge(state)
        state.fields['charge_density'] = charge

        # Solve for EM potential and force
        phi, fx, fy, fz = self._solve_em(charge)
        state.fields['em_potential'] = phi

        # Scale by epoch and matter complexity
        # More complex matter = more defined charges
        phase_frac = phase / max(phase.max(), 1.0)
        effective_scale = self.em_str * scale * phase_frac

        # Apply EM force
        # EM pulls matter toward existing dense structures (binding)
        # and pushes it away from rarefied voids
        state.vx[intact] += (effective_scale * fx)[intact]
        state.vy[intact] += (effective_scale * fy)[intact]
        state.vz[intact] += (effective_scale * fz)[intact]

        # Store force magnitude for diagnostics
        force_mag = np.sqrt(fx**2 + fy**2 + fz**2)
        state.fields['em_force_mag'] = force_mag * scale

        charge_rms = float(np.sqrt((charge**2).mean()))
        em_force_mean = float((force_mag * effective_scale).mean())

        return {
            'em_active':     1,
            'em_scale':      float(scale),
            'charge_rms':    charge_rms,
            'em_force_mean': em_force_mean,
            'em_force_max':  float(force_mag.max()),
            'vort_coupled':  int(state.fields.get('vorticity_mag',
                                  np.zeros(1)).max() > 1e-5),
        }

    def health_check(self, state):
        if 'em_force_mag' in state.fields:
            if state.fields['em_force_mag'].max() > 1e6:
                return f"EM force runaway: {state.fields['em_force_mag'].max():.2e}"
        return None
