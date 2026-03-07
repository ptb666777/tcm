import numpy as np

"""
VDC Sim v8 - Surface tension as restoring force
Key physics:
- Wave equation now includes nonlinear restoring term:
    F_restore = -k * wave * |wave|  (scales with amplitude squared)
  Small waves: barely restrained, propagate freely
  Large waves: snapped back hard toward equilibrium
  This is substrate surface tension - the medium resists extreme deformation
- Wave energy is now self-limiting: can't blow up because
  large amplitudes pull themselves back
- Single boom, one pulse, propagates and interferes with itself
  Structure forms at constructive interference nodes
- Torus noted as approximation (sphere would converge at antipode)
"""

N = 80
grid    = np.zeros((N,N))
wave    = np.zeros((N,N))
wave_v  = np.zeros((N,N))
vx      = np.zeros((N,N))
vy      = np.zeros((N,N))
tension = np.ones((N,N))

xx, yy = np.meshgrid(np.arange(N), np.arange(N))

def torus_dist(cx,cy):
    dx=np.minimum(np.abs(xx-cx),N-np.abs(xx-cx))
    dy=np.minimum(np.abs(yy-cy),N-np.abs(yy-cy))
    return np.sqrt(dx**2+dy**2)

def laplacian(g):
    return (np.roll(g,1,0)+np.roll(g,-1,0)+
            np.roll(g,1,1)+np.roll(g,-1,1)-4*g)

def blur(g,s=0.03):
    return (g*(1-4*s)+s*(np.roll(g,1,0)+np.roll(g,-1,0)+
                         np.roll(g,1,1)+np.roll(g,-1,1)))

def grad(g):
    return ((np.roll(g,-1,0)-np.roll(g,1,0))/2,
            (np.roll(g,-1,1)-np.roll(g,1,1))/2)

def curl(vx,vy):
    return ((np.roll(vy,-1,0)-np.roll(vy,1,0))/2 -
            (np.roll(vx,-1,1)-np.roll(vx,1,1))/2)

def advect(f,vx,vy,dt=0.30):
    sx=(np.arange(N)[:,None]-vx*dt)%N
    sy=(np.arange(N)[None,:]-vy*dt)%N
    ix=sx.astype(int);fx=sx-ix
    iy=sy.astype(int);fy=sy-iy
    return ((1-fx)*(1-fy)*f[ix%N,iy%N]+fx*(1-fy)*f[(ix+1)%N,iy%N]+
            (1-fx)*fy*f[ix%N,(iy+1)%N]+fx*fy*f[(ix+1)%N,(iy+1)%N])

def ascii_grid(g):
    chars=' .:*#&@'
    gn=(g-g.min())/(g.max()-g.min()+1e-10)
    return '\n'.join(''.join(chars[min(int(v*(len(chars)-1)),len(chars)-1)]
                             for v in row) for row in gn)

def count_clumps(g):
    thresh=np.mean(g)+0.5*np.std(g)
    binary=g>thresh
    visited=np.zeros((N,N),dtype=bool)
    count=0
    for i in range(N):
        for j in range(N):
            if binary[i,j] and not visited[i,j]:
                count+=1
                q=[(i,j)]
                while q:
                    ci,cj=q.pop()
                    if visited[ci,cj]: continue
                    visited[ci,cj]=True
                    for di,dj in[(-1,0),(1,0),(0,-1),(0,1)]:
                        ni,nj=(ci+di)%N,(cj+dj)%N
                        if binary[ni,nj] and not visited[ni,nj]:
                            q.append((ni,nj))
    return count

# ── INITIAL CONDITIONS ─────────────────────────────────────────────
np.random.seed(None)
BOOM_X, BOOM_Y = N//2+2, N//2-1

# Small matter seed - universe starts radiation dominated
grid[BOOM_X, BOOM_Y] += 6.0
grid += np.random.exponential(0.008,(N,N))

# Single boom wave pulse - ALL the wave energy released here
# Finite. This is it. No more added later except tiny geysers.
BOOM_WAVE = 60.0
d0 = torus_dist(BOOM_X, BOOM_Y)
wave   = BOOM_WAVE * np.exp(-d0**2/3)
wave_v = -BOOM_WAVE * 0.4 * np.exp(-d0**2/3)   # outward initial velocity

initial_wave_E = 0.5*(wave**2+wave_v**2).sum()
initial_matter = grid.sum()

subway   = 0.0
tear_age = np.zeros((N,N))
seal_str = np.zeros((N,N))

steps = 350

def cooling(step):
    if step < 60:    return 1.0
    elif step < 160: return 1.0 - 0.90*(step-60)/100
    else:            return 0.10

# Wave physics
WAVE_SPEED   = 0.45      # Courant stable (<0.5)
# Surface tension: restoring force proportional to wave^2
# Small waves feel almost nothing, large waves get snapped back
# This is the rubber-band effect you described
SURF_TENSION = 0.015     # strength of restoring force
SURF_LIMIT   = 8.0       # equilibrium amplitude - waves beyond this
                         # get pulled back proportionally harder

