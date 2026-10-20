"""Bounded synthetic source/bootstrap controls; no Atlas imports or subprocesses."""
from copy import deepcopy
from hashlib import sha256
import importlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("_native_entry_controls", HERE / "bootstrap_native.py")
B = importlib.util.module_from_spec(_SPEC)
_RAW = (HERE / 'bootstrap_native.py').read_bytes()
assert sha256(_RAW).hexdigest() == 'f5009a2d9907a4835197714a86587ea4390a7d75a7eb830ca62311c594cc71f5'
exec(compile(_RAW, str(HERE / 'bootstrap_native.py'), 'exec', dont_inherit=True), B.__dict__)
LEAF = "fixture_native_leaf"


class BootstrapControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-entry-fixture-", dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "src").mkdir()
        (self.root / "helpers").mkdir()
        self.source = self.root / "src/example.py"
        self.source.write_text("VALUE = 1\n", encoding="utf8")
        self.leaf = self.root / "helpers" / (LEAF + ".py")
        self.leaf.write_text("VALUE = 7\n", encoding="utf8")
        self.entry = self.root / "helpers" / B.ENTRY_NAME
        self.entry.write_text("import fixture_native_leaf\nVALUE = fixture_native_leaf.VALUE\n", encoding="utf8")
        self.composition = self.root / "composition.json"
        self.saved = {name: sys.modules.get(name) for name in (LEAF, Path(B.ENTRY_NAME).stem)}
        self.addCleanup(self.restore_helpers)
        self.write_composition()

    def restore_helpers(self):
        for name, module in self.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def write_composition(self):
        row = {"root": str(self.root),
            "outputs": {"example.py": sha256(self.source.read_bytes()).hexdigest()},
            "helpers": {path.name: sha256(path.read_bytes()).hexdigest() for path in (self.entry, self.leaf)}}
        self.composition.write_text(json.dumps(row, sort_keys=True), encoding="utf8")
        self.pin = sha256(self.composition.read_bytes()).hexdigest()
        return row

    def closure(self):
        return B.validate_composition(self.composition, self.pin, expected_root=self.root, expected_counts=(1, 2))

    def valid_runtime(self):
        return {"executable": str(B.REAL_PYTHON), "dont_write_bytecode": True, "no_user_site": True,
            "safe_path": True, "hash_randomization": 0, "ignore_environment": False, "isolated": False,
            "trace": False, "profile": False, "tracemalloc": False, "monitoring": False, "xoptions": {},
            "environment": dict(B.PYTHON_ENV, **B.THREAD_ENV)}

    def test_checked_sibling_chain_without_import_path_change(self):
        before = list(sys.path)
        with mock.patch.object(B.PinnedLoader, "get_data", side_effect=AssertionError("bytecode path used")):
            module = B.execute_composition(self.closure(), ["--synthetic"])
        self.assertEqual(module.VALUE, 7)
        self.assertEqual(sys.path, before)
        self.assertIsNone(importlib.machinery.PathFinder.find_spec(LEAF, before))

    def test_wrong_composition_digest_refused(self):
        with self.assertRaisesRegex(B.BootstrapRefused, "source digest differs"):
            B.validate_composition(self.composition, "0" * 64, expected_root=self.root, expected_counts=(1, 2))

    def test_wrong_declared_helper_digest_refused(self):
        row = self.write_composition()
        row["helpers"][self.leaf.name] = "0" * 64
        self.composition.write_text(json.dumps(row), encoding="utf8")
        self.pin = sha256(self.composition.read_bytes()).hexdigest()
        with self.assertRaisesRegex(B.BootstrapRefused, "inventory differs"):
            self.closure()

    def test_foreign_preloaded_helper_refused(self):
        sys.modules[LEAF] = SimpleNamespace(__file__=str(self.root / "foreign.py"))
        with self.assertRaisesRegex(B.BootstrapRefused, "preloaded same-name"):
            B.execute_composition(self.closure(), [])

    def test_missing_and_extra_helper_inventory_refused(self):
        self.leaf.unlink()
        with self.assertRaisesRegex(B.BootstrapRefused, "inventory differs"):
            self.closure()
        self.leaf.write_text("VALUE = 7\n", encoding="utf8")
        (self.root / "helpers/undeclared.py").write_text("VALUE = 9\n", encoding="utf8")
        with self.assertRaisesRegex(B.BootstrapRefused, "inventory differs"):
            self.closure()

    def test_undeclared_helper_is_not_resolved_from_directory(self):
        self.entry.write_text("import fixture_native_undeclared\n", encoding="utf8")
        self.write_composition()
        with self.assertRaises(ModuleNotFoundError):
            B.execute_composition(self.closure(), [])

    def test_linked_file_and_ancestor_refused(self):
        original_lstat = Path.lstat
        for linked in (self.leaf, self.root):
            for mode, attributes in ((stat.S_IFLNK, 0), (stat.S_IFREG, 0x400)):
                def substitute(path, *args, **kwargs):
                    info = original_lstat(path, *args, **kwargs)
                    return SimpleNamespace(st_mode=mode, st_file_attributes=attributes) if path == linked else info
                with self.subTest(linked=str(linked), attributes=attributes), mock.patch.object(Path, "lstat", substitute):
                    with self.assertRaisesRegex(B.BootstrapRefused, "linked or reparse"):
                        B.ordinary(self.leaf)

    def test_source_changed_during_helper_load_refused(self):
        get_code = B.PinnedLoader.get_code
        def mutate(loader, fullname):
            code = get_code(loader, fullname)
            if fullname == LEAF:
                self.leaf.write_text("VALUE = 8\n", encoding="utf8")
            return code
        with mock.patch.object(B.PinnedLoader, "get_code", mutate):
            with self.assertRaises(BaseExceptionGroup):
                B.execute_composition(self.closure(), [])

    def test_complete_source_finality_after_success(self):
        self.entry.write_text("from pathlib import Path\nPath(" + repr(str(self.source)) +
                              ").write_text('VALUE = 2\\n', encoding='utf8')\n", encoding="utf8")
        self.write_composition()
        with self.assertRaisesRegex(B.BootstrapRefused, "inventory differs: src"):
            B.execute_composition(self.closure(), [])

    def test_helper_spec_origin_changed_before_finalisation_refused(self):
        self.entry.write_text("import fixture_native_leaf\nfixture_native_leaf.__spec__.origin = " +
                              repr(str(self.source)) + "\n", encoding="utf8")
        self.write_composition()
        with self.assertRaisesRegex(B.BootstrapRefused, "spec origin differs"):
            B.execute_composition(self.closure(), [])

    def test_original_exception_and_finality_failure_both_survive(self):
        self.entry.write_text("from pathlib import Path\nPath(" + repr(str(self.source)) +
            ").write_text('VALUE = 2\\n', encoding='utf8')\nraise SystemExit(0)\n", encoding="utf8")
        self.write_composition()
        with self.assertRaises(BaseExceptionGroup) as caught:
            B.execute_composition(self.closure(), [])
        self.assertIsInstance(caught.exception.exceptions[0], SystemExit)
        self.assertEqual(caught.exception.exceptions[0].code, 0)
        self.assertIsInstance(caught.exception.exceptions[1], B.BootstrapRefused)

    def test_main_argv_and_finder_restoration(self):
        self.entry.write_text("import sys\nSEEN = (__name__, __file__, list(sys.argv))\n", encoding="utf8")
        self.write_composition()
        before_main, before_argv, before_meta = sys.modules["__main__"], sys.argv, list(sys.meta_path)
        module = B.execute_composition(self.closure(), ["--profile", "a path with spaces"])
        self.assertEqual(module.SEEN, ("__main__", str(self.entry), [str(self.entry), "--profile", "a path with spaces"]))
        self.assertIs(sys.modules["__main__"], before_main)
        self.assertIs(sys.argv, before_argv)
        self.assertEqual(sys.meta_path, before_meta)

    def test_main_argv_and_finder_restored_after_error(self):
        self.entry.write_text("raise RuntimeError('synthetic native failure')\n", encoding="utf8")
        self.write_composition()
        before_main, before_argv, before_meta = sys.modules["__main__"], sys.argv, list(sys.meta_path)
        with self.assertRaisesRegex(RuntimeError, "synthetic native failure"):
            B.execute_composition(self.closure(), [])
        self.assertIs(sys.modules["__main__"], before_main)
        self.assertIs(sys.argv, before_argv)
        self.assertEqual(sys.meta_path, before_meta)

    def test_native_path_and_finder_mutations_refuse_and_restore_state(self):
        for change, diagnostic in (("sys.path.append('foreign-path')", "changed sys.path"),
                                   ("sys.meta_path.append(object())", "finder set was changed")):
            self.entry.write_text("import sys\n" + change + "\n", encoding="utf8")
            self.write_composition()
            before_path, before_meta = list(sys.path), list(sys.meta_path)
            with self.subTest(change=change), self.assertRaisesRegex(B.BootstrapRefused, diagnostic):
                B.execute_composition(self.closure(), [])
            self.assertEqual(sys.path, before_path)
            self.assertEqual(sys.meta_path, before_meta)

    def test_runtime_seed_flags_and_instrumentation_refusals(self):
        B.validate_runtime(self.valid_runtime())
        for field, value in (("trace", True), ("profile", True), ("monitoring", True), ("tracemalloc", True),
            ("safe_path", False), ("no_user_site", False), ("dont_write_bytecode", False),
            ("hash_randomization", 1), ("ignore_environment", True), ("isolated", True), ("xoptions", {"importtime": True})):
            state = deepcopy(self.valid_runtime())
            state[field] = value
            with self.subTest(field=field), self.assertRaises(B.BootstrapRefused):
                B.validate_runtime(state)

    def test_unset_nonzero_seed_and_import_hook_environment_refused(self):
        for name, value in (("PYTHONHASHSEED", None), ("PYTHONHASHSEED", "1"), ("PYTHONPATH", ""),
                            ("PYTHONHOME", str(self.root)), ("COVERAGE_PROCESS_START", ""),
                            ("ATLAS_INITIAL_MEASUREMENT_SEED", ""), ("ATLAS_DEV_TIMING", ""),
                            ("ATLAS_DEV_STAGE_TIMING", "1")):
            state = self.valid_runtime()
            if value is None:
                del state["environment"][name]
            else:
                state["environment"][name] = value
            with self.subTest(name=name, value=value), self.assertRaises(B.BootstrapRefused):
                B.validate_runtime(state)

    def test_cli_requires_boundary_and_fixed_root(self):
        with self.assertRaisesRegex(B.BootstrapRefused, "explicit -- boundary"):
            B.main(["--composition", str(self.composition), "--composition-sha256", self.pin])
        with mock.patch.object(B, "validate_runtime"), mock.patch.object(B, "validate_composition") as validate:
            validate.side_effect = B.BootstrapRefused("synthetic fixed-root stop")
            with self.assertRaisesRegex(B.BootstrapRefused, "fixed-root stop"):
                B.main(["--composition", str(self.composition), "--composition-sha256", self.pin, "--", "--stage", "root"])
        self.assertEqual(validate.call_args.kwargs, {"expected_root": B.REAL_ROOT, "expected_counts": (239, 389)})


if __name__ == "__main__":
    unittest.main()
