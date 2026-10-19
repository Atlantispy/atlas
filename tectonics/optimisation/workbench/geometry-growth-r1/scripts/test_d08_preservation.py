"""Synthetic full-wrapper regression for Plan 03's preserved D08 attempt.

Run: python -B test_d08_preservation.py [--wrapper PATH] [-v]
The default is the sibling run_dj_rearm_r6.sh. An explicit historical r5 path
provides a known-fault control: the bypass cases must fail against that wrapper.
Requires Git Bash on Windows, or Bash with GNU coreutils elsewhere. No scientific
inputs, real logs, Atlas imports, psutil or third-party Python packages are used.
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest


WRAPPER = Path(__file__).with_name("run_dj_rearm_r6.sh")
D08_MTIME_NS = 1792182120860677600
ORIGINAL_OUTER_SHA = "3ba3da59468bb4db3bc3a3fffd2c4ed0f263aafd2589364e7804285674fc1e3f"
OUTER_BYTES = b"Synthetic D08 launch failure; not historical evidence.\n"
OUTER_SHA = hashlib.sha256(OUTER_BYTES).hexdigest()
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def find_bash():
    candidates = [shutil.which("bash")]
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            candidates.append(str(Path(git).parent.parent / "usr/bin/bash.exe"))
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            if os.environ.get(variable):
                candidates.append(str(Path(os.environ[variable]) / "Git/usr/bin/bash.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            # Windows' System32 bash launcher is WSL, not the Git Bash fixture host.
            if os.name != "nt" or "system32" not in Path(candidate).as_posix().lower():
                return str(Path(candidate).resolve())
    raise RuntimeError("Bash unavailable; install/configure it separately before these tests")


def write_executable(path, text):
    path.write_bytes(text.encode("utf-8"))
    path.chmod(0o755)


PY_STUB = r'''#!/usr/bin/env bash
set -u
root=$DJ_TEST_ROOT
out="$root/evidence/workers-dj"
if [ "${1:-}" = -B ] && [ "${2:-}" = parallel_parity.py ]; then
  printf 'called\n' > "$root/parity-called"
  output=
  while [ $# -gt 0 ]; do
    if [ "$1" = --output ]; then shift; output=$1; fi
    shift
  done
  [ -n "$output" ] || exit 90
  printf '{"synthetic":true}\n' > "$output" || exit 91
  case ${DJ_TEST_PARITY_MUTATION:-} in
    missing_log) rm "$out/iv2-w6-r3.log" || exit 92;;
    unexpected_json) printf '{}\n' > "$out/iv2-w6-r3.json" || exit 93;;
    '') ;;
    *) exit 94;;
  esac
elif [ "${1:-}" = -B ] && [ "${2:-}" = -I ] && [ "${3:-}" = summarise_dj.py ]; then
  printf 'called\n' > "$root/summary-called"
  printf 'SYNTHETIC SUMMARY STAND-IN\n'
elif [ "${1:-}" != -B ]; then
  exit 95
fi
# Preflight's interpreter check and CPU quiet probe are deliberate stand-ins.
exit 0
'''


LATE_CP = r'''#!/usr/bin/env bash
set -u
/usr/bin/cp "$@" || exit $?
destination=${!#}
case $destination in
  */workers-dj-merged-r4/r2view/)
    # First r2-view copy is after the post-parity audit, before D08 exclusion.
    printf '{}\n' > "$DJ_TEST_ROOT/evidence/workers-dj/iv2-w6-r3.json" || exit 96
    printf 'called\n' > "$DJ_TEST_ROOT/late-mutation-called";;
esac
'''


class D08PreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = find_bash()
        cls.source = WRAPPER.read_text(encoding="utf-8")

    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="atlas-d08-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.out = self.root / "evidence/workers-dj"
        self.merged = self.root / "evidence/workers-dj-merged-r4"
        for path in (self.out, self.root / "scripts", self.root / "work",
                     self.root / "evidence/workers-six-r2"):
            path.mkdir(parents=True, exist_ok=True)
        (self.out / "iv2-w6.json").write_text("{}\n", encoding="utf-8")
        (self.out / "iv2-store").write_bytes(b"tiny synthetic input store\n")
        (self.root / "evidence/workers-six-r2/iv2-serial.json").write_text(
            "{}\n", encoding="utf-8")
        self.log = self.out / "iv2-w6-r3.log"
        self.log.write_bytes(b"")
        os.utime(self.log, ns=(D08_MTIME_NS, D08_MTIME_NS))
        (self.root / "work/dj-rearm-r3-q21b.log").write_bytes(OUTER_BYTES)
        stub = self.root / "stub.sh"
        write_executable(stub, PY_STUB)

        # The complete wrapper remains intact; only fixture paths and the
        # synthetic outer-log identity replace the original environment.
        source = self.source
        for name, path in (("G", self.root), ("PY", stub)):
            source, count = re.subn(
                rf"^{name}=.*$", lambda match: f"{name}={shlex.quote(path.as_posix())}",
                source, count=1, flags=re.MULTILINE)
            self.assertEqual(count, 1, f"missing {name}= fixture seam")
        self.assertIn(ORIGINAL_OUTER_SHA, source, "D08 identity changed; review fixture")
        source = source.replace(ORIGINAL_OUTER_SHA, OUTER_SHA)
        self.wrapper = self.root / "wrapper.sh"
        write_executable(self.wrapper, source)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("DJ_") and key not in ("BASH_ENV", "ENV")}
        self.env.update(DJ_TEST_ROOT=self.root.as_posix(),
                        DJ_PREFLIGHT_TMP=self.root.as_posix(),
                        DJ_PREFLIGHT_TIMEOUT_S="10", DJ_CLEANUP_TIMEOUT_S="2")

    def run_wrapper(self):
        result = subprocess.run(
            [self.bash, self.wrapper.as_posix(), "r4", "iv2:6"],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=30)
        self.output = result.stdout + result.stderr
        return result.returncode

    def assert_not_summarised(self):
        self.assertFalse((self.root / "summary-called").exists(), self.output)

    def assert_start_refused(self, diagnostic="D08"):
        self.assertEqual(self.run_wrapper(), 2, self.output)
        self.assertIn(diagnostic, self.output)
        self.assertFalse((self.root / "parity-called").exists(), self.output)
        self.assertFalse((self.out / "iv2-store-w6-r4").exists(), self.output)
        self.assertFalse((self.out / "iv2-w6-r4.log").exists(), self.output)
        self.assertFalse(self.merged.exists(), self.output)
        self.assert_not_summarised()

    def assert_merge_refused(self):
        self.assertEqual(self.run_wrapper(), 1, self.output)
        self.assertIn("D08", self.output)
        self.assertTrue((self.root / "parity-called").exists(), self.output)
        self.assertTrue((self.out / "iv2-w6-r4.json").is_file(), self.output)
        self.assertFalse(self.merged.exists(), self.output)
        self.assert_not_summarised()

    def test_valid_attempt_preserves_both_excluded_logs_and_sources(self):
        self.assertEqual(self.run_wrapper(), 0, self.output)
        self.assertTrue((self.root / "parity-called").is_file(), self.output)
        self.assertTrue((self.root / "summary-called").is_file(), self.output)
        self.assertEqual((self.out / "iv2-store-w6-r4").read_bytes(),
                         (self.out / "iv2-store").read_bytes())
        self.assertEqual((self.merged / "iv2-w6.json").read_bytes(),
                         (self.out / "iv2-w6-r4.json").read_bytes())
        self.assertEqual(self.log.read_bytes(), b"")
        self.assertEqual(self.log.stat().st_mtime_ns, D08_MTIME_NS)
        self.assertEqual((self.root / "work/dj-rearm-r3-q21b.log").read_bytes(), OUTER_BYTES)
        self.assertEqual((self.merged / "excluded/iv2-w6-r3.log").read_bytes(), b"")
        self.assertEqual((self.merged / "excluded/dj-rearm-r3-q21b.log").read_bytes(), OUTER_BYTES)
        sources = (self.merged / "sources.txt").read_text(encoding="utf-8")
        for name, digest in (("iv2-w6-r3.log", EMPTY_SHA), ("dj-rearm-r3-q21b.log", OUTER_SHA)):
            self.assertIn(f"excluded/{name} {digest} INVALID_LAUNCH_ENVIRONMENT_D08", sources)
        self.assertFalse((self.merged / "iv2-w6-r3.json").exists())
        self.assertFalse((self.merged / "superseded/iv2-w6-r3.json").exists())

    def test_missing_d08_log_refuses_before_copy_or_parity(self):
        self.log.unlink()
        self.assert_start_refused()

    def test_unexpected_d08_json_refuses_before_copy_or_parity(self):
        (self.out / "iv2-w6-r3.json").write_text("{}\n", encoding="utf-8")
        self.assert_start_refused()

    def test_other_orphan_still_refuses_before_copy_or_parity(self):
        (self.out / "iv2-w4.json").write_text("{}\n", encoding="utf-8")
        (self.out / "iv2-w4-r3.log").write_bytes(b"")
        self.assert_start_refused("attempt with no JSON (crashed or killed): iv2-w4-r3.log")

    def test_d08_log_removed_during_parity_refuses_before_merge(self):
        self.env["DJ_TEST_PARITY_MUTATION"] = "missing_log"
        self.assert_merge_refused()

    def test_d08_json_added_during_parity_refuses_before_merge(self):
        self.env["DJ_TEST_PARITY_MUTATION"] = "unexpected_json"
        self.assert_merge_refused()

    def test_d08_mutation_after_audit_cannot_skip_exclusion(self):
        bindir = self.root / "bin"
        bindir.mkdir()
        write_executable(bindir / "cp", LATE_CP)
        binpath = bindir.as_posix()
        if re.match(r"^[A-Za-z]:/", binpath):
            # PATH is colon-separated inside Bash, so a Windows drive must use
            # Git Bash's mount spelling (ordinary file arguments accept C:/...).
            binpath = "/" + binpath[0].lower() + binpath[2:]
        self.env["DJ_GIT_USR_BIN"] = f"{binpath}:/usr/bin"
        self.assertEqual(self.run_wrapper(), 1, self.output)
        self.assertTrue((self.root / "late-mutation-called").is_file(), self.output)
        self.assertTrue(self.merged.is_dir(), self.output)
        self.assertIn("D08", self.output)
        self.assert_not_summarised()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrapper", type=Path, default=WRAPPER)
    options, remaining = parser.parse_known_args()
    WRAPPER = options.wrapper.resolve()
    unittest.main(argv=[__file__, *remaining])
