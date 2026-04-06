import os
import psutil
import torch

# =============================================
# AGGRESSIVE RESOURCE SETUP - Ryzen 7 3700X + Arc B580
# =============================================

# Leave core 0 free for Windows/OS stability → use the other 15 cores
cpu_list = list(range(1, os.cpu_count()))   # [1, 2, ..., 15]

p = psutil.Process()
p.cpu_affinity(cpu_list)
print(f"✅ CPU affinity locked to cores: {cpu_list} (core 0 free for OS)")

# Force maximum threading for NumPy / PyTorch / MKL / OpenMP
os.environ["OMP_NUM_THREADS"] = str(len(cpu_list))
os.environ["MKL_NUM_THREADS"] = str(len(cpu_list))
os.environ["NUMEXPR_NUM_THREADS"] = str(len(cpu_list))
torch.set_num_threads(len(cpu_list))

print(f"✅ Using {len(cpu_list)} CPU threads aggressively")

# Force full use of Arc B580 GPU + all VRAM
device = torch.device("xpu" if torch.xpu.is_available() else "cpu")
print(f"✅ Using device: {device}")

if device.type == "xpu":
    print(f"   GPU: {torch.xpu.get_device_name(0)}")
    print(f"   VRAM: {torch.xpu.get_device_properties(0).total_memory / 1024**3:.1f} GB")

# Optional safety: limit PyTorch to ~90% of VRAM if you want a buffer
# torch.xpu.set_per_process_memory_fraction(0.90)

print(f"✅ Free system RAM: {psutil.virtual_memory().available / 1024**3:.1f} GB\n")