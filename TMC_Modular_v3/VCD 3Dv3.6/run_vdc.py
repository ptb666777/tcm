# -*- coding: utf-8 -*-
"""
VDC Simulation - Main Run Script v4
=====================================
Hardware optimization added:
  - CPU: 7 of 8 Ryzen cores used for NumPy (leaves 1 for OS stability)
  - GPU: PyOpenCL detected automatically if installed (AMD RX 590)
         Falls back to CPU silently if not available.

Update order (critical - do not reorder):
  1. MatterState   - sets epoch/temperature gate
  2. Substrate     - bang, pins, surface tension, recombination event
  3. Wave          - Chladni resonance, pin-modulated
  4. Gravity       - FFT Poisson, matter-gated
  5. EM            - charge separation, Yukawa screened
  6. Vortex        - Magnus force, circulation conservation
  7. AngularMom    - L-conservation spin-up, collapse detection
  8. Thermal       - pressure, advection LAST (after all forces applied)
  9. Cycle         - BH drain, white holes (late epochs only)
"""

import sys, os

# ------------------------------------------------------------------ #
# CPU THREADING - must be set BEFORE numpy imports
# 7 cores for NumPy operations, leave 1 for OS and Python overhead
# Ryzen 7 3700x: 8 cores / 16 threads
# ------------------------------------------------------------------ #
os.environ["OMP_NUM_THREADS"]      = "7"
os.environ["MKL_NUM_THREADS"]      = "7"
os.environ["OPENBLAS_NUM_THREADS"] = "7"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------------ #
# GPU DETECTION - PyOpenCL for AMD RX 590 (OpenCL, not CUDA)
# Checks silently - no crash if not installed
# ------------------------------------------------------------------ #
_gpu_available = False
_gpu_name = "none"

try:
    import pyopencl as cl
    platforms = cl.get_platforms()
    for platform in platforms:
        devices = platform.get_devices(device_type=cl.device_type.GPU)
        if devices:
            _gpu_name = devices[0].name.strip()
            _gpu_available = True
            break
    if _gpu_available:
        print(f"GPU detected: {_gpu_name} (PyOpenCL)")
        print("  GPU acceleration available for FFT operations")
    else:
        print("PyOpenCL installed but no GPU devices found - using CPU")
except ImportError:
    print("PyOpenCL not installed - using CPU only")
    print("  To enable AMD GPU: pip install pyopencl")
except Exception as e:
    print(f"PyOpenCL error ({e}) - using CPU only")

# ------------------------------------------------------------------ #
# REPORT HARDWARE STATE
# ------------------------------------------------------------------ #
import numpy as np
print(f"\nHardware state:")
print(f"  NumPy: {np.__version__}")
print(f"  CPU threads: OMP/MKL/OPENBLAS = 7 (Ryzen 7 3700x)")
print(f"  GPU: {_gpu_name if _gpu_available else 'not available'}")
print()

# ------------------------------------------------------------------ #
# MODULE IMPORTS
# ------------------------------------------------------------------ #
from vdc_kernel        import Kernel
from matter_state      import MatterStateModule
from substrate         import SubstrateModule
from wave              import WaveModule
from gravity           import GravityModule
from em                import EMModule
from vortex            import VortexModule
from angular_momentum  import AngularMomentumModule
from thermal           import ThermalModule
from cycle             import CycleModule

if __name__ == '__main__':
    cfg_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'vdc_config.txt')

    k = Kernel(cfg_path)

    # Registration order = execution order each step
    # DO NOT reorder - physics depends on this sequence
    k.register(MatterStateModule())       # 1. epoch/temperature referee - MUST be first
    k.register(SubstrateModule())         # 2. bang, pins, tidal field, recombination
    k.register(WaveModule())              # 3. Chladni, pin-modulated resonance
    k.register(GravityModule())           # 4. FFT Poisson gravity
    k.register(EMModule())                # 5. charge separation, Yukawa EM
    k.register(VortexModule())            # 6. Magnus force + circulation conservation
    k.register(AngularMomentumModule())   # 7. L-conservation, spin-up, collapse detect
    k.register(ThermalModule())           # 8. pressure + advection AFTER all forces
    k.register(CycleModule())             # 9. BH drain, white holes (late epochs only)

    k.run()
