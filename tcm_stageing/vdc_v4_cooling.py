import numpy as np

"""
VDC Sim v4 - Cooling curve + Jeans instability tuning
Key changes:
- Pressure DROPS over time (cooling from plasma epoch)
  Early: pressure dominates = blob/plasma phase (correct)
  Mid:   pressure/gravity balance = fragmentation begins
  Late:  gravity dominates locally = web/filament structure
- Jeans length: gravity wins below ~8 cells, pressure wins above
  This is what produces BOTH clumps AND voids simultaneously
- Velocity cap to prevent numerical blowup
- Single boom + noise, everything else emergent
"""

N = 80
grid  = np.zeros((N, N))
vx    = np.zeros((N, N))
vy    = np.zeros((N, N))
tension = np.ones((N, N))

xx, yy = np.meshgrid(np.arange(N), np.arange(N))

def torus_dist(cx, cy):
    dx = np.minimum(np.abs(xx-cx), N-np.abs(xx-cx))
    dy = np.minimum(np.abs(yy-cy), N-np.abs(yy-cy))
    return np.sqrt(dx**2 + dy**2)

def blur(g, s=0.08):
    return (g*(1-4*s) + s*(np.roll(g,1,0)+np.roll(g,-1,0)+
                            np.roll(g,1,1)+np.roll(g,-1,1)))

def grad(g):
    return ((np.roll(g,-1,0)-np.roll(g,1,0))/2,
            (np.roll(g,-1,1)-np.roll(g,1,1))/2)

def vorticity(vx,vy):
    return ((np.roll(vy,-1,0)-np.roll(vy,1,0))/2 -
            (np.roll(vx,-1,1)-np.roll(vx,1,1))/2)

def advect(f, vx, vy, dt=0.35):
    sx = (np.arange(N)[:,None] - vx*dt) % N
    sy = (np.arange(N)[None,:] - vy*dt) % N
    ix=sx.astype(int); fx=sx-ix
    iy=sy.astype(int); fy=sy-iy
    return ((1-fx)*(1-fy)*f[ix%N,iy%N] + fx*(1-fy)*f[(ix+1)%N,iy%N] +
            (1-fx)*fy*f[ix%N,(iy+1)%N] + fx*fy*f[(ix+1)%N,(iy+1)%N])

def ascii_grid(g):
    chars = ' .:*#&@'
    gn = (g-g.min())/(g.max()-g.min()+1e-10)
    return '\n'.join(''.join(chars[min(int(v*(len(chars)-1)),len(chars)-1)]
                             for v in row) for row in gn)

def count_clumps(g):
    thresh = np.mean(g)+0.5*np.std(g)
    binary = g>thresh
    visited = np.zeros((N,N),dtype=bool)
    count = 0
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

