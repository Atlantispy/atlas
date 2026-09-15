"""Fixed-quantum conservative allocation; WORKING NON-CANON.

Frozen policy: Q=2^-64 kg, at most 256 bits per integer mass/error count,
1024 transportation rows/columns, 16385 positive migration slots per origin.
Exact predecessor rational inputs retain the 8192-bit field boundary. Outputs
and accumulated error bounds are integers: no growing rational error ledger.
No physical law, persistent native guard or predecessor state is changed here.
"""
from collections import deque
from collections.abc import Mapping
from fractions import Fraction as F
import heapq
import math


Q = F(1, 2**64)
QUANTUM_DENOMINATOR = 2**64
MAX_UNIT_BITS = 256
MAX_ORIGINS = 1024
MAX_DESTINATIONS = 1024
MAX_POSITIVE_SLOTS = 16385
MAX_EXACT_INPUT_BITS = 8192
MAX_KEY_LENGTH = 1024


def _integer(value, name):
    if type(value) is not int or value < 0 or value.bit_length() > MAX_UNIT_BITS:
        raise ValueError(name + ': nonnegative integer of at most 256 bits required')
    return value


def _exact(value, name, *, positive=False):
    if type(value) not in (int, F):
        raise ValueError(name + ': exact Fraction/int required; no float or bool')
    value = F(value)
    if value < 0 or (positive and value == 0):
        raise ValueError(name + ': positive mass required' if positive else name + ': negative mass')
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_EXACT_INPUT_BITS:
        raise ValueError(name + ': exact input exceeds the retained 8192-bit boundary')
    return value


def _mapping(values, name, limit):
    if not isinstance(values, Mapping) or len(values) > limit:
        raise ValueError(name + ': bounded explicit keyed mapping required')
    detached = dict(values)
    if any(type(key) is not str or not key or len(key) > MAX_KEY_LENGTH for key in detached):
        raise ValueError(name + ': nonempty bounded stable string keys required')
    return {key: detached[key] for key in sorted(detached)}


def _ceil_div(numerator, denominator):
    return (numerator + denominator - 1) // denominator


def units(value):
    """Exact nonnegative Q-valued mass -> bounded integer quantum count."""
    value = _exact(value, 'mass')
    quotient, remainder = divmod(value.numerator * QUANTUM_DENOMINATOR, value.denominator)
    if remainder:
        raise ValueError('mass is not an exact multiple of the frozen quantum')
    return _integer(quotient, 'mass units')


def mass(unit_count):
    """Bounded nonnegative integer quantum count -> exact mass in kg."""
    return F(_integer(unit_count, 'mass units'), QUANTUM_DENOMINATOR)


def ceil_error_units(exact_kg):
    """Outward-round a nonnegative exact mass error to integer Q units."""
    value = _exact(exact_kg, 'mass error')
    return _integer(_ceil_div(value.numerator * QUANTUM_DENOMINATOR, value.denominator),
                    'error units')


def _sum_matches(values, target):
    """Exact migration sum with a bounded scratch denominator, never an LCM ledger.

    The predecessor atoms may have tiny positive dyadic masses. Preserve them
    during this read check; reject unsupported denominator growth BEFORE an
    unbounded common denominator can be constructed. The sum is not persisted.
    """
    total = F()
    for value in values:
        common = math.gcd(total.denominator, value.denominator)
        left = total.denominator // common
        if left.bit_length() + value.denominator.bit_length() - 1 > MAX_EXACT_INPUT_BITS:
            raise ValueError('migration sum exceeds bounded exact scratch denominator')
        denominator = left * value.denominator
        if denominator.bit_length() > MAX_EXACT_INPUT_BITS:
            raise ValueError('migration sum exceeds bounded exact scratch denominator')
        total += value
        if total > target:
            return False
    return total == target


def allocate_positive(total_units, desired):
    """Return (slot unit counts, conservative integer L1-error bound).

    ``desired`` contains only currently positive predecessor incidences in kg,
    whose exact sum equals total_units*Q. Every supplied slot remains positive.
    Floors with a lower bound of one are balanced by deterministic remainders.
    When the lower bounds overfill the total, remove units from eligible slots
    in order of greatest current over-allocation; stable keys break ties.
    At most one adjustment per supplied slot is needed in total. Each local
    error is outward-rounded separately before summing integer error counts.
    """
    total_units = _integer(total_units, 'migration total units')
    desired = _mapping(desired, 'positive migration slots', MAX_POSITIVE_SLOTS)
    exact = {key: _exact(value, 'desired slot mass', positive=True) for key, value in desired.items()}
    if not _sum_matches(exact.values(), mass(total_units)):
        raise ValueError('desired slot masses do not equal the exact origin total')
    if total_units < len(exact):
        raise ValueError('origin total cannot fund one quantum per positive predecessor slot')
    if not exact:
        return {}, 0
    result, fractional = {}, {}
    for key, value in exact.items():
        whole, remainder = divmod(value.numerator * QUANTUM_DENOMINATOR, value.denominator)
        result[key] = max(1, whole)
        fractional[key] = F(remainder, value.denominator)
    difference = total_units - sum(result.values())
    if abs(difference) > len(exact):
        raise ArithmeticError('positive floor allocation exceeded its bounded adjustment count')
    if difference > 0:
        # Deficit = ideal - current; a lower-bound-raised slot has deficit <0.
        ranked = sorted(exact, key=lambda key: (
            -(exact[key] * QUANTUM_DENOMINATOR - result[key]), key))
        for key in ranked[:difference]:
            result[key] += 1
    elif difference < 0:
        # Heap priority is -(current-ideal), so the greatest over-allocation
        # is reduced first. Reinsert a reduced slot only if it can stay >0.
        heap = [(exact[key] * QUANTUM_DENOMINATOR - result[key], key)
                for key in exact if result[key] > 1]
        heapq.heapify(heap)
        for _ in range(-difference):
            if not heap:
                raise ArithmeticError('positive allocation exhausted eligible balancing slots')
            priority, key = heapq.heappop(heap)
            result[key] -= 1
            if result[key] > 1:
                heapq.heappush(heap, (priority + 1, key))
    if sum(result.values()) != total_units or any(value <= 0 for value in result.values()):
        raise ArithmeticError('positive allocation did not preserve total and incidences')
    errors = 0
    for key, original in exact.items():
        numerator = abs(result[key] * original.denominator - original.numerator * QUANTUM_DENOMINATOR)
        errors += _ceil_div(numerator, original.denominator)
        _integer(result[key], 'allocated mass units')
    return result, _integer(errors, 'positive allocation L1 error units')


