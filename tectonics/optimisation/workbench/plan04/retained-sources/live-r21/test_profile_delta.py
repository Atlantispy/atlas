"""Known-fault controls for the exact source/profile delta, no runtime imports."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("plan04_live_delta", HERE / "prepare_live.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


class ProfileDelta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = {}
        for name, pin in D.OLD.items():
            path = D.T / D.OLD_REL / name
            if D.pin(path) != pin:
                raise ValueError("predecessor changed: " + name)
            cls.old[name] = json.loads(path.read_bytes())
        cls.selection = {"assets": {"launch_fresh_interval.py": "a" * 64,
                                    **{"n9-tools-r21/" + n: "b" * 64 for n in D.PAYLOAD}}}

    def test_native_repair_and_policy_remain_exact(self):
        docs = D.derive(self.old, self.selection, "c" * 64)
        original = self.old["manifest.json"]
        changed = docs["manifest.json"]
        changed_keys = {k for k in original["files"] if original["files"][k] != changed["files"][k]}
        self.assertEqual(changed_keys, {D.R_REL + "/launch_fresh_interval.py"})
        self.assertEqual(set(changed["files"]) - set(original["files"]),
                         {D.R_REL + "/n9-tools-r21/" + n for n in D.PAYLOAD})
        old_policy = self.old["runtime-compatibility-policy.json"]
        new_policy = docs["runtime-compatibility-policy.json"]
        self.assertEqual(new_policy["current"]["execution_identity"],
                         old_policy["current"]["execution_identity"])
        self.assertEqual(new_policy["current"]["source_hashes"], old_policy["current"]["source_hashes"])
        for name in set(old_policy) - {"current", "evidence"}:
            self.assertEqual(new_policy[name], old_policy[name], name)
        old_profile = self.old["restart-profile-live-r2.json"]
        new_profile = docs["restart-profile-live-r21.json"]
        for name in set(old_profile) - {"source_manifest", "compatibility_policy",
                                       "output_directory", "completed_query_directory"}:
            self.assertEqual(new_profile[name], old_profile[name], name)
        self.assertEqual(new_profile["source_manifest"]["sha256"],
                         D.sha256(D.encoded(changed)).hexdigest())
        self.assertEqual(new_profile["compatibility_policy"]["sha256"],
                         D.sha256(D.encoded(new_policy)).hexdigest())

    def test_changed_predecessor_launcher_refuses(self):
        old = copy.deepcopy(self.old)
        old["manifest.json"]["files"][D.R_REL + "/launch_fresh_interval.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "predecessor LF"):
            D.derive(old, self.selection, "c" * 64)

    def test_missing_extra_and_escape_assets_refuse(self):
        for path in ("extra.py", "n9-tools-r21/../../native_transfer.py"):
            selected = copy.deepcopy(self.selection)
            selected["assets"][path] = "d" * 64
            with self.assertRaisesRegex(ValueError, "asset set"):
                D.derive(self.old, selected, "c" * 64)
        selected = copy.deepcopy(self.selection)
        del selected["assets"]["n9-tools-r21/field_contracts.py"]
        with self.assertRaisesRegex(ValueError, "asset set"):
            D.derive(self.old, selected, "c" * 64)

    def test_existing_payload_and_invalid_hash_refuse(self):
        old = copy.deepcopy(self.old)
        old["manifest.json"]["files"][D.R_REL + "/n9-tools-r21/field_contracts.py"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "already selected"):
            D.derive(old, self.selection, "c" * 64)
        selected = copy.deepcopy(self.selection)
        selected["assets"]["launch_fresh_interval.py"] = "not-a-pin"
        with self.assertRaisesRegex(ValueError, "asset hash"):
            D.derive(self.old, selected, "c" * 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
