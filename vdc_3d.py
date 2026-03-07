import numpy as np

N = 32  # 3D grid size (small for laptop; 128+ needs GPU/parallel)
grid = np.zeros((N, N, N))  # Density grid
velocity = np.zeros((N, N, N, 3))  # Velocity field (3D)
xx, yy, zz = np.meshgrid(np.arange(N), np.arange(N), np.arange(N))  # Coords

def torus_dist(x1, y1, z1, x2, y2, z2, N):
    dx = np.minimum(np.abs(x1 - x2), N - np.abs(x1 - x2))
    dy = np.minimum(np.abs(y1 - y2), N - np.abs(y1 - y2))
    dz = np.minimum(np.abs(z1 - z2), N - np.abs(z1 - z2))
    return np.sqrt(dx**2 + dy**2 + dz**2)

# Init big central boom
grid[N//2, N//2, N//2] += 50

# Mega-vortex (3D swirl around center)
center = np.array([N//2, N//2, N//2])
for i in range(N):
    for j in range(N):
        for k in range(N):
            r_vec = np.array([i - center[0], j - center[1], k - center[2]])
            r = np.linalg.norm(r_vec)
            if r > 0:
                # 3D vortex (toroidal flow)
                theta = np.arctan2(r_vec[1], r_vec[0])
                phi = np.arccos(r_vec[2] / r)
                v_theta = 1 / (r + 1e-5)
                v_phi = 0.5 / (r + 1e-5)  # Add poloidal component
                vx = v_theta * -np.sin(theta) + v_phi * np.cos(phi) * np.cos(theta)
                vy = v_theta * np.cos(theta) + v_phi * np.cos(phi) * np.sin(theta)
                vz = -v_phi * np.sin(phi)
                velocity[i, j, k] = [vx, vy, vz]

steps = 50  # Short for laptop
density_history = []  # Save snapshots if needed

def manual_blur_3d(g):
    new_g = np.copy(g)
    for i in range(N):
        for j in range(N):
            for k in range(N):
                neighbors = (g[(i-1)%N, j, k] + g[(i+1)%N, j, k] +
                             g[i, (j-1)%N, k] + g[i, (j+1)%N, k] +
                             g[i, j, (k-1)%N] + g[i, j, (k+1)%N])
                new_g[i, j, k] = g[i, j, k] * 0.6 + neighbors * (0.1 / 3)  # Normalize for 3D
    return new_g

# No full 3D ascii—too big. Use slice vis if needed (e.g., print(grid[N//2,:,:]))

for step in range(steps):
    # Ripples from central
    ripples = np.zeros((N, N, N))
    dist = torus_dist(xx, yy, zz, N//2, N//2, N//2, N)
    phase = (dist - step * 1.0) % (2 * np.pi)
    ripples += np.cos(phase) / (dist + 1)
    
    grid += 0.05 * ripples
    
    # Advect density (3D version, slower)
    new_grid = np.zeros_like(grid)
    for i in range(N):
        for j in range(N):
            for k in range(N):
                vx, vy, vz = velocity[i, j, k]
                src_x = (i - vx * 0.5) % N
                src_y = (j - vy * 0.5) % N
                src_z = (k - vz * 0.5) % N
                ix, fx = int(src_x), src_x - int(src_x)
                iy, fy = int(src_y), src_y - int(src_y)
                iz, fz = int(src_z), src_z - int(src_z)
                # 3D interp (simple bilinear)
                val = (1-fx)*(1-fy)*(1-fz)*grid[ix%N, iy%N, iz%N] + \
                      fx*(1-fy)*(1-fz)*grid[(ix+1)%N, iy%N, iz%N] + \
                      (1-fx)*fy*(1-fz)*grid[ix%N, (iy+1)%N, iz%N] + \
                      fx*fy*(1-fz)*grid[(ix+1)%N, (iy+1)%N, iz%N] + \
                      (1-fx)*(1-fy)*fz*grid[ix%N, iy%N, (iz+1)%N] + \
                      fx*(1-fy)*fz*grid[(ix+1)%N, iy%N, (iz+1)%N] + \
                      (1-fx)*fy*fz*grid[ix%N, (iy+1)%N, (iz+1)%N] + \
                      fx*fy*fz*grid[(ix+1)%N, (iy+1)%N, (iz+1)%N]
                new_grid[i, j, k] = val
    grid = new_grid
    
    # Local pull to peaks (3D)
    peaks = grid > np.mean(grid) + np.std(grid)
    peak_positions = np.argwhere(peaks)
    for px, py, pz in peak_positions:
        for i in range(N):
            for j in range(N):
                for k in range(N):
                    r_vec = np.array([i - px, j - py, k - pz])
                    r = np.linalg.norm(r_vec)
                    if r > 0 and r < 10:
                        pull = (grid[px, py, pz] / r**2) * (r_vec / r)
                        velocity[i, j, k] -= 0.02 * pull
    
    grid = manual_blur_3d(grid)
    grid -= 0.02 * grid
    grid[grid < 0] = 0

# Stats (3D mean/std over volume)
mean_d = np.mean([np.mean(d) for d in density_history])
void_frac = np.mean([np.sum(d == 0) / (N**3) for d in density_history])
isolation = np.std(density_history[-1]) / np.mean(density_history[-1]) if np.mean(density_history[-1]) > 0 else 0
print(f"Mean density: {mean_d:.4f}")
print(f"Void fraction: {void_frac:.4f}")
print(f"Isolation: {isolation:.4f}")

# Slice vis (mid-plane density)
print("Final mid-slice:\n" + ascii_grid(density_history[-1][N//2,:,:]))