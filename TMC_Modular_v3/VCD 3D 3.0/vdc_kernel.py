# -*- coding: utf-8 -*-
"""
VDC Simulation Kernel - Orchestrator
=====================================
The kernel is the OS of the simulation. It owns:
  - The shared universe state (grid, velocities, fields)
  - The simulation clock (step counter, epoch tracking)
  - Module registry (what physics is active)
  - The main loop (calls modules in correct order each step)
  - Health monitoring (catches instability before it corrupts)
  - Logging (records what happened and when)
  - Output (saves snapshots, config log)

Modules register themselves with the kernel.
The kernel calls them. Modules never call each other directly.
All shared state lives here, not inside modules.

Usage:
    from vdc_kernel import Kernel
    k = Kernel('vdc_config.txt')
    k.register(SubstrateModule())
    k.register(GravityModule())
    k.run()
"""

import numpy as np
import os
import sys
import time
import json
import traceback
from datetime import datetime

# ------------------------------------------------------------------ #
# UNIVERSE STATE
# Shared data structure passed to every module every step.
# Modules read from it, write to it.
# Kernel owns it - modules never create their own copies.
# ------------------------------------------------------------------ #
class UniverseState:
    def __init__(self, N):
        self.N = N

        # Matter density field - the primary field
        # Shape: (N, N, N)  Values: >= 0
        self.grid = np.zeros((N, N, N))

        # Velocity field (3 components)
        self.vx = np.zeros((N, N, N))
        self.vy = np.zeros((N, N, N))
        self.vz = np.zeros((N, N, N))

        # Wave field (substrate displacement + velocity)
        self.wave   = np.zeros((N, N, N))
        self.wave_v = np.zeros((N, N, N))

        # Substrate surface tension (0=failed, 1=intact)
        self.tension = np.ones((N, N, N))

        # Void age - how long each cell has been true void
        self.void_age = np.zeros((N, N, N))

        # Seal strength - how healed a former tear is
        self.seal_str = np.zeros((N, N, N))

        # Scalar fields available to any module
        # Modules can add their own fields here
        self.fields = {}

        # Subway reservoir - matter held below reality
        self.subway = 0.0

        # Current simulation epoch
        # 'plasma', 'cooling', 'structure'
        self.epoch = 'plasma'

        # Cooling factor (1.0 = hot plasma, cool_floor = cold)
        self.temperature = 1.0

        # Step counter (set by kernel)
        self.step = 0

    def speed(self):
        """Magnitude of velocity field"""
        return np.sqrt(self.vx**2 + self.vy**2 + self.vz**2)

    def intact(self):
        """Boolean mask: cells where substrate is intact"""
        return self.tension > 0.3

    def true_void(self):
        """Boolean mask: cells where substrate has completely failed"""
        return self.tension < 0.05

    def summary(self):
        """One-line health summary for logging"""
        return (f"matter={self.grid.sum():.0f} "
                f"core={np.percentile(self.grid,99):.3f} "
                f"void={self.true_void().mean():.3f} "
                f"subway={self.subway:.0f} "
                f"wave_E={0.5*(self.wave**2+self.wave_v**2).sum():.0f} "
                f"vort_mag={self.fields.get('vorticity_mag', np.array([0])).mean():.5f}")


# ------------------------------------------------------------------ #
# BASE MODULE
# All physics modules inherit from this.
# ------------------------------------------------------------------ #
class VDCModule:
    """
    Base class for all VDC physics modules.
    
    To create a module:
        class MyModule(VDCModule):
            name = "my_module"
            
            def initialize(self, state, cfg):
                # called once before simulation starts
                # read your parameters from cfg
                # set up any initial conditions on state
                pass
            
            def step(self, state, cfg):
                # called every simulation step
                # read from state, compute, write back to state
                # return a dict of metrics for logging (optional)
                return {}
            
            def health_check(self, state):
                # return None if healthy
                # return string describing problem if not
                return None
    """
    name = "unnamed_module"
    enabled = True

    def initialize(self, state, cfg):
        pass

    def step(self, state, cfg):
        return {}

    def health_check(self, state):
        return None


