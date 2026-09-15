"""R24 execution of an unchanged R11 snapshot graph.

The injected store must authenticate records and bind its namespace to the
complete implementation/runtime identity. Content checks here are not a claim
that an arbitrary checksum proves a producer ran. Only validated computed
records are committed; checkpoint bytes alone never authorise fast reuse.

Producers must be deterministic functions of the registered source, context,
inputs and declared dependencies. A backend executes independent ready nodes in
isolated workers; it must not parallelise hidden shared scientific state. Its
execute(jobs) returns {stage_id: {product, artifacts, diagnostics}}. A streaming
backend instead exposes positive integer capacity, submit(jobs), and receive()
returning a nonempty completed subset in the same format. Only declared parents
gate readiness. Both extras are mappings; on_restore installs/validates them
before downstream execution. Each result passes the original validation and
source checks before caching or releasing children. Only a contiguous prefix of
the original order enters a checkpoint; accepted out-of-order results remain
reusable through the authenticated cache. A streaming failure retains its
exception type and exposes snapshot_checkpoint for that accepted prefix.

The scientific return value is exactly the original snapshot.run contract.
producer_executed retains its original mathematical meaning even on reuse.
Actual execution/reuse statistics are deliberately separate from that result.
"""
from copy import deepcopy
from heapq import heapify, heappop, heappush


def _frontiers(nodes, order, completed):
    """Release whole deterministic waves without rescanning unfinished nodes."""
    rank = {ident: index for index, ident in enumerate(order)}
    outstanding, children = {}, {}
    for ident in order:
        # Multiple input ports from one parent still form one readiness edge.
        parents = {dep['stage_id'] for dep in nodes[ident]['dependencies'].values()
                   if dep['stage_id'] not in completed}
        outstanding[ident] = len(parents)
        for parent in parents:
            children.setdefault(parent, []).append(ident)
    ready = [ident for ident in order if outstanding[ident] == 0]
    remaining = len(order)
    while remaining:
        if not ready:
            raise ValueError('no executable graph frontier')
        yield ready
        remaining -= len(ready)
        released = []
        for ident in ready:
            for child in children.get(ident, ()):
                outstanding[child] -= 1
                if outstanding[child] == 0:
                    released.append(child)
        ready = sorted(released, key=rank.__getitem__)


