import numpy as np
print("NumPy version:", np.__version__)

import platform
print("Python:", platform.python_version())

try:
    import pyopencl
    platforms = pyopencl.get_platforms()
    for p in platforms:
        print("OpenCL platform:", p.name)
        for d in p.get_devices():
            print("  Device:", d.name)
except ImportError:
    print("PyOpenCL not installed")

try:
    import torch
    print("PyTorch:", torch.__version__)
    print("CUDA available:", torch.cuda.is_available())
except ImportError:
    print("PyTorch not installed")