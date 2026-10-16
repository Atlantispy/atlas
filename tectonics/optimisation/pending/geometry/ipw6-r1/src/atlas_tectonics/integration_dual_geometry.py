"""Exact dual geometry/material arithmetic for differential physical closure.

These helpers never issue physical bounds, stocks or acceptance. Only the typed
geometry entry point may turn a selected graph into a SpatialALEGraph. Geometric
G, carried material quadrature B and true-minus-G errors remain separate.
SPDX-License-Identifier: AGPL-3.0-only
"""
from copy import deepcopy
from contextlib import ExitStack
from fractions import Fraction as Q
import heapq


def _pair(encoded):
    return Q(int(encoded[0], 16), int(encoded[1], 16))


def _enc(value):
    return [hex(value.numerator), hex(value.denominator)]


def physical_record(record, booked, errors, finite, *, geometric_starts=None,
                    finite_measures=None):
    """Intersect carried true geometry; attach COMPLETE, fixed finite stocks.

    Legacy calls explicitly convert B to the selected-G reference (including
    finite volume_m3). Dual calls require complete physical geometric_starts
    and finite_measures[stock_id] with exact geometric_start_m3 and
    material_quadrature_m3. Retained errors then mean true-minus-G, NOT
    true-minus-B. Native G remains exact even when its transported B differs.

    A dual finite row may omit legacy volume_m3; if present it still declares
    geometric volume and must equal geometric_start_m3. It is never redefined
    as B. Physical exhaustion caps use G only; the returned material uses B.
    This conversion/selection is not physical-density or debit acceptance.
    """
    dual = geometric_starts is not None or finite_measures is not None
    if dual and (type(geometric_starts) is not dict or type(finite_measures) is not dict):
        raise ValueError('dual measures require both explicit geometric_starts and finite_measures')

    def measure(value, label):
        if type(value) not in (int, Q) or value < 0:
            raise ValueError('exact nonnegative '+label+' required')
        return Q(value)

    result = deepcopy(record)
    result.pop('schema', None)
    rows = result['cells']
    keys = {r['cell_id'] for r in rows}
    if len(keys) != len(rows):
        raise ValueError('duplicate geometry cell')
    physical = {r['cell_id'] for r in rows if r['kind'] != 'algebraic-port'}
    if set(booked)-physical or set(errors)-physical:
        raise ValueError('booked material/error has no physical support')
    if dual and (set(geometric_starts) != physical or set(booked) != physical):
        raise ValueError('dual physical G and B must cover the complete physical node set')
    material = {key: (measure(booked[key], 'material quadrature') if dual else Q(booked.get(key, 0)))
                for key in physical}
    reference = {key: (measure(geometric_starts[key], 'geometric start') if dual else material[key])
                 for key in physical}
    for row in rows:
        key = row['cell_id']
        lo, hi = map(_pair, row['start_volume_bounds_m3'])
        end = tuple(map(_pair, row['end_volume_bounds_m3']))
        if not 0 <= lo <= hi or not 0 <= end[0] <= end[1]:
            raise ValueError('invalid physical endpoint enclosure')
        if row['kind'] == 'algebraic-port':
            if (lo, hi) != (0, 0) or end != (0, 0):
                raise ValueError('an algebraic port cannot contain material')
            continue
        value = material[key]
        if value < 0:
            raise ValueError('negative booked material measure')
        geometric = reference[key]
        if dual and value > 0 and geometric == 0:
            raise ValueError('positive B on zero geometric start refused')
        raw = errors.get(key)
        if raw is None:
            if geometric and row['kind'] != 'collar':
                raise ValueError('positive geometric reference lacks carried geometry error')
            raw = (Q(0), Q(0))
        if type(raw) not in (list, tuple) or len(raw) != 2:
            raise ValueError('two signed carried error endpoints required')
        a, b = map(Q, raw)
        if a > b:
            raise ValueError('reversed carried geometry error')
        if row['kind'] == 'collar' and (lo != hi or a or b or geometric != lo):
            raise ValueError('native Cartesian geometric starts remain exact')
        lo, hi = max(lo, geometric+a), min(hi, geometric+b)
        if lo > hi or value > 0 and hi == 0:
            raise ValueError('booked material and retained true geometry disagree')
        row['start_volume_bounds_m3'] = [_enc(lo), _enc(hi)]
        # In particular, DO NOT expand true end bounds using B or its error.

    inventory = {r['stock_id']: r for r in finite['stocks']}
    if len(inventory) != len(finite['stocks']):
        raise ValueError('duplicate finite inventory')
    if dual and set(finite_measures) != set(inventory):
        raise ValueError('dual finite measure mapping must cover the complete inventory')
    finite_geometry, finite_material = {}, {}
    for stock_id, stock in inventory.items():
        if stock['kind'] not in ('source', 'sink', 'reservoir'):
            raise ValueError('finite source/sink/reservoir kind required')
        if dual:
            values = finite_measures[stock_id]
            if (type(values) is not dict or
                    set(values) != {'geometric_start_m3', 'material_quadrature_m3'}):
                raise ValueError('explicit typed finite G/B measures required')
            g = measure(values['geometric_start_m3'], 'finite geometric start')
            b = measure(values['material_quadrature_m3'], 'finite material quadrature')
            if 'volume_m3' in stock and _pair(stock['volume_m3']) != g:
                raise ValueError('legacy finite volume_m3 disagrees with explicit geometric measure')
            if b > 0 and g == 0:
                raise ValueError('positive finite B on zero geometric start refused')
        else:
            g = b = _pair(stock['volume_m3'])
            if g < 0:
                raise ValueError('negative finite inventory')
        finite_geometry[stock_id], finite_material[stock_id] = g, b
    faces = result['face_intervals']
    face_ids = {f['face_id'] for f in faces}
    if len(face_ids) != len(faces):
        raise ValueError('duplicate physical face')
    exports, used = {}, set()
    exchanges = result.pop('finite_exchange_intervals', [])
    for face in exchanges:
        stock = inventory.get(face['stock_id'])
        direction = face['direction']
        if (stock is None or face['stock_lineage'] != stock['lineage'] or
                face['physical_cell_id'] not in physical or face['face_id'] in face_ids or
                direction not in ('supply', 'export') or stock['kind'] not in
                ('reservoir', 'source' if direction == 'supply' else 'sink')):
            raise ValueError('finite physical interface/lineage/direction mismatch')
        lo, hi = map(_pair, face['volume_bounds_m3'])
        if not 0 <= lo <= hi:
            raise ValueError('invalid finite physical interval')
        stock_id = face['stock_id']
        node = 'finite-stock:'+stock_id
        if node in keys:
            raise ValueError('finite inventory collides with physical identity')
        used.add(stock_id)
        face_ids.add(face['face_id'])
        if direction == 'export':
            exports[stock_id] = exports.get(stock_id, Q(0))+hi
        donor, receiver = ((node, face['physical_cell_id']) if direction == 'supply'
                           else (face['physical_cell_id'], node))
        faces.append(dict(face_id=face['face_id'], donor=donor, receiver=receiver,
                          volume_bounds_m3=face['volume_bounds_m3'], finite_exchange=True,
                          physical_certificate_id=face['physical_certificate_id']))
    for stock_id in sorted(used):
        stock = inventory[stock_id]
        value = finite_geometry[stock_id]
        node = 'finite-stock:'+stock_id
        end = ((Q(0), value) if stock['kind'] == 'source' else
               (Q(0) if stock['kind'] == 'reservoir' else value, value+exports.get(stock_id, Q(0))))
        rows.append(dict(cell_id=node, kind='finite-inventory', stock_id=stock_id,
                         stock_kind=stock['kind'], stock_lineage=deepcopy(stock['lineage']),
                         start_volume_bounds_m3=[_enc(value)]*2,
                         end_volume_bounds_m3=list(map(_enc, end))))
        material[node] = finite_material[stock_id]
    # Keep unconnected stocks explicitly: omitting them would hide B/error or
    # turn a later global mass check into a check of only participating nodes.
    for stock_id in sorted(set(inventory)-used):
        node = 'finite-stock:'+stock_id
        value = finite_geometry[stock_id]
        if node in keys or value < 0:
            raise ValueError('invalid unconnected finite inventory')
        rows.append(dict(cell_id=node, kind='finite-inventory', stock_id=stock_id,
                         stock_kind=inventory[stock_id]['kind'],
                         stock_lineage=deepcopy(inventory[stock_id]['lineage']),
                         start_volume_bounds_m3=[_enc(value)]*2,
                         end_volume_bounds_m3=[_enc(value)]*2))
        material[node] = finite_material[stock_id]
    result['finite_inventory_complete'] = sorted('finite-stock:'+key for key in inventory)
    result['measure_input_contract'] = dict(
        mode='explicit-dual-G-B' if dual else 'explicit-legacy-B-equals-G-conversion',
        retained_error_reference='true geometry minus selected G; legacy mode takes its reference G from B',
        geometric_starts={key: _enc(value) for key, value in reference.items()},
        finite_geometric_starts={key: _enc(value) for key, value in finite_geometry.items()},
        finite_material_quadrature={key: _enc(value) for key, value in finite_material.items()},
        physical_debit_authority=False)
    return result, material


