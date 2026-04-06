# VORTEX SUBSTRATE MODEL v3 - ZoneAlarm safe
# No live animation. No dynamic allocation. Disk output only.
# Matplotlib Agg backend - no display driver interaction.

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os, time
from collections import defaultdict

N          = 64
TAU        = 1.0
DT         = 0.05
DAMP       = 0.99
SNAP_EVERY = 50
LOG_EVERY  = 10
OUTPUT_DIR = 'vsm_output'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Pre-allocated grids - created once, never reallocated
_coords = np.arange(N, dtype=float)
_CX, _CY, _CZ = np.meshgrid(_coords, _coords, _coords, indexing='ij')
_psi = np.zeros((N,N,N))
_gx  = np.zeros((N,N,N))
_gy  = np.zeros((N,N,N))
_gz  = np.zeros((N,N,N))

print(f"Grid: {N}^3  RAM: ~{N**3*8*4/1024/1024:.0f}MB  Output: {OUTPUT_DIR}/")

def make_pin(pos, rho=1.0, omega=1.0, label=''):
    return {'pos':np.array(pos,dtype=float),'rho':rho,
            'omega':omega,'vel':np.zeros(3),'label':label}

def compute_psi(pins, out):
    out[:] = 0.0
    for p in pins:
        px,py,pz = p['pos']
        dx = np.minimum(np.abs(_CX-px), N-np.abs(_CX-px))
        dy = np.minimum(np.abs(_CY-py), N-np.abs(_CY-py))
        dz = np.minimum(np.abs(_CZ-pz), N-np.abs(_CZ-pz))
        r2 = dx**2 + dy**2 + dz**2 + TAU
        out += (p['rho'] * p['omega']) / r2

def compute_grad(psi, gx, gy, gz):
    np.subtract(np.roll(psi,-1,0), np.roll(psi,1,0), out=gx); gx *= 0.5
    np.subtract(np.roll(psi,-1,1), np.roll(psi,1,1), out=gy); gy *= 0.5
    np.subtract(np.roll(psi,-1,2), np.roll(psi,1,2), out=gz); gz *= 0.5

def step_pins(pins, psi, gx, gy, gz):
    for p in pins:
        ix,iy,iz = int(p['pos'][0])%N, int(p['pos'][1])%N, int(p['pos'][2])%N
        tr = 1.0 / (1.0 + abs(float(psi[ix,iy,iz])))
        p['vel'] += np.array([-gx[ix,iy,iz],-gy[ix,iy,iz],-gz[ix,iy,iz]]) * DT * tr
        p['vel'] *= DAMP
        p['pos'] = (p['pos'] + p['vel']*DT) % N

def pdist(a, b):
    d = np.minimum(np.abs(a['pos']-b['pos']), N-np.abs(a['pos']-b['pos']))
    return float(np.sqrt(np.sum(d**2)))

def save_snap(pins, psi, s):
    fig, (ax1, ax2) = plt.subplots(1,2,figsize=(12,5),facecolor='#0a0a0a')
    mid = N//2
    vm = max(abs(psi.max()), abs(psi.min())) * 0.6 or 1.0
    im = ax1.imshow(psi[:,:,mid].T, origin='lower', cmap='RdBu_r',
                    interpolation='bilinear', vmin=-vm, vmax=vm)
    for p in pins:
        c = '#00ffff' if p['omega']>0 else '#ff4444'
        ax1.plot(p['pos'][0], p['pos'][1], 'o', color=c, ms=9,
                 markeredgecolor='white', mew=0.8)
        ax1.annotate(p['label'], p['pos'][:2], xytext=(4,4),
                     textcoords='offset points', color=c, fontsize=8)
    plt.colorbar(im, ax=ax1, fraction=0.046)
    ax1.set_title(f'Psi field  step {s}  cyan=+  red=-', color='white', fontsize=9)
    ax1.tick_params(colors='#666')

    ax2.set_facecolor('#111')
    p0 = pins[0]['pos']
    dx = np.minimum(np.abs(_CX-p0[0]), N-np.abs(_CX-p0[0]))
    dy = np.minimum(np.abs(_CY-p0[1]), N-np.abs(_CY-p0[1]))
    dz = np.minimum(np.abs(_CZ-p0[2]), N-np.abs(_CZ-p0[2]))
    r = np.sqrt(dx**2+dy**2+dz**2).flatten()
    pf = psi.flatten()
    rb = np.linspace(0, N//2, 35)
    pm = [float(pf[(r>=rb[k])&(r<rb[k+1])].mean()) if ((r>=rb[k])&(r<rb[k+1])).any() else 0
          for k in range(len(rb)-1)]
    ax2.plot(rb[:-1], pm, color='#ff6b35', linewidth=2)
    ax2.fill_between(rb[:-1], pm, 0, alpha=0.15, color='#ff6b35')
    ax2.axhline(0, color='#444', linewidth=1)
    for j,op in enumerate(pins[1:],1):
        d = pdist(pins[0], op)
        ax2.axvline(d, color='#00d4ff', linestyle='--', alpha=0.8)
        ax2.annotate(f'p{j} {d:.1f}c', (d, max(pm)*0.7 if pm else 0),
                     color='#00d4ff', fontsize=8)
    ax2.set_title('Psi radial from pin 0', color='white', fontsize=9)
    ax2.set_xlabel('Distance (cells)', color='#888')
    ax2.set_ylabel('Psi', color='#888')
    ax2.tick_params(colors='#666')
    for sp in ax2.spines.values(): sp.set_color('#333')

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, f'step_{s:05d}.png'),
                dpi=100, facecolor='#0a0a0a', bbox_inches='tight')
    plt.close(fig)

