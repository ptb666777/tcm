# VORTEX SUBSTRATE MODEL - Single File Implementation
# Based on Patrick's formal logic string
#
# Core equation:
# Psi(x) = sum over pins of (rho_i * omega_i) / (|x - p_i|^2 + tau)
#
# tau  = surface tension of the substrate (vacuum resistance)
# rho  = resonance variant of the pin (atomic geometry)
# omega = spin frequency of the pin
# Psi  = local reality field density at point x

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.gridspec import GridSpec

# ─────────────────────────────────────────────
# SUBSTRATE PARAMETERS
# ─────────────────────────────────────────────
N         = 64          # grid size per axis
TAU       = 1.0         # surface tension - vacuum resistance to pinning
DT        = 0.05        # time step
STEPS     = 5000         # how long to run
SNAP_EVERY = 10         # render every N steps

# ─────────────────────────────────────────────
# PIN DEFINITION
# A pin is a resonant node in the substrate
# pos   = [x, y, z] position on grid
# rho   = resonance variant (1.0 = hydrogen baseline)
# omega = spin frequency
# vel   = current velocity through substrate
# ─────────────────────────────────────────────
def make_pin(pos, rho=1.0, omega=1.0):
    return {
        'pos': np.array(pos, dtype=float),
        'rho': rho,
        'omega': omega,
        'vel': np.zeros(3),
    }

# ─────────────────────────────────────────────
# PSI FIELD
# Compute the local reality density at every
# point in the grid from all pins
# ─────────────────────────────────────────────
def compute_psi(pins, N, tau):
    coords = np.arange(N)
    cx, cy, cz = np.meshgrid(coords, coords, coords, indexing='ij')
    psi = np.zeros((N, N, N))

    for pin in pins:
        px, py, pz = pin['pos']
        # Toroidal distance (wraps at edges)
        dx = np.minimum(np.abs(cx - px), N - np.abs(cx - px))
        dy = np.minimum(np.abs(cy - py), N - np.abs(cy - py))
        dz = np.minimum(np.abs(cz - pz), N - np.abs(cz - pz))
        r2 = dx**2 + dy**2 + dz**2
        # Core equation from the logic string
        psi += (pin['rho'] * pin['omega']) / (r2 + tau)

    return psi

# ─────────────────────────────────────────────
# PRESSURE GRADIENT
# Pins move toward LOW Psi zones (substrate
# pushes from high pressure toward low)
# This IS gravity in this model
# ─────────────────────────────────────────────
def compute_gradient(psi):
    # Central difference gradient
    gx = (np.roll(psi, -1, axis=0) - np.roll(psi, 1, axis=0)) / 2.0
    gy = (np.roll(psi, -1, axis=1) - np.roll(psi, 1, axis=1)) / 2.0
    gz = (np.roll(psi, -1, axis=2) - np.roll(psi, 1, axis=2)) / 2.0
    return gx, gy, gz

# ─────────────────────────────────────────────
# LOCAL TIME RATE
# Time runs slower in dense Psi regions
# time_rate = 1 / (1 + Psi_local)
# This is gravitational time dilation from
# fluid mechanics, not assumed from GR
# ─────────────────────────────────────────────
def local_time_rate(psi_val):
    return 1.0 / (1.0 + psi_val)

# ─────────────────────────────────────────────
# STEP
# Move pins according to substrate pressure
# ─────────────────────────────────────────────
def step(pins, psi, gx, gy, gz, dt):
    for pin in pins:
        ix = int(pin['pos'][0]) % N
        iy = int(pin['pos'][1]) % N
        iz = int(pin['pos'][2]) % N

        # Local time rate at this pin's position
        t_rate = local_time_rate(psi[ix, iy, iz])

        # Pressure gradient at pin location - push toward low Psi
        # Negative because pins move DOWN the gradient (toward voids)
        force = np.array([
            -gx[ix, iy, iz],
            -gy[ix, iy, iz],
            -gz[ix, iy, iz],
        ])

        # Update velocity and position
        # Time rate affects how fast the pin experiences the force
        pin['vel'] += force * dt * t_rate
        pin['vel'] *= 0.98  # tiny damping - substrate has near-zero viscosity
        pin['pos'] = (pin['pos'] + pin['vel'] * dt) % N

