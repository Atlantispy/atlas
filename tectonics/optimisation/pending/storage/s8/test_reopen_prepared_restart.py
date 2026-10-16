"""Pure controls for the independent fresh-process reader.

Synthetic receipts, metadata and guard records only: no store is opened and no
native runtime is imported. The composed two-process reader check is separate.
"""
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import ast
import gc
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

import reopen_prepared_restart as X
import run_prepared_restart as R
import workflow_transfer as W

HERE = Path(__file__).resolve().parent
ROOT = Path(R.__file__).resolve().parent  # SO: relocated copy; the reader sources stay in ROOT
WORKSPACE = Path(os.path.commonpath([HERE, ROOT]))  # SO: relocated copy
LIMITS = dict(rss_bytes=12 << 30, free_floor_bytes=1 << 30)


def encoded(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':')).encode()


def loaded_here():
    found = set()
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name and Path(name).suffix == '.py' and Path(name).resolve().parent in (HERE, ROOT):  # SO: relocated copy
            found.add(Path(name).resolve())
    return found


def groups(sha='0'*64):
    return {group: [dict(name='b', shape=[2], dtype='float64', sha256=sha),
                    dict(name='a', shape=[1, 2], dtype='<f8', sha256=sha)] for group in sorted(X.GROUPS)}


def guard_records(pid, guardian=777):
    parent = dict(pid=pid, created_ticks=133000000000000000)
    guard = dict(schema=X.GUARD_SCHEMA, status='STOPPED', reason=None, nonce='nonce-1', parent=parent,
        guardian=dict(pid=guardian), workload_exit_confirmed=True, workload_exit_code=0,
        cleanup=dict(remaining=[], action_errors=[]), limits=dict(LIMITS))
    control = dict(nonce='nonce-1', parent=dict(parent), phase='done', close_requested=True,
        limits=dict(LIMITS), sample_interval=.25, grace_seconds=5.)
    return guard, control


