# -*- coding: utf-8 -*-
"""
VDC Wave Module v3 - Pin-gated
================================
Wave only exists when stable vortex structures exist.
No pins = no membrane attachment = no oscillation.

Trigger: local vorticity max exceeds pin_threshold AND
         sustained for pin_sustain steps.

Wave seeds locally around vortex structures, not globally.
The Chladni pattern grows FROM the pin locations outward.
"""

import numpy as np
from vdc_kernel import VDCModule


class WaveModule(VDCModule):
    name = "wave"

    def initialize(self, state, cfg):
        self.wave_speed    = cfg.float('wave_speed',      0.45)
        self.wave_couple   = cfg.float('wave_couple',     0.008)
        self.pin_threshold = cfg.float('pin_vort_thresh', 0.005)
        self.pin_sustain   = cfg.int(  'pin_sustain',     20)
        self.surf_tension  = cfg.float('surf_tension',    0.015)
        self.surf_limit    = cfg.float('surf_limit',      8.0)

        self._pin_active      = False
        self._sustain_counter = 0

        courant = 1.0 / np.sqrt(3.0)
        if self.wave_speed >= courant:
            print(f"  WARNING: wave_speed={self.wave_speed} near "
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
        # Check if stable vortex structures exist
        vort_max = state.fields.get('vorticity_mag',
                   np.zeros(state.grid.shape)).max()

        if not self._pin_active:
            if vort_max > self.pin_threshold:
                self._sustain_counter += 1
                if self._sustain_counter >= self.pin_sustain:
                    self._pin_active = True
                    # Seed wave locally around vortex structures
                    # Only where vorticity is strong - these are the pin sites
                    vort_mag = state.fields.get('vorticity_mag',
                               np.zeros(state.grid.shape))
                    pin_sites = vort_mag > self.pin_threshold * 0.5
                    # Wave amplitude proportional to local vortex strength
                    state.wave[pin_sites] = (vort_mag[pin_sites]
                                            / vort_mag.max() * 2.0)
                    print(f"  [step {state.step}] Wave: PINS LOCKED - "
                          f"membrane oscillation begins at "
                          f"{pin_sites.sum()} sites "
                          f"(vort_max={vort_max:.5f})")
            else:
                self._sustain_counter = 0
            return {'wave_active': 0, 'wave_E': 0.0, 'pins_locked': 0}

        # Wave propagation from pin sites
        c2 = self.wave_speed ** 2
        state.wave_v += c2 * self._laplacian(state.wave)
        state.wave   += state.wave_v

        # Surface tension - limits wave amplitude
        restore = (self.surf_tension * state.wave
                  * np.abs(state.wave) / self.surf_limit**2)
        state.wave_v -= restore
        state.wave    = np.clip(state.wave,
                               -self.surf_limit * 3,
                                self.surf_limit * 3)

        # Wave-matter coupling - matter nudges toward nodes
        # Scales with matter_phase - more complex matter couples stronger
        phase = state.fields.get('matter_phase', np.ones(state.grid.shape))
        couple_str = self.wave_couple * (phase / max(phase.max(), 1.0))
        wgx, wgy, wgz = self._grad(state.wave)
        intact = state.intact()
        state.vx[intact] -= (couple_str * wgx)[intact]
        state.vy[intact] -= (couple_str * wgy)[intact]
        state.vz[intact] -= (couple_str * wgz)[intact]

        wave_E = 0.5 * (state.wave**2 + state.wave_v**2).sum()
        return {
            'wave_active': 1,
            'wave_E':      float(wave_E),
            'wave_max':    float(np.abs(state.wave).max()),
            'pins_locked': 1,
        }

    def health_check(self, state):
        wave_E = 0.5*(state.wave**2+state.wave_v**2).sum()
        if wave_E > 1e10:
            return f"Wave energy runaway: {wave_E:.2e}"
        return None