def _residual_flow(row_need, col_need, eligible):
    """Deterministic integral bipartite max flow; no recursion or float costs."""
    nr, nc = len(row_need), len(col_need)
    source, sink = nr + nc, nr + nc + 1
    graph = [[] for _ in range(sink + 1)]

    def edge(a, b, capacity):
        forward = [b, len(graph[b]), capacity]
        reverse = [a, len(graph[a]), 0]
        graph[a].append(forward)
        graph[b].append(reverse)
        return forward

    for i, need in enumerate(row_need):
        edge(source, i, need)
    cell_edges = {}
    for i, j in eligible:
        cell_edges[i, j] = edge(i, nr + j, 1)
    for j, need in enumerate(col_need):
        edge(nr + j, sink, need)
    needed, sent = sum(row_need), 0
    if needed != sum(col_need):
        raise ArithmeticError('residual transportation margins differ')
    while sent < needed:
        level = [-1] * len(graph)
        level[source] = 0
        queue = deque([source])
        while queue:
            node = queue.popleft()
            for following, _, capacity in graph[node]:
                if capacity and level[following] < 0:
                    level[following] = level[node] + 1
                    queue.append(following)
        if level[sink] < 0:
            raise ArithmeticError('fractional transportation residual has no feasible integral flow')
        cursor = [0] * len(graph)
        while True:
            node, path = source, []
            # Find an augmenting path in the level graph. Dead ends advance
            # their parent's current arc; every search terminates finitely.
            while node != sink:
                while cursor[node] < len(graph[node]):
                    item = graph[node][cursor[node]]
                    if item[2] and level[item[0]] == level[node] + 1:
                        break
                    cursor[node] += 1
                if cursor[node] == len(graph[node]):
                    level[node] = -1
                    if not path:
                        node = None
                        break
                    parent, _ = path.pop()
                    cursor[parent] += 1
                    node = parent
                else:
                    path.append((node, cursor[node]))
                    node = graph[node][cursor[node]][0]
            if node is None:
                break
            amount = min(graph[a][index][2] for a, index in path)
            for a, index in path:
                item = graph[a][index]
                item[2] -= amount
                graph[item[0]][item[1]][2] += amount
            sent += amount
    return {key: 1 - item[2] for key, item in cell_edges.items()}


def transportation_matrix(rows, cols):
    """Return (origin/destination unit matrix, integer L1-error bound).

    Both nonnegative integer margins are exact; their grand total must agree.
    Each entry is floor or ceil of ri*cj/N. Zero-margin pairs stay zero. Positive
    origins are conserved globally even where an individual output atom is zero.
    Residual unit-capacity bipartite flow fulfils BOTH margins, with sorted keys
    fixing every tie. The L1 numerator has one common INTEGER denominator N;
    its final outward division gives the error bound without rational summation.
    """
    rows = {key: _integer(value, 'origin units') for key, value in
            _mapping(rows, 'transportation origins', MAX_ORIGINS).items()}
    cols = {key: _integer(value, 'destination units') for key, value in
            _mapping(cols, 'transportation destinations', MAX_DESTINATIONS).items()}
    total = _integer(sum(rows.values()), 'transportation grand total')
    if total != _integer(sum(cols.values()), 'destination grand total'):
        raise ValueError('transportation row and column totals differ')
    matrix = {row: {col: 0 for col in cols} for row in rows}
    if not total:
        return matrix, 0
    rkeys, ckeys = list(rows), list(cols)
    row_need, col_need = list(rows.values()), list(cols.values())
    eligible = []
    for i, row in enumerate(rkeys):
        for j, col in enumerate(ckeys):
            whole, remainder = divmod(rows[row] * cols[col], total)
            matrix[row][col] = whole
            row_need[i] -= whole
            col_need[j] -= whole
            if remainder:
                eligible.append((i, j))
    increments = _residual_flow(row_need, col_need, eligible)
    for (i, j), increment in increments.items():
        matrix[rkeys[i]][ckeys[j]] += increment
    if (any(sum(matrix[row].values()) != rows[row] for row in rows)
            or any(sum(matrix[row][col] for row in rows) != cols[col] for col in cols)):
        raise ArithmeticError('integer transportation margins did not close')
    error_numerator = sum(abs(matrix[row][col] * total - rows[row] * cols[col])
                          for row in rows for col in cols)
    return matrix, _integer(_ceil_div(error_numerator, total), 'transportation L1 error units')
