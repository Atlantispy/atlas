"""Synthetic integration boundaries; direct API defence is separately labelled."""
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
    def test_causal_21_known_header_exact_time(self):
        before, after = self.pair(mutate=lambda r: r[1]["mesh"].update(time_s=F.enc(2)))
        value = self.check(self.verdict(*self.arms(before, after)), "FAIL", "EXACT_UNAFFECTED_CHANGED")
        self.assertTrue(all(item["verdict"] == "PASS" for item in value["addendum_e"].values()))

    def test_causal_22_complete_observation(self):
        a, b = self.arms()
        F.edit_json(b.dumps / "i1/dump.json",
                    lambda d: d["environment_after"].update(prefix="different-prefix"))
        self.check(self.verdict(a, b), "FAIL", "complete interpreter/environment observation changed")

    def test_causal_23_legacy_observation_reviews(self):
        a, b = self.arms()
        for arm in (a, b):
            for interval in (0, 1):
                F.edit_json(arm.dumps / ("i%d/dump.json" % interval),
                            lambda d: (d.update(schema=C.DUMP_SCHEMA_R4),
                                       d["head"].pop("root_metadata")))
        self.check(self.verdict(a, b), "REVIEW", "legacy dump lacks the complete r5 observation contract")

    def changed_root(self, field):
        original = M.before_build

        def changed(fixture, arm):
            original(fixture, arm)
            if arm.name == "after":
                metadata = arm._root_metadata
                fields = metadata["state"]["fields"]
                fields[field] = "changed-synthetic-input"
                identity = {"fields_id": F.force_id(fields, arm.arrays[0]),
                            "native_state_id": metadata["native_state_id"]}
                metadata["state"]["result_id"] = sha256(F.canonical(identity)).hexdigest()
        M.before_build = changed
        try:
            return self.arms()
        finally:
            M.before_build = original

    def test_causal_24_root_metadata_change(self):
        self.check(self.verdict(*self.changed_root("grid")), "REVIEW", "root_metadata")

    def test_causal_25_fixed_domain_change(self):
        value = self.check(self.verdict(*self.changed_root("plan_id")), "REVIEW")
        row = value["arrays"]["i0"]["retained-root-mass"]
        self.assertIsNone(row["equal"], "fixed domain must govern equal numeric payloads")
        self.assertTrue(row["bytes_equal"])

    def test_causal_26_missing_source_context(self):
        # Supply an explicit malformed context so the default migration cannot
        # fill a missing trajectory. Both arms remain byte-identical.
        before, after = self.pair(setup=lambda r: r[1]["mesh"].update(trajectory_id=None))
        value = self.check(self.verdict(*self.arms(before, after)), "REVIEW")
        self.assertTrue(value["source_compiled_contracts"]["i1"]["unresolved"])
        self.assertTrue(any("source field" in s and "unresolved" in s for s in value["review"]))

    def test_causal_27_outer_contract_composition(self):
        a, b = self.arms()
        path = self.root / "miscomposed-v3.json"
        pin = F.write(path, {"schema": "atlas.private.n9-field-contract.v3",
                            "composition": {"before": "1"*64, "after": "2"*64}, "quantities": []})
        self.check(self.verdict(a, b, contract=(path, pin)), "FAIL", "composition")

    def test_causal_28_source_checked_outward_header(self):
        total = C.Fraction(2, 1000)
        before, after = self.pair(mutate=lambda r: (
            r[1].update(mesh=F.mesh(["1/1000", "1/1000"], stored=total+total/C.Fraction(2**65))),
            r[1]["state"].update(time_s=3.0)))
        value = self.check(self.verdict(*self.arms(before, after)), "REVIEW")
        self.assertEqual(value["addendum_e"]["after i1/mesh#0"]["verdict"], "PASS")
        row = value["records"]["i1/mesh"]
        self.assertGreater(row["counts"]["addendum_e_headers"], 0)
        self.assertFalse(any("geometry_volume_max_deviation_m3" in s for s in value["review"]))
        self.assertEqual(value["fail"], [])

    def test_causal_29_network_family_coverage(self):
        arrays = {name: array for name, array in F.i1_arrays().items()
                  if not name.startswith(C.NETWORK_PREFIX)}
        self.check(self.verdict(*self.arms(after={"arrays": arrays})), "FAIL", "network")

    def test_causal_30_isolated_peer_branch(self):
        # The whole retained18 m34 result stays mixed FAIL+ERROR. This isolated
        # intended branch has a complete independent start/stop and assertion.
        a, b = self.arms(after={"gate": False})
        self.reference_root_stop(a)
        self.check(self.verdict(a, b), "FAIL", "after arm interval width gate")

    def test_causal_31_direct_unproved_guard_contract(self):
        # Deliberately an apply_events API defence test, not a reachable
        # whole-route producer history or evidence of a scientific regression.
        _, b = self.arms()
        self.stopped(b, guard=self.CANCEL_DONE, cancel=True)
        row = {"classification": "VOID-SUSPECT", "class": "unresolved",
               "unproved_stop_fail": True, "failed_step": "runner",
               "causality": "unproved capture provenance"}
        value = C.apply_events(row, "interval", {"events": {"event": self.event(b)}}, b.attempt)
        self.assertEqual(value["classification"], "VOID-SUSPECT")
        self.assertIs(value, row)

    def test_causal_32_unbound_header_never_uses_legacy_allowance(self):
        total = C.Fraction(2, 1000)
        before, after = self.pair(
            mutate=lambda r: r[1]["mesh"].update(
                **{C.DEVIATION_FIELD: F.enc(total+total/C.Fraction(2**65))}))
        original = M.records

        def unbound(fixture, supplied):
            value = original(fixture, supplied)
            value[1]["mesh"]["schema"] = "synthetic-unbound-header"
            return value
        M.records = unbound
        try:
            a, b = self.arms(before, after)
        finally:
            M.records = original
        value = self.check(self.verdict(a, b), "REVIEW",
                           "UNBOUND_HEADER_PRODUCER")
        row = value["records"]["i1/mesh"]
        self.assertEqual(row["fields"]["mesh."+C.DEVIATION_FIELD]["changed"], 1)


CAUSAL_NAMES = tuple(sorted(name for name in vars(Causal) if name.startswith("test_causal_")))


def selected_suite(group):
    if group != "causal":
        raise ValueError("Only the exact supplemental set is supported")
    return unittest.TestSuite(Causal(name) for name in CAUSAL_NAMES)
