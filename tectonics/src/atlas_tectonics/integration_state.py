"""I02.1 common physical-state envelope around the real finite-strain column, continued by I02.2b. WORKING NON-CANON.

One immutable, bounded, versioned record of an accepted state: world/scenario, named epoch and forward SI time,
lineage, frame and process support, units, vertical and thermal references, source/runtime identities, closure,
constitutive parameters and numerical policy. Every quantity has one producer and one accounting owner; absent
physics is declared unknown, never zero-filled. The first route is the layered constant-drive finite-strain column of
the I01 finite-strain control. Package code never imports that campaign tool: callers hand over its pinned
preparation inputs and prepared reference values, which are checked against each other and bound by the retained
preparation fingerprints before anything is accepted. Declared support is not empirical truth.

Native payloads are reused, not flattened or copied: a W02 MaterialState carries cohort identity, origin and
formation history; an optional W08Inventory carries finite exterior stocks in its own enthalpy convention. Native
material is never also counted as a reservoir. The envelope itself runs no physics. ``Continuation`` connects it to
the package-owned continuable core (integration_evolution): operators are rebuilt once from the pinned inputs, every
carried reference byte is reproduced, whole steps of the fixed schedule are advanced and verified successor states
are issued with parent lineage. There is no transfer, transaction, storage, accepted clock or event here, no births
and no physical admission. Holding a preparation fingerprint issues nothing to the finite-admission tool.
SPDX-License-Identifier: AGPL-3.0-only
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import math

import numpy as np

from . import _integration_column as _kernel
from . import _integration_heat as _heat
from . import _integration_motion as _motion
from . import _integration_weakening as _weakening
from . import integration_evolution as _evolution
from ._validation import TectonicsError, frozen, input_shape, scalar, snapshot
from .materials import MaterialState, _json, _name, _sha
from .mesh import ColumnGrid1D
from .resources import select_budget
from .timebase import advance_time


SCHEMA = 'atlas.i02-common-state.v1'
ROUTE = 'atlas.i02.finite-strain-column.v1'
UNIT_SYSTEM = 'SI: m, kg, s, K, J, Pa, N; strip extensive quantities per metre of strike'
COLUMN_THERMAL_BASIS = 'atlas.i02.finite-strain-departure-enthalpy.v1'
NOT_CONFERRED = 'NOT_CONFERRED'
# The retained route scope, taken from its package owners rather than mirrored: one copy of each.
LITHOSTATIC, SUPPLIED = _weakening.LITHOSTATIC, _weakening.SUPPLIED
REPRESENTATION = _evolution.REPRESENTATION
STRETCH_CEILING = _evolution.STRETCH_CEILING
TEMPERATURE_CEILING_K = _evolution.TEMPERATURE_CEILING_K
MAX_TEMPERATURE_STEP_K = _evolution.MAX_TEMPERATURE_STEP_K
MAX_STEPS = 256                          # _integration_heat.policy_limits's literal ceiling; no importable name
HORIZON_CEILING_S = 1e14
MAX_LAYERS, MAX_ORDER = _kernel.POLICY['max_layers'], _kernel.POLICY['max_order']
STAGE_ACCOUNTS = tuple(name for name, _ in _evolution.STAGE_ACCOUNTS)
THERMAL_ACCOUNTS = _evolution.THERMAL_ACCOUNTS
COUNTERS = ('stages', 'evaluations', 'iterations', 'restress_mismatches')
EXTREMA = ('max_force_relative', 'max_power_relative', 'min_source_w_m2', 'min_dissipation_w_m',
           'max_step_energy_relative', 'max_temperature_step_k')
SOLVER = {'conduction': True, 'geometry_feedback': True, 'warm_start': True,
          'thermal_operator': 'one reference eigensystem advanced along the thermal clock'}
GEOMETRY = ('local plane-strain strip frame: x across the strip width, z depth positive downward from the material '
            'surface, unit strike; laterally uniform')
VERTICAL_REFERENCE = ('material surface at z = 0, free and unloaded; material depth z0 at lam = 1 and current depth '
                      'z0/lam; absolute elevation is not represented')
THERMAL_REFERENCE = ("the prepared support's discrete steady geotherm; theta = T - T_steady at material points; never "
                     "reset to a stretched geotherm")
THERMAL_BASIS = ('sensible-heat departure from the fixed steady reference with constant per-material density and heat '
                 'capacity: w0 sum(C0 theta) per metre of strike; no absolute datum, latent or phase terms; not '
                 'interchangeable with a phase-equilibrium provider or a W08 stock enthalpy convention')
MAX_METADATA = 512 << 10
_LIMITS = _evolution.REPRESENTATION_LIMITS
_MECHANICAL = frozenset(('key', 'fingerprint', 'layer', 'depth_m', 'weight', 'reference_pa', 'density',
                         'thickness_m'))
_THERMAL = frozenset(('provider', 'inputs', 'fingerprint', 'mechanical_fingerprint', 'layer', 'depth_m', 'volume_m',
                      'reference_density_kg_m3', 'capacity', 'radiogenic', 'steady_k', 'boundary_temperature',
                      'thickness_m'))
_THERMAL_INPUTS = frozenset(('thicknesses', 'props', 'densities', 'boundaries', 'reference_temperature'))
_PROPS = frozenset(('name', 'conductivity_w_m_k', 'heat_capacity_j_kg_k', 'radiogenic_w_m3'))
PIECE_COMPLETE, HISTORY_COMPLETE, HISTORY_INCOMPLETE = 'PIECE_COMPLETE', 'HISTORY_COMPLETE', 'HISTORY_INCOMPLETE'
MATERIAL_ROLE = ('unchanged W02 reference inventory: cohort identity, origin, formation provenance and partial '
                 'thickness h_k at lam = 1, dated at the history start; current strip geometry is derived from the '
                 'reference and the accepted stretch at the state time, never written back')
RESERVOIR_ROLE = ('finite exterior stocks as dated by their native W08 owner; the closed strip transfers nothing, so '
                  'they are carried unchanged and are not re-dated')

_ACCOUNT_MEANINGS = (
    ('drive_work_j_m', 'work of the external drive on the moving strip edge'),
    ('drag_work_j_m', 'dissipation in the disjoint generalised drag; never column heat'),
    ('creep_work_j_m', 'column creep dissipation'),
    ('plastic_work_j_m', 'column plastic dissipation'),
    ('column_work_j_m', 'total work against the layered column resistance'),
    ('heat_j_m', 'mechanical heat deposited once in the column by the declared heat fractions'),
    ('stored_j_m', 'column work not converted to heat'),
    ('radiogenic_j_m', 'radiogenic heat produced'),
    ('reference_outflow_j_m', 'radiogenic production carried off by the steady reference along the thermal clock'),
    ('departure_surface_loss_j_m', 'departure heat leaving through the surface; positive is a loss'),
    ('departure_basal_gain_j_m', 'departure heat entering through the strip base; positive is a gain'),
    ('reference_surface_loss_j_m', 'steady-reference surface outflow along the thermal clock'),
    ('reference_basal_gain_j_m', 'steady-reference basal inflow along the thermal clock'),
    ('thermal_change_j_m', 'change of departure thermal content w0 sum(C0 dtheta)'),
)
_EXTREMA_UNITS = (('max_force_relative', '1'), ('max_power_relative', '1'), ('min_source_w_m2', 'W/m2'),
                  ('min_dissipation_w_m', 'W/m'), ('max_step_energy_relative', '1'), ('max_temperature_step_k', 'K'))
# Counters cover booked stages only: the reference balance plus a predictor and an endpoint per accepted step. A cold
# re-solve of a resumed endpoint is operational work, reported by the continuation and never added here.
_COUNTER_MEANINGS = dict(
    stages='booked stages: the reference balance plus a predictor and an endpoint per accepted step',
    evaluations='motion-root evaluations of booked stages; warm-start dependent operational diagnostic',
    iterations='stress iterations of booked stages; warm-start dependent operational diagnostic',
    restress_mismatches='booked stages whose heat re-evaluation changed the solved stress')
_STRIP = 'whole strip per metre of strike'

# One owner and one producer per quantity. Status: required (always present), supported (present when this
# instance carries it, otherwise unknown) or unknown (not represented by this route; owner names the later stage).
CATALOGUE_FIELDS = ('name', 'units', 'support', 'owner', 'producer', 'status', 'meaning')
CATALOGUE = (
    ('start_time_s', 's', 'epoch instant', 'global schedule', 'declared scenario', 'required',
     'history start in the named epoch; SI seconds increasing forward'),
    ('elapsed_s', 's', 'whole strip', 'global schedule', 'finite-strain evolve', 'required',
     'accepted time since the reference state'),
    ('accepted_steps', '1', 'whole strip', 'global schedule', 'finite-strain evolve', 'required',
     'whole steps of the fixed global schedule; cumulative against max_steps'),
    ('schedule', 's; 1', 'whole strip', 'global schedule', 'declared scenario', 'required',
     'duration_s, steps and step_s = duration_s/steps; continuation keeps whole original steps'),
    ('stretch', '1', 'whole strip', 'column kinematics', 'finite-strain evolve', 'required',
     'lam = w/w0; exactly 1 at the reference'),
    ('displacement_m', 'm', 'strip edge', 'column kinematics', 'finite-strain evolve', 'required',
     'edge displacement since the reference'),
    ('log_path', '1', 'whole strip', 'column kinematics', 'finite-strain evolve', 'required',
     'accumulated absolute log-strain path; bounds raw plastic history growth'),
    ('log_strain_quadrature', '1', 'whole strip', 'column kinematics', 'finite-strain evolve', 'required',
     'stage-weighted integral of the axial rate; checked against ln(lam)'),
    ('velocity_start_m_s', 'm/s', 'strip edge', 'column kinematics', 'finite-strain evolve', 'supported',
     'balanced edge velocity at the reference; unknown until a piece of the history is accepted'),
    ('theta_k', 'K', 'material point', 'column thermal state', 'finite-strain evolve', 'required',
     'temperature departure from the fixed steady reference; signed'),
    ('initial_theta_k', 'K', 'material point', 'column thermal state', 'declared scenario', 'required',
     'initial departure, supplied explicitly; zero is never assumed'),
    ('clock_s', 's', 'whole strip', 'column thermal state', 'finite-strain evolve', 'required',
     'thermal clock tau with dt/dtau = lam^-2'),
    ('departure_enthalpy_j_m', 'J/m', _STRIP, 'column thermal state', 'derived by this envelope', 'required',
     'w0 sum(C0 theta); signed; column departure basis only'),
    ('kappa', '1', 'material point', 'column constitutive memory', 'finite-strain evolve', 'required',
     'raw engineering plastic shear; constitutive memory, never geometry; never decreases'),
    ('initial_kappa', '1', 'material point', 'column constitutive memory', 'declared scenario', 'required',
     'inherited raw history, supplied explicitly'),
    *(('accounts.'+name, 'J/m', _STRIP, 'column accounts', 'finite-strain evolve', 'required', meaning)
      for name, meaning in _ACCOUNT_MEANINGS),
    *(('counters.'+name, '1', 'whole strip', 'column diagnostics', 'finite-strain evolve', 'required',
       _COUNTER_MEANINGS[name]+'; zero before any accepted step') for name in COUNTERS),
    *(('extrema.'+name, unit, 'whole strip', 'column diagnostics', 'finite-strain evolve', 'supported',
       'running extreme over booked stages and accepted steps; undefined before the first accepted step')
      for name, unit in _EXTREMA_UNITS),
    ('yield_stage_counts', '1', 'material point', 'column diagnostics', 'finite-strain evolve', 'required',
     'booked stages at which each point yielded; zero before any accepted step'),
    ('column_force_start_n_m', 'N/m', 'whole strip', 'column diagnostics', 'finite-strain evolve', 'supported',
     'balanced column force at the reference; unknown until a piece of the history is accepted'),
    ('reference_width_m', 'm', 'whole strip', 'mechanical reference', 'external drive width', 'required',
     'w0; current width w0 lam'),
    ('reference_thickness_m', 'm', 'whole strip', 'mechanical reference', 'retained column preparation',
     'required', 'h0; current thickness h0/lam'),
    ('layer_thickness_m', 'm', 'layer', 'mechanical reference', 'pinned preparation inputs', 'required',
     'h_k at lam = 1; current h_k/lam'),
    ('point_layer', '1', 'material point', 'mechanical reference', 'retained column preparation', 'required',
     'owning layer of each Gauss control volume'),
    ('reference_depth_m', 'm', 'material point', 'mechanical reference', 'retained column preparation', 'required',
     'z0 at lam = 1; current z0/lam'),
    ('reference_weight_m', 'm', 'material point', 'mechanical reference', 'retained column preparation',
     'required', 'control-volume width q0 at lam = 1; current q0/lam'),
    ('reference_overburden_pa', 'Pa', 'material point', 'mechanical reference', 'retained column preparation',
     'required', 'P0, lithostatic or supplied mean pressure; current P0/lam'),
    ('reference_density_kg_m3', 'kg/m3', 'material point', 'mechanical reference', 'retained column preparation',
     'supported', 'lithostatic closure only; unknown for supplied-pressure columns'),
    ('pore_pressure_pa', 'Pa', 'material point', 'mechanical reference', 'pinned preparation inputs', 'required',
     'supplied as exactly zero: finite strain does not transport pore pressure'),
    ('reference_mass_kg_m', 'kg/m', _STRIP, 'mechanical reference', 'derived by this envelope', 'supported',
     'w0 sum(rho q0); invariant under affine stretch; unknown without mechanical density'),
    ('reference_volume_m2', 'm2', _STRIP, 'mechanical reference', 'derived by this envelope', 'required',
     'w0 h0; conserved by the incompressible strip'),
    ('steady_temperature_k', 'K', 'material point', 'thermal reference', 'retained thermal preparation',
     'required', 'fixed enthalpy reference'),
    ('capacity_j_m2_k', 'J/(m2 K)', 'material point', 'thermal reference', 'retained thermal preparation',
     'required', 'C0 = rho cp q0 per reference area; whole strip w C = w0 C0'),
    ('radiogenic_w_m2', 'W/m2', 'material point', 'thermal reference', 'retained thermal preparation', 'required',
     'r0 per reference area'),
    ('thermal_density_kg_m3', 'kg/m3', 'material point', 'thermal reference', 'retained thermal preparation',
     'required', 'thermal inventory density; equals the mechanical density for lithostatic columns'),
    ('boundary_temperature_k', 'K', 'surface and strip base', 'thermal reference', 'retained thermal preparation',
     'required', 'fixed boundary temperatures; None where insulated'),
    ('material_cohorts', 'm', 'cohort x strip cell', 'W02 material inventory', 'native MaterialState', 'required',
     'cohort identity, origin and formation time (None is unknown); reference partial thickness h_k at lam = 1, '
     'dated at the history start and carried unchanged; current layer thickness h_k/lam is derived'),
    ('finite_reservoirs', 'kg; J', 'W08 node', 'finite exterior accounts', 'native W08Inventory', 'supported',
     'whole exterior stocks with signed enthalpy in their own convention, carried unchanged with their own date; '
     'absent for the closed strip'),
    ('elastic_stress_pa', 'Pa', 'material point', 'I02/I05 transport; I07 law', 'none in this route', 'unknown',
     'this viscoplastic route has no elastic branch; stored stress is not represented'),
    ('melt_fraction', '1', 'material point', 'I05/I06', 'none in this route', 'unknown',
     'no melting or phase change in this route'),
    ('absolute_elevation_m', 'm', 'strip surface', 'I08 support', 'none in this route', 'unknown',
     'no support or datum calculation; geometry is relative to the material surface'),
    ('global_position', 'm', 'sphere', 'I03 geometry', 'none in this route', 'unknown',
     'not embedded in a spherical world or plate network'),
    ('lateral_structure', '1', 'strip width', 'I05/I07', 'none in this route', 'unknown',
     'laterally uniform strip; no lateral localisation or necking'),
    ('external_loads_pa', 'Pa', 'strip surface', 'I08 exchange ports', 'none in this route', 'unknown',
     'closed dry strip; no water, sediment or geology exchange'),
)
_INDEX = {entry[0]: entry for entry in CATALOGUE}
CATALOGUE_ID = hashlib.sha256(_json([list(entry) for entry in CATALOGUE])).hexdigest()


class _Immutable:
    """No opaque pickle and no copies: immutable envelopes are shared, and the native store persists them."""
    __slots__ = ()

    def __reduce__(self):
        raise TypeError(type(self).__name__+' is not pickled; persistence belongs to the native store (I02.5)')

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self


def _issue(cls, **values):
    item = object.__new__(cls)
    for key, value in values.items():
        object.__setattr__(item, key, value)
    return item


def _canonical(value, label):
    """The native canonical JSON of materials._json: sorted keys, finite numbers; bounded here."""
    try:
        data = _json(value)
    except TectonicsError as exc:
        raise TectonicsError(label+': finite JSON data required') from exc
    if len(data) > MAX_METADATA:
        raise TectonicsError(label+': metadata exceeds the bounded envelope')
    return data


def _digest(value, label='identity record'):
    return hashlib.sha256(_canonical(value, label)).hexdigest()


def _identity(record, arrays):
    """SHA-256 of canonical metadata, then each named array's descriptor and exact bytes."""
    digest = hashlib.sha256(record)
    for name, array in arrays:
        digest.update(b'\0'+_json([name, array.dtype.str, list(array.shape)]))
        digest.update(memoryview(array).cast('B'))
    return digest.hexdigest()


