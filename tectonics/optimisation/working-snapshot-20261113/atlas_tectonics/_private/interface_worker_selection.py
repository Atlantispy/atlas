"""Worker ceilings chosen at launch (coordinator, 16 Oct 2026; revised 20 Nov 2026).

The ceiling is the run's cores less one for the parent, as resources_gate counts them: the set or
ceiling cores of ATLAS_RESOURCES, else the queue ticket's booking, else the measured physical cores.

From interval 2 on, the count steps down one at a time from that ceiling until it fits the
measured parent footprint by the interface policy's own admission formula
(integration_parallel_selection's _resources, evaluated here at launch with the parent's
measured peaks):

- cores: free physical cores >= n + 1 (the parent keeps one core beside its workers);
- memory: available physical memory - the parent's measured real peak
  >= n x per-worker booking + policy.ram_reserve_bytes;
- budget: the parent's fixed storage + n x (per-worker booking + one raw result)
  <= policy.budget_fraction x (logical budget - the parent's measured logical peak).

It never goes below one. Interval 1, with no measured parent, takes the ceiling bounded by
free memory per worker (first_interval_workers). The policy still steps down at dispatch,
to serial only when it cannot keep one worker beside the parent. Execution only: no
equation, tolerance, record or result depends on it.
"""
SCHEMA = 'atlas.interface-worker-selection.v1'
PARENT_FIXED_EXTRA = 8192    # the planner's fixed term beside PARENT_STORAGE (its node term is not known at launch)


def first_interval_workers(policy, load=None, stage=None):
    """Interval 1 (no measured parent): the gate's launch width for the stage, a worker counted at the stored
    largest peak of an interface pool's worker, else at the policy's booking, beside the policy's reserve."""
    from atlas_tectonics import integration_parallel_dispatch as dispatch
    from atlas_tectonics import machine_resources_monitor as MON
    from atlas_tectonics import resources_gate as RG
    machine, times = MON.reading(load), MON.Timings()
    peak = max(times.peak((family, 'worker', 'peak')) or 0 for family in ('interface', 'wall'))
    return RG.launch_width(machine, RG.setting(machine), peak or policy.child_bytes+dispatch.CHILD_BASELINE,
                           policy.ram_reserve_bytes, stage)


def _fits(workers, *, booking, raw, fixed, policy, parent, machine, logical_budget_bytes):
    from atlas_tectonics.resources_gate import free_cores as cores_free
    free_cores = cores_free(machine, machine['physical_cores'])
    free_memory = machine['available_bytes']-parent['real_peak_bytes']
    free_budget = logical_budget_bytes-parent['logical_peak_bytes']
    checks = {'cores': free_cores >= workers+1,
              'memory': free_memory >= workers*booking+policy.ram_reserve_bytes,
              'budget': fixed+workers*(booking+raw) <= policy.budget_fraction*free_budget}
    return checks, {'free_cores': round(free_cores, 2), 'free_memory_bytes': free_memory,
                    'free_budget_bytes': free_budget}


def select(*, policy_type, child_baseline_bytes, parent_storage_bytes, raw_result_bytes, parent, machine,
           logical_budget_bytes, ceiling=None):
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
    if not 0 <= machine.get('busy_cores', -1) <= machine['logical_cpus']:
        raise ValueError('measured busy cores required')
    policy = policy_type()
    booking = policy.child_bytes+child_baseline_bytes
    fixed = parent_storage_bytes+PARENT_FIXED_EXTRA
    options = {'booking': booking, 'raw': raw_result_bytes, 'fixed': fixed, 'policy': policy, 'parent': parent,
               'machine': machine, 'logical_budget_bytes': logical_budget_bytes}
    from atlas_tectonics.resources_gate import step_down
    ceiling = max(1, machine['physical_cores']-1 if ceiling is None else ceiling)
    chosen = max(1, step_down(ceiling, lambda n: all(_fits(n, **options)[0].values())))
    checks, free = _fits(chosen, **options)
    if all(checks.values()):
        reason = f'{chosen} of a ceiling of {ceiling} fit the measured parent footprint by the policy formula'
    else:
        reason = 'one: no count fits: ' + ', '.join(name for name, ok in checks.items() if not ok)
    return {'schema': SCHEMA, 'chosen': chosen, 'selected': chosen, 'ceiling': ceiling, 'reason': reason,
            'per_worker_booked_bytes': booking,
            'checks': {str(chosen): checks}, 'free_at_launch': free,
            'inputs': {'parent': dict(parent), 'machine': dict(machine), 'logical_budget_bytes': logical_budget_bytes,
                       'child_bytes': policy.child_bytes, 'child_baseline_bytes': child_baseline_bytes,
                       'raw_result_bytes': raw_result_bytes, 'fixed_bytes': fixed,
                       'ram_reserve_bytes': policy.ram_reserve_bytes, 'budget_fraction': policy.budget_fraction},
            'scope': 'execution only; the policy still cuts per plan at dispatch'}


def select_composed(*, parent, logical_budget_bytes):
    """select() against the composed runtime's policy and constants, with the machine measured now."""
    from atlas_tectonics import integration_parallel_dispatch as dispatch
    from atlas_tectonics import machine_resources_monitor as MON
    from atlas_tectonics import resources_gate as RG
    from atlas_tectonics.integration_parallel_results import raw_capacity
    from atlas_tectonics.integration_parallel_selection import InterfaceParallelPolicy
    machine = MON.reading()
    host, source = RG.run_cores(machine, RG.setting(machine))
    result = select(policy_type=InterfaceParallelPolicy, child_baseline_bytes=dispatch.CHILD_BASELINE,
                    parent_storage_bytes=dispatch.PARENT_STORAGE, raw_result_bytes=raw_capacity(0), parent=parent,
                    machine=machine, logical_budget_bytes=logical_budget_bytes, ceiling=host-1)
    result['ceiling_source'] = source
    return result


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
            decision['chosen'] < 1 or decision.get('selected') != decision['chosen'] or
            decision.get('inputs', {}).get('parent') != parent):
        raise ValueError('measured parent and a positive worker count required')
    fits = {'cores': True, 'memory': True, 'budget': True}
    if 'ceiling' in decision:    # a count above one fits every gate, within its ceiling
        if (type(decision['ceiling']) is not int or decision['chosen'] > decision['ceiling'] or
                decision['chosen'] > 1 and decision.get('checks', {}).get(str(decision['chosen'])) != fits):
            raise ValueError('the chosen workers must fit every measured-parent gate within the ceiling')
    elif (decision['chosen'] not in (4, 6) or decision.get('policy_maximum') != 6 or    # a four-or-six record
          decision['chosen'] == 6 and decision.get('checks', {}).get('six') != fits):
        raise ValueError('six workers must fit every measured-parent gate')
    return {'mode': 'auto', 'workers': decision['chosen']}
