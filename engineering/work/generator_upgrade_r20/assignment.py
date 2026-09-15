"""Bounded whole-unit assignment, with no supplied political policy defaults.

All edges are positive-length physical adjacencies, even when boundary_score is
zero. Objectives are lexicographic: integer evidence first, then integer support
for distinct-owner frontiers. There is no area/count/ID tie objective. Connectivity
is imposed by valid lazy vertex-separator cuts without choosing an owner root.
An assignment is returned only after excluding it at BOTH optima proves uniqueness.

SciPy milp minimises binary64 linear objectives; all coefficients here are small
integers. Rounded binary candidates are checked against every constraint using
Python integers, objectives are independently reconstructed, and an integer-gap
dual-bound check is required. Solver limits/uncertainty never admit incumbents.
See https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html.
"""
from copy import deepcopy
import math
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


SCHEMA = 'diadem.whole-unit-political-assignment.r20'
MAX_UNITS, MAX_OWNERS, MAX_EDGES = 256, 32, 2048
MAX_SCORE = 1_000_000
MAX_VARIABLES, MAX_ROWS, MAX_NONZEROS = 50_000, 200_000, 1_000_000
BINARY_ATOL = 1e-7
EPS = np.finfo(float).eps
FIELDS = {'unit_ids', 'owners', 'eligible', 'scores', 'edges', 'required_owners',
          'connected_owners', 'required_adjacency', 'prohibited_adjacency', 'limits'}
OPTIONAL_FIELDS = {'required_presence', 'required_any_adjacency'}


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(label+': exact fields required')


def _ids(value, limit, label, *, nonempty=False):
    if (type(value) is not list or len(value) > limit or (nonempty and not value)
            or any(type(v) is not str or not v.strip() or len(v) > 128 for v in value)
            or len(set(value)) != len(value)):
        raise ValueError(label+': bounded distinct explicit identities required')
    return tuple(sorted(value))


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(label+': bounded explicit integer required')
    return value


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _solver_number(value):
    """Keep available finite solver bounds JSON-compatible, never as proof."""
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _pairs(value, owners, label):
    if type(value) is not list or len(value) > MAX_OWNERS*(MAX_OWNERS-1)//2:
        raise ValueError(label+': bounded owner-pair list required')
    pairs = set()
    for row in value:
        if (type(row) is not list or len(row) != 2 or any(type(v) is not str or v not in owners for v in row)
                or row[0] == row[1]):
            raise ValueError(label+': two distinct known owners required')
        pair = tuple(sorted(row))
        if pair in pairs:
            raise ValueError(label+': duplicate undirected owner pair')
        pairs.add(pair)
    return tuple(sorted(pairs))


