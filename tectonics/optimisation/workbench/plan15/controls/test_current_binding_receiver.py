"""UNEXECUTED synthetic controls for the r17 current-control receiver seam.

Fresh exact GO is required to run this direct unittest entry point.  Selected
receiver functions are AST-extracted only inside setUp; the receiver, policy,
native helper and science are never imported.  All process/report/closure data
and filesystem/hash boundaries are synthetic mocks, with no native operation.
"""

import ast
import copy
from hashlib import sha256
import json
from pathlib import Path
import types
import unittest


SOURCE = Path(__file__).resolve().parent / "current_control.py"
CONTROLLER_PID = 91000
WORKER_PID = 91001
FAILED_PID = 91002
H3_SHA256 = "e0be3a309c8ab9ccee3c1a36525f72da27e816b1ce984651dbd85a3c072a14aa"
DLL_SHA256 = "b81a548eb7a23d4e3acbe296f1eff077a0b284617a2c1cc53a1ccdb0637b52b8"
CONTRACT_SHA256 = "1" * 64
FUNCTIONS = {
    "require", "canonical", "contract", "candidate_route_identity",
    "candidate_worker_identity", "assembly_observation_totals",
}
EXPORTS = (
    "mpfr_mul", "mpfr_add", "mpfr_set", "mpfr_less_p", "mpfr_greater_p",
    "mpfr_lessequal_p", "mpfr_regular_p", "mpfr_sgn", "mpfr_get_exp",
    "mpfr_flags_save", "mpfr_flags_clear", "mpfr_flags_restore",
    "mpfr_get_emin", "mpfr_get_emax",
)


def receiver_namespace():
    """Deferred AST extraction: no application/science import or main call."""
    source = SOURCE.read_bytes()
    tree = ast.parse(source, filename=str(SOURCE))
    selected = []
    names = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            selected.append(node)
            names.add(node.name)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id in {"COMPOSITION", "PROFILE"}):
            # These exact source constants are literal strings; exclude all
            # top-level imports, path construction and other application code.
            if not isinstance(node.value, ast.Constant) or type(node.value.value) is not str:
                raise AssertionError("receiver_lineage_constant_is_not_literal")
            selected.append(node)
    if names != FUNCTIONS:
        raise AssertionError("receiver_function_selection_incomplete")
    namespace = {
        "json": json, "sha256": sha256,
        "os": types.SimpleNamespace(getpid=lambda: CONTROLLER_PID),
    }
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    namespace["_source_sha256"] = sha256(source).hexdigest()
    return namespace


def receipt(pid):
    """Closed synthetic receipt; no actual PE or process identity is claimed."""
    base = 0x7FFA10000000 + pid * 0x100000
    return {
        "schema": "plan15.native-binding.r1", "pid": pid,
        "creation_filetime": 132000000000000000 + pid,
        "module": {"path": r"C:\synthetic\libmpfr-6.dll", "sha256": DLL_SHA256,
                   "base": base, "size": 0x100000},
        "exports": {name: {"address": base + 0x1000 + index * 0x100,
                           "rva": 0x1000 + index * 0x100}
                    for index, name in enumerate(EXPORTS)},
    }


def owner(pid, queried):
    """Actual open_admitted owner shape, populated with mock closed state."""
    creation = receipt(pid)["creation_filetime"]
    proof = {
        "schema": "plan15.current-job-proof.r1", "complete": True,
        "caller_pid": CONTROLLER_PID, "required_pids": [CONTROLLER_PID, pid],
        "member_count": 2, "member_pids": [CONTROLLER_PID, pid],
        "authority": "QueryInformationJobObject(NULL), calling controller current retained job",
    }
    result = {
        "schema": "plan15.native-admission.r1", "pid": pid,
        "creation_filetime": creation, "launch_pid": pid,
        "launch_creation_filetime": creation, "actual_parent_pid": CONTROLLER_PID,
        "relationship": "same-process", "read_only_actual_handle": True,
        "job_proof": proof, "closed": True, "close_failure": None, "query_failure": None,
        "costs": {"open_seconds": 0.01, "query_seconds": 0.02 if queried else 0.0,
                  "query_calls": 1 if queried else 0, "module_query_calls": 1 if queried else 0,
                  "cached_receipt_reuses": 0, "close_seconds": 0.001},
    }
    if queried:
        result["last_query_job_proof"] = copy.deepcopy(proof)
    return result


def costs(compiled):
    return {"admission_seconds": 0.01, "receiver_query_seconds": 0.02 if compiled else 0.0,
            "receiver_query_calls": 1 if compiled else 0, "component_times_overlap": True}


