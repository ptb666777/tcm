# -*- coding: utf-8 -*-
"""
VDC Cycle Module v2 - Epoch gated
Black holes only possible in COMPACT epoch.
White hole eruptions only in STRUCTURE epoch or later.
Nothing before its time.
"""

import numpy as np
from vdc_kernel import VDCModule
from matter_state import epoch_at_least, STRUCTURE, COMPACT


class CycleModule(VDCModule):
    name = "cycle"

    def initialize(self, state, cfg):
        self.bh_drain     = cfg.float('bh_drain',          0.007)
        self.bh_pctile    = cfg.float('bh_percentile',     99.2)
        self.bh_min_mult  = cfg.float('bh_min_multiplier', 3.0)
        self.subway_scale = cfg.float('subway_scale',      0.0015)
        self.subway_max   = cfg.float('subway_max_inject', 8.0)
        self.void_age_min = cfg.int(  'void_age_min',      50)
        self.max_eruptions= cfg.int(  'max_eruptions',     3)
        # BH density threshold - must be very high, not just top percentile
        self.bh_abs_thresh= cfg.float('bh_abs_threshold',  10.0)

    def step(self, state, cfg):
        step_drain  = 0.0
        step_erupt  = 0.0

        # ---------------------------------------------------------- #
        # BLACK HOLE DRAIN - COMPACT epoch only
        # Requires extreme density that only forms very late
        # AND we require absolute density threshold, not just relative
        # ---------------------------------------------------------- #
        if epoch_at_least(state.epoch, COMPACT):
            if state.grid.max() > self.bh_abs_thresh:
                bh_val = np.percentile(state.grid, self.bh_pctile)
                bh_cells = ((state.grid > bh_val) &
                            (state.grid > self.bh_abs_thresh) &
                            (state.grid > state.grid.mean()*self.bh_min_mult))
                if bh_cells.any():
                    drained = state.grid[bh_cells] * self.bh_drain
                    step_drain = drained.sum()
                    state.subway += step_drain
                    state.grid[bh_cells] -= drained

        # ---------------------------------------------------------- #
        # WHITE HOLE ERUPTIONS - STRUCTURE epoch and later
        # Only at mature void boundaries with sufficient subway pressure
        # ---------------------------------------------------------- #
        if epoch_at_least(state.epoch, STRUCTURE) and state.subway > 1.0:
            N = state.N
            xx,yy,zz = np.meshgrid(np.arange(N),np.arange(N),
                                   np.arange(N),indexing='ij')
            true_void   = state.true_void()
            mature_void = (state.void_age > self.void_age_min) & true_void
            sites       = np.argwhere(mature_void)

            if len(sites) > self.max_eruptions:
                ages    = state.void_age[mature_void]
                top_idx = np.argsort(ages)[-self.max_eruptions:]
                sites   = sites[top_idx]

            for tx,ty,tz in sites:
                if state.subway < 0.5: break
                inject = min(state.subway*self.subway_scale, self.subway_max)
                dx=np.minimum(np.abs(xx-tx),N-np.abs(xx-tx))
                dy=np.minimum(np.abs(yy-ty),N-np.abs(yy-ty))
                dz=np.minimum(np.abs(zz-tz),N-np.abs(zz-tz))
                d =np.sqrt(dx**2+dy**2+dz**2)
                kernel=np.exp(-d**2/6.0)
                ks=kernel.sum()
                if ks>0:
                    state.grid  += kernel/ks*inject
                    state.subway -= inject
                    step_erupt  += inject
                state.void_age[tx,ty,tz] = 0

        state.subway = max(0, state.subway)
        state.grid   = np.maximum(state.grid, 0)

        return {
            'bh_drain':  float(step_drain),
            'wh_erupt':  float(step_erupt),
            'subway':    float(state.subway),
        }

    def health_check(self, state):
        if state.subway < 0:
            return f"Subway negative: {state.subway:.2f}"
        return None
