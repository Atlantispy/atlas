#!/usr/bin/env python3
"""Assess the current bounded W11 study and selected execution safeguards.

No benchmark replay, physical fitting, source repin or broad test discovery.
W10's retained-file bindings and production membership remain required; newly
added W11 tools/tests receive their own before/after inventory here.
"""
import argparse
import json
from pathlib import Path
import platform
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT/'tools')]
from check_w10 import read_json, digest, local, verifier, Measurements

GATES={
    'PT01_selected_thread_parity': ['test_execution_reuse.ExecutionTests.test_parallel_all_kernels_match_serial'],
    'PT03_selected_invalidation': [
        'test_execution_reuse.IdentityTests.test_source_bytes_changes_without_metadata_shortcuts',
        'test_execution_reuse.CacheExecutionTests.test_changed_inputs_parameters_backend_change_identity'],
    'PT04_same_key': ['test_execution_reuse.CacheExecutionTests.test_concurrent_same_request_computes_and_writes_once'],
    'PT05_ownership': ['test_evolving_mechanics.EvolvingMechanicsTests.test_inputs_outputs_and_descriptors_are_detached_immutable_snapshots'],
    'PT06_admission': [
        'test_execution_reuse.CacheExecutionTests.test_wait_timeout_recursive_call_and_saturation',
        'test_combined_resources.CombinedResourcesTests.test_storage_inflight_blocks_executor_without_spinning'],
    'PT08_current_operators': [
        'test_evolving_mechanics.EvolvingMechanicsTests.test_same_coefficients_retain_factor_but_provenance_changes_result',
        'test_evolving_mechanics.EvolvingMechanicsTests.test_changed_prepared_and_cold_have_full_output_parity'],
    'PT09_atomic_failure': ['test_tectonic_history.TectonicHistoryTests.test_cancelled_or_failed_publication_preserves_last_accepted_output'],
    'PT10_recovery': [
        'test_tectonic_history.TectonicHistoryTests.test_corrupt_payload_and_missing_prefix_refuse_without_partial_adoption',
        'test_storage_profiles.StorageProfileTests.test_backup_keeps_new_encodings_and_parent_independence'],
    'PT11_lossless_profiles': ['test_storage_profiles.StorageProfileTests.test_optimised_default_and_named_profiles'],
    'PT13_selected_backend_identity': ['test_execution_reuse.IdentityTests.test_context_equals_fresh_identity'],
}


def retained_w10(path,inventory):
    import numpy as np
    import scipy
    from atlas_tectonics import reuse
    data=read_json(path)
    if (data['schema']!='atlas.w10-assessment.v1' or data['decision']['status']!='ASSESSMENT_COMPLETE'
            or not data['source_unchanged'] or data['tests_run']!=26
            or data['failures'] or data['errors'] or data['skips'] or data['evidence_errors']):
        raise ValueError('required W10 assessment incomplete')
    expected=data['source_sha256']
    if any(inventory.get(name)!=sha for name,sha in expected.items()):
        raise ValueError('W10 recorded source bytes changed; no automatic repin')
    production=lambda values:{k for k in values if k.startswith('src/')}
    if production(expected)!=production(inventory): raise ValueError('W10 production membership changed')
    for name,sha in data['evidence_sha256'].items():
        if digest(local(name))!=sha: raise ValueError('W10 evidence bytes changed')
    for name,binding in data['evidence']['subduction_reference']['reports'].items():
        if digest(local('evidence/'+name))!=binding['sha256']:
            raise ValueError('W10 historical reference bytes changed')
    runtime=dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__,
        interpreter_sha256=reuse._loaded_binary(reuse._interpreter_binary()))
    if data['runtime']!=runtime: raise ValueError('W10 runtime binding changed')
    return dict(status='REUSED_RECORDED_FILES_AND_EXACT_PRODUCTION_MEMBERSHIP',sha256=digest(path),
        added_nonproduction_files=sorted(set(inventory)-set(expected)),physical_reruns=0,
        retained_decision=data['decision'],scope='Added W11 tools/tests separately checked; W10 is not whole-field validation')


