"""Bounded new-world CLI and persistence checks; no scientific runtime imports.

SPDX-License-Identifier: AGPL-3.0-only
"""
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import new_world as cli
import new_world_contract as contract


class NewWorldCLITests(unittest.TestCase):
    def setUp(self):
        self.request = contract.new_request("0" * 31 + "1")
        self.plan = contract.resolve_request(self.request)

    def call(self, *args, body=b""):
        if not isinstance(body, bytes):
            body = contract.canonical_bytes(body)
        return cli.response(list(args), io.BytesIO(body))

    def error(self, answer, expected=None, private=None):
        record, status = answer
        self.assertEqual(status, 2, record)
        self.assertEqual(set(record), {"schema", "status", "error"})
        self.assertEqual(record["schema"], cli.RESPONSE_SCHEMA)
        self.assertEqual(record["status"], "error")
        self.assertEqual(set(record["error"]), {"code", "message"})
        if expected:
            self.assertEqual(record["error"]["code"], expected)
        if private:
            self.assertNotIn(str(private), json.dumps(record))

    def test_describe_seed_prepare_and_no_random_fallback(self):
        described, status = self.call("describe")
        self.assertEqual(status, 0)
        self.assertEqual(described["data"], contract.contract_description())
        seed, status = self.call("seed")
        self.assertEqual(status, 0)
        self.assertRegex(seed["data"]["seed"], r"^[0-9a-f]{32}$")
        with mock.patch.object(cli, "new_request", side_effect=AssertionError("no fallback")):
            prepared, status = self.call("prepare", body=self.request)
            self.assertEqual(status, 0)
            self.assertEqual(prepared["data"], self.plan)
            self.error(self.call("prepare", body=b"{}"))

    def test_arguments_are_structured_and_path_free(self):
        for args in ([], ["generate"], ["save"], ["load", "--file"],
                     ["load", "--unsafe-private-option"]):
            with self.subTest(args=args):
                self.error(self.call(*args), "INVALID_ARGUMENTS", "unsafe-private-option")

    def test_malformed_duplicate_nonfinite_and_unknown_fields(self):
        unknown = dict(self.request, unexpected=True)
        for body in (b"{", b"{} {}", b'{"schema":1,"schema":2}',
                     b'{"value":NaN}', b'{"value":Infinity}', b"\xff", unknown):
            with self.subTest(body=body):
                self.error(self.call("prepare", body=body))

    def test_stdin_read_is_bounded(self):
        class Bounded(io.BytesIO):
            def read(inner, size=-1):
                self.assertEqual(size, cli.MAX_INPUT_BYTES + 1)
                return super().read(size)
        answer = cli.response(["prepare"], Bounded(b" " * (cli.MAX_INPUT_BYTES + 2)))
        self.error(answer, "INPUT_TOO_LARGE")
        encoded = contract.canonical_bytes(self.request)
        padded = encoded + b" " * (cli.MAX_INPUT_BYTES - len(encoded))
        self.assertEqual(self.call("prepare", body=padded)[1], 0)

    def test_save_load_roundtrip_preserves_seed_and_read_only_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.json"
            saved, status = self.call("save", "--file", str(path), body=self.plan)
            self.assertEqual(status, 0, saved)
            before = path.read_bytes()
            self.assertEqual(before, contract.canonical_bytes(self.plan) + b"\n")
            with mock.patch.object(cli, "new_request", side_effect=AssertionError("no fallback")):
                loaded, status = self.call("load", "--file", str(path))
            self.assertEqual(status, 0, loaded)
            self.assertEqual(loaded["data"], self.plan)
            self.assertEqual(loaded["data"]["request"]["seed"], self.request["seed"])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_existing_file_directory_and_invalid_plan_never_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.json"
            path.write_bytes(b"original bytes")
            self.error(self.call("save", "--file", str(path), body=self.plan), "FILE_EXISTS", tmp)
            self.assertEqual(path.read_bytes(), b"original bytes")
            self.error(self.call("save", "--file", tmp, body=self.plan), "FILE_EXISTS", tmp)
            absent = Path(tmp) / "absent.json"
            damaged = dict(self.plan, plan_id="0" * 64)
            self.error(self.call("save", "--file", str(absent), body=damaged), private=tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_missing_oversized_corrupt_and_nonregular_loads_do_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            self.error(self.call("load", "--file", str(path)), "FILE_NOT_FOUND", tmp)
            self.error(self.call("load", "--file", tmp), "INVALID_PATH", tmp)
            for body in (b" " * (cli.MAX_INPUT_BYTES + 1), b"not json",
                         b'{"plan_id":1,"plan_id":2}'):
                path.write_bytes(body)
                self.error(self.call("load", "--file", str(path)), private=tmp)
                self.assertEqual(path.read_bytes(), body)
                self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_invalid_local_paths_refuse_before_filesystem_access(self):
        paths = ("", "../secret.json", "folder/../secret.json", "NUL", "con.json",
                 "file.json:stream", "bad. ", "\\\\host\\share\\file.json",
                 "//host/share/file.json", "\\\\?\\C:\\secret.json", "x\0y", "x" * 4097,
                 "/".join(["part"] * 129))
        with mock.patch.object(cli.Path, "lstat", side_effect=AssertionError("must refuse first")):
            for raw in paths:
                with self.subTest(raw=raw):
                    self.error(self.call("load", "--file", raw), "INVALID_PATH")

    def test_windows_reparse_flag_is_rejected_on_all_platforms(self):
        self.assertTrue(cli._unsafe(SimpleNamespace(
            st_mode=stat.S_IFDIR, st_file_attributes=0x400)))
        with tempfile.TemporaryDirectory() as tmp:
            real_stat = cli.Path.lstat
            target = Path(tmp)
            def reparse(path):
                info = real_stat(path)
                if path == target:
                    return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
                return info
            with mock.patch.object(cli.Path, "lstat", reparse):
                self.error(self.call("save", "--file", str(target / "new.json"), body=self.plan),
                           "UNSAFE_PATH", tmp)
            self.assertEqual(list(target.iterdir()), [])

    def test_symlink_file_and_parent_are_refused_without_modifying_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "actual.json"
            target.write_bytes(contract.canonical_bytes(self.plan))
            link = root / "link.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError) as error:
                self.skipTest("Symlink creation unavailable: " + type(error).__name__)
            before = target.read_bytes()
            for command in ("load", "save"):
                self.error(self.call(command, "--file", str(link), body=self.plan), "UNSAFE_PATH")
            directory_link = root / "directory-link"
            directory_link.symlink_to(root, target_is_directory=True)
            self.error(self.call("save", "--file", str(directory_link / "new.json"), body=self.plan),
                       "UNSAFE_PATH")
            self.assertFalse((root / "new.json").exists())
            self.assertEqual(target.read_bytes(), before)

    def test_write_failure_cleans_only_owned_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / ".atlas-new-world-existing.tmp"
            sentinel.write_bytes(b"preserve")
            with mock.patch.object(cli.os, "fsync", side_effect=OSError("private failure " + tmp)):
                self.error(self.call("save", "--file", str(root / "plan.json"), body=self.plan),
                           "IO_ERROR", tmp)
            self.assertEqual(list(root.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_publication_failure_preserves_existing_paths_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sentinel = root / "unrelated.json"
            sentinel.write_bytes(b"preserve")
            with mock.patch.object(cli.os, "link", side_effect=OSError("private " + tmp)):
                self.error(self.call("save", "--file", str(root / "plan.json"), body=self.plan),
                           "IO_ERROR", tmp)
            self.assertEqual(list(root.iterdir()), [sentinel])

    def test_racing_destination_is_never_overwritten_or_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            publish = cli._Directory.publish
            def race(directory, source, target):
                path.write_bytes(b"other writer")
                return publish(directory, source, target)
            with mock.patch.object(cli._Directory, "publish", race):
                self.error(self.call("save", "--file", str(path), body=self.plan), "FILE_EXISTS")
            self.assertEqual(path.read_bytes(), b"other writer")
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_changed_temporary_is_not_published_or_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            real_inspect = cli._Directory.inspect
            def changed(directory, name):
                info = real_inspect(directory, name)
                if name.endswith(".tmp"):
                    return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + 1,
                                           st_mode=info.st_mode, st_file_attributes=0)
                return info
            with mock.patch.object(cli._Directory, "inspect", changed):
                self.error(self.call("save", "--file", str(path), body=self.plan), "UNSAFE_PATH")
            self.assertFalse(path.exists())
            remaining = list(Path(tmp).iterdir())
            self.assertEqual(len(remaining), 1)
            self.assertTrue(remaining[0].name.endswith(".tmp"))

    def test_subprocess_prepare_save_load_and_existing_refusal(self):
        def invoke(*args, body=b""):
            result = subprocess.run([sys.executable, "-B", str(TOOLS / "new_world.py"), *args],
                                    input=body, capture_output=True, timeout=20, check=False)
            self.assertEqual(result.stderr, b"")
            return json.loads(result.stdout), result.returncode
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            prepared, status = invoke("prepare", body=contract.canonical_bytes(self.request))
            self.assertEqual(status, 0, prepared)
            saved, status = invoke("save", "--file", str(path),
                                   body=contract.canonical_bytes(prepared["data"]))
            self.assertEqual(status, 0, saved)
            before = path.read_bytes()
            loaded, status = invoke("load", "--file", str(path))
            self.assertEqual(status, 0, loaded)
            self.assertEqual(prepared["data"], loaded["data"])
            self.error(invoke("save", "--file", str(path), body=before), "FILE_EXISTS", tmp)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
