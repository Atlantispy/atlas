"""Compact reader controls: synthetic evidence only, never interval acceptance."""
from copy import deepcopy
import gc
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

import reopen_prepared_restart as X
import test_reopen_prepared_restart as OLD


def identities(successor=True):
    names = {'state', 'partition', 'mesh'}
    if successor:
        names.update(('exchange', 'graph', 'transport', 'heat', 'certification', 'differential'))
    return {name: dict(sha256='a'*64, nbytes=17) for name in names}


def retained_record(pid):
    result = dict(limit_bytes=256 << 20, scope_id='scope', process_epoch='prepared-restart-'+str(pid),
        **dict.fromkeys(X.RETAINED_SCALARS, 0), **{name: {} for name in X.RETAINED_MAPPINGS})
    result['peak_retained_bytes'] = 1024
    return result


class CompactReader(OLD.Fixture):
    def catalog(self):
        directory = self.output/'compact'
        directory.mkdir()
        members = []
        for index in range(2):
            member = directory/('interval-%04d.sqlite' % index)
            member.write_bytes(b'synthetic immutable interval '+str(index).encode())
            members.append(dict(interval=index, filename=member.name, file_sha256=X.RUN.file_hash(member)))
        catalog = directory/X.COMPACT_CATALOG
        catalog.write_bytes(OLD.encoded(dict(schema='atlas.interval-catalog.v1', workflow_id='f'*64,
                                            generation=2, entries=members)))
        return catalog

    def compact_receipt(self, mode='successor'):
        row = self.profile.record()
        row['storage_format'] = 'interval-catalog-v1'
        helper = row['preparation']['path']
        row['modules'].update(dict.fromkeys(X.RUN.COMPACT_MODULES, helper))
        self.profile_path.write_bytes(OLD.encoded(row))
        self.profile = X.RUN.RestartProfile.read(self.profile_path, X.RUN.file_hash(self.profile_path))
        self.sources = X.RUN.RestartSources(self.profile)
        receipt = self.receipt(mode)
        storage = X.storage_inventory(self.catalog())
        receipt.update(compact_storage=storage, checkpoint=storage['catalog'],
                       checkpoint_sha256=storage['catalog_sha256'], record_identities=identities(mode == 'successor'),
                       compact_retained_before_close=retained_record(self.pid),
                       compact_retained_after_close=retained_record(self.pid))
        receipt['published_root'].update(store_limits=X.RUN.COMPACT_STORE_LIMITS,
                                         store_compression=X.RUN.COMPACT_COMPRESSION)
        if mode == 'successor':
            receipt['completed_endpoint'].update(store_limits=X.RUN.COMPACT_STORE_LIMITS,
                                                 store_compression=X.RUN.COMPACT_COMPRESSION)
        return receipt

    def test_inventory_copy_is_complete_and_charged(self):
        source = self.catalog()
        budget = OLD.AuditBudget()
        inventory = X.storage_inventory(source, budget=budget)
        self.assertEqual([r['filename'] for r in inventory['files']],
                         ['interval-0000.sqlite', 'interval-0001.sqlite'])
        copied = X.copy_storage(inventory, self.folder/'copied', budget=budget, check=lambda: None)
        self.assertEqual(copied, dict(inventory, catalog=str(self.folder/'copied'/X.COMPACT_CATALOG)))
        self.assertEqual(X.verify_storage(inventory), inventory)
        self.assertEqual(budget.reserved_bytes, 0)
        self.assertIn('reopen-storage-inventory', budget.categories)
        self.assertIn('restart-checkpoint-copy', budget.categories)
        with self.assertRaisesRegex(X.ReopenRefused, 'fresh separate'):
            X.copy_storage(inventory, self.folder/'copied', budget=budget, check=lambda: None)

    def test_changed_member_and_open_member_refuse(self):
        path = self.catalog()
        saved = X.storage_inventory(path)
        member = path.parent/saved['files'][0]['filename']
        original = member.read_bytes()
        member.write_bytes(b'changed member')
        with self.assertRaisesRegex(X.ReopenRefused, 'file differs'):
            X.verify_storage(saved)
        member.write_bytes(original)
        sidecar = Path(str(member)+'-wal')
        sidecar.write_bytes(b'open database')
        with self.assertRaisesRegex(X.ReopenRefused, 'not closed'):
            X.verify_storage(saved)

    def test_path_duplicate_and_incomplete_catalog_refuse(self):
        path = self.catalog()
        original = json.loads(path.read_bytes())
        for mutate, message in (
            (lambda row: row['entries'][0].update(filename='../outside.sqlite'), 'safe ordered'),
            (lambda row: row['entries'][1].update(**{k: row['entries'][0][k]
                for k in ('filename', 'file_sha256')}), 'unique'),
            (lambda row: row.update(generation=3), 'complete interval catalog'),
            (lambda row: row['entries'][1].update(interval=3), 'safe ordered')):
            row = deepcopy(original)
            mutate(row)
            path.write_bytes(OLD.encoded(row))
            with self.subTest(message=message), self.assertRaisesRegex(X.ReopenRefused, message):
                X.storage_inventory(path)

    def test_cancellation_releases_inventory_reservation(self):
        path, budget = self.catalog(), OLD.AuditBudget()
        def cancelled():
            raise InterruptedError('cancelled')
        with self.assertRaisesRegex(InterruptedError, 'cancelled'):
            X.storage_inventory(path, budget=budget, check=cancelled)
        self.assertEqual(budget.reserved_bytes, 0)

    def test_compact_producer_requires_complete_logical_identities(self):
        receipt = self.compact_receipt()
        expected = self.validate(receipt, checkpoint=receipt['checkpoint_sha256'])
        self.assertEqual(expected['record_identities'], identities())
        self.assertEqual(expected['compact_storage'], receipt['compact_storage'])
        receipt['record_identities'].pop('heat')
        with self.assertRaisesRegex(X.ReopenRefused, 'complete compact endpoint'):
            self.validate(receipt, checkpoint=receipt['checkpoint_sha256'])

    def test_compact_command_refuses_copy_token(self):
        receipt = self.compact_receipt()
        pin = self.write_producer(receipt)
        with self.assertRaisesRegex(X.ReopenRefused, 'readonly interval catalog'):
            X.command(self.profile, X.sys.executable, producer_receipt_sha256=pin,
                      output_directory=str(self.folder/'reader'), store_route='copy-token')

    def test_record_identity_closed_shape_and_exact_integer_length(self):
        self.assertEqual(X.canonical_record_identities(identities(False), successor=False), identities(False))
        for value in ({'sha256': 'a'*64, 'nbytes': True}, {'sha256': 'bad', 'nbytes': 2},
                      {'sha256': 'a'*64, 'nbytes': 0}, {'sha256': 'a'*64, 'nbytes': 2, 'extra': 1}):
            row = identities()
            row['heat'] = value
            with self.subTest(value=value), self.assertRaisesRegex(X.ReopenRefused, 'exact compact record'):
                X.canonical_record_identities(row, successor=True)

    def test_final_receipt_requires_closed_retained_scope(self):
        receipt = self.compact_receipt()
        producer = self.validate(receipt, checkpoint=receipt['checkpoint_sha256'])
        output = self.folder/'reader'
        pid = 5151
        retained = retained_record(pid)
        reopen = dict(schema=X.READER_SCHEMA, status=X.WORKLOAD_STATUS['successor'], errors=[],
            pid=pid, profile_sha256=self.profile.sha256, producer_receipt_sha256=producer['receipt_sha256'],
            mode='successor', store_route='readonly', production_acceptance=False,
            independent_process_reopen=True, final_reserved_bytes=0, remaining_children=[],
            original_database_unchanged=True, checkpoint=str(output/X.COMPACT_DIRECTORY/X.COMPACT_CATALOG),
            independent_checks=dict.fromkeys(X.INDEPENDENT_CHECKS['successor'] | X.COMPACT_CHECKS, True),
            compact_storage=dict(producer['compact_storage'], catalog=str(output/X.COMPACT_DIRECTORY/X.COMPACT_CATALOG)),
            record_identities=identities(), retained_scope=dict(before_close=dict(retained), after_close=dict(retained)),
            supervisor=dict(pid=888))
        guard, control = OLD.guard_records(pid, guardian=888)
        args = dict(guard_receipt=guard, guard_control=control, profile=self.profile, producer=producer,
                    mode='successor', store_route='readonly', output=output)
        X.validate_reopen_receipt(reopen, **args)
        for mutate, message in (
            (lambda row: row['retained_scope']['after_close'].update(retained_bytes=1), 'scope release'),
            (lambda row: row['retained_scope']['after_close'].update(scope_id='other'), 'scope release'),
            (lambda row: row['retained_scope']['before_close'].update(peak_retained_bytes=(256 << 20)+1), 'scope release'),
            (lambda row: row['retained_scope']['before_close'].pop('pinned_bytes'), 'complete shared'),
            (lambda row: row['retained_scope']['before_close'].update(non_cache_owned_bytes=1), 'does not reconcile'),
            (lambda row: row['record_identities']['mesh'].update(nbytes=18), 'logical records differ'),
            (lambda row: row['independent_checks'].pop('compact_storage_authenticated'), 'every independent')):
            changed = deepcopy(reopen)
            mutate(changed)
            with self.subTest(message=message), self.assertRaisesRegex(X.ReopenRefused, message):
                X.validate_reopen_receipt(changed, **args)
        gc.collect()


