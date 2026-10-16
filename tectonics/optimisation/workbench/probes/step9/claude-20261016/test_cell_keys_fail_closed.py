"""q09 (D-l cell keys) fails closed: planted mutants on synthetic arms and temp copies; no heat run.

Run (PYTHONHASHSEED=0, through runq.py small): python -B test_cell_keys_fail_closed.py
On a real saved arm too (copied to temp folders, never written): CK_REAL_ARM=<OUT>/ck-g13l1 python -B ... RealArm

check_cell_keys.py: complete permuted arms pass; a missing, None or repeated key, swapped or changed
values, other array names (exit 1); a missing arm, directory or file, a failed child, an array that is
not the control's, a length or cell-count mismatch, mesh order not True, one directory only, repeated
names, an existing report (exit 2). --contrast reports a differing key (exit 0) but not bad evidence.
heat_control_on_frozen.py: the sys.monitoring saver saves only advance() of a file named like the r13
issuer when it returns to the control's child(), costs one callback per return location, never raises
into the call, still saves under a second saver in one process (restart_events; the mutant without it
misses the advance and fails closed), refuses an occupied tool id or an existing folder; the child, with a stand-in control,
exits 1 on a control that does not PASS, a leak, reference arrays that differ or are absent, a frozen
input changed during the run, no save, and refuses an existing output; the complete case exits 0 and
its saved arms pass check_cell_keys.
run_cell_keys.sh: the real script refuses (exit 2, nothing run) a missing output folder, a misplaced,
unknown or repeated route and an existing output; a temp copy wired to stand-in scripts exits 1 when
one child or either check fails while still running every route, 2 on a reference that is not the
pinned one or a second run into the same folder, and 0 only when every part passes.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_cell_keys as K  # noqa: E402
import heat_control_on_frozen as F  # noqa: E402

sys.path.append(str(F.C))
import step7_same_call_heat_control as CONTROL  # noqa: E402

SCRIPT = HERE/'run_cell_keys.sh'
REFERENCE = F.R/'probes'/'step8'/'claude-20261015'/'g13-same-call-live1.json'
BASH = shutil.which('bash')


def digests(arrays):
    return {name: sha256(np.ascontiguousarray(array).tobytes()).hexdigest() for name, array in arrays.items()}


def cells_of(count=6, route='g13l1'):
    return [dict(cell_id='%s-c%d' % (route, i), logical_cell_id='L%d' % i, voxel_index=i) for i in range(count)]


def arrays_of(count=6):
    return {'enthalpy_j': np.arange(count, dtype=np.float64)*1.5+.25,
            'temperature_k': np.arange(count, dtype=np.int64)*7+300}


def write_arm(directory, cells, arrays, status='PASS', mesh=True, cell_count=None):
    """A saved arm as heat_control_on_frozen.py child writes it."""
    directory.mkdir(parents=True)
    table = {}
    for name, array in arrays.items():
        np.save(directory/(name+'.npy'), array, allow_pickle=False)
        table[name] = dict(shape=list(array.shape), dtype=array.dtype.str, sha256=digests({name: array})[name])
    (directory/'arrays.json').write_text(json.dumps(table), encoding='utf8')
    (directory/'cell_keys.json').write_text(json.dumps(dict(mesh_row_order_equal=mesh, cells=cells)), encoding='utf8')
    verdict = dict(status=status, arrays=digests(arrays), cell_count=len(cells) if cell_count is None else cell_count)
    (directory/'frozen_check.json').write_text(json.dumps(verdict), encoding='utf8')
    return directory


def permuted(cells, arrays, order, route):
    """The same cells in another order (rows kept together), with route-specific cell_ids."""
    return ([dict(cells[i], cell_id='%s-c%d' % (route, i)) for i in order],
            {name: array[list(order)] for name, array in arrays.items()})


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='ckt-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)


class CheckCellKeys(Temp):
    ORDER = (3, 0, 5, 1, 4, 2)

    def setUp(self):
        super().setUp()
        self.cells, self.arrays = cells_of(), arrays_of()
        self.base = write_arm(self.tmp/'ck-g13l1', self.cells, self.arrays)
        self.reports = 0

    def other(self, name='ck-r2', edit=None, **kwargs):
        cells, arrays = permuted(self.cells, self.arrays, self.ORDER, name)
        if edit is not None:
            edit(cells, arrays)
        return write_arm(self.tmp/name, cells, arrays, **kwargs)

    def check(self, *dirs, key='logical_cell_id', contrast=False):
        self.reports += 1
        report = self.tmp/('report-%d.json' % self.reports)
        argv = [str(d) for d in dirs]+['--key', key]+(['--contrast'] if contrast else [])+['--report', str(report)]
        with contextlib.redirect_stderr(io.StringIO()):
            code = K.main(argv)
        return code, (json.loads(report.read_text(encoding='utf8')) if report.exists() else None)

    def test_permuted_complete_arms_pass(self):
        code, report = self.check(self.base, self.other(), self.other('ck-d1'))
        self.assertEqual((code, report['verdict']), (0, 'PASS'))
        entry = report['against']['ck-r2']
        self.assertEqual((entry['primary'], entry['secondary'], entry['positional_identical']), ('PASS', 'PASS', False))

    def test_contrast_reports_a_differing_cell_id_without_failing(self):
        other = self.other()
        self.assertEqual(self.check(self.base, other, key='cell_id', contrast=True)[0], 0)
        self.assertEqual(self.check(self.base, other, key='cell_id', contrast=True)[1]['verdict'], 'FAIL')
        self.assertEqual(self.check(self.base, other, key='cell_id')[0], 1)

    def test_missing_key_fails(self):
        code, report = self.check(self.base, self.other(edit=lambda c, a: c[0].pop('logical_cell_id')))
        self.assertEqual((code, report['against']['ck-r2']['missing_keys']), (1, 1))

    def test_none_key_fails(self):
        self.assertEqual(self.check(self.base, self.other(edit=lambda c, a: c[2].update(logical_cell_id=None)))[0], 1)

    def test_none_key_in_base_fails(self):
        shutil.rmtree(self.base)
        self.cells[4]['logical_cell_id'] = None
        write_arm(self.base, self.cells, self.arrays)
        self.assertEqual(self.check(self.base, self.other())[0], 1)

    def test_repeated_key_fails(self):
        def repeat(cells, arrays):
            cells[1]['logical_cell_id'] = cells[0]['logical_cell_id']
        self.assertEqual(self.check(self.base, self.other(edit=repeat))[0], 1)

    def test_two_cells_swapping_values_fail_although_the_multiset_is_equal(self):
        def swap(cells, arrays):
            for array in arrays.values():
                array[[0, 1]] = array[[1, 0]]
        code, report = self.check(self.base, self.other(edit=swap))
        entry = report['against']['ck-r2']
        self.assertEqual((code, entry['primary'], entry['secondary']), (1, 'FAIL', 'PASS'))

    def test_changed_value_fails(self):
        def change(cells, arrays):
            arrays['enthalpy_j'][3] += 1.
        self.assertEqual(self.check(self.base, self.other(edit=change))[0], 1)

    def test_other_array_names_fail(self):
        def extra(cells, arrays):
            arrays['input_source_w'] = np.zeros(len(cells))
        self.assertEqual(self.check(self.base, self.other(edit=extra))[0], 1)

    def test_missing_arm_directory_is_invalid(self):
        code, report = self.check(self.base, self.other(), self.tmp/'ck-d1')
        self.assertEqual((code, report['verdict'], sorted(report['invalid'])), (2, 'INVALID', ['ck-d1']))

    def test_each_missing_file_is_invalid(self):
        for k, name in enumerate(('arrays.json', 'cell_keys.json', 'frozen_check.json', 'temperature_k.npy')):
            other = self.other('ck-m%d' % k)
            (other/name).unlink()
            self.assertEqual(self.check(self.base, other)[0], 2, name)
            self.assertEqual(self.check(other, self.other('ck-n%d' % k))[0], 2, 'base without '+name)

    def test_failed_or_unrecorded_child_is_invalid(self):
        self.assertEqual(self.check(self.base, self.other(status='FAIL'))[0], 2)
        other = self.other('ck-d1')
        verdict = json.loads((other/'frozen_check.json').read_text(encoding='utf8'))
        del verdict['status']
        (other/'frozen_check.json').write_text(json.dumps(verdict), encoding='utf8')
        self.assertEqual(self.check(self.base, other)[0], 2)

    def test_array_that_is_not_the_control_result_is_invalid(self):
        other = self.other()
        np.save(other/'enthalpy_j.npy', np.zeros(6), allow_pickle=False)
        self.assertEqual(self.check(self.base, other)[0], 2)

    def test_length_or_count_mismatch_is_invalid(self):
        self.assertEqual(self.check(self.base, self.other(edit=lambda c, a: c.pop()))[0], 2)
        self.assertEqual(self.check(self.base, self.other('ck-d1', cell_count=7))[0], 2)

    def test_mesh_order_not_true_is_invalid(self):
        self.assertEqual(self.check(self.base, self.other(mesh=False))[0], 2)
        self.assertEqual(self.check(self.base, self.other('ck-d1', mesh=None))[0], 2)

    def test_base_only_or_repeated_names_are_invalid(self):
        self.assertEqual(self.check(self.base)[0], 2)
        twin = write_arm(self.tmp/'elsewhere'/'ck-g13l1', self.cells, self.arrays)
        self.assertEqual(self.check(self.base, twin)[0], 2)

    def test_existing_report_is_not_overwritten(self):
        report = self.tmp/'kept.json'
        report.write_text('kept', encoding='utf8')
        with contextlib.redirect_stderr(io.StringIO()):
            code = K.main([str(self.base), str(self.other()), '--report', str(report)])
        self.assertEqual((code, report.read_text(encoding='utf8')), (2, 'kept'))

    def test_contrast_does_not_excuse_bad_evidence(self):
        self.assertEqual(self.check(self.base, self.other(status='FAIL'), key='cell_id', contrast=True)[0], 2)

    def test_command_line_exit_status(self):
        def run(*args):
            return subprocess.run([sys.executable, '-B', str(HERE/'check_cell_keys.py'), *map(str, args)],
                                  capture_output=True, text=True).returncode
        self.assertEqual(run(self.base, self.other()), 0)
        self.assertEqual(run(self.base, self.other('ck-d1', edit=lambda c, a: c[0].pop('logical_cell_id'))), 1)
        self.assertEqual(run(self.base, self.tmp/'ck-g13l0'), 2)
        self.assertEqual(run(self.base, '--key'), 2)


# --------------------------------------------------------------- the observer and the child
ISSUER_SOURCE = '''
class Result:
    def __init__(self, arrays):
        self._arrays = arrays
        self.array_names = tuple(arrays)

    def array(self, name):
        return self._arrays[name]


def helper(value):
    return value+1


def advance(call):
    return None if call is None else Result(call)
'''


class Row:
    def __init__(self, value):
        self.value = value


class View:
    def __init__(self, rows):
        self._rows, self.cell_count = rows, len(rows)

    def cell(self, index):
        return Row(dict(self._rows[index]))


def snapshot(order):
    return SimpleNamespace(_snapshot=SimpleNamespace(_metadata=json.dumps(dict(cell_ids=order)).encode()))


def load_issuer(folder, name=F.ISSUER):
    folder.mkdir(parents=True, exist_ok=True)
    (folder/name).write_text(ISSUER_SOURCE, encoding='utf8')
    spec = importlib.util.spec_from_file_location('issuer_under_test_%d' % id(folder), folder/name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_child(issuer, arrays, rows, order, helper_calls=0):
    """The control's shape: ``old`` and ``view`` in the frame that calls the issuer's advance()."""
    old, view = snapshot(order), View(rows)        # read by the saver from this frame
    for value in range(helper_calls):
        issuer.helper(value)
    new = issuer.advance(arrays)
    del old, view
    return new


def other_caller(issuer, arrays):
    return issuer.advance(arrays)


class Monitored(Temp):
    def setUp(self):
        super().setUp()
        self.addCleanup(self.free_tool)
        self.arrays = arrays_of()
        self.cells = cells_of()
        self.order = [cell['cell_id'] for cell in self.cells]

    @staticmethod
    def free_tool():
        monitoring = sys.monitoring
        if monitoring.get_tool(F.TOOL) is not None:
            monitoring.set_events(F.TOOL, 0)
            monitoring.register_callback(F.TOOL, monitoring.events.PY_RETURN, None)
            monitoring.free_tool_id(F.TOOL)


class Saver(Monitored):
    def saver(self, caller=fake_child):
        install, remove, state = F._array_saver(self.tmp/'save', caller.__code__)
        install()
        self.addCleanup(remove)
        return remove, state

    def test_saves_only_the_issuer_advance_returning_to_the_child_at_one_callback_per_location(self):
        issuer = load_issuer(self.tmp/'helpers')
        remove, state = self.saver()
        self.assertIsNone(issuer.advance(None))            # a None return: still watching
        fake_child(issuer, self.arrays, self.cells, self.order, helper_calls=5000)
        remove()
        self.assertIsNone(sys.monitoring.get_tool(F.TOOL))
        self.assertEqual((state['saved'], state['error'], state['cells'], state['advance_returns']), (True, None, 6, 2))
        self.assertLess(state['events'], 200)              # not one per call: 5000 helper() returns
        self.assertEqual({name: row['sha256'] for name, row in state['arrays'].items()}, digests(self.arrays))
        for name, array in self.arrays.items():
            self.assertEqual(np.load(self.tmp/'save'/(name+'.npy')).tobytes(), array.tobytes())
        keys = json.loads((self.tmp/'save'/'cell_keys.json').read_text(encoding='utf8'))
        self.assertEqual((keys['mesh_row_order_equal'], keys['cells']), (True, self.cells))
        hooks = state['hooks_at_save']
        self.assertEqual((hooks['profile'], hooks['trace'], hooks['tracemalloc']), (False, False, False))
        self.assertEqual(hooks['monitoring_tools'], {str(F.TOOL): F.TOOL_NAME})

    def test_another_caller_is_recorded_never_raised(self):
        issuer = load_issuer(self.tmp/'helpers')
        remove, state = self.saver()
        self.assertIsNotNone(other_caller(issuer, self.arrays))
        fake_child(issuer, self.arrays, self.cells, self.order)
        remove()
        self.assertFalse(state['saved'])
        self.assertIn('did not return to the control child', state['error'])
        self.assertTrue(F._save_check(state, dict(arrays=digests(self.arrays), cell_count=6)))

    def test_an_advance_in_another_file_is_ignored(self):
        issuer = load_issuer(self.tmp/'helpers', name='private_heat_native_issuer_r12.py')
        remove, state = self.saver()
        fake_child(issuer, self.arrays, self.cells, self.order)
        remove()
        self.assertEqual((state['saved'], state['advance_returns']), (False, 0))
        self.assertIn('was not saved', F._save_check(state, dict(arrays=digests(self.arrays), cell_count=6))[0])

    def test_a_second_saver_in_one_process_still_sees_advance(self):
        issuer = load_issuer(self.tmp/'helpers')       # the same code objects for both savers
        for k in range(2):
            install, remove, state = F._array_saver(self.tmp/('save-%d' % k), fake_child.__code__)
            install()
            try:
                fake_child(issuer, self.arrays, self.cells, self.order)
            finally:
                remove()
            self.assertEqual((state['saved'], state['error']), (True, None), k)

    def test_mutant_without_restart_events_misses_the_second_advance_and_fails_closed(self):
        issuer = load_issuer(self.tmp/'helpers')
        saved = []
        with mock.patch.object(sys.monitoring, 'restart_events', lambda: None):
            for k in range(2):
                install, remove, state = F._array_saver(self.tmp/('stale-%d' % k), fake_child.__code__)
                install()
                try:
                    fake_child(issuer, self.arrays, self.cells, self.order)
                finally:
                    remove()
                saved.append(state['saved'])
        self.assertEqual(saved, [True, False])         # the stale DISABLE; _save_check then reports 'not saved'
        self.assertTrue(F._save_check(state, dict(arrays=digests(self.arrays), cell_count=6)))

    def test_occupied_tool_or_existing_folder_refuses(self):
        sys.monitoring.use_tool_id(F.TOOL, 'someone else')
        install, remove, state = F._array_saver(self.tmp/'save', fake_child.__code__)
        with self.assertRaises(SystemExit):
            install()
        remove()
        self.assertEqual(sys.monitoring.get_tool(F.TOOL), 'someone else')
        with self.assertRaises(FileExistsError):
            F._array_saver(self.tmp/'save', fake_child.__code__)

    def test_save_check_mutants(self):
        state = dict(saved=True, error=None, advance_returns=1, cells=6,
                     arrays={name: dict(sha256=value) for name, value in digests(self.arrays).items()})
        good = dict(arrays=digests(self.arrays), cell_count=6)
        self.assertEqual(F._save_check(state, good), [])
        self.assertTrue(F._save_check(state, dict(good, cell_count=5)))
        self.assertTrue(F._save_check(state, dict(good, arrays=dict(good['arrays'], enthalpy_j='0'*64))))
        self.assertTrue(F._save_check(state, dict(good, arrays={'enthalpy_j': good['arrays']['enthalpy_j']})))
        self.assertTrue(F._save_check(state, dict(good, arrays=None)))
        self.assertTrue(F._save_check(dict(state, error='x'), good))


SCENARIO = {}


def stand_in_child(directory, out):
    """Stands in for step7_same_call_heat_control.child: the r13 advance from its own frame, then OUT."""
    s = SCENARIO
    old, view = snapshot(s['order']), View(s['rows'])        # read by the saver from this frame
    new = s['issuer'].advance(s['arrays']) if s.get('advance', True) else None
    if s.get('mutate'):
        (Path(directory)/'helpers'/'planted.txt').write_text('changed', encoding='utf8')
    if s.get('stray'):
        stray = types.ModuleType('stray_module_under_test')
        stray.__file__ = str(Path(directory).parent/'stray'/'stray_module_under_test.py')
        sys.modules['stray_module_under_test'] = stray
    Path(out).write_text(json.dumps(dict(
        status=s.get('status', 'PASS'), cell_count=len(s['order']), arrays=digests(s['arrays']),
        legacy=dict(result_id='r', metadata_sha256='m', metadata_bytes=1),
        compact=dict(result_id='r', metadata_sha256='m', metadata_bytes=1))), encoding='utf8')
    del old, view, new


class Child(Monitored):
    def setUp(self):
        super().setUp()
        self.workspace = self.tmp/'ws'
        self.layout = self.workspace/'layout'
        self.issuer = load_issuer(self.layout/'helpers')
        (self.layout/'control.json').write_text(json.dumps(dict(paths=[str(self.layout/'helpers')])), encoding='utf8')
        (self.workspace/'out').mkdir()
        self.reference = self.workspace/'reference.json'
        self.reference.write_text(json.dumps(dict(
            arrays=digests(self.arrays), legacy=dict(result_id='r', metadata_sha256='m', metadata_bytes=1),
            compact=dict(result_id='r', metadata_sha256='m', metadata_bytes=1))), encoding='utf8')
        for patch in (mock.patch.object(F, 'WORKSPACE', self.workspace),
                      mock.patch.object(CONTROL, 'child', stand_in_child)):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(sys.modules.pop, 'stray_module_under_test', None)
        self.addCleanup(SCENARIO.clear)

    def run_child(self, name='ck-g13l1', reference=True, cells=None, arrays=None, **scenario):
        cells, arrays = cells or self.cells, arrays or self.arrays
        SCENARIO.clear()
        SCENARIO.update(issuer=self.issuer, arrays=arrays, rows=cells, order=[c['cell_id'] for c in cells], **scenario)
        out, save = self.workspace/'out'/(name+'.json'), self.workspace/'out'/name
        with contextlib.redirect_stdout(io.StringIO()):
            code = F.child(self.layout, out, self.reference if reference else None, save)
        result = json.loads(out.read_text(encoding='utf8'))['frozen_check']
        return code, result, save

    def test_complete_arms_pass_and_their_saves_pass_the_check(self):
        code, result, base = self.run_child()
        self.assertEqual((code, result['status'], result['differences_from_reference']), (0, 'PASS', []))
        self.assertEqual(json.loads((base/'frozen_check.json').read_text(encoding='utf8'))['status'], 'PASS')
        cells, arrays = permuted(self.cells, self.arrays, (5, 4, 3, 2, 1, 0), 'r2')
        code, result, other = self.run_child('ck-r2', reference=False, cells=cells, arrays=arrays)
        self.assertEqual(code, 0, result['differences_from_reference'])
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(K.main([str(base), str(other)]), 0)

    def test_control_that_does_not_pass_fails_and_its_save_cannot_pass(self):
        code, result, save = self.run_child(status='DIFFERS')
        self.assertEqual((code, result['status']), (1, 'FAIL'))
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(K.main([str(save), str(self.run_child('ck-r2', reference=False)[2])]), 2)

    def test_leak_fails(self):
        code, result, _ = self.run_child(stray=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(result['loaded_outside_frozen']), 1)

    def test_reference_arrays_that_differ_or_are_absent_fail(self):
        self.assertEqual(self.run_child(arrays=dict(self.arrays, enthalpy_j=self.arrays['enthalpy_j'][::-1].copy()))[0], 1)
        self.reference.write_text(json.dumps(dict(legacy=dict(result_id='r', metadata_sha256='m', metadata_bytes=1),
                                                  compact=dict(result_id='r', metadata_sha256='m', metadata_bytes=1))),
                                  encoding='utf8')
        code, result, _ = self.run_child('ck-d1')
        self.assertEqual((code, result['differences_from_reference'][:1]), (1, ['reference has no arrays']))

    def test_frozen_input_changed_during_the_run_fails(self):
        code, result, _ = self.run_child(mutate=True)
        self.assertEqual(code, 1)
        self.assertIn('frozen inputs changed during the run', result['differences_from_reference'])

    def test_no_save_fails(self):
        code, result, _ = self.run_child(advance=False)
        self.assertEqual(code, 1)
        self.assertFalse(result['save']['saved'])

    def test_existing_output_refuses_before_running(self):
        (self.workspace/'out'/'ck-g13l1.json').write_text('kept', encoding='utf8')
        with self.assertRaises(SystemExit):
            F.child(self.layout, self.workspace/'out'/'ck-g13l1.json', None, self.workspace/'out'/'ck-g13l1')
        self.assertFalse((self.workspace/'out'/'ck-g13l1').exists())


# --------------------------------------------------------------- run_cell_keys.sh
STAND_IN_CHILD = '''import os, sys
from pathlib import Path
layout, out, reference, save = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5])
out.write_text('{}')
save.mkdir()
with open(os.environ['STAND_IN_CALLS'], 'a') as calls:
    calls.write('child %s %s\\n' % (layout.name, Path(reference).name if reference != '-' else '-'))
sys.exit(1 if layout.name in os.environ.get('STAND_IN_FAIL', '').split(',') else 0)
'''
STAND_IN_CHECK = '''import os, sys
from pathlib import Path
argv = sys.argv[1:]
key, report = argv[argv.index('--key')+1], Path(argv[argv.index('--report')+1])
with open(report, 'x') as handle:
    handle.write('{}')
dirs = [Path(item).name for item in argv[:argv.index('--key')]]
with open(os.environ['STAND_IN_CALLS'], 'a') as calls:
    calls.write('check %s %s %s\\n' % (key, '--contrast' in argv, ' '.join(dirs)))
sys.exit(int(os.environ.get('STAND_IN_CHECK_'+key, '0')))
'''


@unittest.skipIf(BASH is None, 'no bash')
class Script(Temp):
    def bash(self, script, *args, **env):
        environment = dict(os.environ, **env)
        args = [arg.as_posix() if isinstance(arg, Path) else arg for arg in args]
        return subprocess.run([BASH, script.as_posix(), *args], capture_output=True, text=True, env=environment,
                              timeout=300)

    def refused(self, done, why):
        self.assertEqual(done.returncode, 2, done.stdout+done.stderr)
        self.assertIn('=== REFUSED: '+why, done.stdout)

    def test_real_script_refuses_before_running_anything(self):
        out = self.tmp/'out'
        self.refused(self.bash(SCRIPT, out), 'no output folder')
        out.mkdir()
        self.refused(self.bash(SCRIPT, out, 'g13l0', 'g13l1'), 'the first route must be g13l1')
        self.refused(self.bash(SCRIPT, out, 'g13l1', 'nowhere'), 'unknown route nowhere')
        self.refused(self.bash(SCRIPT, out, 'g13l1', 'r2', 'r2'), 'a route is given twice')
        (out/'ck-r2').mkdir()
        self.refused(self.bash(SCRIPT, out), 'output exists')
        (out/'ck-r2').rmdir()
        (out/'ck-check-cell_id.json').write_text('kept', encoding='utf8')
        self.refused(self.bash(SCRIPT, out), 'output exists')
        self.assertEqual(sorted(path.name for path in out.iterdir()), ['ck-check-cell_id.json'])

    def copy(self):
        """A temp copy of the tree the script reads, wired to the stand-ins."""
        root = self.tmp/'T'
        r = root/F.R.relative_to(F.WORKSPACE)
        s, d = r/'probes'/'step9'/'claude-20261016', r/'probes'/'step8'/'claude-20261015'
        for folder in (s, d, r/'L'):
            folder.mkdir(parents=True)
        for layout in (r/'probes'/'step8'/'g13l1', r/'probes'/'step8'/'g13l0', r/'L'/'d1', r/'composed-checks'/'hc-r2'):
            layout.mkdir(parents=True)
            (layout/'control.json').write_text('{}', encoding='utf8')
        shutil.copyfile(REFERENCE, d/REFERENCE.name)
        (s/'heat_control_on_frozen.py').write_text(STAND_IN_CHILD, encoding='utf8')
        (s/'check_cell_keys.py').write_text(STAND_IN_CHECK, encoding='utf8')
        raw = SCRIPT.read_bytes()
        real_t, real_p = b'T="%s"' % F.WORKSPACE.as_posix().encode(), b'P="$T/.r44-env/Scripts/python.exe"'
        # Never run the real children from a test: both lines must be found once and replaced.
        self.assertEqual((raw.count(real_t), raw.count(real_p)), (1, 1))
        wired = raw.replace(real_t, b'T="%s"' % root.as_posix().encode()).replace(
            real_p, b'P="%s"' % Path(sys.executable).as_posix().encode())
        real = [line.split(b'=')[0] for line in wired.splitlines() if F.WORKSPACE.as_posix().encode() in line]
        self.assertEqual(real, [b'P'])                       # only the interpreter is the real one
        self.assertEqual(wired.count(b'\n'), raw.count(b'\n'))
        (s/'run_cell_keys.sh').write_bytes(wired)
        return s/'run_cell_keys.sh', r/'L', d/REFERENCE.name

    def wired_run(self, **env):
        script, out, reference = self.copy()
        calls = self.tmp/'calls.txt'
        done = self.bash(script, **dict(env, STAND_IN_CALLS=str(calls)))
        return done, (calls.read_text(encoding='utf8').splitlines() if calls.exists() else []), script, out, reference

    def test_every_part_passing_exits_0_with_the_reference_on_g13l1_only(self):
        done, calls, *_ = self.wired_run()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(calls, ['child g13l1 g13-same-call-live1.json', 'child g13l0 -', 'child d1 -', 'child hc-r2 -',
                                 'check logical_cell_id False ck-g13l1 ck-g13l0 ck-d1 ck-r2',
                                 'check cell_id True ck-g13l1 ck-g13l0 ck-d1 ck-r2'])
        self.assertIn('=== PASSED', done.stdout)

    def test_one_failed_child_exits_1_after_every_route_and_check(self):
        done, calls, *_ = self.wired_run(STAND_IN_FAIL='g13l0')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len(calls), 6)
        self.assertIn('=== FAILED', done.stdout)

    def test_a_failed_primary_or_contrast_check_exits_1(self):
        self.assertEqual(self.wired_run(STAND_IN_CHECK_logical_cell_id='1')[0].returncode, 1)
        shutil.rmtree(self.tmp/'T')
        (self.tmp/'calls.txt').unlink()
        self.assertEqual(self.wired_run(STAND_IN_CHECK_cell_id='2')[0].returncode, 1)

    def test_second_run_into_the_same_folder_or_another_reference_refuses(self):
        done, calls, script, out, reference = self.wired_run()
        self.assertEqual(done.returncode, 0)
        self.refused(self.bash(script, STAND_IN_CALLS=str(self.tmp/'calls.txt')), 'output exists')
        self.assertEqual(len((self.tmp/'calls.txt').read_text(encoding='utf8').splitlines()), 6)
        fresh = self.tmp/'fresh'
        fresh.mkdir()
        reference.write_bytes(reference.read_bytes()+b' ')
        self.refused(self.bash(script, fresh, STAND_IN_CALLS=str(self.tmp/'calls.txt')), 'reference')
        self.assertEqual(list(fresh.iterdir()), [])


# --------------------------------------------------------------- one real saved arm (after the smoke)
@unittest.skipUnless(os.environ.get('CK_REAL_ARM'), 'set CK_REAL_ARM to a saved arm (ck-g13l1) to run on real data')
class RealArm(Temp):
    """The real arm saved by the smoke, copied into temp folders: a copy passes; a planted swap, None key or
    changed value fails; nothing under the arm is written."""

    def setUp(self):
        super().setUp()
        self.real = Path(os.environ['CK_REAL_ARM']).resolve()
        self.before = {path.name: sha256(path.read_bytes()).hexdigest() for path in self.real.iterdir()}
        self.base = self.tmp/self.real.name
        shutil.copytree(self.real, self.base)

    def tearDown(self):
        self.assertEqual({path.name: sha256(path.read_bytes()).hexdigest() for path in self.real.iterdir()},
                         self.before)

    def copy(self, name, edit=None):
        other = self.tmp/name
        shutil.copytree(self.real, other)
        if edit is not None:
            table = json.loads((other/'arrays.json').read_text(encoding='utf8'))
            keys = json.loads((other/'cell_keys.json').read_text(encoding='utf8'))
            arrays = {key: np.load(other/(key+'.npy'), allow_pickle=False) for key in table}
            edit(keys['cells'], arrays)
            verdict = json.loads((other/'frozen_check.json').read_text(encoding='utf8'))
            for array_name, array in arrays.items():          # consistent evidence: the check must catch the criterion
                (other/(array_name+'.npy')).unlink()
                np.save(other/(array_name+'.npy'), array, allow_pickle=False)
                table[array_name]['sha256'] = verdict['arrays'][array_name] = digests({array_name: array})[array_name]
            (other/'arrays.json').write_text(json.dumps(table), encoding='utf8')
            (other/'cell_keys.json').write_text(json.dumps(keys), encoding='utf8')
            (other/'frozen_check.json').write_text(json.dumps(verdict), encoding='utf8')
        return other

    def check(self, *dirs, key='logical_cell_id'):
        report = self.tmp/('report-%s.json' % dirs[-1].name)
        with contextlib.redirect_stderr(io.StringIO()):
            code = K.main([str(d) for d in dirs]+['--key', key, '--report', str(report)])
        return code, json.loads(report.read_text(encoding='utf8'))

    def test_real_arm_evidence_and_a_copy_pass(self):
        code, report = self.check(self.base, self.copy('copy'))
        entry = report['against']['copy']
        self.assertEqual((code, entry['primary'], entry['secondary'], entry['positional_identical']),
                         (0, 'PASS', 'PASS', True))
        self.assertGreater(report['cells'], 1)
        print('\nreal arm: %d cells, arrays %s' % (report['cells'], sorted(json.loads(
            (self.real/'arrays.json').read_text(encoding='utf8')))), file=sys.stderr)

    def test_real_arm_with_two_cells_swapping_values_fails_although_the_multiset_is_equal(self):
        def swap(cells, arrays):
            rows = [tuple(arrays[key][i].tobytes() for key in sorted(arrays)) for i in range(len(cells))]
            j = next(j for j in range(1, len(rows)) if rows[j] != rows[0])      # a cell whose values differ
            for array in arrays.values():
                array[[0, j]] = array[[j, 0]]
        code, report = self.check(self.base, self.copy('swapped', swap))
        entry = report['against']['swapped']
        self.assertEqual((code, entry['primary'], entry['secondary']), (1, 'FAIL', 'PASS'))

    def test_real_arm_with_a_none_key_or_a_changed_value_fails(self):
        self.assertEqual(self.check(self.base, self.copy('nokey', lambda c, a: c[0].update(logical_cell_id=None)))[0], 1)

        def change(cells, arrays):
            array = arrays[sorted(arrays)[0]]
            array.reshape(-1).view(np.uint8)[0] ^= 1
        self.assertEqual(self.check(self.base, self.copy('changed', change))[0], 1)


if __name__ == '__main__':
    unittest.main(verbosity=1)
