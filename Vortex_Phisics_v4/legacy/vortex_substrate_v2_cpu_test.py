# VORTEX SUBSTRATE MODEL v2
# Patrick & Claude - VSM formal logic string implementation
#
# Psi(x) = sum_i (rho_i * omega_i) / (|x - p_i|^2 + tau)
#
# tau   = surface tension (vacuum resistance to pinning)
# rho   = resonance variant (atomic geometry factor)
# omega = spin frequency (positive or negative = chirality = charge)
# Psi   = local reality field density
#
# Gravity    : pins pushed toward low-Psi zones (pressure gradient)
# Charge     : omega sign determines field character
# Time       : local rate = 1 / (1 + Psi)  slower in dense regions
# Black hole : Psi > shear limit = cavitation event

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.gridspec import GridSpec
from collections import defaultdict
import time

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

# ─────────────────────────────────────────────
# GRID AND SUBSTRATE
# ─────────────────────────────────────────────
N         = 128         # grid per axis - 128^3, handles 10+ pin scenarios
TAU       = 1.0         # surface tension
DT        = 0.05        # time step
STEPS     = 3000        # default run length
SNAP_EVERY = 20         # render interval
LOG_EVERY  = 10         # measurement log interval
DAMP       = 0.99       # near-zero substrate viscosity

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
# PSI FIELD - vectorized
# ─────────────────────────────────────────────
def compute_psi(pins, N, tau):
    coords = np.arange(N)
    cx, cy, cz = np.meshgrid(coords, coords, coords, indexing='ij')
    psi = np.zeros((N, N, N))
    for pin in pins:
        px, py, pz = pin['pos']
        dx = np.minimum(np.abs(cx - px), N - np.abs(cx - px))
        dy = np.minimum(np.abs(cy - py), N - np.abs(cy - py))
        dz = np.minimum(np.abs(cz - pz), N - np.abs(cz - pz))
        r2 = dx**2 + dy**2 + dz**2
        # omega sign affects field - positive adds density, negative subtracts
        # This is chirality = charge asymmetry
        psi += (pin['rho'] * pin['omega']) / (r2 + tau)
    return psi

# ─────────────────────────────────────────────
# GRADIENT
# ─────────────────────────────────────────────
def compute_gradient(psi):
    gx = (np.roll(psi, -1, axis=0) - np.roll(psi, 1, axis=0)) / 2.0
    gy = (np.roll(psi, -1, axis=1) - np.roll(psi, 1, axis=1)) / 2.0
    gz = (np.roll(psi, -1, axis=2) - np.roll(psi, 1, axis=2)) / 2.0
    return gx, gy, gz

# ─────────────────────────────────────────────
# TOROIDAL DISTANCE between two pins
# ─────────────────────────────────────────────
def pin_distance(p1, p2, N):
    d = np.abs(p1['pos'] - p2['pos'])
    d = np.minimum(d, N - d)
    return float(np.sqrt(np.sum(d**2)))

# ─────────────────────────────────────────────
# STEP
# ─────────────────────────────────────────────
def step_pins(pins, psi, gx, gy, gz, dt, N, damp):
    for pin in pins:
        ix = int(pin['pos'][0]) % N
        iy = int(pin['pos'][1]) % N
        iz = int(pin['pos'][2]) % N

        # Local time rate - slower in dense Psi
        psi_local = psi[ix, iy, iz]
        t_rate = 1.0 / (1.0 + abs(psi_local))

        # Force = negative gradient (toward low Psi = gravity)
        # For negative omega pins, Psi contribution is negative
        # so they are pushed AWAY from other positive pins - repulsion
        force = np.array([
            -gx[ix, iy, iz],
            -gy[ix, iy, iz],
            -gz[ix, iy, iz],
        ])

        pin['vel'] += force * dt * t_rate
        pin['vel'] *= damp
        pin['pos'] = (pin['pos'] + pin['vel'] * dt) % N
        pin['age'] += 1