def _spec(name, array):
    _, units, support, owner, _, _, _ = _INDEX[name]
    return dict(name=name, dtype=array.dtype.str, shape=list(array.shape), units=units, support=support,
                owner=owner)


def _fields(value, keys, label):
    if not isinstance(value, Mapping) or set(value) != keys:
        raise TectonicsError(label+' must declare exactly: '+', '.join(sorted(keys)))
    return dict(value)


def _document(value, label):
    """Detached JSON copy of a caller mapping; later edits to the caller's nested objects cannot reach it."""
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TectonicsError(label+' must be a mapping with text keys')
    return json.loads(_canonical(dict(value), label))


def _number(value, label, *, positive=False, nonnegative=False):
    """A plain finite JSON number; bool, text, None and arrays are refused."""
    if type(value) not in (int, float):
        raise TectonicsError(label+': one plain real number required')
    return scalar(value, label, positive=positive, nonnegative=nonnegative)


def _length(value, label):
    if value is None:
        raise TectonicsError(label+': required; no default is supplied')
    shape = input_shape(value, label)
    if len(shape) != 1 or not shape[0]:
        raise TectonicsError(label+': nonempty one-dimensional data required')
    return shape[0]


def _floats(value, label, count, *, nonnegative=False):
    """Validated immutable binary64: proven immutable native payloads are borrowed, others detached once."""
    if value is None:
        raise TectonicsError(label+': required; no default is supplied')
    if input_shape(value, label) != (count,):
        raise TectonicsError(label+': one value per material point required')
    return snapshot(value, label, nonnegative=nonnegative)


def _integers(value, label, count):
    if value is None:
        raise TectonicsError(label+': required; no default is supplied')
    if input_shape(value, label) != (count,):
        raise TectonicsError(label+': one value per material point required')
    raw = np.asarray(value)
    if raw.dtype.kind not in 'iu' or (raw.dtype.kind == 'u' and int(raw.max()) > np.iinfo(np.int64).max):
        raise TectonicsError(label+': integer layer indices required')
    return np.frombuffer(raw.astype(np.int64).tobytes(), dtype=np.int64)


