"""Focused dependency, caller-presence and arithmetic-check refusal controls.

Standard library only. Caller tests read pinned source through ATLAS_T without
executing it; other controls use synthetic records or mocked producer calls.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from types import ModuleType
from fractions import Fraction
from pathlib import Path
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "n9-tools-r21"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = load("boundary_field_contracts", TOOLS / "field_contracts.py")
P = load("boundary_field_provenance", TOOLS / "field_provenance.py")
CHECK = load("boundary_equat_check", HERE.parent / "check_equat_bound.py")
D = load("boundary_observer", TOOLS / "dump_arm_r5.py")
E_PATH = "atlas_tectonics/integration_exterior_mesh.py"
DEPENDENCY_PATH = "atlas_tectonics/integration_volume.py"


def enc(value):
    value = Fraction(value)
    return [hex(value.numerator), hex(value.denominator)]


def mesh(shift=0):
    segments = [{"angular_velocity_rad_s": [enc(0), enc(0), enc(0)],
                 "start_time_s": enc(0), "end_time_s": enc(1)}]
    return {"schema": C.MESH_SCHEMA,
            "representative_quaternion": [enc(1), enc(shift), enc(0), enc(0)],
            "pose_operator_error_bound": enc(Fraction(1, 256)),
            "trajectory_id": C.digest(segments), "trajectory_segments": segments,
            "endpoint": "end", C.WIDTH: enc(Fraction(1, 8)),
            "funding_id": "synthetic-funding", "source": {"sphere_state_id": "synthetic-sphere"},
            "time_s": enc(1)}


class PoseDependencyBoundaries(unittest.TestCase):
    def check_case(self, sources, changed_dependency, changed_value, fields, expected):
        manifests = {arm: C.digest(arm) for arm in ("before", "after")}
        pins = {
            arm: {E_PATH: sources[index],
                  DEPENDENCY_PATH: C.digest("changed" if index and changed_dependency else "same")}
            for index, arm in enumerate(("before", "after"))
        }
        records = {"before": mesh(), "after": mesh(Fraction(1, 2**24) if changed_value else 0)}
        pair = {arm: {"record": value, "identity": C.digest(value),
                      "producer": {"path": E_PATH, "sha256": pins[arm][E_PATH]}}
                for arm, value in records.items()}
        compiled = C.compile_source_evidence(
            manifests, pins, {"mesh": pair}, [("mesh", field) for field in fields])
        contracts = C.FieldContracts(
            compiled["document"], manifests, pins, compiled["verified_evidence"])
        judged, _ = contracts.compare_record(
            "mesh", records["before"], records["after"], compiled["correspondence"])
        actual = {row["path"][1]: (row["verdict"], row["code"]) for row in judged}
        actual.update({row["path"][1]: ("REVIEW", row["code"]) for row in compiled["unresolved"]})
        self.assertEqual(actual, {field: expected for field in fields})

    def test_original_identity_changed_dependency_reviews(self):
        self.check_case((C.E_SOURCE, C.E_SOURCE), True, True, C.E_POSE_FIELDS,
                        ("REVIEW", "E_POSE_DEPENDENCY_SOURCES_DIFFER"))

    def test_rounded_identity_changed_dependency_reviews(self):
        self.check_case((C.E_ROUNDED, C.E_ROUNDED), True, True, C.E_POSE_FIELDS,
                        ("REVIEW", "E_POSE_DEPENDENCY_SOURCES_DIFFER"))

    def test_rounding_pair_changed_dependency_reviews(self):
        self.check_case((C.E_SOURCE, C.E_ROUNDED), True, True, C.E_POSE_FIELDS,
                        ("REVIEW", "E_POSE_DEPENDENCY_SOURCES_DIFFER"))

    def test_original_identity_unchanged_control(self):
        self.check_case((C.E_SOURCE, C.E_SOURCE), False, False, C.E_POSE_FIELDS,
                        ("PASS", "EXACT_EQUAL"))

    def test_rounded_identity_unchanged_control(self):
        self.check_case((C.E_ROUNDED, C.E_ROUNDED), False, False, C.E_POSE_FIELDS,
                        ("PASS", "EXACT_EQUAL"))

    def test_non_pose_headers_keep_exact_input_contract(self):
        self.check_case((C.E_SOURCE, C.E_SOURCE), True, False, ("time_s", C.WIDTH),
                        ("PASS", "EXACT_EQUAL"))


class CallerPresenceBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("ATLAS_T")
        if not root:
            raise unittest.SkipTest("ATLAS_T is required for pinned caller-source controls")
        source = Path(root) / "ac/p1820c-r4/src/atlas_tectonics"
        expected = (("integration_wall_measures.py", P.W_SOURCE),
                    ("integration_exterior_mesh.py", P.E_SOURCE))
        if any(not (source / name).is_file() for name, _ in expected):
            raise unittest.SkipTest("Pinned caller-control source files are unavailable")
        cls.absent = {}
        for name, pin in expected:
            raw = (source / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != pin:
                raise AssertionError("Source identity mismatch: " + name)
            cls.absent["atlas_tectonics/" + name] = raw
        cls.present = dict(cls.absent)
        cls.present["atlas_tectonics/integration_current_force_pose.py"] = (
            b"from . import integration_exterior_mesh as E\n"
            b"def current_force_pose(segments, goal):\n"
            b"    return E._representative_pose(segments, goal)\n"
        )

    def check_case(self, before, after, expected, counts, missing_arm=None):
        pins = {arm: {path: hashlib.sha256(raw).hexdigest() for path, raw in data.items()}
                for arm, data in (("before", before), ("after", after))}
        manifests = {
            arm: hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            for arm, values in pins.items()
        }
        result = P.assess_records(
            manifests, pins, {"before": before, "after": after}, {"before": {}, "after": {}}, [])
        row = next(item for item in result["receipts"] if item["slot"] == "P.current-force-pose")
        self.assertEqual(result["verdict"], expected)
        self.assertEqual(row["verdict"], expected)
        self.assertEqual({arm: len(row["arms"][arm]["call_sites"]) for arm in counts}, counts)
        self.assertEqual(row["binding"]["relation"], "identity")
        if missing_arm is None:
            self.assertEqual(row["issues"], [])
        else:
            self.assertEqual(set(row["issues"]), {
                "CALLER_SOURCE_CHANGED",
                missing_arm + ":integration_current_force_pose.py:current_force_pose:REVIEWED_CALL_SITE_ABSENT",
            })

    def test_matched_caller_binds(self):
        self.check_case(self.present, self.present, "BOUND", {"before": 1, "after": 1})

    def test_before_only_caller_reviews(self):
        self.check_case(self.present, self.absent, "REVIEW", {"before": 1, "after": 0}, "after")

    def test_after_only_caller_reviews(self):
        self.check_case(self.absent, self.present, "REVIEW", {"before": 0, "after": 1}, "before")


class ArithmeticCheckRefusals(unittest.TestCase):
    def check_case(self, refusals, expected_exit):
        pose = ((Fraction(1), Fraction(0), Fraction(0), Fraction(0)), Fraction(1, 64))
        before = mock.Mock(return_value=pose)
        if refusals == 18:
            before.side_effect = CHECK.VolumeError("synthetic refusal")
            after = mock.Mock(return_value=pose)
        elif refusals:
            after = mock.Mock(side_effect=[CHECK.VolumeError("synthetic refusal")] + [pose]*17)
        else:
            after = mock.Mock(return_value=pose)
        output = io.StringIO()
        with mock.patch.object(CHECK, "pinned", return_value=object()) as pinned, \
                mock.patch.object(CHECK, "build", side_effect=[before, after]) as build, \
                contextlib.redirect_stdout(output):
            status = CHECK.main("baseline-e", "rounded-e", "rounded-w")
        self.assertEqual(status, expected_exit)
        self.assertEqual(pinned.call_count, 3)
        self.assertEqual(build.call_count, 2)
        self.assertEqual(before.call_count, 18)
        self.assertEqual(after.call_count, 0 if refusals == 18 else 18)
        text = output.getvalue()
        verdict = "PASS" if not refusals else "FAIL %d" % refusals
        self.assertIn("RESULT %s evaluated=%d refused=%d expected=18" %
                      (verdict, 18-refusals, refusals), text)
        self.assertEqual(text.count("refused:"), refusals)

    def test_all_refused_fails(self):
        self.check_case(18, 1)

    def test_one_refused_fails(self):
        self.check_case(1, 1)

    def test_all_evaluated_passes(self):
        self.check_case(0, 0)

class ObserverAliasBoundaries(unittest.TestCase):
    @contextlib.contextmanager
    def observer_case(self, *, wrong_pin=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            native = root / "native" / "atlas_tectonics"
            native.mkdir(parents=True)
            (root / "helpers").mkdir()
            source = native / "__init__.py"
            source.write_bytes(b"# disposable source inventory\n")
            observer = root / "observer.py"
            observer.write_bytes(b"# disposable observer entry\n")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "files": {"native/atlas_tectonics/__init__.py": hashlib.sha256(source.read_bytes()).hexdigest()},
                "data_only": {},
            }), encoding="utf8")
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "workspace": str(root), "native_root": "native", "import_roots": ["helpers"],
                "source_manifest": {"path": "manifest.json",
                                    "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()},
            }), encoding="utf8")
            main = ModuleType("__main__")
            main.__file__ = str(observer)
            pin = "0" * 64 if wrong_pin else hashlib.sha256(observer.read_bytes()).hexdigest()
            fence = D.ObserverFence(profile, hashlib.sha256(profile.read_bytes()).hexdigest(), observer, pin)
            with mock.patch.dict(sys.modules, {"__main__": main}):
                yield fence, main

    def test_exact_main_multiprocessing_alias_is_normalised(self):
        with self.observer_case() as (fence, main):
            with mock.patch.dict(sys.modules, {"__mp_main__": main}):
                try:
                    result = fence.audit(bootstrap=True)
                except D.DumpRefused as error:
                    self.fail("Exact multiprocessing main-object alias should normalise: " + str(error))
                self.assertNotIn("__mp_main__", sys.modules)
                self.assertIs(sys.modules["__main__"], main)
                self.assertEqual(result["exempt"], {
                    "path": str(fence.observer_path), "sha256": fence.observer_pin,
                })
                self.assertTrue(result["data_only_exclusion"])
                self.assertTrue(result["first_resolution"])

    def test_foreign_same_path_multiprocessing_alias_refuses_and_remains(self):
        with self.observer_case() as (fence, main):
            foreign = ModuleType("__mp_main__")
            foreign.__file__ = main.__file__
            with mock.patch.dict(sys.modules, {"__mp_main__": foreign}):
                with self.assertRaisesRegex(D.DumpRefused, "observer exemption used by another module"):
                    fence.audit(bootstrap=True)
                self.assertIs(sys.modules["__mp_main__"], foreign)

    def test_wrong_observer_pin_refuses_before_alias_normalisation(self):
        with self.observer_case(wrong_pin=True) as (fence, main):
            with mock.patch.dict(sys.modules, {"__mp_main__": main}):
                with self.assertRaisesRegex(D.DumpRefused, "observer differs from independently supplied pin"):
                    fence.audit(bootstrap=True)
                self.assertIs(sys.modules["__mp_main__"], main)

    def test_other_alias_of_exact_main_object_still_refuses(self):
        with self.observer_case() as (fence, main):
            alias = "_n9_other_observer_alias"
            with mock.patch.dict(sys.modules, {alias: main}):
                with self.assertRaisesRegex(D.DumpRefused, "observer exemption used by another module"):
                    fence.audit(bootstrap=True)
                self.assertIs(sys.modules[alias], main)


if __name__ == "__main__":
    unittest.main()
