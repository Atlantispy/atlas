"""Physical material-to-hydraulic geometry and conservative wet-material ports.

This adapter does not infer soil horizons, fertility, conductivity or strength
from material names or support scores. Point properties are explicit hypotheses.
The persistent material state is the actual pinned R1 finite column contract.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import math
from pathlib import Path

from .deps import landscape, verify

OWNER_PATH = Path('C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/02_Working_Files/Geography/Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-10-R1/CLIMATE_SOILS_OWNER_DECISION_2026-09-10_R1.md')
OWNER_SHA256 = 'ba909d8a3e34a1722cba51925d602eca28d749a91a7bbf2162baf99221b4de19'
MAX_LAYERS = 128
MAX_BITS = 8192
STATUSES = frozenset(('CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST'))
PHYSICAL_FIELDS = ('grain_density_kg_m3', 'porosity', 'theta_r', 'alpha_per_m',
                   'n', 'mualem_l', 'ksat_vertical_m_s', 'ksat_horizontal_m_s',
                   'effective_cohesion_pa', 'friction_angle_deg')


def verify_sources():
    verify()
    landscape._verify_sources()
    if hashlib.sha256(OWNER_PATH.read_bytes()).hexdigest() != OWNER_SHA256:
        raise ValueError('soil owner source changed; no silent repin')


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + ' requires bounded nonempty text')


def _number(value, name, *, signed=False):
    if type(value) not in (int, float, Fraction):
        raise ValueError(name + ' requires a physical quantity, not a bool/score/object')
    if type(value) is float and not math.isfinite(value):
        raise ValueError(name + ' must be finite')
    result = Fraction(value)
    if not signed and result < 0:
        raise ValueError(name + ' cannot be negative')
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > MAX_BITS:
        raise ValueError(name + ' exceeds bounded exact arithmetic')
    return result


def _pair(value):
    return [value.numerator, value.denominator]


def _unpair(value, name, *, signed=False):
    if type(value) is not list or len(value) != 2 or any(type(x) is not int for x in value) or value[1] <= 0:
        raise ValueError(name + ' needs an exact numerator/positive denominator')
    return _number(Fraction(*value), name, signed=signed)


def _fields(record, names, name):
    if type(record) is not dict or set(record) != set(names):
        raise ValueError(name + ' schema fields differ')


def _status(values):
    return 'SYNTHETIC TEST' if all(x == 'SYNTHETIC TEST' for x in values) else 'WORKING NON-CANON'


@dataclass(frozen=True)
class MaterialHydraulics:
    """One explicit physical point scenario for a material phase and packing.

    Theta is volumetric water content [m3/m3]; full saturation equals porosity.
    Retention is van Genuchten with m=1-1/n; no parameter or fluid default exists.
    Evidence must support the *joint* packing, hydraulic and strength hypothesis.
    """
    material_id: str
    phase: str
    grain_density_kg_m3: Fraction
    porosity: Fraction
    theta_r: Fraction
    alpha_per_m: Fraction
    n: Fraction
    mualem_l: Fraction
    ksat_vertical_m_s: Fraction
    ksat_horizontal_m_s: Fraction
    effective_cohesion_pa: Fraction
    friction_angle_deg: Fraction
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.material_id, 'material identity')
        _text(self.evidence, 'physical joint-scenario evidence')
        if self.phase not in landscape.PHASES or self.source_status not in STATUSES:
            raise ValueError('resolved material phase and source status required')
        for key in PHYSICAL_FIELDS:
            object.__setattr__(self, key, _number(getattr(self, key), key, signed=key == 'mualem_l'))
        if (self.grain_density_kg_m3 <= 0 or not 0 < self.porosity < 1 or
                not 0 <= self.theta_r < self.porosity or self.alpha_per_m <= 0 or
                self.n <= 1 or self.mualem_l < 0 or self.friction_angle_deg >= 90):
            raise ValueError('physical soil/retention scenario outside supported range')

    def as_dict(self):
        return {**vars(self), **{key: _pair(getattr(self, key)) for key in PHYSICAL_FIELDS}}

    @classmethod
    def from_dict(cls, record):
        _fields(record, (*PHYSICAL_FIELDS, 'material_id', 'phase', 'evidence', 'source_status'), 'material hydraulics')
        values = dict(record)
        for key in PHYSICAL_FIELDS:
            values[key] = _unpair(values[key], key, signed=key == 'mualem_l')
        return cls(**values)


@dataclass(frozen=True)
class HydraulicBinding:
    layer_id: str
    properties: MaterialHydraulics
    water_volume_m3: Fraction

    def __post_init__(self):
        _text(self.layer_id, 'persistent layer identity')
        if type(self.properties) is not MaterialHydraulics:
            raise ValueError('explicit MaterialHydraulics required')
        object.__setattr__(self, 'water_volume_m3', _number(self.water_volume_m3, 'porewater volume'))


def _compatible(layer, properties):
    if type(layer) is not landscape.Layer or type(properties) is not MaterialHydraulics:
        raise ValueError('actual pinned material layer and physical properties required')
    # Exact represented equality is intentional. A changed packing requires a
    # newly qualified property scenario, not a silent Ksat/strength carry-over.
    for name in ('material_id', 'phase', 'grain_density_kg_m3', 'porosity'):
        if getattr(layer, name) != getattr(properties, name):
            raise ValueError('hydraulic input incompatible with material ' + name)


@dataclass(frozen=True)
class HydraulicProfile:
    profile_id: str
    column: object
    bindings: tuple[HydraulicBinding, ...]
    evidence: str

    def __post_init__(self):
        _text(self.profile_id, 'profile identity')
        _text(self.evidence, 'profile physical interpretation')
        if type(self.column) is not landscape.Column:
            raise ValueError('actual pinned finite material Column required')
        _number(self.column.area_m2, 'column area')
        _number(self.column.basal_elevation_m, 'basal elevation', signed=True)
        if (type(self.bindings) is not tuple or len(self.bindings) > MAX_LAYERS or
                len(self.bindings) != len(self.column.layers) or
                any(type(b) is not HydraulicBinding for b in self.bindings)):
            raise ValueError('one bounded bottom-to-top hydraulic binding per physical layer required')
        if len({b.layer_id for b in self.bindings}) != len(self.bindings):
            raise ValueError('duplicate persistent layer identity')
        density = {}
        for layer, binding in zip(self.column.layers, self.bindings):
            _compatible(layer, binding.properties)
            landscape._check_layer(layer)
            previous = density.setdefault(layer.material_id, layer.grain_density_kg_m3)
            if previous != layer.grain_density_kg_m3:
                raise ValueError('one material identity cannot have conflicting grain density')
            volume = _number(layer.bulk_volume_m3, 'bulk layer volume')
            minimum = _number(binding.properties.theta_r * volume, 'retention residual storage')
            maximum = _number(layer.porosity * volume, 'pore capacity')
            if not minimum <= binding.water_volume_m3 <= maximum:
                raise ValueError('porewater is outside supplied residual-to-saturation storage domain')
        _number(self.water_volume_m3, 'total profile porewater')

    @property
    def water_volume_m3(self):
        return sum((b.water_volume_m3 for b in self.bindings), Fraction())

    @property
    def source_status(self):
        return _status((self.column.source_status, *(b.properties.source_status for b in self.bindings)))

    def as_dict(self):
        return {'schema': 'diadem.material-hydraulic-profile.r3', 'owner_sha256': OWNER_SHA256,
                'profile_id': self.profile_id, 'column': self.column.as_dict(),
                'bindings': [{'layer_id': b.layer_id, 'properties': b.properties.as_dict(),
                              'water_volume_m3': _pair(b.water_volume_m3)} for b in self.bindings],
                'evidence': self.evidence}

    @classmethod
    def from_dict(cls, record):
        verify_sources()
        _fields(record, ('schema', 'owner_sha256', 'profile_id', 'column', 'bindings', 'evidence'), 'hydraulic profile')
        if record['schema'] != 'diadem.material-hydraulic-profile.r3' or record['owner_sha256'] != OWNER_SHA256:
            raise ValueError('hydraulic profile schema/owner binding differs')
        rows = record['bindings']
        if type(rows) is not list or len(rows) > MAX_LAYERS:
            raise ValueError('bounded hydraulic binding records required')
        bindings = []
        for row in rows:
            _fields(row, ('layer_id', 'properties', 'water_volume_m3'), 'hydraulic binding')
            bindings.append(HydraulicBinding(row['layer_id'], MaterialHydraulics.from_dict(row['properties']),
                                             _unpair(row['water_volume_m3'], 'stored water')))
        column_record = record['column']
        _fields(column_record, ('schema', 'area_m2', 'basal_elevation_m', 'source_status', 'layers'), 'material column')
        if type(column_record['layers']) is not list or len(column_record['layers']) != len(bindings):
            raise ValueError('one physical layer record per hydraulic binding required')
        for layer in column_record['layers']:
            _fields(layer, ('material_id', 'mass_kg', 'grain_density_kg_m3', 'porosity', 'phase', 'evidence'), 'physical layer')
        column = landscape.Column.from_dict(column_record)
        return cls(record['profile_id'], column, tuple(bindings), record['evidence'])


def bind_column(column, material_inputs, layer_ids, water_volumes_m3, *, profile_id, evidence):
    """Bind supplied physical properties and actual water to bottom-to-top stock."""
    verify_sources()
    if any(type(values) is not tuple for values in (material_inputs, layer_ids, water_volumes_m3)):
        raise ValueError('immutable bottom-to-top property/identity/water tuples required')
    if not len(material_inputs) == len(layer_ids) == len(water_volumes_m3) or len(material_inputs) > MAX_LAYERS:
        raise ValueError('property, identity and water inventories differ')
    return HydraulicProfile(profile_id, column,
                            tuple(HydraulicBinding(*items) for items in zip(layer_ids, material_inputs, water_volumes_m3)), evidence)


def hydraulic_rows(profile):
    """Top-to-bottom exact physical rows for a compatible vertical Water solver.

    Theta_s is the physical stock porosity. This function does not infer heads:
    saturated theta does not determine positive pressure; Water owns that solve.
    Empty exhausted columns return (), not an invented residual soil/rock layer.
    """
    verify_sources()
    if type(profile) is not HydraulicProfile:
        raise ValueError('HydraulicProfile required')
    rows = []
    depth = Fraction()
    for layer, binding in reversed(tuple(zip(profile.column.layers, profile.bindings))):
        p = binding.properties
        thickness = _number(layer.bulk_volume_m3 / profile.column.area_m2, 'hydraulic thickness')
        bottom = _number(depth + thickness, 'profile depth')
        rows.append({'layer_id': binding.layer_id, 'material_id': layer.material_id, 'phase': layer.phase,
                     'top_depth_m': depth, 'bottom_depth_m': bottom, 'thickness_m': thickness,
                     'mass_kg': layer.mass_kg, 'grain_density_kg_m3': layer.grain_density_kg_m3,
                     'water_volume_m3': binding.water_volume_m3,
                     'theta': _number(binding.water_volume_m3 / layer.bulk_volume_m3, 'volumetric water content'),
                     'theta_s': layer.porosity, 'theta_r': p.theta_r, 'alpha_per_m': p.alpha_per_m,
                     'n': p.n, 'mualem_l': p.mualem_l, 'ksat_m_s': p.ksat_vertical_m_s,
                     'ksat_horizontal_m_s': p.ksat_horizontal_m_s,
                     'effective_cohesion_pa': p.effective_cohesion_pa, 'friction_angle_deg': p.friction_angle_deg,
                     'evidence': p.evidence, 'source_status': profile.source_status})
        depth = bottom
    return tuple(rows)


@dataclass(frozen=True)
class WetParcel:
    source_profile_id: str
    source_layer_id: str
    layer: object
    properties: MaterialHydraulics
    water_volume_m3: Fraction

    def __post_init__(self):
        _text(self.source_profile_id, 'parcel source profile')
        _text(self.source_layer_id, 'parcel source layer')
        _compatible(self.layer, self.properties)
        object.__setattr__(self, 'water_volume_m3', _number(self.water_volume_m3, 'parcel porewater'))
        volume = self.layer.bulk_volume_m3
        if not self.properties.theta_r * volume <= self.water_volume_m3 <= self.layer.porosity * volume:
            raise ValueError('wet parcel violates its physical water capacity')


@dataclass(frozen=True)
class MaterialWaterChange:
    profile: HydraulicProfile
    exported_parcels: tuple[WetParcel, ...]
    water_to_surface_m3: Fraction
    receipt: dict


def _ledger(before, after, *, imported_mass=Fraction(), exported_mass=Fraction(),
            imported_water=Fraction(), exported_water=Fraction(), surface_water=Fraction(), operation):
    mr = before.column.mass_kg + imported_mass - after.column.mass_kg - exported_mass
    wr = before.water_volume_m3 + imported_water - after.water_volume_m3 - exported_water - surface_water
    if mr or wr:
        raise ArithmeticError('material/porewater port accounting failed to close')
    values = {'initial_mass_kg': before.column.mass_kg, 'imported_mass_kg': imported_mass,
              'final_mass_kg': after.column.mass_kg, 'exported_mass_kg': exported_mass, 'mass_residual_kg': mr,
              'initial_water_m3': before.water_volume_m3, 'imported_water_m3': imported_water,
              'final_water_m3': after.water_volume_m3, 'exported_water_m3': exported_water,
              'water_to_surface_m3': surface_water, 'water_residual_m3': wr}
    return {'schema': 'diadem.material-porewater-change.r3', 'operation': operation,
            'owner_sha256': OWNER_SHA256, 'source_status': after.source_status,
            **{key: _pair(_number(value, key)) for key, value in values.items()},
            'accounting': 'exact represented material and water volumes; scalar homogeneous moisture per material layer'}


def reconcile_eroded_column(profile, after_column):
    """Reconcile an actual R1 erosion result without borrowing unchanged geometry.

    Only top-down removal is admissible. Any deposition/repacking/reordering or
    basal/footprint change must take its own explicit material/water port.
    Every removed parcel carries the same water/solid-mass ratio as its source
    layer; retained material preserves theta. Export order is surface downward.
    """
    verify_sources()
    if type(profile) is not HydraulicProfile or type(after_column) is not landscape.Column:
        raise ValueError('physical before profile and actual after column required')
    before = profile.column
    if before.area_m2 != after_column.area_m2 or before.basal_elevation_m != after_column.basal_elevation_m:
        raise ValueError('erosion reconciliation cannot change footprint or basal elevation')
    removed_mass = _number(before.mass_kg - after_column.mass_kg, 'eroded mass')
    expected, raw = before.strip_mass(removed_mass)
    if expected.layers != after_column.layers or raw['unmet_mass_kg']:
        raise ValueError('after column is not the exact finite top-removal transition')
    bindings = tuple(replace(binding, water_volume_m3=_number(binding.water_volume_m3 * layer.mass_kg / old.mass_kg,
                                                              'retained porewater'))
                     for layer, old, binding in zip(after_column.layers, before.layers, profile.bindings))
    # R1 keeps the original exact material metadata in each removed parcel.
    exports = []
    for removed, old, binding in zip(raw['removed_layers'], reversed(before.layers), reversed(profile.bindings)):
        water = _number(binding.water_volume_m3 * removed.mass_kg / old.mass_kg, 'exported porewater')
        exports.append(WetParcel(profile.profile_id, binding.layer_id, removed, binding.properties, water))
    after_column = replace(after_column, source_status=_status((profile.source_status, after_column.source_status)))
    after = HydraulicProfile(profile.profile_id, after_column, bindings, profile.evidence)
    receipt = _ledger(profile, after, exported_mass=removed_mass,
                      exported_water=sum((p.water_volume_m3 for p in exports), Fraction()), operation='TOP_DOWN_EROSION')
    return MaterialWaterChange(after, tuple(exports), Fraction(), receipt)


def strip_surface(profile, requested_mass_kg):
    """Execute actual R1 finite removal then reconcile its wet material stocks."""
    verify_sources()
    if type(profile) is not HydraulicProfile:
        raise ValueError('HydraulicProfile required')
    request = _number(requested_mass_kg, 'requested erosion mass')
    after, raw = profile.column.strip_mass(request)
    result = reconcile_eroded_column(profile, after)
    return replace(result, receipt={**result.receipt, 'requested_mass_kg': _pair(request),
                                    'unmet_mass_kg': _pair(raw['unmet_mass_kg'])})


def deposit_surface(profile, layer, properties, water_volume_m3, *, layer_id, evidence):
    """Deposit supplied wet mobile sediment; release packing excess to surface.

    Caller owns transfer identity, once-only consumption and route/arrival.
    Water may arrive in excess of new pore capacity (e.g. repacked wet sediment).
    It is returned explicitly, never discarded. Drier-than-residual deposits
    reject; callers must supply real water or a valid alternative retention case.
    """
    verify_sources()
    if type(profile) is not HydraulicProfile:
        raise ValueError('HydraulicProfile required')
    _compatible(layer, properties)
    _text(evidence, 'deposition physical evidence')
    if layer.phase != 'mobile_sediment':
        raise ValueError('deposition requires explicitly fragmented mobile sediment')
    water = _number(water_volume_m3, 'imported sediment porewater')
    capacity = _number(layer.bulk_volume_m3 * layer.porosity, 'deposit pore capacity')
    stored = min(water, capacity)
    binding = HydraulicBinding(layer_id, properties, stored)
    status = _status((profile.source_status, properties.source_status))
    after_column = replace(profile.column.deposit(layer), source_status=status)
    after = HydraulicProfile(profile.profile_id, after_column, (*profile.bindings, binding), profile.evidence)
    excess = water - stored
    receipt = _ledger(profile, after, imported_mass=layer.mass_kg, imported_water=water,
                      surface_water=excess, operation='PRESCRIBED_WET_SEDIMENT_DEPOSITION')
    return MaterialWaterChange(after, (), excess, {**receipt, 'deposition_evidence': evidence, 'deposition_layer_id': layer_id})


def replace_porewater(profile, water_volumes_m3, *, evidence):
    """Install externally solved bottom-to-top layer stores, without clipping.

    The returned exact net delta is the quantity the Water caller must reconcile
    against its independent flux ledger, including explicit numerical residuals.
    This adapter does not certify that those external Water fluxes were solved.
    """
    verify_sources()
    if type(profile) is not HydraulicProfile or type(water_volumes_m3) is not tuple or len(water_volumes_m3) != len(profile.bindings):
        raise ValueError('one solved porewater volume per physical layer required')
    _text(evidence, 'external Water state evidence')
    bindings = tuple(replace(b, water_volume_m3=v) for b, v in zip(profile.bindings, water_volumes_m3))
    after = replace(profile, column=replace(profile.column, source_status=profile.source_status), bindings=bindings)
    delta = _number(after.water_volume_m3 - profile.water_volume_m3, 'water solver net change', signed=True)
    return after, {'schema': 'diadem.external-porewater-update.r3', 'net_water_change_m3': _pair(delta),
                   'evidence': evidence, 'flux_balance_status': 'CALLER_MUST_RECONCILE_INDEPENDENT_WATER_LEDGER'}