class Fixture(unittest.TestCase):
    """Synthetic profile and producer attempt; never an admission."""
    pid = 4242

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ro-', dir=HERE)
        self.folder = Path(self.temp.name)
        native = self.folder/'src'
        (native/'atlas_tectonics').mkdir(parents=True)
        (native/'atlas_tectonics/__init__.py').write_text('# synthetic reader fixture\n', encoding='utf8')
        helper = self.folder/'fixture_reader_helper.py'
        helper.write_text('# synthetic bound helper; never executed\n', encoding='utf8')
        policy = self.folder/'fixture-policy.json'
        policy.write_bytes(encoded({'fixture': 'NOT A COMPATIBILITY POLICY'}))
        relative = lambda p: Path(p).relative_to(WORKSPACE).as_posix()
        paths = {Path(R.__file__).resolve(), Path(X.__file__).resolve(), Path(__file__).resolve(), helper,
                 native/'atlas_tectonics/__init__.py', *loaded_here()}
        manifest = self.folder/'manifest.json'
        manifest.write_bytes(encoded(dict(files={relative(p): R.file_hash(p) for p in paths},
            source_hashes={'atlas_tectonics/__init__.py': R.file_hash(native/'atlas_tectonics/__init__.py')},
            data_only={})))
        pin = lambda p: dict(path=relative(p), sha256=R.file_hash(p))
        self.output = self.folder/'producer'
        row = dict(schema=R.PROFILE_SCHEMA, workspace=str(WORKSPACE), source_manifest=pin(manifest),
            native_root=relative(native), import_roots=[relative(self.folder), '.'],
            modules={name: relative(helper) for name in R.REQUIRED_MODULES}, preparation=pin(helper),
            compatibility_policy=pin(policy), evidence_root=relative(self.folder),
            historical_source_root=relative(native),
            advance_driver=dict(module='fixture_reader_driver', **pin(helper)),
            output_directory=str(self.output), store_limits=dict(chunk_bytes=65536, max_staging_bytes=1 << 20),
            compression=dict(codec='raw'), completed_query_directory=relative(self.folder/'queries'),
            completed_query_limits=dict(max_entries=10, max_store_bytes=1 << 20))
        self.profile_path = self.folder/'profile.json'
        self.profile_path.write_bytes(encoded(row))
        self.profile = R.RestartProfile.read(self.profile_path, R.file_hash(self.profile_path))
        self.sources = R.RestartSources(self.profile)
        self.output.mkdir()
        self.checkpoint = self.output/'checkpoint.sqlite'
        self.checkpoint.write_bytes(b'synthetic checkpoint bytes, never opened as a store')
        self.checkpoint_sha = R.file_hash(self.checkpoint)

    def tearDown(self):
        self.temp.cleanup()

    def receipt(self, mode='successor'):
        row = self.profile.record()
        ids = dict(owner='owner-id', spatial_owner='spatial-owner-id', native='native-plan',
                   collar='collar-plan', map='volume-map', funding='funding-id')
        provenance = dict(execution_identity='e'*64, execution_mode='strict')
        inspect = dict(workflow_id='wf', head='root-key', intervals=1, funding_id='funding-id', time_s=5.)
        published = dict(workflow_id='wf', root_key='root-key', root_metadata_sha256='a'*64, sequence=1,
            inspect=inspect, producer_pid=self.pid, store_limits=row['store_limits'],
            store_compression=row['compression'], execution_provenance=provenance, preparation_ids=ids)
        receipt = dict(schema=R.RESULT_SCHEMA, status=X.PRODUCER_STATUS[mode], pid=self.pid,
            profile_sha256=self.profile.sha256, errors=[], production_acceptance=False,
            stop_before_advance=mode == 'root-only', final_reserved_bytes=0, original_database_unchanged=True,
            same_process_cold_reopen=mode == 'root-only', independent_process_reopen=False,
            checkpoint=str(self.output/'checkpoint.sqlite'), checkpoint_sha256=self.checkpoint_sha,
            published_root=published, previous_endpoint=dict(inspect),
            migrated_base=dict(schema='atlas.migrated-workflow-base.v1', sequence=1, historical_head_key='old-head'),
            initial_workload=dict(state=dict(schema='atlas.migrated-initial-workload.v1'), duration_s=.5,
                                  gate='equals the authenticated historical head advance duration_s'),
            supervisor=dict(pid=777), source_proof=self.sources.verify())
        if mode == 'successor':
            # Owner decision 14 Oct 2026: no same-process successor cold reopen.
            receipt['same_process_cold_reopen_reason'] = R.SAME_PROCESS_REOPEN_DROPPED
            receipt['completed_endpoint'] = dict(workflow_id='wf', root_key='root-key',
                root_metadata=dict(key='root-key'), head_key='head-key', producer_pid=self.pid,
                store_limits=row['store_limits'], store_compression=row['compression'],
                collar_result_id='collar', native_result_id='native', exterior_state_id='exterior',
                source_audit_id='audit', joined_heat_id='heat', array_records=groups(),
                preparation_ids=dict(ids), execution_provenance=dict(provenance), sequence=2)
            receipt['continuation'] = dict(parent_head_key='root-key', parent_interval_id='interval-1',
                interval_id='interval-2', parent_interval_number=1, interval_number=2,
                parent_time_seconds=[hex(5), hex(1)], time_seconds=[hex(11), hex(2)],
                root_key='root-key', funding_id='funding-id')
            receipt['advanced_endpoint'] = dict(workflow_id='wf', head='head-key', intervals=2,
                                                funding_id='funding-id', time_s=5.5)
        return receipt

    def validate(self, receipt, *, mode='successor', guard=None, control=None, checkpoint=None, consumer=1):
        default_guard, default_control = guard_records(receipt.get('pid'))
        return X.validate_producer_receipt(receipt, profile=self.profile, receipt_sha256='c'*64,
            guard_receipt=default_guard if guard is None else guard,
            guard_control=default_control if control is None else control,
            checkpoint_sha_now=self.checkpoint_sha if checkpoint is None else checkpoint,
            consumer_pid=consumer, mode=mode)

    def write_producer(self, receipt, guard=None, control=None):
        default_guard, default_control = guard_records(receipt['pid'])
        raw = encoded(receipt)
        (self.output/'run.json').write_bytes(raw)
        (self.output/'run.guard.json').write_bytes(encoded(default_guard if guard is None else guard))
        (self.output/'run.guard-control.json').write_bytes(encoded(default_control if control is None else control))
        return R.file_hash(self.output/'run.json')


