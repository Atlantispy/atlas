"""Focused exact-encoding and native authenticated-store compatibility checks."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from work.generator_runtime_r12 import store as native
from work.generator_upgrade_r23 import storage


class EncodingTests(unittest.TestCase):
    def test_exact_bytes_and_bound(self):
        shared = {"shared": [1, True, None]}
        values = [
            {}, [], "", None, True, False, 0, -1, 10**300,
            0.0, -0.0, 5e-324, -sys.float_info.max, sys.float_info.min,
            "\"\\\b\f\n\r\t\x00\x1f / é 林 😀 \u2028\u2029",
            {"z": 1, "a": 2, "😀": 3, "é": 4, "A": 5},
            [shared, shared],
            {"rows": [{"i": i, "value": i / 7, "label": "seed-é林"}
                      for i in range(100)]},
        ]
        for value in values:
            with self.subTest(value_type=type(value).__name__):
                expected = native._encode(value)
                self.assertEqual(storage._encode(value), expected)
                bound = -storage._remaining(value, 0)
                # Early exit at zero is not a total bound for containers.
                if type(value) not in (dict, list):
                    self.assertGreaterEqual(bound, len(expected))
                self.assertGreaterEqual(storage._remaining(value, len(expected) * 8 + 64), 0)

    def test_small_values_use_fast_encoder(self):
        value = {"a": [1, "é", False], "z": {"x": -0.0}}
        expected = native._encode(value)
        with patch.object(native, "_encode", side_effect=AssertionError("fallback")):
            self.assertEqual(storage._encode(value), expected)

    def test_fallback_retains_exact_size_boundary(self):
        value = "a" * 62
        original = native._encode
        with patch.object(native, "_encode", wraps=original) as fallback:
            self.assertEqual(storage._encode(value, 64), original(value, 64))
            fallback.assert_called_once_with(value, 64)
        with self.assertRaises(native._Oversize):
            storage._encode(value, 63)
        with self.assertRaises(native._Oversize):
            storage._encode({}, 1)

    def test_invalid_data_matches_native(self):
        class String(str):
            pass

        class Integer(int):
            pass

        cycle = []
        cycle.append(cycle)
        values = [float("nan"), float("inf"), -float("inf"), (1,), {1},
                  object(), {1: "key"}, String("value"), Integer(1),
                  {String("key"): 1}, cycle, "\ud800", "\udfff"]
        for value in values:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(native.CacheError) as before:
                    native._encode(value)
                with self.assertRaises(native.CacheError) as after:
                    storage._encode(value)
                self.assertEqual(type(before.exception), type(after.exception))
                self.assertEqual(str(before.exception), str(after.exception))

    def test_depth_boundary(self):
        value = None
        for _ in range(native._MAX_DEPTH):
            value = [value]
        self.assertEqual(storage._encode(value), native._encode(value))
        with self.assertRaisesRegex(native.CacheError, "nesting limit"):
            storage._encode([value])

    def test_large_integer_error_matches_native(self):
        # Both encoders retain the interpreter's decimal conversion protection.
        if not sys.get_int_max_str_digits():
            self.skipTest("interpreter decimal digit bound disabled")
        value = 10 ** (sys.get_int_max_str_digits() + 1)
        for encode in (native._encode, storage._encode):
            with self.assertRaisesRegex(native.CacheError, "Invalid JSON value"):
                encode(value)


class StoreTests(unittest.TestCase):
    namespace = "1" * 64
    key = "2" * 64

    def test_native_bodies_and_private_globals(self):
        for name in ("_read", "put"):
            old = getattr(native.Store, name)
            new = getattr(storage.Store, name)
            self.assertIs(new.__code__, old.__code__)
            self.assertIsNot(new.__globals__, old.__globals__)
            self.assertEqual(set(new.__globals__), set(old.__globals__))
            for key in old.__globals__:
                if key == "_encode":
                    self.assertIs(new.__globals__[key], storage._encode)
                else:
                    self.assertIs(new.__globals__[key], old.__globals__[key])
        for name in ("__init__", "get", "_locked", "_check_key", "_path",
                     "_inventory_bytes", "_load_key"):
            self.assertIs(getattr(storage.Store, name), getattr(native.Store, name))
        self.assertIs(native.Store.put.__globals__["_encode"], native._encode)

    def test_cross_read_idempotence_conflict_and_independent_values(self):
        with tempfile.TemporaryDirectory(prefix="r23store-") as folder:
            root = Path(folder) / "cache"
            old = native.Store(root, self.namespace)
            new = storage.Store(root, self.namespace)
            value = {"a": [1, "é林😀", -0.0], "valid": True}
            old.put(self.key, value)
            raw = old._path(self.key).read_bytes()
            self.assertEqual(new.get(self.key), value)
            new.put(self.key, dict(reversed(list(value.items()))))
            self.assertEqual(new.stats["unchanged"], 1)
            self.assertEqual(old._path(self.key).read_bytes(), raw)
            with self.assertRaises(native.CacheConflictError):
                new.put(self.key, {"different": True})
            other_key = "3" * 64
            new.put(other_key, value)
            self.assertEqual(old.get(other_key), value)
            returned = new.get(other_key)
            returned["a"].append("changed")
            self.assertEqual(old.get(other_key), value)
            self.assertIsNone(new.get("4" * 64))

    def test_corruption_rejected_by_both_stores(self):
        with tempfile.TemporaryDirectory(prefix="r23store-") as folder:
            root = Path(folder) / "cache"
            new = storage.Store(root, self.namespace)
            old = native.Store(root, self.namespace)
            new.put(self.key, {"v": 1})
            path = new._path(self.key)
            raw = path.read_bytes()
            record = json.loads(raw)
            record["value"] = {"v": 2}
            record["value_sha256"] = hashlib.sha256(native._encode(record["value"])).hexdigest()
            path.write_bytes(native._encode(record))
            for store in (old, new):
                with self.assertRaisesRegex(native.CacheError, "authentication failed"):
                    store.get(self.key)
            path.write_bytes(raw + b"\n")
            for store in (old, new):
                with self.assertRaisesRegex(native.CacheError, "not canonical JSON"):
                    store.get(self.key)

    def test_default_limit_and_full_store_semantics(self):
        self.assertEqual(storage._encode.__defaults__, (8 * 1024 * 1024,))
        with tempfile.TemporaryDirectory(prefix="r23store-") as folder:
            root = Path(folder) / "cache"
            new = storage.Store(root, self.namespace, max_bytes=33)
            new.put(self.key, {"v": 1})
            self.assertEqual(new.stats["skipped_full"], 1)
            self.assertIsNone(new.get(self.key))
            new.put(self.key, {"v": "a" * native.MAX_RECORD_BYTES})
            self.assertEqual(new.stats["skipped_oversize"], 1)
            self.assertIsNone(new.get(self.key))


if __name__ == "__main__":
    unittest.main()