# ------------------------------------------------------------------ #
# CONFIG LOADER
# ------------------------------------------------------------------ #
class Config:
    def __init__(self, path):
        self._data = {}
        self.path = path
        if not os.path.exists(path):
            print(f"Config not found: {path}")
            print("Create vdc_config.txt in the same folder as vdc_kernel.py")
            sys.exit(1)
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.split('#')[0].strip()
                self._data[key] = val

    def get(self, key, default=None):
        return self._data.get(key, default)

    def int(self, key, default):
        return int(self._data.get(key, default))

    def float(self, key, default):
        return float(self._data.get(key, default))

    def str(self, key, default):
        return self._data.get(key, str(default))

    def bool(self, key, default):
        val = self._data.get(key, str(default)).lower()
        return val in ('true', '1', 'yes', 'on')

    def all(self):
        return dict(self._data)


# ------------------------------------------------------------------ #
# HEALTH MONITOR
# Watches for numerical instability.
# ------------------------------------------------------------------ #
class HealthMonitor:
    def __init__(self, cfg):
        self.max_density    = cfg.float('health_max_density',   1e8)
        self.max_wave       = cfg.float('health_max_wave',      1e6)
        self.max_velocity   = cfg.float('health_max_velocity',  100.0)
        self.max_subway     = cfg.float('health_max_subway',    1e9)
        self.warn_threshold = cfg.float('health_warn_density',  1e5)
        self.warnings       = []
        self.errors         = []

    def check(self, state, step):
        """
        Returns ('ok', None), ('warn', message), or ('error', message)
        """
        # Check for NaN/Inf first - these are fatal
        for name, arr in [('grid', state.grid),
                          ('wave', state.wave),
                          ('vx',   state.vx)]:
            if not np.isfinite(arr).all():
                msg = f"Step {step}: {name} contains NaN or Inf"
                self.errors.append(msg)
                return ('error', msg)

        # Check for runaway values
        if state.grid.max() > self.max_density:
            msg = f"Step {step}: density runaway ({state.grid.max():.2e} > {self.max_density:.2e})"
            self.errors.append(msg)
            return ('error', msg)

        if np.abs(state.wave).max() > self.max_wave:
            msg = f"Step {step}: wave runaway ({np.abs(state.wave).max():.2e})"
            self.errors.append(msg)
            return ('error', msg)

        if state.speed().max() > self.max_velocity:
            msg = f"Step {step}: velocity runaway ({state.speed().max():.2f})"
            self.errors.append(msg)
            return ('error', msg)

        if state.subway > self.max_subway:
            msg = f"Step {step}: subway overflow ({state.subway:.2e})"
            self.errors.append(msg)
            return ('error', msg)

        # Warnings - non-fatal but worth noting
        if state.grid.max() > self.warn_threshold:
            msg = f"Step {step}: high density warning ({state.grid.max():.2e})"
            if msg not in self.warnings:
                self.warnings.append(msg)
            return ('warn', msg)

        return ('ok', None)


# ------------------------------------------------------------------ #
# LOGGER
# Records what happens each step.
# ------------------------------------------------------------------ #
class SimLogger:
    def __init__(self, outdir, run_id):
        self.outdir = outdir
        self.run_id = run_id
        self.log_path = os.path.join(outdir, f'run_{run_id}.log')
        self.metrics_path = os.path.join(outdir, f'metrics_{run_id}.jsonl')
        self._log_file = open(self.log_path, 'w')
        self._metrics_file = open(self.metrics_path, 'w')

    def log(self, msg):
        timestamp = datetime.now().strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}"
        print(line)
        self._log_file.write(line + '\n')
        self._log_file.flush()

    def metrics(self, step, state, module_metrics):
        """Write machine-readable metrics for plotting later"""
        row = {
            'step':    step,
            'epoch':   state.epoch,
            'temp':    float(state.temperature),
            'matter':  float(state.grid.sum()),
            'core':    float(np.percentile(state.grid, 99)),
            'mean':    float(state.grid.mean()),
            'void':    float(state.true_void().mean()),
            'subway':  float(state.subway),
            'wave_E':  float(0.5*(state.wave**2+state.wave_v**2).sum()),
        }
        row.update(module_metrics)
        self._metrics_file.write(json.dumps(row) + '\n')
        self._metrics_file.flush()

    def close(self):
        self._log_file.close()
        self._metrics_file.close()


