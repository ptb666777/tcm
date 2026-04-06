# VORTEX SUBSTRATE MODEL v4b
# Clean separation of compute and output
# Uses vsm_output.py for all file writing
# 1/r Psi falloff - Newtonian gravity range
# True 3D pin initialization

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import os, time, math
from vsm_output import VSMOutput

# ─────────────────────────────────────────────
# PARAMETERS
# ─────────────────────────────────────────────
N          = 128
TAU        = 1.0
DT         = 0.05
DAMP       = 0.99
SNAP_EVERY = 100    # PNG snapshot
VTI_EVERY  = 200    # ParaView 3D volume
LOG_EVERY  = 10     # CSV log
LIVE_EVERY = 100    # live window update (0 = disabled)
OUTPUT_DIR = 'vsm_output'

_coords = np.arange(N, dtype=np.float32)

def make_pin(pos, rho=1.0, omega=1.0, label=''):
    return {'pos':np.array(pos,dtype=np.float64),
            'rho':float(rho),'omega':float(omega),
            'vel':np.zeros(3),'label':label}

# ─────────────────────────────────────────────
# PSI - 1/r falloff (Newtonian gravity range)
# ─────────────────────────────────────────────
def compute_psi(pins):
    if not pins: return np.zeros((N,N,N),dtype=np.float32)
    positions = np.array([p['pos'] for p in pins], dtype=np.float32)
    weights   = np.array([p['rho']*p['omega'] for p in pins], dtype=np.float32)
    px,py,pz  = positions[:,0],positions[:,1],positions[:,2]
    dx = np.minimum(np.abs(px[:,None]-_coords[None,:]),
                    N-np.abs(px[:,None]-_coords[None,:]))
    dy = np.minimum(np.abs(py[:,None]-_coords[None,:]),
                    N-np.abs(py[:,None]-_coords[None,:]))
    dz = np.minimum(np.abs(pz[:,None]-_coords[None,:]),
                    N-np.abs(pz[:,None]-_coords[None,:]))
    dx2,dy2,dz2 = dx**2, dy**2, dz**2
    psi = np.zeros((N,N,N),dtype=np.float32)
    for i in range(len(pins)):
        r = np.sqrt(dx2[i,:,None,None] +
                    dy2[i,None,:,None] +
                    dz2[i,None,None,:]) + TAU
        psi += weights[i] / r
    return psi

def compute_gradient(psi):
    gx = (np.roll(psi,-1,0)-np.roll(psi,1,0))*0.5
    gy = (np.roll(psi,-1,1)-np.roll(psi,1,1))*0.5
    gz = (np.roll(psi,-1,2)-np.roll(psi,1,2))*0.5
    return gx,gy,gz

def step_pins(pins, psi, gx, gy, gz):
    for p in pins:
        ix,iy,iz = int(p['pos'][0])%N,int(p['pos'][1])%N,int(p['pos'][2])%N
        tr = 1.0/(1.0+abs(float(psi[ix,iy,iz])))
        force = np.array([-float(gx[ix,iy,iz]),
                          -float(gy[ix,iy,iz]),
                          -float(gz[ix,iy,iz])])
        p['vel'] += force*DT*tr
        p['vel'] *= DAMP
        p['pos'] = (p['pos']+p['vel']*DT)%N

def pdist(a,b):
    d=np.minimum(np.abs(a['pos']-b['pos']),N-np.abs(a['pos']-b['pos']))
    return float(np.sqrt(np.sum(d**2)))

# ─────────────────────────────────────────────
# 3D SPHERE INIT
# ─────────────────────────────────────────────
def sphere_pins(n, radius, center, omega_sign, prefix):
    pins = []
    golden = math.pi*(3-math.sqrt(5))
    for i in range(n):
        y = 1-(i/max(n-1,1))*2
        r = math.sqrt(max(1-y*y,0))
        theta = golden*i
        x,z = math.cos(theta)*r, math.sin(theta)*r
        pos = [(center[0]+x*radius)%N,
               (center[1]+y*radius)%N,
               (center[2]+z*radius)%N]
        pins.append(make_pin(pos,omega=omega_sign,label=f'{prefix}{i}'))
    return pins

# ─────────────────────────────────────────────
# LIVE DISPLAY
# ─────────────────────────────────────────────
_fig = _axes = None

def init_live():
    global _fig,_axes
    _fig = plt.figure(figsize=(12,5),facecolor='#0a0a0a')
    gs = GridSpec(1,3,figure=_fig,wspace=0.3)
    _axes = [_fig.add_subplot(gs[0,0]),
             _fig.add_subplot(gs[0,1]),
             _fig.add_subplot(gs[0,2])]
    _fig.suptitle('VSM v4b',color='white',fontsize=10)
    plt.ion(); plt.show()

