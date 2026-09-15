"""Declared snapshot occupancy and finite seasonal transfers, not population history.

No calibrated coefficients, species traits, actual-cover fractions, density,
travel costs, receiving capacity or origin populations are supplied by this module.
"""
from dataclasses import asdict, dataclass
from fractions import Fraction as F
import hashlib
import heapq
import json
import math

KNOWN = frozenset(('CANON', 'WORKING NON-CANON', 'SYNTHETIC TEST', 'MODELLED'))
UNKNOWN = frozenset(('UNKNOWN', 'CONFLICT', 'INCOMPLETE', 'Review-only', 'Provisional'))


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError(name + ': bounded explicit text required')
    return value


def _source(evidence, status):
    _text(evidence, 'evidence')
    if type(status) is not str or status not in KNOWN | UNKNOWN:
        raise ValueError('unrecognised source status')


def _q(value, name, *, maximum=F(10**18), signed=False, positive=False, nullable=False):
    if value is None and nullable:
        return None
    if type(value) not in (int, float, F):
        raise ValueError(name + ': explicit finite number required')
    if type(value) is float and not math.isfinite(value):
        raise ValueError(name + ': nonfinite number')
    f = F(value)
    if max(f.numerator.bit_length(), f.denominator.bit_length()) > 4096:
        raise ValueError(name + ': numeric representation exceeds bounded support')
    if abs(f) > maximum or (not signed and f < 0) or (positive and f <= 0):
        raise ValueError(name + ': outside supported range')
    if f and float(f) == 0:
        raise ValueError(name + ': positive magnitude cannot underflow')
    return f


def quantity(value):
    if value is None:
        return None
    f = F(value)
    value = float(f)
    if not math.isfinite(value) or (f and not value):
        raise ArithmeticError('output quantity not representable')
    return {'exact': str(f), 'value': value}


def plain(value):
    if isinstance(value, F): return str(value)
    if isinstance(value, (Cell, Edge, Origin, SpeciesRule, MovementRequest, PrescribedTotal, ExplicitStock)):
        return plain(asdict(value))
    if type(value) is dict:
        if any(type(k) is not str for k in value): raise ValueError('string keys required')
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [plain(v) for v in value]
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Cell:
    cell_id: str
    area_m2: F
    habitat_support: float | None
    habitat_fraction: F | None
    traversable: bool | None
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.cell_id, 'cell identity'); _source(self.evidence, self.source_status)
        _q(self.area_m2, 'physical area', positive=True)
        _q(self.habitat_support, 'habitat support', maximum=F(1), nullable=True)
        _q(self.habitat_fraction, 'habitat fraction', maximum=F(1), nullable=True)
        if self.traversable is not None and type(self.traversable) is not bool:
            raise ValueError('traversability must be explicit bool or UNKNOWN')


@dataclass(frozen=True)
class Edge:
    edge_id: str
    source: str
    target: str
    travel_cost: F | None
    enabled: bool | None
    capacity_expected_individuals: F | None
    evidence: str
    source_status: str

    def __post_init__(self):
        for k in ('edge_id', 'source', 'target'): _text(getattr(self, k), k)
        if self.source == self.target: raise ValueError('self edges are not movement corridors')
        _source(self.evidence, self.source_status)
        _q(self.travel_cost, 'edge cost', nullable=True)
        _q(self.capacity_expected_individuals, 'finite seasonal corridor capacity', nullable=True)
        if self.enabled is not None and type(self.enabled) is not bool:
            raise ValueError('barrier state must be explicit bool or UNKNOWN')


@dataclass(frozen=True)
class Origin:
    cell_id: str
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.cell_id, 'origin identity'); _source(self.evidence, self.source_status)


