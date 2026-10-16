"""Dry C01; contract: docs/W07_SURFACE_STRENGTH.md.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import asdict, dataclass
import json
import math
from time import perf_counter
from types import MappingProxyType

import numpy as np

from ._validation import TectonicsError, scalar, input_shape, read_array, frozen
from .constitutive import _cancel, _json
from .regional_execution import (PreparedRegionalStokes2D, RegionalMechanicalSnapshot,
                                 _array_hash, _hash, _name)
from .regional_rheology import _same_state, _validate_boundary_support
from .resources import select_budget
from .stokes_execution import _factored_scale

_METHOD = 'atlas.regional-dry-strength-c01.v1'
_SAMPLING = ('C01 plane-strain collocation v1: centre shear=four-vertex mean; '
             'vertex normal strain and PHYSICAL pressure=bilinear centre reconstruction '
             'with linear boundary extrapolation; no viscosity average')


@dataclass(frozen=True, slots=True)
class DryStrengthProfile:
    """Explicit SI parameters and validity limits, with no implicit defaults."""
    name: str
    source: str
    cohesion_pa: float
    friction_angle_rad: float
    creep_viscosity_pa_s: float
    viscosity_validity_pa_s: tuple[float, float]
    tensile_strength_pa: float
    pore_pressure_pa: float

    def __post_init__(self):
        _name(self.name, 'strength profile name'); _name(self.source, 'strength profile source')
        for key in ('cohesion_pa', 'creep_viscosity_pa_s'):
            object.__setattr__(self, key, scalar(getattr(self, key), key, positive=True))
        angle = scalar(self.friction_angle_rad, 'friction angle', nonnegative=True)
        if angle >= math.pi/2:
            raise TectonicsError('friction angle must lie in [0,pi/2) radians')
        object.__setattr__(self, 'friction_angle_rad', angle)
        object.__setattr__(self, 'tensile_strength_pa', scalar(self.tensile_strength_pa, 'tensile strength', nonnegative=True))
        pore = scalar(self.pore_pressure_pa, 'explicit pore pressure')
        if pore != 0.:
            raise TectonicsError('the dry C01 family requires explicit zero pore pressure')
        object.__setattr__(self, 'pore_pressure_pa', pore)
        if type(self.viscosity_validity_pa_s) is not tuple or len(self.viscosity_validity_pa_s) != 2:
            raise TectonicsError('explicit viscosity validity pair required')
        lo, hi = (scalar(v, 'viscosity validity', positive=True) for v in self.viscosity_validity_pa_s)
        if not lo <= self.creep_viscosity_pa_s <= hi:
            raise TectonicsError('creep viscosity must lie within the declared validity interval')
        object.__setattr__(self, 'viscosity_validity_pa_s', (lo, hi))

    def descriptor(self):
        result = {'method': _METHOD, **asdict(self)}
        return dict(result, profile_id=_hash(result))


def evaluate_dry_strength(profile, physical_pressure_pa, strain_xx_s_1,
        strain_zz_s_1, strain_xz_s_1, *, divergence_tolerance_s_1=0., budget=None, cancel=None):
    """Immutable broadcast SI C01 response; explicit divergence tolerance, no clipping."""
    if type(profile) is not DryStrengthProfile:
        raise TectonicsError('typed dry C01 profile required')
    tolerance = scalar(divergence_tolerance_s_1, 'divergence tolerance', nonnegative=True)
    values = (physical_pressure_pa, strain_xx_s_1, strain_zz_s_1, strain_xz_s_1)
    shapes = tuple(input_shape(value) for value in values)
    try:
        shape = np.broadcast_shapes(*shapes)
    except ValueError as exc:
        raise TectonicsError('C01 point supports do not broadcast') from exc
    count = math.prod(shape)
    if not 1 <= count <= 16384:
        raise TectonicsError('C01 point evaluation supports at most 16384 samples')
    _cancel(cancel)
    with select_budget(budget).reserve(256*count+64*sum(math.prod(s) for s in shapes)+65536,
                                       category='regional-strength-evaluate'):
        p, xx, zz, xz = np.broadcast_arrays(*(read_array(v, 'C01 input') for v in values))
        if p.shape != shape:
            raise TectonicsError('C01 input support changed during capture')
        try:
            with np.errstate(over='raise', invalid='raise', divide='raise', under='ignore'):
                effective = p-profile.pore_pressure_pa
                if np.any(effective < 0.):
                    raise TectonicsError('negative effective pressure is outside dry C01')
                if np.any(np.abs(xx+zz) > tolerance):
                    raise TectonicsError('C01 requires isochoric plane-strain inputs within the explicit divergence tolerance')
                invariant = np.hypot(np.hypot(xx/np.sqrt(2.), zz/np.sqrt(2.)), xz)
                strength = (profile.cohesion_pa*math.cos(profile.friction_angle_rad)
                            +effective*math.sin(profile.friction_angle_rad))
                # Log comparison avoids overflow in the trial stress 2*eta*eII.
                log_rate = np.full(shape, -np.inf)
                np.log(invariant, out=log_rate, where=invariant > 0.)
                yielded = log_rate+math.log(profile.creep_viscosity_pa_s)+math.log(2.) > np.log(strength)
                eta = np.full(shape, profile.creep_viscosity_pa_s)
                np.divide(.5*strength, invariant, out=eta, where=yielded)
                lo, hi = profile.viscosity_validity_pa_s
                if np.any((eta < lo)|(eta > hi)):
                    raise TectonicsError('C01 viscosity outside declared validity; clipping is forbidden')
                txx, tzz, txz = 2*(eta*xx), 2*(eta*zz), 2*(eta*xz)
                # Normalised eigenvalue formula avoids avoidable intermediate
                # overflow when pressure and deviatoric principal stresses cancel.
                scale = np.maximum.reduce((np.abs(txx), np.abs(tzz), np.abs(txz), effective))
                divisor = np.where(scale == 0., 1., scale)
                ax, az, axz, pressure = txx/divisor, tzz/divisor, txz/divisor, effective/divisor
                largest = np.maximum(-pressure, .5*ax+.5*az+np.hypot(.5*ax-.5*az, axz)-pressure)*scale
                if np.any(largest > profile.tensile_strength_pa):
                    raise TectonicsError('largest principal effective stress exceeds the tensile envelope')
                tau_ii = np.hypot(np.hypot(txx/np.sqrt(2.), tzz/np.sqrt(2.)), txz)
        except FloatingPointError as exc:
            raise TectonicsError('C01 evaluation outside finite binary64 support') from exc
        _cancel(cancel)
        result = {'viscosity_pa_s': eta, 'yield_stress_pa': strength, 'strain_rate_ii_s_1': invariant,
                  'stress_ii_pa': tau_ii, 'largest_effective_principal_stress_pa': largest,
                  'effective_pressure_pa': effective, 'yielded': yielded.astype(float),
                  'deviatoric_stress_xx_pa': txx, 'deviatoric_stress_zz_pa': tzz,
                  'deviatoric_stress_xz_pa': txz}
        return MappingProxyType({name: frozen(value) for name, value in result.items()})


def _vertices(a):
    """Bilinear centre reconstruction with declared linear boundary extrapolation."""
    h = np.empty((a.shape[0], a.shape[1]+1))
    h[:, 1:-1] = .5*a[:, :-1]+.5*a[:, 1:]
    h[:, 0], h[:, -1] = 1.5*a[:, 0]-.5*a[:, 1], 1.5*a[:, -1]-.5*a[:, -2]
    out = np.empty((a.shape[0]+1, a.shape[1]+1))
    out[1:-1] = .5*h[:-1]+.5*h[1:]
    out[0], out[-1] = 1.5*h[0]-.5*h[1], 1.5*h[-1]-.5*h[-2]
    return out


def _snapshot_law(plan, profile, snapshot, cancel):
    """Only physical pressure participates; no dynamic-gauge pressure substitution."""
    if 'physical_pressure_pa' not in snapshot.array_names:
        raise TectonicsError('C01 requires a defined physical pressure datum')
    xx, zz, xz = (snapshot.array('strain_'+axis+'_s_1') for axis in ('xx', 'zz', 'xz'))
    xc = .25*xz[:-1, :-1]+.25*xz[1:, :-1]+.25*xz[:-1, 1:]+.25*xz[1:, 1:]
    pressure = snapshot.array('physical_pressure_pa')
    definition = plan.descriptor()
    # Boundary tensor extrapolation can multiply the admitted centre divergence
    # by at most four (sum of absolute bilinear weights at an exterior corner).
    divergence_limit = float(_factored_scale(
        np.asarray(snapshot.descriptor()['diagnostics']['divergence_normalisation']),
        (1e-10, definition['scales']['velocity_m_s']), (definition['scales']['length_m'],),
        'C01 admitted SI divergence'))
    centre = evaluate_dry_strength(profile, pressure, xx, zz, xc,
        divergence_tolerance_s_1=divergence_limit, budget=plan._resource, cancel=cancel)
    vertex = evaluate_dry_strength(profile, _vertices(pressure), _vertices(xx), _vertices(zz), xz,
        divergence_tolerance_s_1=4*divergence_limit, budget=plan._resource, cancel=cancel)
    return centre, vertex


@dataclass(frozen=True, slots=True)
class RegionalStrengthResult:
    mechanics: RegionalMechanicalSnapshot
    _metadata: bytes

    def descriptor(self):
        return json.loads(self._metadata)


def solve_regional_strength(plan, profile, force_u_n_m3, force_w_n_m3, boundary_values, *,
        frame_id, epoch_id, time_s, material_source, force_source, boundary_source,
        cancel=None, max_iterations=40):
    """Creep-start C01 Picard; accept physical-pressure/current-law fields under fixed gates."""
    start = perf_counter()
    if type(plan) is not PreparedRegionalStokes2D or type(profile) is not DryStrengthProfile:
        raise TectonicsError('typed regional plan and dry C01 profile required')
    if type(max_iterations) is not int or not 1 <= max_iterations <= 40:
        raise TectonicsError('C01 requires 1..40 finite Picard iterations')
    d = plan.descriptor()
    if frame_id != d['frame_id']:
        raise TectonicsError('regional strength frame mismatch')
    if d['pressure_gauge_required'] and d['physical_mean_pressure_pa'] is None:
        raise TectonicsError('C01 requires physical pressure from an explicit datum or normal traction')
    for value, name in ((epoch_id, 'epoch'), (material_source, 'material source'),
                        (force_source, 'force source'), (boundary_source, 'boundary source')):
        _name(value, name)
    time_s = scalar(time_s, 'strength snapshot time')
    shapes = (d['nz'], d['nx']), (d['nz']+1, d['nx']+1)
    if input_shape(force_u_n_m3) != (d['nz'], d['nx']+1) or input_shape(force_w_n_m3) != (d['nz']+1, d['nx']):
        raise TectonicsError('regional body forces require complete staggered supports')
    _validate_boundary_support(d, boundary_values)
    _cancel(cancel)
    count = sum(math.prod(shape) for shape in shapes)
    with plan._resource.reserve(512*count+262144, category='regional-strength-state'):
        forces = read_array(force_u_n_m3, 'strength force u'), read_array(force_w_n_m3, 'strength force w')
        boundary = {s: {c: scalar(v, 'boundary value') if input_shape(v) == () else
                            frozen(read_array(v, 'boundary value')) for c, v in parts.items()}
                    for s, parts in boundary_values.items()}
        binding = {'profile': profile.descriptor(), 'frame_id': frame_id, 'epoch_id': epoch_id,
                   'time_s': time_s, 'material_source': material_source, 'sampling': _SAMPLING,
                   'pressure_source': {'physical_mean_pressure_pa': d['physical_mean_pressure_pa'],
                       'reference_pressure': d['reference_pressure'], 'boundary_source': boundary_source},
                   'strain_convention': 'full plane-strain Dyy=0, eII=sqrt(D:D/2), admitted numerical divergence only'}
        source = 'regional-C01='+_hash(binding)
        viscosity = tuple(np.full(shape, profile.creep_viscosity_pa_s) for shape in shapes)
        plan.update_viscosity(*viscosity, material_source=source, material_sampling=_SAMPLING, cancel=cancel)
        history = []; evaluation_s = 0.
        request = dict(frame_id=frame_id, epoch_id=epoch_id, time_s=time_s,
                       force_source=force_source, boundary_source=boundary_source, cancel=cancel)
        for iteration in range(1, max_iterations+1):
            _cancel(cancel)
            solved = plan.solve(*forces, boundary, **request)
            t0 = perf_counter()
            response = _snapshot_law(plan, profile, solved, cancel)
            current = tuple(r['viscosity_pa_s'] for r in response)
            evaluation_s += perf_counter()-t0
            change = max(float(np.max(np.abs(np.log(new)-np.log(old)))) for new, old in zip(current, viscosity))
            plan.update_viscosity(*current, material_source=source, material_sampling=_SAMPLING, cancel=cancel)
            accepted, diagnostics = _same_state(plan, solved, cancel, publish=change <= 1e-8)
            history.append({'iteration': iteration, 'viscosity_log_change': change,
                            'momentum_residual': diagnostics['momentum_residual'],
                            'normalised_work_residual': diagnostics['normalised_work_residual']})
            if accepted is not None and change <= 1e-8:
                fields = {name: accepted.array(name) for name in accepted.array_names}
                for support, reply in zip(('center', 'vertex'), response):
                    for name, array in reply.items():
                        fields['strength_'+support+'_'+name] = array
                mechanics = RegionalMechanicalSnapshot(dict(accepted.descriptor(), strength_binding=binding), fields)
                metadata = {'schema': 'atlas.regional-strength-snapshot.v1', 'binding': binding,
                    'mechanical_result_id': mechanics.result_id, 'linear_solve_result_id': solved.result_id,
                    'used_viscosity_hashes': [_array_hash(a) for a in viscosity],
                    'current_law_viscosity_hashes': [_array_hash(a) for a in current],
                    'iterations': iteration, 'history': history, 'viscosity_log_change': change,
                    'current_law_diagnostics': diagnostics, 'viscosity_clipping': False,
                    'damage_evolved': False, 'strain_softening': False, 'localisation_claim': False,
                    'time_advanced': False, 'timings': {'law_evaluation_s': evaluation_s, 'total_s': perf_counter()-start}}
                _cancel(cancel)
                return RegionalStrengthResult(mechanics, _json(metadata))
            viscosity = current
        raise TectonicsError('C01 did not converge within the fixed Picard envelope; '+str(history[-1]))