# Measurements
rec = defaultdict(list)
rec_steps = []

def record(s, pins, psi):
    rec_steps.append(s)
    rec['psi_max'].append(float(psi.max()))
    rec['psi_min'].append(float(psi.min()))
    rec['psi_mean'].append(float(psi.mean()))
    for i,p in enumerate(pins):
        ix,iy,iz = int(p['pos'][0])%N, int(p['pos'][1])%N, int(p['pos'][2])%N
        pl = float(psi[ix,iy,iz])
        rec[f'spd_{i}'].append(float(np.linalg.norm(p['vel'])))
        rec[f'tr_{i}'].append(1.0/(1.0+abs(pl)))
    for i in range(len(pins)):
        for j in range(i+1, len(pins)):
            rec[f'sep_{i}_{j}'].append(pdist(pins[i], pins[j]))

def save_mplot(pins):
    fig, axes = plt.subplots(2,2,figsize=(12,8),facecolor='#0a0a0a')
    fig.suptitle('VSM Measurements', color='white', fontsize=12)
    cols = ['#00d4ff','#ff6b35','#00ff88','#ff00aa','#ffdd00','#aa00ff']

    ax = axes[0,0]; ax.set_facecolor('#111')
    for i in range(len(pins)):
        for j in range(i+1,len(pins)):
            k = f'sep_{i}_{j}'
            ax.plot(rec_steps, rec[k],
                    color=cols[(i+j)%len(cols)],
                    label=f"p{i}({pins[i]['label']})-p{j}({pins[j]['label']})",
                    linewidth=1.5)
    ax.set_title('Separations', color='white')
    ax.set_xlabel('Step', color='#888'); ax.set_ylabel('Cells', color='#888')
    ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
    ax.tick_params(colors='#666')
    for sp in ax.spines.values(): sp.set_color('#333')

    ax = axes[0,1]; ax.set_facecolor('#111')
    for i,p in enumerate(pins):
        ax.plot(rec_steps, rec[f'spd_{i}'],
                color=cols[i%len(cols)], label=p['label'], linewidth=1.5)
    ax.set_title('Pin Speeds', color='white')
    ax.set_xlabel('Step', color='#888'); ax.set_ylabel('Speed', color='#888')
    ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
    ax.tick_params(colors='#666')
    for sp in ax.spines.values(): sp.set_color('#333')

    ax = axes[1,0]; ax.set_facecolor('#111')
    for i,p in enumerate(pins):
        ax.plot(rec_steps, rec[f'tr_{i}'],
                color=cols[i%len(cols)], label=p['label'], linewidth=1.5)
    ax.axhline(1.0, color='#444', linestyle='--', linewidth=1)
    ax.set_title('Local Time Rate', color='white')
    ax.set_xlabel('Step', color='#888'); ax.set_ylabel('Rate', color='#888')
    ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
    ax.tick_params(colors='#666')
    for sp in ax.spines.values(): sp.set_color('#333')

    ax = axes[1,1]; ax.set_facecolor('#111')
    ax.plot(rec_steps, rec['psi_max'],  color='#ff6b35', label='max',  linewidth=1.5)
    ax.plot(rec_steps, rec['psi_mean'], color='#00d4ff', label='mean', linewidth=1.5)
    ax.plot(rec_steps, rec['psi_min'],  color='#00ff88', label='min',  linewidth=1.5)
    ax.axhline(0, color='#444', linewidth=1)
    ax.set_title('Global Psi', color='white')
    ax.set_xlabel('Step', color='#888'); ax.set_ylabel('Psi', color='#888')
    ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
    ax.tick_params(colors='#666')
    for sp in ax.spines.values(): sp.set_color('#333')

    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, 'measurements.png')
    plt.savefig(out, dpi=120, facecolor='#0a0a0a', bbox_inches='tight')
    plt.close(fig)
    print(f"Saved: {out}")

