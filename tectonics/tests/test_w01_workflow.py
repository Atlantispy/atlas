"""Synthetic Stage-7 interface checks, not geological or W03 acceptance.

Inventories and transport expectations below are analytic; fixture descriptions
never assemble the numerical W02 arrays passed to the public workflow.
"""
from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (
    BoundaryRegion, CohortDescription, FeatureGeometry, FeaturePrecedence,
    GeologicalCase, GeologicalProvince, GeologySource, LayerComponent,
    MaterialBoundary, MaterialCohort, RegionalGrid1D, SphericalFrame,
    SurfaceSelector, TectonicsError, build_boundary_network,
)
from atlas_tectonics.regional_forcing import RegionalReduction
from atlas_tectonics.regional_workflow import (
    PoreFluidCohort, PreparedRegionalWorkflow,
    load_regional_workflow, save_regional_workflow,
)
from atlas_tectonics.regional_workflow_geometry import RegionalColumnSupport
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore
from test_w01_geological_description import ROCK, SOURCE, TEMP, WATER, column, layer
from test_w01_initial_sampling import initial
from test_w01_regional_forcing import (
    atlas, box, definition, motion, planar, spherical, store_limits,
)


COHORT_A = MaterialCohort('a', 'rock', 'origin-a', -100.)
COHORT_B = MaterialCohort('b', 'other-rock', 'origin-b', -10.)
LEFT = MaterialBoundary('open', {'a': 4., 'b': 0.}, 'left-reservoir')
RIGHT = MaterialBoundary('open', None, 'right-reservoir')
STEADY_LEFT = MaterialBoundary('open', {'a': 1., 'b': 3.}, 'left-reservoir')


def workflow_fixture(*, cells=3, duration=.25, porosity=0., uniform=False,
                     thermal=True, source=SOURCE, topology=None, epoch='epoch'):
    """A/B depths [1,2,3]/[3,2,1], full width 2 m, total depth 4 m."""
    domain = box(x1=3., y1=2.)
    net = topology or build_boundary_network(domain, (BoundaryRegion('whole', 'A', domain),))
    geometries = tuple(FeatureGeometry('stripe-'+str(i), box(x0=float(i), x1=float(i+1), y1=2.),
                                      'synthetic') for i in (1, 2))
    profiles = tuple(replace(TEMP, profile_id='temperature-'+str(i),
                            temperatures_k=(300. if uniform else 300.+100.*i,)) if thermal else
                     replace(TEMP, profile_id='temperature-'+str(i), mode='unknown',
                             temperatures_k=(), unknown_reason='Not measured in synthetic input.')
                     for i in range(3))
    columns = tuple(column('column-'+str(i), layers=(
        layer('a-layer', thickness=1. if uniform else float(i+1), porosity=porosity,
              components=(LayerComponent('a', 1.),)),
        layer('b-layer', thickness=3. if uniform else float(3-i), porosity=porosity,
              components=(LayerComponent('b', 1.),))),
        profile=profiles[i].profile_id,
        **({'fluid_material_id': 'water'} if porosity else {})) for i in range(3))
    materials = (ROCK, replace(ROCK, material_id='other-rock')) + ((WATER,) if porosity else ())
    case = GeologicalCase(case_id='workflow-synthetic', topology=net, time_s=0., epoch_id=epoch,
        depth_reference_id='local-surface', source_id='synthetic', sources=(source,),
        materials=materials,
        cohorts=(CohortDescription(COHORT_A, 'synthetic'), CohortDescription(COHORT_B, 'synthetic')),
        thermal_profiles=profiles, columns=columns, geometries=geometries,
        provinces=(GeologicalProvince('background', 'column-0', SurfaceSelector('domain'), 'synthetic'),
                   GeologicalProvince('stripe-1', 'column-1', SurfaceSelector('geometry', ('stripe-1',)), 'synthetic'),
                   GeologicalProvince('stripe-2', 'column-2', SurfaceSelector('geometry', ('stripe-2',)), 'synthetic')),
        precedence=FeaturePrecedence(('stripe-2', 'stripe-1', 'background')))
    state = initial(case)
    motions = tuple(motion(p, epoch=epoch) for p in sorted(set(net.plate_ids)))
    return (state, definition(net, motions, epoch_id=epoch, duration_s=duration),
            planar(epoch_id=epoch, origin_m=(0., 1., 0.), length_m=3.),
            RegionalReduction('planar-columns', 'frozen-at-start', SOURCE, 2.),
            RegionalGrid1D(cells, 3.), RegionalColumnSupport('planar-strip', 0., 4., SOURCE))


