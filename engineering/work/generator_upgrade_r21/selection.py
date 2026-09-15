"""Exact bounded choice among supplied complete, whole-plot crop sequences.

No yield, suitability, diet, geometry or water availability is inferred here.
The producer validates disjoint plot geometry and each plan's internal calendar
and soil-water continuity. This feasible set is NOT the old continuous-strip LP.
Resource rows may overlap (daily caps and cumulative storage prefixes); each is
enforced independently, and their reported usages must never be summed as stock.
"""
from fractions import Fraction as F
import time


SCHEMA = 'diadem.whole-plot-season-plan-selection.r21'
MAX_PLOTS, MAX_PLANS, MAX_RESOURCES, MAX_USES = 32, 256, 4096, 65536
MAX_BITS, MAX_NUMERIC_CHARACTERS = 8192, 4*1024*1024


class _Incomplete(Exception):
    pass


def _label(value):
    if type(value) is not str or not value.strip() or len(value) > 1024:
        raise ValueError('bounded nonblank plot/plan/resource identity required')
    return value


def _bounded(value):
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS:
        raise _Incomplete('exact-arithmetic resource envelope exceeded; no rounding accepted')
    return value


def _sum(values):
    result = F(0)
    for value in values:
        result = _bounded(result+value)
    return result


def _read(problem):
    if type(problem) is not dict or set(problem) != {'plots', 'plans', 'resources', 'limits'}:
        raise ValueError('exact whole-plot selection problem fields required')
    limits = problem['limits']
    if type(limits) is not dict or set(limits) != {'node_limit', 'time_limit_s'}:
        raise ValueError('explicit global node/time limits required')
    if type(limits['node_limit']) is not int or not 1 <= limits['node_limit'] <= 1000000:
        raise ValueError('node_limit must be an integer in 1..1000000')
    seconds = limits['time_limit_s']
    if type(seconds) not in (int, float) or not 0 < seconds <= 300:
        raise ValueError('time_limit_s must be finite and in (0,300]')
    numeric_characters = 0

    def quantity(raw, *, positive=False):
        nonlocal numeric_characters
        if type(raw) is not str or not 1 <= len(raw) <= 5000:
            raise ValueError('canonical nonnegative rational string required')
        numeric_characters += len(raw)
        if numeric_characters > MAX_NUMERIC_CHARACTERS:
            raise ValueError('bounded numeric input representation exceeded')
        try:
            value = F(raw)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError('canonical nonnegative rational string required') from exc
        if (str(value) != raw or value < 0 or (positive and not value) or
                max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_BITS):
            raise ValueError('noncanonical, negative, zero area or overlarge rational input')
        return value

    raw_plots = problem['plots']
    if type(raw_plots) is not list or not 1 <= len(raw_plots) <= MAX_PLOTS:
        raise ValueError('reference requires 1..32 whole physical plots')
    plots = {}
    for row in raw_plots:
        if type(row) is not dict or set(row) != {'id', 'area_m2'}:
            raise ValueError('each plot requires exactly id and positive area_m2')
        identity = _label(row['id'])
        if identity in plots:
            raise ValueError('duplicate plot would count land twice')
        plots[identity] = quantity(row['area_m2'], positive=True)
    plots = dict(sorted(plots.items()))
    raw_resources = problem['resources']
    if type(raw_resources) is not dict or len(raw_resources) > MAX_RESOURCES:
        raise ValueError('bounded explicit finite resource-capacity map required')
    resources = {_label(identity): quantity(value) for identity, value in raw_resources.items()}
    resources = dict(sorted(resources.items()))
    resource_index = {identity: i for i, identity in enumerate(resources)}
    raw_plans = problem['plans']
    if type(raw_plans) is not list or not 1 <= len(raw_plans) <= MAX_PLANS:
        raise ValueError('reference requires 1..256 explicitly supplied complete plans')
    plans, choices, count = {}, {plot: [] for plot in plots}, 0
    for row in raw_plans:
        if type(row) is not dict or set(row) != {'id', 'plot_id', 'cultivated', 'energy_kcal', 'resource_use'}:
            raise ValueError('exact complete plan id/plot/cultivation/energy/resource fields required')
        identity, plot = _label(row['id']), _label(row['plot_id'])
        if identity in plans or plot not in plots:
            raise ValueError('unique plan and existing physical parent plot required')
        if type(row['cultivated']) is not bool:
            raise ValueError('explicit whole-plot cultivation flag required')
        energy = quantity(row['energy_kcal'])
        use = row['resource_use']
        if type(use) is not dict or len(use) > MAX_RESOURCES:
            raise ValueError('explicit bounded plan resource-use map required')
        count += len(use)
        if count > MAX_USES:
            raise ValueError('reference resource coefficient count exceeded')
        uses = []
        for resource, raw in use.items():
            resource = _label(resource)
            if resource not in resources:
                raise ValueError('plan uses an undeclared resource; missing availability is not zero')
            amount = quantity(raw)
            if amount:
                uses.append((resource_index[resource], amount))
        uses.sort()
        if not row['cultivated'] and (energy or uses):
            raise ValueError('explicit no-cultivation plan must have zero food energy and withdrawals')
        plan = {'id': identity, 'plot_id': plot, 'cultivated': row['cultivated'],
                'energy': energy, 'uses': tuple(uses)}
        plans[identity] = plan; choices[plot].append(plan)
    for plot, candidates in choices.items():
        if sum(not plan['cultivated'] for plan in candidates) != 1:
            raise ValueError('each plot needs exactly one explicit zero-use fallow/no-cultivation plan')
        # Enumeration order only. Ties are retained, never resolved by an ID.
        candidates.sort(key=lambda plan: (-plan['energy'], plan['id']))
    return plots, resources, plans, choices, {
        'node_limit': limits['node_limit'], 'time_limit_s': float(seconds)}


