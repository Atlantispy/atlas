"""Predeclared kinematic family of the original three-plate control.

The carrierless B|C transform requires their shared rigid rotation. A remains
independent across its declared ridge/trench. This is a physical constraint
before solving, not a projection of a failed set of rates.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
from fractions import Fraction as Q
import math

import numpy as np


CONSTRAINT_SOURCE = ('original coaxial verification family: independent A axial rate; '
                     'shared B/C axial rate required by their carrierless transform')


def original_coaxial_basis(network, pair):
    if set(network.plate_ids) != {'A', 'B', 'C'} or set(pair) != {'A', 'B'}:
        raise ValueError('original A/B/C control and actual A/B native pair required')
    expected = {frozenset(('B', 'C')): 'transform', frozenset(('C', 'A')): 'ridge',
                frozenset(('A', 'B')): 'trench'}
    if (len(network.boundaries) != 3 or
            any(expected.get(frozenset((b.left_plate_id, b.right_plate_id))) != b.kind or
                (b.kind == 'transform' and b.carrier_side is not None) for b in network.boundaries)):
        raise ValueError('original boundary topology/rules differ; no inferred adaptation allowed')
    pair_basis = np.zeros((6, 2))
    pair_basis[2, 0] = pair_basis[5, 1] = 1.
    global_basis = np.zeros((3*len(network.plate_ids), 2))
    for i, plate in enumerate(network.plate_ids):
        global_basis[3*i+2, pair.index('A' if plate == 'A' else 'B')] = 1.
    return pair_basis, global_basis


TRANSFORM_CONSTRAINT_SOURCE = (
    'equatorial transform verification family: independent north/south axial rates; '
    'the declared north carrier preserves the equator without opening or consumption')


ACTUATOR_STRESS_PA = Q(83, 5)  # 2*(5 Pa + 1.1 kg/m3 * 1 m/s2 * 3 m)
ACTUATOR_AREA_M2 = Q(1)
ACTUATOR_LEVER_M = Q(17, 2)
ACTUATOR_TORQUE_N_M = ACTUATOR_STRESS_PA*ACTUATOR_AREA_M2*ACTUATOR_LEVER_M


@dataclass(frozen=True)
class ActuationBudget:
    """Conditional workload budget, not a continuum peak-stress theorem.

    The actual audit must satisfy the power and BOOKED-energy bounds. Across
    two intervals their sum permits only one percent of initial thermal
    headroom at the capacity floor. Transport/conduction keep their own gates.
    """
    power_w: Q
    capacity_floor_j_k: Q
    headroom_k: Q
    duration_s: float

    @property
    def energy_per_interval_j(self):
        return self.capacity_floor_j_k*self.headroom_k/200

    def record(self):
        pair = lambda value: [value.numerator, value.denominator]
        return dict(power_budget_w=pair(self.power_w),
            capacity_floor_j_k=pair(self.capacity_floor_j_k), initial_headroom_k=pair(self.headroom_k),
            energy_per_interval_j=pair(self.energy_per_interval_j), duration_s=self.duration_s,
            intervals=2, maximum_mechanical_source_temperature_rise_k=pair(self.headroom_k/100),
            scope='conditional mechanical-source bound only; no HMM/advection maximum-principle claim')


def actuation_budget(initial_capacities, initial_temperatures, *, gas_constant, volume=Q(1)):
    capacities = tuple(map(Q, initial_capacities)); temperatures = tuple(map(Q, initial_temperatures))
    if not capacities or len(capacities) != len(temperatures) or min(capacities) <= 0 or volume != 1:
        raise ValueError('actual positive native capacities and the declared physical unit box are required')
    headroom = Q(2)-max(temperatures)
    if min(temperatures) < 1 or headroom <= 0:
        raise ValueError('the authored initial temperatures must lie inside1..2K')
    # eta(T)=exp(1/(R*T)) Pa s for the fixture's n1,A=.5,Q=1 law.
    eta_min = math.exp(1/(gas_constant*2))
    stress_scale = ACTUATOR_STRESS_PA+Q(5)+Q(11, 10)*3
    power = Q(float(2*volume*stress_scale**2)/eta_min)
    floor = min(capacities)/2
    limit = floor*headroom/(200*power)
    duration = math.nextafter(float(limit), 0.)
    if duration <= 0 or Q(duration) > limit:
        raise ValueError('the frozen workload duration cannot be represented')
    return ActuationBudget(power, floor, headroom, duration)


@dataclass(frozen=True)
class ForceControl:
    """Explicit test physics, never inferred from a computed force or rate.

    The original control is unchanged. The second control has only tangential
    equatorial motion: its stream scale is transport through a Cartesian cut,
    not a fictitious normal sweep of the transform boundary.
    """
    family: str

    def __post_init__(self):
        if self.family not in ('original-coaxial', 'equatorial-transform', 'far-field-actuated-coaxial'):
            raise ValueError('a predeclared verification family is required')

    @property
    def coaxial(self):
        return self.family in ('original-coaxial', 'far-field-actuated-coaxial')

    @property
    def constraint_source(self):
        return CONSTRAINT_SOURCE if self.coaxial else TRANSFORM_CONSTRAINT_SOURCE

    @property
    def native_directed_max_leaves(self):
        """Declared work cap only; never changes the physical stream width.

        The saved transform has three full-face quadratic branch integrals
        requiring 68..91 leaves. Its genuinely mixed component mask has a
        separate declared partition cap and ALE has its own work allowance.
        """
        return 64 if self.coaxial else 128

    @property
    def native_mask_max_leaves(self):
        """Exact saved transform masks require up to237 partition leaves.

        This is computational allowance, not an error-budget change. The
        original ridge/trench keeps64; ALE has its own work allowance.
        """
        return 64 if self.coaxial else 256

    @property
    def ale_max_leaves(self):
        """Computational work only, with the original per-stream error width.

        The saved transform's genuine early event needs73 terminal leaves
        after exact geometric predicates remove artificial uncertainty.
        Initial geometry and trace limits, and both coaxial controls, stay64.
        """
        return 64 if self.coaxial else 128

    @property
    def interval_predictor_proposals(self):
        """Declared same-parent proposals after the current-geometry one.

        A coaxial native box sees one rigid field on each prescribed wall,
        exactly in Q2, so its first proposal already matches every moving
        component mask. The transform's two plate fields are discontinuous
        across the equator: its Q2 trace is constrained only through integrated
        component masks, and material first exposed DURING the interval has no
        start mask. The preceding proposal's time-integrated masks must then
        drive the next solve: the swept-volume form of the boundary flux in
        place of a single-time one. The masks of a thin swept strip change
        its unit-size equation only by (strip width/face) times the relative
        rate change, so the proposals contract by about 1e-7 per step: the
        retained sequence changed by -5.3e-2, -6.2e-9 and +3.7e-12. Two
        follow the first, inside the unchanged four-attempt limit; a bitwise
        repeated rate needs no further one. This is a declared iteration
        count, never a convergence tolerance: the final actual-rate audit and
        exact closure alone decide.
        """
        return 0 if self.coaxial else 2

    def boundary(self, network):
        if self.coaxial:
            boundary = next(b for b in network.boundaries
                            if {b.left_plate_id, b.right_plate_id} == {'A', 'B'})
            original_coaxial_basis(network, (boundary.left_plate_id, boundary.right_plate_id))
            return boundary
        if set(network.plate_ids) != {'north', 'south'} or len(network.boundaries) != 1:
            raise ValueError('the declared two-hemisphere transform is required')
        boundary = network.boundaries[0]
        carrier = {'left': boundary.left_plate_id, 'right': boundary.right_plate_id}.get(boundary.carrier_side)
        if (boundary.kind != 'transform' or not boundary.closed or
                {boundary.left_plate_id, boundary.right_plate_id} != {'north', 'south'} or carrier != 'north'):
            raise ValueError('the equatorial transform and actual north carrier must remain unchanged')
        return boundary

    def basis(self, network, pair):
        boundary = self.boundary(network)
        if tuple(pair) != (boundary.left_plate_id, boundary.right_plate_id):
            raise ValueError('basis row owners must follow the actual boundary sides')
        if self.coaxial:
            return original_coaxial_basis(network, pair)
        pair_basis = np.zeros((6, 2))
        pair_basis[2, 0] = pair_basis[5, 1] = 1.
        global_basis = np.zeros((3*len(network.plate_ids), 2))
        for i, plate in enumerate(network.plate_ids):
            global_basis[3*i+2, pair.index(plate)] = 1.
        return pair_basis, global_basis

    def torques(self, network):
        boundary = self.boundary(network)
        positive, negative = ((boundary.left_plate_id, boundary.right_plate_id)
                              if self.coaxial else ('north', 'south'))
        magnitude = float(ACTUATOR_TORQUE_N_M) if self.family == 'far-field-actuated-coaxial' else .01
        return {p: (0., 0., magnitude if p == positive else (-magnitude if p == negative else 0.))
                for p in network.plate_ids}

    def workload(self, case):
        if self.family != 'far-field-actuated-coaxial':
            return None
        from atlas_tectonics import _integration_column as I01
        native, initial = case['native'], case['state'].native_state
        material = case['material']
        if (material.density_kg_m3 != 1.1 or material.heat_capacity_j_kg_k != 1. or
                native.cells != (2, 2, 2) or native.lengths_m != (1., 1., 1.) or
                case['law'].dicts() != [dict(a=.5, n=1., energy_j_mol=1.,
                    volume_m3_mol=0., grain_exponent=0.)]):
            raise ValueError('the actuator energy contract belongs to the declared unit-box material')
        masses = np.sum(initial.array('component_mass_kg'), axis=0)
        capacities = masses*material.heat_capacity_j_kg_k
        temperature = initial.array('enthalpy_j')/capacities
        return actuation_budget(capacities.flat, temperature.flat, gas_constant=I01.R)

    def duration(self, case):
        workload = self.workload(case)
        return .001 if workload is None else workload.duration_s

    def validate_case(self, case):
        self.boundary(case['source'][0].network)
        if self.family == 'equatorial-transform':
            if case['supplies'] or case['sinks'] or case['birth_columns']:
                raise ValueError('the transform control has no ridge birth or trench sink')
            cells = case['collar'].cell_geometries()
            vertices = [v for cell in cells for v in cell.vertices_m]
            bounds = tuple(tuple(f(v[j] for v in vertices) for j in range(3)) for f in (min, max))
            if (bounds != ((Q(8), Q(-1, 2), Q(-1, 2)), (Q(9), Q(1, 2), Q(1, 2))) or
                    sum((c.volume_m3 for c in cells), Q(0)) != 1):
                raise ValueError('the tangential transport scale requires the declared physical unit box')

    def stream_reference_volume(self, rates, dt):
        """Exact physical scale before any quadrature or observed error.

        For the transform, u_y=Omega*x and each hemisphere occupies half of
        either y-face. Their relative signed cut transport is
        |DeltaOmega|*dt*integral_8^9 x dx*integral_0^.5 dz =17/4*|DeltaOmega|*dt.
        It is not an equatorial flux (which is exactly zero).
        """
        if any(row[0] or row[1] for row in rates.values()) or dt <= 0:
            raise ValueError('positive time and the declared axial motion subspace are required')
        differences = [abs(a[2]-b[2]) for i, a in enumerate(rates.values())
                       for b in list(rates.values())[i+1:] if a[2] != b[2]]
        if not differences:
            raise ValueError('common rigid motion cannot replace differential motion')
        if self.coaxial:
            if set(rates) != {'A', 'B', 'C'}:
                raise ValueError('original source owners are required')
            return 2*min(differences)*dt*(Q(10)**3-Q(7)**3)/3
        if set(rates) != {'north', 'south'}:
            raise ValueError('both actual transform owners are required')
        return Q(17, 4)*abs(rates['north'][2]-rates['south'][2])*dt


ORIGINAL_CONTROL = ForceControl('original-coaxial')
TRANSFORM_CONTROL = ForceControl('equatorial-transform')
ACTUATED_CONTROL = ForceControl('far-field-actuated-coaxial')
