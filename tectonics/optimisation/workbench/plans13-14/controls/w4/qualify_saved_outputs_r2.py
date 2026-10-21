"""Source-bound offline comparison of the immutable, completed q52 arms.

Delivered unrun. A separate one-core native ``runq small`` GO is required:
    P -B -s -P qualify_saved_outputs_r2.py --configuration ABS \
        --configuration-sha256 SHA --entry-sha256 SHA

The configuration supplies source/data authority, never launch authority. The
consumed q52 authority is not consulted for this dispatch. One owned 90-second
child runs only the new offline verifier. The old FAIL result is never changed.
The 0.6-GiB/one-minute prediction is not a measured peak or a hard memory bound.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import traceback
from types import ModuleType


W = Path('C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
R5 = W / 'work/plan14/w4-r5'
R6 = W / 'work/plan14/w4-r6'
COMMON_SHA = 'aaf978590a3523627ab95ccda3b0eaa637213a9bb91c1d5ed351f4f3bb67c33e'
PAIR_SHA = '5bcced77ff205bdeef975288e0141ae8afc64f77e7b1d451b3e05f086157491e'
REQUEST = W / 'work/plan14/w4-launch-r5/science-request-r1/request-authorised-r1.json'
REQUEST_SHA = 'ca14ad081741ef5fed9bfab483495fbfa0065c89d60cdb7aef4300fe4d403fa2'
NATIVE = T / 'ac/p14-w4-r5-r1'
NATIVE_SHA = '2faa023093ffa2c297a961f35e5d40df1048c718752de120d4ed77833e4a5253'
OUTPUT = T / 'ac/p14-saved-output-proof-r2'
FINGERPRINT = 'e72fc9acfa25b262ce8532fcd6391f02da608302d1113404fad45dc439cb1763'
HARNESS = frozenset(('w4_common.py', 'w4_pair.py', 'w4_verify.py', 'preimage_smoke.py',
    'prepare_w4_request.py', 'test_w4_boundaries.py', 'test_w4_metadata.py'))
CONFIG_KEYS = frozenset(('schema', 'request', 'native_result', 'native_output', 'native_files',
    'verifier', 'output', 'resources'))
THREAD_VARIABLES = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
    'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')
BASE_PYTHON = Path('C:/Users/LOCAL_USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
BASE_PYTHON_SHA = 'b07b03b9ba866a341a3c13ee69710fbc8d43d4ce2523dee13f6df5c25378d15b'
VENV_CONFIGURATION_SHA = '0cc4e57ae5742751f5e39ccbc9b7978e428b6466f3f33a4a6e5d5ec9e698d7a2'


def require(value, message):
    if not value:
        raise ValueError(message)


def failure(error, phase):
    return dict(phase=phase, type=type(error).__name__, message=str(error),
        traceback=''.join(traceback.format_exception(type(error), error, error.__traceback__)))


def reference(path, pin):
    return dict(path=str(Path(path).resolve()), sha256=pin)


def interpreter_identity(C, request, executable, base_executable):
    """Bind the selected venv redirector and its one exact physical runtime."""
    selected = Path(request['python']).resolve()
    C.require(Path(executable).resolve() == selected, 'Selected pinned venv interpreter required')
    C.require(Path(base_executable).resolve() == BASE_PYTHON.resolve(), 'Exact physical base interpreter required')
    configuration = selected.parent.parent / 'pyvenv.cfg'
    refs = dict(selected=reference(selected, request['python_sha256']),
        venv_configuration=reference(configuration, VENV_CONFIGURATION_SHA),
        physical=reference(BASE_PYTHON, BASE_PYTHON_SHA))
    for ref in refs.values():
        C.pinned(ref['path'], ref['sha256'])
    return refs


def offline_argv(request, config_ref, entry, *, child=False):
    result = [request['python'], '-B', '-s', '-P', entry['path'],
        '--configuration', config_ref['path'], '--configuration-sha256', config_ref['sha256'],
        '--entry-sha256', entry['sha256']]
    return result + ['--child'] if child else result


def _process_snapshot(processes, pid):
    candidate = processes.Process(pid)
    require(candidate.pid == pid and candidate.is_running(), 'Ancestry process is dead or its PID changed')
    result = dict(pid=pid, create_time=candidate.create_time(), parent_pid=candidate.ppid(),
        executable=str(Path(candidate.exe()).resolve()), argv=candidate.cmdline())
    require(type(result['create_time']) in (int, float)
        and Decimal(str(result['create_time'])).is_finite() and result['create_time'] > 0,
        'Ancestry process birth is unavailable or invalid')
    require(type(result['parent_pid']) is int and result['parent_pid'] > 0
        and type(result['argv']) is list and all(type(item) is str for item in result['argv']),
        'Ancestry process parent or complete argv is unavailable')
    require(candidate.is_running() and candidate.create_time() == result['create_time'],
        'Ancestry process changed while reading')
    return result


def _physical_argv(argv, expected, identity):
    """Only argv[0] may reflect the proved venv-to-base interpreter redirect."""
    return (len(argv) == len(expected) and argv[1:] == expected[1:]
        and Path(argv[0]).is_absolute() and str(Path(argv[0]).resolve()) in
            {identity['selected']['path'], identity['physical']['path']})


def prove_parent_ancestry(C, claim, request, config_ref, entry, configuration,
        processes, current_pid, executable, base_executable):
    """Prove direct ownership or exactly one selected Windows venv redirector.

    No general ancestor search is admitted. The only intermediate process may
    be the exact pinned selected launcher, with the complete child argv and
    direct claimed-owner parent. All process identities are re-read before
    returning to catch death, PID reuse and changed parent/argv observations.
    """
    identity = interpreter_identity(C, request, executable, base_executable)
    C.require(claim.get('schema') == 'atlas.private.plan14.saved-output-parent-claim.r1'
        and claim.get('configuration') == config_ref and claim.get('control_source') == entry
        and claim.get('original_request') == configuration['request']
        and claim.get('interpreter_identity') == identity,
        'Offline parent claim source/configuration/interpreter identity differs')
    owner_pid = claim.get('parent_pid')
    C.require(type(owner_pid) is int and owner_pid > 0 and owner_pid != current_pid,
        'Distinct exact claimed owner PID required')
    current = _process_snapshot(processes, current_pid)
    C.require(current['executable'] == identity['physical']['path']
        and _physical_argv(current['argv'], offline_argv(request, config_ref, entry, child=True), identity),
        'Current offline child physical executable or complete argv differs')
    owner = _process_snapshot(processes, owner_pid)
    C.require(owner['create_time'] == claim.get('parent_create_time')
        and owner['argv'] == claim.get('parent_argv')
        and owner['executable'] == claim.get('parent_executable') == identity['physical']['path']
        and _physical_argv(owner['argv'], offline_argv(request, config_ref, entry), identity),
        'Claimed offline owner PID birth, exact argv or physical executable differs')
    nodes = [current]
    if current['parent_pid'] != owner_pid:
        launcher = _process_snapshot(processes, current['parent_pid'])
        C.require(launcher['pid'] != owner_pid and launcher['parent_pid'] == owner_pid
            and launcher['executable'] == identity['selected']['path']
            and launcher['argv'] == offline_argv(request, config_ref, entry, child=True)
            and owner['create_time'] <= launcher['create_time'] <= current['create_time'],
            'Only one exact selected-venv child redirector may precede the claimed owner')
        nodes.append(launcher)
    C.require(owner['create_time'] <= current['create_time'], 'Claimed owner was born after its child')
    nodes.append(owner)
    for node in nodes:
        C.require(_process_snapshot(processes, node['pid']) == node,
            'Offline ancestry changed during proof; PID reuse/death cannot be accepted')
    return dict(schema='atlas.private.plan14.saved-output-parent-ancestry.r1',
        matched=True, claimed_owner_pid=owner_pid, interpreter_identity=identity,
        layout='DIRECT_OWNER' if len(nodes) == 2 else 'ONE_PINNED_VENV_REDIRECTOR',
        maximum_redirectors=1, nodes_child_to_owner=nodes)


def bootstrap(args):
    entry = Path(__file__).resolve()
    require(entry == R6 / 'qualify_saved_outputs_r2.py', 'Exact new offline entry required')
    require(hashlib.sha256(entry.read_bytes()).hexdigest() == args.entry_sha256,
        'Separate offline entry identity differs')
    path = R5 / 'w4_common.py'
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == COMMON_SHA, 'Fixed retained r5 common source differs')
    C = ModuleType('w4_common')
    C.__file__ = str(path.resolve())
    sys.modules['w4_common'] = C
    exec(compile(raw, str(path), 'exec'), vars(C))
    config_path = Path(args.configuration)
    require(config_path.is_absolute(), 'Explicit absolute configuration required')
    configuration = C.parse(C.pinned(config_path, args.configuration_sha256))
    require(set(configuration) == CONFIG_KEYS
        and configuration['schema'] == 'atlas.private.plan14.saved-output-configuration.r1',
        'Exact saved-output configuration schema/fields required')
    require(Path(configuration['request']['path']).resolve() == REQUEST
        and configuration['request']['sha256'] == REQUEST_SHA,
        'Only the actual immutable q52 source request is admitted')
    require(Path(configuration['native_output']).resolve() == NATIVE
        and Path(configuration['native_result']['path']).resolve() == NATIVE / 'result.json'
        and configuration['native_result']['sha256'] == NATIVE_SHA,
        'Only the completed immutable q52 native output is admitted')
    require(Path(configuration['verifier']['path']).resolve() == R6 / 'w4_verify.py',
        'Explicit new r6 verifier required')
    require(Path(configuration['output']).is_absolute()
        and Path(configuration['output']).resolve() == OUTPUT,
        'Exact distinct new saved-output destination required')
    resources = configuration['resources']
    require(resources.get('classification') == 'PROJECTED'
        and type(resources.get('predicted_peak_gib')) in (int, float)
        and Decimal(str(resources['predicted_peak_gib'])) == Decimal('0.6')
        and type(resources.get('deadline_seconds')) is int and resources['deadline_seconds'] == 90
        and type(resources.get('basis')) is str and resources['basis'],
        'Explicit projected 0.6-GiB/90-second offline bounds required')
    require(not config_path.resolve().is_relative_to(NATIVE)
        and not config_path.resolve().is_relative_to(OUTPUT),
        'Configuration must remain outside original and new output inventories')
    return C, configuration, reference(config_path, args.configuration_sha256), reference(entry, args.entry_sha256)


def regular_files(root):
    """Enumerate this exact output only; refuse links and reparse points."""
    require(root.is_dir(), 'Original native output directory is missing')
    result = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in ('.', *dirs, *files):
            path = Path(directory) if name == '.' else Path(directory) / name
            info = path.lstat()
            require(not stat.S_ISLNK(info.st_mode)
                and not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                'Output inventory contains a link/reparse point: ' + str(path))
        for name in files:
            path = Path(directory) / name
            require(stat.S_ISREG(path.lstat().st_mode), 'Nonregular output inventory member')
            result.add(str(path.resolve()))
    return result


def verify_data(C, configuration):
    raw = configuration['native_files']
    C.require(type(raw) is dict and len(raw) == 55, 'All 55 original native files must be frozen')
    expected = {}
    for name, pin in raw.items():
        path = Path(name)
        C.require(path.is_absolute() and path.resolve().is_relative_to(NATIVE),
            'Native inventory member escapes its original output')
        key = str(path.resolve())
        C.require(key not in expected, 'Duplicate normalised native inventory member')
        expected[key] = pin
    C.require(regular_files(NATIVE) == set(expected), 'Original native file inventory differs')
    C.require(expected.get(str(NATIVE / 'result.json')) == NATIVE_SHA,
        'Failed native result is absent from the complete frozen inventory')
    for path, pin in expected.items():
        C.pinned(path, pin)
    # Re-enumeration detects members added/removed during the bounded read.
    C.require(regular_files(NATIVE) == set(expected), 'Original native inventory changed while reading')
    return expected


def load_bundle(C, configuration, config_ref, entry):
    C.pinned(config_ref['path'], config_ref['sha256'])
    C.pinned(entry['path'], entry['sha256'])
    C.pinned(configuration['verifier']['path'], configuration['verifier']['sha256'])
    request, inventories = C.validate_request(REQUEST, REQUEST_SHA)
    C.require(request['kind'] == 'science' and Path(request['output']).resolve() == NATIVE
        and request['qualification_fingerprint'] == FINGERPRINT
        and len(request['source_pins']) == 2854 and set(request['harness']) == HARNESS,
        'Exact completed q52 scientific inputs and 2854-source closure required')
    for name, ref in request['harness'].items():
        C.require(Path(ref['path']).resolve() == R5 / name, 'Original seven-file r5 harness must remain exact')
        C.pinned(ref['path'], ref['sha256'])
    C.require(request['harness']['w4_common.py']['sha256'] == COMMON_SHA
        and request['harness']['w4_pair.py']['sha256'] == PAIR_SHA,
        'Original common/pair selection differs')
    files = verify_data(C, configuration)
    native = C.parse(C.pinned(NATIVE / 'result.json', NATIVE_SHA))
    C.require(native.get('schema') == 'atlas.private.plan14.w4-run.r1'
        and native.get('kind') == 'science' and native.get('status') == 'FAIL'
        and native.get('passed') is False and native.get('scientific_acceptance') is False
        and native.get('source_finality') is True and native.get('request_sha256') == REQUEST_SHA
        and native.get('qualification_fingerprint') == FINGERPRINT
        and native.get('error', {}).get('type') == 'ValueError'
        and native['error']['message'] == 'Unproved metadata difference cannot be translated'
        and 'comparison' not in native and len(native['stages']) == 2,
        'Retain the exact original metadata-disposition FAIL; no other failed run is admitted')
    arms = []
    for index, (arm, stage) in enumerate(zip(request['arms'], native['stages'], strict=True)):
        C.process_finality(stage)
        expected_argv = [request['python'], '-B', '-s', '-P', request['harness']['w4_pair.py']['path'],
            'child', '--request', str(REQUEST), '--request-sha256', REQUEST_SHA, '--index', str(index)]
        # argv contains Windows spelling; path-valued operands are compared as paths.
        observed = stage['argv']
        C.require(len(observed) == len(expected_argv), 'Original owned child argv shape differs')
        for position, (value, expected) in enumerate(zip(observed, expected_argv, strict=True)):
            C.require(Path(value).resolve() == Path(expected).resolve() if position in (0, 4, 7)
                else value == expected, 'Original owned child argv differs')
        for suffix, pin in stage['log_sha256'].items():
            C.require(suffix in ('stdout', 'stderr'), 'Unexpected original log kind')
            path = NATIVE / ('arm-' + str(index) + '.' + suffix + '.log')
            C.require(files.get(str(path)) == pin, 'Original owned log is not in frozen inventory')
        C.require(set(stage['log_sha256']) == {'stdout', 'stderr'}, 'Both complete original streams required')
        path = NATIVE / ('arm-' + str(index) + '.json')
        receipt = C.parse(C.pinned(path, files[str(path)]))
        C.require(receipt.get('status') == 'PASS' and receipt.get('source_finality') is True
            and receipt.get('request_sha256') == REQUEST_SHA
            and receipt.get('qualification_fingerprint') == FINGERPRINT
            and receipt.get('composition_sha256') == arm['composition']['sha256']
            and receipt.get('profile_sha256') == arm['profile']['sha256'],
            'Complete source-bound original arm receipt required')
        original = receipt['original_control_receipt']
        C.require(Path(original['path']).resolve() == NATIVE / ('arm-' + str(index)) / 'original-control.json'
            and files.get(str(Path(original['path']).resolve())) == original['sha256'],
            'Separate original CONTROL receipt must be frozen')
        arms.append(reference(path, files[str(path)]))
    ref = request['harness']['w4_pair.py']
    P = C.load_source('w4_pair', ref['path'], ref['sha256'])
    return request, inventories, P, native, arms


def finality(C, configuration, config_ref, entry, request, report):
    def source_check():
        C.verify_source_finality(request)
        C.pinned(R5 / 'w4_common.py', COMMON_SHA)
        C.pinned(configuration['verifier']['path'], configuration['verifier']['sha256'])
        interpreter_identity(C, request, sys.executable, sys._base_executable)
    for name, invoke in (
            ('source_finality', source_check),
            ('data_finality', lambda: (C.pinned(config_ref['path'], config_ref['sha256']),
                C.pinned(REQUEST, REQUEST_SHA), verify_data(C, configuration))),
            ('entry_finality', lambda: C.pinned(entry['path'], entry['sha256']))):
        try:
            invoke()
            report[name] = True
        except BaseException as error:
            report['secondary_failures'].append(failure(error, name))
    report['previous_failed_result_unchanged'] = report['data_finality']


def strict_comparison(C, comparison):
    C.require(comparison.get('schema') == 'atlas.private.plan14.w4-verification.r1'
        and comparison.get('passed') is True and comparison.get('exit_code') == 0
        and comparison.get('status') == comparison.get('new_run_verdict') == 'EXACT_COMPARISON_COMPLETE'
        and comparison.get('request_sha256') == REQUEST_SHA
        and comparison.get('scientific_acceptance') is False
        and comparison.get('physical_context_mismatches') == []
        and comparison.get('corresponding_inputs_equal') is True,
        'Actual strict physical/source/identity/numerical comparison did not pass')
    C.require(comparison['arrays'] and all(row['bitwise_equal'] is True and row['differing_rows'] == []
        for row in comparison['arrays'].values()), 'Complete exact array comparison required')
    C.require(comparison['exact_cell_accounts'] and all(row['exact_equal'] is True and row['differing_rows'] == []
        for row in comparison['exact_cell_accounts'].values()), 'Complete exact cell accounts required')
    C.require(comparison['exact_face_account'] == dict(exact_equal=True, differing_faces=[])
        and comparison['exact_scalars'] and all(value is True for value in comparison['exact_scalars'].values())
        and comparison['within_arm_ledger_errors'] == dict(arm_a=[], arm_b=[]),
        'Exact face/scalar/ledger comparison required')
    metadata = comparison['metadata']
    C.require(metadata['coverage'] == 'ALL_LEAVES_PLUS_COMPLETE_PRIVATE_PREIMAGES'
        and metadata['private_correspondence']['exact'] is True
        and all(metadata[key] == [] for key in ('resource_differences', 'invariant_differences',
            'proof_failures', 'unresolved_required_evidence')),
        'No unproved private, numerical, resource or metadata disposition is permitted')


def base_report(configuration, config_ref, entry, request, arms, schema):
    return dict(schema=schema, status='FAIL', passed=False, scientific_acceptance=False,
        genuine_arms_reused=True, previous_failed_result_unchanged=False,
        new_heat_calls=0, new_worker_pool_calls=0, source_authority_not_launch_go=True,
        configuration=config_ref, control_source=entry, verifier=configuration['verifier'],
        original_request=configuration['request'], original_native_result=configuration['native_result'],
        original_status='FAIL', original_error='Unproved metadata difference cannot be translated',
        original_source_fingerprint=request['qualification_fingerprint'], original_harness=request['harness'],
        arms=request['arms'], original_arm_receipts=arms, primary=request['primary'],
        python_sha256=request['python_sha256'], native_files=configuration['native_files'],
        source_pin_count=len(request['source_pins']), resources=configuration['resources'],
        source_finality=False, data_finality=False, entry_finality=False,
        primary_failure=None, secondary_failures=[], retries=0)


def child(args, C, configuration, config_ref, entry, bundle):
    import psutil
    request, inventories, P, unused_native, arms = bundle
    del unused_native
    P.interpreter_environment(request)
    output = Path(configuration['output']).resolve()
    C.require(output.is_dir() and not (output / 'comparison.json').exists()
        and not (output / 'child-result.json').exists(), 'One parent-owned new comparison destination required')
    report = base_report(configuration, config_ref, entry, request, arms,
        'atlas.private.plan14.saved-output-child.r1')
    began = time.monotonic()
    try:
        C.require(all(os.environ.get(name) == '1' for name in THREAD_VARIABLES),
            'One-thread offline environment required')
        claim_path = output / 'parent-claim.json'
        claim = C.parse(claim_path.read_bytes())
        report['parent_ancestry'] = prove_parent_ancestry(C, claim, request, config_ref, entry,
            configuration, psutil, os.getpid(), sys.executable, sys._base_executable)
        report['interpreter_identity'] = report['parent_ancestry']['interpreter_identity']
        report['parent_claim'] = reference(claim_path, C.file_sha(claim_path))
        small = dict(kind='small', resources=dict(predicted_peak_gib=0.6))
        report['admission'] = C.queue_admission(small, {}, set(), os.environ,
            psutil.virtual_memory().available)
        ref = configuration['verifier']
        V = C.load_source('plan14_saved_output_verifier', ref['path'], ref['sha256'])
        comparison = V.verify_pair(request, REQUEST_SHA, NATIVE, inventories)
        comparison_path = output / 'comparison.json'
        C.write_new(comparison_path, comparison)  # preserve the actual report, unchanged
        report['comparison'] = reference(comparison_path, C.file_sha(comparison_path))
        strict_comparison(C, comparison)
        report['status'] = 'PASS'
    except BaseException as error:
        report['primary_failure'] = failure(error, 'offline-strict-comparison')
    finally:
        finality(C, configuration, config_ref, entry, request, report)
        report['seconds'] = time.monotonic() - began
        report['passed'] = (report['status'] == 'PASS' and report['primary_failure'] is None
            and report['secondary_failures'] == [] and all(report[key] is True
                for key in ('source_finality', 'data_finality', 'entry_finality')))
        if not report['passed']:
            report['status'] = 'FAIL'
        C.write_new(output / 'child-result.json', report)
    print(json.dumps(dict(status=report['status'], passed=report['passed'], new_heat_calls=0)), flush=True)
    return 0 if report['passed'] else 1


def parent(args, C, configuration, config_ref, entry, bundle):
    request, unused_inventories, P, native, arms = bundle
    del unused_inventories
    C.require(sys.flags.dont_write_bytecode, 'Native -B required before removing redundant queue variable')
    removed = False
    if 'PYTHONDONTWRITEBYTECODE' in os.environ:
        C.require(os.environ['PYTHONDONTWRITEBYTECODE'] == '1', 'Only redundant queued bytecode=1 may be removed')
        del os.environ['PYTHONDONTWRITEBYTECODE']
        removed = True
    P.interpreter_environment(request)
    # Match clean_environment's numerical thread bound before importing any
    # optional runtime library; Python-variable admission above is unchanged.
    threads_before = {name: os.environ.get(name) for name in THREAD_VARIABLES}
    for name in THREAD_VARIABLES:
        os.environ[name] = '1'
    import psutil
    output = Path(configuration['output']).resolve()
    C.require(not output.exists(), 'Saved-output attempt is immutable; no retry')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    report = base_report(configuration, config_ref, entry, request, arms,
        'atlas.private.plan14.saved-output-comparison.r1')
    report.update(stages=[], process_finality=False, log_finality=False,
        original_stages=native['stages'],
        queue_environment_adjustment=dict(removed_redundant_bytecode_one=removed,
            native_B_retained=True, other_python_variables_unchanged=True),
        thread_environment=dict(before=threads_before,
            enforced={name: os.environ[name] for name in THREAD_VARIABLES}))
    began = time.monotonic()
    try:
        # This independent small-control dictionary never mutates the consumed
        # scientific request or invokes its authority/queue-ticket admission.
        small = dict(kind='small', resources=dict(predicted_peak_gib=0.6))
        report['admission'] = C.queue_admission(small, {}, set(), os.environ,
            psutil.virtual_memory().available)
        identity = interpreter_identity(C, request, sys.executable, sys._base_executable)
        process = _process_snapshot(psutil, os.getpid())
        C.require(process['executable'] == identity['physical']['path']
            and _physical_argv(process['argv'], offline_argv(request, config_ref, entry), identity),
            'Exact offline owner physical executable and complete invocation required')
        report['interpreter_identity'] = identity
        claim_path = output / 'parent-claim.json'
        C.write_new(claim_path, dict(schema='atlas.private.plan14.saved-output-parent-claim.r1',
            configuration=config_ref, control_source=entry, original_request=configuration['request'],
            parent_pid=process['pid'], parent_create_time=process['create_time'], parent_argv=process['argv'],
            parent_executable=process['executable'], interpreter_identity=identity))
        report['parent_claim'] = reference(claim_path, C.file_sha(claim_path))
        ref = request['primary']['supervisor']
        supervisor = C.load_source('plan14_saved_output_supervisor', ref['path'], ref['sha256'])
        C.require(C.file_sha(supervisor.PREVIOUS / 'owned_windows_job.py')
            == request['primary']['owned_backend']['sha256'], 'Original owned backend location differs')
        argv = offline_argv(request, config_ref, entry, child=True)
        stage = supervisor.execute_owned(argv, output, 'owned-comparison', 90, env=P.clean_environment())
        report['stages'].append(stage)
        for suffix in ('stdout', 'stderr'):
            path = output / ('owned-comparison.' + suffix + '.log')
            if path.is_file():
                report.setdefault('owned_logs', {})[suffix] = reference(path, C.file_sha(path))
        process_path = output / 'owned-comparison.process.json'
        if process_path.is_file():
            report['owned_process_record'] = reference(process_path, C.file_sha(process_path))
        child_path = output / 'child-result.json'
        receipt = None
        if child_path.is_file():
            receipt = C.parse(child_path.read_bytes())
            report['child_result'] = reference(child_path, C.file_sha(child_path))
            report['child_evidence'] = receipt
            report['child_primary_failure'] = receipt.get('primary_failure')
            report['child_secondary_failures'] = receipt.get('secondary_failures')
        C.process_finality(stage)
        report['process_finality'] = True
        C.require(set(stage['log_sha256']) == {'stdout', 'stderr'} and all(
            report['owned_logs'][suffix]['sha256'] == stage['log_sha256'][suffix]
            for suffix in ('stdout', 'stderr')), 'Closed owned streams differ from supervisor hashes')
        C.require(C.canonical(C.parse(C.pinned(process_path, report['owned_process_record']['sha256'])))
            == C.canonical(stage), 'Retained owned process record differs from returned stage')
        report['log_finality'] = True
        C.require(receipt and receipt.get('schema') == 'atlas.private.plan14.saved-output-child.r1'
            and receipt.get('status') == 'PASS' and receipt.get('passed') is True
            and receipt.get('primary_failure') is None and receipt.get('secondary_failures') == []
            and all(receipt.get(key) is True for key in ('source_finality', 'data_finality', 'entry_finality',
                'previous_failed_result_unchanged', 'genuine_arms_reused'))
            and receipt.get('configuration') == config_ref and receipt.get('control_source') == entry
            and receipt.get('verifier') == configuration['verifier'] and receipt.get('arms') == request['arms']
            and receipt.get('parent_claim') == report['parent_claim']
            and receipt.get('interpreter_identity') == identity
            and receipt.get('parent_ancestry', {}).get('schema') == 'atlas.private.plan14.saved-output-parent-ancestry.r1'
            and receipt['parent_ancestry'].get('matched') is True
            and receipt['parent_ancestry'].get('claimed_owner_pid') == process['pid']
            and receipt.get('original_request') == configuration['request']
            and receipt.get('original_native_result') == configuration['native_result']
            and receipt.get('original_source_fingerprint') == FINGERPRINT
            and receipt.get('new_heat_calls') == receipt.get('new_worker_pool_calls') == 0
            and receipt.get('scientific_acceptance') is False,
            'Complete bound offline child comparison receipt required')
        comparison_ref = receipt['comparison']
        C.pinned(claim_path, report['parent_claim']['sha256'])
        C.require(Path(comparison_ref['path']).resolve() == output / 'comparison.json',
            'New comparison report escaped the owned output')
        strict_comparison(C, C.parse(C.pinned(comparison_ref['path'], comparison_ref['sha256'])))
        report['comparison'] = comparison_ref
        report['parent_ancestry'] = receipt['parent_ancestry']
        report['status'] = 'PASS'
    except BaseException as error:
        report['primary_failure'] = failure(error, 'owned-offline-comparison')
    finally:
        finality(C, configuration, config_ref, entry, request, report)
        report['seconds'] = time.monotonic() - began
        report['passed'] = (report['status'] == 'PASS' and report['primary_failure'] is None
            and report['secondary_failures'] == [] and len(report['stages']) == 1
            and all(report[key] is True for key in ('source_finality', 'data_finality', 'entry_finality',
                'process_finality', 'log_finality')))
        if not report['passed']:
            report['status'] = 'FAIL'
        C.write_new(output / 'result.json', report)
    print(json.dumps(dict(status=report['status'], passed=report['passed'],
        result=str(output / 'result.json'), scientific_acceptance=False)), flush=True)
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', required=True)
    parser.add_argument('--configuration-sha256', required=True)
    parser.add_argument('--entry-sha256', required=True)
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    try:
        C, configuration, config_ref, entry = bootstrap(args)
        bundle = load_bundle(C, configuration, config_ref, entry)
        if args.child:
            return child(args, C, configuration, config_ref, entry, bundle)
        return parent(args, C, configuration, config_ref, entry, bundle)
    except BaseException as error:
        print(json.dumps(dict(status='FAIL', passed=False, scientific_acceptance=False,
            primary_failure=failure(error, 'saved-output-preflight')), sort_keys=True),
            file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
