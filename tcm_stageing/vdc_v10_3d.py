# -*- coding: utf-8 -*-
"""
VDC Sim v10 - 3D on torus
Upgrade from v9 (2D 80x80) to 3D (N x N x N torus)
All physics identical, just extended to three axes.
Outputs: density slice images (PNG) at each snapshot + metrics
Visualization: matplotlib cross-sections (XY, XZ, YZ planes through center)

Run: python vdc_v10_3d.py
Outputs saved to ./vdc_output/ folder
"""

import numpy as np
import os

# Optional matplotlib - graceful fallback if not available
try:
    import matplotlib
    matplotlib.use('Agg')  # non-interactive backend, works without display
    import matplotlib.pyplot as plt
    HAS_MPLOT = True
except ImportError:
    HAS_MPLOT = False
    print("matplotlib not found - metrics only, no images")

# ------------------------------------------------------------------ #
N     = 64     # grid size per axis  (64^3 = 262144 cells, manageable)
steps = 300    # steps to run
OUTDIR = "vdc_output"
os.makedirs(OUTDIR, exist_ok=True)

# 3D coordinate grids (used for torus distance)
xx, yy, zz = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing='ij')

# ------------------------------------------------------------------ #
def torus_dist3(cx, cy, cz):
    dx = np.minimum(np.abs(xx - cx), N - np.abs(xx - cx))
    dy = np.minimum(np.abs(yy - cy), N - np.abs(yy - cy))
    dz = np.minimum(np.abs(zz - cz), N - np.abs(zz - cz))
    return np.sqrt(dx**2 + dy**2 + dz**2)

def laplacian3(g):
    return (np.roll(g, 1, axis=0) + np.roll(g, -1, axis=0) +
            np.roll(g, 1, axis=1) + np.roll(g, -1, axis=1) +
            np.roll(g, 1, axis=2) + np.roll(g, -1, axis=2) - 6*g)

def blur3(g, s=0.025):
    return (g * (1 - 6*s) +
            s * (np.roll(g, 1, axis=0) + np.roll(g, -1, axis=0) +
                 np.roll(g, 1, axis=1) + np.roll(g, -1, axis=1) +
                 np.roll(g, 1, axis=2) + np.roll(g, -1, axis=2)))

def grad3(g):
    gx = (np.roll(g, -1, axis=0) - np.roll(g, 1, axis=0)) / 2.0
    gy = (np.roll(g, -1, axis=1) - np.roll(g, 1, axis=1)) / 2.0
    gz = (np.roll(g, -1, axis=2) - np.roll(g, 1, axis=2)) / 2.0
    return gx, gy, gz

def curl3(vx, vy, vz):
    """Returns (wx, wy, wz) vorticity vector field"""
    # omega = curl(v) = (dVz/dy - dVy/dz, dVx/dz - dVz/dx, dVy/dx - dVx/dy)
    wx = ((np.roll(vz,-1,axis=1)-np.roll(vz,1,axis=1))/2 -
          (np.roll(vy,-1,axis=2)-np.roll(vy,1,axis=2))/2)
    wy = ((np.roll(vx,-1,axis=2)-np.roll(vx,1,axis=2))/2 -
          (np.roll(vz,-1,axis=0)-np.roll(vz,1,axis=0))/2)
    wz = ((np.roll(vy,-1,axis=0)-np.roll(vy,1,axis=0))/2 -
          (np.roll(vx,-1,axis=1)-np.roll(vx,1,axis=1))/2)
    return wx, wy, wz

