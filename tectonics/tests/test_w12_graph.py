"""Public graph adapter guards with a tiny fake plan; no physical solves."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import w12_graph


class FakePlan:
    def __init__(self):
        self.plan_id = '1'*64
        self.context = dict(world_id='SYNTHETIC', snapshot_id='fake-final',
            calendar_id='seconds-from-test-epoch', spatial_frame_id='test-strip',
            vertical_reference='test-depth-datum', scenario_id='fake-plan')
        self.field = np.frombuffer(np.array([1., 2., 4.], dtype='<f8').tobytes(), dtype='<f8')
        self.product = dict(schema='atlas.fake-tectonics-product.v1', plan_id=self.plan_id,
            context=deepcopy(self.context), source_status='WORKING NON-CANON',
            data_id=hashlib.sha256(self.field.tobytes()).hexdigest(),
            accounts=dict(physical_owner='supplied synthetic test', unknown_heat=True),
            limitations=['No physical acceptance'], restart=dict(checkpoint_id='2'*64))
        self.run_count = self.read_count = self.verification_count = 0
        self.valid = self.available = True
        self.fail_product_verification_at = None

    def verify(self):
        if not self.valid:
            raise ValueError('fake current source changed')

    def run(self, output_index=None):
        if output_index is not None:
            raise AssertionError('adapter must request the declared final output')
        self.run_count += 1
        return deepcopy(self.product)

    def verify_product(self, value):
        self.verify()
        self.verification_count += 1
        if self.verification_count == self.fail_product_verification_at:
            raise ValueError('fake downstream native bytes unavailable')
        if not self.available:
            raise ValueError('fake native bytes unavailable')
        if value != self.product:
            raise ValueError('fake product/context mismatch')

    def read_fields(self, value):
        self.read_count += 1
        return {'displacement_m': self.field}

    def statistics(self):
        return dict(computed_outputs=self.run_count)


class W12GraphTests(unittest.TestCase):
    def test_explicit_dependency_consumes_fields_and_preserves_provenance(self):
        plan = FakePlan()
        before = set(sys.modules)
        result = w12_graph.run_graph(plan)
        self.assertEqual(result['graph']['status'], 'EXECUTED')
        self.assertEqual(result['execution']['computed_stage_ids'], ['tectonics', 'inspect'])
        self.assertEqual(result['product'], plan.product)
        self.assertEqual(result['inspection']['source_product'], plan.product)
        field = result['inspection']['fields']['displacement_m']
        self.assertEqual(field, dict(dtype='<f8', shape=[3], nbytes=24,
                                     sha256=plan.product['data_id']))
        self.assertEqual((plan.run_count, plan.read_count), (1, 1))
        self.assertFalse(result['physical_acceptance'])
        self.assertFalse(result['graph']['production_authorised'])
        self.assertFalse(result['graph']['category_closure']['plate_tectonics']['domain_acceptance_declared'])
        added = set(sys.modules)-before
        self.assertFalse(any('generator_upgrade_r31' in name or 'native_terrain_r5' in name
                             or name.endswith('generator_upgrade_r24.registry') for name in added))

    def test_authenticated_warm_restore_verifies_both_native_products_without_physics(self):
        plan = FakePlan()
        with tempfile.TemporaryDirectory() as directory:
            first = w12_graph.run_graph(plan, graph_cache_root=Path(directory)/'cache')
            checks = plan.verification_count
            warm = w12_graph.run_graph(plan, graph_cache_root=Path(directory)/'cache')
        self.assertEqual(first['graph'], warm['graph'])
        self.assertEqual(first['binding'], warm['binding'])
        self.assertEqual(warm['execution']['reused_stage_ids'], ['tectonics', 'inspect'])
        self.assertEqual(warm['execution']['computed_stage_ids'], [])
        self.assertEqual(plan.verification_count-checks, 2)
        self.assertEqual((plan.run_count, plan.read_count), (1, 1))

    def test_missing_native_payload_refuses_even_when_graph_cache_exists(self):
        plan = FakePlan()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'cache'
            w12_graph.run_graph(plan, graph_cache_root=cache)
            plan.available = False
            with self.assertRaisesRegex(ValueError, 'native bytes unavailable'):
                w12_graph.run_graph(plan, graph_cache_root=cache)
        self.assertEqual(plan.run_count, 1)

    def test_downstream_cache_hit_independently_verifies_native_payload(self):
        plan = FakePlan()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'cache'
            w12_graph.run_graph(plan, graph_cache_root=cache)
            plan.fail_product_verification_at = plan.verification_count+2
            with self.assertRaisesRegex(ValueError, 'downstream native bytes unavailable'):
                w12_graph.run_graph(plan, graph_cache_root=cache)
        self.assertEqual(plan.run_count, 1)

    def test_source_and_context_mismatch_refuse(self):
        stale = FakePlan(); stale.valid = False
        with self.assertRaisesRegex(ValueError, 'current source changed'):
            w12_graph.run_graph(stale)
        self.assertEqual(stale.run_count, 0)
        wrong = FakePlan()
        wrong.product['context']['vertical_reference'] = 'foreign-datum'
        expected = deepcopy(wrong.product)
        expected['context'] = deepcopy(wrong.context)
        with patch.object(wrong, 'verify_product', side_effect=lambda value:
                          (_ for _ in ()).throw(ValueError('fake product/context mismatch'))
                          if value != expected else None):
            with self.assertRaisesRegex(ValueError, 'product/context mismatch'):
                w12_graph.run_graph(wrong)

    def test_adapter_source_drift_refuses_before_plan_run(self):
        plan = FakePlan()
        with patch.object(w12_graph, '_ADAPTER_EXECUTED_SHA256', '0'*64):
            with self.assertRaisesRegex(ValueError, 'adapter source changed'):
                w12_graph.run_graph(plan)
        self.assertEqual(plan.run_count, 0)

    def test_mutable_field_refuses_before_inspection_publication(self):
        plan = FakePlan(); plan.field = plan.field.copy()
        with self.assertRaisesRegex(ValueError, 'immutable contiguous'):
            w12_graph.run_graph(plan)


if __name__ == '__main__':
    unittest.main()
