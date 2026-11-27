"""Poses folded once per history content equal poses folded through the whole history.

SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q
from pathlib import Path
import tempfile
import types
import unittest

from atlas_tectonics.integration.geometry import differential_geometry as DG
from atlas_tectonics.integration.geometry import wall_measures as W
from atlas_tectonics.integration.geometry.volume_bounds import _Arena
from atlas_tectonics.integration.resources import WorkBudget


def _rows(n, shift=0):
    return DG._history_record(tuple(((Q(1+i+shift, 7), Q(-2, 9+i), Q(3, 11)), Q(5+i, 3)) for i in range(n)))


def _pose(prior, level, vector=(Q(1), Q(2, 3), Q(-1, 5))):
    budget = WorkBudget(1 << 34)
    with _Arena(budget) as arena:
        result = W._pose_vector(vector, (Q(1, 13), Q(0), Q(2, 17)), Q(0), Q(1, 2), level, arena, prior)
        return result, arena.work_units


def _clear():
    DG._history_rows.clear(); W._history_digests.clear(); W._pose_memo.clear()


class PoseHistoryMemo(unittest.TestCase):
    def setUp(self):
        _clear()

    def test_history_decoded_once_per_rows_object(self):
        rows = _rows(3)
        self.assertIs(DG._history(rows), DG._history(rows))
        twin = _rows(3)
        self.assertIsNot(DG._history(twin), DG._history(rows))
        self.assertEqual(W._history_digest(DG._history(twin)), W._history_digest(DG._history(rows)))
        self.assertIsNone(W._history_digest(tuple(list(DG._history(rows)))))  # tuple(t) is t

    def test_memo_pose_equals_full_fold(self):
        for n in (1, 2, 30):
            for level in (0, 3):
                with self.subTest(n=n, level=level):
                    rows = _rows(n)
                    full = _pose(tuple(DG._history(rows)), level)  # a tuple not from _history: full fold
                    self.assertEqual(_pose(DG._history(rows), level), full)  # miss
                    self.assertEqual(_pose(DG._history(_rows(n)), level), full)  # hit by content
        self.assertTrue(W._pose_memo)

    def test_reused_id_is_refused(self):
        rows, other = _rows(2), _rows(2, shift=1)
        DG._history_rows[id(rows)] = (other, DG._history(other))
        self.assertEqual(DG._history(rows), tuple(DG._history(_rows(2))))

    def test_prefix_entry_extends_by_one_step(self):
        for level in (0, 3):
            with self.subTest(level=level):
                _clear()
                _pose(DG._history(_rows(5)), level)  # seeds the 5-step entry
                longer = _rows(6)
                self.assertEqual(_pose(DG._history(longer), level), _pose(tuple(DG._history(longer)), level))

    def test_memo_file_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/W.pose_memo_file
            self.assertEqual(W.load_pose_memo(path), frozenset())  # missing file: a miss
            full = _pose(tuple(DG._history(_rows(5))), 3)
            _pose(DG._history(_rows(5)), 3)
            held = frozenset(W._pose_memo)
            W.save_pose_memo(path)
            W.save_pose_memo(Path(folder)/'none.json', held)  # nothing added: no file
            self.assertFalse((Path(folder)/'none.json').exists())
            _clear()
            self.assertEqual(W.load_pose_memo(path), held)
            self.assertEqual(_pose(DG._history(_rows(5)), 3), full)  # hit from the file
            longer = _rows(6)
            self.assertEqual(_pose(DG._history(longer), 3), _pose(tuple(DG._history(longer)), 3))  # prefix
            path.write_text(path.read_text(encoding='utf-8')[:-7], encoding='utf-8')
            _clear()
            self.assertEqual(W.load_pose_memo(path), frozenset())  # truncated: empty

    def test_other_method_file_is_not_found(self):
        with tempfile.TemporaryDirectory() as folder:
            _pose(DG._history(_rows(3)), 0)
            W.save_pose_memo(Path(folder)/W.pose_memo_name('store').replace(W.METHOD, W.METHOD+'-old'))
            _clear()
            self.assertEqual(W.load_pose_memo(Path(folder)/W.pose_memo_name('store')), frozenset())

    def _mutant(self, old, new):
        source = Path(W.__file__).read_text(encoding='utf-8')
        self.assertEqual(source.count(old), 1)
        mutant = types.ModuleType('wall_measures_mutant')
        mutant.__dict__.update(__file__=W.__file__, __package__=W.__package__)
        exec(compile(source.replace(old, new), W.__file__, 'exec'), mutant.__dict__)
        return mutant

    def _mutant_pose(self, mutant, rows, level):
        prior = DG._history(rows)
        mutant._register_history(prior, rows)
        with _Arena(WorkBudget(1 << 34)) as arena:
            result = mutant._pose_vector((Q(1), Q(2, 3), Q(-1, 5)), (Q(1, 13), Q(0), Q(2, 17)), Q(0), Q(1, 2),
                                         level, arena, prior)
            return result, arena.work_units

    def test_level_mutant_is_killed(self):
        mutant = self._mutant('head = (tuple(vector), tuple(map(type, vector)), level)',
                              'head = (tuple(vector), tuple(map(type, vector)))')
        self._mutant_pose(mutant, _rows(4), 0)
        self.assertNotEqual(self._mutant_pose(mutant, _rows(4), 3), _pose(tuple(DG._history(_rows(4))), 3))

    def test_prefix_from_other_level_mutant_is_killed(self):
        mutant = self._mutant('_pose_memo.get(head+digests[1:])', '_pose_memo.get(head[:2]+(0,)+digests[1:])')
        self._mutant_pose(mutant, _rows(5), 0)
        self.assertNotEqual(self._mutant_pose(mutant, _rows(6), 3), _pose(tuple(DG._history(_rows(6))), 3))

if __name__ == '__main__':
    unittest.main()
