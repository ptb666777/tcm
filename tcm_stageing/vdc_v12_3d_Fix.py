# -*- coding: utf-8 -*-
"""
VDC Sim v12 3D - Config-driven, multiprocessed, fully documented
Reads all parameters from vdc_config.txt in the same folder.
Multiprocessing on gravity loop - leaves core 0 free for Windows.
Dynamic snap intervals from config.
VTK + PNG output for ParaView animation.
"""

import numpy as np
import os
import sys
import multiprocessing as mp
from functools import partial

# ------------------------------------------------------------------ #
# CONFIG LOADER
# ------------------------------------------------------------------ #
def load_config(path="vdc_config.txt"):
    cfg = {}
    if not os.path.exists(path):
        print(f"Config file not found: {path}")
        print("Run with default vdc_config.txt in the same folder.")
        sys.exit(1)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, _, val = line.partition('=')
            key = key.strip()
            val = val.split('#')[0].strip()
            cfg[key] = val
    return cfg

def cfg_int(cfg, key, default):
    return int(cfg.get(key, default))

def cfg_float(cfg, key, default):
    return float(cfg.get(key, default))

def cfg_str(cfg, key, default):
    return cfg.get(key, default)

# ------------------------------------------------------------------ #
# LOAD CONFIG
# ------------------------------------------------------------------ #
cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vdc_config.txt")
cfg = load_config(cfg_path)

N            = cfg_int(cfg,   'N',               64)
steps        = cfg_int(cfg,   'steps',           350)
OUTDIR       = cfg_str(cfg,   'output_dir',      'vdc_output')
SNAP_EVERY   = cfg_int(cfg,   'snap_every',      10)
CPU_CORES    = cfg_int(cfg,   'cpu_cores',       0)

WAVE_SPEED   = cfg_float(cfg, 'wave_speed',      0.45)
SURF_TENSION = cfg_float(cfg, 'surf_tension',    0.015)
SURF_LIMIT   = cfg_float(cfg, 'surf_limit',      8.0)
WAVE_COUPLE  = cfg_float(cfg, 'wave_couple',     0.008)

SELF_GRAV    = cfg_float(cfg, 'self_grav',       0.009)
LONG_GRAV    = cfg_float(cfg, 'long_grav',       0.013)
JEANS        = cfg_int(cfg,   'jeans_length',    10)

PRESSURE_K   = cfg_float(cfg, 'pressure_k',      0.10)
PLASMA_END   = cfg_int(cfg,   'plasma_end',      60)
COOLING_END  = cfg_int(cfg,   'cooling_end',     160)
COOL_FLOOR   = cfg_float(cfg, 'cool_floor',      0.10)

MAGNUS_STR   = cfg_float(cfg, 'magnus_str',      0.014)

BH_DRAIN     = cfg_float(cfg, 'bh_drain',        0.007)
BH_PCTILE    = cfg_float(cfg, 'bh_percentile',   99.2)

SUBWAY_SCALE = cfg_float(cfg, 'subway_scale',    0.0015)
SUBWAY_MAX   = cfg_float(cfg, 'subway_max_inject',8.0)
SUBWAY_PRESS = cfg_float(cfg, 'subway_press_coeff',0.00002)
TEAR_MAX     = cfg_float(cfg, 'tear_thresh_max', 0.05)

OUT_PCTILE   = cfg_float(cfg, 'outflow_percentile',0.98)
OUTFLOW_STR  = cfg_float(cfg, 'outflow_str',     0.012)

SEED         = cfg_int(cfg,   'random_seed',     42)
BOOM_OFF     = [int(x) for x in cfg_str(cfg,'boom_offset','2 1 1').split()]
BOOM_WAVE    = cfg_float(cfg, 'boom_wave',       60.0)
V_CAP        = cfg_float(cfg, 'v_cap',           2.0)

# Auto core count: 0 = all minus 1 (keeps core 0 free)
if CPU_CORES == 0:
    CPU_CORES = max(1, mp.cpu_count() - 1)

os.makedirs(OUTDIR, exist_ok=True)

