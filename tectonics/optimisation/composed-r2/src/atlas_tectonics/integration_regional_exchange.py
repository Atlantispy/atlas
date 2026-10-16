"""Local, read-only deformation/heat exchange of a persistent regional owner.

SPDX-License-Identifier: AGPL-3.0-only

This is not the piece-mean I04 P6/P7 representation. It consumes the source
audit of the existing evolution step, never solves mechanics or books heat.
"""
from fractions import Fraction
import hashlib
import json
import math

import numpy as np

from ._validation import TectonicsError, scalar
from .regional_execution import RegionalMechanicalSnapshot
from .regional_evolution3d import RegionalEvolutionAdvance3D
from .resources import select_budget

SCHEMA = 'atlas.regional-owner-exchange.v1'
LAYOUT_SCHEMA = 'atlas.regional-owner-layout.v1'
AUDIT_SCHEMA = 'atlas.regional-evolution3d-source-audit.v1'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _name(value):
    if type(value) is not str or not value or len(value) > 256:
        raise TectonicsError('regional ownership names must be explicit bounded strings')
    return value


def _layout(layout, budget=None):
    keys = {'schema', 'region_id', 'cells', 'lengths_m', 'plate_ids', 'components',
            'native_plan_id', 'transfer_id'}
    registered = type(layout) is dict and layout.get('schema') == 'atlas.regional-owner-layout.v2'
    if registered:
        keys.add('component_registry')
        if 'initial_source_plate_ids' in layout:
            keys.add('initial_source_plate_ids')
    if type(layout) is not dict or set(layout) != keys or (not registered and layout['schema'] != LAYOUT_SCHEMA):
        raise TectonicsError('explicit regional material layout required')
    cells = tuple(layout['cells'])
    if len(cells) != 3 or any(type(v) is not int or not 2 <= v <= 24 for v in cells):
        raise TectonicsError('regional layout requires three cell counts in [2,24]')
    lengths = tuple(scalar(v, 'regional length', positive=True) for v in layout['lengths_m'])
    if len(lengths) != 3:
        raise TectonicsError('regional layout requires three lengths')
    plates = tuple(_name(v) for v in layout['plate_ids'])
    if len(plates) != 2 or len(set(plates)) != 2:
        raise TectonicsError('regional layout names two distinct surrounding plates')
    given = layout['components']
    if type(given) not in (list, tuple) or not 1 <= len(given) <= (256 if registered else 16):
        raise TectonicsError('regional layout requires one to sixteen material components')
    if registered:
        from .integration_regional_inventory import ComponentRegistry
        registry = ComponentRegistry.from_record(layout['component_registry'], budget=select_budget(budget))
        source_plates = registry.initial_source_plate_ids
        if (layout.get('initial_source_plate_ids', []) != list(source_plates) or
                source_plates and not set(plates) <= set(source_plates) or
                given != registry.layout_components() or
                any(row['plate_id'] not in (source_plates or plates) for row in given)):
            raise TectonicsError('registered regional components differ from their declared lineage/order/plates')
        plain = dict(schema='atlas.regional-owner-layout.v2', region_id=_name(layout['region_id']), cells=list(cells),
                     lengths_m=list(lengths), plate_ids=list(plates), components=registry.layout_components(),
                     native_plan_id=_name(layout['native_plan_id']), transfer_id=_name(layout['transfer_id']),
                     component_registry=registry.record())
        if source_plates:
            plain['initial_source_plate_ids'] = list(source_plates)
        return plain, hashlib.sha256(_json(plain)).hexdigest()
    components = []
    for item in given:
        if type(item) is not dict or set(item) != {'patch_id', 'sublayer', 'plate_id'}:
            raise TectonicsError('each material component names its patch, sublayer and plate')
        if type(item['sublayer']) is not int or item['sublayer'] < 0:
            raise TectonicsError('material sublayer is a nonnegative index')
        component = dict(patch_id=_name(item['patch_id']), sublayer=item['sublayer'],
                         plate_id=_name(item['plate_id']))
        if component['plate_id'] not in plates:
            raise TectonicsError('material component names a plate outside its owner layout')
        components.append(component)
    if len({(p['patch_id'], p['sublayer']) for p in components}) != len(components):
        raise TectonicsError('regional components must have distinct material ownership')
    plain = dict(schema=LAYOUT_SCHEMA, region_id=_name(layout['region_id']), cells=list(cells),
                 lengths_m=list(lengths), plate_ids=list(plates), components=components,
                 native_plan_id=_name(layout['native_plan_id']), transfer_id=_name(layout['transfer_id']))
    return plain, hashlib.sha256(_json(plain)).hexdigest()


def _total(value):
    return sum((Fraction(float(v)) for v in np.asarray(value).flat), Fraction(0))


def _exact(value):
    return '%d/%d' % (value.numerator, value.denominator)


