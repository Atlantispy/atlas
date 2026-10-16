"""Route (1) reader controls: closed producer/reader receipts, lineage, proved width streams, adoption inputs.

Synthetic records only; the real reopen runs in the synthetic run and the smoke.
"""
import contextlib
import copy
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
COMPACT = HERE/'compact-geometry-r1'
RUNTIME = HERE.parent/'runtime-integration-r1'/'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import reopen_fresh_restart as RF
import reopen_prepared_restart as RO
import run_fresh_interval as F
import run_prepared_restart as RUN
import width_gate as WG

PRODUCER, READER, SUPERVISOR = 100, 200, 77


def key(text):
    return sha256(text.encode()).hexdigest()


def digest(value):
    return sha256(F.canonical(value)).hexdigest()


def retained(pid):
    scalars = dict.fromkeys(RO.RETAINED_SCALARS, 0)
    scalars['peak_retained_bytes'] = 4096
    return {'limit_bytes': 256 << 20, 'scope_id': 'scope', 'process_epoch': 'prepared-restart-'+str(pid),
            **scalars, **{name: {} for name in RO.RETAINED_MAPPINGS}}


def guard_records(pid):
    limits = {'rss_bytes': RUN.RSS_BYTES, 'free_floor_bytes': RUN.FREE_BYTES}
    parent = {'pid': pid, 'created_ticks': 1}
    guard = {'schema': RO.GUARD_SCHEMA, 'status': 'STOPPED', 'reason': None, 'workload_exit_confirmed': True,
             'workload_exit_code': 0, 'cleanup': {'remaining': [], 'action_errors': []}, 'parent': parent,
             'nonce': 'nonce', 'guardian': {'pid': SUPERVISOR}, 'limits': limits}
    control = {'parent': parent, 'nonce': 'nonce', 'close_requested': True, 'limits': limits}
    return guard, control


def head_wire(text):
    return {'segment': key(text)}


def array_records():
    return {group: [{'name': group+'-a', 'shape': [2], 'dtype': '<f8', 'sha256': key(group)}]
            for group in sorted(RO.GROUPS)}