# ── SCENARIOS ──────────────────────────────────────────────
half = N//2
SCENARIOS = {
    'single':   {'pins':[make_pin([half,half,half],label='H')], 'steps':1000},
    'same':     {'pins':[make_pin([half-8,half,half],omega= 1.0,label='A+'),
                         make_pin([half+8,half,half],omega= 1.0,label='B+')], 'steps':5000},
    'opposite': {'pins':[make_pin([half-8,half,half],omega= 1.0,label='A+'),
                         make_pin([half+8,half,half],omega=-1.0,label='B-')], 'steps':5000},
    'carbon':   {'pins':[make_pin([half+4,half+4,half+4],label='C1'),
                         make_pin([half-4,half-4,half+4],label='C2'),
                         make_pin([half-4,half+4,half-4],label='C3'),
                         make_pin([half+4,half-4,half-4],label='C4'),
                         make_pin([half,  half,  half+6],label='C5'),
                         make_pin([half,  half,  half-6],label='C6')], 'steps':5000},
    '10v10':    {'pins':(
                    [make_pin([half-18+(i%5)*6, half-5+(i//5)*10, half],
                              omega= 1.0,label=f'P{i}') for i in range(10)]+
                    [make_pin([half+ 2+(i%5)*6, half-5+(i//5)*10, half],
                              omega=-1.0,label=f'N{i}') for i in range(10)]),
                 'steps':3000},
}

ACTIVE = 'opposite'   # <-- change this

sc   = SCENARIOS[ACTIVE]
pins = sc['pins']
STEPS = sc['steps']

print(f"\nScenario: {ACTIVE}  Pins: {len(pins)}  Steps: {STEPS}")
for i,p in enumerate(pins):
    print(f"  Pin {i}: {p['label']:>4}  omega={p['omega']:+.1f}  pos={p['pos'].astype(int)}")
print("\nRunning - no display window - PNGs saved to disk\n")

t0 = time.time()
for s in range(STEPS):
    compute_psi(pins, _psi)
    compute_grad(_psi, _gx, _gy, _gz)
    step_pins(pins, _psi, _gx, _gy, _gz)
    if s % LOG_EVERY  == 0: record(s, pins, _psi)
    if s % SNAP_EVERY == 0:
        seps = [f"p{i}-p{j}:{pdist(pins[i],pins[j]):.1f}"
                for i in range(len(pins)) for j in range(i+1,len(pins))]
        eta = ((time.time()-t0)/(s+1))*(STEPS-s) if s>0 else 0
        print(f"step {s:>5}/{STEPS}  [{' '.join(seps)}]  ETA {eta:.0f}s")
        save_snap(pins, _psi, s)

print(f"\nDone in {time.time()-t0:.1f}s")
print("\n=== SUMMARY ===")
for i,p in enumerate(pins):
    print(f"Pin {i} '{p['label']}': pos={p['pos'].round(2)}  spd={np.linalg.norm(p['vel']):.6f}")
for i in range(len(pins)):
    for j in range(i+1,len(pins)):
        dists = rec[f'sep_{i}_{j}']
        drift = dists[-1]-dists[0]
        beh = 'attracted' if drift<-0.5 else 'repelled' if drift>0.5 else 'stable'
        print(f"Pin {i}-{j}: start={dists[0]:.2f} final={dists[-1]:.2f} drift={drift:+.2f} [{beh}]")

save_mplot(pins)
print(f"\nAll output in: {OUTPUT_DIR}/")
