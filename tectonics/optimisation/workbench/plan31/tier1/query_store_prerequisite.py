"""The retained completed-query prerequisite for the public restart runner.

Only the query-store wiring is ported. Existing public timing, profile schema,
historical admission and release hooks remain those of the authenticated parent.
The fresh leg's real definitions are copied with their decorators by AST span.
"""
import ast
UNITS = ('query_store_arguments', 'QUERY_STAGE_FIELDS', 'QueryStages', 'completed_queries')
CONSTANTS = ('QUERY_STORE_FLAG', 'QUERY_STORES')

def require(ok, reason):
    if not ok:
        raise ValueError('REFUSED: '+reason)


def replace(text, old, new, label):
    require(text.count(old) == 1, 'anchor must occur exactly once: '+label+' (found %d)' % text.count(old))
    return text.replace(old, new)


def spans(text, names):
    """Exact source of each named top-level unit, decorators included."""
    tree = ast.parse(text)
    lines = text.split('\n')
    found = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        else:
            continue
        if name in names:
            require(name not in found, 'duplicate unit: '+name)
            start = min([node.lineno, *(d.lineno for d in getattr(node, 'decorator_list', ()))])
            found[name] = '\n'.join(lines[start-1:node.end_lineno])
    require(set(found) == set(names), 'units missing from run_fresh_interval: '+', '.join(sorted(set(names)-set(found))))
    return found


def restart(text, fresh):
    constants, units = spans(fresh, CONSTANTS), spans(fresh, UNITS)
    text = replace(text, "QUERY_LIMIT_FIELDS = frozenset(('max_entries', 'max_store_bytes'))\n",
        "QUERY_LIMIT_FIELDS = frozenset(('max_entries', 'max_store_bytes'))\n"
        "# The completed-query store the pinned source manifest declares, read as on the fresh leg\n"
        "# (run_fresh_interval): a declared store the runtime lacks refuses, never a silent fallback,\n"
        "# and flush() precedes the recorded counts. These constants and the units before\n"
        "# run_prepared_restart are run_fresh_interval's, AST-identical (test_restart_query_store).\n"
        + constants['QUERY_STORE_FLAG']+'\n'+constants['QUERY_STORES']+'\n', 'constants')
    text = replace(text,
        "                'explicit data-only references disjoint from importable sources required')\n"
        "        self._manifest = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()\n",
        "                'explicit data-only references disjoint from importable sources required')\n"
        "        require(manifest.get(QUERY_STORE_FLAG) in QUERY_STORES,\n"
        "                'the composition must declare its completed-query store: columnar or files')\n"
        "        self._manifest = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()\n",
        'declared store refusal')
    text = replace(text,
        "    def files(self):\n        return dict(_json(self._manifest)['files'])\n",
        "    def files(self):\n        return dict(_json(self._manifest)['files'])\n\n"
        "    def query_store(self):\n"
        "        \"\"\"The completed-query store the pinned composition declares.\"\"\"\n"
        "        return _json(self._manifest)[QUERY_STORE_FLAG]\n", 'query_store method')
    block = ("# The fresh leg's completed-query units, copied by AST span from run_fresh_interval so\n"
             "# that each leg raises its own refusal type; test_restart_query_store fails on any drift.\n"
             + '\n\n\n'.join(units[name] for name in UNITS) + '\n\n\n')
    text = replace(text,
        "def run_prepared_restart(profile, *, sources, guard, record, save, stop_before_advance=False, start_gate=None):\n",
        block + "def run_prepared_restart(profile, *, sources, guard, record, save, stop_before_advance=False, start_gate=None,\n"
        "                         query_stages=None):\n", 'runner signature')
    text = replace(text,
        "    With stop_before_advance the published root is reopened and recorded, and\n"
        "    no driver, completed-query owner or physical interval work runs.\n    \"\"\"\n",
        "    With stop_before_advance the published root is reopened and recorded, and\n"
        "    no driver, completed-query owner or physical interval work runs.\n"
        "    ``query_stages`` (S1): _workload's per-stage completed-query observer, handed to the owner.\n    \"\"\"\n",
        'runner docstring')
    text = replace(text,
        "    from atlas_tectonics.integration_endpoint_checkpoints import EndpointCheckpoints\n",
        "    from atlas_tectonics.integration_endpoint_checkpoints import EndpointCheckpoints\n"
        "    declared = sources.query_store()\n"
        "    query_arguments = query_store_arguments(EndpointCheckpoints, declared)\n"
        "    record['completed_query_store'] = {'declared': declared, 'arguments': query_arguments}\n",
        'declared store record')
    text = replace(text,
        "                                with EndpointCheckpoints(query_directory, context=execution,\n"
        "                                        budget=budget, cancel=check, max_store_bytes=query_limits['max_store_bytes'],\n"
        "                                        max_entries=query_limits['max_entries']) as query_checkpoints:\n"
        "                                    storage_point(record, 'before-advance', checkpoint=destination,\n"
        "                                                  query_directory=query_directory, store=store)\n"
        "                                    save()\n"
        "                                    try:\n"
        "                                        before, after = _advance_checked(driver, workflow=workflow, base=base,\n"
        "                                            case=continuation_case, execution=execution, guard=guard,\n"
        "                                            record=record, save=save, artifacts=output,\n"
        "                                            query_checkpoints=query_checkpoints, fence=sources.check_imported)\n"
        "                                    finally:\n"
        "                                        record['completed_queries'] = dict(directory=str(query_directory),\n"
        "                                            hits=query_checkpoints.hits, misses=query_checkpoints.misses,\n"
        "                                            written=query_checkpoints.written, incomplete=query_checkpoints.incomplete,\n"
        "                                            scope='validated completed queries only; strict current execution binding')\n"
        "                                        save()\n",
        "                                # The declared owner records its counts after flush(), on success and failure.\n"
        "                                with completed_queries(EndpointCheckpoints, query_directory, declared=declared,\n"
        "                                        arguments=query_arguments, execution=execution, budget=budget,\n"
        "                                        cancel=check, limits=query_limits, record=record, save=save,\n"
        "                                        query_stages=query_stages) as query_checkpoints:\n"
        "                                    storage_point(record, 'before-advance', checkpoint=destination,\n"
        "                                                  query_directory=query_directory, store=store)\n"
        "                                    save()\n"
        "                                    before, after = _advance_checked(driver, workflow=workflow, base=base,\n"
        "                                        case=continuation_case, execution=execution, guard=guard,\n"
        "                                        record=record, save=save, artifacts=output,\n"
        "                                        query_checkpoints=query_checkpoints, fence=sources.check_imported)\n",
        'advance owner')
    text = replace(text,
        "        dev_timing = timing.enabled(dev_timing)\n"
        "        save = lambda: G._write(output, record)\n",
        "        dev_timing = timing.enabled(dev_timing)\n"
        "        query_stages = QueryStages(record)\n\n"
        "        def save():\n"
        "            query_stages.observe()\n"
        "            G._write(output, record)\n", 'workload save')
    text = replace(text,
        "                                              stop_before_advance=stop_before_advance, start_gate=start_gate)\n",
        "                                              stop_before_advance=stop_before_advance, start_gate=start_gate,\n"
        "                                              query_stages=query_stages)\n", 'workload call')
    text = replace(text,
        "            record['status'] = final_status(record['errors'], stop_before_advance=stop_before_advance)\n",
        "            query_stages.finish()\n"
        "            record['status'] = final_status(record['errors'], stop_before_advance=stop_before_advance)\n",
        'workload finish')
    return text