# ─────────────────────────────────────────────
# VISUALIZATION
# ─────────────────────────────────────────────
def render(pins, psi, step_num, axes):
    ax_slice, ax_profile, ax_time, ax_3d = axes

    mid = N // 2

    # Clear
    for ax in axes:
        ax.cla()

    # 1. Middle slice of Psi field
    ax_slice.imshow(psi[:, :, mid].T, origin='lower',
                    cmap='inferno', interpolation='bilinear')
    for pin in pins:
        px, py = pin['pos'][0], pin['pos'][1]
        ax_slice.plot(px, py, 'o', color='cyan', markersize=6)
    ax_slice.set_title(f'Ψ field - Z slice  (step {step_num})',
                       color='white', fontsize=9)
    ax_slice.axis('off')

    # 2. Radial profile from first pin
    if pins:
        p0 = pins[0]['pos']
        coords = np.arange(N)
        cx, cy, cz = np.meshgrid(coords, coords, coords, indexing='ij')
        dx = np.minimum(np.abs(cx - p0[0]), N - np.abs(cx - p0[0]))
        dy = np.minimum(np.abs(cy - p0[1]), N - np.abs(cy - p0[1]))
        dz = np.minimum(np.abs(cz - p0[2]), N - np.abs(cz - p0[2]))
        r = np.sqrt(dx**2 + dy**2 + dz**2).flatten()
        psi_flat = psi.flatten()
        # Bin by radius
        r_bins = np.linspace(0, N//2, 30)
        psi_mean = []
        for i in range(len(r_bins)-1):
            mask = (r >= r_bins[i]) & (r < r_bins[i+1])
            psi_mean.append(psi_flat[mask].mean() if mask.any() else 0)
        ax_profile.plot(r_bins[:-1], psi_mean, color='#ff6b35', linewidth=2)
        ax_profile.set_facecolor('#0a0a0a')
        ax_profile.set_title('Ψ radial profile from pin', color='white', fontsize=9)
        ax_profile.set_xlabel('Distance from pin', color='#888')
        ax_profile.set_ylabel('Ψ density', color='#888')
        ax_profile.tick_params(colors='#666')
        for spine in ax_profile.spines.values():
            spine.set_color('#333')

    # 3. Local time rate at pin vs distance
    if pins:
        time_rates = [local_time_rate(v) for v in psi_mean]
        ax_time.plot(r_bins[:-1], time_rates, color='#00d4ff', linewidth=2)
        ax_time.set_facecolor('#0a0a0a')
        ax_time.set_title('Local time rate (1 = normal, <1 = dilated)',
                          color='white', fontsize=9)
        ax_time.set_xlabel('Distance from pin', color='#888')
        ax_time.set_ylabel('Time rate', color='#888')
        ax_time.tick_params(colors='#666')
        ax_time.axhline(y=1.0, color='#444', linestyle='--', linewidth=1)
        for spine in ax_time.spines.values():
            spine.set_color('#333')

    # 4. Pin positions in 3D projection
    ax_3d.set_facecolor('#0a0a0a')
    for pin in pins:
        ax_3d.scatter(*pin['pos'], s=80, c='cyan', zorder=5)
        # Draw velocity vector
        v = pin['vel'] * 20
        ax_3d.quiver(*pin['pos'], *v, color='yellow', alpha=0.7)
    ax_3d.set_xlim(0, N); ax_3d.set_ylim(0, N); ax_3d.set_zlim(0, N)
    ax_3d.set_title('Pin positions + velocity', color='white', fontsize=9)
    ax_3d.tick_params(colors='#444')
    ax_3d.set_facecolor('#0a0a0a')

# ─────────────────────────────────────────────
# SCENARIOS
# Comment/uncomment to test different setups
# ─────────────────────────────────────────────

# SCENARIO A: Single hydrogen-like pin
# Does it create an attractive well?
#pins = [
#    make_pin([32, 32, 32], rho=1.0, omega=1.0),
#]

# SCENARIO B: Two pins - do they attract or repel?
# Uncomment to test
#pins = [
#     make_pin([24, 32, 32], rho=1.0, omega=1.0),
#     make_pin([40, 32, 32], rho=1.0, omega=1.0),
#]

# SCENARIO C: Two pins with opposite spin
# In your model opposite spin = opposite charge
# Do they behave differently than same spin?
pins = [
     make_pin([24, 32, 32], rho=1.0, omega= 1.0),
     make_pin([40, 32, 32], rho=1.0, omega=-1.0),
]

# SCENARIO D: Carbon-like - 6 pins in tetrahedral geometry
# pins = []
# r = 4.0  # bond radius
# verts = [
#     [ 1, 1, 1], [-1,-1, 1], [-1, 1,-1], [ 1,-1,-1],
#     [ 0, 0, 2], [ 0, 0,-2]
# ]
# for v in verts:
#     pos = [32 + v[0]*r, 32 + v[1]*r, 32 + v[2]*r]
#     pins.append(make_pin(pos, rho=1.0, omega=1.0))

# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
print("Vortex Substrate Model")
print(f"Grid: {N}³  |  Pins: {len(pins)}  |  Steps: {STEPS}")
print(f"tau={TAU}  dt={DT}")
print()

fig = plt.figure(figsize=(14, 10), facecolor='#0a0a0a')
gs = GridSpec(2, 3, figure=fig, hspace=0.4, wspace=0.35)
ax_slice  = fig.add_subplot(gs[0, 0])
ax_profile = fig.add_subplot(gs[0, 1])
ax_time   = fig.add_subplot(gs[0, 2])
ax_3d     = fig.add_subplot(gs[1, :], projection='3d')
ax_3d.set_facecolor('#0a0a0a')
axes = [ax_slice, ax_profile, ax_time, ax_3d]

fig.suptitle('VORTEX SUBSTRATE MODEL  —  Ψ Field Dynamics',
             color='#ffffff', fontsize=12, fontweight='bold')

frames = []

for s in range(STEPS):
    psi = compute_psi(pins, N, TAU)
    gx, gy, gz = compute_gradient(psi)
    step(pins, psi, gx, gy, gz, DT)

    if s % SNAP_EVERY == 0:
        psi_center = psi[32, 32, 32]
        psi_edge   = psi[0, 0, 0]
        t_center   = local_time_rate(psi_center)
        t_edge     = local_time_rate(psi_edge)
        print(f"step {s:>4} | Ψ_center={psi_center:.4f}  Ψ_edge={psi_edge:.4f} "
              f"| t_rate_center={t_center:.4f}  t_rate_edge={t_edge:.4f} "
              f"| pin_pos={pins[0]['pos'].round(2)}")

        render(pins, psi, s, axes)
        plt.pause(0.01)

print()
print("Done. Showing final state.")
print(f"Final pin position: {pins[0]['pos'].round(3)}")
print(f"Final pin velocity: {pins[0]['vel'].round(6)}")
psi_final = compute_psi(pins, N, TAU)
print(f"Ψ at pin center: {psi_final[int(pins[0]['pos'][0])%N, int(pins[0]['pos'][1])%N, int(pins[0]['pos'][2])%N]:.4f}")
print(f"Ψ at grid edge:  {psi_final[0,0,0]:.6f}")
print(f"Ψ ratio center/edge: {psi_final[int(pins[0]['pos'][0])%N, int(pins[0]['pos'][1])%N, int(pins[0]['pos'][2])%N] / psi_final[0,0,0]:.1f}x")

plt.show()
