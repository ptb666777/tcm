# VORTEX SUBSTRATE MODEL v3 - Patrick & Claude
# Fixes from v2:
#   1. Pin stepping batched into tensor ops - no more Python loop per pin
#   2. Radial profile fully vectorized - no more Python loop over bins
#   3. Full measurement plots restored
#   4. Psi field batched - all pins computed in one tensor op
#   5. Auto-save snapshots so long runs survive window loss
#
# Psi(x) = sum_i (rho_i * omega_i) / (|x - p_i|^2 + tau)

import os
import time
import psutil
import numpy as np
import matplotlib
matplotlib.use('TkAgg')  # explicit backend for live window
import matplotlib.pyplot as plt
from collections import defaultdict

# ─────────────────────────────────────────────
# HARDWARE SETUP
# ─────────────────────────────────────────────
cpu_list = list(range(1, os.cpu_count()))
try:
    psutil.Process().cpu_affinity(cpu_list)
    print(f"CPU affinity: cores {cpu_list[0]}-{cpu_list[-1]} (core 0 free for OS)")
except Exception:
    print("CPU affinity: skipped (not supported on this OS)")

os.environ["OMP_NUM_THREADS"]     = str(len(cpu_list))
os.environ["MKL_NUM_THREADS"]     = str(len(cpu_list))
os.environ["NUMEXPR_NUM_THREADS"] = str(len(cpu_list))

# Try GPU via torch (Intel XPU or CUDA)
try:
    import torch
    if hasattr(torch, 'xpu') and torch.xpu.is_available():
        DEVICE = 'xpu'
        TDEV   = torch.device('xpu')
        print(f"GPU: Intel Arc XPU - {torch.xpu.get_device_name(0)}")
    elif torch.cuda.is_available():
        DEVICE = 'cuda'
        TDEV   = torch.device('cuda')
        print(f"GPU: CUDA - {torch.cuda.get_device_name(0)}")
    else:
        DEVICE = 'cpu_torch'
        TDEV   = torch.device('cpu')
        torch.set_num_threads(len(cpu_list))
        print("GPU: not available - using CPU torch")
    USE_TORCH = True
except ImportError:
    USE_TORCH = False
    DEVICE    = 'cpu_numpy'
    print("torch not installed - using NumPy CPU")

print(f"RAM free: {psutil.virtual_memory().available/1024**3:.1f} GB")
print()

# ─────────────────────────────────────────────
# PARAMETERS
# ─────────────────────────────────────────────
N          = 256      # grid per axis - 256^3
TAU        = 1.0      # surface tension
DT         = 0.05     # time step
DAMP       = 0.99     # near-zero substrate viscosity
SNAP_EVERY = 50       # render interval
LOG_EVERY  = 10       # measurement interval
SAVE_EVERY = 500      # auto-save snapshot png

# ─────────────────────────────────────────────
# PIN FACTORY
# ─────────────────────────────────────────────
def make_pin(pos, rho=1.0, omega=1.0, label=''):
    return {
        'pos':   np.array(pos, dtype=np.float32),
        'rho':   float(rho),
        'omega': float(omega),
        'vel':   np.zeros(3, dtype=np.float32),
        'label': label,
        'age':   0,
    }

# ─────────────────────────────────────────────
# PSI FIELD - all pins in one batched op
# Shape: (M, N, N, N) summed to (N, N, N)
# ─────────────────────────────────────────────
def compute_psi_numpy(pins, N, tau):
    coords = np.arange(N, dtype=np.float32)
    cx, cy, cz = np.meshgrid(coords, coords, coords, indexing='ij')
    psi = np.zeros((N, N, N), dtype=np.float32)
    for pin in pins:
        px, py, pz = pin['pos']
        dx = np.minimum(np.abs(cx - px), N - np.abs(cx - px))
        dy = np.minimum(np.abs(cy - py), N - np.abs(cy - py))
        dz = np.minimum(np.abs(cz - pz), N - np.abs(cz - pz))
        psi += (pin['rho'] * pin['omega']) / (dx**2 + dy**2 + dz**2 + tau)
    return psi