def route(pid, compiled=True):
    if not compiled:
        return {"route": "unavailable: synthetic optional dependency absent",
                "pinned_sha256": H3_SHA256, "build": None}
    raw = "synthetic already captured assembly\n"
    raw_sha = sha256(raw.encode()).hexdigest()
    return {
        "route": "compiled", "pinned_sha256": H3_SHA256,
        "build": {"compiled_assembly_sha256": raw_sha},
        "assembly_observation": {
            "status": "OBSERVED", "scientific_eligibility": False, "new_compilations": 0,
            "observation_seconds": 0.03, "raw_utf8_bytes": len(raw.encode()),
            "evidence": {"raw_sha256": raw_sha, "raw_utf8_bytes": len(raw.encode()),
                         "context": {"source_generation": {"contract_sha256": CONTRACT_SHA256},
                                     "native_binding": receipt(pid)}},
        },
    }


def process(pid=WORKER_PID, compiled=True):
    return {
        "pid": pid, "faces": 1, "exit_code": 0,
        "candidate_heat_route": route(pid, compiled),
        "native_binding_parent": {"receipt": receipt(pid) if compiled else None,
                                  "owner_record": owner(pid, compiled)},
        "native_binding_costs": costs(compiled),
    }


class ParallelMock:
    def __init__(self):
        self.receipts = {pid: receipt(pid) for pid in (WORKER_PID, CONTROLLER_PID)}
        self.binding_calls = []
        self.comparison_calls = []

    def parent_native_binding(self, pid):
        self.binding_calls.append(pid)
        if pid not in self.receipts:
            raise ValueError("independent parent binding unavailable")
        return copy.deepcopy(self.receipts[pid])

    def assembly_comparison_identity(self, evidence, build, pid):
        self.comparison_calls.append(pid)
        if evidence["context"]["native_binding"] != self.receipts[pid]:
            raise ValueError("mock independent expected binding differs")
        return {"schema": "synthetic.scoped-identity", "scientific_eligibility": False,
                "equivalence_claim": "NONE"}


