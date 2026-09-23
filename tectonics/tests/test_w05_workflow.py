"""Bounded W05 persistence/continuation checks, not another physics sweep."""
from concurrent.futures import CancelledError
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import math
import sys
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_array_equal

from atlas_tectonics import (ColumnGrid1D, ListricGeometry, MaterialCohort,
    PreparedListricExtension, ExtensionSupportPolicy, FlexureParameters,
    PreparedExtensionWorkflow)
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression, StoreError


POLICY = ExtensionSupportPolicy(FlexureParameters('synthetic-elastic', 'workflow control',
    12., 1., 0., 4., 1.), 2., .5, .2, 1e-5, 'synthetic-support')
TIMES = (0., 1., 2., 3.)
LIMITS = StoreLimits(4096, 1024*1024, 16*1024*1024)


class InterruptingStore(ArrayStore):
    """Inject one interruption INSIDE the inherited publication transaction."""
    fail = False

    def put(self, invocation, arrays, metadata=None, **kwargs):
        check = kwargs.pop('publication_check', None)
        def publication_check():
            if check is not None:
                check()
            if self.fail:
                self.fail = False
                raise CancelledError('synthetic interruption before commit')
        return super().put(invocation, arrays, metadata, publication_check=publication_check, **kwargs)


class W05WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = ExecutionContext('reference')

    @classmethod
    def tearDownClass(cls):
        cls.context.close()

    def motion(self, budget, **changes):
        args = dict(velocity_m_s=.2, density_kg_m3=2., width_m=2.,
            cohorts=(MaterialCohort('a', 'rock', 'source-a', -5.),
                     MaterialCohort('b', 'rock', 'source-b', None)), fractions=(.25, .75),
            time_s=0., epoch_id='test-epoch', datum_id='initial-flat-surface', source_id='test-extension',
            backend='reference', context=self.context, budget=budget)
        args.update(changes)
        return PreparedListricExtension(ColumnGrid1D(np.linspace(-16., 24., 81), frame_id='test-frame'),
            ListricGeometry(10., 3., math.atan(1.5), 0., 'test-geometry'), **args)

    def store(self, path, budget, cls=ArrayStore):
        return cls(path, limits=LIMITS, compression=Compression(), budget=budget)

    def equal(self, a, b):
        self.assertEqual(a.checkpoint_id, b.checkpoint_id)
        self.assertEqual(a.state.state_id, b.state.state_id)
        self.assertEqual(a.support.result_id, b.support.result_id)
        self.assertEqual(a.state.material.descriptor(), b.state.material.descriptor())
        assert_array_equal(a.state.material.thickness_m, b.state.material.thickness_m)
        assert_array_equal(a.state.exchange_m2, b.state.exchange_m2)
        assert_array_equal(a.support.cell_means, b.support.cell_means)
        assert_array_equal(a.support.face_centre_response, b.support.face_centre_response)

    def test_all_outputs_restart_and_verified_warm_reuse(self):
        budget = WorkBudget(64*1024*1024)
        with TemporaryDirectory() as tmp, self.motion(budget) as motion:
            with PreparedExtensionWorkflow(motion, POLICY, TIMES, budget=budget) as direct:
                expected = [direct.run(through=i) for i in range(len(TIMES))]
            path = Path(tmp)/'run.db'
            with self.store(path, budget) as store, PreparedExtensionWorkflow(motion, POLICY, TIMES,
                    store=store, budget=budget) as workflow:
                self.assertIsNone(workflow.load(0))
                self.equal(expected[1], workflow.run(through=1))
                self.assertEqual(store.statistics()['snapshots'], 2)
            # Recreate preparations too, not just reload into the original runner.
            with self.motion(budget) as restarted, self.store(path, budget) as store:
                with PreparedExtensionWorkflow(restarted, POLICY, TIMES, store=store) as workflow:
                    self.equal(expected[-1], workflow.run())
                    for i, output in enumerate(expected):
                        self.equal(output, workflow.load(i))
                    count = 0
                    def profile(frame, event, arg):
                        nonlocal count
                        if event == 'call' and frame.f_code.co_name in ('solve', '_characteristic'):
                            count += 1
                    sys.setprofile(profile)
                    try:
                        self.equal(expected[-1], workflow.run())
                    finally:
                        sys.setprofile(None)
                    self.assertEqual(count, 0, 'warm output must not repeat motion or flexure')
                    self.assertEqual(store.statistics()['snapshots'], 4)
                    for a in (workflow.load(3).support.cell_means, workflow.load(3).state.exchange_m2):
                        with self.assertRaises(ValueError):
                            a.setflags(write=True)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_interrupted_publication_is_atomic_and_restartable(self):
        budget = WorkBudget(64*1024*1024)
        with TemporaryDirectory() as tmp, self.motion(budget) as motion:
            path = Path(tmp)/'run.db'
            with self.store(path, budget, InterruptingStore) as store, PreparedExtensionWorkflow(
                    motion, POLICY, TIMES, store=store) as workflow:
                first = workflow.run(through=0)
                before = store.statistics()
                store.fail = True
                with self.assertRaises(CancelledError):
                    workflow.run(through=1)
                self.assertFalse(store.contains(workflow.checkpoint_id(1)))
                self.assertEqual(workflow._current.state.state_id, first.state.state_id)
                self.assertEqual(store.statistics()['unique_chunks'], before['unique_chunks'])
            with self.store(path, budget) as store, PreparedExtensionWorkflow(motion, POLICY, TIMES,
                    store=store) as workflow, PreparedExtensionWorkflow(motion, POLICY, TIMES) as direct:
                self.equal(direct.run(), workflow.run())

    def test_corrupt_payload_is_not_silently_recomputed(self):
        budget = WorkBudget(64*1024*1024)
        with TemporaryDirectory() as tmp, self.motion(budget) as motion, self.store(Path(tmp)/'run.db', budget) as store:
            with PreparedExtensionWorkflow(motion, POLICY, TIMES, store=store) as workflow:
                workflow.run(through=0)
                store._db.execute('UPDATE chunks SET payload=?', (b'broken',))
                with self.assertRaises(StoreError):
                    workflow.run()

    def test_relabelled_complete_output_and_invalid_schema_are_refused(self):
        budget = WorkBudget(64*1024*1024)
        with TemporaryDirectory() as tmp, self.motion(budget) as motion, self.store(Path(tmp)/'run.db', budget) as store:
            with PreparedExtensionWorkflow(motion, POLICY, TIMES, store=store) as workflow:
                first = workflow.run(through=0)
                arrays = store.get(first.checkpoint_id)
                meta = store.metadata(first.checkpoint_id)
                store.put(workflow.checkpoint_id(1), arrays, meta)
                with self.assertRaisesRegex(TectonicsError, 'binding'):
                    workflow.load(1)
                wrong = dict(meta)
                wrong['invocation'] = workflow._invocation(2)
                wrong['intervals'] = 2
                store.put(workflow.checkpoint_id(2), arrays, wrong)
                with self.assertRaises(TectonicsError):
                    workflow.load(2)

    def test_source_change_and_foreign_schedule_cannot_reuse(self):
        budget = WorkBudget(64*1024*1024)
        with TemporaryDirectory() as tmp, self.motion(budget) as motion, self.store(Path(tmp)/'run.db', budget) as store:
            with PreparedExtensionWorkflow(motion, POLICY, TIMES, store=store) as workflow:
                workflow.run(through=0)
                with mock.patch.object(PreparedExtensionWorkflow, '_pack', lambda *args: None):
                    with self.assertRaisesRegex(TectonicsError, 'implementation changed'):
                        workflow.load(0)
                with PreparedExtensionWorkflow(motion, POLICY, (0., 1., 4.), store=store) as other:
                    self.assertNotEqual(workflow.checkpoint_id(0), other.checkpoint_id(0))
                    self.assertIsNone(other.load(0))
            with self.motion(budget, source_id='different-source') as other_motion:
                with PreparedExtensionWorkflow(other_motion, POLICY, TIMES, store=store) as other:
                    self.assertIsNone(other.load(0))

    def test_missing_prior_output_is_a_visible_error(self):
        budget = WorkBudget(64*1024*1024)
        with TemporaryDirectory() as tmp, self.motion(budget) as motion, self.store(Path(tmp)/'run.db', budget) as store:
            with PreparedExtensionWorkflow(motion, POLICY, TIMES, store=store) as workflow:
                workflow.run(through=1)
                store._db.execute('DELETE FROM snapshots WHERE id=?', (workflow.checkpoint_id(0),))
                with self.assertRaisesRegex(TectonicsError, 'missing requested'):
                    workflow.run()

    def test_schedule_resource_cancel_and_lifetime_guards(self):
        budget = WorkBudget(64*1024*1024)
        with self.motion(budget) as motion:
            for times in ((), (1., 1.), (-1., 1.), (2., 1.), (float('nan'),), tuple(range(257))):
                with self.subTest(times=times[:3]), self.assertRaises(TectonicsError):
                    PreparedExtensionWorkflow(motion, POLICY, times)
            child = WorkBudget(1, parent=budget)
            before = budget.reserved_bytes
            with self.assertRaises(MemoryLimitError):
                PreparedExtensionWorkflow(motion, POLICY, TIMES, budget=child)
            self.assertEqual(budget.reserved_bytes, before)
            with self.assertRaises(TectonicsError):
                PreparedExtensionWorkflow(motion, POLICY, TIMES, budget=WorkBudget(64*1024*1024))
            event = Event(); event.set()
            with self.assertRaises(CancelledError):
                PreparedExtensionWorkflow(motion, POLICY, TIMES, cancel=event)
            with PreparedExtensionWorkflow(motion, POLICY, TIMES) as workflow:
                with self.assertRaises(CancelledError):
                    workflow.run(cancel=event)
                for index in (-1, 4, True):
                    with self.assertRaises(TectonicsError):
                        workflow.run(through=index)
                workflow.run()
                with self.assertRaises(TectonicsError):
                    workflow.run(through=0)
            with self.assertRaisesRegex(TectonicsError, 'closed'):
                workflow.run()
            # Workflow close does not close the borrowed motion.
            motion.advance(motion.initial, time_s=1.)
        self.assertEqual(budget.reserved_bytes, 0)


if __name__ == '__main__':
    unittest.main()
