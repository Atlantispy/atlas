"""Difference-ledger controls on tiny synthetic captures: every rule refuses its own violation."""
import copy
import gzip
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import ledger_fresh_interval as LG


def pair(value):
    from fractions import Fraction
    value = Fraction(value)
    return [hex(value.numerator), hex(value.denominator)]


def cell(cell_id, start, end):
    return {'cell_id': cell_id, 'chart': 'c', 'kind': 'inherited', 'start_volume_bounds_m3': [pair(start[0]), pair(start[1])],
            'end_volume_bounds_m3': [pair(end[0]), pair(end[1])], 'positive_witness_m3': pair(1)}


def row(cell_id, endpoint, lower, upper, witness=1, status='met'):
    return {'full_cell': cell_id, 'endpoint': endpoint, 'status': status,
            'exact': [pair(lower), pair(upper), pair(witness)]}


class Runs:
    """r9 and a rerun that differ at most where the test says."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.bounds = {'cells': [cell('a', (10, 20), (30, 40)), cell('b', (5, 6), (7, 8))],
                       'face_intervals': [{'face_id': 'f', 'donor': 'a', 'receiver': 'b',
                                           'volume_bounds_m3': [pair(1), pair(2)]}],
                       'finite_exchange_intervals': [], 'grid_id': 'g', 'max_leaves': 9}
        self.r7 = {key: row(cell_id, endpoint, *bounds) for key, (cell_id, endpoint, bounds) in {
            ('a', 'start'): ('a', 'start', (10, 20)), ('a', 'end'): ('a', 'end', (30, 40)),
            ('b', 'end'): ('b', 'end', (7, 8))}.items()}
        self.replay = copy.deepcopy(self.r7)
        self.arrays = {group: [{'name': group+'-x', 'shape': [1], 'dtype': '<f8', 'sha256': 'h-'+group}]
                       for group in LG.GROUPS}

    def receipt(self, name, bounds, arrays, *, mesh='m', graph='g', root=None):
        folder = self.directory/name
        folder.mkdir(exist_ok=True)
        raw = json.dumps(bounds, sort_keys=True).encode()
        (folder/'preadvance-bounds.json.gz').write_bytes(gzip.compress(raw))
        operands = {'bounds': {'path': 'preadvance-bounds.json.gz', 'raw_bytes': len(raw),
                               'raw_sha256': sha256(raw).hexdigest()},
                    'closed_graph': {'raw_sha256': graph}, 'mesh': {'raw_sha256': mesh}}
        endpoint = {'array_records': arrays, 'root_metadata': root or {'kind': 'root', 'funding': {'f': 1},
                    'exterior_state': {'state_id': 's', 'record_blobs': {'state': name}}},
                    'workflow_id': name, 'producer_pid': 1}
        return folder, {'preadvance_operands': operands, 'completed_endpoint': endpoint}

    def run(self, *, rerun_bounds=None, rerun_arrays=None, mesh='m', graph='g', root=None):
        r9_dir, r9 = self.receipt('r9', self.bounds, self.arrays)
        rerun_dir, rerun = self.receipt('rerun', rerun_bounds or self.bounds, rerun_arrays or self.arrays,
                                        mesh=mesh, graph=graph, root=root)
        return LG.ledger(r9=r9, r9_artifacts=r9_dir, rerun=rerun, rerun_artifacts=rerun_dir, replay=self.replay,
                         r7=self.r7, rerun_verdict={'width_gate': {'passed': True}})


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lg-', dir=HERE)
        self.runs = Runs(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def changed(self, cell_id, field, lower, upper):
        bounds = copy.deepcopy(self.runs.bounds)
        target = next(c for c in bounds['cells'] if c['cell_id'] == cell_id)
        target[field] = [pair(lower), pair(upper)]
        return bounds

    def test_identical_runs_pass_with_nothing_attributed(self):
        result = self.runs.run()
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['heat_inputs']['bounds']['attributed'], [])
        self.assertFalse(result['traced_to_attributed_bounds'])
        self.assertEqual(result['heat_inputs']['bounds']['queried_endpoints'], 3)
        self.assertEqual(result['heat_inputs']['bounds']['unqueried_endpoints'], 1)
        # The storage reference of the compact route is recorded, never failed.
        self.assertEqual(result['start_state']['representation'], ['root_metadata.exterior_state.record_blobs'])

    def test_replayed_cube_stop_difference_is_attributed_and_traces_the_arrays(self):
        self.runs.replay[('a', 'end')] = row('a', 'end', 29, 41)
        arrays = copy.deepcopy(self.runs.arrays)
        arrays['exterior'][0]['sha256'] = 'changed'
        result = self.runs.run(rerun_bounds=self.changed('a', 'end_volume_bounds_m3', 29, 41), rerun_arrays=arrays,
                               graph='g2')
        self.assertEqual(result['verdict'], 'PASS', result['unattributed'])
        self.assertEqual([(r['cell_id'], r['endpoint'], r['change']) for r in
                          result['heat_inputs']['bounds']['attributed']], [('a', 'end', LG.APPROVED_CHANGE)])
        self.assertTrue(result['traced_to_attributed_bounds'])
        self.assertEqual(result['endpoint_arrays']['exterior']['different'], ['exterior-x'])

    def failure(self, reason, **change):
        result = self.runs.run(**change)
        self.assertEqual(result['verdict'], 'FAIL')
        reasons = ' | '.join(str(item.get('reason', item.get('path'))) for item in result['unattributed'])
        self.assertIn(reason, reasons)
        return result

    def test_unattributed_differences_fail(self):
        # A difference the replay does not show.
        self.failure('rerun bound differs from the Step 10 replay',
                     rerun_bounds=self.changed('a', 'start_volume_bounds_m3', 11, 19))
        # A difference at an endpoint without a query (the exact birth rule).
        self.failure('without a query', rerun_bounds=self.changed('b', 'start_volume_bounds_m3', 5, 7))
        # Endpoint arrays differ although every heat input is identical.
        arrays = copy.deepcopy(self.runs.arrays)
        arrays['collar'][0]['sha256'] = 'changed'
        self.failure('no attributed input difference', rerun_arrays=arrays)
        # The mesh and the graph are inputs too.
        self.failure('the end mesh differs', mesh='m2')
        self.failure('graph differs without attributed', graph='g2')

    def test_certification_width_witness_and_overlap(self):
        cases = ((row('a', 'end', 30, 32041), 30, 32041, 'not both certified'),
                 (row('a', 'end', 29, 41, witness=0), 29, 41, 'not both certified'),
                 (row('a', 'end', 29, 41, status='unmet'), 29, 41, 'not both certified'),
                 (row('a', 'end', 41, 50), 41, 50, 'not both certified'))
        for replayed, lower, upper, reason in cases:
            with self.subTest(replay=replayed['exact'], status=replayed['status']):
                self.runs.replay[('a', 'end')] = replayed
                self.failure(reason, rerun_bounds=self.changed('a', 'end_volume_bounds_m3', lower, upper))
        self.runs.replay[('a', 'end')] = row('a', 'end', 30, 40)
        self.runs.r7[('a', 'end')] = row('a', 'end', 30, 39)
        self.failure('r9 bound differs from the r7 replay')

    def test_other_inputs_and_start_state_fail_closed(self):
        bounds = copy.deepcopy(self.runs.bounds)
        bounds['face_intervals'][0]['volume_bounds_m3'] = [pair(1), pair(3)]
        self.failure('face interval differs', rerun_bounds=bounds)
        bounds = copy.deepcopy(self.runs.bounds)
        bounds['max_leaves'] = 10
        self.failure('bounds.max_leaves', rerun_bounds=bounds)
        bounds = copy.deepcopy(self.runs.bounds)
        bounds['cells'].append(cell('c', (1, 2), (3, 4)))
        self.failure('cell present in one run only', rerun_bounds=bounds)
        root = {'kind': 'root', 'funding': {'f': 2}, 'exterior_state': {'state_id': 's', 'record_blobs': {}}}
        result = self.failure('root_metadata.funding.f', root=root)
        self.assertIn('root_metadata.exterior_state.record_blobs', result['start_state']['representation'])

    def test_identity_leaves_are_recorded_not_failed(self):
        root = {'kind': 'root', 'funding': {'f': 1, 'funding_id': 'other'},
                'exterior_state': {'state_id': 'other', 'record_blobs': {'state': 'rerun'}}}
        self.runs.bounds['grid_id'] = 'g'
        result = self.runs.run(root=root)
        self.assertEqual(result['start_state']['value'], [])
        self.assertIn('root_metadata.exterior_state.state_id', result['start_state']['identity'])

    def test_replay_rows_and_capture_pins(self):
        folder = Path(self.temp.name)
        shard = folder/'shard.jsonl'
        shard.write_text('{"header": 1}\n'+json.dumps(row('a', 'end', 1, 2))+'\n', encoding='utf8')
        rows = LG.read_rows([(shard, sha256(shard.read_bytes()).hexdigest())], 'test')
        self.assertEqual(list(rows), [('a', 'end')])
        shard.write_text(json.dumps(row('a', 'end', 1, 2))*1+'\n'+json.dumps(row('a', 'end', 1, 2))+'\n',
                         encoding='utf8')
        with self.assertRaisesRegex(LG.LedgerRefused, 'duplicate'):
            LG.read_rows([(shard, sha256(shard.read_bytes()).hexdigest())], 'test')
        with self.assertRaisesRegex(LG.LedgerRefused, 'pinned input changed'):
            LG.read_rows([(shard, '0'*64)], 'test')
        r9_dir, r9 = self.runs.receipt('r9', self.runs.bounds, self.runs.arrays)
        r9['preadvance_operands']['bounds']['raw_sha256'] = '0'*64
        with self.assertRaisesRegex(LG.LedgerRefused, 'differs from its receipt'):
            LG.capture(r9_dir, r9['preadvance_operands']['bounds'])
        with self.assertRaisesRegex(LG.LedgerRefused, 'reduced canonical'):
            LG.rational(['0x2', '0x4'])


if __name__ == '__main__':
    unittest.main()
