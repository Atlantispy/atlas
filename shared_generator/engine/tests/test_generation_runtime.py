"""Real-filesystem runtime acceptance tests; no production datasets required."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generation_runtime as runtime


class FilesystemCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runtime-test-", dir=runtime._absolute(Path(__file__).parent))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def make_file(self, name="output.bin", contents=b"validated output"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def rewrite_checked(self, path, mutate):
        content = json.loads(path.read_text(encoding="utf-8"))["content"]
        mutate(content)
        path.write_bytes(runtime._canonical_json(runtime._envelope(content)))


class IdentityTests(FilesystemCase):
    def test_file_identity_uses_exact_content(self):
        path = self.make_file(contents=b"abc")
        self.assertEqual(runtime.file_identity(path),
                         {"size_bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()})

    def test_mutation_during_hash_is_rejected(self):
        path = self.make_file(contents=b"original data")
        sha256 = hashlib.sha256

        class MutatingHash:
            def __init__(self):
                self.digest = sha256()

            def update(self, data):
                self.digest.update(data)
                path.write_bytes(b"mutated data with different length")

            def hexdigest(self):
                return self.digest.hexdigest()

        with patch.object(runtime.hashlib, "sha256", MutatingHash):
            with self.assertRaises(runtime.UnstableFileError):
                runtime.file_identity(path)

    def test_missing_and_directory_are_not_file_identities(self):
        with self.assertRaises(FileNotFoundError):
            runtime.file_identity(self.root / "absent")
        with self.assertRaises(runtime.UnsafePathError):
            runtime.file_identity(self.root)

    def test_implementation_binds_exact_files_runtime_and_order(self):
        a = self.make_file("a.py", b"code-a")
        b = self.make_file("runtime.lock", b"dependencies-v1")
        first = runtime.implementation_identity([b, a, b])
        self.assertEqual(first, runtime.implementation_identity([a, b]))
        self.assertEqual(len(first["files"]), 2)
        self.assertIn("numpy", first["dependencies"])
        self.assertIn("sqlite_version", first)
        self.assertIn("version", first["python"])
        b.write_bytes(b"dependencies-v2")
        self.assertNotEqual(first, runtime.implementation_identity([a, b]))

    def test_implementation_rechecks_earlier_files(self):
        a = self.make_file("a.py", b"first")
        b = self.make_file("b.py", b"second")
        identify = runtime.file_identity

        def mutate_previous(path):
            result = identify(path)
            if path == runtime._absolute(b):
                a.write_bytes(b"changed-first")
            return result

        with patch.object(runtime, "file_identity", side_effect=mutate_previous):
            with self.assertRaises(runtime.UnstableFileError):
                runtime.implementation_identity([a, b])

    def test_implementation_identity_is_portable_between_checkouts(self):
        left = self.root / "checkout-one"
        right = self.root / "checkout-two"
        paths = []
        for checkout in (left, right):
            files = []
            for relative, contents in (("engine/run.py", b"same code"),
                                       ("engine/helpers/math.py", b"same helper"),
                                       ("runtime.lock", b"same runtime lock")):
                path = checkout / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
                files.append(path)
            paths.append(files)
        first = runtime.implementation_identity(paths[0])
        self.assertEqual(first, runtime.implementation_identity(paths[1]))
        self.assertEqual([item["path"] for item in first["files"]],
                         ["engine/helpers/math.py", "engine/run.py", "runtime.lock"])
        self.assertNotIn(str(self.root), json.dumps(first))
        self.assertEqual(first, runtime.implementation_identity(paths[0], root=left))

    def test_semantic_identity_is_canonical_and_binds_every_component(self):
        value = runtime.semantic_identity("p", {"b": 2, "a": 1}, {"seed": 9}, {"version": "v1"})
        self.assertEqual(value, runtime.semantic_identity("p", {"a": 1, "b": 2}, {"seed": 9}, {"version": "v1"}))
        self.assertEqual(len(value), 64)
        for producer, inputs, parameters, implementation in (
                ("q", {"a": 1, "b": 2}, {"seed": 9}, {"version": "v1"}),
                ("p", {"a": 1, "b": 3}, {"seed": 9}, {"version": "v1"}),
                ("p", {"a": 1, "b": 2}, {"seed": 8}, {"version": "v1"}),
                ("p", {"a": 1, "b": 2}, {"seed": 9}, {"version": "v2"})):
            self.assertNotEqual(value, runtime.semantic_identity(producer, inputs, parameters, implementation))

    def test_non_json_identity_rejected(self):
        with self.assertRaises(ValueError):
            runtime.semantic_identity("p", {"bad": float("nan")}, {}, {})
        with self.assertRaises(TypeError):
            runtime.semantic_identity("p", {1: "nonstring key"}, {}, {})
        with self.assertRaises(ValueError):
            runtime.implementation_identity([])


class CheckpointTests(FilesystemCase):
    def setUp(self):
        super().setUp()
        self.store = runtime.CheckpointStore(self.root / "checkpoints", "run-one")

    def test_roundtrip_namespace_and_key_containment(self):
        key = "../../not-a-path"
        payload = {"records": [1, "ä", None, True], "complete": True}
        self.assertIsNone(self.store.load(key))
        self.store.save(key, payload)
        self.assertEqual(self.store.load(key), payload)
        self.assertTrue(self.store._path(key).is_relative_to(self.store.root))
        self.assertIsNone(runtime.CheckpointStore(self.store.root, "run-two").load(key))
        self.assertIsNone(self.store.load("different-key"))

    def test_corrupt_and_truncated_checkpoint_are_misses(self):
        self.store.save("unit", {"ok": True})
        path = self.store._path("unit")
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["content"]["payload"]["ok"] = False
        path.write_text(json.dumps(raw), encoding="utf-8")
        self.assertIsNone(self.store.load("unit"))
        path.write_bytes(b'{"content":')
        self.assertIsNone(self.store.load("unit"))

    def test_wrong_identity_and_key_are_misses_even_with_valid_checksum(self):
        for field, bad in (("identity", "wrong-run"), ("key", "wrong-unit"), ("schema", "v0")):
            self.store.save("unit", {"ok": True})
            self.rewrite_checked(self.store._path("unit"), lambda data: data.update({field: bad}))
            self.assertIsNone(self.store.load("unit"))

    def test_failed_atomic_replace_preserves_predecessor_and_cleans_temp(self):
        self.store.save("unit", {"generation": 1})
        with patch.object(runtime.os, "replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(OSError):
                self.store.save("unit", {"generation": 2})
        self.assertEqual(self.store.load("unit"), {"generation": 1})
        self.assertEqual(list(self.store.directory.glob("*.tmp")), [])

    def test_failed_file_fsync_preserves_predecessor(self):
        self.store.save("unit", {"generation": 1})
        with patch.object(runtime.os, "fsync", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                self.store.save("unit", {"generation": 2})
        self.assertEqual(self.store.load("unit"), {"generation": 1})
        self.assertEqual(list(self.store.directory.glob("*.tmp")), [])

    def test_concurrent_saves_are_whole_checked_records(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(lambda value: self.store.save("shared", {"value": value, "data": [value] * 100}), range(12)))
        result = self.store.load("shared")
        self.assertIn(result["value"], range(12))
        self.assertEqual(result["data"], [result["value"]] * 100)
        self.assertEqual(list(self.store.directory.glob("*.tmp")), [])

    def test_record_parser_rejects_duplicate_keys_and_nonfinite_constants(self):
        self.store.save("unit", {"value": 1})
        path = self.store._path("unit")
        for raw in (b'{"content":{},"content":{},"content_sha256":"x"}',
                    b'{"content":{"payload":NaN},"content_sha256":"x"}'):
            path.write_bytes(raw)
            self.assertIsNone(self.store.load("unit"))

    def test_corrupt_checkpoint_recomputes_only_missing_unit(self):
        calls = []

        def run():
            results = []
            for item in range(4):
                cached = self.store.load(str(item))
                if cached is None:
                    calls.append(item)
                    cached = {"answer": item * item}
                    self.store.save(str(item), cached)
                results.append(cached)
            return results

        expected = run()
        calls.clear()
        self.store._path("2").write_bytes(b"incomplete write")
        self.assertEqual(run(), expected)
        self.assertEqual(calls, [2])


class ReceiptTests(FilesystemCase):
    def setUp(self):
        super().setUp()
        self.a = self.make_file("a.bin", b"first")
        self.b = self.make_file("nested/b.bin", b"second")
        self.path = self.root / "receipt.json"
        self.result = {"complete": True, "count": 2}

    def save(self):
        runtime.save_receipt(self.path, "run-id", self.root, [self.a, self.b], self.result)

    def test_roundtrip_and_wrong_run_or_root_miss(self):
        self.save()
        self.assertEqual(runtime.load_receipt(self.path, "run-id", self.root), self.result)
        self.assertIsNone(runtime.load_receipt(self.path, "other-run", self.root))
        other = self.root / "other-root"
        other.mkdir()
        self.assertIsNone(runtime.load_receipt(self.path, "run-id", other))

    def test_changed_missing_and_same_metadata_content_miss(self):
        self.save()
        metadata = self.a.stat()
        self.a.write_bytes(b"other")
        os.utime(self.a, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        self.assertIsNone(runtime.load_receipt(self.path, "run-id", self.root))
        self.a.write_bytes(b"first")
        self.b.unlink()
        self.assertIsNone(runtime.load_receipt(self.path, "run-id", self.root))

    def test_result_corruption_miss(self):
        self.save()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["content"]["result"]["complete"] = False
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNone(runtime.load_receipt(self.path, "run-id", self.root))

    def test_empty_duplicate_and_self_manifests_cannot_be_saved(self):
        for outputs in ([], [self.a, self.a]):
            with self.assertRaises(ValueError):
                runtime.save_receipt(self.path, "run-id", self.root, outputs, self.result)
        self.save()
        with self.assertRaises(ValueError):
            runtime.save_receipt(self.path, "run-id", self.root, [self.path], self.result)

    def test_forged_empty_and_duplicate_manifests_are_misses(self):
        for mutate in (lambda data: data.update(outputs=[]),
                       lambda data: data["outputs"].append(data["outputs"][0])):
            self.save()
            self.rewrite_checked(self.path, mutate)
            self.assertIsNone(runtime.load_receipt(self.path, "run-id", self.root))

    def test_unsafe_manifest_paths_are_misses(self):
        for unsafe in ("../escape.bin", "/absolute.bin", "C:/outside.bin", "C:relative.bin",
                       "nested/../a.bin", "nested\\b.bin", "nested//b.bin", "./a.bin",
                       "nested/b.bin:stream", "//server/share/file", "a.bin "):
            with self.subTest(path=unsafe):
                self.save()
                self.rewrite_checked(self.path, lambda data: data["outputs"][0].update(path=unsafe))
                self.assertIsNone(runtime.load_receipt(self.path, "run-id", self.root))

    def test_output_outside_root_and_directory_rejected(self):
        narrower = self.root / "nested"
        for output, root in ((self.a, narrower), (narrower, self.root)):
            with self.assertRaises((runtime.UnsafePathError, ValueError)):
                runtime.save_receipt(self.path, "run-id", root, [output], self.result)

    def test_change_of_previous_output_during_verification_is_miss(self):
        self.save()
        identify = runtime.file_identity

        def mutate_previous(path):
            value = identify(path)
            if path == runtime._absolute(self.b):
                self.a.write_bytes(b"changed first after hashing")
            return value

        with patch.object(runtime, "file_identity", side_effect=mutate_previous):
            self.assertIsNone(runtime.load_receipt(self.path, "run-id", self.root))

    def test_change_during_receipt_save_does_not_write_proof(self):
        identify = runtime.file_identity

        def mutate_previous(path):
            value = identify(path)
            if path == runtime._absolute(self.b):
                self.a.write_bytes(b"changed first during save")
            return value

        with patch.object(runtime, "file_identity", side_effect=mutate_previous):
            with self.assertRaises(runtime.UnstableFileError):
                self.save()
        self.assertFalse(self.path.exists())

    def test_symlink_output_and_symlink_parent_rejected(self):
        link = self.root / "linked.bin"
        try:
            link.symlink_to(self.a)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Host does not allow symlinks: {exc}")
        with self.assertRaises(runtime.UnsafePathError):
            runtime.save_receipt(self.path, "run-id", self.root, [link], self.result)
        folder_link = self.root / "linked-directory"
        folder_link.symlink_to(self.b.parent, target_is_directory=True)
        with self.assertRaises(runtime.UnsafePathError):
            runtime.file_identity(folder_link / self.b.name)
        self.save()
        self.rewrite_checked(self.path, lambda data: data["outputs"][0].update(path=link.name))
        self.assertIsNone(runtime.load_receipt(self.path, "run-id", self.root))


class SchedulerTests(unittest.TestCase):
    def test_sequential_reference_uses_caller_and_is_lazy(self):
        caller = threading.get_ident()
        pulled = []

        def items():
            for value in range(5):
                pulled.append(value)
                yield value

        results = runtime.bounded_map(lambda value: (value * 2, threading.get_ident()), items(), workers=1)
        self.assertEqual(pulled, [])
        self.assertEqual(next(results), (0, caller))
        self.assertEqual(pulled, [0])
        self.assertEqual(list(results), [(value * 2, caller) for value in range(1, 5)])

    def test_parallel_order_and_caller_only_item_loading(self):
        caller = threading.get_ident()
        source_threads = []
        worker_threads = []
        finished = []
        lock = threading.Lock()

        def items():
            for value in range(8):
                source_threads.append(threading.get_ident())
                yield value

        def work(value):
            time.sleep((3 - value % 4) * 0.005)
            with lock:
                worker_threads.append(threading.get_ident())
                finished.append(value)
            return value * value

        results = list(runtime.bounded_map(work, items(), workers=4))
        self.assertEqual(results, [value * value for value in range(8)])
        self.assertEqual(source_threads, [caller] * 8)
        self.assertNotIn(caller, worker_threads)
        self.assertNotEqual(finished[:4], [0, 1, 2, 3])

    def test_memory_budget_and_inflight_bound_admission(self):
        pulled = []
        active = 0
        peak = 0
        lock = threading.Lock()

        def items():
            for value in range(10):
                pulled.append(value)
                yield value

        def work(value):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.003)
            with lock:
                active -= 1
            return value

        iterator = runtime.bounded_map(work, items(), workers=8, max_inflight=4,
                                       memory_budget_bytes=20, estimated_task_bytes=10)
        self.assertEqual(next(iterator), 0)
        self.assertEqual(len(pulled), 2)
        self.assertEqual(list(iterator), list(range(1, 10)))
        self.assertLessEqual(peak, 2)
        self.assertEqual(active, 0)

    def test_single_memory_slot_falls_back_to_caller_thread(self):
        caller = threading.get_ident()
        result = list(runtime.bounded_map(lambda value: threading.get_ident(), [1, 2],
                                          workers=8, memory_budget_bytes=10, estimated_task_bytes=10))
        self.assertEqual(result, [caller, caller])

    def test_invalid_resource_configuration_rejected_before_loading(self):
        for settings in ({"workers": 0}, {"workers": True}, {"max_inflight": 0},
                         {"memory_budget_bytes": 0}, {"estimated_task_bytes": 0},
                         {"memory_budget_bytes": 10, "estimated_task_bytes": 11}):
            pulled = []

            def items():
                pulled.append(1)
                yield 1

            with self.subTest(settings=settings), self.assertRaises(ValueError):
                list(runtime.bounded_map(lambda value: value, items(), **settings))
            self.assertEqual(pulled, [])

    def test_precancelled_does_not_load_or_compute(self):
        event = threading.Event()
        event.set()
        calls = []
        with self.assertRaises(runtime.GenerationCancelled):
            list(runtime.bounded_map(lambda value: calls.append(value), range(5), workers=3, cancel_event=event))
        self.assertEqual(calls, [])

    def test_cancellation_waits_for_admitted_workers_and_stops_loading(self):
        event = threading.Event()
        started = threading.Barrier(3)
        finished = []
        pulled = []

        def items():
            for value in range(9):
                pulled.append(value)
                yield value

        def work(value):
            started.wait(timeout=3)
            if value == 0:
                event.set()
            time.sleep(0.02 if value else 0)
            finished.append(value)
            return value

        with self.assertRaises(runtime.GenerationCancelled):
            list(runtime.bounded_map(work, items(), workers=3, cancel_event=event))
        self.assertCountEqual(finished, [0, 1, 2])
        self.assertEqual(pulled, [0, 1, 2])

    def test_worker_exception_joins_other_workers(self):
        started = threading.Barrier(3)
        completed = []

        def work(value):
            started.wait(timeout=3)
            if value == 0:
                raise RuntimeError("intentional worker failure")
            time.sleep(0.02)
            completed.append(value)
            return value

        with self.assertRaisesRegex(RuntimeError, "intentional worker failure"):
            list(runtime.bounded_map(work, range(9), workers=3))
        self.assertCountEqual(completed, [1, 2])

    def test_input_exception_joins_workers(self):
        finished = threading.Event()

        def items():
            yield 0
            raise RuntimeError("input loader failed")

        def work(value):
            time.sleep(0.01)
            finished.set()
            return value

        with self.assertRaisesRegex(RuntimeError, "input loader failed"):
            list(runtime.bounded_map(work, items(), workers=3))
        self.assertTrue(finished.is_set())

    def test_explicit_close_joins_workers_before_caller_cleanup(self):
        started = threading.Barrier(3)
        completed = []

        def work(value):
            started.wait(timeout=3)
            time.sleep(0.02 if value else 0)
            completed.append(value)
            return value

        iterator = runtime.bounded_map(work, range(9), workers=3)
        self.assertEqual(next(iterator), 0)
        iterator.close()
        self.assertCountEqual(completed, [0, 1, 2])


class StatsTests(unittest.TestCase):
    def test_timing_records_failures_and_returns_independent_snapshot(self):
        stats = runtime.RuntimeStats()
        stats.increment("hits")
        with self.assertRaises(ValueError):
            with stats.measure("compute"):
                raise ValueError("failed operation is still measured")
        first = stats.snapshot()
        self.assertEqual(first["counts"], {"hits": 1})
        self.assertGreaterEqual(first["seconds"]["compute"], 0)
        first["counts"]["hits"] = 999
        self.assertEqual(stats.snapshot()["counts"]["hits"], 1)


if __name__ == "__main__":
    unittest.main()