# ------------------------------------------------------------------ #
# OUTPUT MANAGER
# Handles saving snapshots in correct format for ParaView.
# ------------------------------------------------------------------ #
class OutputManager:
    def __init__(self, outdir, N):
        self.outdir = outdir
        self.N = N
        os.makedirs(outdir, exist_ok=True)

        # Try to load matplotlib
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            self._plt = plt
            self._has_mpl = True
        except ImportError:
            self._has_mpl = False

    def save_vti(self, state, step):
        """
        Save density field as VTK ImageData XML (.vti)
        Verified correct for ParaView 6.x
        Open in ParaView: File -> Open -> *.vti (load as series)
        Apply Threshold filter (min=0.5) to see structure
        """
        N = self.N
        fname = os.path.join(self.outdir, f"step_{step:05d}.vti")
        flat = state.grid.flatten(order='F')
        with open(fname, 'w') as f:
            f.write('<?xml version="1.0"?>\n')
            f.write('<VTKFile type="ImageData" version="0.1" '
                    'byte_order="LittleEndian">\n')
            f.write(f'<ImageData WholeExtent="0 {N-1} 0 {N-1} 0 {N-1}" '
                    f'Origin="0 0 0" Spacing="1 1 1">\n')
            f.write(f'<Piece Extent="0 {N-1} 0 {N-1} 0 {N-1}">\n')
            f.write('<PointData Scalars="density">\n')
            f.write('<DataArray type="Float32" Name="density" '
                    'format="ascii">\n')
            for i in range(0, len(flat), 6):
                f.write(' '.join(f'{v:.4f}'
                                 for v in flat[i:i+6]) + '\n')
            f.write('</DataArray>\n')
            # Also save tension field for void visualization
            flat_t = state.tension.flatten(order='F')
            f.write('<DataArray type="Float32" Name="tension" '
                    'format="ascii">\n')
            for i in range(0, len(flat_t), 6):
                f.write(' '.join(f'{v:.4f}'
                                 for v in flat_t[i:i+6]) + '\n')
            f.write('</DataArray>\n')
            f.write('</PointData>\n')
            f.write('</Piece>\n</ImageData>\n</VTKFile>\n')
        return fname

    def save_slices(self, state, step, label=""):
        """Save 2D cross-section PNGs through center of mass"""
        if not self._has_mpl:
            return
        g = state.grid
        N = self.N
        total = g.sum() + 1e-10
        xx, yy, zz = np.meshgrid(np.arange(N), np.arange(N),
                                  np.arange(N), indexing='ij')
        cm = [int((g*xx).sum()/total) % N,
              int((g*yy).sum()/total) % N,
              int((g*zz).sum()/total) % N]

        fig, axes = self._plt.subplots(1, 3, figsize=(15, 5))
        fig.suptitle(f"VDC | step {step} {label} | "
                     f"T={state.temperature:.2f}", fontsize=11)
        vmin = 0
        vmax = max(np.percentile(g, 99), 0.01)

        axes[0].imshow(g[:, :, cm[2]].T, origin='lower',
                       cmap='inferno', vmin=vmin, vmax=vmax)
        axes[0].set_title(f"XY (z={cm[2]})")

        axes[1].imshow(g[:, cm[1], :].T, origin='lower',
                       cmap='inferno', vmin=vmin, vmax=vmax)
        axes[1].set_title(f"XZ (y={cm[1]})")

        axes[2].imshow(g[cm[0], :, :].T, origin='lower',
                       cmap='inferno', vmin=vmin, vmax=vmax)
        axes[2].set_title(f"YZ (x={cm[0]})")

        self._plt.tight_layout()
        fname = os.path.join(self.outdir, f"step_{step:05d}.png")
        self._plt.savefig(fname, dpi=100, bbox_inches='tight')
        self._plt.close()