# Matter physics
WAVE_COUPLE  = 0.008     # wave gradient moves matter (velocity only)
SELF_GRAV    = 0.009
LONG_GRAV    = 0.013
PRESSURE_K   = 0.10
MAGNUS_STR   = 0.016
JEANS        = 10
V_CAP        = 2.0
BH_DRAIN     = 0.007

snaps={}; vort_hist=[]; chiral_hist=[]
core_hist=[]; wave_E_hist=[]; matter_hist=[]
clump_hist=[]

print(f"VDC v8 | {N}x{N} | {steps} steps")
print(f"Surface tension restoring force - self-limiting waves")
print(f"Initial wave energy: {initial_wave_E:.0f}")
print(f"Surface tension limit: ±{SURF_LIMIT} (rubber-band beyond this)\n")

for step in range(steps):
    cool=cooling(step)
    intact=tension>0.3

    # ── WAVE EQUATION WITH SURFACE TENSION ────────────────────────
    # Standard: d²w/dt² = c²∇²w
    # + Surface tension: -σ * w * |w| / SURF_LIMIT²
    #   This pulls large amplitudes back toward zero
    #   Scales with w² so small waves propagate freely
    #   Large waves get snapped back - the rubber band
    wave_a = (WAVE_SPEED**2 * laplacian(wave)
              - SURF_TENSION * wave * np.abs(wave) / SURF_LIMIT**2)

    wave_v += wave_a
    wave   += wave_v

    # Hard clip as safety - surface tension should prevent this
    # but numerical noise can still spike
    wave = np.clip(wave, -SURF_LIMIT*3, SURF_LIMIT*3)

    w_energy = 0.5*(wave**2+wave_v**2).sum()
    wave_E_hist.append(w_energy)

    # ── WAVE MOVES MATTER (velocity only, no density injection) ────
    wgx, wgy = grad(wave)
    vx -= WAVE_COUPLE * wgx
    vy -= WAVE_COUPLE * wgy

    # ── PRESSURE ──────────────────────────────────────────────────
    pressure=PRESSURE_K*cool*(grid**1.4)
    px,py=grad(pressure)
    vx[intact]-=px[intact]*0.40
    vy[intact]-=py[intact]*0.40

    # ── SELF-GRAVITY ──────────────────────────────────────────────
    sg_x,sg_y=grad(grid)
    self_pull=grid/(np.mean(grid)+1e-6)
    vx-=SELF_GRAV*self_pull*sg_x
    vy-=SELF_GRAV*self_pull*sg_y

    # ── LONG-RANGE GRAVITY ────────────────────────────────────────
    peaks=np.argwhere(grid>np.mean(grid)+0.7*np.std(grid))
    for px_i,py_i in peaks:
        dx=xx-px_i; dy=yy-py_i
        dx=np.where(np.abs(dx)>N//2,dx-np.sign(dx)*N,dx)
        dy=np.where(np.abs(dy)>N//2,dy-np.sign(dy)*N,dy)
        r=np.sqrt(dx**2+dy**2)+0.5
        mask=(r<JEANS)&(r>0.1)&intact
        pull=grid[px_i,py_i]*LONG_GRAV/r**2
        vx-=np.where(mask,pull*(dx/r),0)
        vy-=np.where(mask,pull*(dy/r),0)

    # ── MAGNUS / TIDAL FORCE ──────────────────────────────────────
    omega=curl(vx,vy)
    vx[intact]+=(-MAGNUS_STR*grid*omega*vy)[intact]
    vy[intact]+=(MAGNUS_STR*grid*omega*vx)[intact]

    # ── VELOCITY CAP ──────────────────────────────────────────────
    speed=np.sqrt(vx**2+vy**2)
    cap=speed>V_CAP
    vx[cap]*=V_CAP/speed[cap]; vy[cap]*=V_CAP/speed[cap]

    # ── ADVECT ────────────────────────────────────────────────────
    grid=advect(grid,vx,vy)
    vx=advect(vx,vx,vy); vy=advect(vy,vx,vy)
    vx*=0.97; vy*=0.97

    # ── BLACK HOLE → SUBWAY (conserved) ───────────────────────────
    bh_val=np.percentile(grid,99.2)
    bh_cells=(grid>bh_val)&(grid>np.mean(grid)*3)
    if bh_cells.any():
        drained=grid[bh_cells]*BH_DRAIN
        subway+=drained.sum()
        grid[bh_cells]-=drained

    # ── SUBSTRATE & TRUE VOID ─────────────────────────────────────
    thin=grid<0.008
    tension[thin] -=0.018; tension[~thin]+=0.014
    tension=np.clip(tension,0,1)
    true_void=tension<0.05

    void_d=grid*true_void
    if void_d.sum()>0:
        spill=void_d*0.8
        grid-=spill
        grid+=(np.roll(spill,1,0)+np.roll(spill,-1,0)+
               np.roll(spill,1,1)+np.roll(spill,-1,1))*0.25
        grid[grid<0]=0

    tear_age[true_void]+=1
    tear_age[~true_void]=np.maximum(0,tear_age[~true_void]-3)

    # ── GEYSERS (small pebbles - matter only, from subway) ────────
    erupts=np.argwhere(tear_age>12)[:2]
    for tx,ty in erupts:
        if subway>0.5:
            inject=min(subway*0.05, 2.5)   # small - pebble not meteor
            d_g=torus_dist(tx,ty)
            grid+=inject*np.exp(-d_g**2/6)
            subway-=inject
            seal_str[tx,ty]+=0.35
    sealed=(seal_str>1.8)&(grid>0.008)
    tear_age[sealed]=0; seal_str[sealed]=0

    # ── DIFFUSION (minimal numerical stability only) ───────────────
    grid=blur(grid,0.03)
    grid[grid<0]=0

    # ── TRACK ─────────────────────────────────────────────────────
    om=curl(vx,vy)
    vort_hist.append(om.mean())
    chiral_hist.append([om[:N//2,:N//2].mean(),om[:N//2,N//2:].mean(),
                        om[N//2:,:N//2].mean(),om[N//2:,N//2:].mean()])
    core_hist.append(np.percentile(grid,99))
    matter_hist.append(grid.sum())

    if step%50==0:
        nc=count_clumps(grid)
        clump_hist.append((step,nc))
        print(f"  step {step:>4} | T={cool:.2f} | clumps={nc:>3} | "
              f"wave_E={w_energy:.0f} | matter={matter_hist[-1]:.1f} | "
              f"core={core_hist[-1]:.3f} | vort_std={om.std():.4f} | "
              f"subway={subway:.1f}")

    if step in [0,40,100,180,260,steps-1]:
        snaps[step]=grid.copy()

# ── OUTPUT ────────────────────────────────────────────────────────
epoch_labels=[(0,"PLASMA"),(40,"EARLY WAVE"),(100,"WAVE REVERB"),
              (180,"COOLING"),(260,"STRUCTURE"),(steps-1,"FINAL")]
for s,label in epoch_labels:
    print(f"\n=== {label} (step {s}) ===")
    print(ascii_grid(snaps[s]))

g=snaps[steps-1]

print("\n=== WAVE ENERGY - IS SURFACE TENSION LIMITING IT? ===")
for si in [0,20,60,120,200,280,steps-1]:
    if si<len(wave_E_hist):
        ratio=wave_E_hist[si]/wave_E_hist[0] if wave_E_hist[0]>0 else 0
        trend="↑" if si>0 and wave_E_hist[si]>wave_E_hist[max(0,si-1)] else "↓"
        print(f"  step {si+1:>4}: {wave_E_hist[si]:>12.1f}  "
              f"({ratio:6.3f}x initial) {trend}")
peak_E=max(wave_E_hist)
final_E=wave_E_hist[-1]
print(f"\n  Peak wave energy: {peak_E:.1f}")
print(f"  Final wave energy: {final_E:.1f}")
print(f"  {'Self-limiting: final < 2x peak' if final_E < peak_E*2 else 'Still growing - surface tension needs tuning'}")

print("\n=== CORE DENSITY ===")
for si in [0,50,100,160,220,280,steps-1]:
    if si<len(core_hist):
        phase="plasma" if si<60 else "cooling" if si<160 else "structure"
        print(f"  step {si+1:>4} [{phase:9}]: {core_hist[si]:.4f}")
sc=core_hist[min(steps-1,len(core_hist)-1)]-core_hist[min(160,len(core_hist)-1)]
print(f"\n  Structure epoch core change: {sc:+.4f}")
print(f"  {'CONCENTRATING ✓' if sc>0 else 'dispersing'}")

print("\n=== WAVE INTERFERENCE STRUCTURE ===")
print(f"  Wave field std: {wave.std():.4f}")
print(f"  Wave field max: {wave.max():.4f}  (limit: {SURF_LIMIT*3:.1f})")
print(f"  Wave field min: {wave.min():.4f}")
if wave.max() < SURF_LIMIT*2:
    print(f"  Surface tension IS limiting amplitude ✓")
else:
    print(f"  Amplitude exceeded limit - surface tension needs strengthening")

print("\n=== QUADRANT CHIRALITY (final 30 steps) ===")
q=np.mean(chiral_hist[-30:],axis=0)
for lbl,v in zip(['Top-Left','Top-Right','Bot-Left','Bot-Right'],q):
    print(f"  {lbl:10}: {v:+.6f}  ({'CCW' if v>0 else 'CW'})")
mixed=len(set(np.sign(q).astype(int)))>1
print(f"  Mixed handedness: {'YES - position-dependent chirality' if mixed else 'NO'}")

final_om=curl(vx,vy)
print(f"  Vorticity std: {final_om.std():.6f}")

print(f"\n=== CONSERVATION (approximate) ===")
print(f"  Initial: matter={initial_matter:.1f}  wave={initial_wave_E:.1f}")
print(f"  Final:   matter={matter_hist[-1]:.1f}  wave={wave_E_hist[-1]:.1f}  subway={subway:.1f}")

print("\nDone.")
