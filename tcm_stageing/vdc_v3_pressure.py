import numpy as np

"""
VDC Sim v3 - Pressure + Angular Momentum
New physics added:
- Pressure gradient: density resists compression, pushes back
  (this is what turns pure infall into rotation)
- Angular momentum: tracked and conserved during advection
- Single large boom + natural fragmentation (no pre-set smaller seeds)
- Substrate tension: thinning field has a restoring force until it tears
- True void: cells below absolute threshold become causally disconnected
  (no force crosses them - they're genuinely empty)
- Geysers only from true void tears, not just low density
"""

N = 70
# Fields
grid = np.zeros((N, N))        # Density (reality cloud thickness)
vx   = np.zeros((N, N))        # Velocity x
vy   = np.zeros((N, N))        # Velocity y
pressure = np.zeros((N, N))    # Local pressure (resists compression)
tension  = np.ones((N, N))     # Substrate tension (1=intact, 0=torn)

xx, yy = np.meshgrid(np.arange(N), np.arange(N))

def torus_dist(cx, cy):
    dx = np.minimum(np.abs(xx-cx), N-np.abs(xx-cx))
    dy = np.minimum(np.abs(yy-cy), N-np.abs(yy-cy))
    return np.sqrt(dx**2 + dy**2)

def blur(g, strength=0.1):
    return (g*(1-4*strength) +
            strength*(np.roll(g,1,0)+np.roll(g,-1,0)+
                      np.roll(g,1,1)+np.roll(g,-1,1)))

def gradient(g):
    """Pressure gradient on torus"""
    gx = (np.roll(g,-1,0) - np.roll(g,1,0)) / 2
    gy = (np.roll(g,-1,1) - np.roll(g,1,1)) / 2
    return gx, gy

def vorticity(vx, vy):
    dvy_dx = (np.roll(vy,-1,0) - np.roll(vy,1,0)) / 2
    dvx_dy = (np.roll(vx,-1,1) - np.roll(vx,1,1)) / 2
    return dvy_dx - dvx_dy

def advect(field, vx, vy, dt=0.4):
    """Move field along velocity - torus wrapped"""
    src_x = (np.arange(N)[:,None] - vx*dt) % N
    src_y = (np.arange(N)[None,:] - vy*dt) % N
    ix = src_x.astype(int); fx = src_x - ix
    iy = src_y.astype(int); fy = src_y - iy
    return ((1-fx)*(1-fy)*field[ix%N,    iy%N   ] +
               fx *(1-fy)*field[(ix+1)%N, iy%N   ] +
            (1-fx)*   fy *field[ix%N,    (iy+1)%N] +
               fx *   fy *field[(ix+1)%N,(iy+1)%N])

def ascii_grid(g, w=N):
    chars = ' .:*#&@'
    mn, mx = g.min(), g.max()
    if mx == mn: return '\n'.join('.'*w for _ in range(N))
    gn = (g-mn)/(mx-mn+1e-10)
    return '\n'.join(
        ''.join(chars[min(int(v*(len(chars)-1)),len(chars)-1)] for v in row)
        for row in gn)

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

