"""Debug runs (--run-profile): the linked tree/tool settings, the wrapped command, the four offline views on one small
raw sample, and a fresh-interval run whose receipt says run_mode debug and has the stage-timing file only with 'stages'.
  python -B -I test_profile_tree_r1.py <shared source root>"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))
from atlas_shared.execution import profiling  # noqa: E402

# Collapsed stacks as the sampler writes them with --subprocesses: process prefix, frames root -> leaf, count.
RAW = '''process 7:"python run.py";main (run.py:10);verify_pin (gate.py:5) 3
process 7:"python run.py";main (run.py:10);solve (heat.py:20) 5
process 8:"python w.py";serve (w.py:3);wait (w.py:4) 2
'''


def view(kind, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        profiling.report(kind, *args)
    return output.getvalue()


class TreeSettings(unittest.TestCase):
    def test_tree_and_tool_are_given_together_and_the_tool_is_a_file(self):
        with tempfile.TemporaryDirectory() as folder:
            tool = Path(folder)/'sampler.exe'
            tool.write_bytes(b'')
            for selection, path in ((frozenset({'tree'}), None), (frozenset({'stacks'}), tool),
                                    (frozenset({'tree'}), Path(folder)/'missing.exe')):
                with self.subTest(selection=selection, path=path), self.assertRaises(ValueError):
                    profiling.profile_tool(selection, path)
            self.assertEqual(profiling.profile_tool(frozenset({'tree', 'stages'}), tool), tool)
            self.assertIsNone(profiling.profile_tool(frozenset(), None))

    def test_wrapped_command_begins_with_the_tool_and_ends_with_the_command(self):
        argv = ['python', '-B', 'guard.py', '--', 'python', 'run.py']
        wrapped = profiling.profile_command(frozenset({'tree'}), argv, raw_path=Path('out/profile-tree.raw'),
                                            executable=Path('sampler.exe'))
        self.assertEqual((wrapped[0], wrapped[-len(argv):]), ('sampler.exe', argv))
        self.assertIn(str(Path('out/profile-tree.raw')), wrapped)
        self.assertIs(profiling.profile_command(frozenset({'stages', 'stacks'}), argv, raw_path=None, executable=None), argv)

    def test_child_words_carry_the_whole_selection(self):
        self.assertEqual(profiling.profile_words(frozenset({'tree', 'stages'})), ['--run-profile', 'stages,tree'])
        self.assertEqual(profiling.profile_words(frozenset()), [])


class Views(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.raw = self.root/'profile-tree.raw'
        self.raw.write_text(RAW, encoding='utf-8')

    def test_active(self):
        self.assertIn('samples 10; wait-leaf 2; active 8; check-stack active 3 (37.5% of active)', view('active', self.raw, 'main'))

    def test_check_share(self):
        self.assertIn('samples 10; check-stack samples 3 (30.0%)', view('check-share', self.raw))

    def test_callers(self):
        text = view('callers', self.raw, 'solve')
        self.assertIn('solve: 5 incl', text)
        self.assertIn('5  run.py:10 main', text)

    def test_rows(self):
        source = self.root/'source'
        source.mkdir()
        (source/'heat.py').write_text('\n'*19 + 'def solve():\n    pass\n', encoding='utf-8')
        notes, out = self.root/'notes.md', self.root/'rows.tsv'
        notes.write_text('| H-1 | heat.py:20 |\n', encoding='utf-8')
        self.assertIn('rows 1; active 8', view('rows', self.raw, source, out, [f'r1={notes}']))
        self.assertEqual(out.read_text(encoding='utf-8').splitlines()[2].split('\t')[:4], ['H-1', '0.05', '0.05', 'solve'])


class DebugRun(unittest.TestCase):
    """The runner's own receipt path with the interval body stubbed: the run profile changes only run_mode and the
    timing file, never what the body records."""

    def run_once(self, folder, run_profile):
        from atlas_tectonics._private.integration import interval_admission as IA, run_fresh_interval as R
        output = Path(folder)/'out'
        output.mkdir()

        def body(profile, *, record, save, **_):
            profiling.checkpoint('body')
            record['science'] = {'heat': sum(range(10))}
            save()

        def write(path, record):
            path.write_text(json.dumps(record), encoding='utf8')
        guard = SimpleNamespace(budget=None, check=lambda force: None, close=lambda: None)
        sources = SimpleNamespace(module=lambda name: SimpleNamespace(ContinuationGuard=lambda *a, **k: guard,
                                                                       _write=write))
        profile = SimpleNamespace(sha256='0'*64, record=lambda: {'store_directory': folder,
                                                                  'output_directory': str(output/'store')})
        patches = (mock.patch.object(IA, 'admitted', lambda paths: contextlib.nullcontext()),
                   mock.patch.object(R, 'FreshSources', lambda profile: sources),
                   mock.patch.object(R, '_recording', lambda sources, asked: None),
                   mock.patch.object(R, 'mode_output', lambda row, mode, interval: output),
                   mock.patch.object(R, '_heat_faces', lambda folder, sources: None),
                   mock.patch.object(R, 'QueryStages', lambda record: SimpleNamespace(observe=lambda: None,
                                                                                    finish=lambda: None)),
                   mock.patch.object(R.SG, 'child_limits', lambda gate: {}),
                   mock.patch.object(R, 'run_fresh_interval', body))
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            self.assertEqual(R._workload(profile, mode='root', run_profile=run_profile), 0)
        return json.loads((output/'run.json').read_text(encoding='utf8')), (output/profiling.FILENAME).is_file()

    def test_stages_writes_debug_and_the_timing_file_with_the_same_results(self):
        runs = {}
        for run_profile in (frozenset({'stages'}), frozenset()):
            with self.subTest(run_profile=run_profile), tempfile.TemporaryDirectory() as folder:
                runs[run_profile] = self.run_once(folder, run_profile)
        (debug, timed), (release, untimed) = runs[frozenset({'stages'})], runs[frozenset()]
        self.assertEqual((debug['run_mode'], timed, 'dev_stage_timing' in debug), ('debug', True, True))
        self.assertEqual((release['run_mode'], untimed, 'dev_stage_timing' in release), ('release', False, False))
        volatile = {'run_mode', 'dev_stage_timing', 'pid', 'parent_cpu_seconds'}
        self.assertEqual({k: v for k, v in debug.items() if k not in volatile},
                         {k: v for k, v in release.items() if k not in volatile})
        self.assertEqual(debug['science'], {'heat': 45})


if __name__ == '__main__':
    unittest.main()