# ─────────────────────────────────────────────
# MEASUREMENTS - logged every LOG_EVERY steps
# ─────────────────────────────────────────────
class Measurements:
    def __init__(self, pins):
        self.steps       = []
        self.separations = defaultdict(list)  # (i,j) -> [distances]
        self.psi_at_pins = defaultdict(list)  # pin_i -> [psi values]
        self.velocities  = defaultdict(list)  # pin_i -> [speed]
        self.time_rates  = defaultdict(list)  # pin_i -> [local time rate]
        self.psi_min     = []
        self.psi_max     = []
        self.psi_mean    = []
        self.n_pins      = len(pins)

    def record(self, step_num, pins, psi, N):
        self.steps.append(step_num)
        self.psi_min.append(float(psi.min()))
        self.psi_max.append(float(psi.max()))
        self.psi_mean.append(float(psi.mean()))

        for i, pin in enumerate(pins):
            ix = int(pin['pos'][0]) % N
            iy = int(pin['pos'][1]) % N
            iz = int(pin['pos'][2]) % N
            psi_local = float(psi[ix, iy, iz])
            self.psi_at_pins[i].append(psi_local)
            self.velocities[i].append(float(np.linalg.norm(pin['vel'])))
            self.time_rates[i].append(1.0 / (1.0 + abs(psi_local)))

        for i in range(len(pins)):
            for j in range(i+1, len(pins)):
                d = pin_distance(pins[i], pins[j], N)
                self.separations[(i,j)].append(d)

    def print_summary(self, pins):
        print()
        print("=== MEASUREMENT SUMMARY ===")
        print(f"Steps recorded: {len(self.steps)}")
        print()
        for i, pin in enumerate(pins):
            speeds = self.velocities[i]
            trates = self.time_rates[i]
            print(f"Pin {i} ({pin['label'] or 'unlabeled'}) omega={pin['omega']:+.1f}")
            print(f"  Final pos:    {pin['pos'].round(2)}")
            print(f"  Final speed:  {speeds[-1]:.6f}")
            print(f"  Time rate:    {trates[-1]:.6f}  (started {trates[0]:.6f})")
            print(f"  Avg speed:    {np.mean(speeds):.6f}")

        print()
        for (i,j), dists in self.separations.items():
            print(f"Pin {i}-{j} separation:")
            print(f"  Start: {dists[0]:.3f} cells")
            print(f"  Final: {dists[-1]:.3f} cells")
            print(f"  Min:   {min(dists):.3f} cells")
            print(f"  Max:   {max(dists):.3f} cells")
            drift = dists[-1] - dists[0]
            print(f"  Drift: {drift:+.3f} cells  "
                  f"({'attracted' if drift < -0.5 else 'repelled' if drift > 0.5 else 'stable'})")

    def plot_measurements(self, pins):
        fig, axes = plt.subplots(2, 2, figsize=(12, 8),
                                 facecolor='#0a0a0a')
        fig.suptitle('VSM Measurements', color='white', fontsize=12)
        colors = ['#00d4ff', '#ff6b35', '#00ff88', '#ff00aa',
                  '#ffdd00', '#aa00ff']

        # Pin separations
        ax = axes[0,0]
        ax.set_facecolor('#111')
        for (i,j), dists in self.separations.items():
            lbl = (f"Pin {i}({pins[i]['label']}) - "
                   f"Pin {j}({pins[j]['label']})")
            ax.plot(self.steps, dists,
                    color=colors[(i+j)%len(colors)], label=lbl, linewidth=1.5)
        ax.set_title('Pin Separations (cells)', color='white')
        ax.set_xlabel('Step', color='#888')
        ax.set_ylabel('Distance', color='#888')
        ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
        ax.tick_params(colors='#666')
        for sp in ax.spines.values(): sp.set_color('#333')

        # Velocities
        ax = axes[0,1]
        ax.set_facecolor('#111')
        for i, pin in enumerate(pins):
            ax.plot(self.steps, self.velocities[i],
                    color=colors[i%len(colors)],
                    label=f"Pin {i} {pin['label']}", linewidth=1.5)
        ax.set_title('Pin Speeds', color='white')
        ax.set_xlabel('Step', color='#888')
        ax.set_ylabel('Speed', color='#888')
        ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
        ax.tick_params(colors='#666')
        for sp in ax.spines.values(): sp.set_color('#333')

        # Local time rates
        ax = axes[1,0]
        ax.set_facecolor('#111')
        for i, pin in enumerate(pins):
            ax.plot(self.steps, self.time_rates[i],
                    color=colors[i%len(colors)],
                    label=f"Pin {i} {pin['label']}", linewidth=1.5)
        ax.axhline(y=1.0, color='#444', linestyle='--', linewidth=1)
        ax.set_title('Local Time Rate at Each Pin', color='white')
        ax.set_xlabel('Step', color='#888')
        ax.set_ylabel('Time rate (1=normal)', color='#888')
        ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
        ax.tick_params(colors='#666')
        for sp in ax.spines.values(): sp.set_color('#333')

        # Global Psi stats
        ax = axes[1,1]
        ax.set_facecolor('#111')
        ax.plot(self.steps, self.psi_max,
                color='#ff6b35', label='Psi max', linewidth=1.5)
        ax.plot(self.steps, self.psi_mean,
                color='#00d4ff', label='Psi mean', linewidth=1.5)
        ax.plot(self.steps, self.psi_min,
                color='#00ff88', label='Psi min', linewidth=1.5)
        ax.set_title('Global Ψ Field Stats', color='white')
        ax.set_xlabel('Step', color='#888')
        ax.set_ylabel('Ψ', color='#888')
        ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
        ax.tick_params(colors='#666')
        for sp in ax.spines.values(): sp.set_color('#333')

        plt.tight_layout()
        plt.savefig('vsm_measurements.png', dpi=120,
                    facecolor='#0a0a0a', bbox_inches='tight')
        print("Measurements saved: vsm_measurements.png")
        plt.show()

