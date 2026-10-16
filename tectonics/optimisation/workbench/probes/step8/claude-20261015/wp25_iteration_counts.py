"""WP25 evidence: LOW/HIGH sparse-solve iteration counts and times on the genuine W4 heat call.

Usage: python -B wp25_iteration_counts.py LAYOUT OUT_JSON CONTROL_OUT_JSON

Runs step7_same_call_heat_control's child on an existing prepared LAYOUT (it computes the
genuine owner/transport/mesh call twice, r12 and r13 packaging, and compares them), under a
sys.setprofile hook that only READS the return values of the two sparse cores' _solve:
private_heat_decimal_sparse_core_r1 (LOW: SuperLU + Decimal-80 corrections) and
private_heat_decimal_sparse_core_r2 (HIGH: MPFR512 LU + the same corrections). No code object,
module attribute or input is changed. Writes, per solve: core, cells, refinements, final
residual, residual history, factor seconds, solve seconds and L+U nnz.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = HERE.parents[2]/'compact-geometry-r1'
CORES = {'private_heat_decimal_sparse_core_r1.py': 'LOW', 'private_heat_decimal_sparse_core_r2.py': 'HIGH'}


def main():
    layout, out, control_out = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
    sys.path.insert(0, str(C))
    import step7_same_call_heat_control as CONTROL
    solves = []

    def hook(frame, event, arg):
        if event != 'return' or frame.f_code.co_name != '_solve':
            return
        core = CORES.get(Path(frame.f_code.co_filename).name)
        if core is None or type(arg) is not dict:
            return
        diagnostics = arg.get('sparse_diagnostics') or {}
        solves.append({'core': core, 'cells': diagnostics.get('cells'), 'refinements': arg.get('refinements'),
                       'residual': arg.get('residual'), 'residual_history': diagnostics.get('residual_history'),
                       'factor_seconds': diagnostics.get('factor_seconds'), 'solve_seconds': diagnostics.get('seconds'),
                       'factor_L_plus_U_nnz': diagnostics.get('factor_L_plus_U_nnz'),
                       'factor_precision_bits': diagnostics.get('factor_precision_bits')})

    started = time.perf_counter()
    sys.setprofile(hook)
    try:
        CONTROL.child(layout, control_out)
    finally:
        sys.setprofile(None)
    control = json.loads(Path(control_out).read_text(encoding='utf8'))
    result = {'schema': 'atlas.private.wp25-iteration-counts.v1', 'layout': layout,
              'control_status': control.get('status'), 'control_checks': control.get('checks'),
              'cells': control.get('cell_count'), 'faces': control.get('face_count'),
              'seconds_under_profile_hook': round(time.perf_counter()-started, 1), 'solves': solves}
    out.write_text(json.dumps(result, indent=1), encoding='utf8')
    for row in solves:
        print(json.dumps(row))
    print('control', control.get('status'))


if __name__ == '__main__':
    main()