def spherical_fixture(*, cells=1, hemisphere='north-hemisphere'):
    net = atlas(SphericalFrame(10., 'world'))
    case = GeologicalCase(case_id='spherical-workflow', topology=net, time_s=0., epoch_id='epoch',
        depth_reference_id='radial-surface', source_id='synthetic', sources=(SOURCE,), materials=(ROCK,),
        cohorts=(CohortDescription(COHORT_A, 'synthetic'),), thermal_profiles=(TEMP,),
        columns=(column(layers=(layer(thickness=2., components=(LayerComponent('a', 1.),)),)),),
        provinces=(GeologicalProvince('background', 'continental', SurfaceSelector('domain'), 'synthetic'),),
        precedence=FeaturePrecedence(('background',)))
    d, section = spherical(net, length=5.*math.pi, omega=(0., 0., .01))
    return (initial(case), d, section,
            RegionalReduction('great-circle-columns', 'frozen-at-start', SOURCE, 10.),
            RegionalGrid1D(cells, section.length_m), RegionalColumnSupport(hemisphere, 0., 2., SOURCE))


def cohort_values(state, cohort_id):
    index = next(i for i, c in enumerate(state.material.cohorts) if c.cohort_id == cohort_id)
    return state.material.thickness_m[index]


def lineage(state):
    while state.parent is not None:
        yield state
        state = state.parent


