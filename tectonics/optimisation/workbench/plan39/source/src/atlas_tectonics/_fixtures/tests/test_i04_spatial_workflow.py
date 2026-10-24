"""One actual spatial owner/adoption/store seam, not a resolution campaign.

Use the existing physical ALE fixture once. Keep its declared coarse geometry
errors, native projection limits and 256 MiB budget. Numerical field allowances
are fixed BEFORE joint outcomes at the existing transport factor 1e-10 times
the first actual donor plus funded exterior absolute stocks, in kg/J/kg-history.
The second interval cannot widen those allowances. This is not an accuracy
claim for the coarse physical or thermal geometry.
SPDX-License-Identifier: AGPL-3.0-only
"""
from concurrent.futures import CancelledError
from fractions import Fraction as Q
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from threadpoolctl import threadpool_limits

import i02_workflow_fixtures as F2
from test_integration_collar_geometry import fixture as fresh_collar_fixture
from test_integration_spatial_ale import actual_spatial_fixture
from test_regional_collar3d import native_driving
from atlas_tectonics import integration_exterior_mesh as E
from atlas_tectonics import integration_spatial_ale as A
from atlas_tectonics import integration_wall_measures as W
from atlas_tectonics.integration_collar_geometry import FullCellFunding
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.integration_regional_workflow import CollarWorkflow, retained_inventory_accounts
from atlas_tectonics.integration_spatial_owner import PreparedSpatialOwner
from atlas_tectonics.regional_collar3d import RigidCollarMotion
from atlas_tectonics.storage import StoreConflict


def allowances(case):
    """A pre-solve field-unit contract, never fitted to the observed residual."""
    donor = case['stage'].inventory
    values = {f'component_mass_kg:{i}': sum((abs(Q(float(v))) for v in a.flat), Q(0))
              for i, a in enumerate(donor.array('component_mass_kg'))}
    values.update({k: sum((abs(Q(float(v))) for v in donor.array(k).flat), Q(0))
                   for k in donor.array_names if k != 'component_mass_kg'})
    keys = tuple(map(tuple, case['funding'].descriptor()['component_keys']))
    for row in case['funding'].exterior_remainder():
        stock = row['stocks']; at = keys.index((row['patch_id'], row['sublayer']))
        values[f'component_mass_kg:{at}'] += abs(W._decode(stock['mass_kg']))
        values['enthalpy_j'] += abs(W._decode(stock['enthalpy_j']))
        values['tracer:source_kappa'] += abs(W._decode(stock['source_kappa_mass_kg']))
    return {k: v/Q(10**10) for k, v in values.items()}


def thermal_mesh(case, wall, endpoint):
    radius = Q(case['source'][0].network.sphere.radius_m)
    # Existing elementary pi<4 whole-sphere bound from the mesh control.
    return E.build_exterior_mesh(case['funding'], case['source'][0], wall,
        grid_lines=case['grid_lines'], max_geometry_volume_error_m3=32*radius**3/3,
        max_leaves=64, budget=case['budget'], endpoint=endpoint)


def next_interval(case, workflow):
    dt, omega = Q(1, 64), (0., 0., 1/64)
    outer = workflow.exterior_state
    wall = W.measure_walls(case['funding'], case['source'][0], case['collar'],
        parent_state_id=outer.state_id, start_time_s=outer.time_s, end_time_s=Q(outer.time_s)+dt,
        angular_velocity_rad_s=omega, prior_trajectory=outer.record()['trajectory']['segments'],
        max_volume_error_m3=Q(1, 10000), max_leaves=256, budget=case['budget'])
    motion = RigidCollarMotion(omega, 'test:actual prescribed common rigid motion')
    source = workflow.source_flow_stage(float(dt), wall_measures=wall, rigid_motion=motion,
        **native_driving(case['collar'].interior_velocity(motion)))
    radius = Q(case['source'][0].network.sphere.radius_m)
    bounds = A.enclose_spatial_ale(case['funding'], case['source'][0], case['collar'], wall, source,
        grid_lines=case['grid_lines'], max_volume_error_m3=32*radius**3,
        max_leaves=64, budget=case['budget'])
    return source, bounds, thermal_mesh(case, wall, 'end'), wall


