import torch
import psutil
import os

print("=== FRESH XPU TEST ===")
print("PyTorch version:", torch.__version__)
print("XPU available?", torch.xpu.is_available())

if torch.xpu.is_available():
    print("GPU:", torch.xpu.get_device_name(0))
    vram = torch.xpu.get_device_properties(0).total_memory / (1024**3)
    print(f"VRAM: {vram:.1f} GB")
    print("✅ Your Arc B580 is ready!")
else:
    print("❌ XPU not detected — make sure latest Intel Arc drivers are installed.")

print("\nCPU logical cores:", os.cpu_count())
print(f"Free RAM: {psutil.virtual_memory().available / (1024**3):.1f} GB")