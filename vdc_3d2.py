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
                phi = np.arccos(r_vec[2] / r if r > 0 else 0)
                v_theta = 1 / (r + 1e-5)
                v_phi = 0.5 / (r + 1e-5)  # Add poloidal component
                vx = v_theta * -np.sin(theta) + v_phi * np.cos(phi) * np.cos(theta)
                vy = v_theta * np.cos(theta) + v_phi * np.cos(phi) * np.sin(theta)
                vz = -v_phi * np.sin(phi)
                velocity[i, j, k] = [vx, vy, vz]

steps = 50  # Short for laptop
density_history = []

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

def compute_vorticity_3d(v):
    vx, vy, vz = v[...,0], v[...,1], v[...,2]
    dvy_dx = (vy[2:, :, :] - vy[:-2, :, :]) / 2
    dvx_dy = (vx[:, 2:, :] - vx[:, :-2, :] ) / 2
    dvz_dx = (vz[2:, :, :] - vz[:-2, :, :] ) / 2
    dvx_dz = (vx[:, :, 2:] - vx[:, :, :-2] ) / 2
    dvz_dy = (vz[:, 2:, :] - vz[:, :-2, :] ) / 2
    dvy_dz = (vy[:, :, 2:] - vy[:, :, :-2] ) / 2
    omega = np.zeros((N, N, N, 3))
    omega[1:-1, 1:-1, 1:-1, 0] = dvy_dz - dvz_dy  # x-component curl
    omega[1:-1, 1:-1, 1:-1, 1] = dvz_dx - dvx_dz  # y-component
    omega[1:-1, 1:-1, 1:-1, 2] = dvx_dy - dvy_dx  # z-component
    return omega

def ascii_grid_2d_slice(g_slice):
    chars = ' .:*#&@'
    if g_slice.max() == g_slice.min():
        return '\n'.join('.' * N for _ in range(N))
    g_norm = (g_slice - g_slice.min()) / (g_slice.max() - g_slice.min() + 1e-10)
    ascii = '\n'.join(''.join(chars[min(int(v * (len(chars)-1)), len(chars)-1)] for v in row) for row in g_norm)
    return ascii

for step in range(steps):
    # Ripples from central
    ripples = np.zeros((N, N, N))
    dist = torus_dist(xx, yy, zz, N//2, N//2, N//2, N)
    phase = (dist - step * 1.0) % (2 * np.pi)
    ripples += np.cos(phase) / (dist + 1)
    
    # Lensing: Bend/amplify around peaks (3D)
    for i in range(N):
        for j in range(N):
            for k in range(N):
                if grid[i, j, k] > np.mean(grid):
                    neighbors = [(i-1)%N, (i+1)%N, (j-1)%N, (j+1)%N, (k-1)%N, (k+1)%N]
                    for ni in [neighbors[0], neighbors[1]]:
                        for nj in [neighbors[2], neighbors[3]]:
                            for nk in [neighbors[4], neighbors[5]]:
                                ripples[ni, nj, nk] *= 1.05
    
    grid += 0.05 * ripples
    
    # Geysers / mini booms from voids
    low_density = grid < np.mean(grid) * 0.5
    tear_positions = np.argwhere(low_density)
    if len(tear_positions) > 0:
        for tx, ty, tz in tear_positions[:3]:
            geyser_strength = np.random.uniform(5, 20)
            dist = torus_dist(xx, yy, zz, tx, ty, tz, N)
            phase = (dist - step * 0.5) % (2 * np.pi)
            geyser_ripples = np.cos(phase) / (dist + 1) * geyser_strength
            grid += 0.03 * geyser_ripples
            if grid[tx, ty, tz] > np.mean(grid):
                low_density[tx, ty, tz] = False  # Seal
    
    # Advect density (3D)
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
                # 3D interp
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
    
    # Red shift: Dim in thins (energy strip)
    grid[grid < np.mean(grid) * 0.5] *= 0.9

    # Vorticity for handedness emergence
    omega = compute_vorticity_3d(velocity)
    vorticity_history.append(omega.mean())
    
    density_history.append(grid.copy())

# Stats (3D)
mean_d = np.mean([np.mean(d) for d in density_history])
void_frac = np.mean([np.sum(d == 0) / (N**3) for d in density_history])
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

# Slice vis (mid-plane 2D slice for print)
print("Final mid-slice:\n" + ascii_grid_2d_slice(density_history[-1][N//2,:,:]))