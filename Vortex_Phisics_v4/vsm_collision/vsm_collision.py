# VSM COLLISION TEST
# Tests nuclear binding via hydrodynamic pressure locking
#
# Gemini/Patrick insight:
#   SIGMA = macro shear limit (substrate tears -> black hole)
#   1/SIGMA = micro coupling threshold (substrate seals -> nucleus)
#   Same constant, symmetric universe, two directions
#
# Two-TAU model:
#   TAU_atomic  = 1.0  (vortex knot outer size, governs EM-like field)
#   TAU_nuclear = 0.01 (vortex core interior, governs strong-force coupling)
#
# Test: same-sign pins fired at each other at different speeds
# Find the capture velocity where they lock instead of bounce

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os, time

# ─────────────────────────────────────────────
N            = 64
TAU_ATOMIC   = 1.0      # outer vortex size
TAU_NUCLEAR  = 0.01     # inner vortex core
SIGMA        = 1.0      # macro shear limit
COUPLING_THR = 1.0/SIGMA  # micro seal threshold = 1.0
DT           = 0.02     # smaller timestep for collision accuracy
DAMP         = 0.999    # near zero damping - collisions are elastic
OUTPUT_DIR   = 'vsm_collision'
os.makedirs(OUTPUT_DIR, exist_ok=True)

half = N//2
_coords = np.arange(N, dtype=np.float32)

print(f"VSM COLLISION TEST")
print(f"SIGMA={SIGMA}  CouplingThreshold=1/sigma={COUPLING_THR}")
print(f"TAU_atomic={TAU_ATOMIC}  TAU_nuclear={TAU_NUCLEAR}")
print()

# ─────────────────────────────────────────────
# PIN
# ─────────────────────────────────────────────
def make_pin(pos, omega=1.0, vel=None, label=''):
    return {
        'pos':   np.array(pos, dtype=np.float64),
        'omega': float(omega),
        'rho':   1.0,
        'vel':   np.array(vel, dtype=np.float64) if vel else np.zeros(3),
        'label': label,
        'coupled': False,
        'coupled_to': None,
    }

# ─────────────────────────────────────────────
# PSI - uses TAU_ATOMIC for long range
# ─────────────────────────────────────────────
def compute_psi(pins):
    positions = np.array([p['pos'] for p in pins], dtype=np.float32)
    weights   = np.array([p['rho']*p['omega'] for p in pins], dtype=np.float32)
    px,py,pz  = positions[:,0],positions[:,1],positions[:,2]
    dx = np.minimum(np.abs(px[:,None]-_coords[None,:]),
                    N-np.abs(px[:,None]-_coords[None,:]))
    dy = np.minimum(np.abs(py[:,None]-_coords[None,:]),
                    N-np.abs(py[:,None]-_coords[None,:]))
    dz = np.minimum(np.abs(pz[:,None]-_coords[None,:]),
                    N-np.abs(pz[:,None]-_coords[None,:]))
    dx2,dy2,dz2 = dx**2,dy**2,dz**2
    psi = np.zeros((N,N,N),dtype=np.float32)
    for i in range(len(pins)):
        r = np.sqrt(dx2[i,:,None,None]+
                    dy2[i,None,:,None]+
                    dz2[i,None,None,:])+TAU_ATOMIC
        psi += weights[i]/r
    return psi

# ─────────────────────────────────────────────
# NUCLEAR GRADIENT - uses TAU_NUCLEAR
# Sharp core field - what each pin feels at close range
# ─────────────────────────────────────────────
def nuclear_gradient_at(source, probe_pos):
    """
    Gradient of source pin's nuclear-scale field at probe position.
    Uses TAU_NUCLEAR for sharp close-range interaction.
    This is what drives coupling/locking.
    """
    sp = source['pos']
    d = np.minimum(np.abs(probe_pos - sp), N - np.abs(probe_pos - sp))
    r = np.sqrt(np.sum(d**2))
    
    if r < 0.01:
        return np.zeros(3)
    
    # Gradient of 1/(r + TAU_NUCLEAR) with respect to probe position
    r_nuclear = r + TAU_NUCLEAR
    # d(1/r_n)/dr * dr/dx_i = -1/r_n^2 * (x_i - sx_i) / r
    direction = d / r  # unit vector (toroidal)
    # Sign: gradient points away from source
    # For probe to the right of source, gradient is positive (field decreasing)
    signs = np.sign(probe_pos - sp)
    # Handle toroidal wraparound
    for i in range(3):
        if abs(probe_pos[i] - sp[i]) > N/2:
            signs[i] = -signs[i]
    
    grad_mag = source['omega'] / (r_nuclear**2)
    return grad_mag * signs * direction

