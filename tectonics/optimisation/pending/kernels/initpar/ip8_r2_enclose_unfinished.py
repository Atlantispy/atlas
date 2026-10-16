"""Refuter i19, R2: the real enclose_initial_partition when its serial loop raises after the pass started.

Builds test_initpar's fixture and initial partition, then, with a low leaf ceiling (genuine input,
no patching) so that some component is legitimately unmet:
  serial     enclose_initial_partition, no pass: the exception and its initial_accuracy;
  parallel   the same call inside `with InitialParallel(...)`: the exception must be identical; then,
             still inside the with, the pass/session/worker/budget state left behind (finish() is
             never reached), and a second identical call in the same with (must not adopt);
  after      state once the with has exited.
Usage: python -B r2_enclose_unfinished.py OUT.json [--leaves=N] [--workers=W] [--batch=B]
"""
import hashlib
import json
import pickle
import sys
from fractions import Fraction as Q
from pathlib import Path

import psutil

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
sys.path[:0] = [str(T/'ck/ip8/src'), str(R/'composed-r2/helpers'),
                str(T/'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests')]


def _option(name, default):
    return next((a.split('=', 1)[1] for a in sys.argv[2:] if a.startswith(name+'=')), default)


def main():
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    out = Path(sys.argv[1])
    leaves, workers, batch = int(_option('--leaves', '64')), int(_option('--workers', '2')), int(_option('--batch', '8'))
    import atlas_tectonics
    assert Path(atlas_tectonics.__file__).resolve().is_relative_to(T/'ck/ip8/src')
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_initial_parallel as IP
    from atlas_tectonics import integration_volume as V
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.integration_dual_measures import policy_record
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    import i04_differential_fixture as F
    import private_heat_original_spatial_r1 as spatial
    import probe_heat_original_connected_r9 as D
    require_strict_execution()
    me = psutil.Process()
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    report = dict(leaves=leaves, workers=workers, batch=batch)

    def children():
        return [p.pid for p in me.children(recursive=True) if p.is_running()]

    def call(partition, relative):
        try:
            G.enclose_initial_partition(partition, max_volume_error_m3=Q(32000), max_leaves=leaves,
                                        budget=budget, relative_error=relative)
            return dict(raised=None)
        except V.VolumeError as error:
            accuracy = getattr(error, 'initial_accuracy', None)
            return dict(raised=type(error).__name__, message=str(error),
                        cell=None if accuracy is None else accuracy.get('cell_id'),
                        accuracy_pickle=hashlib.sha256(pickle.dumps(accuracy, protocol=5)).hexdigest(),
                        payload_keys=sorted(k for k in vars(error) if not k.startswith('__')))

    def snapshot(pass_):
        session = pass_.session
        return dict(pass_started=pass_.started, pass_closed=pass_.closed, active_is_pass=IP.active() is pass_,
                    session_open=session is not None and session.active(),
                    running_batches=None if session is None else session.running(),
                    held_batches=None if session is None else len(session.batches),
                    live_child_pids=children(), budget_reserved=budget.reserved_bytes,
                    revoker=None if budget._revoker is None else budget._revoker.state,
                    counters={k: pass_.report.get(k) for k in ('batches', 'offered', 'adopted', 'serial',
                                                               'refused', 'note')})

    with ExecutionContext('reference') as reference, \
            F.radial_differential_fixture(budget=budget, pressure_space='q1-p0', material_quadrature=True) as case:
        current, partition = spatial.initial_partition(case, max_components=4096)
        relative = W._decode(policy_record(D.POLICY)['initial_relative_error'])
        first = next(iter(partition.supports))
        report['support_type'] = type(first).__name__
        report['support_has_compact_ref'] = getattr(first, '_compact_ref', None) is not None
        report['components'] = sum(len(s.record()['components']) for s in partition.supports)
        report['budget_reserved_before'] = budget.reserved_bytes
        report['serial'] = call(partition, relative)
        report['budget_reserved_after_serial'] = budget.reserved_bytes
        print('serial', report['serial'], flush=True)
        pass_ = IP.InitialParallel(workers=workers, budget=budget, context=reference, batch_jobs=batch)
        with pass_:
            report['parallel'] = call(partition, relative)
            report['left_open_after_raise'] = snapshot(pass_)
            print('parallel', report['parallel'], report['left_open_after_raise'], flush=True)
            report['second_call'] = call(partition, relative)
            report['after_second_call'] = snapshot(pass_)
            print('second', report['second_call'], report['after_second_call'], flush=True)
        report['after_exit'] = snapshot(pass_)
        report['pass_report_cause'] = pass_.report.get('cause')
        report['pass_report_log'] = pass_.report.get('log')
        reference.verify_boundary()
    report['identical_failure'] = all(report['serial'].get(k) == report[arm].get(k)
                                      for arm in ('parallel', 'second_call')
                                      for k in ('raised', 'message', 'cell', 'accuracy_pickle'))
    out.write_text(json.dumps(report, indent=1, default=str), encoding='utf8')
    print(json.dumps({k: report[k] for k in ('identical_failure', 'left_open_after_raise', 'after_exit')},
                     default=str))


if __name__ == '__main__':
    main()
