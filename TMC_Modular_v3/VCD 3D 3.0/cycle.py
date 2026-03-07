# -*- coding: utf-8 -*-
"""
VDC Cycle Module
================
Black hole drain, subway reservoir, white hole eruption.

Physical model:
    Matter concentrates under gravity into extreme density.
    At sufficient density, the substrate surface tension under
    that matter is overwhelmed - matter punches through the
    membrane back into the subway.

    Black holes in VDC:
        Not singularities. Drain points.
        Where density is extreme, the pin holding matter to
        reality is yanked through. Matter enters subway queue.
        The black hole grows as more matter drains.
        Most matter draining in sits in queue - the bottleneck
        is the membrane, not the drain rate.

    Subway reservoir:
        Holds matter between drain events and eruptions.
        Has pressure - higher subway level = more pressure
        pushing up on the membrane from below.
        This pressure couples to void formation in substrate.py.

    White holes / eruptions:
        NOT geysers in the old sense.
        Matter does not erupt back through random holes.
        It erupts at TRUE VOID boundaries - where the membrane
        has already failed completely and the subway is exposed.
        The subway pressure pushing up meets no resistance
        at true void boundaries.
        Eruption rate scales with subway pressure AND void age.
        Young fresh voids: small eruption (membrane just failed)
        Old mature voids: larger eruption (pressure built up)
        This creates the oscillation:
            BH drains -> subway fills -> pressure rises ->
            voids form more easily -> eruptions at void edges ->
            subway empties -> pressure drops -> voids heal ->
            BH drains again -> repeat

    Note on geyser vs white hole:
        The old geyser model had matter erupting at any void
        regardless of context. This is more physical:
        eruptions only happen where void is mature and
        subway pressure is sufficient. The rate and location
        emerge from the dynamics, not from fixed thresholds.
"""

import numpy as np
from vdc_kernel import VDCModule


class CycleModule(VDCModule):
    name = "cycle"

    def initialize(self, state, cfg):
        self.bh_drain      = cfg.float('bh_drain',         0.007)
        self.bh_pctile     = cfg.float('bh_percentile',    99.2)
        self.bh_min_mult   = cfg.float('bh_min_multiplier', 3.0)
        self.subway_scale  = cfg.float('subway_scale',     0.0015)
        self.subway_max    = cfg.float('subway_max_inject', 8.0)
        self.void_age_min  = cfg.int(  'void_age_min',     12)
        self.max_eruptions = cfg.int(  'max_eruptions',    3)

    def _grad(self, g):
        return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
                (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
                (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

    def step(self, state, cfg):
        N = state.N
        xx, yy, zz = np.meshgrid(np.arange(N), np.arange(N),
                                  np.arange(N), indexing='ij')

        # ---------------------------------------------------------- #
        # 1. BLACK HOLE DRAIN
        # Extreme density cells drain matter into subway.
        # Threshold: top bh_pctile AND above mean * multiplier.
        # Two-condition prevents draining uniform high-density fields.
        # ---------------------------------------------------------- #
        step_drain = 0.0
        if state.grid.max() > 0:
            bh_val = np.percentile(state.grid, self.bh_pctile)
            bh_cells = ((state.grid > bh_val) &
                        (state.grid > state.grid.mean() * self.bh_min_mult))
            if bh_cells.any():
                drained = state.grid[bh_cells] * self.bh_drain
                step_drain = drained.sum()
                state.subway += step_drain
                state.grid[bh_cells] -= drained

        # ---------------------------------------------------------- #
        # 2. WHITE HOLE ERUPTIONS AT TRUE VOID BOUNDARIES
        # Eruptions happen where:
        #   - void_age > minimum (void is mature, not fresh)
        #   - subway has sufficient pressure
        # Injection amount scales with subway level.
        # More subway pressure = bigger eruption.
        # Eruption is a gaussian blob centered on void cell.
        # ---------------------------------------------------------- #
        step_erupt = 0.0
        true_void = state.true_void()
        mature_void = (state.void_age > self.void_age_min) & true_void

        # Find eruption sites - up to max_eruptions per step
        sites = np.argwhere(mature_void)
        if len(sites) > self.max_eruptions:
            # Prefer oldest voids - they have most built-up pressure
            ages = state.void_age[mature_void]
            top_idx = np.argsort(ages)[-self.max_eruptions:]
            sites = sites[top_idx]

        for tx, ty, tz in sites:
            if state.subway < 0.5:
                break
            # Injection scales with subway pressure
            inject = min(state.subway * self.subway_scale,
                         self.subway_max)
            # Gaussian blob centered on eruption site
            dx = np.minimum(np.abs(xx-tx), N-np.abs(xx-tx))
            dy = np.minimum(np.abs(yy-ty), N-np.abs(yy-ty))
            dz = np.minimum(np.abs(zz-tz), N-np.abs(zz-tz))
            d  = np.sqrt(dx**2 + dy**2 + dz**2)
            kernel = np.exp(-d**2 / 6.0)
            ks = kernel.sum()
            if ks > 0:
                state.grid  += kernel / ks * inject
                state.subway -= inject
                step_erupt  += inject
            # Age resets at eruption site - it just healed
            state.void_age[tx, ty, tz] = 0
            state.seal_str[tx, ty, tz] = 0

        state.subway = max(0, state.subway)
        state.grid   = np.maximum(state.grid, 0)

        return {
            'bh_drain':    float(step_drain),
            'wh_erupt':    float(step_erupt),
            'subway':      float(state.subway),
            'bh_net':      float(step_drain - step_erupt),
        }

    def health_check(self, state):
        if state.subway < 0:
            return f"Subway negative: {state.subway:.2f}"
        return None