def _problem(problem):
    if (type(problem) is not dict or not FIELDS <= set(problem)
            or not set(problem) <= FIELDS | OPTIONAL_FIELDS):
        raise ValueError('assignment problem: required and known optional fields only')
    units = _ids(problem['unit_ids'], MAX_UNITS, 'units', nonempty=True)
    owners = _ids(problem['owners'], MAX_OWNERS, 'owners', nonempty=True)
    if (type(problem['eligible']) is not dict or set(problem['eligible']) != set(units)
            or type(problem['scores']) is not dict or set(problem['scores']) != set(units)):
        raise ValueError('one explicit eligibility/score row per unit required')
    eligible, scores = {}, {}
    for unit in units:
        eligible[unit] = _ids(problem['eligible'][unit], MAX_OWNERS, 'eligible owners')
        if not set(eligible[unit]) <= set(owners):
            raise ValueError('unknown eligible owner')
        row = problem['scores'][unit]
        if (type(row) is not dict or not set(eligible[unit]) <= set(row)
                or not set(row) <= set(owners)):
            raise ValueError('every eligible owner needs an explicit integer score')
        scores[unit] = {owner: _integer(value, -MAX_SCORE, MAX_SCORE, 'evidence score')
                        for owner, value in row.items()}
    edges, seen = [], set()
    if type(problem['edges']) is not list or len(problem['edges']) > MAX_EDGES:
        raise ValueError('bounded physical adjacency list required')
    for row in problem['edges']:
        _exact(row, ('left', 'right', 'length_m', 'boundary_score'), 'physical edge')
        left, right = row['left'], row['right']
        if type(left) is not str or type(right) is not str or left not in units or right not in units or left == right:
            raise ValueError('edge requires distinct known units')
        pair = tuple(sorted((left, right)))
        if pair in seen:
            raise ValueError('duplicate undirected physical edge')
        seen.add(pair)
        length = row['length_m']
        if not _finite(length) or length <= 0:
            raise ValueError('physical edge requires finite positive length_m')
        edges.append((*pair, _integer(row['boundary_score'], 0, MAX_SCORE, 'frontier evidence')))
    required = _ids(problem['required_owners'], MAX_OWNERS, 'required owners')
    connected = _ids(problem['connected_owners'], MAX_OWNERS, 'connected owners')
    if not set(required+connected) <= set(owners):
        raise ValueError('unknown required/connected owner')
    adjacency = _pairs(problem['required_adjacency'], owners, 'required adjacency')
    prohibited = _pairs(problem['prohibited_adjacency'], owners, 'prohibited adjacency')
    presence, seen_presence = [], set()
    rows = problem.get('required_presence', [])
    if type(rows) is not list or len(rows) > MAX_UNITS*MAX_OWNERS:
        raise ValueError('bounded required-presence list required')
    for row in rows:
        _exact(row, ('owner', 'unit_ids'), 'required presence')
        owner = row['owner']
        if type(owner) is not str or owner not in owners:
            raise ValueError('required presence: known owner required')
        subset = _ids(row['unit_ids'], MAX_UNITS, 'required-presence units', nonempty=True)
        if not set(subset) <= set(units):
            raise ValueError('required presence: unknown unit')
        key = (owner, subset)
        if key in seen_presence:
            raise ValueError('duplicate required owner/unit-subset presence')
        seen_presence.add(key); presence.append(key)
    any_adjacency, seen_any = [], set()
    rows = problem.get('required_any_adjacency', [])
    if type(rows) is not list or len(rows) > MAX_OWNERS*MAX_OWNERS:
        raise ValueError('bounded required-any-adjacency list required')
    for row in rows:
        _exact(row, ('owner', 'other_owners'), 'required any adjacency')
        owner = row['owner']
        if type(owner) is not str or owner not in owners:
            raise ValueError('required any adjacency: known owner required')
        others = _ids(row['other_owners'], MAX_OWNERS-1, 'other owners', nonempty=True)
        if owner in others or not set(others) <= set(owners):
            raise ValueError('required any adjacency: distinct known other owners required')
        key = (owner, others)
        if key in seen_any:
            raise ValueError('duplicate required-any-adjacency group')
        seen_any.add(key); any_adjacency.append(key)
    limits = problem['limits']
    _exact(limits, ('max_cut_rounds', 'node_limit', 'time_limit_s'), 'global search limits')
    cuts = _integer(limits['max_cut_rounds'], 0, 256, 'connectivity cut rounds')
    nodes = _integer(limits['node_limit'], 1, 1_000_000, 'global node limit')
    seconds = limits['time_limit_s']
    if not _finite(seconds) or not 0 < seconds <= 300:
        raise ValueError('global time limit must be finite in (0,300] seconds')
    return (units, owners, eligible, scores, tuple(sorted(edges)), required, connected,
            adjacency, prohibited, cuts, nodes, float(seconds), tuple(sorted(presence)),
            tuple(sorted(any_adjacency)))


class _Incomplete(Exception):
    pass


