"""Planted mutants of start_gate (the by-need start gate, coordinator item of 16 Oct 2026).

Each mutant is one textual change to the gate source, written to a temporary folder here (never over the
real module). All of test_start_gate (StartGateTests and the route (1) StageRecordTests) then runs against it in a fresh process through
start_gate_mutant_tests.py and must fail. The unmutated source must pass through the same wrapper first,
so a broken wrapper cannot look like a catch. The coordinator's three are the first three: no prediction and
no booking refuses (not a silent default); a booking below the measured peak uses the measured one; a gate
above the available memory refuses. The caller's "with no output" half is tested where the launchers call it.
Prints one line per mutant; exit 1 if any mutant survives or does not apply exactly once.
Usage: python -B start_gate_mutants.py   (seed 0, no -I; writes only temporary folders under this folder)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESUMABILITY = HERE.parents[2]
SOURCE = (RESUMABILITY/'start_gate.py').read_text(encoding='utf8')
WRAPPER = HERE/'start_gate_mutant_tests.py'

NO_PREDICTION = ("        raise StartGateRefused('no completed PASS record of %s and no declared booking: the start "
                 "gate has no '\n                               'prediction and refuses (there is no default)' "
                 "% (key,))")
MEASURED_FIRST = ("    if measured:\n        predicted, basis = max(peak for _, peak in measured), MEASURED\n"
                  "    elif booking is not None:\n        predicted, basis = booking[0], BOOKING\n")
BOOKING_FIRST = ("    if booking is not None:\n        predicted, basis = booking[0], BOOKING\n"
                 "    elif measured:\n        predicted, basis = max(peak for _, peak in measured), MEASURED\n")
RETURN = 'return dict(decision, available_bytes=available_bytes, hash_randomization=0)'

# name: (exact original text, replacement). Each original must occur exactly once in the module.
MUTANTS = {
    'silent_default_without_prediction': (NO_PREDICTION, '        predicted, basis = 10 << 30, BOOKING'),
    'booking_wins_over_measured': (MEASURED_FIRST, BOOKING_FIRST),
    'gate_not_checked_against_available': ('available_bytes >= gate):', 'available_bytes > 0):'),
    'gate_boundary_strict': ('available_bytes >= gate):', 'available_bytes > gate):'),
    'smallest_measured_peak': ('max(peak for _, peak in measured)', 'min(peak for _, peak in measured)'),
    'fifth_rounded_down': ('-(-predicted_peak_bytes // 5)', 'predicted_peak_bytes // 5'),
    'no_margin': ('predicted_peak_bytes + -(-predicted_peak_bytes // 5) + FREE_BYTES', 'predicted_peak_bytes + FREE_BYTES'),
    'no_allowance': ('+ FREE_BYTES + ALLOWANCE_BYTES', '+ FREE_BYTES'),
    'logical_budget_changed': ('12 << 30, 1 << 30, 16 << 30', '12 << 30, 1 << 30, 14 << 30'),
    'duplicate_records_allowed': ("require(len({source for source, _ in measured}) == len(measured), "
                                  "'a record was given twice')", 'pass'),
    'booking_unchecked_with_records': ('    if booking is not None:\n        require(type(booking)',
                                       '    if booking is not None and not measured:\n        require(type(booking)'),
    'self_consistency_dropped': ("and gate == gate_bytes(decision.get('predicted_peak_bytes'))):", 'and gate > 0):'),
    'schema_unchecked': (" and decision.get('schema') == SCHEMA", ''),
    'basis_unchecked': (" and decision.get('basis') in (MEASURED, BOOKING)", ''),
    'seed_unchecked': ("require(getattr(flags, 'hash_randomization', None) == 0,", 'require(True,'),
    'interpreter_flags_ignored': ('flags = sys.flags if flags is None else flags',
                                  "flags = __import__('types').SimpleNamespace(hash_randomization=0) "
                                  "if flags is None else flags"),
    'bools_count_as_bytes': ('return type(value) is int and value > 0', 'return isinstance(value, int) and value > 0'),
    'key_not_copied': ("'key': dict(key),", "'key': key,"),
    'booking_marked_used': ("'used': not measured}", "'used': True}"),
    'booking_labelled_measured': ('predicted, basis = booking[0], BOOKING', 'predicted, basis = booking[0], MEASURED'),
    'decision_mutated_in_place': (RETURN, 'decision.update(available_bytes=available_bytes, hash_randomization=0)\n'
                                          '    return decision'),
    'seed_flag_not_recorded': (RETURN, 'return dict(decision, available_bytes=available_bytes)'),
    # Route (1) wiring helpers (StageRecordTests): stage records, the child's re-admission, the receipts' limits.
    'record_skipped_not_refused': ("        require(peak is not None, 'not a completed PASS record of stage %r interval "
                                   "%r: %s' % (\n            key['stage'], key['interval'], path))\n",
                                   '        if peak is None:\n            continue\n'),
    'record_schema_unchecked': ("record.get('schema') == STAGE_SCHEMA and ", ''),
    'record_stage_unmatched': ("record.get('stage') == key['stage'] and ", ''),
    'record_interval_type_unchecked': (" type(record.get('interval')) is int and", ''),
    'record_interval_unmatched': ("record.get('interval') == key['interval']):", 'True):'),
    'record_status_unchecked': ("record.get('status') in STAGE_PASS", 'True'),
    'record_steps_ok_unchecked': ("all(step.get('ok') is True for step in steps)", 'True'),
    'record_step_names_unchecked': ("tuple(step.get('name') for step in steps) == STAGE_STEPS", 'True'),
    'reader_peak_ignored': ("GUARDED_STEPS = ('runner', 'reader')", "GUARDED_STEPS = ('runner',)"),
    'parent_peak_predicted': ("TREE_PEAK = 'process_tree_rss'", "TREE_PEAK = 'parent_rss'"),
    'sample_shape_unchecked': ('peaks = [sample.get(TREE_PEAK) if type(sample) is dict else None for sample in samples]',
                               'peaks = [sample.get(TREE_PEAK) if type(sample) is dict else sample for sample in samples]'),
    'smaller_guarded_peak': ('return max(sized) if', 'return min(sized) if'),
    'peak_type_unchecked': ('sized = [peak for peak in peaks if type(peak) is int and peak > 0]',
                            'sized = [peak for peak in peaks if peak]'),
    'one_guarded_peak_enough': ('if sized and len(sized) == len(peaks) else None', 'if sized else None'),
    'source_without_hash': ("'%s sha256=%s' % (path, sha256(raw).hexdigest())", 'str(path)'),
    'record_paths_unchecked': ("    require(type(paths) in (list, tuple), 'stage records are given as a list of "
                               "paths')\n", ''),
    'booking_half_accepted': ("    require((booking_bytes is None) == (booking_basis is None),\n            'a declared "
                              "booking needs both --booking-bytes and --booking-basis')\n", ''),
    'child_not_readmitted': ('    return admit(decision, available_bytes, flags)',
                             '    return dict(decision, available_bytes=available_bytes, hash_randomization=0)'),
    'child_text_unchecked': ("    require(type(text) is str, 'this run has no start gate decision: launch it with "
                             "--peak-record or a booking')\n", ''),
    'child_parse_error_escapes': ('    except ValueError:\n        decision = None\n',
                                  '    except TypeError:\n        decision = None\n'),
    'guard_limits_hold_the_prediction': ("'start_available_bytes': admitted['gate_bytes']",
                                         "'start_available_bytes': admitted['predicted_peak_bytes']"),
}


def passes(folder):
    """True if the wrapper's tests all pass against the module in ``folder`` (a fresh process each time)."""
    env = dict(os.environ, PYTHONHASHSEED='0')
    result = subprocess.run([sys.executable, '-B', str(WRAPPER), str(folder/'start_gate.py')],
                            cwd=RESUMABILITY, env=env, capture_output=True, text=True, timeout=300)
    ran = (result.stdout.strip().splitlines() or ['?'])[-1]
    return result.returncode == 0, ran


def write(folder, text):
    folder.mkdir()
    with open(folder/'start_gate.py', 'w', encoding='utf8', newline='\n') as handle:
        handle.write(text)


def main():
    survived, unapplied = [], []
    with tempfile.TemporaryDirectory(prefix='msg-', dir=HERE) as root:
        write(Path(root)/'baseline', SOURCE)
        ok, ran = passes(Path(root)/'baseline')
        print('baseline', 'passes' if ok else 'FAILED', ran, flush=True)
        if not ok:
            print('start gate mutants: the unmutated module must pass through the wrapper; nothing judged')
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
    print('start gate mutants: %d caught, %d survived %s, %d did not apply %s' % (
        caught, len(survived), survived, len(unapplied), unapplied))
    return 1 if survived or unapplied else 0


if __name__ == '__main__':
    sys.exit(main())
