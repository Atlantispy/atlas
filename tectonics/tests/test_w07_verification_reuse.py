"""Live geology verification with workflow-owned producer contexts."""
from concurrent.futures import CancelledError
from threading import Event
import unittest
from unittest.mock import patch

from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.regional_geology import bind_regional_geology
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.w07_workflow import PreparedW07Workflow, _cancel, _hash
from test_w07_geology import geology_fixture
import test_w07_workflow as fixture


class FreshGeologyVerificationWorkflow(PreparedW07Workflow):
    """Retained pre-optimisation verification path; scientific code is identical."""
    def _check(self, cancel=None):
        import threading
        if self._closed or threading.get_ident() != self._owner:
            raise TectonicsError('closed or wrong-thread W07 workflow')
        _cancel(cancel)
        self._context.verify()
        self.geology.verify(cancel=cancel)
        if _hash(self._definition) != self.plan_id:
            raise TectonicsError('W07 source/policy changed; prepare a new workflow')


class GeologyVerificationReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        state, options = geology_fixture()
        cls.geology = bind_regional_geology(state, **options)

    def test_fresh_and_borrowed_verify_identical_content_without_owning_context(self):
        geology = self.geology
        before = (geology.result_id, geology._metadata, geology._fields)
        with ExecutionContext(geology.descriptor()['execution_backend']) as context:
            geology.verify()
            geology.verify(context=context)
            geology.verify(context=context)
            self.assertFalse(context._closed)
        self.assertEqual((geology.result_id, geology._metadata, geology._fields), before)

    def test_wrong_backend_untyped_and_closed_context_refuse(self):
        with self.assertRaisesRegex(TectonicsError, 'same-backend'):
            self.geology.verify(context=object())
        with ExecutionContext('scipy') as wrong:
            with self.assertRaisesRegex(TectonicsError, 'same-backend'):
                self.geology.verify(context=wrong)
        context = ExecutionContext('reference')
        context.close()
        with self.assertRaisesRegex(TectonicsError, 'closed'):
            self.geology.verify(context=context)

    def test_source_loaded_method_and_identity_changes_refuse(self):
        with ExecutionContext('reference') as context:
            with patch('atlas_tectonics.reuse._source_bytes', return_value={}):
                with self.assertRaisesRegex(TectonicsError, 'source changed'):
                    self.geology.verify(context=context)
            with patch('atlas_tectonics.regional_geology._profile_physics', lambda value: {}):
                with self.assertRaisesRegex(TectonicsError, 'loaded implementation changed'):
                    self.geology.verify(context=context)
            with patch.object(context, '_identity', 'different-execution'):
                with self.assertRaisesRegex(TectonicsError, 'source/runtime changed'):
                    self.geology.verify(context=context)

    def test_content_hash_and_cancellation_are_still_checked(self):
        with ExecutionContext('reference') as context:
            original = self.geology._fields
            name, shape, raw = original[0]
            object.__setattr__(self.geology, '_fields', ((name, shape, raw[:-1]+bytes([raw[-1]^1])), *original[1:]))
            try:
                with self.assertRaisesRegex(TectonicsError, 'identity mismatch'):
                    self.geology.verify(context=context)
            finally:
                object.__setattr__(self.geology, '_fields', original)
            event = Event(); event.set()
            with self.assertRaises(CancelledError):
                self.geology.verify(cancel=event, context=context)

    def test_all_workflow_routes_match_complete_outputs_with_live_reuse(self):
        for route in ('steady', 'thermal', 'surface'):
            outputs = []
            for cls in (FreshGeologyVerificationWorkflow, PreparedW07Workflow):
                owner = WorkBudget(128 << 20)
                with patch.object(fixture, 'PreparedW07Workflow', cls):
                    with fixture.make_workflow_fixture(route, thermal=route == 'thermal', budget=owner) as plan:
                        output = plan.run()
                        outputs.append((fixture.output_signature(output),
                            tuple((obj.array_names, tuple(obj.array(n).tobytes() for n in obj.array_names))
                                  for obj in (output.state, output.mechanics))))
                        borrowed = plan._geology_context
                        self.assertEqual(borrowed.backend, plan.geology.descriptor()['execution_backend'])
                        self.assertFalse(borrowed._closed)
                    self.assertTrue(borrowed._closed)
                self.assertEqual(owner.reserved_bytes, 0)
            with self.subTest(route=route):
                self.assertEqual(outputs[0], outputs[1])

    def test_verifier_constructor_failure_releases_owner_admission(self):
        owner = WorkBudget(4 << 20)
        with self.assertRaises(MemoryLimitError):
            PreparedW07Workflow(self.geology, (0.,), route='steady', scales=fixture.SCALES,
                boundary_motion=fixture.W07BoundaryMotion('source-translation', fixture.SOURCE),
                physical_mean_pressure_pa=10., budget=owner)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_closed_workflow_verifier_refuses_latest_hit_and_cleanup_releases_owner(self):
        owner = WorkBudget(128 << 20)
        with fixture.make_workflow_fixture('steady', budget=owner) as plan:
            # Closed producer verifier must also refuse a previously completed hit.
            plan.run()
            plan._geology_context.close()
            with self.assertRaisesRegex(TectonicsError, 'closed'):
                plan.run()
        self.assertEqual(owner.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
