"""Independent frozen W09 water accounts and bounded lifecycle controls."""
from concurrent.futures import CancelledError
import gc
import math
from threading import Event
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.storage import ArrayStore, Compression, StoreLimits
from atlas_tectonics.w09_water import PreparedWater


CAP = 128 * 1024**2


def prepare(bed, areas, links, outlets, **kwargs):
    return PreparedWater(bed, areas, links, np.ones(len(links)), outlets,
        frame_id='synthetic-planar-SI', datum_id='synthetic-z-up',
        source_id='synthetic-water-fixture', **kwargs)


def w2(**kwargs):
    return prepare([0., 1., 2.], [2., 1., 0.], [[0, 1], [1, 2]], [2], **kwargs)


def w3(**kwargs):
    # Node 2 is a massless physical saddle, not an extra water-bearing cell.
    return prepare([0., -1., 1., 3.], [1., 1., 0., 0.],
                   [[0, 2], [1, 2], [2, 3]], [3], **kwargs)


def single_lake(**kwargs):
    return prepare([0., 10.], [2., 0.], [[0, 1]], [1], **kwargs)


def levels(plan, state):
    wet = plan.geometry.areas_m2 > 0
    return plan.geometry.bed_m[wet] + state.water_m3[wet] / plan.geometry.areas_m2[wet]


def physical_signature(state):
    """Partition comparison excludes identity and accepted-step history only."""
    return np.r_[state.water_m3, state.time_s, state.subsurface_m3,
        state.evaporated_m3, state.exported_m3, state.supplied_m3,
        state.initial_total_m3]


