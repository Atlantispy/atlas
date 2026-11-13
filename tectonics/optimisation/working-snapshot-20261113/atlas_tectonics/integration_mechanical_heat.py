"""Exact material-labelled observation of already-booked regional heat.

No spherical patch is heated here. A source patch labels material ancestry;
the current native cell, not that patch's old position, owns this heat source.
SPDX-License-Identifier: AGPL-3.0-only
"""
from dataclasses import dataclass
from fractions import Fraction as Q
import hashlib
import json
import math

import numpy as np

from ._validation import TectonicsError
from .integration_regional_evolution import PreparedRegionalOwner, RegionalOwnerAdvance
from .resources import select_budget

SCHEMA = 'atlas.material-owned-mechanical-heat.v1'
ENERGIES = ('creep_j', 'plastic_j', 'constitutive_partition_j', 'quadrature_roundoff_j',
            'nonmechanical_j', 'source_sum_roundoff_j', 'enthalpy_addition_roundoff_j',
            'mechanical_source_integral_j', 'source_enthalpy_change_j')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _q(value):
    return Q(float(value))


def _encoded(value):
    return [hex(value.numerator), hex(value.denominator)]


def _width(value):
    q = _q(value)
    return abs(q.numerator).bit_length()+q.denominator.bit_length()


def _sum(values):
    return sum((_q(v) for v in values), Q(0))


@dataclass(frozen=True, slots=True, init=False)
class MechanicalHeatSources:
    _record: bytes
    receipt_id: str

    def descriptor(self):
        return json.loads(self._record)

    def rows(self):
        """Detached exact account rows; no aggregate spatial redeposition API."""
        rows = self.descriptor()['rows']
        for row in rows:
            for key in (*ENERGIES, 'donor_mass_kg', 'cell_mass_fraction'):
                row[key] = Q(*(int(v, 16) for v in row[key]))
        return rows


def mechanical_heat_sources(owner, parent_state, advance, *, budget=None):
    """Attribute one actual donor-time source to its current material owners.

    The supported native caloric model has one rho/Cp and shared cell T. Its
    admitted law is common to components. Consequently each component receives
    the same specific heat increment, and its extensive share is m_i/sum(m).
    This is an account of that declared local model, not a new homogenisation,
    post-advection allocation, or claim of separate component temperatures.
    """
    if type(owner) is not PreparedRegionalOwner or type(advance) is not RegionalOwnerAdvance:
        raise TectonicsError('actual prepared regional owner and its advance required')
    owner._verify(); owner._bound(parent_state); owner._bound(advance.state)
    old = parent_state.descriptor()['metadata']; new = advance.state.descriptor()['metadata']
    native, exchange = advance.native_advance, advance.exchange
    if (new['parent_owner_state_id'] != parent_state.owner_state_id or
            new['intervals'] != old['intervals']+1 or
            advance.state.native_state.result_id != native.state.result_id or
            advance.state.exchange.result_id != exchange.result_id):
        raise TectonicsError('heat ownership must follow the actual owner interval')
    audit = native.source_audit
    meta, data = native.descriptor(), audit.descriptor()
    exchanged = exchange.descriptor()
    if (meta['parent_state_id'] != parent_state.native_state.result_id or
            data['parent_state_id'] != parent_state.native_state.result_id or
            data['initial_mechanics_id'] != native.initial_mechanics.result_id or
            meta['source_audit_id'] != audit.result_id or
            exchanged['source_audit_id'] != audit.result_id or
            exchanged['layout'] != owner.layout() or data['include_viscous_heating'] is not True):
        raise TectonicsError('heat source, donor, mechanical snapshot or owner layout is stale')
    if (not np.array_equal(parent_state.native_state.array('component_mass_kg'),
                           exchange.array('component_mass_before_sources_kg')) or
            not np.array_equal(parent_state.native_state.array('enthalpy_j'),
                               exchange.array('audit:enthalpy_before_sources_j'))):
        raise TectonicsError('heat attribution requires actual donor fields before transport')
    return _from_state(owner, advance.state, budget=budget)