# ─────────────────────────────────────────────
# COUPLING CHECK
# Check if gradient between two pins exceeds 1/sigma
# This is hydrodynamic pressure locking
# ─────────────────────────────────────────────
def check_coupling(p1, p2):
    """
    Returns True if the nuclear-scale gradient between pins
    exceeds the coupling threshold (1/sigma).
    This is the substrate sealing condition.
    """
    g = nuclear_gradient_at(p1, p2['pos'])
    g_mag = np.linalg.norm(g)
    return g_mag > COUPLING_THR, g_mag

# ─────────────────────────────────────────────
# STEP
# ─────────────────────────────────────────────
def step_pins(pins, psi, gx, gy, gz):
    for p in pins:
        if p['coupled']:
            # Coupled pins move as unit with their partner
            continue
            
        ix = int(p['pos'][0]) % N
        iy = int(p['pos'][1]) % N
        iz = int(p['pos'][2]) % N
        
        psi_local = float(psi[ix, iy, iz])
        t_rate = 1.0 / (1.0 + abs(psi_local))
        
        # EM-scale force (atomic TAU)
        force = p['omega'] * np.array([
            -float(gx[ix, iy, iz]),
            -float(gy[ix, iy, iz]),
            -float(gz[ix, iy, iz]),
        ])
        
        p['vel'] += force * DT * t_rate
        p['vel'] *= DAMP
        p['pos'] = (p['pos'] + p['vel'] * DT) % N

def compute_gradient(psi):
    gx = (np.roll(psi,-1,0)-np.roll(psi,1,0))*0.5
    gy = (np.roll(psi,-1,1)-np.roll(psi,1,1))*0.5
    gz = (np.roll(psi,-1,2)-np.roll(psi,1,2))*0.5
    return gx,gy,gz

def pdist(a, b):
    d = np.minimum(np.abs(a['pos']-b['pos']), N-np.abs(a['pos']-b['pos']))
    return float(np.sqrt(np.sum(d**2)))

# ─────────────────────────────────────────────
# COLLISION EXPERIMENT
# Fire two same-sign pins at each other
# Test multiple approach velocities
# ─────────────────────────────────────────────
def run_collision(approach_speed, steps=2000, label=''):
    """
    Two same-sign (+) pins fired at each other.
    approach_speed: initial velocity magnitude toward each other
    Returns: 'locked', 'bounced', 'passed_through'
    """
    # Start separated by 20 cells, moving toward each other
    pins = [
        make_pin([half-10, half, half], omega=1.0,
                 vel=[ approach_speed, 0, 0], label='A+'),
        make_pin([half+10, half, half], omega=1.0,
                 vel=[-approach_speed, 0, 0], label='B+'),
    ]
    
    history = {
        'sep': [],
        'spd_a': [],
        'spd_b': [],
        'coupled': [],
        'grad_mag': [],
    }
    
    coupled_step = None
    min_sep = 999.0
    
    for s in range(steps):
        psi = compute_psi(pins)
        gx,gy,gz = compute_gradient(psi)
        
        # Check coupling before stepping
        coupled, g_mag = check_coupling(pins[0], pins[1])
        
        if coupled and not pins[0]['coupled']:
            pins[0]['coupled'] = True
            pins[1]['coupled'] = True
            # Lock velocities - average them (momentum conservation)
            avg_vel = (pins[0]['vel'] + pins[1]['vel']) / 2.0
            pins[0]['vel'] = avg_vel.copy()
            pins[1]['vel'] = avg_vel.copy()
            coupled_step = s
        
        step_pins(pins, psi, gx, gy, gz)
        
        # If coupled, move together
        if pins[0]['coupled']:
            cm_vel = pins[0]['vel']
            pins[0]['pos'] = (pins[0]['pos'] + cm_vel * DT) % N
            pins[1]['pos'] = (pins[1]['pos'] + cm_vel * DT) % N
        
        sep = pdist(pins[0], pins[1])
        min_sep = min(min_sep, sep)
        
        history['sep'].append(sep)
        history['spd_a'].append(float(np.linalg.norm(pins[0]['vel'])))
        history['spd_b'].append(float(np.linalg.norm(pins[1]['vel'])))
        history['coupled'].append(pins[0]['coupled'])
        history['grad_mag'].append(g_mag)
        
        # Early exit if clearly bounced and separating
        if s > 200 and not pins[0]['coupled']:
            recent_seps = history['sep'][-50:]
            if all(recent_seps[i] < recent_seps[i+1] 
                   for i in range(len(recent_seps)-1)):
                break
    
    final_sep = history['sep'][-1]
    
    if pins[0]['coupled']:
        result = 'LOCKED'
    elif min_sep < 1.0:
        result = 'PASSED_THROUGH'
    else:
        result = 'BOUNCED'
    
    return result, min_sep, coupled_step, history, pins

