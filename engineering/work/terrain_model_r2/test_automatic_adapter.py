import copy
import unittest

from fixtures import suite
from workflow import execute


class AutomaticBasinAdapterTests(unittest.TestCase):
    def recipe(self):
        return suite()[-1]

    def test_exact_shared_surface_and_ledger(self):
        recipe=self.recipe(); before=copy.deepcopy(recipe)
        result=execute(recipe); w=result["water"]
        self.assertEqual(recipe,before)
        self.assertEqual(result["change_m"],[0.]*16)
        self.assertEqual(w["input_volume_m3"],16.)
        self.assertAlmostEqual(w["stored_volume_m3"]+w["exported_volume_m3"],16.)
        self.assertFalse(w["transient_channel_feedback_solved"])
        self.assertEqual(w["topology"]["leaf_pit_indices"],{"leaf_0009":9})

    def test_draining_flat_does_not_invent_a_lake(self):
        recipe=self.recipe(); recipe["initial"]["bedrock_m"]=[5.]*16
        w=execute(recipe)["water"]
        self.assertEqual(w["topology"]["basins"],[])
        self.assertEqual(w["water_depth_m"],[0.]*16)
        self.assertEqual(w["direct_boundary_export_m3"],16.)

    def test_closed_flat_stores_without_height_perturbation(self):
        recipe=self.recipe(); recipe["initial"]["bedrock_m"]=[5.]*16
        recipe["operations"][0]["outlets"]=[]
        w=execute(recipe)["water"]
        self.assertAlmostEqual(w["stored_volume_m3"],16.)
        self.assertEqual(w["exported_volume_m3"],0.)
        for value in w["water_depth_m"]:self.assertAlmostEqual(value,.01)

    def test_repeated_water_cannot_reset_inventory(self):
        recipe=self.recipe(); recipe["operations"]*=2
        with self.assertRaisesRegex(ValueError,"inventory continuation"):execute(recipe)

    def test_new_bed_invalidates_water(self):
        recipe=self.recipe(); recipe["operations"]+=suite()[2]["operations"][:1]
        result=execute(recipe)
        self.assertIsNone(result["water"])
        self.assertEqual(result["water_status"],"STALE_BED_CHANGED_REQUIRES_RECOMPUTATION")

    def test_unbound_inputs_fail_closed(self):
        for value in (-1.,True,float("nan")):
            recipe=self.recipe();recipe["operations"][0]["water_input_m3"][0]=value
            with self.assertRaises(ValueError):execute(recipe)
        recipe=self.recipe();recipe["operations"][0]["source"]="preceding_channel_export"
        with self.assertRaises(ValueError):execute(recipe)


if __name__=="__main__":unittest.main()