def _view(array):
    """A fresh descriptor chain: .base must never expose a retained ndarray descriptor.

    All stored arrays have compact immutable byte backing. Borrow those bytes
    without copying the payload, just as MaterialState does. A read-only ndarray
    alone still permits edits to its shape and dtype.
    """
    if array is None:
        return None
    owner = array
    while type(owner) is np.ndarray:
        owner = owner.base
    if type(owner) is not bytes or len(owner) != array.nbytes:
        raise TectonicsError('state array needs compact immutable byte backing')
    return np.frombuffer(owner, dtype=array.dtype).reshape(array.shape)


def _capture_bytes(count):
    # Transient capture workspace, not RSS: detached arrays, comparison temporaries and bounded metadata.
    return 256*count+2*MAX_METADATA+65536


def _preparation_fingerprint(pinned):
    """The retained identity of (layers, order, closure, gravity), computed by its package owner."""
    return _weakening.fingerprint(pinned['layers'], pinned['order'], pinned['closure'], pinned['gravity'])


def _support_fingerprint(inputs, layer, depth, weight):
    """_integration_heat.prepare_thermal's inline identity of thermal inputs plus support bytes (no owner function)."""
    text = json.dumps(dict(props=inputs['props'], densities=[float(d) for d in inputs['densities']],
                           boundaries=inputs['boundaries'], thicknesses=[float(h) for h in inputs['thicknesses']],
                           reference=inputs['reference_temperature']), sort_keys=True)
    support = layer.astype(np.int64).tobytes()+depth.tobytes()+weight.tobytes()
    return hashlib.sha256(text.encode()+support).hexdigest()


def _pinned_preparation(key):
    if type(key) not in (tuple, list) or len(key) != 4:
        raise TectonicsError('the pinned preparation key is (layers, order, closure, gravity)')
    layers, order, closure, gravity = key
    pinned = json.loads(_canonical(dict(layers=layers, order=order, closure=closure, gravity=gravity),
                                   'pinned preparation inputs'))
    layers, order, closure, gravity = (pinned[k] for k in ('layers', 'order', 'closure', 'gravity'))
    if closure not in (LITHOSTATIC, SUPPLIED):
        raise TectonicsError('unsupported pressure closure')
    if type(order) is not int or not 2 <= order <= MAX_ORDER:
        raise TectonicsError('quadrature order must be an integer in 2..128')
    if closure == LITHOSTATIC:
        _number(gravity, 'gravity', positive=True)
    elif gravity is not None:
        raise TectonicsError('a supplied-pressure preparation carries no gravity')
    if type(layers) is not list or not 1 <= len(layers) <= MAX_LAYERS:
        raise TectonicsError('one to 64 pinned layers required')
    for layer in layers:
        if type(layer) is not dict:
            raise TectonicsError('each pinned layer is a field mapping')
        _name(layer.get('name'), 'layer name')
        _number(layer.get('thickness_m'), 'layer thickness', positive=True)
        pore = layer.get('pore_pressure_pa')
        if type(pore) is not list or len(pore) != 2 or any(type(v) not in (int, float) or v != 0 for v in pore):
            raise TectonicsError('pore pressure must be supplied as exactly zero: finite strain does not transport it')
        if closure == LITHOSTATIC:
            _number(layer.get('density_kg_m3'), 'layer density', positive=True)
        else:
            mean = layer.get('mean_pressure_pa')
            if type(mean) is not list or len(mean) != 2:
                raise TectonicsError('a supplied-pressure layer declares a [top, bottom] mean pressure')
            for value in mean:
                _number(value, 'supplied mean pressure', nonnegative=True)
    return pinned


def _boundaries(value):
    if type(value) is not dict or set(value) != {'top', 'bottom'}:
        raise TectonicsError('thermal boundaries declare only top and bottom')
    ends = []
    for side in ('top', 'bottom'):
        boundary = value[side]
        if type(boundary) is not dict or boundary.get('type') not in ('temperature', 'insulated'):
            raise TectonicsError('a thermal boundary is a fixed temperature or insulated')
        if boundary['type'] == 'temperature':
            if set(boundary) != {'type', 'value_k'}:
                raise TectonicsError('a fixed-temperature boundary declares only its value')
            ends.append(_number(boundary['value_k'], 'boundary temperature', positive=True))
        else:
            if set(boundary) != {'type'}:
                raise TectonicsError('an insulated boundary takes no value; supplied heat flux is not admitted')
            ends.append(None)
    return tuple(ends)


def _thermal_inputs(value, names, thicknesses, layers, closure):
    if not isinstance(value, Mapping) or set(value) != _THERMAL_INPUTS:
        raise TectonicsError('pinned thermal inputs declare exactly: '+', '.join(sorted(_THERMAL_INPUTS)))
    data = _document(value, 'pinned thermal inputs')
    declared = data['thicknesses']
    if type(declared) is not list or [_number(h, 'thermal layer thickness', positive=True)
                                      for h in declared] != thicknesses:
        raise TectonicsError('thermal layer thicknesses differ from the pinned mechanical layers')
    props, densities = data['props'], data['densities']
    if type(props) is not list or len(props) != len(names):
        raise TectonicsError('one thermal property set per pinned layer required')
    for prop, name in zip(props, names):
        if type(prop) is not dict or set(prop) != _PROPS or prop['name'] != name:
            raise TectonicsError('thermal properties declare conductivity, heat capacity and radiogenic heat by '
                                 'layer name')
        _number(prop['conductivity_w_m_k'], 'conductivity', positive=True)
        _number(prop['heat_capacity_j_kg_k'], 'heat capacity', positive=True)
        _number(prop['radiogenic_w_m3'], 'radiogenic heat', nonnegative=True)
    if type(densities) is not list or len(densities) != len(names):
        raise TectonicsError('one thermal inventory density per pinned layer required')
    rho = [_number(d, 'thermal density', positive=True) for d in densities]
    if closure == LITHOSTATIC and rho != [float(layer['density_kg_m3']) for layer in layers]:
        raise TectonicsError('thermal inventory density differs from the mechanical reference density')
    ends = _boundaries(data['boundaries'])
    reference = data['reference_temperature']
    if ends == (None, None):
        _number(reference, 'insulated reference temperature', positive=True)
        if any(prop['radiogenic_w_m3'] for prop in props):
            raise TectonicsError('an insulated column has a steady reference only without radiogenic heat')
    elif reference is not None:
        raise TectonicsError('the steady reference is fixed by the boundary temperatures')
    return data, ends


def _support(layer, depth, weight, thicknesses, order):
    """The retained supplied-support rules, never repaired: whole ordered layers, positive widths, interior points."""
    count = len(thicknesses)
    if layer.size != order*count or not np.array_equal(layer, np.repeat(np.arange(count, dtype=np.int64), order)):
        raise TectonicsError('support must hold the pinned quadrature order of points in every layer, in order')
    if np.any(np.diff(depth) <= 0) or np.any(weight <= 0):
        raise TectonicsError('support depths must strictly increase and control-volume widths must be positive')
    tops = np.concatenate([[0.], np.cumsum(thicknesses)])
    for k, h in enumerate(thicknesses):
        chosen = layer == k
        widths, points = weight[chosen], depth[chosen]
        if abs(math.fsum(widths)-h) > _heat.width_tolerance(widths.size)*h:      # the retained 8 (n + 3) u rule
            raise TectonicsError('control-volume widths of layer %d do not sum to its thickness' % k)
        if not (np.all(points > tops[k]) and np.all(points < tops[k+1])):
            raise TectonicsError('a material point lies outside its layer')


def _boundary_values(value, ends):
    if type(value) not in (tuple, list) or len(value) != 2:
        raise TectonicsError('surface and strip-base boundary temperatures required')
    got = tuple(None if v is None else scalar(v, 'boundary temperature', positive=True) for v in value)
    if got != ends:
        raise TectonicsError('prepared boundary temperatures differ from the pinned boundaries')
    return got


def _window(stretch, temperature):
    bounds = []
    for pair, label in ((stretch, 'stretch window'), (temperature, 'temperature window')):
        if type(pair) is not list or len(pair) != 2:
            raise TectonicsError(label+' must be [low, high]')
        bounds += [_number(value, label) for value in pair]
    lo, hi, tlo, thi = bounds
    if not STRETCH_CEILING[0] <= lo < 1. < hi <= STRETCH_CEILING[1]:
        raise TectonicsError('stretch window must contain the reference geometry and lie within [0.6, 1.4]')
    if not TEMPERATURE_CEILING_K[0] <= tlo < thi <= TEMPERATURE_CEILING_K[1]:
        raise TectonicsError('temperature window must lie within the reviewed [273, 1613] K range')
    return lo, hi, tlo, thi


@dataclass(frozen=True, slots=True)
class StateIdentity:
    """World/scenario labels, the named epoch, caller-declared source/runtime digests and the unit declaration.

    Labels are necessary, not sufficient: compatibility is established by checked content elsewhere. Source and
    runtime digests are recorded as the producer declared them; this carrier does not re-hash the producer.
    """
    world_id: str
    scenario_id: str
    epoch_id: str
    source_id: str
    runtime_id: str
    unit_system: str

    def __post_init__(self):
        for name in ('world_id', 'scenario_id', 'epoch_id'):
            _name(getattr(self, name), name.replace('_', ' '))
        _sha(self.source_id, 'source identity')
        _sha(self.runtime_id, 'runtime identity')
        if self.unit_system != UNIT_SYSTEM:
            raise TectonicsError('only the declared SI unit system is admitted; convert explicitly before entry')