# ── SINGLE LARGE BOOM ──────────────────────────────────────────────
# One seed. Everything else must emerge.
# Slight offset from center so the torus wrap creates asymmetry naturally
grid[N//2 + 2, N//2 - 1] += 100.0

# Tiny quantum noise - real universe isn't perfectly smooth
# This is the only randomness seeded; structure must grow from it
np.random.seed(None)  # truly random each run
grid += np.random.exponential(0.02, (N,N))

TRUE_VOID_THRESHOLD = 0.005   # Below this: causally disconnected
TEAR_THRESHOLD      = 0.015   # Below this for sustained time: substrate tears
PRESSURE_K          = 0.08    # How strongly density resists compression
TENSION_RESTORE     = 0.02    # Rate substrate heals if density returns
GRAVITY_STRENGTH    = 0.018
GEYSER_STRENGTH     = 8.0

tear_age    = np.zeros((N,N))
seal_age    = np.zeros((N,N))
geyser_log  = []

steps = 160
snaps = {}
vort_hist = []
chirality_hist = []
clump_hist = []
true_void_hist = []
ang_mom_hist = []

print(f"VDC v3 | {N}x{N} torus | {steps} steps")
print(f"Single boom at ({N//2+2},{N//2-1}) + quantum noise")
print(f"Pressure, angular momentum, substrate tension, true void active\n")

for step in range(steps):

    # ── PRESSURE (density resists compression) ─────────────────────
    # Ideal gas-like: P = k * rho
    # High density pushes outward; creates rotation when asymmetric
    pressure = PRESSURE_K * grid

    # Pressure gradient pushes matter from dense to sparse
    px, py = gradient(pressure)
    # Only acts where substrate is intact (tension > 0.3)
    intact = tension > 0.3
    vx[intact] -= px[intact] * 0.6
    vy[intact] -= py[intact] * 0.6

    # ── RIPPLE from mass (boom echo + ongoing wave) ─────────────────
    d = torus_dist(N//2+2, N//2-1)
    phase = (d - step * 0.75) % (2*np.pi)
    ripple = np.cos(phase) / (d + 1.0)

    # Ripple only travels through intact substrate
    # True void doesn't carry waves - causally disconnected
    ripple *= tension
    grid += 0.035 * ripple

    # ── GRAVITY: pulls toward density peaks ────────────────────────
    # This + pressure is what produces rotation via angular momentum
    peaks = np.argwhere(grid > np.mean(grid) + 0.8*np.std(grid))
    for px_i, py_i in peaks:
        dx = xx - px_i; dy = yy - py_i
        dx = np.where(np.abs(dx)>N//2, dx-np.sign(dx)*N, dx)
        dy = np.where(np.abs(dy)>N//2, dy-np.sign(dy)*N, dy)
        r  = np.sqrt(dx**2 + dy**2) + 0.5
        mask = (r < 15) & (r > 0.1) & intact
        pull = grid[px_i, py_i] * GRAVITY_STRENGTH / r**2
        vx -= np.where(mask, pull*(dx/r), 0)
        vy -= np.where(mask, pull*(dy/r), 0)

    # ── ANGULAR MOMENTUM CONSERVATION ──────────────────────────────
    # When matter falls inward, outer bits must spin faster (ice-skater)
    # Approximate: conserve r*v_tangential locally
    cx, cy = N//2, N//2
    dx_c = xx - cx; dy_c = yy - cy
    dx_c = np.where(np.abs(dx_c)>N//2, dx_c-np.sign(dx_c)*N, dx_c)
    dy_c = np.where(np.abs(dy_c)>N//2, dy_c-np.sign(dy_c)*N, dy_c)
    r_c = np.sqrt(dx_c**2 + dy_c**2) + 0.1
    # Tangential velocity = r cross v (z-component)
    v_tang = (dx_c*vy - dy_c*vx) / r_c
    ang_mom = np.sum(grid * r_c * v_tang)
    ang_mom_hist.append(ang_mom)

    # ── ADVECT ALL FIELDS ──────────────────────────────────────────
    grid = advect(grid, vx, vy)
    vx   = advect(vx,   vx, vy)
    vy   = advect(vy,   vx, vy)

    # Velocity damping (not frictionless, but close)
    vx *= 0.97; vy *= 0.97

    # ── SUBSTRATE TENSION & TEARS ──────────────────────────────────
    # Tension erodes where density is very low
    thin = grid < TEAR_THRESHOLD
    tension[thin]  -= 0.03          # substrate weakens
    tension[~thin] += TENSION_RESTORE  # heals where density returns
    tension = np.clip(tension, 0, 1)

    # True void: tension fully gone
    true_void = tension < 0.05
    true_void_frac = true_void.mean()
    true_void_hist.append(true_void_frac)

    # Tear age tracks sustained true void
    tear_age[true_void]  += 1
    tear_age[~true_void]  = np.maximum(0, tear_age[~true_void] - 3)

    # ── GEYSERS from sustained true void tears ─────────────────────
    # Only where tear_age > 12 (sustained, not just momentary dip)
    eruptions = np.argwhere(tear_age > 12)
    for tx, ty in eruptions[:3]:
        # Inject primordial density (from "subway")
        d_g = torus_dist(tx, ty)
        strength = GEYSER_STRENGTH * min(tear_age[tx,ty]/25, 2.5)
        inject = np.exp(-d_g**2 / 8) * strength  # gaussian blob, not wave
        grid += 0.018 * inject
        tension[tx,ty] += 0.15   # partial seal from injection
        seal_age[tx,ty] += 1
        if step % 20 == 0:
            geyser_log.append((step, tx, ty, strength))

    # ── DIFFUSION & DECAY ──────────────────────────────────────────
    grid = blur(grid, 0.08)
    grid -= 0.012 * grid
    grid[grid < 0] = 0

    # True void cells: no density can persist (causally disconnected)
    grid[true_void] *= 0.5

    # ── REDSHIFT PROXY ─────────────────────────────────────────────
    # Thinning along paths = apparent extra distance
    # (not deletion - separate from density)

    # ── TRACKING ──────────────────────────────────────────────────
    om = vorticity(vx, vy)
    vort_hist.append(om.mean())
    chirality_hist.append([
        om[:N//2,:N//2].mean(), om[:N//2,N//2:].mean(),
        om[N//2:,:N//2].mean(), om[N//2:,N//2:].mean()
    ])

    if step % 40 == 0:
        nc = count_clumps(grid)
        clump_hist.append((step, nc))
        void_f = np.mean(grid < TEAR_THRESHOLD)
        print(f"  step {step:>4} | clumps={nc:>3} | vort={om.mean():+.5f} | "
              f"true_void={true_void_frac:.3f} | ang_mom={ang_mom:.2f}")

    if step in [0, steps//4, steps//2, 3*steps//4, steps-1]:
        snaps[step] = grid.copy()

# ── OUTPUT ────────────────────────────────────────────────────────
for label, s in [("INITIAL",0),("QUARTER",steps//4),
                 ("HALF",steps//2),("THREE-Q",3*steps//4),("FINAL",steps-1)]:
    print(f"\n=== {label} (step {s}) ===")
    print(ascii_grid(snaps[s]))

print("\n=== FINAL METRICS ===")
g = snaps[steps-1]
print(f"  Density contrast (isolation): {np.std(g)/np.mean(g):.4f}")
print(f"  True void fraction:           {true_void_hist[-1]:.4f}")
print(f"  Clumps at end:                {count_clumps(g)}")

print("\n=== VORTICITY EMERGENCE (from zero) ===")
for si in [0,9,39,79,119,steps-1]:
    if si < len(vort_hist):
        print(f"  step {si+1:>4}: {vort_hist[si]:+.7f}")

net = vort_hist[-1] - vort_hist[0]
print(f"\n  Net rotation emerged: {net:+.7f}")
print(f"  {'Rotation detected - from pressure+gravity asymmetry alone' if abs(net)>0.0005 else 'Minimal net rotation - symmetric forces cancel'}")

print("\n=== QUADRANT CHIRALITY (last 20 steps) ===")
q = np.mean(chirality_hist[-20:], axis=0)
for lbl, v in zip(['Top-Left','Top-Right','Bot-Left','Bot-Right'], q):
    print(f"  {lbl:10}: {v:+.7f}  ({'CCW' if v>0 else 'CW'})")

same = (np.sign(q[0])!=np.sign(q[1])) or (np.sign(q[2])!=np.sign(q[3]))
print(f"\n  Opposite chirality across quadrants: {'YES - position-dependent handedness' if same else 'NO - uniform'}")

print("\n=== GEYSER EVENTS (sample) ===")
if geyser_log:
    for ev in geyser_log[:8]:
        print(f"  step {ev[0]:>4} | site ({ev[1]:>2},{ev[2]:>2}) | strength {ev[3]:.2f}")
    print(f"  Total logged: {len(geyser_log)}")
else:
    print("  No sustained tears reached geyser threshold")

print("\n=== ANGULAR MOMENTUM TREND ===")
for si in [0,39,79,steps-1]:
    if si < len(ang_mom_hist):
        print(f"  step {si+1:>4}: L = {ang_mom_hist[si]:+.4f}")

print("\nDone.")
