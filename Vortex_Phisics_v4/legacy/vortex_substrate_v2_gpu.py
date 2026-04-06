# VORTEX SUBSTRATE MODEL v2 - GPU ACCELERATED for Intel Arc B580
# Patrick & Claude - VSM formal logic string implementation
# Optimized with aggressive CPU + XPU usage

import os
import psutil
import torch
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
import time

# =============================================
# AGGRESSIVE RESOURCE SETUP - Ryzen 7 3700X + Arc B580
# =============================================

# Leave core 0 free for OS stability → use the other 15 cores
cpu_list = list(range(1, os.cpu_count()))

p = psutil.Process()
p.cpu_affinity(cpu_list)
print(f"✅ CPU affinity locked to cores: {cpu_list} (core 0 free for OS)")

# Aggressive threading for NumPy/PyTorch
os.environ["OMP_NUM_THREADS"] = str(len(cpu_list))
os.environ["MKL_NUM_THREADS"] = str(len(cpu_list))
os.environ["NUMEXPR_NUM_THREADS"] = str(len(cpu_list))
torch.set_num_threads(len(cpu_list))

print(f"✅ Using {len(cpu_list)} CPU threads aggressively")

# Force Arc B580 (XPU)
device = torch.device("xpu" if torch.xpu.is_available() else "cpu")
print(f"✅ Using device: {device}")
if device.type == "xpu":
    print(f"   GPU: {torch.xpu.get_device_name(0)}")
    print(f"   VRAM: {torch.xpu.get_device_properties(0).total_memory / 1024**3:.1f} GB")

print(f"✅ Free system RAM: {psutil.virtual_memory().available / 1024**3:.1f} GB\n")

# ─────────────────────────────────────────────
# GRID AND SUBSTRATE
# ─────────────────────────────────────────────
N         = 256         # grid per axis
TAU       = 1.0
DT        = 0.05
SNAP_EVERY = 20
LOG_EVERY  = 10
DAMP       = 0.99

tau_tensor = torch.tensor(TAU, device=device, dtype=torch.float32)

# ─────────────────────────────────────────────
# PIN
# ─────────────────────────────────────────────
def make_pin(pos, rho=1.0, omega=1.0, label=''):
    return {
        'pos':   np.array(pos, dtype=float),
        'rho':   rho,
        'omega': omega,
        'vel':   np.zeros(3),
        'label': label,
        'age':   0,
    }

# ─────────────────────────────────────────────
# PSI FIELD - GPU ACCELERATED
# ─────────────────────────────────────────────
def compute_psi(pins, N, tau_tensor, device):
    psi = torch.zeros((N, N, N), device=device, dtype=torch.float32)
    coords = torch.arange(N, device=device, dtype=torch.float32)
    cx, cy, cz = torch.meshgrid(coords, coords, coords, indexing='ij')

    for pin in pins:
        px, py, pz = pin['pos']
        dx = torch.minimum(torch.abs(cx - px), float(N) - torch.abs(cx - px))
        dy = torch.minimum(torch.abs(cy - py), float(N) - torch.abs(cy - py))
        dz = torch.minimum(torch.abs(cz - pz), float(N) - torch.abs(cz - pz))
        r2 = dx**2 + dy**2 + dz**2
        contrib = (pin['rho'] * pin['omega']) / (r2 + tau_tensor)
        psi += contrib
    return psi

# ─────────────────────────────────────────────
# GRADIENT - GPU ACCELERATED
# ─────────────────────────────────────────────
def compute_gradient(psi):
    gx = (torch.roll(psi, -1, dims=0) - torch.roll(psi, 1, dims=0)) / 2.0
    gy = (torch.roll(psi, -1, dims=1) - torch.roll(psi, 1, dims=1)) / 2.0
    gz = (torch.roll(psi, -1, dims=2) - torch.roll(psi, 1, dims=2)) / 2.0
    return gx, gy, gz

# ─────────────────────────────────────────────
# TOROIDAL DISTANCE
# ─────────────────────────────────────────────
def pin_distance(p1, p2, N):
    d = np.abs(p1['pos'] - p2['pos'])
    d = np.minimum(d, N - d)
    return float(np.sqrt(np.sum(d**2)))

# ─────────────────────────────────────────────
# STEP PINS
# ─────────────────────────────────────────────
def step_pins(pins, psi, gx, gy, gz, dt, N, damp):
    psi_cpu = psi.cpu().numpy()
    for pin in pins:
        ix = int(pin['pos'][0]) % N
        iy = int(pin['pos'][1]) % N
        iz = int(pin['pos'][2]) % N

        psi_local = psi_cpu[ix, iy, iz]
        t_rate = 1.0 / (1.0 + abs(psi_local))

        force = np.array([
            -gx[ix, iy, iz].item(),
            -gy[ix, iy, iz].item(),
            -gz[ix, iy, iz].item(),
        ])

        pin['vel'] += force * dt * t_rate
        pin['vel'] *= damp
        pin['pos'] = (pin['pos'] + pin['vel'] * dt) % N
        pin['age'] += 1

