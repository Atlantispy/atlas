"""Synthetic Route 2 admission evidence; no workload or scientific acceptance."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import route2_gate as RG
import start_gate as SG


GIB = 1 << 30
CHECKS = set('guard_schema guard_stopped guard_exit guard_cleanup guard_limits guard_parent '
    'guard_control guard_supervisor guard_no_abort resource_summary tracking launch_record '
    'launch_sources_unchanged no_live_workers run_schema run_status run_errors zero_reservations '
    'not_production_acceptance original_unchanged_recorded reopen_scope run_guard_limits '
    'run_start_gate profile_pin interpreter_seed checkpoint original_database sources gate_evidence'.split())


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def binding(path):
    return dict(path=str(path.resolve()), sha256=sha256(path.read_bytes()).hexdigest())


def decision(key, peak=GIB):
    # Independent integer oracle for the existing policy.
    return dict(schema='atlas.private.start-gate.r1', key=key, predicted_peak_bytes=peak,
        basis='declared booking (no completed PASS record)', measured=[],
        booking=dict(bytes=peak, basis='synthetic test booking', used=True),
        gate_bytes=peak+(peak+4)//5+2*GIB, margin='1/5', free_floor_bytes=GIB, allowance_bytes=GIB)


class Evidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='route2-gate-')
        self.root = Path(self.temp.name).resolve()
        self.entry, self.python, self.guard_source = (self.root/name for name in ('entry.py', 'python.exe', 'guard.py'))
        for path in (self.entry, self.python, self.guard_source):
            path.write_bytes(b'synthetic identity only: '+path.name.encode())
        self.row = dict(schema='atlas.prepared-restart-launch.v1', workspace=str(self.root),
            output_directory=str(self.root/'producer'), source_manifest=dict(path='manifest.json', sha256='a'*64),
            preparation=dict(path='preparation.json', sha256='b'*64), completed_query_directory='queries',
            completed_query_limits=dict(max_entries=10, max_store_bytes=GIB), storage_format='native-v1')
        self.sequence = 0

    def tearDown(self):
        self.temp.cleanup()

    def key(self, row=None, step='producer', **options):
        profile = SimpleNamespace(record=lambda: deepcopy(self.row if row is None else row))
        if step == 'reader':
            options = dict(dict(producer_receipt_sha256='c'*64, mode='successor', store_route='readonly'), **options)
        return RG.command_key(profile, self.python, entry=self.entry, step=step, **options)

    def bundle(self, *, step='producer', staged=False, mode='successor', peak=5*GIB):
        self.sequence += 1
        output = self.root/('attempt-%d' % self.sequence)
        output.mkdir()
        row = deepcopy(self.row)
        if step == 'producer':
            row['output_directory'] = str(output)
        profile_path = self.root/('profile-%d.json' % self.sequence)
        profile_path.write_bytes(raw(row))
        key = self.key(row, step=step, **(dict(stop_before_advance=staged) if step == 'producer' else dict(mode=mode)))
        gate = decision(key)
        admitted = dict(gate, available_bytes=16*GIB, hash_randomization=0)
        parent = dict(pid=4242, created_ticks=133000000000000000)
        limits = dict(rss_bytes=12*GIB, free_floor_bytes=GIB)
        guard = dict(schema='atlas.private.continuation-guard.r3', status='STOPPED', reason=None,
            workload_exit_confirmed=True, workload_exit_code=0, cleanup=dict(remaining=[], action_errors=[]),
            limits=limits, parent=parent, nonce='fixture-nonce', guardian=dict(pid=777), samples=3,
            sampled_peak_bytes=dict(parent_rss=GIB, process_tree_rss=peak), sample_interval=.25, grace_seconds=5.)
        control = dict(parent=parent, nonce='fixture-nonce', close_requested=True, limits=limits)
        run = dict(pid=4242, profile_sha256=binding(profile_path)['sha256'], errors=[], production_acceptance=False,
            final_reserved_bytes=0, start_gate=admitted, guard_limits=dict(rss_bytes=12*GIB, free_floor_bytes=GIB,
                logical_budget_bytes=16*GIB, start_available_bytes=gate['gate_bytes']),
            supervisor=dict(pid=777, status='STOPPED'), resources=dict(sampled_peak_bytes=dict(process_tree_rss=peak-1)))
        basename = 'run' if step == 'producer' else 'reopen'
        paths = dict(profile=profile_path, run=output/(basename+'.json'), guard=output/(basename+'.guard.json'),
                     control=output/(basename+'.guard-control.json'))
        rows = dict(profile=row, run=run, guard=guard, control=control)
        if step == 'producer':
            run.update(schema='atlas.prepared-restart-result.v1', stop_before_advance=staged,
                status='STOPPED_BEFORE_ADVANCE_ROOT_PUBLISHED' if staged else 'PASS_ONE_INTERVAL_PENDING_INDEPENDENT_REOPEN')
            argv = [str(self.python), '-B', str(self.guard_source), '--launch', '--output', str(paths['run']), '--',
                str(self.python), '-B', str(self.entry), '--workload', '--profile', str(profile_path),
                '--profile-sha256', binding(profile_path)['sha256']]
            argv += ['--stop-before-advance'] if staged else []
            argv += ['--start-gate', raw(gate).decode()]
            rows['launch'] = dict(schema='atlas.private.monitored-interval-launch.r1', status='PREFLIGHT_PASSED',
                cwd=str(output), profile=binding(profile_path), env=dict(RG.ENVIRONMENT), stop_before_advance=staged,
                dev_timing=False, start_gate=admitted, workload=binding(self.entry), python=str(self.python),
                source_manifest=row['source_manifest'], guard=binding(self.guard_source), argv=argv)
            rows['tracking'] = dict(output=str(output), parent=parent, guardian=dict(pid=777))
            paths.update(launch=self.root/(output.name+'.launch.json'), tracking=self.root/(output.name+'.tracking.json'))
            names = CHECKS | ({'root_only'} if staged else {'one_interval', 'completed_queries'})
            completed = dict(schema='atlas.private.monitored-interval-postcheck.r1', status='PASS', failures=[],
                checks=[dict(name=name, ok=True, detail=None) for name in sorted(names)],
                stop_before_advance=staged, output=str(output))
            final_path = self.root/(output.name+'.postcheck.json')
        else:
            run.update(schema='atlas.prepared-restart-reopen-result.v1',
                status='PASS_SUCCESSOR_REOPENED_PENDING_FINALISE' if mode == 'successor' else 'PASS_ROOT_REOPENED_PENDING_FINALISE',
                mode=mode, store_route='readonly', producer_receipt_sha256='c'*64, independent_process_reopen=True)
            completed = dict(schema='atlas.prepared-restart-reopen-final.v1',
                status='PASS_SECOND_INTERVAL_INDEPENDENT_REOPEN' if mode == 'successor' else
                       'PASS_MIGRATED_ROOT_INDEPENDENT_REOPEN_NOT_INTERVAL_ACCEPTANCE',
                errors=[], mode=mode, store_route='readonly', producer_receipt_sha256='c'*64, independent_process_reopen=True)
            final_path = output/'reopen-final.json'
        for role, path in paths.items():
            path.write_bytes(raw(rows[role]))
        snapshots = {role: (deepcopy(rows[role]), binding(path)) for role, path in paths.items()}
        expected = dict(schema='atlas.private.route2-peak.r1', key=key, peak_bytes=peak,
                        records={role: binding(path) for role, path in paths.items()})
        completed.update(production_acceptance=False, profile_sha256=binding(profile_path)['sha256'], gate_evidence=expected)
        if step == 'reader':
            completed['reopen_receipt_sha256'] = binding(paths['run'])['sha256']
        final_path.write_bytes(raw(completed))
        return SimpleNamespace(key=key, paths=paths, snapshots=snapshots, expected=expected,
                               completed=completed, final=final_path, rows=rows)

    def test_independent_successful_producer_reader_and_root_bundles(self):
        for options in ({}, dict(staged=True), dict(step='reader'), dict(step='reader', mode='root-only')):
            with self.subTest(options=options):
                b = self.bundle(**options)
                self.assertEqual(RG.evidence(b.key, b.snapshots), b.expected)
                result = RG.decide(b.key, records=[b.final], booking_bytes=2*GIB, booking_basis='lower booking')
                self.assertEqual((result['predicted_peak_bytes'], result['gate_bytes']), (5*GIB, 8*GIB))
                self.assertFalse(result['booking']['used'])

    def test_largest_measurement_and_declared_fallback(self):
        first, second = self.bundle(peak=3*GIB), self.bundle(peak=5*GIB)
        self.assertEqual(first.key, second.key)
        self.assertEqual(RG.decide(first.key, records=[first.final, second.final])['gate_bytes'], 8*GIB)
        fallback = RG.decide(first.key, booking_bytes=GIB, booking_basis='explicit synthetic estimate')
        self.assertEqual(fallback['gate_bytes'], GIB+(GIB+4)//5+2*GIB)
        self.assertTrue(fallback['booking']['used'])
        for options in ({}, dict(booking_bytes=GIB), dict(booking_basis='only basis'),
                        dict(booking_bytes=True, booking_basis='boolean'), dict(booking_bytes=GIB, booking_basis=' ')):
            with self.subTest(options=options), self.assertRaises(ValueError):
                RG.decide(first.key, **options)

    def test_named_invalid_missing_duplicate_records_never_fall_back(self):
        b = self.bundle()
        historical = self.root/'historical.json'
        historical.write_bytes(raw(dict(schema='atlas.private.monitored-interval-postcheck.r1', status='PASS')))
        for records in ([historical], [self.root/'missing.json'], [b.final, b.final]):
            with self.subTest(records=records), self.assertRaises((ValueError, OSError)):
                RG.decide(b.key, records=records, booking_bytes=8*GIB, booking_basis='must not conceal evidence failure')

    def test_key_normalises_only_producer_attempt_and_separates_inputs_and_modes(self):
        producer, reader = self.key(), self.key(step='reader')
        changed = deepcopy(self.row)
        changed['output_directory'] = str(self.root/'other-attempt')
        self.assertEqual(producer, self.key(changed))
        self.assertNotEqual(reader, self.key(changed, step='reader'))
        for field, value in (('source_manifest', dict(path='manifest.json', sha256='d'*64)),
                             ('preparation', dict(path='preparation.json', sha256='d'*64)),
                             ('completed_query_directory', 'other-queries'),
                             ('completed_query_limits', dict(max_entries=11, max_store_bytes=GIB)),
                             ('storage_format', 'interval-catalog-v1')):
            with self.subTest(field=field):
                self.assertNotEqual(producer, self.key(dict(self.row, **{field: value})))
        self.assertNotEqual(producer, self.key(stop_before_advance=True))
        self.assertNotEqual(producer, self.key(dev_timing=True))
        self.assertNotEqual(reader, self.key(step='reader', mode='root-only'))
        self.assertNotEqual(reader, self.key(step='reader', store_route='copy-token'))
        self.assertNotEqual(reader, self.key(step='reader', producer_receipt_sha256='d'*64))
        self.python.write_bytes(b'changed executable bytes at same path')
        self.assertNotEqual(producer, self.key())

    def test_mismatched_command_keys_refuse(self):
        b = self.bundle()
        for key in (self.key(stop_before_advance=True), self.key(dev_timing=True), self.key(step='reader'),
                    self.key(dict(self.row, preparation=dict(path='changed', sha256='b'*64)))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                RG.decide(key, records=[b.final])

    def test_completion_status_checks_and_tampering_refuse(self):
        b = self.bundle()
        for edit in (lambda r: r.update(status='FAILED'), lambda r: r.update(failures=['sources']),
                     lambda r: r.update(output='foreign-attempt'),
                     lambda r: r['checks'].pop(), lambda r: r['checks'].append(deepcopy(r['checks'][0])),
                     lambda r: r['checks'][0].update(ok=1), lambda r: r['gate_evidence'].update(peak_bytes=1)):
            row = deepcopy(b.completed)
            edit(row)
            b.final.write_bytes(raw(row))
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                RG.decide(b.key, records=[b.final])
        b.final.write_bytes(raw(b.completed))
        b.paths['guard'].write_bytes(raw(dict(b.rows['guard'], sampled_peak_bytes=dict(process_tree_rss=1))))
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            RG.decide(b.key, records=[b.final])

    def test_invalid_peak_guard_identity_and_mirror_refuse_publication(self):
        edits = [lambda s: s['guard'][0].update(status='HARD_STOPPED'),
                 lambda s: s['control'][0].update(nonce='foreign'),
                 lambda s: s['run'][0].update(status='FAILED'),
                 lambda s: s['run'][0]['resources']['sampled_peak_bytes'].update(process_tree_rss=6*GIB)]
        edits += [lambda s, value=value: s['guard'][0]['sampled_peak_bytes'].update(process_tree_rss=value)
                  for value in (None, True, 0, -1, 1.5)]
        for edit in edits:
            b = self.bundle()
            edit(b.snapshots)
            # Bind the modified synthetic bytes: failure must be semantic, not merely hash drift.
            for role, (row, _) in b.snapshots.items():
                b.paths[role].write_bytes(raw(row))
                b.snapshots[role] = (row, binding(b.paths[role]))
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                RG.evidence(b.key, b.snapshots)

    def test_publication_refuses_change_after_validation_snapshot(self):
        b = self.bundle()
        b.paths['guard'].write_bytes(b.paths['guard'].read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError, 'changed before completion publication'):
            RG.evidence(b.key, b.snapshots)

    def test_cross_attempt_paths_and_parent_decision_refuse(self):
        b = self.bundle()
        snapshots = deepcopy(b.snapshots)
        snapshots['profile'][0]['output_directory'] = str(self.root/'foreign-attempt')
        with self.assertRaisesRegex(ValueError, 'attempt paths differ'):
            RG.evidence(b.key, snapshots)
        snapshots = deepcopy(b.snapshots)
        snapshots['tracking'][1]['path'] = str(self.root/'foreign.tracking.json')
        with self.assertRaisesRegex(ValueError, 'attempt paths differ'):
            RG.evidence(b.key, snapshots)
        snapshots = deepcopy(b.snapshots)
        snapshots['launch'][0]['start_gate']['predicted_peak_bytes'] += 1
        with self.assertRaisesRegex(ValueError, 'admission decisions differ'):
            RG.evidence(b.key, snapshots)

    def test_strict_json_snapshot(self):
        path = self.root/'bad.json'
        for content in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'[]'):
            path.write_bytes(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                RG.read_snapshot(path)
        path.write_bytes(b'{"a":1}\n')
        self.assertEqual(RG.read_snapshot(path), ({'a': 1}, binding(path)))

    def test_child_arithmetic_seed_memory_and_documented_trust_boundary(self):
        key = self.key()
        understated = decision(key, peak=1)
        text = raw(understated).decode()
        seeded = SimpleNamespace(hash_randomization=0)
        self.assertEqual(SG.child_admit(text, 3*GIB, seeded)['predicted_peak_bytes'], 1)
        inconsistent = dict(understated, gate_bytes=understated['gate_bytes']-1)
        with self.assertRaises(ValueError):
            SG.child_admit(raw(inconsistent).decode(), 3*GIB, seeded)
        with self.assertRaises(ValueError):
            SG.child_admit(text, understated['gate_bytes']-1, seeded)
        with self.assertRaises(ValueError):
            SG.child_admit(text, 3*GIB, SimpleNamespace(hash_randomization=1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