class ReceiptValidation(Fixture):
    def test_valid_successor_and_root_only_receipts(self):
        expected = self.validate(self.receipt())
        self.assertEqual(expected['continuation']['interval_number'], 2)
        self.assertEqual(expected['completed_endpoint']['head_key'], 'head-key')
        root = self.validate(self.receipt('root-only'), mode='root-only')
        self.assertNotIn('completed_endpoint', root)
        self.assertEqual(root['published_root']['root_key'], 'root-key')

    def refuse(self, change, message, *, mode='successor', **options):
        receipt = self.receipt(mode)
        change(receipt)
        with self.assertRaisesRegex(X.ReopenRefused, message):
            self.validate(receipt, mode=mode, **options)

    def test_receipt_mutations_refused(self):
        cases = (
            (lambda r: r.update(status='FAILED'), 'successful producer'),
            (lambda r: r.update(status=R.STOPPED_STATUS), 'successful producer'),
            (lambda r: r['errors'].append('x'), 'successful producer'),
            (lambda r: r.update(final_reserved_bytes=1), 'successful producer'),
            (lambda r: r.update(production_acceptance=True), 'successful producer'),
            (lambda r: r.update(profile_sha256='0'*64), 'successful producer'),
            (lambda r: r.update(stop_before_advance=True), 'successful producer'),
            (lambda r: r.update(original_database_unchanged=False), 'finalisation is incomplete'),
            (lambda r: r.update(independent_process_reopen=True), 'finalisation is incomplete'),
            (lambda r: r.update(checkpoint=str(self.folder/'elsewhere.sqlite')), 'checkpoint path or bytes'),
            (lambda r: r['published_root'].update(producer_pid=1), 'recorded by this producer'),
            (lambda r: r['published_root']['preparation_ids'].pop('map'), 'preparation identities'),
            (lambda r: r['published_root']['execution_provenance'].update(execution_mode='release'), 'strict'),
            (lambda r: r['published_root'].update(store_limits={}), 'store limits'),
            (lambda r: r['migrated_base'].update(sequence=2), 'migrated base'),
            (lambda r: r.pop('initial_workload'), 'initial workload'),
            (lambda r: r['completed_endpoint'].update(sequence=3), 'extend the published'),
            (lambda r: r['completed_endpoint']['preparation_ids'].update(owner='other'), 'extend the published'),
            (lambda r: r['completed_endpoint'].update(producer_pid=1), 'extend the published'),
            (lambda r: r['completed_endpoint']['array_records'].pop('native'), 'six complete'),
            (lambda r: r['continuation'].update(parent_head_key='other-head'), 'advance the migrated root'),
            (lambda r: r['continuation'].update(interval_number=3), 'exactly one interval'),
            (lambda r: r['continuation'].update(funding_id='new-funding'), 'unchanged funding'),
            (lambda r: r['advanced_endpoint'].update(funding_id='new-funding'), 'unchanged funding'),
            (lambda r: r['continuation'].update(interval_id='interval-1'), 'advance the migrated root'),
            (lambda r: r['continuation'].update(time_seconds=[hex(22), hex(4)]), 'reduced canonical'),
            (lambda r: r['continuation'].update(time_seconds=[hex(4), hex(1)]), 'exceed its exact parent'),
            (lambda r: r.pop('supervisor'), 'supervisor'),
        )
        for change, message in cases:
            with self.subTest(message=message):
                self.refuse(change, message)
        self.refuse(lambda r: r.update(completed_endpoint={}), 'cannot carry an advanced endpoint', mode='root-only')
        self.refuse(lambda r: r.update(previous_endpoint={}), 'cannot carry an advanced endpoint', mode='root-only')
        # Owner decision 14 Oct 2026: exactly the runner's dropped-reopen record.
        self.assertEqual(R.SAME_PROCESS_REOPEN_DROPPED, 'dropped by owner decision 14 Oct 2026; '
                         'the mandatory independent fresh-process reader performs the cold reopen')
        reopen_cases = (
            ('successor', lambda r: r.update(same_process_cold_reopen=True)),
            ('successor', lambda r: r.pop('same_process_cold_reopen_reason')),
            ('successor', lambda r: r.update(same_process_cold_reopen_reason='skipped')),
            ('successor', lambda r: r.update(same_process_cold_reopen=0)),
            ('root-only', lambda r: r.update(same_process_cold_reopen=False)),
            ('root-only', lambda r: r.update(same_process_cold_reopen_reason=R.SAME_PROCESS_REOPEN_DROPPED)))
        for index, (mode, change) in enumerate(reopen_cases):
            with self.subTest(reopen_case=index, mode=mode):
                self.refuse(change, 'finalisation is incomplete', mode=mode)

    def test_process_checkpoint_and_guard_mutations_refused(self):
        receipt = self.receipt()
        with self.assertRaisesRegex(X.ReopenRefused, 'separate producer and reader'):
            self.validate(receipt, consumer=self.pid)
        with self.assertRaisesRegex(X.ReopenRefused, 'checkpoint path or bytes'):
            self.validate(receipt, checkpoint='d'*64)
        for change, message in (
                (lambda g, c: g.update(status='HARD_STOPPED'), 'stop cleanly'),
                (lambda g, c: g.update(reason='rss_limit'), 'stop cleanly'),
                (lambda g, c: g.update(workload_exit_code=1), 'stop cleanly'),
                (lambda g, c: g.update(workload_exit_confirmed=False), 'stop cleanly'),
                (lambda g, c: g['cleanup']['remaining'].append(99), 'stop cleanly'),
                (lambda g, c: c.update(nonce='other'), 'close handshake'),
                (lambda g, c: c.update(close_requested=False), 'close handshake'),
                (lambda g, c: c['parent'].update(created_ticks=1), 'guardian parent'),
                (lambda g, c: g['parent'].update(pid=1), 'guardian parent'),
                (lambda g, c: g['guardian'].update(pid=1), 'recorded supervisor'),
                (lambda g, c: g['limits'].update(rss_bytes=13 << 30), '12 GiB / 1 GiB'),
                (lambda g, c: c['limits'].update(free_floor_bytes=1 << 29), '12 GiB / 1 GiB')):
            guard, control = guard_records(self.pid)
            change(guard, control)
            with self.subTest(message=message), self.assertRaisesRegex(X.ReopenRefused, message):
                self.validate(receipt, guard=guard, control=control)

    def test_producer_files_sidecars_and_source_proof(self):
        receipt = self.receipt()
        pin = self.write_producer(receipt)
        expected = X.producer_inputs(self.profile, sources=self.sources, receipt_sha256=pin, mode='successor',
                                     consumer_pid=os.getpid())
        self.assertEqual(expected['receipt_sha256'], pin)
        with self.assertRaisesRegex(R.RestartRefused, 'pinned configuration changed'):
            X.producer_inputs(self.profile, sources=self.sources, receipt_sha256='0'*64, mode='successor',
                              consumer_pid=os.getpid())
        for name, message in (('checkpoint.sqlite-wal', 'not closed'), ('run.guard-abort.json', 'aborted or cancelled'),
                              ('run.cancel', 'aborted or cancelled')):
            extra = self.output/name
            extra.write_bytes(b'')
            with self.subTest(name=name), self.assertRaisesRegex(X.ReopenRefused, message):
                X.producer_inputs(self.profile, sources=self.sources, receipt_sha256=pin, mode='successor',
                                  consumer_pid=os.getpid())
            extra.unlink()
        pin = self.write_producer(dict(receipt, source_proof=dict(receipt['source_proof'], native_source_digest='0'*64)))
        with self.assertRaisesRegex(X.ReopenRefused, 'source proof'):
            X.producer_inputs(self.profile, sources=self.sources, receipt_sha256=pin, mode='successor',
                              consumer_pid=os.getpid())
        self.checkpoint.write_bytes(b'changed')
        with self.assertRaisesRegex(X.ReopenRefused, 'checkpoint path or bytes'):
            X.producer_inputs(self.profile, sources=self.sources, receipt_sha256=self.write_producer(receipt),
                              mode='successor', consumer_pid=os.getpid())

    def test_reader_output_must_be_new_canonical_and_outside_producer(self):
        fresh = str(self.folder/'reader')
        self.assertEqual(X.reader_output(self.profile, self.sources, fresh, exists=False), Path(fresh))
        for value, message in ((str(self.output/'reader'), 'outside the producer'),
                               (str(self.output), 'outside the producer'),
                               (str(WORKSPACE.parent/'reader-outside'), 'inside the workspace'),
                               (fresh.lower(), 'canonical absolute'), ('reader', 'canonical absolute')):
            with self.subTest(value=value), self.assertRaisesRegex(R.RestartRefused if 'canonical' in message
                                                                  else X.ReopenRefused, message):
                X.reader_output(self.profile, self.sources, value, exists=False)
        Path(fresh).mkdir()
        with self.assertRaisesRegex(X.ReopenRefused, 'exclusive new reader output'):
            X.reader_output(self.profile, self.sources, fresh, exists=False)
        self.assertEqual(X.reader_output(self.profile, self.sources, fresh, exists=True), Path(fresh))


