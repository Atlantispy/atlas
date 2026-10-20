"""Small stdlib guard fixtures. Never imports an Atlas runtime."""
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ASSEMBLER_SHA = "345d00311f8b7521ed63225054530c1aa2fe2391446d2c236871aa1dd47e4322"


class Adapter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = (HERE / "assemble_r3_plan06.py").read_bytes()
        self.assertEqual(sha256(raw).hexdigest(), ASSEMBLER_SHA)
        spec = importlib.util.spec_from_file_location("fixture_assembler", HERE / "assemble_r3_plan06.py")
        self.a = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.a)
        self.a.R = self.root / "box"
        self.a.G = self.a.R / "geometry-growth-r1"
        self.assets = {"hook": self.a.G / "transforms/plan06_d5_wall_hooks.py"}
        self.assets.update({n: self.a.R / "plan06-d5" / n for n in self.a.PLAN06_D5_NAMES})
        for name, path in self.assets.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture " + name + "\n", encoding="utf8")
        self.doc = {"schema": "atlas.private.plan06-d5-assembly.r1", "selection": "fixture only",
                    "wall_input_sha256": self.a.text_sha("before"),
                    "wall_output_sha256": self.a.text_sha("after"),
                    "assets": {n: self.a.file_sha(p) for n, p in self.assets.items()}}
        self.a.SELECTED = {self.a.norm(p): self.a.file_sha(p) for p in self.assets.values()}
        self.contract = self.root / "contract.json"

    def select(self):
        self.contract.write_text(json.dumps(self.doc), encoding="utf8")
        return self.a.plan06_select_d5(str(self.contract), self.a.file_sha(self.contract))

    def apply(self, sources=None, mutate=False):
        sources = {"atlas_tectonics/integration_wall_measures.py": "before"} if sources is None else sources
        stages = []
        def stage(name, label, fn):
            sources["atlas_tectonics/" + name] = fn(sources["atlas_tectonics/" + name])
            stages.append(label)
        def replace(name, label, text):
            sources["atlas_tectonics/" + name] = text
            stages.append(label)
        def load(name):
            self.assertEqual(name, "plan06_d5_wall_hooks")
            def fn(text):
                if mutate:
                    self.assets["hook"].write_text("changed", encoding="utf8")
                return "after"
            return fn
        self.a.plan06_apply_d5(sources, stage, replace, load)
        return sources, stages

    def test_disabled_without_io(self):
        self.a.R = None
        self.assertIsNone(self.a.plan06_select_d5(None, None))
        self.assertIsNone(self.a.PLAN06_D5)

    def test_partial_options(self):
        with self.assertRaisesRegex(self.a.Refused, "both"):
            self.a.plan06_select_d5(str(self.contract), None)

    def test_contract_pin(self):
        self.contract.write_text("{}", encoding="utf8")
        with self.assertRaisesRegex(self.a.Refused, "pin"):
            self.a.plan06_select_d5(str(self.contract), "0" * 64)

    def test_duplicate_key(self):
        self.contract.write_text('{"schema":"a","schema":"b"}', encoding="utf8")
        with self.assertRaisesRegex(self.a.Refused, "duplicate"):
            self.a.plan06_select_d5(str(self.contract), self.a.file_sha(self.contract))

    def test_missing_asset(self):
        self.assets["hook"].unlink()
        with self.assertRaisesRegex(self.a.Refused, "missing"):
            self.select()

    def test_unselected_asset(self):
        self.a.SELECTED.clear()
        with self.assertRaisesRegex(self.a.Refused, "not selected"):
            self.select()

    def test_changed_asset(self):
        self.assets["hook"].write_text("changed", encoding="utf8")
        with self.assertRaisesRegex(self.a.Refused, "bytes differ"):
            self.select()

    def test_empty_selection(self):
        self.doc["selection"] = ""
        with self.assertRaisesRegex(self.a.Refused, "selection absent"):
            self.select()

    def test_success_has_three_stages_and_exact_modules(self):
        self.select()
        sources, stages = self.apply()
        self.assertEqual(len(stages), 3)
        self.assertEqual(len(sources), 3)
        for name in self.a.PLAN06_D5_NAMES:
            self.assertEqual(sources["atlas_tectonics/" + name].encode(), self.assets[name].read_bytes())

    def test_duplicate_module_refuses(self):
        self.select()
        sources = {"atlas_tectonics/integration_wall_measures.py": "before",
                   "atlas_tectonics/integration_exact_twin.py": "existing"}
        with self.assertRaisesRegex(self.a.Refused, "already present"):
            self.apply(sources)

    def test_wrong_input(self):
        self.select()
        with self.assertRaisesRegex(self.a.Refused, "wall input"):
            self.apply({"atlas_tectonics/integration_wall_measures.py": "wrong"})

    def test_wrong_output(self):
        self.doc["wall_output_sha256"] = "0" * 64
        self.select()
        with self.assertRaisesRegex(self.a.Refused, "wall output"):
            self.apply()

    def test_changed_after_selection(self):
        self.select()
        self.assets["hook"].write_text("changed", encoding="utf8")
        with self.assertRaisesRegex(self.a.Refused, "before composition"):
            self.apply()

    def test_finality_detects_mutation(self):
        self.select()
        with self.assertRaisesRegex(self.a.Refused, "changed during"):
            self.apply(mutate=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