print(f"VDC v12 3D | N={N} | steps={steps} | cores={CPU_CORES}")
print(f"Config: {cfg_path}")
print(f"Output: {OUTDIR}/ | snap every {SNAP_EVERY} steps")
print(f"Wave: speed={WAVE_SPEED} surf_tension={SURF_TENSION} limit={SURF_LIMIT}")
print(f"Grav: self={SELF_GRAV} long={LONG_GRAV} jeans={JEANS}")
print(f"BH: drain={BH_DRAIN} | Subway: scale={SUBWAY_SCALE} max={SUBWAY_MAX}")
print(f"Outflow: str={OUTFLOW_STR}\n")

# ------------------------------------------------------------------ #
# GRID SETUP
# ------------------------------------------------------------------ #
xx, yy, zz = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing='ij')

def torus_dist3(cx, cy, cz):
    dx=np.minimum(np.abs(xx-cx),N-np.abs(xx-cx))
    dy=np.minimum(np.abs(yy-cy),N-np.abs(yy-cy))
    dz=np.minimum(np.abs(zz-cz),N-np.abs(zz-cz))
    return np.sqrt(dx**2+dy**2+dz**2)

def laplacian3(g):
    return (np.roll(g,1,axis=0)+np.roll(g,-1,axis=0)+
            np.roll(g,1,axis=1)+np.roll(g,-1,axis=1)+
            np.roll(g,1,axis=2)+np.roll(g,-1,axis=2)-6*g)

def blur3(g,s=0.025):
    return (g*(1-6*s)+s*(np.roll(g,1,axis=0)+np.roll(g,-1,axis=0)+
                         np.roll(g,1,axis=1)+np.roll(g,-1,axis=1)+
                         np.roll(g,1,axis=2)+np.roll(g,-1,axis=2)))

def grad3(g):
    return ((np.roll(g,-1,axis=0)-np.roll(g,1,axis=0))/2,
            (np.roll(g,-1,axis=1)-np.roll(g,1,axis=1))/2,
            (np.roll(g,-1,axis=2)-np.roll(g,1,axis=2))/2)

def curl3(vx,vy,vz):
    wx=((np.roll(vz,-1,axis=1)-np.roll(vz,1,axis=1))/2-
        (np.roll(vy,-1,axis=2)-np.roll(vy,1,axis=2))/2)
    wy=((np.roll(vx,-1,axis=2)-np.roll(vx,1,axis=2))/2-
        (np.roll(vz,-1,axis=0)-np.roll(vz,1,axis=0))/2)
    wz=((np.roll(vy,-1,axis=0)-np.roll(vy,1,axis=0))/2-
        (np.roll(vx,-1,axis=1)-np.roll(vx,1,axis=1))/2)
    return wx,wy,wz

def advect3(f,vx,vy,vz,dt=0.28):
    sx=(np.arange(N)[:,None,None]-vx*dt)%N
    sy=(np.arange(N)[None,:,None]-vy*dt)%N
    sz=(np.arange(N)[None,None,:]-vz*dt)%N
    ix=sx.astype(int);fx=sx-ix
    iy=sy.astype(int);fy=sy-iy
    iz=sz.astype(int);fz=sz-iz
    return ((1-fx)*(1-fy)*(1-fz)*f[ix%N,iy%N,iz%N]+
            fx*(1-fy)*(1-fz)*f[(ix+1)%N,iy%N,iz%N]+
            (1-fx)*fy*(1-fz)*f[ix%N,(iy+1)%N,iz%N]+
            (1-fx)*(1-fy)*fz*f[ix%N,iy%N,(iz+1)%N]+
            fx*fy*(1-fz)*f[(ix+1)%N,(iy+1)%N,iz%N]+
            fx*(1-fy)*fz*f[(ix+1)%N,iy%N,(iz+1)%N]+
            (1-fx)*fy*fz*f[ix%N,(iy+1)%N,(iz+1)%N]+
            fx*fy*fz*f[(ix+1)%N,(iy+1)%N,(iz+1)%N])

def cooling(step):
    if step < PLASMA_END:   return 1.0
    elif step < COOLING_END: return 1.0-((1.0-COOL_FLOOR)*(step-PLASMA_END)/
                                          (COOLING_END-PLASMA_END))
    else:                    return COOL_FLOOR