def run(snapshot_module, recipe, registry, *, store=None, stop_after=None,
        resume=None, backend=None, on_restore=None, on_computed=None, stats=None):
    """Execute/reuse a deterministic graph, or strictly resume a cached prefix.

Without a store an existing checkpoint uses the original semantic replay path;
no fast-resume promise is made and execution callbacks/backend are not used.
With a store every prefix row must match an authenticated entry before any
suffix producer can run. A missing or invalid entry fails closed.
"""
    s = snapshot_module
    metrics = {} if stats is None else stats
    if type(metrics) is not dict:
        raise ValueError('separate mutable statistics dictionary required')
    metrics.clear()
    metrics.update(executed_stage_ids=[], computed_stage_ids=[], reused_stage_ids=[],
                   restored_prefix_stage_ids=[], completed=False,
                   uncached_semantic_replay=False)
    if store is None and resume is not None:
        result = s.run(recipe, registry, stop_after=stop_after, resume=resume)
        metrics['uncached_semantic_replay'] = True
        metrics['completed'] = True
        return result
    recipe = deepcopy(recipe)
    nodes, order = s.parse(recipe, registry)
    until = len(order) if stop_after is None else stop_after
    if type(until) is not int or not 0 <= until <= len(order):
        raise ValueError('bounded complete-stage cursor required')
    recipe_sha = s.sha(recipe)
    rows = {}
    if store is not None and (not callable(getattr(store, 'get', None))
                              or not callable(getattr(store, 'put', None))):
        raise ValueError('authenticated get/put store required')
    streaming = backend is not None and (hasattr(backend, 'submit')
                                         or hasattr(backend, 'receive'))
    if streaming:
        if (not callable(getattr(backend, 'submit', None))
                or not callable(getattr(backend, 'receive', None))
                or type(getattr(backend, 'capacity', None)) is not int
                or backend.capacity < 1):
            raise ValueError('explicit submit/receive backend and positive integer capacity required')
    elif backend is not None and not callable(getattr(backend, 'execute', None)):
        raise ValueError('explicit execute(jobs) backend required')
    for callback in (on_restore, on_computed):
        if callback is not None and not callable(callback):
            raise ValueError('callable execution hook required')

    def prepare(ident):
        stage = nodes[ident]
        missing = list(stage['missing_inputs'])
        incoming, bindings = {}, {}
        for name, dep in sorted(stage['dependencies'].items()):
            source = rows[dep['stage_id']]
            bindings[name] = source['product_sha256']
            if source['product']['status'] == 'UNKNOWN':
                missing.append('dependency '+dep['stage_id']+': '+', '.join(source['product']['unresolved']))
            else:
                incoming[name] = deepcopy(source['product']['values'][dep['output']])
        invocation = s.sha({'context': recipe['context'], 'stage': stage,
                            'dependency_products': bindings})
        unknown = None
        if missing:
            unknown = s.emission(recipe['context'], stage['outputs'],
                {k: None for k in stage['outputs']},
                evidence='Required input closure failed; no affected producer execution',
                source_status='UNKNOWN', status='UNKNOWN', unresolved=missing)
        return {'stage': stage, 'incoming': incoming, 'invocation': invocation,
                'unknown': unknown}

    def verify(ident):
        registered = registry[nodes[ident]['producer_id']]
        if registered['sha256'] != nodes[ident]['producer_sha256']:
            raise ValueError('actual registered execution differs for stage '+ident
                +': expected '+nodes[ident]['producer_sha256']
                +'; actual '+str(registered['sha256']))
        registered['verify']()

    def validate_row(row, prepared):
        s.exact(row, ('invocation_sha256', 'product_sha256',
                      'producer_executed', 'product'), 'cached stage row')
        if row['invocation_sha256'] != prepared['invocation']:
            raise ValueError('cached invocation differs')
        if type(row['producer_executed']) is not bool:
            raise ValueError('exact cached execution flag required')
        expected_execution = prepared['unknown'] is None
        if row['producer_executed'] != expected_execution:
            raise ValueError('cached producer execution semantics differ')
        result, stage = row['product'], prepared['stage']
        s.product(result, recipe['context'], stage['outputs'])
        if s.digest(row['product_sha256']) != s.sha(result):
            raise ValueError('cached product hash differs')
        if not expected_execution:
            if result != prepared['unknown']:
                raise ValueError('cached UNKNOWN input closure differs')
        elif ((stage['mode'] == 'SUPPLIED_CONSTRAINT'
               and result['status'] not in ('SUPPLIED_CONSTRAINT', 'UNKNOWN'))
              or (stage['mode'] == 'GENERATED'
                  and result['status'] == 'SUPPLIED_CONSTRAINT')):
            raise ValueError('a supplied constraint cannot be counted as regeneration')
        return deepcopy(row)

    def extras(value):
        s.exact(value, ('artifacts', 'diagnostics'), 'execution extras')
        if type(value['artifacts']) is not dict or type(value['diagnostics']) is not dict:
            raise ValueError('artifact and diagnostic mappings required')
        # Units remain individually bounded/validated by the artifact adapter.
        # Do not impose the graph's aggregate 8 MiB limit on their collection.
        s.plain(value)
        return deepcopy(value)

    def validate_record(record, prepared):
        s.exact(record, ('row', 'artifacts', 'diagnostics'), 'cache record')
        extra = extras({'artifacts': record['artifacts'], 'diagnostics': record['diagnostics']})
        return {'row': validate_row(record['row'], prepared), **extra}

    def restore(ident, record):
        if on_restore is not None:
            on_restore(ident, deepcopy(record))
        elif record['artifacts'] or record['diagnostics']:
            raise ValueError('artifact-bearing reuse requires an explicit restore hook')
        verify(ident)

    def accept_cached(ident, prepared, expected=None):
        verify(ident)
        record = store.get(prepared['invocation']) if store is not None else None
        if record is None:
            if expected is not None:
                raise ValueError('checkpoint prefix has no authenticated cache entry'
                    +' for stage '+ident+'; invocation '+prepared['invocation'])
            return False
        record = validate_record(record, prepared)
        if expected is not None and record['row'] != expected:
            raise ValueError('checkpoint prefix differs from authenticated cache'
                +' for stage '+ident+'; invocation '+prepared['invocation'])
        restore(ident, record)
        rows[ident] = record['row']
        metrics['reused_stage_ids'].append(ident)
        return True

    prefix_count = 0
    if resume is not None:
        s.exact(resume, ('schema', 'recipe_sha256', 'state_sha256', 'state'), 'snapshot checkpoint')
        for field, expected in (
                ('schema', 'diadem.snapshot-graph-checkpoint.r11'),
                ('recipe_sha256', recipe_sha)):
            if resume[field] != expected:
                raise ValueError('checkpoint binding differs: '+field
                    +'; expected '+expected+'; actual '+str(resume[field]))
        actual_state_sha = s.sha(resume['state'])
        if resume['state_sha256'] != actual_state_sha:
            raise ValueError('checkpoint binding differs: state_sha256'
                +'; expected '+str(resume['state_sha256'])+'; actual '+actual_state_sha)
        s.exact(resume['state'], ('completed_stages', 'rows'), 'checkpoint state')
        prefix_count = resume['state']['completed_stages']
        if type(prefix_count) is not int or not 0 <= prefix_count <= until:
            raise ValueError('bounded checkpoint prefix required: completed_stages='
                +repr(prefix_count)+'; expected integer in 0..'+str(until))
        prefix_rows = resume['state']['rows']
        if type(prefix_rows) is not dict:
            raise ValueError('exact checkpoint prefix inventory required: rows must be a mapping')
        expected_ids = set(order[:prefix_count])
        if set(prefix_rows) != expected_ids:
            missing = sorted(expected_ids - set(prefix_rows))
            extra = sorted(set(prefix_rows) - expected_ids)
            raise ValueError('exact checkpoint prefix inventory required: missing '
                +str(len(missing))+' '+repr(missing[:8])+'; extra '
                +str(len(extra))+' '+repr(extra[:8]))
        for ident in order[:prefix_count]:
            prepared = prepare(ident)
            try:
                validate_row(prefix_rows[ident], prepared)
                accept_cached(ident, prepared, expected=prefix_rows[ident])
            except ValueError as exc:
                raise ValueError('checkpoint stage '+ident+'; invocation '
                    +prepared['invocation']+': '+str(exc)) from exc
            metrics['restored_prefix_stage_ids'].append(ident)

    def attach_failure_checkpoint(exc, cursor):
        state = {'completed_stages': cursor,
                 'rows': {ident: deepcopy(rows[ident]) for ident in order[:cursor]}}
        try:
            exc.snapshot_checkpoint = s.checkpoint({
                'schema': 'diadem.snapshot-graph-result.r11',
                'recipe_sha256': recipe_sha, 'state': state})
        except Exception as checkpoint_error:
            # A bounded checkpoint envelope failure must not replace the actual
            # worker/validation error. Authenticated accepted cache survives.
            exc.snapshot_checkpoint_error = str(checkpoint_error)

    def stream():
        # Rank is the original layer-sorted topological order, not the order in
        # which workers happen to finish. Prefix commits never include holes.
        rank = {ident: index for index, ident in enumerate(order)}
        outstanding, children = {}, {}
        for ident in order[prefix_count:until]:
            parents = {dep['stage_id'] for dep in nodes[ident]['dependencies'].values()
                       if dep['stage_id'] not in rows}
            outstanding[ident] = len(parents)
            for parent in parents:
                children.setdefault(parent, []).append(ident)
        ready = [rank[ident] for ident, count in outstanding.items() if count == 0]
        heapify(ready)
        pending = {}
        cursor = prefix_count

        def release(ident):
            nonlocal cursor
            while cursor < until and order[cursor] in rows:
                cursor += 1
            for child in children.get(ident, ()):
                outstanding[child] -= 1
                if outstanding[child] == 0:
                    heappush(ready, rank[child])

        def save(ident, prepared, record):
            verify(ident)
            if store is not None:
                store.put(prepared['invocation'], deepcopy(record))
            verify(ident)
            rows[ident] = deepcopy(record['row'])
            metrics['computed_stage_ids'].append(ident)
            if record['row']['producer_executed']:
                metrics['executed_stage_ids'].append(ident)
            release(ident)

        try:
            while ready or pending:
                jobs = []
                while ready and len(pending) < backend.capacity:
                    ident = order[heappop(ready)]
                    prepared = prepare(ident)
                    if accept_cached(ident, prepared):
                        release(ident)
                    elif prepared['unknown'] is not None:
                        verify(ident)
                        result = prepared['unknown']
                        row = validate_row({'invocation_sha256': prepared['invocation'],
                            'product_sha256': s.sha(result), 'producer_executed': False,
                            'product': result}, prepared)
                        verify(ident)
                        extra = {'artifacts': {}, 'diagnostics': {}}
                        if on_computed is not None:
                            extra = extras(on_computed(ident, deepcopy(row)))
                        save(ident, prepared, {'row': row, **extra})
                    else:
                        verify(ident)
                        stage = prepared['stage']
                        jobs.append({'stage_id': ident, 'producer_id': stage['producer_id'],
                            'context': deepcopy(recipe['context']),
                            'inputs': deepcopy(stage['inputs']),
                            'incoming': deepcopy(prepared['incoming'])})
                        pending[ident] = prepared
                if jobs:
                    backend.submit(jobs)
                if not pending:
                    continue
                completed = backend.receive()
                if (type(completed) is not dict or not completed
                        or not set(completed) <= pending.keys()):
                    raise ValueError('nonempty exact pending backend completion inventory required')
                # Validate/detach every returned result before any callback can
                # mutate another producer's retained output alias. This checks
                # only the completed subset; it never waits for a whole wave.
                accepted = {}
                for ident in sorted(completed, key=rank.__getitem__):
                    prepared = pending[ident]
                    value = completed[ident]
                    s.exact(value, ('product', 'artifacts', 'diagnostics'), 'backend result')
                    row = {'invocation_sha256': prepared['invocation'],
                           'product_sha256': s.sha(value['product']),
                           'producer_executed': True, 'product': value['product']}
                    accepted[ident] = validate_record({'row': row,
                        'artifacts': value['artifacts'], 'diagnostics': value['diagnostics']}, prepared)
                    verify(ident)
                for ident, record in accepted.items():
                    prepared = pending[ident]
                    restore(ident, record)
                    save(ident, prepared, record)
                    del pending[ident]
            if cursor != until:
                raise ValueError('no executable graph frontier')
        except Exception as exc:
            attach_failure_checkpoint(exc, cursor)
            raise
        # Execution diagnostics retain canonical order as in the wave executor.
        for key in ('executed_stage_ids', 'computed_stage_ids', 'reused_stage_ids'):
            metrics[key].sort(key=rank.__getitem__)

    if streaming:
        stream()
    for ready in (() if streaming else _frontiers(nodes, order[prefix_count:until], rows)):
        # This is the original topological layer order, restricted to the
        # requested prefix. Never execute descendants of unfinished producers.
        prepared_by_id = {ident: prepare(ident) for ident in ready}
        missing_cache = []
        for ident in ready:
            if not accept_cached(ident, prepared_by_id[ident]):
                missing_cache.append(ident)
        jobs = []
        for ident in missing_cache if backend is not None else ():
            prepared = prepared_by_id[ident]
            if prepared['unknown'] is None:
                stage = prepared['stage']
                jobs.append({'stage_id': ident, 'producer_id': stage['producer_id'],
                             'context': deepcopy(recipe['context']),
                             'inputs': deepcopy(stage['inputs']),
                             'incoming': deepcopy(prepared['incoming'])})
        batch = None
        if backend is not None and jobs:
            for job in jobs:
                verify(job['stage_id'])
            batch = backend.execute(deepcopy(jobs))
            if type(batch) is not dict or set(batch) != {job['stage_id'] for job in jobs}:
                raise ValueError('exact completed backend job inventory required')
            # Validate/detach the complete batch before callbacks or commits.
            accepted_batch = {}
            for job in jobs:
                ident = job['stage_id']
                value = batch[ident]
                s.exact(value, ('product', 'artifacts', 'diagnostics'), 'backend result')
                row = {'invocation_sha256': prepared_by_id[ident]['invocation'],
                       'product_sha256': s.sha(value['product']),
                       'producer_executed': True, 'product': value['product']}
                accepted_batch[ident] = validate_record({'row': row,
                    'artifacts': value['artifacts'], 'diagnostics': value['diagnostics']},
                    prepared_by_id[ident])
                verify(ident)
            batch = accepted_batch
        for ident in missing_cache:
            prepared = prepared_by_id[ident]
            verify(ident)
            if batch is not None and ident in batch:
                record = batch[ident]
                restore(ident, record)
            else:
                result = prepared['unknown']
                if result is None:
                    result = registry[prepared['stage']['producer_id']]['run'](
                        deepcopy(recipe['context']), deepcopy(prepared['stage']['inputs']),
                        deepcopy(prepared['incoming']))
                row = {'invocation_sha256': prepared['invocation'],
                       'product_sha256': s.sha(result),
                       'producer_executed': prepared['unknown'] is None,
                       'product': result}
                row = validate_row(row, prepared)
                verify(ident)
                extra = {'artifacts': {}, 'diagnostics': {}}
                if on_computed is not None:
                    extra = extras(on_computed(ident, deepcopy(row)))
                record = {'row': row, **extra}
            verify(ident)
            if store is not None:
                store.put(prepared['invocation'], deepcopy(record))
            verify(ident)
            rows[ident] = deepcopy(record['row'])
            metrics['computed_stage_ids'].append(ident)
            if record['row']['producer_executed']:
                metrics['executed_stage_ids'].append(ident)
    # Cache hits and misses can be interleaved within a frontier. Preserve the
    # original row insertion order as well as its canonical JSON meaning.
    state = {'completed_stages': until, 'rows': {ident: rows[ident] for ident in order[:until]}}
    closure = {}
    for category in s.CATEGORIES:
        required_stages = [k for k in order if nodes[k]['category'] == category]
        complete = bool(required_stages) and all(
            k in state['rows'] and state['rows'][k]['product']['status'] != 'UNKNOWN'
            for k in required_stages)
        accepted = complete and all(nodes[k]['acceptance']['status'] == 'DOMAIN_ACCEPTED'
                                    for k in required_stages)
        closure[category] = {'stage_ids': required_stages,
            'required': category in recipe['required_categories'],
            'execution_complete': complete, 'domain_acceptance_declared': accepted,
            'generated_stage_ids': [k for k in required_stages if nodes[k]['mode'] == 'GENERATED'],
            'supplied_constraint_stage_ids': [k for k in required_stages if nodes[k]['mode'] == 'SUPPLIED_CONSTRAINT']}
    target_complete = all(closure[k]['execution_complete'] for k in recipe['required_categories'])
    result = {'schema': 'diadem.snapshot-graph-result.r11', 'recipe_sha256': recipe_sha,
        'state': state, 'category_closure': closure,
        'status': 'STOPPED' if until < len(order) else 'EXECUTED' if target_complete else 'INCOMPLETE',
        'whole_generator_implemented_claim': False, 'production_authorised': False,
        'canon_changed': False, 'acceptance_declarations_are_not_verified_authority': True}
    try:
        for ident in order[:until]:
            verify(ident)
    except Exception as exc:
        if streaming:
            attach_failure_checkpoint(exc, until)
        raise
    metrics['completed'] = True
    return result
