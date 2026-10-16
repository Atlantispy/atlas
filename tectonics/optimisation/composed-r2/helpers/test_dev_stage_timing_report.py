"""Subsection-completion checkpoint tests; synthetic clocks, no workload."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import dev_stage_timing_report as R


def event(kind, seq, wall, cpu, **fields):
    return dict(event=kind, seq=seq, wall_ns=wall, cpu_ns=cpu, **fields)


def start(**fields):
    return event('session_start', 0, 0, 0, schema=R.EVENT_SCHEMA,
                 pid=123, phase='startup', metadata={}, **fields)


def checkpoint(seq, wall, cpu, name, **fields):
    return event('checkpoint', seq, wall, cpu, name=name, **fields)


def end(seq, wall, cpu, status='ok', **fields):
    name = 'timing-finalisation' if status == 'ok' else 'incomplete-subsection'
    return event('session_end', seq, wall, cpu, phase=name, workload_status=status, closed=True, **fields)


class TimingReportTests(unittest.TestCase):
    def setUp(self):
        # Windows sandbox Temp permits directory creation but can deny child
        # writes. Use the authorised short task root for disposable fixtures.
        self.temp = tempfile.TemporaryDirectory(prefix='timing-report-',
            dir=Path(__file__).resolve().parents[4])
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder/'events.jsonl'

    def write(self, records, tail=b''):
        self.path.write_bytes(b''.join(json.dumps(row, allow_nan=False).encode('utf8')+b'\n'
                                       for row in records)+tail)
        return self.path

    def report(self, records, tail=b'', **kwargs):
        return R.build_report(self.write(records, tail), **kwargs)

    def assert_reconciled(self, report, wall, cpu):
        self.assertEqual(report['coverage']['wall_ns'], wall)
        self.assertEqual(report['coverage']['process_cpu_ns'], cpu)
        self.assertEqual(sum(row['wall_ns'] for row in report['stages']['rows']), wall)
        self.assertEqual(sum(row['process_cpu_ns'] for row in report['stages']['rows']), cpu)
        self.assertTrue(report['stages']['reconciled'])

    def test_intervals_belong_to_ending_checkpoint_and_repeated_names_sum(self):
        report = self.report([start(), checkpoint(1, 10, 4, 'advance'),
            checkpoint(2, 25, 10, 'reopen'), checkpoint(3, 40, 16, 'advance'), end(4, 60, 28)])
        self.assertEqual(report['status'], 'COMPLETE')
        self.assert_reconciled(report, 60, 28)
        rows = {row['phase']: row for row in report['stages']['rows']}
        self.assertEqual(rows['advance'], dict(phase='advance', visits=2, wall_ns=25, process_cpu_ns=10,
            completed=True, memory_observations=dict(events_with_memory=0, observed_maxima={})))
        self.assertNotIn('startup', rows)
        self.assertEqual((rows['reopen']['wall_ns'], rows['reopen']['process_cpu_ns']), (15, 6))
        self.assertEqual((rows['timing-finalisation']['wall_ns'], rows['timing-finalisation']['process_cpu_ns']), (20, 12))
        self.assertTrue(rows['timing-finalisation']['completed'])
        self.assertIn('intervals ending at explicit subsection checkpoints', report['stages']['scope'])
        self.assertIn('excludes children', report['stages']['scope'])
        self.assertNotIn('queries', report)
        self.assertEqual(report['bounds'], dict(line_bytes=R.MAX_LINE_BYTES,
            file_bytes=R.MAX_FILE_BYTES, phase_aggregates=256))

    def test_equal_clock_boundaries_are_valid_without_invented_time(self):
        report = self.report([start(), checkpoint(1, 0, 0, 'advance'), end(2, 0, 0)])
        self.assertEqual(report['status'], 'COMPLETE')
        self.assert_reconciled(report, 0, 0)

    def test_partial_crash_tail_stops_at_last_completed_subsection(self):
        records = [start(), checkpoint(1, 10, 4, 'advance'), checkpoint(2, 30, 9, 'reopen')]
        for tail in (b'', b'{"event":"session_end"', json.dumps(end(3, 100, 40)).encode()):
            with self.subTest(tail=tail):
                report = self.report(records, tail)
                self.assertEqual(report['status'], 'INCOMPLETE')
                self.assert_reconciled(report, 30, 9)
                self.assertFalse(report['coverage']['session_end_observed'])
                self.assertEqual(report['stages']['last_completed_subsection'], 'reopen')
                self.assertEqual(report['stages']['rows'][-1]['wall_ns'], 20)
                self.assertTrue(all(row['completed'] for row in report['stages']['rows']))
                self.assertIn('no measured duration', report['stages']['scope'])
        initial = self.report([start(memory={'parent_rss_bytes': 80})])
        self.assertEqual(initial['stages']['rows'], [])
        self.assertIsNone(initial['stages']['last_completed_subsection'])
        self.assert_reconciled(initial, 0, 0)

    def test_missing_empty_and_foreign_files_refuse_or_remain_incomplete(self):
        self.assertEqual(R.build_report(self.path)['status'], 'REFUSED')
        self.assertEqual(self.report([])['status'], 'INCOMPLETE')
        for row in ({'event': 'foreign'}, end(0, 0, 0), dict(start(), schema='other')):
            with self.subTest(row=row):
                result = self.report([row])
                self.assertEqual(result['status'], 'REFUSED')
                self.assertEqual(result['coverage']['valid_events'], 0)

    def test_sequence_timestamps_types_and_unknown_fields_refuse_valid_prefix(self):
        prefix = [start(), checkpoint(1, 10, 5, 'advance')]
        bad = [end(3, 20, 10), end(2, 9, 10), end(2, 20, 4), end(2, -1, 5),
               end(2, True, 5), end(2, 20.0, 5), end(2, 1 << 70, 5),
               dict(end(2, 20, 10), phase='foreign'),
               dict(end(2, 20, 10), result={'payload': 1}), start(),
               dict(end(2, 20, 10), closed=1), checkpoint(2, 20, 10, '')]
        for row in bad:
            with self.subTest(row=row):
                result = self.report(prefix+[row])
                self.assertEqual(result['status'], 'REFUSED')
                self.assert_reconciled(result, 10, 5)

    def test_former_phase_query_and_heartbeat_kinds_are_refused(self):
        former = [event('phase', 2, 20, 10, name='advance'),
            event('query_start', 2, 20, 10, query_id=1, name='endpoint-volume', phase='advance'),
            event('query_end', 2, 20, 10, query_id=1, name='endpoint-volume', phase='advance',
                  start_wall_ns=10, start_cpu_ns=5, status='ok'),
            event('heartbeat', 2, 20, 10, phase='advance', active_query_ids=[])]
        for row in former:
            with self.subTest(kind=row['event']):
                result = self.report([start(), checkpoint(1, 10, 5, 'advance'), row])
                self.assertEqual(result['status'], 'REFUSED')
                self.assertEqual(result['issues'][0]['reason'], 'unknown event type')
                self.assert_reconciled(result, 10, 5)
                self.assertNotIn('queries', result)
        self.assertEqual(set(R.FIELDS), {'session_start', 'checkpoint', 'session_end'})

    def test_closed_error_timing_is_complete_but_final_subsection_is_not(self):
        good = [start(), checkpoint(1, 10, 5, 'advance'), end(2, 30, 8, status='error')]
        result = self.report(good)
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(result['coverage']['workload_status'], 'error')
        self.assert_reconciled(result, 30, 8)
        last = result['stages']['rows'][-1]
        self.assertEqual((last['phase'], last['wall_ns'], last['process_cpu_ns'], last['completed']),
                         ('incomplete-subsection', 20, 3, False))
        self.assertTrue(result['stages']['rows'][0]['completed'])
        result = self.report(good+[checkpoint(3, 40, 10, 'after-end')])
        self.assertEqual(result['status'], 'REFUSED')
        self.assert_reconciled(result, 30, 8)

    def test_duplicate_keys_nonfinite_utf8_and_nested_json_refused(self):
        for tail in (b'{"event":"checkpoint","event":"checkpoint"}\n',
                     b'{"event":"checkpoint","wall_ns":NaN}\n', b'\xff\n', b'\n',
                     b'['*1500+b']'*1500+b'\n'):
            with self.subTest(tail=tail[:40]):
                self.assertEqual(self.report([start()], tail)['status'], 'REFUSED')

    def test_line_file_and_stage_aggregate_bounds(self):
        result = self.report([start()], b'x'*(R.MAX_LINE_BYTES+1))
        self.assertEqual(result['status'], 'REFUSED')
        self.assertLessEqual(result['bytes_read'], len(json.dumps(start()).encode())+1+R.MAX_LINE_BYTES+1)
        with patch.object(R, 'MAX_FILE_BYTES', 100):
            self.assertEqual(self.report([start()])['status'], 'REFUSED')
        records = [start()]+[checkpoint(index, index, index, 'part-'+str(index)) for index in range(1, 257)]
        result = self.report(records+[checkpoint(257, 257, 257, 'overflow')])
        self.assertEqual(result['status'], 'REFUSED')
        self.assertEqual(len(result['stages']['rows']), 256)
        self.assert_reconciled(result, 256, 256)
        self.assertEqual(self.report(records+[end(257, 257, 257)])['status'], 'REFUSED')

    def test_memory_observations_have_scope_and_invalid_fields_refuse(self):
        result = self.report([start(memory={'parent_rss_bytes': 50, 'parent_os_peak_working_set_bytes': 90}),
            end(1, 10, 5, memory={'parent_rss_bytes': 40, 'parent_private_bytes': None,
                                 'logical_reserved_bytes': 200})])
        memory = result['memory_observations']
        self.assertEqual(memory['observed_maxima']['parent_rss_bytes'], 50)
        self.assertEqual(memory['events_with_memory'], 2)
        self.assertIn('not global peaks', memory['scope'])
        self.assertIn('OS-lifetime', memory['scope'])
        self.assertIn('not physical RAM', memory['scope'])
        for values in ({'result': 1}, {'parent_rss_bytes': -1}, {'parent_rss_bytes': True}, None):
            self.assertEqual(self.report([start(memory=values)])['status'], 'REFUSED')

    def test_memory_belongs_to_finished_subsection_and_initial_is_global_only(self):
        result = self.report([start(memory={'parent_rss_bytes': 100}),
            checkpoint(1, 10, 4, 'advance', memory={'parent_rss_bytes': 200}),
            checkpoint(2, 20, 8, 'advance', memory={'parent_rss_bytes': 150, 'parent_os_peak_working_set_bytes': 400}),
            checkpoint(3, 30, 12, 'reopen', memory={'parent_rss_bytes': 90}),
            checkpoint(4, 40, 16, 'advance', memory={'parent_rss_bytes': 250}),
            end(5, 50, 20, memory={'parent_rss_bytes': 75})])
        self.assertEqual(result['status'], 'COMPLETE')
        self.assert_reconciled(result, 50, 20)
        rows = {row['phase']: row for row in result['stages']['rows']}
        self.assertNotIn('startup', rows)
        self.assertEqual(rows['advance']['memory_observations'], dict(events_with_memory=3,
            observed_maxima={'parent_rss_bytes': 250, 'parent_os_peak_working_set_bytes': 400}))
        self.assertEqual(rows['reopen']['memory_observations'],
                         dict(events_with_memory=1, observed_maxima={'parent_rss_bytes': 90}))
        self.assertEqual(rows['timing-finalisation']['memory_observations'],
                         dict(events_with_memory=1, observed_maxima={'parent_rss_bytes': 75}))
        self.assertEqual(result['memory_observations']['events_with_memory'], 6)
        self.assertEqual(result['memory_observations']['observed_maxima']['parent_rss_bytes'], 250)
        self.assertIn('not actual phase or global peaks', result['stages']['memory_scope'])
        self.assertIn('subsection that just finished', result['stages']['memory_scope'])
        self.assertIn('process-lifetime', result['stages']['memory_scope'])

    def test_null_missing_and_empty_checkpoint_observations_remain_unknown(self):
        result = self.report([start(), checkpoint(1, 10, 4, 'advance', memory={'parent_rss_bytes': None}),
            checkpoint(2, 20, 8, 'advance'), checkpoint(3, 30, 12, 'advance', memory={}),
            checkpoint(4, 40, 16, 'advance', memory={'parent_rss_bytes': 0}), end(5, 50, 20)])
        self.assertEqual(result['status'], 'COMPLETE')
        rows = {row['phase']: row for row in result['stages']['rows']}
        self.assertEqual(rows['timing-finalisation']['memory_observations'], dict(events_with_memory=0, observed_maxima={}))
        self.assertEqual(rows['advance']['memory_observations'],
                         dict(events_with_memory=3, observed_maxima={'parent_rss_bytes': 0}))
        self.assertNotIn('parent_private_bytes', rows['advance']['memory_observations']['observed_maxima'])
        partial = self.report([start(), checkpoint(1, 10, 4, 'advance', memory={'parent_rss_bytes': None})])
        self.assertEqual(partial['stages']['rows'][0]['memory_observations'],
                         dict(events_with_memory=1, observed_maxima={}))
        self.assertEqual(partial['memory_observations']['observed_maxima'], {})
        self.assertIn('unknown, not zero', result['stages']['memory_scope'])

    def test_unknown_scalar_metadata_is_preserved_without_affecting_accounting(self):
        first = start()
        first['metadata'] = {'external_build_hint': 'abc', 'external_trial': 3, 'external_unknown': None}
        result = self.report([first, end(1, 10, 5)])
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertEqual(result['session']['metadata'], first['metadata'])
        self.assert_reconciled(result, 10, 5)

    def guard(self, **fields):
        receipt = dict(schema=R.GUARD_SCHEMA, parent={'pid': 123, 'creation_time': 900},
            workload_exit_code=0, resource_summary=dict(schema='atlas.private.resource-summary.r1',
            samples=2, overlapping_identity_cpu_seconds=8.0, phases={}, peaks={'parent_rss_bytes': 50}))
        receipt.update(fields)
        path = self.folder/'guard.json'
        path.write_text(json.dumps(receipt), encoding='utf8')
        return path

    def test_guard_evidence_is_separate_sampled_and_never_implies_completion(self):
        result = self.report([start(), checkpoint(1, 10, 5, 'advance')], guard_path=self.guard())
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assert_reconciled(result, 10, 5)
        guard = result['guard_sampled_evidence']
        self.assertIn('PID matches', guard['binding'])
        self.assertIn('sampled', guard['scope'])
        self.assertIn('exited-process tails', guard['scope'])
        self.assertIn('lifetime', guard['scope'])
        self.assertEqual(guard['resource_summary']['overlapping_identity_cpu_seconds'], 8.0)
        result = self.report([start(), end(1, 10, 5)], guard_path=self.guard(parent=None))
        self.assertEqual(result['status'], 'COMPLETE')
        self.assertIn('UNVERIFIED', result['guard_sampled_evidence']['binding'])

    def test_guard_schema_pid_and_size_refusals(self):
        for fields in ({'parent': {'pid': 124}}, {'schema': 'foreign'}, {'resource_summary': None},
                       {'parent': {'pid': True}},
                       {'resource_summary': {'schema':'atlas.private.resource-summary.r1', 'payload': []}},
                       {'resource_summary': {'schema':'atlas.private.resource-summary.r1', 'samples': 10**1000}}):
            with self.subTest(fields=str(fields)[:80]):
                result = self.report([start(), end(1, 10, 5)], guard_path=self.guard(**fields))
                self.assertEqual(result['status'], 'REFUSED')
                self.assertEqual(result['coverage']['status'], 'COMPLETE')
                self.assert_reconciled(result, 10, 5)
        with patch.object(R, 'MAX_GUARD_BYTES', 20):
            self.assertEqual(self.report([start()], guard_path=self.guard())['status'], 'REFUSED')

    def test_cli_complete_partial_and_guard_refused_exit_codes(self):
        for records, expected, guard in (([start(), end(1, 10, 5)], 0, None),
                                         ([start()], 2, None),
                                         ([start(), end(1, 10, 5)], 2, self.guard(parent={'pid': 9}))):
            with self.subTest(expected=expected, guard=guard):
                command = [sys.executable, '-B', R.__file__, '--events', str(self.write(records))]
                if guard is not None:
                    command.extend(['--guard-receipt', str(guard)])
                result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(json.loads(result.stdout)['schema'], R.REPORT_SCHEMA)
                self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
