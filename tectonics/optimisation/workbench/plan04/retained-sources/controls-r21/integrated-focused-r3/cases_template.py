"""r24 integration properties; missing issue tests stay diagnostic-only."""
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).with_name("adapter_base.py")
BASE_SHA256 = "@ADAPTER_SHA256@"
if sha256(BASE.read_bytes()).hexdigest() != BASE_SHA256:
    raise AssertionError("Generated adapter bytes changed")
spec = importlib.util.spec_from_file_location("focused_base", BASE)
A = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = A
spec.loader.exec_module(A)
C, F, M = A.C, A.F, A.M
OBSERVATIONS = A.OBSERVATIONS


def verify_sources():
    if sha256(BASE.read_bytes()).hexdigest() != BASE_SHA256:
        raise AssertionError("Generated adapter bytes changed")
    A.verify_sources()


class Causal(A.Causal):
    def test_causal_41_mandatory_provenance_on_equal_records(self):
        value = self.check(self.verdict(*self.arms()), "REVIEW",
                           "producer provenance unresolved")
        reports = value.get("producer_provenance", {})
        self.assertEqual(set(reports), {"i0", "i1"}, "mandatory report retained")
        self.assertTrue(all(row["bytes_equal"] for name, row in value["records"].items()
                            if not name.endswith("/root_metadata")))
        for report in reports.values():
            self.assertTrue(report["verdict"] == "REVIEW")
            self.assertTrue(set(report["mandatory_slots"]) ==
                            {"E.representative-quaternion", "E.pose-operator-error"})
            self.assertTrue(len(report["receipts"]) == 2)
            for receipt in report["receipts"]:
                self.assertTrue(receipt["mandatory"] and receipt["verdict"] == "REVIEW")
                self.assertTrue(receipt["applicable_radius"] is None and
                                receipt["comparison_bound"] is None)
                self.assertTrue("NO_AUTHENTICATED_PRODUCER_INVOCATION_CONTEXT" in receipt["issues"])
                self.assertTrue(all(side["source"]["known"] and
                                    side["observed_call_site"] is None
                                    for side in receipt["arms"].values()))

    def test_causal_42_reader_raw_identity_not_rederived(self):
        _, b = self.arms()
        folder = b.dumps / "i1"
        import json
        dump = json.loads((folder / "dump.json").read_bytes())
        bound = C.ProvedRecordBytes(folder, dump["records"])
        before = bound["mesh"]
        self.assertEqual(sha256(before["raw"]).hexdigest(), before["identity"])
        # Mutate after the identity was independently supplied. The direct
        # integration boundary must reject, not derive authority from new bytes.
        F.edit_json(folder / "records/mesh.json", lambda row: row.update(unproved_change=True))
        with self.assertRaisesRegex(C.ProofError, "field provenance record differs from reader target"):
            bound["mesh"]

    def test_causal_43_provenance_contradiction_is_fail(self):
        original = C.ProvedRecordBytes

        class WrongTarget(original):
            def __getitem__(self, kind):
                row = super().__getitem__(kind)
                return {"identity": "0"*64, "raw": row["raw"]}

        # Inject a wrong forwarding target after the ordinary dump proof, at
        # the exact integration boundary. The provenance consumer must reject.
        C.ProvedRecordBytes = WrongTarget
        try:
            value = self.verdict(*self.arms())
        finally:
            C.ProvedRecordBytes = original
        self.check(value, "FAIL", "producer provenance")
        self.assertTrue(all(row["verdict"] == "FAIL" and
                            row["code"] == "PROVENANCE_INPUT_INTEGRITY"
                            for row in value["producer_provenance"].values()))

    def test_causal_44_root_issue_survives_other_review(self):
        original = M.before_build

        def changed(fixture, arm):
            original(fixture, arm)
            if arm.name == "after":
                metadata = arm._root_metadata
                fields = metadata["state"]["fields"]
                fields["grid"] = "changed-synthetic-root-input"
                identity = {"fields_id": F.force_id(fields, arm.arrays[0]),
                            "native_state_id": metadata["native_state_id"]}
                metadata["state"]["result_id"] = sha256(F.canonical(identity)).hexdigest()
        M.before_build = changed
        try:
            a, b = self.arms()
        finally:
            M.before_build = original
        value = self.check(self.verdict(a, b), "REVIEW", "root_metadata")
        self.assertTrue(all(row["verdict"] == "REVIEW"
                            for row in value["producer_provenance"].values()))

    def test_causal_45_source_issue_survives_other_review(self):
        before, after = self.pair(setup=lambda r: r[1]["mesh"].update(trajectory_id=None))
        value = self.check(self.verdict(*self.arms(before, after)), "REVIEW", "source field")
        self.assertTrue(value["source_compiled_contracts"]["i1"]["unresolved"])
        self.assertTrue(all(row["verdict"] == "REVIEW"
                            for row in value["producer_provenance"].values()))

    def test_causal_46_exact_fail_survives_provenance_review(self):
        before, after = self.pair(mutate=lambda r: r[1]["mesh"].update(time_s=F.enc(2)))
        value = self.check(self.verdict(*self.arms(before, after)), "FAIL", "EXACT_UNAFFECTED_CHANGED")
        self.assertTrue(all(row["verdict"] == "REVIEW"
                            for row in value["producer_provenance"].values()))
        self.assertTrue(all(row["verdict"] == "PASS" for row in value["addendum_e"].values()))


CAUSAL_NAMES = tuple(sorted(name for name in vars(Causal) if name.startswith("test_causal_")))


def selected_suite(group):
    if group != "causal":
        raise ValueError("Only the exact supplemental set is supported")
    return unittest.TestSuite(Causal(name) for name in CAUSAL_NAMES)