@dataclass(frozen=True, init=False, eq=False, slots=True)
class ColumnReference(_Immutable):
    """The absolute lam = 1 mechanical and thermal reference of one prepared column; never re-based.

    ``mechanical`` and ``thermal`` name the retained preparation's attributes (I02_COMMON_STATE.md, section 3). Their
    pinned inputs must reproduce both preparation fingerprints, so a later package-owned core can rebuild disposable
    operators instead of serialising them. Support, densities, capacities, radiogenic sources, thicknesses and
    boundary temperatures are cross-checked exactly. Overburden and the steady geotherm are carried as prepared; a
    rebuild must reproduce them bitwise. Immutable native arrays are borrowed; other inputs are detached once.
    """
    closure: str
    order: int
    gravity_m_s2: float | None
    layer_names: tuple
    thickness_m: float
    boundary_temperature_k: tuple
    mechanical_fingerprint: str
    thermal_fingerprint: str
    thermal_provider: str
    support_id: str
    reference_id: str
    _pinned: bytes = field(repr=False)
    _thermal_inputs: bytes = field(repr=False)
    _record: bytes = field(repr=False)
    _layer_thickness: np.ndarray = field(repr=False)
    _layer: np.ndarray = field(repr=False)
    _depth: np.ndarray = field(repr=False)
    _weight: np.ndarray = field(repr=False)
    _overburden: np.ndarray = field(repr=False)
    _density: np.ndarray | None = field(repr=False)
    _steady: np.ndarray = field(repr=False)
    _capacity: np.ndarray = field(repr=False)
    _radiogenic: np.ndarray = field(repr=False)
    _thermal_density: np.ndarray = field(repr=False)

    def __init__(self, *, mechanical, thermal, budget=None):
        m = _fields(mechanical, _MECHANICAL, 'mechanical reference')
        t = _fields(thermal, _THERMAL, 'thermal reference')
        count = _length(m['depth_m'], 'reference depth')
        with select_budget(budget).reserve(_capture_bytes(count), category='i02-state-capture'):
            pinned = _pinned_preparation(m['key'])
            layers, order, closure = pinned['layers'], pinned['order'], pinned['closure']
            fingerprint = _sha(m['fingerprint'], 'preparation fingerprint')
            if _preparation_fingerprint(pinned) != fingerprint:
                raise TectonicsError('pinned inputs do not reproduce the reference preparation: stale, stretched or '
                                     'foreign column')
            names = tuple(layer['name'] for layer in layers)
            thicknesses = [float(layer['thickness_m']) for layer in layers]
            total = 0.
            for h in thicknesses:                    # the retained kernel's sequential column thickness
                total += h
            if scalar(m['thickness_m'], 'reference thickness', positive=True) != total:
                raise TectonicsError("reference thickness is not the pinned layers' total: a stretched or re-based "
                                     "column cannot pose as lam = 1")
            layer = _integers(m['layer'], 'point layer', count)
            depth = _floats(m['depth_m'], 'reference depth', count)
            weight = _floats(m['weight'], 'reference control-volume width', count)
            _support(layer, depth, weight, thicknesses, order)
            overburden = _floats(m['reference_pa'], 'reference overburden', count, nonnegative=True)
            index = layer.tolist()
            if closure == LITHOSTATIC:
                density = _floats(m['density'], 'mechanical reference density', count)
                if not np.array_equal(density, np.array([float(layers[k]['density_kg_m3']) for k in index])):
                    raise TectonicsError('mechanical reference density differs from the pinned layers')
                if np.any(np.diff(overburden) < 0):
                    raise TectonicsError('lithostatic reference overburden cannot decrease with depth')
            elif m['density'] is not None:
                raise TectonicsError('a supplied-pressure column has no mechanical density: declare it unknown (None)')
            else:
                density = None
            if t['provider'] != COLUMN_THERMAL_BASIS:
                raise TectonicsError('incompatible thermal provider: this route supports only its constant-capacity '
                                     'departure basis')
            inputs, ends = _thermal_inputs(t['inputs'], names, thicknesses, layers, closure)
            if _sha(t['mechanical_fingerprint'], 'thermal mechanical fingerprint') != fingerprint:
                raise TectonicsError('thermal support was prepared for a different mechanical column')
            if not (np.array_equal(_integers(t['layer'], 'thermal layer', count), layer)
                    and np.array_equal(_floats(t['depth_m'], 'thermal depth', count), depth)
                    and np.array_equal(_floats(t['volume_m'], 'thermal control-volume width', count), weight)):
                raise TectonicsError('thermal layers, depths or widths differ from the mechanical quadrature')
            thermal_fingerprint = _sha(t['fingerprint'], 'thermal support fingerprint')
            if _support_fingerprint(inputs, layer, depth, weight) != thermal_fingerprint:
                raise TectonicsError('pinned thermal inputs do not reproduce the prepared support fingerprint')
            thermal_density = _floats(t['reference_density_kg_m3'], 'thermal reference density', count)
            if not np.array_equal(thermal_density, np.array([float(inputs['densities'][k]) for k in index])):
                raise TectonicsError('thermal reference density differs from the pinned thermal inputs')
            capacity = _floats(t['capacity'], 'reference heat capacity', count)
            rho_cp = np.array([float(inputs['densities'][k])*float(inputs['props'][k]['heat_capacity_j_kg_k'])
                               for k in index])
            if not np.array_equal(capacity, rho_cp*weight):          # prepare_thermal's own expression
                raise TectonicsError('heat capacity does not follow the pinned density, heat capacity and control '
                                     'volumes (units or support mismatch)')
            radiogenic = _floats(t['radiogenic'], 'reference radiogenic heat', count, nonnegative=True)
            source = np.array([float(inputs['props'][k]['radiogenic_w_m3']) for k in index])
            if not np.array_equal(radiogenic, weight*source):
                raise TectonicsError('radiogenic heat does not follow the pinned sources and control volumes')
            steady = _floats(t['steady_k'], 'steady reference temperature', count)
            if np.any(steady <= 0):
                raise TectonicsError('steady reference temperature must be positive kelvin')
            boundary = _boundary_values(t['boundary_temperature'], ends)
            if scalar(t['thickness_m'], 'thermal support thickness', positive=True) != total:
                raise TectonicsError('thermal support thickness differs from the mechanical column')
            layer_thickness = np.frombuffer(np.asarray(thicknesses, dtype=np.float64).tobytes(), dtype=np.float64)
            support_id = _identity(
                _canonical(dict(schema='atlas.i02-column-support.v1', geometry=GEOMETRY, closure=closure, order=order,
                                layer_names=list(names), layer_thickness_m=thicknesses), 'support record'),
                (('point_layer', layer), ('reference_depth_m', depth), ('reference_weight_m', weight)))
            arrays = (('layer_thickness_m', layer_thickness), ('point_layer', layer), ('reference_depth_m', depth),
                      ('reference_weight_m', weight), ('reference_overburden_pa', overburden),
                      *((('reference_density_kg_m3', density),) if density is not None else ()),
                      ('steady_temperature_k', steady), ('capacity_j_m2_k', capacity),
                      ('radiogenic_w_m2', radiogenic), ('thermal_density_kg_m3', thermal_density))
            gravity = None if closure == SUPPLIED else float(pinned['gravity'])
            record = _canonical(dict(
                schema='atlas.i02-column-reference.v1', route=ROUTE, geometry=GEOMETRY,
                vertical_reference=VERTICAL_REFERENCE, thermal_reference=THERMAL_REFERENCE, closure=closure,
                order=order, gravity_m_s2=gravity, layer_names=list(names), thickness_m=total,
                mechanical_fingerprint=fingerprint, thermal_fingerprint=thermal_fingerprint,
                thermal_provider=COLUMN_THERMAL_BASIS, boundary_temperature_k=list(boundary), support_id=support_id,
                pinned_preparation=pinned, pinned_thermal=inputs, arrays=[_spec(name, a) for name, a in arrays],
                unknown=[] if density is not None else ['reference_density_kg_m3', 'reference_mass_kg_m']),
                'column reference')
            values = dict(closure=closure, order=order, gravity_m_s2=gravity, layer_names=names, thickness_m=total,
                          boundary_temperature_k=boundary, mechanical_fingerprint=fingerprint,
                          thermal_fingerprint=thermal_fingerprint, thermal_provider=COLUMN_THERMAL_BASIS,
                          support_id=support_id, reference_id=_identity(record, arrays),
                          _pinned=_canonical(pinned, 'pinned preparation inputs'),
                          _thermal_inputs=_canonical(inputs, 'pinned thermal inputs'), _record=record,
                          _layer_thickness=layer_thickness, _layer=layer, _depth=depth, _weight=weight,
                          _overburden=overburden, _density=density, _steady=steady, _capacity=capacity,
                          _radiogenic=radiogenic, _thermal_density=thermal_density)
            for key, value in values.items():
                object.__setattr__(self, key, value)

    @property
    def points(self): return int(self._depth.size)
    @property
    def layer_thickness_m(self): return _view(self._layer_thickness)
    @property
    def point_layer(self): return _view(self._layer)
    @property
    def depth_m(self): return _view(self._depth)
    @property
    def weight_m(self): return _view(self._weight)
    @property
    def overburden_pa(self): return _view(self._overburden)
    @property
    def density_kg_m3(self): return _view(self._density)
    @property
    def steady_temperature_k(self): return _view(self._steady)
    @property
    def capacity_j_m2_k(self): return _view(self._capacity)
    @property
    def radiogenic_w_m2(self): return _view(self._radiogenic)
    @property
    def thermal_density_kg_m3(self): return _view(self._thermal_density)

    @property
    def nbytes(self):
        arrays = {id(a): a.nbytes for a in (self._layer_thickness, self._layer, self._depth, self._weight,
                                            self._overburden, self._density, self._steady, self._capacity,
                                            self._radiogenic, self._thermal_density) if a is not None}
        return sum(arrays.values())+len(self._record)+len(self._pinned)+len(self._thermal_inputs)

    def preparation_key(self):
        """Fresh (layers, order, closure, gravity): the retained preparation's own inputs, for a rebuild."""
        pinned = json.loads(self._pinned)
        return pinned['layers'], pinned['order'], pinned['closure'], pinned['gravity']

    def thermal_inputs(self):
        """Fresh pinned thermal inputs: thicknesses, props, densities, boundaries and reference temperature."""
        return json.loads(self._thermal_inputs)

    def descriptor(self):
        return json.loads(self._record)

    def _arrays(self):
        """The identity-bound arrays, in the order reference_id hashes them."""
        return (('layer_thickness_m', self._layer_thickness), ('point_layer', self._layer),
                ('reference_depth_m', self._depth), ('reference_weight_m', self._weight),
                ('reference_overburden_pa', self._overburden),
                *((('reference_density_kg_m3', self._density),) if self._density is not None else ()),
                ('steady_temperature_k', self._steady), ('capacity_j_m2_k', self._capacity),
                ('radiogenic_w_m2', self._radiogenic), ('thermal_density_kg_m3', self._thermal_density))