def advect3(f, vx, vy, vz, dt=0.28):
    sx = (np.arange(N)[:,None,None] - vx*dt) % N
    sy = (np.arange(N)[None,:,None] - vy*dt) % N
    sz = (np.arange(N)[None,None,:] - vz*dt) % N
    ix = sx.astype(int); fx = sx - ix
    iy = sy.astype(int); fy = sy - iy
    iz = sz.astype(int); fz = sz - iz
    # trilinear interpolation
    return (
        (1-fx)*(1-fy)*(1-fz)*f[ix%N, iy%N, iz%N] +
        fx    *(1-fy)*(1-fz)*f[(ix+1)%N, iy%N, iz%N] +
        (1-fx)*fy    *(1-fz)*f[ix%N, (iy+1)%N, iz%N] +
        (1-fx)*(1-fy)*fz    *f[ix%N, iy%N, (iz+1)%N] +
        fx    *fy    *(1-fz)*f[(ix+1)%N, (iy+1)%N, iz%N] +
        fx    *(1-fy)*fz    *f[(ix+1)%N, iy%N, (iz+1)%N] +
        (1-fx)*fy    *fz    *f[ix%N, (iy+1)%N, (iz+1)%N] +
        fx    *fy    *fz    *f[(ix+1)%N, (iy+1)%N, (iz+1)%N]
    )

def save_slices(g, step, label=""):
    """Save XY, XZ, YZ cross-sections through center of mass"""
    if not HAS_MPLOT:
        return
    total = g.sum() + 1e-10
    cm = [int((g * xx).sum()/total) % N,
          int((g * yy).sum()/total) % N,
          int((g * zz).sum()/total) % N]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(f"VDC 3D | step {step} {label}", fontsize=12)
    vmin, vmax = 0, np.percentile(g, 99)

    axes[0].imshow(g[:,:,cm[2]].T, origin='lower', cmap='inferno', vmin=vmin, vmax=vmax)
    axes[0].set_title(f"XY slice (z={cm[2]})")
    axes[0].set_xlabel("X"); axes[0].set_ylabel("Y")

    axes[1].imshow(g[:,cm[1],:].T, origin='lower', cmap='inferno', vmin=vmin, vmax=vmax)
    axes[1].set_title(f"XZ slice (y={cm[1]})")
    axes[1].set_xlabel("X"); axes[1].set_ylabel("Z")

    axes[2].imshow(g[cm[0],:,:].T, origin='lower', cmap='inferno', vmin=vmin, vmax=vmax)
    axes[2].set_title(f"YZ slice (x={cm[0]})")
    axes[2].set_xlabel("Y"); axes[2].set_ylabel("Z")

    plt.tight_layout()
    fname = os.path.join(OUTDIR, f"step_{step:04d}.png")
    plt.savefig(fname, dpi=100, bbox_inches='tight')
    plt.close()
    return fname

def count_clumps3(g):
    thresh = np.mean(g) + 0.5*np.std(g)
    binary = g > thresh
    visited = np.zeros((N,N,N), dtype=bool)
    count = 0
    pts = list(zip(*np.where(binary & ~visited)))
    for start in pts:
        if visited[start]: continue
        count += 1
        q = [start]
        while q:
            ci,cj,ck = q.pop()
            if visited[ci,cj,ck]: continue
            visited[ci,cj,ck] = True
            for di,dj,dk in [(-1,0,0),(1,0,0),(0,-1,0),(0,1,0),(0,0,-1),(0,0,1)]:
                ni,nj,nk = (ci+di)%N,(cj+dj)%N,(ck+dk)%N
                if binary[ni,nj,nk] and not visited[ni,nj,nk]:
                    q.append((ni,nj,nk))
    return count

# ------------------------------------------------------------------ #
print(f"VDC v10 3D | {N}^3 grid | {steps} steps")
print(f"Output images -> {OUTDIR}/")

np.random.seed(42)  # reproducible - change to None for random each run

# Initial conditions
grid    = np.zeros((N,N,N))
wave    = np.zeros((N,N,N))
wave_v  = np.zeros((N,N,N))
vx      = np.zeros((N,N,N))
vy      = np.zeros((N,N,N))
vz      = np.zeros((N,N,N))
tension = np.ones((N,N,N))