class Lineage(unittest.TestCase):
    def operands(self):
        base = dict(schema='atlas.migrated-workflow-base.v1', sequence=1, historical_head_key='old-head')
        root = dict(schema=W.WORKFLOW_SCHEMA, workflow_id='wf', key='root-key', kind='migrated-root', sequence=1,
            funding_id='funding-id', migration=deepcopy(base), historical_payload_key='old-head',
            differential_geometry=dict(interval_id='interval-1', start_time_s=[hex(0), hex(1)],
                                       end_time_s=[hex(5), hex(1)]),
            state=dict(fields=dict(time_s=5.)))
        head = dict(schema=W.WORKFLOW_SCHEMA, workflow_id='wf', key=W.workflow_key('successor', 'root-key'),
            kind='successor', sequence=2, parent_key='root-key', parent_digest=W.digest(root),
            funding_id='funding-id', differential_partition=dict(partition_id='partition-2'),
            differential_geometry=dict(interval_id='interval-2', start_time_s=[hex(5), hex(1)],
                                       end_time_s=[hex(11), hex(2)]),
            state=dict(fields=dict(time_s=5.5)))
        continuation = dict(parent_head_key='root-key', parent_interval_id='interval-1', interval_id='interval-2',
            parent_interval_number=1, interval_number=2, parent_time_seconds=[hex(5), hex(1)],
            time_seconds=[hex(11), hex(2)], root_key='root-key', funding_id='funding-id')
        observed = dict(interval_id='interval-2', partition_id='partition-2', fields_time_s=5.5,
                        native_time_s=5.5, exterior_time_s=5.5, funding_id='funding-id')
        return dict(root=root, head=head, continuation=continuation, base_record=base, observed=observed)

    def test_migrated_root_successor_lineage_passes(self):
        result = X.validate_migrated_lineage(**self.operands())
        self.assertTrue(result['migrated_root_is_parent'] and result['exact_endpoint_clocks_identical'])

    def test_lineage_mutations_refused(self):
        def changed(edit):
            operands = self.operands()
            edit(operands)
            return operands
        cases = (
            (lambda o: o['root'].update(kind='successor'), 'admitted base'),
            (lambda o: o['root'].update(kind='root', sequence=0), 'admitted base'),
            (lambda o: o['root']['migration'].update(sequence=2), 'admitted base'),
            (lambda o: o['root'].update(historical_payload_key='advanced-head'), 'admitted base'),
            (lambda o: o['head'].update(parent_key='other'), 'exactly once'),
            (lambda o: o['head'].update(parent_digest='0'*64), 'exactly once'),
            (lambda o: o['head'].update(sequence=3), 'exactly once'),
            (lambda o: o['head'].update(kind='migrated-root'), 'exactly once'),
            (lambda o: o['continuation'].update(parent_head_key='other'), 'continuation lineage'),
            (lambda o: o['continuation'].update(interval_number=3), 'continuation lineage'),
            (lambda o: o['observed'].update(interval_id='other'), 'interval identity'),
            (lambda o: o['head']['differential_geometry'].update(start_time_s=[hex(4), hex(1)]), 'interval clocks'),
            (lambda o: o['root']['differential_geometry'].update(end_time_s=[hex(4), hex(1)]), 'interval clocks'),
            (lambda o: o['observed'].update(native_time_s=5.25), 'state clocks'),
            (lambda o: o['root']['state']['fields'].update(time_s=4.), 'state clocks'),
            (lambda o: o['observed'].update(partition_id='other'), 'partition'),
            (lambda o: o['observed'].update(funding_id='other'), 'funding'),
            (lambda o: o['head'].pop('differential_partition'), 'header missing'),
            (lambda o: o['observed'].pop('funding_id'), 'complete lineage operands'),
        )
        for edit, message in cases:
            operands = changed(edit)
            # Keep the digest consistent unless the case is about the digest itself.
            if message != 'exactly once' and 'parent_digest' in operands['head']:
                operands['head']['parent_digest'] = W.digest(operands['root'])
            with self.subTest(message=message), self.assertRaisesRegex(X.ReopenRefused, message):
                X.validate_migrated_lineage(**operands)

    def test_six_group_canonical_records(self):
        records = groups()
        reordered = {k: list(reversed(v)) for k, v in records.items()}
        self.assertEqual(X.canonical_records(records), X.canonical_records(reordered))
        self.assertNotEqual(X.canonical_records(records), X.canonical_records(groups('1'*64)))
        duplicate = deepcopy(records)
        duplicate['native'].append(dict(duplicate['native'][0]))
        with self.assertRaisesRegex(X.ReopenRefused, 'duplicate'):
            X.canonical_records(duplicate)
        missing = deepcopy(records)
        missing.pop('spatial_audit')
        with self.assertRaisesRegex(X.ReopenRefused, 'six complete'):
            X.canonical_records(missing)
        malformed = deepcopy(records)
        malformed['collar'][0]['sha256'] = 'XYZ'
        with self.assertRaisesRegex(X.ReopenRefused, 'exact array name'):
            X.canonical_records(malformed)