def _minimum_cost(nodes, edges, arena):
    """Exact bounded min-cost circulation; integral costs, rational capacities.

    Saturate negative-cost arcs initially. Every initial residual cost is
    nonnegative, though this pseudoflow has node imbalances. Successive shortest
    augmenting paths remove those imbalances while retaining feasible dual
    potentials. The final residual reduced costs certify optimality, not an
    approximate LP residual. Resource refusal returns no candidate.
    """
    from . import integration_spatial_ale as A
    from . import integration_volume as V
    labels = {key: i for i, key in enumerate(nodes)}
    if len(labels) != len(nodes):
        raise ValueError('duplicate min-cost node')
    n = len(nodes); source, sink = n, n+1
    adjacency = [[] for _ in range(n+2)]
    balance = [Q(0)]*n
    saved = []

    def add(i, j, forward, backward, cost):
        a = [j, len(adjacency[j]), forward, cost]
        b = [i, len(adjacency[i]), backward, -cost]
        adjacency[i].append(a); adjacency[j].append(b)
        return a

    for a, b, low, high, cost in edges:
        if (a not in labels or b not in labels or a == b or not 0 <= low <= high
                or type(cost) is not int):
            raise ValueError('invalid min-cost bounded edge')
        i, j = labels[a], labels[b]
        initial = high if cost < 0 else low
        balance[i] -= initial; balance[j] += initial
        saved.append(add(i, j, high-initial, initial-low, cost))
    required = Q(0)
    for i, value in enumerate(balance):
        if value > 0:
            add(source, i, value, Q(0), 0); required += value
        elif value < 0:
            add(i, sink, -value, Q(0), 0)
    arena.keep((*balance, *(v for edge in edges for v in edge[2:4])), 12*(n+len(edges)))
    potentials = [0]*(n+2); sent = Q(0); augmentations = 0
    while sent < required:
        distance = [None]*(n+2); previous = [None]*(n+2)
        distance[source] = 0; queue = [(0, source)]; visits = 0
        while queue:
            d, i = heapq.heappop(queue)
            if distance[i] != d:
                continue
            for ei, (j, _, capacity, cost) in enumerate(adjacency[i]):
                visits += 1
                if not capacity:
                    continue
                reduced = cost+potentials[i]-potentials[j]
                if reduced < 0:
                    raise ArithmeticError('min-cost residual dual feasibility lost')
                candidate = d+reduced
                if distance[j] is None or candidate < distance[j]:
                    distance[j] = candidate; previous[j] = (i, ei)
                    heapq.heappush(queue, (candidate, j))
        arena.work(n+2+2*visits)
        if distance[sink] is None:
            cut = {key for key, i in labels.items() if distance[i] is not None}
            incoming = sum((lo for a, b, lo, hi, _ in edges if a not in cut and b in cut), Q(0))
            outgoing = sum((hi for a, b, lo, hi, _ in edges if a in cut and b not in cut), Q(0))
            if incoming-outgoing != required-sent or incoming <= outgoing:
                raise ArithmeticError('min-cost infeasibility cut failed exact identity')
            raise A.GCLInfeasible(sorted(cut), incoming, outgoing, required-sent)
        # Unreachable→reachable residual arcs also retain nonnegative reduced
        # cost; no residual arc goes from a reachable to an unreachable node.
        maximum = max(v for v in distance if v is not None)
        potentials = [p+(maximum if d is None else d) for p, d in zip(potentials, distance)]
        at = sink; path = []
        while at != source:
            i, ei = previous[at]; path.append((i, ei)); at = i
        amount = min(adjacency[i][ei][2] for i, ei in path)
        arena.work(4*len(path))
        with V._work((amount, sent, *(adjacency[i][ei][2] for i, ei in path)), arena.resource):
            for i, ei in path:
                j, reverse, capacity, _ = adjacency[i][ei]
                adjacency[i][ei][2] = capacity-amount
                adjacency[j][reverse][2] += amount
            sent += amount
        augmentations += 1
    if any(cost+potentials[i]-potentials[j] < 0 for i, arcs in enumerate(adjacency)
           for j, _, capacity, cost in arcs if capacity):
        raise ArithmeticError('final min-cost dual certificate failed')
    values = tuple(edge[3]-arc[2] for edge, arc in zip(edges, saved))
    balances = dict.fromkeys(nodes, Q(0))
    for (a, b, low, high, _), value in zip(edges, values):
        if not low <= value <= high:
            raise ArithmeticError('min-cost primal bound failed')
        balances[a] -= value; balances[b] += value
    if any(balances.values()):
        raise ArithmeticError('min-cost primal conservation failed')
    return values, augmentations