class CurrentBindingReceiverControls(unittest.TestCase):
    def setUp(self):
        self.receiver = receiver_namespace()
        self.parallel = ParallelMock()
        self.request = {"_contract_sha256": CONTRACT_SHA256}
        self.report = {"calls": [{"processes": [process()]}]}
        self.controller = route(CONTROLLER_PID)

    def identity(self, report=None, controller=None):
        return self.receiver["candidate_worker_identity"](
            self.report if report is None else report,
            self.controller if controller is None else controller,
            self.parallel, self.request)

    def test_valid_compiled_workers_and_controller_use_independent_receipts(self):
        identity = self.identity()
        self.assertEqual(identity["route"], "compiled")
        self.assertIs(identity["literal_diagnostic_bytes_equivalent"], False)
        self.assertIs(identity["numerical_equivalence_claim"], False)
        self.assertEqual(self.parallel.comparison_calls, [WORKER_PID, CONTROLLER_PID])
        self.assertIn(WORKER_PID, self.parallel.binding_calls)
        self.assertIn(CONTROLLER_PID, self.parallel.binding_calls)

    def test_genuine_unavailable_route_has_no_receipt_and_no_queries(self):
        unavailable = {"calls": [{"processes": [process(compiled=False)]}]}
        identity = self.identity(unavailable, route(CONTROLLER_PID, False))
        self.assertTrue(identity["route"].startswith("unavailable: "))
        self.assertIsNone(identity["build"])
        self.assertEqual(self.parallel.binding_calls, [])
        self.assertEqual(self.parallel.comparison_calls, [])
        retained = unavailable["calls"][0]["processes"][0]
        self.assertIsNone(retained["native_binding_parent"]["receipt"])
        self.assertEqual(retained["native_binding_costs"]["receiver_query_calls"], 0)

    def test_unavailable_fabricated_receipt_assembly_or_query_is_refused(self):
        for fault in ("receipt", "assembly", "query"):
            with self.subTest(fault=fault):
                item = process(compiled=False)
                if fault == "receipt":
                    item["native_binding_parent"]["receipt"] = receipt(WORKER_PID)
                elif fault == "assembly":
                    item["candidate_heat_route"]["assembly_observation"] = route(WORKER_PID)["assembly_observation"]
                else:
                    item["native_binding_costs"]["receiver_query_calls"] = 1
                with self.assertRaises(ValueError):
                    self.identity({"calls": [{"processes": [item]}]}, route(CONTROLLER_PID, False))

    def test_missing_or_forged_parent_binding_is_refused(self):
        for fault in ("missing", "forged", "registry_missing"):
            with self.subTest(fault=fault):
                report = copy.deepcopy(self.report)
                item = report["calls"][0]["processes"][0]
                if fault == "missing":
                    del item["native_binding_parent"]
                elif fault == "forged":
                    item["native_binding_parent"]["receipt"]["module"]["base"] += 1
                else:
                    del self.parallel.receipts[WORKER_PID]
                with self.assertRaises(ValueError):
                    self.identity(report)

    def test_wrong_creation_unclosed_handle_or_failed_ownership_is_refused(self):
        for name, value in (("creation_filetime", 1), ("closed", False),
                            ("close_failure", {"code": "CLOSE"}),
                            ("query_failure", {"code": "QUERY"}),
                            ("read_only_actual_handle", False), ("relationship", "unknown")):
            with self.subTest(name=name):
                report = copy.deepcopy(self.report)
                report["calls"][0]["processes"][0]["native_binding_parent"]["owner_record"][name] = value
                with self.assertRaises(ValueError):
                    self.identity(report)

    def test_query_count_and_nonfinite_or_untyped_costs_are_refused(self):
        faults = (("receiver_query_calls", 0), ("receiver_query_calls", 2),
                  ("receiver_query_calls", True), ("receiver_query_calls", 1.0),
                  ("admission_seconds", float("nan")),
                  ("receiver_query_seconds", float("nan")),
                  ("receiver_query_seconds", float("inf")),
                  ("receiver_query_seconds", -0.1), ("admission_seconds", 1),
                  ("component_times_overlap", False))
        for name, value in faults:
            with self.subTest(name=name, value=repr(value)):
                report = copy.deepcopy(self.report)
                report["calls"][0]["processes"][0]["native_binding_costs"][name] = value
                with self.assertRaises(ValueError):
                    self.identity(report)

    def test_controller_binding_mismatch_is_refused(self):
        controller = copy.deepcopy(self.controller)
        controller["assembly_observation"]["evidence"]["context"]["native_binding"]["creation_filetime"] += 1
        with self.assertRaises(ValueError):
            self.identity(controller=controller)

    def test_compiled_worker_receipt_and_evidence_must_both_match_parent(self):
        report = copy.deepcopy(self.report)
        item = report["calls"][0]["processes"][0]
        forged = copy.deepcopy(item["native_binding_parent"]["receipt"])
        forged["creation_filetime"] += 1
        item["native_binding_parent"]["receipt"] = forged
        item["native_binding_parent"]["owner_record"]["creation_filetime"] = forged["creation_filetime"]
        item["candidate_heat_route"]["assembly_observation"]["evidence"]["context"]["native_binding"] = forged
        with self.assertRaises(ValueError):
            self.identity(report)

    def contract_fixture(self):
        adapter = "C:/synthetic/current_control.py"
        native = "C:/synthetic/native_binding.py"
        library = "C:/synthetic/libmpfr-6.dll"
        pins = {adapter: "a" * 64, native: "b" * 64, library: DLL_SHA256}
        observer = {
            "schema": "plan15.assembly-observer-binding.r2", "policy": {},
            "emitter_sources": {}, "source_pins": dict(pins), "generation_files": {},
            "adapter": {"path": adapter, "sha256": pins[adapter]},
            "native_binding_source": {"path": native, "sha256": pins[native]},
            "native_library": {"path": library, "sha256": pins[library]},
            "prospective_native_bindings": True, "prospective_rule_version": "plan15.native-binding.r1",
        }
        value = {"schema": "plan15.current-control.r3", "logical_budget_bytes": 16 << 30,
                 "lineage": {"composition": {"sha256": self.receiver["COMPOSITION"]},
                             "profile": {"sha256": self.receiver["PROFILE"]}},
                 "H3": "CANDIDATE_NOT_ENABLED", "default_changed": False,
                 "pins": dict(pins), "comparison_policy_candidate": True,
                 "assembly_observer": observer}
        return value, adapter, native, library, pins

    def call_contract(self, value, adapter, expected_pins):
        raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()

        class MemoryPath:
            def __init__(self, path):
                self.path = str(path)

            def __str__(self):
                return self.path

            def resolve(self):
                return self

            def read_bytes(self):
                if self.path != "C:/synthetic/contract.json":
                    raise AssertionError("unexpected_real_file_read")
                return raw

        # Exact file hashing is its own mocked boundary: no claimed actual DLL
        # bytes and no real file reads are substituted for a native proof.
        self.receiver.update(Path=MemoryPath, __file__=adapter,
                             digest=lambda name: expected_pins[str(name)])
        return self.receiver["contract"]("C:/synthetic/contract.json", sha256(raw).hexdigest())

    def test_valid_r3_contract_binds_both_native_sources_in_exact_closure(self):
        value, adapter, _, _, pins = self.contract_fixture()
        result = self.call_contract(value, adapter, pins)
        self.assertEqual(result["schema"], "plan15.current-control.r3")
        self.assertEqual(result["_verified_source_digest"],
                         sha256(self.receiver["canonical"](pins)).hexdigest())

    def test_contract_schema_missing_native_pin_and_unknown_closure_are_refused(self):
        for fault in ("schema", "observer_schema", "native_pin", "library_pin",
                      "native_source_pin", "native_key", "extra_key", "rule"):
            with self.subTest(fault=fault):
                value, adapter, native, library, pins = self.contract_fixture()
                observer = value["assembly_observer"]
                if fault == "schema":
                    value["schema"] = "plan15.current-control.r2"
                elif fault == "observer_schema":
                    observer["schema"] = "plan15.assembly-observer-binding.r1"
                elif fault == "native_pin":
                    del value["pins"][native]
                elif fault == "library_pin":
                    del value["pins"][library]
                elif fault == "native_source_pin":
                    del observer["source_pins"][native]
                elif fault == "native_key":
                    del observer["native_binding_source"]
                elif fault == "extra_key":
                    observer["unknown_authority"] = True
                else:
                    observer["prospective_rule_version"] = "future"
                with self.assertRaises(ValueError):
                    self.call_contract(value, adapter, pins)

    def test_totals_retain_failed_partial_evidence_and_native_cost_error_metadata(self):
        text = "synthetic failed partial raw\n"
        failed_costs = costs(True)
        failed = {
            "pid": FAILED_PID, "faces": 0, "exit_code": 2,
            "candidate_heat_route": {"route": "OBSERVATION_FAILED", "assembly_observation": {
                "status": "REFUSED", "partial": {"process_id": FAILED_PID, "raw_text": text,
                    "raw_sha256": sha256(text.encode()).hexdigest(), "observation_seconds": 0.04,
                    "raw_capture_complete": False}}},
            "native_binding_costs": failed_costs,
            "native_binding_error": {"code": "QUERY_REFUSED", "message": "synthetic query failure"},
            "native_binding_cleanup_error": {"code": "CLOSE_REFUSED", "message": "synthetic close failure"},
        }
        report = copy.deepcopy(self.report)
        report["calls"][0]["processes"].append(failed)
        # A repeated identical process record must not double-count raw text.
        report["calls"].append(copy.deepcopy(self.report["calls"][0]))
        controller = copy.deepcopy(self.controller)
        controller["assembly_observation"]["native_binding_costs"] = {"self_capture_seconds": 0.005}
        total = self.receiver["assembly_observation_totals"](report, controller)
        self.assertEqual(total["compiled_process_records"], 2)
        self.assertEqual(total["failed_process_records"], 1)
        self.assertEqual(total["total_process_observation_records"], 3)
        self.assertEqual(total["raw_utf8_bytes"], 2 * self.controller["assembly_observation"]["raw_utf8_bytes"] + len(text.encode()))
        self.assertEqual(total["native_binding_costs_by_process"][str(FAILED_PID)], failed_costs)
        self.assertEqual(total["native_binding_costs_by_process"][str(CONTROLLER_PID)],
                         controller["assembly_observation"]["native_binding_costs"])
        self.assertEqual(total["native_binding_errors_by_process"][str(FAILED_PID)], {
            "native_binding_error": failed["native_binding_error"],
            "native_binding_cleanup_error": failed["native_binding_cleanup_error"]})
        self.assertIs(total["raw_capture_complete_by_process"][str(FAILED_PID)], False)
        self.assertEqual(total["retained_observation_seconds_by_process"][str(FAILED_PID)], 0.04)
        self.assertIs(total["concurrent_component_times_not_additive"], True)
        self.assertIs(total["numerical_or_literal_diagnostic_byte_equivalence_claim"], False)

    def test_totals_refuse_conflicting_duplicate_process_or_failed_raw_hash(self):
        report = copy.deepcopy(self.report)
        conflict = copy.deepcopy(report["calls"][0])
        conflict["processes"][0]["candidate_heat_route"]["assembly_observation"]["observation_seconds"] += 0.01
        report["calls"].append(conflict)
        with self.assertRaises(ValueError):
            self.receiver["assembly_observation_totals"](report, {"route": "NOT_OBSERVED"})
        failed = {"pid": FAILED_PID, "faces": 0, "candidate_heat_route": {
            "route": "OBSERVATION_FAILED", "assembly_observation": {"status": "REFUSED", "partial": {
                "process_id": FAILED_PID, "raw_text": "synthetic", "raw_sha256": "0" * 64}}}}
        with self.assertRaises(ValueError):
            self.receiver["assembly_observation_totals"]({"calls": [{"processes": [failed]}]}, {"route": "NOT_OBSERVED"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