@dataclass(frozen=True)
class SpeciesRule:
    species_id: str
    suitability_minimum: float | None
    logit_intercept: float | None
    logit_slope: float | None
    conditional_occupied_fraction: F | None
    density_per_occupied_m2: F | None
    travel_budget: F | None
    travel_unit: str
    movement_mode: str
    evidence: str
    source_status: str

    def __post_init__(self):
        _text(self.species_id, 'species identity'); _source(self.evidence, self.source_status)
        for k in ('suitability_minimum', 'conditional_occupied_fraction'):
            _q(getattr(self, k), k, maximum=F(1), nullable=True)
        for k in ('logit_intercept', 'logit_slope'):
            _q(getattr(self, k), k, maximum=F(1000), signed=True, nullable=True)
        _q(self.density_per_occupied_m2, 'expected individuals per occupied square metre', nullable=True)
        _q(self.travel_budget, 'travel budget', nullable=True)
        _text(self.travel_unit, 'travel unit')
        if self.travel_unit not in ('s', 'm') and not self.travel_unit.startswith('RESISTANCE:'):
            raise ValueError('travel unit must be s, m or explicitly named RESISTANCE:...')
        if self.travel_unit == 'RESISTANCE:': raise ValueError('resistance unit needs a definition')
        if self.movement_mode not in ('NONMOVING', 'SEASONAL_MOVEMENT', 'UNKNOWN'):
            raise ValueError('explicit movement applicability required')


@dataclass(frozen=True)
class PrescribedTotal:
    expected_individuals: F
    evidence: str
    source_status: str

    def __post_init__(self):
        _q(self.expected_individuals, 'authorised prescribed total')
        _source(self.evidence, self.source_status)


@dataclass(frozen=True)
class ExplicitStock:
    species_id: str
    counting_unit: str
    cohort_id: str
    scope_id: str
    snapshot_id: str
    phase_id: str
    counts: tuple
    evidence: str
    source_status: str

    def __post_init__(self):
        for key in ('species_id','counting_unit','cohort_id','scope_id','snapshot_id','phase_id'): _text(getattr(self,key),key)
        _source(self.evidence,self.source_status)
        if type(self.counts) is not tuple or not 1<=len(self.counts)<=128: raise ValueError('immutable complete explicit stock tuple required')
        seen=set()
        for pair in self.counts:
            if type(pair) is not tuple or len(pair)!=2: raise ValueError('immutable cell/count pair required')
            _text(pair[0],'stock cell')
            if pair[0] in seen: raise ValueError('duplicate explicit stock cell')
            seen.add(pair[0]); _q(pair[1],'explicit departure count',nullable=True)
        object.__setattr__(self,'counts',tuple(sorted(self.counts)))


@dataclass(frozen=True)
class MovementRequest:
    request_id: str
    source: str
    target: str
    expected_individuals: F | None
    priority: int
    evidence: str
    source_status: str

    def __post_init__(self):
        for k in ('request_id', 'source', 'target'): _text(getattr(self, k), k)
        if self.source == self.target: raise ValueError('stationary stock is not a movement request')
        _q(self.expected_individuals, 'requested expected-individual transfer', nullable=True)
        if type(self.priority) is not int or not 0 <= self.priority <= 10**9:
            raise ValueError('explicit bounded integer priority required')
        _source(self.evidence, self.source_status)


def _inputs(cells, edges, origins, rule, season_id):
    if type(rule) is not SpeciesRule: raise ValueError('actual SpeciesRule required')
    _text(season_id, 'season identity')
    if type(cells) is not tuple or not 1 <= len(cells) <= 128 or any(type(c) is not Cell for c in cells):
        raise ValueError('one to 128 actual physical cells required')
    if type(edges) is not tuple or len(edges) > 4096 or any(type(e) is not Edge for e in edges):
        raise ValueError('bounded explicit directed edges required')
    if origins is not None and (type(origins) is not tuple or any(type(o) is not Origin for o in origins)):
        raise ValueError('explicit origin tuple or UNKNOWN required')
    cs = {c.cell_id: c for c in cells}; es = {e.edge_id: e for e in edges}
    if len(cs) != len(cells) or len(es) != len(edges): raise ValueError('duplicate cell or edge identity')
    if any(e.source not in cs or e.target not in cs for e in edges): raise ValueError('unknown edge endpoint')
    if origins is not None:
        if len({o.cell_id for o in origins}) != len(origins): raise ValueError('duplicate origin')
        if any(o.cell_id not in cs for o in origins): raise ValueError('unknown origin cell')
    return cs, es