class FreshProcessCopy(unittest.TestCase):
    def test_endpoint_identity_helper_streams_real_compact_records(self):
        """Actual codecs; a stub workflow supplies their already-issued handles."""
        here = Path(__file__).resolve().parent
        temporary_root = here.parents[3]/'_t'
        temporary_root.mkdir(exist_ok=True)
        script = r'''
import gc, json, sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0] = sys.argv[2:5]
from atlas_tectonics.resources import WorkBudget
from content_cache import create_retained_scope
from compact_restart_store import CompactRestartStore
from compact_store import CompactMeshStoreV3
from record_tables import canonical
from record_views import RecordRef, CompactRecord
import partition_native_patch as PN
import spatial_records_patch as SR
from test_mesh_v3 import fixture
import reopen_prepared_restart as X
budget = WorkBudget(768 << 20)
scope = create_retained_scope(budget, process_epoch='step8-record-identities')
producer = {'role': 'synthetic reader codec fixture'}
with CompactRestartStore.create_migration(Path(sys.argv[1])/'catalog.json', scope=scope,
        workflow_id='1'*64, producer_identity='2'*64, runtime_identity='3'*64) as store:
    old_mesh, _, support, partition, _ = fixture(scope, store.resolver, count=1)
    adapter = CompactMeshStoreV3(store.resolver, scope=scope, support_source=support)
    ref = adapter.publish(old_mesh, producer=sha256(canonical(producer)).hexdigest())
    mesh = adapter.open(ref, expected_geometry_id=old_mesh.geometry_id)
    names = ('state', 'exchange', 'graph', 'transport', 'heat', 'certification', 'differential')
    rows = {name: {'schema': 'synthetic.'+name, 'literal': ['0x'+('f'*8192), -17, False],
                   'shared': [[1, 2, 3]]*12} for name in names}
    refs = SR.publish_records(store, rows, budget=budget, source_producer=producer)
    head = dict(kind='successor', exterior_state=dict(record_blobs={'state': refs['state']},
        compact_mesh={'source_producer': producer}), exterior_advance=dict(record_blobs={
        name: refs[name] for name in ('exchange', 'graph', 'transport', 'heat')}),
        differential_certification={'record_blob': refs['certification']},
        differential_geometry={'record_blob': refs['differential']})
    workflow = SimpleNamespace(_store=store, _budget=budget, _head=head, differential_partition=object(),
        exterior_state=SimpleNamespace(indexed_record=lambda: SimpleNamespace(value={'thermal_mesh': mesh})))
    expected = {name: {'sha256': sha256(canonical(value)).hexdigest(), 'nbytes': len(canonical(value))}
                for name, value in rows.items()}
    with partition.record.export(max_logical_bytes=4 << 20, max_owned_bytes=32 << 20) as held:
        raw = canonical(held.value)
        expected['partition'] = {'sha256': sha256(raw).hexdigest(), 'nbytes': len(raw)}
    expected['mesh'] = {'sha256': old_mesh.identity().sha256, 'nbytes': old_mesh.identity().canonical_bytes}
    with patch.object(PN, 'compact_view', return_value=partition), \
            patch.object(RecordRef, 'export', side_effect=AssertionError('whole record export')), \
            patch.object(CompactRecord, 'export', side_effect=AssertionError('whole compact record export')):
        found = X.endpoint_record_identities(workflow)
    assert found == expected
    del workflow, held, raw
    mesh.close()
    support.close()
    partition.close()
    del old_mesh, adapter, mesh, support, partition
gc.collect()
scope.close()
assert budget.reserved_bytes == 0
print(json.dumps({'status': 'PASS', 'records': len(found), 'final_reserved_bytes': 0}))
'''
        with tempfile.TemporaryDirectory(prefix='step8-records-', dir=temporary_root) as folder:
            process = subprocess.run([sys.executable, '-B', '-c', script, folder,
                str(here/'compact-geometry-r1'), str(here.parent/'runtime-integration-r1/runtime-src'), str(here)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stdout+process.stderr)
            self.assertEqual(json.loads(process.stdout), dict(status='PASS', records=9, final_reserved_bytes=0))

    def test_authenticated_copy_reopens_in_separate_process(self):
        """Real sealed storage, synthetic fields; no native science is accepted."""
        here = Path(__file__).resolve().parent
        temporary_root = here.parents[3]/'_t'
        temporary_root.mkdir(exist_ok=True)
        script = r'''
import json, os, sys
from hashlib import sha256
from pathlib import Path
sys.path[:0] = sys.argv[3:6]
import numpy as np
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, Compression
import compact_restart_store as C
from content_cache import create_retained_scope
import reopen_prepared_restart as X
mode, directory = sys.argv[1], Path(sys.argv[2])
budget = WorkBudget(768 << 20)
scope = create_retained_scope(budget, process_epoch='prepared-restart-'+str(os.getpid()))
key = sha256(b'synthetic reader head').hexdigest()
if mode == 'produce':
    source = directory/'source'
    source.mkdir()
    with C.CompactRestartStore.create_migration(source/X.COMPACT_CATALOG,
            workflow_id=sha256(b'workflow').hexdigest(), scope=scope,
            producer_identity=sha256(b'producer').hexdigest(),
            runtime_identity=sha256(b'runtime').hexdigest()) as store:
        values = np.arange(18000, dtype='<i8')
        store.put(key, {'values': values}, {'sequence': 1})
        store.seal_and_promote(key)
    inventory = X.storage_inventory(source/X.COMPACT_CATALOG, budget=budget)
    expected = dict(inventory=inventory, producer_pid=os.getpid(),
                    field_sha256=sha256(values.tobytes()).hexdigest())
    (directory/'expected.json').write_text(json.dumps(expected), encoding='utf8')
else:
    expected = json.loads((directory/'expected.json').read_bytes())
    assert expected['producer_pid'] != os.getpid()
    copied = X.copy_storage(expected['inventory'], directory/'reader', budget=budget, check=lambda: None)
    with X._reader_store(None, ArrayStore, Path(copied['catalog']), route='readonly',
            pin=copied['catalog_sha256'], limits=C.LIMITS, compression=Compression(),
            budget=budget, check=lambda: None, compact=C, scope=scope) as store:
        token = store.change_token()
        assert store.readonly and store.metadata(key) == {'sequence': 1}
        digest, length = sha256(), 0
        for offset, values in store.iter_chunks(key, 'values', budget=budget):
            assert offset*8 == length
            digest.update(memoryview(values).cast('B'))
            length += values.nbytes
        del values
        assert length == 18000*8 and digest.hexdigest() == expected['field_sha256']
        assert list(store.snapshot_keys()) == [key] and token == store.change_token()
    X.verify_storage(expected['inventory'], budget=budget)
    X.verify_storage(copied, budget=budget)
before = X.retained_accounting(scope)
X.validate_retained_accounting(before, pid=os.getpid())
scope.close()
after = X.retained_accounting(scope)
X.validate_retained_accounting(after, pid=os.getpid())
assert budget.reserved_bytes == after['retained_bytes'] == 0
print(json.dumps(dict(status='PASS', pid=os.getpid(), before_close=before, after_close=after)))
'''
        with tempfile.TemporaryDirectory(prefix='step8-reader-', dir=temporary_root) as folder:
            directory = Path(folder)
            try:
                pids = []
                for mode in ('produce', 'read'):
                    process = subprocess.run([sys.executable, '-B', '-c', script, mode, str(directory),
                        str(here/'compact-geometry-r1'), str(here.parent/'runtime-integration-r1/runtime-src'),
                        str(here)], capture_output=True, text=True, timeout=60)
                    self.assertEqual(process.returncode, 0, process.stdout+process.stderr)
                    result = json.loads(process.stdout)
                    self.assertEqual(result['status'], 'PASS')
                    self.assertEqual(result['after_close']['retained_bytes'], 0)
                    pids.append(result['pid'])
                self.assertNotEqual(*pids)
            finally:
                for file in directory.rglob('*'):
                    if file.is_file():
                        os.chmod(file, stat.S_IREAD | stat.S_IWRITE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