# ─────────────────────────────────────────────
# MEASUREMENTS CLASS (unchanged)
# ─────────────────────────────────────────────
class Measurements:
    def __init__(self, pins):
        self.steps       = []
        self.separations = defaultdict(list)
        self.psi_at_pins = defaultdict(list)
        self.velocities  = defaultdict(list)
        self.time_rates  = defaultdict(list)
        self.psi_min     = []
        self.psi_max     = []
        self.psi_mean    = []
        self.n_pins      = len(pins)

    def record(self, step_num, pins, psi, N):
        self.steps.append(step_num)
        psi_np = psi.cpu().numpy()
        self.psi_min.append(float(psi_np.min()))
        self.psi_max.append(float(psi_np.max()))
        self.psi_mean.append(float(psi_np.mean()))

        for i, pin in enumerate(pins):
            ix = int(pin['pos'][0]) % N
            iy = int(pin['pos'][1]) % N
            iz = int(pin['pos'][2]) % N
            psi_local = float(psi_np[ix, iy, iz])
            self.psi_at_pins[i].append(psi_local)
            self.velocities[i].append(float(np.linalg.norm(pin['vel'])))
            self.time_rates[i].append(1.0 / (1.0 + abs(psi_local)))

        for i in range(len(pins)):
            for j in range(i+1, len(pins)):
                d = pin_distance(pins[i], pins[j], N)
                self.separations[(i,j)].append(d)

    def print_summary(self, pins):
        print("\n=== MEASUREMENT SUMMARY ===")
        print(f"Steps recorded: {len(self.steps)}")
        for i, pin in enumerate(pins):
            speeds = self.velocities[i]
            trates = self.time_rates[i]
            print(f"Pin {i} ({pin['label'] or 'unlabeled'}) omega={pin['omega']:+.1f}")
            print(f"  Final pos:    {pin['pos'].round(2)}")
            print(f"  Final speed:  {speeds[-1]:.6f}")
            print(f"  Time rate:    {trates[-1]:.6f}")
            print(f"  Avg speed:    {np.mean(speeds):.6f}")
        for (i,j), dists in self.separations.items():
            print(f"Pin {i}-{j} separation: Final {dists[-1]:.3f} cells")

    def plot_measurements(self, pins):
        fig, axes = plt.subplots(2, 2, figsize=(12, 8), facecolor='#0a0a0a')
        fig.suptitle('VSM Measurements', color='white', fontsize=12)
        colors = ['#00d4ff', '#ff6b35', '#00ff88', '#ff00aa', '#ffdd00', '#aa00ff']

        ax = axes[0,0]
        ax.set_facecolor('#111')
        for (i,j), dists in self.separations.items():
            lbl = f"Pin {i}-{j}"
            ax.plot(self.steps, dists, color=colors[(i+j)%len(colors)], label=lbl, linewidth=1.5)
        ax.set_title('Pin Separations (cells)', color='white')
        ax.set_xlabel('Step', color='#888')
        ax.set_ylabel('Distance', color='#888')
        ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
        ax.tick_params(colors='#666')
        for sp in ax.spines.values(): sp.set_color('#333')

        # Velocities, Time Rates, Psi Stats (simplified - you can expand later)
        plt.tight_layout()
        plt.savefig('vsm_measurements.png', dpi=120, facecolor='#0a0a0a', bbox_inches='tight')
        print("Measurements saved: vsm_measurements.png")
        plt.show()