def payload_identity(arrays):
    return {k: (v.dtype.str, v.shape, hashlib.sha256(v.tobytes()).hexdigest()) for k, v in arrays.items()}


def operations(collar):
    def strip(value):
        return {k: strip(v) for k, v in value.items() if k != 'budget'} if isinstance(value, dict) else value
    return tuple(strip(p.statistics()) for p in (collar._native, collar._transport, collar._heat))


def exact_fields(snapshot):
    totals = {f'component_mass_kg:{i}': sum((Q(float(v)) for v in a.flat), Q(0))
              for i, a in enumerate(snapshot.array('component_mass_kg'))}
    totals.update({k: sum((Q(float(v)) for v in snapshot.array(k).flat), Q(0))
                   for k in snapshot.array_names if k != 'component_mass_kg'})
    return totals


def check_global_accounts(test, before_exterior, source, result):
    """Exact physical inventories plus separate cumulative numerical accounts."""
    def complete(collar_state, exterior_state):
        report = retained_inventory_accounts(collar_state, exterior_state, budget=exterior_state._budget)
        return {name: W._decode(value) for name, value in report['accounted'].items()}

    old = complete(source.parent, before_exterior)
    new = complete(result.state, result.exterior.state)
    before, donor = exact_fields(source.parent.fields), exact_fields(source.inventory)
    booked = {k: donor[k]-before[k] for k in before}
    audit = result.collar.source_stage.source_audit
    total = lambda name: sum((Q(float(v)) for v in audit.array(name).flat), Q(0))
    test.assertEqual(booked['enthalpy_j'], total('enthalpy_after_sources_j')-total('enthalpy_before_sources_j'))
    test.assertEqual(booked['tracer:accumulated_strain_ii'],
                     total('strain_history_after_sources_kg')-total('strain_history_before_kg'))
    for name, value in booked.items():
        if name not in ('enthalpy_j', 'tracer:accumulated_strain_ii'):
            test.assertEqual(value, 0, name)  # This Newtonian control has no other source.
    heat = result.exterior._heat.descriptor()
    outgoing = W._decode(heat['exact_outward_boundary_energy_j'])
    heating = W._decode(heat['exact_source_energy_j'])
    test.assertEqual(outgoing, 0)
    test.assertEqual(heating, 0)  # Native sources have already been booked once.
    requested = total('requested_source_energy_j')
    source_addition_rounding = requested-booked['enthalpy_j']
    for name in old:
        expected = old[name]+booked[name]
        if name == 'enthalpy_j':
            expected = old[name]+requested-source_addition_rounding+heating-outgoing
        test.assertEqual(new[name], expected, name)


