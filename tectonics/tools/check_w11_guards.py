"""Focused W11 shared-source guard regression; no scientific campaign."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--tests', nargs='+', help='Explicit focused selection, recorded as such; default is the shared W11 guard set.')
    args = parser.parse_args()
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
        os.environ[name] = '1'
    root = args.repo/'tectonics'
    sys.path[:0] = [str(root), str(root/'src'), str(root/'tests'), str(root/'tools')]
    from verify import source_inventory
    from check_w10 import Measurements
    modules = ['test_source_inventory', 'test_source_verification_r4_4',
               'test_execution_reuse.IdentityTests', 'test_foundations',
               'test_w01_workflow.RegionalWorkflowTests.test_cold_restore_and_continuation_match_without_resampling',
               'test_w01_workflow.RegionalWorkflowTests.test_loaded_workflow_implementation_change_invalidates_plan_and_resume',
               'test_w01_workflow.RegionalWorkflowTests.test_cached_transport_matches_direct_and_warm_hit_avoids_kernel',
               'test_w01_workflow.RegionalWorkflowTests.test_budget_refusal_and_close_release_all_reservations',
               'test_w03_workflow.W03WorkflowTests.test_roundtrip_continuation_preserves_all_accounts_and_history',
               'test_w03_workflow.W03WorkflowTests.test_mixed_signed_exchange_retains_clock_and_both_material_receipts',
               'test_w03_workflow.W03WorkflowTests.test_budget_and_cancellation_refuse_without_partial_publication',
               'test_w04_workflow.W04WorkflowTests.test_changed_source_datum_and_loaded_callable_refuse',
               'test_w04_workflow.W04WorkflowTests.test_repeated_projection_reuses_stored_load_and_flexure',
               'test_w04_workflow.W04WorkflowTests.test_finite_capacity_and_linear_validity_limits_refuse',
               'test_w04_regional_workflow.W04RegionalWorkflowTests.test_explicit_halo_load_changes_crop_and_restores_cache_exactly',
               'test_w04_variable_workflow.W04VariableWorkflowTests.test_factors_are_reused_and_budget_is_released',
               'test_w02_completion.PersistenceAndExecutionTests.test_remap_cache_history_invalidation',
               'test_w02_completion.PersistenceAndExecutionTests.test_ale_cache_motion_and_events',
               'test_w02_completion.IntegratedW02Tests.test_event_sequence_regrid_motion_birth_split_merge_restore']
    if args.tests is not None:
        modules = args.tests
    with args.report.open('x', encoding='utf-8') as handle:
        before = source_inventory(root)
        report = dict(schema='atlas.w11-current-guards.v1', status='INCOMPLETE',
            source_status='WORKING NON-CANON', selected_modules=modules,
            source_before=before, platform=platform.platform(), python=platform.python_version(),
            driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        json.dump(report, handle); handle.flush()
        start = time.perf_counter()
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
        result = unittest.TextTestRunner(verbosity=1, resultclass=Measurements).run(suite)
        after = source_inventory(root)
        report.update(wall_s=time.perf_counter()-start, tests_run=result.testsRun,
            results=result.rows, failures=len(result.failures), errors=len(result.errors),
            skips=[dict(test=t.id(), reason=r) for t,r in result.skipped],
            source_unchanged=before==after,
            details=[dict(test=t.id(), traceback=r) for t,r in result.failures+result.errors])
        # A privilege skip is reported, not silently upgraded to zero-skip PASS.
        report['status'] = ('CHECKS_PASSED_WITH_PLATFORM_GAP' if result.skipped else 'PASS') if result.wasSuccessful() and before==after else 'FAIL'
        handle.seek(0); handle.truncate(); json.dump(report, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({k:report[k] for k in ('status','wall_s','tests_run','failures','errors','skips','source_unchanged')}))
    return int(report['status']=='FAIL')


if __name__ == '__main__':
    raise SystemExit(main())
