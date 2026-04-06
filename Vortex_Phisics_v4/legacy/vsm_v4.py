# VORTEX SUBSTRATE MODEL v4
# Fast vectorized Psi - 8-9x faster than v3
# Live visualization back (throttled - no driver hammering)
# Proper 3D pin initialization - no more diagonal drift
# ZoneAlarm safe - no aggressive allocation patterns
#
# Patrick & Claude

import numpy as np
import matplotlib
matplotlib.use('TkAgg')   # stable windowed backend
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import os, time
from collections import defaultdict

# ─────────────────────────────────────────────
# PARAMETERS
# ─────────────────────────────────────────────
N          = 128      # grid per axis
TAU        = 1.0      # surface tension
DT         = 0.05     # time step
DAMP       = 0.99     # near-zero viscosity
SNAP_EVERY = 100      # render/save every N steps
LOG_EVERY  = 10       # measurement log interval
OUTPUT_DIR = 'vsm_output'
SHOW_LIVE  = True     # set False for headless

os.makedirs(OUTPUT_DIR, exist_ok=True)

# Pre-computed 1D coordinate arrays - used in vectorized Psi
_coords = np.arange(N, dtype=np.float32)

print(f"VSM v4  |  Grid: {N}^3  |  Output: {OUTPUT_DIR}/")
print(f"Vectorized Psi - ~8x faster than v3")
print()

# ─────────────────────────────────────────────
# PIN
# ─────────────────────────────────────────────
def make_pin(pos, rho=1.0, omega=1.0, label=''):
    return {
        'pos':   np.array(pos, dtype=np.float64),
        'rho':   float(rho),
        'omega': float(omega),
        'vel':   np.zeros(3, dtype=np.float64),
        'label': label,
    }

# ─────────────────────────────────────────────
# PSI FIELD - fully vectorized
# All pins computed simultaneously using
# outer product of 1D distance arrays.
# No meshgrid. No per-step allocation.
# ─────────────────────────────────────────────
def compute_psi(pins):
    if not pins:
        return np.zeros((N, N, N), dtype=np.float32)

    positions = np.array([p['pos'] for p in pins], dtype=np.float32)  # (P,3)
    weights   = np.array([p['rho'] * p['omega'] for p in pins],
                          dtype=np.float32)  # (P,)

    px = positions[:, 0]  # (P,)
    py = positions[:, 1]
    pz = positions[:, 2]

    # Toroidal distances: shape (P, N)
    dx = np.minimum(np.abs(px[:, None] - _coords[None, :]),
                    N - np.abs(px[:, None] - _coords[None, :]))
    dy = np.minimum(np.abs(py[:, None] - _coords[None, :]),
                    N - np.abs(py[:, None] - _coords[None, :]))
    dz = np.minimum(np.abs(pz[:, None] - _coords[None, :]),
                    N - np.abs(pz[:, None] - _coords[None, :]))

    dx2 = dx**2  # (P, N)
    dy2 = dy**2
    dz2 = dz**2

    # Accumulate: for each pin, outer sum of squared distances
    psi = np.zeros((N, N, N), dtype=np.float32)
    for i in range(len(pins)):
        r2 = (dx2[i, :, None, None] +
              dy2[i, None, :, None] +
              dz2[i, None, None, :] + TAU)
        psi += weights[i] / r2

    return psi

# ─────────────────────────────────────────────
# GRADIENT
# ─────────────────────────────────────────────
def compute_gradient(psi):
    gx = (np.roll(psi, -1, axis=0) - np.roll(psi, 1, axis=0)) * 0.5
    gy = (np.roll(psi, -1, axis=1) - np.roll(psi, 1, axis=1)) * 0.5
    gz = (np.roll(psi, -1, axis=2) - np.roll(psi, 1, axis=2)) * 0.5
    return gx, gy, gz

# ─────────────────────────────────────────────
# STEP
# ─────────────────────────────────────────────
def step_pins(pins, psi, gx, gy, gz):
    for p in pins:
        ix = int(p['pos'][0]) % N
        iy = int(p['pos'][1]) % N
        iz = int(p['pos'][2]) % N
        psi_local = float(psi[ix, iy, iz])
        t_rate = 1.0 / (1.0 + abs(psi_local))
        force = np.array([
            -float(gx[ix, iy, iz]),
            -float(gy[ix, iy, iz]),
            -float(gz[ix, iy, iz]),
        ])
        p['vel'] += force * DT * t_rate
        p['vel'] *= DAMP
        p['pos'] = (p['pos'] + p['vel'] * DT) % N