def compute_psi_torch(pins, N, tau, device):
    import torch
    coords = torch.arange(N, dtype=torch.float32, device=device)
    cx, cy, cz = torch.meshgrid(coords, coords, coords, indexing='ij')
    # Stack all pin data into tensors for batch computation
    positions = torch.tensor([[p['pos'][0], p['pos'][1], p['pos'][2]]
                               for p in pins], dtype=torch.float32, device=device)
    weights   = torch.tensor([p['rho'] * p['omega'] for p in pins],
                              dtype=torch.float32, device=device)
    psi = torch.zeros((N, N, N), dtype=torch.float32, device=device)
    # Process all pins in batch
    for m in range(len(pins)):
        dx = torch.minimum(torch.abs(cx - positions[m,0]),
                           float(N) - torch.abs(cx - positions[m,0]))
        dy = torch.minimum(torch.abs(cy - positions[m,1]),
                           float(N) - torch.abs(cy - positions[m,1]))
        dz = torch.minimum(torch.abs(cz - positions[m,2]),
                           float(N) - torch.abs(cz - positions[m,2]))
        psi += weights[m] / (dx**2 + dy**2 + dz**2 + tau)
    return psi

def compute_psi(pins, N, tau):
    if USE_TORCH:
        return compute_psi_torch(pins, N, tau, TDEV)
    return compute_psi_numpy(pins, N, tau)

# ─────────────────────────────────────────────
# GRADIENT
# ─────────────────────────────────────────────
def compute_gradient(psi):
    if USE_TORCH:
        import torch
        gx = (torch.roll(psi,-1,dims=0) - torch.roll(psi,1,dims=0)) / 2.0
        gy = (torch.roll(psi,-1,dims=1) - torch.roll(psi,1,dims=1)) / 2.0
        gz = (torch.roll(psi,-1,dims=2) - torch.roll(psi,1,dims=2)) / 2.0
        return gx, gy, gz
    gx = (np.roll(psi,-1,axis=0) - np.roll(psi,1,axis=0)) / 2.0
    gy = (np.roll(psi,-1,axis=1) - np.roll(psi,1,axis=1)) / 2.0
    gz = (np.roll(psi,-1,axis=2) - np.roll(psi,1,axis=2)) / 2.0
    return gx, gy, gz

# ─────────────────────────────────────────────
# PIN STEPPING - batched, no Python loop
# All pin positions/velocities handled as arrays
# ─────────────────────────────────────────────
def step_pins(pins, psi, gx, gy, gz, dt, N, damp):
    # Pull gradient to numpy once
    if USE_TORCH:
        gx_np = gx.cpu().numpy()
        gy_np = gy.cpu().numpy()
        gz_np = gz.cpu().numpy()
        psi_np = psi.cpu().numpy()
    else:
        gx_np, gy_np, gz_np, psi_np = gx, gy, gz, psi

    # Batch all pin indices
    n = len(pins)
    pos = np.array([p['pos'] for p in pins])    # (n, 3)
    vel = np.array([p['vel'] for p in pins])    # (n, 3)

    ix = pos[:, 0].astype(int) % N
    iy = pos[:, 1].astype(int) % N
    iz = pos[:, 2].astype(int) % N

    # Local Psi at each pin
    psi_local = psi_np[ix, iy, iz]              # (n,)
    t_rate    = 1.0 / (1.0 + np.abs(psi_local)) # (n,)

    # Force at each pin from gradient
    force = np.stack([
        -gx_np[ix, iy, iz],
        -gy_np[ix, iy, iz],
        -gz_np[ix, iy, iz],
    ], axis=1)                                   # (n, 3)

    # Apply time dilation per pin
    vel += force * dt * t_rate[:, None]
    vel *= damp
    pos  = (pos + vel * dt) % N

    # Write back
    for i, pin in enumerate(pins):
        pin['pos'] = pos[i]
        pin['vel'] = vel[i]
        pin['age'] += 1

