# -*- coding: utf-8 -*-
"""
VDC Substrate Module v3
=======================
Key conceptual changes from v2:

PIN MODEL REWRITE:
    Pins are NOT fixed points on a grid.
    Pins are topologically stable vortex knots carried by the fluid.
    Like a knot in a river - moves with the current but maintains
    its own structure. The knot is stable relative to itself, not
    to the grid.

    Pin lifecycle:
        1. Vortex knot forms spontaneously from bang perturbations
        2. If knot exceeds stability threshold AND sustains for
           pin_sustain steps -> crystallizes as a pin
        3. Pin position drifts with local fluid velocity each step
        4. Pin strengthens as tidal forces accumulate around it
           (gravity + EM both contribute to tidal depth)
        5. Pin dissolves if local vorticity drops below threshold
           for dissolve_steps consecutive steps
        6. Pins that drift within merge_radius of each other merge
           into a stronger combined pin

SURFACE TENSION AS TIDAL THICKNESS:
    Surface tension is not uniform.
    It thickens around pin sites proportional to accumulated
    tidal force - gravity and EM are the same tidal phenomenon
    at different scales. Both deepen the substrate indentation
    around a pin, which thickens the local surface tension.
    
    Moving away from a pin: lower tidal force, thinner tension.
    This creates the natural web geometry - thick filaments
    between pins, thin sheets between filaments, empty voids
    where no pins exist.

TIME AS TIDAL DEPTH:
    Time dilation and gravitational field strength are the same
    thing expressed differently (GR). The vortex indentation that
    creates gravity also creates a time gradient.
    We model this as a scalar 'tidal_depth' field that combines
    gravity potential and EM potential into one field.
    Deeper tidal depth = slower effective time = stronger
    surface tension = more stable pin.
    
    This is not a separate force. It is the depth dimension of
    the vortex shear geometry. Gravity and time together are
    tidal depth. EM is the rotational expression at shorter scales.

RECOMBINATION EVENT:
    At recombination, photon pressure drops ~6000x suddenly.
    This is modeled as a pressure withdrawal shockwave -
    every region simultaneously loses the radiation support
    that was holding matter smooth.
    Matter falls inward everywhere at once.
    The suddenness is what triggers Jeans instability.
    Not a gradual parameter change - a single-step event.
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import (epoch_at_least, CONFINEMENT,
                          RECOMBINATION, STRUCTURE)


class PinField:
    """
    Tracks active pins as a list of objects with positions,
    strengths, and drift velocities.
    Pins are debris in the fluid - they move, grow, dissolve, merge.
    """
    def __init__(self, N):
        self.N = N
        self.pins = []  # list of dicts: {pos, strength, age, dissolve_count}
        self._grid_cache = None
        self._cache_valid = False

    def add(self, pos, strength=1.0):
        self.pins.append({
            'pos': np.array(pos, dtype=float),
            'strength': strength,
            'age': 0,
            'dissolve_count': 0,
        })
        self._cache_valid = False

    def update_positions(self, vx, vy, vz):
        """Drift pins with local fluid velocity"""
        N = self.N
        for p in self.pins:
            ix, iy, iz = (int(p['pos'][i]) % N for i in range(3))
            p['pos'][0] = (p['pos'][0] + vx[ix, iy, iz]) % N
            p['pos'][1] = (p['pos'][1] + vy[ix, iy, iz]) % N
            p['pos'][2] = (p['pos'][2] + vz[ix, iy, iz]) % N
            p['age'] += 1
        self._cache_valid = False

    def strengthen(self, tidal_depth):
        """Pins grow stronger in deeper tidal wells"""
        N = self.N
        for p in self.pins:
            ix, iy, iz = (int(p['pos'][i]) % N for i in range(3))
            local_depth = float(tidal_depth[ix, iy, iz])
            p['strength'] = min(p['strength'] * (1.0 + 0.02 * local_depth),
                                10.0)
        self._cache_valid = False

    def dissolve_weak(self, vorticity, threshold, dissolve_steps):
        """Remove pins where vorticity has dropped below threshold"""
        N = self.N
        surviving = []
        for p in self.pins:
            ix, iy, iz = (int(p['pos'][i]) % N for i in range(3))
            local_vort = float(vorticity[ix, iy, iz])
            if local_vort < threshold:
                p['dissolve_count'] += 1
            else:
                p['dissolve_count'] = 0
            if p['dissolve_count'] < dissolve_steps:
                surviving.append(p)
        if len(surviving) < len(self.pins):
            self._cache_valid = False
        self.pins = surviving

    def merge_close(self, merge_radius):
        """Merge pins that have drifted within merge_radius of each other"""
        if len(self.pins) < 2:
            return
        N = self.N
        merged = []
        used = set()
        for i, p1 in enumerate(self.pins):
            if i in used:
                continue
            group = [p1]
            for j, p2 in enumerate(self.pins):
                if j <= i or j in used:
                    continue
                # Toroidal distance
                d = np.sqrt(sum(
                    min(abs(p1['pos'][k] - p2['pos'][k]),
                        N - abs(p1['pos'][k] - p2['pos'][k]))**2
                    for k in range(3)))
                if d < merge_radius:
                    group.append(p2)
                    used.add(j)
            used.add(i)
            if len(group) == 1:
                merged.append(p1)
            else:
                # Merge: weighted average position, sum strength
                total_str = sum(g['strength'] for g in group)
                avg_pos = sum(g['pos'] * g['strength'] for g in group) / total_str
                merged.append({
                    'pos': avg_pos % N,
                    'strength': min(total_str, 10.0),
                    'age': max(g['age'] for g in group),
                    'dissolve_count': 0,
                })
        if len(merged) < len(self.pins):
            self._cache_valid = False
        self.pins = merged

    def to_grid(self, sigma=2.5):
        """
        Vectorized pin grid - all pins computed simultaneously.
        Replaces per-pin loop which was O(n_pins * N^3).
        """
        if self._cache_valid and self._grid_cache is not None:
            return self._grid_cache

        N = self.N
        grid = np.zeros((N, N, N))
        if not self.pins:
            self._grid_cache = grid
            self._cache_valid = True
            return grid

        # Stack all pin positions and strengths
        positions = np.array([p['pos'] for p in self.pins])  # (M, 3)
        strengths = np.array([p['strength'] for p in self.pins])  # (M,)

        coords = np.arange(N)
        # For each axis compute toroidal distances from all pins at once
        # positions[:, 0] shape (M,), coords shape (N,)
        # Result dx shape (M, N)
        dx = np.minimum(
            np.abs(positions[:, 0:1] - coords[np.newaxis, :]),
            N - np.abs(positions[:, 0:1] - coords[np.newaxis, :]))
        dy = np.minimum(
            np.abs(positions[:, 1:2] - coords[np.newaxis, :]),
            N - np.abs(positions[:, 1:2] - coords[np.newaxis, :]))
        dz = np.minimum(
            np.abs(positions[:, 2:3] - coords[np.newaxis, :]),
            N - np.abs(positions[:, 2:3] - coords[np.newaxis, :]))

        # Gaussian per pin: exp(-r²/2σ²)
        # dx² shape (M, N) -> broadcast to (M, N, N, N) is too large
        # Instead compute contribution per pin using outer products
        inv_2sig2 = 1.0 / (2 * sigma**2)
        gx = np.exp(-dx**2 * inv_2sig2)  # (M, N)
        gy = np.exp(-dy**2 * inv_2sig2)  # (M, N)
        gz = np.exp(-dz**2 * inv_2sig2)  # (M, N)

        # grid[x,y,z] += strength * gx[m,x] * gy[m,y] * gz[m,z]
        # Use einsum for efficiency
        # First compute strength-weighted outer products
        for m in range(len(self.pins)):
            grid += strengths[m] * np.einsum('i,j,k->ijk',
                                              gx[m], gy[m], gz[m])

        self._grid_cache = grid
        self._cache_valid = True
        return grid


class SubstrateModule(VDCModule):
    name = "substrate"

    def initialize(self, state, cfg):
        N = state.N

        # Surface tension base parameters
        self.surf_tension   = cfg.float('surf_tension',      0.015)
        self.surf_limit     = cfg.float('surf_limit',        5.0)

        # Tidal thickening: how much tidal depth amplifies surface tension
        # This is the gravity+EM+time effect on substrate thickness
        self.tidal_thick_k  = cfg.float('tidal_thick_k',    0.08)

        # Void / tension parameters (late game only)
        self.tension_decay  = cfg.float('tension_decay',     0.018)
        self.tension_repair = cfg.float('tension_repair',    0.014)
        self.base_thin      = cfg.float('base_thin_density', 0.008)
        self.subway_press_k = cfg.float('subway_press_coeff',0.00002)
        self.tear_max       = cfg.float('tear_thresh_max',   0.05)
        self.spill_frac     = cfg.float('void_spill_frac',   0.9)
        self.void_loss_frac = cfg.float('void_loss_frac',    0.1)
        self.void_threshold = cfg.float('void_threshold',    0.05)

        # Pin parameters
        self.pin_vort_thresh  = cfg.float('pin_vort_thresh',   0.005)
        self.pin_sustain      = cfg.int(  'pin_sustain',        20)
        self.pin_dissolve_steps = cfg.int('pin_dissolve_steps', 30)
        self.pin_merge_radius = cfg.float('pin_merge_radius',   3.0)
        self.pin_max          = cfg.int(  'pin_max',            500)
        self._pin_candidates  = {}  # pos_key -> sustain_count

        # Bang parameters
        self.bang_energy  = cfg.float('bang_energy',   120.0)
        self.bang_noise   = cfg.float('bang_noise',    0.02)

        # Recombination event
        self._recomb_event_fired = False
        self.recomb_shockwave_k  = cfg.float('recomb_shockwave_k', 0.35)

        # Pin field
        state.pin_field = PinField(N)

        # ---------------------------------------------------------- #
        # INITIAL CONDITIONS - THE BANG
        # ---------------------------------------------------------- #
        np.random.seed(cfg.int('random_seed', 42)
                       if cfg.int('random_seed', 42) != 0 else None)

        mean_density = self.bang_energy / (N**3)
        perturbation = np.random.exponential(self.bang_noise, (N, N, N))

        state.grid    = np.full((N, N, N), mean_density) + perturbation
        state.wave    = np.zeros((N, N, N))
        state.wave_v  = np.zeros((N, N, N))
        state.tension = np.ones((N, N, N))
        state.void_age  = np.zeros((N, N, N))
        state.seal_str  = np.zeros((N, N, N))
        state.subway    = 0.0

        # Tidal depth field - combined gravity + EM depth
        # Updated each step by reading from fields written by
        # gravity and EM modules
        state.fields['tidal_depth'] = np.zeros((N, N, N))
        state.fields['pin_density'] = np.zeros((N, N, N))

        print(f"  Substrate v3: fluid pin model active")
        print(f"  Mean density: {state.grid.mean():.6f}")
        print(f"  Pin crystallization threshold: vort>{self.pin_vort_thresh} "
              f"for {self.pin_sustain} steps")

    def _update_tidal_depth(self, state):
        """
        Tidal depth = gravity potential + EM potential combined.
        This is the 'depth of the indentation' in the substrate.
        Gravity and time dilation are the same thing at this level -
        both are expressions of tidal depth.
        EM is the rotational shear at shorter scales.
        Together they determine how thick the substrate is locally.
        """
        # Gravity contributes through density field
        # (proxy for gravitational potential - denser = deeper well)
        grav_depth = state.grid / (state.grid.mean() + 1e-10)

        # EM contributes through charge separation and force magnitude
        em_depth = state.fields.get('em_force_mag',
                                     np.zeros(state.grid.shape))
        em_max = em_depth.max()
        if em_max > 1e-10:
            em_depth = em_depth / em_max
        else:
            em_depth = np.zeros_like(em_depth)

        # Pin field itself deepens the well (positive feedback)
        pin_depth = state.fields.get('pin_density',
                                      np.zeros(state.grid.shape))
        pin_max = pin_depth.max()
        if pin_max > 1e-10:
            pin_depth = pin_depth / pin_max * 0.5

        # Combined tidal depth
        state.fields['tidal_depth'] = grav_depth + em_depth + pin_depth

    def _update_surface_tension(self, state):
        """
        Surface tension thickens in deeper tidal wells.
        The cosmic web geometry emerges from this:
        - Thick tension along filaments between pins
        - Thin tension in sheets between filaments
        - Failed tension in voids where no tidal force reaches
        """
        tidal = state.fields['tidal_depth']
        tidal_norm = tidal / (tidal.max() + 1e-10)

        # Base tension modified by tidal depth
        # Deeper well = thicker tension = more stable
        tidal_boost = 1.0 + self.tidal_thick_k * tidal_norm

        # Apply to tension field (only strengthen, decay handled separately)
        if epoch_at_least(state.epoch, CONFINEMENT):
            state.tension = np.clip(state.tension * tidal_boost, 0, 2.0)

    def _detect_and_crystallize_pins(self, state):
        """
        Scan for vortex knots that are stable enough to crystallize.
        Uses local vorticity maximum detection.
        Knots that sustain above threshold for pin_sustain steps
        become pins.
        """
        if not epoch_at_least(state.epoch, CONFINEMENT):
            return

        if len(state.pin_field.pins) >= self.pin_max:
            return

        vort = state.fields.get('vorticity_mag',
                                 np.zeros(state.grid.shape))
        N = state.N

        # Find local maxima in vorticity above threshold
        # A cell is a local max if it exceeds all 6 neighbors
        above = vort > self.pin_vort_thresh
        is_local_max = above.copy()
        for axis in range(3):
            is_local_max &= vort >= np.roll(vort,  1, axis=axis)
            is_local_max &= vort >= np.roll(vort, -1, axis=axis)

        candidates = np.argwhere(is_local_max)

        # Track sustain counter for each candidate
        active_keys = set()
        for cx, cy, cz in candidates:
            key = (cx, cy, cz)
            active_keys.add(key)
            self._pin_candidates[key] = self._pin_candidates.get(key, 0) + 1

            if self._pin_candidates[key] >= self.pin_sustain:
                # Crystallize as pin
                state.pin_field.add(
                    [cx, cy, cz],
                    strength=float(vort[cx, cy, cz]) / self.pin_vort_thresh)
                del self._pin_candidates[key]
                # Small print to avoid spam - only log occasionally
                if len(state.pin_field.pins) % 50 == 1:
                    print(f"  [step {state.step}] Pin #{len(state.pin_field.pins)} "
                          f"crystallized at ({cx},{cy},{cz}) "
                          f"vort={vort[cx,cy,cz]:.4f}")

        # Clean up candidates that are no longer above threshold
        stale = set(self._pin_candidates.keys()) - active_keys
        for key in stale:
            del self._pin_candidates[key]

    def _fire_recombination_event(self, state):
        """
        THE RECOMBINATION SHOCKWAVE.
        
        At recombination, photon pressure drops ~6000x suddenly.
        This is not a gradual parameter change.
        It is a single-step event where the radiation support
        holding matter smooth is simultaneously withdrawn everywhere.
        
        Effect:
        - Every region above mean density gets an inward velocity impulse
          (matter falls toward existing overdensities)
        - Every region below mean density gets an outward impulse
          (voids open up suddenly)
        - The impulse magnitude is proportional to local density contrast
        
        This is the Jeans instability trigger.
        Without the suddenness, collapse never starts.
        With it, every overdense region begins falling simultaneously.
        """
        print(f"  [step {state.step}] *** RECOMBINATION SHOCKWAVE ***")
        print(f"  Photon pressure withdrawn - matter falls inward")

        N = state.N
        rho = state.grid
        mean_rho = rho.mean()

        # Density contrast
        contrast = (rho - mean_rho) / (mean_rho + 1e-10)

        # Gravity-like infall toward overdensities
        # Use FFT to compute infall direction (same as gravity solver)
        kx = np.fft.fftfreq(N) * 2 * np.pi
        ky = np.fft.fftfreq(N) * 2 * np.pi
        kz = np.fft.fftfreq(N) * 2 * np.pi
        KX, KY, KZ = np.meshgrid(kx, ky, kz, indexing='ij')
        K2 = (2*(np.cos(KX)-1) + 2*(np.cos(KY)-1) + 2*(np.cos(KZ)-1))
        K2[0,0,0] = 1.0
        green = -1.0 / K2
        green[0,0,0] = 0.0

        contrast_k = np.fft.fftn(contrast)
        phi_k = contrast_k * green
        phi_k2 = np.fft.fftn(np.fft.ifftn(phi_k).real)

        fx = np.fft.ifftn(1j * KX * phi_k2).real
        fy = np.fft.ifftn(1j * KY * phi_k2).real
        fz = np.fft.ifftn(1j * KZ * phi_k2).real

        # Apply shockwave impulse
        intact = state.intact()
        state.vx[intact] -= (self.recomb_shockwave_k * fx)[intact]
        state.vy[intact] -= (self.recomb_shockwave_k * fy)[intact]
        state.vz[intact] -= (self.recomb_shockwave_k * fz)[intact]

        # Also strengthen pins at this moment - recombination
        # locks in the structure that radiation was smoothing over
        for p in state.pin_field.pins:
            p['strength'] *= 1.5

        impulse_mag = np.sqrt(fx**2 + fy**2 + fz**2)
        print(f"  Shockwave impulse max: {impulse_mag.max():.4f}")
        print(f"  Active pins at recombination: {len(state.pin_field.pins)}")
        self._recomb_event_fired = True

    def step(self, state, cfg):
        # ---------------------------------------------------------- #
        # UPDATE TIDAL DEPTH from gravity and EM fields
        # ---------------------------------------------------------- #
        self._update_tidal_depth(state)

        # ---------------------------------------------------------- #
        # PIN CRYSTALLIZATION - ongoing from confinement
        # ---------------------------------------------------------- #
        if epoch_at_least(state.epoch, CONFINEMENT):
            self._detect_and_crystallize_pins(state)

            # Update pin positions (drift with fluid)
            state.pin_field.update_positions(
                state.vx, state.vy, state.vz)

            # Strengthen pins in tidal wells
            state.pin_field.strengthen(state.fields['tidal_depth'])

            # Dissolve weak pins
            state.pin_field.dissolve_weak(
                state.fields.get('vorticity_mag',
                                  np.zeros(state.grid.shape)),
                self.pin_vort_thresh * 0.3,
                self.pin_dissolve_steps)

            # Merge close pins
            if len(state.pin_field.pins) > 1:
                state.pin_field.merge_close(self.pin_merge_radius)

            # Update pin density field for wave module and tidal depth
            state.fields['pin_density'] = state.pin_field.to_grid(sigma=2.5)

        # ---------------------------------------------------------- #
        # SURFACE TENSION TIDAL THICKENING
        # ---------------------------------------------------------- #
        self._update_surface_tension(state)

        # ---------------------------------------------------------- #
        # WAVE SURFACE TENSION (amplitude limiting)
        # Now modulated by local pin density - stronger near pins
        # ---------------------------------------------------------- #
        if epoch_at_least(state.epoch, CONFINEMENT):
            pin_grid = state.fields['pin_density']
            pin_norm = pin_grid / (pin_grid.max() + 1e-10)
            # Surface tension stronger near pins = wave nodes form there
            local_surf = self.surf_tension * (1.0 + pin_norm * 2.0)
            wave_restore = (local_surf
                           * state.wave
                           * np.abs(state.wave)
                           / self.surf_limit**2)
            state.wave_v -= wave_restore
            state.wave    = np.clip(state.wave,
                                   -self.surf_limit * 3,
                                    self.surf_limit * 3)

        # ---------------------------------------------------------- #
        # RECOMBINATION EVENT - fires once
        # ---------------------------------------------------------- #
        if (epoch_at_least(state.epoch, RECOMBINATION) and
                not self._recomb_event_fired):
            self._fire_recombination_event(state)

        # ---------------------------------------------------------- #
        # VOID MECHANICS (STRUCTURE epoch only)
        # ---------------------------------------------------------- #
        step_void_loss = 0.0
        if epoch_at_least(state.epoch, STRUCTURE):
            dynamic_thin = min(
                self.base_thin + state.subway * self.subway_press_k,
                self.tear_max)

            matter_present = state.grid > dynamic_thin
            state.tension[matter_present]  += self.tension_repair
            state.tension[~matter_present] -= self.tension_decay
            state.tension = np.clip(state.tension, 0, 2.0)

            true_void = state.tension < self.void_threshold
            state.void_age[true_void]  += 1
            state.void_age[~true_void]  = np.maximum(
                0, state.void_age[~true_void] - 3)

            void_matter = state.grid * true_void
            if void_matter.sum() > 0:
                spill = void_matter * self.spill_frac
                state.grid -= spill
                per_neighbor = spill / 6.0
                state.grid += (
                    np.roll(per_neighbor,  1, axis=0) +
                    np.roll(per_neighbor, -1, axis=0) +
                    np.roll(per_neighbor,  1, axis=1) +
                    np.roll(per_neighbor, -1, axis=1) +
                    np.roll(per_neighbor,  1, axis=2) +
                    np.roll(per_neighbor, -1, axis=2))
                lost = void_matter * self.void_loss_frac
                state.subway += lost.sum()
                step_void_loss = lost.sum()
                state.grid -= lost

            state.grid = np.maximum(state.grid, 0)

        # ---------------------------------------------------------- #
        # METRICS
        # ---------------------------------------------------------- #
        true_void_frac = (state.tension < self.void_threshold).mean()
        pin_count = len(state.pin_field.pins)

        return {
            'void_frac':      float(true_void_frac),
            'tension_mean':   float(state.tension.mean()),
            'void_loss':      float(step_void_loss),
            'pin_count':      pin_count,
            'pin_strength_mean': float(np.mean([p['strength']
                                for p in state.pin_field.pins])
                                if pin_count > 0 else 0.0),
            'tidal_depth_max': float(state.fields['tidal_depth'].max()),
            'recomb_fired':   int(self._recomb_event_fired),
        }

    def health_check(self, state):
        if state.grid.min() < -0.01:
            return f"Negative density: {state.grid.min():.4f}"
        if len(state.pin_field.pins) > self.pin_max * 1.5:
            return f"Pin count runaway: {len(state.pin_field.pins)}"
        return None
