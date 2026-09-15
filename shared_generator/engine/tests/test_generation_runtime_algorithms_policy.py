from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import algorithm_policy as policy
import generation_runtime as runtime


def _worker_policy(_):
    return os.getpid(), policy.snapshot()


class AlgorithmPolicyTests(unittest.TestCase):
    def setUp(self):
        self.old_mode = policy.snapshot()["mode"]
        self.environment = mock.patch.dict(os.environ)
        self.environment.start()

    def tearDown(self):
        policy.configure(self.old_mode)
        self.environment.stop()

    def test_reference_disables_every_registered_path_and_unknown_names(self):
        policy.configure("reference")
        for name in (*policy.ENABLED_ALGORITHMS, "unknown"):
            self.assertFalse(policy.use_optimized(name))
        self.assertEqual(policy.snapshot(), {"mode": "reference", "enabled_algorithms": []})

    def test_auto_selects_only_registered_paths(self):
        policy.configure("auto")
        for name in policy.ENABLED_ALGORITHMS:
            self.assertTrue(policy.use_optimized(name))
        for name in ("unknown", "settlement_transforms", "topology_column_index"):
            self.assertFalse(policy.use_optimized(name))

    def test_invalid_mode_does_not_change_policy(self):
        policy.configure("reference")
        for value in (None, True, "unsafe", "AUTO"):
            with self.assertRaises(ValueError):
                policy.configure(value)
        self.assertEqual(policy.snapshot()["mode"], "reference")

    def test_new_interpreter_inherits_reference_mode(self):
        policy.configure("reference")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(policy.__file__).parent) + os.pathsep + environment.get("PYTHONPATH", "")
        result = subprocess.run([sys.executable, "-B", "-c",
            "import json,algorithm_policy; print(json.dumps(algorithm_policy.snapshot()))"],
            env=environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"mode": "reference", "enabled_algorithms": []})

    def test_threads_and_spawn_pool_inherit_reference_mode(self):
        policy.configure("reference")
        for backend in ("thread", "process"):
            with self.subTest(backend=backend):
                values = list(runtime.bounded_map(_worker_policy, range(4), workers=2,
                    backend=backend, estimated_task_bytes=16 * 1024**2,
                    memory_budget_bytes=256 * 1024**2))
                self.assertEqual(len(values), 4)
                for process_id, selected in values:
                    self.assertEqual(selected, {"mode": "reference", "enabled_algorithms": []})
                    if backend == "process":
                        self.assertNotEqual(process_id, os.getpid())


if __name__ == "__main__":
    unittest.main()
