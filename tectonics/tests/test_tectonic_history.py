"""Bounded ordered tectonic snapshots and recoverable prefix ownership.

These supplied histories retain each producer's physical meaning. Regional
mechanics remains quasi-static; W04 outputs share one absolute reference.
"""
from concurrent.futures import CancelledError
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np
from numpy.testing import assert_array_equal

from atlas_tectonics import reuse
from atlas_tectonics._validation import TectonicsError
from atlas_tectonics.evolving_flexure import PreparedEvolvingW04Support
from atlas_tectonics.resources import MemoryLimitError, WorkBudget
from atlas_tectonics.storage import ArrayStore, Compression, StoreError, StoreLimits
from atlas_tectonics.tectonic_history import PreparedTectonicHistory, W04HistoryInput
from atlas_tectonics.w03_workflow import advance_w03_columns
from test_evolving_flexure import datum, supplied, PERIODIC
from test_evolving_mechanics import context, prepare as prepare_regional, request
from test_underthrust import fixture as prepare_underthrust
from test_w03_workflow import initialise, workflow_fixture
from test_w04_variable_workflow import ACCURACY, profile
from test_w04_workflow import surface


CAP = 128 * 1024**2
SOURCE = 'supplied synthetic tectonic history; not geological calibration'
ROUTES = ('underthrust', 'w04', 'regional')
LIMITS = StoreLimits(65536, 8 * 1024**2, 64 * 1024**2)


def open_store(path, budget, cls=ArrayStore):
    """Use an explicit raw temporary store under the producer's shared cap."""
    return cls(path, limits=LIMITS,
               compression=Compression(codec='raw', shuffle='none'), budget=budget)


def make_history_case(route, *, budget=None, regional_n=4, cells=8):
    """Return an open borrowed producer and its immutable three-output schedule.

    The caller owns the returned producer. The helper also serves the bounded
    benchmark so its preparation cost is explicit rather than hidden in a cache.
    """
    owner = WorkBudget(CAP) if budget is None else budget
    if route == 'underthrust':
        return prepare_underthrust(budget=owner), (0., .5, 1.)
    if route == 'regional':
        c = context(nx=regional_n, nz=regional_n)
        inputs = tuple(request(replace(c, time_s=float(i)), eta=1.+i,
                               shear=1.+.25*i, gravity=float(i), state='time-'+str(i))
                       for i in range(3))
        return prepare_regional(c, budget=owner), inputs
    if route != 'w04':
        raise ValueError('unknown history fixture route')
    reference = initialise(workflow_fixture(cells=cells, length_m=float(cells)))
    states = [reference]
    for time_s in (1e6, 2e6):
        states.append(advance_w03_columns(states[-1], time_s=time_s,
                                          top_effective_stress_pa=0.))
    inputs = tuple(W04HistoryInput(state,
        surface(state, pressure=np.linspace(0., 10.*i, cells)),
        supplied(state, profile(state, te=np.full(cells, thickness), far=False)))
        for i, (state, thickness) in enumerate(zip(states, (1., 2., 1.5))))
    pressure = 100.*np.sin(2*np.pi*(np.arange(cells)+.5)/cells)
    prepared = PreparedEvolvingW04Support(reference, inputs[0].surface, PERIODIC,
        reference_rigidity=inputs[0].rigidity,
        reference_absolute_load=datum(reference, inputs[0].surface, pressure),
        accuracy=ACCURACY, budget=owner)
    return prepared, inputs


@contextmanager
def make_history_fixture(route, *, budget=None, store=None, source_id=SOURCE, **kwargs):
    prepared, inputs = make_history_case(route, budget=budget, **kwargs)
    with prepared:
        with PreparedTectonicHistory(prepared, inputs, source_id=source_id, store=store) as history:
            yield history


def evaluate(prepared, item):
    if type(item) is W04HistoryInput:
        return prepared.solve(item.state, item.surface,
                              rigidity=item.rigidity, exterior=item.exterior)
    return prepared.evaluate(item)


def result_arrays(result):
    """All published arrays, including geometry and absolute W04 equilibria."""
    if hasattr(result, 'array_names'):
        return {name: result.array(name) for name in result.array_names}
    if hasattr(result, 'absolute_values'):
        return {'values': result.values, 'absolute_values': result.absolute_values}
    return {name: getattr(result, name) for name in (
        'volume_m3', 'mass_kg', 'enthalpy_j', 'boundary_work_j',
        'gravitational_change_j', 'displacement_m')}


