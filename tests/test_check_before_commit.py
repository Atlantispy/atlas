"""Tests of the before-commit candidate guard on throwaway Git repositories; no Atlas test runs here."""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools import check_before_commit as guard

RECEIPT = b'{\n  "status": "PASS"\n}\n'
# Stand-ins for the three guards. The checker fails on any CR in the receipt or on an unexpected record.
CHECKER = b'''import pathlib, sys
evidence = pathlib.Path(__file__).resolve().parents[1] / "tectonics" / "evidence"
sys.exit(1 if b"\\r" in (evidence / "receipt.json").read_bytes() or (evidence / "unexpected.json").exists() else 0)
'''
PASSING = b'import unittest\n\n\nclass Fixture(unittest.TestCase):\n    def test_passes(self):\n        pass\n'
# A program Git must never start here. It creates its marker file, then copies stdin to stdout as a clean filter
# does ("copy") or exits at once, so a process filter or fsmonitor query started by mistake fails instead of hanging.
HELPER = b'''import pathlib, shutil, sys
pathlib.Path(sys.argv[1]).write_bytes(b"ran")
if sys.argv[2:3] == ["copy"]:
    shutil.copyfileobj(sys.stdin.buffer, sys.stdout.buffer)
'''


class DocumentationSelectionTests(unittest.TestCase):
    def snapshot(self, changed=(), *, skipped=(), regular=True):
        return guard.Candidate(Path('candidate'), changed, (), skipped, regular)

    def test_only_reviewed_added_or_modified_documents_qualify(self):
        for path in guard.DOCUMENTATION:
            for status in ('A', 'M'):
                with self.subTest(path=path, status=status):
                    self.assertTrue(guard.documentation_only(self.snapshot((f'{status} {path}',))))

    def test_unknown_or_ambiguous_changes_keep_the_full_route(self):
        changes = [(), ('A (no HEAD commit: every candidate path is new)',),
                   ('D README.md',), ('R100 README.md renamed.md',), ('T README.md',),
                   ('M docs/I01_MELT_SEGREGATION.md',), ('M tectonics/docs/I01_MELT_SEGREGATION.md',),
                   ('A docs/NEW_METHOD.md',), ('M engineering/work/README.md',),
                   ('M README.md', 'M tectonics/src/atlas_tectonics/execution.py'),
                   ('M README.md', 'M tectonics/evidence/current-evidence.json')]
        for changed in changes:
            with self.subTest(changed=changed):
                self.assertFalse(guard.documentation_only(self.snapshot(changed)))
        self.assertFalse(guard.documentation_only(self.snapshot(('A README.md',), regular=False)))
        self.assertFalse(guard.documentation_only(self.snapshot(('M README.md',),
                                                                 skipped=('120000 tectonics/link.md',))))

    def test_omitting_the_suite_keeps_both_mandatory_guards(self):
        steps = guard.checks(Path('candidate'), None)
        self.assertEqual([name for name, _, _ in steps], ['current-evidence register', 'digest line endings'])


