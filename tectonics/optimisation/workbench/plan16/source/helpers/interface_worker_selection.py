"""Interface worker ceiling chosen at launch, from interval 2 on (coordinator, 16 Oct 2026).

Default 4. Six only when the measured parent footprint leaves room for six by the
interface policy's own admission formula (integration_parallel_selection's planner
_resources, evaluated here at launch with the parent's measured peaks):

- cores: free physical cores >= n + 1 (the parent keeps one core beside its workers);
- memory: available physical memory - the parent's measured real peak
  >= n x per-worker booking + policy.ram_reserve_bytes;
- budget: the parent's fixed storage + n x (per-worker booking + one raw result)
  <= policy.budget_fraction x (logical budget - the parent's measured logical peak).

The per-worker booking is policy.child_bytes + integration_parallel_dispatch.CHILD_BASELINE
(0.75 GiB in RC1); the real use measured by the geometry chat is 0.15-0.25 GiB. The count
is then clamped to the largest one the composed policy accepts: 2 in RC1, until the
geometry chat's worker-cap lift is in the composition. The policy still makes its own
per-plan cuts at dispatch; this sets only its ceiling. Execution only: no equation,
tolerance, record or result depends on it. Interval 1 keeps r9's literal workers=2.
"""
SCHEMA = 'atlas.interface-worker-selection.v1'
DEFAULT = 4
WIDE = 6
PARENT_FIXED_EXTRA = 8192    # the planner's fixed term beside PARENT_STORAGE (its node term is not known at launch)


def policy_maximum(policy_type, *, upto=WIDE):
    """The largest worker count the composed policy accepts (it refuses others at construction)."""
    for workers in range(upto, 0, -1):
        try:
            policy_type(workers=workers)
        except ValueError:
            continue
        return workers
    raise ValueError('the interface policy accepts no worker count')


def _fits(workers, *, booking, raw, fixed, policy, parent, machine, logical_budget_bytes):
    busy = machine['logical_cpus']*machine['load_percent']/100
    free_cores = max(0.0, machine['physical_cores']-busy)
    free_memory = machine['available_bytes']-parent['real_peak_bytes']
    free_budget = logical_budget_bytes-parent['logical_peak_bytes']
    checks = {'cores': free_cores >= workers+1,
              'memory': free_memory >= workers*booking+policy.ram_reserve_bytes,
              'budget': fixed+workers*(booking+raw) <= policy.budget_fraction*free_budget}
    return checks, {'free_cores': round(free_cores, 2), 'free_memory_bytes': free_memory,
                    'free_budget_bytes': free_budget}


def select(*, policy_type, child_baseline_bytes, parent_storage_bytes, raw_result_bytes, parent, machine,
           logical_budget_bytes):
    """The interface worker ceiling and the record run.json keeps.

    parent: {'real_peak_bytes', 'logical_peak_bytes'}, the parent's measured peaks (the
    previous interval's run record). machine: {'physical_cores', 'logical_cpus',
    'load_percent', 'available_bytes'}, measured at launch.
    """
    for name in ('real_peak_bytes', 'logical_peak_bytes'):
        if type(parent.get(name)) is not int or parent[name] < 0:
            raise ValueError('measured parent footprint required: '+name)
    for name in ('physical_cores', 'logical_cpus', 'available_bytes'):
        if type(machine.get(name)) is not int or machine[name] < 1:
            raise ValueError('measured machine resources required: '+name)
    if not 0 <= machine.get('load_percent', -1) <= 100:
        raise ValueError('measured CPU load percentage required')
    policy = policy_type()
    booking = policy.child_bytes+child_baseline_bytes
    fixed = parent_storage_bytes+PARENT_FIXED_EXTRA
    options = {'booking': booking, 'raw': raw_result_bytes, 'fixed': fixed, 'policy': policy, 'parent': parent,
               'machine': machine, 'logical_budget_bytes': logical_budget_bytes}
    wide, free = _fits(WIDE, **options)
    default, _ = _fits(DEFAULT, **options)
    if all(wide.values()):
        selected, reason = WIDE, 'six fit the measured parent footprint by the policy formula'
    else:
        selected = DEFAULT
        reason = 'default four; six do not fit: ' + ', '.join(name for name, ok in wide.items() if not ok)
    maximum = policy_maximum(policy_type)
    chosen = min(selected, maximum)
    if chosen < selected:
        reason += f'; clamped to {maximum} by the policy (its accepted maximum)'
    return {'schema': SCHEMA, 'chosen': chosen, 'selected': selected, 'policy_maximum': maximum, 'reason': reason,
            'default': DEFAULT, 'wide': WIDE, 'per_worker_booked_bytes': booking,
            'checks': {'six': wide, 'four': default}, 'free_at_launch': free,
            'inputs': {'parent': dict(parent), 'machine': dict(machine), 'logical_budget_bytes': logical_budget_bytes,
                       'child_bytes': policy.child_bytes, 'child_baseline_bytes': child_baseline_bytes,
                       'raw_result_bytes': raw_result_bytes, 'fixed_bytes': fixed,
                       'ram_reserve_bytes': policy.ram_reserve_bytes, 'budget_fraction': policy.budget_fraction},
            'scope': 'execution only; the policy still cuts per plan at dispatch'}