@dataclass(frozen=True, init=False, eq=False, slots=True)
class ColumnSettings(_Immutable):
    """Closure, constitutive parameters and numerical policy fixed for one history of the route.

    Only the retained finite-strain representation and production solver configuration are admitted, inside the
    frozen stretch/temperature ceilings and the 5 K step guard. The policy is carried verbatim; its step ceiling (at
    most 256) is cumulative, and the global schedule fixes step_s = duration_s/steps once, never per restart.
    """
    window: tuple
    temperature_step_k: float
    law_parameters: tuple
    drive_parameters: tuple
    heat_fractions: tuple
    duration_s: float
    steps: int
    step_s: float
    max_steps: int
    maximum_seconds: float
    closure_id: str
    parameter_id: str
    policy_id: str
    settings_id: str
    _policy: bytes = field(repr=False)
    _record: bytes = field(repr=False)

    def __init__(self, *, representation, law, drive, heat_fractions, policy, schedule):
        rep = _document(representation, 'representation')
        if set(rep) != set(REPRESENTATION) | _LIMITS:
            raise TectonicsError('representation must declare only the supported finite-strain fields')
        for key, text in REPRESENTATION.items():
            if rep[key] != text:
                raise TectonicsError('only the supported finite-strain representation is admitted: '+key)
        window = _window(rep['stretch_window'], rep['temperature_window_k'])
        guard = _number(rep['max_temperature_step_k'], 'temperature step guard', positive=True)
        if guard > MAX_TEMPERATURE_STEP_K:
            raise TectonicsError('temperature step guard above the declared 5 K ceiling')
        weak = _document(law, 'weakening law')
        if set(weak) != {'start', 'end', 'cohesion_factor', 'friction_factor'}:
            raise TectonicsError('weakening law declares exactly start, end, cohesion_factor and friction_factor')
        start, end, cohesion, friction = (_number(weak[k], 'weakening '+k, nonnegative=True)
                                          for k in ('start', 'end', 'cohesion_factor', 'friction_factor'))
        if not start < end or not (0 < cohesion <= 1 and 0 < friction <= 1):
            raise TectonicsError('weakening interval must increase and its factors lie in (0, 1]')
        forcing = _document(drive, 'external drive')
        if set(forcing) != {'force_n_m', 'drag_pa_s', 'width_m'}:
            raise TectonicsError('external drive declares exactly force_n_m, drag_pa_s and width_m')
        force = _number(forcing['force_n_m'], 'drive force')
        drag = _number(forcing['drag_pa_s'], 'generalised drag', positive=True)
        width = _number(forcing['width_m'], 'reference strip width', positive=True)
        if force:
            scalar(abs(force)/drag/width, 'representable drag-only axial rate', positive=True)
        if type(heat_fractions) not in (list, tuple) or len(heat_fractions) != 2:
            raise TectonicsError('creep and plastic heat fractions required')
        fractions = tuple(scalar(f, 'heat fraction', nonnegative=True) for f in heat_fractions)
        if any(f > 1 for f in fractions):
            raise TectonicsError('heat fractions must lie in [0, 1]; dissipation is not amplified')
        pol = _document(policy, 'numerical policy')
        max_steps = pol.get('max_steps')
        if type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS:
            raise TectonicsError('cumulative step ceiling must be an integer in 1..256')
        allowance = _number(pol.get('maximum_seconds'), 'cooperative time budget', positive=True)
        plan = _document(schedule, 'global schedule')
        if set(plan) != {'duration_s', 'steps'}:
            raise TectonicsError('global schedule declares exactly duration_s and steps')
        duration = _number(plan['duration_s'], 'scheduled duration', positive=True)
        if duration > HORIZON_CEILING_S:
            raise TectonicsError('scheduled duration exceeds the retained finite-strain horizon')
        steps = plan['steps']
        if type(steps) is not int or not 1 <= steps <= max_steps:
            raise TectonicsError('scheduled steps must be an integer within the cumulative step ceiling')
        step_s = scalar(duration/steps, 'global time step', positive=True)
        closure = dict(route=ROUTE, representation={key: rep[key] for key in REPRESENTATION}, solver=SOLVER)
        parameters = dict(law=dict(start=start, end=end, cohesion_factor=cohesion, friction_factor=friction),
                          drive=dict(force_n_m=force, drag_pa_s=drag, width_m=width), heat_fractions=list(fractions))
        numerics = dict(policy=pol, schedule=dict(duration_s=duration, steps=steps, step_s=step_s),
                        window=dict(stretch=list(window[:2]), temperature_k=list(window[2:]),
                                    max_temperature_step_k=guard), solver=SOLVER)
        record = _canonical(dict(schema='atlas.i02-finite-strain-settings.v1', closure=closure,
                                 parameters=parameters, numerical_policy=numerics), 'settings')
        values = dict(window=window, temperature_step_k=guard, law_parameters=(start, end, cohesion, friction),
                      drive_parameters=(force, drag, width), heat_fractions=fractions, duration_s=duration,
                      steps=steps, step_s=step_s, max_steps=max_steps, maximum_seconds=allowance,
                      closure_id=_digest(closure), parameter_id=_digest(parameters), policy_id=_digest(numerics),
                      settings_id=hashlib.sha256(record).hexdigest(), _policy=_canonical(pol, 'numerical policy'),
                      _record=record)
        for key, value in values.items():
            object.__setattr__(self, key, value)

    def policy(self):
        return json.loads(self._policy)

    def window_mapping(self):
        """The window in the retained evolve's form: dict(stretch=[lo, hi], temperature_k=[lo, hi])."""
        return dict(stretch=list(self.window[:2]), temperature_k=list(self.window[2:]))

    def descriptor(self):
        return json.loads(self._record)


@dataclass(frozen=True, init=False, eq=False, slots=True)
class ColumnState(_Immutable):
    """Finite-strain history measured from the absolute reference: the initial value or an accepted prefix.

    At the reference nothing has been booked, so cumulative accounts and counters are exactly zero and running
    extrema are undefined (None), not zero. An accepted prefix (at least one whole step, issued by a Continuation)
    carries the cumulative values of its booked stages and steps. Initial departure and history stay separate from
    the current ones and are shared, unchanged, by every successor.
    """
    stretch: float
    elapsed_s: float
    accepted_steps: int
    clock_s: float
    displacement_m: float
    log_path: float
    log_strain_quadrature: float
    velocity_start_m_s: float | None
    column_force_start_n_m: float | None
    column_state_id: str
    _accounts: tuple = field(repr=False)
    _counters: tuple = field(repr=False)
    _extrema: tuple = field(repr=False)
    _theta0: np.ndarray = field(repr=False)
    _theta: np.ndarray = field(repr=False)
    _kappa0: np.ndarray = field(repr=False)
    _kappa: np.ndarray = field(repr=False)
    _yield: np.ndarray = field(repr=False)
    _record: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('ColumnState is issued by initial_state() or a Continuation advance only')

    @property
    def theta_k(self): return _view(self._theta)
    @property
    def initial_theta_k(self): return _view(self._theta0)
    @property
    def kappa(self): return _view(self._kappa)
    @property
    def initial_kappa(self): return _view(self._kappa0)
    @property
    def yield_stage_counts(self): return _view(self._yield)
    @property
    def accounts_j_m(self): return dict(self._accounts)
    @property
    def counters(self): return dict(self._counters)
    @property
    def extrema(self): return dict(self._extrema)

    @property
    def nbytes(self):
        arrays = {id(a): a.nbytes for a in (self._theta0, self._theta, self._kappa0, self._kappa, self._yield)}
        return sum(arrays.values())+len(self._record)

    def descriptor(self):
        return json.loads(self._record)

    def _arrays(self):
        """The identity-bound arrays, in the order column_state_id hashes them."""
        return (('initial_theta_k', self._theta0), ('theta_k', self._theta), ('initial_kappa', self._kappa0),
                ('kappa', self._kappa), ('yield_stage_counts', self._yield))


_SCALARS = ('stretch', 'elapsed_s', 'accepted_steps', 'clock_s', 'displacement_m', 'log_path', 'log_strain_quadrature',
            'velocity_start_m_s', 'column_force_start_n_m')


def _column_state(semantics, scalars, accounts, counters, extrema, theta0, theta, kappa0, kappa, yields):
    """One column record: canonical metadata plus the exact bytes of its five immutable arrays."""
    arrays = (('initial_theta_k', theta0), ('theta_k', theta), ('initial_kappa', kappa0), ('kappa', kappa),
              ('yield_stage_counts', yields))
    record = _canonical(dict(
        schema='atlas.i02-finite-strain-column-state.v1', route=ROUTE, semantics=semantics, **scalars,
        accounts_j_m=dict(accounts), counters=dict(counters), extrema=dict(extrema),
        arrays=[_spec(name, a) for name, a in arrays]), 'column state')
    return _issue(ColumnState, **scalars, column_state_id=_identity(record, arrays), _accounts=accounts,
                  _counters=counters, _extrema=extrema, _theta0=theta0, _theta=theta, _kappa0=kappa0, _kappa=kappa,
                  _yield=yields, _record=record)