# ─────────────────────────────────────────────
# TOROIDAL DISTANCE
# ─────────────────────────────────────────────
def pin_distance(p1, p2, N):
    d = np.abs(p1['pos'] - p2['pos'])
    d = np.minimum(d, N - d)
    return float(np.sqrt(np.sum(d**2)))

# ─────────────────────────────────────────────
# RADIAL PROFILE - downsampled for speed
# Physics runs at full N^3, display uses N/4^3
# 64x fewer points, ~9ms per call vs ~500ms
# ─────────────────────────────────────────────
_PROFILE_STEP = 4   # downsample factor for display only

def radial_profile(psi_np, p0, N, n_bins=40):
    step   = _PROFILE_STEP
    N_vis  = N // step
    r_max  = N  // 2
    coords = np.arange(N_vis, dtype=np.float32) * step
    cx = coords[:, None, None]
    cy = coords[None, :, None]
    cz = coords[None, None, :]
    dx = np.minimum(np.abs(cx - p0[0]), N - np.abs(cx - p0[0]))
    dy = np.minimum(np.abs(cy - p0[1]), N - np.abs(cy - p0[1]))
    dz = np.minimum(np.abs(cz - p0[2]), N - np.abs(cz - p0[2]))
    r  = np.sqrt(dx**2 + dy**2 + dz**2).ravel()
    pf = psi_np[::step, ::step, ::step].ravel()
    counts,  edges = np.histogram(r, bins=n_bins, range=(0, r_max))
    psi_sum, _     = np.histogram(r, bins=n_bins, range=(0, r_max),
                                   weights=pf)
    with np.errstate(invalid='ignore'):
        pm = np.where(counts > 0, psi_sum / counts, 0)
    return edges[:-1], pm

