"""Small explicit W06 workflow recipes shared by focused tests and timing.

This is not a checkpoint-to-input factory: callers select the original recipe.
The inherited margin is a separate physical domain, never ocean hot birth.
"""
from contextlib import contextmanager
from dataclasses import fields, is_dataclass, replace
import hashlib
import json

import numpy as np

from atlas_tectonics.constitutive import BoussinesqMaterial
from atlas_tectonics.margin_cooling import PreparedMarginCooling, MarginSupportResult
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
from atlas_tectonics.thermal_support import ThermalSupportParameters
from atlas_tectonics.w06_workflow import MarginWorkflowPolicy
from test_w06_spreading_cooling import CASE, COOLING, YEAR, ROOT, cooling_fixture
from test_w06_history_cooling import HISTORY, history_fixture
from test_w06_margin_cooling import PLATE, inherited, changed_case
import precursor_fixtures


ROUTES = ('constant', 'history', 'margin')
THREAD_VARIABLES = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS')
LIMITS = StoreLimits(65536, 8*1024**2, 64*1024**2)
COMPRESSION = Compression()
CALLER_ALLOWANCE = 16*1024**2


def verify_frozen_design():
    design = CASE['frozen_design']
    if (design != COOLING['frozen_design'] or design != HISTORY['frozen_design'] or
            hashlib.sha256((ROOT/design['path']).read_bytes()).hexdigest() != design['sha256']):
        raise ValueError('frozen W06 design changed; do not repin')


def margin_source(*, temperature_shift_k=0., unknown_reason='earlier thermal history unknown'):
    source = inherited()
    profile = replace(source.case.thermal_profiles[0],
        temperatures_k=(300., 650.+temperature_shift_k, 800., 1300.))
    case = changed_case(source.case, time_s=1e12, thermal_profiles=(profile,))
    unknown = replace(source.cooling_history[0], start_time_s=None, unknown_reason=unknown_reason)
    return precursor_fixtures.state(case, cooling_history=(unknown,))


def margin_policy(source):
    materials = tuple(BoussinesqMaterial(m.material_id, m.source_id, m.density_kg_m3,
        m.specific_heat_j_kg_k, m.conductivity_w_m_k, m.thermal_expansion_per_k,
        m.reference_temperature_k, 0., 0., (300., 2000.), .05) for m in source.case.materials)
    support = ThermalSupportParameters('reference-surface', 'synthetic inherited reference',
        'reference-surface', 'column-isostasy', 3300., 1030., 9.81, .05)
    return MarginWorkflowPolicy(materials, support, 2000., 10., 1e6,
                                'finite-test-ocean', 'w06-inherited-workflow-policy')


@contextmanager
def route_fixture(route, *, budget, context=None, cells=8, source=None, policy=None, **changes):
    if route == 'margin':
        source = margin_source() if source is None else source
        policy = margin_policy(source) if policy is None else policy
        with PreparedMarginCooling(source, 'continent', PLATE, thinning_source_id='fixture',
                geometry_reference_id='reference-surface', context=context, budget=budget, **changes) as plan:
            origin = source.case.time_s
            yield plan, policy, (origin, origin+1e12, origin+1e14, origin+1e15)
    elif route in ('constant', 'history'):
        factory = cooling_fixture if route == 'constant' else history_fixture
        edges = changes.pop('edges', np.linspace(*CASE['domain_m'], cells+1))
        with factory(edges=edges, context=context, budget=budget, **changes) as plan:
            yield plan, None, tuple(years*YEAR for years in CASE['output_years'])
    else:
        raise ValueError('unknown explicit workflow recipe')


def open_store(path, budget, cls=ArrayStore, *, limits=LIMITS):
    return cls(path, limits=limits, compression=COMPRESSION, budget=budget)


def _record(value):
    """Complete typed-state byte fingerprint, independent of persistence codecs."""
    if isinstance(value, np.ndarray):
        return dict(dtype=value.dtype.str, shape=value.shape,
                    sha256=hashlib.sha256(value.tobytes()).hexdigest())
    if isinstance(value, bytes):
        return dict(length=len(value), sha256=hashlib.sha256(value).hexdigest())
    if is_dataclass(value):
        return dict(type=type(value).__name__, fields={f.name: (
            dict(state_id=value.source_state.state_id) if f.name == 'source_state'
            else _record(getattr(value, f.name)))
            for f in fields(value)})
    if isinstance(value, (tuple, list)):
        return [_record(item) for item in value]
    if isinstance(value, dict):
        return {key: _record(item) for key, item in value.items()}
    if isinstance(value, np.generic):
        return value.item()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # Geological state itself is source-bound by this scientific identity;
    # its actual profile/history records are also fields of MarginThermalResult.
    if hasattr(value, 'state_id'):
        return dict(type=type(value).__name__, state_id=value.state_id)
    raise TypeError('unhandled workflow record '+type(value).__name__)


def checkpoint_signature(checkpoint):
    body = json.dumps(_record(checkpoint), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return dict(checkpoint_id=checkpoint.checkpoint_id, output_index=checkpoint.output_index,
                state_type=type(checkpoint.state).__name__, sha256=hashlib.sha256(body).hexdigest())


def scientific_arrays(state):
    if type(state) is MarginSupportResult:
        t = state.thermal
        return tuple(getattr(t, name) for name in ('depth_edges_m', 'mean_temperature_k',
            'initial_reference_temperature_k', 'temperature_change_k', 'outward_heat_j_m2'))
    arrays = tuple(getattr(state, name) for name in ('cell_values', 'centre_values',
        'ocean_fraction', 'centre_valid', 'heat_accounts_j', 'water_accounts_m3'))
    geometry = ('intersections', 'centre_age_s', 'centre_strip_index') if hasattr(
        state.motion, 'intersections') else ('cell_geometry',)
    return arrays+(state.motion.accounts_kg,)+tuple(getattr(state.motion, name) for name in geometry)