def _initial_column(reference, settings, theta0, kappa0, budget):
    if theta0 is None:
        raise TectonicsError('initial temperature departure must be supplied explicitly; zero is not assumed')
    if kappa0 is None:
        raise TectonicsError('inherited raw plastic history must be supplied explicitly; zero is not assumed')
    count = reference.points
    with select_budget(budget).reserve(_capture_bytes(count), category='i02-state-capture'):
        theta = _floats(theta0, 'initial temperature departure', count)
        kappa = _floats(kappa0, 'initial raw plastic history', count, nonnegative=True)
        temperature = reference._steady+theta           # the retained evolve's reference + theta
        _, _, low, high = settings.window
        if (not np.all(np.isfinite(temperature) & (temperature > 0))
                or not np.all((temperature >= low) & (temperature <= high))):
            raise TectonicsError('initial material temperatures lie outside the declared window')
        yields = np.frombuffer(bytes(8*count), dtype=np.int64)
        return _column_state(
            'initial state at the reference geometry: nothing is booked since lam = 1, so cumulative accounts and '
            'counters are exactly zero and running extrema are undefined',
            dict(stretch=1., elapsed_s=0., accepted_steps=0, clock_s=0., displacement_m=0., log_path=0.,
                 log_strain_quadrature=0., velocity_start_m_s=None, column_force_start_n_m=None),
            tuple((name, 0.) for name in STAGE_ACCOUNTS+THERMAL_ACCOUNTS), tuple((name, 0) for name in COUNTERS),
            tuple((name, None) for name in EXTREMA), theta, theta, kappa, kappa, yields)


def _material_payload(materials, reference, width, frame, epoch, start, layer_cohorts):
    if type(materials) is not MaterialState:
        raise TectonicsError('the native W02 MaterialState carrying cohort identity and formation history is required')
    grid = materials.grid
    if type(grid) is not ColumnGrid1D:
        raise TectonicsError('material cohorts need a frame-bearing ColumnGrid1D strip cell')
    if grid.frame_id != frame:
        raise TectonicsError('material cohorts belong to a different coordinate frame')
    if grid.cells != 1 or float(grid.widths_m[0]) != width:
        raise TectonicsError('material cohorts must fill one laterally uniform strip cell of the reference width')
    if materials.epoch_id != epoch:
        raise TectonicsError('material cohorts are dated in a different epoch')
    if materials.time_s != start:
        raise TectonicsError('material cohorts are not dated at the history start')
    names = reference.layer_names
    if (type(layer_cohorts) is not tuple or len(layer_cohorts) != len(names)
            or any(type(cohort) is not str for cohort in layer_cohorts)):
        raise TectonicsError('one cohort identity per reference layer, in layer order, required')
    ids = tuple(cohort.cohort_id for cohort in materials.cohorts)
    if len(set(layer_cohorts)) != len(layer_cohorts):
        raise TectonicsError('one cohort cannot own two layers')
    if set(layer_cohorts) != set(ids):
        raise TectonicsError('every native cohort must own exactly one layer: unowned or missing material refused')
    thickness = materials.thickness_m
    for k, cohort_id in enumerate(layer_cohorts):
        i = ids.index(cohort_id)
        if materials.cohorts[i].material_id != names[k]:
            raise TectonicsError('cohort material does not match its reference layer')
        if float(thickness[i, 0]) != float(reference._layer_thickness[k]):
            raise TectonicsError('cohort reference thickness differs from its layer (units or re-based geometry)')
    return ids


def _reservoir_payload(reservoirs, basis, time_s, cohort_ids):
    if reservoirs is None:
        if basis is not None:
            raise TectonicsError('a reservoir enthalpy basis was declared without reservoirs')
        return None
    from .w08_inventory import W08Inventory      # only when finite stocks are actually attached
    if type(reservoirs) is not W08Inventory:
        raise TectonicsError('finite reservoirs must be a native W08Inventory')
    if basis is None:
        raise TectonicsError('attached reservoirs must declare their enthalpy basis; none is assumed')
    _name(basis, 'reservoir enthalpy basis')
    if basis == COLUMN_THERMAL_BASIS:
        raise TectonicsError('a W08 stock enthalpy cannot share the column departure basis: the providers are not '
                             'interchangeable')
    if reservoirs.enthalpy_source != basis:
        raise TectonicsError('reservoir enthalpy convention differs from the declared basis')
    if reservoirs.time_s != time_s:
        raise TectonicsError('reservoir stocks are dated at a different time')
    if any(kind in ('crust', 'mantle') for kind in reservoirs.node_kinds):
        raise TectonicsError('lithospheric material is owned by the native cohorts; W08 crust/mantle rows would be a '
                             'second copy')
    if set(reservoirs.node_ids) & set(cohort_ids):
        raise TectonicsError('a reservoir row reuses a native material cohort identity')
    return reservoirs


_PRESENCE = {
    'velocity_start_m_s': lambda s: s.column.velocity_start_m_s is not None,
    'column_force_start_n_m': lambda s: s.column.column_force_start_n_m is not None,
    'reference_density_kg_m3': lambda s: s.reference.density_kg_m3 is not None,
    'reference_mass_kg_m': lambda s: s.reference.density_kg_m3 is not None,
    'finite_reservoirs': lambda s: s.reservoirs is not None,
    **{'extrema.'+name: (lambda s, name=name: s.column.extrema[name] is not None) for name in EXTREMA},
}


@dataclass(frozen=True, init=False, eq=False, slots=True)
class CommonState(_Immutable):
    """One accepted-state envelope of the finite-strain route; compare states by ``state_id``.

    Issued by initial_state() (the root) and by Continuation.advance() (a successor naming its parent and root). It
    owns identities, lineage and the joins between its immutable parts, not their physics. A successor shares the
    unchanged reference, settings and native payloads of its parent; current geometry is always derived from the
    original reference and the accepted stretch. ``admission`` is always NOT_CONFERRED: finite admission still
    requires a state issued by that tool's own retained evolution. Operational timing never enters the identity.
    """
    schema: str
    route: str
    world_id: str
    scenario_id: str
    epoch_id: str
    source_id: str
    runtime_id: str
    unit_system: str
    frame_id: str
    start_time_s: float
    time_s: float
    parent_state_id: str | None
    initial_state_id: str | None
    reference: ColumnReference
    settings: ColumnSettings
    column: ColumnState
    materials: MaterialState
    layer_cohorts: tuple
    reservoirs: object
    reservoir_basis: str | None
    admission: str
    state_id: str
    _record: bytes = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('CommonState is issued by initial_state() or, for successors, by Continuation.advance()')

    @property
    def root_state_id(self):
        return self.state_id if self.parent_state_id is None else self.initial_state_id

    @property
    def remaining_steps(self):
        """Whole steps of the fixed global schedule not yet accepted; a completed piece may leave some."""
        return self.settings.steps-self.column.accepted_steps

    @property
    def reference_width_m(self):
        return self.settings.drive_parameters[2]

    @property
    def current_width_m(self):
        return self.reference_width_m*self.column.stretch             # the retained w0 lam

    @property
    def current_thickness_m(self):
        return self.reference.thickness_m/self.column.stretch         # the retained h0/lam

    @property
    def current_layer_thickness_m(self):
        return frozen(self.reference._layer_thickness/self.column.stretch)

    @property
    def current_depth_m(self):
        return frozen(self.reference._depth/self.column.stretch)

    @property
    def temperature_k(self):
        return frozen(self.reference._steady+self.column._theta)

    @property
    def reference_volume_m2(self):
        return self.reference_width_m*self.reference.thickness_m      # the retained w0 h0

    @property
    def reference_mass_kg_m(self):
        density = self.reference._density
        return None if density is None else self.reference_width_m*math.fsum(density*self.reference._weight)

    @property
    def departure_enthalpy_j_m(self):
        return self.reference_width_m*math.fsum(self.reference._capacity*self.column._theta)

    def cohort_reference_volume_m2(self):
        thickness = self.materials.thickness_m
        return {cohort.cohort_id: self.reference_width_m*float(thickness[i, 0])
                for i, cohort in enumerate(self.materials.cohorts)}

    @property
    def nbytes(self):
        """Arrays and metadata held by this envelope's parts; native payloads report their own nbytes."""
        return (self.reference.nbytes+self.column.nbytes+len(self.settings._record)+len(self.settings._policy)
                + len(self._record))

    def identities(self):
        return dict(state_id=self.state_id, root_state_id=self.root_state_id,
                    reference_id=self.reference.reference_id, support_id=self.reference.support_id,
                    mechanical_fingerprint=self.reference.mechanical_fingerprint,
                    thermal_fingerprint=self.reference.thermal_fingerprint, settings_id=self.settings.settings_id,
                    closure_id=self.settings.closure_id, parameter_id=self.settings.parameter_id,
                    policy_id=self.settings.policy_id, column_state_id=self.column.column_state_id,
                    material_state_id=self.materials.state_id,
                    reservoir_inventory_id=None if self.reservoirs is None else self.reservoirs.inventory_id,
                    source_id=self.source_id, runtime_id=self.runtime_id, catalogue_id=CATALOGUE_ID)

    def declaration(self):
        """Every declared quantity with its units, support, single owner/producer, status and presence here."""
        out = []
        for entry in CATALOGUE:
            name, status = entry[0], entry[5]
            known = status == 'required' or (status == 'supported' and _PRESENCE[name](self))
            out.append(dict(zip(CATALOGUE_FIELDS, entry), known=known))
        return out

    def unknown(self):
        return [entry for entry in self.declaration() if not entry['known']]

    def descriptor(self):
        out = json.loads(self._record)
        out.update(reference=self.reference.descriptor(), settings=self.settings.descriptor(),
                   column=self.column.descriptor())
        out['materials']['descriptor'] = self.materials.descriptor()
        if self.reservoirs is not None:
            out['reservoirs']['descriptor'] = self.reservoirs.descriptor()
        return out


_LABELS = ('world_id', 'scenario_id', 'epoch_id', 'source_id', 'runtime_id', 'unit_system')