import sys


def _selection_int_bytes(bits):
    return 40 + sys.int_info.sizeof_digit * ((max(1, bits) +
        sys.int_info.bits_per_digit - 1) // sys.int_info.bits_per_digit)


def _selection_q_bits(value):
    if type(value) is int:
        return max(1, abs(value).bit_length()), 1
    if type(value) is Q:
        return max(1, abs(value.numerator).bit_length()), value.denominator.bit_length()
    # Preserve the existing preferred-start validation and its exception.
    return 1, 1


def _selection_raw_bits(encoded):
    # Prefix/sign/leading zeroes only increase this bound. No integer, Fraction
    # or decoded graph is allocated by the admission scan.
    return max(1, 4 * len(encoded[0])), max(1, 4 * len(encoded[1]))


def _selection_q_bytes(bits):
    return 64 + sum(_selection_int_bytes(b) for b in bits)


def _selection_difference_bits(a, b):
    # Before cancellation: a.n*b.d - b.n*a.d over a.d*b.d.
    return max(a[0] + b[1], b[0] + a[1]) + 1, a[1] + b[1]


def _selection_encoding_bytes(bits):
    # _enc creates a two-reference list and two ASCII hex strings. This counts
    # the widest uncancelled form, including signs/prefixes and object headers.
    return 128 + sum(96 + (b + 3) // 4 for b in bits)


def _selection_map_bytes(count):
    return 256 + 128 * count


def _selection_sequence_bytes(count):
    return 128 + 16 * count


def _selection_deepcopy_bytes(value):
    """New mutable JSON containers, deepcopy memo and traversal allowance.

    deepcopy reuses immutable strings/numbers; charging their text again would
    invent a copy. Repeated mutable references are conservatively counted at
    every occurrence, so no identity set or unadmitted memo is needed here.
    The input is an issued JSON record, hence has no custom objects or cycles.
    """
    if type(value) is dict:
        return 512 + _selection_map_bytes(len(value)) + sum(
            _selection_deepcopy_bytes(v) for v in value.values())
    if type(value) in (list, tuple):
        return 512 + _selection_sequence_bytes(len(value)) + sum(
            _selection_deepcopy_bytes(v) for v in value)
    if type(value) in (str, int, float, bool, type(None), Q):
        return 0
    raise TypeError('issued JSON geometry metadata required for copy accounting')


def _selection_input_workspace(record, preferred_starts):
    """Only selection-owned input edges/indices, not the borrowed evidence.

    Residual adjacency, balances, searches and rational path updates belong to
    the unchanged circulation arena. Expanded split capacities get a local
    cross-product bound, not a global denominator multiplied by every arc.
    """
    rows, faces = record['cells'], record['face_intervals']
    r, f = len(rows), len(faces)
    e = 2 * r + f
    size = 65536 + _selection_sequence_bytes(r)
    size += _selection_map_bytes(r) + _selection_map_bytes(f)
    size += _selection_sequence_bytes(e) + e * _selection_sequence_bytes(4)
    size += _selection_sequence_bytes(e)  # returned representatives
    largest = 1
    for row in rows:
        for name in ('start_volume_bounds_m3', 'end_volume_bounds_m3'):
            for value in row[name]:
                bits = _selection_raw_bits(value)
                size += _selection_q_bytes(bits)
                largest = max(largest, sum(bits))
        if preferred_starts is not None:
            low, high = map(_selection_raw_bits, row['start_volume_bounds_m3'])
            preferred = _selection_q_bits(preferred_starts.get(row['cell_id'], 0))
            middle = tuple(max(values) for values in zip(low, high, preferred))
            for bound in (low, high):
                bits = _selection_difference_bits(middle, bound)
                size += _selection_q_bytes(bits)
                largest = max(largest, sum(bits))
            size += 2 * _selection_q_bytes((1, 1)) + _selection_q_bytes(preferred)
    for face in faces:
        for value in face['volume_bounds_m3']:
            bits = _selection_raw_bits(value)
            size += _selection_q_bytes(bits)
            largest = max(largest, sum(bits))
    if preferred_starts is not None:
        x = e + 2 * r
        size += _selection_sequence_bytes(x) + x * _selection_sequence_bytes(5)
        size += _selection_sequence_bytes(e) + e * _selection_sequence_bytes(2)
        size += _selection_sequence_bytes(x) + 2 * _selection_map_bytes(r)
    # One decode/subtraction at a time: uncancelled products, GCD and result.
    return size + 32 * _selection_int_bytes(2 * largest + 2)


def _selection_sum_workspace(values):
    """Sequential exact sums, without a graph-wide common-denominator copy.

    Every sum/difference denominator divides the product of the operand
    denominators. This conservative bit-only bound funds a constant number of
    accumulators/products, never one worst-case Fraction for every graph arc.
    The generator is consumed once and no operand list/LCM is materialised.
    """
    denominator_bits, magnitude_bits, count = 1, 1, 0
    for value in values:
        n, d = _selection_q_bits(value)
        denominator_bits += d
        magnitude_bits = max(magnitude_bits, n)
        count += 1
    numerator_bits = denominator_bits + magnitude_bits + (count + 1).bit_length() + 3
    return 4096 + 32 * (_selection_int_bytes(2 * numerator_bits + 1) +
                       _selection_int_bytes(2 * denominator_bits))


def _selection_objective_workspace(edges, chosen, values, preferred_starts):
    from itertools import chain
    return _selection_sum_workspace(chain(chosen, values,
        (edge[2] for edge in edges), preferred_starts.values()))


def _selection_output_workspace(record, chosen):
    """Admission from the actual selected rationals, before fixed/output copies.

    Top-level provenance and nested row/face metadata remain borrowed in all
    shallow copies. Only original_face_intervals really deep-copies full face
    metadata. The original endpoint/bound lists are also genuinely copied.
    """
    rows, faces = record['cells'], record['face_intervals']
    r, f = len(rows), len(faces)
    e = 2 * r + f
    size = 65536 + 2 * _selection_map_bytes(len(record) + 10)
    # select_geometry and _close_record indices, sets, maps and output lists;
    # all slots are new, their identity/metadata referents are borrowed.
    size += 12 * _selection_map_bytes(r) + 4 * _selection_map_bytes(f)
    size += 2 * _selection_map_bytes(2 * f)
    size += 8 * _selection_sequence_bytes(r) + 8 * _selection_sequence_bytes(f)
    size += _selection_sequence_bytes(e) + e * _selection_sequence_bytes(4)
    size += 2 * sum(_selection_map_bytes(len(row) + 2) for row in rows)
    size += 3 * sum(_selection_map_bytes(len(face) + 2) for face in faces)
    size += (2 * r + f) * _selection_sequence_bytes(2)
    # Fixed-edge decodes, selected copies and final GCL partial balances. Each
    # edge contributes to at most two node sums. The actual rational payload
    # sum bounds their aggregate limb storage without a per-node global LCM.
    size += 16 * sum(_selection_q_bytes(_selection_q_bits(v)) for v in chosen)
    for index, row in enumerate(rows):
        for position, name in ((2 * index, 'start_volume_bounds_m3'),
                               (2 * index + 1, 'end_volume_bounds_m3')):
            size += 2 * _selection_encoding_bytes(_selection_q_bits(chosen[position]))
            size += _selection_deepcopy_bytes(row[name])
    for index, face in enumerate(faces):
        selected = _selection_q_bits(chosen[2 * r + index])
        size += 2 * _selection_encoding_bytes(selected)
        differences = [_selection_difference_bits(selected, _selection_raw_bits(v))
                       for v in face['volume_bounds_m3']]
        difference = tuple(max(v) for v in zip(*differences))
        size += 3 * _selection_encoding_bytes(difference)
        size += 2 * _selection_deepcopy_bytes(face['volume_bounds_m3'])
        size += 16 * _selection_q_bytes(difference)
    size += _selection_deepcopy_bytes(faces)
    return size + _selection_sum_workspace(chosen)



def select_geometry(record, *, budget, preferred_starts=None):
    """Pure geometric feasibility, with shared ports and fixed inventory caps.

    No source-group sum is invented from booked material funding. Such a
    constraint would require an independent exact GEOMETRIC identity.
    """
    from . import integration_spatial_ale as A
    from . import integration_volume_bounds as B
    from .integration_regional_inventory import _width

    rows, faces = record['cells'], record['face_intervals']
    keys = [r['cell_id'] for r in rows]
    reservoir = 'volume-endpoint-reservoir'
    if len(set(keys)) != len(keys) or reservoir in keys:
        raise ValueError('unique nonreserved geometry identities required')
    if len({f['face_id'] for f in faces}) != len(faces):
        raise ValueError('unique physical faces required')
    with ExitStack() as storage:
        storage.enter_context(budget.reserve(_selection_input_workspace(record, preferred_starts),
            category='private-geometric-circulation'))
        edges = []
        for row in rows:
            edges.append((reservoir, row['cell_id'], *map(_pair, row['start_volume_bounds_m3'])))
            edges.append((row['cell_id'], reservoir, *map(_pair, row['end_volume_bounds_m3'])))
        edges.extend((f['donor'], f['receiver'], *map(_pair, f['volume_bounds_m3'])) for f in faces)
        optimum = None
        with B._Arena(budget) as arena:
            if preferred_starts is None:
                chosen = A._circulation([reservoir]+keys, edges, arena)
            else:
                physical = {r['cell_id'] for r in rows if r['kind'] != 'algebraic-port'}
                if set(preferred_starts) != physical or any(type(v) not in (int, Q) or v < 0
                                                          for v in preferred_starts.values()):
                    raise ValueError('complete exact nonnegative preferred starts required')
                expanded, indices = [], []
                for index, (a, b, lo, hi) in enumerate(edges):
                    begin = len(expanded)
                    if index < 2*len(rows) and index % 2 == 0:
                        preferred = Q(preferred_starts.get(b, 0))
                        middle = min(hi, max(lo, preferred))
                        expanded.extend(((a, b, lo, lo, 0), (a, b, Q(0), middle-lo, -1),
                                         (a, b, Q(0), hi-middle, 1)))
                    else:
                        expanded.append((a, b, lo, hi, 0))
                    indices.append((begin, len(expanded)))
                values, augmentations = _minimum_cost([reservoir]+keys, expanded, arena)
                chosen = tuple(sum(values[a:b], Q(0)) for a, b in indices)
                storage.enter_context(budget.reserve(
                    _selection_objective_workspace(edges, chosen, values, preferred_starts),
                    category='private-geometric-objective'))
                objective = sum((abs(chosen[2*i]-Q(preferred_starts.get(key, 0)))
                                 for i, key in enumerate(keys)), Q(0))
                offset = sum((abs(edges[2*i][2]-Q(preferred_starts.get(key, 0)))
                              for i, key in enumerate(keys)), Q(0))
                if objective != offset+sum((value*edge[4] for edge, value in zip(expanded, values)), Q(0)):
                    raise ArithmeticError('split-arc objective does not equal actual L1 rebase')
                optimum = dict(method='exact-rational minimum-L1 geometric rebase',
                    optimality='all primal balances/bounds and all residual reduced costs verified exactly',
                    augmentations=augmentations,
                    objective_m3=_enc(objective))
        storage.enter_context(budget.reserve(_selection_output_workspace(record, chosen),
            category='private-geometric-output'))
        start = dict(zip(keys, chosen[:2*len(rows):2]))
        end = dict(zip(keys, chosen[1:2*len(rows):2]))
        flux = dict(zip((f['face_id'] for f in faces), chosen[2*len(rows):]))
        # Reuse the production graph assembly/port elimination and exact GCL
        # checks with these fully fixed representatives. This second call has
        # zero residual demands, not another representative search.
        fixed = dict(record,
            cells=[dict(r, start_volume_bounds_m3=[_enc(start[r['cell_id']])]*2,
                        end_volume_bounds_m3=[_enc(end[r['cell_id']])]*2) for r in rows],
            face_intervals=[dict(f, volume_bounds_m3=[_enc(flux[f['face_id']])]*2) for f in faces])
        row_by_id = {r['cell_id']: r for r in rows}
        graph = A._close_record(fixed, {k: v for k, v in start.items()
                                       if row_by_id[k]['kind'] != 'algebraic-port'}, budget)
        face_by_id = {f['face_id']: f for f in faces}
        for row in graph['cells']+graph['inactive_zero_measure_cells']:
            original = row_by_id[row['cell_id']]
            for key in ('start_volume_bounds_m3', 'end_volume_bounds_m3'):
                row[key] = deepcopy(original[key])
        for face in graph['selected_face_representatives']+graph['transfers']:
            original = face_by_id[face['face_id']]
            face['volume_bounds_m3'] = deepcopy(original['volume_bounds_m3'])
            lo, hi = map(_pair, original['volume_bounds_m3'])
            face['max_deviation_m3'] = _enc(max(flux[face['face_id']]-lo, hi-flux[face['face_id']]))
        graph.update(schema='atlas.private-geometric-only-circulation.v1',
                     original_face_intervals=deepcopy(faces), scientific_acceptance=False,
                     selection='joint GEOMETRIC start/end/face representatives in unchanged enclosures; NOT booked material')
        if optimum is not None:
            graph['geometric_rebase_minimum'] = optimum
        return graph


def initial_allocation(bounds, total, *, relative_limits, max_total_width, budget):
    """Prospective static quadrature with explicit local accuracy, no defaults.

    Caller must prove complete source partition/independent total and supply
    its STATIC certified bounds. This pure arithmetic seam cannot certify
    coverage, source density or geometry. It never reads future motion.

    For true V in [l,h], |B/V-1| <= r holds for every positive V iff
    (1-r)h <= B <= (1+r)l (0<=r<1). Intersect with original [l,h], then use
    the existing exact partition allocator. A contradiction refuses: no
    tolerance relaxation, post-transport material correction or new stock.
    This controls geometric dilution of a source-uniform extensive field,
    not the source's own uncertainty or later transport discretisation error.

    Inputs/results are caller-owned diagnostic arithmetic. Retention must be
    charged by the caller. No material state or scientific acceptance issued.
    """
    from .integration_collar_geometry import _partition
    from .integration_regional_inventory import _width
    from . import integration_volume as V
    from .resources import WorkBudget

    if type(budget) is not WorkBudget or type(bounds) is not dict or not bounds:
        raise ValueError('explicit budget and complete static bound mapping required')
    if (type(relative_limits) is not dict or set(relative_limits) != set(bounds) or
            any(type(k) is not str or not k for k in bounds)):
        raise ValueError('explicit local initial-accuracy limit for every cell required')
    if any(type(v) not in (int, Q) for v in (total, max_total_width, *relative_limits.values())):
        raise ValueError('exact initial accuracy limits and independent total required')
    if total < 0 or max_total_width < 0 or any(not 0 <= r < 1 for r in relative_limits.values()):
        raise ValueError('nonnegative total/width and local relative errors below one required')
    with budget.reserve(65536+12*_width((bounds, total, relative_limits, max_total_width)),
                        category='private-initial-accuracy-allocation'):
        keys = sorted(bounds)
        admitted, raw, width = [], [], Q(0)
        for key in keys:
            pair = bounds[key]
            if (type(pair) not in (tuple, list) or len(pair) != 2 or
                    any(type(v) not in (int, Q) for v in pair)):
                raise ValueError('two exact static volume bounds required')
            low, high = map(Q, pair)
            if not 0 <= low <= high:
                raise ValueError('invalid static physical volume bounds')
            if low == 0 and high > 0:
                raise V.VolumeError('positive initial volume lacks a positive lower bound; refine '+key)
            r = Q(relative_limits[key])
            a, b = max(low, (1-r)*high), min(high, (1+r)*low)
            if a > b:
                raise V.VolumeError('initial local geometry accuracy unmet; refine '+key)
            admitted.append((a, b)); raw.append((low, high)); width += high-low
        if width > max_total_width:
            raise V.VolumeError('original total initial geometry width exceeds declared allowance')
        # No allocation occurs until all local and original absolute bounds
        # have passed. This is a NEW initial state, never a repair to old B.
        values = _partition(admitted, Q(total))
        errors = []
        for value, (low, high), key in zip(values, raw, keys):
            error = max(abs(value/low-1), abs(value/high-1)) if low else Q(0)
            if error > relative_limits[key]:
                raise ArithmeticError('initial quadrature local certificate failed')
            errors.append(error)
        return dict(status='STATIC_ARITHMETIC_ONLY_NOT_ACCEPTED', scientific_acceptance=False,
            booked=dict(zip(keys, values)), original_bounds=dict(zip(keys, raw)),
            admissible_bounds=dict(zip(keys, admitted)), independent_total=Q(total),
            actual_total_width=width, declared_total_width=Q(max_total_width),
            relative_limits={k: Q(relative_limits[k]) for k in keys},
            worst_relative_quadrature_errors=dict(zip(keys, errors)),
            selection='fresh static source partition only; no future trajectory or evolved-stock edit')


def measure_initial_component(support, cell_id, *, relative_error, absolute_width_m3,
                              max_leaves_per_query, budget, _volume=None):
    """One retained certified query on unchanged initial static support.

    Absolute and relative stopping use the progressively refined enclosure.
    The queue is never restarted with a weaker earlier lower bound; failure
    retains the actual work and bounds without starting another try.
    The caller must establish complete initial partition/funding authority.
    """
    from . import integration_differential_geometry as G
    from . import integration_volume as V
    from . import integration_wall_measures as W
    from .resources import WorkBudget

    if (type(budget) is not WorkBudget or type(relative_error) not in (int, Q) or
            type(absolute_width_m3) not in (int, Q) or not 0 <= relative_error < 1 or
            absolute_width_m3 < 0 or type(max_leaves_per_query) is not int or max_leaves_per_query < 1):
        raise V.VolumeError('explicit exact local/absolute accuracy and finite work limits required')
    r, width = Q(relative_error), Q(absolute_width_m3)
    if type(support) is not G.DifferentialSupport or support._resource is not budget:
        raise V.VolumeError('issued physical support and its original budget required')
    with budget.reserve(65536+16*len(support._json), category='initial-local-accuracy'):
        raw = support.record()
        if W._decode(raw['duration_s']) != 0 or raw['start_time_s'] != raw['end_time_s']:
            raise V.VolumeError('only static initial support, not a future/evolved interval')
        queries = []

        def query(target):
            # initpar r1 (T/ck/transforms/initpar_r1.py): a worker's measure of exactly this call, adopted at
            # this serial position by an opened pass, else the unchanged call.
            adopted = None if _volume is None else _volume.claim(support, cell_id, raw,
                max_width_m3=target, max_leaves=max_leaves_per_query, relative_error=r, budget=budget)
            result = (G.component_volume_bounds(support, cell_id, endpoint='start',
                max_width_m3=target, max_leaves=max_leaves_per_query,
                positive_witness=True, budget=budget, relative_error=r) if adopted is None else adopted).record()
            adopted = None
            queries.append(result)
            return W._decode(result['lower_m3']), W._decode(result['upper_m3'])

        low, high = query(width)
        if low == 0 and high > 0:
            failure = V.VolumeError('initial positive support unresolved within declared work; no material assigned')
            failure.initial_accuracy = dict(cell_id=cell_id, bounds=(low, high),
                relative_error_bound=None, requested_relative_error=r, queries=queries)
            raise failure
        error = (high-low)/low if low else Q(0)
        if high-low > width or error > r:
            failure = V.VolumeError('initial local/absolute accuracy unmet within declared work; no material assigned')
            failure.initial_accuracy = dict(cell_id=cell_id, bounds=(low, high),
                relative_error_bound=error, requested_relative_error=r, queries=queries)
            raise failure
        if low < 0 or high < low or high and not low:
            raise V.VolumeError('initial support is neither certified empty nor positive')
        measured = queries[-1]
        if (measured['met'] is not True or high > 0 and
                (not 0 < W._decode(measured['positive_witness_m3']) <= low or
                 not measured.get('positive_witness_point_m') or
                 len(measured['positive_witness_point_m']) != 3)):
            failure = V.VolumeError('initial support lacks a completed physical volume/witness certificate; no material assigned')
            failure.initial_accuracy = dict(cell_id=cell_id, bounds=(low, high),
                relative_error_bound=error, requested_relative_error=r, queries=queries)
            raise failure
        return dict(cell_id=cell_id, support_id=support.support_id,
            bounds=(low, high), relative_error_bound=error, requested_relative_error=r,
            absolute_width_m3=width, queries=queries,
            query_count=len(queries), cumulative_leaf_units=sum(q['leaves'] for q in queries),
            cumulative_work_units=sum(q['work_units'] for q in queries),
            declared_max_queries=1, declared_max_leaves_per_query=max_leaves_per_query,
            rule='every allocation and every true volume in this enclosure obey |B/V-1| <= r')


def cached_initial_component(support, cell_id, *, relative_error, absolute_width_m3,
                             max_leaves_per_query, budget, store, context, _volume=None):
    """Explicit lossless reuse of successful static measurements, not material.

    Use the existing verified ArrayStore and full ExecutionContext identity.
    The exact support, requested accuracy and work ceiling all participate in
    the key. Failed/partial queries are never cached. Older diagnostic JSON is
    not imported or rebound. A hit retains its original query/work provenance.
    """
    import json
    import numpy as np
    from . import integration_differential_geometry as G
    from . import integration_volume as V
    from . import integration_wall_measures as W
    from .resources import WorkBudget
    from .reuse import ExecutionContext
    from .storage import ArrayStore

    if (type(budget) is not WorkBudget or type(support) is not G.DifferentialSupport or
            support._resource is not budget or type(relative_error) not in (int, Q) or
            type(absolute_width_m3) not in (int, Q) or not 0 <= relative_error < 1 or
            absolute_width_m3 < 0 or type(max_leaves_per_query) is not int or
            max_leaves_per_query < 1 or type(store) is not ArrayStore or
            type(context) is not ExecutionContext or context.backend != 'reference'):
        raise V.VolumeError('explicit initial query, ArrayStore and reference ExecutionContext required')
    raw = support.record()
    if (W._decode(raw['duration_s']) != 0 or raw['start_time_s'] != raw['end_time_s'] or
            not any(c['logical_cell_id'] == cell_id for c in raw['components'])):
        raise V.VolumeError('cached initial query requires the same static physical component')
    r, width = Q(relative_error), Q(absolute_width_m3)
    metadata = dict(schema='atlas.initial-component-cache.v1', execution_identity=context.identity,
        support_id=support.support_id, cell_id=cell_id, relative_error=str(r),
        absolute_width_m3=str(width), max_leaves_per_query=max_leaves_per_query)
    key = W._hash(metadata)
    with budget.reserve(4 << 20, category='initial-measurement-cache-codec'):
        restored = store.get(key, budget=budget)
        if restored is None:
            result = measure_initial_component(support, cell_id, relative_error=r,
                absolute_width_m3=width, max_leaves_per_query=max_leaves_per_query, budget=budget,
                _volume=_volume)
            payload = json.dumps(result, default=str, sort_keys=True, separators=(',', ':'),
                                 allow_nan=False).encode('utf8')
            if len(payload) > 1 << 20:
                raise V.VolumeError('initial measurement exceeds bounded cache record size')
            context.verify()
            store.put(key, {'measurement': np.frombuffer(payload, dtype=np.uint8)}, metadata,
                      publication_check=context.verify, budget=budget)
        else:
            if (set(restored) != {'measurement'} or store.metadata(key) != metadata or
                    restored['measurement'].dtype != np.dtype('uint8') or
                    restored['measurement'].ndim != 1 or restored['measurement'].size > 1 << 20):
                raise V.VolumeError('initial measurement cache contract differs')
            result = json.loads(restored['measurement'].tobytes())
            result['bounds'] = tuple(map(Q, result['bounds']))
            for name in ('relative_error_bound', 'requested_relative_error', 'absolute_width_m3'):
                result[name] = Q(result[name])
        # Storage authenticates bytes; these checks establish their query and
        # precision meaning before the normal complete-partition allocator.
        low, high = result['bounds']
        query, = result['queries']
        error = (high-low)/low if low else Q(0)
        if (result['cell_id'] != cell_id or result['support_id'] != support.support_id or
                result['requested_relative_error'] != r or result['absolute_width_m3'] != width or
                result['declared_max_leaves_per_query'] != max_leaves_per_query or
                result['declared_max_queries'] != 1 or result['query_count'] != 1 or
                not 0 <= low <= high or high > 0 and low == 0 or high-low > width or
                result['relative_error_bound'] != error or error > r or
                query['support_id'] != support.support_id or query['logical_cell_id'] != cell_id or
                query['endpoint'] != 'start' or query['time_s'] != raw['start_time_s'] or
                W._decode(query['lower_m3']) != low or W._decode(query['upper_m3']) != high or
                W._decode(query['relative_error']) != r or W._decode(query['max_width_m3']) != width or
                query['met'] is not True or query['max_leaves'] != max_leaves_per_query or
                not 1 <= query['leaves'] <= max_leaves_per_query or
                query['leaves'] != result['cumulative_leaf_units'] or
                query['work_units'] != result['cumulative_work_units'] or
                high > 0 and (not 0 < W._decode(query['positive_witness_m3']) <= low or
                              not query.get('positive_witness_point_m') or
                              len(query['positive_witness_point_m']) != 3)):
            raise V.VolumeError('cached initial measurement does not certify the requested bounds')
        context.verify()
        return result
