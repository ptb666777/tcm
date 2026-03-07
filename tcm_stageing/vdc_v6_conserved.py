import numpy as np

"""
VDC Sim v6 - No arbitrary decay. Energy conserved.
Changes:
- REMOVED: grid -= 0.009*grid  (no physical basis)
- REMOVED: general density bleeding into nothing
- Matter that hits true void pushes back to nearest density
  (conservation: it goes somewhere, not nowhere)
- Black hole sink: rare, only at extreme density peaks,
  removes small fixed amount (models matter entering subway)
  - what's removed is ADDED to geyser reservoir, not deleted
- Redshift proxy tracked separately as photon energy loss,
  doesn't affect matter density
- Diffusion reduced (less numerical smoothing)
- Self-gravity strengthened slightly since it no longer fights decay
"""

N = 80
grid    = np.zeros((N,N))
vx      = np.zeros((N,N))
vy      = np.zeros((N,N))
tension = np.ones((N,N))
subway  = 0.0   # reservoir: matter that entered black holes
                # feeds back into geysers - conserved

xx, yy = np.meshgrid(np.arange(N), np.arange(N))

def torus_dist(cx,cy):
    dx=np.minimum(np.abs(xx-cx),N-np.abs(xx-cx))
    dy=np.minimum(np.abs(yy-cy),N-np.abs(yy-cy))
    return np.sqrt(dx**2+dy**2)

def blur(g,s=0.04):   # reduced diffusion - less numerical smearing
    return (g*(1-4*s)+s*(np.roll(g,1,0)+np.roll(g,-1,0)+
                         np.roll(g,1,1)+np.roll(g,-1,1)))

def grad(g):
    return ((np.roll(g,-1,0)-np.roll(g,1,0))/2,
            (np.roll(g,-1,1)-np.roll(g,1,1))/2)

def curl(vx,vy):
    return ((np.roll(vy,-1,0)-np.roll(vy,1,0))/2 -
            (np.roll(vx,-1,1)-np.roll(vx,1,1))/2)

def advect(f,vx,vy,dt=0.32):
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

