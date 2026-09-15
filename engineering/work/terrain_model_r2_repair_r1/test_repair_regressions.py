"""Independent regressions for the four audited foundation defects.

Only synthetic states and temporary source/output copies are used.
"""
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import core
import fixtures
import workflow as w


def peat():
    return next(r for r in fixtures.suite() if r["scenario_id"] == "organic_accumulation_compaction")


class PeriodicGradientRepairTests(unittest.TestCase):
    def scene(self, cols=8):
        g = core.Grid(4, cols, 1., 1.)
        bed = tuple(.2*math.sin(2*math.pi*c/cols)+.1*r
                    for r in range(g.rows) for c in range(cols))
        return core.State(g, bed, (1.,)*g.size, (0.,)*g.size, 2700., 2700.)

    def roll(self, values, grid, offset):
        return tuple(values[r*grid.cols+(c-offset)%grid.cols]
                     for r in range(grid.rows) for c in range(grid.cols))

    def test_nonlinear_periodic_evolution_is_cyclically_equivariant(self):
        s = self.scene(); g = s.grid
        k = tuple(.01*(1+i%3*.1) for i in range(g.size))
        critical = tuple(.9+i%2*.1 for i in range(g.size))
        s = replace(s, porosity=tuple(.1*(i%2) for i in range(g.size)))
        result, _ = core.hillslope_step(s, k, .1, critical, periodic_x=True)
        for offset in range(1, g.cols):
            shifted = replace(s, bedrock_m=self.roll(s.bedrock_m,g,offset),
                mobile_solid_m3=self.roll(s.mobile_solid_m3,g,offset),
                porosity=self.roll(s.porosity,g,offset))
            actual, _ = core.hillslope_step(shifted,self.roll(k,g,offset),.1,
                self.roll(critical,g,offset),periodic_x=True)
            for expected, got in zip(self.roll(result.mobile_solid_m3,g,offset),actual.mobile_solid_m3):
                self.assertLessEqual(abs(expected-got),8*math.ulp(expected))

    def test_periodic_derivative_uses_both_wrapped_neighbours(self):
        g = core.Grid(2, 4, 2., 3.)
        z = [0.,1.,3.,2.,0.,1.,3.,2.]
        d = core.gradients(g,z,periodic_x=True)
        self.assertEqual(d["dz_dx"],[-.25,.75,.25,-.75]*2)
        self.assertEqual(d["dz_dy"],[0.]*8)

    def test_two_column_periodic_tangential_derivative_is_centred(self):
        g = core.Grid(2,2,1.,1.)
        d = core.gradients(g,[1.,2.,2.,3.],periodic_x=True)
        self.assertEqual(d["dz_dx"],[0.]*4)
        self.assertEqual(d["dz_dy"],[1.]*4)

    def test_gradient_periodicity_requires_bool(self):
        s = self.scene()
        with self.assertRaisesRegex(ValueError,"Boolean"):
            core.gradients(s.grid,s.surface_m,periodic_x=1)


class CompactionHistoryRepairTests(unittest.TestCase):
    def test_duplicate_loading_is_rejected(self):
        recipe = peat()
        recipe["operations"].append(deepcopy(recipe["operations"][-1]))
        before = w.canonical(recipe)
        with self.assertRaisesRegex(ValueError,"previous effective stress"):
            w.execute(recipe)
        self.assertEqual(w.canonical(recipe),before)

    def test_consistent_loading_matches_single_endpoint(self):
        recipe = peat()
        second = deepcopy(recipe["operations"][-1])
        second.update(effective_stress_before_pa=[2000.]*4,effective_stress_after_pa=[4000.]*4)
        recipe["operations"].append(second)
        result = w.execute(recipe)
        direct = peat(); direct["operations"][-1]["effective_stress_after_pa"]=[4000.]*4
        oracle = w.execute(direct)
        layer = result["auxiliary_layers"]["organic"]
        self.assertEqual(layer["effective_stress_pa"],[4000.]*4)
        self.assertEqual(layer["compaction_branch"],"monotonic_virgin")
        for a,b in zip(layer["void_ratio"],oracle["auxiliary_layers"]["organic"]["void_ratio"]):
            self.assertLessEqual(abs(a-b),2*math.ulp(b))

    def test_unchanged_pressure_cannot_compact_again(self):
        recipe = peat(); original=w.execute(recipe)
        second=deepcopy(recipe["operations"][-1])
        second["effective_stress_before_pa"]=[2000.]*4
        recipe["operations"].append(second)
        result=w.execute(recipe)
        self.assertEqual(result["state"],original["state"])
        self.assertTrue(all(t["settlement_m"]==0 for t in result["operations"][-1]["transfers"]))

    def test_one_cell_stress_reset_and_parameter_change_reject(self):
        for change in ("stress","parameters"):
            recipe=peat(); second=deepcopy(recipe["operations"][-1])
            second.update(effective_stress_before_pa=[2000.]*4,effective_stress_after_pa=[4000.]*4)
            if change=="stress": second["effective_stress_before_pa"][2]=1000.
            else: second["parameters"]["compression_index"]*=2
            recipe["operations"].append(second)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,"compaction"):
                w.execute(recipe)

    def test_organic_continuation_preserves_stress_history(self):
        recipe=peat(); layer=w.execute(recipe)["auxiliary_layers"]["organic"]
        organic=deepcopy(recipe["operations"][0]); organic["duration_years"]=0.
        organic["external_water_m3"]=[0.]*4
        for key in ("organic_kg","mineral_kg","void_ratio"): organic[key]=layer[key]
        recipe["operations"].append(organic)
        result=w.execute(recipe)
        self.assertEqual(result["auxiliary_layers"]["organic"]["effective_stress_pa"],[2000.]*4)
        recipe["operations"].append(deepcopy(recipe["operations"][1]))
        with self.assertRaisesRegex(ValueError,"previous effective stress"):
            w.execute(recipe)

    def test_json_recovery_retains_stress_and_exact_result(self):
        for interrupt in ("after_products","after_receipt"):
            with self.subTest(interrupt=interrupt),tempfile.TemporaryDirectory() as scratch:
                root=Path(scratch); here=root/"work"/"terrain_model_r2_repair_r1"
                here.mkdir(parents=True); (here/"fixture.py").write_bytes(b"# temporary IO identity fixture")
                recipe=peat(); source=root/"recipe.json"; source.write_bytes(w.canonical(recipe))
                output=root/"outputs"/"terrain-model-r2-repair-r1"/"peat"
                with patch.object(w,"HERE",here):
                    with self.assertRaisesRegex(RuntimeError,"injected interruption"):
                        w.run(source,output,interrupt_at=interrupt)
                    self.assertFalse(output.exists())
                    w.run(source,output,resume=True)
                    result=w.read_json(output/"RESULT.json")
                    self.assertEqual(w.canonical(result),w.canonical(w.execute(recipe)))
                    self.assertEqual(result["auxiliary_layers"]["organic"]["effective_stress_pa"],[2000.]*4)
                    self.assertEqual(w.run(source,output,resume=True)["status"],"VERIFIED_REUSE")


