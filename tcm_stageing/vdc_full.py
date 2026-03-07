import numpy as np

N = 50  # Grid size
grid = np.zeros((N, N))  # Density (high = thick cloud/clumps)
velocity = np.zeros((N, N, 2))  # Velocity for pulls/vortices
xx, yy = np.meshgrid(np.arange(N), np.arange(N))  # Coord mesh

def torus_dist(x1, y1, x2, y2, N):
    dx = np.abs(x1 - x2)
    dy = np.abs(y1 - y2)
    dx = np.minimum(dx, N - dx)
    dy = np.minimum(dy, N - dy)
    return np.sqrt(dx**2 + dy**2)

# Init big central boom
grid[N//2, N//2] += 50

# Mega-vortex (spine/attractor, slight clockwise seed)
center = np.array([N//2, N//2])
for i in range(N):
    for j in range(N):
        r_vec = np.array([i - center[0], j - center[1]])
        r = np.linalg.norm(r_vec)
        if r > 0:
            theta = np.arctan2(r_vec[1], r_vec[0])
            v_theta = 1 / (r + 1e-5)
            velocity[i, j] = v_theta * np.array([-np.sin(theta), np.cos(theta)])

steps = 100
density_history = []
vorticity_history = []

def manual_blur(g):
    new_g = np.copy(g)
    for i in range(N):
        for j in range(N):
            neighbors = (g[(i-1)%N, j] + g[(i+1)%N, j] + g[i, (j-1)%N] + g[i, (j+1)%N])
            new_g[i, j] = g[i, j] * 0.6 + neighbors * 0.1
    return new_g

def compute_vorticity(v):
    vx, vy = v[:,:,0], v[:,:,1]
    dvx_dy = (vx[:, 2:] - vx[:, :-2]) / 2
    dvy_dx = (vy[2:, :] - vy[:-2, :]) / 2
    omega = np.zeros((N, N))
    omega[1:-1, 1:-1] = dvy_dx - dvx_dy
    return omega

def ascii_grid(g):
    chars = ' .:*#&@'
    if g.max() == g.min():
        return '\n'.join('.' * N for _ in range(N))
    g_norm = (g - g.min()) / (g.max() - g.min() + 1e-10)
    ascii = '\n'.join(''.join(chars[min(int(v * (len(chars)-1)), len(chars)-1)] for v in row) for row in g_norm)
    return ascii

for step in range(steps):
    # Ripples from central
    ripples = np.zeros((N, N))
    dist = torus_dist(xx, yy, N//2, N//2, N)
    phase = (dist - step * 1.0) % (2 * np.pi)
    ripples += np.cos(phase) / (dist + 1)
    
    # Lensing: Bend around peaks
    for i in range(N):
        for j in range(N):
            if grid[i, j] > np.mean(grid):
                neighbors = [(i-1)%N, (i+1)%N, (j-1)%N, (j+1)%N]
                for ni in [neighbors[0], neighbors[1]]:
                    for nj in [neighbors[2], neighbors[3]]:
                        ripples[ni, nj] *= 1.05
    
    grid += 0.05 * ripples
    
    # Mini booms / geysers from voids
    low_density = grid < np.mean(grid) * 0.5
    tear_positions = np.argwhere(low_density)
    if len(tear_positions) > 0:
        for tx, ty in tear_positions[:3]:
            geyser_strength = np.random.uniform(5, 20)
            dist = torus_dist(xx, yy, tx, ty, N)
            phase = (dist - step * 0.5) % (2 * np.pi)
            geyser_ripples = np.cos(phase) / (dist + 1) * geyser_strength
            grid += 0.03 * geyser_ripples
            if grid[tx, ty] > np.mean(grid):
                low_density[tx, ty] = False  # Seal
    
    # Advect density
    new_grid = np.zeros_like(grid)
    for i in range(N):
        for j in range(N):
            vx, vy = velocity[i, j]
            src_x = (i - vx * 0.5) % N
            src_y = (j - vy * 0.5) % N
            ix, fx = int(src_x), src_x - int(src_x)
            iy, fy = int(src_y), src_y - int(src_y)
            new_grid[i, j] = ((1-fx)*(1-fy)*grid[ix % N, iy % N] +
                              fx*(1-fy)*grid[(ix+1)%N, iy % N] +
                              (1-fx)*fy*grid[ix % N, (iy+1)%N] +
                              fx*fy*grid[(ix+1)%N, (iy+1)%N])
    grid = new_grid
    
    # Local pull to peaks
    peaks = grid > np.mean(grid) + np.std(grid)
    peak_positions = np.argwhere(peaks)
    for px, py in peak_positions:
        for i in range(N):
            for j in range(N):
                r_vec = np.array([i - px, j - py])
                r = np.linalg.norm(r_vec)
                if r > 0 and r < 10:
                    pull = (grid[px, py] / r**2) * (r_vec / r)
                    velocity[i, j] -= 0.02 * pull
    
    grid = manual_blur(grid)
    grid -= 0.02 * grid
    grid[grid < 0] = 0
    
    # Red shift: Dim in thins (energy strip)
    grid[grid < np.mean(grid) * 0.5] *= 0.9  # 10% dim per step in lows
    
    # Vorticity for handedness emergence
    omega = compute_vorticity(velocity)
    vorticity_history.append(omega.mean())
    
    density_history.append(grid.copy())

# Outputs (trimmed ascii)
print("Initial:\n" + ascii_grid(density_history[0]))
print("Mid:\n" + ascii_grid(density_history[steps//2]))
print("Final:\n" + ascii_grid(density_history[-1]))

mean_d = np.mean([np.mean(d) for d in density_history])
void_frac = np.mean([np.sum(d == 0) / (N*N) for d in density_history])
isolation = np.std(density_history[-1]) / np.mean(density_history[-1]) if np.mean(density_history[-1]) > 0 else 0
final_vorticity = vorticity_history[-1]
print(f"Mean density: {mean_d:.4f}")
print(f"Void fraction: {void_frac:.4f}")
print(f"Isolation: {isolation:.4f}")
print(f"Final average vorticity: {final_vorticity:.4f}")
print("Positive = counterclockwise, negative = clockwise")
if abs(final_vorticity) > 0.01:
    print("Bias detected toward", "counterclockwise" if final_vorticity > 0 else "clockwise")
else:
    print("No strong bias")
