"""Backlog item 11: where the heat tail (conservative finish, native projection) spends its time.

Usage: python -B profile_heat_tail.py LAYOUT OUT_PREFIX

Runs step7_same_call_heat_control's child on an existing prepared LAYOUT (the genuine W4
owner/transport/mesh call, computed twice: r12 and r13 packaging) under cProfile, read-only on
the layout. Writes OUT_PREFIX.pstats and OUT_PREFIX.txt. The text has the cumulative time of the
forward kernel's stages (LOW.solve, FUNCTIONS.reconstruct, SPARSE.solve_rounded, FINISH.finish,
the issuer's projection) and the top functions called inside FINISH.finish and the projection.
cProfile adds overhead, so the shares, not the absolute seconds, are the evidence.
"""
import cProfile
import io
import json
import pstats
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = HERE.parents[2]/'compact-geometry-r1'
STAGES = (('private_heat_low_solver_kernel_r5.py', 'solve'), ('private_heat_functionals_kernel_r5.py', 'reconstruct'),
          ('private_heat_decimal_sparse_core_r2.py', 'solve_rounded'), ('private_heat_finish_kernel_r10.py', 'finish'),
          ('private_heat_native_projection_r4.py', 'project'), ('private_heat_forward_kernel_r13.py', '_run'))


def main():
    layout, prefix = sys.argv[1], Path(sys.argv[2])
    sys.path.insert(0, str(C))
    import step7_same_call_heat_control as CONTROL
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        CONTROL.child(layout, str(prefix)+'-control.json')
    finally:
        profiler.disable()
    profiler.dump_stats(str(prefix)+'.pstats')
    stats = pstats.Stats(profiler)
    lines = ['control '+json.loads(Path(str(prefix)+'-control.json').read_text(encoding='utf8'))['status'], '']
    total = stats.total_tt
    lines.append(f'total profiled seconds {total:.1f}')
    for (filename, line, name), row in sorted(stats.stats.items(), key=lambda item: -item[1][3]):
        for file_name, function in STAGES:
            if Path(filename).name == file_name and name == function:
                lines.append(f'{file_name}:{function}  calls {row[1]}  cumulative {row[3]:.2f} s ({100*row[3]/total:.1f}%)')
    for file_name, function in (('private_heat_finish_kernel_r10.py', 'finish'),
                                ('private_heat_native_projection_r4.py', 'project')):
        stream = io.StringIO()
        view = pstats.Stats(profiler, stream=stream)
        view.sort_stats('cumulative')
        view.print_callees(f'{Path(file_name).stem}.py:\\d+\\({function}\\)')
        lines += ['', f'== callees of {file_name}:{function}', stream.getvalue()[:6000]]
    stream = io.StringIO()
    view = pstats.Stats(profiler, stream=stream)
    view.sort_stats('tottime').print_stats(40)
    lines += ['', '== top 40 by own time', stream.getvalue()[:12000]]
    Path(str(prefix)+'.txt').write_text('\n'.join(lines), encoding='utf8')
    print('\n'.join(lines[:12]))


if __name__ == '__main__':
    main()
