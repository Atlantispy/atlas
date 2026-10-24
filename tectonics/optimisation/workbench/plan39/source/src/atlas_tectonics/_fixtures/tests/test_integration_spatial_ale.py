"""Predeclared exact GCL controls; no physical error tolerance is fitted.

The bounded circulation must retain supplied intervals, close each material
node exactly, retain through-flow cells with zero endpoint volumes, enforce
each signed wall partition and refuse infeasibility/resource exhaustion.
The actual source control uses a deliberately coarse, explicitly loose volume
enclosure; it establishes connection/coverage, not spatial accuracy.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from contextlib import contextmanager
import unittest

from atlas_tectonics import integration_spatial_ale as A
from atlas_tectonics import integration_exterior_mesh as E
from atlas_tectonics import integration_volume_bounds as B
from atlas_tectonics import integration_volume as V
from atlas_tectonics import integration_wall_measures as W
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def cell(key, start, end, kind='exterior', **kwargs):
    return dict(cell_id=key, kind=kind, start_volume_bounds_m3=list(map(E._enc, start)),
                end_volume_bounds_m3=list(map(E._enc, end)), **kwargs)


def face(key, a, b, low, high=None, **kwargs):
    return dict(face_id=key, donor=a, receiver=b,
                volume_bounds_m3=list(map(E._enc, (low, low if high is None else high))), **kwargs)


class ExactSpatialGCL(unittest.TestCase):
    def test_outer_exact_sign_split_is_not_a_velocity_correction(self):
        # u(x)=x on [-1,1], unit face area: exact +/- means are 1/4.
        # Two represented symmetric samples have a deliberately different
        # positive-part quadrature but exactly the same affine field/net zero.
        row = dict(normals=(Q(-3, 4), Q(3, 4)), raw_normals=(Q(-3, 4), Q(3, 4)),
            weights=(Q(1, 2), Q(1, 2)), area_m2=Q(1), duration_s=Q(1))
        audit = A._audit_outer_face(row, row['normals'], (Q(1, 4), Q(1, 4)),
            speed_scale=Q(1), absolute_limit=Q(0), relative_limit=Q(0), budget=WorkBudget(8 << 20))
        self.assertEqual(audit['total_normal_correction_bound_m_s'], 0)
        self.assertEqual(audit['positive_part_quadrature_difference_m3'], Q(-1, 8))
        self.assertEqual(audit['negative_part_quadrature_difference_m3'], Q(-1, 8))

    def test_outer_actual_field_change_and_net_arithmetic_use_original_gates(self):
        eps = Q(1, 10**18)
        row = dict(normals=(Q(1),), raw_normals=(1-eps,), weights=(Q(1),),
                   area_m2=Q(1), duration_s=Q(1))
        # Already-used eps + actual sample-to-field eps + net quadrature eps.
        physical = (1+eps,)
        audit = A._audit_outer_face(row, physical, (1+2*eps, Q(0)), speed_scale=Q(1),
            absolute_limit=3*eps, relative_limit=3*eps, budget=WorkBudget(8 << 20))
        self.assertEqual(audit['total_normal_correction_bound_m_s'], 3*eps)
        for absolute, relative in ((2*eps, Q(1)), (Q(1), 2*eps)):
            with self.assertRaisesRegex(V.VolumeError, 'ORIGINAL'):
                A._audit_outer_face(row, physical, (1+2*eps, Q(0)), speed_scale=Q(1),
                    absolute_limit=absolute, relative_limit=relative, budget=WorkBudget(8 << 20))

    def test_explicit_native_projection_closes_and_preserves_opposed_streams(self):
        eps = Q(1, 10**18)
        row = dict(donor='a', receiver='b', normals=(-1+eps, 1+eps), raw_normals=(Q(-1), Q(1)),
                   weights=(Q(1, 2), Q(1, 2)), area_m2=Q(1), duration_s=Q(1))
        values, audit = A._project_native(['a', 'b'], [row], dict(a=Q(0), b=Q(0)),
            speed_scale=Q(1), absolute_limit=3*eps, relative_limit=3*eps, budget=WorkBudget(8 << 20))
        self.assertEqual(values[0]['positive'], Q(1, 2))
        self.assertEqual(values[0]['negative'], Q(1, 2))
        self.assertEqual(values[0]['normal_increment_m_s'], -eps)
        self.assertEqual(values[0]['total_normal_correction_bound_m_s'], 2*eps)
        self.assertFalse(audit['source_normal_samples_changed'])
        self.assertEqual(row['normals'], (-1+eps, 1+eps))

    def test_native_projection_uses_total_original_allowance_and_fixed_wall(self):
        eps = Q(1, 10**18)
        row = dict(donor='a', receiver='b', normals=(1+eps,), raw_normals=(Q(1),),
                   weights=(Q(1),), area_m2=Q(1), duration_s=Q(1))
        for absolute, relative in ((eps, 1), (1, eps)):
            with self.assertRaisesRegex(V.VolumeError, 'ORIGINAL'):
                A._project_native(['a', 'b'], [row], dict(a=Q(-1), b=Q(1)), speed_scale=Q(1),
                    absolute_limit=absolute, relative_limit=relative, budget=WorkBudget(8 << 20))
        with self.assertRaisesRegex(V.VolumeError, 'nonzero global'):
            A._project_native(['a', 'b'], [row], dict(a=Q(-1), b=1+eps), speed_scale=Q(1),
                absolute_limit=Q(1), relative_limit=Q(1), budget=WorkBudget(8 << 20))

    def test_joint_selection_closes_every_node_inside_original_bounds(self):
        record = dict(cells=[cell('a', (1, 1), (Q(1, 4), Q(3, 4))),
                            cell('b', (1, 1), (Q(5, 4), Q(7, 4)))],
                      face_intervals=[face('ab', 'a', 'b', Q(1, 4), Q(3, 4))])
        result = A._close_record(record, dict(a=Q(1), b=Q(1)), WorkBudget(8 << 20))
        self.assertEqual(result['original_face_intervals'], record['face_intervals'])
        volume = W._decode(result['transfers'][0]['volume_m3'])
        self.assertLessEqual(Q(1, 4), volume); self.assertLessEqual(volume, Q(3, 4))
        ends = {r['cell_id']: W._decode(r['end_volume_m3']) for r in result['cells']}
        self.assertEqual(ends, dict(a=1-volume, b=1+volume))

    def test_zero_endpoint_transit_cell_and_signed_wall_partition_survive(self):
        rows = [cell('a', (1, 1), (0, 0)), cell('transit', (0, 0), (0, 0)),
                cell('native', (1, 1), (2, 2), 'collar'),
                cell('port', (0, 0), (0, 0), 'algebraic-port', collar_cell_id='native')]
        edges = [face('at', 'a', 'transit', 1), face('tp', 'transit', 'port', Q(1, 2), Q(3, 2)),
                 face('pn', 'port', 'native', 1, partition_total=True)]
        result = A._close_record(dict(cells=rows, face_intervals=edges), dict(a=Q(1), native=Q(1)), WorkBudget(8 << 20))
        self.assertEqual({r['cell_id'] for r in result['cells']}, {'a', 'transit', 'native'})
        self.assertEqual([(r['donor'], r['receiver'], W._decode(r['volume_m3'])) for r in result['transfers']],
                         [('a', 'transit', 1), ('transit', 'native', 1)])
        self.assertEqual(result['selected_face_representatives'][-1]['volume_m3'], E._enc(1))

    def test_infeasible_native_flux_is_not_given_divergence_slack(self):
        record = dict(cells=[cell('a', (1, 1), (1, 1), 'collar'), cell('b', (1, 1), (1, 1), 'collar')],
                      face_intervals=[face('ab', 'a', 'b', Q(1, 10**30))])
        with self.assertRaisesRegex(A.GCLInfeasible, 'no exact GCL') as failure:
            A._close_record(record, dict(a=Q(1), b=Q(1)), WorkBudget(8 << 20))
        self.assertEqual(failure.exception.incoming_lower_m3-failure.exception.outgoing_upper_m3, Q(1, 10**30))
        self.assertEqual(failure.exception.unsatisfied_m3, Q(1, 10**30))

    def test_budget_refusal_releases_exact_graph_workspace(self):
        budget = WorkBudget(128)
        with self.assertRaises(MemoryLimitError), B._Arena(budget) as arena:
            A._circulation(['a', 'b'], [('a', 'b', Q(0), Q(1))], arena)
        self.assertEqual(budget.reserved_bytes, 0)


@contextmanager
def actual_spatial_fixture(*, close=True):
        from threadpoolctl import threadpool_limits
        from test_integration_collar_geometry import fixture, fund
        from test_regional_collar3d import native_driving
        from atlas_tectonics.regional_collar3d import RigidCollarMotion
        with threadpool_limits(1), fixture() as (source, owner, collar, budget):
            funding = fund(source, owner, collar, budget)
            parent = collar.initial_state_from_funding(funding, owner)
            omega, dt = (0., 0., 1/64), Q(1, 64)
            wall = W.measure_walls(funding, source[0], collar, parent_state_id='initial-spatial-source',
                start_time_s=source[1].time_s, end_time_s=Q(source[1].time_s)+dt,
                angular_velocity_rad_s=omega, max_volume_error_m3=Q(1, 10000), max_leaves=256, budget=budget)
            motion = RigidCollarMotion(omega, 'test:actual prescribed common rigid motion')
            stage = collar.source_flow_stage(parent, float(dt), rigid_motion=motion, wall_measures=wall,
                **native_driving(collar.interior_velocity(motion)))
            boxes = collar.cell_geometries(); base = boxes[0]
            radius = Q(source[0].network.sphere.radius_m)
            offset = tuple(sum(base.basis[k][j]*base.origin_m[k] for k in range(3)) for j in range(3))
            lines = tuple(tuple(sorted({-radius-offset[j], -offset[j], radius-offset[j],
                *(v for box in boxes for v in (box.lower_m[j], box.upper_m[j]))})) for j in range(3))
            # Topology/ownership control only: two source cones, two endpoints,
            # each enclosed by the whole (2R)^3 box gives 32R^3 as a declared
            # coarse physical-volume uncertainty. No accuracy inference.
            bounds = A.enclose_spatial_ale(funding, source[0], collar, wall, stage, grid_lines=lines,
                max_volume_error_m3=32*radius**3, max_leaves=64, budget=budget)
            record = bounds.record(); starts = {}
            from atlas_tectonics.integration_collar_geometry import _partition
            for remainder in funding.exterior_remainder():
                key = [remainder['patch_id'], remainder['sublayer']]
                rows = [r for r in record['cells'] if r.get('source_key') == key]
                values = _partition([tuple(map(W._decode, r['start_volume_bounds_m3'])) for r in rows],
                                    W._decode(remainder['stocks']['volume_m3']))
                starts.update((r['cell_id'], v) for r, v in zip(rows, values))
            for row in record['cells']:
                if row['kind'] == 'collar':
                    starts[row['cell_id']] = boxes[row['index']].volume_m3
            graph = A.close_spatial_ale(bounds, starts, budget=budget) if close else None
            case = dict(source=source, owner=owner, collar=collar, budget=budget, funding=funding,
                parent=parent, wall=wall, stage=stage, bounds=bounds, starts=starts, graph=graph,
                grid_lines=lines, boxes=boxes)
            # Caller controls the lifetime of construction evidence. Retaining
            # hidden generator aliases would accumulate a second complete
            # interval's geometry while a continuation owns its actual fields.
            del parent, wall, stage, bounds, starts, graph, boxes, record, rows, values
            yield case


class SourceSpatialGCL(unittest.TestCase):
    def test_actual_funding_native_flow_and_rigid_spatial_graph(self):
        with actual_spatial_fixture() as case:
            graph, stage, funding = (case[k] for k in ('graph', 'stage', 'funding'))
            boxes, budget = case['boxes'], case['budget']
            saved = graph.record()
            self.assertEqual(saved['source_flow_stage_id'], stage.result_id)
            self.assertEqual(saved['flow_id'], stage.flow.flow_id)
            self.assertEqual(saved['component_keys'], funding.descriptor()['component_keys'])
            projection = saved['native_flux_projection']
            self.assertFalse(projection['source_normal_samples_changed'])
            self.assertEqual(projection['source_flow_id'], stage.flow.flow_id)
            self.assertLessEqual(W._decode(projection['total_normal_correction_bound_m_s']),
                                 W._decode(projection['absolute_limit_m_s']))
            self.assertEqual({r['index'] for r in saved['cells'] if r['kind'] == 'collar'}, set(range(len(boxes))))
            self.assertGreater(sum(W._decode(r['volume_m3']) for r in saved['transfers']), 0)
            balance = {r['cell_id']: W._decode(r['start_volume_m3'])-W._decode(r['end_volume_m3']) for r in saved['cells']}
            for row in saved['transfers']:
                v = W._decode(row['volume_m3']); balance[row['donor']] -= v; balance[row['receiver']] += v
            self.assertFalse(any(balance.values()))
            print('actual spatial ALE:', dict(cells=len(saved['cells']), transfers=len(saved['transfers']),
                encoded_bytes=len(graph._json), peak_reserved_bytes=budget.peak_reserved_bytes,
                total_normal_correction_bound_m_s=float(W._decode(projection['total_normal_correction_bound_m_s'])),
                absolute_limit_m_s=float(W._decode(projection['absolute_limit_m_s'])),
                relative_limit=float(W._decode(projection['relative_limit']))))


if __name__ == '__main__':
    unittest.main()
