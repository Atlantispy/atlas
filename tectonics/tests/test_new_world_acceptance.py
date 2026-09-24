"""Acceptance-report guards only; no generation, child processes or campaign."""
import copy
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import check_new_world_acceptance as check


def rows():
    a = dict(ranked_plate_area_fractions=[.1,.9], sorted_crust_thickness_m=[7000.,35000.],
             boundary_rms_cm_year=2., structure_id='a', motion_id='a', plate_count=6)
    b = dict(ranked_plate_area_fractions=[.2,.8], sorted_crust_thickness_m=[7500.,37000.],
             boundary_rms_cm_year=3., structure_id='b', motion_id='b', plate_count=6)
    c = dict(a, motion_id='c', plate_count=12)
    return [dict(status='PASS', create=dict(world=w),
                 resume=dict(physics=dict(mean_surface_change_m=float(i)))) for i,w in enumerate((a,b,c))]


class AcceptanceGuards(unittest.TestCase):
    def test_missing_failed_and_identical_physical_worlds_do_not_pass(self):
        good = rows()
        self.assertTrue(check.diversity(good)['changed_dependent_motion'])
        for changed in (good[:2], [dict(good[0],status='INCOMPLETE'),*good[1:]],
                        [good[0],copy.deepcopy(good[0]),good[2]]):
            with self.assertRaises(AssertionError):
                check.diversity(changed)

    def test_upstream_geology_and_dependent_motion_relationship_is_checked(self):
        for key,value in (('structure_id','changed'),('motion_id','a'),('plate_count',6)):
            changed = rows()
            changed[2]['create']['world'][key] = value
            with self.assertRaises(AssertionError):
                check.diversity(changed)

    def test_independent_physics_rejects_inventory_or_area_error(self):
        n = dict(gradient_s=[[-1e-14,0.],[2e-14,0.]], density_kg_m3=[2700.],
                 mantle_density_kg_m3=3300., epoch_id='e',frame_id='f',datum_id='d')
        initial = dict(native_input=n, project_id='p', initial_id='i')
        out = []
        for t in check.TIMES:
            j = math.exp(-1e-14*t)
            delta = 30000./j - 30000.
            out.append(dict(project_id='p',initial_id='i',elapsed_s=t,epoch_id='e',frame_id='f',datum_id='d',
                volume_m3=[[30000.]],mass_kg=[[81000000.]],enthalpy_known=False,enthalpy_j=None,
                evolved_temperature_k=None,absolute_elevation_m=None,area_ratio=[j],area_m2=[j],
                thickness_m=[[30000./j]],base_change_m=[-delta*2700./3300.],
                surface_change_m=[delta*600./3300.],accounted_workspace_peak_bytes=100))
        self.assertTrue(check.physical_checks(initial,out)['finite_area_and_thickness'])
        for key,value in (('area_ratio',[1.]),('mass_kg',[[0.]]),('absolute_elevation_m',[0.])):
            changed = copy.deepcopy(out)
            changed[-1][key] = value
            with self.assertRaises(AssertionError):
                check.physical_checks(initial,changed)

    def test_report_cannot_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'receipt.json'
            check.write_new(path, {'first':True})
            with self.assertRaises(FileExistsError):
                check.write_new(path, {'second':True})
            self.assertEqual(check.read(path),{'first':True})


if __name__ == '__main__':
    unittest.main()