def solve(problem):
    """Return {solution, diagnostics} with exact rational scientific quantities.

Each plan covers its entire physical parent once; one and only one complete plan
is selected for each plot. Resource coefficients are TOTAL amounts for that plan,
not intensities to be multiplied by area again. Omitted use-map entries explicitly
mean zero, never an unknown requirement. MODELLED requires exhaustive proof via
enumeration or exact upper-bound pruning; ties yield ALLOCATION_UNRESOLVED.
"""
    started = time.perf_counter()
    plots, resources, plans, choices, limits = _read(problem)
    deadline = started+limits['time_limit_s']
    identities = list(plots)
    capacity = list(resources.values())
    used = [F(0)]*len(resources)
    nodes = examined_plans = resource_prunes = energy_prunes = 0
    best, witnesses, suffix, physical_area = None, [], None, None
    selected = {}

    def check_time():
        if time.perf_counter() >= deadline:
            raise _Incomplete('global elapsed-time budget exhausted')

    def witness(selection):
        # Recompute from original plans, independently of mutable search state.
        if set(selection) != set(plots) or len(set(selection.values())) != len(plots):
            raise ArithmeticError('complete exactly-once whole-plot selection readback failed')
        amounts = [F(0)]*len(resources)
        rows, energy_values, cultivated_areas = [], [], []
        for plot in identities:
            plan = plans[selection[plot]]
            if plan['plot_id'] != plot:
                raise ArithmeticError('selected plan belongs to a different physical plot')
            energy_values.append(plan['energy'])
            if plan['cultivated']:
                cultivated_areas.append(plots[plot])
            for index, amount in plan['uses']:
                amounts[index] = _bounded(amounts[index]+amount)
            rows.append({'plot_id': plot, 'plan_id': plan['id'], 'area_m2': str(plots[plot]),
                         'cultivated': plan['cultivated'], 'energy_kcal': str(plan['energy'])})
        energy = _sum(energy_values)
        if energy != best:
            raise ArithmeticError('selected-plan exact objective readback failed')
        ledger = []
        for identity, cap, amount in zip(resources, capacity, amounts):
            if amount > cap:
                raise ArithmeticError('selected plans overdraw a finite resource row')
            unused = _bounded(cap-amount)
            ledger.append({'resource_id': identity, 'capacity': str(cap), 'used': str(amount),
                           'unused': str(unused), 'residual': '0'})
        return {'selection': dict(sorted(selection.items())), 'objective_kcal': str(energy),
            'physical_area_m2': str(physical_area), 'cultivated_area_m2': str(_sum(cultivated_areas)),
            'plot_ledger': rows, 'resource_ledger': ledger}

    def finish(status, reason, **values):
        elapsed = time.perf_counter()-started
        if status != 'INCOMPLETE' and elapsed >= limits['time_limit_s']:
            status, reason, values = 'INCOMPLETE', 'global time budget expired before final readback', {}
        solution = {'schema': SCHEMA, 'status': status, 'reason': reason, 'selection': None,
            'objective': 'MAXIMUM_SUPPLIED_EDIBLE_ENERGY_KCAL',
            'scope': 'COMPLETE_WHOLE_PLOT_SEQUENCE_CHOICES_NOT_CONTINUOUS_STRIP_ALLOCATION',
            'resource_rows': 'INDEPENDENT_CONSTRAINTS_MAY_OVERLAP; DO_NOT_SUM_DAILY_AND_PREFIX_ROWS_AS_WATER_STOCK',
            'producer_responsibilities': ['disjoint actual plot geometry', 'valid within-plan occupation calendar',
                'continuous soil-water state and applicable crop yields', 'source-bound finite resource capacities'],
            'population_used_for_supply': False, 'preferred_selection': None,
            **values}
        return {'solution': solution, 'diagnostics': {'elapsed_s': elapsed, 'nodes': nodes,
            'examined_plans': examined_plans, 'resource_prunes': resource_prunes, 'energy_prunes': energy_prunes,
            'limits': limits, 'reference_limits': {'plots': MAX_PLOTS, 'plans': MAX_PLANS,
                'resources': MAX_RESOURCES, 'resource_uses': MAX_USES, 'exact_bits': MAX_BITS},
            'optimality': 'EXACT_RATIONAL_BRANCH_AND_BOUND; NO_FLOATING_OBJECTIVE_OR_SOLVER_TOLERANCE'}}

    def visit(depth, energy):
        nonlocal nodes, examined_plans, resource_prunes, energy_prunes, best, witnesses
        check_time()
        if nodes >= limits['node_limit']:
            raise _Incomplete('global search-node budget exhausted')
        nodes += 1
        upper = _bounded(energy+suffix[depth])
        if best is not None and (upper < best or (upper == best and len(witnesses) == 2)):
            energy_prunes += 1
            return
        if depth == len(identities):
            candidate = dict(selected)
            if best is None or energy > best:
                best, witnesses = energy, [candidate]
            elif energy == best and candidate not in witnesses:
                witnesses.append(candidate)
                witnesses.sort(key=lambda item: tuple(item[plot] for plot in identities))
                witnesses = witnesses[:2]
            return
        plot = identities[depth]
        for plan in choices[plot]:
            check_time(); examined_plans += 1
            following = []
            for index, amount in plan['uses']:
                value = _bounded(used[index]+amount)
                if value > capacity[index]:
                    resource_prunes += 1
                    break
                following.append((index, value))
            else:
                previous = [(index, used[index]) for index, _ in following]
                for index, value in following:
                    used[index] = value
                selected[plot] = plan['id']
                visit(depth+1, _bounded(energy+plan['energy']))
                del selected[plot]
                for index, value in previous:
                    used[index] = value

    try:
        check_time()
        physical_area = _sum(plots.values())
        suffix = [F(0)]*(len(identities)+1)
        for i in range(len(identities)-1, -1, -1):
            suffix[i] = _bounded(suffix[i+1]+max(plan['energy'] for plan in choices[identities[i]]))
        visit(0, F(0))
        if best is None or not witnesses:
            raise ArithmeticError('explicit zero-use fallow plans did not yield a feasible complete selection')
        checked = [witness(selection) for selection in witnesses]
        check_time()
        certificate = {'method': 'COMPLETE_EXACT_RATIONAL_BRANCH_AND_BOUND',
            'search_complete': True, 'lower_bound_kcal': str(best), 'upper_bound_kcal': str(best),
            'bound_rule': 'CURRENT_ENERGY_PLUS_SUM_OF_UNCONSTRAINED_REMAINING_PLOT_MAXIMA',
            'equal_bound_pruned_only_after_two_optimum_witnesses': True}
        if len(checked) == 1:
            return finish('MODELLED', 'one certified optimum whole-plot selection',
                **checked[0], objective_upper_bound_kcal=str(best), certificate=certificate)
        return finish('ALLOCATION_UNRESOLVED', 'at least two distinct optimum plan selections; no preferred map',
            alternatives=checked, alternatives_exhaustive=False, objective_kcal=str(best),
            objective_upper_bound_kcal=str(best), physical_area_m2=str(physical_area), certificate=certificate)
    except _Incomplete as exc:
        # Even a feasible incumbent is not an accepted map before global proof.
        return finish('INCOMPLETE', str(exc))
