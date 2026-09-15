"""One scheduling-only check; no source-array read or geological generation."""
from copy import deepcopy
import unittest

from work.generator_upgrade_r17 import region


class RegionTests(unittest.TestCase):
    def test_complete_native_window_lazy_batches_signed_steps_and_invalid_limits(self):
        grid = {'first_sample_m': [-318000, -478000], 'step_m': [4000, 4000], 'shape': [665, 710]}
        window = {'row_start': 149, 'row_stop': 212, 'col_start': 263, 'col_stop': 364}
        pending = region.support_batches(grid, window)
        self.assertIs(iter(pending), pending)
        batches = list(pending)
        self.assertEqual([len(batch) for batch in batches], [32]*198+[27])
        ordered = [identity for batch in batches for identity in batch]
        expected = [f'r{row}_c{col}' for row in range(149, 212) for col in range(263, 364)]
        self.assertEqual(ordered, expected)
        self.assertEqual(len(ordered), 6363)
        self.assertEqual(len(set(ordered)), 6363)
        self.assertEqual(next(iter(batches[0].values()))['xy_m'], [734000, 118000])
        self.assertEqual(batches[-1]['r211_c363']['xy_m'], [1134000, 366000])
        self.assertEqual(ordered[31:33], ['r149_c294', 'r149_c295'])
        self.assertTrue(all(row['area_m2'] == 16000000 for batch in batches for row in batch.values()))
        signed = {'first_sample_m': [4, 8], 'step_m': [-2, 3], 'shape': [2, 2]}
        small = {'row_start': 0, 'row_stop': 2, 'col_start': 0, 'col_stop': 2}
        plan = region.support_batches(signed, small, 1)
        signed['first_sample_m'][0] = 999
        self.assertEqual(list(plan), [
            {'r0_c0': {'xy_m': [4, 8], 'area_m2': 6}},
            {'r0_c1': {'xy_m': [2, 8], 'area_m2': 6}},
            {'r1_c0': {'xy_m': [4, 11], 'area_m2': 6}},
            {'r1_c1': {'xy_m': [2, 11], 'area_m2': 6}}])
        for size in (0, 33, True, 1.5):
            with self.subTest(batch_size=size), self.assertRaises(ValueError):
                region.support_batches(grid, window, size)
        changes = [lambda g, w: g.update(extra=1),
                   lambda g, w: g.update(shape=[0, 710]),
                   lambda g, w: g.update(shape=[True, 710]),
                   lambda g, w: g.update(first_sample_m=[float('nan'), 0]),
                   lambda g, w: g.update(first_sample_m=[False, 0]),
                   lambda g, w: g.update(step_m=[0, 4000]),
                   lambda g, w: g.update(step_m=[4000, float('inf')]),
                   lambda g, w: w.update(row_start=True),
                   lambda g, w: w.update(row_start=-1),
                   lambda g, w: w.update(row_stop=666),
                   lambda g, w: w.update(col_stop=711),
                   lambda g, w: w.update(col_stop=263),
                   lambda g, w: w.update(extra=1)]
        for change in changes:
            other_grid, other_window = deepcopy(grid), deepcopy(window)
            change(other_grid, other_window)
            with self.subTest(change=change), self.assertRaises(ValueError):
                region.support_batches(other_grid, other_window)


if __name__ == '__main__':
    unittest.main()