# ─────────────────────────────────────────────
# VISUALIZATION - live slice view
# ─────────────────────────────────────────────
def render_live(pins, psi, step_num, fig, axes, N):
    ax_slice, ax_profile = axes
    mid = N // 2

    ax_slice.cla()
    ax_profile.cla()

    # Psi slice
    ax_slice.imshow(psi[:, :, mid].T, origin='lower',
                    cmap='inferno', interpolation='bilinear',
                    vmin=0, vmax=psi.max()*0.5)
    for i, pin in enumerate(pins):
        px, py = pin['pos'][0], pin['pos'][1]
        color = '#00ffff' if pin['omega'] > 0 else '#ff4444'
        ax_slice.plot(px, py, 'o', color=color, markersize=8,
                      markeredgecolor='white', markeredgewidth=0.5)
        ax_slice.annotate(f"{pin['label']} ω={pin['omega']:+.0f}",
                         (px, py), textcoords='offset points',
                         xytext=(5, 5), color=color, fontsize=7)
    ax_slice.set_title(f'Ψ field Z-slice  step {step_num}  '
                       f'(cyan=+spin  red=-spin)',
                       color='white', fontsize=9)
    ax_slice.axis('off')

    # Radial profile from pin 0
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
        pf = psi.flatten()
        r_bins = np.linspace(0, N//2, 40)
        pm = [pf[(r>=r_bins[k])&(r<r_bins[k+1])].mean()
              if ((r>=r_bins[k])&(r<r_bins[k+1])).any() else 0
              for k in range(len(r_bins)-1)]
        ax_profile.plot(r_bins[:-1], pm,
                        color='#ff6b35', linewidth=2)
        ax_profile.fill_between(r_bins[:-1], pm, alpha=0.2, color='#ff6b35')
        ax_profile.set_facecolor('#111')
        ax_profile.set_title('Ψ radial from pin 0', color='white', fontsize=9)
        ax_profile.set_xlabel('Distance (cells)', color='#888')
        ax_profile.set_ylabel('Ψ', color='#888')
        ax_profile.tick_params(colors='#666')
        for sp in ax_profile.spines.values(): sp.set_color('#333')

        # Mark pin separations
        for j, other in enumerate(pins[1:], 1):
            d = pin_distance(pins[0], other, N)
            ax_profile.axvline(x=d, color='#00d4ff',
                               linestyle='--', alpha=0.7, linewidth=1)
            ax_profile.annotate(f'pin{j} d={d:.1f}',
                               (d, max(pm)*0.8),
                               color='#00d4ff', fontsize=7)

# ─────────────────────────────────────────────
# SCENARIOS - edit ACTIVE_SCENARIO to switch
# ─────────────────────────────────────────────
#
# 'single'   - one hydrogen-like pin
# 'same'     - two same-spin (B from v1)
# 'opposite' - two opposite-spin (C from v1)
# 'carbon'   - 6 pins tetrahedral geometry
# 'h_vs_fe'  - hydrogen cluster vs iron-like cluster
# '10v10'    - ten positive vs ten negative

ACTIVE_SCENARIO = '10v10'   # <-- CHANGE THIS

half = N // 2
quarter = N // 4

SCENARIOS = {

    'single': {
        'pins': [make_pin([half, half, half], rho=1.0, omega=1.0, label='H')],
        'steps': 1000,
        'desc': 'Single hydrogen-like pin - baseline field'
    },

    'same': {
        'pins': [
            make_pin([half-8, half, half], rho=1.0, omega=1.0, label='A+'),
            make_pin([half+8, half, half], rho=1.0, omega=1.0, label='B+'),
        ],
        'steps': 5000,
        'desc': 'Same spin - do they bond or repel?'
    },

    'opposite': {
        'pins': [
            make_pin([half-8, half, half], rho=1.0, omega= 1.0, label='A+'),
            make_pin([half+8, half, half], rho=1.0, omega=-1.0, label='B-'),
        ],
        'steps': 5000,
        'desc': 'Opposite spin - charge asymmetry test'
    },

    'carbon': {
        'pins': [
            # 6 protons in tetrahedral/octahedral geometry
            # rho=6 because carbon resonance involves 6-fold geometry
            make_pin([half+4, half+4, half+4], rho=1.0, omega=1.0, label='C1'),
            make_pin([half-4, half-4, half+4], rho=1.0, omega=1.0, label='C2'),
            make_pin([half-4, half+4, half-4], rho=1.0, omega=1.0, label='C3'),
            make_pin([half+4, half-4, half-4], rho=1.0, omega=1.0, label='C4'),
            make_pin([half,   half,   half+6], rho=1.0, omega=1.0, label='C5'),
            make_pin([half,   half,   half-6], rho=1.0, omega=1.0, label='C6'),
        ],
        'steps': 5000,
        'desc': 'Carbon-like - 6 pins tetrahedral. Do they hold geometry?'
    },

    '10v10': {
        'pins': (
            # 10 positive spin pins
            [make_pin([half - 15 + (i%5)*6,
                       half - 5 + (i//5)*10,
                       half + np.random.randint(-3,3)],
                      rho=1.0, omega=1.0, label=f'P{i}')
             for i in range(10)] +
            # 10 negative spin pins
            [make_pin([half + 3 + (i%5)*6,
                       half - 5 + (i//5)*10,
                       half + np.random.randint(-3,3)],
                      rho=1.0, omega=-1.0, label=f'N{i}')
             for i in range(10)]
        ),
        'steps': 3000,
        'desc': '10 positive vs 10 negative - collective behavior'
    },

}

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
scenario = SCENARIOS[ACTIVE_SCENARIO]
pins     = scenario['pins']
STEPS    = scenario['steps']

print("=" * 60)
print("VORTEX SUBSTRATE MODEL v2")
print("=" * 60)
print(f"Scenario : {ACTIVE_SCENARIO}")
print(f"Desc     : {scenario['desc']}")
print(f"Grid     : {N}³")
print(f"Pins     : {len(pins)}")
print(f"Steps    : {STEPS}")
print(f"tau      : {TAU}")
print()
for i, p in enumerate(pins):
    print(f"  Pin {i}: {p['label']:>4}  omega={p['omega']:+.1f}  "
          f"pos={p['pos'].astype(int)}")
print()

# Setup live plot
fig, (ax_slice, ax_profile) = plt.subplots(
    1, 2, figsize=(13, 6), facecolor='#0a0a0a')
fig.suptitle(f'VSM — {ACTIVE_SCENARIO} — {scenario["desc"]}',
             color='white', fontsize=10)
axes = [ax_slice, ax_profile]

measurements = Measurements(pins)
t0 = time.time()

for s in range(STEPS):
    psi = compute_psi(pins, N, TAU)
    gx, gy, gz = compute_gradient(psi)
    step_pins(pins, psi, gx, gy, gz, DT, N, DAMP)

    if s % LOG_EVERY == 0:
        measurements.record(s, pins, psi, N)

    if s % SNAP_EVERY == 0:
        elapsed = time.time() - t0
        eta = (elapsed / (s+1)) * (STEPS - s)
        seps = []
        for i in range(len(pins)):
            for j in range(i+1, len(pins)):
                seps.append(f"p{i}-p{j}:{pin_distance(pins[i],pins[j],N):.1f}")
        print(f"step {s:>5}/{STEPS}  "
              f"sep=[{' '.join(seps)}]  "
              f"ETA {eta:.0f}s")
        render_live(pins, psi, s, fig, axes, N)
        plt.pause(0.001)

# Final state
print()
print(f"Completed in {time.time()-t0:.1f}s")
measurements.print_summary(pins)
measurements.plot_measurements(pins)

plt.show()