class _Search:
    def __init__(self, data, started):
        (self.units, self.owners, self.eligible, self.scores, self.edges,
         self.required, self.connected, self.required_adj, self.prohibited_adj,
         self.max_rounds, self.node_limit, seconds, self.required_presence,
         self.required_any_adj) = data
        self.deadline, self.started = started+seconds, started
        self.calls, self.nodes, self.cut_rounds = [], 0, 0
        self.rows, self.row_keys, self.nonzeros, self.nvars = [], set(), 0, 0
        self.x = {(unit, owner): self.variable() for unit in self.units for owner in self.eligible[unit]}
        self.frontiers = [self.variable() for _ in self.edges]
        self.neighbours = {unit: set() for unit in self.units}
        for left, right, _ in self.edges:
            self.neighbours[left].add(right); self.neighbours[right].add(left)
        for unit in self.units:
            self.row({self.x[unit, owner]: 1 for owner in self.eligible[unit]}, 1, 1)
        for owner in self.required:
            self.row({self.x[unit, owner]: 1 for unit in self.units if (unit, owner) in self.x}, 1, None)
        for owner, subset in self.required_presence:
            self.row({self.x[unit, owner]: 1 for unit in subset if (unit, owner) in self.x}, 1, None)
        for (left, right, _), frontier in zip(self.edges, self.frontiers):
            for owner in self.eligible[left]:
                terms = {self.x[left, owner]: 1, frontier: -1}
                if (right, owner) in self.x:
                    terms[self.x[right, owner]] = -1
                self.row(terms, None, 0)  # Different endpoints force frontier=1.
            for owner in set(self.eligible[left]) & set(self.eligible[right]):
                self.row({frontier: 1, self.x[left, owner]: 1, self.x[right, owner]: 1}, None, 2)
            for a, b in self.prohibited_adj:
                for first, second in ((a, b), (b, a)):
                    if (left, first) in self.x and (right, second) in self.x:
                        self.row({self.x[left, first]: 1, self.x[right, second]: 1}, None, 1)
        self.adjacency_cache = {}
        groups = [(pair,) for pair in self.required_adj]
        groups.extend(tuple(tuple(sorted((owner, other))) for other in others)
                      for owner, others in self.required_any_adj)
        for pairs in groups:
            witnesses = {}
            for pair in pairs:
                witnesses.update(self.adjacency_witnesses(pair))
            self.row(witnesses, 1, None)
        self.evidence = {index: self.scores[unit][owner] for (unit, owner), index in self.x.items()}
        self.natural = {index: edge[2] for index, edge in zip(self.frontiers, self.edges)}

    def adjacency_witnesses(self, pair):
        """Reuse identical physical pair witnesses across AND/OR requirements."""
        if pair in self.adjacency_cache:
            return self.adjacency_cache[pair]
        witnesses = {}
        a, b = pair
        for (left, right, _), frontier in zip(self.edges, self.frontiers):
            if not (((left, a) in self.x and (right, b) in self.x)
                    or ((left, b) in self.x and (right, a) in self.x)):
                continue
            witness = self.variable(); witnesses[witness] = 1
            for unit in (left, right):
                terms = {witness: 1}
                terms.update({self.x[unit, owner]: -1 for owner in pair if (unit, owner) in self.x})
                self.row(terms, None, 0)
            self.row({witness: 1, frontier: -1}, None, 0)
        self.adjacency_cache[pair] = witnesses
        return witnesses

    def variable(self):
        if self.nvars >= MAX_VARIABLES:
            raise ValueError('assignment variable resource bound exceeded')
        self.nvars += 1
        return self.nvars-1

    def row(self, terms, lower, upper):
        terms = {key: value for key, value in terms.items() if value}
        key = (tuple(sorted(terms.items())), lower, upper)
        if key in self.row_keys:
            return False
        if len(self.rows) >= MAX_ROWS or self.nonzeros+len(terms) > MAX_NONZEROS:
            raise _Incomplete('CONSTRAINT_RESOURCE_BUDGET')
        if time.perf_counter() >= self.deadline:
            raise _Incomplete('TOTAL_TIME_BUDGET')
        self.row_keys.add(key); self.rows.append((terms, lower, upper)); self.nonzeros += len(terms)
        return True

    def integer_candidate(self, result, objective, phase):
        values = np.asarray(result.x, dtype=float)
        if values.shape != (self.nvars,) or not np.all(np.isfinite(values)):
            raise _Incomplete('NONFINITE_OR_MISSING_BINARY_SOLUTION')
        rounded = np.rint(values)
        if np.any(np.abs(values-rounded) > BINARY_ATOL) or np.any((rounded < 0) | (rounded > 1)):
            raise _Incomplete('NONBINARY_SOLVER_READBACK')
        bits = [int(v) for v in rounded]
        for terms, lower, upper in self.rows:
            value = sum(coefficient*bits[index] for index, coefficient in terms.items())
            if (lower is not None and value < lower) or (upper is not None and value > upper):
                raise _Incomplete('EXACT_INTEGER_CONSTRAINT_READBACK_FAILED')
        cost = -sum(value*bits[index] for index, value in objective.items())
        scale = max(1, sum(abs(value) for value in objective.values()))
        allowance = 128*EPS*scale
        if (result.fun is None or not math.isfinite(result.fun)
                or abs(float(result.fun)-cost) > allowance):
            raise _Incomplete('EXACT_INTEGER_OBJECTIVE_READBACK_FAILED')
        if phase != 'alternative':
            bound = getattr(result, 'mip_dual_bound', None)
            if (bound is None or not math.isfinite(bound) or allowance >= .25
                    or float(bound) > cost+allowance or cost-float(bound) >= 1-allowance):
                raise _Incomplete('INTEGER_OPTIMUM_NOT_CERTIFIED')
        assignment = {}
        for (unit, owner), index in self.x.items():
            if bits[index]:
                if unit in assignment:
                    raise _Incomplete('MULTIPLE_OWNERS_IN_READBACK')
                assignment[unit] = owner
        if set(assignment) != set(self.units) or not set(self.required) <= set(assignment.values()):
            raise _Incomplete('COVERAGE_OR_REQUIRED_OWNER_READBACK_FAILED')
        if any(not any(assignment[unit] == owner for unit in subset)
               for owner, subset in self.required_presence):
            raise _Incomplete('REQUIRED_PRESENCE_READBACK_FAILED')
        adjacency = {tuple(sorted((assignment[left], assignment[right])))
                     for left, right, _ in self.edges if assignment[left] != assignment[right]}
        if not set(self.required_adj) <= adjacency or set(self.prohibited_adj) & adjacency:
            raise _Incomplete('HARD_OWNER_ADJACENCY_READBACK_FAILED')
        if any(not any(tuple(sorted((owner, other))) in adjacency for other in others)
               for owner, others in self.required_any_adj):
            raise _Incomplete('REQUIRED_ANY_ADJACENCY_READBACK_FAILED')
        for (left, right, _), index in zip(self.edges, self.frontiers):
            if bits[index] != int(assignment[left] != assignment[right]):
                raise _Incomplete('FRONTIER_VARIABLE_READBACK_FAILED')
        return assignment, bits

    def disconnected_cuts(self, assignment):
        cuts = []
        for owner in self.connected:
            selected = {unit for unit in self.units if assignment[unit] == owner}
            remaining, components = set(selected), []
            while remaining:
                seed = min(remaining); component, stack = set(), [seed]
                while stack:
                    unit = stack.pop()
                    if unit not in remaining:
                        continue
                    remaining.remove(unit); component.add(unit)
                    stack.extend(sorted(self.neighbours[unit] & remaining, reverse=True))
                components.append(component)
            if len(components) <= 1:
                continue
            for component in components:
                inside, outside = min(component), min(selected-component)
                boundary = set().union(*(self.neighbours[unit] for unit in component))-component
                # If these two selected vertices are retained, any connected
                # owner path must leave this component via an owner vertex in
                # its physical neighbour set. Dropping a witness remains legal.
                terms = {self.x[inside, owner]: 1, self.x[outside, owner]: 1}
                terms.update({self.x[unit, owner]: -1 for unit in boundary if (unit, owner) in self.x})
                cuts.append(terms)
        return cuts

    def optimise(self, objective, phase):
        while True:
            remaining = self.deadline-time.perf_counter()
            if remaining <= 0 or len(self.calls) >= self.max_rounds+3:
                raise _Incomplete('TOTAL_TIME_OR_SOLVE_CALL_BUDGET')
            row_indices, col_indices, coefficients, lower, upper = [], [], [], [], []
            for row_index, (terms, lo, hi) in enumerate(self.rows):
                for index, coefficient in terms.items():
                    row_indices.append(row_index); col_indices.append(index); coefficients.append(coefficient)
                lower.append(-np.inf if lo is None else lo); upper.append(np.inf if hi is None else hi)
            matrix = coo_matrix((np.asarray(coefficients, dtype=float), (row_indices, col_indices)),
                                shape=(len(self.rows), self.nvars)).tocsc()
            cost = np.zeros(self.nvars)
            for index, value in objective.items():
                cost[index] = -value
            remaining = self.deadline-time.perf_counter()
            if remaining <= 0:
                raise _Incomplete('TOTAL_TIME_BUDGET')
            start = time.perf_counter()
            node_allowance = self.node_limit-self.nodes
            try:
                result = milp(cost, integrality=np.ones(self.nvars), bounds=Bounds(0, 1),
                    constraints=LinearConstraint(matrix, np.asarray(lower), np.asarray(upper)),
                    # Bundled HiGHS presolve returned an excluded assignment as
                    # optimal in the four-unit regression (no-good sum 4 > 3).
                    # Solve the unchanged rows directly; all proof/readback and
                    # global budget gates still apply.
                    options={'disp': False, 'presolve': False, 'mip_rel_gap': 0.,
                             'node_limit': node_allowance, 'time_limit': remaining})
            except (ValueError, RuntimeError, OverflowError) as error:
                self.nodes += node_allowance
                self.calls.append({'phase': phase, 'status': None, 'message': str(error),
                    'nodes': None, 'reported_nodes': None, 'charged_nodes': node_allowance,
                    'fun': None, 'mip_dual_bound': None,
                    'wall_seconds': time.perf_counter()-start})
                raise _Incomplete('SOLVER_EXCEPTION_NO_ACCEPTED_ASSIGNMENT') from error
            used = getattr(result, 'mip_node_count', None)
            valid_nodes = (isinstance(used, (int, np.integer))
                           and not isinstance(used, (bool, np.bool_)) and used >= 0)
            reported_nodes = int(used) if valid_nodes else None
            charged_nodes = reported_nodes if valid_nodes else node_allowance
            self.nodes += charged_nodes
            self.calls.append({'phase': phase, 'status': int(result.status),
                'message': str(result.message), 'nodes': reported_nodes,
                'reported_nodes': reported_nodes, 'charged_nodes': charged_nodes,
                'fun': _solver_number(getattr(result, 'fun', None)),
                'mip_dual_bound': _solver_number(getattr(result, 'mip_dual_bound', None)),
                'wall_seconds': time.perf_counter()-start})
            if used is not None and not valid_nodes:
                raise _Incomplete('UNVERIFIABLE_SOLVER_NODE_ACCOUNT')
            if time.perf_counter() >= self.deadline or self.nodes > self.node_limit:
                raise _Incomplete('TOTAL_TIME_OR_NODE_BUDGET')
            if result.status == 2:
                return None
            if result.status != 0 or not result.success:
                raise _Incomplete('SOLVER_DID_NOT_PROVE_OPTIMALITY_OR_INFEASIBILITY')
            if used is None:
                raise _Incomplete('UNVERIFIABLE_SOLVER_NODE_ACCOUNT')
            assignment, bits = self.integer_candidate(result, objective, phase)
            cuts = self.disconnected_cuts(assignment)
            if not cuts:
                return assignment, bits
            if self.cut_rounds >= self.max_rounds:
                raise _Incomplete('CONNECTIVITY_CUT_ROUND_BUDGET')
            added = sum(self.row(terms, None, 1) for terms in cuts)
            if not added:
                raise _Incomplete('CONNECTIVITY_CUT_PROGRESS_FAILED')
            self.cut_rounds += 1


