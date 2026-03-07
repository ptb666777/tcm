import numpy as np

"""
VDC Sim v2 - Emergent, vectorized for speed
- No seeded spin - emerges from asymmetric mass only
- Redshift as path-thinning proxy, not deletion
- Persistent tear memory for geysers
- Real spatial clump counting
"""

N = 60
grid = np.zeros((N, N))
velocity = np.zeros((N, N, 2))
xx, yy = np.meshgrid(np.arange(N), np.arange(N))

def torus_dist_grid(cx, cy):
    dx = np.abs(xx - cx); dy = np.abs(yy - cy)
    dx = np.minimum(dx, N - dx); dy = np.minimum(dy, N - dy)
    return np.sqrt(dx**2 + dy**2)

# SEEDS - no velocity, no spin
grid[N//2, N//2] += 80
grid[N//3, N//3] += 25
grid[2*N//3, N//4] += 12

tear_age = np.zeros((N, N))
seal_strength = np.zeros((N, N))

def blur(g):
    return (g * 0.6 +
            0.1 * (np.roll(g,1,0) + np.roll(g,-1,0) +
                   np.roll(g,1,1) + np.roll(g,-1,1)))

def vorticity(v):
    dvy_dx = (np.roll(v[:,:,1],-1,0) - np.roll(v[:,:,1],1,0)) / 2
    dvx_dy = (np.roll(v[:,:,0],-1,1) - np.roll(v[:,:,0],1,1)) / 2
    return dvy_dx - dvx_dy

def ascii_grid(g):
    chars = ' .:*#&@'
    g_norm = (g - g.min()) / (g.max() - g.min() + 1e-10)
    return '\n'.join(
        ''.join(chars[min(int(v*(len(chars)-1)), len(chars)-1)] for v in row)
        for row in g_norm)

def count_clumps(g):
    thresh = np.mean(g) + 0.5*np.std(g)
    binary = g > thresh
    visited = np.zeros((N,N), dtype=bool)
    count = 0
    for i in range(N):
        for j in range(N):
            if binary[i,j] and not visited[i,j]:
                count += 1
                q = [(i,j)]
                while q:
                    ci,cj = q.pop()
                    if visited[ci,cj]: continue
                    visited[ci,cj] = True
                    for di,dj in [(-1,0),(1,0),(0,-1),(0,1)]:
                        ni,nj=(ci+di)%N,(cj+dj)%N
                        if binary[ni,nj] and not visited[ni,nj]:
                            q.append((ni,nj))
    return count

# Precompute distances from seed positions
d_center = torus_dist_grid(N//2, N//2)
d_b2 = torus_dist_grid(N//3, N//3)
d_b3 = torus_dist_grid(2*N//3, N//4)

steps = 120
vort_hist = []
clump_hist = []
rs_hist = []
chirality_hist = []
snap = {}

print(f"VDC v2 | {N}x{N} torus | {steps} steps | zero initial velocity")
print(f"Seeds: ({N//2},{N//2})=80  ({N//3},{N//3})=25  ({2*N//3},{N//4})=12\n")

for step in range(steps):
    # Multi-source ripples
    rip = (np.cos((d_center - step*0.8) % (2*np.pi)) / (d_center+1) +
           0.3*np.cos((d_b2 - step*0.6) % (2*np.pi)) / (d_b2+1) +
           0.15*np.cos((d_b3 - step*0.7) % (2*np.pi)) / (d_b3+1))

    # Lensing at peaks
    peak_mask = grid > np.mean(grid) + np.std(grid)
    rip[peak_mask] *= 1.08
    grid += 0.04 * rip

    # Tear memory
    void_thresh = np.mean(grid) * 0.4
    is_void = grid < void_thresh
    tear_age[is_void] += 1
    tear_age[~is_void] = np.maximum(0, tear_age[~is_void] - 2)

    # Geysers from sustained tears only
    erupt = np.argwhere(tear_age > 8)
    for tx, ty in erupt[:3]:
        d = torus_dist_grid(tx, ty)
        strength = np.random.uniform(3,10) * min(tear_age[tx,ty]/20, 2.0)
        grid += 0.02 * np.cos((d - step*0.4)%(2*np.pi)) / (d+1) * strength
        seal_strength[tx,ty] += 0.5

    sealed = (seal_strength > 2.0) & (grid > void_thresh)
    tear_age[sealed] = 0; seal_strength[sealed] = 0

    # Advect (vectorized bilinear on torus)
    src_x = (np.arange(N)[:,None] - velocity[:,:,0]*0.4) % N
    src_y = (np.arange(N)[None,:] - velocity[:,:,1]*0.4) % N
    ix = src_x.astype(int); fx = src_x - ix
    iy = src_y.astype(int); fy = src_y - iy
    grid = ((1-fx)*(1-fy)*grid[ix%N, iy%N] +
             fx*(1-fy)*grid[(ix+1)%N, iy%N] +
             (1-fx)*fy*grid[ix%N, (iy+1)%N] +
             fx*fy*grid[(ix+1)%N, (iy+1)%N])

    # Gravity: vectorized pull toward ALL peaks
    # This asymmetric pull is the ONLY source of possible rotation
    peaks = np.argwhere(grid > np.mean(grid) + np.std(grid))
    for px, py in peaks:
        dx = xx - px; dy = yy - py
        dx = np.where(np.abs(dx)>N//2, dx-np.sign(dx)*N, dx)
        dy = np.where(np.abs(dy)>N//2, dy-np.sign(dy)*N, dy)
        r = np.sqrt(dx**2 + dy**2) + 0.5
        mask = (r < 12) & (r > 0.1)
        pull = grid[px,py] / r**2
        velocity[:,:,0] -= np.where(mask, 0.012*pull*(dx/r), 0)
        velocity[:,:,1] -= np.where(mask, 0.012*pull*(dy/r), 0)

    velocity *= 0.98
    grid = blur(grid)
    grid -= 0.015 * grid
    grid[grid < 0] = 0

    # Redshift proxy: path thinning (NOT deletion)
    mean_g = np.mean(grid)
    thinness = np.maximum(0, mean_g - grid) / (mean_g + 1e-10)
    rs = blur(thinness).mean()
    rs_hist.append(rs)

    # Vorticity (emergent)
    om = vorticity(velocity)
    vort_hist.append(om.mean())

    # Quadrant chirality
    chirality_hist.append([
        om[:N//2,:N//2].mean(), om[:N//2,N//2:].mean(),
        om[N//2:,:N//2].mean(), om[N//2:,N//2:].mean()
    ])

    if step in [0, steps//4, steps//2, 3*steps//4, steps-1]:
        snap[step] = grid.copy()

    if step % 30 == 0:
        nc = count_clumps(grid)
        clump_hist.append((step, nc))
        print(f"  step {step:>4} | clumps={nc} | vort={vort_hist[-1]:+.6f} | void_frac={np.mean(grid<void_thresh):.3f}")

# Output
for label, s in [("INITIAL",0),("QUARTER",steps//4),("HALF",steps//2),("THREE-Q",3*steps//4),("FINAL",steps-1)]:
    print(f"\n=== {label} (step {s}) ===")
    print(ascii_grid(snap[s]))

print("\n=== METRICS ===")
print(f"Final void fraction:      {np.mean(grid < np.mean(grid)*0.4):.4f}")
print(f"Density contrast:         {np.std(grid)/np.mean(grid):.4f}")
print(f"Redshift proxy (mean):    {np.mean(rs_hist[-20:]):.4f}")

print("\n=== VORTICITY EMERGENCE ===")
for si in [0,9,29,59,99,steps-1]:
    if si < len(vort_hist):
        print(f"  step {si+1:>4}: {vort_hist[si]:+.6f}")

net = vort_hist[-1] - vort_hist[0]
print(f"\n  Net spin emerged: {net:+.6f}")
if abs(net) > 0.0005:
    print(f"  Direction: {'counterclockwise (CCW)' if net>0 else 'clockwise (CW)'}")
    print(f"  Emerged from asymmetric mass positions alone - NOT seeded.")
else:
    print(f"  No significant net rotation emerged.")

print("\n=== QUADRANT CHIRALITY (avg last 20 steps) ===")
q_avg = np.mean(chirality_hist[-20:], axis=0)
for lbl, val in zip(['Top-Left','Top-Right','Bot-Left','Bot-Right'], q_avg):
    print(f"  {lbl:10}: {val:+.6f}  ({'CCW' if val>0 else 'CW'})")

print("\n=== CLUMPS OVER TIME ===")
for s, nc in clump_hist:
    print(f"  step {s:>4}: {nc} clumps")

print("\nDone.")
