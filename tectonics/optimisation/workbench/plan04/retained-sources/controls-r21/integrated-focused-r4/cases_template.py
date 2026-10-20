"""Observer path coverage, isolated peer coverage and separate direct API defence."""
from hashlib import sha256
import copy
import importlib.util
import json
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
    def test_causal_50_valid_observer_path_with_matching_termination(self):
        a, b = self.arms()
        pin = self.real_observer(a, b)
        spec = self.interruption(b, self.observer_event(b), pin=pin)
        (b.dumps / "i1" / "dump.json").unlink()
        value = self.check(self.verdict(a, b, evidence=[spec], observer=pin),
                           "VOID-OBSERVER", "i1 observer interrupted by external operator_cancel")
        self.assertEqual(value["fail"], [])
        self.assertEqual(value["causal_evidence"]["after"]["observer_interruptions"], [1])
        self.assertNotIn("i1", value["arrays"])

    def bad_path_verdict(self, invalid_path):
        a, b = self.arms()
        pin = self.real_observer(a, b)

        def coherent_bad_path(value, arm):
            payload = value["payload"]
            invocation = payload["observer_invocation"]
            invocation["path"] = invalid_path(arm)
            # Re-seal the matching termination echo. The historical
            # case changed only the invocation, so termination binding
            # independently rejected it when entry validation vanished.
            retained = payload["termination"]["record"]
            content = json.loads(Path(retained["path"]).read_bytes())
            content["invocation"] = copy.deepcopy(invocation)
            payload["termination"]["record"] = self.retained(
                "termination-matching-invalid-path", content)

        spec = self.interruption(b, self.observer_event(b), coherent_bad_path, pin=pin)
        (b.dumps / "i1" / "dump.json").unlink()
        return self.verdict(a, b, evidence=[spec], observer=pin)

    def test_causal_51_observer_path_none_with_matching_termination(self):
        self.check(self.bad_path_verdict(lambda arm: None), "FAIL",
                   "not an ordinary file with the pinned observer bytes")

    def test_causal_52_observer_path_empty_with_matching_termination(self):
        self.check(self.bad_path_verdict(lambda arm: ""), "FAIL",
                   "not an ordinary file with the pinned observer bytes")

    def test_causal_53_observer_path_missing_with_matching_termination(self):
        self.check(self.bad_path_verdict(lambda arm: str(arm.dir / "absent_observer.py")), "FAIL",
                   "not an ordinary file with the pinned observer bytes")

    def test_causal_54_observer_path_wrong_bytes_with_matching_termination(self):
        def other_bytes(arm):
            path = arm.dir / "other_observer.py"
            F.write(path, b"# another observer\n")
            return str(path)

        self.check(self.bad_path_verdict(other_bytes), "FAIL",
                   "not an ordinary file with the pinned observer bytes")

    def test_causal_56_isolated_peer_branch(self):
        # The whole retained18 m34 result stays mixed FAIL+ERROR. This isolated
        # intended branch has a complete independent start/stop and assertion.
        a, b = self.arms(after={"gate": False})
        self.reference_root_stop(a)
        self.check(self.verdict(a, b), "FAIL", "after arm interval width gate")

    def test_causal_57_direct_unproved_guard_contract(self):
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


CAUSAL_NAMES = tuple(sorted(name for name in vars(Causal) if name.startswith("test_causal_")))


def selected_suite(group):
    if group != "causal":
        raise ValueError("Only the exact supplemental set is supported")
    return unittest.TestSuite(Causal(name) for name in CAUSAL_NAMES)
