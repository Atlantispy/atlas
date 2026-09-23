"""W07 regional snapshots using source-explicit retained constitutive laws.

SPDX-License-Identifier: AGPL-3.0-only

Picard updates retain the exact Tosi Frobenius/factor-two conventions and the
BF23 fixed-damage law in constitutive.evaluate_rheology. No clipping, damage
evolution, pressure-sensitive yielding or hidden temperature transfer occurs.
"""
from dataclasses import asdict, dataclass
import json
from time import perf_counter

import numpy as np

from ._validation import TectonicsError, scalar, input_shape, read_array, frozen
from .constitutive import DiffusiveScales, RheologyProfile, evaluate_rheology, _cancel, _json
from .regional_execution import (PreparedRegionalStokes2D, RegionalMechanicalSnapshot,
                                 _array_hash, _hash, _name)
from .stokes_execution import _factored_scale

_SAMPLING = ('regional-tensor-collocation-v1: centre shear=four-vertex mean; '
             'vertex normal strain=bilinear centre reconstruction with linear boundary extrapolation; '
             'temperature and damage=explicit samples at both stress supports')


def _validate_boundary_support(definition, values):
    """Bound support before adapters copy any caller-owned boundary arrays."""
    if (not isinstance(values,dict) or set(values)!=set(definition['boundary_types']) or
            any(not isinstance(parts,dict) or set(parts)!={'u','w'} for parts in values.values())):
        raise TectonicsError('complete regional boundary values required')
    for side,parts in values.items():
        vertical=side in ('left','right')
        n=definition['nz'] if vertical else definition['nx']
        for component,value in parts.items():
            count=n+(2 if (component=='u')==vertical else 1)
            if input_shape(value) not in ((),(count,)):
                raise TectonicsError('boundary samples do not match declared supports')


@dataclass(frozen=True, slots=True)
class RegionalRheologyResult:
    """One immutable accepted current-law mechanics state and bounded metadata."""
    mechanics: RegionalMechanicalSnapshot
    _metadata: bytes

    def descriptor(self):
        return json.loads(self._metadata)


def _invariant_sites(exx, ezz, exz):
    """Return sqrt(D:D/2), including complete boundary shear support.

    The tensor components are collocated before taking their norm. Linear
    one-sided extrapolation of centre components preserves affine tensor fields
    at edges/corners; it is a declared reconstruction, not a viscosity mixture.
    """
    def vertices(a):
        horizontal = np.empty((a.shape[0], a.shape[1]+1))
        horizontal[:, 1:-1] = .5*a[:, :-1]+.5*a[:, 1:]
        horizontal[:, 0] = 1.5*a[:, 0]-.5*a[:, 1]
        horizontal[:, -1] = 1.5*a[:, -1]-.5*a[:, -2]
        out = np.empty((a.shape[0]+1, a.shape[1]+1))
        out[1:-1] = .5*horizontal[:-1]+.5*horizontal[1:]
        out[0] = 1.5*horizontal[0]-.5*horizontal[1]
        out[-1] = 1.5*horizontal[-1]-.5*horizontal[-2]
        return out
    centre_shear = .25*exz[:-1, :-1]+.25*exz[1:, :-1]+.25*exz[:-1, 1:]+.25*exz[1:, 1:]
    return (np.hypot(np.hypot(exx, ezz)/np.sqrt(2.), centre_shear),
            np.hypot(np.hypot(vertices(exx), vertices(ezz))/np.sqrt(2.), exz))