class W09WaterTests(unittest.TestCase):
    def assert_account(self, state):
        stocks = [*state.water_m3, state.subsurface_m3, state.evaporated_m3,
                  state.exported_m3, state.initial_total_m3, state.supplied_m3]
        residual = math.fsum([*state.water_m3, state.subsurface_m3,
            state.evaporated_m3, state.exported_m3,
            -state.initial_total_m3, -state.supplied_m3])
        self.assertLessEqual(abs(residual),
            128 * np.finfo(float).eps * math.fsum(abs(float(v)) for v in stocks))

    def test_w1_receiver_change_uses_physical_bed_and_rebuilds_geometry(self):
        identities = []
        for outlet_bed, expected_water, expected_export in (
                (0., [0., 0., 0., 0.], .08),
                (3., [0., 0., 0., .08], 0.)):
            bed = [3., 2., outlet_bed, 1.]
            with prepare(bed, [2., 3., 0., 1.],
                         [[0, 1], [1, 2], [1, 3]], [2]) as plan:
                state = plan.advance(plan.initialise(), 10.,
                    runoff_m_s=[.001, .002, 0., 0.], forcing_id='W1-runoff')
                q=plan.accumulate_runoff([.001,.002,0.,0.])
                self.assertAlmostEqual(q[2 if outlet_bed == 0. else 3],.008,places=12)
                np.testing.assert_allclose(state.water_m3, expected_water, rtol=1e-10, atol=1e-12)
                np.testing.assert_array_equal(plan.geometry.bed_m, bed)
                self.assertAlmostEqual(state.exported_m3, expected_export, places=12)
                self.assertAlmostEqual(state.supplied_m3, .08, places=12)
                identities.append(state.geometry_id)
                self.assert_account(state)
        self.assertNotEqual(*identities)

    def test_w2_area_weighted_filling_and_finite_sill_export(self):
        with w2() as plan:
            first = plan.add_water(plan.initialise(), [2.5, 0., 0.], source_id='W2-first')
            np.testing.assert_allclose(levels(plan, first), [7/6, 7/6], rtol=1e-10, atol=1e-12)
            self.assertEqual(first.exported_m3, 0.)
            final = plan.add_water(first, [4., 0., 0.], source_id='W2-second')
            np.testing.assert_allclose(final.water_m3, [4., 1., 0.], rtol=1e-10, atol=1e-12)
            self.assertAlmostEqual(final.exported_m3, 1.5, places=12)
            self.assertAlmostEqual(final.supplied_m3, 6.5, places=12)
            self.assert_account(first)
            self.assert_account(final)

    def test_w3_nested_fill_merge_then_outer_spill(self):
        with w3() as plan:
            first = plan.add_water(plan.initialise(), [6., 0., 0., 0.], source_id='W3-first')
            np.testing.assert_allclose(first.water_m3, [2.5, 3.5, 0., 0.], rtol=1e-10, atol=1e-12)
            final = plan.add_water(first, [3., 0., 0., 0.], source_id='W3-second')
            np.testing.assert_allclose(final.water_m3, [3., 4., 0., 0.], rtol=1e-10, atol=1e-12)
            self.assertAlmostEqual(final.exported_m3, 2., places=12)
            self.assert_account(final)

    def test_w3_drawdown_splits_at_saddle_and_preserves_other_child(self):
        with w3() as plan:
            initial = plan.initialise([2.5, 3.5, 0., 0.])
            split = plan.advance(initial, 3., evaporation_m_s=[1., 0., 0., 0.],
                                 forcing_id='W3-to-saddle')
            np.testing.assert_allclose(split.water_m3, [1., 2., 0., 0.], rtol=1e-10, atol=1e-12)
            dry = plan.advance(split, 1., evaporation_m_s=[1., 0., 0., 0.],
                               forcing_id='W3-to-first-dry')
            np.testing.assert_allclose(dry.water_m3, [0., 2., 0., 0.], rtol=1e-10, atol=1e-12)
            final = plan.advance(dry, 1., evaporation_m_s=[1., 0., 0., 0.],
                                 forcing_id='W3-after-first-dry')
            np.testing.assert_array_equal(final.water_m3, dry.water_m3)
            self.assertAlmostEqual(final.evaporated_m3, 4., places=12)
            self.assertEqual(final.exported_m3, 0.)
            self.assert_account(final)

    def test_w4_dryout_limits_losses_and_dry_start_has_none(self):
        with single_lake() as plan:
            for initial_volume in (1., 0.):
                with self.subTest(initial_volume=initial_volume):
                    initial = plan.initialise([initial_volume, 0.])
                    final = plan.advance(initial, 3., evaporation_m_s=.2,
                        infiltration_m_s=.3, forcing_id='W4-losses')
                    np.testing.assert_array_equal(final.water_m3, [0., 0.])
                    self.assertAlmostEqual(final.evaporated_m3, .4*initial_volume, places=12)
                    self.assertAlmostEqual(final.subsurface_m3, .6*initial_volume, places=12)
                    self.assertEqual(final.exported_m3, 0.)
                    self.assert_account(final)

    def test_empty_lake_shares_inflow_between_simultaneous_loss_demands(self):
        with single_lake() as plan:
            final = plan.advance(plan.initialise(), 4.,
                boundary_inflow_m3_s=[.25, 0.], evaporation_m_s=.2,
                infiltration_m_s=.3, forcing_id='finite-dry-inflow')
            np.testing.assert_array_equal(final.water_m3, [0., 0.])
            self.assertAlmostEqual(final.evaporated_m3, .4, places=12)
            self.assertAlmostEqual(final.subsurface_m3, .6, places=12)
            self.assertAlmostEqual(final.supplied_m3, 1., places=12)
            self.assert_account(final)

    def test_rain_and_runoff_have_disjoint_wet_and_dry_footprints(self):
        with single_lake() as plan:
            final = plan.advance(plan.initialise([2., 0.]), 1.,
                rain_m_s=.1, runoff_m_s=.9, forcing_id='wet-rain-only')
            np.testing.assert_allclose(final.water_m3, [2.2, 0.], rtol=1e-10, atol=1e-12)
            self.assertAlmostEqual(final.supplied_m3, .2, places=12)
            self.assert_account(final)
        with prepare([1., 0.], [2., 0.], [[0, 1]], [1]) as plan:
            final = plan.advance(plan.initialise(), 1., rain_m_s=.1,
                                 runoff_m_s=.9, forcing_id='dry-runoff-only')
            self.assertAlmostEqual(final.exported_m3, 1.8, places=12)
            self.assertAlmostEqual(final.supplied_m3, 1.8, places=12)
            self.assert_account(final)

    def test_forcing_partition_invariance_through_split_and_dryout(self):
        with w3() as plan:
            initial = plan.initialise([2.5, 3.5, 0., 0.])
            once = plan.advance(initial, 5., evaporation_m_s=[1., 0., 0., 0.],
                                forcing_id='one-interval')
            split = initial
            for index, duration in enumerate((1., 2., 2.)):
                split = plan.advance(split, duration, evaporation_m_s=[1., 0., 0., 0.],
                                     forcing_id=f'partition-{index}')
            np.testing.assert_allclose(physical_signature(once), physical_signature(split),
                                       rtol=1e-10, atol=1e-12)
            self.assert_account(once)
            self.assert_account(split)

    def test_receding_shore_stops_losing_water_from_newly_dry_cell(self):
        with w2() as plan:
            initial=plan.initialise([2.4,.2,0.])
            final=plan.advance(initial,5.,evaporation_m_s=[0.,1.,0.],forcing_id='upper-shore-drying')
            np.testing.assert_allclose(final.water_m3,[2.,0.,0.],rtol=1e-10,atol=1e-12)
            self.assertAlmostEqual(final.evaporated_m3,.6,places=12)
            self.assert_account(final)

    def test_checkpoint_restore_and_remaining_interval_match_without_replay(self):
        owner=WorkBudget(CAP)
        with TemporaryDirectory() as folder:
            with ArrayStore(Path(folder)/'water.sqlite',limits=StoreLimits(65536,1048576,16777216),
                            compression=Compression(codec='raw',shuffle='none'),budget=owner) as store:
                with w3(store=store,budget=owner) as plan:
                    initial=plan.initialise([2.5,3.5,0.,0.])
                    prefix=plan.advance(initial,3.,evaporation_m_s=[1.,0.,0.,0.],forcing_id='prefix')
                    key=plan.checkpoint(prefix)
                    expected=plan.advance(prefix,2.,evaporation_m_s=[1.,0.,0.,0.],forcing_id='suffix')
                with w3(store=store,budget=owner) as resumed:
                    restored=resumed.restore(key)
                    self.assertEqual(restored.state_id,prefix.state_id)
                    got=resumed.advance(restored,2.,evaporation_m_s=[1.,0.,0.,0.],forcing_id='suffix')
                    self.assertEqual(got.state_id,expected.state_id)
                    self.assertEqual(got.evaporated_m3,4.)
                    self.assertEqual(resumed.statistics()['computed_intervals'],2)
                with w2(store=store,budget=owner) as wrong:
                    with self.assertRaises(TectonicsError):
                        wrong.restore(key)
        self.assertEqual(owner.reserved_bytes,0)

    def test_multiple_independent_shore_contacts_are_all_resolved(self):
        with prepare([0.,1.,2.,0.,1.,2.],[1.,1.,0.,1.,1.,0.],
                     [[0,1],[1,2],[3,4],[4,5]],[2,5]) as plan:
            state=plan.initialise([1.,0.,0.,1.,0.,0.])
            out=plan.advance(state,1.,boundary_inflow_m3_s=[1.,0.,0.,1.,0.,0.],
                evaporation_m_s=[0.,2.,0.,0.,2.,0.],forcing_id='two-shore-contacts')
            np.testing.assert_allclose(out.water_m3,[1.,0.,0.,1.,0.,0.],rtol=1e-10,atol=1e-12)
            self.assertAlmostEqual(out.evaporated_m3,2.,places=12)
            self.assert_account(out)

    def test_cache_hit_and_interval_limit_preserve_accepted_input(self):
        from atlas_tectonics.w09_water import WaterState
        with single_lake() as plan:
            initial=plan.initialise([1.,0.])
            first=plan.advance(initial,1.,forcing_id='same')
            again=plan.advance(initial,1.,forcing_id='same')
            self.assertEqual(first.state_id,again.state_id)
            self.assertEqual(plan.statistics()['latest_hits'],1)
            d=initial.descriptor(); d['accepted_intervals']=256
            exhausted=WaterState(initial.water_m3,**d)
            with self.assertRaises(TectonicsError):
                plan.advance(exhausted,1.,forcing_id='over-limit')
            self.assertEqual(exhausted.accepted_intervals,256)

    def test_stillwater_and_immutable_snapshots_do_not_borrow_caller_buffers(self):
        bed = np.array([0., 10.]); areas = np.array([2., 0.])
        links = np.array([[0, 1]]); water = np.array([1., 0.])
        with prepare(bed, areas, links, [1]) as plan:
            initial = plan.initialise(water, subsurface_m3=2.)
            bed[0] = 99.; areas[0] = 99.; links[0, 1] = 0; water[0] = 99.
            final = plan.advance(initial, 60., forcing_id='still-water')
            np.testing.assert_array_equal(final.water_m3, [1., 0.])
            np.testing.assert_array_equal(plan.geometry.bed_m, [0., 10.])
            self.assertEqual(final.subsurface_m3, 2.)
            self.assertEqual(final.initial_total_m3, 3.)
            with self.assertRaises(ValueError):
                final.water_m3.setflags(write=True)
            with self.assertRaises((AttributeError, TypeError)):
                final.time_s = 99.
            self.assert_account(final)
            # A changed physical bed drains the same finite stock; rebuilding
            # routing must not reset the water ledger or re-supply its volume.
            with prepare([2., 1.], [2., 0.], [[0, 1]], [1]) as changed:
                moved = changed.relocate(final, plan.geometry, source_id='declared-bed-change')
                np.testing.assert_array_equal(moved.water_m3, [0., 0.])
                self.assertEqual(moved.exported_m3, 1.)
                self.assertEqual(moved.subsurface_m3, 2.)
                self.assertEqual(moved.initial_total_m3, 3.)
                self.assertEqual(moved.supplied_m3, 0.)
                self.assertEqual(moved.time_s, 60.)
                self.assertNotEqual(moved.geometry_id, final.geometry_id)
                self.assert_account(moved)

    def test_changed_forcing_reuses_geometry_but_computes_new_water(self):
        with single_lake() as plan:
            initial = plan.initialise([1., 0.])
            first = plan.advance(initial, 1., rain_m_s=.1, forcing_id='rain-A')
            first_stats = plan.statistics()
            second = plan.advance(initial, 1., rain_m_s=.2, forcing_id='rain-B')
            stats = plan.statistics()
            self.assertEqual(stats['geometry_preparations'], 1)
            self.assertGreater(stats['computed_intervals'], first_stats['computed_intervals'])
            self.assertEqual(stats['latest_hits'], first_stats['latest_hits'])
            np.testing.assert_allclose(first.water_m3, [1.2, 0.], rtol=1e-10, atol=1e-12)
            np.testing.assert_allclose(second.water_m3, [1.4, 0.], rtol=1e-10, atol=1e-12)
            self.assertNotEqual(first.state_id, second.state_id)

    def test_invalid_geometry_water_and_forcing_refuse(self):
        for bed, areas, links in (
                ([0., math.nan], [2., 0.], [[0, 1]]),
                ([0., 1.], [-2., 0.], [[0, 1]]),
                ([0., 1.], [math.inf, 0.], [[0, 1]]),
                ([0., 1.], [2., 0.], [[0, 2]])):
            with self.subTest(bed=bed, areas=areas, links=links), self.assertRaises(TectonicsError):
                with prepare(bed, areas, links, [1]):
                    pass
        with single_lake() as plan:
            for water in ([-1., 0.], [math.nan, 0.], [1., 1.], [1.]):
                with self.subTest(water=water), self.assertRaises(TectonicsError):
                    plan.initialise(water)
            initial = plan.initialise([1., 0.])
            for values in (dict(runoff_m_s=-1.), dict(rain_m_s=math.inf),
                           dict(evaporation_m_s=[0., 1.]),
                           dict(boundary_inflow_m3_s=[1.]), dict(infiltration_m_s=math.nan)):
                with self.subTest(values=values), self.assertRaises(TectonicsError):
                    plan.advance(initial, 1., forcing_id='invalid', **values)
            for amount in ([-1., 0.], [math.inf, 0.], [1., 1.]):
                with self.subTest(amount=amount), self.assertRaises(TectonicsError):
                    plan.add_water(initial, amount, source_id='invalid')

    def test_cancellation_is_atomic_and_combined_budget_stays_bounded(self):
        cancelled = Event(); cancelled.set()
        owner = WorkBudget(CAP)
        with w2(budget=owner) as plan, single_lake(budget=owner) as other:
            initial = plan.initialise([1., 0., 0.])
            identity = initial.state_id
            for operation in (
                    lambda: plan.advance(initial, 1., forcing_id='cancelled', cancel=cancelled),
                    lambda: plan.add_water(initial, [1., 0., 0.], source_id='cancelled', cancel=cancelled)):
                with self.assertRaises(CancelledError):
                    operation()
            self.assertEqual(initial.state_id, identity)
            np.testing.assert_array_equal(initial.water_m3, [1., 0., 0.])
            self.assertGreater(owner.reserved_bytes, 0)
            self.assertLessEqual(owner.peak_reserved_bytes, CAP)
        del initial, plan, other, operation
        gc.collect()
        self.assertEqual(owner.reserved_bytes, 0)
        tiny = WorkBudget(1)
        with self.assertRaises(MemoryLimitError):
            with w2(budget=tiny):
                pass
        self.assertEqual(tiny.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