def scale_evidence(path):
    import numpy as np
    import scipy
    from atlas_tectonics.reuse import _source_bytes
    from check_w11_scale import summarise_case, SIZES, PAIRS, LIMIT_BYTES
    data=read_json(path)
    if (data['schema']!='atlas.w11-scale-evidence.v1' or data['status']!='PASS_BOUNDED_SCALE'
            or data['source_bindings_unchanged'] is not True):
        raise ValueError('scale study failed or incomplete')
    production={k:json.loads(v) for k,v in _source_bytes().items()}
    if data['sources']['production']!=production: raise ValueError('scale production binding changed')
    for name,sha in data['sources']['tools_and_fixtures'].items():
        if digest(local(name))!=sha: raise ValueError('scale driver/fixture binding changed')
    hw=data['execution_card']['hardware'];runtime=data['runtime']
    if (hw['platform']!=platform.platform() or hw['python']!=platform.python_version()
            or runtime['numpy']!=np.__version__ or runtime['scipy']!=scipy.__version__
            or runtime['native_threads']!=1): raise ValueError('scale runtime binding changed')
    if (data['execution_card']['paired_repetitions']!=PAIRS or
            data['execution_card']['shared_accounting_limit_bytes']!=LIMIT_BYTES
            or [c['grid'] for c in data['cases']]!=[[n,n] for n in SIZES]):
        raise ValueError('scale coverage or limits changed')
    for case in data['cases']:
        if summarise_case(case)!=case['summary']: raise ValueError('scale summary differs from observations')
        for row in case['trials']:
            budget=row['shared_accounting']
            if (budget['reserved_bytes'] or budget['peak_reserved_bytes']>LIMIT_BYTES
                    or len(row['numerical_checks'])!=3
                    or not all(c['mechanical_diagnostics']['gates_passed'] for c in row['numerical_checks'])):
                raise ValueError('scale numerical/resource gates failed')
    return dict(status=data['status'],sha256=digest(path),
        all_sizes_improve_median=all(c['summary']['useful_improvement_observed'] for c in data['cases']),
        cases=[dict(grid=c['grid'],summary=c['summary']) for c in data['cases']],
        process_memory_end=data['process_memory_end'],wall_s=data['wall_before_evidence_write_s'],
        physical_replays=0,scope='Fixed synthetic affine mechanical case only; no planet extrapolation')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.report.exists(): raise FileExistsError('new report path required')
    from check_w11_scale import EvidenceWriter
    with EvidenceWriter(args.report) as writer:
        return assess(writer)


def assess(writer):
    sys.dont_write_bytecode=True
    verify=verifier();before=verify.source_inventory(ROOT)
    evidence_paths=[local('evidence/w10-assessment-r1.json'),local('evidence/w11-scale-r2.json')]
    report=dict(schema='atlas.w11-assessment.v1',source_status='WORKING NON-CANON',status='INCOMPLETE',
        production_ready=False,planetary_scale_validated=False,R4_4_status='HELD_INCOMPLETE',
        source_sha256=before,evidence_sha256={p.name:digest(p) for p in evidence_paths})
    started=time.perf_counter()
    try:
        report['w10']=retained_w10(evidence_paths[0],before)
        report['scale']=scale_evidence(evidence_paths[1])
        suite,selection=verify._acceptance_suite(GATES,'W11')
        if suite.countTestCases()!=14: raise ValueError('W11 requires exactly 14 selected safeguards')
        result=unittest.TextTestRunner(stream=sys.stderr,verbosity=1,resultclass=Measurements).run(suite)
        report.update(selected_tests_by_gate=selection,results=result.rows,tests_run=result.testsRun,
            failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),
            failure_details=[dict(test=t.id(),traceback=s) for t,s in result.failures+result.errors])
        after=verify.source_inventory(ROOT)
        unchanged=after==before and all(digest(p)==report['evidence_sha256'][p.name] for p in evidence_paths)
        report['source_and_evidence_unchanged']=unchanged
        report['status']='PASS_BOUNDED_W11' if verify._checks_passed(result,unchanged) else 'FAIL_OR_INCOMPLETE'
        report['reuse_decision']='RETAIN_MEASURED_PREPARED_PATH' if report['scale']['all_sizes_improve_median'] else 'NO_UNIFORM_BENEFIT'
    except (ValueError,KeyError,OSError,TypeError,AssertionError,RuntimeError) as exc:
        report.update(status='FAIL_OR_INCOMPLETE',failure=dict(type=type(exc).__name__,message=str(exc)))
    report['wall_s']=time.perf_counter()-started
    report['untested_scope']=['Full PT01-PT14 matrix','Distributed mechanics/flux exchange',
        'Adaptive remeshing and arbitrary scale transfer','GPU/MPI/new numerical approximations',
        'Physical envelopes unresolved by W10']
    writer.write(report)
    print(json.dumps({k:report.get(k) for k in ('status','tests_run','failures','errors','skips','wall_s','failure','reuse_decision')},sort_keys=True))
    return 0 if report['status']=='PASS_BOUNDED_W11' else 1


if __name__=='__main__': raise SystemExit(main())
