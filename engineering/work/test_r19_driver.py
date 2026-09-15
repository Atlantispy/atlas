"""One bounded R19 continuation/cursor regression; synthetic finite reaches.

No actual Sea geometry, source calibration, annual or regional generation.
The explicit endpoints and substep ceilings match between compared executions.
"""
from copy import deepcopy
from fractions import Fraction as F
import unittest

from work.test_r19_physics import palette_fixture, cell_fixture, forcing_fixture
from work.generator_upgrade_r19 import driver, provenance as p


class CoastalDriverTests(unittest.TestCase):
    def test_pending_pulse_restart_tampering_and_failed_prefix(self):
        palette, mid = palette_fixture()
        calm = forcing_fixture()
        packet_id = 'synthetic-finite-river-pulse'
        links = [{'id': 'synthetic-mouth', 'left': 'L', 'right': 'R',
                  'crest_m': 0, 'conductance_m2_s': 1}]

        def fresh():
            cells = {'L': cell_fixture(palette, mid, free=2, kind='reach'),
                     'R': cell_fixture(palette, mid, free=1, kind='reach')}
            run = driver.CoastalRun(cells, palette, [], links,
                evidence='SYNTHETIC TEST; two finite disjoint reach stores',
                lineage={'fixture': 'R19_DRIVER_FINITE_PULSE_RESTART'})
            run.enqueue(packet_id, 'L', F(1, 16), {mid: F(1, 100000)},
                duration_s=F(3, 2), attached_pore_liquid_m3=0,
                momentum=(0., 0.), source='SYNTHETIC TEST; prescribed finite source, not a discharge estimate')
            return run

        # Save at the SAME explicit forcing endpoint, while source water and
        # material remain pending; uninterrupted and restored paths share it.
        full = fresh()
        saved = full.advance(1, calm, max_step_s=F(1, 4), max_steps=64)
        pending = saved['scientific']['pulses'][packet_id]
        self.assertGreater(F(pending['water']), 0)
        self.assertGreater(F(pending['materials'][mid]), 0)
        self.assertEqual(F(pending['end']), F(3, 2))
        expected = full.advance(2, calm, max_step_s=F(1, 4), max_steps=64)
        resumed = driver.CoastalRun.restore(deepcopy(saved))
        self.assertEqual(resumed.checkpoint(), saved)
        actual = resumed.advance(2, calm, max_step_s=F(1, 4), max_steps=64)
        self.assertEqual(actual, expected)
        self.assertEqual(actual['scientific']['pulses'], {})
        self.assertIn(packet_id, actual['scientific']['consumed'])
        self.assertEqual(F(actual['scientific']['imported']['water_m3']), F(1, 16))
        self.assertEqual(F(actual['scientific']['imported']['materials_kg'][mid]), F(1, 100000))
        self.assertEqual(F(actual['scientific']['accounts']['water_residual_m3']), 0)
        before_duplicate = resumed.checkpoint()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            resumed.enqueue(packet_id, 'L', 1, {}, duration_s=1, source='duplicate attempt')
        self.assertEqual(resumed.checkpoint(), before_duplicate)

        # Rehashing does not legitimise internally inconsistent packet cursors,
        # stocks, momentum or accepted clocks. Each starts from the good save.
        def corrupt(science, kind):
            if kind == 'negative_pending_water':
                science['pulses'][packet_id]['water'] = '-1'
            elif kind == 'changed_pending_material':
                pulse = science['pulses'][packet_id]
                pulse['materials'][mid] = str(F(pulse['materials'][mid])+F(1, 100000))
            elif kind == 'changed_pending_momentum':
                science['pulses'][packet_id]['momentum'] = [1., 0.]
            elif kind == 'orphan_pending_packet':
                science['pulses']['unregistered-packet'] = deepcopy(science['pulses'][packet_id])
            elif kind == 'removed_consumed_id':
                del science['consumed'][packet_id]
            elif kind == 'changed_original_packet':
                science['source_packets'][packet_id]['packet']['water'] = '2'
            elif kind == 'changed_clock':
                science['time_s'] = str(F(science['time_s'])+F(1, 8))
            elif kind == 'changed_pending_endpoint':
                science['pulses'][packet_id]['end'] = '3'
            else:
                raise AssertionError('unhandled explicit corruption fixture')

        for kind in ('negative_pending_water', 'changed_pending_material',
                     'changed_pending_momentum', 'orphan_pending_packet',
                     'removed_consumed_id', 'changed_original_packet',
                     'changed_clock', 'changed_pending_endpoint'):
            with self.subTest(rehashed_corruption=kind):
                broken = deepcopy(saved)
                corrupt(broken['scientific'], kind)
                broken['scientific_sha256'] = p.sha(broken['scientific'])
                with self.assertRaises(ValueError):
                    driver.CoastalRun.restore(broken)
        changed_source = deepcopy(saved)
        source_path = next(iter(changed_source['execution']['sources']))
        changed_source['execution']['sources'][source_path] = '0'*64
        with self.assertRaises(ValueError):
            driver.CoastalRun.restore(changed_source)

        # A work-budget stop is not completion, but the accepted prefix remains
        # source-bound and can finish its ORIGINAL interval without recompute.
        continuous = fresh()
        uninterrupted = continuous.advance(2, calm, max_step_s=F(1, 4), max_steps=64)
        limited = fresh()
        with self.assertRaisesRegex(ValueError, 'step budget exhausted'):
            limited.advance(2, calm, max_step_s=F(1, 4), max_steps=1)
        prefix = limited.checkpoint()
        science = prefix['scientific']
        self.assertGreater(F(science['time_s']), 0)
        self.assertLess(F(science['time_s']), 2)
        self.assertEqual(len(science['receipts']), 1)
        self.assertEqual(science['active_interval'], 0)
        self.assertIs(science['intervals'][0]['complete'], False)
        self.assertEqual(F(science['intervals'][0]['end_s']), 2)
        self.assertEqual(science['intervals'][0]['forcing'], calm)
        self.assertEqual(science['intervals'][0]['forcing_sha256'], p.sha(calm))
        self.assertEqual(F(science['accounts']['water_residual_m3']), 0)
        continuation = driver.CoastalRun.restore(deepcopy(prefix))
        self.assertEqual(continuation.checkpoint(), prefix)
        changed_forcing = deepcopy(calm)
        changed_forcing['wind_stress_Pa'] = [.01, 0.]
        for end, forcing in ((F(9, 4), calm), (F(2), changed_forcing)):
            with self.subTest(changed_interrupted_end=str(end), changed_forcing=forcing != calm):
                with self.assertRaisesRegex(ValueError, 'bound end and forcing'):
                    continuation.advance(end, forcing, max_step_s=F(1, 4), max_steps=64)
                self.assertEqual(continuation.checkpoint(), prefix)
        finished = continuation.advance(2, calm, max_step_s=F(1, 4), max_steps=64)
        self.assertEqual(finished, uninterrupted)
        self.assertIsNone(finished['scientific']['active_interval'])
        self.assertIs(finished['scientific']['intervals'][0]['complete'], True)


if __name__ == '__main__':
    unittest.main()