# ─────────────────────────────────────────────
# RUN SWEEP - find capture velocity
# ─────────────────────────────────────────────
print("VELOCITY SWEEP - Finding nuclear capture velocity")
print(f"{'speed':>8} {'result':>14} {'min_sep':>10} {'coupled_at':>12}")
print("-"*50)

speeds = [0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0]
results = []
capture_speed = None

for spd in speeds:
    result, min_sep, coupled_step, history, final_pins = run_collision(spd)
    coupled_str = f"step {coupled_step}" if coupled_step else "never"
    print(f"{spd:>8.2f} {result:>14} {min_sep:>10.3f} {coupled_str:>12}")
    results.append((spd, result, min_sep, coupled_step, history))
    if result == 'LOCKED' and capture_speed is None:
        capture_speed = spd

print()
if capture_speed:
    print(f"Nuclear capture velocity: ~{capture_speed}")
    print(f"Pins lock into bound nucleus at or above this approach speed")
    print(f"This is your 'collision energy' threshold for nuclear binding")
else:
    print("No locking observed - coupling threshold may need adjustment")
    print(f"Minimum separation achieved: {min(r[2] for r in results):.3f} cells")
    print(f"Coupling threshold: {COUPLING_THR:.3f}")
    print(f"Max gradient achieved: check - may need TAU_NUCLEAR adjustment")

# ─────────────────────────────────────────────
# PLOT RESULTS
# ─────────────────────────────────────────────
fig, axes = plt.subplots(2, 3, figsize=(14, 8), facecolor='#0a0a0a')
fig.suptitle('VSM Nuclear Collision Test\nHydrodynamic Pressure Locking',
             color='white', fontsize=11)

colors = ['#00d4ff','#ff6b35','#00ff88','#ff00aa','#ffdd00',
          '#aa00ff','#ffffff','#88ff00','#ff8800','#00ffdd']

# Plot separations for all speeds
ax = axes[0,0]; ax.set_facecolor('#111')
for i,(spd,result,_,_,hist) in enumerate(results):
    style = '-' if result=='LOCKED' else '--'
    ax.plot(hist['sep'], color=colors[i%len(colors)],
            linewidth=1.5, linestyle=style,
            label=f"v={spd} [{result[:4]}]")
ax.axhline(y=1.0/COUPLING_THR, color='red', linestyle=':', 
           linewidth=1, label=f'coupling range')
ax.set_title('Pin Separations', color='white', fontsize=9)
ax.set_xlabel('Step', color='#888', fontsize=7)
ax.set_ylabel('Distance (cells)', color='#888', fontsize=7)
ax.legend(fontsize=6, facecolor='#222', labelcolor='white', ncol=2)
ax.tick_params(colors='#555', labelsize=6)
for sp in ax.spines.values(): sp.set_color('#333')

# Plot gradient magnitudes
ax = axes[0,1]; ax.set_facecolor('#111')
for i,(spd,result,_,_,hist) in enumerate(results):
    ax.plot(hist['grad_mag'], color=colors[i%len(colors)],
            linewidth=1.2, label=f"v={spd}")
ax.axhline(y=COUPLING_THR, color='red', linestyle='--',
           linewidth=1.5, label=f'threshold={COUPLING_THR}')
ax.set_title('Nuclear Gradient Magnitude\n(coupling when > threshold)',
             color='white', fontsize=9)
ax.set_xlabel('Step', color='#888', fontsize=7)
ax.set_ylabel('|∇Ψ_nuclear|', color='#888', fontsize=7)
ax.legend(fontsize=6, facecolor='#222', labelcolor='white')
ax.tick_params(colors='#555', labelsize=6)
for sp in ax.spines.values(): sp.set_color('#333')

# Min separation vs speed
ax = axes[0,2]; ax.set_facecolor('#111')
spds = [r[0] for r in results]
mins = [r[2] for r in results]
cols_bar = [('#00ff88' if r[1]=='LOCKED' else
             '#ff4444' if r[1]=='PASSED_THROUGH' else
             '#ff6b35') for r in results]
bars = ax.bar(range(len(spds)), mins, color=cols_bar, alpha=0.8)
ax.set_xticks(range(len(spds)))
ax.set_xticklabels([f'{s:.2f}' for s in spds], rotation=45, fontsize=6)
ax.axhline(y=TAU_NUCLEAR*10, color='red', linestyle='--', linewidth=1)
ax.set_title('Min Separation by Speed\n(green=locked, orange=bounced)',
             color='white', fontsize=9)