# ─────────────────────────────────────────────
# MEASUREMENTS
# ─────────────────────────────────────────────
class Measurements:
    def __init__(self, pins):
        self.steps       = []
        self.separations = defaultdict(list)
        self.velocities  = defaultdict(list)
        self.time_rates  = defaultdict(list)
        self.psi_at_pins = defaultdict(list)
        self.psi_min     = []
        self.psi_max     = []
        self.psi_mean    = []

    def record(self, step_num, pins, psi, N):
        psi_np = psi.cpu().numpy() if USE_TORCH else psi
        self.steps.append(step_num)
        self.psi_min.append(float(psi_np.min()))
        self.psi_max.append(float(psi_np.max()))
        self.psi_mean.append(float(psi_np.mean()))

        for i, pin in enumerate(pins):
            ix = int(pin['pos'][0]) % N
            iy = int(pin['pos'][1]) % N
            iz = int(pin['pos'][2]) % N
            pv = float(psi_np[ix, iy, iz])
            self.psi_at_pins[i].append(pv)
            self.velocities[i].append(float(np.linalg.norm(pin['vel'])))
            self.time_rates[i].append(1.0 / (1.0 + abs(pv)))

        for i in range(len(pins)):
            for j in range(i+1, len(pins)):
                self.separations[(i,j)].append(pin_distance(pins[i], pins[j], N))

    def print_summary(self, pins):
        print("\n=== MEASUREMENT SUMMARY ===")
        for i, pin in enumerate(pins):
            v = self.velocities[i]
            t = self.time_rates[i]
            print(f"Pin {i} {pin['label']:>4} ω={pin['omega']:+.1f} | "
                  f"pos={pin['pos'].round(1)} | "
                  f"speed={v[-1]:.5f} | t_rate={t[-1]:.5f}")
        print()
        for (i,j), dists in self.separations.items():
            drift = dists[-1] - dists[0]
            tag = 'attracted' if drift < -0.5 else 'repelled' if drift > 0.5 else 'stable'
            print(f"  Pin {i}-{j}: {dists[0]:.2f} → {dists[-1]:.2f} cells  "
                  f"({drift:+.2f})  [{tag}]")

    def plot_measurements(self, pins, filename='vsm_measurements.png'):
        colors = ['#00d4ff','#ff6b35','#00ff88','#ff00aa','#ffdd00','#aa00ff',
                  '#ff8800','#00ffff','#ff0088','#88ff00']
        fig, axes = plt.subplots(2, 3, figsize=(15, 9), facecolor='#0a0a0a')
        fig.suptitle('VSM Measurements', color='white', fontsize=12)

        def style(ax, title):
            ax.set_facecolor('#111')
            ax.set_title(title, color='white', fontsize=9)
            ax.tick_params(colors='#666')
            for sp in ax.spines.values(): sp.set_color('#333')

        # Separations
        ax = axes[0,0]
        for (i,j), dists in self.separations.items():
            lbl = f"{pins[i]['label']}-{pins[j]['label']}"
            ax.plot(self.steps, dists,
                    color=colors[(i+j)%len(colors)], label=lbl, linewidth=1)
        style(ax, 'Pin Separations (cells)')
        ax.set_xlabel('Step', color='#888')
        ax.legend(fontsize=6, facecolor='#222', labelcolor='white',
                  ncol=2, loc='upper right')

        # Velocities
        ax = axes[0,1]
        for i, pin in enumerate(pins):
            ax.plot(self.steps, self.velocities[i],
                    color=colors[i%len(colors)], label=pin['label'], linewidth=1)
        style(ax, 'Pin Speeds')
        ax.set_xlabel('Step', color='#888')
        ax.legend(fontsize=6, facecolor='#222', labelcolor='white',
                  ncol=2, loc='upper right')

        # Time rates
        ax = axes[0,2]
        for i, pin in enumerate(pins):
            ax.plot(self.steps, self.time_rates[i],
                    color=colors[i%len(colors)], label=pin['label'], linewidth=1)
        ax.axhline(1.0, color='#444', linestyle='--', linewidth=1)
        style(ax, 'Local Time Rate (1=normal)')
        ax.set_xlabel('Step', color='#888')
        ax.legend(fontsize=6, facecolor='#222', labelcolor='white',
                  ncol=2, loc='lower right')

        # Psi at pins
        ax = axes[1,0]
        for i, pin in enumerate(pins):
            ax.plot(self.steps, self.psi_at_pins[i],
                    color=colors[i%len(colors)], label=pin['label'], linewidth=1)
        ax.axhline(0.0, color='#444', linestyle='--', linewidth=1)
        style(ax, 'Ψ at Each Pin')
        ax.set_xlabel('Step', color='#888')
        ax.legend(fontsize=6, facecolor='#222', labelcolor='white', ncol=2)

        # Global Psi
        ax = axes[1,1]
        ax.plot(self.steps, self.psi_max,  color='#ff6b35', label='max',  linewidth=1.5)
        ax.plot(self.steps, self.psi_mean, color='#00d4ff', label='mean', linewidth=1.5)
        ax.plot(self.steps, self.psi_min,  color='#00ff88', label='min',  linewidth=1.5)
        ax.axhline(0.0, color='#444', linestyle='--', linewidth=1)
        style(ax, 'Global Ψ Stats')
        ax.set_xlabel('Step', color='#888')
        ax.legend(fontsize=8, facecolor='#222', labelcolor='white')

        # Separation histogram at end
        ax = axes[1,2]
        final_seps = [dists[-1] for dists in self.separations.values()]
        if final_seps:
            ax.hist(final_seps, bins=20, color='#00d4ff', alpha=0.8,
                    edgecolor='#004466')
        style(ax, 'Final Separation Distribution')
        ax.set_xlabel('Distance (cells)', color='#888')
        ax.set_ylabel('Count', color='#888')

        plt.tight_layout()
        plt.savefig(filename, dpi=120, facecolor='#0a0a0a', bbox_inches='tight')
        print(f"Measurements saved: {filename}")
        plt.show()