class Fixture:
    """One consistent run A / run B record set; tests break exactly one thing each."""

    def __init__(self):
        self.profile = F.FreshProfile(Path('profile.json'), key('profile'), b'{}')
        self.identities = {'producer_identity': key('profile'), 'runtime_identity': key('runtime')}
        self.root_metadata = {'key': key('root'), 'kind': 'root', 'funding_id': 'funding',
                              'state': {'fields': {'time_s': 0}}}
        self.root = {'workflow_id': key('workflow'), 'root_key': key('root'), 'kind': 'root', 'sequence': 0,
                     'inspect': {'head': key('root'), 'intervals': 0, 'workflow_id': key('workflow'),
                                 'funding_id': 'funding', 'time_s': 0.0},
                     'producer_pid': PRODUCER, 'root_metadata_sha256': digest(self.root_metadata),
                     'store_limits': dict(RUN.COMPACT_STORE_LIMITS), 'store_compression': dict(RUN.COMPACT_COMPRESSION),
                     'execution_provenance': {'execution_identity': key('execution'), 'execution_mode': 'strict'},
                     'preparation_ids': {name: 'funding' if name == 'funding' else name for name in RO.PREPARATIONS}}

    def entry(self, interval):
        return {'interval': interval, 'filename': f'interval-{interval:04d}.sqlite', 'file_sha256': key('file'),
                'logical_seal': key('seal'), 'head': head_wire(str(interval)), 'references': [], **self.identities}

    def records(self, mode):
        interval = F.INTERVALS[mode]
        runner = {'schema': F.RUNNER_RECORD_SCHEMA, 'interval': interval, 'head': head_wire(str(interval)),
                  'workflow_id': key('workflow'), 'producer_pid': PRODUCER, **self.identities}
        root_runner = None
        if mode == 'root':
            runner['root'] = copy.deepcopy(self.root)
        else:
            root_runner = dict(self.records('root')[0], producer_pid=PRODUCER-1)
            root_runner['root'] = dict(root_runner['root'], producer_pid=PRODUCER-1)
            runner.update(previous_endpoint=copy.deepcopy(self.root['inspect']),
                          advanced_endpoint={'head': key('head'), 'intervals': 1, 'workflow_id': key('workflow'),
                                             'funding_id': 'funding', 'time_s': 1.5},
                          record_identities={name: {'sha256': key(name), 'nbytes': 10} for name in (
                              'state', 'partition', 'mesh', 'exchange', 'graph', 'transport', 'heat',
                              'certification', 'differential')},
                          root_runner_record_sha256=digest(root_runner))
        sealed = {'schema': F.SEALED_SCHEMA, 'interval': interval, 'entry': self.entry(interval),
                  'expected_catalog_digest': None if mode == 'root' else key('catalog'),
                  'runner_record_sha256': digest(runner)}
        return runner, sealed, root_runner

    def receipt(self, mode, runner, sealed):
        interval = F.INTERVALS[mode]
        receipt = {'schema': F.RESULT_SCHEMA, 'status': F.SEALED_STATUS[mode], 'errors': [], 'final_reserved_bytes': 0,
                   'production_acceptance': False, 'profile_sha256': self.profile.sha256, 'mode': mode,
                   'interval': interval, 'pid': PRODUCER, 'same_process_cold_reopen': False,
                   'same_process_cold_reopen_reason': RF.REOPEN_REASON[mode],
                   'compact_retained_before_close': retained(PRODUCER),
                   'compact_retained_after_close': retained(PRODUCER),
                   'source_proof': {'source_manifest_sha256': key('manifest'), 'native_source_digest': key('runtime')},
                   'identities': dict(self.identities),
                   'runner_record': {'path': 'runner', 'sha256': digest(runner)}, 'sealed': copy.deepcopy(sealed),
                   'supervisor': {'pid': SUPERVISOR}}
        if mode == 'root':
            receipt.update(published_root=copy.deepcopy(runner['root']), workflow_id=key('workflow'))
        else:
            completed = {'workflow_id': key('workflow'), 'root_key': key('root'),
                         'root_metadata': copy.deepcopy(self.root_metadata), 'head_key': key('head'),
                         'producer_pid': PRODUCER, 'store_limits': dict(RUN.COMPACT_STORE_LIMITS),
                         'store_compression': dict(RUN.COMPACT_COMPRESSION), 'collar_result_id': 'collar',
                         'native_result_id': 'native', 'exterior_state_id': 'exterior', 'source_audit_id': 'audit',
                         'joined_heat_id': 'heat', 'array_records': array_records(),
                         'preparation_ids': copy.deepcopy(self.root['preparation_ids']),
                         'execution_provenance': copy.deepcopy(self.root['execution_provenance']), 'sequence': 1}
            receipt.update(previous_endpoint=copy.deepcopy(runner['previous_endpoint']),
                           advanced_endpoint=copy.deepcopy(runner['advanced_endpoint']),
                           record_identities=copy.deepcopy(runner['record_identities']), completed_endpoint=completed,
                           completed_query_store={'declared': 'columnar', 'arguments': F.QUERY_STORES['columnar']},
                           completed_queries={'store': 'columnar', 'hits': 0, 'misses': 3, 'written': 3,
                                              'incomplete': 0, 'unflushed': 0})
        return receipt

    def validate(self, mode, *, receipt=None, runner=None, sealed=None, root_runner=None, guard=None):
        base_runner, base_sealed, base_root = self.records(mode)
        runner, sealed = runner or base_runner, sealed or base_sealed
        receipt = receipt or self.receipt(mode, runner, sealed)
        guard_receipt, control = guard or guard_records(PRODUCER)
        return RF.validate_producer_receipt(receipt, profile=self.profile, receipt_sha256=key('receipt'),
            runner=runner, sealed=sealed, guard_receipt=guard_receipt, guard_control=control, consumer_pid=READER,
            mode=mode, root_runner=root_runner or base_root)


class ProducerReceiptTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()

    def test_consistent_root_and_interval_records_validate(self):
        root = self.f.validate('root')
        self.assertEqual((root['interval'], root['root'], root['producer_pid']), (0, self.f.root, PRODUCER))
        interval = self.f.validate('interval')
        self.assertEqual(interval['completed_endpoint']['head_key'], key('head'))
        self.assertEqual(interval['root']['workflow_id'], key('workflow'))

    def refuse(self, mode, message, change):
        runner, sealed, root_runner = self.f.records(mode)
        receipt = self.f.receipt(mode, runner, sealed)
        guard = guard_records(PRODUCER)
        change(SimpleNamespace(receipt=receipt, runner=runner, sealed=sealed, root_runner=root_runner, guard=guard))
        # Refusals come from this reader and from the shared validators (ReopenRefused, RestartRefused).
        with self.assertRaisesRegex(ValueError, message):
            self.f.validate(mode, receipt=receipt, runner=runner, sealed=sealed, root_runner=root_runner, guard=guard)

    def test_root_refusals(self):
        cases = (
            ('successful sealed producer', lambda c: c.receipt.update(status='FAILED')),
            ('successful sealed producer', lambda c: c.receipt.update(errors=[{'type': 'X'}])),
            ('successful sealed producer', lambda c: c.receipt.update(interval=1)),
            ('separate producer and reader', lambda c: c.receipt.update(pid=READER)),
            ('reopen scope differs', lambda c: c.receipt.update(same_process_cold_reopen=True)),
            ('retained scope was not released', lambda c: c.receipt['compact_retained_after_close'].update(
                retained_bytes=1, pinned_bytes=1, purpose_bytes={'x': 1})),
            ('identities differ', lambda c: c.receipt['identities'].update(runtime_identity=key('other'))),
            ('sealed entry, runner record', lambda c: c.runner.update(head=head_wire('forged'))),
            ('sealed entry, runner record', lambda c: c.sealed['entry'].update(runtime_identity=key('other'))),
            ('sealed entry, runner record', lambda c: c.receipt['runner_record'].update(sha256=key('other'))),
            ('fresh root identity', lambda c: c.runner['root'].update(sequence=1)),
            ('strict source/runtime', lambda c: c.runner['root']['execution_provenance'].update(execution_mode='x')),
            ('compact store bounds', lambda c: c.runner['root']['store_limits'].update(chunk_bytes=1)),
            ('not the first interval', lambda c: c.sealed.update(expected_catalog_digest=key('catalog'))),
            ('not the first interval', lambda c: c.receipt['published_root'].update(producer_pid=1)),
            ('guardian did not stop cleanly', lambda c: c.guard[0].update(workload_exit_code=1)),
        )
        for message, change in cases:
            with self.subTest(message=message):
                def keep_bound(c, change=change, message=message):
                    change(c)
                    # Re-bind the runner record after its own change, so only the intended check can refuse.
                    if c.runner is not None and 'sealed entry' not in message:
                        c.sealed['runner_record_sha256'] = digest(c.runner)
                        c.receipt['runner_record']['sha256'] = digest(c.runner)
                        c.receipt['sealed'] = copy.deepcopy(c.sealed)
                self.refuse('root', message, keep_bound)

    def test_interval_refusals(self):
        def rebind(c):
            c.sealed['runner_record_sha256'] = digest(c.runner)
            c.receipt.update(runner_record={'path': 'runner', 'sha256': digest(c.runner)},
                             sealed=copy.deepcopy(c.sealed))
        cases = (
            ('do not extend run A', lambda c: c.runner.update(root_runner_record_sha256=key('other'))),
            ('record identities differ from their receipt', lambda c: c.receipt.update(record_identities={})),
            ('advance run A root exactly once', lambda c: c.runner['advanced_endpoint'].update(intervals=2)),
            ('advance run A root exactly once', lambda c: c.runner['advanced_endpoint'].update(time_s=0.0)),
            ('advance run A root exactly once', lambda c: c.runner['advanced_endpoint'].update(funding_id='x')),
            ('completed-query record', lambda c: c.receipt['completed_queries'].update(store='files')),
            ('does not extend run A root', lambda c: c.receipt['completed_endpoint'].update(sequence=2)),
            ('does not extend run A root', lambda c: c.receipt['completed_endpoint']['root_metadata'].update(x=1)),
            ('complete exact array', lambda c: c.receipt['completed_endpoint']['array_records']['collar'][0].update(
                sha256='x')),
        )
        for message, change in cases:
            with self.subTest(message=message):
                def apply(c, change=change):
                    change(c)
                    if c.receipt.get('advanced_endpoint') is not c.runner['advanced_endpoint']:
                        c.receipt['advanced_endpoint'] = copy.deepcopy(c.runner['advanced_endpoint'])
                    rebind(c)
                self.refuse('interval', message, apply)