class SpatialStore(unittest.TestCase):
    def test_closed_native_plans_rebuild_and_continue_from_saved_fields(self):
        """Fresh prepared objects, not just a new connection around warm plans.

        Compare the full second publication with the uninterrupted proposal,
        retained as metadata and array digests after an injected write refusal.
        Only initial admission operands and grid lines survive the old fixture;
        no stage, state, wall measure or solver object drives the restarted step.
        This exercises common-trajectory recovery, not differential acceptance
        or isolation in a separate operating-system process.
        """
        with tempfile.TemporaryDirectory() as directory, threadpool_limits(1):
            path = Path(directory)/'fresh-plans.sqlite'
            with actual_spatial_fixture(close=False) as case:
                budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
                admission = funding.descriptor()
                admission_fields = {k: a.copy() for k, a in funding.arrays().items()}
                grid_lines = case['grid_lines']
                mesh0 = thermal_mesh(case, case['wall'], 'start')
                with PreparedSpatialOwner(funding, collar, case['bounds'], mesh0,
                        method='implicit-upwind', max_projection_errors=allowances(case),
                        budget=budget) as exterior:
                    for name in ('stage', 'bounds', 'graph', 'parent', 'wall', 'starts', 'boxes'):
                        case.pop(name)
                    del mesh0
                    with F2.store(path) as store, CollarWorkflow.create(store, collar, case['owner'],
                            funding, budget=budget, exterior_owner=exterior) as workflow:
                        identity = workflow.workflow_id
                        first_args = next_interval(case, workflow)
                        initial_exterior = workflow.exterior_state
                        first = workflow.advance_spatial(*first_args[:3], wall_measures=first_args[3])
                        check_global_accounts(self, initial_exterior, first_args[0], first)
                        first_inspection = workflow.inspect()
                        first_record = workflow.exterior_state.record()
                        first_fields = payload_identity(workflow.exterior_state.arrays())
                        native_state = workflow.state.native_state
                        first_native = payload_identity({k: native_state.array(k) for k in native_state.array_names})
                        first_audit = workflow.source_audit.result_id
                        del first, first_args, initial_exterior, native_state
                        second_args = next_interval(case, workflow)
                        proposed = {}

                        def refuse(key, arrays, metadata, **_):
                            proposed.update(key=key, arrays=payload_identity(arrays), metadata=metadata)
                            raise StoreConflict('retain uninterrupted second proposal only')

                        with patch.object(store, 'put', side_effect=refuse), self.assertRaises(StoreConflict):
                            workflow.advance_spatial(*second_args[:3], wall_measures=second_args[3])
                        self.assertTrue(proposed)
                        self.assertEqual(workflow.inspect(), first_inspection)
                        self.assertEqual(store.statistics()['snapshots'], 2)
                        del second_args
                    old_owner, old_collar = case['owner'], collar
                    old_plans = (collar._native, collar._transport, collar._heat)
                old_exterior = exterior
            # Every old prepared object has actually closed before any fresh
            # object is admitted. Keep references only to assert non-reuse.
            for old in (old_owner, old_collar, old_exterior, *old_plans):
                self.assertTrue(old._closed)
            old_budget = budget
            del case, funding, workflow, exterior, collar, budget
            with fresh_collar_fixture() as (source, owner, collar, budget):
                self.assertIsNot(budget, old_budget)
                self.assertIsNot(owner, old_owner)
                self.assertIsNot(collar, old_collar)
                for new, old in zip((collar._native, collar._transport, collar._heat), old_plans):
                    self.assertIsNot(new, old)
                # Revalidate the original admission, not the evolved fields.
                # This does not publish/refill a root in the existing store.
                funding = FullCellFunding.restore(admission, admission_fields, *source[:2],
                    collar, owner, budget=budget)
                case = dict(source=source, owner=owner, collar=collar, budget=budget,
                            funding=funding, grid_lines=grid_lines)
                before = operations(collar)
                with F2.store(path) as store:
                    snapshots = store.statistics()['snapshots']
                    with CollarWorkflow.open(store, identity, collar, owner, funding, budget=budget) as workflow:
                        self.assertEqual(operations(collar), before)
                        self.assertEqual(store.statistics()['snapshots'], snapshots)
                        self.assertEqual(workflow.inspect(), first_inspection)
                        self.assertIsNot(workflow._exterior_owner, old_exterior)
                        self.assertEqual(workflow.exterior_state.record(), first_record)
                        self.assertEqual(payload_identity(workflow.exterior_state.arrays()), first_fields)
                        native_state = workflow.state.native_state
                        self.assertEqual(payload_identity({k: native_state.array(k) for k in native_state.array_names}),
                                         first_native)
                        self.assertEqual(workflow.source_audit.result_id, first_audit)
                        args = next_interval(case, workflow)
                        previous = workflow.exterior_state
                        actual = workflow.advance_spatial(*args[:3], wall_measures=args[3])
                        check_global_accounts(self, previous, args[0], actual)
                        self.assertEqual(store.metadata(proposed['key']), proposed['metadata'])
                        self.assertEqual(payload_identity(store.get(proposed['key'], budget=budget)),
                                         proposed['arrays'])
                        self.assertEqual(workflow.inspect()['intervals'], 2)
                        self.assertEqual(workflow.inspect()['time_s'], 2/64)
                        self.assertEqual(store.statistics()['snapshots'], 3)

    def test_actual_joint_fields_are_saved_reopened_and_continued_without_replay(self):
        with actual_spatial_fixture() as case, tempfile.TemporaryDirectory() as directory:
            budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
            mesh0 = thermal_mesh(case, case['wall'], 'start')
            limits = allowances(case)
            with PreparedSpatialOwner(funding, collar, case['bounds'], mesh0,
                    method='implicit-upwind', max_projection_errors=limits, budget=budget) as exterior:
                # Physical initial evidence was consumed and bound by the
                # owner. Do not retain a complete obsolete prototype solve
                # throughout a later interval merely for test convenience.
                for name in ('stage', 'bounds', 'graph', 'parent', 'wall', 'starts', 'boxes'):
                    case.pop(name)
                del mesh0
                path = Path(directory)/'spatial.sqlite'
                with F2.store(path) as store, CollarWorkflow.create(store, collar, case['owner'], funding,
                        budget=budget, exterior_owner=exterior) as workflow:
                    identity = workflow.workflow_id
                    changed_definition = exterior.descriptor()
                    changed_definition['conductivity_w_m_k'] *= 2
                    with self.assertRaisesRegex(TectonicsError, 'actual material/source/plan'):
                        PreparedSpatialOwner.from_saved(funding, collar, changed_definition,
                            exterior.initial_state.record(), exterior.initial_state.arrays(), budget=budget)
                    changed_material = exterior.initial_state.record()
                    row = changed_material['cells'][0]
                    name = next(k for k, v in row['exact'].items()
                                if k.startswith('component_mass_kg:') and W._decode(v) > 0)
                    row['exact'][name] = E._enc(W._decode(row['exact'][name])+1)
                    with self.assertRaisesRegex(TectonicsError, 'initial material was changed'):
                        PreparedSpatialOwner.from_saved(funding, collar, exterior.descriptor(),
                            changed_material, exterior.initial_state.arrays(), budget=budget)
                    del changed_definition, changed_material, row
                    with self.assertRaisesRegex(TectonicsError, 'advance_spatial'):
                        workflow.advance(1/64)
                    first_args = next_interval(case, workflow)
                    initial_exterior = workflow.exterior_state
                    with self.assertRaises(CancelledError):
                        workflow.advance_spatial(*first_args[:3], wall_measures=first_args[3], cancel=lambda: True)
                    self.assertEqual(workflow.inspect()['intervals'], 0)
                    first = workflow.advance_spatial(*first_args[:3], wall_measures=first_args[3])
                    check_global_accounts(self, initial_exterior, first_args[0], first)
                    self.assertEqual(workflow.inspect()['time_s'], 1/64)
                    self.assertEqual(workflow.inspect()['exterior_time_s'], 1/64)
                    self.assertIs(first.collar.transport_stage.spatial_result, first.exterior._transport)
                    self.assertIs(first.collar.heat_stage.joined_result, first.exterior._heat)
                    self.assertTrue(np.all(first.exterior._heat.array('input_source_w') == 0))
                    self.assertNotEqual(exterior.initial_state.record()['cells'], workflow.exterior_state.record()['cells'])
                    head = workflow.inspect()['head']
                    meta, saved = store.metadata(head), store.get(head, budget=budget)
                    self.assertNotIn('thermal_mesh', meta['exterior_state'])
                    self.assertNotIn('spatial_graph', meta['exterior_advance'])
                    self.assertEqual({k.removeprefix('spatial-record:') for k in saved if k.startswith('spatial-record:')},
                                     {'state', 'mesh', 'exchange', 'graph', 'transport', 'heat'})
                    for key, expected in first.exterior.audit_arrays().items():
                        np.testing.assert_array_equal(saved['spatial-audit:'+key], expected)
                    corrupt = dict(first.exterior.audit_arrays())
                    key = 'joined-heat:enthalpy_j'
                    corrupt[key] = corrupt[key].copy(); corrupt[key][0] += 1.
                    with self.assertRaisesRegex(TectonicsError, 'arrays changed'):
                        exterior.validate_exchange(first.exterior.state, first.exterior.record(), audit_arrays=corrupt)
                    with self.assertRaises(TectonicsError):
                        workflow.advance_spatial(*first_args[:3], wall_measures=first_args[3])
                    first_ids = (first.state.result_id, first.exterior.state.state_id,
                                 first.collar.source_stage.source_audit.result_id)
                    # The actual results are verified above and saved in the
                    # immutable store. Only small identities are needed later.
                    del first, first_args, initial_exterior, saved, meta, corrupt, expected
                    second_args = next_interval(case, workflow)
                    proposed = {}

                    def refuse(key, arrays, metadata, **_):
                        proposed.update(key=key, arrays=payload_identity(arrays), metadata=metadata)
                        raise StoreConflict('injected spatial publication refusal')

                    with patch.object(store, 'put', side_effect=refuse), self.assertRaises(StoreConflict):
                        workflow.advance_spatial(*second_args[:3], wall_measures=second_args[3])
                    self.assertEqual(workflow.inspect()['head'], head)
                    self.assertEqual(store.statistics()['snapshots'], 2)
                # Fresh real store connection; accepted advection/heat/physics
                # counters must not change on decode, field restore or audit.
                exterior.close()
                with F2.store(path) as store:
                    before = operations(collar)
                    # RuntimeContext binds the loaded callable inventory, so
                    # mocking geometry functions here would itself invalidate
                    # the scientific plan. Verify operation counts unchanged;
                    # the saved-owner factory has no geometry/source replay.
                    reopened = CollarWorkflow.open(store, identity, collar, case['owner'], funding, budget=budget)
                    with reopened as workflow:
                        self.assertEqual(before, operations(collar))
                        self.assertIsNot(workflow._exterior_owner, exterior)
                        self.assertEqual(workflow._exterior_owner.owner_id, exterior.owner_id)
                        self.assertEqual(workflow.state.result_id, first_ids[0])
                        self.assertEqual(workflow.exterior_state.state_id, first_ids[1])
                        self.assertEqual(workflow.source_audit.result_id, first_ids[2])
                        previous_exterior = workflow.exterior_state
                        actual = workflow.advance_spatial(*second_args[:3], wall_measures=second_args[3])
                        check_global_accounts(self, previous_exterior, second_args[0], actual)
                        self.assertEqual(store.metadata(proposed['key']), proposed['metadata'])
                        saved = store.get(proposed['key'], budget=budget)
                        self.assertEqual(payload_identity(saved), proposed['arrays'])
                        self.assertEqual(workflow.inspect()['intervals'], 2)
                        self.assertEqual(actual.exterior.state.time_s, 2/64)
                        self.assertEqual(workflow.inspect()['time_s'], 2/64)
                        statistics = store.statistics()
                        self.assertEqual(statistics['snapshots'], 3)
                        print('spatial workflow resources:', dict(
                            peak_reserved_work_bytes=budget.peak_reserved_bytes,
                            saved_payload_bytes=sum(a.nbytes for a in saved.values()),
                            spatial_record_bytes=sum(a.nbytes for k, a in saved.items() if k.startswith('spatial-record:')),
                            spatial_audit_bytes=sum(a.nbytes for k, a in saved.items() if k.startswith('spatial-audit:')),
                            **{k: statistics[k] for k in ('snapshots', 'unique_chunks', 'encoded_payload_bytes')}))
                        # This remains a required real-field connection, but
                        # its enclosure must not hide earlier storage/account
                        # failures. Alpha=0 verifies binding, not feedback.
                        from test_i04_spatial_pressure import check_spatial_endpoint
                        pressure_ids = check_spatial_endpoint(case, actual, second_args[3])
                        print('current spatial pressure/force identities:', pressure_ids)
                    self.assertTrue(workflow._exterior_owner._closed)


if __name__ == '__main__':
    unittest.main()