def update_live(pins,psi,step):
    if _fig is None: return
    mid=N//2
    vm=float(np.percentile(np.abs(psi),99)) or 1.0
    for ax,(data,title) in zip(_axes[:2],[
        (psi[:,:,mid].T,f'XY z={mid} step {step}'),
        (psi[:,mid,:].T,f'XZ y={mid}')]):
        ax.cla()
        ax.imshow(data,origin='lower',cmap='RdBu_r',
                  interpolation='bilinear',vmin=-vm,vmax=vm)
        for p in pins:
            c='#00ffff' if p['omega']>0 else '#ff4444'
            ax.plot(p['pos'][0],
                    p['pos'][2] if 'XZ' in title else p['pos'][1],
                    'o',color=c,ms=5,markeredgecolor='white',mew=0.4)
        ax.set_title(title,color='white',fontsize=8)
        ax.tick_params(colors='#555',labelsize=6)
    # Radial profile
    ax=_axes[2]; ax.cla(); ax.set_facecolor('#111')
    if pins:
        p0=pins[0]['pos'].astype(np.float32)
        dx=np.minimum(np.abs(_coords[:,None,None]-p0[0]),
                      N-np.abs(_coords[:,None,None]-p0[0]))
        dy=np.minimum(np.abs(_coords[None,:,None]-p0[1]),
                      N-np.abs(_coords[None,:,None]-p0[1]))
        dz=np.minimum(np.abs(_coords[None,None,:]-p0[2]),
                      N-np.abs(_coords[None,None,:]-p0[2]))
        r=np.sqrt(dx**2+dy**2+dz**2).flatten()
        pf=psi.flatten()
        rb=np.linspace(0,N//2,40)
        pm=[float(pf[(r>=rb[k])&(r<rb[k+1])].mean())
            if ((r>=rb[k])&(r<rb[k+1])).any() else 0
            for k in range(len(rb)-1)]
        ax.plot(rb[:-1],pm,color='#ff6b35',linewidth=2)
        ax.fill_between(rb[:-1],pm,0,alpha=0.15,color='#ff6b35')
        ax.axhline(0,color='#444',linewidth=1)
    ax.set_title('Ψ radial pin 0',color='white',fontsize=8)
    ax.tick_params(colors='#555',labelsize=6)
    for sp in ax.spines.values(): sp.set_color('#333')
    _fig.canvas.draw(); _fig.canvas.flush_events()

# ─────────────────────────────────────────────
# SCENARIOS
# ─────────────────────────────────────────────
half=N//2
SCENARIOS = {
    'single':   {'pins':[make_pin([half,half,half],label='H')],
                 'steps':1000,'desc':'Single pin baseline'},
    'same':     {'pins':[make_pin([half-8,half,half],omega=1.0,label='A+'),
                         make_pin([half+8,half,half],omega=1.0,label='B+')],
                 'steps':5000,'desc':'Same spin bond test'},
    'opposite': {'pins':[make_pin([half-8,half,half],omega= 1.0,label='A+'),
                         make_pin([half+8,half,half],omega=-1.0,label='B-')],
                 'steps':5000,'desc':'Opposite spin charge test'},
    'carbon':   {'pins':[make_pin([half+4,half+4,half+4],label='C1'),
                         make_pin([half-4,half-4,half+4],label='C2'),
                         make_pin([half-4,half+4,half-4],label='C3'),
                         make_pin([half+4,half-4,half-4],label='C4'),
                         make_pin([half,  half,  half+6],label='C5'),
                         make_pin([half,  half,  half-6],label='C6')],
                 'steps':5000,'desc':'Carbon 6-pin tetrahedral'},
    '10v10':    {'pins':(sphere_pins(10,8,[half-20,half,half], 1.0,'P')+
                         sphere_pins(10,8,[half+20,half,half],-1.0,'N')),
                 'steps':5000,'desc':'10 pos vs 10 neg 3D spheres'},
    'hydrogen': {'pins':[make_pin([np.random.uniform(20,N-20),
                                   np.random.uniform(20,N-20),
                                   np.random.uniform(20,N-20)],
                                  omega=1.0,label=f'H{i}')
                         for i in range(20)],
                 'steps':5000,'desc':'20 hydrogen pins random 3D'},
}

# ── ACTIVE ──────────────────────────────────
ACTIVE = '10v10'

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
np.random.seed(42)
sc    = SCENARIOS[ACTIVE]
pins  = sc['pins']
STEPS = sc['steps']

print("="*60)
print(f"VSM v4b  |  {ACTIVE}  |  {sc['desc']}")
print(f"Grid: {N}^3  Pins: {len(pins)}  Steps: {STEPS}")
print(f"Psi: 1/r falloff (Newtonian range)")
print()
for i,p in enumerate(pins):
    print(f"  {i:>2}: {p['label']:>4} ω={p['omega']:+.0f} "
          f"[{p['pos'][0]:.0f},{p['pos'][1]:.0f},{p['pos'][2]:.0f}]")
print()
print(VSMOutput.paraview_instructions())

out = VSMOutput(OUTPUT_DIR, ACTIVE, N)

if LIVE_EVERY > 0:
    init_live()

t0 = time.time()
step_times = []

for s in range(STEPS):
    ts = time.time()
    psi = compute_psi(pins)
    gx,gy,gz = compute_gradient(psi)
    step_pins(pins,psi,gx,gy,gz)
    step_times.append(time.time()-ts)

    if s % LOG_EVERY  == 0: out.record(s,pins,psi)
    if s % SNAP_EVERY == 0: out.save_png(s,pins,psi)
    if s % VTI_EVERY  == 0: out.save_vti(s,psi)
    if LIVE_EVERY>0 and s % LIVE_EVERY == 0:
        update_live(pins,psi,s)

    if s % 100 == 0:
        avg = np.mean(step_times[-50:]) if step_times else 0
        eta = avg*(STEPS-s)
        seps=[f"p0-p1:{pdist(pins[0],pins[1]):.1f}"] if len(pins)>1 else []
        print(f"step {s:>5}/{STEPS}  {avg*1000:.0f}ms/step  "
              f"ETA {eta/60:.1f}min  {' '.join(seps)}")

elapsed = time.time()-t0
print(f"\nDone {elapsed/60:.1f}min")

out.save_summary(pins,psi,STEPS,elapsed)
out.save_final_plot(pins)
out.close()

print(f"\nAll output in: {OUTPUT_DIR}/")
print("CSV log: log.csv  (share this for analysis)")
print("3D render: psi_*.vti in ParaView")

if LIVE_EVERY > 0:
    plt.ioff(); plt.show()