def _passable(cell, optimistic):
    if cell.source_status in KNOWN:
        return cell.traversable is not False if optimistic else cell.traversable is True
    return optimistic


def _edges(cs, es, optimistic, residual=None):
    adjacency = {k: [] for k in cs}
    for e in sorted(es.values(), key=lambda v: v.edge_id):
        if not _passable(cs[e.source], optimistic) or not _passable(cs[e.target], optimistic): continue
        known = e.source_status in KNOWN
        if known and (e.enabled is False or e.capacity_expected_individuals == 0): continue
        if not optimistic and (not known or e.enabled is not True or e.travel_cost is None or e.capacity_expected_individuals is None): continue
        if residual is not None and residual[e.edge_id] <= 0: continue
        # Unknown edge costs are zero ONLY in the optimistic lower-bound graph;
        # this certifies possible access, never a realised path or transfer.
        cost = F(e.travel_cost) if known and e.travel_cost is not None else F()
        adjacency[e.source].append((e.target, e.edge_id, cost))
    return adjacency


def _distances(adjacency, starts):
    """Exact nonnegative shortest paths; lexicographic edge-ID tie policy."""
    best = {}; heap = []
    for start in sorted(starts):
        best[start] = (F(), ())
        heapq.heappush(heap, (F(), (), start, (start,)))
    while heap:
        cost, path, node, visited = heapq.heappop(heap)
        if best.get(node) != (cost, path): continue
        for target, edge, weight in adjacency[node]:
            if target in visited: continue
            key = (cost+weight, path+(edge,))
            if target not in best or key < best[target]:
                best[target] = key
                heapq.heappush(heap, (*key, target, visited+(target,)))
    return best