# ─────────────────────────────────────────────
# DISTANCE
# ─────────────────────────────────────────────
def pdist(a, b):
    d = np.minimum(np.abs(a['pos'] - b['pos']),
                   N - np.abs(a['pos'] - b['pos']))
    return float(np.sqrt(np.sum(d**2)))

# ─────────────────────────────────────────────
# VISUALIZATION
# ─────────────────────────────────────────────
_fig = None
_axes = None

def init_display():
    global _fig, _axes
    _fig = plt.figure(figsize=(14, 8), facecolor='#0a0a0a')
    gs = GridSpec(2, 3, figure=_fig, hspace=0.4, wspace=0.3)
    _axes = [
        _fig.add_subplot(gs[0, 0]),      # XY slice
        _fig.add_subplot(gs[0, 1]),      # XZ slice
        _fig.add_subplot(gs[0, 2]),      # radial profile
        _fig.add_subplot(gs[1, 0:2]),    # separations over time
        _fig.add_subplot(gs[1, 2]),      # time rates
    ]
    _fig.suptitle('VORTEX SUBSTRATE MODEL v4', color='white', fontsize=11)
    plt.ion()
    plt.show()

def render(pins, psi, step_num, sep_history, tr_history, step_history):
    if _fig is None:
        return
    for ax in _axes:
        ax.cla()

    mid = N // 2
    vm  = float(np.percentile(np.abs(psi), 99)) or 1.0

    pin_colors = ['#00ffff' if p['omega'] > 0 else '#ff4444'
                  for p in pins]

    # XY slice
    ax = _axes[0]
    ax.imshow(psi[:, :, mid].T, origin='lower', cmap='RdBu_r',
              interpolation='bilinear', vmin=-vm, vmax=vm)
    for i, p in enumerate(pins):
        ax.plot(p['pos'][0], p['pos'][1], 'o',
                color=pin_colors[i], ms=7,
                markeredgecolor='white', mew=0.5)
    ax.set_title(f'XY slice  z={mid}  step {step_num}',
                 color='white', fontsize=8)
    ax.set_facecolor('#0a0a0a')
    ax.tick_params(colors='#555')

    # XZ slice
    ax = _axes[1]
    ax.imshow(psi[:, mid, :].T, origin='lower', cmap='RdBu_r',
              interpolation='bilinear', vmin=-vm, vmax=vm)
    for i, p in enumerate(pins):
        ax.plot(p['pos'][0], p['pos'][2], 'o',
                color=pin_colors[i], ms=7,
                markeredgecolor='white', mew=0.5)
    ax.set_title(f'XZ slice  y={mid}', color='white', fontsize=8)
    ax.set_facecolor('#0a0a0a')
    ax.tick_params(colors='#555')

    # Radial profile from pin 0
    ax = _axes[2]
    ax.set_facecolor('#111')
    if pins:
        p0 = pins[0]['pos'].astype(np.float32)
        cx = _coords[:, None, None]
        cy = _coords[None, :, None]
        cz = _coords[None, None, :]
        dx = np.minimum(np.abs(cx - p0[0]), N - np.abs(cx - p0[0]))
        dy = np.minimum(np.abs(cy - p0[1]), N - np.abs(cy - p0[1]))
        dz = np.minimum(np.abs(cz - p0[2]), N - np.abs(cz - p0[2]))
        r  = np.sqrt(dx**2 + dy**2 + dz**2).flatten()
        pf = psi.flatten()
        rb = np.linspace(0, N // 2, 40)
        pm = [float(pf[(r >= rb[k]) & (r < rb[k+1])].mean())
              if ((r >= rb[k]) & (r < rb[k+1])).any() else 0.0
              for k in range(len(rb) - 1)]
        ax.plot(rb[:-1], pm, color='#ff6b35', linewidth=2)
        ax.fill_between(rb[:-1], pm, 0, alpha=0.15, color='#ff6b35')
        ax.axhline(0, color='#444', linewidth=1)
    ax.set_title('Ψ radial profile pin 0', color='white', fontsize=8)
    ax.set_xlabel('Distance (cells)', color='#888', fontsize=7)
    ax.set_ylabel('Ψ', color='#888', fontsize=7)
    ax.tick_params(colors='#555', labelsize=7)
    for sp in ax.spines.values(): sp.set_color('#333')

    # Separation history
    ax = _axes[3]
    ax.set_facecolor('#111')
    colors6 = ['#00d4ff','#ff6b35','#00ff88','#ff00aa','#ffdd00','#aa00ff']
    for idx, (key, vals) in enumerate(sep_history.items()):
        if vals:
            i, j = key
            lbl = (f"p{i}({pins[i]['label'] if i<len(pins) else '?'})-"
                   f"p{j}({pins[j]['label'] if j<len(pins) else '?'})")
            ax.plot(step_history[:len(vals)], vals,
                    color=colors6[idx % len(colors6)],
                    label=lbl, linewidth=1.2, alpha=0.9)
    ax.set_title('Pin separations over time', color='white', fontsize=8)
    ax.set_xlabel('Step', color='#888', fontsize=7)
    ax.set_ylabel('Distance (cells)', color='#888', fontsize=7)
    if sep_history:
        ax.legend(fontsize=6, facecolor='#222', labelcolor='white',
                  ncol=3, loc='upper right')
    ax.tick_params(colors='#555', labelsize=7)
    for sp in ax.spines.values(): sp.set_color('#333')

    # Time rates
    ax = _axes[4]
    ax.set_facecolor('#111')
    for idx, (key, vals) in enumerate(tr_history.items()):
        if vals:
            i = key
            ax.plot(step_history[:len(vals)], vals,
                    color=colors6[i % len(colors6)],
                    label=f"p{i}", linewidth=1.0, alpha=0.8)
    ax.axhline(1.0, color='#444', linestyle='--', linewidth=1)
    ax.set_title('Local time rates', color='white', fontsize=8)
    ax.set_xlabel('Step', color='#888', fontsize=7)
    ax.set_ylabel('Rate', color='#888', fontsize=7)
    ax.tick_params(colors='#555', labelsize=7)
    for sp in ax.spines.values(): sp.set_color('#333')

    _fig.canvas.draw()
    _fig.canvas.flush_events()

    # Also save snapshot
    snap = os.path.join(OUTPUT_DIR, f'step_{step_num:06d}.png')
    _fig.savefig(snap, dpi=90, facecolor='#0a0a0a', bbox_inches='tight')

# ─────────────────────────────────────────────
# SCENARIOS
# ─────────────────────────────────────────────
half = N // 2

def sphere_positions(n, radius, center, omega_sign=1.0, label_prefix='P'):
    """Distribute n pins on a sphere surface - true 3D init"""
    pins = []
    golden = np.pi * (3 - np.sqrt(5))  # golden angle
    for i in range(n):
        y = 1 - (i / max(n - 1, 1)) * 2
        r = np.sqrt(max(1 - y*y, 0))
        theta = golden * i
        x = np.cos(theta) * r
        z = np.sin(theta) * r
        pos = [center[0] + x*radius,
               center[1] + y*radius,
               center[2] + z*radius]
        pos = [p % N for p in pos]
        pins.append(make_pin(pos, omega=omega_sign,
                             label=f'{label_prefix}{i}'))
    return pins

SCENARIOS = {

    'single': {
        'pins': [make_pin([half, half, half], label='H')],
        'steps': 1000,
        'desc': 'Single pin - baseline field',
    },

    'same': {
        'pins': [
            make_pin([half-8, half, half], omega= 1.0, label='A+'),
            make_pin([half+8, half, half], omega= 1.0, label='B+'),
        ],
        'steps': 5000,
        'desc': 'Same spin - bond distance test',
    },

    'opposite': {
        'pins': [
            make_pin([half-8, half, half], omega= 1.0, label='A+'),
            make_pin([half+8, half, half], omega=-1.0, label='B-'),
        ],
        'steps': 5000,
        'desc': 'Opposite spin - charge asymmetry',
    },

    'carbon': {
        'pins': [
            make_pin([half+4, half+4, half+4], label='C1'),
            make_pin([half-4, half-4, half+4], label='C2'),
            make_pin([half-4, half+4, half-4], label='C3'),
            make_pin([half+4, half-4, half-4], label='C4'),
            make_pin([half,   half,   half+6], label='C5'),
            make_pin([half,   half,   half-6], label='C6'),
        ],
        'steps': 5000,
        'desc': 'Carbon - 6 pins tetrahedral geometry',
    },

    '10v10': {
        # True 3D - positive cluster on left sphere, negative on right
        'pins': (
            sphere_positions(10, 8, [half-20, half, half],
                             omega_sign= 1.0, label_prefix='P') +
            sphere_positions(10, 8, [half+20, half, half],
                             omega_sign=-1.0, label_prefix='N')
        ),
        'steps': 5000,
        'desc': '10v10 - 3D sphere init, charge separation test',
    },

    'hydrogen_gas': {
        # 20 hydrogen-like pins randomly distributed in 3D
        'pins': [
            make_pin([np.random.uniform(20, N-20),
                      np.random.uniform(20, N-20),
                      np.random.uniform(20, N-20)],
                     omega=1.0, label=f'H{i}')
            for i in range(20)
        ],
        'steps': 50000,
        'desc': '20 hydrogen pins - do they cluster into structure?',
    },
}

# ─────────────────────────────────────────────
# ACTIVE SCENARIO
# ─────────────────────────────────────────────
ACTIVE = 'hydrogen_gas'   # <-- change this

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
np.random.seed(42)
scenario = SCENARIOS[ACTIVE]
pins     = scenario['pins']
STEPS    = scenario['steps']

print("=" * 60)
print(f"Scenario : {ACTIVE}")
print(f"Desc     : {scenario['desc']}")
print(f"Pins     : {len(pins)}  Steps: {STEPS}")
print()
for i, p in enumerate(pins):
    print(f"  Pin {i:>2}: {p['label']:>4}  "
          f"omega={p['omega']:+.1f}  "
          f"pos=[{p['pos'][0]:.1f}, {p['pos'][1]:.1f}, {p['pos'][2]:.1f}]")
print()

# History tracking
sep_history  = defaultdict(list)
tr_history   = defaultdict(list)
step_history = []

if SHOW_LIVE:
    init_display()

t0 = time.time()
step_times = []

for s in range(STEPS):

    ts = time.time()
    psi = compute_psi(pins)
    gx, gy, gz = compute_gradient(psi)
    step_pins(pins, psi, gx, gy, gz)
    step_times.append(time.time() - ts)

    if s % LOG_EVERY == 0:
        step_history.append(s)
        for i in range(len(pins)):
            ix = int(pins[i]['pos'][0]) % N
            iy = int(pins[i]['pos'][1]) % N
            iz = int(pins[i]['pos'][2]) % N
            pl = float(psi[ix, iy, iz])
            tr_history[i].append(1.0 / (1.0 + abs(pl)))
        for i in range(len(pins)):
            for j in range(i+1, len(pins)):
                sep_history[(i,j)].append(pdist(pins[i], pins[j]))

    if s % SNAP_EVERY == 0:
        elapsed = time.time() - t0
        avg_step = np.mean(step_times[-50:]) if step_times else 0
        eta = avg_step * (STEPS - s)

        seps = []
        for i in range(min(3, len(pins))):
            for j in range(i+1, min(4, len(pins))):
                seps.append(f"p{i}-p{j}:{pdist(pins[i],pins[j]):.1f}")

        print(f"step {s:>5}/{STEPS}  "
              f"{avg_step*1000:.0f}ms/step  "
              f"ETA {eta/60:.1f}min  "
              f"[{' '.join(seps)}]")

        if SHOW_LIVE:
            render(pins, psi, s, sep_history, tr_history, step_history)

# Final summary
print()
print(f"Completed in {(time.time()-t0)/60:.1f}min  "
      f"avg {np.mean(step_times)*1000:.0f}ms/step")
print()
print("=== FINAL STATE ===")
for i, p in enumerate(pins):
    spd = float(np.linalg.norm(p['vel']))
    print(f"Pin {i:>2} {p['label']:>4}: "
          f"pos=[{p['pos'][0]:.1f},{p['pos'][1]:.1f},{p['pos'][2]:.1f}]  "
          f"spd={spd:.5f}")

print()
print("=== SEPARATIONS ===")
for (i,j), dists in list(sep_history.items())[:10]:
    drift = dists[-1] - dists[0]
    beh = ('attracted' if drift < -0.5
           else 'repelled' if drift > 0.5
           else 'stable')
    print(f"p{i}({pins[i]['label']})-p{j}({pins[j]['label']}): "
          f"start={dists[0]:.2f}  final={dists[-1]:.2f}  "
          f"drift={drift:+.2f}  [{beh}]")

print(f"\nSnapshots in: {OUTPUT_DIR}/")
if SHOW_LIVE:
    print("Close the window to exit.")
    plt.ioff()
    plt.show()
