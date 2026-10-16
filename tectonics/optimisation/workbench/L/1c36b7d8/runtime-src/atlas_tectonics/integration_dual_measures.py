"""Separate geometric measure G from conservative material quadrature B.

G obeys the certified geometric conservation law. B is an extensive field
advanced once by that same positive operator, alongside mass and enthalpy.
These are caller-declared numerical admission limits, not physical defaults.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import nullcontext
from fractions import Fraction as Q
import hashlib
import json

from ._validation import TectonicsError
from .integration_mimetic_heat import _enc, _q
from .integration_regional_inventory import _width
from .resources import WorkBudget
from .integration_spatial_transport import (_json_encoding_capacity, _integer_storage,
    _hex_pair_bits, _exact_bits, _rational_storage, _rational_encoding_storage,
    _difference_bits, _sum_profile_bits, _add_profile, _workspace)

B_NAME = 'material_quadrature_m3'
_LIMITS = ('initial_relative_error', 'max_initial_width_m3',
           'max_relative_material_error', 'max_l1_material_error_m3',
           'max_relative_rebase', 'max_l1_rebase_m3')


def policy_record(policy):
    if type(policy) is not dict or set(policy) != set(_LIMITS):
        raise TectonicsError('all explicit dual-measure admission limits required')
    values = {k: Q(v) if type(v) in (int, Q) else _q(v) for k, v in policy.items()}
    if any(v < 0 for v in values.values()) or values['initial_relative_error'] >= 1:
        raise TectonicsError('invalid dual-measure numerical admission limits')
    return {k: _enc(v) for k, v in values.items()}


def check_discrepancies(values, geometry, *, relative, absolute, label):
    """No cancellation credit, cell deletion or volume floor in this gate."""
    if set(values) != set(geometry):
        raise TectonicsError(label+' requires complete cell coverage')
    total = Q(0)
    for key, error in values.items():
        g = geometry[key]
        if g < 0 or (not g and error) or abs(error) > relative*g:
            raise TectonicsError(label+' exceeds local allowance: '+key)
        total += abs(error)
    if total > absolute:
        raise TectonicsError(label+' exceeds total L1 allowance')
    return total


def check_state_cells(cells, policy):
    geometry = {row['cell_id']: _q(row['volume_m3']) for row in cells}
    if len(geometry) != len(cells):
        raise TectonicsError('duplicate dual-measure cell identity')
    errors = {}
    for row in cells:
        key, fields = row['cell_id'], row['exact']
        b = _q(fields[B_NAME])
        if b < 0 or (not b and any(_q(v) for k, v in fields.items() if k != B_NAME)):
            raise TectonicsError('material quadrature cannot be negative or leave unfunded fields')
        errors[key] = b-geometry[key]
    return check_discrepancies(errors, geometry,
        relative=_q(policy['max_relative_material_error']),
        absolute=_q(policy['max_l1_material_error_m3']), label='carried B minus G')


def _dual_audit_capacity(graph, result, prior_geometry, policy, budget):
    """New B/G maps, per-cell differences and constant-count exact L1 sums.

    Original graph/result/provenance stay caller-owned. Denominator products
    bound the few global accumulators, not every row. Per-cell retained errors
    and emitted rebase encodings use only their own operand widths.
    """
    rows = graph['cells']
    with _workspace(budget, 65536 + 512 * len(rows), 'dual-measure-accounting-scan'):
        size = 65536 + 2048 * len(rows) + 256 * len(policy)
        aggregate = [1, 1, 0]
        largest = 1
        policy_n = policy_d = 1
        for value in policy.values():
            bits = _hex_pair_bits(value)
            policy_n, policy_d = max(policy_n, bits[0]), max(policy_d, bits[1])
            size += _rational_storage(bits)
            _add_profile(aggregate, bits)
        for i, row in enumerate(rows):
            start = _hex_pair_bits(row['start_volume_m3'])
            end = _hex_pair_bits(row['end_volume_m3'])
            def vector_bits(name):
                vector = result[name][B_NAME]
                return _hex_pair_bits(vector[i]) if i < len(vector) else (1, 1)
            before = vector_bits('exact_input_stocks')
            after = vector_bits('exact_stocks')
            residual = vector_bits('exact_projection_accounts')
            prior = _exact_bits(prior_geometry.get(row['cell_id'], 0))
            for bits in (start, end, before, after, residual):
                size += _rational_storage(bits)
            rebase = _difference_bits(start, prior)
            errors = (_difference_bits(before, prior), _difference_bits(before, start),
                      _difference_bits(after, end))
            size += _rational_storage(rebase) + max(map(_rational_storage, errors))
            size += _rational_encoding_storage(prior) + _rational_encoding_storage(rebase)
            for bits in (start, end, before, after, residual, prior):
                _add_profile(aggregate, bits)
                largest = max(largest, sum(bits) + policy_n + policy_d)
            largest = max(largest, sum(rebase), *(sum(v) for v in errors))
        # Zero-material funding checks decode one other field at a time.
        for name in ('exact_input_stocks', 'exact_stocks'):
            for vector in result[name].values():
                for value in vector:
                    largest = max(largest, sum(_hex_pair_bits(value)))
        sums = _sum_profile_bits(aggregate)
        largest = max(largest, sum(sums) + policy_n + policy_d)
        # Simultaneous L1 results, running sums, cross-products/GCDs and exact
        # comparisons; hexadecimal output is funded separately from integers.
        size += 32 * _rational_storage(sums) + 8 * _rational_encoding_storage(sums)
        return size + 64 * _integer_storage(2 * largest + 32)


def transport_audit(graph, result, prior_geometry, policy, *, budget):
    """Audit the actual complete physical+finite solve, never a second solve."""
    if type(budget) is not WorkBudget:
        raise TectonicsError('shared dual-measure audit budget required')
    encoded_bytes, encoding_scratch = _json_encoding_capacity(graph, budget)
    with _workspace(budget, _dual_audit_capacity(graph, result, prior_geometry, policy, budget),
                    'dual-measure-audit'):
        return _transport_audit(graph, result, prior_geometry, policy,
            _encoding_scope=_workspace(budget, encoded_bytes+encoding_scratch, 'dual-measure-graph-encoding'))


def _transport_audit(graph, result, prior_geometry, policy, *, _encoding_scope=None):
    rows = graph['cells']
    keys = [r['cell_id'] for r in rows]
    with nullcontext() if _encoding_scope is None else _encoding_scope:
        geometry_id = hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if keys != result['cell_ids'] or set(prior_geometry) != set(keys) or result['geometry_id'] != geometry_id:
        raise TectonicsError('dual-measure audit requires the actual complete ordered graph')
    starts = {r['cell_id']: _q(r['start_volume_m3']) for r in rows}
    ends = {r['cell_id']: _q(r['end_volume_m3']) for r in rows}
    before = dict(zip(keys, map(_q, result['exact_input_stocks'][B_NAME])))
    after = dict(zip(keys, map(_q, result['exact_stocks'][B_NAME])))
    residual = dict(zip(keys, map(_q, result['exact_projection_accounts'][B_NAME])))
    if any(len(result[k][B_NAME]) != len(keys) for k in
           ('exact_input_stocks', 'exact_stocks', 'exact_projection_accounts')):
        raise TectonicsError('incomplete material quadrature vectors')
    for name, values in (('input', before), ('output', after)):
        fields = result['exact_input_stocks' if name == 'input' else 'exact_stocks']
        for i, key in enumerate(keys):
            if values[key] < 0 or (not values[key] and
                    any(_q(v[i]) for k, v in fields.items() if k != B_NAME)):
                raise TectonicsError('unfunded '+name+' material quadrature')
    relative = _q(policy['max_relative_material_error'])
    absolute = _q(policy['max_l1_material_error_m3'])
    old_l1 = check_discrepancies({k: before[k]-prior_geometry[k] for k in keys}, prior_geometry,
        relative=relative, absolute=absolute, label='prior B minus G')
    rebase = {k: starts[k]-prior_geometry[k] for k in keys}
    rebase_l1 = check_discrepancies(rebase, starts,
        relative=_q(policy['max_relative_rebase']), absolute=_q(policy['max_l1_rebase_m3']),
        label='geometric rebase')
    input_l1 = check_discrepancies({k: before[k]-starts[k] for k in keys}, starts,
        relative=relative, absolute=absolute, label='input B minus G')
    end_l1 = check_discrepancies({k: after[k]-ends[k] for k in keys}, ends,
        relative=relative, absolute=absolute, label='output B minus G')
    numerical_l1 = sum(map(abs, residual.values()), Q(0))
    if sum(before.values()) != sum(after.values())+sum(residual.values()):
        raise TectonicsError('material quadrature conservation account does not close')
    if end_l1 > input_l1+numerical_l1:
        raise TectonicsError('positive transport quadrature L1 contraction failed')
    return dict(schema='atlas.dual-measure-transport-audit.v1',
        geometry_id=result['geometry_id'], transport_id=result['result_id'],
        prior_geometry_m3={k: _enc(v) for k, v in prior_geometry.items()},
        geometric_rebase_m3={k: _enc(v) for k, v in rebase.items()},
        prior_l1_m3=_enc(old_l1), rebase_l1_m3=_enc(rebase_l1), input_l1_m3=_enc(input_l1),
        end_l1_m3=_enc(end_l1), numerical_l1_m3=_enc(numerical_l1),
        convention='G is geometry; B is material quadrature; q/G is physical density; q/B is a bookkeeping ratio')