def solve(problem):
    """Return {solution, diagnostics}; diagnostics must not enter science hashes.

Invalid schemas/ranges raise ValueError. Valid but infeasible hard constraints
return FAILED. UNKNOWN solver outcomes/budgets return INCOMPLETE, with no partial
assignment. MODELLED requires uniqueness at both exact integer maxima; a second
assignment yields POLYCENTRIC_UNRESOLVED, without a preferred assignment.
Its two canonical witnesses are retained; they are not an exhaustive enumeration.
Optional required_presence rows {owner, unit_ids} each require that owner in at
least one supplied unit. This is a hard occurrence constraint, not a quota or
objective. Omission is equivalent to an empty list.
Optional required_any_adjacency rows {owner, other_owners} each require a physical
frontier to at least one listed other owner. Omission means no such requirement.
"""
    started = time.perf_counter()
    data = _problem(deepcopy(problem))
    search, objectives = None, {'evidence': None, 'frontier_support': None}

    def finish(status, reason, assignment=None, alternatives=()):
        finished = time.perf_counter()
        if search is not None and finished >= search.deadline:
            status, reason, assignment = 'INCOMPLETE', 'TOTAL_TIME_BUDGET', None
        witnesses = []
        if status == 'POLYCENTRIC_UNRESOLVED':
            witnesses = [dict(sorted(row.items())) for row in alternatives]
            witnesses.sort(key=lambda row: tuple(row.items()))
        solution = {'schema': SCHEMA, 'status': status, 'assignment': assignment,
                    'objectives': deepcopy(objectives), 'reason': reason,
                    'alternatives': witnesses, 'alternatives_exhaustive': False}
        diagnostics = {'wall_seconds': finished-started,
            'solver_calls': [] if search is None else deepcopy(search.calls),
            'nodes_used': 0 if search is None else search.nodes,
            'cut_rounds': 0 if search is None else search.cut_rounds,
            'presolve': False,
            'binary_readback_atol': BINARY_ATOL,
            'method': 'INTEGER_EVIDENCE_THEN_FRONTIER_MAXIMA; VALID_CONNECTIVITY_CUTS; EXACT_OPTIMUM_ASSIGNMENT_EXCLUSION'}
        return {'solution': solution, 'diagnostics': diagnostics}

    if any(not row for row in data[2].values()):
        return finish('FAILED', 'UNIT_HAS_NO_ELIGIBLE_OWNER')
    if set(data[7]) & set(data[8]):
        return finish('FAILED', 'REQUIRED_AND_PROHIBITED_ADJACENCY_CONFLICT')
    try:
        search = _Search(data, started)
        first = search.optimise(search.evidence, 'evidence')
        if first is None:
            return finish('FAILED', 'HARD_CONSTRAINTS_INFEASIBLE')
        objectives['evidence'] = sum(value*first[1][index] for index, value in search.evidence.items())
        search.row(search.evidence, objectives['evidence'], objectives['evidence'])
        second = search.optimise(search.natural, 'frontier')
        if second is None:
            return finish('INCOMPLETE', 'SECONDARY_INFEASIBLE_AFTER_PRIMARY_WITNESS')
        objectives['frontier_support'] = sum(value*second[1][index] for index, value in search.natural.items())
        search.row(search.natural, objectives['frontier_support'], objectives['frontier_support'])
        chosen = second[0]
        search.row({search.x[unit, owner]: 1 for unit, owner in chosen.items()}, None, len(search.units)-1)
        alternative = search.optimise({}, 'alternative')
        if alternative is not None:
            if alternative[0] == chosen:
                return finish('INCOMPLETE', 'ASSIGNMENT_EXCLUSION_READBACK_FAILED')
            return finish('POLYCENTRIC_UNRESOLVED', 'MULTIPLE_ASSIGNMENTS_AT_BOTH_OPTIMA',
                          alternatives=(chosen, alternative[0]))
        return finish('MODELLED', 'UNIQUE_AT_BOTH_INTEGER_OPTIMA', dict(sorted(chosen.items())))
    except _Incomplete as error:
        return finish('INCOMPLETE', str(error))