# ─────────────────────────────────────────────
# LIVE RENDER (unchanged logic)
# ─────────────────────────────────────────────
def render_live(pins, psi, step_num, fig, axes, N):
    ax_slice, ax_profile = axes
    mid = N // 2
    psi_np = psi.cpu().numpy()

    ax_slice.cla()
    ax_profile.cla()

    ax_slice.imshow(psi_np[:, :, mid].T, origin='lower', cmap='inferno',
                    interpolation='bilinear', vmin=0, vmax=psi_np.max()*0.5)

    for i, pin in enumerate(pins):
        px, py = pin['pos'][0], pin['pos'][1]
        color = '#00ffff' if pin['omega'] > 0 else '#ff4444'
        ax_slice.plot(px, py, 'o', color=color, markersize=8, markeredgecolor='white', markeredgewidth=0.5)
        ax_slice.annotate(f"{pin['label']} ω={pin['omega']:+.0f}",
                         (px, py), textcoords='offset points', xytext=(5, 5),
                         color=color, fontsize=7)

    ax_slice.set_title(f'Ψ field Z-slice  step {step_num}', color='white', fontsize=9)
    ax_slice.axis('off')

    # Radial profile from pin 0 (kept from your original)
    if pins:
        p0 = pins[0]['pos']
        coords = np.arange(N)
        cx = coords[:, None, None]
        cy = coords[None, :, None]
        cz = coords[None, None, :]
        dx = np.minimum(np.abs(cx - p0[0]), N - np.abs(cx - p0[0]))
        dy = np.minimum(np.abs(cy - p0[1]), N - np.abs(cy - p0[1]))
        dz = np.minimum(np.abs(cz - p0[2]), N - np.abs(cz - p0[2]))
        r = np.sqrt(dx**2 + dy**2 + dz**2).flatten()
        pf = psi_np.flatten()
        r_bins = np.linspace(0, N//2, 40)
        pm = [pf[(r>=r_bins[k]) & (r<r_bins[k+1])].mean() if any((r>=r_bins[k]) & (r<r_bins[k+1])) else 0
              for k in range(len(r_bins)-1)]
        ax_profile.plot(r_bins[:-1], pm, color='#ff6b35', linewidth=2)
        ax_profile.fill_between(r_bins[:-1], pm, alpha=0.2, color='#ff6b35')
        ax_profile.set_facecolor('#111')
        ax_profile.set_title('Ψ radial from pin 0', color='white', fontsize=9)
        ax_profile.set_xlabel('Distance (cells)', color='#888')
        ax_profile.set_ylabel('Ψ', color='#888')
        ax_profile.tick_params(colors='#666')
        for sp in ax_profile.spines.values(): sp.set_color('#333')

# ─────────────────────────────────────────────
# SCENARIOS (your original dict - unchanged)
# ─────────────────────────────────────────────
ACTIVE_SCENARIO = '10v10'

half = N // 2
quarter = N // 4

SCENARIOS = {
    'single': {
        'pins': [make_pin([half, half, half], rho=1.0, omega=1.0, label='H')],
        'steps': 1000,
        'desc': 'Single hydrogen-like pin'
    },
    'same': {
        'pins': [
            make_pin([half-8, half, half], rho=1.0, omega=1.0, label='A+'),
            make_pin([half+8, half, half], rho=1.0, omega=1.0, label='B+'),
        ],
        'steps': 5000,
        'desc': 'Same spin'
    },
    'opposite': {
        'pins': [
            make_pin([half-8, half, half], rho=1.0, omega=1.0, label='A+'),
            make_pin([half+8, half, half], rho=1.0, omega=-1.0, label='B-'),
        ],
        'steps': 5000,
        'desc': 'Opposite spin'
    },
    'carbon': {
        'pins': [
            make_pin([half+4, half+4, half+4], rho=1.0, omega=1.0, label='C1'),
            make_pin([half-4, half-4, half+4], rho=1.0, omega=1.0, label='C2'),
            make_pin([half-4, half+4, half-4], rho=1.0, omega=1.0, label='C3'),
            make_pin([half+4, half-4, half-4], rho=1.0, omega=1.0, label='C4'),
            make_pin([half,   half,   half+6], rho=1.0, omega=1.0, label='C5'),
            make_pin([half,   half,   half-6], rho=1.0, omega=1.0, label='C6'),
        ],
        'steps': 5000,
        'desc': 'Carbon-like tetrahedral'
    },
    '10v10': {
        'pins': (
            [make_pin([half - 15 + (i%5)*6, half - 5 + (i//5)*10, half + np.random.randint(-3,3)],
                      rho=1.0, omega=1.0, label=f'P{i}') for i in range(10)] +
            [make_pin([half + 3 + (i%5)*6, half - 5 + (i//5)*10, half + np.random.randint(-3,3)],
                      rho=1.0, omega=-1.0, label=f'N{i}') for i in range(10)]
        ),
        'steps': 100000,
        'desc': '10 positive vs 10 negative'
    },
}

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
scenario = SCENARIOS[ACTIVE_SCENARIO]
pins     = scenario['pins']
STEPS    = scenario['steps']

print("=" * 60)
print("VORTEX SUBSTRATE MODEL v2 - GPU ACCELERATED")
print("=" * 60)
print(f"Scenario : {ACTIVE_SCENARIO}")
print(f"Desc     : {scenario['desc']}")
print(f"Grid     : {N}³")
print(f"Pins     : {len(pins)}")
print(f"Device   : {device}\n")

# Setup live plot
fig, (ax_slice, ax_profile) = plt.subplots(1, 2, figsize=(13, 6), facecolor='#0a0a0a')
fig.suptitle(f'VSM — {ACTIVE_SCENARIO} — {scenario["desc"]}', color='white', fontsize=10)
axes = [ax_slice, ax_profile]

measurements = Measurements(pins)
t0 = time.time()

for s in range(STEPS):
    psi = compute_psi(pins, N, tau_tensor, device)
    gx, gy, gz = compute_gradient(psi)
    step_pins(pins, psi, gx, gy, gz, DT, N, DAMP)

    if s % LOG_EVERY == 0:
        measurements.record(s, pins, psi, N)

    if s % SNAP_EVERY == 0:
        elapsed = time.time() - t0
        eta = (elapsed / (s + 1)) * (STEPS - s)
        print(f"step {s:>5}/{STEPS}   ETA {eta:.0f}s")
        render_live(pins, psi, s, fig, axes, N)
        plt.pause(0.001)

print(f"\nCompleted in {time.time()-t0:.1f}s")
measurements.print_summary(pins)
measurements.plot_measurements(pins)
plt.show()