def evaluate_range(cells, edges, origins, rule, *, season_id, prescribed_total=None):
    """Separate suitability, accessibility, occurrence probability and abundance.

    Origins delimit a declared accessibility scenario; they are not evidence of
    certain occupancy or a reconstruction of dispersal time/history. A logistic
    occurrence law must be supplied/calibrated at this physical cell support.
    """
    cs, es = _inputs(cells, edges, origins, rule, season_id)
    if prescribed_total is not None and type(prescribed_total) is not PrescribedTotal:
        raise ValueError('explicit PrescribedTotal or no total constraint required')
    known_origins = [] if origins is None else [o.cell_id for o in origins if o.source_status in KNOWN and _passable(cs[o.cell_id], False)]
    possible_origins = [k for k, c in cs.items() if _passable(c, True)] if origins is None else [o.cell_id for o in origins if _passable(cs[o.cell_id], True)]
    known_paths = _distances(_edges(cs, es, False), known_origins)
    possible_paths = _distances(_edges(cs, es, True), possible_origins)
    budget = None if rule.source_status not in KNOWN else _q(rule.travel_budget, 'budget', nullable=True)
    rows = {}
    for ident, c in sorted(cs.items()):
        kp, pp = known_paths.get(ident), possible_paths.get(ident)
        if budget is not None and kp is not None and kp[0] <= budget:
            access = 'ACCESSIBLE'
        elif pp is None or (budget is not None and pp[0] > budget):
            access = 'INACCESSIBLE'
        else: access = 'UNKNOWN'
        known = c.source_status in KNOWN and rule.source_status in KNOWN
        support = float(c.habitat_support) if known and c.habitat_support is not None else None
        fraction = F(c.habitat_fraction) if known and c.habitat_fraction is not None else None
        threshold = rule.suitability_minimum if rule.source_status in KNOWN else None
        habitat = ('FAIL' if fraction == 0 or (support is not None and threshold is not None and support < threshold)
                   else 'PASS' if support is not None and fraction is not None and threshold is not None else 'UNKNOWN')
        probability = None; occupied_fraction = None; area = None; individuals = None; numerical = False
        conditional_abundance = None; abundance_reason = None
        if access == 'INACCESSIBLE' or habitat == 'FAIL' or (rule.source_status in KNOWN and rule.conditional_occupied_fraction == 0):
            probability = 0.; occupied_fraction = area = individuals = F()
        elif access == 'ACCESSIBLE' and habitat == 'PASS' and rule.logit_intercept is not None and rule.logit_slope is not None:
            z = float(rule.logit_intercept)+float(rule.logit_slope)*support
            exp = math.exp(-abs(z))
            probability = 1/(1+exp) if z >= 0 else exp/(1+exp)
            if not 0 < probability < 1:
                probability = None; numerical = True
            elif rule.conditional_occupied_fraction is not None:
                occupied_fraction = fraction*F(rule.conditional_occupied_fraction)*F(probability)
                area = F(c.area_m2)*occupied_fraction
                if rule.density_per_occupied_m2 is not None:
                    conditional_abundance = F(c.area_m2)*fraction*F(rule.conditional_occupied_fraction)*F(rule.density_per_occupied_m2)
                    if conditional_abundance < 1:
                        abundance_reason = 'E[N | occupied] must be at least one biological individual at this cell support'
                    else:
                        individuals = area*F(rule.density_per_occupied_m2)
        rows[ident] = {'cell_id': ident, 'area_m2': quantity(c.area_m2),
            'habitat_support': support, 'habitat_status': habitat,
            'accessibility': {'status': access, 'least_cost': quantity(kp[0]) if kp else None,
                              'path_edge_ids': list(kp[1]) if kp else None, 'travel_unit': rule.travel_unit,
                              'optimistic_lower_cost': quantity(pp[0]) if pp else None},
            'occupancy_status': 'NUMERICAL_FAILURE' if numerical else 'UNKNOWN' if probability is None or area is None else 'MODELLED',
            'occupancy_probability': probability, 'expected_occupied_fraction': quantity(occupied_fraction),
            'expected_occupied_area_m2': quantity(area), 'expected_individuals': quantity(individuals),
            'abundance_status': 'NUMERICAL_FAILURE' if numerical else 'OUTSIDE_REGIME' if abundance_reason else 'UNKNOWN' if individuals is None else 'MODELLED',
            'conditional_expected_individuals_if_occupied': quantity(conditional_abundance), 'abundance_reason': abundance_reason,
            'realised_occupied_fraction': None, 'observed_individuals': None, 'active_bonds': None,
            'evidence': c.evidence, 'source_status': c.source_status}
    unknown = any(r['expected_individuals'] is None for r in rows.values())
    partial = sum((F(r['expected_individuals']['exact']) for r in rows.values() if r['expected_individuals'] is not None), F())
    total = None if unknown else partial
    constraint = {'status': 'NOT_REQUESTED', 'prescribed': None, 'difference': None}
    if prescribed_total is not None:
        difference = None if total is None else total-F(prescribed_total.expected_individuals)
        constraint = {'status': 'UNKNOWN' if total is None or prescribed_total.source_status not in KNOWN else 'MATCH' if not difference else 'CONFLICT',
                      'prescribed': plain(prescribed_total), 'difference': quantity(difference)}
    status = ('NUMERICAL_FAILURE' if any(r['occupancy_status'] == 'NUMERICAL_FAILURE' for r in rows.values())
              else 'CONFLICT' if constraint['status'] == 'CONFLICT' else 'UNKNOWN' if unknown or constraint['status'] == 'UNKNOWN' else 'MODELLED')
    inputs = {'cells': sorted(cells, key=lambda v: v.cell_id), 'edges': sorted(edges, key=lambda v: v.edge_id),
              'origins': None if origins is None else sorted(origins, key=lambda v: v.cell_id),
              'rule': rule, 'season_id': season_id, 'prescribed_total': prescribed_total}
    return {'schema': 'diadem.spatial-snapshot.r9', 'status': status, 'species_id': rule.species_id,
            'season_id': season_id, 'cells': rows, 'total_expected_individuals': quantity(total),
            'known_subtotal_expected_individuals': quantity(partial), 'prescribed_total_check': constraint,
            'inputs_sha256': _digest(inputs), 'inputs': plain(inputs),
            'scope': 'conditional snapshot expectation at supplied cell support; no realised census, historical colonisation, carrying-capacity certification, food biomass or bonds'}


