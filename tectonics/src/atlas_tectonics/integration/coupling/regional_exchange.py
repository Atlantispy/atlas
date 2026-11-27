"""Local, read-only deformation/heat exchange of a persistent regional owner.

SPDX-License-Identifier: AGPL-3.0-only

This is not the piece-mean I04 P6/P7 representation. It consumes the source
audit of the existing evolution step, never solves mechanics or books heat.
"""
from fractions import Fraction
import hashlib
import math
from typing import cast

import numpy as np

from atlas_tectonics._validation import TectonicsError, scalar
from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
from atlas_tectonics.integration.resources import select_budget
from atlas_tectonics.integration.resources import canonical_json as _json

SCHEMA = 'atlas.regional-owner-exchange.v1'
LAYOUT_SCHEMA = 'atlas.regional-owner-layout.v1'


def _name(value):
    return value


def _layout(layout, budget=None):
    keys = {'schema', 'region_id', 'cells', 'lengths_m', 'plate_ids', 'components',
            'native_plan_id', 'transfer_id'}
    registered = type(layout) is dict and layout.get('schema') == 'atlas.regional-owner-layout.v2'
    if registered:
        keys.add('component_registry')
        if 'initial_source_plate_ids' in layout:
            keys.add('initial_source_plate_ids')
    cells = tuple(layout['cells'])
    lengths = tuple(scalar(v, 'regional length', positive=True) for v in layout['lengths_m'])
    plates = tuple(v for v in layout['plate_ids'])
    given = layout['components']
    if type(given) not in (list, tuple) or not 1 <= len(given) <= (256 if registered else 16):
        raise TectonicsError('regional layout requires one to sixteen material components')
    if registered:
        from atlas_tectonics.integration.coupling.regional_inventory import ComponentRegistry
        registry = ComponentRegistry.from_record(layout['component_registry'], budget=select_budget(budget))
        source_plates = registry.initial_source_plate_ids
        plain = dict(schema='atlas.regional-owner-layout.v2', region_id=layout['region_id'], cells=list(cells),
                     lengths_m=list(lengths), plate_ids=list(plates), components=registry.layout_components(),
                     native_plan_id=layout['native_plan_id'], transfer_id=layout['transfer_id'],
                     component_registry=registry.record())
        if source_plates:
            plain['initial_source_plate_ids'] = list(source_plates)
        return plain, hashlib.sha256(_json(plain)).hexdigest()
    components = []
    for item in given:
        if type(item['sublayer']) is not int or item['sublayer'] < 0:
            raise TectonicsError('material sublayer is a nonnegative index')
        component = dict(patch_id=item['patch_id'], sublayer=item['sublayer'],
                         plate_id=item['plate_id'])
        components.append(component)
    plain = dict(schema=LAYOUT_SCHEMA, region_id=layout['region_id'], cells=list(cells),
                 lengths_m=list(lengths), plate_ids=list(plates), components=components,
                 native_plan_id=layout['native_plan_id'], transfer_id=layout['transfer_id'])
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
    audit = advance.source_audit
    meta, source = advance.descriptor(), audit.descriptor()
    radial = source.get('rheology_family') == 'radial-3d-creep-plastic'
    dt = scalar(meta.get('duration_s'), 'interval duration', positive=True)
    cells, components = tuple(definition['cells']), len(definition['components'])
    n = math.prod(cells)
    # Immutable output/copy allowance is separate from the solver's own budget.
    required = 65536+4*(audit.nbytes+8*n*(2*components+27*14+12)+len(_json(definition)))
    with select_budget(budget).reserve(required, category='regional-local-exchange'):
        before = parent_state.array('component_mass_kg')
        after = advance.state.array('component_mass_kg')
        _, rate = audit.array('viscous_dissipation_w_m3'), audit.array('strain_rate_ii_s_inv')
        weights = audit.array('quadrature_fraction')
        requested = audit.array('requested_source_energy_j')
        old = audit.array('enthalpy_before_sources_j')
        heated = audit.array('enthalpy_after_sources_j')
        gradient = advance.initial_mechanics.array('velocity_gradient_s_inv')
        arrays = {'audit:'+name: audit.array(name) for name in audit.array_names}
        arrays.update(component_mass_before_sources_kg=before, component_mass_after_interval_kg=after,
                      velocity_gradient_s_inv=gradient,
                      strain_increment_ii=rate*dt, plastic_kappa_increment=np.zeros_like(rate))
        plastic_account = None
        if radial:
            plastic_rate = audit.array('plastic_kappa_rate_s_1')
            before_plastic = audit.array('plastic_history_before_kg')
            after_plastic = audit.array('plastic_history_after_sources_kg')
            mass = np.sum(before, axis=0)
            requested_plastic = mass*np.sum(plastic_rate*weights, axis=1).reshape(cells)*dt
            arrays['plastic_kappa_increment'] = plastic_rate*dt
            change = _total(after_plastic)-_total(before_plastic)
            plastic_account = dict(source_plastic_kappa_mass_change_kg=_exact(change),
                requested_plastic_kappa_mass_kg=_exact(_total(requested_plastic)),
                source_addition_roundoff_kg=_exact(change-_total(requested_plastic)))
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
            descriptor['exact_binary_plastic_accounts'] = cast('dict[str, str]', plastic_account)
        return RegionalMechanicalSnapshot(descriptor, arrays)


def restore_exchange(record, arrays, *, layout, expected_result_id, budget=None):
    """Restore a saved exchange only on its identical ordered owner layout."""
    definition, layout_id = _layout(layout, budget)
    values = {k: np.asarray(v) for k, v in arrays.items()}
    required = 65536+4*(sum(a.nbytes for a in values.values())+len(_json(record)))
    with select_budget(budget).reserve(required, category='regional-local-exchange-restore'):
        restored = RegionalMechanicalSnapshot(record, values)
        return restored
