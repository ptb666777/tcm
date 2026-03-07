# -*- coding: utf-8 -*-
"""
VDC Gravity Module
==================
FFT-based Poisson solver for self-gravity.

Why FFT gravity instead of peak sampling:
    The old approach (sample N random peaks, apply 1/r² pull)
    introduced artificial symmetry breaking - which peaks got
    selected each step was random, creating noisy asymmetric
    gravitational fields that could generate false vortices
    and runaway condensation artifacts.

    FFT gravity solves the full Poisson equation exactly:
        ∇²φ = 4π G ρ
    Where φ is the gravitational potential and ρ is density.

    In Fourier space this becomes a simple division:
        φ̂(k) = -ρ̂(k) / |k|²
    
    Then force = -∇φ (gradient of potential)

    This is:
    - O(N³ log N) instead of O(N² * peaks)  -> faster at large N
    - Exact for the given density field      -> no sampling bias
    - Fully symmetric                        -> no false vortices
    - Standard approach in cosmological sims -> well validated

    The only physics we add on top: a Jeans length cutoff.
    Below the Jeans length, pressure prevents collapse.
    We implement this as a k-space filter that suppresses
    gravity at scales smaller than jeans_length cells.

Torus boundary conditions:
    FFT naturally assumes periodic boundaries - perfect for our torus.
    No special treatment needed at grid edges.
"""

import numpy as np
from vdc_kernel import VDCModule


class GravityModule(VDCModule):
    name = "gravity"

    def initialize(self, state, cfg):
        N = state.N
        self.N           = N
        self.grav_str    = cfg.float('grav_str',     0.012)
        self.jeans_cells = cfg.float('jeans_length', 10.0)

        # Precompute the Green's function in k-space.
        # This is the 3D periodic Laplacian inverse.
        # Only needs computing once - save it.
        # k-space coordinates for N-point periodic grid
        kx = np.fft.fftfreq(N) * 2 * np.pi
        ky = np.fft.fftfreq(N) * 2 * np.pi
        kz = np.fft.fftfreq(N) * 2 * np.pi
        KX, KY, KZ = np.meshgrid(kx, ky, kz, indexing='ij')

        # Discrete Laplacian eigenvalues in k-space
        # For 6-point stencil: lambda = 2(cos(kx)-1) + 2(cos(ky)-1) + 2(cos(kz)-1)
        K2 = (2*(np.cos(KX)-1) +
               2*(np.cos(KY)-1) +
               2*(np.cos(KZ)-1))

        # Avoid division by zero at k=0 (DC component = mean field)
        # Set to 1 temporarily, we'll zero it after
        K2[0, 0, 0] = 1.0

        # Green's function: G(k) = -1 / K²
        # Negative because Poisson eq: ∇²φ = ρ -> φ = -ρ/K²
        self._green = -1.0 / K2
        self._green[0, 0, 0] = 0.0  # zero mean potential (no net force)

        # Jeans filter: suppress gravity at small scales
        # Physical meaning: pressure prevents collapse below Jeans length
        # k_jeans = 2π / jeans_cells
        k_jeans = 2 * np.pi / self.jeans_cells
        K_mag = np.sqrt(KX**2 + KY**2 + KZ**2)
        # Smooth cutoff: suppress modes with |k| > k_jeans
        self._jeans_filter = 1.0 / (1.0 + (K_mag / (k_jeans + 1e-10))**4)

        # Precompute k-components for force calculation
        self._KX = KX
        self._KY = KY
        self._KZ = KZ

    def _solve_potential(self, density):
        """
        Solve ∇²φ = density for φ using FFT.
        Returns gravitational potential field.
        """
        # Forward FFT of density
        rho_k = np.fft.fftn(density)

        # Multiply by Green's function and Jeans filter in k-space
        phi_k = rho_k * self._green * self._jeans_filter

        # Inverse FFT to get potential in real space
        phi = np.fft.ifftn(phi_k).real
        return phi

    def _gradient(self, phi):
        """
        Compute gradient of potential in k-space (spectral derivatives).
        More accurate than finite differences for smooth fields.
        Returns (fx, fy, fz) force components.
        """
        phi_k = np.fft.fftn(phi)

        # Spectral derivative: d/dx -> multiply by i*kx
        fx = np.fft.ifftn(1j * self._KX * phi_k).real
        fy = np.fft.ifftn(1j * self._KY * phi_k).real
        fz = np.fft.ifftn(1j * self._KZ * phi_k).real

        return fx, fy, fz

    def step(self, state, cfg):
        # ---------------------------------------------------------- #
        # SOLVE POISSON EQUATION
        # ∇²φ = ρ  ->  φ = FFT⁻¹(ρ̂ * G(k))
        # Force = -∇φ * G_str
        # ---------------------------------------------------------- #
        phi = self._solve_potential(state.grid)

        # Gravitational force = -gradient of potential
        fx, fy, fz = self._gradient(phi)

        # Apply force to velocity where substrate is intact
        intact = state.intact()
        state.vx[intact] -= (self.grav_str * fx)[intact]
        state.vy[intact] -= (self.grav_str * fy)[intact]
        state.vz[intact] -= (self.grav_str * fz)[intact]

        # ---------------------------------------------------------- #
        # METRICS
        # ---------------------------------------------------------- #
        phi_range = phi.max() - phi.min()
        force_mag = np.sqrt(fx**2 + fy**2 + fz**2)

        return {
            'phi_range':    float(phi_range),
            'force_mean':   float(force_mag.mean()),
            'force_max':    float(force_mag.max()),
        }

    def health_check(self, state):
        if not np.isfinite(state.vx).all():
            return "vx contains NaN/Inf after gravity"
        return None
