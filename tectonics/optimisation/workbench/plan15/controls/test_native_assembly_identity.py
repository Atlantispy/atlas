"""UNEXECUTED source-only controls for the prospective r17 pure policy.

No live process, MPFR, H3, JIT, pickle or candidate import occurs at import time.
Running these controls requires a fresh exact GO.  The r13 text is an immutable
grammar template only: the two rebasing receipts below are independent synthetic
receiver fixtures, not recovered mapping proof or qualification of old results.
Unchanged r11 controls/evidence remain separate and are not automatically rerun.
"""

import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import types
import unittest


HERE = Path(__file__).resolve().parent
POLICY_PATH = HERE / "assembly_identity.py"
TEMPLATE = HERE.parent / "r13" / "candidate-builds-r1" / "probe0"
TEMPLATE_PINS = {
    "result.json": "0caaf4f52203ef952207972590e818bc5cf2331c83f0c934c594ab7bd96a5639",
    "assembly.asm": "a63dbe8c106b5757445ff9ed0178ced38b14633545856229cb3463160140accf",
}
MPFR_PATH = (
    r"C:\Users\LOCAL_USER\Documents\Codex\2026-09-02\the-diadem-local-tasks-10"
    r"\.r44-env\Lib\site-packages\gmpy2.libs\libmpfr-6.dll"
)
MPFR_SHA256 = "b81a548eb7a23d4e3acbe296f1eff077a0b284617a2c1cc53a1ccdb0637b52b8"
# Saved r13 offsets are grammar-fixture inputs only.  Production must obtain
# size/RVAs from pinned PE bytes and actual mapping from its retained handle.
SYNTHETIC_RVAS = {
    "mpfr_mul": 0x766E0, "mpfr_add": 0x71C90, "mpfr_set": 0x11880,
    "mpfr_less_p": 0x2780, "mpfr_greater_p": 0x2700, "mpfr_lessequal_p": 0x27C0,
    "mpfr_regular_p": 0x43120, "mpfr_sgn": 0x2AC70, "mpfr_get_exp": 0x5940,
    "mpfr_flags_save": 0x7190F, "mpfr_flags_clear": 0x718BC,
    "mpfr_flags_restore": 0x71929, "mpfr_get_emin": 0x71870, "mpfr_get_emax": 0x71896,
}
SYNTHETIC_SIZE = 0x100000  # Mock metadata, not the actual DLL SizeOfImage.
TEMPLATE_BASE = 140724463271936
GLOBAL = re.compile(r"numba\.dynamic\.globals\.([1-9a-f][0-9a-f]{0,15})(\.[1-9][0-9]*)?")


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def load_policy():
    """Load only on an authorised test invocation, never during preparation."""
    source = POLICY_PATH.read_bytes()
    tree = ast.parse(source, filename=str(POLICY_PATH))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name not in {"hashlib", "json", "re"} for alias in node.names):
                raise AssertionError("unexpected_policy_import")
        elif isinstance(node, ast.ImportFrom):
            raise AssertionError("unexpected_policy_from_import")
    module = types.ModuleType("plan15_r17_native_assembly_controls")
    module.__file__ = str(POLICY_PATH)
    exec(compile(source, str(POLICY_PATH), "exec"), module.__dict__)
    module._POLICY_SOURCE_SHA256 = digest(source)
    return module


def synthetic_binding(pid, creation, base):
    """Independent mock receiver metadata/mapping, not worker-map inference."""
    return {
        "schema": "plan15.native-binding.r1", "pid": pid, "creation_filetime": creation,
        "module": {"path": MPFR_PATH, "sha256": MPFR_SHA256,
                   "base": base, "size": SYNTHETIC_SIZE},
        "exports": {name: {"address": base + rva, "rva": rva}
                    for name, rva in SYNTHETIC_RVAS.items()},
    }


