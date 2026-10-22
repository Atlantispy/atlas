"""Plan15 native-binding successor W4 control adapter; importing performs no workload.

The immutable original CONTROL body is reused in an unregistered namespace.
Its fixture budget is explicitly bound to the selected runner's existing
16 GiB limit. No production source, default, method or resource limit is changed.
Every execution requires a separately cleared, exact source-bound request.
"""
import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
COMPOSITION = 'e2a684ed9a93c57ea10c1e75f86c61f69ca9f2ffcefd4949119197d735af1e28'
PROFILE = 'f94d89d7484e8d0ff0f3050b8699df6a9281d6a61a75706e5d4d20a3581769ce'
CHECKS = {'array_names', 'arrays', 'exact_accounts', 'metadata_bytes', 'metadata_length',
          'metadata_sha256', 'plan_descriptor', 'result_id', 'snapshot_identity'}
ARRAYS = {'enthalpy_j', 'input_capacity_j_k', 'input_enthalpy_j', 'input_source_w', 'temperature_k'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def contract(path, expected):
    raw = Path(path).read_bytes()
    require(sha256(raw).hexdigest() == expected, 'contract identity differs')
    value = json.loads(raw)
    require(value['schema'] == 'plan15.current-control.r3', 'wrong contract schema')
    require(value['lineage']['composition']['sha256'] == COMPOSITION
            and value['lineage']['profile']['sha256'] == PROFILE, 'different selected parent lineage')
    require(type(value['logical_budget_bytes']) is int and value['logical_budget_bytes'] == 16 << 30,
            'selected runner budget differs')
    require(value['H3'] == 'CANDIDATE_NOT_ENABLED' and value['default_changed'] is False,
            'candidate/default authority differs')
    require(value['pins'].get(str(Path(__file__).resolve())) == digest(__file__), 'adapter unbound')
    for filename, pin in value['pins'].items():
        require(digest(filename) == pin, 'source/input identity differs: '+filename)
    require(value['comparison_policy_candidate'] is True, 'comparison policy is not a declared candidate')
    observer = value.get('assembly_observer')
    require(type(observer) is dict and set(observer) == {'schema', 'policy', 'emitter_sources',
        'source_pins', 'generation_files', 'adapter', 'native_binding_source', 'native_library',
        'prospective_native_bindings', 'prospective_rule_version'}
        and observer['schema'] == 'plan15.assembly-observer-binding.r2'
        and observer['prospective_native_bindings'] is True
        and observer['prospective_rule_version'] == 'plan15.native-binding.r1',
        'native binding contract absent or outside prospective rule')
    for kind in ('native_binding_source', 'native_library'):
        ref = observer[kind]
        require(type(ref) is dict and set(ref) == {'path', 'sha256'}
            and type(ref['path']) is str and type(ref['sha256']) is str
            and value['pins'].get(str(Path(ref['path']).resolve())) == ref['sha256']
            and observer['source_pins'].get(str(Path(ref['path']).resolve())) == ref['sha256'],
            'native binding source outside exact closure: '+kind)
    require(observer['native_library']['sha256'] ==
        'b81a548eb7a23d4e3acbe296f1eff077a0b284617a2c1cc53a1ccdb0637b52b8',
        'native binding DLL differs')
    value['_contract_sha256'] = expected
    value['_verified_source_digest'] = sha256(canonical(value['pins'])).hexdigest()
    return value


def load(name, ref):
    require(name not in sys.modules, 'fresh source namespace required: '+name)
    require(digest(ref['path']) == ref['sha256'], 'helper source differs')
    spec = importlib.util.spec_from_file_location(name, ref['path'])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parity(result, reference=None):
    """Same-generation exact identities only; no cross-generation translation."""
    require(result.get('status') == 'PASS' and type(result.get('checks')) is dict
            and set(result['checks']) == CHECKS
            and all(value is True for value in result['checks'].values()), 'same-call checks failed')
    require(type(result.get('arrays')) is dict and set(result['arrays']) == ARRAYS
            and all(type(v) is str and len(v) == 64 for v in result['arrays'].values()), 'array identities absent')
    for side in ('legacy', 'compact'):
        row = result[side]
        require(type(row['metadata_bytes']) is int and row['metadata_bytes'] > 0,
                'metadata byte count absent')
        require(all(type(row[key]) is str and len(row[key]) == 64 for key in ('result_id', 'metadata_sha256')),
                'required exact identity absent')
        if reference is not None:
            require(all(row[key] == reference[side][key]
                        for key in ('result_id', 'metadata_sha256', 'metadata_bytes')),
                    side+' differs from current-generation reference')
    if reference is not None:
        require(result['arrays'] == reference['arrays'], 'arrays differ from current-generation reference')


def reference_binding(value, generation):
    require(value.get('generation_binding') == generation and value.get('verdict') == 'PASS'
            and value.get('status') == 'PASS' and value.get('source_finality') is True
            and value.get('mode') == 'baseline' and value.get('scientific_control_executed') is True
            and value.get('selected_context', {}).get('context_exit_completed') is True,
            'reference generation/completion/verdict differs')
    parity(value['control'])


def candidate_route_identity(value, parallel, request, process_id):
    """Retain the raw build; compare only the explicitly prepared bounded rule."""
    require(type(value.get('route')) is str and value['route']
            and type(value.get('pinned_sha256')) is str and len(value['pinned_sha256']) == 64,
            'candidate route identity absent')
    require(value['pinned_sha256'] == 'e0be3a309c8ab9ccee3c1a36525f72da27e816b1ce984651dbd85a3c072a14aa',
            'candidate H3 source differs')
    require(value['route'] == 'compiled' or value['route'].startswith('unavailable: '),
            'candidate execution availability was not observed')
    build = value.get('build')
    if value['route'] != 'compiled':
        require(build is None and 'assembly_observation' not in value,
                'unavailable candidate has fabricated compiled evidence')
        return dict(route=value['route'], pinned_sha256=value['pinned_sha256'], build=None)
    require(type(build) is dict, 'compiled build missing')
    observed = value.get('assembly_observation')
    require(type(observed) is dict and observed.get('status') == 'OBSERVED'
            and observed.get('scientific_eligibility') is False
            and type(observed.get('new_compilations')) is int and observed['new_compilations'] == 0
            and type(observed.get('observation_seconds')) is float
            and 0.0 <= observed['observation_seconds'] < float('inf')
            and type(observed.get('raw_utf8_bytes')) is int and observed['raw_utf8_bytes'] > 0,
            'compiled assembly observation absent or refused')
    evidence = observed.get('evidence')
    require(type(evidence) is dict and evidence.get('context', {}).get('source_generation', {}).get('contract_sha256')
            == request['_contract_sha256'], 'assembly evidence contract differs')
    # This API supplies retained parent authority (or actual controller self binding),
    # never the worker's saved receipt as its own expected context.
    binding = parallel.parent_native_binding(process_id)
    require(evidence.get('context', {}).get('native_binding') == binding,
            'assembly evidence differs from independently retained native binding')
    comparison = parallel.assembly_comparison_identity(evidence, build, process_id)
    require(evidence['raw_sha256'] == build.get('compiled_assembly_sha256')
            and observed.get('raw_utf8_bytes') == evidence['raw_utf8_bytes'],
            'raw assembly/build/volume differs')
    return dict(route=value['route'], pinned_sha256=value['pinned_sha256'],
        assembly_comparison=comparison, literal_diagnostic_bytes_equivalent=False,
        numerical_equivalence_claim=False)


def candidate_worker_identity(report, controller, parallel, request):
    """Require positive evidence from every worker that actually processed faces."""
    identities = []
    for call in report['calls']:
        for process in call['processes']:
            status = process.get('candidate_heat_route')
            require(not status or status.get('route') != 'OBSERVATION_FAILED', 'worker assembly observation refused')
            if process['faces'] or status and status.get('route') == 'compiled':
                require(process.get('exit_code') == 0, 'candidate worker exit is not complete')
                status = process.get('candidate_heat_route')
                require(type(status) is dict and status.get('route') != 'NOT_OBSERVED',
                        'candidate worker route/build/availability not retained')
                require(type(process.get('pid')) is int and process['pid'] > 0, 'admitted worker PID absent')
                binding = process.get('native_binding_parent')
                require(type(binding) is dict and set(binding) == {'receipt', 'owner_record'}
                    and type(binding['owner_record']) is dict,
                    'independent parent binding ownership/cost record absent')
                owner = binding['owner_record']
                require(owner.get('schema') == 'plan15.native-admission.r1'
                    and owner.get('pid') == process['pid']
                    and type(owner.get('creation_filetime')) is int and owner['creation_filetime'] > 0
                    and owner.get('read_only_actual_handle') is True
                    and owner.get('closed') is True and owner.get('close_failure') is None
                    and owner.get('query_failure') is None
                    and owner.get('relationship') in ('same-process', 'live-immediate-child'),
                    'native binding process ownership/finality differs')
                compiled = status.get('route') == 'compiled'
                if compiled:
                    require(binding['receipt'] == parallel.parent_native_binding(process['pid'])
                        and owner['creation_filetime'] == binding['receipt']['creation_filetime'],
                        'compiled receipt differs from independent parent process binding')
                else:
                    require(binding['receipt'] is None, 'unavailable candidate has fabricated native receipt')
                costs = process.get('native_binding_costs')
                require(type(costs) is dict and set(costs) == {'admission_seconds',
                    'receiver_query_seconds', 'receiver_query_calls', 'component_times_overlap'}
                    and type(costs['receiver_query_calls']) is int
                    and costs['receiver_query_calls'] == (1 if compiled else 0)
                    and costs['component_times_overlap'] is True
                    and all(type(costs[name]) is float and 0.0 <= costs[name] < float('inf')
                            for name in ('admission_seconds', 'receiver_query_seconds')),
                    'native binding costs/query count absent or inconsistent')
                identities.append(candidate_route_identity(status, parallel, request, process['pid']))
    require(identities and all(value == identities[0] for value in identities),
            'mixed candidate worker route/build/availability')
    if controller.get('route') != 'NOT_OBSERVED':
        require(candidate_route_identity(controller, parallel, request, os.getpid()) == identities[0],
                'controller/worker candidate route/build/availability differs')
    return identities[0]


def assembly_observation_totals(report, controller):
    """Actual process records, raw bytes and costs; no forecast or summed RSS."""
    records = [(process['pid'], process.get('candidate_heat_route'))
               for call in report['calls'] for process in call['processes']]
    records.append((os.getpid(), controller))
    unique = {}
    for process_id, status in records:
        if not status or status.get('route') not in ('compiled', 'OBSERVATION_FAILED'):
            continue
        require(type(process_id) is int and process_id > 0, 'observed process PID absent')
        observed = status['assembly_observation']
        prior = unique.get(process_id)
        require(prior is None or canonical(prior) == canonical(observed),
                'one process supplied inconsistent assembly records')
        unique[process_id] = observed
    volume, costs, outcomes, complete = {}, {}, {}, {}
    for pid, observed in unique.items():
        outcomes[str(pid)] = observed['status']
        if observed['status'] == 'OBSERVED':
            volume[str(pid)] = observed['raw_utf8_bytes']
            costs[str(pid)] = observed['observation_seconds']
            complete[str(pid)] = True
        else:
            partial = observed.get('partial', {})
            require(partial.get('process_id') == pid, 'failed evidence PID differs')
            text = partial.get('raw_text')
            if text is not None:
                require(type(text) is str and sha256(text.encode('utf8')).hexdigest() == partial.get('raw_sha256'),
                        'partial raw assembly hash differs')
            volume[str(pid)] = 0 if text is None else len(text.encode('utf8'))
            costs[str(pid)] = partial.get('observation_seconds')
            complete[str(pid)] = partial.get('raw_capture_complete') is True
    native_costs = {}
    native_errors = {}
    for call in report['calls']:
        for process in call['processes']:
            pid = str(process['pid'])
            if 'native_binding_costs' in process:
                native_costs[pid] = process['native_binding_costs']
            errors = {name: process[name] for name in
                ('native_binding_error', 'native_binding_cleanup_error') if name in process}
            if errors:
                native_errors[pid] = errors
    local_costs = (controller or {}).get('assembly_observation', {}).get('native_binding_costs')
    if local_costs is not None:
        native_costs[str(os.getpid())] = local_costs
    return dict(compiled_process_records=sum(value == 'OBSERVED' for value in outcomes.values()),
        failed_process_records=sum(value != 'OBSERVED' for value in outcomes.values()),
        total_process_observation_records=len(unique), raw_utf8_bytes=sum(volume.values()),
        retained_observation_seconds_by_process=costs,
        raw_bytes_by_process=volume, observation_status_by_process=outcomes,
        raw_capture_complete_by_process=complete,
        native_binding_costs_by_process=native_costs, native_binding_errors_by_process=native_errors,
        concurrent_component_times_not_additive=True,
        source='actual completed report records, including observed failed/zero-face processes',
        reported_raw_bytes_exclude_JSON_escaping_and_other_metadata=True,
        numerical_or_literal_diagnostic_byte_equivalence_claim=False)


def native_runtime_probe(args, request, parallel):
    # The actual worker launches with -B and inherits these safe-path settings.
    # The probe checks the same selected native runtime without launching a pool.
    os.environ.update(PYTHONNOUSERSITE='1', PYTHONSAFEPATH='1')
    command = [sys.executable, '-B', '-s', '-P', str(Path(__file__).resolve()),
               '--contract', str(args.contract), '--sha256', args.sha256, '--mode', 'worker-runtime']
    completed = subprocess.run(command, env=dict(os.environ), capture_output=True, check=False,
                               timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(completed.returncode == 0, 'selected worker-style runtime probe failed: '
            + completed.stderr.decode('utf8', 'replace')[-2000:])
    # Only trusted bytes from this request-pinned local child are unpickled.
    require(parallel._runtime() == pickle.loads(completed.stdout), 'caller/worker native runtime differs')
    return dict(native_runtime_equal=True, pool_started=False, command=command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--mode', choices=('preflight', 'baseline', 'arm', 'worker-runtime'), required=True)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--reference-sha256')
    parser.add_argument('--inspect-candidate-build', action='store_true')
    args = parser.parse_args()
    started = perf_counter()
    request = contract(args.contract, args.sha256)
    require(Path(sys.executable).resolve() == Path(request['python']).resolve(), 'wrong interpreter')
    require(sys.flags.dont_write_bytecode and sys.flags.no_user_site and sys.flags.safe_path
            and not sys.flags.hash_randomization and not sys.flags.isolated and not sys.flags.ignore_environment,
            'required -B -s -P/seed-zero flags missing')
    allowed_python = {'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    if args.mode == 'worker-runtime':
        allowed_python.update(PYTHONNOUSERSITE='1', PYTHONSAFEPATH='1')
    require({k.upper(): v for k, v in os.environ.items() if k.upper().startswith('PYTHON')} == allowed_python,
            'unexpected Python environment')
    require(all(os.environ.get(k) == '1' for k in request['numerical_threads']), 'numerical threads differ')
    require(type(args.workers) is int and 1 <= args.workers <= 16, 'invalid requested workers')
    require(not args.inspect_candidate_build or args.mode == 'worker-runtime', 'build inspection is a probe only')
    common = load('w4_common', request['tools']['common'])
    pair = load('plan15_selected_pair', request['tools']['pair'])
    h4 = load('plan15_qualified_h4', request['tools']['h4'])
    inventory = common.arm_inventory(request['arm'])
    require(inventory['root'] == Path(request['permanent_root']).resolve(), 'permanent source root differs')
    pair.install_fence(inventory)
    import private_heat_functionals_parallel_r1 as parallel
    parallel.configure_assembly_observer(args.contract, args.sha256)
    if args.mode == 'worker-runtime':
        payload = parallel._runtime()
        if args.inspect_candidate_build:
            import private_heat_certification_kernel_r1 as certificate
            certificate.h3_status()  # only the explicitly requested build probe initialises H3
            payload = dict(native_runtime=payload, candidate=parallel._candidate_heat_route())
        sys.stdout.buffer.write(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
        return 0
    require(args.output is not None and not args.output.exists(), 'fresh output required')
    require((args.reference is None) == (args.reference_sha256 is None), 'reference needs path and identity')
    require((args.mode == 'arm') == (args.reference is not None),
            'only measured arms require a current-generation reference')
    reference = None
    if args.mode == 'arm':
        require(digest(args.reference) == args.reference_sha256, 'reference identity differs')
        reference = json.loads(args.reference.read_bytes())
        reference_binding(reference, request['generation_binding'])
    # A preflight is import/contract qualification only. Scientific arms retain
    # the conservative declared 4 GiB projection until matching PASS history exists.
    booking = (1 if args.mode == 'preflight' else 4) << 30
    decision = h4.SG.decide(dict(route='plan15-current-'+args.mode,
        binding=request['generation_binding'], workers=args.workers, reference_sha256=args.reference_sha256),
        booking=(booking, 'PROJECTED current-generation '+args.mode+'; no matching completed PASS peak'))
    admission = h4.SG.admit(decision, h4.psutil.virtual_memory().available)
    args.output.mkdir(parents=True, exist_ok=False)
    physical, logical = h4.psutil.cpu_count(logical=False), h4.psutil.cpu_count()
    record = dict(schema='plan15.current-control-result.r1', mode=args.mode,
        generation_binding=request['generation_binding'], workers=args.workers, start_gate=admission,
        reference=None if reference is None else dict(path=str(args.reference),sha256=args.reference_sha256),
        cpu_booking=dict(requested_workers=args.workers,physical_cores=physical,logical_cores=logical,
            scientific_controller_processes=1,retained_guard_supervisor_processes=1,
            additional_conservative_controller_allowance=1,conservative_workers_plus_controllers=args.workers+3,
            queue_idleness_threshold=min(args.workers+3,7),
            conservative_oversubscription_physical=None if physical is None else args.workers+3 > physical,
            conservative_oversubscription_logical=None if logical is None else args.workers+3 > logical,
            queue_monitor='external queue controller; included in machine load',
            queue_exclusive_is_not_OS_reservation=True),
        H3='CANDIDATE_NOT_ENABLED', default_changed=False, status='INCOMPLETE', verdict='FAIL',
        scientific_control_started=False, scientific_control_executed=False,
        selected_context={}, source_finality=False)
    code = 1
    try:
        import run_fresh_interval as fresh
        profile = fresh.FreshProfile.read(Path(request['arm']['profile']['path']), request['arm']['profile']['sha256'])
        sources = fresh.FreshSources(profile)
        with pair.selected_boundary(sources, record['selected_context']):
            import run_prepared_restart as runner
            require(runner.LOGICAL_BYTES == request['logical_budget_bytes'], 'actual runner logical limit differs')
            require(runner.RSS_BYTES == 12 << 30 and runner.FREE_BYTES == 1 << 30, 'actual global guards differ')
            import private_heat_native_issuer_r13 as issuer
            require(callable(issuer.advance_legacy_packaging), 'selected legacy packaging entry absent')
            issuer._verify_implementation()
            issuer.F._check_sources(lambda: None)
            probe = native_runtime_probe(args, request, parallel)
            writer = common.load_source('plan15_selected_funded_writer',
                request['tools']['writer']['path'], request['tools']['writer']['sha256'])
            writer.C = Path(request['tools']['control']['path']).parent
            writer._SELECTED_ORDER_REPAIR = None  # already bound in selected production source
            runtime = pair.observer_runtime(writer, inventory)
            control, control_binding = pair.load_original_control(request['tools']['control'])
            require(control.BUDGET_BYTES == 6 << 30, 'historical CONTROL budget changed')
            # Explicit new harness parameter: use the selected runner's existing
            # limit, never host free RAM and never a changed production budget.
            control.BUDGET_BYTES = runner.LOGICAL_BYTES
            record.update(worker_runtime=probe, control_binding=control_binding,
                original_control_budget_bytes=6 << 30, actual_control_budget_bytes=control.BUDGET_BYTES,
                logical_budget_basis='selected run_fresh_interval -> run_prepared_restart -> start_gate.LOGICAL_BYTES')
            parallel.configure(workers=args.workers)
            if args.mode != 'preflight':
                native = args.output/'original-control.json'
                me = h4.psutil.Process()
                cpu0, own0, t0 = h4.psutil.cpu_times(), me.cpu_times(), perf_counter()
                hooks_before = h4._hooks()
                observation = h4._selector_probe(parallel)
                try:
                    stop, disposition = writer._observer(args.output, 0, Path(request['arm']['control']['path']).parent, runtime)
                    record['scientific_control_started'] = True
                    writer._control_boundary(lambda: control.child(
                        str(Path(request['arm']['control']['path']).parent), str(native)),
                        stop, disposition, args.output)
                finally:
                    h4._selector_probe_end(parallel)
                    try:
                        record['parallel_report'] = parallel.report()
                        record['candidate_h3_route'] = parallel._candidate_heat_route()
                        record['assembly_evidence_volume'] = assembly_observation_totals(record['parallel_report'], record['candidate_h3_route'])
                    except Exception as capture_error:
                        record['assembly_capture_error'] = dict(kind=type(capture_error).__name__, message=str(capture_error))
                record['scientific_control_executed'] = True
                result = json.loads(native.read_bytes())
                report = parallel.report()
                record.update(control=result, parallel_report=report, observer_disposition=disposition)
                # Passive controller evidence was retained in the control-boundary finally block.
                parity(result, None if reference is None else reference['control'])
                calls = [h4._call_summary(call) for call in report['calls']]
                cpu1, own1, wall = h4.psutil.cpu_times(), me.cpu_times(), perf_counter()-t0
                worker_compute = sum(call['worker_compute_seconds'] for call in calls)
                parent_cpu = (own1.user+own1.system)-(own0.user+own0.system)
                system_busy = h4._busy(cpu1)-h4._busy(cpu0)
                # Reuse the qualified exact worker/call/outer-selector acceptance.
                result['h4'] = dict(minimum_faces=report['minimum_faces'], calls=calls,
                    identical=True, differing_from_reference=[], selector=observation,
                    totals=report['totals'], fallbacks=report['fallbacks'],
                    other_load_cpus=round((system_busy-parent_cpu-worker_compute)/wall, 2),
                    module_sha256=digest(parallel.__file__), hooks_before=hooks_before, hooks_after=h4._hooks())
                child = args.output/'child.json'
                common.write_new(child, result)
                arm = dict(arm=0, workers=args.workers)
                require(h4._read_arm(arm, child) is None, 'incomplete current-generation child')
                after = contract(args.contract, args.sha256)
                verdict_code, failures, reduced = h4._verdict(dict(counts=[args.workers], arms=[arm],
                    layout_sha256_before=request['_verified_source_digest'],
                    layout_sha256_after=after['_verified_source_digest'],
                    reference_sha256='BASELINE' if reference is None else args.reference_sha256,
                    reference_sha256_after='BASELINE' if reference is None else digest(args.reference)))
                participation = [sum(process['faces'] > 0 for process in call['processes'])
                                 for call in report['calls']]
                for index, (call, active) in enumerate(zip(arm['calls'], participation, strict=True)):
                    if call['expected_workers'] and active < call['expected_workers']:
                        reduced.append('call %d: %d workers processed faces, %d expected' %
                                       (index, active, call['expected_workers']))
                if not failures and reduced:
                    verdict_code = 3
                record.update(control=result, arm=arm, failures=failures, workers_reduced=reduced,
                    observer_disposition=disposition, scientific_control_executed=True,
                    observed_control_wall_seconds=wall, parent_cpu_seconds=parent_cpu,
                    system_busy_cpu_seconds=system_busy, worker_compute_seconds=worker_compute,
                    participating_face_workers=participation,
                    verdict={0:'PASS', 1:'FAIL', 3:'WORKERS_REDUCED'}[verdict_code])
                # Never call the loader merely to make a reporting field appear.
                identity_started = perf_counter()
                try:
                    record['candidate_h3_identity'] = candidate_worker_identity(report, record['candidate_h3_route'], parallel, request)
                finally:
                    record.setdefault('assembly_evidence_volume', {})['receiver_validation_seconds'] = perf_counter()-identity_started
                record['candidate_batch_fallbacks'] = 'Not separately counted by the unchanged certificate kernel'
                if reference is not None:
                    require(record['candidate_h3_identity'] == reference['candidate_h3_identity'],
                            'candidate execution route/build changed')
                code = verdict_code
            else:
                record['verdict'], code = 'PASS', 0
            pair.audit_imports(dict(source_pins=request['pins']), inventory)
            issuer._verify_implementation()
        contract(args.contract, args.sha256)
        record['source_finality'] = True
        record['status'] = record['verdict']
    except BaseException as error:
        record.update(status='FAIL', verdict='FAIL', error=pair.failure_record(error, 'current-control'))
        code = 1
    finally:
        record['adapter_elapsed_seconds'] = perf_counter()-started
        common.write_new(args.output/'result.json', record)
    print(json.dumps(dict(status=record['status'], mode=args.mode, evidence=str(args.output/'result.json'))))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
