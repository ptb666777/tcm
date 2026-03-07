# -*- coding: utf-8 -*-
"""
VDC Sim v11 3D - Proper subway oscillation + peak outflow
New physics (all emergent, no hardcoded targets):

1. SCALED GEYSER INJECTION
   Geyser strength scales with subway pressure.
   More subway = bigger eruption.
   Creates relaxation oscillator: fill -> burst -> refill -> burst
   Same physics as real geysers, heartbeats, dripping faucets.
   Nobody tells it to oscillate - it emerges from the pressure coupling.

2. PEAK OUTFLOW (stellar wind proxy)
   Extreme density peaks generate outward pressure.
   Models: radiation pressure from hot dense matter pushing
   surrounding material outward into filaments.
   Creates halos and filaments around cores naturally.
   Not hardcoded - emerges wherever density exceeds threshold.

3. SUBWAY SURFACE TENSION COUPLING
   Tear threshold now depends on subway pressure.
   High subway pressure = easier to tear (more force pushing up).
   Low subway pressure = harder to tear (less force).
   Same surface tension that limits wave peaks also governs tears.
   This is the relationship you identified - one mechanism, two scales.

4. VTK EXPORT for ParaView
   Saves density field as .vts files ParaView can read directly.
"""

import numpy as np
import os
import struct

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MPLOT = True
except ImportError:
    HAS_MPLOT = False
    print("matplotlib not found - no PNG slices")

# ------------------------------------------------------------------ #
N      = 64
steps  = 350
OUTDIR = "vdc_output_v11"
os.makedirs(OUTDIR, exist_ok=True)

xx, yy, zz = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing='ij')

# ------------------------------------------------------------------ #
def torus_dist3(cx, cy, cz):
    dx = np.minimum(np.abs(xx-cx), N-np.abs(xx-cx))
    dy = np.minimum(np.abs(yy-cy), N-np.abs(yy-cy))
    dz = np.minimum(np.abs(zz-cz), N-np.abs(zz-cz))
    return np.sqrt(dx**2+dy**2+dz**2)

def laplacian3(g):
    return (np.roll(g,1,axis=0)+np.roll(g,-1,axis=0)+
            np.roll(g,1,axis=1)+np.roll(g,-1,axis=1)+
            np.roll(g,1,axis=2)+np.roll(g,-1,axis=2)-6*g)

def blur3(g, s=0.025):
    return (g*(1-6*s)+s*(np.roll(g,1,axis=0)+np.roll(g,-1,axis=0)+
                         np.roll(g,1,axis=1)+np.roll(g,-1,axis=1)+
                         np.roll(g,1,axis=2)+np.roll(g,-1,axis=2)))