def select_composed(*, parent, logical_budget_bytes):
    """select() against the composed runtime's policy and constants, with the machine measured now."""
    import psutil
    from atlas_tectonics import integration_parallel_dispatch as dispatch
    from atlas_tectonics.integration_parallel_results import raw_capacity
    from atlas_tectonics.integration_parallel_selection import InterfaceParallelPolicy
    cores = psutil.cpu_count(logical=False) or 1
    machine = {'physical_cores': cores, 'logical_cpus': max(cores, psutil.cpu_count() or cores),
               'load_percent': psutil.cpu_percent(interval=0.05), 'available_bytes': psutil.virtual_memory().available}
    return select(policy_type=InterfaceParallelPolicy, child_baseline_bytes=dispatch.CHILD_BASELINE,
                  parent_storage_bytes=dispatch.PARENT_STORAGE, raw_result_bytes=raw_capacity(0), parent=parent,
                  machine=machine, logical_budget_bytes=logical_budget_bytes)


PARENT_SELECTION_SCHEMA = 'atlas.parent-measured-interface-workers.v1'


def policy_from_selection(selection):
    """Consume the runner's authenticated parent measurement, never a bare worker override."""
    if type(selection) is not dict or set(selection) != {'schema', 'parent_receipt', 'parent', 'decision'}:
        raise ValueError('authenticated parent worker selection required')
    receipt, parent, decision = selection['parent_receipt'], selection['parent'], selection['decision']
    if (selection['schema'] != PARENT_SELECTION_SCHEMA or type(receipt) is not dict or
            set(receipt) != {'path', 'sha256'} or type(receipt['path']) is not str or not receipt['path'] or
            type(receipt['sha256']) is not str or len(receipt['sha256']) != 64 or
            any(c not in '0123456789abcdef' for c in receipt['sha256'])):
        raise ValueError('source-bound parent receipt required')
    if (type(parent) is not dict or set(parent) != {'real_peak_bytes', 'logical_peak_bytes'} or
            any(type(v) is not int or v < 0 for v in parent.values()) or
            parent['real_peak_bytes'] == 0 or type(decision) is not dict or
            decision.get('schema') != SCHEMA or type(decision.get('chosen')) is not int or
            decision['chosen'] not in (4, 6) or decision.get('policy_maximum') != 6 or
            decision.get('selected') != decision['chosen'] or
            decision.get('inputs', {}).get('parent') != parent):
        raise ValueError('measured parent and current six-worker policy required')
    if decision['chosen'] == 6 and decision.get('checks', {}).get('six') != {
            'cores': True, 'memory': True, 'budget': True}:
        raise ValueError('six workers must fit every measured-parent gate')
    return {'mode': 'auto', 'workers': decision['chosen']}
