"""Executable R2 case alignment and offline source-profile example."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from atlas_tectonics import PreparedPrecursor, InitialSamplingCell, PrecursorSamplingLimits

ROOT=Path(__file__).resolve().parents[1]


def example_module():
    spec=importlib.util.spec_from_file_location('r2_example_tool',ROOT/'tools'/'prepare_precursor_example.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class ExampleContracts(unittest.TestCase):
    def test_policy_matches_declared_default_numerics(self):
        spec=json.loads((ROOT/'cases/precursor_r2.json').read_text())
        limits=PrecursorSamplingLimits()
        for k in ('inventory_relative','thermal_absolute_k','thermal_relative','quadrature_intervals'):
            self.assertEqual(getattr(limits,k),spec['numerical_policy'][k])

    def test_example_uses_offline_profiles_and_retains_unresolved_physics(self):
        s=example_module().build_example();c=s.case
        with PreparedPrecursor(s) as p:
            r=p.sample_cells((InitialSamplingCell('whole',c.topology.domain,0.,100000.),),
                frame_id=c.topology.frame_id,epoch_id=c.epoch_id,depth_reference_id=c.depth_reference_id)
        self.assertAlmostEqual(r.temperature()[0],933.15,places=10)
        self.assertEqual(r.array('cell_volume_m3')[0],2e15)
        self.assertFalse(r.array('solid_volume_known').any())
        self.assertTrue(all(m.source_id.startswith('earth-ref-') for m in c.materials))
        self.assertTrue(any(path=='stress' for path,reason in s.unresolved_initial_state))

    def test_example_store_is_explicit_single_snapshot_and_no_overwrite(self):
        tool=str(ROOT/'tools/prepare_precursor_example.py')
        with tempfile.TemporaryDirectory() as tmp:
            target=str(Path(tmp)/'example.db')
            proc=subprocess.run([sys.executable,'-I','-B',tool,'--save-store',target],capture_output=True,text=True,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr)
            record=json.loads(proc.stdout);self.assertTrue(record['store_written'])
            before=Path(target).read_bytes()
            second=subprocess.run([sys.executable,'-I','-B',tool,'--save-store',target],capture_output=True,text=True,timeout=30)
            self.assertEqual(second.returncode,2)
            self.assertEqual(before,Path(target).read_bytes())