def regional_exchange(advance, *, layout, parent_state, budget=None):
    """Observe one already-heated interval of an explicitly admitted local law.

    Component positions are the carried cell masses, not a frozen assignment of
    cells to plates. Sources belong to donor cells before transport. Individual
    component enthalpies after mixing/conduction are not represented by the
    native shared-cell caloric model, and are not invented here.
    """
    definition, layout_id = _layout(layout, budget)
    if type(advance) is not RegionalEvolutionAdvance3D or type(parent_state) is not RegionalMechanicalSnapshot:
        raise TectonicsError('a regional evolution advance and its actual parent snapshot are required')
    audit = advance.source_audit
    if type(audit) is not RegionalMechanicalSnapshot:
        raise TectonicsError('this evolution result has no retained source audit')
    meta, source = advance.descriptor(), audit.descriptor()
    expected = dict(plan_id=definition['native_plan_id'], parent_state_id=parent_state.result_id,
                    initial_mechanics_id=advance.initial_mechanics.result_id)
    if any(meta.get(k) != v or source.get(k) != v for k, v in expected.items()):
        raise TectonicsError('regional exchange parent, plan or initial mechanics is stale')
    if (meta.get('source_audit_id') != audit.result_id or source.get('schema') != AUDIT_SCHEMA
            or meta.get('state_id') != advance.state.result_id
            or meta.get('mechanics_id') != advance.mechanics.result_id
            or meta.get('transport_id') != advance.transport.result_id
            or meta.get('heat_id') != advance.heat.result_id):
        raise TectonicsError('regional exchange does not name the actual interval outputs')
    radial = source.get('rheology_family') == 'radial-3d-creep-plastic'
    if (source.get('rheology_family') not in ('constant', 'i01-newtonian-creep', 'radial-3d-creep-plastic')
            or source.get('include_viscous_heating') is not True):
        raise TectonicsError('this local exchange requires admitted rheology and already-booked local dissipation heat')
    dt = scalar(meta.get('duration_s'), 'interval duration', positive=True)
    if source.get('duration_s') != dt or source.get('start_time_s') != parent_state.descriptor()['time_s']:
        raise TectonicsError('regional source audit names another interval')
    cells, components = tuple(definition['cells']), len(definition['components'])
    if source.get('cells') != definition['cells'] or source.get('lengths_m') != definition['lengths_m']:
        raise TectonicsError('regional owner geometry differs from the audited source support')
    n = math.prod(cells)
    # Immutable output/copy allowance is separate from the solver's own budget.
    required = 65536+4*(audit.nbytes+8*n*(2*components+27*14+12)+len(_json(definition)))
    with select_budget(budget).reserve(required, category='regional-local-exchange'):
        before = parent_state.array('component_mass_kg')
        after = advance.state.array('component_mass_kg')
        if (before.shape != (components, *cells) or after.shape != before.shape
                or np.any(before < 0) or np.any(after < 0)):
            raise TectonicsError('regional material component arrays do not match the owner layout')
        volume = audit.array('cell_volume_m3')
        power, rate = audit.array('viscous_dissipation_w_m3'), audit.array('strain_rate_ii_s_inv')
        weights = audit.array('quadrature_fraction')
        if (volume.shape != cells or power.shape != (n, 27) or rate.shape != power.shape
                or weights.shape != (27,) or np.any(volume <= 0) or np.any(weights <= 0)
                or np.any(power < 0) or np.any(rate < 0)):
            raise TectonicsError('regional source audit has incompatible local volume fields')
        external = audit.array('external_heat_source_w_m3')
        internal = audit.array('material_heat_source_w_m3')
        viscous = audit.array('viscous_heat_source_w_m3')
        total = audit.array('total_heat_source_w_m3')
        requested = audit.array('requested_source_energy_j')
        old = audit.array('enthalpy_before_sources_j')
        heated = audit.array('enthalpy_after_sources_j')
        if any(a.shape != cells for a in (external, internal, viscous, total, requested, old, heated)):
            raise TectonicsError('regional source fields are not on the declared cell support')
        # These are identities in the same arithmetic order as the source step,
        # not new tolerances or another calculation of constitutive heating.
        if (not np.array_equal(old, parent_state.array('enthalpy_j'))
                or not np.array_equal(viscous, np.sum(power*weights, axis=1).reshape(cells))
                or not np.array_equal(total, external+internal+viscous)
                or not np.array_equal(requested, total*volume*dt)
                or not np.array_equal(heated, old+requested)):
            raise TectonicsError('regional source audit does not reproduce the booked source arithmetic')
        gradient = advance.initial_mechanics.array('velocity_gradient_s_inv')
        if gradient.shape != (n, 27, 3, 3):
            raise TectonicsError('regional deformation is not on the source quadrature support')
        arrays = {'audit:'+name: audit.array(name) for name in audit.array_names}
        arrays.update(component_mass_before_sources_kg=before, component_mass_after_interval_kg=after,
                      velocity_gradient_s_inv=gradient,
                      strain_increment_ii=rate*dt, plastic_kappa_increment=np.zeros_like(rate))
        plastic_account = None
        if radial:
            if source.get('constitutive_result_id') != meta['initial_constitutive'].get('constitutive_result_id'):
                raise TectonicsError('plastic source audit belongs to another constitutive solution')
            plastic_rate = audit.array('plastic_kappa_rate_s_1')
            before_plastic = audit.array('plastic_history_before_kg')
            after_plastic = audit.array('plastic_history_after_sources_kg')
            if (plastic_rate.shape != (n, 27) or np.any(plastic_rate < 0) or
                    before_plastic.shape != cells or after_plastic.shape != cells):
                raise TectonicsError('plastic source audit has incompatible local support')
            mass = np.sum(before, axis=0)
            requested_plastic = mass*np.sum(plastic_rate*weights, axis=1).reshape(cells)*dt
            if (not np.array_equal(before_plastic, parent_state.array('tracer:radial_plastic_kappa')) or
                    not np.array_equal(after_plastic, before_plastic+requested_plastic)):
                raise TectonicsError('plastic source audit does not reproduce the actual booked tracer update')
            arrays['plastic_kappa_increment'] = plastic_rate*dt
            change = _total(after_plastic)-_total(before_plastic)
            plastic_account = dict(source_plastic_kappa_mass_change_kg=_exact(change),
                requested_plastic_kappa_mass_kg=_exact(_total(requested_plastic)),
                source_addition_roundoff_kg=_exact(change-_total(requested_plastic)))
        if any(not np.isfinite(value).all() for value in arrays.values()):
            raise TectonicsError('regional exchange fields must be finite')
        transported = advance.transport.array('enthalpy_j')
        endpoint = advance.state.array('enthalpy_j')
        source_change = _total(heated)-_total(old)
        account = dict(source_enthalpy_change_j=_exact(source_change),
                       requested_source_energy_j=_exact(_total(requested)),
                       source_addition_roundoff_j=_exact(source_change-_total(requested)),
                       transport_enthalpy_change_j=_exact(_total(transported)-_total(heated)),
                       conduction_enthalpy_change_j=_exact(_total(endpoint)-_total(transported)),
                       endpoint_enthalpy_change_j=_exact(_total(endpoint)-_total(old)))
        descriptor = dict(schema=SCHEMA, layout=definition, layout_id=layout_id,
            parent_state_id=parent_state.result_id, state_id=advance.state.result_id,
            initial_mechanics_id=advance.initial_mechanics.result_id,
            endpoint_mechanics_id=advance.mechanics.result_id, source_audit_id=audit.result_id,
            transport_id=advance.transport.result_id, heat_id=advance.heat.result_id,
            start_time_s=source['start_time_s'], duration_s=dt,
            heat_rule='already booked once by regional evolution; this exchange is read-only',
            plastic_history=('separate radial_plastic_kappa sourced by 2*plastic invariant rate, then transported'
                if radial else 'admitted Newtonian law: plastic kappa increment exactly zero'),
            deformation='local source-time symgrad invariant; not plate Euler rotation',
            ownership='component index labels material; component cell masses carry its evolving position',
            heat_ownership='donor cells before transport; no exterior drag or boundary/conduction heat in viscous source',
            thermal_scope='shared-cell enthalpy after transport/conduction; no per-component temperature claim',
            exact_binary_enthalpy_accounts=account, declared_work_bytes=required,
            scientific_acceptance=False)
        if radial:
            descriptor['exact_binary_plastic_accounts'] = plastic_account
        return RegionalMechanicalSnapshot(descriptor, arrays)


def restore_exchange(record, arrays, *, layout, expected_result_id, budget=None):
    """Restore a saved exchange only on its identical ordered owner layout."""
    definition, layout_id = _layout(layout, budget)
    if (type(record) is not dict or record.get('schema') != SCHEMA
            or record.get('layout_id') != layout_id or record.get('layout') != definition):
        raise TectonicsError('saved regional exchange has another owner layout')
    if type(arrays) is not dict or not arrays:
        raise TectonicsError('saved regional exchange arrays are required')
    values = {k: np.asarray(v) for k, v in arrays.items()}
    if any(a.dtype != np.float64 or not np.isfinite(a).all() for a in values.values()):
        raise TectonicsError('saved regional exchange requires finite binary64 arrays')
    required = 65536+4*(sum(a.nbytes for a in values.values())+len(_json(record)))
    with select_budget(budget).reserve(required, category='regional-local-exchange-restore'):
        restored = RegionalMechanicalSnapshot(record, values)
        if restored.result_id != expected_result_id:
            raise TectonicsError('saved regional exchange identity does not reproduce')
        return restored
