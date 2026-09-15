"""Installed successor import, task schema and launch-source closure contracts."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import build_terrain_reference as entry
from diadem_launch_gate import gate


class TerrainReferenceIntegrationTests(unittest.TestCase):
    def test_both_record_schemas_allow_every_live_task(self):
        root=Path(gate.__file__).resolve().parents[2]/"schemas"
        for name in ("generator_launch_intent.schema.json","generator_run.schema.json"):
            with self.subTest(name=name):
                schema=json.loads((root/name).read_text("utf-8"))
                values=schema["properties"]["task"]["enum"]
                self.assertEqual(len(values),len(set(values)))
                self.assertEqual(set(values),set(gate.TASKS))
                self.assertIn("TerrainReference",values)

    def test_shim_selects_versioned_successor(self):
        self.assertEqual(entry.PACKAGE.name,"terrain_reference_r2_repair_r1")

    def test_real_successor_loads_bound_private_modules_despite_stale_globals(self):
        stale={name:types.ModuleType(name) for name in
               ("workflow","core","materials","constructive","water","basin_topology")}
        with mock.patch.dict(sys.modules,stale):
            workflow=entry.load_workflow()
            pins=workflow.verify_loaded_sources()
            self.assertEqual(len(pins),8)
            for pin in pins:
                raw=(entry.PACKAGE/pin["name"]).read_bytes()
                self.assertEqual(pin["sha256"],hashlib.sha256(raw).hexdigest())
                self.assertEqual(pin["bytes"],len(raw))
            self.assertEqual(len(workflow.implementation_pins()),20)
            for name,module in workflow._RUNTIME_MODULES.items():
                self.assertEqual(Path(module.__file__).parent,entry.PACKAGE)
                self.assertIsNot(module,stale[Path(name).stem])

    def stub(self,root):
        path=root/"workflow.py"
        path.write_text(
            "from pathlib import Path\nimport hashlib\n"
            "state=[]\n"
            "def verify_loaded_sources():\n"
            " raw=Path(__file__).read_bytes()\n"
            " return ({'name':'workflow.py','bytes':len(raw),"
            "'sha256':hashlib.sha256(raw).hexdigest()},)\n",
            encoding="utf-8",
        )
        return path

    def test_existing_global_workflow_cannot_replace_exact_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.stub(root)
            stale=types.ModuleType("workflow")
            stale.state=["stale"]
            before=list(sys.path)
            with mock.patch.dict(sys.modules,{"workflow":stale}):
                fresh=entry.load_workflow(root)
                self.assertEqual(fresh.state,[])
                self.assertIs(sys.modules["workflow"],stale)
            self.assertEqual(sys.path,before)

    def test_each_load_has_private_workflow_globals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.stub(root)
            first=entry.load_workflow(root)
            first.state.append("changed")
            self.assertEqual(entry.load_workflow(root).state,[])

    def test_executed_bytes_must_match_workflows_own_source_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=self.stub(root)
            different=path.read_bytes()+b"\nstate=['executed unpinned code']\n"
            with mock.patch.object(entry,"_workflow_source",return_value=different):
                with self.assertRaisesRegex(ValueError,"executed bytes differ"):
                    entry.load_workflow(root)

    def test_missing_successor_cannot_fall_back_to_old_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(sys.modules,{"workflow":types.ModuleType("workflow")}):
                with self.assertRaises(FileNotFoundError):
                    entry.load_workflow(Path(temporary))

    def test_launch_source_closure_contains_both_preserved_and_successor_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            generator=root/"06_Generator_System"
            engine=generator/"engine"
            files=[generator/"Run-Generator.ps1",engine/"build_terrain_reference.py",
                   engine/"terrain_reference_r2"/"workflow.py",
                   engine/"terrain_reference_r2_repair_r1"/"workflow.py",
                   engine/"terrain_reference_r2_repair_r1"/"source_binding.py",
                   root/"04_Manifests/Tools/LocalFirst/SafetyControls/INSTALLATION_STATUS.json"]
            for index,path in enumerate(files):
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(str(index),encoding="utf-8")
            actual=gate._first_party_bindings(generator,root)
            names={row["relative_path"] for row in actual}
            self.assertEqual(names,{path.relative_to(root).as_posix() for path in files})
            successor=files[3]
            prior=next(row for row in actual if row["relative_path"]==successor.relative_to(root).as_posix())
            successor.write_text("new code",encoding="utf-8")
            updated=gate._first_party_bindings(generator,root)
            new=next(row for row in updated if row["relative_path"]==prior["relative_path"])
            self.assertNotEqual(prior["sha256"],new["sha256"])


if __name__=="__main__":
    unittest.main()
