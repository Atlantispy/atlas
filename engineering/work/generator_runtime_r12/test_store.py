"""Focused, actual-mode-independent tests of authenticated local result reuse."""

import concurrent.futures
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from work.generator_runtime_r12 import store


NAMESPACE = hashlib.sha256(b"exact producer/runtime namespace").hexdigest()
OTHER_NAMESPACE = hashlib.sha256(b"changed producer/runtime namespace").hexdigest()
KEY = hashlib.sha256(b"complete invocation").hexdigest()
OTHER_KEY = hashlib.sha256(b"changed invocation").hexdigest()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "cache"

    def create(self, **kwargs):
        return store.Store(self.root, NAMESPACE, **kwargs)

    def record(self, key=KEY, namespace=NAMESPACE):
        return self.root / namespace / (key + ".json")

    def write_record(self, record, *, key=KEY, namespace=NAMESPACE):
        self.record(key, namespace).write_bytes(store._encode(record))

    def read_record(self):
        return json.loads(self.record().read_bytes())

    def signed(self, record):
        body = {key: value for key, value in record.items() if key != "mac"}
        key = (self.root / ".cache-key").read_bytes()
        return dict(body, mac=hmac.new(key, store._encode(body), hashlib.sha256).hexdigest())

    def test_miss_returns_none(self):
        cache = self.create()
        self.assertIsNone(cache.get(KEY))
        self.assertEqual(cache.stats["misses"], 1)

    def test_exact_roundtrip(self):
        cache = self.create()
        value = {"values": [1, 1.0, -0.0, None, False, "\u96ea\u2744"], "nested": {}}
        cache.put(KEY, value)
        self.assertEqual(store._encode(cache.get(KEY)), store._encode(value))
        self.assertEqual(cache.stats["writes"], 1)
        self.assertEqual(cache.stats["hits"], 1)
        self.assertEqual(cache.stats["bytes_written"], cache.stats["bytes_read"])

    def test_empty_dict_is_hit(self):
        cache = self.create()
        cache.put(KEY, {})
        self.assertEqual(cache.get(KEY), {})
        self.assertEqual(cache.stats["hits"], 1)

    def test_fresh_instance_reuses_managed_key(self):
        cache = self.create()
        cache.put(KEY, {"answer": 42})
        raw_key = (self.root / ".cache-key").read_bytes()
        self.assertEqual(self.create().get(KEY), {"answer": 42})
        self.assertEqual((self.root / ".cache-key").read_bytes(), raw_key)
        self.assertEqual(len(raw_key), 32)

    def test_put_defensive_copy(self):
        cache = self.create()
        value = {"list": [1, {"nested": [2]}]}
        cache.put(KEY, value)
        value["list"][1]["nested"].append(3)
        self.assertEqual(cache.get(KEY), {"list": [1, {"nested": [2]}]})

    def test_get_defensive_copy(self):
        cache = self.create()
        cache.put(KEY, {"list": [{"n": 1}]})
        cache.get(KEY)["list"][0]["n"] = 900
        self.assertEqual(cache.get(KEY), {"list": [{"n": 1}]})

    def test_stats_defensive_copy_and_no_secret(self):
        cache = self.create()
        cache.stats["hits"] = 999
        self.assertEqual(cache.stats["hits"], 0)
        self.assertTrue(all(type(value) is int for value in cache.stats.values()))
        self.assertNotIn((self.root / ".cache-key").read_bytes().hex(), repr(cache.stats))

    def test_idempotent_put(self):
        cache = self.create()
        cache.put(KEY, {"b": 2, "a": 1})
        original = self.record().read_bytes()
        cache.put(KEY, {"a": 1, "b": 2})
        self.assertEqual(self.record().read_bytes(), original)
        self.assertEqual(cache.stats["writes"], 1)
        self.assertEqual(cache.stats["unchanged"], 1)

    def test_different_result_same_invocation_rejected(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        with self.assertRaises(store.CacheConflictError):
            cache.put(KEY, {"n": 2})
        self.assertEqual(cache.get(KEY), {"n": 1})

    def test_numeric_representation_difference_is_conflict(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        with self.assertRaises(store.CacheConflictError):
            cache.put(KEY, {"n": 1.0})

    def test_distinct_namespace_cannot_reuse(self):
        self.create().put(KEY, {"n": 1})
        changed = store.Store(self.root, OTHER_NAMESPACE)
        self.assertIsNone(changed.get(KEY))
        changed.put(KEY, {"n": 2})
        self.assertEqual(self.create().get(KEY), {"n": 1})
        self.assertEqual(changed.get(KEY), {"n": 2})

    def test_distinct_invocation_cannot_reuse(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        self.assertIsNone(cache.get(OTHER_KEY))

    def test_absolute_path_required(self):
        for root in ("C:/not-a-Path", Path("relative"), self.root / ".." / "elsewhere"):
            with self.subTest(root=root), self.assertRaises(store.CacheError):
                store.Store(root, NAMESPACE)

    def test_filesystem_root_rejected(self):
        with self.assertRaises(store.CacheError):
            store.Store(Path(self.root.anchor), NAMESPACE)

    def test_namespace_validation(self):
        for namespace in (None, 0, "", "A" * 64, "../escape", "a" * 63, "a" * 65):
            with self.subTest(namespace=namespace), self.assertRaises(store.CacheError):
                store.Store(self.root, namespace)

    def test_key_validation(self):
        cache = self.create()
        for key in (None, True, "", "B" * 64, "../escape", "a" * 63, "a" * 65):
            with self.subTest(key=key), self.assertRaises(store.CacheError):
                cache.get(key)
            with self.subTest(key=key), self.assertRaises(store.CacheError):
                cache.put(key, {})

    def test_max_bytes_validation(self):
        for cap in (-1, 0, 32, True, 256.0, None):
            with self.subTest(cap=cap), self.assertRaises(store.CacheError):
                self.create(max_bytes=cap)

    def test_only_json_dict_results(self):
        cache = self.create()
        for value in ([], None, 1, "text", {"tuple": (1, 2)}, {1: "bad"}, {"set": {1}}):
            with self.subTest(value=value), self.assertRaises(store.CacheError):
                cache.put(KEY, value)
        self.assertIsNone(cache.get(KEY))

    def test_json_subclasses_rejected(self):
        class AmbiguousInt(int):
            pass
        with self.assertRaises(store.CacheError):
            self.create().put(KEY, {"n": AmbiguousInt(1)})

    def test_nonfinite_write_rejected(self):
        cache = self.create()
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(store.CacheError):
                cache.put(KEY, {"n": value})

    def test_cyclic_value_rejected(self):
        value = {}
        value["cycle"] = value
        with self.assertRaises(store.CacheError):
            self.create().put(KEY, value)

    def test_shared_noncyclic_value_supported(self):
        item = [1, 2]
        cache = self.create()
        cache.put(KEY, {"a": item, "b": item})
        result = cache.get(KEY)
        result["a"].append(3)
        self.assertEqual(result["b"], [1, 2])

    def test_nesting_bound_rejected(self):
        value = {}
        for _ in range(130):
            value = {"n": value}
        with self.assertRaises(store.CacheError):
            self.create().put(KEY, value)

    def test_invalid_unicode_rejected(self):
        with self.assertRaises(store.CacheError):
            self.create().put(KEY, {"text": "\ud800"})

    def test_payload_oversize_skips_without_eviction(self):
        cache = self.create()
        cache.put(KEY, {"good": 1})
        original = self.record().read_bytes()
        cache.put(OTHER_KEY, {"large": "x" * store.MAX_RECORD_BYTES})
        self.assertEqual(cache.stats["skipped_oversize"], 1)
        self.assertFalse(self.record(OTHER_KEY).exists())
        self.assertEqual(self.record().read_bytes(), original)

    def test_oversized_changed_result_still_conflicts(self):
        cache = self.create()
        cache.put(KEY, {})
        with self.assertRaises(store.CacheConflictError):
            cache.put(KEY, {"large": "x" * store.MAX_RECORD_BYTES})
        self.assertEqual(cache.get(KEY), {})
        self.assertEqual(cache.stats["skipped_oversize"], 0)

    def test_oversized_put_does_not_hide_lost_key(self):
        cache = self.create()
        cache.put(KEY, {})
        (self.root / ".cache-key").unlink()
        with self.assertRaises(store.CacheError):
            cache.put(OTHER_KEY, {"large": "x" * store.MAX_RECORD_BYTES})

    def test_record_envelope_also_counts_towards_8mib(self):
        cache = self.create()
        value = {"large": "x" * (store.MAX_RECORD_BYTES - 30)}
        self.assertLess(len(store._encode(value)), store.MAX_RECORD_BYTES)
        cache.put(KEY, value)
        self.assertEqual(cache.stats["skipped_oversize"], 1)
        self.assertIsNone(cache.get(KEY))

    def test_full_store_skips_without_eviction(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        occupied = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        tight = self.create(max_bytes=occupied)
        tight.put(OTHER_KEY, {"n": 2})
        self.assertEqual(tight.stats["skipped_full"], 1)
        self.assertEqual(tight.get(KEY), {"n": 1})
        self.assertIsNone(tight.get(OTHER_KEY))
        self.assertEqual(occupied, sum(path.stat().st_size for path in self.root.rglob("*")
                                       if path.is_file()))

    def test_total_cap_spans_namespaces(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        occupied = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        changed = store.Store(self.root, OTHER_NAMESPACE, max_bytes=occupied)
        changed.put(KEY, {"n": 2})
        self.assertEqual(changed.stats["skipped_full"], 1)
        self.assertIsNone(changed.get(KEY))

    def test_existing_root_exceeding_total_cap_rejected_without_eviction(self):
        cache = self.create()
        cache.put(KEY, {})
        original = self.record().read_bytes()
        with self.assertRaisesRegex(store.CacheError, "exceed max_bytes"):
            self.create(max_bytes=33)
        self.assertEqual(self.record().read_bytes(), original)

    def test_minimum_cap_keeps_only_key_and_lock(self):
        cache = self.create(max_bytes=33)
        cache.put(KEY, {})
        self.assertEqual(cache.stats["skipped_full"], 1)
        self.assertEqual({path.name for path in self.root.iterdir()}, {".cache-key", ".store.lock"})

    def test_payload_tamper_recomputed_plain_hash_rejected(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        record = self.read_record()
        record["value"]["n"] = 2
        record["value_sha256"] = hashlib.sha256(store._encode(record["value"])).hexdigest()
        self.write_record(record)
        with self.assertRaisesRegex(store.CacheError, "authentication"):
            cache.get(KEY)
        self.assertEqual(cache.stats["hits"], 0)

    def test_wrong_hash_rejected_even_with_valid_mac(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        record = self.read_record()
        record["value_sha256"] = "0" * 64
        self.write_record(self.signed(record))
        with self.assertRaisesRegex(store.CacheError, "result hash"):
            cache.get(KEY)

    def test_wrong_mac_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        record = self.read_record()
        record["mac"] = "0" * 64
        self.write_record(record)
        with self.assertRaises(store.CacheError):
            cache.get(KEY)

    def test_record_copied_to_other_invocation_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        self.record(OTHER_KEY).write_bytes(self.record().read_bytes())
        with self.assertRaises(store.CacheError):
            cache.get(OTHER_KEY)

    def test_record_copied_to_other_namespace_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        changed = store.Store(self.root, OTHER_NAMESPACE)
        self.record(namespace=OTHER_NAMESPACE).parent.mkdir()
        self.record(namespace=OTHER_NAMESPACE).write_bytes(self.record().read_bytes())
        with self.assertRaises(store.CacheError):
            changed.get(KEY)

    def test_foreign_root_record_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        other = store.Store(Path(self.temporary.name) / "other", NAMESPACE)
        other.put(KEY, {})
        self.record().write_bytes((other.root / NAMESPACE / (KEY + ".json")).read_bytes())
        with self.assertRaises(store.CacheError):
            cache.get(KEY)

    def test_unknown_envelope_field_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        record = self.read_record()
        record["extra"] = True
        self.write_record(self.signed(record))
        with self.assertRaises(store.CacheError):
            cache.get(KEY)

    def test_wrong_schema_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        record = self.read_record()
        record["schema"] = "other"
        self.write_record(self.signed(record))
        with self.assertRaises(store.CacheError):
            cache.get(KEY)

    def test_non_dictionary_saved_value_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        record = self.read_record()
        record["value"] = []
        self.write_record(self.signed(record))
        with self.assertRaises(store.CacheError):
            cache.get(KEY)

    def test_duplicate_json_keys_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        raw = self.record().read_bytes()
        self.record().write_bytes(b'{"schema":"ignored",' + raw[1:])
        with self.assertRaisesRegex(store.CacheError, "Duplicate"):
            cache.get(KEY)

    def test_nested_duplicate_json_keys_rejected(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        self.record().write_bytes(self.record().read_bytes().replace(b'"n":1', b'"n":0,"n":1'))
        with self.assertRaisesRegex(store.CacheError, "Duplicate"):
            cache.get(KEY)

    def test_noncanonical_json_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        self.record().write_bytes(self.record().read_bytes() + b"\n")
        with self.assertRaisesRegex(store.CacheError, "canonical"):
            cache.get(KEY)

    def test_nonfinite_saved_value_rejected(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        original = self.record().read_bytes()
        for spelling in (b"NaN", b"Infinity", b"-Infinity", b"1e999"):
            self.record().write_bytes(original.replace(b'"n":1', b'"n":' + spelling))
            with self.subTest(spelling=spelling), self.assertRaises(store.CacheError):
                cache.get(KEY)

    def test_truncated_and_nonutf8_saved_values_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        for raw in (b"{", b"\xff", b"null", b"{}", b"[]"):
            self.record().write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(store.CacheError):
                cache.get(KEY)

    def test_oversized_saved_record_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        self.record().write_bytes(b" " * (store.MAX_RECORD_BYTES + 1))
        with self.assertRaises(store.CacheError):
            cache.get(KEY)
        with self.assertRaises(store.CacheError):
            self.create()

    def test_oversized_integer_encoding_rejected(self):
        cache = self.create()
        with self.assertRaises(store.CacheError):
            cache.put(KEY, {"n": 10 ** 10000})
        self.assertEqual(cache.stats["errors"], 1)

    def test_oversized_integer_decoding_rejected(self):
        cache = self.create()
        cache.put(KEY, {"n": 1})
        self.record().write_bytes(b'{"n":' + b"1" * 10000 + b"}")
        with self.assertRaises(store.CacheError):
            cache.get(KEY)
        self.assertEqual(cache.stats["errors"], 1)

    def test_corruption_never_overwritten(self):
        cache = self.create()
        cache.put(KEY, {})
        self.record().write_bytes(b"broken")
        with self.assertRaises(store.CacheError):
            cache.put(KEY, {"replacement": 1})
        self.assertEqual(self.record().read_bytes(), b"broken")

    def test_missing_key_with_records_not_regenerated(self):
        cache = self.create()
        cache.put(KEY, {})
        (self.root / ".cache-key").unlink()
        with self.assertRaises(store.CacheError):
            self.create()
        self.assertFalse((self.root / ".cache-key").exists())
        with self.assertRaises(store.CacheError):
            cache.get(KEY)

    def test_missing_key_with_empty_namespace_not_regenerated(self):
        self.root.mkdir()
        (self.root / NAMESPACE).mkdir()
        with self.assertRaises(store.CacheError):
            self.create()
        self.assertFalse((self.root / ".cache-key").exists())

    def test_changed_key_fails_existing_instance(self):
        cache = self.create()
        cache.put(KEY, {})
        (self.root / ".cache-key").write_bytes(b"\x00" * 32)
        with self.assertRaisesRegex(store.CacheError, "key changed"):
            cache.get(KEY)
        with self.assertRaisesRegex(store.CacheError, "key changed"):
            cache.put(OTHER_KEY, {})
        with self.assertRaises(store.CacheError):
            self.create().get(KEY)

    def test_malformed_key_rejected(self):
        cache = self.create()
        for raw in (b"", b"1" * 31, b"1" * 33):
            (self.root / ".cache-key").write_bytes(raw)
            with self.subTest(length=len(raw)), self.assertRaises(store.CacheError):
                self.create()
            with self.subTest(length=len(raw)), self.assertRaises(store.CacheError):
                cache.get(KEY)

    def test_unknown_files_preserved_and_rejected(self):
        self.root.mkdir()
        user_file = self.root / "user-data.txt"
        user_file.write_text("Do not delete", encoding="utf-8")
        with self.assertRaises(store.CacheError):
            self.create()
        self.assertEqual(user_file.read_text(encoding="utf-8"), "Do not delete")
        self.assertFalse((self.root / ".cache-key").exists())

    def test_unknown_file_after_creation_not_evicted(self):
        cache = self.create()
        user_file = self.root / "user-data.txt"
        user_file.write_text("Do not delete", encoding="utf-8")
        with self.assertRaises(store.CacheError):
            cache.put(KEY, {})
        self.assertEqual(user_file.read_text(encoding="utf-8"), "Do not delete")

    def test_unexpected_nested_directory_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        (self.root / NAMESPACE / "unexpected").mkdir()
        with self.assertRaises(store.CacheError):
            self.create()

    def test_oversized_lock_rejected(self):
        self.create()
        (self.root / ".store.lock").write_bytes(b"wrong")
        with self.assertRaises(store.CacheError):
            self.create()

    def test_hardlinked_record_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        linked = Path(self.temporary.name) / "hard-link"
        os.link(self.record(), linked)
        with self.assertRaises(store.CacheError):
            cache.get(KEY)
        with self.assertRaises(store.CacheError):
            cache.put(KEY, {})

    def test_hardlinked_key_rejected(self):
        self.create()
        os.link(self.root / ".cache-key", Path(self.temporary.name) / "key-link")
        with self.assertRaises(store.CacheError):
            self.create()

    def test_reparse_attribute_rejected(self):
        self.create()
        original = Path.lstat
        def reparse(path):
            actual = original(path)
            if path == self.root:
                return type("Reparse", (), {"st_mode": actual.st_mode,
                                           "st_file_attributes": 0x400})()
            return actual
        with mock.patch.object(Path, "lstat", reparse), self.assertRaises(store.CacheError):
            self.create()

    def test_symbolic_link_mode_rejected(self):
        self.create()
        original = Path.lstat
        def linked(path):
            actual = original(path)
            if path == self.root:
                return type("Linked", (), {"st_mode": stat.S_IFLNK | 0o777})()
            return actual
        with mock.patch.object(Path, "lstat", linked), self.assertRaises(store.CacheError):
            self.create()

    def test_failed_atomic_replace_preserves_no_partial_record(self):
        cache = self.create()
        with mock.patch.object(store.os, "replace", side_effect=OSError("test write failure")):
            with self.assertRaises(OSError):
                cache.put(KEY, {})
        self.assertFalse(self.record().exists())
        self.assertEqual(list((self.root / NAMESPACE).iterdir()), [])
        cache.put(KEY, {})
        self.assertEqual(cache.get(KEY), {})

    def test_interrupted_pending_file_is_preserved_and_rejected(self):
        cache = self.create()
        cache.put(KEY, {})
        pending = self.root / NAMESPACE / ".pending-interrupted"
        pending.write_bytes(b"uncommitted")
        with self.assertRaises(store.CacheError):
            self.create()
        self.assertEqual(pending.read_bytes(), b"uncommitted")

    def test_parallel_threads_shared_instance(self):
        cache = self.create()
        keys = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(12)]
        def operation(index):
            cache.put(keys[index], {"i": index})
            return cache.get(keys[index])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(operation, range(12)))
        self.assertEqual(results, [{"i": i} for i in range(12)])
        self.assertEqual(cache.stats["writes"], 12)
        self.assertEqual(cache.stats["hits"], 12)

    def test_parallel_instances_initialise_key_and_write_once(self):
        def operation(_):
            cache = self.create()
            cache.put(KEY, {"n": 1})
            return cache.get(KEY)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(operation, range(12)))
        self.assertEqual(results, [{"n": 1}] * 12)
        self.assertEqual(self.create().get(KEY), {"n": 1})

    def test_parallel_processes_initialise_key_and_write_once(self):
        script = ("from pathlib import Path; import sys; "
                  "from work.generator_runtime_r12.store import Store; "
                  "s=Store(Path(sys.argv[1]),sys.argv[2]); "
                  "s.put(sys.argv[3],{'n':1}); "
                  "v=s.get(sys.argv[3]); "
                  "sys.exit(0 if v=={'n':1} else 7)")
        flags = ["-OO"] if sys.flags.optimize == 2 else []
        processes = [subprocess.Popen([sys.executable, "-B", *flags, "-c", script,
                                       str(self.root), NAMESPACE, KEY],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(3)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, (stdout, stderr))
        self.assertEqual(self.create().get(KEY), {"n": 1})

    def sized_root(self, units):
        base = Path(self.temporary.name)
        leaf_units = units - len(str(base).encode("utf-16-le")) // 2 - 1
        self.assertGreaterEqual(leaf_units, 4)
        return base / ("r12-" + "x" * (leaf_units - 4))

    def test_windows_too_long_destination_rejected_before_any_writes(self):
        if os.name != "nt":
            return
        self.root = self.sized_root(125)
        self.assertEqual(len(str(self.record()).encode("utf-16-le")) // 2, 260)
        with self.assertRaisesRegex(store.CacheError, "use a shorter cache root"):
            self.create()
        self.assertFalse(self.root.exists())

    def test_windows_reported_265_character_failure_is_now_fail_fast(self):
        if os.name != "nt":
            return
        self.root = self.sized_root(130)
        self.assertEqual(len(str(self.record()).encode("utf-16-le")) // 2, 265)
        with self.assertRaisesRegex(store.CacheError, "maximum 259"):
            self.create()
        self.assertFalse(self.root.exists())

    def test_windows_too_long_existing_root_is_preserved_without_key_or_lock(self):
        if os.name != "nt":
            return
        self.root = self.sized_root(130)
        self.root.mkdir()
        evidence = self.root / "retained-evidence.txt"
        evidence.write_text("preserve this evidence", encoding="utf-8")
        with self.assertRaisesRegex(store.CacheError, "use a shorter cache root"):
            self.create()
        self.assertEqual(evidence.read_text(encoding="utf-8"), "preserve this evidence")
        self.assertEqual([path.name for path in self.root.iterdir()], [evidence.name])

    def test_windows_259_unit_destination_short_root_roundtrip(self):
        if os.name != "nt":
            return
        self.root = self.sized_root(124)
        self.assertEqual(len(str(self.record()).encode("utf-16-le")) // 2, 259)
        cache = self.create()
        cache.put(KEY, {"n": [1, 2, 3]})
        self.assertEqual(cache.get(KEY), {"n": [1, 2, 3]})
        self.assertEqual(self.create().get(KEY), {"n": [1, 2, 3]})
        self.assertEqual(self.record().name, KEY + ".json")
        self.assertEqual(self.record().parent.name, NAMESPACE)

    def test_windows_length_guard_counts_utf16_units_not_codepoints(self):
        if os.name != "nt":
            return
        plain = self.sized_root(124)
        self.root = plain.with_name(plain.name[:-1] + chr(0x1F30D))
        self.assertEqual(len(str(self.record()).encode("utf-16-le")) // 2, 260)
        self.assertLess(len(str(self.record())), 260)
        with self.assertRaisesRegex(store.CacheError, "UTF-16 units"):
            self.create()
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