class AuditBudget:
    """Records every reservation; nothing native."""
    def __init__(self):
        self.reserved_bytes, self.categories = 0, []

    def reserve(self, size, *, category):
        budget = self

        class Lease:
            def __enter__(self):
                budget.reserved_bytes += size
                budget.categories.append(category)
                return self

            def __exit__(self, *_):
                budget.reserved_bytes -= size
        return Lease()


class AuditStore:
    """Fake store holding ONE successor head whose manifest carries compact aliases.

    Every array read is recorded by name; the whole-head store.get is refused.
    Alias descriptors are far larger than max_array_bytes, as a real partition
    DAG and spatial mesh can be, so a whole-head read would also refuse.
    """
    CHUNK_BYTES = 16

    def __init__(self, audit, budget):
        import numpy as np
        self.budget, self.audit, self.read, self.manifests = budget, audit, [], 0
        self.limits = types.SimpleNamespace(max_manifest_bytes=4096, max_array_bytes=1 << 20)
        huge = dict(shape=[1 << 40], dtype='<f8', chunks=['alias-chunk'])
        self.arrays = {'partition-dag:cells': huge, 'spatial-mesh:faces': dict(huge, dtype='<i8'),
                       'collar:temperature': dict(shape=[3], dtype='<f8', chunks=['c'])}
        for name, value in audit.items():
            width = self.CHUNK_BYTES//value.dtype.itemsize
            self.arrays['spatial-audit:'+name] = dict(shape=list(value.shape), dtype=value.dtype.str,
                chunks=['k%d' % i for i in range(-(-value.size//width))])
        self.np = np

    @contextmanager
    def _workspace(self, size, budget, *, category):
        assert budget is self.budget
        with budget.reserve(size, category=category):
            yield

    @contextmanager
    def _read_scope(self, *, budget=None):
        yield

    def _manifest(self, key):
        self.manifests += 1
        return deepcopy(dict(arrays=self.arrays, metadata=dict(kind='successor'))) if key == 'head-key' else None

    def iter_chunks(self, key, name, *, budget=None):
        assert key == 'head-key' and budget is self.budget
        self.read.append(name)
        if not name.startswith('spatial-audit:'):
            raise AssertionError('compact alias or non-audit array read: '+name)
        flat = self.audit[name.removeprefix('spatial-audit:')].reshape(-1)
        width = self.CHUNK_BYTES//flat.dtype.itemsize
        for start in range(0, flat.size, width):
            chunk = flat[start:start+width].copy()
            chunk.flags.writeable = False
            yield start, chunk

    def get(self, *args, **kwargs):
        raise AssertionError('whole-head store.get used')


class AuditWorkflow:
    def __init__(self, store, budget, *, kind='successor', spatial=True):
        import numpy as np
        self._store, self._budget, self._spatial = store, budget, spatial
        self._head = dict(key='head-key', kind=kind)
        self.refreshes = 0
        self.state = types.SimpleNamespace(fields='fields', native_state='native',
                                           arrays=lambda: {'full': np.arange(3.)})
        self.exterior_state = types.SimpleNamespace(_snapshot='exterior')
        self.source_audit = 'audit'

    def _refresh(self):
        self.refreshes += 1

    def _is_spatial(self):
        return self._spatial

    @property
    def spatial_audit_arrays(self):
        raise AssertionError('native whole-head spatial_audit_arrays used')


class SpatialAuditRead(unittest.TestCase):
    """W4 defect 1: only the head's spatial-audit arrays are read, budget-charged."""
    def setUp(self):
        import numpy as np
        self.np = np
        self.audit = {'residual': np.array([1.5, -2., 3.25, 4., 5.], dtype='<f8'),
                      'counts': np.arange(6, dtype='<i4').reshape(2, 3),
                      'flag': np.array(7, dtype='<i8'), 'empty': np.zeros((0, 2), dtype='<f8')}

    @staticmethod
    def records(values):
        # probe r9 D.arrays: name, shape, dtype.str and C-order sha256.
        from hashlib import sha256
        return [dict(name=name, shape=list(value.shape), dtype=value.dtype.str,
                     sha256=sha256(value.tobytes(order='C')).hexdigest()) for name, value in values.items()]

    def test_alias_carrying_head_reads_only_spatial_audit_arrays(self):
        budget = AuditBudget()
        store = AuditStore(self.audit, budget)
        workflow = AuditWorkflow(store, budget)
        D = types.SimpleNamespace(snapshots=lambda value: [dict(name=str(value))], arrays=self.records)
        groups = X.endpoint_array_records(D, workflow)
        self.assertEqual(sorted(store.read), sorted('spatial-audit:'+name for name in self.audit))
        self.assertFalse([name for name in store.read if name.startswith(('partition-dag:', 'spatial-mesh:'))])
        self.assertEqual((store.manifests, workflow.refreshes), (1, 1))
        expected = sorted(self.records(self.audit), key=lambda row: row['name'])
        self.assertEqual(sorted(groups['spatial_audit'], key=lambda row: row['name']), expected)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertEqual(set(budget.categories), {'reopen-spatial-audit-manifest', 'reopen-spatial-audit-arrays',
                                                  'reopen-spatial-audit-array-read'})
        # The returned arrays hold the one reservation until the last of them dies.
        arrays = X.spatial_audit_arrays(workflow)
        self.assertEqual(set(arrays), set(self.audit))
        for name, value in self.audit.items():
            self.assertEqual((arrays[name].dtype.str, arrays[name].shape), (value.dtype.str, value.shape))
            self.assertTrue(self.np.array_equal(arrays[name], value))
            self.assertFalse(arrays[name].flags.writeable)
        self.assertGreater(budget.reserved_bytes, 0)
        del arrays, name, value
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_audit_read_refusals(self):
        budget = AuditBudget()
        cases = {'spatial successor head': AuditWorkflow(AuditStore(self.audit, budget), budget, kind='migrated-root'),
                 'spatial successor': AuditWorkflow(AuditStore(self.audit, budget), budget, spatial=False)}
        store = AuditStore(self.audit, budget)
        store.limits.max_array_bytes = 8
        cases['read allowance'] = AuditWorkflow(store, budget)
        store = AuditStore(self.audit, budget)
        store.arrays['spatial-audit:residual']['shape'] = [7]
        cases['incomplete'] = AuditWorkflow(store, budget)
        store = AuditStore({}, budget)
        cases['no saved spatial audit'] = AuditWorkflow(store, budget)
        for message, workflow in cases.items():
            with self.subTest(message), self.assertRaisesRegex(X.ReopenRefused, message):
                X.spatial_audit_arrays(workflow)
            self.assertFalse([n for n in workflow._store.read if not n.startswith('spatial-audit:')])
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


class CommandOnly(Fixture):
    def test_inspection_reads_no_store_creates_no_output_and_binds_pins(self):
        pin = self.write_producer(self.receipt())
        reader = str(self.folder/'reader')
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = X.main(['--profile', str(self.profile_path), '--profile-sha256', self.profile.sha256,
                           '--producer-receipt-sha256', pin, '--output-directory', reader])
        self.assertEqual(code, 0)
        printed = json.loads(stdout.getvalue())
        self.assertEqual(printed['status'], 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION')
        argv = printed['command']
        self.assertEqual(argv[1:4], ['-B', str(self.sources.path(self.profile.record()['modules']
                                                               ['private_heat_continuation_guard_r3'])), '--launch'])
        self.assertEqual(argv[argv.index('--output')+1], str(Path(reader)/'reopen.json'))
        for flag, value in (('--profile-sha256', self.profile.sha256), ('--producer-receipt-sha256', pin),
                            ('--output-directory', reader), ('--mode', 'successor'), ('--store-route', 'readonly')):
            self.assertEqual(argv[argv.index(flag)+1], value)
        self.assertIn('--workload', argv)
        self.assertEqual(Path(argv[argv.index('--workload')-1]), Path(X.__file__).resolve())
        self.assertFalse(Path(reader).exists())
        self.assertNotIn('atlas_tectonics', sys.modules)
        self.assertEqual(sorted(p.name for p in self.output.iterdir()),
                         ['checkpoint.sqlite', 'run.guard-control.json', 'run.guard.json', 'run.json'])
        with self.assertRaisesRegex(X.ReopenRefused, 'successful producer'):
            X.command(self.profile, sys.executable, producer_receipt_sha256=pin, output_directory=reader,
                      mode='root-only')
        for options in (['--finalise'], ['--reopen-receipt-sha256', '0'*64]):
            with self.assertRaisesRegex(X.ReopenRefused, 'reopen-receipt-sha256'):
                X.main(['--profile', str(self.profile_path), '--profile-sha256', self.profile.sha256,
                        '--producer-receipt-sha256', pin, '--output-directory', reader, *options])

    def test_reader_never_writes_and_uses_the_migrated_lineage(self):
        tree = ast.parse(Path(X.__file__).read_text(encoding='utf8'))
        text = Path(X.__file__).read_text(encoding='utf8')
        for forbidden in ('_validate_continuation', 'publish_migrated_root', 'publish_and_reopen',
                          '.put(', '.advance(', 'advance_spatial', 'probe_heat_original_continue'):
            self.assertNotIn(forbidden, text)
        core = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'reopen_prepared_restart')
        calls = {}
        for node in ast.walk(core):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', None)
                calls.setdefault(name, []).append(node.lineno)
        order = ('_guard_boundary', '_copy_bound_file', 'admit_historical_endpoint', '_reader_store',
                 'materialise', '_check_runtime_binding', 'initial_workload_state', 'open_migrated',
                 '_root_identity', '_history')
        self.assertEqual([min(calls[n]) for n in order], sorted(min(calls[n]) for n in order))
        materialise = next(n for n in ast.walk(core) if isinstance(n, ast.Call) and
                           getattr(n.func, 'attr', None) == 'materialise')
        self.assertEqual(ast.unparse(next(k.value for k in materialise.keywords if k.arg == 'working_store')), 'store')
        self.assertEqual(X.READER_SCHEMA, 'atlas.prepared-restart-reopen-result.v1')
        self.assertTrue(all(status.endswith('PENDING_FINALISE') for status in X.WORKLOAD_STATUS.values()))
        self.assertNotIn('SECOND_INTERVAL', X.FINAL_STATUS['root-only'])


class Finalise(Fixture):
    def reader_records(self, pin, *, mode='successor'):
        reader = self.folder/'reader'
        reader.mkdir()
        (reader/X.CHECKPOINT).write_bytes(self.checkpoint.read_bytes())
        pid = 5151
        reopen = dict(schema=X.READER_SCHEMA, status=X.WORKLOAD_STATUS[mode], pid=pid,
            profile_sha256=self.profile.sha256, producer_receipt_sha256=pin, mode=mode, store_route='readonly',
            errors=[], production_acceptance=False, independent_process_reopen=True, final_reserved_bytes=0,
            remaining_children=[], original_database_unchanged=True, checkpoint=str(reader/X.CHECKPOINT),
            independent_checks=dict.fromkeys(X.INDEPENDENT_CHECKS[mode], True), supervisor=dict(pid=888),
            source_proof=self.sources.verify())
        guard, control = guard_records(pid, guardian=888)
        return reader, reopen, guard, control

    def write_reader(self, reader, reopen, guard, control):
        (reader/'reopen.json').write_bytes(encoded(reopen))
        (reader/'reopen.guard.json').write_bytes(encoded(guard))
        (reader/'reopen.guard-control.json').write_bytes(encoded(control))
        return R.file_hash(reader/'reopen.json')

    def finalise(self, pin, reader, reopen_pin, mode='successor'):
        with redirect_stdout(io.StringIO()):
            code = X.finalise(self.profile, producer_receipt_sha256=pin, output_directory=str(reader), mode=mode,
                              store_route='readonly', reopen_receipt_sha256=reopen_pin)
        return code, json.loads((reader/'reopen-final.json').read_bytes())

    def test_finalise_passes_only_complete_clean_reader(self):
        pin = self.write_producer(self.receipt())
        reader, reopen, guard, control = self.reader_records(pin)
        code, final = self.finalise(pin, reader, self.write_reader(reader, reopen, guard, control))
        self.assertEqual((code, final['status'], final['errors']), (0, X.FINAL_STATUS['successor'], []))
        self.assertIs(final['production_acceptance'], False)
        with self.assertRaisesRegex(X.ReopenRefused, 'final record already exists'):
            self.finalise(pin, reader, '0'*64)

    def test_finalise_records_failure_for_each_deviation(self):
        pin = self.write_producer(self.receipt())
        cases = (
            (lambda r, g, c: r.update(status='FAILED'), 'successful independent reader'),
            (lambda r, g, c: r.update(final_reserved_bytes=8), 'successful independent reader'),
            (lambda r, g, c: r.update(remaining_children=[1]), 'successful independent reader'),
            (lambda r, g, c: r.update(store_route='copy-token'), 'successful independent reader'),
            (lambda r, g, c: r.update(pid=self.pid), 'separate from the producer'),
            (lambda r, g, c: r['independent_checks'].update(history_preserved=False), 'every independent'),
            (lambda r, g, c: r['independent_checks'].pop('migrated_lineage'), 'every independent'),
            (lambda r, g, c: g.update(status='PARENT_EXITED'), 'stop cleanly'),
            (lambda r, g, c: c.update(close_requested=False), 'close handshake'),
            (lambda r, g, c: r.update(source_proof={}), 'source proof'),
        )
        for index, (change, message) in enumerate(cases):
            with self.subTest(message=message):
                reader, reopen, guard, control = self.reader_records(pin)
                change(reopen, guard, control)
                code, final = self.finalise(pin, reader, self.write_reader(reader, reopen, guard, control))
                self.assertEqual((code, final['status']), (1, 'FAILED'))
                self.assertRegex(final['errors'][0]['message'], message)
                reader.rename(self.folder/('failed-%02d' % index))
        reader, reopen, guard, control = self.reader_records(pin)
        reopen_pin = self.write_reader(reader, reopen, guard, control)
        (reader/X.CHECKPOINT).write_bytes(b'changed copy')
        code, final = self.finalise(pin, reader, reopen_pin)
        self.assertEqual((code, final['status']), (1, 'FAILED'))
        self.assertRegex(final['errors'][0]['message'], 'copy changed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
