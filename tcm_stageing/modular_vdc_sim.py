import numpy as np

# Modular VDC Sim: Functions for each force, compose in loop
N = 50
grid = np.zeros((N, N))
velocity = np.zeros((N, N, 2))
xx, yy = np.meshgrid(np.arange(N), np.arange(N))

def torus_dist(x1, y1, x2, y2, N):
    dx = np.abs(x1 - x2)
    dy = np.abs(y1 - y2)
    dx = np.minimum(dx, N - dx)
    dy = np.minimum(dy, N - dy)
    return np.sqrt(dx**2 + dy**2)

def add_booms(grid, num_booms=3, boom_radius=3):
    boom_positions = np.random.randint(0, N, size=(num_booms, 2))
    for px, py in boom_positions:
        dist = torus_dist(xx, yy, px, py, N)
        mask = dist < boom_radius
        grid[mask] += (boom_radius - dist[mask]) / boom_radius * 10
    return grid, boom_positions

def add_mega_vortex(velocity):
    center = np.array([N//2, N//2])
    for i in range(N):
        for j in range(N):
            r_vec = np.array([i - center[0], j - center[1]])
            r = np.linalg.norm(r_vec)
            if r > 0:
                theta = np.arctan2(r_vec[1], r_vec[0])
                v_theta = 1 / (r + 1e-5)
                velocity[i, j] = v_theta * np.array([-np.sin(theta), np.cos(theta)])
    return velocity

def apply_ripples(grid, boom_positions, step, wave_speed=1.0):
    ripples = np.zeros((N, N))
    for px, py in boom_positions:
        dist = torus_dist(xx, yy, px, py, N)
        phase = (dist - wave_speed * step) % (2 * np.pi)
        ripples += np.cos(phase) / (dist + 1)
    grid += 0.1 * ripples
    return grid

def apply_drains(velocity, grid):
    high_density = grid > np.mean(grid) + np.std(grid)
    drain_positions = np.argwhere(high_density)[:2]
    for dx, dy in drain_positions:
        for i in range(N):
            for j in range(N):
                r_vec = np.array([i - dx, j - dy])
                r = np.linalg.norm(r_vec)
                if r > 0 and r < 5:
                    pull = (1 / r**2) * (r_vec / r)
                    velocity[i, j] -= 0.05 * pull
    return velocity

def advect_density(grid, velocity):
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
    return new_grid

def apply_thinning(grid, thinning_rate=0.05):
    grid = manual_blur(grid)
    grid -= thinning_rate * grid
    grid[grid < 0] = 0
    return grid

def manual_blur(g):
    new_g = np.copy(g)
    for i in range(N):
        for j in range(N):
            neighbors = (g[(i-1)%N, j] + g[(i+1)%N, j] +
                         g[i, (j-1)%N] + g[i, (j+1)%N])
            new_g[i, j] = g[i, j] * 0.6 + neighbors * 0.1
    return new_g

def ascii_grid(g):
    chars = ' .:*#&@'
    if g.max() == g.min():
        return '\n'.join('.' * N for _ in range(N))
    g_norm = (g - g.min()) / (g.max() - g.min() + 1e-10)
    ascii = '\n'.join(''.join(chars[min(int(v * (len(chars)-1)), len(chars)-1)]
                            for v in row) for row in g_norm)
    return ascii

def compute_light(grid):
    light_grid = grid.copy()
    light_grid[grid < 0.5 * np.mean(grid)] *= 0.9
    return light_grid

# Init modules
grid, boom_positions = add_booms(grid)
velocity = add_mega_vortex(velocity)
steps = 30
density_history = []

for step in range(steps):
    grid = apply_ripples(grid, boom_positions, step)
    velocity = apply_drains(velocity, grid)
    grid = advect_density(grid, velocity)
    grid = apply_thinning(grid)
    density_history.append(grid.copy())

# Outputs
print("Initial Density (Booms):\n" + ascii_grid(density_history[0]) + "\n")
print("Mid Density (After Ripples/Vortices):\n" + ascii_grid(density_history[steps//2]) + "\n")
print("Final Density (After Thinning/Isolation):\n" + ascii_grid(density_history[-1]) + "\n")
print("Final Light (Redshift Strip):\n" + ascii_grid(compute_light(density_history[-1])) + "\n")

# Stats
mean_density = np.mean([np.mean(d) for d in density_history])
void_fraction = np.mean([np.sum(d == 0) / (N*N) for d in density_history])
clump_isolation = np.std(density_history[-1]) / np.mean(density_history[-1]) if np.mean(density_history[-1]) > 0 else 0
print(f"Mean density evolution: {mean_density:.4f}")
print(f"Average void fraction: {void_fraction:.4f}")
print(f"Clump isolation metric: {clump_isolation:.4f}")
print("Modular sim complete")</parameter>
</xai:function_call>