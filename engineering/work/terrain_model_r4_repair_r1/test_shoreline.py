"""Small independent oracles for the event-free shoreline operator only."""
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
import math
import unittest

import shoreline as s


@dataclass(frozen=True)
class NativeState:
    shape: tuple
    cell_area_m2: tuple
    bedrock_m: tuple
    bed_solid_m3: tuple
    liquid_m3: tuple
    suspended_solid_m3: tuple
    solid_density_kg_m3: float = 2700.
    water_density_kg_m3: float = 1000.
    time_years: float = 3.

    @property
    def bed_m(self):
        return tuple(b + v/a for b, v, a in zip(self.bedrock_m, self.bed_solid_m3, self.cell_area_m2))


def native(bed=(3., 1.), area=None, cover=None, water=None, solids=None, shape=None):
    n = len(bed)
    area = tuple([100.] * n if area is None else area)
    cover = tuple([0.] * n if cover is None else cover)
    return NativeState((1, n) if shape is None else shape, area,
                       tuple(z-h for z, h in zip(bed, cover)),
                       tuple(h*a for h, a in zip(cover, area)),
                       tuple([0.] * n if water is None else water),
                       tuple([0.] * n if solids is None else solids))


def controls(**changes):
    result = dict(receivers=[1, -1], link_lengths_m=[10., 0.],
                  contributing_area_m2=[100., 200.], pool_owner=[None, None],
                  pool_stages_m={}, incipient_pool_cells=[], external_outlets=[1],
                  runoff_m_year=[1., 0.], sediment_k_per_year=0., rock_k_per_year=0.,
                  cover_scale_m=1., settling_m_year=0., dt_years=.1)
    result.update(changes)
    return result


def pool_controls(**changes):
    result = controls(pool_owner=[None, "pool"], pool_stages_m={"pool": 2.}, external_outlets=[])
    result.update(changes)
    return result