def fixture(policy_sha256, pid, creation, base):
    """Retain saved grammar, construct two separately allocated mock contexts."""
    blobs = {name: (TEMPLATE / name).read_bytes() for name in TEMPLATE_PINS}
    for name, expected in TEMPLATE_PINS.items():
        if digest(blobs[name]) != expected:
            raise AssertionError("template_pin_mismatch:" + name)
    saved = json.loads(blobs["result.json"].decode("utf-8"))
    original = blobs["assembly.asm"].decode("utf-8")
    known = {TEMPLATE_BASE + rva: rva for rva in SYNTHETIC_RVAS.values()}

    def substitute(match):
        old = int(match.group(1), 16)
        if old not in known:
            raise AssertionError("unrecognised_template_global")
        return "numba.dynamic.globals." + format(base + known[old], "x") + (match.group(2) or "")

    lines = original.splitlines(keepends=True)
    replaced = []
    for index, line in enumerate(lines):
        if line.startswith("\t.quad\t") and index and GLOBAL.fullmatch(lines[index - 1].rstrip(":\n")):
            old = int(line[len("\t.quad\t"):].strip())
            if old not in known:
                raise AssertionError("unrecognised_template_pointer")
            replaced.append("\t.quad\t" + str(base + known[old]) + "\n")
        else:
            replaced.append(GLOBAL.sub(substitute, line))
    assembly = "".join(replaced)
    if len(assembly) != len(original):
        raise AssertionError("synthetic_fixture_changed_width")
    signatures = copy.deepcopy(saved["signatures"])
    for signature in signatures:
        signature["sha256"] = digest(assembly[signature["byte_start"]:signature["byte_end"]].encode("ascii"))
    common = copy.deepcopy(saved["raw_worker_payload"]["candidate"]["assembly_observation"]["evidence"]["context"])
    common["process_id"] = pid
    common["build"]["compiled_assembly_sha256"] = digest(assembly.encode("ascii"))
    pins = common["source_pins"]
    for path in list(pins):
        if path.replace("\\", "/").rsplit("/", 1)[-1] == "assembly_identity.py":
            del pins[path]
    pins[str(POLICY_PATH)] = policy_sha256
    worker, expected = copy.deepcopy(common), copy.deepcopy(common)
    worker["native_binding"] = synthetic_binding(pid, creation, base)
    expected["native_binding"] = synthetic_binding(pid, creation, base)
    return assembly, signatures, worker, expected


class NativeAssemblyControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy()
        cls.fixtures = [
            fixture(cls.policy._POLICY_SOURCE_SHA256, 81001, 132000000000000001, 0x7FFA10000000),
            fixture(cls.policy._POLICY_SOURCE_SHA256, 81002, 132000000000000002, 0x7FFA10200000),
        ]
        cls.records = [cls.policy.observe(*item[:3]) for item in cls.fixtures]

    def refused(self, function, *args):
        with self.assertRaises(self.policy.AssemblyIdentityError) as caught:
            function(*args)
        self.assertIs(type(caught.exception.code), str)
        self.assertTrue(caught.exception.code)
        return caught.exception.code

    def changed(self, old, new):
        assembly, signatures, context, expected = copy.deepcopy(self.fixtures[0])
        self.assertIn(old, assembly)
        self.assertEqual(len(old), len(new))
        assembly = assembly.replace(old, new, 1)
        sha = digest(assembly.encode("ascii"))
        context["build"]["compiled_assembly_sha256"] = sha
        expected["build"]["compiled_assembly_sha256"] = sha
        for signature in signatures:
            signature["sha256"] = digest(assembly[signature["byte_start"]:signature["byte_end"]].encode("ascii"))
        return assembly, signatures, context, expected

    def different_or_refused(self, old, new):
        assembly, signatures, context, expected = self.changed(old, new)
        try:
            record = self.policy.observe(assembly, signatures, context)
        except self.policy.AssemblyIdentityError:
            return
        self.assertNotEqual(self.policy.comparison_identity(record, expected),
                            self.policy.comparison_identity(self.records[0], self.fixtures[0][3]))
        self.assertIn(new, record["raw_text"])

    def test_independently_supplied_rebasing_has_equal_scoped_identity_and_strict_difference(self):
        identities = [self.policy.comparison_identity(record, item[3])
                      for record, item in zip(self.records, self.fixtures, strict=True)]
        self.assertEqual(identities[0], identities[1])
        self.assertNotEqual(self.records[0]["raw_sha256"], self.records[1]["raw_sha256"])
        self.assertEqual([unit["comparison_sha256"] for unit in self.records[0]["units"]],
                         [unit["comparison_sha256"] for unit in self.records[1]["units"]])
        for record, item, identity in zip(self.records, self.fixtures, identities, strict=True):
            self.assertEqual(record["raw_text"], item[0])
            self.assertEqual(record["context"]["native_binding"], item[3]["native_binding"])
            self.assertIs(record["scientific_eligibility"], False)
            self.assertEqual(record["equivalence_claim"], "NONE")
            retained = identity["context"]["native_binding"]
            self.assertEqual(set(retained), {"schema", "module", "exports"})
            self.assertEqual(retained["module"], {"path": MPFR_PATH, "sha256": MPFR_SHA256,
                                                  "size": SYNTHETIC_SIZE})
            self.assertEqual(retained["exports"], {name: {"rva": rva} for name, rva in SYNTHETIC_RVAS.items()})

    def test_maps_retain_every_actual_slot_export_instance_and_consumer_link(self):
        record = self.records[0]
        changes = [item for item in record["transformations"] if item["kind"].startswith("mpfr-export-")]
        self.assertEqual(sum(item["kind"] == "mpfr-export-address" for item in changes), 286)
        self.assertEqual(sum(item["kind"] == "mpfr-export-pointer" for item in changes), 54)
        self.assertEqual({item["function_index"] for item in changes}, {0, 1, 2, 3})
        for item in changes:
            self.assertEqual(record["raw_text"][item["byte_start"]:item["byte_end"]], item["before"])
            target = record["context"]["native_binding"]["exports"][item["export_name"]]
            self.assertEqual(item["export_rva"], target["rva"])
            self.assertEqual(item["after"], item["export_name"] + "_rva_" + format(target["rva"], "x"))
            matched = GLOBAL.fullmatch(item["symbol"])
            self.assertIsNotNone(matched)
            self.assertEqual(int(matched.group(1), 16), target["address"])
            self.assertEqual(item["instance"], matched.group(2) or "")
        consumers = [consumer for unit in record["units"] for consumer in unit["consumer_evidence"]
                     if consumer["consumer"] == "pinned-mpfr-function-address"]
        self.assertEqual(len(consumers), 54)
        for consumer in consumers:
            self.assertEqual(record["raw_text"][consumer["byte_start"]:consumer["byte_end"]], consumer["raw_text"])
            self.assertIn("\t.quad\t", consumer["raw_text"])
            self.assertTrue(consumer["references"])
            for reference in consumer["references"]:
                self.assertEqual(record["raw_text"][reference["byte_start"]:reference["byte_end"]], reference["raw_text"])
                self.assertIn("$" + consumer["symbol"] + ", %", reference["raw_text"])

    def test_receiver_context_is_mandatory_and_worker_receipt_cannot_authorise_itself(self):
        with self.assertRaises(TypeError):
            self.policy.comparison_identity(self.records[0])
        self.refused(self.policy.comparison_identity, self.records[0], None)
        forged = copy.deepcopy(self.records[0])
        forged["context"]["native_binding"]["creation_filetime"] += 1
        self.assertEqual(self.refused(self.policy.validate_evidence, forged, self.fixtures[0][3]), "CONTEXT_MISMATCH")

    def test_in_image_target_without_pinned_receiver_export_proof_is_refused(self):
        assembly, signatures, worker, expected = copy.deepcopy(self.fixtures[0])
        # This unused named target stays in-image and is internally consistent.
        # Only the independent pinned-byte receiver metadata can authorise its
        # RVA/code/export meaning; a forged worker claim cannot substitute it.
        target = worker["native_binding"]["exports"]["mpfr_flags_clear"]
        target["rva"] += 1
        target["address"] += 1
        record = self.policy.observe(assembly, signatures, worker)
        self.assertEqual(self.refused(self.policy.validate_evidence, record, expected), "CONTEXT_MISMATCH")

    def test_missing_forged_process_proof_and_closed_receipt_faults_are_refused(self):
        for fault in ("missing", "unknown", "pid", "creation", "module_bool", "size_bool",
                      "zero_size", "address_bool", "rva_bool", "outside", "address_mismatch",
                      "missing_export", "extra_export", "forwarded", "alias", "relative_path"):
            with self.subTest(fault=fault):
                assembly, signatures, context, _ = copy.deepcopy(self.fixtures[0])
                binding = context["native_binding"]
                target = binding["exports"]["mpfr_mul"]
                if fault == "missing":
                    del context["native_binding"]
                elif fault == "unknown":
                    binding["authority"] = "worker"
                elif fault == "pid":
                    binding["pid"] += 1
                elif fault == "creation":
                    binding["creation_filetime"] = True
                elif fault == "module_bool":
                    binding["module"]["base"] = True
                elif fault == "size_bool":
                    binding["module"]["size"] = True
                elif fault == "zero_size":
                    binding["module"]["size"] = 0
                elif fault == "address_bool":
                    target["address"] = True
                elif fault == "rva_bool":
                    target["rva"] = True
                elif fault == "outside":
                    target["rva"] = binding["module"]["size"]
                    target["address"] = binding["module"]["base"] + target["rva"]
                elif fault == "address_mismatch":
                    target["address"] += 1
                elif fault == "missing_export":
                    del binding["exports"]["mpfr_get_emax"]
                elif fault == "extra_export":
                    binding["exports"]["mpfr_unknown"] = dict(target)
                elif fault == "forwarded":
                    target["forwarded"] = True
                elif fault == "alias":
                    binding["exports"]["mpfr_add"] = dict(target)
                else:
                    binding["module"]["path"] = "libmpfr-6.dll"
                self.refused(self.policy.observe, assembly, signatures, context)

    def test_expected_module_path_sha_size_rva_process_and_creation_mismatch_refuse(self):
        for fault in ("path", "sha", "size", "rva", "process", "creation", "base"):
            with self.subTest(fault=fault):
                expected = copy.deepcopy(self.fixtures[0][3])
                binding = expected["native_binding"]
                if fault == "path":
                    binding["module"]["path"] = MPFR_PATH.replace("libmpfr", "Libmpfr")
                elif fault == "sha":
                    binding["module"]["sha256"] = "0" * 64
                elif fault == "size":
                    binding["module"]["size"] += 4096
                elif fault == "rva":
                    binding["exports"]["mpfr_mul"]["rva"] += 1
                    binding["exports"]["mpfr_mul"]["address"] += 1
                elif fault == "process":
                    expected["process_id"] += 1
                    binding["pid"] += 1
                elif fault == "creation":
                    binding["creation_filetime"] += 1
                else:
                    binding["module"]["base"] += 0x10000
                    for target in binding["exports"].values():
                        target["address"] += 0x10000
                self.refused(self.policy.validate_evidence, self.records[0], expected)

    def test_unknown_global_pointer_mismatch_unsupported_syntax_and_instance_link_refuse(self):
        assembly = self.fixtures[0][0]
        symbol = GLOBAL.search(assembly).group(0)
        target = self.fixtures[0][2]["native_binding"]["exports"]["mpfr_regular_p"]["address"]
        controls = [
            (symbol, symbol[:-1] + "1"),
            ("\t.quad\t" + str(target), "\t.quad\t" + str(target + 1)),
            ("\t.weak\t" + symbol, "\t.glob\t" + symbol),
            ("\tmovabsq\t$" + symbol + ", %r15", "\tmovabsq\t$" + symbol + ", %r14"),
            (symbol + ".1:", symbol + ".2:"),
        ]
        for old, new in controls:
            with self.subTest(old=old):
                self.refused(self.policy.observe, *self.changed(old, new)[:3])

    def test_changed_link_to_other_proven_export_is_refused_or_remains_distinct(self):
        assembly = self.fixtures[0][0]
        first = GLOBAL.search(assembly).group(0)
        other = "numba.dynamic.globals." + format(self.fixtures[0][2]["native_binding"]["exports"]["mpfr_mul"]["address"], "x")
        self.different_or_refused(first, other)

    def test_outside_slot_instruction_register_control_flow_and_data_changes_remain_exact(self):
        controls = [
            ("\tpushq\t%r15", "\tpushq\t%r14"),
            ("\tsubq\t$104, %rsp", "\tsubq\t$105, %rsp"),
            ("\tcallq\t*%rax", "\tcallq\t*%rbx"),
            ("\tjne\t", "\tje \t"),
            ("missing Environment:", "missing Environmenx:"),
            ("\\214\\005numpy", "\\214\\005numpz"),
            ("\t.quad\t0\n", "\t.quad\t1\n"),
        ]
        for old, new in controls:
            with self.subTest(old=old):
                self.different_or_refused(old, new)

    def test_consumer_transform_and_raw_tampering_cannot_survive_reconstruction(self):
        for fault in ("transform", "target", "consumer", "reference", "raw"):
            with self.subTest(fault=fault):
                record = copy.deepcopy(self.records[0])
                change = next(item for item in record["transformations"] if item["kind"] == "mpfr-export-address")
                consumer = next(item for unit in record["units"] for item in unit["consumer_evidence"]
                                if item["consumer"] == "pinned-mpfr-function-address")
                if fault == "transform":
                    change["before"] = "0"
                elif fault == "target":
                    change["export_rva"] += 1
                elif fault == "consumer":
                    consumer["raw_text"] = ""
                elif fault == "reference":
                    consumer["references"][0]["byte_start"] += 1
                else:
                    record["raw_sha256"] = "0" * 64
                self.refused(self.policy.validate_evidence, record, self.fixtures[0][3])

    def test_exact_cache_guard_includes_process_creation_base_and_all_binding_bytes(self):
        _, signatures, context, _ = copy.deepcopy(self.fixtures[0])
        original = self.policy.source_signature_key(context, signatures)
        for fault in ("creation", "base", "rva"):
            with self.subTest(fault=fault):
                changed = copy.deepcopy(context)
                binding = changed["native_binding"]
                if fault == "creation":
                    binding["creation_filetime"] += 1
                elif fault == "base":
                    binding["module"]["base"] += 0x10000
                    for target in binding["exports"].values():
                        target["address"] += 0x10000
                else:
                    binding["exports"]["mpfr_mul"]["rva"] += 1
                    binding["exports"]["mpfr_mul"]["address"] += 1
                self.assertNotEqual(original, self.policy.source_signature_key(changed, signatures))


if __name__ == "__main__":
    unittest.main(verbosity=2)