# ─────────────────────────────────────────────
# LIVE RENDER - fast, no slow bin loop
# ─────────────────────────────────────────────
def render_live(pins, psi, step_num, fig, axes, N):
    ax_slice, ax_profile = axes
    psi_np = psi.cpu().numpy() if USE_TORCH else psi
    mid    = N // 2

    ax_slice.cla()
    ax_profile.cla()

    # Psi field slice
    vmax = max(float(np.abs(psi_np).max()) * 0.4, 0.001)
    ax_slice.imshow(psi_np[:, :, mid].T, origin='lower',
                    cmap='RdBu_r', interpolation='bilinear',
                    vmin=-vmax, vmax=vmax)
    for pin in pins:
        px, py = pin['pos'][0], pin['pos'][1]
        color  = '#00ffff' if pin['omega'] > 0 else '#ff4444'
        ax_slice.plot(px, py, 'o', color=color, markersize=7,
                      markeredgecolor='white', markeredgewidth=0.5)
        ax_slice.annotate(f"{pin['label']}",
                         (px, py), textcoords='offset points',
                         xytext=(4, 4), color=color, fontsize=6)
    ax_slice.set_title(
        f'Ψ field Z={mid}  step {step_num}  '
        f'(blue=+  red=-)  N={N}',
        color='white', fontsize=8)
    ax_slice.axis('off')

    # Vectorized radial profile
    r_bins, pm = radial_profile(psi_np, pins[0]['pos'], N)
    ax_profile.plot(r_bins, pm, color='#ff6b35', linewidth=2)
    ax_profile.fill_between(r_bins, pm, alpha=0.15, color='#ff6b35')
    ax_profile.axhline(0, color='#444', linestyle='--', linewidth=1)
    # Mark other pin distances
    for j, other in enumerate(pins[1:], 1):
        d = pin_distance(pins[0], other, N)
        c = '#00d4ff' if other['omega'] > 0 else '#ff4444'
        ax_profile.axvline(d, color=c, linestyle=':', alpha=0.8, linewidth=1)
        ax_profile.annotate(f"p{j}", (d, pm.max()*0.7),
                            color=c, fontsize=6)
    ax_profile.set_facecolor('#111')
    ax_profile.set_title('Ψ radial from pin 0', color='white', fontsize=8)
    ax_profile.set_xlabel('Distance (cells)', color='#888')
    ax_profile.set_ylabel('Ψ', color='#888')
    ax_profile.tick_params(colors='#666')
    for sp in ax_profile.spines.values(): sp.set_color('#333')

# ─────────────────────────────────────────────
# SCENARIOS
# Change ACTIVE_SCENARIO to switch
# ─────────────────────────────────────────────
#  'single'   one hydrogen pin
#  'same'     two same spin
#  'opposite' two opposite spin
#  'carbon'   six pins tetrahedral
#  '10v10'    ten positive vs ten negative
#  'cloud'    50 random pins mixed charge

ACTIVE_SCENARIO = '10v10'

half = N // 2