# ------------------------------------------------------------------ #
# KERNEL - THE MAIN ORCHESTRATOR
# ------------------------------------------------------------------ #
class Kernel:
    """
    The simulation kernel. Owns state, runs the loop, calls modules.
    
    Usage:
        k = Kernel('vdc_config.txt')
        k.register(SubstrateModule())
        k.register(GravityModule())
        k.run()
    """

    def __init__(self, config_path='vdc_config.txt'):
        self.cfg = Config(config_path)

        # Core parameters
        self.N        = self.cfg.int('N', 64)
        self.steps    = self.cfg.int('steps', 500)
        self.snap_every = self.cfg.int('snap_every', 10)
        self.print_every = self.cfg.int('print_every', 30)

        # Output
        run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_outdir = self.cfg.str('output_dir', 'vdc_output')
        self.outdir = f"{base_outdir}_{run_id}"

        # Epoch boundaries
        self.plasma_end  = self.cfg.int('plasma_end', 60)
        self.cooling_end = self.cfg.int('cooling_end', 160)
        self.cool_floor  = self.cfg.float('cool_floor', 0.10)

        # Universe state
        self.state = UniverseState(self.N)

        # Module registry - ordered list
        self._modules = []

        # Infrastructure
        os.makedirs(self.outdir, exist_ok=True)
        self.logger  = SimLogger(self.outdir, run_id)
        self.output  = OutputManager(self.outdir, self.N)
        self.health  = HealthMonitor(self.cfg)

        # Last good state snapshot for recovery
        self._last_good_state = None

        self.logger.log(f"Kernel initialized | N={self.N} | "
                        f"steps={self.steps} | output={self.outdir}")

    def register(self, module):
        """
        Add a physics module to the simulation.
        Modules are called in registration order each step.
        Register in this order:
            wave -> gravity -> thermal -> vortex -> cycle -> output
        """
        if not isinstance(module, VDCModule):
            raise TypeError(f"{module} is not a VDCModule")
        self._modules.append(module)
        status = "ENABLED" if module.enabled else "DISABLED"
        self.logger.log(f"  [{status}] Module registered: {module.name}")

    def _update_epoch(self, step):
        """Update temperature and epoch label"""
        if step < self.plasma_end:
            self.state.temperature = 1.0
            self.state.epoch = 'plasma'
        elif step < self.cooling_end:
            frac = (step - self.plasma_end) / (self.cooling_end - self.plasma_end)
            self.state.temperature = 1.0 - (1.0 - self.cool_floor) * frac
            self.state.epoch = 'cooling'
        else:
            self.state.temperature = self.cool_floor
            self.state.epoch = 'structure'

    def _save_state_snapshot(self):
        """Save a lightweight copy of current state for recovery"""
        self._last_good_state = {
            'grid':    self.state.grid.copy(),
            'wave':    self.state.wave.copy(),
            'wave_v':  self.state.wave_v.copy(),
            'vx':      self.state.vx.copy(),
            'vy':      self.state.vy.copy(),
            'vz':      self.state.vz.copy(),
            'tension': self.state.tension.copy(),
            'subway':  self.state.subway,
        }

    def _restore_state_snapshot(self):
        """Restore last good state after an error"""
        if self._last_good_state is None:
            return False
        s = self._last_good_state
        self.state.grid    = s['grid'].copy()
        self.state.wave    = s['wave'].copy()
        self.state.wave_v  = s['wave_v'].copy()
        self.state.vx      = s['vx'].copy()
        self.state.vy      = s['vy'].copy()
        self.state.vz      = s['vz'].copy()
        self.state.tension = s['tension'].copy()
        self.state.subway  = s['subway']
        return True

    def run(self):
        """Main simulation loop"""
        self.logger.log(f"\nStarting simulation | {len(self._modules)} modules active")
        self.logger.log(f"Config: {self.cfg.path}")

        # Initialize all modules
        self.logger.log("\nInitializing modules...")
        for mod in self._modules:
            if not mod.enabled:
                continue
            try:
                mod.initialize(self.state, self.cfg)
                self.logger.log(f"  {mod.name}: initialized")
            except Exception as e:
                self.logger.log(f"  {mod.name}: INIT FAILED - {e}")
                traceback.print_exc()
                sys.exit(1)

        # Log initial state
        self.logger.log(f"\nInitial state: {self.state.summary()}")
        self.logger.log(f"\n{'='*60}")

        # Save initial snapshot
        self._save_state_snapshot()
        self.output.save_vti(self.state, 0)
        self.output.save_slices(self.state, 0, "(INITIAL)")

        # Log config used
        config_log = os.path.join(self.outdir, 'config_used.txt')
        with open(config_log, 'w') as f:
            f.write(f"VDC run | {datetime.now()}\n")
            f.write(f"Modules: {[m.name for m in self._modules]}\n\n")
            for k, v in self.cfg.all().items():
                f.write(f"{k} = {v}\n")

        t_start = time.time()
        error_count = 0
        MAX_ERRORS = 3

        # Main loop
        for step in range(1, self.steps + 1):
            self.state.step = step
            self._update_epoch(step)

            # Save state before this step for potential recovery
            if step % 50 == 0:
                self._save_state_snapshot()

            # Run each module
            step_metrics = {}
            step_ok = True

            for mod in self._modules:
                if not mod.enabled:
                    continue
                try:
                    metrics = mod.step(self.state, self.cfg)
                    if metrics:
                        step_metrics.update(
                            {f"{mod.name}_{k}": v
                             for k, v in metrics.items()})
                except Exception as e:
                    self.logger.log(
                        f"Step {step} | {mod.name} ERROR: {e}")
                    traceback.print_exc()
                    step_ok = False
                    break

            if not step_ok:
                error_count += 1
                if error_count >= MAX_ERRORS:
                    self.logger.log(
                        f"Too many errors ({MAX_ERRORS}). Stopping.")
                    break
                self._restore_state_snapshot()
                continue

            # Health check
            health_status, health_msg = self.health.check(
                self.state, step)

            if health_status == 'error':
                self.logger.log(f"HEALTH ERROR: {health_msg}")
                error_count += 1
                if error_count >= MAX_ERRORS:
                    self.logger.log("Simulation terminated - instability")
                    break
                if self._restore_state_snapshot():
                    self.logger.log("Restored last good state")
                continue

            if health_status == 'warn' and step % 30 == 0:
                self.logger.log(f"HEALTH WARN: {health_msg}")

            # Logging
            self.logger.metrics(step, self.state, step_metrics)

            if step % self.print_every == 0:
                elapsed = time.time() - t_start
                rate = step / elapsed
                remaining = (self.steps - step) / rate
                self.logger.log(
                    f"step {step:>5}/{self.steps} | "
                    f"[{self.state.epoch:9}] T={self.state.temperature:.2f} | "
                    f"{self.state.summary()} | "
                    f"{rate:.1f} steps/s | "
                    f"ETA {remaining/60:.1f}min")

            # Snapshots
            if step % self.snap_every == 0 or step == self.steps:
                label = f"({self.state.epoch.upper()})"
                self.output.save_vti(self.state, step)
                self.output.save_slices(self.state, step, label)

        # Final summary
        elapsed = time.time() - t_start
        self.logger.log(f"\n{'='*60}")
        self.logger.log(f"Simulation complete | {elapsed:.1f}s | "
                        f"{self.steps/elapsed:.1f} steps/s")
        self.logger.log(f"Final state: {self.state.summary()}")
        self.logger.log(f"Output: {os.path.abspath(self.outdir)}")
        self.logger.log(
            "ParaView: File->Open->*.vti (as series) -> "
            "Threshold filter min=0.5")
        self.logger.close()


# ------------------------------------------------------------------ #
# QUICK TEST - run kernel alone with no modules to verify it works
# ------------------------------------------------------------------ #
if __name__ == '__main__':
    print("VDC Kernel self-test (no modules)")
    print("Create vdc_config.txt and register modules to run a sim")
    print("\nKernel structure OK - ready for modules")
    print("\nModule registration order:")
    print("  1. SubstrateModule  - void, surface tension, boundary")
    print("  2. WaveModule       - propagation, torus geometry")
    print("  3. GravityModule    - FFT Poisson solver")
    print("  4. ThermalModule    - cooling, pressure, phase transition")
    print("  5. VortexModule     - Magnus force, chirality")
    print("  6. CycleModule      - BH drain, subway, white holes")
    print("\nNext: build substrate.py")