def _envelope(labels, start, frame, reference, settings, column, materials, layer_cohorts, stocks, basis, parent,
              root):
    """One envelope record over already-checked parts. Native payloads keep their own dates and roles."""
    time_s = advance_time(start, column.elapsed_s)
    record = _canonical(dict(
        schema=SCHEMA, route=ROUTE, unit_system=labels['unit_system'],
        identity=dict(world_id=labels['world_id'], scenario_id=labels['scenario_id'], source_id=labels['source_id'],
                      runtime_id=labels['runtime_id']),
        frame=dict(frame_id=frame, geometry=GEOMETRY, vertical_reference=VERTICAL_REFERENCE,
                   support_id=reference.support_id),
        clock=dict(epoch_id=labels['epoch_id'], time_unit='SI seconds forward from the named epoch',
                   start_time_s=start, elapsed_s=column.elapsed_s, time_s=time_s,
                   accepted_steps=column.accepted_steps),
        lineage=dict(parent_state_id=parent, initial_state_id=root),
        reference_id=reference.reference_id, settings_id=settings.settings_id,
        column_state_id=column.column_state_id,
        thermal=dict(provider=reference.thermal_provider, basis=THERMAL_BASIS, reference=THERMAL_REFERENCE),
        materials=dict(state_id=materials.state_id, layer_cohorts=list(layer_cohorts), dated_time_s=materials.time_s,
                       role=MATERIAL_ROLE),
        reservoirs=None if stocks is None else dict(
            inventory_id=stocks.inventory_id, enthalpy_basis=basis, node_ids=list(stocks.node_ids),
            units='kg and J of whole stocks, not per metre of strike', dated_time_s=stocks.time_s,
            role=RESERVOIR_ROLE),
        catalogue_id=CATALOGUE_ID, admission=NOT_CONFERRED), 'common state')
    return _issue(CommonState, schema=SCHEMA, route=ROUTE, world_id=labels['world_id'],
                  scenario_id=labels['scenario_id'], epoch_id=labels['epoch_id'], source_id=labels['source_id'],
                  runtime_id=labels['runtime_id'], unit_system=labels['unit_system'], frame_id=frame,
                  start_time_s=start, time_s=time_s, parent_state_id=parent, initial_state_id=root,
                  reference=reference, settings=settings, column=column, materials=materials,
                  layer_cohorts=layer_cohorts, reservoirs=stocks, reservoir_basis=basis, admission=NOT_CONFERRED,
                  state_id=hashlib.sha256(record).hexdigest(), _record=record)


def initial_state(*, identity, start_time_s, frame_id, reference, settings, theta0_k, kappa0, materials,
                  layer_cohorts, reservoirs, reservoir_basis, budget=None):
    """The declared initial state of the finite-strain route at lam = 1: carried, not evolved or admitted.

    Every argument except ``budget`` is required; ``reservoirs=None`` explicitly declares that the closed strip has
    no attached finite exterior stocks. Nothing is booked, born or authorised here.
    """
    if (type(identity) is not StateIdentity or type(reference) is not ColumnReference
            or type(settings) is not ColumnSettings):
        raise TectonicsError('typed StateIdentity, ColumnReference and ColumnSettings required')
    start = scalar(start_time_s, 'history start time')
    frame = _name(frame_id, 'frame identity')
    column = _initial_column(reference, settings, theta0_k, kappa0, budget)
    time_s = advance_time(start, column.elapsed_s)
    cohort_ids = _material_payload(materials, reference, settings.drive_parameters[2], frame, identity.epoch_id,
                                   start, layer_cohorts)
    stocks = _reservoir_payload(reservoirs, reservoir_basis, time_s, cohort_ids)
    labels = {name: getattr(identity, name) for name in _LABELS}
    return _envelope(labels, start, frame, reference, settings, column, materials, layer_cohorts, stocks,
                     None if stocks is None else reservoir_basis, None, None)


# ----------------------------------------------------------------------------- continuation (I02.2b)

def _verified(state):
    """The exact issued types, every identity recomputed from its content and every join cross-checked.

    A look-alike, a swapped part or an edited record or array refuses. Introspection that rewrites a whole envelope and
    all its identities consistently is not defended, and nothing here confers admission.
    """
    if type(state) is not CommonState:
        raise TectonicsError('a CommonState issued by initial_state() or Continuation.advance() is required')
    reference, settings, column, materials = state.reference, state.settings, state.column, state.materials
    if (type(reference) is not ColumnReference or type(settings) is not ColumnSettings
            or type(column) is not ColumnState or type(materials) is not MaterialState):
        raise TectonicsError('state parts are not the issued reference, settings, column and material records')
    if (hashlib.sha256(state._record).hexdigest() != state.state_id
            or hashlib.sha256(settings._record).hexdigest() != settings.settings_id
            or _identity(reference._record, reference._arrays()) != reference.reference_id
            or _identity(column._record, column._arrays()) != column.column_state_id):
        raise TectonicsError('a record or array no longer reproduces its identity: edited or forged state')
    record, values, stocks = json.loads(state._record), json.loads(column._record), state.reservoirs
    reserved = record['reservoirs']
    joins = (
        (record['schema'], record['route'], record['admission'], record['unit_system'])
        == (state.schema, state.route, state.admission, state.unit_system) == (SCHEMA, ROUTE, NOT_CONFERRED,
                                                                                 UNIT_SYSTEM),
        record['identity'] == dict(world_id=state.world_id, scenario_id=state.scenario_id,
                                   source_id=state.source_id, runtime_id=state.runtime_id),
        (record['frame']['frame_id'], record['frame']['support_id']) == (state.frame_id, reference.support_id),
        record['clock'] == dict(epoch_id=state.epoch_id, time_unit='SI seconds forward from the named epoch',
                                start_time_s=state.start_time_s, elapsed_s=column.elapsed_s, time_s=state.time_s,
                                accepted_steps=column.accepted_steps),
        record['lineage'] == dict(parent_state_id=state.parent_state_id, initial_state_id=state.initial_state_id),
        (record['reference_id'], record['settings_id'], record['column_state_id'])
        == (reference.reference_id, settings.settings_id, column.column_state_id),
        record['materials'] == dict(state_id=materials.state_id, layer_cohorts=list(state.layer_cohorts),
                                    dated_time_s=materials.time_s, role=MATERIAL_ROLE),
        (reserved is None) == (stocks is None) == (state.reservoir_basis is None),
        stocks is None or (reserved['inventory_id'], reserved['enthalpy_basis'], reserved['dated_time_s'])
        == (stocks.inventory_id, state.reservoir_basis, stocks.time_s),
        all(values[name] == getattr(column, name) for name in _SCALARS),
        (values['accounts_j_m'], values['counters'], values['extrema'])
        == (dict(column._accounts), dict(column._counters), dict(column._extrema)),
        (state.parent_state_id is None) == (state.initial_state_id is None) == (column.accepted_steps == 0),
        column.accepted_steps <= settings.steps and column.elapsed_s == column.accepted_steps*settings.step_s,
        state.time_s == advance_time(state.start_time_s, column.elapsed_s))
    if not all(joins):
        raise TectonicsError('state labels, clock, lineage, joins or column values disagree with their identity-bound '
                             'records')
    return state


def _reproduces(reference, base, thermal):
    """The rebuilt preparation reproduces every carried reference byte, not only the two fingerprints."""
    def same(a, b):
        a, b = np.asarray(a), np.asarray(b)
        return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()
    density = reference._density
    checks = (
        ('fingerprints', (base.fingerprint, thermal.fingerprint, thermal.mechanical_fingerprint)
         == (reference.mechanical_fingerprint, reference.thermal_fingerprint, reference.mechanical_fingerprint)),
        ('point layers', np.array_equal(base.layer, reference._layer)
         and np.array_equal(thermal.layer, reference._layer)),
        ('support depths', same(base.depth_m, reference._depth) and same(thermal.depth_m, reference._depth)),
        ('control-volume widths', same(base.weight, reference._weight) and same(thermal.volume_m, reference._weight)),
        ('overburden', same(base.reference_pa, reference._overburden)),
        ('mechanical density', same(base.density, density) if density is not None
         else bool(np.all(np.isnan(base.density)))),
        ('thickness', base.thickness_m == thermal.thickness_m == reference.thickness_m),
        ('thermal density', same(thermal.reference_density_kg_m3, reference._thermal_density)),
        ('heat capacity', same(thermal.capacity, reference._capacity)),
        ('radiogenic source', same(thermal.radiogenic, reference._radiogenic)),
        ('steady geotherm', same(thermal.steady_k, reference._steady)),
        ('boundary temperatures', tuple(thermal.boundary_temperature) == reference.boundary_temperature_k),
        ('pore pressure', not np.any(np.asarray(base.pore_pa) != 0)))
    for name, ok in checks:
        if not ok:
            raise TectonicsError('the rebuilt reference differs from the carried bytes ('+name+'): a changed runtime '
                                 'or an edited reference cannot continue this history')


def _context(state):
    """What every state of one continuation shares: labels, frame, origin, reference, settings, payloads and root."""
    stocks = state.reservoirs
    return (state.world_id, state.scenario_id, state.epoch_id, state.source_id, state.runtime_id, state.unit_system,
            state.frame_id, state.start_time_s, state.reference.reference_id, state.settings.settings_id,
            state.materials.state_id, state.layer_cohorts, None if stocks is None else stocks.inventory_id,
            state.reservoir_basis, state.root_state_id)


def _carried(state):
    """resume() keywords of a verified accepted state: cumulative values, arrays as fresh immutable descriptors."""
    column = state.column
    counters, extrema = dict(column._counters), dict(column._extrema)
    return dict(accepted=column.accepted_steps, stretch=column.stretch, clock_s=column.clock_s,
                displacement_m=column.displacement_m, log_strain_quadrature=column.log_strain_quadrature,
                log_path=column.log_path, theta0=column.initial_theta_k, theta=column.theta_k,
                kappa0=column.initial_kappa, kappa=column.kappa, accounts=dict(column._accounts),
                diagnostics={name: counters[name] if name in counters else extrema[name]
                             for name in _evolution.DIAGNOSTICS},
                yield_counts=column.yield_stage_counts, max_step_energy_relative=extrema['max_step_energy_relative'],
                max_temperature_step_k=extrema['max_temperature_step_k'],
                velocity_start_m_s=column.velocity_start_m_s, column_force_start_n_m=column.column_force_start_n_m)