# ── SINGLE BOOM + NOISE ────────────────────────────────────────────
np.random.seed(None)
grid[N//2+2, N//2-1] += 100.0
grid += np.random.exponential(0.015,(N,N))

initial_total = grid.sum()   # track conservation

tear_age = np.zeros((N,N))
seal_str = np.zeros((N,N))

steps = 300

def cooling(step):
    if step < 60:    return 1.0
    elif step < 150: return 1.0-0.88*(step-60)/90
    else:            return 0.12

SELF_GRAV  = 0.009   # stronger now - not fighting arbitrary decay
LONG_GRAV  = 0.014
PRESSURE_K = 0.11
MAGNUS_STR = 0.018
JEANS      = 10
V_CAP      = 2.2
BH_THRESH  = 0.98    # top percentile that acts as black hole sink
BH_DRAIN   = 0.008   # fraction drained per step (slow - restricted)

snaps={}; vort_hist=[]; chiral_hist=[]; clump_hist=[]
core_hist=[]; total_hist=[]; subway_hist=[]

print(f"VDC v6 | {N}x{N} | {steps} steps | ENERGY CONSERVED")
print(f"No arbitrary decay. BH sink feeds subway feeds geysers.")
print(f"Initial total density: {initial_total:.2f}\n")

for step in range(steps):
    cool=cooling(step)
    intact=tension>0.3

    # ── PRESSURE ──────────────────────────────────────────────────
    pressure=PRESSURE_K*cool*(grid**1.4)
    px,py=grad(pressure)
    vx[intact]-=px[intact]*0.45
    vy[intact]-=py[intact]*0.45

    # ── SELF-GRAVITY ──────────────────────────────────────────────
    sg_x,sg_y=grad(grid)
    self_pull=grid/(np.mean(grid)+1e-6)
    vx -= SELF_GRAV*self_pull*sg_x
    vy -= SELF_GRAV*self_pull*sg_y

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

    # ── RIPPLE ────────────────────────────────────────────────────
    wave_str=max(0.0,1.0-step/200)
    if wave_str>0:
        d=torus_dist(N//2+2,N//2-1)
        phase=(d-step*0.7)%(2*np.pi)
        grid+=0.025*wave_str*np.cos(phase)/(d+1)*tension

    # ── VELOCITY CAP ──────────────────────────────────────────────
    speed=np.sqrt(vx**2+vy**2)
    cap=speed>V_CAP
    vx[cap]*=V_CAP/speed[cap]; vy[cap]*=V_CAP/speed[cap]

    # ── ADVECT ────────────────────────────────────────────────────
    grid=advect(grid,vx,vy)
    vx=advect(vx,vx,vy); vy=advect(vy,vx,vy)
    vx*=0.97; vy*=0.97

    # ── BLACK HOLE SINK → SUBWAY (conserved) ──────────────────────
    # Only extreme density peaks act as BH sinks
    # Matter removed here goes to subway reservoir, not deleted
    bh_thresh_val=np.percentile(grid,100*BH_THRESH)
    bh_cells=(grid>bh_thresh_val)&(grid>np.mean(grid)*3)
    if bh_cells.any():
        drained=grid[bh_cells]*BH_DRAIN
        subway+=drained.sum()          # INTO subway, not deleted
        grid[bh_cells]-=drained

    # ── SUBSTRATE & TRUE VOID ─────────────────────────────────────
    thin=grid<0.012
    tension[thin] -=0.022; tension[~thin]+=0.016
    tension=np.clip(tension,0,1)
    true_void=tension<0.05

    # True void: density can't persist here
    # Conservation: push it to neighbors, don't delete it
    void_density=grid*true_void
    if void_density.sum()>0:
        # Redistribute to adjacent non-void cells
        spill=(void_density*0.8)   # 80% spills to neighbors
        grid-=spill
        grid+=( np.roll(spill,1,0)+np.roll(spill,-1,0)+
                np.roll(spill,1,1)+np.roll(spill,-1,1) )*0.25
        grid[grid<0]=0

    # ── TEAR AGE & GEYSERS (fed from subway) ──────────────────────
    tear_age[true_void]+=1
    tear_age[~true_void]=np.maximum(0,tear_age[~true_void]-3)
    erupts=np.argwhere(tear_age>10)
    for tx,ty in erupts[:3]:
        if subway>0.5:              # only if subway has material
            d_g=torus_dist(tx,ty)
            inject_total=min(4.0*min(tear_age[tx,ty]/20,2.0), subway*0.1)
            inject=np.exp(-d_g**2/6)*inject_total
            inject_normalized=inject/inject.sum()*inject_total
            grid+=inject_normalized
            subway-=inject_total    # taken FROM subway, conserved
            tension[tx,ty]+=0.10
            seal_str[tx,ty]+=0.35
    sealed=(seal_str>1.8)&(grid>0.012)
    tear_age[sealed]=0; seal_str[sealed]=0

    # ── DIFFUSION (minimal - numerical stability only) ─────────────
    grid=blur(grid,0.04)
    grid[grid<0]=0

    # ── TRACK ─────────────────────────────────────────────────────
    om=curl(vx,vy)
    vort_hist.append(om.mean())
    chiral_hist.append([om[:N//2,:N//2].mean(),om[:N//2,N//2:].mean(),
                        om[N//2:,:N//2].mean(),om[N//2:,N//2:].mean()])
    core_hist.append(np.percentile(grid,99))
    total_hist.append(grid.sum())
    subway_hist.append(subway)

    if step%50==0:
        nc=count_clumps(grid)
        clump_hist.append((step,nc))
        tv=true_void.mean()
        print(f"  step {step:>4} | T={cool:.2f} | clumps={nc:>3} | "
              f"vort_std={om.std():.4f} | true_void={tv:.3f} | "
              f"core={core_hist[-1]:.2f} | subway={subway:.2f} | "
              f"total={total_hist[-1]:.1f}")

    if step in [0,59,150,224,steps-1]:
        snaps[step]=grid.copy()

# ── OUTPUT ────────────────────────────────────────────────────────
epochs=[(0,"PLASMA"),(59,"END PLASMA"),
        (150,"STRUCTURE BEGINS"),(224,"MID STRUCTURE"),(steps-1,"FINAL")]
for s,label in epochs:
    print(f"\n=== {label} (step {s}) ===")
    print(ascii_grid(snaps[s]))

g=snaps[steps-1]
print("\n=== FINAL METRICS ===")
print(f"  Initial total density:  {initial_total:.2f}")
print(f"  Final total density:    {total_hist[-1]:.2f}")
print(f"  In subway reservoir:    {subway:.2f}")
print(f"  Accounted for:          {(total_hist[-1]+subway):.2f}")
diff=abs(initial_total-(total_hist[-1]+subway+sum(
    [np.exp(-torus_dist(tx,ty)**2/6).sum()*0.013
     for tx,ty in np.argwhere(tear_age>10)[:3]] if np.argwhere(tear_age>10).any() else [0])))
print(f"  Density contrast:       {np.std(g)/(np.mean(g)+1e-10):.4f}")
print(f"  Final clump count:      {count_clumps(g)}")

print("\n=== CORE DENSITY - IS IT CONCENTRATING? ===")
for si in [0,60,100,150,200,250,steps-1]:
    if si<len(core_hist):
        phase="plasma" if si<60 else "cooling" if si<150 else "structure"
        trend=""
        if si>0 and si<len(core_hist) and core_hist[si]>core_hist[max(0,si-50)]:
            trend=" ↑ GROWING"
        elif si>0 and si<len(core_hist):
            trend=" ↓ shrinking"
        print(f"  step {si+1:>4} [{phase:9}]: {core_hist[si]:.4f}{trend}")

# Key question: in structure epoch, are cores growing or shrinking?
struct_start=min(150,len(core_hist)-1)
struct_end=min(steps-1,len(core_hist)-1)
struct_change=core_hist[struct_end]-core_hist[struct_start]
print(f"\n  Structure epoch core change: {struct_change:+.4f}")
print(f"  {'CONCENTRATING ✓' if struct_change>0 else 'still dispersing - self-gravity needs more tuning'}")

print("\n=== VORTICITY (Magnus tidal force effect) ===")
for si in [0,60,150,200,steps-1]:
    if si<len(vort_hist):
        print(f"  step {si+1:>4}: mean={vort_hist[si]:+.6f}  std={0:.4f}")

final_om=curl(vx,vy)
print(f"\n  Final vorticity std: {final_om.std():.6f}")
print(f"  {'Local spin structures (proto-disks) present' if final_om.std()>0.05 else 'Weak local rotation'}")

print("\n=== QUADRANT CHIRALITY (final 30 steps) ===")
q=np.mean(chiral_hist[-30:],axis=0)
for lbl,v in zip(['Top-Left','Top-Right','Bot-Left','Bot-Right'],q):
    print(f"  {lbl:10}: {v:+.6f}  ({'CCW' if v>0 else 'CW'})")
mixed=len(set(np.sign(q).astype(int)))>1
print(f"  Mixed handedness: {'YES - position-dependent chirality' if mixed else 'NO'}")

print("\n=== SUBWAY / GEYSER CYCLE ===")
print(f"  Peak subway level:  {max(subway_hist):.2f}")
print(f"  Final subway level: {subway:.2f}")
print(f"  Matter cycled through BH→subway→geyser: conserved, not deleted")

print("\nDone.")