# ------------------------------------------------------------------ #
# MULTIPROCESSED GRAVITY
# Splits peak list across cores. Each core handles a chunk of peaks.
# ------------------------------------------------------------------ #
def gravity_chunk(args):
    """Worker: compute velocity delta from a subset of peaks"""
    peaks_chunk, grid_flat, N, LONG_GRAV, JEANS = args
    grid = grid_flat.reshape((N,N,N))
    xx_l,yy_l,zz_l = np.meshgrid(np.arange(N),np.arange(N),np.arange(N),indexing='ij')
    dvx = np.zeros((N,N,N))
    dvy = np.zeros((N,N,N))
    dvz = np.zeros((N,N,N))
    for px_i,py_i,pz_i in peaks_chunk:
        dx=xx_l-px_i; dy=yy_l-py_i; dz=zz_l-pz_i
        dx=np.where(np.abs(dx)>N//2,dx-np.sign(dx)*N,dx)
        dy=np.where(np.abs(dy)>N//2,dy-np.sign(dy)*N,dy)
        dz=np.where(np.abs(dz)>N//2,dz-np.sign(dz)*N,dz)
        r=np.sqrt(dx**2+dy**2+dz**2)+0.5
        mask=(r<JEANS)&(r>0.1)
        pull=grid[px_i,py_i,pz_i]*LONG_GRAV/r**2
        dvx-=np.where(mask,pull*(dx/r),0)
        dvy-=np.where(mask,pull*(dy/r),0)
        dvz-=np.where(mask,pull*(dz/r),0)
    return dvx,dvy,dvz

def apply_long_grav_parallel(grid, vx, vy, vz, intact, pool):
    peaks=np.argwhere(grid>np.mean(grid)+0.7*np.std(grid))
    if len(peaks)>80:
        idx=np.random.choice(len(peaks),80,replace=False)
        peaks=peaks[idx]
    if len(peaks)==0:
        return vx,vy,vz
    # Split peaks across workers
    chunks=np.array_split(peaks, CPU_CORES)
    chunks=[c for c in chunks if len(c)>0]
    args=[(c.tolist(), grid.flatten(), N, LONG_GRAV, JEANS) for c in chunks]
    results=pool.map(gravity_chunk, args)
    for dvx,dvy,dvz in results:
        vx[intact]+=dvx[intact]
        vy[intact]+=dvy[intact]
        vz[intact]+=dvz[intact]
    return vx,vy,vz

# ------------------------------------------------------------------ #
# OUTPUT
# ------------------------------------------------------------------ #
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MPLOT=True
except ImportError:
    HAS_MPLOT=False

def save_slices(g, step, label=""):
    if not HAS_MPLOT: return
    total=g.sum()+1e-10
    cm=[int((g*xx).sum()/total)%N,
        int((g*yy).sum()/total)%N,
        int((g*zz).sum()/total)%N]
    fig,axes=plt.subplots(1,3,figsize=(15,5))
    fig.suptitle(f"VDC 3D v12 | step {step} {label}",fontsize=12)
    vmin,vmax=0,max(np.percentile(g,99),0.01)
    axes[0].imshow(g[:,:,cm[2]].T,origin='lower',cmap='inferno',vmin=vmin,vmax=vmax)
    axes[0].set_title(f"XY (z={cm[2]})");axes[0].set_xlabel("X");axes[0].set_ylabel("Y")
    axes[1].imshow(g[:,cm[1],:].T,origin='lower',cmap='inferno',vmin=vmin,vmax=vmax)
    axes[1].set_title(f"XZ (y={cm[1]})");axes[1].set_xlabel("X");axes[1].set_ylabel("Z")
    axes[2].imshow(g[cm[0],:,:].T,origin='lower',cmap='inferno',vmin=vmin,vmax=vmax)
    axes[2].set_title(f"YZ (x={cm[0]})");axes[2].set_xlabel("Y");axes[2].set_ylabel("Z")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTDIR,f"step_{step:04d}.png"),dpi=100,bbox_inches='tight')
    plt.close()

def save_vti(g, step):
    """
    VTK ImageData XML format (.vti) - verified correct for ParaView 6.x
    Dense blob in center of grid appears in center of ParaView view.
    x-fastest ordering matches ParaView ImageData convention.
    """
    fname=os.path.join(OUTDIR,f"step_{step:04d}.vti")
    flat=g.flatten(order='F')  # x-fastest for [x,y,z] indexed array
    with open(fname,'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="ImageData" version="0.1" byte_order="LittleEndian">\n')
        f.write(f'<ImageData WholeExtent="0 {N-1} 0 {N-1} 0 {N-1}" '
                f'Origin="0 0 0" Spacing="1 1 1">\n')
        f.write(f'<Piece Extent="0 {N-1} 0 {N-1} 0 {N-1}">\n')
        f.write('<PointData Scalars="density">\n')
        f.write('<DataArray type="Float32" Name="density" format="ascii">\n')
        for i in range(0,len(flat),6):
            f.write(' '.join(f'{v:.4f}' for v in flat[i:i+6])+'\n')
        f.write('</DataArray>\n</PointData>\n')
        f.write('</Piece>\n</ImageData>\n</VTKFile>\n')

# ------------------------------------------------------------------ #
# MAIN
# ------------------------------------------------------------------ #
if __name__ == '__main__':
    if SEED == 0:
        np.random.seed(None)
    else:
        np.random.seed(SEED)

    grid    = np.zeros((N,N,N))
    wave    = np.zeros((N,N,N))
    wave_v  = np.zeros((N,N,N))
    vx      = np.zeros((N,N,N))
    vy      = np.zeros((N,N,N))
    vz      = np.zeros((N,N,N))
    tension = np.ones((N,N,N))

    BOOM=(N//2+BOOM_OFF[0], N//2-BOOM_OFF[1], N//2+BOOM_OFF[2])
    grid[BOOM]+=6.0
    grid+=np.random.exponential(0.008,(N,N,N))

    d0=torus_dist3(*BOOM)
    wave   = BOOM_WAVE*np.exp(-d0**2/3)
    wave_v = -BOOM_WAVE*0.4*np.exp(-d0**2/3)

    subway=0.0
    tear_age=np.zeros((N,N,N))
    seal_str=np.zeros((N,N,N))

    core_hist=[]; matter_hist=[]; drain_hist=[]; geyser_hist=[]; subway_hist=[]

    snap_steps=set(range(0,steps,SNAP_EVERY))|{steps-1}

    # Log config used for this run
    log_path=os.path.join(OUTDIR,"run_config_log.txt")
    with open(log_path,'w') as lf:
        lf.write(f"VDC v12 run log\n")
        lf.write(f"N={N} steps={steps} cores={CPU_CORES} seed={SEED}\n")
        for k,v in cfg.items():
            lf.write(f"{k} = {v}\n")
    print(f"Config logged to {log_path}\n")

    with mp.Pool(processes=CPU_CORES) as pool:
        for step in range(steps):
            cool=cooling(step)
            intact=tension>0.3

            # WAVE
            wave_a=(WAVE_SPEED**2*laplacian3(wave)
                    -SURF_TENSION*wave*np.abs(wave)/SURF_LIMIT**2)
            wave_v+=wave_a
            wave+=wave_v
            wave=np.clip(wave,-SURF_LIMIT*3,SURF_LIMIT*3)

            wgx,wgy,wgz=grad3(wave)
            vx-=WAVE_COUPLE*wgx
            vy-=WAVE_COUPLE*wgy
            vz-=WAVE_COUPLE*wgz

            # PRESSURE
            pressure=PRESSURE_K*cool*(grid**1.4)
            pgx,pgy,pgz=grad3(pressure)
            vx[intact]-=pgx[intact]*0.40
            vy[intact]-=pgy[intact]*0.40
            vz[intact]-=pgz[intact]*0.40

            # PEAK OUTFLOW
            ot=np.percentile(grid,100*OUT_PCTILE)
            hot=grid>ot
            if hot.any():
                hgx,hgy,hgz=grad3(hot.astype(float))
                vx[intact]-=OUTFLOW_STR*hgx[intact]
                vy[intact]-=OUTFLOW_STR*hgy[intact]
                vz[intact]-=OUTFLOW_STR*hgz[intact]

            # SELF-GRAVITY
            sgx,sgy,sgz=grad3(grid)
            sp=grid/(np.mean(grid)+1e-6)
            vx-=SELF_GRAV*sp*sgx
            vy-=SELF_GRAV*sp*sgy
            vz-=SELF_GRAV*sp*sgz

            # LONG-RANGE GRAVITY (multiprocessed)
            vx,vy,vz=apply_long_grav_parallel(grid,vx,vy,vz,intact,pool)

            # MAGNUS
            wx,wy,wz=curl3(vx,vy,vz)
            vx[intact]+=(MAGNUS_STR*grid*(wy*vz-wz*vy))[intact]
            vy[intact]+=(MAGNUS_STR*grid*(wz*vx-wx*vz))[intact]
            vz[intact]+=(MAGNUS_STR*grid*(wx*vy-wy*vx))[intact]

            # VELOCITY CAP
            speed=np.sqrt(vx**2+vy**2+vz**2)
            cap=speed>V_CAP
            vx[cap]*=V_CAP/speed[cap]
            vy[cap]*=V_CAP/speed[cap]
            vz[cap]*=V_CAP/speed[cap]

            # ADVECT
            grid=advect3(grid,vx,vy,vz)
            vx=advect3(vx,vx,vy,vz)
            vy=advect3(vy,vx,vy,vz)
            vz=advect3(vz,vx,vy,vz)
            vx*=0.97;vy*=0.97;vz*=0.97

            # BLACK HOLE -> SUBWAY
            bh_val=np.percentile(grid,BH_PCTILE)
            bh_cells=(grid>bh_val)&(grid>np.mean(grid)*3)
            step_drain=0.0
            if bh_cells.any():
                drained=grid[bh_cells]*BH_DRAIN
                step_drain=drained.sum()
                subway+=step_drain
                grid[bh_cells]-=drained
            drain_hist.append(step_drain)

            # SUBSTRATE & VOID
            dyn_thresh=min(0.008+subway*SUBWAY_PRESS, TEAR_MAX)
            thin=grid<dyn_thresh
            tension[thin]-=0.018
            tension[~thin]+=0.014
            tension=np.clip(tension,0,1)
            true_void=tension<0.05

            void_d=grid*true_void
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

            # GEYSERS
            step_geyser=0.0
            erupts=np.argwhere(tear_age>12)[:3]
            for tx,ty,tz in erupts:
                if subway>0.5:
                    inject=min(subway*SUBWAY_SCALE,SUBWAY_MAX)
                    d_g=torus_dist3(tx,ty,tz)
                    kernel=np.exp(-d_g**2/6)
                    ks=kernel.sum()
                    if ks>0:
                        grid+=kernel/ks*inject
                        subway-=inject
                        step_geyser+=inject
                    seal_str[tx,ty,tz]+=0.35
            sealed=(seal_str>1.8)&(grid>dyn_thresh)
            tear_age[sealed]=0;seal_str[sealed]=0
            geyser_hist.append(step_geyser)
            subway_hist.append(subway)

            # DIFFUSION
            grid=blur3(grid,0.025)
            grid[grid<0]=0

            core_hist.append(np.percentile(grid,99))
            matter_hist.append(grid.sum())

            if step%30==0:
                tv=true_void.mean()
                dr=np.mean(drain_hist[-10:]) if len(drain_hist)>=10 else step_drain
                ge=np.mean(geyser_hist[-10:]) if len(geyser_hist)>=10 else step_geyser
                print(f"  step {step:>4} | T={cool:.2f} | matter={matter_hist[-1]:.0f} | "
                      f"core={core_hist[-1]:.3f} | void={tv:.3f} | "
                      f"BH={dr:.2f} | geyser={ge:.2f} | subway={subway:.0f}")

            if step in snap_steps:
                label=""
                if step<PLASMA_END:    label="(PLASMA)"
                elif step<COOLING_END: label="(COOLING)"
                else:                  label="(STRUCTURE)"
                save_slices(grid,step,label)
                save_vti(grid,step)

    # FINAL
    print("\n=== FINAL ===")
    g=grid
    total=g.sum()+1e-10
    cm=[int((g*xx).sum()/total)%N,
        int((g*yy).sum()/total)%N,
        int((g*zz).sum()/total)%N]
    print(f"  Center of mass: {cm}")
    print(f"  Core (top 1%):  {core_hist[-1]:.4f}")
    print(f"  Mean density:   {g.mean():.4f}")
    print(f"  Final matter:   {matter_hist[-1]:.1f}")
    print(f"  Final subway:   {subway:.1f}")
    sc=core_hist[-1]-core_hist[min(COOLING_END,len(core_hist)-1)]
    print(f"  Core change (structure epoch): {sc:+.4f}")
    print(f"  {'CONCENTRATING' if sc>0 else 'dispersing'}")

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

    print(f"\n  Output: {os.path.abspath(OUTDIR)}/")
    print(f"  Config logged: {log_path}")
    print(f"  ParaView: File -> Open -> step_XXXX.vti -> Apply Threshold filter (min 0.5)")
    print("\nDone.")