def _from_state(owner, state, *, budget=None):
    """The carried exchange suffices for restart; no reconstruction of mechanics."""
    owner._verify(); owner._bound(state)
    exchange = state.exchange
    if exchange is None:
        raise TectonicsError('initial owner state has no interval heat receipt')
    data = exchange.descriptor()
    audit = lambda name: exchange.array('audit:'+name)
    family = owner._native._rheology_family
    if family not in ('constant', 'i01-newtonian-creep', 'radial-3d-creep-plastic'):
        raise TectonicsError('material-owned heat requires the admitted common constitutive law')
    masses = exchange.array('component_mass_before_sources_kg')
    components, cells = masses.shape[0], masses.shape[1:]
    n = math.prod(cells)
    layout = owner.layout()
    if len(layout['components']) != components or list(cells) != layout['cells']:
        raise TectonicsError('current donor cells and named owner components differ')
    power = audit('viscous_dissipation_w_m3')
    creep = audit('creep_dissipation_w_m3') if family == 'radial-3d-creep-plastic' else power
    plastic = audit('plastic_dissipation_w_m3') if family == 'radial-3d-creep-plastic' else power
    weights = audit('quadrature_fraction')
    volume = audit('cell_volume_m3').reshape(n)
    viscous = audit('viscous_heat_source_w_m3').reshape(n)
    external = audit('external_heat_source_w_m3').reshape(n)
    internal = audit('material_heat_source_w_m3').reshape(n)
    requested = audit('requested_source_energy_j').reshape(n)
    before = audit('enthalpy_before_sources_j').reshape(n)
    after = audit('enthalpy_after_sources_j').reshape(n)
    dt = _q(data['duration_s'])
    arrays = (masses, power, creep, plastic, weights, volume, viscous, external, internal, requested, before, after)
    if (power.shape != (n, 27) or creep.shape != power.shape or plastic.shape != power.shape or
            weights.shape != (27,) or any(not np.isfinite(a).all() for a in arrays) or
            any(np.any(a < 0) for a in (masses, power, creep, plastic)) or dt <= 0):
        raise TectonicsError('heat source has unsupported local shapes or negative dissipation')
    if (not np.array_equal(viscous, np.sum(power*weights, axis=1)) or
            not np.array_equal(requested, audit('total_heat_source_w_m3').reshape(n)*volume*float(dt)) or
            not np.array_equal(after, before+requested)):
        raise TectonicsError('heat audit differs from the actual donor source arithmetic')
    resource = owner._budget if budget is None else select_budget(budget)
    # Input views are retained by their immutable snapshots. Exact products are
    # dyadic until the local component-mass division. Bound rational widths by
    # operand bit widths plus addition carries, not a fixed denominator ceiling.
    widths = [max((_width(v) for v in a.flat), default=1) for a in arrays]
    # Aligning dyadic operands with opposite exponent extremes can double the
    # largest width (a huge integer plus a tiny fraction). Include that before
    # the component ratio and residual subtractions; the 64 carry bits cover
    # 27 quadrature terms, <=16 components and <=24^3 cells. Per-cell component
    # sums share one mass denominator; no unrelated cross-cell ratios are added.
    bits = (4*widths[0]+2*(max(widths[1:4])+widths[4]+widths[5]+_width(float(dt)))+
            2*max(widths[6:])+64)
    count = int(np.count_nonzero(masses))
    # Per row: dict/key overhead, eleven rational pairs, JSON bytes and four live
    # copies. Per-cell accounts have the same bound but no component division.
    required = 65536+sum(a.nbytes for a in arrays)+4*(count+n)*(2048+11*(256+(bits+3)//4))
    with resource.reserve(required, category='material-owned-mechanical-heat'):
        rows, cell_accounts = [], []
        flattened = masses.reshape(components, n)
        global_change = global_mechanical = Q(0)
        for cell in range(n):
            total_mass = _sum(flattened[:, cell])
            if total_mass <= 0:
                raise TectonicsError('positive donor mass required for local caloric ownership')
            measure = _q(volume[cell])*dt
            integral = lambda field: sum((_q(p)*_q(w) for p, w in zip(field[cell], weights)), Q(0))*measure
            c, p, ideal = integral(creep), (integral(plastic) if family == 'radial-3d-creep-plastic' else Q(0)), integral(power)
            mechanical = _q(viscous[cell])*measure
            nonmechanical = (_q(external[cell])+_q(internal[cell]))*measure
            asked, change = _q(requested[cell]), _q(after[cell])-_q(before[cell])
            energy = dict(creep_j=c, plastic_j=p, constitutive_partition_j=ideal-c-p,
                quadrature_roundoff_j=mechanical-ideal, nonmechanical_j=nonmechanical,
                source_sum_roundoff_j=asked-mechanical-nonmechanical,
                enthalpy_addition_roundoff_j=change-asked,
                mechanical_source_integral_j=mechanical, source_enthalpy_change_j=change)
            if sum((energy[k] for k in ENERGIES[:7]), Q(0)) != change:
                raise TectonicsError('exact source energy decomposition does not close')
            subtotal = {key: Q(0) for key in ENERGIES}
            for component, declaration in enumerate(layout['components']):
                mass = _q(flattened[component, cell])
                if mass == 0:
                    continue
                fraction = mass/total_mass
                allocated = {key: value*fraction for key, value in energy.items()}
                for key, value in allocated.items():
                    subtotal[key] += value
                rows.append(dict(declaration, cell=cell, component=component,
                    donor_mass_kg=_encoded(mass), cell_mass_fraction=_encoded(fraction),
                    **{key: _encoded(value) for key, value in allocated.items()}))
            if subtotal != energy:
                raise TectonicsError('component heat sources do not close their actual donor cell')
            cell_accounts.append(dict(cell=cell, **{key: _encoded(value) for key, value in energy.items()}))
            global_change += change; global_mechanical += mechanical
        record = dict(schema=SCHEMA, owner_id=owner.owner_id,
            parent_owner_state_id=state.descriptor()['metadata']['parent_owner_state_id'], owner_state_id=state.owner_state_id,
            source=owner.reservation()['source'], layout=layout,
            source_audit_id=data['source_audit_id'], initial_mechanics_id=data['initial_mechanics_id'],
            endpoint_mechanics_id=data['endpoint_mechanics_id'], exchange_id=exchange.result_id,
            start_time_s=data['start_time_s'], duration_s=data['duration_s'],
            rows=rows, cell_accounts=cell_accounts,
            source_enthalpy_change_j=_encoded(global_change), mechanical_source_integral_j=_encoded(global_mechanical),
            position='current donor cell before source transport; patch identity is ancestry, not deposition geometry',
            caloric_model='common rho/Cp/law and shared cell T; exact component mass fraction of the same specific increment',
            heat_rule='already booked exactly once by native evolution; this receipt never deposits heat',
            exclusions='exterior/basal drag, pressure work, exports, conduction and boundary heat are not dissipation sources',
            residuals='constitutive partition, floating quadrature, source summation and enthalpy addition kept separately',
            declared_work_bytes=required)
        encoded = _json(record)
        obj = object.__new__(MechanicalHeatSources)
        object.__setattr__(obj, '_record', encoded)
        object.__setattr__(obj, 'receipt_id', hashlib.sha256(encoded).hexdigest())
        return obj


def restore_heat_sources(record, *, owner, state, expected_receipt_id, budget=None):
    """Reproduce a saved source receipt from actual outputs, without re-solving."""
    if type(owner) is not PreparedRegionalOwner:
        raise TectonicsError('actual prepared regional owner required')
    actual = _from_state(owner, state, budget=budget)
    if actual.receipt_id != expected_receipt_id or record != actual.descriptor():
        raise TectonicsError('saved material heat receipt does not reproduce its actual source/ownership')
    return actual
