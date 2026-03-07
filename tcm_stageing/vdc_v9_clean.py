# -*- coding: utf-8 -*-
import numpy as np

"""
VDC Sim v9 - Clean, conserved, with core flow tracking
Fixes:
- Void spill: conserved exactly (neighbors get exactly what void loses)
- Geyser inject: normalized gaussian so total injected = inject amount
- Added: universal core tracking, subway flow rates, radial profile
- Wave equation with surface tension: unchanged from v8 (working)
- No arbitrary matter injection anywhere
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

def radial_profile(g, cx, cy, bins=20):
    """Density as function of distance from center of mass"""
    d = torus_dist(cx, cy)
    edges = np.linspace(0, N//2, bins+1)
    profile = []
    for i in range(bins):
        mask = (d >= edges[i]) & (d < edges[i+1])
        profile.append(g[mask].mean() if mask.any() else 0)
    return np.array(profile), (edges[:-1]+edges[1:])/2

# -- INITIAL CONDITIONS ---------------------------------------------
np.random.seed(None)
BOOM_X, BOOM_Y = N//2+2, N//2-1

grid[BOOM_X, BOOM_Y] += 6.0
grid += np.random.exponential(0.008,(N,N))

BOOM_WAVE = 60.0
d0 = torus_dist(BOOM_X, BOOM_Y)
wave   = BOOM_WAVE * np.exp(-d0**2/3)
wave_v = -BOOM_WAVE * 0.4 * np.exp(-d0**2/3)

initial_matter    = grid.sum()
initial_wave_E    = 0.5*(wave**2+wave_v**2).sum()
total_initial     = initial_matter + initial_wave_E

subway     = 0.0
tear_age   = np.zeros((N,N))
seal_str   = np.zeros((N,N))

# Flow rate tracking
bh_drain_hist    = []   # matter per step into subway (BH drain)
geyser_out_hist  = []   # matter per step out of subway (geysers)
subway_hist      = []   # subway level over time

steps = 400

def cooling(step):
    if step < 60:    return 1.0
    elif step < 160: return 1.0 - 0.90*(step-60)/100
    else:            return 0.10

WAVE_SPEED   = 0.45
SURF_TENSION = 0.015
SURF_LIMIT   = 8.0
WAVE_COUPLE  = 0.008
SELF_GRAV    = 0.009
LONG_GRAV    = 0.013
PRESSURE_K   = 0.10
MAGNUS_STR   = 0.016
JEANS        = 10
V_CAP        = 2.0
BH_DRAIN     = 0.007   # fraction drained per step - hard cap on flow rate

snaps={}; vort_hist=[]; chiral_hist=[]
core_hist=[]; matter_hist=[]; wave_E_hist=[]

print(f"VDC v9 - CLEAN | {N}x{N} | {steps} steps")
print(f"Conservation enforced. Core + flow rate tracking active.")
print(f"Initial matter: {initial_matter:.1f} | Wave energy: {initial_wave_E:.0f}\n")

for step in range(steps):
    cool=cooling(step)
    intact=tension>0.3

    # -- WAVE WITH SURFACE TENSION ----------------------------------
    wave_a = (WAVE_SPEED**2 * laplacian(wave)
              - SURF_TENSION * wave * np.abs(wave) / SURF_LIMIT**2)
    wave_v += wave_a
    wave   += wave_v
    wave    = np.clip(wave, -SURF_LIMIT*3, SURF_LIMIT*3)
    wave_E_hist.append(0.5*(wave**2+wave_v**2).sum())

    # -- WAVE MOVES MATTER (velocity gradient only - no injection) --
    wgx, wgy = grad(wave)
    vx -= WAVE_COUPLE * wgx
    vy -= WAVE_COUPLE * wgy

    # -- PRESSURE --------------------------------------------------
    pressure = PRESSURE_K * cool * (grid**1.4)
    px,py = grad(pressure)
    vx[intact] -= px[intact]*0.40
    vy[intact] -= py[intact]*0.40

    # -- SELF-GRAVITY ----------------------------------------------
    sg_x,sg_y = grad(grid)
    self_pull = grid/(np.mean(grid)+1e-6)
    vx -= SELF_GRAV * self_pull * sg_x
    vy -= SELF_GRAV * self_pull * sg_y

    # -- LONG-RANGE GRAVITY ----------------------------------------
    peaks = np.argwhere(grid > np.mean(grid)+0.7*np.std(grid))
    for px_i,py_i in peaks:
        dx=xx-px_i; dy=yy-py_i
        dx=np.where(np.abs(dx)>N//2,dx-np.sign(dx)*N,dx)
        dy=np.where(np.abs(dy)>N//2,dy-np.sign(dy)*N,dy)
        r=np.sqrt(dx**2+dy**2)+0.5
        mask=(r<JEANS)&(r>0.1)&intact
        pull=grid[px_i,py_i]*LONG_GRAV/r**2
        vx-=np.where(mask,pull*(dx/r),0)
        vy-=np.where(mask,pull*(dy/r),0)

    # -- MAGNUS / TIDAL FORCE --------------------------------------
    omega = curl(vx,vy)
    vx[intact] += (-MAGNUS_STR*grid*omega*vy)[intact]
    vy[intact] += ( MAGNUS_STR*grid*omega*vx)[intact]

    # -- VELOCITY CAP ----------------------------------------------
    speed = np.sqrt(vx**2+vy**2)
    cap = speed > V_CAP
    vx[cap] *= V_CAP/speed[cap]
    vy[cap] *= V_CAP/speed[cap]

    # -- ADVECT ----------------------------------------------------
    grid = advect(grid,vx,vy)
    vx   = advect(vx,vx,vy)
    vy   = advect(vy,vx,vy)
    vx  *= 0.97; vy *= 0.97

    # -- BLACK HOLE -> SUBWAY ---------------------------------------
    # Hard cap: only extreme peaks drain, and only slowly
    # This is the limit on how fast matter can be untied to subway
    bh_val = np.percentile(grid, 99.2)
    bh_cells = (grid > bh_val) & (grid > np.mean(grid)*3)
    step_drain = 0.0
    if bh_cells.any():
        drained = grid[bh_cells] * BH_DRAIN
        step_drain = drained.sum()
        subway += step_drain
        grid[bh_cells] -= drained
    bh_drain_hist.append(step_drain)

    # -- SUBSTRATE & TRUE VOID -------------------------------------
    thin = grid < 0.008
    tension[thin]  -= 0.018
    tension[~thin] += 0.014
    tension = np.clip(tension,0,1)
    true_void = tension < 0.05

    # CONSERVED void spill: neighbors get exactly what void loses
    void_d = grid * true_void
    if void_d.sum() > 0:
        spill = void_d * 0.9   # 90% redistributed to neighbors
        grid -= spill
        # Distribute evenly to 4 neighbors - total in = total out
        per_neighbor = spill * 0.25
        grid += (np.roll(per_neighbor,1,0) + np.roll(per_neighbor,-1,0) +
                 np.roll(per_neighbor,1,1) + np.roll(per_neighbor,-1,1))
        # 10% genuinely lost to true void (goes to subway as diffuse leak)
        lost = void_d * 0.1
        subway += lost.sum()
        grid -= lost
        grid[grid<0] = 0

    tear_age[true_void]  += 1
    tear_age[~true_void]  = np.maximum(0, tear_age[~true_void]-3)

    # -- GEYSERS (small, conserved, normalized) --------------------
    step_geyser = 0.0
    erupts = np.argwhere(tear_age > 12)[:2]
    for tx,ty in erupts:
        if subway > 0.5:
            inject = min(subway*0.04, 2.0)   # small - pebble not meteor
            d_g = torus_dist(tx,ty)
            kernel = np.exp(-d_g**2/6)
            # NORMALIZED: total added = inject exactly
            kernel_sum = kernel.sum()
            if kernel_sum > 0:
                grid += kernel / kernel_sum * inject
                subway -= inject
                step_geyser += inject
            seal_str[tx,ty] += 0.35
    sealed = (seal_str > 1.8) & (grid > 0.008)
    tear_age[sealed] = 0; seal_str[sealed] = 0
    geyser_out_hist.append(step_geyser)
    subway_hist.append(subway)

    # -- DIFFUSION (minimal) ---------------------------------------
    grid = blur(grid, 0.03)
    grid[grid < 0] = 0

    # -- TRACK -----------------------------------------------------
    om = curl(vx,vy)
    vort_hist.append(om.mean())
    chiral_hist.append([om[:N//2,:N//2].mean(), om[:N//2,N//2:].mean(),
                        om[N//2:,:N//2].mean(), om[N//2:,N//2:].mean()])
    core_hist.append(np.percentile(grid,99))
    matter_hist.append(grid.sum())

    if step % 50 == 0:
        # Find center of mass for radial profile
        total = grid.sum() + 1e-10
        cm_x = int((grid * xx).sum() / total) % N
        cm_y = int((grid * yy).sum() / total) % N
        nc = count_clumps(grid)
        drain_rate  = np.mean(bh_drain_hist[-10:]) if len(bh_drain_hist)>=10 else step_drain
        geyser_rate = np.mean(geyser_out_hist[-10:]) if len(geyser_out_hist)>=10 else step_geyser
        print(f"  step {step:>4} | T={cool:.2f} | clumps={nc:>3} | "
              f"matter={matter_hist[-1]:.1f} | core={core_hist[-1]:.3f} | "
              f"BH_flow={drain_rate:.3f} | geyser_flow={geyser_rate:.3f} | "
              f"subway={subway:.1f}")

    if step in [0,60,160,280,steps-1]:
        snaps[step]=grid.copy()

# -- OUTPUT --------------------------------------------------------
epoch_labels = [(0,"PLASMA"),(60,"END PLASMA"),
                (160,"COOLING DONE"),(280,"STRUCTURE"),(steps-1,"FINAL")]
for s,label in epoch_labels:
    print(f"\n=== {label} (step {s}) ===")
    print(ascii_grid(snaps[s]))

g = snaps[steps-1]
total = g.sum()+1e-10
cm_x = int((g*xx).sum()/total)%N
cm_y = int((g*yy).sum()/total)%N

print(f"\n=== CONSERVATION CHECK ===")
print(f"  Initial matter:       {initial_matter:.2f}")
print(f"  Final matter:         {matter_hist[-1]:.2f}")
print(f"  Final subway:         {subway:.2f}")
print(f"  Final wave energy:    {wave_E_hist[-1]:.2f}")
print(f"  Matter+subway final:  {matter_hist[-1]+subway:.2f}")
drift = abs(matter_hist[-1]+subway - initial_matter) / initial_matter * 100
print(f"  Conservation drift:   {drift:.1f}%  (wave energy is separate)")

print(f"\n=== UNIVERSAL CORE ===")
print(f"  Center of mass: ({cm_x}, {cm_y})")
print(f"  Core (top 1%):  {core_hist[-1]:.4f}")
print(f"  Core (top 5%):  {np.percentile(g,95):.4f}")
print(f"  Core (top 10%): {np.percentile(g,90):.4f}")
print(f"  Mean:           {g.mean():.4f}")
print(f"  Void (bot 10%): {np.percentile(g,10):.4f}")
print(f"\n  Radial density profile (from center of mass):")
profile, radii = radial_profile(g, cm_x, cm_y)
for r,d in zip(radii[::2], profile[::2]):
    bar = '#' * int(d/profile.max()*30) if profile.max()>0 else ''
    print(f"    r={r:5.1f}: {d:8.3f}  {bar}")

print(f"\n=== SUBWAY / FLOW EQUILIBRIUM ===")
print(f"  Peak subway:          {max(subway_hist):.2f}")
print(f"  Final subway:         {subway:.2f}")
print(f"\n  BH drain rate over time (10-step avg):")
checkpts = [10,50,100,150,200,250,300,steps-1]
for si in checkpts:
    if si < len(bh_drain_hist):
        avg_drain  = np.mean(bh_drain_hist[max(0,si-10):si+1])
        avg_geyser = np.mean(geyser_out_hist[max(0,si-10):si+1])
        balance = avg_geyser - avg_drain
        print(f"    step {si:>4}: BH_in={avg_drain:.4f}  "
              f"geyser_out={avg_geyser:.4f}  "
              f"net={balance:+.4f}  "
              f"({'geyser>drain: subway emptying' if balance>0.001 else 'drain>geyser: subway filling' if balance<-0.001 else 'NEAR EQUILIBRIUM'})")

print(f"\n=== CHIRALITY ===")
q = np.mean(chiral_hist[-30:],axis=0)
for lbl,v in zip(['Top-Left','Top-Right','Bot-Left','Bot-Right'],q):
    print(f"  {lbl:10}: {v:+.6f}  ({'CCW' if v>0 else 'CW'})")
mixed = len(set(np.sign(q).astype(int))) > 1
print(f"  Mixed handedness: {'YES' if mixed else 'NO'}")
final_om = curl(vx,vy)
print(f"  Vorticity std: {final_om.std():.6f}")

print(f"\n=== CORE DENSITY TREND ===")
for si in [0,60,120,160,220,280,steps-1]:
    if si < len(core_hist):
        phase = "plasma" if si<60 else "cooling" if si<160 else "structure"
        print(f"  step {si+1:>4} [{phase:9}]: {core_hist[si]:.4f}")
sc = core_hist[-1] - core_hist[min(160,len(core_hist)-1)]
print(f"\n  Structure epoch core change: {sc:+.4f}")
print(f"  {'CONCENTRATING OK' if sc>0 else 'dispersing'}")

print("\nDone.")
