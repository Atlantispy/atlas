"""Unit tests r3 for H5a. r2 (log evidence/test-h5a-r2.log) passed 11 of 12. Its EmptyRefusal check read the
budget while assertRaises still held the exception, whose traceback keeps the refused workspace's lease alive.
probe_h5a_refusal_hold.py (evidence/probe-h5a-refusal-hold.log) shows r5 reconstruct, r5 _prepare, r6
reconstruct and r6 prepare_shared all hold the same bytes while the exception lives and 0 once it is dropped.
r3 reruns r2's tests unchanged except that one, which now drops the exception and collects before reading.
"""
import gc
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_h5a_prepare_reuse_r2 as T2  # noqa: E402

TransformTests, ReuseDecision, CubeMesh = T2.TransformTests, T2.ReuseDecision, T2.CubeMesh


class EmptyRefusal(unittest.TestCase):
    def test_same_refusal_and_nothing_held(self):
        old = T2.load('private_heat_functionals_kernel_r5_h5a_r3e', T2.FUN5)
        new = T2.load('private_heat_functionals_kernel_r6_h5a_r3e', T2.FUN6)
        payload = dict(cells=[], faces=[])
        messages, held = [], []
        for attempt in (lambda b: old.reconstruct(payload, boundary_point_faces=set(), boundary_power_faces=set(),
                                                  budget=b, selected_faces=()),
                        lambda b: new.reconstruct(payload, boundary_point_faces=set(), boundary_power_faces=set(),
                                                  budget=b, selected_faces=(), prepared_shared=None),
                        lambda b: new.prepare_shared(payload, set(), set(), 1, budget=b)):
            budget = T2.WorkBudget(1 << 34)
            try:
                attempt(budget)
                messages.append('accepted')
            except ValueError as error:
                messages.append(str(error))
            gc.collect()
            held.append(T2.booked(budget)[0])
        self.assertEqual(messages, ['Distinct nonempty cell and face inventories required']*3)
        self.assertEqual(held, [0, 0, 0])


if __name__ == '__main__':
    unittest.main()
