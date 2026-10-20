"""Disposable gate faults only: no native imports, workers, science or queue."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


G = load("consumer_gate_test_subject", "proof_gate.py")
A = load("consumer_adapter_test_subject", "launch_adapter.py")


class ProofGateTests(unittest.TestCase):
    def setUp(self):
        artifacts = HERE / "test-artifacts"
        artifacts.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="gate-", dir=artifacts)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.integration, self.task = self.root / "integration", self.root / "native"
        self.integration.mkdir()
        self.task.mkdir()
        self.patches = [patch.object(G, "INTEGRATION", self.integration),
                        patch.object(G, "TASK", self.task), patch.object(A, "GATE", G)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.proof = self.root / "proof"
        self.proof.mkdir()
        self.output = self.root / "timing-output"
        self.selection_path = self.root / "proof-selection.json"
        self.manifest_path = self.root / "consumer-selection.json"
        self.report_path = self.proof / "verification.json"
        self.disposition_path = self.root / "dispositions.json"
        self.acceptance_path = self.root / "acceptance.json"
        self.authority_path = self.root / "authority.json"
        self.authority_evidence = self.root / "synthetic-authority.txt"
        self.authority_evidence.write_text("SYNTHETIC TEST ONLY. No real science is accepted or authorised.")
        self.source_paths = [self.root / "selected-code.py"]
        self.source_paths[0].write_text("# fixture source\n")
        self.overlays = [self.integration / "order-repair/private_heat_physical_order_r1.py"]
        self.overlays.extend(self.integration / "order-repair" / arm / name
                             for arm in ("lf3", "lh")
                             for name in ("private_heat_forward_kernel_r13.py", "private_heat_native_issuer_r13.py"))
        for path in self.overlays:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic selected overlay\n")
        self.source_paths += self.overlays
        self.metrics_path = self.integration / "consumer-repair/metrics.py"
        self.metrics_path.parent.mkdir()
        self.metrics_path.write_text("# synthetic metrics source; never executed\n")
        self.source_paths.append(self.metrics_path)
        self.history_paths = list(G.prediction_history_paths())
        for path in self.history_paths:
            path.parent.mkdir(parents=True)
            self.write(path, dict(arms=[]))
            self.source_paths.append(path)
        self.required_patch = patch.object(G, "required_source_paths", return_value=set(self.source_paths))
        self.required_patch.start()
        self.addCleanup(self.required_patch.stop)
        self.source_pins = {str(path): G.digest(path) for path in self.source_paths}
        self.selection = dict(schema="plan05-integrated-r13.v1", scope=["lf3", "lh"],
                              historical_q10="FAIL", q22="HELD", source_pins=dict(self.source_pins),
                              order_repair=dict(schema="plan05.physical-order-selection.r1", scope=["lf3", "lh"],
                                                source_pins={str(path): G.digest(path) for path in self.overlays}))
        self.write(self.selection_path, self.selection)
        self.selection_sha = G.digest(self.selection_path)
        self.report = dict(schema="atlas.private.d02-verifier.r13", historical_q10="FAIL", q22="HELD",
                           scientific_acceptance=False, new_run_verdict="METADATA_DISPOSITION_REQUIRED",
                           historical_q10_binding_status="NOT_REPRODUCED",
                           corresponding_inputs_equal=True, solver_attribution_permitted=True,
                           physical_context_mismatches=[], cell_bijection_pi=[1, 0],
                           face_bijection_sigma=[0], face_orientation=[-1],
                           arrays={name: dict(bitwise_equal=True, differing_rows=[]) for name in G.ARRAYS},
                           exact_cell_accounts={name: dict(exact_equal=True, differing_rows=[]) for name in G.ACCOUNTS},
                           exact_face_account=dict(exact_equal=True, differing_faces=[]),
                           exact_scalars={name: True for name in G.SCALARS},
                           within_arm_ledger_errors=dict(arm_a=[], arm_b=[]),
                           metadata=dict(coverage="ALL_LEAVES", compared_leaves=1, equal_leaves=0,
                                         separately_mapped_account_and_axis_leaves=0,
                                         leaf_dispositions={"/identity": "PROVENANCE"},
                                         invariant_differences=[], proof_failures=[],
                                         unresolved_required_evidence=[],
                                         provenance_differences=[dict(path="/identity", arm_a="left", arm_b="right")],
                                         resource_differences=[], header_provenance_differences=[],
                                         evidence=dict(order_repair={})))
        for arm, layout in (("arm_a", "lf3"), ("arm_b", "lh")):
            self.report["metadata"]["evidence"]["order_repair"][arm] = dict(
                status="EXACT_SELECTED_REPAIR_SOURCES_BOUND", launch_manifest_sha256=self.selection_sha,
                descriptor=dict(layout=layout, manifest_path=str(self.selection_path),
                                manifest_sha256=self.selection_sha, numerical_tolerances_changed=False,
                                original_metric_mutated=False))
        self.write(self.proof / "attempt.json", dict(mode="capture", manifest_sha256=self.selection_sha))
        self.stages = []
        for name in ("arm-0", "arm-1", "check-arms", "verification"):
            hashes = {}
            for stream in ("stdout", "stderr"):
                path = self.proof / (name + "." + stream + ".log")
                path.write_text("synthetic process log\n")
                hashes[stream] = G.digest(path)
            stage = dict(finality="COMPLETE", log_final=True, errors=[],
                         last_observation=dict(job=dict(active=0)),
                         exit_code=1 if name == "verification" else 0,
                         passed=name != "verification", log_sha256=hashes)
            self.stages.append(stage)
            self.write(self.proof / (name + ".process.json"), stage)
        self.result = dict(schema="plan05-route-result.v1", mode="capture",
                           historical_q10="FAIL", q22="HELD", passed=False, stages=self.stages)
        self.write(self.proof / "result.json", self.result)
        self.write(self.proof / "summary.json", dict(arms=[
            dict(arm=index, label=layout, status="PASS", exit_code=0, leaks=0,
                 used=[6, 6], fallback=[None, None]) for index, layout in enumerate(("lf3", "lh"))]))
        for index in (0, 1):
            arm = self.proof / ("arm-" + str(index))
            arm.mkdir()
            for name in ("arrays.json", "legacy_metadata.json", "thermal_mesh_record.json",
                         "d02_correspondence_capture.json", "observer_disposition.json",
                         *(field + ".npy" for field in G.ARRAYS)):
                (arm / name).write_text("synthetic bound companion\n")
            self.write(self.proof / ("arm-" + str(index) + ".json"), {"fixture": True})
        self.reseal()

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf8")

    @staticmethod
    def ref(path):
        return dict(path=str(path), sha256=G.digest(path))

    def reseal(self):
        self.write(self.report_path, self.report)
        self.dispositions = dict(schema="plan05.metadata-dispositions.r1",
                                 verification_sha256=G.digest(self.report_path), decisions={
            key: dict(entry_sha256=value, decision="DISPOSITION_RECORDED",
                      reason="Synthetic test: retain this distinct context without claiming equivalence.")
            for key, value in G.required_dispositions(self.report).items()})
        self.write(self.disposition_path, self.dispositions)
        proof_artifacts = {str(path): G.digest(path) for path in G.required_proof_paths(self.proof)}
        self.acceptance = dict(schema="plan05.scientific-correctness-acceptance.r1",
                               decision="ACCEPTED", scope=["lf3", "lh"], historical_q10="FAIL",
                               historical_linkage="NOT_REPRODUCED", order_selection_sha256=self.selection_sha,
                               verification_sha256=G.digest(self.report_path),
                               dispositions_sha256=G.digest(self.disposition_path),
                               proof_artifacts_sha256=G.canonical_hash(proof_artifacts),
                               authority_evidence=self.ref(self.authority_evidence))
        self.write(self.acceptance_path, self.acceptance)
        self.authority = dict(schema="plan12.run-authority.r1", decision="AUTHORIZED", queue_ticket="q22",
                              order_selection_sha256=self.selection_sha,
                              correctness_acceptance_sha256=G.digest(self.acceptance_path),
                              source_pins_sha256=G.canonical_hash(self.source_pins),
                              schedule=list(G.SCHEDULE), output=str(self.output),
                              authority_evidence=self.ref(self.authority_evidence))
        self.write(self.authority_path, self.authority)
        self.manifest = dict(schema="plan12.successor-consumer-selection.r1", historical_q10="FAIL",
                             queue_ticket="q22", schedule=list(G.SCHEDULE), source_pins=self.source_pins,
                             order_selection=self.ref(self.selection_path), verification=self.ref(self.report_path),
                             dispositions=self.ref(self.disposition_path), proof_artifacts=proof_artifacts,
                             correctness_acceptance=self.ref(self.acceptance_path),
                             run_authority=self.ref(self.authority_path), output=str(self.output),
                             prediction_history=[self.ref(path) for path in self.history_paths])
        self.save_manifest()

    def save_manifest(self):
        self.write(self.manifest_path, self.manifest)
        self.sha = G.digest(self.manifest_path)

    def validate(self):
        return G.validate_selection(self.manifest_path, self.sha)

    def test_valid_bound_proof_and_separate_decisions(self):
        self.assertEqual(self.validate(), self.manifest)
        self.output.mkdir()
        self.assertEqual(G.validate_child(self.manifest_path, self.sha, "time",
                                         self.task / "hs/lf3", self.output, 3), self.manifest)

    def test_missing_acceptance_and_run_authority_refuse(self):
        for field in ("correctness_acceptance", "run_authority"):
            with self.subTest(field=field):
                original = self.manifest.pop(field)
                self.save_manifest()
                with self.assertRaises(G.Refuse):
                    self.validate()
                self.manifest[field] = original

    def test_numerical_fault_cannot_be_dispositioned_or_accepted_away(self):
        for family, field, key in (("arrays", G.ARRAYS[0], "bitwise_equal"),
                                   ("exact_cell_accounts", G.ACCOUNTS[0], "exact_equal")):
            with self.subTest(family=family):
                self.report[family][field][key] = False
                self.reseal()
                with self.assertRaises(G.Refuse):
                    self.validate()
                self.report[family][field][key] = True
        self.report["exact_face_account"]["differing_faces"] = [0]
        self.reseal()
        with self.assertRaises(G.Refuse):
            self.validate()

    def test_missing_required_field_refuses(self):
        del self.report["arrays"][G.ARRAYS[-1]]
        self.reseal()
        with self.assertRaises(G.Refuse):
            self.validate()

    def test_incomplete_bijection_refuses(self):
        self.report["cell_bijection_pi"] = [0, 0]
        self.reseal()
        with self.assertRaises(G.Refuse):
            self.validate()

    def test_invariant_codec_and_missing_evidence_refuse(self):
        for key in ("invariant_differences", "proof_failures", "unresolved_required_evidence"):
            with self.subTest(key=key):
                self.report["metadata"][key] = [{"path": "/fault"}]
                self.reseal()
                with self.assertRaises(G.Refuse):
                    self.validate()
                self.report["metadata"][key] = []

    def test_metadata_coverage_count_refuses(self):
        self.report["metadata"]["compared_leaves"] = 2
        self.reseal()
        with self.assertRaises(G.Refuse):
            self.validate()

    def test_missing_disposition_refuses(self):
        self.dispositions["decisions"].clear()
        self.write(self.disposition_path, self.dispositions)
        self.manifest["dispositions"] = self.ref(self.disposition_path)
        self.save_manifest()
        with self.assertRaisesRegex(G.Refuse, "Metadata decisions incomplete"):
            self.validate()

    def test_changed_proof_bytes_refuse(self):
        (self.proof / "arm-0/enthalpy_j.npy").write_text("changed")
        with self.assertRaisesRegex(G.Refuse, "Pinned bytes changed"):
            self.validate()

    def test_changed_selected_code_refuses(self):
        self.source_paths[0].write_text("changed")
        with self.assertRaisesRegex(G.Refuse, "Pinned bytes changed"):
            self.validate()

    def test_metrics_source_pin_is_required_and_changed_bytes_refuse(self):
        original = self.manifest["source_pins"].pop(str(self.metrics_path))
        self.save_manifest()
        with self.assertRaisesRegex(G.Refuse, "consumer source unbound"):
            self.validate()
        self.manifest["source_pins"][str(self.metrics_path)] = original
        self.save_manifest()
        self.metrics_path.write_text("# changed metric implementation\n")
        with self.assertRaisesRegex(G.Refuse, "Pinned bytes changed"):
            self.validate()

    def test_exact_two_prediction_history_routes_are_required(self):
        original = self.manifest["prediction_history"]
        for references in (None, original[:1], original + original[:1],
                           list(reversed(original)), [original[0], original[0]]):
            with self.subTest(references=references):
                self.manifest["prediction_history"] = references
                self.save_manifest()
                with self.assertRaises(G.Refuse):
                    self.validate()
        self.manifest["prediction_history"] = original

    def test_prediction_history_reference_pin_and_bytes_are_bound(self):
        reference = self.manifest["prediction_history"][0]
        old_hash = reference["sha256"]
        reference["sha256"] = "0" * 64
        self.save_manifest()
        with self.assertRaisesRegex(G.Refuse, "reference is not source-bound"):
            self.validate()
        reference["sha256"] = old_hash
        self.save_manifest()
        self.history_paths[0].write_text('{"arms":[{"status":"changed"}]}')
        with self.assertRaisesRegex(G.Refuse, "Pinned bytes changed"):
            self.validate()

    def test_wrong_acceptance_binding_refuses(self):
        self.acceptance["verification_sha256"] = "0" * 64
        self.write(self.acceptance_path, self.acceptance)
        self.manifest["correctness_acceptance"] = self.ref(self.acceptance_path)
        self.save_manifest()
        with self.assertRaisesRegex(G.Refuse, "Acceptance binds different evidence"):
            self.validate()

    def test_live_descendant_refuses_even_with_new_hashes(self):
        self.stages[0]["last_observation"]["job"]["active"] = 1
        self.write(self.proof / "arm-0.process.json", self.stages[0])
        self.write(self.proof / "result.json", self.result)
        self.reseal()
        with self.assertRaisesRegex(G.Refuse, "finality incomplete"):
            self.validate()

    def test_wrong_proof_selection_refuses(self):
        self.report["metadata"]["evidence"]["order_repair"]["arm_b"]["descriptor"]["layout"] = "lf3"
        self.reseal()
        with self.assertRaisesRegex(G.Refuse, "not from the selected"):
            self.validate()

    def test_child_mode_layout_output_and_index_are_bound(self):
        for mode, layout, out, index in (
            ("prof", "lf3", self.output, 3), ("time", "lh", self.output, 3),
            ("time", "lf3", self.root / "other", 3), ("time", "lf3", self.output, 11),
        ):
            with self.subTest(mode=mode, layout=layout, index=index):
                with self.assertRaises(G.Refuse):
                    G.validate_child(self.manifest_path, self.sha, mode, self.task / "hs" / layout, out, index)

    def test_adapter_exact_schedule_clean_environment_and_no_replay(self):
        with patch.dict(os.environ, {"PYTHONPATH": "wrong", "PYTHONSTARTUP": "untrusted"}, clear=True):
            plan = A.build_plan(self.manifest_path, self.sha)
        self.assertEqual(len(plan["arms"]), 11)
        self.assertEqual([(arm["mode"], arm["layout"]) for arm in plan["arms"]],
                         [(arm["mode"], arm["layout"]) for arm in G.SCHEDULE])
        for arm in plan["arms"]:
            self.assertNotIn("PYTHONSTARTUP", arm["environment"])
            self.assertEqual(arm["environment"]["PYTHONHASHSEED"], "0")
            self.assertEqual(arm["argv"][-3:], ["--consumer-selection", str(self.manifest_path), self.sha])
        self.assertNotIn("PYTHONPATH", plan["arms"][0]["environment"])
        self.assertEqual(plan["arms"][10]["environment"]["PYTHONPATH"], str(self.task / "hs/workerprof"))
        self.assertEqual(plan["checker_argv"][-1], "11")
        self.output.mkdir()
        with self.assertRaisesRegex(G.Refuse, "output exists"):
            A.build_plan(self.manifest_path, self.sha)


if __name__ == "__main__":
    unittest.main()
