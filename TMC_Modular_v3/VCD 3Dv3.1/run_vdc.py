# -*- coding: utf-8 -*-
"""
VDC Simulation - Main Run Script v2
Register order matters. MatterState must be first.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vdc_kernel   import Kernel
from matter_state import MatterStateModule
from substrate    import SubstrateModule
from wave         import WaveModule
from gravity      import GravityModule
from thermal      import ThermalModule
from vortex       import VortexModule
from cycle        import CycleModule

if __name__ == '__main__':
    cfg_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'vdc_config.txt')

    k = Kernel(cfg_path)

    # MatterState MUST be first - sets epoch before others check it
    k.register(MatterStateModule())  # referee - sets epoch and temperature
    k.register(SubstrateModule())    # bang fill, tension, void (late)
    k.register(WaveModule())         # Chladni pattern (from confinement)
    k.register(GravityModule())      # FFT gravity (from confinement, full at recomb)
    k.register(ThermalModule())      # pressure, advection, viscosity
    k.register(VortexModule())       # Magnus, chirality (from confinement)
    k.register(CycleModule())        # BH drain (compact only), white holes (structure)

    k.run()