def put_rehashed_workflow_record(store, record):
    """Publish coherent storage bytes to test semantics beyond hash checking."""
    encoded = json.dumps(record, ensure_ascii=True, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    identity = hashlib.sha256(encoded).hexdigest()
    store.put(identity, {'node': np.empty(0, dtype='u1')}, record)
    return identity


class RegionalWorkflowTests(unittest.TestCase):
    def test_mixed_cells_keep_actual_cohort_inventories(self):
        args = workflow_fixture(cells=2)
        with PreparedRegionalWorkflow(*args) as plan:
            state = plan.initialise()
        assert_allclose(cohort_values(state, 'a'), [4./3., 8./3.], rtol=2e-14, atol=0.)
        assert_allclose(cohort_values(state, 'b'), [8./3., 4./3.], rtol=2e-14, atol=0.)
        self.assertAlmostEqual(math.fsum(state.initial_samples.array('phase_volume_m3')), 24.)
        self.assertEqual(state.material.cohorts, (COHORT_A, COHORT_B))
        self.assertEqual(state.material.ages_s(), (100., 10.))
        self.assertEqual(state.steps, 0)
        self.assertIsNone(state.parent)
        self.assertIs(state.initial_samples.state, args[0])

    def test_open_transport_has_independent_analytic_cohort_and_exterior_accounts(self):
        with PreparedRegionalWorkflow(*workflow_fixture(), scheme='upwind') as plan:
            original = plan.initialise()
            result = plan.advance(original, left=LEFT, right=RIGHT)
        assert_array_equal(cohort_values(result, 'a'), [7./4., 7./4., 11./4.])
        assert_array_equal(cohort_values(result, 'b'), [9./4., 9./4., 5./4.])
        assert_array_equal(result.material.total_thickness(), [4., 4., 4.])
        accounts = result.material.transition_record['cohort_accounts_m2']
        self.assertEqual(accounts['a']['inflow_m2'], 1.)
        self.assertEqual(accounts['a']['outflow_m2'], .75)
        self.assertEqual(accounts['b']['inflow_m2'], 0.)
        self.assertEqual(accounts['b']['outflow_m2'], .25)
        self.assertEqual(2.*sum(cohort_values(result, 'a')), 25./2.)
        self.assertEqual(2.*sum(cohort_values(result, 'b')), 23./2.)
        self.assertEqual(result.material.ages_s(), (100.25, 10.25))
        self.assertIs(result.parent, original)
        self.assertEqual(result.material.parent_state_id, original.material.state_id)

    def test_refinement_preserves_description_and_integrated_material(self):
        args = workflow_fixture(cells=2)
        fine_args = args[:4] + (RegionalGrid1D(6, 3.), args[5])
        with PreparedRegionalWorkflow(*args) as coarse, PreparedRegionalWorkflow(*fine_args) as fine:
            a, b = coarse.initialise(), fine.initialise()
        self.assertEqual(a.initial_samples.state.case.definition_id, b.initial_samples.state.case.definition_id)
        self.assertEqual(a.initial_samples.state.case.descriptor(), b.initial_samples.state.case.descriptor())
        for cohort in ('a', 'b'):
            self.assertAlmostEqual(sum(cohort_values(a, cohort))*1.5*2., 12.)
            self.assertAlmostEqual(sum(cohort_values(b, cohort))*.5*2., 12.)

    def test_default_muscl_retains_exact_uniform_case(self):
        with PreparedRegionalWorkflow(*workflow_fixture(uniform=True, duration=.25)) as plan:
            state = plan.initialise()
            result = plan.advance(state, left=STEADY_LEFT, right=RIGHT)
        self.assertEqual(result.scheme, 'muscl')
        assert_array_equal(result.material.thickness_m, state.material.thickness_m)

    def test_multiple_steps_cover_exact_frozen_interval_and_keep_every_parent(self):
        with PreparedRegionalWorkflow(*workflow_fixture(uniform=True, duration=1.1)) as plan:
            start = plan.initialise()
            end = plan.advance(start, left=STEADY_LEFT, right=RIGHT)
            with self.assertRaises(TectonicsError):
                plan.advance(end, left=STEADY_LEFT, right=RIGHT)
        steps = list(lineage(end))
        self.assertEqual(end.material.time_s, 1.1)
        self.assertGreater(len(steps), 1)
        self.assertEqual(end.steps, len(steps))
        self.assertAlmostEqual(math.fsum(s.material.transition_record['duration_s'] for s in steps), 1.1)
        for s in steps:
            self.assertIs(s.initial_samples, start.initial_samples)
            self.assertIs(s.forcing, start.forcing)
            self.assertEqual(s.material.parent_state_id, s.parent.material.state_id)
            self.assertIn('cohort_accounts_m2', s.material.transition_record)

    def test_step_limit_is_cumulative_and_refusal_preserves_parent(self):
        with PreparedRegionalWorkflow(*workflow_fixture(uniform=True, duration=1.1), max_steps=2) as plan:
            first = plan.advance(plan.initialise(), .25, left=STEADY_LEFT, right=RIGHT)
            before = first.material.thickness_m.tobytes()
            with self.assertRaises(TectonicsError):
                plan.advance(first, left=STEADY_LEFT, right=RIGHT)
            self.assertEqual(first.material.thickness_m.tobytes(), before)
            self.assertEqual(first.steps, 1)

    def test_thermal_profile_is_initial_epoch_provenance_after_material_moves(self):
        args = workflow_fixture()
        with PreparedRegionalWorkflow(*args, scheme='upwind') as plan:
            start = plan.initialise()
            end = plan.advance(start, left=LEFT, right=RIGHT)
        assert_array_equal(start.initial_samples.temperature(), [300., 400., 500.])
        self.assertIs(end.initial_samples, start.initial_samples)
        self.assertEqual(end.initial_samples.state.case.thermal_profiles, args[0].case.thermal_profiles)
        self.assertEqual(end.initial_samples.state.cooling_history, args[0].cooling_history)
        self.assertEqual(end.initial_samples.state.case.time_s, 0.)
        self.assertEqual(end.material.time_s, .25)
        self.assertEqual(end.descriptor()['temperature_semantics'],
                         'initial-epoch only; not evolved heat or temperature')
        self.assertFalse(np.array_equal(start.material.thickness_m, end.material.thickness_m))

    def test_explicitly_unsampled_temperature_keeps_unknown_masks(self):
        args = workflow_fixture(thermal=False)
        with self.assertRaises(TectonicsError):
            with PreparedRegionalWorkflow(*args) as plan:
                plan.initialise()
        with PreparedRegionalWorkflow(*args, include_temperature=False) as plan:
            start = plan.initialise()
            end = plan.advance(start, left=LEFT, right=RIGHT)
        self.assertFalse(end.initial_samples.array('temperature_known').any())
        with self.assertRaises(TectonicsError):
            end.initial_samples.temperature()
        self.assertIs(end.initial_samples.state.case.thermal_profiles, start.initial_samples.state.case.thermal_profiles)

    def test_pore_volume_requires_explicit_fluid_cohort_history(self):
        args = workflow_fixture(porosity=.25)
        with self.assertRaises(TectonicsError):
            with PreparedRegionalWorkflow(*args) as plan:
                plan.initialise()
        fluid = MaterialCohort('fluid', 'water', 'explicit-fluid-origin', None)
        mapping = tuple(PoreFluidCohort(u.unit_id, fluid, SOURCE) for u in args[0].units)
        with PreparedRegionalWorkflow(*args, fluid_cohorts=mapping) as plan:
            state = plan.initialise()
        assert_array_equal(cohort_values(state, 'a'), [.75, 1.5, 2.25])
        assert_array_equal(cohort_values(state, 'b'), [2.25, 1.5, .75])
        assert_array_equal(cohort_values(state, 'fluid'), [1., 1., 1.])
        self.assertIsNone(next(c.formation_time_s for c in state.material.cohorts if c.cohort_id == 'fluid'))
        self.assertAlmostEqual(sum(state.initial_samples.array('matrix_volume_m3')), 18.)
        self.assertAlmostEqual(sum(state.initial_samples.array('explicit_pore_volume_m3')), 6.)

    def test_frame_epoch_and_whole_cell_extent_mismatch_refuse(self):
        args = workflow_fixture()
        altered = [args[:2] + (replace(args[2], epoch_id='different'),) + args[3:],
                   args[:2] + (replace(args[2], frame_id='different'),) + args[3:],
                   args[:3] + (replace(args[3], reference_width_m=4.),) + args[4:]]
        for values in altered:
            with self.subTest(section=values[2], reduction=values[3]), self.assertRaises(TectonicsError):
                with PreparedRegionalWorkflow(*values) as plan:
                    plan.initialise()

    def test_hidden_plate_discontinuity_cannot_be_hidden_inside_one_cell(self):
        domain = box(x1=3., y1=2.)
        regions = (BoundaryRegion('left', 'A', box(x1=.25, y1=2.)),
                   BoundaryRegion('hidden', 'B', box(x0=.25, x1=.75, y1=2.)),
                   BoundaryRegion('right', 'A', box(x0=.75, x1=3., y1=2.)))
        net = build_boundary_network(domain, regions)
        args = workflow_fixture(cells=1, topology=net)
        d = definition(net, (motion('A'), motion('B', translation=(2., 0., 0.))))
        with self.assertRaises(TectonicsError):
            with PreparedRegionalWorkflow(args[0], d, *args[2:]) as plan:
                plan.initialise()

    def test_spherical_shell_metric_is_not_radial_thickness_and_refines(self):
        for hemisphere in ('north-hemisphere', 'south-hemisphere'):
            for cells in (1, 2):
                with self.subTest(hemisphere=hemisphere, cells=cells):
                    with PreparedRegionalWorkflow(*spherical_fixture(cells=cells, hemisphere=hemisphere)) as plan:
                        state = plan.initialise()
                    assert_allclose(cohort_values(state, 'a'), 122./75., rtol=3e-14, atol=0.)
                    self.assertAlmostEqual(sum(state.initial_samples.array('phase_volume_m3')), 244.*math.pi/3.)
                    self.assertAlmostEqual(sum(cohort_values(state, 'a'))*(5.*math.pi/cells)*10., 244.*math.pi/3.)

    def test_budget_refusal_and_close_release_all_reservations(self):
        budget = WorkBudget(1)
        with self.assertRaises(MemoryLimitError):
            with PreparedRegionalWorkflow(*workflow_fixture(), budget=budget) as plan:
                plan.initialise()
        self.assertEqual(budget.reserved_bytes, 0)
        budget = WorkBudget(128 << 20)
        with PreparedRegionalWorkflow(*workflow_fixture(), budget=budget) as plan:
            plan.advance(plan.initialise(), left=LEFT, right=RIGHT)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cancellation_before_preparation_and_before_advance(self):
        token = threading.Event()
        token.set()
        budget = WorkBudget(128 << 20)
        with self.assertRaises(CancelledError):
            with PreparedRegionalWorkflow(*workflow_fixture(), budget=budget, cancel=token) as plan:
                plan.initialise()
        self.assertEqual(budget.reserved_bytes, 0)
        token.clear()
        with PreparedRegionalWorkflow(*workflow_fixture(), budget=budget) as plan:
            state = plan.initialise()
            token.set()
            with self.assertRaises(CancelledError):
                plan.advance(state, left=LEFT, right=RIGHT, cancel=token)
            self.assertEqual(state.material.time_s, 0.)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_cold_restore_and_continuation_match_without_resampling(self):
        from atlas_tectonics.precursor_sampling import PreparedPrecursor
        args = workflow_fixture(duration=.75)
        with PreparedRegionalWorkflow(*args) as plan:
            first = plan.advance(plan.initialise(), .25, left=LEFT, right=RIGHT)
            expected = plan.advance(first, left=LEFT, right=RIGHT)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'workflow.db'
            with ArrayStore(path, store_limits()) as store:
                save_regional_workflow(first, store)
            calls = []
            def observe(frame, event, arg):
                if event == 'call' and frame.f_code is PreparedPrecursor.sample_cells.__code__:
                    calls.append(1)
            previous = sys.getprofile()
            try:
                sys.setprofile(observe)
                with ArrayStore(path, store_limits()) as store:
                    restored = load_regional_workflow(store, first.workflow_id)
                with PreparedRegionalWorkflow.from_state(restored) as plan:
                    result = plan.advance(restored, left=LEFT, right=RIGHT)
            finally:
                sys.setprofile(previous)
            # A fresh interpreter must bind the stored execution identity and
            # continue from saved descriptions without the parent's live objects.
            code = '''import json, sys
from atlas_tectonics.regional_workflow import load_regional_workflow, PreparedRegionalWorkflow
from atlas_tectonics.storage import ArrayStore
from test_w01_workflow import LEFT, RIGHT
from test_w01_regional_forcing import store_limits
with ArrayStore(sys.argv[1], store_limits()) as store:
    restored = load_regional_workflow(store, sys.argv[2])
with PreparedRegionalWorkflow.from_state(restored) as plan:
    result = plan.advance(restored, left=LEFT, right=RIGHT)
print(json.dumps([result.workflow_id, result.material.state_id, result.steps]))
'''
            base = Path(__file__).resolve().parents[1]
            env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(base/'src'), str(base/'tests'))),
                       PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
                       MKL_NUM_THREADS='1', NUMBA_NUM_THREADS='1')
            process = subprocess.run([sys.executable, '-B', '-c', code, str(path), first.workflow_id],
                                     env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout),
                             [expected.workflow_id, expected.material.state_id, expected.steps])
        self.assertEqual(calls, [])
        self.assertEqual(restored.workflow_id, first.workflow_id)
        self.assertEqual(restored.initial_samples.state.descriptor(), first.initial_samples.state.descriptor())
        self.assertEqual(result.material.state_id, expected.material.state_id)
        self.assertEqual(result.workflow_id, expected.workflow_id)
        assert_array_equal(result.material.thickness_m, expected.material.thickness_m)
        self.assertEqual(result.material.transition_record, expected.material.transition_record)
        self.assertEqual(result.steps, expected.steps)
        self.assertEqual(result.initial_samples.sample_id, first.initial_samples.sample_id)

    def test_changed_source_identity_cannot_reuse_old_workflow_state(self):
        changed = replace(SOURCE, statement='Changed synthetic source evidence.')
        with PreparedRegionalWorkflow(*workflow_fixture()) as old, \
             PreparedRegionalWorkflow(*workflow_fixture(source=changed)) as new:
            a, b = old.initialise(), new.initialise()
            self.assertNotEqual(a.workflow_id, b.workflow_id)
            with self.assertRaises(TectonicsError):
                new.advance(a, left=LEFT, right=RIGHT)

    def test_loaded_workflow_implementation_change_invalidates_plan_and_resume(self):
        from atlas_tectonics import regional_workflow as workflow
        with PreparedRegionalWorkflow(*workflow_fixture()) as plan:
            state = plan.initialise()
            # Changed loaded instructions must refuse even while source files
            # retain their original bytes. Restore the callable before close.
            with mock.patch.object(workflow, '_initial_material', lambda *args: None):
                with self.assertRaises(TectonicsError):
                    plan.initialise()
                with self.assertRaises(TectonicsError):
                    plan.advance(state, left=LEFT, right=RIGHT)
                with self.assertRaises(TectonicsError):
                    with PreparedRegionalWorkflow.from_state(state):
                        pass

    def test_cached_transport_matches_direct_and_warm_hit_avoids_kernel(self):
        from atlas_tectonics.materials import advect_materials
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'cache.db', store_limits()) as store, \
                 PreparedRegionalWorkflow(*workflow_fixture()) as plan:
                state = plan.initialise()
                direct = plan.advance(state, left=LEFT, right=RIGHT)
                cached = plan.advance(state, left=LEFT, right=RIGHT,
                                      store=store, cache_policy=CachePolicy(mode='always'))
                snapshot_count = store.statistics()['snapshots']
                calls = []
                def observe(frame, event, arg):
                    if event == 'call' and frame.f_code is advect_materials.__code__:
                        calls.append(1)
                previous = sys.getprofile()
                try:
                    sys.setprofile(observe)
                    hit = plan.advance(state, left=LEFT, right=RIGHT,
                                       store=store, cache_policy=CachePolicy(mode='always'))
                finally:
                    sys.setprofile(previous)
                self.assertEqual(store.statistics()['snapshots'], snapshot_count)
                self.assertEqual(calls, [])
                self.assertGreater(snapshot_count, 0)
        for result in (cached, hit):
            self.assertEqual(result.workflow_id, direct.workflow_id)
            self.assertEqual(result.material.state_id, direct.material.state_id)
            self.assertEqual(result.material.transition_record, direct.material.transition_record)
            assert_array_equal(result.material.thickness_m, direct.material.thickness_m)
            self.assertIs(result.parent, state)

    def test_restore_refuses_rehashed_support_that_disagrees_with_sample_cells(self):
        with PreparedRegionalWorkflow(*workflow_fixture()) as plan:
            state = plan.initialise()
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'support.db', store_limits()) as store:
                save_regional_workflow(state, store)
                changed = state.descriptor()
                changed['support']['bottom_depth_m'] = 3.
                identity = put_rehashed_workflow_record(store, changed)
                self.assertEqual(store.metadata(identity), changed)
                with self.assertRaises(TectonicsError):
                    load_regional_workflow(store, identity)

    def test_restore_refuses_valid_material_transport_from_foreign_velocity(self):
        from atlas_tectonics.materials import advect_materials, save_material_state
        with PreparedRegionalWorkflow(*workflow_fixture()) as plan:
            start = plan.initialise()
            valid = plan.advance(start, left=LEFT, right=RIGHT)
        foreign = advect_materials(start.material, 2.*start.forcing.face_velocity_m_s, .25,
            left=LEFT, right=RIGHT, scheme=valid.scheme, backend=valid.backend).state
        self.assertNotEqual(foreign.transition_record['velocity'], valid.material.transition_record['velocity'])
        self.assertEqual(foreign.parent_state_id, start.material.state_id)
        self.assertEqual(foreign.time_s, valid.material.time_s)
        with tempfile.TemporaryDirectory() as directory:
            with ArrayStore(Path(directory)/'foreign-velocity.db', store_limits()) as store:
                save_regional_workflow(valid, store)
                save_material_state(foreign, store)
                changed = valid.descriptor()
                changed['material_state_id'] = foreign.state_id
                identity = put_rehashed_workflow_record(store, changed)
                self.assertEqual(store.metadata(identity), changed)
                with self.assertRaises(TectonicsError):
                    load_regional_workflow(store, identity)

    def test_repeated_initialise_and_steps_reuse_prepared_samples_and_forcing(self):
        from atlas_tectonics.precursor_sampling import PreparedPrecursor
        from atlas_tectonics.regional_forcing import PreparedRegionalForcing
        counts = {'samples': 0, 'faces': 0}
        codes = {PreparedPrecursor.sample_cells.__code__: 'samples', PreparedRegionalForcing.faces.__code__: 'faces'}
        def observe(frame, event, arg):
            if event == 'call' and frame.f_code in codes:
                counts[codes[frame.f_code]] += 1
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            with PreparedRegionalWorkflow(*workflow_fixture(duration=1.1, uniform=True)) as plan:
                start = plan.initialise()
                end = plan.advance(start, left=STEADY_LEFT, right=RIGHT)
                again = plan.initialise()
        finally:
            sys.setprofile(previous)
        self.assertEqual(counts, {'samples': 1, 'faces': 1})
        self.assertEqual(start.workflow_id, again.workflow_id)
        self.assertIs(end.initial_samples, start.initial_samples)

    def test_results_immutable_and_invalid_requested_intervals_refuse(self):
        with PreparedRegionalWorkflow(*workflow_fixture()) as plan:
            state = plan.initialise()
            for duration in (0., -.1, .5, float('nan'), float('inf'), True):
                with self.subTest(duration=duration), self.assertRaises(TectonicsError):
                    plan.advance(state, duration, left=LEFT, right=RIGHT)
            with self.assertRaises(FrozenInstanceError):
                state.steps = 3
            with self.assertRaises(ValueError):
                state.material.thickness_m.setflags(write=True)
            with self.assertRaises(ValueError):
                state.initial_samples.array('phase_volume_m3').setflags(write=True)


if __name__ == '__main__':
    unittest.main()