def _successor(parent, prefix, budget):
    """The accepted successor of ``parent``: the prefix as a new column record; everything unchanged is shared."""
    settings, previous = parent.settings, parent.column
    values = prefix.carried()
    with select_budget(budget).reserve(_capture_bytes(parent.reference.points), category='i02-state-capture'):
        if (values['theta0'].tobytes() != previous._theta0.tobytes()
                or values['kappa0'].tobytes() != previous._kappa0.tobytes()):
            raise TectonicsError("the advanced prefix does not start from this history's initial departure and "
                                 "history")
        accepted, diagnostics = values['accepted'], values['diagnostics']
        scalars = dict(stretch=float(values['stretch']), elapsed_s=accepted*settings.step_s, accepted_steps=accepted,
                       clock_s=float(values['clock_s']), displacement_m=float(values['displacement_m']),
                       log_path=float(values['log_path']),
                       log_strain_quadrature=float(values['log_strain_quadrature']),
                       velocity_start_m_s=float(values['velocity_start_m_s']),
                       column_force_start_n_m=float(values['column_force_start_n_m']))
        extrema = dict({name: diagnostics[name] for name in EXTREMA[:4]},
                       max_step_energy_relative=values['max_step_energy_relative'],
                       max_temperature_step_k=values['max_temperature_step_k'])
        column = _column_state(
            'accepted state: cumulative since the reference at lam = 1 over whole steps of the fixed global schedule; '
            'accounts, counters, extrema and yield counts cover booked stages only, never a reconstruction re-solve',
            scalars, tuple((name, float(values['accounts'][name])) for name in STAGE_ACCOUNTS+THERMAL_ACCOUNTS),
            tuple((name, int(diagnostics[name])) for name in COUNTERS),
            tuple((name, float(extrema[name])) for name in EXTREMA),
            previous._theta0, values['theta'], previous._kappa0, values['kappa'], values['yield_counts'])
    return _envelope({name: getattr(parent, name) for name in _LABELS}, parent.start_time_s, parent.frame_id,
                     parent.reference, settings, column, parent.materials, parent.layer_cohorts, parent.reservoirs,
                     parent.reservoir_basis, parent.state_id, parent.root_state_id)


@dataclass(frozen=True, init=False, eq=False, slots=True)
class Advance(_Immutable):
    """The outcome of one requested piece, issued by Continuation.advance(); completing a piece is not the history.

    ``state`` is the accepted successor, or the input state itself when no step was accepted. ``status`` is
    PIECE_COMPLETE, HISTORY_COMPLETE or a retained refusal (REFUSED_STRETCH_WINDOW, REFUSED_TEMPERATURE_WINDOW,
    REFUSED_TEMPERATURE_STEP, REFUSED_CONSTITUTIVE or REFUSED_DEADLINE) with its ``reason``; a refusal keeps the exact
    accepted prefix. ``warm`` is True when the piece continued this continuation's own endpoint stage; otherwise the
    reference was balanced (a root) or a carried endpoint was re-solved cold, whose operational work is reported in
    ``reconstruction_*`` and never booked.
    """
    state: CommonState
    status: str
    reason: str | None
    requested_steps: int
    accepted_steps: int
    history_complete: bool
    warm: bool
    reconstruction_evaluations: int
    reconstruction_iterations: int

    def __init__(self, *args, **kwargs):
        raise TypeError('Advance is issued by Continuation.advance() only')


class Continuation:
    """One prepared continuation of a common-state history: operators rebuilt once, then reused by every piece.

    Construction verifies the state, rebuilds the mechanical preparation and thermal support from the pinned inputs,
    reproduces every carried reference byte and prepares the one reference eigensystem; nothing is serialised, and no
    piece rebuilds an operator or reruns accepted steps. States of the same root history advance by whole steps of the
    fixed global schedule; the cumulative step index, the 1e14 s horizon, the windows and the 5 K guard are never
    reset. The warm endpoint stage of the latest accepted state is kept (one entry) and used only for that exact state
    object; any other state's endpoint is re-solved cold as unbooked operational work. Not a transaction, store,
    accepted clock or thread-safe object.
    """
    __slots__ = ('_runner', '_context', '_budget', '_head')

    def __init__(self, state, *, budget=None):
        state = _verified(state)
        reference, settings = state.reference, state.settings
        advance_time(state.start_time_s, settings.step_s)           # one global step stays resolvable at this epoch
        if settings.duration_s > HORIZON_CEILING_S or not settings.steps <= settings.max_steps <= MAX_STEPS:
            raise TectonicsError('schedule outside the retained horizon or the cumulative step ceiling')
        described = json.loads(reference._record)
        pinned, inputs = described['pinned_preparation'], described['pinned_thermal']
        layers, order, closure, gravity = pinned['layers'], pinned['order'], pinned['closure'], pinned['gravity']
        base = _weakening.prepare(layers, order, closure=closure, gravity=gravity)
        thermal = _heat.prepare_thermal(base.layer, base.depth_m, base.weight, inputs['thicknesses'], inputs['props'],
                                        inputs['densities'], inputs['boundaries'],
                                        reference_temperature=inputs['reference_temperature'],
                                        mechanical_fingerprint=base.fingerprint)
        _reproduces(reference, base, thermal)
        record = json.loads(settings._record)
        parameters, numerics = record['parameters'], record['numerical_policy']
        law, drive, window, schedule = (parameters['law'], parameters['drive'], numerics['window'],
                                        numerics['schedule'])
        if (record['closure'] != dict(route=ROUTE, representation=REPRESENTATION, solver=SOLVER)
                or numerics['solver'] != SOLVER):
            raise TectonicsError('settings do not declare the supported route, representation and production solver')
        runner = _evolution.prepare_run(
            base, thermal,
            _weakening.WeakeningLaw(law['start'], law['end'], law['cohesion_factor'], law['friction_factor']),
            _motion.Drive(drive['force_n_m'], drive['drag_pa_s'], drive['width_m']),
            duration_s=schedule['duration_s'], steps=schedule['steps'],
            window=dict(stretch=window['stretch'], temperature_k=window['temperature_k']),
            temperature_step_k=window['max_temperature_step_k'], fractions=tuple(parameters['heat_fractions']),
            policy=numerics['policy'], conduction=SOLVER['conduction'], geometry_feedback=SOLVER['geometry_feedback'],
            warm_start=SOLVER['warm_start'], inputs=(layers, order, closure, gravity))
        if (runner.dt, runner.steps) != (settings.step_s, settings.steps):
            raise TectonicsError('the prepared schedule differs from the declared global schedule')
        self._runner, self._context, self._budget, self._head = runner, _context(state), budget, None

    def __reduce__(self):
        raise TypeError('a Continuation holds rebuilt operators and is never serialised; continue from a state')

    @property
    def runner(self):
        """The immutable prepared runner every piece reuses; it hands out its operators only as fresh copies."""
        return self._runner

    def _check(self, state):
        state = _verified(state)
        if _context(state) != self._context:
            raise TectonicsError('state belongs to another history, reference, settings, payload or root')
        return state

    def _prefix(self, state, deadline):
        """The accepted prefix of ``state`` and whether it is this continuation's warm head; rebuild work."""
        head = self._head
        if head is not None and head[0] is state:
            return head[1], True, (0, 0)
        column = state.column
        if column.accepted_steps == 0:
            prefix = _evolution.begin(self._runner, column.initial_kappa, column.initial_theta_k, deadline=deadline)
            return prefix, False, (0, 0)
        prefix = _evolution.resume(self._runner, deadline=deadline, **_carried(state))
        work = prefix.stage_work
        return prefix, False, (work['evaluations'], work['iterations'])

    def advance(self, state, steps, *, deadline=None):
        """Advance ``state`` by ``steps`` whole steps of its fixed global schedule; the input state never changes.

        ``steps`` is an integer in 1..remaining_steps: the original dt is kept, never a new duration or budget. Trial
        steps run on isolated candidate values inside the core; a refusal returns the exact accepted prefix, and an
        exception leaves the input state and this continuation's warm head unchanged. ``deadline`` is the caller's
        cooperative time budget for this piece (a perf_counter instant), as in evolve.
        """
        state = self._check(state)
        done, total = state.column.accepted_steps, state.settings.steps
        if done == total:
            raise TectonicsError('the scheduled history is complete: no whole steps remain')
        if type(steps) is not int or not 1 <= steps <= total-done:
            raise TectonicsError('a piece selects whole steps of the fixed schedule: an integer in 1..%d'
                                 % (total-done))
        try:
            prefix, warm, work = self._prefix(state, deadline)
        except RuntimeError:
            if not _evolution.expired(deadline):
                raise
            return _issue(Advance, state=state, status='REFUSED_DEADLINE',
                          reason='cooperative time budget exhausted before the endpoint stage was balanced',
                          requested_steps=steps, accepted_steps=0, history_complete=False, warm=False,
                          reconstruction_evaluations=0, reconstruction_iterations=0)
        after, status, reason = _evolution.advance(self._runner, prefix, steps, deadline=deadline)
        successor = state if after is prefix else _successor(state, after, self._budget)
        complete = after.accepted == total
        if status == 'COMPLETE':
            status = HISTORY_COMPLETE if complete else PIECE_COMPLETE
        self._head = (successor, after)
        return _issue(Advance, state=successor, status=status, reason=reason, requested_steps=steps,
                      accepted_steps=after.accepted-done, history_complete=complete, warm=warm,
                      reconstruction_evaluations=work[0], reconstruction_iterations=work[1])

    def report(self, state, *, deadline=None):
        """The retained evolve result of an accepted state, including the derived account identities; books nothing.

        Its status is HISTORY_COMPLETE or HISTORY_INCOMPLETE. The warm head is used when ``state`` is it; otherwise
        the endpoint is re-solved cold, and the warm head is kept.
        """
        state = self._check(state)
        prefix, _, _ = self._prefix(state, deadline)
        complete = prefix.accepted == state.settings.steps
        return _evolution.finish(self._runner, prefix, HISTORY_COMPLETE if complete else HISTORY_INCOMPLETE, None)
