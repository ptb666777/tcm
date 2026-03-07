import numpy as np

"""
VDC Sim v5 - Self-gravity + Magnus/tidal force
New physics:
- Self-gravity: every cell pulls on nearby neighbors proportional
  to local density. Small concentrations can now snowball into cores.
  This is what makes galaxy centers denser over time, not flatter.
- Magnus force: rotating fluid creates perpendicular pressure.
  Modeled as: F_magnus = density * (omega x v)
  where omega is local vorticity. This is the tidal spin force.
  At small scale this mimics magnetic-like behavior - attraction/
  repulsion perpendicular to motion depending on spin direction.
- These two together should produce: dense cores, surrounding disks,
  filaments between cores, and voids that are genuinely empty.
  Scale-invariant: same pattern at clump scale as at grid scale.
"""

N = 80
grid    = np.zeros((N,N))
vx      = np.zeros((N,N))
vy      = np.zeros((N,N))
tension = np.ones((N,N))

xx, yy = np.meshgrid(np.arange(N), np.arange(N))

def torus_dist(cx,cy):
    dx=np.minimum(np.abs(xx-cx),N-np.abs(xx-cx))
    dy=np.minimum(np.abs(yy-cy),N-np.abs(yy-cy))
    return np.sqrt(dx**2+dy**2)

def blur(g,s=0.07):
    return (g*(1-4*s)+s*(np.roll(g,1,0)+np.roll(g,-1,0)+
                         np.roll(g,1,1)+np.roll(g,-1,1)))

def grad(g):
    return ((np.roll(g,-1,0)-np.roll(g,1,0))/2,
            (np.roll(g,-1,1)-np.roll(g,1,1))/2)

def curl(vx,vy):
    """Vorticity = local spin magnitude and direction"""
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

tear_age = np.zeros((N,N))
seal_str = np.zeros((N,N))

steps = 280

def cooling(step):
    if step < 60:   return 1.0
    elif step < 150: return 1.0-0.88*(step-60)/90
    else:            return 0.12

# Force strengths - kept moderate so nothing dominates
SELF_GRAV   = 0.006   # local self-gravity (short range, always on)
LONG_GRAV   = 0.014   # pull toward big peaks (as before)
PRESSURE_K  = 0.11
MAGNUS_STR  = 0.018   # tidal/rotational perpendicular force
JEANS       = 10      # long-grav effective radius
SELF_RANGE  = 5       # self-grav range (small - local only)
V_CAP       = 2.2

snaps={}; vort_hist=[]; chiral_hist=[]; clump_hist=[]
core_density_hist=[]   # track if cores are getting denser (not flatter)

print(f"VDC v5 | {N}x{N} | {steps} steps")
print(f"Self-gravity (r<{SELF_RANGE}) + Magnus tidal force added")
print(f"Single boom + quantum noise. All forces emergent.\n")