def route_movements(cells, edges, origins, rule, requests, *, season_id,
                    receiving_capacity, evidence, source_status, prescribed_total=None,
                    destination_cells=None, destination_edges=None, destination_origins=None,
                    destination_rule=None, destination_season_id=None, destination_prescribed_total=None,
                    declared_departure_stock=None):
    """Feasible, explicitly prioritised seasonal allocation, NOT a flow optimum.

    Source stock comes from the actual range function. Receiving capacity is an
    independently supplied finite number of ADDITIONAL expected-individual places.
    Arrivals cannot be retransmitted. Residual edge capacities are shared by all
    requests in this call; separate species/calls are counterfactual unless an
    external owner explicitly partitions their shared capacities.
    """
    cs, es = _inputs(cells, edges, origins, rule, season_id)
    _source(evidence, source_status)
    if type(requests) is not tuple or len(requests) > 512 or any(type(r) is not MovementRequest for r in requests):
        raise ValueError('bounded explicit MovementRequest tuple required')
    if len({r.request_id for r in requests}) != len(requests) or len({r.priority for r in requests}) != len(requests):
        raise ValueError('unique request identities and explicit priorities required')
    if any(r.source not in cs or r.target not in cs for r in requests): raise ValueError('unknown movement endpoint')
    if type(receiving_capacity) is not dict or set(receiving_capacity) != set(cs):
        raise ValueError('complete explicit additional receiving capacities required')
    capacity = {k: _q(v, 'additional receiving places', nullable=True) for k, v in receiving_capacity.items()}
    result = evaluate_range(cells, edges, origins, rule, season_id=season_id, prescribed_total=prescribed_total)
    if destination_season_id is None:
        if any(v is not None for v in (destination_cells, destination_edges, destination_origins, destination_rule, destination_prescribed_total)):
            raise ValueError('arrival scenario requires explicit destination season identity')
        destination = result; destination_map = cs; arrival_rule = rule
    else:
        destination = evaluate_range(destination_cells, destination_edges, destination_origins,
                                     destination_rule, season_id=destination_season_id,
                                     prescribed_total=destination_prescribed_total)
        destination_map = {c.cell_id: c for c in destination_cells}
        arrival_rule = destination_rule
        if destination_rule.species_id != rule.species_id or set(destination_map) != set(cs):
            raise ValueError('departure and arrival species/cell identities must match')
        if any(F(c.area_m2) != F(destination_map[k].area_m2) for k, c in cs.items()):
            raise ValueError('arrival geometry differs; no implicit spatial remapping')
    explicit_invalid=False
    if declared_departure_stock is not None:
        value=declared_departure_stock
        if type(value) is not ExplicitStock or value.species_id!=rule.species_id or value.phase_id!=season_id or set(dict(value.counts))!=set(cs):
            raise ValueError('complete matching explicit cohort/phase stock required')
        # This is a different abundance mode, not a density back-solve. No unused
        # probability/density scenario may silently override or veto its counts.
        if prescribed_total is not None or destination_prescribed_total is not None or any(getattr(r,k) is not None for r in (rule,arrival_rule) for k in ('logit_intercept','logit_slope','conditional_occupied_fraction','density_per_occupied_m2')):
            raise ValueError('explicit-stock routing requires density-free phase rules and no independent total reconciliation')
        explicit_invalid=value.source_status not in KNOWN or any(n is not None and n>0 and
            (result['cells'][k]['habitat_status']!='PASS' or result['cells'][k]['accessibility']['status']!='ACCESSIBLE') for k,n in value.counts)
    movement_inputs = {'departure_range_inputs_sha256': result['inputs_sha256'],
        'arrival_range_inputs_sha256': destination['inputs_sha256'],
        'requests': sorted(requests, key=lambda r: r.priority), 'receiving_capacity': capacity,
        'evidence': evidence, 'source_status': source_status}
    if declared_departure_stock is not None: movement_inputs['declared_departure_stock']=declared_departure_stock
    base = {'schema': 'diadem.seasonal-transfer.r9', 'species_id': rule.species_id, 'season_id': season_id,
            'range_inputs_sha256': result['inputs_sha256'], 'evidence': evidence, 'source_status': source_status,
            'destination_range_inputs_sha256': destination['inputs_sha256'],
            'destination_season_id': destination['season_id'], 'movement_inputs_sha256': _digest(movement_inputs),
            'policy': 'EXPLICIT_PRIORITY_THEN_LEAST_COST_RESIDUAL_PATH; unmet is not a global infeasibility certificate',
            'receiving_capacity': {k: quantity(v) for k, v in sorted(capacity.items())}}
    if declared_departure_stock is not None:
        base['declared_departure_stock']=plain(declared_departure_stock)
        base['stock_basis']='explicit allocated cohort stock; no density/probability back-solve'
    if rule.movement_mode == 'NONMOVING' and rule.source_status in KNOWN and source_status in KNOWN:
        if requests: raise ValueError('nonmoving applicability cannot contain movement requests')
        return {**base, 'status': 'NOT_APPLICABLE', 'requests': [], 'paths': [], 'cells': None, 'edges': None,
                'reason': 'explicit nonmoving life-stage; propagule dispersal requires a separately supplied model'}
    reconciliation_unresolved = any(r['prescribed_total_check']['status'] in ('UNKNOWN', 'CONFLICT') for r in (result, destination))
    if (rule.movement_mode == 'UNKNOWN' or rule.source_status not in KNOWN or source_status not in KNOWN
            or any(r['status'] in ('CONFLICT', 'NUMERICAL_FAILURE') for r in (result, destination)) or reconciliation_unresolved or explicit_invalid):
        return {**base, 'status': 'UNKNOWN', 'requests': None, 'paths': [], 'cells': None, 'edges': None,
                'reason': 'movement applicability/source or departure/arrival stock reconciliation unresolved',
                'departure_total_check': result['prescribed_total_check'], 'arrival_total_check': destination['prescribed_total_check']}
    stock = {k: None if r['expected_individuals'] is None else F(r['expected_individuals']['exact']) for k, r in result['cells'].items()}
    if declared_departure_stock is not None:
        stock={k:None if n is None else F(n) for k,n in declared_departure_stock.counts}
    remaining = dict(stock); places = dict(capacity)
    residual = {k: F(e.capacity_expected_individuals) if e.source_status in KNOWN and e.capacity_expected_individuals is not None else F() for k, e in es.items()}
    original_edges = dict(residual)
    outgoing = {k: F() for k in cs}; incoming = {k: F() for k in cs}; paths = []; rows = []
    for request in sorted(requests, key=lambda r: r.priority):
        requested = _q(request.expected_individuals, 'requested expected individuals', nullable=True)
        source, target = request.source, request.target
        target_row = destination['cells'][target]
        endpoint_unknown = any(c.source_status not in KNOWN or c.traversable is None
                               for c in (cs[source], cs[target], destination_map[target]))
        endpoint_blocked = any(c.source_status in KNOWN and c.traversable is False
                               for c in (cs[source], cs[target], destination_map[target]))
        # Zero conditional footprint is a declared structural exclusion, unlike
        # zero current occupancy caused only by the arrival accessibility origins.
        # An actual transfer can change access, but cannot overrule this footprint.
        endpoint_blocked = endpoint_blocked or (arrival_rule.source_status in KNOWN and arrival_rule.conditional_occupied_fraction == 0)
        uncertain = (request.source_status not in KNOWN or requested is None or remaining[source] is None
                     or places[target] is None or rule.travel_budget is None
                     or target_row['habitat_status'] == 'UNKNOWN' or endpoint_unknown
                     or target_row['abundance_status'] == 'OUTSIDE_REGIME')
        fulfilled = F(); detail = []
        if not uncertain and not endpoint_blocked and target_row['habitat_status'] == 'PASS':
            left = min(requested, remaining[source], places[target])
            while left > 0:
                shortest = _distances(_edges(cs, es, False, residual), [source]).get(target)
                if shortest is None or shortest[0] > F(rule.travel_budget): break
                cost, path = shortest
                amount = min(left, *(residual[k] for k in path))
                if amount <= 0: raise ArithmeticError('nonpositive path allocation')
                record = {'request_id': request.request_id, 'source': source, 'target': target,
                          'edge_ids': list(path), 'travel_cost': quantity(cost), 'travel_unit': rule.travel_unit,
                          'expected_individuals': quantity(amount)}
                paths.append(record); detail.append(len(paths)-1)
                for edge in path: residual[edge] -= amount
                remaining[source] -= amount; places[target] -= amount
                outgoing[source] += amount; incoming[target] += amount
                fulfilled += amount; left -= amount
        unmet = None if requested is None else requested-fulfilled
        # Unknown paths may explain policy-unmet demand: preserve this without
        # using optimistic edges to create transfers. Known structural barriers
        # remain policy-unmet, not a statement about all possible route policies.
        optimistic_residual = {k: residual[k] if e.source_status in KNOWN and e.capacity_expected_individuals is not None else F(1)
                               for k, e in es.items()}
        possible = _distances(_edges(cs, es, True, optimistic_residual), [source]).get(target)
        possible_unknown = (unmet is not None and unmet > 0 and possible is not None
                            and (rule.travel_budget is None or possible[0] <= F(rule.travel_budget))
                            and (any(es[k].source_status not in KNOWN or es[k].travel_cost is None or es[k].enabled is None or es[k].capacity_expected_individuals is None for k in possible[1])
                                 or any(cs[es[k].target].source_status not in KNOWN or cs[es[k].target].traversable is None for k in possible[1])))
        state = 'UNKNOWN' if uncertain or possible_unknown else 'FULFILLED' if unmet == 0 else 'POLICY_UNMET'
        rows.append({'request_id': request.request_id, 'source': source, 'target': target,
                     'priority': request.priority, 'status': state,
                     'requested_expected_individuals': quantity(requested), 'transferred_expected_individuals': quantity(fulfilled),
                     'unmet_expected_individuals': quantity(unmet), 'path_indices': detail,
                     'evidence': request.evidence, 'source_status': request.source_status})
    cell_rows = {}
    persistence=[]
    for ident in sorted(cs):
        final = None if stock[ident] is None else stock[ident]-outgoing[ident]+incoming[ident]
        if stock[ident] is not None and outgoing[ident] > stock[ident]: raise ArithmeticError('source stock exceeded')
        if capacity[ident] is not None and incoming[ident] > capacity[ident]: raise ArithmeticError('receiving capacity exceeded')
        cell_rows[ident] = {'initial_expected_individuals': quantity(stock[ident]), 'outgoing_expected_individuals': quantity(outgoing[ident]),
            'incoming_expected_individuals': quantity(incoming[ident]), 'final_expected_individuals': quantity(final),
            'unused_receiving_capacity': quantity(places[ident])}
        if declared_departure_stock is not None:
            arrival=destination['cells'][ident]; physical=destination_map[ident]
            state=('NOT_APPLICABLE_ZERO_COMMITTED_STOCK' if final==0 else 'UNKNOWN' if final is None else
                'CONFLICT' if arrival['habitat_status']=='FAIL' or physical.source_status in KNOWN and physical.traversable is False else
                'PASS' if arrival['habitat_status']=='PASS' and physical.source_status in KNOWN and physical.traversable is True else 'UNKNOWN')
            cell_rows[ident]['arrival_persistence_status']=state; persistence.append(state)
    if sum(outgoing.values(), F()) != sum(incoming.values(), F()): raise ArithmeticError('movement conservation failure')
    edge_rows = {k: {'used_expected_individuals': quantity(original_edges[k]-residual[k]),
                    'remaining_expected_individuals': quantity(residual[k]) if es[k].source_status in KNOWN and es[k].capacity_expected_individuals is not None else None,
                    'source': es[k].source, 'target': es[k].target} for k in sorted(es)}
    return {**base, 'status': 'CONFLICT' if 'CONFLICT' in persistence else 'UNKNOWN' if 'UNKNOWN' in persistence or any(r['status'] == 'UNKNOWN' for r in rows) else 'MODELLED_FEASIBLE_ALLOCATION',
            'requests': rows, 'paths': paths, 'cells': cell_rows, 'edges': edge_rows,
            'transfer_conservation_residual_expected_individuals': quantity(F()),
            'scope': 'one finite transfer expectation; no births/deaths, actual animal tracks, food conversion, evolutionary gene flow or optimal multi-origin routing'}
