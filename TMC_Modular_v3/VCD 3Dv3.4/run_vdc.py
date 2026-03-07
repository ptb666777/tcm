# -*- coding: utf-8 -*-
"""
VDC Simulation - Main Run Script v3
Register order matters. MatterState must be first.

Module order rationale:
    1. MatterStateModule   - sets epoch and temperature FIRST
                             (everything else reads epoch)
    2. SubstrateModule     - bang fill, tension, void (late)
    3. WaveModule          - Chladni pattern (from confinement)
    4. GravityModule       - FFT gravity (from confinement, full at recomb)
    5. EMModule            - charge separation, EM binding (from confinement)
                             AFTER gravity: EM pre-seeds what gravity collapses
    6. ThermalModule       - pressure, advection, viscosity
                             AFTER EM: pressure opposes EM/gravity, correct order
    7. VortexModule        - Magnus, chirality (from confinement)
                             AFTER thermal: vorticity uses updated velocities
    8. AngularMomentumModule - L conservation spin-up (from confinement)
                             AFTER vortex: reads vorticity_mag and omega_z
                             written by VortexModule this same step
    9. CycleModule         - BH drain (compact only), white holes (structure)
                             LAST: acts on final density state of step
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vdc_kernel          import Kernel
from matter_state        import MatterStateModule
from substrate           import SubstrateModule
from wave                import WaveModule
from gravity             import GravityModule
from em                  import EMModule
from thermal             import ThermalModule
from vortex              import VortexModule
from angular_momentum    import AngularMomentumModule
from cycle               import CycleModule

if __name__ == '__main__':
    cfg_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'vdc_config.txt')

    k = Kernel(cfg_path)

    k.register(MatterStateModule())      # referee - sets epoch and temperature
    k.register(SubstrateModule())        # bang fill, tension, void (late)
    k.register(WaveModule())             # Chladni pattern (from confinement)
    k.register(GravityModule())          # FFT gravity (matter-phase gated)
    k.register(EMModule())               # charge separation, EM binding force
    k.register(ThermalModule())          # pressure, advection, viscosity
    k.register(VortexModule())           # Magnus, chirality (writes vorticity)
    k.register(AngularMomentumModule())  # L conservation -> spin-up -> Magnus
    k.register(CycleModule())            # BH drain (compact only), white holes

    k.run()
