# -*- coding: utf-8 -*-
"""
VDC Simulation - Main Run Script
=================================
Assembles all modules and hands control to the kernel.
Edit vdc_config.txt to change parameters.
Output goes to a timestamped folder inside output_dir.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vdc_kernel  import Kernel
from substrate   import SubstrateModule
from wave        import WaveModule
from gravity     import GravityModule
from thermal     import ThermalModule
from vortex      import VortexModule
from cycle       import CycleModule

if __name__ == '__main__':
    cfg_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'vdc_config.txt')

    k = Kernel(cfg_path)

    # Register modules IN ORDER - order matters each step:
    # 1. Substrate  - tension, voids, precipitation (sets the stage)
    # 2. Wave       - propagation, matter coupling (moves energy)
    # 3. Gravity    - FFT Poisson (pulls matter together)
    # 4. Thermal    - pressure, advection, diffusion (moves matter)
    # 5. Vortex     - Magnus force, chirality (adds spin)
    # 6. Cycle      - BH drain, subway, eruptions (closes the loop)

    k.register(SubstrateModule())
    k.register(WaveModule())
    k.register(GravityModule())
    k.register(ThermalModule())
    k.register(VortexModule())
    k.register(CycleModule())

    k.run()