ax.set_xlabel('Approach Speed', color='#888', fontsize=7)
ax.set_ylabel('Min Sep (cells)', color='#888', fontsize=7)
ax.tick_params(colors='#555', labelsize=6)
for sp in ax.spines.values(): sp.set_color('#333')

# Detailed view of a locked collision if any
locked_results = [(s,r,m,c,h,p) for s,r,m,c,h in results 
                  for p in [None] if r=='LOCKED']
# Re-run best locked case for detail
if capture_speed:
    result, min_sep, coupled_step, history, final_pins = run_collision(
        capture_speed, steps=3000)
    
    ax = axes[1,0]; ax.set_facecolor('#111')
    ax.plot(history['sep'], color='#00d4ff', linewidth=2, label='separation')
    if coupled_step:
        ax.axvline(x=coupled_step, color='red', linestyle='--',
                   linewidth=1.5, label=f'lock step {coupled_step}')
    ax.set_title(f'Lock Detail (v={capture_speed})', color='white', fontsize=9)
    ax.set_xlabel('Step', color='#888', fontsize=7)
    ax.set_ylabel('Distance', color='#888', fontsize=7)
    ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
    ax.tick_params(colors='#555', labelsize=6)
    for sp in ax.spines.values(): sp.set_color('#333')
    
    ax = axes[1,1]; ax.set_facecolor('#111')
    ax.plot(history['spd_a'], color='#00d4ff', linewidth=1.5, label='pin A')
    ax.plot(history['spd_b'], color='#ff6b35', linewidth=1.5, label='pin B')
    if coupled_step:
        ax.axvline(x=coupled_step, color='red', linestyle='--', linewidth=1.5)
    ax.set_title('Pin Speeds During Lock', color='white', fontsize=9)
    ax.set_xlabel('Step', color='#888', fontsize=7)
    ax.set_ylabel('Speed', color='#888', fontsize=7)
    ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
    ax.tick_params(colors='#555', labelsize=6)
    for sp in ax.spines.values(): sp.set_color('#333')

    ax = axes[1,2]; ax.set_facecolor('#111')
    ax.plot(history['grad_mag'], color='#00ff88', linewidth=1.5,
            label='gradient mag')
    ax.axhline(y=COUPLING_THR, color='red', linestyle='--',
               linewidth=1.5, label=f'threshold')
    if coupled_step:
        ax.axvline(x=coupled_step, color='yellow', linestyle='--',
                   linewidth=1.5, label=f'lock')
    ax.set_title('Nuclear Gradient at Lock', color='white', fontsize=9)
    ax.set_xlabel('Step', color='#888', fontsize=7)
    ax.set_ylabel('|∇Ψ_nuclear|', color='#888', fontsize=7)
    ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
    ax.tick_params(colors='#555', labelsize=6)
    for sp in ax.spines.values(): sp.set_color('#333')
else:
    # Show gradient analysis instead
    ax = axes[1,0]; ax.set_facecolor('#111')
    seps_test = np.linspace(0.1, 20, 200)
    grads = []
    for s in seps_test:
        r = s + TAU_NUCLEAR
        g = 1.0 / r**2
        grads.append(g)
    ax.plot(seps_test, grads, color='#00ff88', linewidth=2)
    ax.axhline(y=COUPLING_THR, color='red', linestyle='--',
               linewidth=1.5, label=f'threshold={COUPLING_THR}')
    ax.set_title('Nuclear Field Gradient vs Distance\n(coupling where line crosses threshold)',
                 color='white', fontsize=9)
    ax.set_xlabel('Distance (cells)', color='#888', fontsize=7)
    ax.set_ylabel('Gradient magnitude', color='#888', fontsize=7)
    ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
    ax.tick_params(colors='#555', labelsize=6)
    ax.set_ylim(0, min(5, max(grads)))
    for sp in ax.spines.values(): sp.set_color('#333')
    
    # Find theoretical coupling distance
    coupling_dist = (1.0/COUPLING_THR)**0.5 - TAU_NUCLEAR
    print(f"\nTheoretical coupling distance: {coupling_dist:.4f} cells")
    print(f"Pins need to reach separation < {coupling_dist:.4f} to lock")
    print(f"This is sub-grid scale - TAU_NUCLEAR may need further reduction")
    
    for ax in [axes[1,1], axes[1,2]]:
        ax.set_facecolor('#111')
        ax.text(0.5, 0.5, 'No locking\nobserved',
                transform=ax.transAxes, color='#888',
                ha='center', va='center', fontsize=12)
        for sp in ax.spines.values(): sp.set_color('#333')

plt.tight_layout()
fname = os.path.join(OUTPUT_DIR, 'collision_results.png')
plt.savefig(fname, dpi=100, facecolor='#0a0a0a', bbox_inches='tight')
plt.close()
print(f"\nPlot saved: {fname}")
