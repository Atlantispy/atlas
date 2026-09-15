"""One connected actual-material check; no geographical/full-year claim."""
from copy import deepcopy
from fractions import Fraction as F
import time
import unittest

from work.generator_upgrade_r16 import regional
from work.generator_upgrade_r19 import working, driver, state, provenance as p


class WorkingCoastalTests(unittest.TestCase):
    evidence = {}
    checkpoints = {}
    timings = {}
    cache_reports = {}

    def _run(self, case, *, cache=True):
        started = time.perf_counter()
        run, evidence = working.build_case(case, cache=cache)
        try:
            working.run_case(run, case, stop_s=900, cache=cache)
            saved = run.checkpoint()
            restored = driver.CoastalRun.restore(deepcopy(saved))
            self.assertEqual(saved, restored.checkpoint())
            working.run_case(restored, case, stop_s=3600, cache=cache)
            run = restored
            self.assertEqual(run.time, 3600)
            self.assertEqual(run.checkpoint()['scientific']['accounts']['water_residual_m3'], '0')
        finally:
            type(self).evidence[case] = evidence
            type(self).checkpoints[case] = run.checkpoint()
            type(self).cache_reports[case] = getattr(run, 'cache_reporting', {})
            type(self).timings[case] = time.perf_counter()-started
        return run, evidence

    def test_connected_native_export_three_hour_cases_and_cached_reuse(self):
        run, evidence = self._run('C1_NATIVE_RIVER_TO_COAST')
        self.assertFalse(evidence['lineage']['geographic_coupling_claimed'])
        self.assertEqual(evidence['lineage']['sea_registration'], 'NOT_ASSERTED')
        self.assertFalse(evidence['lineage']['receiving_bed_translated'])
        packet = evidence['finite_river_packet']
        self.assertEqual(F(packet['free_carrier_liquid_m3']), 4000)
        self.assertGreater(sum((F(row['mass_kg']) for row in packet['dry_materials'].values()), F()), 0)
        self.assertFalse(run.pulses)
        self.assertEqual(len(run.consumed), 1)
        self.assertEqual(run.imported['water_m3'], 4000)
        transfers = [row for receipt in run.receipts for row in receipt['flow']['transfers']]
        self.assertTrue(any(row['donor'] == 'reach' and row['receiver'] == 'coast_a'
                            and any(F(v) > 0 for v in row['dry_material_kg'].values()) for row in transfers))
        self.assertTrue(any(any(F(v) > 0 for v in receipt[half]['coast_a']['deposited_mass_kg'].values())
                            for receipt in run.receipts for half in ('first_bed', 'second_bed')))
        _, native = regional.p.backend()
        initial = native.LandscapeState.from_dict(evidence['r18_snapshot']['scientific']['state'])
        remaining = native.Column.from_dict(evidence['upstream_remaining_column'])
        joint_before = {}
        for _, column in initial.columns:
            for layer in column.layers:
                joint_before[layer.material_id] = joint_before.get(layer.material_id, F())+layer.mass_kg
        joint_after = state.inventory(run.cells, run.palette)['materials_kg']
        for layer in remaining.layers:
            joint_after[layer.material_id] = joint_after.get(layer.material_id, F())+layer.mass_kg
        self.assertEqual(joint_before, joint_after)  # Coast stock is not counted twice.

        started = time.perf_counter()
        warm, warm_evidence = working.build_case('C1_NATIVE_RIVER_TO_COAST')
        self.assertTrue(warm.cache_reporting['native_geology_hit'])
        self.assertTrue(warm.cache_reporting['native_river_hit'])
        working.run_case(warm, 'C1_NATIVE_RIVER_TO_COAST')
        type(self).timings['C1_WARM_REUSE'] = time.perf_counter()-started
        type(self).cache_reports['C1_WARM_REUSE'] = deepcopy(warm.cache_reporting)
        self.assertEqual(warm.cache_reporting['interval_hits'], 4)
        self.assertEqual(warm.checkpoint(), run.checkpoint())
        self.assertEqual(warm_evidence, evidence)
        self.assertFalse(warm.cache_reporting.get('warnings'))

        calm, calm_evidence = self._run('C0_CLOSED_CALM')
        self.assertEqual(calm.imported['water_m3'], 0)
        self.assertFalse(calm.links)
        self.assertTrue(all(not any(cell.momentum) for cell in calm.cells.values()))
        self.assertTrue(all(F(receipt['flow']['gross_mixture_transfer_m3']) == 0 for receipt in calm.receipts))
        waves, wave_evidence = self._run('C2_WAVE_STIRRING_AND_CURRENT')
        gross_erosion = sum((F(value) for receipt in waves.receipts
                            for half in ('first_bed', 'second_bed') for cell in receipt[half].values()
                            for value in cell['eroded_mass_kg'].values()), F())
        self.assertGreater(gross_erosion, 0)
        self.assertTrue(any(any(receipt['flow']['momentum_ports_m4_s']['wind']) for receipt in waves.receipts))
        self.assertTrue(all(cell['wave_mean_momentum_added_m4_s'] == [0., 0.]
                            for receipt in waves.receipts for half in ('first_bed', 'second_bed')
                            for cell in receipt[half].values()))
        type(self).wave_gross_eroded_mass_kg = str(gross_erosion)


if __name__ == '__main__':
    unittest.main()
