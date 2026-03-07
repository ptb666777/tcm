# -*- coding: utf-8 -*-
"""
VDC Matter State Module
=======================
The referee. Tracks what epoch the universe is in and what
physics is allowed to operate. Nothing runs before its time.

Epoch sequence (each unlocks new physics):
    PLASMA_HOT      - quark-gluon plasma, pure energy, no structure possible
                      fluid: superfluid, near-zero viscosity
                      active: nothing except wave propagation and cooling

    PLASMA_COOLING  - hadron formation begins, quarks binding into protons/neutrons
                      each failed binding attempt radiates a photon (cooling mechanism)
                      fluid: still superfluid but viscosity rising
                      active: wave propagation, radiation cooling

    CONFINEMENT     - quarks lock permanently into hadrons
                      pins stabilize through boundary, membrane starts oscillating
                      Chladni pattern begins forming
                      fluid: viscoelastic transition
                      active: wave interference, gravity awakens (weak), Magnus begins

    NUCLEOSYNTHESIS - protons and neutrons fusing into light nuclei (H, He, Li)
                      brief window ~3 minutes in real time
                      fluid: viscoelastic, matter partially rigid
                      active: gravity, Magnus, weak vortex structures

    RECOMBINATION   - electrons attach to nuclei, neutral atoms form
                      universe becomes transparent, CMB releases
                      pressure drops dramatically, Jeans instability can begin
                      fluid: gas dynamics, no longer plasma
                      active: all gravity, full vortex, Jeans collapse begins

    STRUCTURE       - filaments and voids emerge from gravitational collapse
                      voids form because matter LEFT, not as primary mechanic
                      fluid: collisional gas in dense regions, collisionless in voids
                      active: everything except compact objects

    STELLAR         - first stars ignite in dense nodes
                      stellar wind, radiation pressure, supernova possible
                      active: everything except black holes

    COMPACT         - cores of massive stars collapse
                      black holes and neutron stars possible
                      active: everything including BH drain and subway cycle

Temperature thresholds (normalized, 1.0 = bang temperature):
    These are ORDER OF MAGNITUDE correct relative to each other.
    Actual values tunable in config.
    What matters is the SEQUENCE and RATIOS.
"""

import numpy as np
from vdc_kernel import VDCModule

# Epoch constants - used by all modules to check what's allowed
PLASMA_HOT      = 'plasma_hot'
PLASMA_COOLING  = 'plasma_cooling'
CONFINEMENT     = 'confinement'
NUCLEOSYNTHESIS = 'nucleosynthesis'
RECOMBINATION   = 'recombination'
STRUCTURE       = 'structure'
STELLAR         = 'stellar'
COMPACT         = 'compact'

# Ordered sequence
EPOCH_ORDER = [
    PLASMA_HOT,
    PLASMA_COOLING,
    CONFINEMENT,
    NUCLEOSYNTHESIS,
    RECOMBINATION,
    STRUCTURE,
    STELLAR,
    COMPACT,
]

def epoch_at_least(current, minimum):
    """Check if current epoch is at or past minimum epoch"""
    if current not in EPOCH_ORDER or minimum not in EPOCH_ORDER:
        return False
    return EPOCH_ORDER.index(current) >= EPOCH_ORDER.index(minimum)