class LineageAndWidthTests(unittest.TestCase):
    def heads(self):
        root = {'state': {'fields': {'time_s': 0}}, 'funding_id': 'funding'}
        head = {'state': {'fields': {'time_s': 1.5}}, 'funding_id': 'funding',
                'differential_geometry': {'start_time_s': ['0x0', '0x1'], 'end_time_s': ['0x3', '0x2'],
                                          'interval_id': 'i1'},
                'differential_partition': {'partition_id': 'p1'}}
        observed = {'interval_id': 'i1', 'partition_id': 'p1', 'fields_time_s': 1.5, 'native_time_s': 1.5,
                    'exterior_time_s': 1.5, 'funding_id': 'funding'}
        return root, head, observed

    def test_fresh_lineage_exact_clocks_interval_and_funding(self):
        root, head, observed = self.heads()
        self.assertTrue(RF.validate_fresh_lineage(root=root, head=head, observed=observed)['root_is_parent'])
        cases = (
            ('clocks differ', lambda r, h, o: h['differential_geometry'].update(start_time_s=['0x1', '0x1'])),
            ('state clocks differ', lambda r, h, o: o.update(native_time_s=1.25)),
            ('interval or partition', lambda r, h, o: o.update(partition_id='p2')),
            ('funding identity changed', lambda r, h, o: h.update(funding_id='other')),
            ('reduced canonical', lambda r, h, o: h['differential_geometry'].update(end_time_s=['0x6', '0x4'])),
            ('header missing', lambda r, h, o: h.pop('differential_geometry')),
        )
        for message, change in cases:
            with self.subTest(message=message):
                root, head, observed = self.heads()
                change(root, head, observed)
                with self.assertRaisesRegex(ValueError, message):
                    RF.validate_fresh_lineage(root=root, head=head, observed=observed)

    def test_width_stream_must_be_the_proved_record(self):
        record = F.canonical({'cells': [['0xff', '0x3']], 'trajectory_segments': [{}]})
        refs = {'state': {'sha256': sha256(record).hexdigest(), 'bytes': len(record)}}

        class Child:
            def __init__(self, raw):
                self.raw, self.closed = raw, False

            def iter_json(self):
                yield self.raw[:5]
                yield memoryview(self.raw[5:])

            def close(self):
                self.closed = True

        def fake_open(raw):
            @contextlib.contextmanager
            def open_records(store, refs, **_):
                yield {'state': Child(raw)}
            return open_records
        import spatial_records_patch as SR
        table = WG.WidthTable(0)
        with mock.patch.object(SR, 'open_records', fake_open(record)):
            result = RF._proved_records(None, refs, budget=None, scope=None, source_producer=None, table=table)
        self.assertEqual(result, {'state': {'sha256': refs['state']['sha256'], 'nbytes': len(record)}})
        self.assertEqual(table.records['state']['cells']['max_numerator_bits'], 8)
        self.assertEqual(table.trajectory_steps, 1)
        forged = F.canonical({'cells': [['0x1', '0x3']], 'trajectory_segments': [{}]})
        with mock.patch.object(SR, 'open_records', fake_open(forged)), \
                self.assertRaisesRegex(RF.ReaderRefused, 'width stream differs from the proved record'):
            RF._proved_records(None, refs, budget=None, scope=None, source_producer=None, table=WG.WidthTable(0))

    def native_root(self, records, *, stored=None):
        """A reopened native root (smoke, 16 Oct): record_blobs state and mesh as JSON arrays of the root."""
        import numpy as np
        stored = dict(records if stored is None else stored)
        blobs = {name: {'array': 'spatial-record:'+name, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
                 for name, raw in records.items()}
        reads = []

        class Store:
            scope = SimpleNamespace(run_budget='budget')

            def iter_chunks(self, key, name, *, budget):
                reads.append((key, name, budget))
                raw = stored[name.removeprefix('spatial-record:')]
                for start in range(0, len(raw), 4):
                    yield start, np.frombuffer(raw[start:start+4], dtype=np.uint8)
        head = {'kind': 'root', 'key': 'root-key', 'exterior_state': {'record_blobs': blobs}}
        return SimpleNamespace(_store=Store(), _budget='budget', _head=head), reads

    def test_native_root_records_are_streamed_proved_and_scanned(self):
        records = {'state': F.canonical({'cells': [['0xff', '0x3']], 'trajectory_segments': [{}]}),
                   'mesh': F.canonical({'cells': [['0x7', '0x1']], 'faces': []})}
        workflow, reads = self.native_root(records)
        table = WG.WidthTable(0)
        result = RF.root_record_identities(workflow, table)
        self.assertEqual(result, {name: {'sha256': sha256(raw).hexdigest(), 'nbytes': len(raw)}
                                  for name, raw in records.items()})
        self.assertEqual(sorted(reads), [('root-key', 'spatial-record:mesh', 'budget'),
                                         ('root-key', 'spatial-record:state', 'budget')])
        self.assertEqual(table.records['state']['cells']['max_numerator_bits'], 8)
        forged = dict(records, mesh=F.canonical({'cells': [['0x5', '0x1']], 'faces': []}))
        workflow, _ = self.native_root(records, stored=forged)
        with self.assertRaisesRegex(RF.ReaderRefused, 'width stream differs from the proved record: mesh'):
            RF.root_record_identities(workflow, WG.WidthTable(0))
        workflow, _ = self.native_root({'state': records['state']})
        with self.assertRaisesRegex(RF.ReaderRefused, 'native root state and mesh records required'):
            RF.root_record_identities(workflow, WG.WidthTable(0))
        workflow, _ = self.native_root(records)
        workflow._head['exterior_state']['record_blobs']['mesh']['array'] = 'spatial-record:other'
        with self.assertRaisesRegex(RF.ReaderRefused, 'native root record reference differs: mesh'):
            RF.root_record_identities(workflow, WG.WidthTable(0))


class ReaderReceiptAndAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture()
        self.producer = self.f.validate('interval')

    def reopen(self):
        widths = WG.WidthTable(1)
        widths.scan('heat', [F.canonical({'r': ['0xff', '0x1']})])
        checks = dict.fromkeys(RF.CHECKS['interval'], True)
        return {'schema': RF.READER_SCHEMA, 'status': RF.WORKLOAD_STATUS['interval'], 'errors': [],
                'final_reserved_bytes': 0, 'production_acceptance': False, 'independent_process_reopen': True,
                'mode': 'interval', 'profile_sha256': self.f.profile.sha256, 'producer_receipt_sha256': key('receipt'),
                'review_only': False,
                'remaining_children': [], 'pid': READER, 'independent_checks': checks, 'view_digest': key('view'),
                'widths': widths.wire(), 'record_identities': copy.deepcopy(self.producer['runner']['record_identities']),
                'width_gate': WG.gate(WG.WidthTable(0), widths),
                'retained_scope': {'before_close': retained(READER), 'after_close': retained(READER)},
                'supervisor': {'pid': SUPERVISOR}}

    def validate(self, reopen):
        guard, control = guard_records(READER)
        RF.validate_reopen_receipt(reopen, guard_receipt=guard, guard_control=control, profile=self.f.profile,
                                   producer=self.producer, mode='interval')

    def test_reader_receipt_closed_checks(self):
        self.validate(self.reopen())
        cases = (
            ('successful independent reader', lambda r: r.update(status='FAILED')),
            ('successful independent reader', lambda r: r.update(remaining_children=[5])),
            ('process separate from the producer', lambda r: r.update(pid=PRODUCER)),
            ('every independent reopen check', lambda r: r['independent_checks'].update(fresh_lineage=False)),
            ('every independent reopen check', lambda r: r['independent_checks'].pop('store_unchanged')),
            ('pending view digest', lambda r: r.update(view_digest='x')),
            ('another interval', lambda r: r.update(widths=WG.WidthTable(0).wire())),
            ('compact logical records differ', lambda r: r['record_identities']['heat'].update(nbytes=11)),
            ('width gate', lambda r: r.pop('width_gate')),
            ('retained scope release', lambda r: r['retained_scope'].pop('after_close')),
        )
        for message, change in cases:
            with self.subTest(message=message):
                reopen = self.reopen()
                change(reopen)
                with self.assertRaisesRegex(ValueError, message):
                    self.validate(reopen)

    def test_adoption_uses_one_consistent_record_set_only(self):
        with tempfile.TemporaryDirectory(prefix='ra-', dir=HERE) as temporary:
            store = Path(temporary)
            runner, sealed, _ = self.f.records('interval')
            runner_sha = F.write_durable(F.runner_record_path(store, 1), runner)
            F.write_durable(F.sealed_record_path(store, 1), sealed)
            verdict = {'schema': F.VERDICT_SCHEMA, 'status': F.READER_PASS['interval'], 'interval': 1,
                       'entry': sealed['entry'], 'runner_record_sha256': runner_sha, 'view_digest': key('view')}
            pin = F.write_durable(F.verdict_path(store, 1), verdict)
            found = RF.adoption_inputs(store, 1, pin)
            self.assertEqual(found, (verdict, runner, sealed))
            with self.assertRaisesRegex(F.FreshRefused, 'differs from its recorded SHA-256'):
                RF.adoption_inputs(store, 1, key('another verdict'))
            for name, change in (('status', {'status': 'FAILED'}), ('entry', {'entry': self.f.entry(0)}),
                                 ('view', {'view_digest': 'x'})):
                with self.subTest(change=name):
                    F.verdict_path(store, 1).unlink()
                    pin = F.write_durable(F.verdict_path(store, 1), {**verdict, **change})
                    with self.assertRaisesRegex(F.FreshRefused, 'one consistent runner record'):
                        RF.adoption_inputs(store, 1, pin)


class ReviewTests(unittest.TestCase):
    """Piece 3: an interval sealed for review is read only with --review and adopted only with a recorded approval."""

    def setUp(self):
        self.f = Fixture()
        self.cause = {'type': 'PresealRefused', 'message': 'binding differs',
                      'first_raised': {'type': 'PresealRefused', 'message': 'binding differs'}}

    def review_records(self):
        runner, sealed, root_runner = self.f.records('interval')
        receipt = self.f.receipt('interval', runner, sealed)
        receipt.pop('record_identities')
        runner.pop('record_identities')
        runner.update(review_only=True, preseal_refused=self.cause)
        sealed['runner_record_sha256'] = digest(runner)
        receipt.update(runner_record={'path': 'runner', 'sha256': digest(runner)}, sealed=copy.deepcopy(sealed))
        entry = sealed['entry']
        receipt.update(status=F.REVIEW_STATUS, preseal_refused=self.cause,
                       errors=[{'type': 'PresealSealedForReview', 'message': 'sealed for review'}],
                       review_only={'state': F.REVIEW_STATUS, 'cause': self.cause, 'adoption': F.REVIEW_ADOPTION,
                                    'sealed_file': {k: entry[k] for k in ('filename', 'file_sha256', 'logical_seal')}})
        return receipt, runner, sealed, root_runner

    def validate(self, receipt, runner, sealed, root_runner, *, review):
        guard, control = guard_records(PRODUCER)
        return RF.validate_producer_receipt(receipt, profile=self.f.profile, receipt_sha256=key('receipt'),
            runner=runner, sealed=sealed, guard_receipt=guard, guard_control=control, consumer_pid=READER,
            mode='interval', root_runner=root_runner, review=review)

    def test_review_receipts_need_the_review_flag_and_the_flag_needs_them(self):
        receipt, runner, sealed, root_runner = self.review_records()
        self.assertTrue(self.validate(receipt, runner, sealed, root_runner, review=True)['review'])
        with self.assertRaisesRegex(ValueError, 'successful sealed producer'):
            self.validate(receipt, runner, sealed, root_runner, review=False)
        runner2, sealed2, root2 = self.f.records('interval')
        with self.assertRaisesRegex(ValueError, 'successful sealed producer'):
            self.validate(self.f.receipt('interval', runner2, sealed2), runner2, sealed2, root2, review=True)
        receipt['review_only']['sealed_file']['file_sha256'] = key('another file')
        with self.assertRaisesRegex(ValueError, 'one refusal and this sealed file'):
            self.validate(receipt, runner, sealed, root_runner, review=True)
        with self.assertRaisesRegex(ValueError, 'only an interval'):
            RF._producer_receipt({}, profile=self.f.profile, mode='root', consumer_pid=READER, review=True)

    def test_adoption_requires_every_review_condition(self):
        with tempfile.TemporaryDirectory(prefix='rv-', dir=HERE) as temporary:
            store = Path(temporary)
            _, runner, sealed, _ = self.review_records()
            runner_sha = F.write_durable(F.runner_record_path(store, 1), runner)
            F.write_durable(F.sealed_record_path(store, 1), sealed)
            verdict = {'schema': F.VERDICT_SCHEMA, 'status': F.READER_PASS['interval'], 'interval': 1,
                       'entry': sealed['entry'], 'runner_record_sha256': runner_sha, 'view_digest': key('view'),
                       'review_only': True, 'preseal_refused': self.cause}
            verdict_sha = F.write_durable(F.verdict_path(store, 1), verdict)
            with self.assertRaisesRegex(ValueError, 'needs its recorded approval'):
                RF.adoption_inputs(store, 1, verdict_sha)
            diagnosis = store/'diagnosis.md'
            diagnosis.write_text('checker defect: draft binding helpers', encoding='utf8')
            approval = {'schema': RF.REVIEW_APPROVAL_SCHEMA, 'interval': 1, 'file_sha256': sealed['entry']['file_sha256'],
                        'verdict_sha256': verdict_sha, 'approver': 'coordinator', 'approved_at': '2026-10-16T07:30',
                        'cause_class': 'checker-defect',
                        'diagnosis': {'path': str(diagnosis), 'sha256': RUN.file_hash(diagnosis)}}
            cases = (('data-integrity cause is quarantined', {'cause_class': 'data-defect'}),
                     ('does not name this sealed file', {'file_sha256': key('another file')}),
                     ('does not name this sealed file', {'verdict_sha256': key('another verdict')}),
                     ('does not name this sealed file', {'approver': 'the runner'}),
                     ('written diagnosis evidence', {'diagnosis': {'path': str(diagnosis), 'sha256': key('x')}}))
            for message, change in cases:
                with self.subTest(message=message, change=sorted(change)):
                    RF.approval_path(store, 1).unlink(missing_ok=True)
                    pin = F.write_durable(RF.approval_path(store, 1), {**approval, **change})
                    with self.assertRaisesRegex(ValueError, message):
                        RF.adoption_inputs(store, 1, verdict_sha, pin)
            RF.approval_path(store, 1).unlink()
            pin = F.write_durable(RF.approval_path(store, 1), approval)
            self.assertEqual(RF.adoption_inputs(store, 1, verdict_sha, pin)[1], runner)

    def test_an_ordinary_interval_refuses_an_approval(self):
        with tempfile.TemporaryDirectory(prefix='ro-', dir=HERE) as temporary:
            store = Path(temporary)
            runner, sealed, _ = self.f.records('interval')
            runner_sha = F.write_durable(F.runner_record_path(store, 1), runner)
            F.write_durable(F.sealed_record_path(store, 1), sealed)
            verdict_sha = F.write_durable(F.verdict_path(store, 1), {'schema': F.VERDICT_SCHEMA,
                'status': F.READER_PASS['interval'], 'interval': 1, 'entry': sealed['entry'],
                'runner_record_sha256': runner_sha, 'view_digest': key('view')})
            with self.assertRaisesRegex(ValueError, 'only a review-only interval takes one'):
                RF.adoption_inputs(store, 1, verdict_sha, key('approval'))


class CliTests(unittest.TestCase):
    def test_action_arguments_are_exclusive_and_complete(self):
        base = ['--profile', 'p.json', '--profile-sha256', key('p'), '--mode', 'root']
        for extra in (['--adopt'], ['--finalise', '--producer-receipt-sha256', key('r')],
                      ['--producer-receipt-sha256', key('r'), '--verdict-sha256', key('v')], [],
                      ['--adopt', '--verdict-sha256', key('v'), '--review'],
                      ['--workload', '--producer-receipt-sha256', key('r'), '--review-approval-sha256', key('a')]):
            with self.subTest(extra=extra), self.assertRaisesRegex(F.FreshRefused, 'goes with'):
                RF.main(base+extra)

    def test_reader_output_and_statuses(self):
        row = {'output_directory': str(HERE/'attempt')}
        self.assertEqual(RF.reader_output(row, 'interval'), HERE/'attempt'/'reader-interval')
        self.assertNotIn('PASS', json.dumps(F.SEALED_STATUS))
        self.assertTrue(all(status.startswith('PASS_') for status in RF.WORKLOAD_STATUS.values()))


if __name__ == '__main__':
    unittest.main()
