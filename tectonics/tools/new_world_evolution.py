"""Generated crust -> full-vector W08 deformation -> dry local isostatic change.

SPDX-License-Identifier: AGPL-3.0-only
This is a bounded regional scenario, not global plate-topology evolution. Initial
temperatures remain source evidence, not an evolved thermal or enthalpy field.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import importlib
import json
import math
from pathlib import Path

from new_world_contract import ContractError, validate_plan

SCHEMA = 'atlas.generated-regional-initial.v1'
OUTPUT_SCHEMA = 'atlas.generated-regional-output.v1'
METHOD = 'generated-affine-crust-dry-airy-v1'
MAX_BYTES = 2 * 1024**2
_FILE = Path(__file__).resolve()
_HASH = hashlib.sha256(_FILE.read_bytes()).hexdigest()
_DEPENDENCIES = ('new_world_native', 'new_world_contract', 'new_world_project',
                 'new_world_layout', 'new_world_structure', 'new_world_thermal',
                 'new_world_motion', 'new_world_arcs')
_LOADED = None
REFERENCES = (
    'https://www.gplates.org/docs/pygplates/generated/pygplates.StrainRate.html',
    'https://gflex.readthedocs.io/en/latest/theory_and_numerics.html',
    'https://gmd.copernicus.org/articles/9/997/2016/gmd-9-997-2016.html',
)


def _fail(message):
    raise ContractError('EVOLUTION_REFUSED', message)


def encode(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ContractError('EVOLUTION_REFUSED', 'Invalid finite evolution record.') from exc
    if len(raw) > MAX_BYTES:
        _fail('Evolution record exceeds its 2 MiB envelope.')
    return raw


def _digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def _adapter_binding():
    """Cheap file-byte guard; numerical calls separately verify native execution."""
    global _LOADED
    modules = {name: importlib.import_module(name) for name in _DEPENDENCIES}
    now = {name: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
           for name, m in modules.items()}
    now['new_world_evolution'] = hashlib.sha256(_FILE.read_bytes()).hexdigest()
    if now['new_world_evolution'] != _HASH or (_LOADED is not None and now != _LOADED):
        raise ContractError('SOURCE_MISMATCH', 'Evolution adapters changed while loaded.')
    # The scientific adapters also check their own import-time hashes.
    modules['new_world_native'].source_binding()
    modules['new_world_structure']._source_binding()
    modules['new_world_motion']._source_binding()
    if _LOADED is None:
        _LOADED = now.copy()
    return now


def source_binding():
    """Bind adapters and native loaded-code/runtime identity, including cache hits."""
    from atlas_tectonics.reuse import ExecutionContext
    now = _adapter_binding()
    with ExecutionContext('scipy') as context:
        context.verify()
        return dict(adapters=now, native_execution_id=context.identity)


def prepare(project, options, *, cancel=None):
    """Sample a genuine saved world once; no layout/structure/motion generation."""
    from new_world_native import assemble_input
    from new_world_project import SavedProject
    if type(project) is not SavedProject or not project.configuration_compatible:
        _fail('A current, loaded native project is required for new execution.')
    plan = validate_plan(project.manifest['plan'])
    # assemble_input owns the structure/motion current-source checks. Do not
    # repeat those native checks simply because this is a second adapter layer.
    binding = source_binding()
    native = assemble_input(project, options, cancel=cancel)
    result = dict(schema=SCHEMA, method=METHOD, status='WORKING NON-CANON',
        project_id=project.manifest['project_id'], plan_id=plan['plan_id'],
        atlas_id=project.atlas.atlas_id, structure_id=project.structure.structure_id,
        motion_id=project.motion.motion_id, source_binding=binding,
        max_elapsed_s=native['max_elapsed_s'], native_input=native,
        support=dict(method='dry-local-Airy-change-v1', elastic_rigidity_nm=0.,
            fill_density_kg_m3=0., reference='same-material-parcel-at-initial-epoch',
            mantle_density_kg_m3=native['mantle_density_kg_m3'],
            interpretation='relative-upward-surface-and-base-displacement-not-absolute-DEM'),
        assumptions=[
            'Distributed affine deformation is a prescribed finite-width scenario, not a force solution.',
            'Normal convergence and along-strike slip both enter the finite material map.',
            'Exact spherical sampled volume is represented as volume divided by planar parcel area.',
            'Reference material densities and complete crustal parcel volumes are conserved.',
            'Instantaneous dry local compensation has zero elastic rigidity; no second flexural correction.',
            'Uplift is change relative to the initial material column, not a sea-level or absolute-height map.',
            'Initial temperature and unknown enthalpy are retained, not silently evolved or set to zero.',
            'The surrounding global plate network is not evolved by this regional continuation.'],
        references=list(REFERENCES))
    result['initial_id'] = _digest(result)
    if source_binding() != binding:
        raise ContractError('SOURCE_MISMATCH', 'Evolution sources changed during assembly.')
    return result


def check_initial(initial):
    """Authenticate current definition before restoring a closed-form producer."""
    if type(initial) is not dict or initial.get('schema') != SCHEMA or initial.get('method') != METHOD:
        _fail('Unsupported generated evolution initial state.')
    copied = json.loads(encode(initial))
    identity = copied.pop('initial_id', None)
    if identity != _digest(copied):
        _fail('Stored initial state identity does not match its physical inputs.')
    if initial.get('source_binding') != source_binding():
        raise ContractError('SOURCE_MISMATCH', 'Stored evolution source/runtime differs; no silent rebind.')
    t = initial.get('max_elapsed_s')
    if type(t) not in (float, int) or not math.isfinite(t) or t <= 0:
        _fail('A finite positive evolution horizon is required.')
    if initial['native_input'].get('max_elapsed_s') != t:
        _fail('Native and job evolution horizons disagree.')
    support = initial['support']
    if (support.get('method') != 'dry-local-Airy-change-v1'
            or support.get('elastic_rigidity_nm') != 0. or support.get('fill_density_kg_m3') != 0.):
        _fail('Unsupported vertical support law.')
    return initial


def local_isostatic_change(reference_h, current_h, density, mantle_density):
    """Exact dry zero-rigidity column balance, upward positive.

    At a common compensation depth, delta column weight is
    sum(rho_k * delta H_k) - rho_m * (delta H_total - delta surface) = 0.
    Gravity cancels; no arbitrary elevation multiplier or added flexure.
    """
    import numpy as np
    h0, h = np.asarray(reference_h, float), np.asarray(current_h, float)
    rho = np.asarray(density, float)
    if (h0.ndim != 2 or h.shape != h0.shape or rho.shape != (h.shape[0],)
            or not all(np.isfinite(a).all() for a in (h0, h, rho))
            or np.any(h0 < 0) or np.any(h < 0) or np.any(rho <= 0)
            or type(mantle_density) not in (float, int) or not math.isfinite(mantle_density)
            or mantle_density <= float(np.max(rho))):
        _fail('Dry crustal support needs finite lighter crust above an explicit denser mantle.')
    delta = h-h0
    thickening = np.sum(delta, axis=0)
    surface = np.sum((1-rho/mantle_density)[:, None]*delta, axis=0)
    base = surface-thickening
    residual = np.sum(rho[:, None]*delta, axis=0) + mantle_density*base
    return thickening, surface, base, residual


class PreparedEvolution:
    """One prepared native material owner for several outputs and direct restore.

    Native expm evaluates the prescribed finite map directly from the stored
    initial state; resume need not replay output times or resample source geology.
    """
    def __init__(self, initial, *, cancel=None):
        import numpy as np
        from atlas_tectonics.geometry import PlanarGeometry
        from atlas_tectonics.materials import MaterialCohort
        from atlas_tectonics.resources import WorkBudget
        from atlas_tectonics.transform import AffineMotionInterval, PreparedAffineMotion, PreparedPlanarMaterials
        self.initial = json.loads(encode(check_initial(initial)))
        self._adapter_sources = self.initial['source_binding'].get('adapters')
        self._cancel = cancel
        self._stack = ExitStack()
        self._closed = False
        n = self.initial['native_input']
        try:
            self._budget = WorkBudget(n['max_work_bytes'])
            self._polygons = tuple(PlanarGeometry.polygon(p, frame_id=n['frame_id'], budget=self._budget)
                                   for p in n['polygons_m'])
            self._areas = np.array([p.area_m2 for p in self._polygons])
            volume = np.asarray(n['volume_m3'], float)
            if volume.shape != (len(n['cohorts']), len(self._polygons)) or not np.isfinite(volume).all() or np.any(volume < 0):
                _fail('Invalid native sampled material inventory.')
            self._h0 = volume/self._areas
            self._rho = np.asarray(n['density_kg_m3'], float)
            self._mantle = self.initial['support']['mantle_density_kg_m3']
            local_isostatic_change(self._h0, self._h0, self._rho, self._mantle)
            event = AffineMotionInterval(n['epoch_time_s'] + self.initial['max_elapsed_s'],
                n['gradient_s'], n['velocity_m_s'], n['anchor_m'], self.initial['initial_id'])
            motion = self._stack.enter_context(PreparedAffineMotion(self._polygons, (event,),
                parcel_ids=tuple(n['parcel_ids']), time_s=n['epoch_time_s'],
                source_id=self.initial['initial_id'], budget=self._budget, cancel=cancel))
            self._material = self._stack.enter_context(PreparedPlanarMaterials(motion,
                tuple(MaterialCohort(**c) for c in n['cohorts']), self._h0,
                density_kg_m3=self._rho, epoch_id=n['epoch_id'], datum_id=n['datum_id'],
                source_id=self.initial['initial_id'], budget=self._budget, cancel=cancel))
        except BaseException:
            self._stack.close()
            raise

    def evaluate(self, elapsed_s):
        import numpy as np
        import shapely
        if self._closed:
            _fail('Evolution preparation is closed.')
        if self._adapter_sources is not None and _adapter_binding() != self._adapter_sources:
            raise ContractError('SOURCE_MISMATCH', 'Evolution adapters changed during continuation.')
        if type(elapsed_s) not in (int, float) or not math.isfinite(elapsed_s) or not 0 <= elapsed_s <= self.initial['max_elapsed_s']:
            _fail('Output lies outside the admitted finite forcing interval.')
        n = self.initial['native_input']
        absolute = n['epoch_time_s'] + elapsed_s
        if elapsed_s and absolute == n['epoch_time_s']:
            _fail('Absolute epoch cannot resolve the requested elapsed time.')
        state = self._material.evaluate(absolute, cancel=self._cancel)
        delta, surface, base, balance = local_isostatic_change(
            self._h0, state.thickness_m, self._rho, self._mantle)
        record = dict(schema=OUTPUT_SCHEMA, method=METHOD, status='WORKING NON-CANON',
            scope='generated-regional-material-scenario', initial_id=self.initial['initial_id'],
            project_id=self.initial['project_id'], elapsed_s=float(elapsed_s), time_s=absolute,
            epoch_id=n['epoch_id'], frame_id=n['frame_id'], datum_id=n['datum_id'],
            material_state_id=state.state_id, motion_state_id=state.motion.state_id,
            parcel_ids=n['parcel_ids'], cohorts=n['cohorts'],
            polygons_m=[shapely.get_coordinates(p._geom).tolist() for p in state.motion.polygons],
            area_m2=[p.area_m2 for p in state.motion.polygons],
            deformation_gradient=state.motion.deformation_gradient.tolist(),
            area_ratio=state.motion.jacobian.tolist(), thickness_m=state.thickness_m.tolist(),
            volume_m3=state.volume_m3.tolist(), mass_kg=state.mass_kg.tolist(),
            crust_thickness_change_m=delta.tolist(), surface_change_m=surface.tolist(),
            base_change_m=base.tolist(), column_balance_residual_kg_m2=balance.tolist(),
            enthalpy_j=None, enthalpy_known=False, evolved_temperature_k=None,
            absolute_elevation_m=None, support=self.initial['support'],
            units=dict(thickness_m='m', surface_change_m='m-upward', base_change_m='m-upward',
                volume_m3='m3', mass_kg='kg', elapsed_s='s'),
            accounted_workspace_peak_bytes=self._budget.peak_reserved_bytes)
        chart = n.get('metadata', {}).get('chart')
        if chart is not None:
            record['coordinate_mapping'] = dict(method='inverse-source-gnomonic-display',
                **{key:chart[key] for key in ('centre','basis_x','basis_y','radius_m')})
            centre, x, y = (np.asarray(chart[key]) for key in ('centre','basis_x','basis_y'))
            directions = []
            for polygon in record['polygons_m']:
                xy = np.asarray(polygon)/chart['radius_m']
                unit = centre+xy[:, :1]*x+xy[:, 1:]*y
                unit /= np.linalg.norm(unit, axis=1)[:, None]
                directions.append(unit.tolist())
            record['footprints_unit_sphere'] = directions
            record['coordinate_mapping']['meaning'] = 'located material view; area/thickness owner remains the admitted planar scenario'
        # Resource diagnostics are deliberately outside scientific identity.
        scientific = {k:v for k,v in record.items() if k != 'accounted_workspace_peak_bytes'}
        record['output_id'] = _digest(scientific)
        encode(record)
        if self._adapter_sources is not None and _adapter_binding() != self._adapter_sources:
            raise ContractError('SOURCE_MISMATCH', 'Evolution adapters changed before output publication.')
        return record

    def close(self):
        if not self._closed:
            self._closed = True
            self._stack.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
