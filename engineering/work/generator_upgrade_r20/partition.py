"""Bounded connected graph multicut; no political identities or spatial seeds.

The integer objective is read back exactly. HiGHS supplies the floating MILP
lower-bound certificate: we require its integer ceiling to equal that exact
cost, with no tolerance for binary variables, constraints or objective values.
This is a bounded MILP reference, not an arbitrary-precision solver/world run.
"""
from collections import deque
import hashlib
import json
import math
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


SCHEMA = 'diadem.connected-physical-multicut.r20'
MAX_UNITS, MAX_EDGES, MAX_FACTS, MAX_ROWS = 256, 2048, 4096, 65536
MAX_TOTAL_QUANTA = 2**40


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _identity(value):
    if type(value) is not str or not value.strip() or len(value) > 1024:
        raise ValueError('bounded nonblank unit identity required')
    return value


def _positive_int(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(name+' requires a positive integer, not a boolean')
    return value


def _read(problem):
    if type(problem) is not dict or set(problem) != {
            'unit_ids', 'edges', 'must_join', 'must_cut', 'limits'}:
        raise ValueError('exact multicut problem fields required')
    units = problem['unit_ids']
    if type(units) is not list or not 1 <= len(units) <= MAX_UNITS:
        raise ValueError('reference limit: 1..256 explicit units')
    units = sorted(_identity(unit) for unit in units)
    if len(set(units)) != len(units):
        raise ValueError('duplicate unit identity')
    index = {unit: i for i, unit in enumerate(units)}

    def pair(value):
        if type(value) not in (list, tuple) or len(value) != 2:
            raise ValueError('explicit two-unit hard fact required')
        left, right = (_identity(item) for item in value)
        if left not in index or right not in index or left == right:
            raise ValueError('distinct existing endpoints required')
        return tuple(sorted((index[left], index[right])))

    raw = problem['edges']
    if type(raw) is not list or len(raw) > MAX_EDGES:
        raise ValueError('reference limit: at most 2048 physical edges')
    edges, seen, total = [], set(), 0
    for edge in raw:
        if type(edge) is not dict or set(edge) != {
                'left', 'right', 'length_m', 'separation_u', 'continuity_u'}:
            raise ValueError('exact physical edge fields required')
        endpoints = pair((edge['left'], edge['right']))
        if endpoints in seen:
            raise ValueError('duplicate undirected physical edge; aggregate evidence explicitly')
        seen.add(endpoints)
        length = edge['length_m']
        if type(length) not in (int, float):
            raise ValueError('positive finite physical edge length required')
        try:
            length = float(length)
        except OverflowError as exc:
            raise ValueError('physical edge length exceeds binary64') from exc
        if not math.isfinite(length) or length <= 0:
            raise ValueError('point/zero/nonfinite contact is not physical adjacency')
        for key in ('separation_u', 'continuity_u'):
            if type(edge[key]) is not int or edge[key] < 0:
                raise ValueError('evidence quanta must be nonnegative integers, never implicit weights')
            total += edge[key]
        if total > MAX_TOTAL_QUANTA:
            raise ValueError('reference integer objective exceeds 2**40 total evidence quanta')
        edges.append((endpoints[0], endpoints[1], length,
                      edge['separation_u'], edge['continuity_u']))
    edges.sort()
    facts = {}
    for name in ('must_join', 'must_cut'):
        values = problem[name]
        if type(values) is not list or len(values) > MAX_FACTS:
            raise ValueError('bounded explicit hard-fact list required')
        values = [pair(value) for value in values]
        if len(set(values)) != len(values):
            raise ValueError('duplicate undirected hard fact')
        facts[name] = sorted(values)
    limits = problem['limits']
    if type(limits) is not dict or set(limits) != {'max_cut_rounds', 'node_limit', 'time_limit_s'}:
        raise ValueError('all three global solver limits are required')
    rounds = _positive_int(limits['max_cut_rounds'], 'max_cut_rounds')
    nodes = _positive_int(limits['node_limit'], 'node_limit')
    seconds = limits['time_limit_s']
    if type(seconds) not in (int, float) or not 0 < seconds <= 86400:
        raise ValueError('time_limit_s must be finite positive and at most one day')
    seconds = float(seconds)
    return units, edges, facts, {'max_cut_rounds': rounds,
        'node_limit': nodes, 'time_limit_s': seconds}


def _graph(n, edges, bits=None):
    graph = [[] for _ in range(n)]
    for e, row in enumerate(edges):
        if bits is None or bits[e] == 0:
            left, right = row[:2]
            graph[left].append((right, e)); graph[right].append((left, e))
    for neighbours in graph:
        neighbours.sort()
    return graph


def _components(graph):
    labels, blocks = [-1]*len(graph), []
    for first in range(len(graph)):
        if labels[first] >= 0:
            continue
        label, pending, block = len(blocks), [first], []
        labels[first] = label
        while pending:
            unit = pending.pop(); block.append(unit)
            for other, _ in graph[unit]:
                if labels[other] < 0:
                    labels[other] = label; pending.append(other)
        blocks.append(sorted(block))
    return labels, blocks


def _path(graph, first, last):
    previous, pending = {first: None}, deque([first])
    while pending:
        unit = pending.popleft()
        if unit == last:
            result = []
            while previous[unit] is not None:
                unit, edge = previous[unit]; result.append(edge)
            return result
        for other, edge in graph[unit]:
            if other not in previous:
                previous[other] = (unit, edge); pending.append(other)
    return None


def _partition(units, edges, bits):
    _, blocks = _components(_graph(len(units), edges, bits))
    groups = [{'id': 'r20-group-'+_sha([units[i] for i in block]),
               'members': [units[i] for i in block]} for block in blocks]
    return {'groups': groups,
        'memberships': {unit: row['id'] for row in groups for unit in row['members']},
        'cut_edges': [[units[row[0]], units[row[1]]]
                      for row, bit in zip(edges, bits) if bit]}


def solve(problem):
    """Return {solution, diagnostics}; only certified unique optima are PASS.

All MILP calls (including uniqueness), nodes, cut rounds and elapsed time share
one budget. A limit/numerical failure publishes no usable partial membership.
Alternative witnesses are not an exhaustive enumeration of every optimum.
"""
    started = time.perf_counter()
    units, edges, facts, limits = _read(problem)
    n, m = len(units), len(edges)
    baseline = sum(row[3] for row in edges)
    costs = [row[4]-row[3] for row in edges]
    rows, row_set, cut_counts, calls = [], set(), {}, []
    nodes_charged = cut_rounds = 0
    physical_labels, physical_blocks = _components(_graph(n, edges))
    envelope = {'unit_ids': units,
        'physical_components': [[units[i] for i in block] for block in physical_blocks],
        'must_join': [[units[a], units[b]] for a, b in facts['must_join']],
        'must_cut': [[units[a], units[b]] for a, b in facts['must_cut']],
        'complete_unit_coverage': True, 'is_candidate_partition': False,
        'meaning': 'DIAGNOSTIC_SUPPORT_ENVELOPE_ONLY; NOT_AN_OPTIMUM_OR_PREFERRED_MEMBERSHIP'}

    def finish(status, reason, **values):
        elapsed = time.perf_counter()-started
        if status in ('PASS', 'POLYCENTRIC_UNRESOLVED') and elapsed > limits['time_limit_s']:
            status, reason, values = 'INCOMPLETE', 'global time budget expired before final readback', {}
        solution = {'schema': SCHEMA, 'status': status, 'reason': reason,
                    'diagnostic_envelope': envelope, **values}
        return {'solution': solution, 'diagnostics': {
            'limits': dict(limits), 'elapsed_s': elapsed,
            'solver_calls': calls, 'nodes_charged': nodes_charged,
            'cut_rounds': cut_rounds, 'cut_counts': dict(cut_counts),
            'constraint_count': len(rows), 'constraints_sha256': _sha(rows),
            'precision': 'BINARY64_HIGHS_BOUND; EXACT_BINARY_INTEGER_COST_AND_CONSTRAINT_READBACK; ZERO_ACCEPTANCE_TOLERANCE',
            'presolve': False,
            'presolve_reason': 'BUNDLED_HIGHS_PREPROCESSOR_RETURNED_A_CANDIDATE_VIOLATING_EXACT_OPTIMUM_EXCLUSION',
            'reference_limits': {'units': MAX_UNITS, 'edges': MAX_EDGES,
                                 'constraint_rows': MAX_ROWS, 'total_evidence_quanta': MAX_TOTAL_QUANTA}}}

    def add(coefficients, lower, upper, kind):
        coefficients = tuple(sorted((i, int(value)) for i, value in coefficients.items() if value))
        row = (coefficients, lower, upper)
        if row in row_set:
            return False
        if len(rows) >= MAX_ROWS:
            raise RuntimeError('reference lazy-constraint row budget exhausted')
        rows.append(row); row_set.add(row)
        cut_counts[kind] = cut_counts.get(kind, 0)+1
        return True

    for left, right in facts['must_join']:
        if physical_labels[left] != physical_labels[right]:
            return finish('FAILED', 'must_join has no physical path')
    if set(facts['must_join']) & set(facts['must_cut']):
        return finish('FAILED', 'the same pair is both must_join and must_cut')
    if not m:
        partition = _partition(units, edges, [])
        return finish('PASS', 'unique edgeless connected partition', **partition,
            objective_u=0, objective_bound_u=0,
            optimum_certificate='ANALYTIC_EDGELESS_GRAPH', uniqueness_certificate='ONLY_ONE_EDGE_PATTERN')
    lower, upper = [0]*m, [1]*m
    edge_index = {(row[0], row[1]): i for i, row in enumerate(edges)}
    for kind, bound in (('must_join', 0), ('must_cut', 1)):
        for pair in facts[kind]:
            if pair in edge_index:
                lower[edge_index[pair]] = upper[edge_index[pair]] = bound

    def violations(bits):
        graph = _graph(n, edges, bits)
        labels, _ = _components(graph)
        result = []
        for e, (left, right, *_rest) in enumerate(edges):
            if bits[e] and labels[left] == labels[right]:
                coefficients = {i: -1 for i in _path(graph, left, right)}
                coefficients[e] = 1
                result.append((coefficients, None, 0, 'cycle'))
        for left, right in facts['must_join']:
            if labels[left] != labels[right]:
                boundary = {e: 1 for e, row in enumerate(edges)
                    if (labels[row[0]] == labels[left]) != (labels[row[1]] == labels[left])}
                result.append((boundary, None, len(boundary)-1, 'must_join_boundary'))
        for left, right in facts['must_cut']:
            if labels[left] == labels[right]:
                result.append(({i: 1 for i in _path(graph, left, right)}, 1, None, 'must_cut_path'))
        return result

    phase, first_bits, optimum = 'optimum', None, None
    while True:
        remaining_s = limits['time_limit_s']-(time.perf_counter()-started)
        remaining_nodes = limits['node_limit']-nodes_charged
        if remaining_s <= 0 or remaining_nodes <= 0:
            return finish('INCOMPLETE', 'global solver time/node budget exhausted')
        if len(calls) >= limits['max_cut_rounds']+2:
            return finish('INCOMPLETE', 'global solver call budget exhausted')
        ri, ci, values, lo, hi = [], [], [], [], []
        for r, (coefficients, lb, ub) in enumerate(rows):
            for c, value in coefficients:
                ri.append(r); ci.append(c); values.append(float(value))
            lo.append(-np.inf if lb is None else lb)
            hi.append(np.inf if ub is None else ub)
        constraints = None
        if rows:
            matrix = coo_matrix((values, (ri, ci)), shape=(len(rows), m)).tocsc()
            constraints = LinearConstraint(matrix, np.asarray(lo), np.asarray(hi))
        # Account for Python-side sparse assembly before passing the remaining deadline.
        remaining_s = limits['time_limit_s']-(time.perf_counter()-started)
        if remaining_s <= 0:
            return finish('INCOMPLETE', 'global time budget exhausted assembling constraints')
        call_started = time.perf_counter()
        try:
            result = milp(np.asarray(costs, dtype=float), integrality=np.ones(m, dtype=np.uint8),
                bounds=Bounds(lower, upper), constraints=constraints,
                options={'node_limit': remaining_nodes, 'time_limit': remaining_s,
                         # Retain original rows: this bundled preprocessor was
                         # observed dropping the exact optimum-exclusion row.
                         'mip_rel_gap': 0.0, 'presolve': False, 'disp': False})
        except Exception as exc:
            calls.append({'phase': phase, 'error': type(exc).__name__+': '+str(exc),
                          'elapsed_s': time.perf_counter()-call_started})
            return finish('INCOMPLETE', 'solver invocation did not produce a certificate')
        raw_nodes = result.get('mip_node_count')
        # Missing accounting consumes the entire allocated allowance, never zero.
        charged = remaining_nodes if raw_nodes is None else int(raw_nodes)
        if charged < 0 or (raw_nodes is not None and charged != raw_nodes):
            return finish('INCOMPLETE', 'solver node accounting is invalid')
        nodes_charged += charged
        dual, objective = result.get('mip_dual_bound'), result.get('fun')
        calls.append({'phase': phase, 'status': int(result.status), 'message': str(result.message),
            'elapsed_s': time.perf_counter()-call_started, 'node_allowance': remaining_nodes,
            'reported_nodes': None if raw_nodes is None else int(raw_nodes), 'charged_nodes': charged,
            'linear_objective': float(objective) if objective is not None and math.isfinite(objective) else None,
            'linear_dual_bound': float(dual) if dual is not None and math.isfinite(dual) else None})
        if nodes_charged > limits['node_limit'] or time.perf_counter()-started > limits['time_limit_s']:
            return finish('INCOMPLETE', 'global resource budget exceeded before certificate completion')
        if result.status == 1:
            return finish('INCOMPLETE', 'solver reported a resource limit')
        if result.status == 2:
            if phase == 'optimum':
                return finish('FAILED', 'hard connected-partition constraints are infeasible')
            partition = _partition(units, edges, first_bits)
            return finish('PASS', 'one certified optimum edge pattern', **partition,
                objective_u=optimum, objective_bound_u=optimum,
                optimum_certificate='HIGHS_INTEGER_LOWER_BOUND_WITH_EXACT_READBACK',
                uniqueness_certificate='FIXED_OPTIMUM_EXCLUDED_PATTERN_INFEASIBLE')
        if result.status != 0:
            return finish('INCOMPLETE', 'solver did not certify optimality or infeasibility')
        vector = result.get('x')
        if vector is None or len(vector) != m or any(value not in (0.0, 1.0) for value in vector):
            return finish('INCOMPLETE', 'solver vector is not exactly binary; no rounding accepted')
        bits = [int(value) for value in vector]
        if any(not lower[i] <= bit <= upper[i] for i, bit in enumerate(bits)):
            return finish('INCOMPLETE', 'exact direct-edge bound readback failed')
        for coefficients, lb, ub in rows:
            value = sum(coefficient*bits[i] for i, coefficient in coefficients)
            if (lb is not None and value < lb) or (ub is not None and value > ub):
                return finish('INCOMPLETE', 'exact integer constraint readback failed')
        linear = sum(cost*bit for cost, bit in zip(costs, bits))
        cost = sum(row[4] if bit else row[3] for row, bit in zip(edges, bits))
        if cost != baseline+linear or objective != linear:
            return finish('INCOMPLETE', 'exact integer objective readback failed')
        if dual is None or not math.isfinite(dual) or dual > linear or math.ceil(dual) != linear:
            return finish('INCOMPLETE', 'integer objective lower bound does not certify exact readback')
        calls[-1]['certified_integer_bound_u'] = baseline+math.ceil(dual)
        invalid = violations(bits)
        if invalid:
            if cut_rounds >= limits['max_cut_rounds']:
                return finish('INCOMPLETE', 'global lazy-cut round budget exhausted')
            try:
                added = sum(add(*row) for row in invalid)
            except RuntimeError as exc:
                return finish('INCOMPLETE', str(exc))
            if not added:
                return finish('INCOMPLETE', 'violating candidate produced no new valid constraint')
            cut_rounds += 1
            continue
        if phase == 'optimum':
            first_bits, optimum = bits, cost
            try:
                add({i: value for i, value in enumerate(costs)}, linear, linear, 'fixed_optimum')
                add({i: -1 if bit else 1 for i, bit in enumerate(bits)},
                    1-sum(bits), None, 'exclude_first_pattern')
            except RuntimeError as exc:
                return finish('INCOMPLETE', str(exc))
            phase = 'alternative'
            continue
        if cost != optimum or bits == first_bits:
            return finish('INCOMPLETE', 'alternative optimum exact readback failed')
        alternatives = [_partition(units, edges, value) for value in sorted((first_bits, bits))]
        return finish('POLYCENTRIC_UNRESOLVED', 'at least two distinct certified optimum partitions',
            objective_u=optimum, objective_bound_u=optimum, alternatives=alternatives,
            alternatives_exhaustive=False, preferred_partition=None,
            optimum_certificate='HIGHS_INTEGER_LOWER_BOUND_WITH_EXACT_READBACK',
            ambiguity_certificate='TWO_DISTINCT_FEASIBLE_EDGE_PATTERNS_AT_CERTIFIED_OPTIMUM')