class ImportedSourceRepairTests(unittest.TestCase):
    def probe(self, body):
        with tempfile.TemporaryDirectory(prefix="terrain-repair-import-") as scratch:
            root=Path(scratch); package=root/"work"/"terrain_model_r2_repair_r1"
            package.mkdir(parents=True)
            for name in (*w._binding.RUNTIME_DEPENDENCIES,"source_binding.py","workflow.py","NUMERICAL_CONTRACT.json"):
                shutil.copyfile(Path(w.__file__).parent/name,package/name)
            recipe=next(r for r in fixtures.suite() if r["scenario_id"]=="gentle_plain_zero_forcing")
            recipe["operations"][0]["steps"]=1
            source=root/"recipe.json"; source.write_bytes(w.canonical(recipe))
            setup=("import hashlib,json,sys,types\nfrom pathlib import Path\n"
                   f"root=Path({str(root)!r}); package=Path({str(package)!r})\n"
                   "sys.path.insert(0,str(package))\n"
                   "output=root/'outputs'/'terrain-model-r2-repair-r1'/'run'\n")
            completed=subprocess.run([sys.executable,"-B","-c",setup+body],capture_output=True,text=True,timeout=20)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            return json.loads(completed.stdout)

    def test_import_then_edit_runtime_rejects_before_output(self):
        for name in ("core.py","workflow.py","source_binding.py","NUMERICAL_CONTRACT.json"):
            result=self.probe("import workflow as w\n"
                f"p=package/{name!r}\nwith p.open('ab') as f: f.write(b'\\n# changed after import\\n')\n"
                "try:\n w.run(root/'recipe.json',output)\nexcept ValueError as e:\n"
                " print(json.dumps({'error':str(e),'created':output.parent.exists()}))\n"
                "else:\n raise AssertionError('stale import accepted')\n")
            self.assertIn("changed since import",result["error"])
            self.assertFalse(result["created"])

    def test_global_module_name_collision_cannot_substitute_core(self):
        result=self.probe("fake=types.ModuleType('core'); fake.Grid=None\nsys.modules['core']=fake\n"
            "import workflow as w\nr=w.run(root/'recipe.json',output)\n"
            "print(json.dumps({'status':r['status'],'private_core':w._core is not fake,"
            "'path':str(Path(w._core.__file__).parent==package)}))\n")
        self.assertEqual(result["status"],"COMMITTED_BOUNDED_REFERENCE")
        self.assertTrue(result["private_core"])
        self.assertEqual(result["path"],"True")

    def test_receipt_contains_the_exact_compiled_dependency_bytes(self):
        result=self.probe("import workflow as w\nw.run(root/'recipe.json',output)\n"
            "r=w.read_json(output/'RECEIPT.json')\n"
            "print(json.dumps({'matches':all(hashlib.sha256((package/p['name']).read_bytes()).hexdigest()==p['sha256'] "
            "for p in r['identity']['import_loaded_runtime']),'count':len(r['identity']['import_loaded_runtime'])}))\n")
        self.assertTrue(result["matches"])
        self.assertEqual(result["count"],8)

    def test_disk_mutation_during_dependency_load_rejects(self):
        result=self.probe("import source_binding as b\noriginal=b.read_source\nchanged=False\n"
            "def read(path):\n global changed\n raw=original(path)\n"
            " if Path(path).name=='core.py' and not changed:\n"
            "  changed=True\n  with Path(path).open('ab') as f: f.write(b'\\n# import race fixture\\n')\n"
            " return raw\n"
            "b.read_source=read\n"
            "try:\n b.load(package,{})\nexcept ValueError as e:\n print(json.dumps({'error':str(e)}))\n"
            "else:\n raise AssertionError('source drift accepted')\n")
        self.assertIn("changed since import",result["error"])


if __name__=="__main__": unittest.main()
