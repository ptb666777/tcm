# VSM OUTPUT MODULE
# Handles: CSV log, small PNG snapshots, binary VTI for ParaView, text summary
# Keeps compute and output completely separate

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import base64, struct, os, csv
from collections import defaultdict

class VSMOutput:
    def __init__(self, output_dir, scenario_name, N):
        self.output_dir = output_dir
        self.N = N
        self.scenario_name = scenario_name
        os.makedirs(output_dir, exist_ok=True)

        # CSV log
        self.csv_path = os.path.join(output_dir, 'log.csv')
        self.csv_file = open(self.csv_path, 'w', newline='')
        self.csv_writer = None  # init on first write when we know columns

        # History for final plot
        self.history = defaultdict(list)
        self.steps = []

        print(f"Output: {output_dir}/")
        print(f"  log.csv       - all metrics every LOG_EVERY steps")
        print(f"  step_*.png    - small slice images every SNAP_EVERY steps")
        print(f"  psi_*.vti     - ParaView 3D volumes every VTI_EVERY steps")
        print(f"  summary.txt   - final state always written")
        print()

    def record(self, step, pins, psi):
        N = self.N
        self.steps.append(step)

        # Build row
        row = {'step': step}
        row['psi_max']  = float(psi.max())
        row['psi_min']  = float(psi.min())
        row['psi_mean'] = float(psi.mean())

        for i, p in enumerate(pins):
            ix,iy,iz = int(p['pos'][0])%N, int(p['pos'][1])%N, int(p['pos'][2])%N
            pl = float(psi[ix,iy,iz])
            spd = float(np.linalg.norm(p['vel']))
            tr  = 1.0 / (1.0 + abs(pl))
            row[f'p{i}_x']   = round(float(p['pos'][0]), 3)
            row[f'p{i}_y']   = round(float(p['pos'][1]), 3)
            row[f'p{i}_z']   = round(float(p['pos'][2]), 3)
            row[f'p{i}_spd'] = round(spd, 6)
            row[f'p{i}_tr']  = round(tr, 6)
            self.history[f'spd_{i}'].append(spd)
            self.history[f'tr_{i}'].append(tr)

        for i in range(len(pins)):
            for j in range(i+1, len(pins)):
                d = self._pdist(pins[i], pins[j])
                row[f'sep_{i}_{j}'] = round(d, 3)
                self.history[f'sep_{i}_{j}'].append(d)

        self.history['psi_max'].append(row['psi_max'])
        self.history['psi_min'].append(row['psi_min'])
        self.history['psi_mean'].append(row['psi_mean'])

        # Write CSV header on first row
        if self.csv_writer is None:
            self.csv_writer = csv.DictWriter(
                self.csv_file, fieldnames=list(row.keys()))
            self.csv_writer.writeheader()
        self.csv_writer.writerow(row)
        self.csv_file.flush()

    def save_png(self, step, pins, psi):
        N = self.N
        mid = N // 2
        vm = float(np.percentile(np.abs(psi), 99)) or 1.0

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4),
                                        facecolor='#0a0a0a')
        for ax, data, title in [
            (ax1, psi[:,:,mid].T, f'XY  z={mid}'),
            (ax2, psi[:,mid,:].T, f'XZ  y={mid}'),
        ]:
            ax.imshow(data, origin='lower', cmap='RdBu_r',
                      interpolation='bilinear', vmin=-vm, vmax=vm)
            for p in pins:
                c = '#00ffff' if p['omega'] > 0 else '#ff4444'
                ax.plot(p['pos'][0],
                        p['pos'][2] if 'XZ' in title else p['pos'][1],
                        'o', color=c, ms=5,
                        markeredgecolor='white', mew=0.5)
            ax.set_title(f'{title}  step {step}',
                         color='white', fontsize=8)
            ax.tick_params(colors='#555', labelsize=6)
            ax.set_facecolor('#0a0a0a')

        plt.tight_layout(pad=0.5)
        fname = os.path.join(self.output_dir, f'step_{step:06d}.png')
        plt.savefig(fname, dpi=80, facecolor='#0a0a0a',
                    bbox_inches='tight')
        plt.close(fig)

    def save_vti(self, step, psi):
        N = self.N
        data = psi.astype(np.float32).flatten(order='F')
        raw = struct.pack('<I', len(data)*4) + data.tobytes()
        encoded = base64.b64encode(raw).decode('ascii')
        fname = os.path.join(self.output_dir, f'psi_{step:06d}.vti')
        with open(fname, 'w') as f:
            f.write('<?xml version="1.0"?>\n')
            f.write('<VTKFile type="ImageData" version="0.1" '
                    'byte_order="LittleEndian" encoding="base64">\n')
            f.write(f'  <ImageData WholeExtent="0 {N-1} 0 {N-1} 0 {N-1}" '
                    f'Origin="0 0 0" Spacing="1 1 1">\n')
            f.write(f'    <Piece Extent="0 {N-1} 0 {N-1} 0 {N-1}">\n')
            f.write('      <PointData Scalars="Psi">\n')
            f.write('        <DataArray type="Float32" Name="Psi" '
                    'format="binary">\n')
            f.write(f'          {encoded}\n')
            f.write('        </DataArray>\n')
            f.write('      </PointData>\n')
            f.write('    </Piece>\n')
            f.write('  </ImageData>\n')
            f.write('</VTKFile>\n')

    def save_summary(self, pins, psi, total_steps, elapsed):
        N = self.N
        fname = os.path.join(self.output_dir, 'summary.txt')
        with open(fname, 'w') as f:
            f.write(f"VSM Summary - {self.scenario_name}\n")
            f.write(f"{'='*50}\n")
            f.write(f"Steps: {total_steps}  Time: {elapsed:.1f}s\n")
            f.write(f"Grid: {N}^3\n\n")
            f.write("FINAL PIN STATES\n")
            for i, p in enumerate(pins):
                ix,iy,iz = int(p['pos'][0])%N,int(p['pos'][1])%N,int(p['pos'][2])%N
                pl = float(psi[ix,iy,iz])
                spd = float(np.linalg.norm(p['vel']))
                f.write(f"  Pin {i:>2} {p['label']:>4} "
                        f"omega={p['omega']:+.1f}  "
                        f"pos=[{p['pos'][0]:.2f},{p['pos'][1]:.2f},{p['pos'][2]:.2f}]  "
                        f"spd={spd:.6f}  psi={pl:.6f}\n")
            f.write("\nSEPARATIONS\n")
            for i in range(len(pins)):
                for j in range(i+1, len(pins)):
                    key = f'sep_{i}_{j}'
                    if key in self.history and self.history[key]:
                        dists = self.history[key]
                        drift = dists[-1] - dists[0]
                        beh = ('attracted' if drift < -0.5
                               else 'repelled' if drift > 0.5
                               else 'stable')
                        f.write(f"  p{i}({pins[i]['label']})-p{j}({pins[j]['label']}): "
                                f"start={dists[0]:.2f} final={dists[-1]:.2f} "
                                f"drift={drift:+.2f} [{beh}]\n")
            f.write(f"\nPSI FIELD\n")
            f.write(f"  max={psi.max():.4f}  min={psi.min():.4f}  "
                    f"mean={psi.mean():.6f}\n")
            f.write(f"\nParaView: File->Open->psi_*.vti (as series)\n")
            f.write(f"  Apply -> Filters -> Contour -> set value ~0.05\n")
            f.write(f"  Or: Filters -> Threshold for density shells\n")
        print(f"Summary: {fname}")

    def save_final_plot(self, pins):
        if not self.steps:
            return
        fig, axes = plt.subplots(2, 2, figsize=(11,7), facecolor='#0a0a0a')
        fig.suptitle(f'VSM - {self.scenario_name}', color='white', fontsize=11)
        cols = ['#00d4ff','#ff6b35','#00ff88','#ff00aa',
                '#ffdd00','#aa00ff','#ffffff','#88ff00']

        # Separations
        ax = axes[0,0]; ax.set_facecolor('#111')
        plotted = 0
        for i in range(len(pins)):
            for j in range(i+1, len(pins)):
                k = f'sep_{i}_{j}'
                if k in self.history and plotted < 8:
                    ax.plot(self.steps[:len(self.history[k])],
                            self.history[k],
                            color=cols[plotted%len(cols)],
                            linewidth=1.0, alpha=0.8,
                            label=f"p{i}-p{j}")
                    plotted += 1
        ax.set_title('Separations', color='white', fontsize=9)
        ax.set_xlabel('Step', color='#888', fontsize=7)
        ax.set_ylabel('Cells', color='#888', fontsize=7)
        if plotted <= 6:
            ax.legend(fontsize=6, facecolor='#222', labelcolor='white')
        ax.tick_params(colors='#555', labelsize=6)
        for sp in ax.spines.values(): sp.set_color('#333')

        # Speeds
        ax = axes[0,1]; ax.set_facecolor('#111')
        for i, p in enumerate(pins[:8]):
            k = f'spd_{i}'
            if k in self.history:
                ax.plot(self.steps[:len(self.history[k])],
                        self.history[k],
                        color=cols[i%len(cols)],
                        linewidth=1.0, alpha=0.8,
                        label=p['label'])
        ax.set_title('Pin Speeds', color='white', fontsize=9)
        ax.set_xlabel('Step', color='#888', fontsize=7)
        ax.tick_params(colors='#555', labelsize=6)
        for sp in ax.spines.values(): sp.set_color('#333')

        # Time rates
        ax = axes[1,0]; ax.set_facecolor('#111')
        for i, p in enumerate(pins[:8]):
            k = f'tr_{i}'
            if k in self.history:
                ax.plot(self.steps[:len(self.history[k])],
                        self.history[k],
                        color=cols[i%len(cols)],
                        linewidth=1.0, alpha=0.8)
        ax.axhline(1.0, color='#444', linestyle='--', linewidth=1)
        ax.set_title('Local Time Rates', color='white', fontsize=9)
        ax.set_xlabel('Step', color='#888', fontsize=7)
        ax.tick_params(colors='#555', labelsize=6)
        for sp in ax.spines.values(): sp.set_color('#333')

        # Psi global
        ax = axes[1,1]; ax.set_facecolor('#111')
        ax.plot(self.steps, self.history['psi_max'],
                color='#ff6b35', label='max', linewidth=1.5)
        ax.plot(self.steps, self.history['psi_mean'],
                color='#00d4ff', label='mean', linewidth=1.5)
        ax.plot(self.steps, self.history['psi_min'],
                color='#00ff88', label='min', linewidth=1.5)
        ax.axhline(0, color='#444', linewidth=1)
        ax.set_title('Global Ψ', color='white', fontsize=9)
        ax.set_xlabel('Step', color='#888', fontsize=7)
        ax.legend(fontsize=7, facecolor='#222', labelcolor='white')
        ax.tick_params(colors='#555', labelsize=6)
        for sp in ax.spines.values(): sp.set_color('#333')

        plt.tight_layout()
        fname = os.path.join(self.output_dir, 'measurements.png')
        plt.savefig(fname, dpi=100, facecolor='#0a0a0a', bbox_inches='tight')
        plt.close(fig)
        print(f"Plot: {fname}")

    def close(self):
        self.csv_file.close()

    def _pdist(self, a, b):
        N = self.N
        d = np.minimum(np.abs(a['pos']-b['pos']), N-np.abs(a['pos']-b['pos']))
        return float(np.sqrt(np.sum(d**2)))

    @staticmethod
    def paraview_instructions():
        return """
PARAVIEW 3D INSTRUCTIONS
========================
1. File -> Open -> select psi_*.vti -> OK (loads as series)
2. Click Apply in Properties panel
3. For isosurface view:
   Filters -> Common -> Contour
   Set isosurface value to 0.1 (positive field) or -0.1 (negative)
   Apply -> renders 3D surface of Psi field
4. For volume view:
   Change representation dropdown from 'Surface' to 'Volume'
   Adjust opacity in Color Map Editor
5. Pin positions visible as bright spots in field
6. Use animation controls to play through time steps
"""