def _same_state(plan, snapshot, cancel, *, publish=True):
    """Recompute physical fields with the currently installed coefficients.

    No solve is performed. The previous linear solution is explicitly identified;
    this publication certifies the fixed nonlinear field gates, not a new strict
    linear residual for the changed material operator.
    """
    from .regional_stokes import boundary_coordinates
    with plan._operation(cancel), plan._resource.reserve(1024*plan._upper+262144,
                                                        category='regional-current-law'):
        d = plan.descriptor()
        previous = snapshot.descriptor()
        length, velocity = d['scales']['length_m'], d['scales']['velocity_m_s']
        eta = d['viscosity_pa_s']
        reference = d['reference_pressure']
        top, rho_g = (0., 0.) if reference is None else (
            reference['top_pressure_pa'], reference['density_times_gravity_n_m3'])
        def pref(z):
            return top+rho_g*(d['height_m']-z)
        fx, fz = snapshot.array('force_u_n_m3'), snapshot.array('force_w_n_m3')
        nu = _factored_scale(fx, (length, length), (eta, velocity), 'current law force u')
        nw = _factored_scale(fz+rho_g, (length, length), (eta, velocity), 'current law force w')
        core = plan._core
        full = np.zeros(core.full_velocity_unknowns)
        full[core._iu[1:-1]] = _factored_scale(snapshot.array('u_m_s'), (), (velocity,), 'current law u')
        full[core._iw[:, 1:-1]] = _factored_scale(snapshot.array('w_m_s'), (), (velocity,), 'current law w')
        p = _factored_scale(snapshot.array('dynamic_pressure_pa'), (length,), (eta, velocity), 'current law pressure')
        bc = {}
        normals = {'left': (-1., 0.), 'right': (1., 0.), 'bottom': (0., -1.), 'top': (0., 1.)}
        for side, components in d['boundary_types'].items():
            bc[side] = {}
            for component, kind in components.items():
                suffix = side+'_'+component
                full[core._indices[side][component]] = _factored_scale(
                    snapshot.array('boundary_velocity_'+suffix+'_m_s'), (), (velocity,), 'current law boundary velocity')
                value = snapshot.array('boundary_input_'+suffix)
                if kind == 'velocity':
                    value = _factored_scale(value, (), (velocity,), 'current law velocity trace')
                else:
                    _, z = boundary_coordinates(d['nx'], d['nz'], d['width_m'], d['height_m'], side, component)
                    normal = normals[side][0 if component == 'u' else 1]
                    value = _factored_scale(value+normal*pref(z), (length,), (eta, velocity), 'current law traction')
                bc[side][component] = (kind, value)
        raw = core.evaluate(full, p, nu, nw, boundaries=bc, cancel=cancel)
        diagnostics = {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in raw['diagnostics'].items()}
        if not diagnostics['gates_passed'] or not publish:
            return None, diagnostics
        arrays = {name: snapshot.array(name) for name in snapshot.array_names}
        arrays['viscosity_center_pa_s'], arrays['viscosity_vertex_pa_s'] = plan._viscosity
        total_pressure = -snapshot.array('stress_yy_pa')
        for axis in ('xx', 'zz', 'xz'):
            arrays['strain_'+axis+'_s_1'] = _factored_scale(raw['e'+axis], (velocity,), (length,), 'current law strain')
            stress = _factored_scale(raw['tau_'+axis], (eta, velocity), (length,), 'current law stress')
            arrays['deviatoric_stress_'+axis+'_pa'] = stress
            arrays['stress_'+axis+'_pa'] = stress-(0. if axis == 'xz' else total_pressure)
        arrays['effective_boundary_reaction_force_n_per_m'] = _factored_scale(
            raw['boundary_reactions'], (eta, velocity), (), 'current law reaction')
        datum = d['physical_mean_pressure_pa']
        zc = (np.arange(d['nz'])+.5)*d['height_m']/d['nz']
        offset = 0. if datum is None else datum-float(np.mean(pref(zc)))
        for side, parts in raw['boundary_tractions'].items():
            for component, traction in parts.items():
                _, z = boundary_coordinates(d['nx'], d['nz'], d['width_m'], d['height_m'], side, component)
                normal = normals[side][0 if component == 'u' else 1]
                arrays['boundary_traction_'+side+'_'+component+'_pa'] = _factored_scale(
                    traction, (eta, velocity), (length,), 'current law boundary stress')-normal*(pref(z)+offset)
        dimensional = {}
        for name in ('dissipation', 'body_work', 'prescribed_traction_work', 'reaction_work',
                     'total_boundary_work', 'work_residual'):
            dimensional[name+'_w_per_m'] = float(_factored_scale(np.asarray(diagnostics[name]),
                (eta, velocity, velocity), (), 'current law power'))
        for source, target, numerator, denominator in (
            ('net_boundary_flux', 'net_boundary_flux_m2_s', (velocity, length), ()),
            ('net_force', 'net_force_n_per_m', (eta, velocity), ()),
            ('net_torque', 'net_torque_n', (eta, velocity, length), ()),
            ('max_free_force_residual', 'max_free_force_residual_n_per_m', (eta, velocity), ()),
            ('max_divergence', 'max_divergence_s_1', (velocity,), (length,))):
            dimensional[target] = _factored_scale(np.asarray(diagnostics[source]), numerator, denominator,
                                                 'current law dimensional diagnostic').tolist()
        request = dict(previous['request'], plan_id=plan.plan_id)
        metadata = dict(previous, definition=d, request=request, request_id=_hash(request),
            diagnostics=diagnostics, dimensional_diagnostics=dimensional,
            mechanical_acceptance='current-law nonlinear field gates at unchanged physical velocity and pressure',
            linear_solve_origin={'result_id': snapshot.result_id, 'plan_id': previous['request']['plan_id'],
                                 'linear_residual': previous['diagnostics']['linear_residual']})
        return RegionalMechanicalSnapshot(metadata, arrays), diagnostics


