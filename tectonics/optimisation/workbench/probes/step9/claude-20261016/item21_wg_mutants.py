"""Item 21 planted mutants of width_gate.gate_next (the gate before interval N+1, N >= 2).

Each mutant is one textual change to the gate source, written to a temporary folder here (never over the
real module). test_width_gate's WidthGateTests then run against it in a fresh process through
item21_wg_mutant_tests.py and must fail. The unmutated source must pass through the same wrapper first,
so a broken wrapper cannot look like a catch.
Not planted, being equivalent: dropping the W(N+2) <= 100% half. With W(N) >= 0,
W(N+2) = 2*W(N+1) - W(N) <= 2*50% - W(N) <= 100% whenever the 50% half passes; both halves stay as approved.
Prints one line per mutant; exit 1 if any mutant survives or does not apply exactly once.
Usage: python -B item21_wg_mutants.py   (writes only temporary folders under this folder)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESUMABILITY = HERE.parents[2]
SOURCE = (RESUMABILITY/'width_gate.py').read_text(encoding='utf8')
WRAPPER = HERE/'item21_wg_mutant_tests.py'

CHECK = 'if not (type(previous) is WidthTable and type(current) is WidthTable'
PROJECT = 'w_next, w_after_next = w+(w-w_previous), w+2*(w-w_previous)'
ROW = "        rows.append({'record': key[0], 'field': key[1], 'w_previous_bits'"
TOP = "'next_interval': current.interval+1, 'passed': passed, 'limit_bits': LIMIT_BITS,"

# name: (exact original text, replacement). Each original must occur exactly once in the module.
MUTANTS = {
    'previous_type_unchecked': (CHECK, 'if not (type(current) is WidthTable'),
    'current_type_unchecked': (CHECK+' and', 'if not (type(previous) is WidthTable and'),
    'current_interval_type_unchecked': (' and type(current.interval) is int\n', '\n'),
    'from_interval_1': ('current.interval >= 2 and', 'current.interval >= 1 and'),
    'previous_interval_type_unchecked': (' and type(previous.interval) is int\n', '\n'),
    'consecutive_unchecked': ('\n            and previous.interval == current.interval-1):', '):'),
    'absent_as_unchanged': ('w, w_previous = after[key], before.get(key, 0)',
                            'w, w_previous = after[key], before.get(key, after[key])'),
    'strict_next': ('ok = w_next <= INTERVAL2_SHARE*LIMIT_BITS', 'ok = w_next < INTERVAL2_SHARE*LIMIT_BITS'),
    'next_share_100': ('ok = w_next <= INTERVAL2_SHARE*LIMIT_BITS', 'ok = w_next <= INTERVAL3_SHARE*LIMIT_BITS'),
    'passed_last_row_only': ('        passed = passed and ok\n'+ROW, '        passed = ok\n'+ROW),
    'unsorted_rows': ('for key in sorted(after):\n        w, w_previous', 'for key in after:\n        w, w_previous'),
    'measured_flag_true': ("'w_previous_measured': key in before", "'w_previous_measured': True"),
    'no_growth_projection': (PROJECT, 'w_next, w_after_next = w, w+2*(w-w_previous)'),
    'after_next_one_step': (PROJECT, 'w_next, w_after_next = w+(w-w_previous), w+(w-w_previous)'),
    'previous_bits_reported_as_current': ("'w_previous_bits': w_previous,", "'w_previous_bits': w,"),
    'row_next_share_from_w': ("'w_next_share': w_next/LIMIT_BITS", "'w_next_share': w/LIMIT_BITS"),
    'row_after_next_share_from_next': ("'w_after_next_share': w_after_next/LIMIT_BITS",
                                       "'w_after_next_share': w_next/LIMIT_BITS"),
    'schema_v1': ("'schema': 'atlas.exact-width-gate.v2'", "'schema': 'atlas.exact-width-gate.v1'"),
    'interval_from_previous': ("'interval': current.interval,", "'interval': previous.interval,"),
    'next_interval_same': (TOP, TOP.replace('current.interval+1', 'current.interval')),
    'passed_reported_true': (TOP, TOP.replace("'passed': passed", "'passed': True")),
    'limit_bits_wrong': (TOP, TOP.replace("'limit_bits': LIMIT_BITS", "'limit_bits': LIMIT_BITS//2")),
    'shares_swapped': ("'next_share': INTERVAL2_SHARE, 'after_next_share': INTERVAL3_SHARE",
                       "'next_share': INTERVAL3_SHARE, 'after_next_share': INTERVAL2_SHARE"),
    'previous_steps_from_current': ("'previous_trajectory_steps': previous.trajectory_steps",
                                    "'previous_trajectory_steps': current.trajectory_steps"),
    'steps_from_previous': ("'trajectory_steps': current.trajectory_steps, 'rows': rows}",
                            "'trajectory_steps': previous.trajectory_steps, 'rows': rows}"),
}


def passes(folder):
    """True if the wrapper's tests all pass against the module in ``folder`` (a fresh process each time)."""
    env = dict(os.environ, PYTHONHASHSEED='0')
    result = subprocess.run([sys.executable, '-B', str(WRAPPER), str(folder/'width_gate.py')],
                            cwd=RESUMABILITY, env=env, capture_output=True, text=True, timeout=300)
    ran = (result.stdout.strip().splitlines() or ['?'])[-1]
    return result.returncode == 0, ran


def write(folder, text):
    folder.mkdir()
    with open(folder/'width_gate.py', 'w', encoding='utf8', newline='\n') as handle:
        handle.write(text)


def main():
    survived, unapplied = [], []
    with tempfile.TemporaryDirectory(prefix='m21w-', dir=HERE) as root:
        write(Path(root)/'baseline', SOURCE)
        ok, ran = passes(Path(root)/'baseline')
        print('baseline', 'passes' if ok else 'FAILED', ran, flush=True)
        if not ok:
            print('item21 width-gate mutants: the unmutated module must pass through the wrapper; nothing judged')
            return 1
        for index, (name, (old, new)) in enumerate(MUTANTS.items()):
            count = SOURCE.count(old)
            if count != 1 or old == new:
                unapplied.append(name)
                print(name, 'DOES NOT APPLY (%d matches)' % count, flush=True)
                continue
            folder = Path(root)/('m%02d' % index)
            write(folder, SOURCE.replace(old, new))
            ok, ran = passes(folder)
            print(name, 'SURVIVED' if ok else 'caught', ran, flush=True)
            if ok:
                survived.append(name)
    caught = len(MUTANTS)-len(survived)-len(unapplied)
    print('item21 width-gate mutants: %d caught, %d survived %s, %d did not apply %s' % (
        caught, len(survived), survived, len(unapplied), unapplied))
    return 1 if survived or unapplied else 0


if __name__ == '__main__':
    sys.exit(main())
