"""Finite physical halo funding of an independently retained regional box.

These homogeneous boundary finite volumes are a declared discretisation, not
exact swept stream tubes. They are debited once from certified source support;
there is no refill, global reinsertion or moving-exterior geometry inference.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import json
import math
import weakref

import numpy as np

from ._validation import TectonicsError
from . import integration_material as M, integration_support as U, integration_volume as V
from .regional_execution import RegionalMechanicalSnapshot
from .regional_execution3d import SIDES
from .regional_transport3d import FiniteBoundaryStock3D
from .resources import WorkBudget, select_budget


TRACERS = ('accumulated_strain_ii', 'damage', 'source_kappa')
FIELDS = ('volume_m3', 'component_mass_kg', 'enthalpy_j')+tuple('tracer:'+k for k in TRACERS)
ACCOUNT_NAMES = ('volume_m3', 'mass_kg', 'relative_heat_j', 'absolute_heat_j', 'source_kappa_mass_kg')


class InventoryRefused(TectonicsError):
    """Unfunded, overlapping, stale or exhausted regional boundary inventory."""


def _json(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _q(value):
    if type(value) not in (list, tuple) or len(value) != 2 or any(type(v) is not str for v in value):
        raise InventoryRefused('an exact rational is a numerator/denominator string pair')
    try:
        return Q(*(int(v, 16) if v.startswith(('0x', '-0x')) else int(v) for v in value))
    except (ValueError, ZeroDivisionError) as exc:
        raise InventoryRefused('invalid exact inventory rational') from exc


def _encoded(value):
    return [hex(value.numerator), hex(value.denominator)]


def _width(value):
    """Input widths without serialising/parsing caller-owned values first."""
    if type(value) is Q:
        return 64+(abs(value.numerator).bit_length()+value.denominator.bit_length()+7)//8
    if type(value) is str:
        return 64+len(value)*4
    if type(value) is dict:
        return 128+sum(_width(k)+_width(v) for k, v in value.items())
    if type(value) in (tuple, list):
        return 64+sum(_width(v) for v in value)
    return 64


def _project(q):
    try:
        value = float(q)
    except OverflowError as exc:
        raise InventoryRefused('inventory projection overflows') from exc
    if not math.isfinite(value) or q != 0 and value == 0:
        raise InventoryRefused('inventory projection overflows or erases a nonzero value')
    return value


def _total(array):
    return sum((Q(float(v)) for v in np.asarray(array).flat), Q(0))


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class ComponentRegistry:
    """Fixed native component order, including explicitly absent finite supplies.

    The registry declares identity and constitutive compatibility, never stocks.
    Supply mass, heat and history must be funded by a separate finite inventory.
    Initial patch/layer components remain an unchanged sorted prefix.
    """
    _record: bytes = field(repr=False)
    _budget: object = field(repr=False, compare=False)

    def __init__(self, rows, *, budget, max_components=16, initial_source_plate_ids=()):
        if (type(max_components) is not int or not 1 <= max_components <= 256 or
                type(budget) is not WorkBudget or type(rows) not in (tuple, list) or
                not 1 <= len(rows) <= max_components):
            raise InventoryRefused('explicit component capacity within transport admission and shared budget required')
        if (type(initial_source_plate_ids) is not tuple or
                any(type(p) is not str or not p or len(p) > 256 for p in initial_source_plate_ids) or
                initial_source_plate_ids != tuple(sorted(set(initial_source_plate_ids)))):
            raise InventoryRefused('initial source plate domain must be an explicit sorted unique tuple')
        with budget.reserve(65536+4*_width(rows), category='regional-component-registry'):
            given, sources, supplies, started = [], set(), set(), False
            for row in rows:
                if type(row) is not dict or set(row) != {'lineage', 'plate_id', 'material_id', 'creep_law_id',
                                                       'composition_value', 'profile'}:
                    raise InventoryRefused('complete component lineage, profile and composition declaration required')
                for name in ('plate_id', 'material_id', 'creep_law_id'):
                    if type(row[name]) is not str or not row[name] or len(row[name]) > 256:
                        raise InventoryRefused('component identity must be an explicit bounded string')
                c = row['composition_value']
                if type(c) is not float or not math.isfinite(c) or not 0 <= c <= 1:
                    raise InventoryRefused('component composition_value must be a finite binary64 value in [0,1]')
                lineage = row['lineage']
                if type(lineage) is not dict or lineage.get('kind') not in ('initial-patch-layer', 'finite-supply'):
                    raise InventoryRefused('actual initial source or explicitly declared finite supply lineage required')
                initial = lineage['kind'] == 'initial-patch-layer'
                key = 'patch_id' if initial else 'supply_id'
                if set(lineage) != {'kind', 'source_id', key, 'sublayer'}:
                    raise InventoryRefused('component lineage fields do not match their declared kind')
                if (any(type(lineage[n]) is not str or not lineage[n] or len(lineage[n]) > 256
                        for n in ('source_id', key)) or
                        type(lineage['sublayer']) is not int or lineage['sublayer'] < 0):
                    raise InventoryRefused('component source identity and nonnegative sublayer required')
                if initial:
                    if started or (lineage[key], lineage['sublayer']) in sources:
                        raise InventoryRefused('initial components must form a unique unchanged prefix')
                    sources.add((lineage[key], lineage['sublayer']))
                else:
                    started = True
                    identity = (lineage[key], lineage['sublayer'])
                    if identity in supplies:
                        raise InventoryRefused('duplicate finite supply component')
                    supplies.add(identity)
                if (type(row['profile']) is not dict or set(row['profile']) != {'material', 'rheology'} or
                        any(type(row['profile'][n]) is not dict for n in ('material', 'rheology'))):
                    raise InventoryRefused('actual thermophysical and rheology profile records required')
                try:
                    plain = json.loads(_json(row))
                except (TypeError, ValueError) as exc:
                    raise InventoryRefused('component profile must be finite canonical data') from exc
                given.append(dict(component_id=hashlib.sha256(_json(plain)).hexdigest(), **plain))
            if not sources or tuple((r['lineage']['patch_id'], r['lineage']['sublayer'])
                    for r in given if r['lineage']['kind'] == 'initial-patch-layer') != tuple(sorted(sources)):
                raise InventoryRefused('actual source prefix must preserve the sorted patch/layer order')
            if any(r['profile'] != given[0]['profile'] for r in given):
                raise InventoryRefused('this native route requires one identical actual profile, not averaged laws')
            if initial_source_plate_ids and set(initial_source_plate_ids) != {
                    r['plate_id'] for r in given if r['lineage']['kind'] == 'initial-patch-layer'}:
                raise InventoryRefused('initial source domain differs from its actual registered plate owners')
            record = dict(schema='atlas.regional-component-registry.v1', rows=given)
            if max_components != 16:
                record['max_components'] = max_components
            if initial_source_plate_ids:
                record['initial_source_plate_ids'] = list(initial_source_plate_ids)
            encoded = _json(record)
            object.__setattr__(self, '_record', encoded)
            object.__setattr__(self, '_budget', budget)
            lease = budget.reserve(8192+len(encoded), category='regional-component-registry-retained')
            lease.__enter__()
            weakref.finalize(self, lease.__exit__, None, None, None)

    @property
    def registry_id(self):
        return hashlib.sha256(self._record).hexdigest()

    def record(self):
        return dict(registry_id=self.registry_id, **json.loads(self._record))

    @property
    def rows(self):
        return tuple(json.loads(self._record)['rows'])

    @property
    def source_keys(self):
        return tuple((r['lineage']['patch_id'], r['lineage']['sublayer']) for r in self.rows
                     if r['lineage']['kind'] == 'initial-patch-layer')

    @property
    def max_components(self):
        return json.loads(self._record).get('max_components', 16)

    @property
    def initial_source_plate_ids(self):
        return tuple(json.loads(self._record).get('initial_source_plate_ids', ()))

    def field_names(self, tracers):
        names = tuple(tracers)
        if len(set(names)) != len(names) or any(type(n) is not str or not n.startswith('tracer:') for n in names):
            raise InventoryRefused('explicit unique tracer field names required')
        return tuple('component_mass_kg:'+str(i) for i in range(len(self.rows)))+('enthalpy_j',)+tuple(sorted(names))

    def layout_components(self):
        return [dict(component_id=r['component_id'], plate_id=r['plate_id'], lineage=r['lineage']) for r in self.rows]

    @staticmethod
    def native_profile(native):
        """Only radial source geometry is excluded; no constitutive term is dropped."""
        from .regional_evolution3d import PreparedRegionalEvolution3D
        if type(native) is not PreparedRegionalEvolution3D:
            raise InventoryRefused('actual prepared native evolution required for component compatibility')
        d = native.descriptor()
        r = d['rheology']
        if r['family'] == 'radial-3d-creep-plastic':
            r = {k: v for k, v in r.items() if k not in ('source', 'source_id')}
        return dict(material=d['material'], rheology=r)

    def validate_native(self, native, *, source_id=None):
        profile, rows = self.native_profile(native), self.rows
        if (native._resource is not self._budget or len(rows) != len(native._composition) or
                native.descriptor().get('max_components', 16) != self.max_components):
            raise InventoryRefused('registry and native component count/shared budget differ')
        if any(r['profile'] != profile or r['composition_value'] != float(c)
               for r, c in zip(rows, native._composition)):
            raise InventoryRefused('component actual material/rheology/composition differs from native plan')
        if source_id is not None and any(r['lineage']['source_id'] != source_id for r in rows[:len(self.source_keys)]):
            raise InventoryRefused('initial registry source identity differs')

    @classmethod
    def from_record(cls, record, *, budget):
        if (type(budget) is not WorkBudget or type(record) is not dict or
                not {'schema', 'registry_id', 'rows'} <= set(record) or
                set(record)-{'schema', 'registry_id', 'rows', 'max_components', 'initial_source_plate_ids'} or
                record['schema'] != 'atlas.regional-component-registry.v1' or type(record['rows']) is not list):
            raise InventoryRefused('complete canonical component registry record required')
        with budget.reserve(65536+4*_width(record), category='regional-component-registry-restore'):
            rows = []
            for row in record['rows']:
                if type(row) is not dict or 'component_id' not in row:
                    raise InventoryRefused('registered component identity missing')
                rows.append({k: v for k, v in row.items() if k != 'component_id'})
            result = cls(rows, budget=budget, max_components=record.get('max_components', 16),
                         initial_source_plate_ids=tuple(record.get('initial_source_plate_ids', ())))
            if result.record() != record:
                raise InventoryRefused('component registry record is changed or noncanonical')
            return result


def birth_source_id(supply, column):
    """Identity of actual author-supplied birth physics, not an old patch alias."""
    from .integration_transfer import Supply
    if type(supply) is not Supply or type(column) is not M.BirthColumn:
        raise InventoryRefused('typed actual Supply and BirthColumn required')
    return hashlib.sha256(_json(dict(supply=supply.record(), birth_column=column.record()))).hexdigest()


def finite_birth_stocks(registry, supply, column, *, native, sphere, finite_area_m2,
                        enthalpy_reference_k, budget):
    """Author one finite shell supply; never infer or replenish a mantle stock.

    Physical stocks use exact ideal shell volume and declared caloric fields.
    The independently booked Supply projection is a separate signed account.
    That numerical account is not transported, heated, or re-created each step.
    """
    from .integration_transfer import Supply
    from .integration_sphere import SphereState, RIDGE
    if type(supply) is not Supply or type(sphere) is not SphereState:
        raise InventoryRefused('actual typed supply and sphere required')
    boundary = sphere.network.boundary(supply.boundary_id)
    context = dict(sphere_state_id=sphere.state_id, network_id=sphere.network.network_id,
        reference_radius_m=sphere.network.sphere.radius_m, boundary_id=boundary.boundary_id,
        boundary_kind=boundary.kind,
        plate_id=boundary.left_plate_id if supply.side == 'left' else boundary.right_plate_id)
    return _finite_birth_stocks(registry, supply, column, native=native, source_context=context,
        finite_area_m2=finite_area_m2, enthalpy_reference_k=enthalpy_reference_k, budget=budget)


def _finite_birth_stocks(registry, supply, column, *, native, source_context, finite_area_m2,
                         enthalpy_reference_k, budget):
    from .integration_transfer import Supply
    from .integration_sphere import RIDGE
    if (type(registry) is not ComponentRegistry or type(supply) is not Supply or
            type(column) is not M.BirthColumn or
            type(budget) is not WorkBudget or registry._budget is not budget):
        raise InventoryRefused('actual registered native/source/birth declarations on one budget required')
    registry.validate_native(native)
    if (not supply.stock or supply.history_id is None or column.volume_convention != V.PHYSICAL_RADIAL_SHELL or
            column.reference_radius_m != source_context['reference_radius_m'] or
            type(finite_area_m2) is not Q or finite_area_m2 <= 0 or
            type(enthalpy_reference_k) not in (int, float) or not math.isfinite(enthalpy_reference_k)):
        raise InventoryRefused('explicit finite area, heat reference and physical shell birth on the actual sphere required')
    if source_context['boundary_kind'] != RIDGE or source_context['boundary_id'] != supply.boundary_id:
        raise InventoryRefused('finite birth supply must name an actual ridge boundary')
    plate = source_context['plate_id']
    source_id = birth_source_id(supply, column)
    rows = registry.rows
    selected = [(i, row) for i, row in enumerate(rows)
                if row['lineage']['kind'] == 'finite-supply' and row['lineage']['supply_id'] == supply.source]
    if (len(selected) != len(column.sublayers) or
            [r['lineage']['sublayer'] for _, r in selected] != list(range(len(column.sublayers))) or
            any(r['lineage']['source_id'] != source_id or r['plate_id'] != plate for _, r in selected)):
        raise InventoryRefused('finite supply must have exactly its actual ordered birth-layer components')
    with budget.reserve(131072+8*(_width(registry.record())+_width(column.record())+_width(finite_area_m2)),
                        category='regional-finite-birth-admission'):
        # Preserve the existing declaration gate; no exact rho*rounded-volume
        # equality is substituted and no observed tolerance is introduced.
        M._check_birth(column, supply, budget=budget)
        shells = M.layer_geometry(column, budget=budget)
        weights = tuple(g.volume_per_area_m for g in shells)
        relative = M.declared_areal_heat(column, enthalpy_reference_k, budget=budget)
        booked_relative = tuple(Q(float(v)) for v in relative)
        if (supply.enthalpy_per_area_j_m2 is None or
                supply.enthalpy_per_area_j_m2 != float(sum(booked_relative, Q(0)))):
            raise InventoryRefused('finite birth heat must declare the existing per-layer caloric projection exactly')
        # The scalar Supply can round the sum of per-layer booked heat once.
        # Keep that column-only numerical remainder ONCE, on the first row's
        # account, without changing any physical layer temperature or energy.
        column_roundoff = Q(supply.enthalpy_per_area_j_m2)-sum(booked_relative, Q(0))
        phases = {s.phase for s in column.sublayers}
        phase_volume = {p: sum((w for s, w in zip(column.sublayers, weights) if s.phase == p), Q(0)) for p in phases}
        declared_mass, declared_volume = dict(supply.mass_per_area_kg_m2), dict(supply.thickness_m)
        tracers = ('tracer:accumulated_strain_ii', 'tracer:damage', 'tracer:source_kappa')
        if native._rheology_family == 'radial-3d-creep-plastic':
            tracers += ('tracer:radial_plastic_kappa',)
        names = registry.field_names(tracers)
        material = native.descriptor()['material']
        expected = (material['density_kg_m3'], material['heat_capacity_j_kg_k'], material['conductivity_w_m_k'],
                    material['expansion_per_k'], material['internal_heating_w_m3'])
        result = []
        for j, ((component, registered), layer, weight, heat) in enumerate(zip(selected, column.sublayers, weights, relative)):
            actual = (layer.reference_density_kg_m3, layer.heat_capacity_j_kg_k, layer.conductivity_w_m_k,
                      layer.alpha_per_k, layer.radiogenic_w_m3)
            if (actual != expected or registered['material_id'] != layer.material_id or
                    registered['creep_law_id'] != layer.creep_law_id):
                raise InventoryRefused('finite birth layer material/creep does not match its actual registered profile')
            if (native._rheology_family == 'radial-3d-creep-plastic' and
                    layer.pore_pressure_pa != registered['profile']['rheology']['pore_pressure_pa']):
                raise InventoryRefused('finite birth pore law differs from the registered radial material')
            area, rho, cp, reference = finite_area_m2, Q(layer.reference_density_kg_m3), Q(layer.heat_capacity_j_kg_k), Q(enthalpy_reference_k)
            volume, mass = area*weight, area*weight*rho
            absolute = area*heat+mass*cp*reference
            temperature = absolute/(mass*cp)
            if not Q(material['temperature_range_k'][0]) <= temperature <= Q(material['temperature_range_k'][1]):
                raise InventoryRefused('finite birth actual FV temperature exceeds the declared native material range')
            density_anomaly = (-rho*Q(material['expansion_per_k'])*(temperature-Q(material['reference_temperature_k']))
                +Q(material['composition_density_contrast_kg_m3'])*Q(registered['composition_value']))
            if abs(density_anomaly) > rho*Q(material['max_relative_density_anomaly']):
                raise InventoryRefused('finite birth exceeds the existing Boussinesq density envelope')
            fraction = weight/phase_volume[layer.phase]
            declared_v = area*Q(declared_volume[layer.phase])*fraction
            declared_m = area*Q(declared_mass[layer.phase])*fraction
            declared_relative = area*(booked_relative[j]+(column_roundoff if j == 0 else Q(0)))
            declared_absolute = declared_relative+declared_m*cp*reference
            fields = dict.fromkeys(names, Q(0)); fields['component_mass_kg:'+str(component)] = mass
            fields['enthalpy_j'] = absolute
            projection = dict.fromkeys(names, Q(0))
            projection['component_mass_kg:'+str(component)] = declared_m-mass
            projection['enthalpy_j'] = declared_absolute-absolute
            lineage = dict(kind='declared-finite-shell-birth', component_id=registered['component_id'],
                source_id=source_id, supply_id=supply.source, sublayer=j, plate_id=plate,
                source_context=source_context, reference_radius_m=column.reference_radius_m,
                finite_area_m2=_encoded(area), enthalpy_reference_k=enthalpy_reference_k,
                supply=supply.record(), birth_column=column.record(),
                physical_temperature_k=_encoded(temperature),
                declared=dict(volume_m3=_encoded(declared_v), mass_kg=_encoded(declared_m),
                              relative_heat_j=_encoded(declared_relative), absolute_heat_j=_encoded(declared_absolute)),
                admission_projection={k: _encoded(v) for k, v in projection.items()},
                admission_volume_projection_m3=_encoded(declared_v-volume),
                account_rule='declared source = physical finite stock + separate once-only admission projection',
                scalar_heat_roundoff_owner=(j == 0))
            ident = hashlib.sha256(_json(dict(source=supply.source, sublayer=j))).hexdigest()
            result.append(dict(stock_id=ident, kind='source', lineage=lineage,
                               volume_m3=_encoded(volume), exact={k: _encoded(v) for k, v in fields.items()}))
        return result


def _finite_export_rows(sink, context, names):
    source_id = hashlib.sha256(_json(dict(sink=sink.record(), source_context=context))).hexdigest()
    result = []
    for destination, fraction, stock in sink.destinations:
        lineage = dict(kind='declared-finite-trench-export', source_id=source_id,
            source_context=context, sink=sink.record(), destination=destination,
            destination_fraction=_encoded(Q(fraction)), declared_stock_node=stock)
        identity = hashlib.sha256(_json(dict(source_id=source_id, destination=destination, stock=stock))).hexdigest()
        result.append(dict(stock_id=identity, kind='sink', lineage=lineage,
            volume_m3=_encoded(Q(0)), exact={k: _encoded(Q(0)) for k in names}))
    return result


def finite_export_stocks(registry, sink, *, native, sphere, funding, budget):
    """Declare empty carried receivers from an actual trench Sink partition.

    A destination's original stock-node flag is preserved, not converted into a
    W08 stock or a physical thermal cell. Only real certified exports can fill it.
    """
    from .integration_transfer import Sink
    from .integration_sphere import SphereState, TRENCH
    from .integration_collar_geometry import FullCellFunding
    if (type(registry) is not ComponentRegistry or type(sink) is not Sink or
            type(sphere) is not SphereState or type(funding) is not FullCellFunding or
            registry._budget is not budget or funding._resource is not budget):
        raise InventoryRefused('actual registered sink, sphere and physical funding on one budget required')
    registry.validate_native(native)
    funded = funding.descriptor()
    if (funded['source']['sphere_state_id'] != sphere.state_id or
            funded['source']['network_id'] != sphere.network.network_id or
            funded.get('component_registry') != registry.record()):
        raise InventoryRefused('export declaration differs from actual registered funding/source')
    boundary = sphere.network.boundary(sink.boundary_id)
    if boundary.kind != TRENCH:
        raise InventoryRefused('finite export declaration requires an actual consuming trench')
    context = dict(sphere_state_id=sphere.state_id, network_id=sphere.network.network_id,
        reference_radius_m=sphere.network.sphere.radius_m, boundary_id=boundary.boundary_id,
        boundary_kind=boundary.kind, subducting_side=boundary.subducting_side,
        plate_id=boundary.left_plate_id if boundary.subducting_side == 'left' else boundary.right_plate_id)
    names = registry.field_names(k for k in funding.arrays() if k.startswith('tracer:'))
    with budget.reserve(65536+16*_width(sink.record())+2048*len(names)*len(sink.destinations),
                        category='regional-finite-export-admission'):
        return _finite_export_rows(sink, context, names)


def validate_birth_stocks(registry, stocks, *, native, funding, budget):
    """Recheck actual scalar birth physics, never claim a wall geometry proof.

    The registered full declarations and funding source are authoritative inputs.
    A later incoming edge still requires the issued differential boundary/side
    certificate; this routine cannot infer network topology from a source ID.
    Sinks initially contain exactly no physical stock and gain real exports.
    Optional material_quadrature_m3 is B=G at fresh admission only; all original
    physical stocks and lineage must still reproduce their declared funding.
    """
    from .integration_transfer import Supply, Sink
    from .integration_sphere import TRENCH
    from .integration_collar_geometry import FullCellFunding
    if (type(registry) is not ComponentRegistry or type(funding) is not FullCellFunding or
            registry._budget is not budget or funding._resource is not budget or type(stocks) is not list):
        raise InventoryRefused('actual typed registry/funding and declared finite rows required')
    registry.validate_native(native)
    with budget.reserve(65536+8*_width(stocks), category='regional-finite-birth-restore'):
        funded = funding.descriptor()
        if funded.get('component_registry') != registry.record():
            raise InventoryRefused('finite birth registry differs from actual physical funding')
        source = funded['source']
        radii = {_q(row['radial_layer']['radius_m']) for row in funding.exterior_remainder()}
        names = registry.field_names(k for k in funding.arrays() if k.startswith('tracer:'))
        groups, sink_groups, identifiers = {}, {}, set()
        for row in stocks:
            if type(row) is not dict or set(row) != {'stock_id', 'kind', 'lineage', 'volume_m3', 'exact'}:
                raise InventoryRefused('complete finite source/sink row required')
            if type(row['stock_id']) is not str or not row['stock_id'] or row['stock_id'] in identifiers:
                raise InventoryRefused('finite source/sink identities must be unique')
            identifiers.add(row['stock_id'])
            if type(row['lineage']) is not dict:
                raise InventoryRefused('explicit finite inventory lineage record required')
            if type(row['exact']) is not dict:
                raise InventoryRefused('complete exact finite inventory fields required')
            if 'material_quadrature_m3' in row['exact']:
                material = _q(row['exact']['material_quadrature_m3'])
                if (material < 0 or _encoded(material) != row['exact']['material_quadrature_m3'] or
                        material != _q(row['volume_m3'])):
                    raise InventoryRefused('initial material quadrature must equal declared geometric volume')
                # Compare the original declaration without mutating the supplied
                # dual-measure row. This never funds or repairs an evolved state.
                row = dict(row, exact={k: v for k, v in row['exact'].items() if k != 'material_quadrature_m3'})
            if row['kind'] == 'sink':
                if (_q(row['volume_m3']) != 0 or set(row['exact']) != set(names) or
                        any(_q(v) != 0 for v in row['exact'].values()) or not row['lineage'] or
                        'admission_projection' in row['lineage']):
                    raise InventoryRefused('fresh export sink must be explicitly empty, not another hidden material source')
                if row['lineage'].get('kind') != 'declared-finite-trench-export':
                    raise InventoryRefused('physical export receiver requires its actual declared trench Sink')
                sink_groups.setdefault(row['lineage'].get('source_id'), []).append(row)
                continue
            if row['kind'] != 'source' or row['lineage'].get('kind') != 'declared-finite-shell-birth':
                raise InventoryRefused('physical supply requires an actual registered shell BirthColumn, not raw algebra stocks')
            groups.setdefault(row['lineage']['source_id'], []).append(row)
        for group in groups.values():
            group.sort(key=lambda r: r['lineage']['sublayer'])
            lineage = group[0]['lineage']
            context = lineage['source_context']
            if (set(context) != {'sphere_state_id', 'network_id', 'reference_radius_m', 'boundary_id', 'boundary_kind', 'plate_id'} or
                    context['sphere_state_id'] != source['sphere_state_id'] or context['network_id'] != source['network_id'] or
                    radii != {Q(context['reference_radius_m'])}):
                raise InventoryRefused('finite birth source/sphere radius differs from actual physical funding')
            try:
                supply = Supply(**lineage['supply'])
                column = M.BirthColumn.from_record(lineage['birth_column'])
                expected = _finite_birth_stocks(registry, supply, column, native=native, source_context=context,
                    finite_area_m2=_q(lineage['finite_area_m2']),
                    enthalpy_reference_k=lineage['enthalpy_reference_k'], budget=budget)
            except (KeyError, TypeError, ValueError) as exc:
                raise InventoryRefused('finite birth declaration is malformed') from exc
            if group != expected:
                raise InventoryRefused('finite birth stocks/projections do not reproduce the actual registered declarations')
        for group in sink_groups.values():
            lineage = group[0]['lineage']
            try:
                context = lineage['source_context']
                if (set(context) != {'sphere_state_id', 'network_id', 'reference_radius_m', 'boundary_id',
                                     'boundary_kind', 'subducting_side', 'plate_id'} or
                        context['sphere_state_id'] != source['sphere_state_id'] or
                        context['network_id'] != source['network_id'] or
                        radii != {Q(context['reference_radius_m'])} or context['boundary_kind'] != TRENCH or
                        context['subducting_side'] not in ('left', 'right')):
                    raise InventoryRefused('finite export source/trench differs from actual physical funding')
                sink = Sink(**lineage['sink'])
                if sink.boundary_id != context['boundary_id']:
                    raise InventoryRefused('finite export boundary differs from its actual Sink')
                expected = _finite_export_rows(sink, context, names)
            except (KeyError, TypeError, ValueError) as exc:
                raise InventoryRefused('finite export declaration is malformed') from exc
            if sorted(group, key=lambda r: r['stock_id']) != sorted(expected, key=lambda r: r['stock_id']):
                raise InventoryRefused('finite export receivers do not reproduce the complete declared Sink partition')
        return True


@dataclass(frozen=True, slots=True)
class HaloReservoir:
    """An adjacent slab over exactly one native FV face; depth is exact metres.

    Tangential indices follow native x,y,z order with the normal axis removed.
    No corner extension or arbitrary translated reservoir is admissible.
    """
    side: str
    face_index: tuple
    patch_id: str
    sublayer: int
    depth_m: Q

    def __post_init__(self):
        if type(self.side) is not str or self.side not in SIDES:
            raise InventoryRefused('one native boundary side is required')
        if (type(self.face_index) is not tuple or len(self.face_index) != 2 or
                any(type(i) is not int or i < 0 for i in self.face_index)):
            raise InventoryRefused('two nonnegative tangential cell indices are required')
        if type(self.patch_id) is not str or not self.patch_id or len(self.patch_id) > 256:
            raise InventoryRefused('one actual source patch identity is required')
        if type(self.sublayer) is not int or self.sublayer < 0:
            raise InventoryRefused('one actual source sublayer is required')
        if type(self.depth_m) is not Q or self.depth_m <= 0:
            raise InventoryRefused('positive exact halo depth is required; operation width is budgeted at admission')

    def record(self):
        return dict(side=self.side, face_index=list(self.face_index), patch_id=self.patch_id,
                    sublayer=self.sublayer, depth_m=_encoded(self.depth_m))

    @classmethod
    def from_record(cls, row, *, budget=None):
        if type(row) is not dict or set(row) != {'side', 'face_index', 'patch_id', 'sublayer', 'depth_m'}:
            raise InventoryRefused('complete halo reservoir record required')
        if (type(row['face_index']) is not list or len(row['face_index']) != 2 or
                type(row['depth_m']) is not list or len(row['depth_m']) != 2 or
                any(type(s) is not str for s in row['depth_m'])):
            raise InventoryRefused('canonical face indices and exact rational halo depth required')
        with select_budget(budget).reserve(65536+64*_width(row), category='regional-halo-record-restore'):
            try:
                result = cls(row['side'], tuple(row['face_index']), row['patch_id'], row['sublayer'], _q(row['depth_m']))
            except (TypeError, ValueError, ZeroDivisionError) as exc:
                raise InventoryRefused('invalid exact halo reservoir record') from exc
            if result.record() != row:
                raise InventoryRefused('noncanonical halo reservoir record')
            return result


class RegionalBoundaryFunding:
    """Prepared finite funding; each successor owns remaining and exported fields."""

    def __setattr__(self, name, value):
        if not name.startswith('_') and hasattr(self, name):
            raise InventoryRefused('prepared boundary funding is immutable')
        object.__setattr__(self, name, value)

    def __init__(self, volume_map, sphere, moving, native, layout, remainder, reservoirs, *, budget):
        self._guard = None
        if type(budget) is not WorkBudget or budget is not native._resource:
            raise InventoryRefused('boundary funding and native owner must share the caller budget')
        if type(reservoirs) is not tuple or not reservoirs or any(type(r) is not HaloReservoir for r in reservoirs):
            raise InventoryRefused('nonempty typed finite halo reservoirs required')
        M.bound_moving(moving, sphere)
        self._budget, self._native = budget, native
        self._shape = native.cells
        self._nc = len(layout['components'])
        self._plastic = native.descriptor()['rheology']['family'] == 'radial-3d-creep-plastic'
        self._tracers = tuple(sorted(TRACERS+(('radial_plastic_kappa',) if self._plastic else ())))
        self._fields = ('volume_m3', 'component_mass_kg', 'enthalpy_j')+tuple('tracer:'+k for k in self._tracers)
        faces = sum(2*math.prod(n for j, n in enumerate(native.cells) if j != i) for i in range(3))
        if len(reservoirs) > faces:
            raise InventoryRefused('at most one halo reservoir per native boundary face')
        exact_width = sum(_width(r.depth_m) for r in reservoirs)+_width(remainder)+len(volume_map._record)
        self._work = 131072+(self._nc+8)*8192*faces+16*exact_width+4*U.required(sphere.material).workspace_bytes()
        self._guard = budget.reserve(self._work, category='regional-halo-funding-retained')
        self._guard.__enter__()
        try:
            self._prepare(volume_map, sphere, moving, native, layout, remainder, reservoirs)
        except BaseException:
            self.close()
            raise

    def _prepare(self, volume_map, sphere, moving, native, layout, remainder, reservoirs):
        mapped = volume_map.record()
        if mapped['source']['sphere_state_id'] != sphere.state_id or mapped['source']['moving_id'] != moving.moving_id:
            raise InventoryRefused('halo source differs from its physical volume map')
        embedding = mapped['embedding']
        basis = tuple(tuple(_q(v) for v in row) for row in embedding['basis'])
        origin = tuple(map(_q, embedding['origin_global_m']))
        spacing = tuple(map(_q, embedding['spacing_m']))
        lengths = tuple(Q(v) for v in native.lengths_m)
        if 'component_registry' in layout:
            registry = ComponentRegistry.from_record(layout['component_registry'], budget=self._budget)
            registry.validate_native(native, source_id=moving.moving_id)
            components = {key: i for i, key in enumerate(registry.source_keys)}
        else:
            components = {(v['patch_id'], v['sublayer']): i for i, v in enumerate(layout['components'])}
        patches = {p.patch_id: p for p in U.required(sphere.material).patches}
        remaining = {(r['patch_id'], r['sublayer']): json.loads(_json(r)) for r in remainder}
        for row in remaining.values():
            row['stocks'] = {k: _encoded(_q(q)) for k, q in row['stocks'].items()}
            row['geometry_volume_enclosure_m3'] = [_encoded(_q(q)) for q in row['geometry_volume_enclosure_m3']]
            row['physical_temperature_k'] = _encoded(_q(row['physical_temperature_k']))
            row['source_kappa'] = _encoded(_q(row['source_kappa']))
        extra_tracers = ('source_kappa', 'radial_plastic_kappa') if self._plastic else ('source_kappa',)
        stocks = native.empty_boundary_stocks(extra_tracers)
        arrays = {s: {k: stocks[s].array(k).copy() for k in self._fields} for s in SIDES}
        rho, cp, ref = Q(native._material.density_kg_m3), Q(native._material.heat_capacity_j_kg_k), Q(moving.enthalpy_reference_k)
        rows, seen, debits, projections, cones = [], set(), {}, [], {}
        fields = dict(moving._physical_columns)
        for spec in sorted(reservoirs, key=lambda r: (SIDES.index(r.side), r.face_index)):
            address = spec.side, spec.face_index
            if address in seen:
                raise InventoryRefused('overlapping duplicate boundary-face halo reservoir')
            seen.add(address)
            key = spec.patch_id, spec.sublayer
            if key not in components or key not in remaining:
                raise InventoryRefused('halo source must already be an admitted regional source component')
            axis = 'xyz'.index(spec.side[0]); end = int(spec.side[1])
            tangents = tuple(i for i in range(3) if i != axis)
            if any(i >= native.cells[j] for i, j in zip(spec.face_index, tangents)):
                raise InventoryRefused('halo tangential index is outside the actual native face')
            lower, upper = [Q(0)]*3, [Q(0)]*3
            lower[axis], upper[axis] = ((-spec.depth_m, Q(0)) if end == 0 else
                                       (lengths[axis], lengths[axis]+spec.depth_m))
            for index, j in zip(spec.face_index, tangents):
                lower[j], upper[j] = index*spacing[j], (index+1)*spacing[j]
            cell = V.CartesianCell(tuple(lower), tuple(upper), origin_m=origin, basis=basis, budget=self._budget)
            patch = patches[spec.patch_id]
            record = moving.cohort(patch.cohort_id)
            shell = M.layer_geometry(record, fields[spec.patch_id][0], budget=self._budget)[spec.sublayer]
            if spec.patch_id not in cones:
                try:
                    cones[spec.patch_id] = (V.convex_cone_union(patch.cells, budget=self._budget),)
                except V.VolumeError:
                    cones[spec.patch_id] = patch.cells
            if not any(V.contains_cartesian_cell(shell, cone, cell, budget=self._budget) for cone in cones[spec.patch_id]):
                raise InventoryRefused('whole halo box is not contained in its actual source cone/radial layer')
            v = cell.volume_m3
            previous = debits.get(key, Q(0))
            # Existing measured-area enclosure is retained; no geometric margin
            # or area allowance is used to move the physical box.
            if previous+v > _q(remaining[key]['geometry_volume_enclosure_m3'][0]):
                raise InventoryRefused('halo debit exceeds the certified outside-native source volume')
            debits[key] = previous+v
            temperature, kappa = _q(remaining[key]['physical_temperature_k']), _q(remaining[key]['source_kappa'])
            mass = rho*v; absolute = mass*cp*temperature
            ideal = (v, mass, absolute-mass*cp*ref, absolute, mass*kappa)
            fv, fm, fe, fk = map(_project, (v, mass, absolute, mass*kappa))
            represented = (Q(fv), Q(fm), Q(fe)-Q(fm)*cp*ref, Q(fe), Q(fk))
            a = arrays[spec.side]; index = spec.face_index
            a['volume_m3'][index] = fv
            a['component_mass_kg'][(components[key], *index)] = fm
            a['enthalpy_j'][index] = fe
            a['tracer:source_kappa'][index] = fk
            projections.append(dict(**spec.record(), **{name: _encoded(x-y) for name, x, y in zip(ACCOUNT_NAMES, ideal, represented)}))
            for name, value in zip(ACCOUNT_NAMES, ideal):
                after = _q(remaining[key]['stocks'][name])-value
                if name != 'relative_heat_j' and after < 0:
                    raise InventoryRefused('actual source stock cannot fund this halo box')
                remaining[key]['stocks'][name] = _encoded(after)
            geometry = remaining[key]['geometry']
            geometry.setdefault('excluded_halo_cell_ids', []).append(cell.cell_id)
            rows.append(dict(reservoir=spec.record(), cell=cell.record(), cell_id=cell.cell_id,
                             ideal_debit={name: _encoded(q) for name, q in zip(ACCOUNT_NAMES, ideal)}))
        for key, amount in debits.items():
            remaining[key]['geometry_volume_enclosure_m3'] = [
                _encoded(_q(q)-amount) for q in remaining[key]['geometry_volume_enclosure_m3']]
        record = dict(schema='atlas.regional-boundary-funding.v1', volume_map_id=volume_map.volume_map_id,
            number_encoding='canonical rational-hex for halo funding/remainder and cumulative inventory; original admission accounts retain their codec',
            native_plan_id=native.plan_id, source=mapped['source'], layout=layout,
            reservoirs=[r['reservoir'] for r in rows], certified_halo_cells=rows,
            projection_accounts=projections, physical_remainder=[remaining[k] for k in sorted(remaining)],
            disjointness='unique grid-face prisms: one coordinate strictly outside native box, others inside; interiors cannot overlap',
            flux_mapping='one native side/tangential FV face per reservoir; all omitted inlet stocks are zero',
            model='finite homogeneous boundary finite volumes; proportional withdrawal is the uniform FV law, never a refill',
            geometry_scope='initial physical halo support; depleted reservoirs are FV inventories, not certified moving swept-tube remainders',
            global_scope='frozen reference source; no active global exterior draw, no reinsertion, no shared kinematic clock')
        self._record = _json(record)
        self.funding_id = hashlib.sha256(self._record).hexdigest()
        self._keys = tuple(f'{side}:{key}' for side in SIDES for key in self._fields)
        self._array_shapes = {f'{side}:{key}': a.shape for side, values in arrays.items() for key, a in values.items()}
        initial_arrays = {f'remaining:{side}:{key}': a for side, values in arrays.items() for key, a in values.items()}
        initial_arrays.update({f'export:{side}:{key}': np.zeros_like(a) for side, values in arrays.items() for key, a in values.items()})
        exact_exports = {key: [_encoded(Q(0)) for _ in range(math.prod(shape))] for key, shape in self._array_shapes.items()}
        metadata = dict(schema='atlas.regional-boundary-inventory.v1', funding_id=self.funding_id,
            intervals=0, parent_inventory_id=None, native_state_id=None, transport_id=None,
            export_exact=exact_exports, transport_roundoff_accounts={},
            export_scope='cumulative per-face exported material held by this owner; never silently returned to global source')
        self.initial_state = RegionalMechanicalSnapshot(metadata, initial_arrays)

    def descriptor(self):
        return dict(funding_id=self.funding_id, **json.loads(self._record))

    def _bound(self, state):
        if type(state) is not RegionalMechanicalSnapshot:
            raise InventoryRefused('typed retained boundary inventory required')
        # Charge retained encoded width BEFORE JSON decode or integer parsing.
        with self._budget.reserve(65536+32*len(state._metadata), category='regional-halo-inventory-bound'):
            self._bound_values(state, state.descriptor())

    def _bound_values(self, state, metadata):
        if metadata.get('schema') != 'atlas.regional-boundary-inventory.v1' or metadata.get('funding_id') != self.funding_id:
            raise InventoryRefused('boundary inventory has another source/funding plan')
        count = metadata.get('intervals')
        if type(count) is not int or not 0 <= count <= 256:
            raise InventoryRefused('bounded boundary-inventory interval count required')
        expected = {prefix+':'+key for prefix in ('remaining', 'export') for key in self._keys}
        if set(state.array_names) != expected or set(metadata['export_exact']) != set(self._keys):
            raise InventoryRefused('boundary inventory field support was changed')
        for key, shape in self._array_shapes.items():
            for prefix in ('remaining', 'export'):
                a = state.array(prefix+':'+key)
                if a.shape != shape or not np.isfinite(a).all() or np.any(a < 0):
                    raise InventoryRefused('boundary inventory shape or nonnegative physical stock was changed')
            exact = tuple(map(_q, metadata['export_exact'][key]))
            if len(exact) != math.prod(shape) or any(q < 0 for q in exact):
                raise InventoryRefused('invalid exact exported material account')
            if [_encoded(q) for q in exact] != metadata['export_exact'][key]:
                raise InventoryRefused('noncanonical exact exported material account')
            if not np.array_equal(np.asarray([_project(q) for q in exact]).reshape(shape), state.array('export:'+key)):
                raise InventoryRefused('export float projection differs from its exact held material account')
        if any(_encoded(_q(q)) != q for q in metadata['transport_roundoff_accounts'].values()):
            raise InventoryRefused('noncanonical signed transport account')
        if count == 0 and state.result_id != self.initial_state.result_id:
            raise InventoryRefused('initial boundary inventory does not reproduce its exact funding')

    def stocks(self, state):
        self._bound(state)
        return {s: FiniteBoundaryStock3D(state.array(f'remaining:{s}:volume_m3'),
            state.array(f'remaining:{s}:component_mass_kg'), state.array(f'remaining:{s}:enthalpy_j'),
            {k: state.array(f'remaining:{s}:tracer:{k}') for k in self._tracers}) for s in SIDES}

    def advance(self, state, result, parent_native):
        """Capture only the actual accepted native transfers; no second solve."""
        stocks = self.stocks(state)
        report = result.transport.descriptor()
        if report['input_boundary_stock_ids'] != {s: stocks[s].result_id for s in SIDES}:
            raise InventoryRefused('native transport did not consume this exact owned boundary inventory')
        if result.descriptor()['parent_state_id'] != parent_native.result_id:
            raise InventoryRefused('native interval has another retained material parent')
        with self._budget.reserve(self._work+64*len(state._metadata), category='regional-halo-inventory-advance'):
            previous = state.descriptor(); arrays = {}; exact_exports = {}
            for side in SIDES:
                left, exported = result.transport.boundary_stocks[side], result.transport.exports[side]
                for key in self._fields:
                    address = side+':'+key
                    arrays['remaining:'+address] = left.array(key)
                    values = tuple(_q(q)+Q(float(v)) for q, v in
                                   zip(previous['export_exact'][address], exported.array(key).flat))
                    exact_exports[address] = [_encoded(v) for v in values]
                    arrays['export:'+address] = np.asarray([_project(v) for v in values]).reshape(self._array_shapes[address])
            # These signed exact differences expose floating transport/account
            # arithmetic. They are not added to physical stocks or heat sources.
            rounding = dict(previous['transport_roundoff_accounts'])
            before = dict(component_mass_kg=parent_native.array('component_mass_kg'),
                enthalpy_j=result.source_audit.array('enthalpy_after_sources_j'),
                **{'tracer:accumulated_strain_ii': result.source_audit.array('strain_history_after_sources_kg'),
                   'tracer:damage': parent_native.array('tracer:damage'),
                   'tracer:source_kappa': parent_native.array('tracer:source_kappa')})
            if self._plastic:
                before['tracer:radial_plastic_kappa'] = result.source_audit.array('plastic_history_after_sources_kg')
            for key, old in before.items():
                pieces = range(self._nc) if key == 'component_mass_kg' else (None,)
                for component in pieces:
                    select = lambda a: a if component is None else a[component]
                    error = _total(select(old))-_total(select(result.transport.array(key)))
                    for side in SIDES:
                        error += _total(select(stocks[side].array(key)))
                        error -= _total(select(result.transport.boundary_stocks[side].array(key)))
                        error -= _total(select(result.transport.exports[side].array(key)))
                    name = key if component is None else key+':'+str(component)
                    rounding[name] = _encoded(_q(rounding.get(name, ['0', '1']))+error)
            volume_error = sum((_total(stocks[s].array('volume_m3'))-
                _total(result.transport.boundary_stocks[s].array('volume_m3'))-
                _total(result.transport.exports[s].array('volume_m3')) for s in SIDES), Q(0))
            rounding['volume_m3'] = _encoded(_q(rounding.get('volume_m3', ['0', '1']))+volume_error)
            metadata = dict(previous, intervals=previous['intervals']+1, parent_inventory_id=state.result_id,
                native_state_id=result.state.result_id, transport_id=result.transport.result_id,
                source_audit_id=result.source_audit.result_id, duration_s=result.descriptor()['duration_s'],
                export_exact=exact_exports, transport_roundoff_accounts=rounding,
                last_remaining_stock_ids=report['remaining_boundary_stock_ids'], last_export_ids=report['export_ids'])
            issued = RegionalMechanicalSnapshot(metadata, arrays)
            self._bound(issued)
            return issued

    def restore(self, record, arrays, expected_result_id):
        with self._budget.reserve(self._work+32*_width(record), category='regional-halo-inventory-restore'):
            if any(np.asarray(a).dtype != np.dtype('float64') for a in arrays.values()):
                raise InventoryRefused('boundary inventory checkpoint must retain binary64 arrays')
            state = RegionalMechanicalSnapshot(record, arrays)
            if state.result_id != expected_result_id:
                raise InventoryRefused('boundary inventory checkpoint identity was changed')
            self._bound(state)
            return state

    def close(self):
        if self._guard is not None:
            self._guard.__exit__(None, None, None)
            self._guard = None
