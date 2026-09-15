"""Focused full-inventory parity, safety and public-store regression checks."""

import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from work.generator_runtime_r12 import store as native
from work.generator_upgrade_r23.storage import Store as PreviousStore
from work.generator_upgrade_r24 import storage


class StorageTests(unittest.TestCase):
    namespace = "1" * 64
    key = "2" * 64

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="r24store-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "cache"
        self.old = PreviousStore(self.root, self.namespace)
        self.new = storage.Store(self.root, self.namespace)

    def test_complete_inventory_matches_native_across_namespaces(self):
        for namespace in (self.namespace, "3" * 64):
            store = PreviousStore(self.root, namespace)
            for number in range(3):
                store.put(format(number, "064x"), {"i": number, "text": "é林😀"})
        expected = self.old._inventory_bytes()
        self.assertEqual(self.new._inventory_bytes(), expected)
        with patch.object(native, "_check_path", wraps=native._check_path) as checks:
            self.assertEqual(self.new._inventory_bytes(), expected)
        self.assertEqual(checks.call_args_list, [
            unittest.mock.call(self.root, directory=True),
            unittest.mock.call(self.root, directory=True)])

    def test_new_writes_reconcile_inventory_and_preserve_capacity(self):
        self.new.put(self.key, {"v": 1})
        used = self.old._inventory_bytes()
        bounded = storage.Store(self.root, self.namespace, max_bytes=used)
        bounded.put("4" * 64, {"v": 2})
        self.assertEqual(bounded.stats["skipped_full"], 1)
        self.assertIsNone(self.old.get("4" * 64))
        # A different cooperating instance can write between public calls;
        # the next write sees the complete fresh inventory, never cached totals.
        self.old.put("5" * 64, {"v": 3})
        self.assertGreater(self.new._inventory_bytes(), used)
        self.assertEqual(self.new._inventory_bytes(), self.old._inventory_bytes())
        with self.assertRaisesRegex(native.CacheError, "exceed max_bytes"):
            storage.Store(self.root, self.namespace, max_bytes=used)

    def test_native_read_write_authentication_conflict_and_recovery(self):
        self.new.put(self.key, {"v": [1, "é", False]})
        value = self.old.get(self.key)
        restarted = storage.Store(self.root, self.namespace)
        self.assertEqual(restarted.get(self.key), value)
        restarted.put(self.key, value)
        self.assertEqual(restarted.stats["unchanged"], 1)
        with self.assertRaises(native.CacheConflictError):
            restarted.put(self.key, {"different": True})
        path = self.old._path(self.key)
        path.write_bytes(path.read_bytes().replace(b'"v":[1,', b'"v":[2,'))
        with self.assertRaisesRegex(native.CacheError, "authentication failed"):
            restarted.get(self.key)
        for name in ("get", "put", "_read", "_locked", "_load_key", "_check_key"):
            self.assertIs(getattr(storage.Store, name), getattr(PreviousStore, name))

    def test_invalid_names_types_and_oversize_rejected_like_native(self):
        namespace = self.root / self.namespace
        namespace.mkdir()
        invalid = [self.root / "unknown", namespace / "unexpected.json"]
        for path in invalid:
            path.write_bytes(b"invalid")
            for store in (self.old, self.new):
                with self.assertRaises(native.CacheError):
                    store._inventory_bytes()
            path.unlink()
        record = namespace / (self.key + ".json")
        record.mkdir()
        for store in (self.old, self.new):
            with self.assertRaisesRegex(native.CacheError, "regular files"):
                store._inventory_bytes()
        record.rmdir()
        with record.open("wb") as handle:
            handle.truncate(native.MAX_RECORD_BYTES + 1)
        for store in (self.old, self.new):
            with self.assertRaisesRegex(native.CacheError, "byte limit"):
                store._inventory_bytes()

    def test_hardlinks_and_reparse_entries_rejected(self):
        self.new.put(self.key, {"v": 1})
        os.link(self.new._path(self.key), self.root / self.namespace / ("6" * 64 + ".json"))
        for store in (self.old, self.new):
            with self.assertRaisesRegex(native.CacheError, "regular files"):
                store._inventory_bytes()
        fake = SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=1,
                               st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=fake):
            with self.assertRaisesRegex(native.CacheError, "reparse"):
                storage._entry(self.root / "mock", directory=False)

    def test_namespace_replacement_detected_by_postcheck(self):
        self.new.put(self.key, {"v": 1})
        namespace = self.root / self.namespace
        original = storage._entry
        changed = False

        def replace_after_record(path, *, directory):
            nonlocal changed
            info = original(path, directory=directory)
            if path == self.new._path(self.key) and not changed:
                changed = True
                namespace.rename(self.root / "retained")
                namespace.mkdir()
            return info

        with patch.object(storage, "_entry", side_effect=replace_after_record):
            with self.assertRaisesRegex(native.CacheError, "directory changed"):
                self.new._inventory_bytes()


if __name__ == "__main__":
    unittest.main()
