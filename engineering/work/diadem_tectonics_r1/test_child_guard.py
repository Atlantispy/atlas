"""Small subprocess fixtures only; never imports or runs a legacy generator."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import child_guard


class ChildGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="diadem-guard-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "trial"
        self.root.mkdir()
        self.script = self.root / "fixture.py"
        self.outside = self.base / "reserved-sibling.txt"
        self.source = self.base / "readonly-source.txt"
        self.source.write_text("preserve source", encoding="utf-8")

    def invoke(self, code, *, script=None, write_root=None):
        self.script.write_text(code, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-I", "-B", str(Path(child_guard.__file__).resolve()),
             "--write-root", str(self.root if write_root is None else write_root),
             "--script", str(self.script if script is None else script)],
            cwd=self.root, capture_output=True, text=True, encoding="utf-8",
            timeout=20, check=False,
        )

    def assert_blocked(self, result):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('"status": "GUARD_BLOCKED"', result.stderr)
        self.assertEqual(self.source.read_text("utf-8"), "preserve source")

    def test_permitted_writes_imports_and_argv(self):
        result = self.invoke(
            "import json, os, sys, tempfile\nfrom pathlib import Path\n"
            "assert __name__ == '__main__'\nassert len(sys.argv) == 1\n"
            "p=Path('nested'); p.mkdir(); (p/'one').write_text('ok')\n"
            "os.rename(p/'one',p/'two')\n"
            "with tempfile.TemporaryFile() as f: f.write(b'temporary')\n"
            "print(json.dumps({'argv':sys.argv,'tmp':tempfile.gettempdir(),'cache':os.environ['XDG_CACHE_HOME']}))\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["argv"], [str(self.script)])
        self.assertEqual(Path(payload["tmp"]), self.root / "_runtime" / "tmp")
        self.assertEqual(Path(payload["cache"]), self.root / "_runtime" / "cache")
        self.assertEqual((self.root / "nested" / "two").read_text(), "ok")

    def test_sibling_write_forbidden(self):
        self.assert_blocked(self.invoke(f"from pathlib import Path\nPath({str(self.outside)!r}).write_text('escape')\n"))
        self.assertFalse(self.outside.exists())

    def test_os_open_write_flags_forbidden(self):
        self.assert_blocked(self.invoke(f"import os\nos.open({str(self.outside)!r},os.O_WRONLY|os.O_CREAT)\n"))
        self.assertFalse(self.outside.exists())

    def test_source_modification_forbidden(self):
        self.assert_blocked(self.invoke(f"from pathlib import Path\nPath({str(self.source)!r}).write_text('changed')\n"))

    def test_readonly_input_allowed(self):
        result = self.invoke(f"from pathlib import Path\nPath('copy.txt').write_text(Path({str(self.source)!r}).read_text())\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "copy.txt").read_text(), "preserve source")
        self.assertEqual(self.source.read_text(), "preserve source")

    def test_mkdir_escape_forbidden(self):
        directory = self.base / "reserved-outside-directory"
        self.assert_blocked(self.invoke(f"import os\nos.mkdir({str(directory)!r})\n"))
        self.assertFalse(directory.exists())

    def test_rename_destination_escape_forbidden(self):
        inside = self.root / "inside.txt"
        inside.write_text("keep")
        self.assert_blocked(self.invoke(f"import os\nos.rename({str(inside)!r},{str(self.outside)!r})\n"))
        self.assertEqual(inside.read_text(), "keep")
        self.assertFalse(self.outside.exists())

    def test_rename_source_escape_forbidden(self):
        self.assert_blocked(self.invoke(f"import os\nos.replace({str(self.source)!r},'stolen.txt')\n"))
        self.assertFalse((self.root / "stolen.txt").exists())

    def test_remove_escape_forbidden(self):
        self.assert_blocked(self.invoke(f"import os\nos.remove({str(self.source)!r})\n"))

    def test_truncate_escape_forbidden(self):
        self.assert_blocked(self.invoke(f"import os\nos.truncate({str(self.source)!r},0)\n"))

    def test_chmod_escape_forbidden(self):
        before = self.source.stat().st_mode
        self.assert_blocked(self.invoke(f"import os\nos.chmod({str(self.source)!r},0o600)\n"))
        self.assertEqual(self.source.stat().st_mode, before)

    def test_utime_escape_forbidden(self):
        before = self.source.stat().st_mtime_ns
        self.assert_blocked(self.invoke(f"import os\nos.utime({str(self.source)!r},(1,1))\n"))
        self.assertEqual(self.source.stat().st_mtime_ns, before)

    def test_chdir_escape_forbidden(self):
        self.assert_blocked(self.invoke(f"import os\nos.chdir({str(self.base)!r})\n"))

    def test_nondefault_dir_fd_forbidden(self):
        self.assert_blocked(self.invoke("import sys\nsys.audit('os.remove','unused.txt',123)\n"))

    def test_os_open_dir_fd_forbidden_before_syscall(self):
        self.assert_blocked(self.invoke("import os\nos.open('unused.txt',os.O_WRONLY|os.O_CREAT,dir_fd=123)\n"))
        self.assertFalse((self.root / "unused.txt").exists())

    def test_links_forbidden_even_inside_root(self):
        self.assert_blocked(self.invoke("import os\nos.link('fixture.py','linked.py')\n"))
        self.assertFalse((self.root / "linked.py").exists())

    def test_symlink_event_forbidden(self):
        self.assert_blocked(self.invoke("import sys\nsys.audit('os.symlink','fixture.py','linked.py',-1)\n"))

    def test_subprocess_forbidden(self):
        result = self.invoke("import subprocess, sys\nsubprocess.run([sys.executable,'-c','print(123)'])\n")
        self.assert_blocked(result)
        self.assertEqual(result.stdout, "")

    def test_network_event_forbidden_without_network_io(self):
        self.assert_blocked(self.invoke("import sys\nsys.audit('socket.connect',None,('127.0.0.1',9))\n"))

    def test_standard_output_descriptors_allowed(self):
        result = self.invoke("import os\nf=os.fdopen(1,'w',closefd=False); f.write('stdout ok'); f.flush()\ng=os.fdopen(2,'w',closefd=False); g.write('stderr ok'); g.flush()\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stdout ok", result.stdout)
        self.assertIn("stderr ok", result.stderr)

    def test_script_outside_root_rejected_before_runtime_creation(self):
        result = self.invoke("raise RuntimeError('must not execute')", script=self.source)
        self.assert_blocked(result)
        self.assertFalse((self.root / "_runtime").exists())

    def test_relative_root_rejected_before_runtime_creation(self):
        self.assert_blocked(self.invoke("pass", write_root="."))
        self.assertFalse((self.root / "_runtime").exists())

    def test_existing_runtime_not_reused(self):
        runtime = self.root / "_runtime"
        runtime.mkdir()
        sentinel = runtime / "sentinel"
        sentinel.write_text("preserve")
        result = self.invoke("raise RuntimeError('must not execute')")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_reparse_path_rejected(self):
        fake = mock.Mock(st_mode=stat.S_IFDIR, st_file_attributes=0x400, st_nlink=1)
        with mock.patch.object(Path, "lstat", return_value=fake):
            with self.assertRaises(child_guard.AuditGuardError):
                child_guard.inspect_paths(self.root, self.script)

    def test_dangling_symlink_rejected_by_lstat(self):
        fake = mock.Mock(st_mode=stat.S_IFLNK, st_file_attributes=0, st_nlink=1)
        with mock.patch.object(Path, "lstat", return_value=fake):
            with self.assertRaises(child_guard.AuditGuardError):
                child_guard.reject_links(self.root / "dangling")

    def test_existing_hardlink_rejected(self):
        fake = mock.Mock(st_mode=stat.S_IFREG, st_file_attributes=0, st_nlink=2)
        with mock.patch.object(Path, "lstat", return_value=fake):
            with self.assertRaises(child_guard.AuditGuardError):
                child_guard.reject_links(self.script)

    def test_namespace_and_traversal_rejected(self):
        for value in (r"\\?\C:\temp\x", r"\\.\NUL", r"\\server\share\x", "../x"):
            with self.subTest(value=value), self.assertRaises(child_guard.AuditGuardError):
                child_guard.plain_local_path(value)


if __name__ == "__main__":
    unittest.main()