class InterruptingStore(ArrayStore):
    """Inject failure inside the real transaction, before publication."""
    failure = None

    def put(self, invocation, arrays, metadata=None, **kwargs):
        check = kwargs.pop('publication_check', None)

        def publication_check():
            if check is not None:
                check()
            if self.failure is not None:
                failure, self.failure = self.failure, None
                raise failure

        return super().put(invocation, arrays, metadata,
                           publication_check=publication_check, **kwargs)


class TectonicHistoryTests(unittest.TestCase):
    def equal_result(self, actual, expected):
        self.assertIs(type(actual), type(expected))
        self.assertEqual(actual.descriptor(), expected.descriptor())
        first, second = result_arrays(actual), result_arrays(expected)
        self.assertEqual(set(first), set(second))
        for name in first:
            self.assertEqual(first[name].shape, second[name].shape)
            self.assertEqual(first[name].dtype, second[name].dtype)
            self.assertEqual(first[name].tobytes(), second[name].tobytes(), name)
        if hasattr(actual, 'polygons'):
            self.assertEqual(tuple(p.geometry_id for p in actual.polygons),
                             tuple(p.geometry_id for p in expected.polygons))

    def equal_output(self, actual, expected):
        self.assertEqual(actual.index, expected.index)
        self.assertEqual(actual.time_s, expected.time_s)
        self.assertEqual(actual.output_id, expected.output_id)
        self.assertEqual(actual.checkpoint_id, expected.checkpoint_id)
        self.assertEqual(actual.descriptor(), expected.descriptor())
        self.equal_result(actual.result, expected.result)

    def test_all_routes_match_direct_complete_outputs_and_detached_descriptors(self):
        for route in ROUTES:
            with self.subTest(route=route):
                prepared, inputs = make_history_case(route)
                with prepared:
                    expected = tuple(evaluate(prepared, item) for item in inputs)
                    with PreparedTectonicHistory(prepared, inputs, source_id=SOURCE) as history:
                        for i, direct in enumerate(expected):
                            output = history.run(through=i)
                            self.equal_result(output.result, direct)
                            self.assertEqual(output.index, i)
                            self.assertEqual(output.checkpoint_id, history.checkpoint_id(i))
                            with self.assertRaises((AttributeError, TectonicsError)):
                                output.index = 99
                            descriptor = output.descriptor()
                            descriptor['caller-injected'] = True
                            self.assertNotIn('caller-injected', output.descriptor())
                        self.assertEqual(history.statistics()['computed_outputs'], 3)

    def test_stopped_resumed_and_warm_histories_preserve_exact_ids_without_replay(self):
        for route in ROUTES:
            owner = WorkBudget(CAP)
            with self.subTest(route=route), TemporaryDirectory() as tmp:
                with make_history_fixture(route, budget=owner) as direct:
                    expected = tuple(direct.run(through=i) for i in range(3))
                path = Path(tmp)/'history.db'
                with open_store(path, owner) as store:
                    with make_history_fixture(route, budget=owner, store=store) as partial:
                        self.assertIsNone(partial.load(0))
                        self.equal_output(partial.run(through=1), expected[1])
                    with make_history_fixture(route, budget=owner, store=store) as resumed:
                        self.equal_output(resumed.run(), expected[2])
                        self.assertEqual(resumed.statistics()['computed_outputs'], 1)
                        self.assertEqual(resumed.statistics()['restored_outputs'], 1)
                        self.assertEqual(store.statistics()['snapshots'], 3)
                        for i, output in enumerate(expected):
                            self.equal_output(resumed.load(i), output)
                    with make_history_fixture(route, budget=owner, store=store) as warm:
                        self.equal_output(warm.run(), expected[2])
                        self.assertEqual(warm.statistics()['computed_outputs'], 0)
                        self.assertEqual(warm.statistics()['restored_outputs'], 1)
            self.assertEqual(owner.reserved_bytes, 0)

    def test_w04_outputs_keep_one_fixed_reference_without_accumulated_displacement(self):
        prepared, inputs = make_history_case('w04')
        with prepared, PreparedTectonicHistory(prepared, inputs, source_id=SOURCE) as history:
            first = history.run(through=1).result
            final = history.run().result
            direct = evaluate(prepared, inputs[-1])
            self.equal_result(final, direct)
            assert_array_equal(first.absolute_values[:, (0, 2)], final.absolute_values[:, (0, 2)])
            self.assertGreater(np.max(np.abs(first.downward_displacement_from_reference_m)), 0.)
            self.assertFalse(np.array_equal(final.downward_displacement_from_reference_m,
                first.downward_displacement_from_reference_m + direct.downward_displacement_from_reference_m))

    def test_schedule_type_order_bounds_and_producer_contexts_refuse(self):
        with prepare_underthrust() as prepared:
            cases = ((), [0., .5], (0., 0.), (.5, 0.), (-1.,), (2.,),
                     (True,), (float('nan'),), tuple(np.linspace(0., 1., 257)),
                     (request(),))
            for inputs in cases:
                with self.subTest(inputs=str(inputs)[:60]), self.assertRaises(TectonicsError):
                    with PreparedTectonicHistory(prepared, inputs, source_id=SOURCE):
                        pass
            with PreparedTectonicHistory(prepared, tuple(np.linspace(0., 1., 256)),
                                         source_id=SOURCE) as maximum:
                self.assertEqual(len(maximum.times), 256)
        with prepare_regional() as prepared:
            for c in (context(frame_id='foreign-frame'), context(epoch_id='foreign-epoch'),
                      context(origin_x_m=13.)):
                with self.subTest(context=c), self.assertRaises(TectonicsError):
                    with PreparedTectonicHistory(prepared, (request(c),), source_id=SOURCE):
                        pass
            before_epoch = tuple(request(context(time_s=t)) for t in (-2., -1., 0.))
            with PreparedTectonicHistory(prepared, before_epoch, source_id=SOURCE) as dated:
                self.assertEqual(dated.times, (-2., -1., 0.))
        prepared, inputs = make_history_case('w04')
        with prepared:
            with self.assertRaises(TectonicsError):
                invalid = W04HistoryInput(inputs[1].state, inputs[0].surface, inputs[1].rigidity)
                with PreparedTectonicHistory(prepared, (invalid,), source_id=SOURCE):
                    pass
            independent = advance_w03_columns(inputs[0].state, time_s=2e6,
                                              top_effective_stress_pa=0.)
            branch = W04HistoryInput(independent, surface(independent),
                supplied(independent, profile(independent, te=np.ones(8), far=False)))
            with self.assertRaises(TectonicsError):
                with PreparedTectonicHistory(prepared, (*inputs[:2], branch), source_id=SOURCE):
                    pass
            with self.assertRaises(TectonicsError):
                invalid = W04HistoryInput(inputs[1].state, inputs[1].surface, inputs[0].rigidity)
                with PreparedTectonicHistory(prepared, (invalid,), source_id=SOURCE):
                    pass

    def test_whole_schedule_and_source_bind_checkpoints_and_foreign_ids_refuse(self):
        owner = WorkBudget(CAP)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'bound.db', owner) as store:
            with prepare_underthrust(budget=owner) as prepared:
                with PreparedTectonicHistory(prepared, (0., .5, 1.), source_id=SOURCE, store=store) as first:
                    output = first.run(through=0)
                for schedule, source_id in (((0., .5, .75), SOURCE), ((0., .5, 1.), SOURCE+' revised')):
                    with PreparedTectonicHistory(prepared, schedule, source_id=source_id, store=store) as changed:
                        self.assertNotEqual(changed.checkpoint_id(0), output.checkpoint_id)
                        self.assertIsNone(changed.load(0))
                        with self.assertRaises((TectonicsError, StoreError)):
                            changed.load(0, checkpoint_id=output.checkpoint_id)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_corrupt_payload_and_missing_prefix_refuse_without_partial_adoption(self):
        for corrupt in ('payload', 'gap'):
            owner = WorkBudget(CAP)
            with self.subTest(corrupt=corrupt), TemporaryDirectory() as tmp:
                with open_store(Path(tmp)/'corrupt.db', owner) as store:
                    with make_history_fixture('underthrust', budget=owner, store=store) as history:
                        history.run()
                        first_key = history.checkpoint_id(0)
                    if corrupt == 'payload':
                        store._db.execute('UPDATE chunks SET payload=?', (b'corrupt',))
                    else:
                        store._db.execute('DELETE FROM snapshots WHERE id=?', (first_key,))
                    with make_history_fixture('underthrust', budget=owner, store=store) as resumed:
                        with self.assertRaises((TectonicsError, StoreError)):
                            resumed.run()
                        self.assertEqual(resumed.statistics()['computed_outputs'], 0)
                        self.assertEqual(resumed.statistics()['restored_outputs'], 0)
            self.assertEqual(owner.reserved_bytes, 0)

    def test_cancelled_or_failed_publication_preserves_last_accepted_output(self):
        owner = WorkBudget(CAP)
        with TemporaryDirectory() as tmp, open_store(Path(tmp)/'atomic.db', owner, InterruptingStore) as store:
            with make_history_fixture('underthrust', budget=owner, store=store) as history:
                accepted = history.run(through=0)
                before = store.statistics()
                event = Event(); event.set()
                with self.assertRaises(CancelledError):
                    history.run(cancel=event)
                for failure in (CancelledError('synthetic cancellation'), OSError('synthetic storage failure')):
                    store.failure = failure
                    with self.assertRaises(type(failure)):
                        history.run(through=1)
                    self.assertFalse(store.contains(history.checkpoint_id(1)))
                    for key in ('unique_chunks', 'encoded_payload_bytes', 'snapshots'):
                        self.assertEqual(store.statistics()[key], before[key])
                    self.equal_output(history.load(0), accepted)
                    self.assertEqual(history.statistics()['computed_outputs'], 1)
                self.assertEqual(history.run().index, 2)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_borrowed_producer_lifetime_and_closed_history_refuse(self):
        prepared, inputs = make_history_case('underthrust')
        with prepared:
            history = PreparedTectonicHistory(prepared, inputs, source_id=SOURCE)
            expected = history.run(through=0).result
            history.close(); history.close()
            self.equal_result(prepared.evaluate(0.), expected)
            with self.assertRaises(TectonicsError):
                history.run()
            other = PreparedTectonicHistory(prepared, inputs, source_id=SOURCE)
            prepared.close()
            try:
                with self.assertRaises(TectonicsError):
                    other.run()
            finally:
                other.close()
        with self.assertRaises(TectonicsError):
            with PreparedTectonicHistory(prepared, inputs, source_id=SOURCE):
                pass
        with self.assertRaises(TectonicsError):
            with PreparedTectonicHistory(object(), inputs, source_id=SOURCE):
                pass

    def test_common_budget_required_and_scoped_release_preserves_sibling(self):
        owner = WorkBudget(CAP)
        with owner.reserve(4096, category='independent-sibling'):
            with TemporaryDirectory() as tmp:
                with open_store(Path(tmp)/'owned.db', owner) as store:
                    with make_history_fixture('underthrust', budget=owner, store=store) as history:
                        history.run()
                        self.assertLessEqual(owner.peak_reserved_bytes, CAP)
                self.assertEqual(owner.reserved_bytes, 4096)
                with open_store(Path(tmp)/'foreign.db', WorkBudget(CAP)) as foreign:
                    with prepare_underthrust(budget=owner) as prepared:
                        retained = owner.reserved_bytes
                        with self.assertRaises((TectonicsError, MemoryLimitError)):
                            with PreparedTectonicHistory(prepared, (0., 1.), source_id=SOURCE, store=foreign):
                                pass
                        self.assertEqual(owner.reserved_bytes, retained)
            self.assertEqual(owner.reserved_bytes, 4096)
        self.assertEqual(owner.reserved_bytes, 0)

    def test_nonstored_rewind_refuses_and_latest_hit_still_verifies_source(self):
        with make_history_fixture('underthrust') as history:
            last = history.run()
            self.equal_output(history.run(), last)
            counts = history.statistics()
            self.assertEqual(counts['computed_outputs'], 3)
            self.assertEqual(counts['latest_hits'], 1)
            with self.assertRaises(TectonicsError):
                history.run(through=0)
            self.assertIsNone(history.load(0))
            original = reuse._source_bytes

            def changed():
                sources = original()
                sources['synthetic-history-source-drift.py'] = b'changed source identity'
                return sources

            with patch.object(reuse, '_source_bytes', changed):
                with self.assertRaises(TectonicsError):
                    history.run()
            self.assertEqual(history.statistics()['computed_outputs'], counts['computed_outputs'])
            self.assertEqual(history.statistics()['latest_hits'], counts['latest_hits'])


if __name__ == '__main__':
    unittest.main()