# ── SINGLE BOOM + QUANTUM NOISE ────────────────────────────────────
np.random.seed(None)
grid[N//2+2, N//2-1] += 100.0
grid += np.random.exponential(0.015, (N,N))  # primordial noise

tear_age = np.zeros((N,N))
seal_str  = np.zeros((N,N))

steps = 240  # longer run = more time for structure to mature

# Cooling schedule:
# Steps 0-60:   hot plasma, pressure ~= gravity  (blob epoch)
# Steps 60-120: cooling, pressure falls           (fragmentation epoch)  
# Steps 120+:   cold, gravity dominates locally   (structure epoch)
def cooling(step):
    if step < 60:
        return 1.0                          # hot: full pressure
    elif step < 140:
        return 1.0 - 0.9*(step-60)/80      # cooling curve
    else:
        return 0.1                          # cold: residual pressure only

JEANS_SCALE  = 8     # cells - gravity wins inside this radius
GRAV_STR     = 0.014
PRESSURE_K   = 0.12  # base pressure (scaled by cooling)
V_CAP        = 2.5   # velocity cap - prevents blowup
TRUE_VOID    = 0.004
TEAR_THRESH  = 0.012

snaps={}; vort_hist=[]; chiral_hist=[]; clump_hist=[]; cool_hist=[]

print(f"VDC v4 | {N}x{N} | {steps} steps | single boom + noise")
print(f"Cooling: plasma(0-60) -> fragmentation(60-140) -> structure(140+)\n")

for step in range(steps):

    cool = cooling(step)
    cool_hist.append(cool)

    # ── PRESSURE (falls with cooling) ──────────────────────────────
    # Adiabatic-ish: P ~ rho^(5/3) * temperature
    pressure = PRESSURE_K * cool * (grid**1.4)
    px,py = grad(pressure)
    intact = tension > 0.3
    vx[intact] -= px[intact]*0.5
    vy[intact] -= py[intact]*0.5

    # ── RIPPLE (wave from boom, weakens over time) ──────────────────
    wave_str = max(0.0, 1.0 - step/180)  # waves damp out as energy spreads
    if wave_str > 0:
        d = torus_dist(N//2+2, N//2-1)
        phase = (d - step*0.7) % (2*np.pi)
        ripple = np.cos(phase)/(d+1) * tension
        grid += 0.03 * wave_str * ripple

    # ── GRAVITY (vectorized, Jeans-aware) ──────────────────────────
    # Only acts within Jeans scale - this is what makes CLUMPS not blobs
    peaks = np.argwhere(grid > np.mean(grid)+0.7*np.std(grid))
    for px_i,py_i in peaks:
        dx = xx-px_i; dy = yy-py_i
        dx = np.where(np.abs(dx)>N//2, dx-np.sign(dx)*N, dx)
        dy = np.where(np.abs(dy)>N//2, dy-np.sign(dy)*N, dy)
        r  = np.sqrt(dx**2+dy**2)+0.5
        # Jeans: gravity effective only within Jeans scale
        # Outside: pressure + expansion wins, creates voids
        jeans_mask = (r < JEANS_SCALE) & (r > 0.1) & intact
        pull = grid[px_i,py_i]*GRAV_STR/r**2
        vx -= np.where(jeans_mask, pull*(dx/r), 0)
        vy -= np.where(jeans_mask, pull*(dy/r), 0)

    # ── VELOCITY CAP ───────────────────────────────────────────────
    speed = np.sqrt(vx**2+vy**2)
    cap_mask = speed > V_CAP
    vx[cap_mask] *= V_CAP/speed[cap_mask]
    vy[cap_mask] *= V_CAP/speed[cap_mask]

    # ── ADVECT ─────────────────────────────────────────────────────
    grid = advect(grid, vx, vy)
    vx   = advect(vx,   vx, vy)
    vy   = advect(vy,   vx, vy)
    vx  *= 0.97; vy *= 0.97

    # ── SUBSTRATE TENSION ──────────────────────────────────────────
    thin = grid < TEAR_THRESH
    tension[thin]  -= 0.025
    tension[~thin] += 0.018
    tension = np.clip(tension,0,1)
    true_void = tension < 0.05
    grid[true_void] *= 0.6  # void can't hold density

    # ── TEAR AGE & GEYSERS ─────────────────────────────────────────
    tear_age[true_void]  += 1
    tear_age[~true_void]  = np.maximum(0, tear_age[~true_void]-3)
    erupts = np.argwhere(tear_age > 10)
    for tx,ty in erupts[:3]:
        d_g = torus_dist(tx,ty)
        strength = 6.0*min(tear_age[tx,ty]/20, 2.0)
        grid += 0.015*np.exp(-d_g**2/6)*strength
        tension[tx,ty] += 0.12
        seal_str[tx,ty] += 0.4
    sealed = (seal_str>1.8)&(grid>TEAR_THRESH)
    tear_age[sealed]=0; seal_str[sealed]=0

    # ── DIFFUSION + DECAY ──────────────────────────────────────────
    grid = blur(grid, 0.07)
    grid -= 0.010*grid
    grid[grid<0] = 0

    # ── TRACK ──────────────────────────────────────────────────────
    om = vorticity(vx,vy)
    vort_hist.append(om.mean())
    chiral_hist.append([om[:N//2,:N//2].mean(), om[:N//2,N//2:].mean(),
                        om[N//2:,:N//2].mean(), om[N//2:,N//2:].mean()])

    if step % 40 == 0:
        nc = count_clumps(grid)
        clump_hist.append((step,nc))
        tv = true_void.mean()
        print(f"  step {step:>4} | T={cool:.2f} | clumps={nc:>3} | "
              f"vort={om.mean():+.5f} | true_void={tv:.3f} | "
              f"mean_dens={grid.mean():.4f}")

    if step in [0,59,120,179,steps-1]:
        snaps[step] = grid.copy()

# ── OUTPUT ─────────────────────────────────────────────────────────
epochs = [(0,"PLASMA EPOCH (step 0)"),
          (59,"END OF PLASMA (step 59)"),
          (120,"FRAGMENTATION (step 120)"),
          (179,"STRUCTURE FORMING (step 179)"),
          (steps-1,f"FINAL (step {steps-1})")]

for s,label in epochs:
    print(f"\n=== {label} ===")
    print(ascii_grid(snaps[s]))

g = snaps[steps-1]
print("\n=== FINAL METRICS ===")
print(f"  Density contrast:   {np.std(g)/np.mean(g):.4f}")
print(f"  True void fraction: {(tension<0.05).mean():.4f}")
print(f"  Final clump count:  {count_clumps(g)}")

print("\n=== VORTICITY EMERGENCE ===")
checkpoints = [0,30,60,90,120,160,steps-1]
for si in checkpoints:
    if si < len(vort_hist):
        phase = "plasma" if si<60 else "cooling" if si<140 else "structure"
        print(f"  step {si+1:>4} [{phase:9}]: {vort_hist[si]:+.7f}")

net = vort_hist[-1]-vort_hist[0]
print(f"\n  Net spin: {net:+.7f}")

print("\n=== QUADRANT CHIRALITY - FINAL 30 STEPS ===")
q = np.mean(chiral_hist[-30:],axis=0)
labels = ['Top-Left','Top-Right','Bot-Left','Bot-Right']
for lbl,v in zip(labels,q):
    print(f"  {lbl:10}: {v:+.7f}  ({'CCW' if v>0 else 'CW'})")

mixed = len(set(np.sign(q).astype(int))) > 1
print(f"\n  Mixed handedness across quadrants: {'YES' if mixed else 'NO'}")
print(f"  {'Position-dependent chirality present' if mixed else 'Uniform rotation'}")

print("\n=== EPOCH SUMMARY ===")
for s,label in epochs:
    g_s = snaps[s]
    nc = count_clumps(g_s)
    contrast = np.std(g_s)/(np.mean(g_s)+1e-10)
    print(f"  {label[:30]:30} | clumps={nc:>3} | contrast={contrast:.3f}")

print("\nDone.")