class ShorelineTests(unittest.TestCase):
    def test_actual_pinned_capture_state_interface(self):
        from r3_bindings import capture
        initial = capture.CaptureState(**native().__dict__)
        result, report = s.channel_trial(initial, **controls(rock_k_per_year=.01))
        self.assertIsInstance(result, capture.CaptureState)
        self.assertEqual(result.liquid_m3, initial.liquid_m3)
        self.assertEqual(result.suspended_solid_m3, initial.suspended_solid_m3)
        self.assertEqual(result.time_years, initial.time_years)
        self.assertEqual(report["status"], "PASS_NUMERICAL_TRIAL_ONLY")

    def test_hand_rock_source_and_settling_balance(self):
        initial = native()
        result, report = s.channel_trial(initial, **controls(rock_k_per_year=.01, settling_m_year=1.))
        # A=100, slope=.2, sqrt(Ac)=10 -> Er=.02 m/yr;
        # Qw=100, Qs=2/(1+1)=1 m3/yr, D=.01 m/yr.
        self.assertAlmostEqual(result.bedrock_m[0], 2.998, places=14)
        self.assertAlmostEqual(result.bed_solid_m3[0], .1, places=14)
        self.assertAlmostEqual(report["rock_debit_solid_m3"][0], .2, places=14)
        self.assertAlmostEqual(report["external_solid_export_m3"], .1, places=14)
        self.assertAlmostEqual(report["external_liquid_export_m3"], 10., places=14)
        self.assertLess(abs(report["solid_volume_residual_m3"]), report["solid_volume_tolerance_m3"])

    def test_decimal_independent_mixed_cover_oracle(self):
        initial = native(cover=[.3, 0.])
        result, report = s.channel_trial(initial, **controls(
            rock_k_per_year=.005, sediment_k_per_year=.01, settling_m_year=5.,
            incoming_liquid_m3_year=[2., 0.], incoming_solid_m3_year=[.25, 0.]))
        with localcontext() as context:
            context.prec = 60
            D = Decimal
            exposed = (-D('.3')).exp()
            er = D('.005') * D(10) * D('.2') * exposed
            es = D('.01') * D(10) * D('.2') * (1-exposed)
            qs = (D('.25') + D(100)*(er+es)) / (1+D(5)*100/102)
            deposited = D(5)*qs/102
            expected_rock = D('2.7') - er*D('.1')
            expected_cover = D(30) + (deposited-es)*100*D('.1')
        self.assertAlmostEqual(result.bedrock_m[0], float(expected_rock), places=14)
        self.assertAlmostEqual(result.bed_solid_m3[0], float(expected_cover), places=13)
        self.assertAlmostEqual(report["sediment_outflux_m3_year"][0], float(qs), places=14)

    def test_shore_crossing_does_not_replace_bed_gradient_or_area(self):
        state1 = native(water=[0., 100.])
        state2 = native(water=[0., 150.])
        c1 = pool_controls(rock_k_per_year=.01, settling_m_year=1.)
        c2 = dict(c1, pool_stages_m={"pool": 2.5})
        a, ra = s.channel_trial(state1, **c1)
        b, rb = s.channel_trial(state2, **c2)
        pa, pb = ra["pool_ports"][0], rb["pool_ports"][0]
        self.assertEqual(a.bedrock_m, b.bedrock_m)
        self.assertEqual(a.bed_solid_m3, b.bed_solid_m3)
        self.assertEqual(pa["suspended_solid_m3"], pb["suspended_solid_m3"])
        ca, cb = pa["shoreline_connector"], pb["shoreline_connector"]
        self.assertEqual(ca["distance_from_source_m"], 5.)
        self.assertEqual(cb["distance_from_source_m"], 2.5)
        self.assertEqual(ca["bed_slope"], .2)
        self.assertEqual(ca["source_area_m2"], 100.)
        self.assertEqual((ca["connector_area_m2"], ca["connector_storage_m3"]), (0., 0.))
        self.assertAlmostEqual(ra["rock_debit_solid_m3"][0], .2, places=14)

    def test_paired_ports_and_pool_local_runoff_are_disjoint(self):
        state = native(water=[0., 100.])
        result, report = s.channel_trial(state, **pool_controls(
            runoff_m_year=[1., 2.], incoming_liquid_m3_year=[0., 5.],
            incoming_solid_m3_year=[0., .2]))
        self.assertEqual(report["pool_local_runoff_source_cells"], [1])
        self.assertEqual(report["pool_local_runoff_m3"], 20.)
        self.assertEqual(report["dry_local_runoff_m3"], 10.)
        self.assertEqual(report["pool_liquid_transfer_m3"], 10.5)
        self.assertAlmostEqual(report["pool_suspended_transfer_m3"], .02, places=15)
        self.assertEqual(len(report["pool_ports"]), 2)
        self.assertEqual({p["kind"] for p in report["pool_ports"]},
                         {"dry_channel_shoreline", "explicit_boundary_to_pool"})
        self.assertEqual(result.liquid_m3, state.liquid_m3)
        self.assertEqual(result.suspended_solid_m3, state.suspended_solid_m3)
        self.assertEqual(report["liquid_volume_residual_m3"], 0.)

    def test_incipient_bottom_receives_phases_without_bed_deposition(self):
        state = native()
        result, report = s.channel_trial(state, **pool_controls(
            pool_stages_m={"pool": 1.}, incipient_pool_cells=[1],
            incoming_liquid_m3_year=[1., 0.], incoming_solid_m3_year=[.25, 0.]))
        self.assertEqual(result, state)
        self.assertAlmostEqual(report["pool_ports"][0]["liquid_m3"], 10.1, places=14)
        self.assertEqual(report["pool_ports"][0]["suspended_solid_m3"], .025)
        self.assertEqual(report["incipient_pool_cells"], [1])
        self.assertEqual(report["pool_ports"][0]["shoreline_connector"]["fraction_from_source"], 1.)

    def test_incipient_local_runoff_not_a_channel_debit(self):
        state = native()
        result, report = s.channel_trial(state, **pool_controls(
            pool_stages_m={"pool": 1.}, incipient_pool_cells=[1],
            runoff_m_year=[0., 1.], rock_k_per_year=10., sediment_k_per_year=10.))
        self.assertEqual(result, state)
        self.assertEqual(report["pool_ports"], [])
        self.assertEqual(report["pool_local_runoff_m3"], 10.)
        self.assertEqual(report["rock_debit_solid_m3"], [0., 0.])

    def test_no_inflow_does_not_invent_pool(self):
        state = native()
        result, report = s.channel_trial(state, **controls(runoff_m_year=0., external_outlets=[]))
        self.assertEqual(result, state)
        self.assertEqual(report["pool_ports"], [])
        with self.assertRaisesRegex(s.ShorelineError, "no actual positive"):
            s.channel_trial(state, **pool_controls(pool_stages_m={"pool": 1.},
                incipient_pool_cells=[1], runoff_m_year=0.))

    def test_positive_flow_unowned_pit_is_not_legacy_terminal_deposit(self):
        state = native()
        with self.assertRaisesRegex(s.ShorelineError, "incipient-pool ownership"):
            s.channel_trial(state, **controls(external_outlets=[],
                incoming_liquid_m3_year=[1., 0.], incoming_solid_m3_year=[1., 0.]))
        self.assertEqual(state.bed_solid_m3, (0., 0.))

    def test_zero_length_and_inconsistent_connectors_reject(self):
        for eta, water, message in ((3., 200., "zero-length"), (3.1, 210., "ownership conflicts")):
            with self.subTest(eta=eta), self.assertRaisesRegex(s.ShorelineError, message):
                s.channel_trial(native(water=[0., water]), **pool_controls(pool_stages_m={"pool": eta}))

    def test_resting_zero_head_margin_preserves_original_relief_link(self):
        state = native(water=[0., 200.])
        result, report = s.channel_trial(state, **pool_controls(
            pool_stages_m={"pool": 3.}, runoff_m_year=0.,
            sediment_k_per_year=1., rock_k_per_year=1.))
        self.assertEqual(result, state)
        self.assertEqual(report["pool_ports"], [])
        self.assertEqual(report["rock_debit_solid_m3"], [0., 0.])
        self.assertEqual(len(report["active_links"]), 1)
        link = report["active_links"][0]
        self.assertEqual((link["old_drop_m"], link["bed_slope"]), (2., .2))
        self.assertEqual(link["shoreline_transfer_status"], "ZERO_FLOW_NO_TRANSFER_POINT")
        self.assertNotIn("shoreline_connector", link)
        with self.assertRaisesRegex(s.ShorelineError, "relative link relief"):
            s.check_relief(state.bed_m, (3., 1.5), report["active_links"])

    def test_zero_local_runoff_with_positive_upstream_flow_still_rejects_zero_head(self):
        state = native(bed=[4., 3., 1.], water=[0., 0., 200.])
        kwargs = pool_controls(receivers=[1, 2, -1], link_lengths_m=[10., 10., 0.],
            contributing_area_m2=[100., 200., 300.], pool_owner=[None, None, "pool"],
            pool_stages_m={"pool": 3.}, runoff_m_year=[1., 0., 0.])
        with self.assertRaisesRegex(s.ShorelineError, "zero-length"):
            s.channel_trial(state, **kwargs)
        kwargs.update(runoff_m_year=[0., 0., 0.], incoming_liquid_m3_year=[1., 0., 0.])
        with self.assertRaisesRegex(s.ShorelineError, "zero-length"):
            s.channel_trial(state, **kwargs)
        kwargs["incoming_liquid_m3_year"] = [0., 0., 0.]
        result, report = s.channel_trial(state, **kwargs)
        self.assertEqual(result, state)
        self.assertEqual(len(report["active_links"]), 2)
        self.assertEqual(report["water_discharge_m3_year"], [0., 0., 0.])

    def test_zero_discharge_does_not_excuse_submerged_dry_ownership(self):
        with self.assertRaisesRegex(s.ShorelineError, "ownership conflicts"):
            s.channel_trial(native(water=[0., 210.]), **pool_controls(
                pool_stages_m={"pool": 3.1}, runoff_m_year=0.))

    def test_zero_water_cannot_carry_suspension(self):
        with self.assertRaisesRegex(s.ShorelineError, "dry suspended"):
            s.channel_trial(native(), **controls(runoff_m_year=0., incoming_solid_m3_year=[1., 0.]))
        with self.assertRaisesRegex(s.ShorelineError, "no transporting liquid"):
            s.channel_trial(native(water=[0., 100.]), **pool_controls(
                incoming_solid_m3_year=[0., 1.]))

    def test_zero_limits_preserve_stocks(self):
        for runoff, ks, kr, cover, velocity in ((0., 1., 1., [.3, 0.], 5.),
                (1., 0., 0., [.3, 0.], 5.), (1., 1., 0., [0., 0.], 5.)):
            state = native(cover=cover)
            result, report = s.channel_trial(state, **controls(runoff_m_year=runoff,
                sediment_k_per_year=ks, rock_k_per_year=kr, settling_m_year=velocity))
            self.assertEqual(result, state)
            self.assertEqual(report["rock_debit_solid_m3"], [0., 0.])
            self.assertEqual(report["dry_deposition_solid_m3"], [0., 0.])

    def test_zero_settling_exports_all_eroded_and_incoming_solid(self):
        result, report = s.channel_trial(native(), **controls(rock_k_per_year=.01,
            incoming_liquid_m3_year=[1., 0.], incoming_solid_m3_year=[2., 0.]))
        self.assertEqual(result.bed_solid_m3, (0., 0.))
        self.assertAlmostEqual(report["external_solid_export_m3"], .4, places=14)

    def test_tributaries_and_external_runoff_are_counted_once(self):
        state = native(bed=[4., 3., 2., 1.], shape=(2, 2))
        result, report = s.channel_trial(state, **controls(receivers=[3, 3, 3, -1],
            link_lengths_m=[math.sqrt(200.), 10., 10., 0.],
            contributing_area_m2=[100., 100., 100., 400.], pool_owner=[None]*4,
            external_outlets=[3], runoff_m_year=[1., 2., 0., 3.],
            incoming_liquid_m3_year=[1., 0., 0., 0.], incoming_solid_m3_year=[.5, 0., 0., 0.]))
        self.assertEqual(result, state)
        self.assertEqual(report["water_discharge_m3_year"][3], 601.)
        self.assertEqual(report["external_liquid_export_m3"], 60.1)
        self.assertEqual(report["external_solid_export_m3"], .05)
        self.assertEqual(len(report["active_links"]), 3)

    def test_native_variable_area_is_used_for_debits_and_runoff(self):
        state = native(area=[3., 7.])
        _, report = s.channel_trial(state, **controls(contributing_area_m2=[3., 10.], rock_k_per_year=.01))
        self.assertAlmostEqual(report["rock_debit_solid_m3"][0], .01*math.sqrt(3)*.2*3*.1, places=15)
        self.assertAlmostEqual(report["external_liquid_export_m3"], .3, places=15)

    def test_post_pool_guard_keeps_old_dry_receiver_link(self):
        state = native(water=[0., 100.])
        _, report = s.channel_trial(state, **pool_controls())
        self.assertTrue(report["post_pool_relief_check_required"])
        self.assertEqual(s.check_relief(state.bed_m, (3., 1.4), report["active_links"])["status"], "PASS")
        with self.assertRaisesRegex(s.ShorelineError, "relative link relief"):
            s.check_relief(state.bed_m, (3., 1.5), report["active_links"])

    def test_zero_flow_links_still_participate_in_final_guard(self):
        state = native(water=[0., 100.])
        _, report = s.channel_trial(state, **pool_controls(runoff_m_year=0.))
        self.assertEqual(len(report["active_links"]), 1)
        self.assertEqual(report["pool_ports"], [])
        with self.assertRaisesRegex(s.ShorelineError, "relative link relief"):
            s.check_relief(state.bed_m, (3., 1.5), report["active_links"])

    def test_original_relief_and_link_identity_must_match(self):
        for links in ([{"source_cell": 0, "receiver_cell": 1, "old_drop_m": 1.}],
                      [{"source_cell": 0, "receiver_cell": 1, "old_drop_m": 2.}]*2):
            with self.assertRaises(s.ShorelineError):
                s.check_relief((3., 1.), (3., 1.), links)
        with self.assertRaises(s.ShorelineError):
            s.check_relief((1., 1.), (1., 1.), [{"source_cell": 0, "receiver_cell": 1, "old_drop_m": 0.}])

    def test_dry_guard_and_exhausted_cover_fail_without_mutation(self):
        state = native()
        with self.assertRaisesRegex(s.ShorelineError, "relative link relief"):
            s.channel_trial(state, **controls(rock_k_per_year=1., dt_years=1.))
        covered = native(cover=[.001, 0.])
        with self.assertRaisesRegex(s.ShorelineError, "trial bed solids"):
            s.channel_trial(covered, **controls(sediment_k_per_year=100., dt_years=1.))
        self.assertEqual(state.bedrock_m, (3., 1.))

    def test_existing_phases_require_consistent_pool_geometry(self):
        with self.assertRaisesRegex(s.ShorelineError, "dry source"):
            s.channel_trial(native(water=[0., 100.]), **controls())
        with self.assertRaisesRegex(s.ShorelineError, "stage conflicts"):
            s.channel_trial(native(water=[0., 50.]), **pool_controls())
        with self.assertRaisesRegex(s.ShorelineError, "positive depth"):
            s.channel_trial(native(), **pool_controls())

    def test_positive_suspension_occupies_pool_capacity(self):
        state = native(water=[0., 90.], solids=[0., 10.])
        result, _ = s.channel_trial(state, **pool_controls())
        self.assertEqual(result.suspended_solid_m3, state.suspended_solid_m3)
        self.assertEqual(result.liquid_m3, state.liquid_m3)
        with self.assertRaisesRegex(s.ShorelineError, "stage conflicts"):
            s.channel_trial(state, **pool_controls(pool_stages_m={"pool": 1.9}))

    def test_invalid_raw_graph_and_area_reject(self):
        cases = ({"receivers": [0, -1]}, {"receivers": [1, 0], "link_lengths_m": [10., 10.]},
                 {"link_lengths_m": [0., 0.]}, {"link_lengths_m": [10., 1.]},
                 {"contributing_area_m2": [99., 200.]}, {"external_outlets": [1, 1]})
        for patch in cases:
            with self.subTest(patch=patch), self.assertRaises(s.ShorelineError):
                s.channel_trial(native(), **controls(**patch))
        with self.assertRaises(s.ShorelineError):
            s.channel_trial(native(bed=[2., 2.]), **controls())

    def test_bad_scalars_and_resource_envelope_fail_closed(self):
        for value in (True, -1., math.nan, math.inf, 10**1000):
            with self.subTest(value=str(value)[:20]), self.assertRaises(s.ShorelineError):
                s.channel_trial(native(), **controls(dt_years=value))
        for patch in ({"runoff_m_year": [1.]}, {"pool_owner": [None, True]},
                      {"pool_stages_m": {"unused": 1.}}, {"incipient_pool_cells": [0]},
                      {"incoming_liquid_m3_year": True}):
            with self.subTest(patch=patch), self.assertRaises(s.ShorelineError):
                s.channel_trial(native(), **controls(**patch))
        with self.assertRaisesRegex(s.ShorelineError, "envelope"):
            s.channel_trial(replace(native(), shape=(1, 4097)), **controls())
        with self.assertRaisesRegex(s.ShorelineError, "identity inventory"):
            s.channel_trial(native(water=[0., 100.]), **pool_controls(
                pool_owner=[None, 1], pool_stages_m={1.0: 2.}))

    def test_extreme_and_unrepresentable_trials_are_controlled_failures(self):
        for patch in ({"rock_k_per_year": 1e308}, {"rock_k_per_year": .01, "dt_years": 1e-300},
                      {"runoff_m_year": 1e-323, "dt_years": 5e-324}, {"settling_m_year": 1e308}):
            with self.subTest(patch=patch), self.assertRaises(s.ShorelineError):
                s.channel_trial(native(), **controls(**patch))

    def test_dry_euler_refines_to_independent_bed_exponential(self):
        # Bare source above fixed external toe: dz/dt=-Kr*sqrt(Ac)/L*z.
        errors = []
        for steps in (10, 20, 40):
            state = native(bed=[2., 0.])
            for _ in range(steps):
                state, _ = s.channel_trial(state, **controls(rock_k_per_year=.05, dt_years=1/steps))
            errors.append(abs(state.bed_m[0] - 2*math.exp(-.05)))
        orders = [math.log(a/b, 2) for a, b in zip(errors, errors[1:])]
        self.assertTrue(all(.99 < order < 1.02 for order in orders), (errors, orders))

    def test_purity_restart_and_scope_flags(self):
        state = native()
        initial = state
        cfg = controls(rock_k_per_year=.01)
        for _ in range(10):
            state, report = s.channel_trial(state, **cfg)
        restarted = initial
        for _ in range(5):
            restarted, _ = s.channel_trial(restarted, **cfg)
        restarted = replace(restarted)
        for _ in range(5):
            restarted, _ = s.channel_trial(restarted, **cfg)
        self.assertEqual(state, restarted)
        self.assertEqual(initial.bedrock_m, (3., 1.))
        self.assertEqual(state.time_years, initial.time_years)
        for key in ("persistent_phases_changed", "time_advanced", "spatial_cut_cell_erosion",
                    "hydraulics_solved", "production_authorized"):
            self.assertIs(report[key], False)
        self.assertEqual(report["physical_validation"], "NOT_ESTABLISHED")


if __name__ == "__main__":
    unittest.main()