def grad3(g):
    return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
            (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
            (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

def curl3(vx, vy, vz):
    wx = ((np.roll(vz,-1,axis=1)-np.roll(vz,1,axis=1))/2 -
          (np.roll(vy,-1,axis=2)-np.roll(vy,1,axis=2))/2)
    wy = ((np.roll(vx,-1,axis=2)-np.roll(vx,1,axis=2))/2 -
          (np.roll(vz,-1,axis=0)-np.roll(vz,1,axis=0))/2)
    wz = ((np.roll(vy,-1,axis=0)-np.roll(vy,1,axis=0))/2 -
          (np.roll(vx,-1,axis=1)-np.roll(vx,1,axis=1))/2)
    return wx, wy, wz

def advect3(f, vx, vy, vz, dt=0.28):
    sx = (np.arange(N)[:,None,None]-vx*dt)%N
    sy = (np.arange(N)[None,:,None]-vy*dt)%N
    sz = (np.arange(N)[None,None,:]-vz*dt)%N
    ix=sx.astype(int); fx=sx-ix
    iy=sy.astype(int); fy=sy-iy
    iz=sz.astype(int); fz=sz-iz
    return ((1-fx)*(1-fy)*(1-fz)*f[ix%N,iy%N,iz%N]+
            fx*(1-fy)*(1-fz)*f[(ix+1)%N,iy%N,iz%N]+
            (1-fx)*fy*(1-fz)*f[ix%N,(iy+1)%N,iz%N]+
            (1-fx)*(1-fy)*fz*f[ix%N,iy%N,(iz+1)%N]+
            fx*fy*(1-fz)*f[(ix+1)%N,(iy+1)%N,iz%N]+
            fx*(1-fy)*fz*f[(ix+1)%N,iy%N,(iz+1)%N]+
            (1-fx)*fy*fz*f[ix%N,(iy+1)%N,(iz+1)%N]+
            fx*fy*fz*f[(ix+1)%N,(iy+1)%N,(iz+1)%N])

def save_slices(g, step, label=""):
    if not HAS_MPLOT: return
    total = g.sum()+1e-10
    cm = [int((g*xx).sum()/total)%N,
          int((g*yy).sum()/total)%N,
          int((g*zz).sum()/total)%N]
    fig, axes = plt.subplots(1,3,figsize=(15,5))
    fig.suptitle(f"VDC 3D v11 | step {step} {label}", fontsize=12)
    vmin,vmax = 0, max(np.percentile(g,99), 0.01)
    axes[0].imshow(g[:,:,cm[2]].T, origin='lower', cmap='inferno', vmin=vmin, vmax=vmax)
    axes[0].set_title(f"XY (z={cm[2]})"); axes[0].set_xlabel("X"); axes[0].set_ylabel("Y")
    axes[1].imshow(g[:,cm[1],:].T, origin='lower', cmap='inferno', vmin=vmin, vmax=vmax)
    axes[1].set_title(f"XZ (y={cm[1]})"); axes[1].set_xlabel("X"); axes[1].set_ylabel("Z")
    axes[2].imshow(g[cm[0],:,:].T, origin='lower', cmap='inferno', vmin=vmin, vmax=vmax)
    axes[2].set_title(f"YZ (x={cm[0]})"); axes[2].set_xlabel("Y"); axes[2].set_ylabel("Z")
    plt.tight_layout()
    fname = os.path.join(OUTDIR, f"step_{step:04d}.png")
    plt.savefig(fname, dpi=100, bbox_inches='tight')
    plt.close()

def save_vtk(g, step):
    """
    Save density field as VTK structured points file.
    Open in ParaView: File -> Open -> step_XXXX.vtk
    Apply 'Volume' or 'Contour' filter to see 3D structure.
    """
    fname = os.path.join(OUTDIR, f"step_{step:04d}.vtk")
    with open(fname, 'w') as f:
        f.write("# vtk DataFile Version 3.0\n")
        f.write(f"VDC density step {step}\n")
        f.write("ASCII\n")
        f.write("DATASET STRUCTURED_POINTS\n")
        f.write(f"DIMENSIONS {N} {N} {N}\n")
        f.write("ORIGIN 0 0 0\n")
        f.write("SPACING 1 1 1\n")
        f.write(f"POINT_DATA {N*N*N}\n")
        f.write("SCALARS density float 1\n")
        f.write("LOOKUP_TABLE default\n")
        # VTK expects Z-major order (x fastest)
        flat = g.flatten(order='F')
        for i in range(0, len(flat), 6):
            f.write(' '.join(f'{v:.4f}' for v in flat[i:i+6]) + '\n')

# ------------------------------------------------------------------ #
print(f"VDC v11 3D | {N}^3 | {steps} steps")
print(f"Subway oscillation + peak outflow + VTK export")
print(f"Output -> {OUTDIR}/\n")

np.random.seed(42)

grid    = np.zeros((N,N,N))
wave    = np.zeros((N,N,N))
wave_v  = np.zeros((N,N,N))
vx      = np.zeros((N,N,N))
vy      = np.zeros((N,N,N))
vz      = np.zeros((N,N,N))
tension = np.ones((N,N,N))

BOOM = (N//2+2, N//2-1, N//2+1)
grid[BOOM] += 6.0
grid += np.random.exponential(0.008,(N,N,N))

BOOM_WAVE = 60.0
d0 = torus_dist3(*BOOM)
wave   = BOOM_WAVE * np.exp(-d0**2/3)
wave_v = -BOOM_WAVE * 0.4 * np.exp(-d0**2/3)

initial_matter = grid.sum()
subway = 0.0
tear_age = np.zeros((N,N,N))
seal_str = np.zeros((N,N,N))

# Physics
WAVE_SPEED    = 0.45
SURF_TENSION  = 0.015
SURF_LIMIT    = 8.0
WAVE_COUPLE   = 0.008
SELF_GRAV     = 0.009
LONG_GRAV     = 0.013
PRESSURE_K    = 0.10
MAGNUS_STR    = 0.014
JEANS         = 10
V_CAP         = 2.0
BH_DRAIN      = 0.007

# NEW: Peak outflow (radiation/stellar wind pressure)
OUTFLOW_THRESH = 0.98   # percentile above which peaks push outward
OUTFLOW_STR    = 0.012  # outflow velocity strength
                        # small - creates halos, doesn't blow cores apart

# NEW: Subway oscillation parameters
# Geyser inject scales with subway level
# Tear threshold drops when subway is pressurized
SUBWAY_SCALE   = 0.0015  # inject = subway * this (not fixed cap)
SUBWAY_MAX_INJ = 8.0     # hard ceiling per geyser per step
TEAR_BASE      = 0.008   # base thin-density threshold
SUBWAY_PRESS   = 0.00002 # how much subway pressure lowers tear threshold
                         # high subway = easier to tear = more geysers = pressure release

core_hist=[]; matter_hist=[]; wave_E_hist=[]
subway_hist=[]; drain_hist=[]; geyser_hist=[]
vort_hist=[]; outflow_hist=[]

def cooling(step):
    if step < 60:    return 1.0
    elif step < 160: return 1.0-0.90*(step-60)/100.0
    else:            return 0.10

snap_steps = [0, 60, 160, 240, 310, steps-1]

for step in range(steps):
    cool = cooling(step)
    intact = tension > 0.3

    # -- WAVE WITH SURFACE TENSION --
    wave_a = (WAVE_SPEED**2*laplacian3(wave)
              - SURF_TENSION*wave*np.abs(wave)/SURF_LIMIT**2)
    wave_v += wave_a
    wave   += wave_v
    wave    = np.clip(wave, -SURF_LIMIT*3, SURF_LIMIT*3)
    wave_E_hist.append(0.5*(wave**2+wave_v**2).sum())

    # -- WAVE MOVES MATTER --
    wgx,wgy,wgz = grad3(wave)
    vx -= WAVE_COUPLE*wgx
    vy -= WAVE_COUPLE*wgy
    vz -= WAVE_COUPLE*wgz

    # -- PRESSURE --
    pressure = PRESSURE_K*cool*(grid**1.4)
    pgx,pgy,pgz = grad3(pressure)
    vx[intact] -= pgx[intact]*0.40
    vy[intact] -= pgy[intact]*0.40
    vz[intact] -= pgz[intact]*0.40

    # -- PEAK OUTFLOW (radiation/wind pressure from hot dense cores) --
    # Extreme density peaks push surrounding matter outward.
    # This emerges wherever density is extreme - not pre-targeted.
    # Creates halos, clears cores slightly, feeds filaments.
    outflow_thresh_val = np.percentile(grid, 100*OUTFLOW_THRESH)
    hot_cores = grid > outflow_thresh_val
    step_outflow = hot_cores.sum()
    if hot_cores.any():
        # Outward push: gradient points toward peaks, we push away
        # Use local gradient of the hot_core mask
        hcf = hot_cores.astype(float)
        hgx,hgy,hgz = grad3(hcf)
        # Push away from hot regions (negative of gradient toward them)
        vx[intact] -= OUTFLOW_STR * hgx[intact]
        vy[intact] -= OUTFLOW_STR * hgy[intact]
        vz[intact] -= OUTFLOW_STR * hgz[intact]
    outflow_hist.append(step_outflow)

    # -- SELF-GRAVITY --
    sgx,sgy,sgz = grad3(grid)
    sp = grid/(np.mean(grid)+1e-6)
    vx -= SELF_GRAV*sp*sgx
    vy -= SELF_GRAV*sp*sgy
    vz -= SELF_GRAV*sp*sgz

    # -- LONG-RANGE GRAVITY --
    peaks = np.argwhere(grid > np.mean(grid)+0.7*np.std(grid))
    if len(peaks) > 40:
        idx = np.random.choice(len(peaks), 40, replace=False)
        peaks = peaks[idx]
    for px_i,py_i,pz_i in peaks:
        dx=xx-px_i; dy=yy-py_i; dz=zz-pz_i
        dx=np.where(np.abs(dx)>N//2,dx-np.sign(dx)*N,dx)
        dy=np.where(np.abs(dy)>N//2,dy-np.sign(dy)*N,dy)
        dz=np.where(np.abs(dz)>N//2,dz-np.sign(dz)*N,dz)
        r=np.sqrt(dx**2+dy**2+dz**2)+0.5
        mask=(r<JEANS)&(r>0.1)&intact
        pull=grid[px_i,py_i,pz_i]*LONG_GRAV/r**2
        vx-=np.where(mask,pull*(dx/r),0)
        vy-=np.where(mask,pull*(dy/r),0)
        vz-=np.where(mask,pull*(dz/r),0)

    # -- MAGNUS / TIDAL --
    wx,wy,wz = curl3(vx,vy,vz)
    vx[intact]+=(MAGNUS_STR*grid*(wy*vz-wz*vy))[intact]
    vy[intact]+=(MAGNUS_STR*grid*(wz*vx-wx*vz))[intact]
    vz[intact]+=(MAGNUS_STR*grid*(wx*vy-wy*vx))[intact]

    # -- VELOCITY CAP --
    speed=np.sqrt(vx**2+vy**2+vz**2)
    cap=speed>V_CAP
    vx[cap]*=V_CAP/speed[cap]
    vy[cap]*=V_CAP/speed[cap]
    vz[cap]*=V_CAP/speed[cap]

    # -- ADVECT --
    grid=advect3(grid,vx,vy,vz)
    vx=advect3(vx,vx,vy,vz)
    vy=advect3(vy,vx,vy,vz)
    vz=advect3(vz,vx,vy,vz)
    vx*=0.97; vy*=0.97; vz*=0.97

    # -- BLACK HOLE -> SUBWAY --
    bh_val=np.percentile(grid,99.2)
    bh_cells=(grid>bh_val)&(grid>np.mean(grid)*3)
    step_drain=0.0
    if bh_cells.any():
        drained=grid[bh_cells]*BH_DRAIN
        step_drain=drained.sum()
        subway+=step_drain
        grid[bh_cells]-=drained
    drain_hist.append(step_drain)

    # -- SUBSTRATE & TRUE VOID --
    # Tear threshold drops when subway is pressurized
    # High subway pressure pushes up from below, thins the surface faster
    # Same surface tension governing wave peaks also governs tears
    dynamic_tear_thresh = TEAR_BASE + subway * SUBWAY_PRESS
    dynamic_tear_thresh = min(dynamic_tear_thresh, 0.05)  # cap at 5x base

    thin = grid < dynamic_tear_thresh
    tension[thin]  -= 0.018
    tension[~thin] += 0.014
    tension = np.clip(tension, 0, 1)
    true_void = tension < 0.05

    void_d = grid*true_void
    if void_d.sum()>0:
        spill=void_d*0.9
        grid-=spill
        pn=spill/6.0
        grid+=(np.roll(pn,1,axis=0)+np.roll(pn,-1,axis=0)+
               np.roll(pn,1,axis=1)+np.roll(pn,-1,axis=1)+
               np.roll(pn,1,axis=2)+np.roll(pn,-1,axis=2))
        lost=void_d*0.1
        subway+=lost.sum()
        grid-=lost
        grid[grid<0]=0

    tear_age[true_void]+=1
    tear_age[~true_void]=np.maximum(0,tear_age[~true_void]-3)

    # -- GEYSERS (pressure-scaled injection = relaxation oscillator) --
    # inject scales with subway level - more pressure = bigger burst
    # This creates the oscillation you described:
    # subway fills -> tears form more easily -> big geyser -> subway drops
    # -> tears harder to form -> BH fills subway again -> repeat
    step_geyser=0.0
    erupts=np.argwhere(tear_age>12)[:3]  # up to 3 simultaneous geysers
    for tx,ty,tz in erupts:
        if subway>0.5:
            # Inject scales with subway pressure - not a fixed cap
            inject=min(subway*SUBWAY_SCALE, SUBWAY_MAX_INJ)
            d_g=torus_dist3(tx,ty,tz)
            kernel=np.exp(-d_g**2/6)
            ks=kernel.sum()
            if ks>0:
                grid+=kernel/ks*inject
                subway-=inject
                step_geyser+=inject
            seal_str[tx,ty,tz]+=0.35
    sealed=(seal_str>1.8)&(grid>dynamic_tear_thresh)
    tear_age[sealed]=0; seal_str[sealed]=0
    geyser_hist.append(step_geyser)
    subway_hist.append(subway)

    # -- DIFFUSION --
    grid=blur3(grid,0.025)
    grid[grid<0]=0

    # -- TRACK --
    core_hist.append(np.percentile(grid,99))
    matter_hist.append(grid.sum())
    wx2,wy2,wz2=curl3(vx,vy,vz)
    vort_hist.append(np.sqrt(wx2**2+wy2**2+wz2**2).mean())

    if step%30==0:
        tv=true_void.mean()
        dr=np.mean(drain_hist[-10:]) if len(drain_hist)>=10 else step_drain
        ge=np.mean(geyser_hist[-10:]) if len(geyser_hist)>=10 else step_geyser
        sub_press=subway*SUBWAY_PRESS
        print(f"  step {step:>4} | T={cool:.2f} | matter={matter_hist[-1]:.0f} | "
              f"core={core_hist[-1]:.3f} | void={tv:.3f} | "
              f"BH={dr:.2f} | geyser={ge:.2f} | subway={subway:.0f} | "
              f"sub_press={sub_press:.4f} | vort={vort_hist[-1]:.5f}")

    if step in snap_steps:
        label=""
        if step<60:    label="(PLASMA)"
        elif step<160: label="(COOLING)"
        else:          label="(STRUCTURE)"
        save_slices(grid, step, label)
        save_vtk(grid, step)
        print(f"    -> saved step {step} PNG + VTK")

# ------------------------------------------------------------------ #
print("\n=== FINAL METRICS ===")
g=grid
total=g.sum()+1e-10
cm=[int((g*xx).sum()/total)%N,
    int((g*yy).sum()/total)%N,
    int((g*zz).sum()/total)%N]
print(f"  Center of mass:  {cm}")
print(f"  Core (top 1%):   {core_hist[-1]:.4f}")
print(f"  Mean density:    {g.mean():.4f}")
print(f"  Final matter:    {matter_hist[-1]:.1f}")
print(f"  Final subway:    {subway:.1f}")

sc=core_hist[-1]-core_hist[min(160,len(core_hist)-1)]
print(f"\n  Structure epoch core change: {sc:+.4f}")
print(f"  {'CONCENTRATING' if sc>0 else 'dispersing'}")

print("\n=== SUBWAY OSCILLATION CHECK ===")
print("  (looking for fill->burst->fill cycles)")
for si in [30,60,100,150,200,250,300,steps-1]:
    if si<len(subway_hist):
        dr=np.mean(drain_hist[max(0,si-5):si+1])
        ge=np.mean(geyser_hist[max(0,si-5):si+1])
        net=ge-dr
        st=subway_hist[si]
        dyn_t=min(TEAR_BASE+st*SUBWAY_PRESS,0.05)
        print(f"  step {si:>4}: subway={st:>8.1f} | "
              f"BH={dr:.3f} | geyser={ge:.3f} | net={net:+.3f} | "
              f"tear_thresh={dyn_t:.4f}")

print("\n=== OCTANT CHIRALITY ===")
wx_f,wy_f,wz_f=curl3(vx,vy,vz)
omega_z=wz_f
h=N//2
labels=['FTL','FTR','FBL','FBR','BTL','BTR','BBL','BBR']
regions=[omega_z[:h,:h,:h],omega_z[:h,h:,:h],
         omega_z[:h,:h,h:],omega_z[:h,h:,h:],
         omega_z[h:,:h,:h],omega_z[h:,h:,:h],
         omega_z[h:,:h,h:],omega_z[h:,h:,h:]]
signs=[]
for lbl,reg in zip(labels,regions):
    v=reg.mean()
    signs.append(int(np.sign(v)))
    print(f"  {lbl}: {v:+.7f}  ({'CCW' if v>0 else 'CW '})")
mixed=len(set(signs))>1
print(f"  Mixed handedness: {'YES' if mixed else 'NO'}")

print(f"\n  VTK files in {os.path.abspath(OUTDIR)}/")
print("  Open in ParaView: File -> Open -> step_XXXX.vtk")
print("  Apply 'Volume' filter for 3D density rendering")
print("\nDone.")
