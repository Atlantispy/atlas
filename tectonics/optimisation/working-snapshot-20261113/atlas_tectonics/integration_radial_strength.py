"""Actual radial material fields consumed by isotropic full-3D rheology.

This is a same-time constitutive/mechanical adapter, not a plastic-history
transport law. Hydrostatic radial stress is never substituted for mean stress.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import math

import numpy as np

from . import _integration_column as C
from . import _integration_weakening as W
from . import integration_material as M
from . import integration_patch_heat as H
from . import integration_support as U
from . import integration_volume as V
from . import integration_regional_evolution as O
from .integration_strength import CreepLaw
from ._validation import TectonicsError, frozen
from .regional_execution import RegionalMechanicalSnapshot
from .regional_execution3d import PreparedRegionalStokes3D, _array, _cancel, _json
from .resources import select_budget

SOURCE = 'atlas.radial-strength-source.v1'
RESPONSE = 'atlas.radial-strength-response.v1'
YIELD = 'atlas.drucker-prager-3d-middle-circumscribed.v1'
LOG_TOL = 1e-8                 # Existing regional constitutive same-state gate.
MAX_ITERATIONS = 32           # Existing regional evolution iteration ceiling.
FAMILY = 'radial-3d-creep-plastic'
PLASTIC_HISTORY = 'radial_plastic_kappa'


class RadialStrengthRefused(TectonicsError):
    pass


def _name(value, label):
    if type(value) is not str or not value.strip() or len(value) > 1024:
        raise RadialStrengthRefused(label+' requires a bounded explicit name')
    return value


@dataclass(frozen=True, slots=True)
class RadialPlasticity3D:
    """Explicit 3D input convention, not converted/calibrated 2D parameters.

    ``plastic_viscosity_pa_s=None`` explicitly disables the plastic element.
    The interval is on Atlas raw engineering plastic kappa, not total strain.
    """
    cohesion_pa: float
    friction_rad: float
    plastic_viscosity_pa_s: float | None
    grain_m: float
    weakening_interval: tuple
    cohesion_factor: float
    friction_factor: float
    provenance: str

    def __post_init__(self):
        for key in ('cohesion_pa', 'friction_rad', 'grain_m'):
            object.__setattr__(self, key, C.number(getattr(self, key), key,
                positive=key == 'grain_m', nonnegative=key != 'grain_m'))
        if self.friction_rad >= math.pi/2:
            raise RadialStrengthRefused('friction must be in [0,pi/2)')
        if self.plastic_viscosity_pa_s is not None:
            object.__setattr__(self, 'plastic_viscosity_pa_s', C.number(
                self.plastic_viscosity_pa_s, 'plastic viscosity', positive=True))
        if type(self.weakening_interval) is not tuple or len(self.weakening_interval) != 2:
            raise RadialStrengthRefused('explicit engineering-plastic weakening interval required')
        law = W.WeakeningLaw(*self.weakening_interval, self.cohesion_factor, self.friction_factor)
        object.__setattr__(self, 'weakening_interval', (law.start, law.end))
        object.__setattr__(self, 'cohesion_factor', law.cohesion_factor)
        object.__setattr__(self, 'friction_factor', law.friction_factor)
        _name(self.provenance, '3D material provenance')

    def record(self):
        return dict(yield_convention=YIELD, **asdict(self))

    def factors(self, kappa):
        return W.WeakeningLaw(*self.weakening_interval, self.cohesion_factor,
                             self.friction_factor).factors(kappa)


@dataclass(frozen=True, eq=False, slots=True, init=False)
class RadialStrengthSource:
    _snapshot: RegionalMechanicalSnapshot
    _materials: tuple
    _creep: tuple
    _map: O.RegionalVolumeMap

    @property
    def source_id(self):
        return self._snapshot.result_id

    def descriptor(self):
        return self._snapshot.descriptor()

    def array(self, name):
        return self._snapshot.array(name)

    @property
    def array_names(self):
        return self._snapshot.array_names

    def bind(self, native):
        binding = self._map.native_binding(native)
        if binding['source'] != self.descriptor()['source']:
            raise RadialStrengthRefused('native volume map differs from the constitutive source')
        return binding


def radial_strength_source(moving, sphere, volume_map, *, materials, creep_laws,
                           provenance, budget=None):
    """Admit actual pure-cell source patches; never a face/piece-mean profile.

    The exact contained-cell map establishes positions. Temperature is the
    retained layer's physical FV value; radial depth varies at actual Gauss
    positions. No source geometry is flattened or stock invented here.
    """
    M.bound_moving(moving, sphere)
    if type(volume_map) is not O.RegionalVolumeMap:
        raise RadialStrengthRefused('actual contained radial volume map required')
    _name(provenance, 'constitutive source provenance')
    data = volume_map.record()
    if data['source'] != O._source_binding(sphere, moving):
        raise RadialStrengthRefused('radial constitutive map has stale material/heat identity')
    if moving._physical_columns is None or moving._patch_heat is None:
        raise RadialStrengthRefused('actual retained physical columns and heat required')
    if type(materials) is not dict or type(creep_laws) is not dict:
        raise RadialStrengthRefused('explicit named material and creep tables required')
    if any(type(m) is not RadialPlasticity3D for m in materials.values()):
        raise RadialStrengthRefused('3D material declarations required; old 2D laws cannot be relabelled')
    if any(type(c) is not CreepLaw for c in creep_laws.values()):
        raise RadialStrengthRefused('typed already-SI creep laws required')
    cells = tuple(data['request']['cells']); n = math.prod(cells)
    resource = select_budget(budget)
    # Fields, geometry/ownership records and snapshot copies; exact physical
    # source arithmetic has a separate actual-width reservation below.
    with resource.reserve(65536+32768*n+8*len(volume_map._record), category='radial-strength-source'):
        patches = {p.patch_id: p for p in U.required(sphere.material).patches}
        fields, heat = dict(moving._physical_columns), dict(moving._patch_heat)
        selected = {row['patch_id'] for row in data['cell_sources']}
        column_data = {}
        for patch_id in selected:
            patch = patches[patch_id]; record = moving.cohort(patch.cohort_id)
            if record.volume_convention != V.PHYSICAL_RADIAL_SHELL:
                raise RadialStrengthRefused('physical radial shell convention required')
            field = fields[patch_id]
            with resource.reserve(H.field_workspace({patch_id: field}), category='radial-strength-column'):
                piece = U.piece_of(patch, sphere.material.phases)
                ratios = M._thickness_ratios(record, piece, sphere.material.phases, budget=resource)
                M._check_reference_mass(record, piece, ratios, sphere.material.phases,
                                        moving.step-moving.declared_step, budget=resource)
                if any(abs(q-patch.stock[0]*u) > b for q, u, b in zip(heat[patch_id], field[1], field[2])):
                    raise RadialStrengthRefused('retained physical source exceeds its caloric account allowance')
                geometry = M.layer_geometry(record, field[0], budget=resource)
                temperature = H.field_temperature(record, field, moving.enthalpy_reference_k, budget=resource)
                column_data[patch_id] = (record, geometry, temperature)
        keys, laws, creep, temperatures, history, pores, geometries, thermal = [], [], [], [], [], [], [], []
        for row in data['cell_sources']:
            record, geometry, temperature = column_data[row['patch_id']]
            j = row['sublayer']; layer = record.sublayers[j]
            if (layer.material_id not in materials or layer.creep_law_id not in creep_laws or
                    layer.pore_pressure_pa is None):
                raise RadialStrengthRefused('every owned sublayer needs declared material, creep and pore pressure')
            if record.elastic != M.NOT_REPRESENTED or record.compaction != M.NOT_REPRESENTED:
                raise RadialStrengthRefused('elastic/compaction source memory needs its own constitutive law')
            keys.append(dict(row, material_id=layer.material_id, creep_law_id=layer.creep_law_id))
            laws.append(materials[layer.material_id]); creep.append(creep_laws[layer.creep_law_id])
            temperatures.append(temperature[j]); history.append(record.kappa[j]); pores.append(layer.pore_pressure_pa)
            geometries.append(geometry[j].record())
            thermal.append({k: getattr(layer, k) for k in ('reference_density_kg_m3', 'heat_capacity_j_kg_k',
                'conductivity_w_m_k', 'alpha_per_k', 'radiogenic_w_m3')})
        nodes, weights = np.polynomial.legendre.leggauss(3)
        ijk = np.indices(cells).reshape(3, -1).T
        ref = np.indices((3, 3, 3)).reshape(3, -1).T
        lengths = np.asarray(data['request']['lengths_m'])
        local = (ijk[:, None, :]+(nodes[ref][None, :, :]+1)/2)*(lengths/np.asarray(cells))
        embedded = data['embedding']
        basis = np.asarray([[float(Fraction(*map(int, q))) for q in row] for row in embedded['basis']])
        origin = np.asarray([float(Fraction(*map(int, q))) for q in embedded['origin_global_m']])
        positions = local@basis.T+origin
        radius = np.linalg.norm(positions, axis=-1)
        depth = sphere.network.sphere.radius_m-radius
        arrays = dict(temperature_k=np.repeat(np.asarray(temperatures)[:, None], 27, axis=1),
            plastic_kappa=np.repeat(np.asarray(history)[:, None], 27, axis=1),
            pore_pressure_pa=np.repeat(np.asarray(pores)[:, None], 27, axis=1),
            depth_m=depth, radius_m=radius, position_m=positions, local_position_m=local,
            quadrature_volume_m3=np.broadcast_to(np.prod(lengths/np.asarray(cells))*
                np.prod(weights[ref], axis=1)/8, (n, 27)))
        described = dict(schema=SOURCE, source=data['source'], volume_map_id=volume_map.volume_map_id,
            cells=list(cells), lengths_m=lengths.tolist(), frame_id=embedded['frame']['frame_id'],
            time_s=sphere.time_s, epoch_id=sphere.network.epoch_id, ownership=keys,
            layer_geometry=geometries, thermophysical=thermal,
            materials={k: v.record() for k, v in sorted(materials.items())},
            creep_laws={k: v.record() for k, v in sorted(creep_laws.items())}, provenance=provenance,
            temperature='actual retained source-layer FV temperature, no spatial averaging',
            history='source raw engineering plastic kappa; not total accumulated strain',
            pressure='actual full-stress mean supplied by the mechanics owner; no hydrostatic substitution',
            time_advanced=False)
        obj = object.__new__(RadialStrengthSource)
        for key, value in (('_snapshot', RegionalMechanicalSnapshot(described, arrays)),
                           ('_materials', tuple(laws)), ('_creep', tuple(creep)), ('_map', volume_map)):
            object.__setattr__(obj, key, value)
        return obj


def evaluate_radial_strength(source, strain_rate_s_1, physical_mean_pressure_pa, *, budget=None, cancel=None):
    """Isotropic 3D SI point response at actual pressure; no work is booked.

    The deviatoric symmetric tensor is objective. Any numerical volumetric
    rate is reported separately, not counted as plastic strain or heat.
    """
    if type(source) is not RadialStrengthSource:
        raise RadialStrengthRefused('source-bound radial constitutive fields required')
    n = len(source._materials); shape = (n, 27)
    with select_budget(budget).reserve(65536+16384*n, category='radial-strength-evaluate'):
        strain = _array(strain_rate_s_1, shape+(3, 3), 'full strain-rate tensor')
        if not np.array_equal(strain, strain.swapaxes(-1, -2)):
            raise RadialStrengthRefused('the strain-rate tensor must be symmetric')
        pressure = _array(physical_mean_pressure_pa, shape, 'actual physical mean pressure', scalar_ok=True)
        trace = np.trace(strain, axis1=-2, axis2=-1)
        dev = strain-trace[..., None, None]*np.eye(3)/3
        rate = np.sqrt(.5*np.sum(dev*dev, axis=(-2, -1)))
        temperature, kappa, pore = (source.array(k) for k in ('temperature_k', 'plastic_kappa', 'pore_pressure_pa'))
        fields = {k: np.zeros(shape) for k in ('viscosity_pa_s', 'stress_ii_pa', 'yield_stress_pa',
            'creep_rate_ii_s_1', 'plastic_rate_ii_s_1', 'creep_power_w_m3', 'plastic_power_w_m3',
            'plastic_kappa_rate_s_1', 'constitutive_rate_relative_residual')}
        stress = np.zeros(shape+(3, 3))
        for cell, (material, creep) in enumerate(zip(source._materials, source._creep)):
            mechanisms = tuple(C.Creep(**row) for row in creep.dicts())
            for q in range(27):
                _cancel(cancel)
                t, p, e = float(temperature[cell, q]), float(pressure[cell, q]), float(rate[cell, q])
                lc, lf = material.factors(float(kappa[cell, q]))
                cohesion, phi = material.cohesion_pa*lc, material.friction_rad*lf
                y = 6*(cohesion*math.cos(phi)+max(p-float(pore[cell, q]), 0.)*math.sin(phi))/(
                    math.sqrt(3)*(3+math.sin(phi)))
                coefficients = tuple(C.number(math.log(m.a)-m.grain_exponent*math.log(material.grain_m)
                    -(m.energy_j_mol+p*m.volume_m3_mol)/(C.R*t), 'creep coefficient') for m in mechanisms)
                law = C.LocalLaw(coefficients, tuple(m.n for m in mechanisms), y, material.plastic_viscosity_pa_s)
                reply = law.solve(e, cancel=cancel)
                s, ep, ec = reply['stress_pa'], reply['plastic_rate_s'], math.fsum(reply['creep_rates_s'])
                if e:
                    eta = s/(2*e)
                    stress[cell, q] = (s/e)*dev[cell, q]
                else:
                    # Exact zero-rate tangent: superlinear mechanisms have zero
                    # fluidity. No arbitrary minimum strain rate or viscosity cap.
                    linear = [c for c, m in zip(coefficients, mechanisms) if m.n == 1.]
                    if y == 0 and material.plastic_viscosity_pa_s is not None:
                        linear.append(-math.log(2*material.plastic_viscosity_pa_s))
                    if not linear:
                        raise RadialStrengthRefused('zero-rate viscosity is infinite for a purely superlinear source')
                    logfluid = float(np.logaddexp.reduce(linear))
                    eta = math.exp(-math.log(2)-logfluid)
                if not math.isfinite(eta) or eta <= 0:
                    raise RadialStrengthRefused('constitutive viscosity is not finite positive; no clipping')
                for key, value in dict(viscosity_pa_s=eta, stress_ii_pa=s, yield_stress_pa=y,
                        creep_rate_ii_s_1=ec, plastic_rate_ii_s_1=ep, creep_power_w_m3=2*s*ec,
                        plastic_power_w_m3=2*s*ep, plastic_kappa_rate_s_1=2*ep,
                        constitutive_rate_relative_residual=reply['rate_residual']).items():
                    fields[key][cell, q] = value
        fields.update(strain_rate_ii_s_1=rate, volumetric_rate_s_1=trace,
            deviatoric_stress_pa=stress, physical_mean_pressure_pa=pressure,
            dissipation_w_m3=np.einsum('...ij,...ij->...', stress, dev))
        if any(not np.isfinite(v).all() for v in fields.values()):
            raise RadialStrengthRefused('constitutive response is outside finite binary64 support')
        return RegionalMechanicalSnapshot(dict(schema=RESPONSE, source_id=source.source_id,
            yield_convention=YIELD, pressure='actual mean stress, not radial hydrostatic pressure',
            history_rate='2*plastic invariant rate only; source history unchanged',
            heat='creep plus plastic partition of one deviatoric dissipation; no exterior work',
            time_advanced=False), fields)


def native_descriptor(source):
    """A transported shared cell admits one actual law, never a mixture rule."""
    if type(source) is not RadialStrengthSource:
        raise RadialStrengthRefused('typed radial constitutive source required')
    material, creep = source._materials[0].record(), source._creep[0].record()
    if (any(m.record() != material for m in source._materials) or
            any(c.record() != creep for c in source._creep) or
            np.any(source.array('pore_pressure_pa') != source.array('pore_pressure_pa')[0, 0])):
        raise RadialStrengthRefused('transported shared cells require identical material/creep/pore laws; no averaging')
    return dict(method='atlas.radial-3d-creep-plastic.v1', family=FAMILY, source_id=source.source_id,
        source=source.descriptor(), material=material, creep_law=creep,
        pore_pressure_pa=float(source.array('pore_pressure_pa')[0, 0]),
        history='(source_kappa + radial_plastic_kappa)/cell mass; engineering plastic only',
        pressure='full solved mean; full physical gravity and boundary traction; no hydrostatic subtraction')


def refresh_radial_strength(source, state, native_plan, *, budget=None):
    """Read actual owned current enthalpy and separate plastic tracers.

    The native plan must bind this exact source in its definition. Its state
    parser checks its plan/runtime identity and reference inventories. The
    enclosing owner's accepted-chain check still owns ordering/branch authority.
    """
    if getattr(native_plan, '_radial_constitutive', None) is not source:
        raise RadialStrengthRefused('current native plan does not own this radial constitutive declaration')
    native_descriptor(source)
    source._map.native_binding(native_plan)
    n = len(source._materials)
    with select_budget(budget).reserve(65536+16384*n, category='radial-strength-refresh'):
        _, _, mass, temperature, _, _, _, histories = native_plan._fields(state)
        if 'source_kappa' not in histories or PLASTIC_HISTORY not in histories:
            raise RadialStrengthRefused('separate original and incremental plastic histories required')
        kappa = (histories['source_kappa']+histories[PLASTIC_HISTORY])/mass
        if np.any(kappa < 0) or not np.isfinite(kappa).all():
            raise RadialStrengthRefused('raw engineering plastic history is invalid')
        fields = {k: source.array(k) for k in source.array_names}
        fields['temperature_k'] = np.repeat(temperature.reshape(n, 1), 27, axis=1)
        fields['plastic_kappa'] = np.repeat(kappa.reshape(n, 1), 27, axis=1)
        fields['component_mass_kg'] = state.array('component_mass_kg')
        record = dict(source.descriptor(), initial_source_id=source.source_id,
            native_state_id=state.result_id, native_plan_id=native_plan.plan_id,
            time_s=state.descriptor()['time_s'],
            temperature='actual current native enthalpy/(mass*cp); shared-cell FV temperature',
            history='actual current (source_kappa+radial_plastic_kappa)/mass; never accumulated_strain_ii',
            ownership_scope='initial source labels identify components; current component masses own positions')
        result = object.__new__(RadialStrengthSource)
        for key, value in (('_snapshot', RegionalMechanicalSnapshot(record, fields)),
                           ('_materials', source._materials), ('_creep', source._creep), ('_map', source._map)):
            object.__setattr__(result, key, value)
        return result


@dataclass(frozen=True, slots=True)
class RadialStrengthResult:
    mechanics: RegionalMechanicalSnapshot
    constitutive: RegionalMechanicalSnapshot
    iterations: int
    constitutive_log_residual: float


def solve_radial_strength(plan, source, body_force_n_m3, velocity_m_s, traction_pa, *,
        parent_state_id, epoch_id, time_s, force_source, boundary_source, coupling=None, cancel=None,
        hydrostatic_lift=None, residual_body_force_n_m3=None):
    """Full native momentum/pressure and current rheology at the same snapshot.

    The caller supplies ALL actual loads, including any reference gravity and
    normal traction. This adapter adds none. The original plan is not mutated;
    at most one changed-viscosity operator is retained, then released.
    """
    if type(plan) is not PreparedRegionalStokes3D or type(source) is not RadialStrengthSource:
        raise RadialStrengthRefused('typed full-3D native plan and radial source required')
    source.bind(plan)
    meta = source.descriptor()
    if epoch_id != meta['epoch_id'] or time_s != meta['time_s']:
        raise RadialStrengthRefused('mechanics time/epoch differs from its source material snapshot')
    if parent_state_id != meta.get('native_state_id', meta['source']['sphere_state_id']):
        raise RadialStrengthRefused('mechanics parent differs from its actual source snapshot')
    if not plan._physical:
        raise RadialStrengthRefused('actual mean-pressure datum or natural normal traction required')
    request = dict(parent_state_id=parent_state_id, epoch_id=epoch_id, time_s=time_s,
                   force_source=force_source, boundary_source=boundary_source, cancel=cancel)
    if hydrostatic_lift is not None or residual_body_force_n_m3 is not None:
        request.update(hydrostatic_lift=hydrostatic_lift, residual_body_force_n_m3=residual_body_force_n_m3)
    if coupling is not None:
        required = {'boundary_modes_m', 'external_generalized_force_j', 'external_resistance_j_s', 'source',
                    'pressure_reference_id'}
        if type(coupling) is dict and 'natural_traction_binding' in coupling:
            required.add('natural_traction_binding')
        if type(coupling) is not dict or set(coupling) != required or plan._pressure_reference is None:
            raise RadialStrengthRefused('coupled full strength requires an explicit same-field pressure-reference partition')
    current = plan
    try:
        with plan._resource.reserve(65536+32768*len(source._materials), category='radial-strength-mechanics'):
            for iteration in range(1, MAX_ITERATIONS+1):
                if coupling is None:
                    solved = current.solve(body_force_n_m3, velocity_m_s, traction_pa, **request)
                else:
                    solved = current.solve_force_coupled(body_force_n_m3, velocity_m_s, traction_pa,
                        coupling['boundary_modes_m'], coupling['external_generalized_force_j'],
                        coupling['external_resistance_j_s'], coupling_source=coupling['source'],
                        pressure_reference_id=coupling['pressure_reference_id'],
                        **({} if 'natural_traction_binding' not in coupling else
                           {'natural_traction_binding': coupling['natural_traction_binding']}), **request)
                grad = solved.array('velocity_gradient_s_inv')
                strain = (grad+grad.swapaxes(-1, -2))/2
                # Q1 pressure at precisely the mechanical Gauss points. Native
                # 2*eta*D includes a numerical trace; subtract it from p to get
                # -tr(sigma)/3, preserving the identical full stress tensor.
                if 'physical_pressure_q_pa' in solved.array_names:
                    pressure = solved.array('physical_pressure_q_pa').copy()
                else:
                    nodal = solved.array('physical_pressure_pa')
                    pressure = np.einsum('qa,ea->eq', current._mesh._shape_p,
                                         nodal[current._mesh.pressure_cells])
                trace = np.trace(strain, axis1=-2, axis2=-1)
                pressure -= (2/3)*current._eta*trace
                response = evaluate_radial_strength(source, strain, pressure,
                                                    budget=plan._resource, cancel=cancel)
                eta = response.array('viscosity_pa_s')
                difference = float(np.max(np.abs(np.log(eta)-np.log(current._eta))))
                if difference <= LOG_TOL:
                    fields = {k: response.array(k) for k in response.array_names}
                    fields['native_viscosity_pa_s'] = current._eta
                    fields['numerical_volumetric_viscous_work_w_m3'] = (2/3)*current._eta*trace*trace
                    response = RegionalMechanicalSnapshot(dict(response.descriptor(),
                        mechanical_result_id=solved.result_id, iterations=iteration,
                        constitutive_log_residual=difference, source=meta['source'],
                        volume_map_id=meta['volume_map_id'], numerical_trace='pressure corrected to -tr(sigma)/3; '
                        'numerical volumetric viscous work is separate, not plastic/creep heat'), fields)
                    return RadialStrengthResult(solved, response, iteration, difference)
                # The plan's owner declaration remains stable across iterations;
                # the actual current source is separately bound in the response.
                current = current.with_viscosity(eta, material_source=plan.descriptor()['material_source'],
                                                cancel=cancel, release=current is not plan)
            raise RadialStrengthRefused('3D radial constitutive iteration did not converge; no history or heat booked')
    finally:
        if current is not plan:
            current.close()