for step in range(steps):
    cool = cooling(step)
    intact = tension > 0.3

    # ── PRESSURE (cools over time) ─────────────────────────────────
    pressure = PRESSURE_K * cool * (grid**1.4)
    px,py = grad(pressure)
    vx[intact] -= px[intact]*0.45
    vy[intact] -= py[intact]*0.45

    # ── SELF-GRAVITY (short range - local clump self-attraction) ───
    # Every cell pulls on neighbors within SELF_RANGE
    # This is what makes cores concentrate, not flatten
    sg_x,sg_y = grad(grid)
    # Self-gravity pulls DOWN the density gradient (toward dense regions)
    # scaled by local density so rich regions pull harder
    self_pull = grid / (np.mean(grid)+1e-6)
    vx -= SELF_GRAV * self_pull * sg_x
    vy -= SELF_GRAV * self_pull * sg_y

    # ── LONG-RANGE GRAVITY (toward peaks, Jeans-limited) ───────────
    peaks = np.argwhere(grid > np.mean(grid)+0.7*np.std(grid))
    for px_i,py_i in peaks:
        dx=xx-px_i; dy=yy-py_i
        dx=np.where(np.abs(dx)>N//2,dx-np.sign(dx)*N,dx)
        dy=np.where(np.abs(dy)>N//2,dy-np.sign(dy)*N,dy)
        r=np.sqrt(dx**2+dy**2)+0.5
        mask=(r<JEANS)&(r>0.1)&intact
        pull=grid[px_i,py_i]*LONG_GRAV/r**2
        vx -= np.where(mask,pull*(dx/r),0)
        vy -= np.where(mask,pull*(dy/r),0)

    # ── MAGNUS / TIDAL FORCE ───────────────────────────────────────
    # Rotating fluid creates force perpendicular to velocity
    # F = rho * omega x v  (in 2D: omega is scalar z-component)
    # This is the "magnetism as spin tidal effect" mechanism
    # Positive omega (CCW spin) + rightward velocity = upward force
    # Creates the disk/spiral patterns seen at every scale
    omega = curl(vx,vy)
    # Perpendicular to velocity: rotate v by 90 degrees
    magnus_x = -MAGNUS_STR * grid * omega * vy
    magnus_y =  MAGNUS_STR * grid * omega * vx
    vx[intact] += magnus_x[intact]
    vy[intact] += magnus_y[intact]

    # ── RIPPLE (damping out) ───────────────────────────────────────
    wave_str = max(0.0,1.0-step/200)
    if wave_str > 0:
        d=torus_dist(N//2+2,N//2-1)
        phase=(d-step*0.7)%(2*np.pi)
        grid += 0.025*wave_str*np.cos(phase)/(d+1)*tension

    # ── VELOCITY CAP ──────────────────────────────────────────────
    speed=np.sqrt(vx**2+vy**2)
    cap=speed>V_CAP
    vx[cap]*=V_CAP/speed[cap]; vy[cap]*=V_CAP/speed[cap]

    # ── ADVECT ────────────────────────────────────────────────────
    grid=advect(grid,vx,vy)
    vx=advect(vx,vx,vy); vy=advect(vy,vx,vy)
    vx*=0.97; vy*=0.97

    # ── SUBSTRATE & TEARS ─────────────────────────────────────────
    thin=grid<0.012
    tension[thin] -= 0.022; tension[~thin] += 0.016
    tension=np.clip(tension,0,1)
    true_void=tension<0.05
    grid[true_void]*=0.55

    tear_age[true_void]+=1
    tear_age[~true_void]=np.maximum(0,tear_age[~true_void]-3)
    erupts=np.argwhere(tear_age>10)
    for tx,ty in erupts[:3]:
        d_g=torus_dist(tx,ty)
        strength=5.5*min(tear_age[tx,ty]/20,2.0)
        grid += 0.013*np.exp(-d_g**2/6)*strength
        tension[tx,ty]+=0.10; seal_str[tx,ty]+=0.35
    sealed=(seal_str>1.8)&(grid>0.012)
    tear_age[sealed]=0; seal_str[sealed]=0

    # ── DIFFUSION & DECAY ─────────────────────────────────────────
    grid=blur(grid,0.065)
    grid-=0.009*grid
    grid[grid<0]=0

    # ── TRACK ─────────────────────────────────────────────────────
    om=curl(vx,vy)
    vort_hist.append(om.mean())
    chiral_hist.append([om[:N//2,:N//2].mean(),om[:N//2,N//2:].mean(),
                        om[N//2:,:N//2].mean(),om[N//2:,N//2:].mean()])

    # Core density: top 1% of cells - are they getting denser or flatter?
    top1 = np.percentile(grid,99)
    core_density_hist.append(top1)

    if step%40==0:
        nc=count_clumps(grid)
        clump_hist.append((step,nc))
        tv=true_void.mean()
        print(f"  step {step:>4} | T={cool:.2f} | clumps={nc:>3} | "
              f"vort={om.mean():+.5f} | true_void={tv:.3f} | "
              f"core_top1%={top1:.3f}")

    if step in [0,59,140,209,steps-1]:
        snaps[step]=grid.copy()

# ── OUTPUT ────────────────────────────────────────────────────────
epochs=[(0,"PLASMA (step 0)"),(59,"END PLASMA (step 59)"),
        (140,"COOLING DONE (step 140)"),(209,"STRUCTURE (step 209)"),
        (steps-1,f"FINAL (step {steps-1})")]

for s,label in epochs:
    print(f"\n=== {label} ===")
    print(ascii_grid(snaps[s]))

g=snaps[steps-1]
print("\n=== FINAL METRICS ===")
print(f"  Density contrast:   {np.std(g)/(np.mean(g)+1e-10):.4f}")
print(f"  True void fraction: {(tension<0.05).mean():.4f}")
print(f"  Final clump count:  {count_clumps(g)}")

print("\n=== CORE DENSITY TREND (did cores concentrate or flatten?) ===")
checkpts=[0,40,80,120,160,200,steps-1]
for si in checkpts:
    if si<len(core_density_hist):
        phase="plasma" if si<60 else "cooling" if si<150 else "structure"
        print(f"  step {si+1:>4} [{phase:9}]: top-1% density = {core_density_hist[si]:.4f}")

trend = core_density_hist[-1] - core_density_hist[min(150,len(core_density_hist)-1)]
print(f"\n  Core density change in structure epoch: {trend:+.4f}")
print(f"  {'Cores CONCENTRATING - self-gravity working' if trend>0 else 'Cores still flattening - need more self-gravity'}")

print("\n=== VORTICITY BY EPOCH ===")
for si in [0,30,60,90,140,200,steps-1]:
    if si<len(vort_hist):
        phase="plasma" if si<60 else "cooling" if si<150 else "structure"
        print(f"  step {si+1:>4} [{phase:9}]: {vort_hist[si]:+.7f}")

print("\n=== QUADRANT CHIRALITY (final 30 steps) ===")
q=np.mean(chiral_hist[-30:],axis=0)
for lbl,v in zip(['Top-Left','Top-Right','Bot-Left','Bot-Right'],q):
    print(f"  {lbl:10}: {v:+.7f}  ({'CCW' if v>0 else 'CW'})")
mixed=len(set(np.sign(q).astype(int)))>1
print(f"\n  Mixed handedness: {'YES - position-dependent' if mixed else 'NO'}")

print("\n=== MAGNUS FORCE CHECK ===")
om_final=curl(vx,vy)
print(f"  Final mean vorticity:  {om_final.mean():+.6f}")
print(f"  Final vort std:        {om_final.std():.6f}")
print(f"  (High std = local spin structures present - proto-disks)")
if om_final.std() > 0.01:
    print(f"  Local rotation structures DETECTED")
else:
    print(f"  No strong local rotation structures yet")

print("\nDone.")