class MatterStateModule(VDCModule):
    """
    Tracks universe epoch based on temperature.
    Updates state.epoch each step.
    Other modules call epoch_at_least() to check if they should run.

    Also manages:
    - Effective viscosity (changes at confinement)
    - Radiation cooling (photon emission from failed bond attempts)
    - Jeans threshold tracking (when gravity wins locally)
    - Matter phase field (what state matter is in at each cell)
    """
    name = "matter_state"

    def initialize(self, state, cfg):
        N = state.N

        # Temperature thresholds for epoch transitions
        # All normalized: 1.0 = initial bang temperature
        self.T_plasma_cooling  = cfg.float('T_plasma_cooling',  0.90)
        self.T_confinement     = cfg.float('T_confinement',     0.70)
        self.T_nucleosynthesis = cfg.float('T_nucleosynthesis', 0.50)
        self.T_recombination   = cfg.float('T_recombination',   0.20)
        self.T_structure       = cfg.float('T_recombination',   0.20)

        # Cooling parameters
        # Radiation cooling: heat lost per step as photons
        # Scales with density (more matter = more bond attempts = more photons)
        self.rad_cooling_k    = cfg.float('rad_cooling_k',    0.0008)
        # Base cooling rate (expansion analog - energy spreading out)
        self.base_cooling     = cfg.float('base_cooling',     0.0005)
        # Latent heat released at confinement transition
        self.confinement_heat = cfg.float('confinement_heat', 0.05)
        self._confinement_released = False

        # Viscosity by epoch
        # Superfluid pre-confinement: near zero
        # Viscoelastic post-confinement: rises
        # Gas post-recombination: standard
        self.visc_superfluid  = cfg.float('visc_superfluid',  0.002)
        self.visc_viscoelastic= cfg.float('visc_viscoelastic',0.015)
        self.visc_gas         = cfg.float('visc_gas',         0.030)

        # Temperature floor for cooling
        # Below this T, the universe is too cold for bond attempts.
        # Radiation cooling stops. Prevents endless T->0 trickle.
        self.T_cool_floor = cfg.float('T_cool_floor', 0.02)

        # Jeans tracking
        # When local gravity energy > thermal energy: collapse begins
        # Jeans mass ~ (T/rho)^(3/2) - simplified to density threshold
        self.jeans_density_thresh = cfg.float('jeans_density_thresh', 2.0)

        # Matter phase field - tracks state of matter at each cell
        # 0 = pure energy/plasma
        # 1 = hadron plasma
        # 2 = neutral atoms
        # 3 = condensed/collapsed
        state.fields['matter_phase'] = np.zeros((N, N, N))
        state.fields['viscosity']    = np.full((N, N, N),
                                                self.visc_superfluid)
        state.fields['jeans_collapse'] = np.zeros((N, N, N), dtype=bool)

        # Initialize temperature at bang
        state.temperature = 1.0
        state.epoch = PLASMA_HOT

        # Track epoch history for logging
        self._epoch_history = {PLASMA_HOT: 0}

        print(f"  MatterState: epoch sequence active")
        print(f"  Thresholds: confinement={self.T_confinement} "
              f"recombination={self.T_recombination}")

    def _update_temperature(self, state):
        """
        Physical cooling mechanisms:
        1. Radiation cooling: failed bond attempts emit photons
           Rate proportional to density (more matter = more attempts)
        2. Base cooling: energy spreading through growing reality
        3. Latent heat bump at confinement (brief warming then continued cooling)
        """
        # Radiation cooling - proportional to mean density
        mean_rho = state.grid.mean()
        rad_loss = self.rad_cooling_k * mean_rho * state.temperature

        # Base cooling
        base_loss = self.base_cooling * state.temperature

        # Total cooling
        dT = -(rad_loss + base_loss)

        # TRICKLE FIX: stop cooling below floor temperature
        # Below T_cool_floor the universe is too cold for bond attempts.
        # Radiation cooling ceases. Temperature stabilizes.
        if state.temperature <= self.T_cool_floor:
            dT = 0.0

        # Confinement latent heat - brief warming as quarks lock
        # Happens once when crossing confinement threshold
        if (not self._confinement_released and
                state.temperature <= self.T_confinement + 0.02):
            dT += self.confinement_heat
            self._confinement_released = True
            print(f"  [step {state.step}] Confinement: latent heat released, "
                  f"pins locking, membrane oscillation begins")

        state.temperature = max(0.001, state.temperature + dT)

    def _update_epoch(self, state):
        """Update epoch based on current temperature"""
        T = state.temperature
        old_epoch = state.epoch

        if T > self.T_plasma_cooling:
            state.epoch = PLASMA_HOT
        elif T > self.T_confinement:
            state.epoch = PLASMA_COOLING
        elif T > self.T_nucleosynthesis:
            state.epoch = CONFINEMENT
        elif T > self.T_recombination:
            state.epoch = NUCLEOSYNTHESIS
        else:
            # Check if structure has formed
            if state.grid.max() > self.jeans_density_thresh * 3:
                state.epoch = STRUCTURE
            else:
                state.epoch = RECOMBINATION

        # Log epoch transitions
        if state.epoch != old_epoch:
            self._epoch_history[state.epoch] = state.step
            print(f"  [step {state.step}] EPOCH: {old_epoch} -> {state.epoch} "
                  f"(T={state.temperature:.4f})")

    def _update_viscosity(self, state):
        """
        Viscosity changes with epoch.
        Pre-confinement: superfluid
        Post-confinement: viscoelastic
        Post-recombination: gas
        """
        if epoch_at_least(state.epoch, RECOMBINATION):
            visc = self.visc_gas
        elif epoch_at_least(state.epoch, CONFINEMENT):
            # Smooth transition through confinement
            visc = self.visc_viscoelastic
        else:
            visc = self.visc_superfluid

        state.fields['viscosity'][:] = visc

    def _update_matter_phase(self, state):
        """
        Track what phase matter is in at each cell.
        Used by other modules to know what physics applies locally.
        """
        phase = state.fields['matter_phase']

        if epoch_at_least(state.epoch, RECOMBINATION):
            # Dense cells are neutral atoms/molecules
            phase[:] = np.where(state.grid > 0.01, 2, 0)
        elif epoch_at_least(state.epoch, CONFINEMENT):
            # Hadron plasma
            phase[:] = np.where(state.grid > 0.001, 1, 0)
        else:
            # Pure energy plasma
            phase[:] = 0

    def _update_jeans(self, state):
        """
        Mark cells where Jeans instability has triggered.
        Condition: local density exceeds Jeans threshold.
        Only possible post-recombination when pressure drops.
        """
        if not epoch_at_least(state.epoch, RECOMBINATION):
            state.fields['jeans_collapse'][:] = False
            return

        # Simplified Jeans: collapse where density > threshold
        # and local gravity > local pressure
        rho = state.grid
        T = state.temperature
        # Jeans density: rho_J ~ T (higher temp = harder to collapse)
        jeans_rho = self.jeans_density_thresh * T / 0.1
        state.fields['jeans_collapse'] = rho > jeans_rho

    def step(self, state, cfg):
        self._update_temperature(state)
        self._update_epoch(state)
        self._update_viscosity(state)
        self._update_matter_phase(state)
        self._update_jeans(state)

        jeans_cells = state.fields['jeans_collapse'].sum()

        return {
            'temperature':  float(state.temperature),
            'epoch':        state.epoch,
            'viscosity':    float(state.fields['viscosity'].mean()),
            'jeans_cells':  int(jeans_cells),
            'matter_phase_mean': float(state.fields['matter_phase'].mean()),
        }

    def health_check(self, state):
        if state.temperature < 0:
            return f"Temperature negative: {state.temperature}"
        if state.temperature > 2.0:
            return f"Temperature runaway: {state.temperature}"
        return None