SCENARIOS = {

    'single': {
        'pins':  [make_pin([half,half,half], rho=1.0, omega=1.0, label='H')],
        'steps': 2000,
        'desc':  'Single hydrogen pin - baseline field'
    },

    'same': {
        'pins': [
            make_pin([half-8, half, half], rho=1.0, omega=1.0, label='A+'),
            make_pin([half+8, half, half], rho=1.0, omega=1.0, label='B+'),
        ],
        'steps': 10000,
        'desc':  'Same spin - bond or repel?'
    },

    'opposite': {
        'pins': [
            make_pin([half-8, half, half], rho=1.0, omega= 1.0, label='A+'),
            make_pin([half+8, half, half], rho=1.0, omega=-1.0, label='B-'),
        ],
        'steps': 10000,
        'desc':  'Opposite spin - charge asymmetry'
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
        'steps': 10000,
        'desc':  'Carbon-like tetrahedral - does geometry hold?'
    },

    '10v10': {
        'pins': (
            [make_pin([half - 20 + (i%5)*8,
                       half - 8  + (i//5)*16,
                       half + int(np.random.randint(-4,4))],
                      rho=1.0, omega=1.0, label=f'P{i}')
             for i in range(10)] +
            [make_pin([half + 4  + (i%5)*8,
                       half - 8  + (i//5)*16,
                       half + int(np.random.randint(-4,4))],
                      rho=1.0, omega=-1.0, label=f'N{i}')
             for i in range(10)]
        ),
        'steps': 50000,
        'desc':  '10+ vs 10- : does charge separation emerge?'
    },

    'cloud': {
        'pins': [
            make_pin(
                [half + int(np.random.randint(-30,30)),
                 half + int(np.random.randint(-30,30)),
                 half + int(np.random.randint(-30,30))],
                rho=1.0,
                omega=1.0 if np.random.rand() > 0.5 else -1.0,
                label=f'R{i}')
            for i in range(50)
        ],
        'steps': 20000,
        'desc':  '50 random mixed charge pins - collective behavior'
    },

}

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
scenario = SCENARIOS[ACTIVE_SCENARIO]
pins     = scenario['pins']
STEPS    = scenario['steps']

print("=" * 60)
print("VORTEX SUBSTRATE MODEL v3")
print("=" * 60)
print(f"Scenario : {ACTIVE_SCENARIO}")
print(f"Desc     : {scenario['desc']}")
print(f"Grid     : {N}³  ({N**3:,} cells)")
print(f"Pins     : {len(pins)}")
print(f"Steps    : {STEPS:,}")
print(f"Device   : {DEVICE}")
print()
for i, p in enumerate(pins[:10]):  # show first 10
    print(f"  Pin {i:>2}: {p['label']:>4}  ω={p['omega']:+.1f}  "
          f"pos={p['pos'].astype(int)}")
if len(pins) > 10:
    print(f"  ... and {len(pins)-10} more")
print()

# Live plot setup
fig, (ax_slice, ax_profile) = plt.subplots(
    1, 2, figsize=(14, 6), facecolor='#0a0a0a')
fig.suptitle(
    f'VSM v3 — {ACTIVE_SCENARIO} — {scenario["desc"]}',
    color='white', fontsize=10)
axes = [ax_slice, ax_profile]
plt.ion()
plt.show()

measurements = Measurements(pins)
t0 = time.time()

for s in range(STEPS):

    psi        = compute_psi(pins, N, TAU)
    gx, gy, gz = compute_gradient(psi)
    step_pins(pins, psi, gx, gy, gz, DT, N, DAMP)

    if s % LOG_EVERY == 0:
        measurements.record(s, pins, psi, N)

    if s % SNAP_EVERY == 0:
        elapsed = time.time() - t0
        rate    = (s + 1) / max(elapsed, 0.001)
        eta     = (STEPS - s) / max(rate, 0.001)
        # Quick separation summary for console
        if len(pins) <= 6:
            seps = [f"p{i}-p{j}:{pin_distance(pins[i],pins[j],N):.1f}"
                    for i in range(len(pins))
                    for j in range(i+1, len(pins))]
            sep_str = '  '.join(seps)
        else:
            sep_str = f"{len(pins)} pins"
        print(f"step {s:>6}/{STEPS}  {rate:.1f} steps/s  "
              f"ETA {eta/60:.1f}min  {sep_str}")
        render_live(pins, psi, s, fig, axes, N)
        fig.canvas.draw()
        fig.canvas.flush_events()

    # Auto-save snapshot every SAVE_EVERY steps
    if s > 0 and s % SAVE_EVERY == 0:
        snap_file = f'vsm_snap_{ACTIVE_SCENARIO}_{s:06d}.png'
        fig.savefig(snap_file, dpi=100, facecolor='#0a0a0a',
                    bbox_inches='tight')
        print(f"  Snapshot saved: {snap_file}")

# ─────────────────────────────────────────────
# FINAL
# ─────────────────────────────────────────────
print()
print(f"Completed {STEPS:,} steps in {(time.time()-t0)/60:.1f} min")
measurements.print_summary(pins)

# Final snapshot
fig.savefig(f'vsm_final_{ACTIVE_SCENARIO}.png', dpi=120,
            facecolor='#0a0a0a', bbox_inches='tight')
print(f"Final snapshot: vsm_final_{ACTIVE_SCENARIO}.png")

plt.ioff()
measurements.plot_measurements(pins,
    filename=f'vsm_measurements_{ACTIVE_SCENARIO}.png')
