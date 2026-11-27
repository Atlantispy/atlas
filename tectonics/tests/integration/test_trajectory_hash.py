"""Streamed trajectory and support ids equal the whole-list hashes they replace.

SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import types
import unittest

from atlas_tectonics.integration.geometry import differential_geometry as DG
from atlas_tectonics.integration.geometry import wall_measures as W


def _segment(i):
    return dict(start_time_s=[hex(i), '0x1'], end_time_s=[hex(i+1), '0x1'], parent_network_id=f'p{i}',
                endpoint_network_id=f'e{i}', motion_id='m\u00e9',
                plate_angular_velocity_rad_s={'b': [['0x1', '0x3']]*3, 'a': [['-0x2', '0x7']]*3},
                boundary_angular_velocity_rad_s={} if i % 2 else {'k"1': [['0x0', '0x1']]*3})


def _expected(previous, segment, epoch):
    full = previous+[segment]
    return dict(prior_trajectory_id=W._hash(previous), trajectory_id=W._hash(full),
                start_support_id=W._hash(dict(epoch_network_id=epoch, segments=previous)),
                end_support_id=W._hash(dict(epoch_network_id=epoch, segments=full)))


def _streamed(previous, segment, epoch, prior_record):
    trajectory, support, prior = DG._trajectory_hashes(prior_record, previous, epoch)
    start = support.id()
    trajectory.append(segment); support.append(segment)
    return dict(prior_trajectory_id=prior, trajectory_id=trajectory.id(), start_support_id=start,
                end_support_id=support.id()), (trajectory, support)


class StreamedTrajectoryIds(unittest.TestCase):
    def test_equal_to_whole_list_hashes_on_miss_and_hit(self):
        for n in (0, 1, 2, 300):
            with self.subTest(n=n):
                segments = [_segment(i) for i in range(n+2)]
                previous, segment, following = segments[:n], segments[n], segments[n+1]
                epoch = segments[0]['parent_network_id']
                DG._trajectory_states.clear()
                prior_record = None if n == 0 else dict(trajectory_id=W._hash(previous))
                miss, states = _streamed(previous, segment, epoch, prior_record)
                self.assertEqual(miss, _expected(previous, segment, epoch))
                self.assertFalse(DG._trajectory_states)
                DG._trajectory_states[miss['trajectory_id']] = states
                hit, _ = _streamed(None, following, epoch, dict(trajectory_id=miss['trajectory_id']))
                self.assertEqual(hit, _expected(previous+[segment], following, epoch))
                again, _ = _streamed(None, following, epoch, dict(trajectory_id=miss['trajectory_id']))
                self.assertEqual(again, hit)

    def test_comma_mutant_is_killed(self):
        source = Path(W.__file__).read_text(encoding='utf-8')
        old = "(',' if self._count else '')"
        self.assertEqual(source.count(old), 1)
        mutant = types.ModuleType('wall_measures_mutant')
        mutant.__dict__.update(__file__=W.__file__, __package__=W.__package__)
        exec(compile(source.replace(old, "''"), W.__file__, 'exec'), mutant.__dict__)
        state = mutant.TrajectoryHash()
        state.extend([_segment(0), _segment(1)])
        self.assertNotEqual(state.id(), W._hash([_segment(0), _segment(1)]))


if __name__ == '__main__':
    unittest.main()