@unittest.skipIf(shutil.which('git') is None, 'git is not on PATH; the guard itself requires Git')
class CandidateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'repo'
        self.root.mkdir()
        self.program = Path(temp.name) / 'helper.py'          # outside the checkout
        self.program.write_bytes(HELPER)
        self.git('init', '-q')
        for key, value in (('user.name', 'Guard test'), ('user.email', 'guard@example.invalid'),
                           ('core.autocrlf', 'false'), ('commit.gpgsign', 'false')):
            self.git('config', key, value)
        self.write('.gitattributes', b'*.json text eol=lf\n')
        self.write('.gitignore', b'tectonics/private/\n')
        self.write('tectonics/evidence/receipt.json', RECEIPT)
        self.write('tectonics/tools/tool.py', b'VALUE = 1\n')
        self.write('tectonics/tests/test_digest_line_endings.py', PASSING)
        self.write('tectonics/tests/test_i01_fixture.py', PASSING)
        self.write('tools/check_current_evidence.py', CHECKER)
        self.write('README.md', b'# Guard fixture\n')
        self.git('add', '--all')
        self.git('commit', '-q', '--no-verify', '-m', 'fixture')

    def git(self, *args, cwd=None):
        env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
        env.pop('GIT_INDEX_FILE', None)
        return subprocess.run(['git', *args], cwd=cwd or self.root, env=env, check=True, capture_output=True).stdout

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def main(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = guard.main(['--root', str(self.root), *args])
        return code, output.getvalue()

    def helper(self, name, *extra):
        """Shell command that runs HELPER, which would create the working-tree file MARKER-<name>."""
        words = (Path(sys.executable).as_posix(), self.program.as_posix(), (self.root / f'MARKER-{name}').as_posix(),
                 *extra)
        return ' '.join(f'"{word}"' for word in words)

    def snapshot(self):
        """Every file of the checkout, including the real index, configuration and hooks. Only Git's object store
        is left out: building a candidate may add objects to it, as git add does."""
        files = {}
        for path in self.root.rglob('*'):
            name = path.relative_to(self.root).as_posix()
            if path.is_file() and not name.startswith('.git/objects/'):
                files[name] = path.read_bytes()
        return files

    def assert_refused(self, pattern, staged=False):
        with self.assertRaisesRegex(guard.CandidateError, pattern):
            with guard.candidate(self.root, staged=staged):
                self.fail('the candidate was built')

    def test_a_crlf_working_copy_is_checked_as_the_lf_bytes_git_stores(self):
        self.write('tectonics/evidence/receipt.json', RECEIPT.replace(b'\n', b'\r\n'))
        with guard.candidate(self.root) as snapshot:
            self.assertEqual((snapshot.root / 'tectonics/evidence/receipt.json').read_bytes(), RECEIPT)
            self.assertEqual(snapshot.changed, ())
        self.assertEqual(self.main()[0], 0)

    def test_unstaged_and_untracked_edits_are_checked_but_ignored_files_are_not(self):
        self.write('tectonics/tools/tool.py', b'VALUE = 2\n')
        self.write('tectonics/tools/new.py', b'NEW = True\n')
        self.write('tectonics/private/notes.json', b'{}\n')
        with guard.candidate(self.root) as snapshot:
            self.assertEqual((snapshot.root / 'tectonics/tools/tool.py').read_bytes(), b'VALUE = 2\n')
            self.assertEqual((snapshot.root / 'tectonics/tools/new.py').read_bytes(), b'NEW = True\n')
            self.assertFalse((snapshot.root / 'tectonics/private').exists())
            self.assertEqual(set(snapshot.changed), {'M tectonics/tools/tool.py', 'A tectonics/tools/new.py'})
            self.assertEqual(snapshot.excluded, ())

    def test_staged_mode_checks_the_index_and_names_what_it_leaves_out(self):
        self.write('tectonics/tools/tool.py', b'VALUE = 2\n')
        self.git('add', 'tectonics/tools/tool.py')
        self.write('tectonics/tools/tool.py', b'VALUE = 3\n')
        self.write('tectonics/evidence/unexpected.json', b'{}\n')
        with guard.candidate(self.root, staged=True) as snapshot:
            self.assertEqual((snapshot.root / 'tectonics/tools/tool.py').read_bytes(), b'VALUE = 2\n')
            self.assertFalse((snapshot.root / 'tectonics/evidence/unexpected.json').exists())
            self.assertEqual(set(snapshot.excluded), {'unstaged tectonics/tools/tool.py',
                                                      'untracked tectonics/evidence/unexpected.json'})
        code, output = self.main()                     # the default candidate includes the untracked record
        self.assertEqual(code, 1)
        self.assertIn('FAIL current-evidence register', output)
        code, output = self.main('--staged')           # left out, and reported as left out
        self.assertEqual(code, 0)
        self.assertIn('NOT IN CANDIDATE: untracked tectonics/evidence/unexpected.json', output)

    def test_added_and_modified_regular_documents_select_only_mandatory_checks(self):
        self.write('README.md', b'# Updated guard fixture\n')
        self.write('docs/CURRENT_STATE.md', b'# Current state\n')
        with guard.candidate(self.root) as snapshot:
            self.assertEqual(set(snapshot.changed), {'M README.md', 'A docs/CURRENT_STATE.md'})
            self.assertTrue(snapshot.regular_changes)
            self.assertTrue(guard.documentation_only(snapshot))
        code, output = self.main()
        self.assertEqual(code, 0)
        self.assertIn('reviewed documentation-only changes', output)
        self.assertIn('PASS current-evidence register', output)
        self.assertIn('PASS digest line endings', output)
        self.assertNotIn('I01/I02 tests (', output)
        self.write('tectonics/docs/NEW_METHOD.md', b'# Unreviewed method\n')
        code, output = self.main()
        self.assertEqual(code, 0)
        self.assertIn(f'PASS I01/I02 tests ({guard.TESTS})', output)

    def test_staged_document_selection_uses_only_the_index_and_reports_omissions(self):
        self.write('README.md', b'# Updated guard fixture\n')
        self.git('add', 'README.md')
        self.write('tectonics/tools/tool.py', b'VALUE = 2\n')
        code, output = self.main('--staged')
        self.assertEqual(code, 0)
        self.assertIn('reviewed documentation-only changes', output)
        self.assertIn('NOT IN CANDIDATE: unstaged tectonics/tools/tool.py', output)
        code, output = self.main()
        self.assertEqual(code, 0)
        self.assertIn(f'I01/I02 tests ({guard.TESTS})', output)

    def test_explicit_full_and_test_pattern_override_document_selection(self):
        self.write('README.md', b'# Updated guard fixture\n')
        for args, pattern in ((('--full',), guard.TESTS),
                              (('--tests', 'test_i01_fixture.py'), 'test_i01_fixture.py'),
                              (('--full', '--tests', 'test_i01_fixture.py'), 'test_i01_fixture.py')):
            with self.subTest(args=args):
                code, output = self.main(*args)
                self.assertEqual(code, 0)
                self.assertIn(f'PASS I01/I02 tests ({pattern})', output)
                self.assertNotIn('reviewed documentation-only changes', output)

    def test_document_symlink_outside_exported_trees_keeps_full_checks(self):
        # A Git symlink entry needs no OS symlink privilege. Its added path is in
        # the allowlist but outside EXPORTED, so snapshot.skipped cannot catch it.
        blob = self.git('rev-parse', 'HEAD:README.md').decode('ascii').strip()
        self.git('update-index', '--add', '--cacheinfo', f'120000,{blob},docs/CURRENT_STATE.md')
        with guard.candidate(self.root, staged=True) as snapshot:
            self.assertEqual(snapshot.changed, ('A docs/CURRENT_STATE.md',))
            self.assertEqual(snapshot.skipped, ())
            self.assertFalse(snapshot.regular_changes)
            self.assertFalse(guard.documentation_only(snapshot))
        code, output = self.main('--staged')
        self.assertEqual(code, 0)
        self.assertIn(f'PASS I01/I02 tests ({guard.TESTS})', output)

    def test_document_change_cannot_bypass_failed_evidence_binding(self):
        self.write('tectonics/docs/TECTONICS_PLAN.md', b'bound document\n')
        self.write('tools/check_current_evidence.py', b'''import pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
sys.exit(0 if (root / "tectonics/docs/TECTONICS_PLAN.md").read_bytes() == b"bound document\\n" else 1)
''')
        self.git('add', '--all')
        self.git('commit', '-q', '--no-verify', '-m', 'bind document fixture')
        self.write('tectonics/docs/TECTONICS_PLAN.md', b'changed document\n')
        code, output = self.main()
        self.assertEqual(code, 1)
        self.assertIn('reviewed documentation-only changes', output)
        self.assertIn('FAIL current-evidence register', output)
        self.assertIn('PASS digest line endings', output)
        self.assertNotIn('I01/I02 tests (', output)

    def test_document_change_cannot_bypass_failed_line_ending_guard(self):
        self.write('tectonics/tests/test_digest_line_endings.py', b'''import unittest
class Fixture(unittest.TestCase):
    def test_refuses(self):
        self.fail("synthetic line-ending failure")
''')
        self.git('add', '--all')
        self.git('commit', '-q', '--no-verify', '-m', 'failing line-ending fixture')
        self.write('README.md', b'# Updated guard fixture\n')
        code, output = self.main()
        self.assertEqual(code, 1)
        self.assertIn('reviewed documentation-only changes', output)
        self.assertIn('PASS current-evidence register', output)
        self.assertIn('FAIL digest line endings', output)
        self.assertNotIn('I01/I02 tests (', output)

    def test_the_real_index_and_working_tree_are_left_unchanged(self):
        self.write('tectonics/tools/tool.py', b'VALUE = 2\n')
        self.write('tectonics/tools/new.py', b'NEW = True\n')
        before = self.snapshot()
        for staged in (False, True):
            with guard.candidate(self.root, staged=staged):
                pass
        self.assertEqual(self.snapshot(), before)

    def test_an_applicable_clean_filter_is_refused_before_it_can_run(self):
        # The reviewed reproduction: a tracked attribute sends a normal file through a named clean filter.
        self.write('.gitattributes', b'*.json text eol=lf\ntectonics/tools/tool.py filter=review\n')
        self.git('add', '.gitattributes')
        self.git('commit', '-q', '--no-verify', '-m', 'filter attribute')
        self.git('config', 'filter.review.clean', self.helper('clean', 'copy'))
        self.write('tectonics/tools/tool.py', b'VALUE = 2\n')
        before = self.snapshot()
        for staged in (False, True):                   # git add, or git diff for --staged, would run it
            with self.subTest(staged=staged):
                self.assert_refused("filter 'review' applies to tectonics/tools/tool.py", staged)
        self.assertFalse((self.root / 'MARKER-clean').exists())
        self.assertEqual(self.snapshot(), before)

    def test_an_applicable_process_filter_is_refused_before_it_can_start(self):
        self.write('.gitattributes', b'*.json text eol=lf\n*.dat filter=review\n')
        self.git('add', '.gitattributes')
        self.git('commit', '-q', '--no-verify', '-m', 'filter attribute')
        self.git('config', 'filter.review.process', self.helper('process'))
        self.write('tectonics/tools/new.dat', b'data\n')     # untracked: only git add --all would read it
        before = self.snapshot()
        self.assert_refused("filter 'review' applies to tectonics/tools/new.dat")
        with guard.candidate(self.root, staged=True) as snapshot:    # no indexed path uses the filter
            self.assertEqual(snapshot.excluded, ('untracked tectonics/tools/new.dat',))
        self.assertFalse((self.root / 'MARKER-process').exists())
        self.assertEqual(self.snapshot(), before)

    def test_a_filter_that_no_candidate_path_uses_is_not_refused(self):
        # Git for Windows configures filter.lfs for every repository; only an applicable filter is refused.
        self.git('config', 'filter.unused.clean', self.helper('unused', 'copy'))
        self.git('config', 'filter.unused.process', self.helper('unused'))
        self.write('.gitattributes', b'*.json text eol=lf\ntectonics/tools/tool.py filter=undefined\n')
        self.write('tectonics/tools/tool.py', b'VALUE = 2\n')
        with guard.candidate(self.root) as snapshot:
            self.assertEqual((snapshot.root / 'tectonics/tools/tool.py').read_bytes(), b'VALUE = 2\n')
        self.assertFalse((self.root / 'MARKER-unused').exists())

    def test_hook_files_and_the_fsmonitor_never_run(self):
        self.write('.git/hooks/post-index-change', f'#!/bin/sh\n{self.helper("hook")}\n'.encode())
        (self.root / '.git/hooks/post-index-change').chmod(0o755)      # run by any index write, as by git add
        self.git('config', 'core.fsmonitor', self.helper('fsmonitor'))  # queried whenever an index is read
        self.write('tectonics/tools/tool.py', b'VALUE = 2\n')
        before = self.snapshot()
        for staged, value in ((False, b'VALUE = 2\n'), (True, b'VALUE = 1\n')):
            with self.subTest(staged=staged), guard.candidate(self.root, staged=staged) as snapshot:
                self.assertEqual((snapshot.root / 'tectonics/tools/tool.py').read_bytes(), value)
        self.assertFalse((self.root / 'MARKER-hook').exists())
        self.assertFalse((self.root / 'MARKER-fsmonitor').exists())
        self.assertEqual(self.snapshot(), before)

    def test_a_configured_post_index_change_hook_is_refused_before_it_can_run(self):
        # Git 2.54 and later also run hooks defined in configuration, wherever core.hooksPath points.
        self.git('config', 'hook.review.command', self.helper('confighook'))
        self.git('config', 'hook.review.event', 'post-index-change')
        self.write('tectonics/tools/tool.py', b'VALUE = 2\n')
        before = self.snapshot()
        for staged in (False, True):
            with self.subTest(staged=staged):
                self.assert_refused("hook 'review' is configured for post-index-change", staged)
        self.assertFalse((self.root / 'MARKER-confighook').exists())
        self.assertEqual(self.snapshot(), before)

    def test_a_submodule_is_refused_before_git_can_run_inside_it(self):
        nested = self.root / 'tectonics' / 'nested'
        nested.mkdir()
        self.git('init', '-q', cwd=nested)
        for key, value in (('user.name', 'Guard test'), ('user.email', 'guard@example.invalid'),
                           ('commit.gpgsign', 'false')):
            self.git('config', key, value, cwd=nested)
        (nested / 'data.txt').write_bytes(b'one\n')
        self.git('add', 'data.txt', cwd=nested)
        self.git('commit', '-q', '--no-verify', '-m', 'nested', cwd=nested)
        commit = self.git('rev-parse', 'HEAD', cwd=nested).decode('ascii').strip()
        self.git('update-index', '--add', '--cacheinfo', f'160000,{commit},tectonics/nested')
        # git add and git diff would run git status inside it, passing this edit through the nested clean filter.
        self.write('tectonics/nested/.git/info/attributes', b'* filter=nested\n')
        self.git('config', 'filter.nested.clean', self.helper('submodule', 'copy'), cwd=nested)
        (nested / 'data.txt').write_bytes(b'two\n')
        before = self.snapshot()
        for staged in (False, True):
            with self.subTest(staged=staged):
                self.assert_refused('submodule tectonics/nested', staged)
        self.assertFalse((self.root / 'MARKER-submodule').exists())
        self.assertEqual(self.snapshot(), before)

    def test_every_check_runs_and_any_failure_fails_the_run(self):
        steps = [('fails', [sys.executable, '-c', 'raise SystemExit(3)'], {}),
                 ('passes', [sys.executable, '-c', 'pass'], {})]
        self.assertEqual([(name, code) for name, code, _ in guard.run(steps, self.root)], [('fails', 3), ('passes', 0)])

    def test_the_existing_guards_run_on_the_export_with_its_own_package(self):
        steps = guard.checks(self.root)
        self.assertEqual(steps[0][1][-1], str(self.root / 'tools' / 'check_current_evidence.py'))
        self.assertIn('test_digest_line_endings.py', steps[1][1])
        self.assertEqual(steps[2][1][-1], guard.TESTS)
        self.assertEqual(steps[2][2], {'PYTHONPATH': str(self.root / 'tectonics' / 'src')})


if __name__ == '__main__':
    unittest.main()
