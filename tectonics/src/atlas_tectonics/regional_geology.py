"""W01/W02 -> W07; contract: docs/W07_WORKFLOW.md.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import asdict, dataclass
import hashlib
import math

import numpy as np

from ._validation import TectonicsError, scalar
from .constitutive import _cancel
from .geological_records import GeologySource
from .precursor_sampling import _temperature, _profile_mean, PrecursorSamplingLimits
from .regional_execution import RegionalMechanicalSnapshot, _name, _hash
from .regional_forcing import PlanarRegionalSection
from .regional_workflow import RegionalWorkflowState
from .resources import WorkBudget, select_budget
from .reuse import ExecutionContext


@dataclass(frozen=True, slots=True)
class GeologicalMaterialLaw:
    """Explicit constant viscosity and bounded reference/buoyancy density law."""
    material_id: str
    viscosity_pa_s: float
    source: GeologySource
    density_law: str = 'reference-constant'

    def __post_init__(self):
        _name(self.material_id, 'material ID')
        object.__setattr__(self, 'viscosity_pa_s', scalar(self.viscosity_pa_s, 'viscosity', positive=True))
        if type(self.source) is not GeologySource:
            raise TectonicsError('material law requires a typed source')
        if self.density_law not in ('reference-constant', 'boussinesq-linear-reference'):
            raise TectonicsError('unknown geological density law')


@dataclass(frozen=True, slots=True)
class RegionalPhysicsOwnership:
    """Single contribution owners; no duplicate or unsupported additions."""
    gravity_source: GeologySource
    thermal_source: GeologySource
    motion_source: GeologySource
    surface_load_source: GeologySource
    boundary_motion_owner: str = 'W01-S6'
    boundary_source: GeologySource | None = None
    vertical_response_owner: str = 'W07'
    w04_state_id: str | None = None
    water_state_id: str | None = None
    extra_gravity_sources: tuple = ()
    extra_thermal_sources: tuple = ()
    extra_displacement_sources: tuple = ()

    def __post_init__(self):
        for name in ('gravity_source', 'thermal_source', 'motion_source', 'surface_load_source'):
            if type(getattr(self, name)) is not GeologySource:
                raise TectonicsError('ownership needs typed '+name)
        if self.vertical_response_owner != 'W07' or self.w04_state_id is not None:
            raise TectonicsError('W07 owns load/buoyancy response; W04 compensation cannot also be applied')
        if self.water_state_id is not None:
            raise TectonicsError('water loading requires a compatible water mass/load bridge')
        for key in ('extra_gravity_sources', 'extra_thermal_sources', 'extra_displacement_sources'):
            if type(getattr(self, key)) is not tuple or getattr(self, key):
                raise TectonicsError('duplicate or unsupported contribution: '+key)
        if self.boundary_motion_owner not in ('W01-S6', 'W07-boundary'):
            raise TectonicsError('explicit supported boundary-motion owner required')
        if self.boundary_motion_owner == 'W07-boundary':
            if type(self.boundary_source) is not GeologySource:
                raise TectonicsError('replacement W07 boundary motion requires its own source')
        elif self.boundary_source is not None:
            raise TectonicsError('S6 motion cannot also have a replacement boundary owner')


class RegionalGeologicalInputs(RegionalMechanicalSnapshot):
    """Immutable accepted inputs; no mutable producers or solver iterates retained."""
    __slots__ = ()

    def __init__(self, *args, **kwargs):
        raise TectonicsError('derive geological inputs with bind_regional_geology from typed W01/W02 state')

    @property
    def binding_id(self): return self.result_id
    @property
    def nx(self): return self.descriptor()['nx']
    @property
    def nz(self): return self.descriptor()['nz']
    @property
    def width_m(self): return self.descriptor()['width_m']
    @property
    def height_m(self): return self.descriptor()['height_m']
    @property
    def strike_width_m(self): return self.descriptor()['strike_width_m']
    @property
    def frame_id(self): return self.descriptor()['frame_id']
    @property
    def epoch_id(self): return self.descriptor()['epoch_id']
    @property
    def time_s(self): return self.descriptor()['time_s']
    @property
    def vertical_datum(self): return self.descriptor()['vertical_datum']
    @property
    def homogeneous_material(self): return self.descriptor()['homogeneous_material']

    def verify(self, cancel=None):
        """Fresh source/runtime comparison, without retaining an open context."""
        _cancel(cancel)
        d = self.descriptor()
        identity = _hash({'metadata': d, 'arrays': {
            key: {'shape': shape, 'sha256': hashlib.sha256(raw).hexdigest()}
            for key, shape, raw in self._fields}})
        if identity != self.binding_id:
            raise TectonicsError('geological input identity mismatch')
        with ExecutionContext(d['execution_backend']) as context:
            if context.identity != d['execution_id']:
                raise TectonicsError('geological source/runtime changed; no automatic rebind')
        _cancel(cancel)

    def surface_parameters(self):
        d = self.descriptor()
        if not d['surface_eligible']:
            raise TectonicsError('true-surface bridge needs one homogeneous isothermal reference-density cohort with zero heat production, whole surface support and stationary owned boundaries')
        material = d['homogeneous_material']
        return dict(nx=d['nx'], nz=d['nz'], width_m=d['width_m'], bottom_m=0.,
            reference_height_m=d['height_m'], viscosity_pa_s=material['viscosity_pa_s'],
            density_kg_m3=material['density_kg_m3'], gravity_m_s2=d['gravity_m_s2'],
            external_pressure_pa=d['external_pressure_pa'], strike_width_m=d['strike_width_m'],
            frame_id=d['frame_id'], vertical_datum=d['vertical_datum'],
            material_source=self.binding_id, load_source=_hash(d['ownership']))


def _profile_physics(profile):
    return {k: v for k, v in asdict(profile).items() if k not in ('profile_id', 'source_id')}


def _layers(workflow, laws):
    """Certify complete pure layers from exact W01 intersection volumes."""
    samples = workflow.initial_samples
    state = samples.state
    case = state.case
    profiles = {p.profile_id: p for p in case.thermal_profiles}
    materials = {m.material_id: m for m in case.materials}
    cohorts = {c.cohort.cohort_id: c.cohort for c in case.cohorts}
    rows = samples.array('row_cell')
    codes = samples.array('unit_code')
    volumes = samples.array('bulk_volume_m3')
    top, bottom = workflow.support.top_depth_m, workflow.support.bottom_depth_m
    area = workflow.material.grid.spacing_m*workflow.forcing.reduction.reference_width_m
    groups = {}
    for row, cell in enumerate(rows):
        unit = state.units[int(codes[row])]
        layer = unit.layer
        if (unit.kind != 'column' or layer.porosity != 0. or len(layer.components) != 1
                or layer.components[0].solid_volume_fraction != 1.):
            raise TectonicsError('ordered pure nonporous W01 column layers required; no implicit mixture/body sampling')
        cohort = cohorts[layer.components[0].cohort_id]
        material = materials[cohort.material_id]
        if material.material_class != 'solid' or material.material_id not in laws:
            raise TectonicsError('each represented solid material needs an explicit mechanical law')
        if material.density_kg_m3 is None or material.reference_temperature_k is None:
            raise TectonicsError('reference density and its temperature must be known')
        if material.valid_temperature_k is None:
            raise TectonicsError('material temperature validity must be explicitly declared')
        profile = profiles[unit.thermal_profile_id]
        if profile.mode == 'unknown':
            raise TectonicsError('original W01 thermal profile is unresolved')
        a, b = max(top, unit.top_depth_m), min(bottom, unit.bottom_depth_m)
        if b <= a:
            raise TectonicsError('sampled unit has no declared depth overlap')
        key = (a, b, cohort.cohort_id, _hash(_profile_physics(profile)))
        entry = groups.setdefault(key, dict(top_depth_m=a, bottom_depth_m=b,
            cohort=cohort, material=material, profile=profile, units=set(), profiles=set(), volumes={}))
        entry['units'].add(unit.unit_id)
        entry['profiles'].add(profile.profile_id)
        entry['volumes'].setdefault(int(cell), []).append(float(volumes[row]))
    layers = sorted(groups.values(), key=lambda x: (x['top_depth_m'], x['bottom_depth_m']))
    cursor = top
    for layer in layers:
        if layer['top_depth_m'] != cursor:
            raise TectonicsError('lateral/overlapping/gapped geological layers need a compatible spatial bridge')
        cursor = layer['bottom_depth_m']
        expected = area*(cursor-layer['top_depth_m'])
        for i in range(workflow.material.grid.cells):
            actual = math.fsum(layer['volumes'].get(i, ()))
            if abs(actual-expected) > 128*np.finfo(float).eps*expected:
                raise TectonicsError('each layer must cover every full planar column footprint')
    if cursor != bottom:
        raise TectonicsError('geological layers do not cover the mechanical depth support')
    if set(laws) != {layer['material'].material_id for layer in layers}:
        raise TectonicsError('material laws must match exactly the represented material set')
    return layers


def bind_regional_geology(workflow, *, nz, material_laws, ownership,
                          gravity_m_s2, vertical_datum, external_pressure_pa=0.,
                          w03=None, w06_state_id=None, budget=None, cancel=None):
    """Bind initial ordered geology, preserving depth/vector conventions."""
    _cancel(cancel)
    if type(workflow) is not RegionalWorkflowState:
        raise TectonicsError('typed current RegionalWorkflowState required')
    if type(ownership) is not RegionalPhysicsOwnership:
        raise TectonicsError('explicit typed regional ownership required')
    if w03 is not None:
        from .w03_workflow import W03ColumnState
        if type(w03) is not W03ColumnState:
            raise TectonicsError('W03 input must be W03ColumnState')
        raise TectonicsError('W03 ordered porous compaction geometry and fixed-reference cooling require a compatible deformed thermal/material bridge; initial W01 remap is stale')
    if w06_state_id is not None:
        raise TectonicsError('W06 motion needs an explicit compatible vector/boundary bridge')
    initial = workflow.initial_samples.state
    case = initial.case
    section = workflow.forcing.section
    nx = workflow.material.grid.cells
    if type(nz) is not int or not 2 <= nz <= 64 or not 2 <= nx <= 64:
        raise TectonicsError('bounded 2..64 mechanical counts required')
    if (workflow.steps != 0 or workflow.parent is not None or workflow.material.parent_state_id is not None
            or workflow.material.time_s != case.time_s or workflow.material.epoch_id != case.epoch_id):
        raise TectonicsError('evolved W02 has no ordered layer geometry or evolved temperature; compatible producer required')
    if type(section) is not PlanarRegionalSection or workflow.support.kind != 'planar-strip':
        raise TectonicsError('spherical wedge volumes cannot be silently flattened into a Cartesian section')
    if initial.bodies or initial.fields or case.weak_zones or case.faults:
        raise TectonicsError('body/stress/damage/forcing/weak-zone fields require explicit mechanical interpretation')
    if (section.frame_id != initial.sampling_domain.frame_id or section.epoch_id != case.epoch_id
            or section.time_s != case.time_s):
        raise TectonicsError('geological frame/epoch/time mismatch')
    components = workflow.forcing.samples.components_m_s
    if np.any(components[:, 1:] != 0.):
        raise TectonicsError('nonzero omitted/out-of-plane source motion cannot be discarded')
    speed = workflow.forcing.face_velocity_m_s
    if np.any(speed != speed[0]):
        raise TectonicsError('heterogeneous source deformation requires a compatible layer evolution bridge')
    if ownership.boundary_motion_owner == 'W07-boundary' and np.any(speed != 0.):
        raise TectonicsError('replacement boundary scenario cannot discard active source S6 motion')
    if (type(material_laws) is not tuple or not 0 < len(material_laws) <= 4096
            or any(type(x) is not GeologicalMaterialLaw for x in material_laws)):
        raise TectonicsError('bounded immutable tuple of geological material laws required')
    laws = {law.material_id: law for law in material_laws}
    if len(laws) != len(material_laws):
        raise TectonicsError('duplicate material laws')
    gravity = scalar(gravity_m_s2, 'gravity', nonnegative=True)
    pressure = scalar(external_pressure_pa, 'external pressure', nonnegative=True)
    _name(vertical_datum, 'vertical datum')
    resource = WorkBudget(128*1024**2, parent=select_budget(budget))
    count = len(workflow.material.cohorts)
    allowance = (128*count*nx*nz+2048*nx*nz+16*workflow.initial_samples.nbytes
                 +4*initial.retained_bytes_estimate+8*1024**2)
    with resource.reserve(allowance, category='regional-geological-binding'), ExecutionContext(workflow.backend) as context:
        context.verify()
        if context.identity != workflow.execution_id or _hash(workflow.descriptor()) != workflow.workflow_id:
            raise TectonicsError('upstream workflow source/runtime/identity changed; no automatic rebind')
        layers = _layers(workflow, laws)
        top, bottom = workflow.support.top_depth_m, workflow.support.bottom_depth_m
        height = bottom-top
        width = workflow.material.grid.length_m
        strike = workflow.forcing.reduction.reference_width_m
        dx, dz = width/nx, height/nz
        zv = np.linspace(0., height, nz+1)
        zc = (np.arange(nz)+.5)*dz
        cohorts = workflow.material.cohorts
        indices = {cohort.cohort_id: i for i, cohort in enumerate(cohorts)}
        phase = np.zeros((count, nz, nx))
        refmass = np.zeros_like(phase)
        eta_c = np.empty(nz)
        eta_v = np.empty(nz+1)
        temp_c = np.zeros(nz)
        temp_v = np.empty(nz+1)
        rho_c = np.zeros(nz)
        rho_w = np.zeros(nz+1)
        limits = PrecursorSamplingLimits()

        def temperature(layer, a, b=None):
            profile = layer['profile']
            if b is None:
                value = float(_temperature(profile, np.array([a]), case.time_s, resource)[0])
            else:
                value, _ = _profile_mean(profile, a, b, case.time_s, None, limits, cancel)
            material = layer['material']
            if not material.valid_temperature_k[0] <= value <= material.valid_temperature_k[1]:
                raise TectonicsError('sample temperature outside declared material validity')
            return value

        def density(layer, t):
            material = layer['material']
            rho = material.density_kg_m3
            if laws[material.material_id].density_law == 'boussinesq-linear-reference':
                if material.thermal_expansion_per_k is None:
                    raise TectonicsError('linear buoyancy requires the original expansion coefficient')
                rho *= 1.-material.thermal_expansion_per_k*(t-material.reference_temperature_k)
            return scalar(rho, 'buoyancy density', positive=True)

        def at_depth(depth):
            # Inward half-open layer membership, closing only the exterior bottom.
            for layer in layers:
                if layer['top_depth_m'] <= depth < layer['bottom_depth_m']:
                    return layer
            if depth == bottom:
                return layers[-1]
            raise TectonicsError('stress site outside geological support')

        for layer in layers:
            _cancel(cancel)
            # Whole-envelope endpoint/table-extremum check, not just mean validity.
            profile = layer['profile']
            cuts = (layer['top_depth_m'], layer['bottom_depth_m'],
                    *(v for v in profile.depths_m if layer['top_depth_m'] < v < layer['bottom_depth_m']))
            for value in cuts:
                t = temperature(layer, value)
                density(layer, t)
            a, b = bottom-layer['bottom_depth_m'], bottom-layer['top_depth_m']
            for j in range(nz):
                lo, hi = max(j*dz, a), min((j+1)*dz, b)
                if hi <= lo:
                    continue
                mean = temperature(layer, bottom-hi, bottom-lo)
                fraction = (hi-lo)/dz
                temp_c[j] += fraction*mean
                rho_c[j] += fraction*density(layer, mean)
                ci = indices[layer['cohort'].cohort_id]
                volume = (hi-lo)*dx*strike
                phase[ci, j, :] += volume
                refmass[ci, j, :] += volume*layer['material'].density_kg_m3
        for j, z in enumerate(zc):
            eta_c[j] = laws[at_depth(bottom-z)['material'].material_id].viscosity_pa_s
        for j, z in enumerate(zv):
            _cancel(cancel)
            layer = at_depth(bottom-z)
            temp_v[j] = temperature(layer, bottom-z)
            lo, hi = max(0., z-.5*dz), min(height, z+.5*dz)
            compliance = []
            density_integral = []
            for part in layers:
                a = max(lo, bottom-part['bottom_depth_m'])
                b = min(hi, bottom-part['top_depth_m'])
                if b > a:
                    compliance.append((b-a)/laws[part['material'].material_id].viscosity_pa_s)
                    density_integral.append((b-a)*density(part, temperature(part, bottom-b, bottom-a)))
            eta_v[j] = (hi-lo)/math.fsum(compliance)
            rho_w[j] = math.fsum(density_integral)/(hi-lo)
        actual_column_volume = workflow.material.thickness_m*dx*strike
        projected = np.sum(phase, axis=1)
        if np.any(np.abs(projected-actual_column_volume) > 128*np.finfo(float).eps*np.maximum(actual_column_volume, height*dx*strike)):
            raise TectonicsError('ordered W01 layer phase inventory disagrees with actual W02 inventory')
        broadcast = lambda a, n: np.broadcast_to(a[:, None], (len(a), n)).copy()
        arrays = dict(eta_center_pa_s=broadcast(eta_c, nx), eta_vertex_pa_s=broadcast(eta_v, nx+1),
            temperature_k=broadcast(temp_c, nx), temperature_vertex_k=broadcast(temp_v, nx+1),
            density_center_kg_m3=broadcast(rho_c, nx), density_w_kg_m3=broadcast(rho_w, nx),
            force_u_n_m3=np.zeros((nz, nx+1)), force_w_n_m3=-gravity*broadcast(rho_w, nx),
            cohort_partial_thickness_m=workflow.material.thickness_m,
            source_face_velocity_m_s=speed, phase_volume_m3=phase, reference_mass_kg=refmass,
            surface_height_m=np.full(2*nx+1, height))
        homogeneous = None
        if len(laws) == 1:
            material = layers[0]['material']
            homogeneous = asdict(material)
            homogeneous.update(viscosity_pa_s=laws[material.material_id].viscosity_pa_s,
                density_law=laws[material.material_id].density_law)
        thermal_records = [asdict(p) for p in case.thermal_profiles
                           if any(p.profile_id in layer['profiles'] for layer in layers)]
        isothermal = bool(np.all(temp_c == temp_c[0]) and np.all(temp_v == temp_c[0]))
        surface_eligible = bool(homogeneous is not None and len(cohorts) == 1 and isothermal and top == 0.
            and homogeneous['density_law'] == 'reference-constant'
            and homogeneous['heat_production_w_m3'] == 0. and np.all(speed == 0.))
        layer_records = [dict(top_depth_m=l['top_depth_m'], bottom_depth_m=l['bottom_depth_m'],
            cohort_id=l['cohort'].cohort_id, material_id=l['material'].material_id,
            unit_ids=sorted(l['units']), thermal_profile_ids=sorted(l['profiles'])) for l in layers]
        metadata = dict(schema='atlas.regional-geological-inputs.v1', nx=nx, nz=nz,
            width_m=width, height_m=height, strike_width_m=strike, frame_id=section.frame_id,
            epoch_id=case.epoch_id, time_s=case.time_s, vertical_datum=vertical_datum,
            gravity_m_s2=gravity, external_pressure_pa=pressure, ownership=asdict(ownership),
            source_workflow_id=workflow.workflow_id, source_root_id=workflow.root_id,
            initial_state_id=initial.state_id, geological_case_id=case.definition_id,
            initial_sample_id=workflow.initial_samples.sample_id, material_state_id=workflow.material.state_id,
            forcing_id=workflow.forcing.forcing_id, w03_state_id=None, w06_state_id=None,
            execution_id=context.identity, execution_backend=workflow.backend, source_execution_id=workflow.execution_id,
            cohorts=[asdict(c) for c in cohorts], layers=layer_records,
            material_definitions=[asdict(layers[next(i for i,l in enumerate(layers) if l['material'].material_id == mid)]['material']) for mid in sorted(laws)],
            material_laws=[asdict(laws[mid]) for mid in sorted(laws)],
            thermal_profiles=thermal_records, cooling_history=[asdict(h) for h in initial.cooling_history
                if h.profile_id in {p['profile_id'] for p in thermal_records}],
            geological_sources=[asdict(s) for s in case.sources], origins=[asdict(o) for o in initial.origins],
            material_volume_bases=[asdict(b) for b in initial.material_bases],
            transform=dict(x='section offset - grid.origin_m', x_origin_m=workflow.material.grid.origin_m,
                section_origin_m=section.origin_m, section_direction_xy=section.direction_xy,
                z='support.bottom_depth_m - inward_depth_m', inward_depth_origin_m=bottom,
                original_depth_reference_id=case.depth_reference_id,
                vector='u=tangent projection; w=-inward component; strike velocity explicitly absent',
                tensor='xx,dd unchanged; xz=-xd; plane strain yy=0'),
            material_sampling='centre exact inward-half-open point; vertex viscosity exact vertical dual-interval series compliance; no universal mixture law',
            temperature_semantics='W01 initial epoch: cell volume means and explicit vertex points; not evolved heat',
            force_semantics='full physical rho_b*(0,-g); regional execution alone subtracts declared reference gravity',
            inventory_semantics='actual W02 phase amounts; exact ordered phase intersections; reference_mass uses original rho0, not buoyancy density',
            homogeneous_material=homogeneous, isothermal=isothermal, surface_eligible=surface_eligible)
        _cancel(cancel)
        context.verify()
        result = object.__new__(RegionalGeologicalInputs)
        RegionalMechanicalSnapshot.__init__(result, metadata, arrays)
        return result