# Single boom - slightly off center (same as v9)
BOOM = (N//2+2, N//2-1, N//2+1)
grid[BOOM] += 6.0
grid += np.random.exponential(0.008, (N,N,N))

# Wave pulse - finite energy
BOOM_WAVE = 60.0
d0 = torus_dist3(*BOOM)
wave   = BOOM_WAVE * np.exp(-d0**2/3)
wave_v = -BOOM_WAVE * 0.4 * np.exp(-d0**2/3)

initial_matter = grid.sum()
initial_wave_E = 0.5*(wave**2 + wave_v**2).sum()

subway   = 0.0
tear_age = np.zeros((N,N,N))
seal_str = np.zeros((N,N,N))

# Physics constants (same as v9)
WAVE_SPEED   = 0.45
SURF_TENSION = 0.015
SURF_LIMIT   = 8.0
WAVE_COUPLE  = 0.008
SELF_GRAV    = 0.009
LONG_GRAV    = 0.013
PRESSURE_K   = 0.10
MAGNUS_STR   = 0.014   # slightly reduced in 3D (3 vorticity components)
JEANS        = 10
V_CAP        = 2.0
BH_DRAIN     = 0.007

def cooling(step):
    if step < 60:    return 1.0
    elif step < 160: return 1.0 - 0.90*(step-60)/100.0
    else:            return 0.10

# Tracking
core_hist    = []
matter_hist  = []
wave_E_hist  = []
subway_hist  = []
drain_hist   = []
geyser_hist  = []
vort_hist    = []

snap_steps = [0, 60, 160, 240, steps-1]

print(f"Initial matter: {initial_matter:.1f} | Wave energy: {initial_wave_E:.0f}\n")

for step in range(steps):
    cool = cooling(step)
    intact = tension > 0.3

    # -- WAVE WITH SURFACE TENSION --
    wave_a = (WAVE_SPEED**2 * laplacian3(wave)
              - SURF_TENSION * wave * np.abs(wave) / SURF_LIMIT**2)
    wave_v += wave_a
    wave   += wave_v
    wave    = np.clip(wave, -SURF_LIMIT*3, SURF_LIMIT*3)
    w_E = 0.5*(wave**2 + wave_v**2).sum()
    wave_E_hist.append(w_E)

    # -- WAVE MOVES MATTER --
    wgx, wgy, wgz = grad3(wave)
    vx -= WAVE_COUPLE * wgx
    vy -= WAVE_COUPLE * wgy
    vz -= WAVE_COUPLE * wgz

    # -- PRESSURE --
    pressure = PRESSURE_K * cool * (grid**1.4)
    pgx, pgy, pgz = grad3(pressure)
    vx[intact] -= pgx[intact]*0.40
    vy[intact] -= pgy[intact]*0.40
    vz[intact] -= pgz[intact]*0.40

    # -- SELF-GRAVITY --
    sgx, sgy, sgz = grad3(grid)
    sp = grid / (np.mean(grid) + 1e-6)
    vx -= SELF_GRAV * sp * sgx
    vy -= SELF_GRAV * sp * sgy
    vz -= SELF_GRAV * sp * sgz

    # -- LONG-RANGE GRAVITY (toward density peaks) --
    peaks = np.argwhere(grid > np.mean(grid) + 0.7*np.std(grid))
    # Subsample peaks in 3D or it's too slow
    if len(peaks) > 40:
        idx = np.random.choice(len(peaks), 40, replace=False)
        peaks = peaks[idx]
    for px_i, py_i, pz_i in peaks:
        dx = xx - px_i; dy = yy - py_i; dz = zz - pz_i
        dx = np.where(np.abs(dx)>N//2, dx-np.sign(dx)*N, dx)
        dy = np.where(np.abs(dy)>N//2, dy-np.sign(dy)*N, dy)
        dz = np.where(np.abs(dz)>N//2, dz-np.sign(dz)*N, dz)
        r = np.sqrt(dx**2 + dy**2 + dz**2) + 0.5
        mask = (r < JEANS) & (r > 0.1) & intact
        pull = grid[px_i, py_i, pz_i] * LONG_GRAV / r**2
        vx -= np.where(mask, pull*(dx/r), 0)
        vy -= np.where(mask, pull*(dy/r), 0)
        vz -= np.where(mask, pull*(dz/r), 0)

    # -- MAGNUS / TIDAL FORCE (3D: omega x v) --
    wx, wy, wz = curl3(vx, vy, vz)
    # F = rho * (omega x v)
    # omega x v = (wy*vz - wz*vy, wz*vx - wx*vz, wx*vy - wy*vx)
    vx[intact] += (MAGNUS_STR * grid * (wy*vz - wz*vy))[intact]
    vy[intact] += (MAGNUS_STR * grid * (wz*vx - wx*vz))[intact]
    vz[intact] += (MAGNUS_STR * grid * (wx*vy - wy*vx))[intact]

    # -- VELOCITY CAP --
    speed = np.sqrt(vx**2 + vy**2 + vz**2)
    cap = speed > V_CAP
    vx[cap] *= V_CAP/speed[cap]
    vy[cap] *= V_CAP/speed[cap]
    vz[cap] *= V_CAP/speed[cap]

    # -- ADVECT --
    grid = advect3(grid, vx, vy, vz)
    vx   = advect3(vx,   vx, vy, vz)
    vy   = advect3(vy,   vx, vy, vz)
    vz   = advect3(vz,   vx, vy, vz)
    vx  *= 0.97; vy *= 0.97; vz *= 0.97

    # -- BLACK HOLE -> SUBWAY --
    bh_val = np.percentile(grid, 99.2)
    bh_cells = (grid > bh_val) & (grid > np.mean(grid)*3)
    step_drain = 0.0
    if bh_cells.any():
        drained = grid[bh_cells] * BH_DRAIN
        step_drain = drained.sum()
        subway += step_drain
        grid[bh_cells] -= drained
    drain_hist.append(step_drain)

    # -- SUBSTRATE & TRUE VOID --
    thin = grid < 0.008
    tension[thin]  -= 0.018
    tension[~thin] += 0.014
    tension = np.clip(tension, 0, 1)
    true_void = tension < 0.05

    void_d = grid * true_void
    if void_d.sum() > 0:
        spill = void_d * 0.9
        grid -= spill
        pn = spill / 6.0
        grid += (np.roll(pn,1,axis=0)+np.roll(pn,-1,axis=0)+
                 np.roll(pn,1,axis=1)+np.roll(pn,-1,axis=1)+
                 np.roll(pn,1,axis=2)+np.roll(pn,-1,axis=2))
        lost = void_d * 0.1
        subway += lost.sum()
        grid -= lost
        grid[grid < 0] = 0

    tear_age[true_void]  += 1
    tear_age[~true_void]  = np.maximum(0, tear_age[~true_void]-3)

    # -- GEYSERS --
    step_geyser = 0.0
    erupts = np.argwhere(tear_age > 12)[:2]
    for tx,ty,tz in erupts:
        if subway > 0.5:
            inject = min(subway*0.04, 2.0)
            d_g = torus_dist3(tx, ty, tz)
            kernel = np.exp(-d_g**2/6)
            ks = kernel.sum()
            if ks > 0:
                grid += kernel / ks * inject
                subway -= inject
                step_geyser += inject
            seal_str[tx,ty,tz] += 0.35
    sealed = (seal_str > 1.8) & (grid > 0.008)
    tear_age[sealed] = 0; seal_str[sealed] = 0
    geyser_hist.append(step_geyser)
    subway_hist.append(subway)

    # -- DIFFUSION --
    grid = blur3(grid, 0.025)
    grid[grid < 0] = 0

    # -- TRACK --
    core_hist.append(np.percentile(grid, 99))
    matter_hist.append(grid.sum())
    wx2,wy2,wz2 = curl3(vx,vy,vz)
    omega_mag = np.sqrt(wx2**2 + wy2**2 + wz2**2)
    vort_hist.append(omega_mag.mean())

    if step % 30 == 0:
        nc = "?" # skip clump count in 3D (slow) except at snapshots
        tv = true_void.mean()
        dr = np.mean(drain_hist[-10:]) if len(drain_hist)>=10 else step_drain
        ge = np.mean(geyser_hist[-10:]) if len(geyser_hist)>=10 else step_geyser
        print(f"  step {step:>4} | T={cool:.2f} | matter={matter_hist[-1]:.1f} | "
              f"core={core_hist[-1]:.3f} | void={tv:.3f} | "
              f"BH={dr:.3f} | geyser={ge:.3f} | subway={subway:.1f} | "
              f"vort={vort_hist[-1]:.4f}")

    if step in snap_steps:
        label = ""
        if step < 60:   label = "(PLASMA)"
        elif step < 160: label = "(COOLING)"
        else:            label = "(STRUCTURE)"
        fname = save_slices(grid, step, label)
        if fname:
            print(f"    -> saved {fname}")

# ------------------------------------------------------------------ #
print("\n=== FINAL METRICS ===")
g = grid
total = g.sum() + 1e-10
cm = [int((g*xx).sum()/total)%N,
      int((g*yy).sum()/total)%N,
      int((g*zz).sum()/total)%N]

print(f"  Center of mass: {cm}")
print(f"  Core (top 1%):  {core_hist[-1]:.4f}")
print(f"  Core (top 5%):  {np.percentile(g,95):.4f}")
print(f"  Mean density:   {g.mean():.4f}")
print(f"  Final matter:   {matter_hist[-1]:.1f}")
print(f"  Final subway:   {subway:.1f}")
print(f"  Final wave E:   {wave_E_hist[-1]:.1f}")

sc = core_hist[-1] - core_hist[min(160, len(core_hist)-1)]
print(f"\n  Structure epoch core change: {sc:+.4f}")
print(f"  {'CONCENTRATING' if sc>0 else 'dispersing'}")

print("\n=== OCTANT CHIRALITY (3D version of quadrant check) ===")
wx_f,wy_f,wz_f = curl3(vx,vy,vz)
omega_z = wz_f  # z-component of vorticity (spin in XY plane)
h = N//2
labels = ['FTL','FTR','FBL','FBR','BTL','BTR','BBL','BBR']
regions = [
    omega_z[:h,:h,:h], omega_z[:h,h:,:h],
    omega_z[:h,:h,h:], omega_z[:h,h:,h:],
    omega_z[h:,:h,:h], omega_z[h:,h:,:h],
    omega_z[h:,:h,h:], omega_z[h:,h:,h:]
]
signs = []
for lbl, reg in zip(labels, regions):
    v = reg.mean()
    signs.append(np.sign(v))
    print(f"  {lbl}: {v:+.6f}  ({'CCW' if v>0 else 'CW'})")

mixed = len(set(signs)) > 1
print(f"\n  Mixed handedness: {'YES - emergent position-dependent chirality' if mixed else 'NO'}")

print("\n=== FLOW EQUILIBRIUM ===")
for si in [30, 100, 150, 200, 260, steps-1]:
    if si < len(drain_hist):
        d = np.mean(drain_hist[max(0,si-10):si+1])
        ge = np.mean(geyser_hist[max(0,si-10):si+1])
        net = ge - d
        eq = "~EQ" if abs(net) < 0.05*max(d,ge,0.001) else ("geyser>BH" if net>0 else "BH>geyser")
        print(f"  step {si:>4}: BH={d:.4f}  geyser={ge:.4f}  net={net:+.4f}  {eq}")

print(f"\nImages saved to: {os.path.abspath(OUTDIR)}/")
print("Done.")