def solve_regional_rheology(plan, profile, scales, thermal_center_k, thermal_vertex_k,
        force_u_n_m3, force_w_n_m3, boundary_values, *, frame_id, epoch_id, time_s,
        thermal_source, material_source, force_source, boundary_source,
        damage_center=None, damage_vertex=None, cancel=None, max_iterations=40):
    """Return a current-law regional snapshot; all temperature supports are supplied.

    Depth is measured down from the regional top. Invariants are computed in SI
    then multiplied by L^2/kappa; temperature and viscosity use DiffusiveScales.
    Damage is captured once and held fixed. Picard starts at the analytical
    zero-rate viscosity; no artificial tiny rate is introduced.
    """
    start = perf_counter()
    if type(plan) is not PreparedRegionalStokes2D or type(profile) is not RheologyProfile or type(scales) is not DiffusiveScales:
        raise TectonicsError('typed regional plan, retained rheology profile and diffusive scales required')
    if profile.viscosity_bounds is not None:
        raise TectonicsError('regional rheology refuses numerical viscosity clipping')
    if type(max_iterations) is not int or not 1 <= max_iterations <= 40:
        raise TectonicsError('regional rheology requires 1..40 finite Picard iterations')
    d = plan.descriptor()
    if frame_id != d['frame_id']:
        raise TectonicsError('regional rheology frame mismatch')
    if d['height_m'] > scales.depth_scale_m:
        raise TectonicsError('regional height exceeds the law depth normalisation')
    for value, name in ((epoch_id, 'epoch'), (thermal_source, 'thermal source'),
                        (material_source, 'material source'), (force_source, 'force source'),
                        (boundary_source, 'boundary source')):
        _name(value, name)
    time_s = scalar(time_s, 'mechanical time')
    shapes = ((d['nz'], d['nx']), (d['nz']+1, d['nx']+1))
    if input_shape(thermal_center_k) != shapes[0] or input_shape(thermal_vertex_k) != shapes[1]:
        raise TectonicsError('explicit temperature arrays required on both complete stress supports')
    if input_shape(force_u_n_m3) != (d['nz'], d['nx']+1) or input_shape(force_w_n_m3) != (d['nz']+1, d['nx']):
        raise TectonicsError('regional body forces require full staggered face shapes')
    _validate_boundary_support(d,boundary_values)
    if profile.family == 'bf23-memory':
        if input_shape(damage_center) != shapes[0] or input_shape(damage_vertex) != shapes[1]:
            raise TectonicsError('BF requires explicit frozen damage on both stress supports')
    elif damage_center is not None or damage_vertex is not None:
        raise TectonicsError('only BF regional snapshots accept frozen damage')
    _cancel(cancel)
    count = sum(int(np.prod(s)) for s in shapes)
    with plan._resource.reserve(256*count+262144, category='regional-rheology-state'):
        temperatures = tuple(frozen(read_array(v, 'stress-site temperature')) for v in (thermal_center_k, thermal_vertex_k))
        damages = ((frozen(read_array(damage_center, 'centre damage')), frozen(read_array(damage_vertex, 'vertex damage')))
                   if profile.family == 'bf23-memory' else (None, None))
        loads = read_array(force_u_n_m3, 'regional force u'), read_array(force_w_n_m3, 'regional force w')
        boundary = {s: {c: scalar(v, 'regional boundary value') if input_shape(v) == () else
                            frozen(read_array(v, 'regional boundary value')) for c, v in parts.items()}
                    for s, parts in boundary_values.items()}
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise'):
                thermal = tuple((t-scales.surface_temperature_k)/scales.temperature_scale_k for t in temperatures)
                zc = (d['height_m']-(np.arange(d['nz'])+.5)*d['height_m']/d['nz'])/scales.depth_scale_m
                zv = (d['height_m']-np.arange(d['nz']+1)*d['height_m']/d['nz'])/scales.depth_scale_m
        except FloatingPointError as exc:
            raise TectonicsError('regional thermal/depth scaling outside binary64') from exc
        depths = np.broadcast_to(zc[:, None], shapes[0]), np.broadcast_to(zv[:, None], shapes[1])
        binding = {'profile': profile.descriptor(), 'scales': asdict(scales), 'frame_id': frame_id,
                   'epoch_id': epoch_id, 'time_s': time_s, 'thermal_source': thermal_source,
                   'material_source': material_source, 'thermal_hashes': [_array_hash(a) for a in temperatures],
                   'damage_hashes': [None if a is None else _array_hash(a) for a in damages],
                   'sampling': _SAMPLING, 'depth': 'distance down from regional top / depth_scale_m'}
        law_source = 'regional-law='+_hash(binding)
        coefficient_s = 0.
        def law(rates):
            nonlocal coefficient_s
            t0 = perf_counter()
            values = tuple(evaluate_rheology(profile, t, z,
                _factored_scale(rate, (scales.time_s,), (), 'dimensionless regional invariant'), damage,
                budget=plan._resource, cancel=cancel)['viscosity']
                for t, z, rate, damage in zip(thermal, depths, rates, damages))
            out = tuple(_factored_scale(a, (scales.viscosity_pa_s,), (), 'regional law viscosity') for a in values)
            coefficient_s += perf_counter()-t0
            return out
        viscosities = law(tuple(np.zeros(shape) for shape in shapes))
        plan.update_viscosity(*viscosities, material_source=law_source, material_sampling=_SAMPLING, cancel=cancel)
        history = []
        request = dict(frame_id=frame_id, epoch_id=epoch_id, time_s=time_s,
                       force_source=force_source, boundary_source=boundary_source, cancel=cancel)
        for iteration in range(1, max_iterations+1):
            _cancel(cancel)
            solved = plan.solve(*loads, boundary, **request)
            rates = _invariant_sites(*(solved.array('strain_'+axis+'_s_1') for axis in ('xx', 'zz', 'xz')))
            current = law(rates)
            change = max(float(np.max(np.abs(np.log(new)-np.log(old)))) for old, new in zip(viscosities, current))
            plan.update_viscosity(*current, material_source=law_source, material_sampling=_SAMPLING, cancel=cancel)
            accepted, diagnostics = _same_state(plan, solved, cancel, publish=change <= 1e-8)
            history.append({'iteration': iteration, 'viscosity_log_change': change,
                            'momentum_residual': diagnostics['momentum_residual'],
                            'normalised_work_residual': diagnostics['normalised_work_residual']})
            if change <= 1e-8 and accepted is not None:
                _cancel(cancel)
                metadata = {'schema': 'atlas.regional-rheology-snapshot.v1', 'binding': binding,
                    'mechanical_result_id': accepted.result_id, 'linear_solve_result_id': solved.result_id,
                    'used_viscosity_hashes': [_array_hash(a) for a in viscosities],
                    'current_law_viscosity_hashes': [_array_hash(a) for a in current],
                    'iterations': iteration, 'history': history, 'viscosity_log_change': change,
                    'current_law_diagnostics': diagnostics,
                    'acceptance': 'log viscosity <=1e-8 and unchanged frozen momentum/divergence/gauge/work gates',
                    'viscosity_clipping': False, 'damage_evolved': False, 'time_advanced': False,
                    'timings': {'coefficient_evaluation_s': coefficient_s, 'total_s': perf_counter()-start}}
                return RegionalRheologyResult(accepted, _json(metadata))
            viscosities = current
        raise TectonicsError('regional rheology did not converge within the fixed Picard envelope; '+str(history[-1]))
