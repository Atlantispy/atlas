"""Route (1) runner controls: profile, source pins, Step 9(a) records, run B chain, WP17 wiring.

Synthetic stores and stand-in owners only; nothing here is run acceptance.
"""
import ast
import gc
import json
import os
import stat
import sys
import tempfile
import unittest
from concurrent.futures import CancelledError
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
COMPACT = HERE/'compact-geometry-r1'
RUNTIME = HERE.parent/'runtime-integration-r1'/'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import numpy as np
import run_fresh_interval as F
import run_prepared_restart as RUN
import start_gate as SG
from atlas_tectonics.resources import WorkBudget
from compact_restart_store import CompactRestartStore
from content_cache import create_retained_scope
from interval_store_set import IntervalStoreSet

WP17_PACKAGE = (HERE.parents[2]/'claude-review-steps1-7-20261015'/'fixes'/'wp17'/'files'/
                'integration_endpoint_checkpoints.py')


def key(text):
    return sha256(text.encode()).hexdigest()


def encoded(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':')).encode()


def loaded_here():
    found = set()
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name and Path(name).suffix == '.py' and Path(name).resolve().parent == HERE:
            found.add(Path(name).resolve())
    return found


def writable_tree(root):
    for path in Path(root).rglob('*'):
        if path.is_file():
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


class ProfileAndSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rf-', dir=HERE)
        self.folder = Path(self.temp.name)
        self.native = self.folder/'src'
        (self.native/'atlas_tectonics').mkdir(parents=True)
        (self.native/'atlas_tectonics/__init__.py').write_text('# synthetic fence fixture\n', encoding='utf8')
        self.helper = self.folder/'fixture_fresh_helper.py'
        self.helper.write_text('VALUE = 1\n', encoding='utf8')
        self.driver = self.folder/'fixture_fresh_driver.py'
        self.driver.write_text('def create_root(*args, **kwargs):\n    raise AssertionError\n', encoding='utf8')
        self.manifest = self.folder/'manifest.json'
        self.attempt = self.folder/'attempt'
        self.attempt.mkdir()
        self.extra, self.store_flag = [], {F.QUERY_STORE_FLAG: 'columnar'}
        self.write_manifest()
        self.row: dict = {
            'schema': F.PROFILE_SCHEMA, 'workspace': str(HERE),
            'source_manifest': {'path': self.relative(self.manifest), 'sha256': RUN.file_hash(self.manifest)},
            'native_root': self.relative(self.native), 'import_roots': [self.relative(self.folder), '.'],
            'modules': {name: self.relative(self.helper) for name in F.FRESH_MODULES},
            'advance_driver': {'module': F.DRIVER, 'path': self.relative(self.driver),
                               'sha256': RUN.file_hash(self.driver)},
            'output_directory': str(self.attempt), 'store_directory': str(self.folder/'store'),
            'completed_query_directory': self.relative(self.folder/'queries'),
            'completed_query_limits': {'max_entries': 2000000, 'max_store_bytes': 8 << 30}}
        self.path = self.folder/'profile.json'
        self.profile = self.write_profile()

    def tearDown(self):
        self.temp.cleanup()

    def relative(self, path):
        return Path(path).relative_to(HERE).as_posix()

    def write_manifest(self):
        paths = {Path(F.__file__).resolve(), Path(RUN.__file__).resolve(), Path(__file__).resolve(), self.helper,
                 self.driver, self.native/'atlas_tectonics/__init__.py', *loaded_here(), *self.extra}
        native = {'atlas_tectonics/__init__.py': RUN.file_hash(self.native/'atlas_tectonics/__init__.py')}
        self.manifest.write_bytes(encoded({'files': {self.relative(p): RUN.file_hash(p) for p in paths},
                                           'source_hashes': native, 'data_only': {}, **self.store_flag}))

    def write_profile(self):
        self.row['source_manifest'] = {'path': self.relative(self.manifest), 'sha256': RUN.file_hash(self.manifest)}
        self.path.write_bytes(encoded(self.row))
        return F.FreshProfile.read(self.path, RUN.file_hash(self.path))

    def refused(self, message, change):
        change(self.row)
        with self.assertRaisesRegex(RUN.RestartRefused, message):
            self.write_profile()

    def test_closed_profile_round_trips_and_pins(self):
        self.assertEqual(self.profile.record(), self.row)
        self.path.write_bytes(encoded({**self.row, 'output_directory': str(self.folder)}))
        with self.assertRaisesRegex(RUN.RestartRefused, 'pinned configuration changed'):
            self.profile.verify()

    def test_profile_refusals(self):
        cases = (
            ('closed reviewed', lambda row: row.update(storage_format='interval-catalog-v1')),
            ('helper bindings', lambda row: row['modules'].pop('bounded_preseal')),
            ('helper bindings', lambda row: row['modules'].update(fresh_interval_driver='x.py')),
            ('exactly fresh_interval_driver', lambda row: row['advance_driver'].update(module='other_driver')),
            ('exactly fresh_interval_driver', lambda row: row['advance_driver'].update(extra=1)),
            ('outlive both run outputs', lambda row: row.update(store_directory=str(self.attempt/'run-root'/'s'))),
            ('outlive both run outputs', lambda row: row.update(output_directory=str(self.folder/'store'/'a'))),
            ('canonical absolute', lambda row: row.update(store_directory='relative-store')),
            ('contained completed-query', lambda row: row.update(completed_query_directory='../queries')),
            ('contained completed-query', lambda row: row.update(completed_query_directory=str(self.folder))),
            ('positive completed-query', lambda row: row['completed_query_limits'].update(max_entries=0)),
            ('positive completed-query', lambda row: row['completed_query_limits'].update(max_store_bytes=1.5)),
        )
        for message, change in cases:
            with self.subTest(message=message):
                saved = json.loads(encoded(self.row))
                self.refused(message, change)
                self.row = saved

    def test_sources_verify_pins_the_runner_its_orchestration_and_native_inventory(self):
        sources = F.FreshSources(self.profile)
        proof = sources.verify()
        native = {'atlas_tectonics/__init__.py': RUN.file_hash(self.native/'atlas_tectonics/__init__.py')}
        self.assertEqual(proof['native_source_digest'], sha256(F.canonical(native)).hexdigest())
        self.helper.write_text('VALUE = 2\n', encoding='utf8')
        with self.assertRaisesRegex(F.FreshRefused, 'participating source changed'):
            sources.verify()
        self.helper.write_text('VALUE = 1\n', encoding='utf8')
        (self.native/'atlas_tectonics/extra.py').write_text('', encoding='utf8')
        with self.assertRaisesRegex(F.FreshRefused, 'native package inventory changed'):
            sources.verify()

    def test_composition_declares_its_completed_query_store(self):
        self.assertEqual(F.FreshSources(self.profile).query_store(), 'columnar')
        for flag in ({F.QUERY_STORE_FLAG: 'files'}, {}, {F.QUERY_STORE_FLAG: 'sqlite'}):
            with self.subTest(flag=flag):
                self.store_flag = flag
                self.write_manifest()
                profile = self.write_profile()
                if flag.get(F.QUERY_STORE_FLAG) == 'files':
                    self.assertEqual(F.FreshSources(profile).query_store(), 'files')
                else:
                    with self.assertRaisesRegex(F.FreshRefused, 'declare its completed-query store'):
                        F.FreshSources(profile)

    def test_driver_and_helpers_must_be_in_the_closure(self):
        self.row['advance_driver']['sha256'] = key('another driver')
        profile = self.write_profile()
        with self.assertRaisesRegex(F.FreshRefused, 'driver absent'):
            F.FreshSources(profile).verify()
        self.row['advance_driver']['sha256'] = RUN.file_hash(self.driver)
        self.row['modules']['bounded_preseal'] = self.relative(self.folder/'profile.json')
        profile = self.write_profile()
        with self.assertRaisesRegex(F.FreshRefused, 'helper missing'):
            F.FreshSources(profile).verify()

    def test_command_is_mode_specific_and_creates_nothing(self):
        for mode in F.MODES:
            argv = F.command(self.profile, sys.executable, mode=mode)
            self.assertEqual(argv[argv.index('--mode')+1], mode)
            self.assertIn('--workload', argv)
            self.assertEqual(argv[argv.index('--output')+1], str(self.attempt/('run-'+mode)/'run.json'))
            self.assertNotIn('--dev-timing', argv)
            self.assertFalse((self.attempt/('run-'+mode)).exists())
        self.assertIn('--dev-timing', F.command(self.profile, sys.executable, mode='root', dev_timing=True))
        self.assertEqual(F.command(self.profile, sys.executable, mode='interval', stop_before_advance=True)[-1],
                         '--stop-before-advance')
        with self.assertRaisesRegex(F.FreshRefused, 'run B only'):
            F.command(self.profile, sys.executable, mode='root', stop_before_advance=True)
        (self.attempt/'run-root').mkdir()
        with self.assertRaisesRegex(F.FreshRefused, 'exclusive new run output'):
            F.command(self.profile, sys.executable, mode='root')
        with self.assertRaisesRegex(F.FreshRefused, 'explicit route'):
            F.command(self.profile, sys.executable, mode='successor')

    def test_command_carries_an_explicit_measurement_seed_for_run_b_only(self):
        seed = {'receipt_sha256': key('receipt'), 'store_sha256': key('store')}
        argv = F.command(self.profile, sys.executable, mode='interval', stop_before_advance=True, seed=seed)
        self.assertEqual(argv[-5:], ['--seed-receipt-sha256', seed['receipt_sha256'], '--seed-store-sha256',
                                     seed['store_sha256'], '--stop-before-advance'])
        self.assertFalse([item for item in F.command(self.profile, sys.executable, mode='interval')
                          if item.startswith('--seed')])
        for mode, value, message in (('root', seed, 'run B only'),
                                     ('interval', {**seed, 'extra': key('x')}, 'names exactly'),
                                     ('interval', {'receipt_sha256': key('receipt')}, 'names exactly'),
                                     ('interval', {**seed, 'store_sha256': key('store').upper()}, 'lowercase SHA-256')):
            with self.subTest(mode=mode, seed=value), self.assertRaisesRegex(RUN.RestartRefused, message):
                F.command(self.profile, sys.executable, mode=mode, seed=value)
        self.assertEqual(F._seed(dict(reversed(list(seed.items()))), 'interval'), seed)
        self.assertIsNone(F._seed(None, 'root'))
        self.assertFalse((self.attempt/'run-interval').exists())

    def test_main_takes_both_seed_pins_or_neither(self):
        base = ['--profile', str(self.path), '--profile-sha256', self.profile.sha256, '--mode', 'interval',
                '--workload']
        for extra in (['--seed-store-sha256', key('store')], ['--seed-receipt-sha256', key('receipt')]):
            with self.subTest(extra=extra[0]), self.assertRaisesRegex(F.FreshRefused, 'needs both'):
                F.main(base+extra)


class StoreRecordTests(unittest.TestCase):
    """Step 9(a) records on real compact stores: record, seal, nothing promoted."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rs-', dir=HERE)
        self.root = Path(self.temp.name)
        self.budget = WorkBudget(512 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='fresh-runner-tests')
        self.stores = []
        self.identities = {'producer_identity': key('producer'), 'runtime_identity': key('runtime')}

    def tearDown(self):
        for store in self.stores:
            store.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        writable_tree(self.root)
        self.temp.cleanup()

    def new_store(self, name):
        (self.root/name).mkdir()
        catalog = self.root/name/F.CATALOG
        store = CompactRestartStore.create_migration(catalog, workflow_id=key('workflow'), scope=self.scope,
                                                     **self.identities)
        self.stores.append(store)
        head = key('root')
        store.put(head, {'a': np.arange(4096, dtype='<i8')}, {'kind': 'root', 'sequence': 0})
        return catalog, store, head

    def seal(self, store, head, directory, record, **change):
        return F.seal_with_records(store, head, store_directory=directory, interval=0,
            identities={**self.identities, **change}, record=record, save=lambda: record.setdefault('saves', 0),
            extra={'workflow_id': key('workflow'), 'root': {'root_key': head}, 'head': 'forged', 'schema': 'forged'})

    def test_runner_record_precedes_the_seal_and_nothing_is_promoted(self):
        catalog, store, head = self.new_store('a')
        candidate, record = store.candidate, {}
        sealed = self.seal(store, head, self.root/'a', record)
        runner = F.read_record(F.runner_record_path(self.root/'a', 0), schema=F.RUNNER_RECORD_SCHEMA,
                               expected_sha256=record['runner_record']['sha256'])
        self.assertEqual(runner['head'], sealed['entry']['head'])
        self.assertEqual((runner['producer_identity'], runner['runtime_identity']),
                         (self.identities['producer_identity'], self.identities['runtime_identity']))
        self.assertEqual(runner['root'], {'root_key': head})
        stored = F.read_record(F.sealed_record_path(self.root/'a', 0), schema=F.SEALED_SCHEMA,
                               expected_sha256=record['sealed_awaiting_reader']['sha256'])
        self.assertEqual(stored, sealed)
        self.assertEqual(stored['runner_record_sha256'], record['runner_record']['sha256'])
        self.assertIsNone(stored['expected_catalog_digest'])
        self.assertEqual(candidate._state, 'SEALED')
        self.assertFalse(catalog.exists())
        self.assertTrue(store.readonly)
        self.assertFalse(os.access(catalog.parent/sealed['entry']['filename'], os.W_OK))

    def test_existing_record_or_foreign_identity_leaves_the_candidate_unsealed(self):
        _, store, head = self.new_store('b')
        candidate = store.candidate
        with self.assertRaisesRegex(F.FreshRefused, 'differ from the candidate'):
            self.seal(store, head, self.root/'b', {}, runtime_identity=key('another runtime'))
        self.assertFalse(F.runner_record_path(self.root/'b', 0).exists())
        F.runner_record_path(self.root/'b', 0).write_bytes(b'{}')
        with self.assertRaises(FileExistsError):
            self.seal(store, head, self.root/'b', {})
        self.assertEqual(candidate._state, 'WRITING')
        self.assertIs(store.candidate, candidate)
        self.assertFalse(F.sealed_record_path(self.root/'b', 0).exists())

    def promoted_root(self, name):
        """A real accepted catalog holding one root interval and the three run A records."""
        catalog, store, head = self.new_store(name)
        store.seal_and_promote(head)
        accepted = CompactRestartStore.open_catalog(catalog, scope=self.scope)
        self.stores.append(accepted)
        entry = accepted.store_set.head.to_wire()
        records = self.root/name/'records'
        records.mkdir()
        runner = {'schema': F.RUNNER_RECORD_SCHEMA, 'interval': 0, 'head': entry['head'],
                  'workflow_id': key('workflow'), 'root': {'root_key': head}, 'producer_pid': 1, **self.identities}
        return accepted, records, runner, entry

    def write_chain(self, records, runner, entry, *, status=F.READER_PASS['root'], verdict_entry=None):
        runner_sha = F.write_durable(F.runner_record_path(records, 0), runner)
        F.write_durable(F.sealed_record_path(records, 0), {'schema': F.SEALED_SCHEMA, 'interval': 0, 'entry': entry,
                        'expected_catalog_digest': None, 'runner_record_sha256': runner_sha})
        F.write_durable(F.verdict_path(records, 0), {'schema': F.VERDICT_SCHEMA, 'status': status, 'interval': 0,
                        'entry': entry if verdict_entry is None else verdict_entry,
                        'runner_record_sha256': runner_sha, 'view_digest': key('view')})

    def test_run_b_requires_the_whole_adopted_root_chain(self):
        accepted, records, runner, entry = self.promoted_root('c')
        self.write_chain(records, runner, entry)
        self.assertEqual(F.require_promoted_root(accepted, records), runner)
        forged = {**entry, 'logical_seal': key('another seal')}
        cases = (
            ('no independent reader PASS', {'status': 'FAILED'}),
            ('no independent reader PASS', {'verdict_entry': forged}),
            ('exactly run A adopted root', {'runner': {**runner, 'workflow_id': key('another workflow')}}),
            ('exactly run A adopted root', {'runner': {**runner, 'head': {**entry['head'], 'merkle_root': key('m')}}}),
            ('exactly run A adopted root', {'entry': forged}),
        )
        for index, (message, change) in enumerate(cases):
            with self.subTest(message=message, index=index):
                directory = records/str(index)
                directory.mkdir()
                self.write_chain(directory, change.pop('runner', runner), change.pop('entry', entry), **change)
                with self.assertRaisesRegex(F.FreshRefused, message):
                    F.require_promoted_root(accepted, directory)

    def test_unbound_or_noncanonical_records_refuse(self):
        accepted, records, runner, entry = self.promoted_root('d')
        self.write_chain(records, runner, entry)
        sealed = json.loads(F.sealed_record_path(records, 0).read_bytes())
        os.chmod(F.sealed_record_path(records, 0), stat.S_IREAD | stat.S_IWRITE)
        F.sealed_record_path(records, 0).write_bytes(F.canonical({**sealed, 'runner_record_sha256': key('x')}))
        with self.assertRaisesRegex(F.FreshRefused, 'does not bind its runner record'):
            F.require_promoted_root(accepted, records)
        F.sealed_record_path(records, 0).write_bytes(json.dumps(sealed, indent=1).encode())
        with self.assertRaisesRegex(F.FreshRefused, 'canonical'):
            F.require_promoted_root(accepted, records)
        F.verdict_path(records, 0).unlink()
        F.sealed_record_path(records, 0).write_bytes(F.canonical(sealed))
        with self.assertRaises(FileNotFoundError):
            F.require_promoted_root(accepted, records)

    @unittest.skipUnless(hasattr(IntervalStoreSet, 'adopt_and_promote'), 'Step 9(a) storage primitives not merged yet')
    def test_sealed_records_adopt_and_satisfy_run_b(self):
        catalog, store, head = self.new_store('e')
        record = {}
        sealed = self.seal(store, head, self.root/'e', record)
        runner = F.read_record(F.runner_record_path(self.root/'e', 0), schema=F.RUNNER_RECORD_SCHEMA)
        from compact_contracts import SegmentRef
        entry = sealed['entry']
        identity = {'expected_sha256': entry['file_sha256'], 'expected_logical_seal': entry['logical_seal'],
                    'head': SegmentRef.from_wire(runner['head']), 'producer_identity': runner['producer_identity'],
                    'runtime_identity': runner['runtime_identity']}
        view = IntervalStoreSet.open_pending(catalog, entry['filename'], scope=self.scope, workflow_id=key('workflow'),
                                             expected_catalog_digest=None, **identity)
        try:
            digest = view.catalog_digest
        finally:
            view.close()
        store.close()
        stores = IntervalStoreSet.create_migration(catalog, workflow_id=key('workflow'), scope=self.scope)
        try:
            stores.adopt_and_promote(entry['filename'], expected_catalog_digest=sealed['expected_catalog_digest'],
                                     reader_view_digest=digest, **identity)
        finally:
            stores.close()
        F.write_durable(F.verdict_path(self.root/'e', 0), {'schema': F.VERDICT_SCHEMA,
            'status': F.READER_PASS['root'], 'interval': 0, 'entry': entry,
            'runner_record_sha256': sealed['runner_record_sha256'], 'view_digest': digest})
        accepted = CompactRestartStore.open_catalog(catalog, scope=self.scope)
        self.stores.append(accepted)
        self.assertEqual(F.require_promoted_root(accepted, self.root/'e'), runner)


class FakeOwner:
    """Stand-in batched owner: held entries become ``written`` only on flush()."""
    def __init__(self, directory, *, context, budget, cancel=None, max_store_bytes=1, max_entries=1,
                 storage='files', batch_entries=1, batch_seconds=0):
        self.arguments = {'directory': directory, 'context': context, 'budget': budget, 'cancel': cancel,
                          'max_store_bytes': max_store_bytes, 'max_entries': max_entries, 'storage': storage,
                          'batch_entries': batch_entries, 'batch_seconds': batch_seconds}
        self.hits = self.misses = self.written = self.incomplete = 0
        self.held, self.events, self.flush_error = 0, [], None
        self.storage = storage

    def __enter__(self):
        self.events.append('enter')
        return self

    def __exit__(self, *_):
        self.events.append('exit')
        return False

    @property
    def unflushed(self):
        return self.held

    def flush(self):
        self.events.append('flush')
        if self.flush_error is not None:
            raise self.flush_error
        self.written, self.held = self.written+self.held, 0
        return self.written


class SerialOwner:
    """Stand-in for an owner that predates the storage choice: file store, no flush()."""
    def __init__(self, directory, *, context, budget, cancel=None, max_store_bytes=1, max_entries=1):
        self.hits = self.misses = self.written = self.incomplete = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class CompletedQueryTests(unittest.TestCase):
    def queries(self, record, events, *, owner_type: type = FakeOwner, declared='columnar'):
        save = lambda: events.append('save')
        arguments = F.query_store_arguments(owner_type, declared)
        return F.completed_queries(owner_type, Path('queries'), declared=declared, arguments=arguments,
            execution='execution', budget='budget', cancel='cancel',
            limits={'max_store_bytes': 7, 'max_entries': 5}, record=record, save=save)

    def test_flush_precedes_the_recorded_counts(self):
        record, events = {}, []
        with self.queries(record, events) as owner:
            owner.written, owner.held = 5, 3
        self.assertEqual(owner.arguments, {'directory': Path('queries'), 'context': 'execution', 'budget': 'budget',
            'cancel': 'cancel', 'max_store_bytes': 7, 'max_entries': 5, **F.QUERY_STORES['columnar']})
        self.assertEqual(owner.events, ['enter', 'flush', 'exit'])
        self.assertEqual(events, ['save'])
        self.assertEqual((record['completed_queries']['written'], record['completed_queries']['unflushed']), (8, 0))
        self.assertEqual(record['completed_queries']['flush'], 'flushed before recording')
        self.assertEqual((record['completed_queries']['store'], record['completed_queries']['arguments']),
                         ('columnar', F.QUERY_STORES['columnar']))

    def test_file_store_is_explicit_and_flushed_or_serial(self):
        record, events = {}, []
        with self.queries(record, events, declared='files') as owner:
            owner.written, owner.held = 2, 0
        self.assertEqual(owner.arguments['storage'], 'files')
        self.assertEqual(owner.arguments['batch_entries'], 1)
        self.assertEqual(owner.events, ['enter', 'flush', 'exit'])
        self.assertEqual((record['completed_queries']['store'], record['completed_queries']['flush']),
                         ('files', 'flushed before recording'))
        record, events = {}, []
        with self.queries(record, events, owner_type=SerialOwner, declared='files'):
            pass
        self.assertEqual((record['completed_queries']['arguments'], record['completed_queries']['flush'],
                          record['completed_queries']['unflushed']), ({}, 'serial store holds none', 0))
        self.assertEqual(events, ['save'])

    def test_owner_must_match_the_declared_store(self):
        class Columnar(FakeOwner):
            def __init__(self, *args, storage='files', **kwargs):
                super().__init__(*args, storage='columnar', **kwargs)
        with self.assertRaisesRegex(F.FreshRefused, 'differs from the declared store'), \
                self.queries({}, [], owner_type=Columnar, declared='files'):
            pass

    def test_flush_failure_never_masks_the_original_failure(self):
        record, events = {}, []
        with self.assertRaisesRegex(ValueError, 'advance failed') as caught, self.queries(record, events) as owner:
            owner.held, owner.flush_error = 3, CancelledError('guard abort')
            raise ValueError('advance failed')
        self.assertIn('Completed-query flush also failed', ' '.join(getattr(caught.exception, '__notes__', ())))
        self.assertEqual((record['completed_queries']['written'], record['completed_queries']['unflushed']), (0, 3))
        self.assertEqual(events, ['save'])

    def test_flush_failure_on_success_is_raised_and_still_recorded(self):
        record, events = {}, []
        with self.assertRaisesRegex(CancelledError, 'late abort'), self.queries(record, events) as owner:
            owner.held, owner.flush_error = 2, CancelledError('late abort')
        self.assertEqual(record['completed_queries']['unflushed'], 2)
        self.assertEqual(events, ['save'])

    def test_declared_store_selects_arguments_and_never_falls_back(self):
        self.assertEqual(F.query_store_arguments(FakeOwner, 'columnar'), F.QUERY_STORES['columnar'])
        self.assertEqual(F.query_store_arguments(FakeOwner, 'files'), {'storage': 'files'})
        self.assertEqual(F.query_store_arguments(SerialOwner, 'files'), {})

        class Unbatched:
            def __init__(self, directory, *, context, budget, storage='files'):
                pass

            def flush(self):
                pass

        class Unflushable:
            def __init__(self, directory, *, storage='files', batch_entries=1, batch_seconds=0):
                pass
        for owner_type in (Unbatched, Unflushable, SerialOwner):
            with self.subTest(owner=owner_type.__name__), \
                    self.assertRaisesRegex(F.FreshRefused, 'declares the WP17 columnar store'):
                F.query_store_arguments(owner_type, 'columnar')
        with self.assertRaisesRegex(F.FreshRefused, 'declare its completed-query store'):
            F.query_store_arguments(FakeOwner, None)

    def test_delivered_wp17_package_carries_the_wired_api(self):
        if not WP17_PACKAGE.is_file():
            self.skipTest('WP17 package moved; check the merged EndpointCheckpoints instead')
        tree = ast.parse(WP17_PACKAGE.read_text(encoding='utf8'))
        owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'EndpointCheckpoints')
        members = {n.name: n for n in owner.body if isinstance(n, ast.FunctionDef)}
        arguments = {a.arg for a in members['__init__'].args.kwonlyargs}
        self.assertLessEqual(set(F.QUERY_STORES['columnar']), arguments)
        self.assertIn('flush', members)
        self.assertIn('unflushed', members)


class FlowOrderTests(unittest.TestCase):
    """The run B protocol order inside the open workflow, and run A's record-before-seal."""

    def nested(self, name, *, within='run_fresh_interval'):
        tree = ast.parse(Path(F.__file__).read_text(encoding='utf8'))
        runner = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == within)
        return next(n for n in ast.walk(runner) if isinstance(n, ast.FunctionDef) and n.name == name)

    def call_lines(self, function):
        named = lambda n: n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', None)
        found = {}
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                found.setdefault(named(node), []).append(node.lineno)
        return {name: sorted(lines) for name, lines in found.items()}

    def test_successor_checks_then_preseal_then_record_and_seal(self):
        lines = self.call_lines(self.nested('finish', within='_advance'))
        self.assertLess(lines['check_imported'][0], lines['_successor_checks'][0])
        self.assertLess(lines['_successor_checks'][0], lines['bounded_preseal'][0])
        # Two seals: the review seal (inside seal_for_review, used only on a refusal) and the ordinary one.
        self.assertEqual(len(lines['seal_with_records']), 2)
        self.assertLess(lines['bounded_preseal'][0], lines['seal_with_records'][-1])
        self.assertLess(lines['preseal_or_review'][0], lines['seal_with_records'][-1])
        lines = self.call_lines(self.nested('finish_root'))
        self.assertLess(lines['storage_point'][0], lines['seal_with_records'][0])

    def test_the_publication_record_is_kept_before_the_preseal(self):
        """R2's token, R3's heat-checkpoint decision and the end mesh's supports (G-R3-1 (b'))."""
        finish = self.nested('finish', within='_advance')
        assigned = [node for node in ast.walk(finish) if isinstance(node, ast.Assign) and
                    any(isinstance(t, ast.Subscript) and ast.unparse(t) == "record['publication']" for t in node.targets)]
        self.assertEqual(len(assigned), 1)
        keys = {key.value for key in assigned[0].value.keys}
        self.assertEqual(keys, {'token_adopted', 'r3_heat_checkpoint', 'end_mesh_supports'})
        self.assertLess(assigned[0].lineno, self.call_lines(finish)['bounded_preseal'][0])
        self.assertIn('private_heat_original_joined_r8', F.FRESH_MODULES)
        self.assertIn('publish_mesh_patch', F.FRESH_MODULES)
        self.assertNotIn('private_heat_original_joined_r7', F.FRESH_MODULES)

    def test_first_raised_follows_the_chain_and_survives_cycles(self):
        try:
            try:
                raise KeyError('first')
            except KeyError as error:
                raise ValueError('second') from error
        except ValueError as error:
            self.assertIsInstance(F.first_raised(error), KeyError)
        a, b = ValueError('a'), ValueError('b')
        a.__context__, b.__context__ = b, a
        self.assertIn(F.first_raised(a), (a, b))

    def test_statuses_never_claim_an_interval_result(self):
        self.assertEqual(F.final_status([], 'root'), 'SEALED_ROOT_AWAITING_READER')
        self.assertEqual(F.final_status([], 'interval'), 'SEALED_INTERVAL_AWAITING_READER')
        self.assertEqual(F.final_status([{'type': 'X'}], 'interval'), 'FAILED')
        self.assertEqual(F.final_status([{'type': 'PresealSealedForReview'}], 'interval',
                                        {'review_only': {'state': F.REVIEW_STATUS}}), F.REVIEW_STATUS)
        self.assertEqual(F.final_status([], 'interval', {'stop_before_advance': True}), F.STOPPED_STATUS)
        self.assertEqual(F.final_status([{'type': 'X'}], 'interval', {'stop_before_advance': True}), 'FAILED')
        self.assertNotIn('PASS', ' '.join((*F.SEALED_STATUS.values(), F.REVIEW_STATUS, F.STOPPED_STATUS)))


class PresealReviewTests(unittest.TestCase):
    """Piece 3: a pre-seal refusal or checker defect seals for review; abort and memory do not."""

    def run_rule(self, preseal, *, check=lambda: None):
        sealed = []
        try:
            value = F.preseal_or_review(preseal, seal_for_review=sealed.append, check=check)
        except BaseException as error:  # noqa: BLE001 - the helper returns whatever the rule raises
            return error, sealed
        return value, sealed

    def test_evidence_passes_through_and_nothing_is_sealed_for_review(self):
        value, sealed = self.run_rule(lambda: {'record_identities': {}})
        self.assertEqual((value, sealed), ({'record_identities': {}}, []))

    def test_refusal_or_checker_defect_is_sealed_then_raised_with_its_first_cause(self):
        class PresealRefused(ValueError):
            pass

        def refused():
            raise PresealRefused('candidate chunk id/content binding differs')

        def defect():
            return {}['record_identities']
        for preseal, kind in ((refused, 'PresealRefused'), (defect, 'KeyError')):
            with self.subTest(kind=kind):
                error, sealed = self.run_rule(preseal)
                self.assertIsInstance(error, F.PresealSealedForReview)
                self.assertEqual([cause['type'] for cause in sealed], [kind])
                self.assertEqual(type(F.first_raised(error)).__name__, kind)

    def test_abort_memory_and_cancellation_propagate_unsealed(self):
        from concurrent.futures import CancelledError

        class GuardAborted(Exception):
            pass

        def raising(error):
            def preseal():
                raise error
            return preseal

        def aborting():
            raise GuardAborted('free memory floor')
        for preseal, check, expected in ((raising(MemoryError()), lambda: None, MemoryError),
                                         (raising(CancelledError()), lambda: None, CancelledError),
                                         (raising(ValueError('refused')), aborting, GuardAborted)):
            with self.subTest(expected=expected.__name__):
                error, sealed = self.run_rule(preseal, check=check)
                self.assertIsInstance(error, expected)
                self.assertEqual(sealed, [])

    def test_a_failing_seal_stays_fatal(self):
        def failing(_cause):
            raise OSError('seal failed')
        with self.assertRaisesRegex(OSError, 'seal failed'):
            F.preseal_or_review(lambda: (_ for _ in ()).throw(ValueError('refused')), seal_for_review=failing,
                                check=lambda: None)


class MeasurementSeedTests(unittest.TestCase):
    """Item 7: run B's seeded measurement store. Every refusal precedes the copy and the admission."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ms-', dir=HERE)
        self.addCleanup(temp.cleanup)
        self.base, self.count, self.checks = Path(temp.name), 0, []
        self.binding = {'profile_sha256': key('profile'), 'source_proof': {'native_source_digest': key('native')},
                        'advance_driver_sha256': key('driver'), 'helper_sha256': {'helper': key('helper')},
                        'interpreter_seed': {'PYTHONHASHSEED': '0', 'hash_randomization': 0}}

    def chain(self, *, receipt=None, stored=None, verdict=None, adopted=None):
        """Run A's verdict, adoption, receipt and closed store (two copy blocks) in a new folder."""
        self.count += 1
        folder = self.base/str(self.count)
        c = SimpleNamespace(store_directory=folder/'store', root_output=folder/'run-root',
                            artifacts=folder/'run-interval', data=bytes(range(256))*4100)
        for directory in (c.store_directory, c.root_output, c.artifacts):
            directory.mkdir(parents=True)
        (c.root_output/F.MEASUREMENT_STORE).write_bytes(c.data)
        c.pin = sha256(c.data).hexdigest()
        c.root_runner = {'schema': F.RUNNER_RECORD_SCHEMA, 'interval': 0, 'head': {'key': key('head')},
                         'workflow_id': key('workflow'), 'root': {'root_key': key('root')}, 'producer_pid': 41}
        root_sha = sha256(F.canonical(c.root_runner)).hexdigest()
        store = {'filename': F.MEASUREMENT_STORE, 'bytes': len(c.data), 'sha256': c.pin, 'composition': self.binding,
                 'statistics': {'snapshots': 7, 'operations': {'payload_reads': 0}}, 'initial_component_queries': 7}
        store.update(stored or {})
        run = {'schema': F.RESULT_SCHEMA, 'mode': 'root', 'status': F.SEALED_STATUS['root'], 'errors': [],
               'profile_sha256': key('profile'), 'pid': 41, 'workflow_id': key('workflow'),
               'initial_measurement_store': store}
        run.update(receipt or {})
        raw = json.dumps(run, indent=1).encode()
        (c.root_output/'run.json').write_bytes(raw)
        c.receipt_sha256 = sha256(raw).hexdigest()
        entry = {'interval': 0, 'filename': 'interval-0000.sqlite', 'logical_seal': key('seal')}
        c.verdict = {'schema': F.VERDICT_SCHEMA, 'status': F.READER_PASS['root'], 'interval': 0, 'entry': entry,
                     'runner_record_sha256': root_sha, 'producer_receipt_sha256': c.receipt_sha256,
                     'view_digest': key('view')}
        c.verdict.update(verdict or {})
        c.verdict_sha256 = F.write_durable(F.verdict_path(c.store_directory, 0), c.verdict)
        c.adopted = {'schema': F.ADOPTED_SCHEMA, 'status': F.ADOPTED_STATUS, 'interval': 0, 'entry': entry,
                     'catalog_digest': key('catalog'), 'verdict_sha256': c.verdict_sha256,
                     'runner_record_sha256': root_sha, 'adopter_pid': 51}
        c.adopted.update(adopted or {})
        c.adopted_sha256 = F.write_durable(c.store_directory/F.record_name('adopted', 0), c.adopted)
        c.seed = {'receipt_sha256': c.receipt_sha256, 'store_sha256': c.pin}
        return c

    def seed(self, c, **change):
        arguments = {'seed': c.seed, 'profile_sha256': key('profile'), 'root_runner': c.root_runner,
                     'store_directory': c.store_directory, 'root_output': c.root_output, 'artifacts': c.artifacts,
                     'binding': self.binding, **change}
        return F.seed_initial_measurements(arguments.pop('seed'), check=lambda: self.checks.append(1), **arguments)

    def refused(self, c, message, error=RUN.RestartRefused, **change):
        """Refused with ``message``; the source store unchanged and nothing written in the target folder."""
        with self.assertRaisesRegex(error, message):
            self.seed(c, **change)
        source = c.root_output/F.MEASUREMENT_STORE
        self.assertEqual(source.read_bytes() if source.exists() else None, c.data if source.exists() else None)
        self.assertEqual(list(c.artifacts.iterdir()), [])

    def test_a_clean_chain_copies_the_exact_bytes_and_records_the_chain(self):
        c = self.chain()
        reused = self.seed(c)
        target = c.artifacts/F.MEASUREMENT_STORE
        self.assertEqual((target.read_bytes(), (c.root_output/F.MEASUREMENT_STORE).read_bytes()), (c.data, c.data))
        self.assertEqual([path.name for path in c.artifacts.iterdir()], [F.MEASUREMENT_STORE])
        self.assertGreaterEqual(len(self.checks), 2)
        names = ('schema', 'status', 'pinned_sha256', 'bytes', 'verdict_sha256', 'adopted_sha256', 'composition_equal',
                 'seed_snapshots', 'seed_initial_component_queries')
        self.assertEqual({name: reused[name] for name in names},
                         {'schema': F.SEED_SCHEMA, 'status': 'COPIED_BEFORE_ADMISSION', 'pinned_sha256': c.pin,
                          'bytes': len(c.data), 'verdict_sha256': c.verdict_sha256, 'adopted_sha256': c.adopted_sha256,
                          'composition_equal': True, 'seed_snapshots': 7, 'seed_initial_component_queries': 7})
        self.assertEqual(reused['receipt'], {'path': str(c.root_output/'run.json'), 'sha256': c.receipt_sha256})
        self.assertEqual((reused['source'], reused['target']), (str(c.root_output/F.MEASUREMENT_STORE), str(target)))
        self.assertGreaterEqual(reused['copy_seconds'], 0)
        self.assertEqual(set(reused), {*names, 'receipt', 'source', 'target', 'copy_seconds'})

    def test_the_seed_names_exactly_two_lowercase_pins(self):
        c = self.chain()
        for seed in ({**c.seed, 'extra': key('x')}, {'receipt_sha256': c.receipt_sha256}, None, [c.seed]):
            with self.subTest(seed=seed):
                self.refused(c, 'names exactly its receipt and store SHA-256', seed=seed)
        for name in sorted(F.SEED_FIELDS):
            with self.subTest(upper=name):
                self.refused(c, 'exact lowercase SHA-256', seed={**c.seed, name: c.seed[name].upper()})
        self.refused(c, 'not the run A receipt its reader passed', seed={**c.seed, 'receipt_sha256': key('other')})
        self.refused(c, 'does not name exactly the pinned measurement store',
                     seed={**c.seed, 'store_sha256': key('other')})

    def test_the_reader_verdict_and_the_adoption_must_bind_run_a(self):
        for change in ({'status': 'FAILED'}, {'interval': 1}, {'runner_record_sha256': key('other')},
                       {'producer_receipt_sha256': key('other')}):
            with self.subTest(verdict=change):
                self.refused(self.chain(verdict=change), 'not the run A receipt its reader passed')
        c = self.chain()
        self.refused(c, 'not the run A receipt its reader passed', root_runner={**c.root_runner, 'producer_pid': 42})
        for change in ({'status': 'ADOPTED'}, {'interval': 1}, {'entry': {'interval': 0}},
                       {'verdict_sha256': key('other')}, {'runner_record_sha256': key('other')}):
            with self.subTest(adopted=change):
                self.refused(self.chain(adopted=change), 'not adopted after exactly that reader PASS')
        c = self.chain()
        (c.store_directory/F.record_name('adopted', 0)).unlink()
        self.refused(c, '', error=(OSError, RUN.RestartRefused))
        c = self.chain()
        (c.store_directory/F.record_name('adopted', 0)).write_bytes(json.dumps(c.adopted, indent=1).encode())
        self.refused(c, 'canonical')

    def test_the_receipt_must_be_run_a_clean_sealed_root_of_this_profile(self):
        for change in ({'schema': 'other'}, {'mode': 'interval'}, {'status': 'FAILED'}, {'errors': [{'type': 'X'}]},
                       {'profile_sha256': key('other')}, {'pid': 42}, {'workflow_id': key('other')}):
            with self.subTest(receipt=change):
                self.refused(self.chain(receipt=change), 'not run A clean sealed root of this profile')
        c = self.chain()
        self.refused(c, 'not run A clean sealed root of this profile', profile_sha256=key('another profile'))
        with open(c.root_output/'run.json', 'ab') as stream:
            stream.write(b' ')
        self.refused(c, 'pinned configuration changed')

    def test_the_receipt_must_name_exactly_the_pinned_store_and_its_composition(self):
        for change in ({'filename': 'other.sqlite'}, {'sha256': key('other')}, {'statistics': None},
                       {'statistics': {'snapshots': 7.0}}, {'statistics': {}}):
            with self.subTest(stored=change):
                self.refused(self.chain(stored=change), 'does not name exactly the pinned measurement store')
        self.refused(self.chain(receipt={'initial_measurement_store': None}),
                     'does not name exactly the pinned measurement store')
        self.refused(self.chain(stored={'composition': None}), 'does not record its measurement composition')

    def test_the_composition_must_match_field_by_field(self):
        for name in sorted(self.binding):
            with self.subTest(theirs=name):
                self.refused(self.chain(stored={'composition': {**self.binding, name: 'other'}}),
                             'composition differs from this run: '+name+'$')
            with self.subTest(ours=name):
                self.refused(self.chain(), 'composition differs from this run: '+name+'$',
                             binding={**self.binding, name: 'other'})
            with self.subTest(missing=name):
                theirs = {k: value for k, value in self.binding.items() if k != name}
                self.refused(self.chain(stored={'composition': theirs}), 'composition differs from this run: '+name+'$')
        self.refused(self.chain(stored={'composition': {**self.binding, 'extra': 1}}),
                     'composition differs from this run: extra$')

    def test_the_store_files_must_be_closed_and_the_target_new(self):
        for suffix in F.MEASUREMENT_SIDECARS:
            with self.subTest(source_sidecar=suffix):
                c = self.chain()
                (c.root_output/(F.MEASUREMENT_STORE+suffix)).write_bytes(b'')
                self.refused(c, 'the seed store has a journal or WAL')
        for name in (F.MEASUREMENT_STORE, F.MEASUREMENT_STORE+'-journal'):
            with self.subTest(existing_target=name):
                c = self.chain()
                (c.artifacts/name).write_bytes(b'keep')
                with self.assertRaisesRegex(F.FreshRefused, 'the seed target already exists'):
                    self.seed(c)
                self.assertEqual([(path.name, path.read_bytes()) for path in c.artifacts.iterdir()], [(name, b'keep')])
        c = self.chain()
        (c.root_output/F.MEASUREMENT_STORE).unlink()
        self.refused(c, '', error=(OSError, RUN.RestartRefused))
        c = self.chain()
        (c.root_output/F.MEASUREMENT_STORE).write_bytes(c.data[:-1]+b'x')
        with self.assertRaisesRegex(F.FreshRefused, 'differs from its pinned SHA-256'):
            self.seed(c)
        self.assertEqual(list(c.artifacts.iterdir()), [])

    def test_a_store_that_changes_during_or_after_the_copy_refuses(self):
        c = self.chain()
        (c.root_output/F.MEASUREMENT_STORE).write_bytes(c.data[:-1]+b'x')
        with mock.patch.object(RUN, 'file_hash', return_value=c.pin), \
                self.assertRaisesRegex(F.FreshRefused, 'changed while it was copied'):
            self.seed(c)
        c = self.chain()
        with mock.patch.object(RUN, 'file_hash', side_effect=[c.pin, c.pin, key('changed')]), \
                self.assertRaisesRegex(F.FreshRefused, 'differs from the pinned SHA-256 after the copy'):
            self.seed(c)

    def test_outcomes_count_hits_and_misses_and_flag_disagreement(self):
        reused = {'pinned_sha256': key('pin'), 'seed_snapshots': 7, 'copy_seconds': 0.5}

        def measured(snapshots, sha):
            return {'sha256': sha, 'initial_component_queries': 7,
                    'statistics': {'snapshots': snapshots, 'operations': {'payload_reads': 11}}}
        disagree = 'COUNTS_DISAGREE_WITH_BYTES'
        for snapshots, sha, status, hits, misses in ((7, key('pin'), 'FULL_REUSE', 7, 0),
                                                     (9, key('after'), 'MISSES_MEASURED', 5, 2),
                                                     (7, key('after'), disagree, 7, 0), (8, key('pin'), disagree, 6, 1),
                                                     (15, key('after'), disagree, -1, 8),
                                                     (6, key('after'), disagree, 8, -1)):
            with self.subTest(snapshots=snapshots, status=status):
                outcome = F.reuse_outcome(reused, measured(snapshots, sha))
                self.assertEqual((outcome['status'], outcome['hits'], outcome['misses']), (status, hits, misses))
                self.assertEqual((outcome['full_reuse'], outcome['counts_agree_with_bytes']),
                                 (sha == key('pin'), status != disagree))
                self.assertEqual((outcome['after_sha256'], outcome['chunk_reads'], outcome['copy_seconds'],
                                  outcome['initial_component_queries']), (sha, 11, 0.5, 7))
        self.assertEqual(reused, {'pinned_sha256': key('pin'), 'seed_snapshots': 7, 'copy_seconds': 0.5})

    def test_the_hook_reports_once_and_counts_initial_component_queries(self):
        observed = {}
        observe = F.observe_measurements(observed)
        statistics = {name: index for index, name in enumerate(F.MEASUREMENT_COUNTS)}
        bounds = SimpleNamespace(record=lambda: {'cells': [{'initial_accuracy': {}}, {}, {'initial_accuracy': None}]})
        observe({**statistics, 'decoded_cache_bytes': 5}, bounds)
        self.assertEqual(observed, {'statistics': statistics, 'initial_component_queries': 2})
        with self.assertRaisesRegex(F.FreshRefused, 'reports once per admission'):
            observe(statistics, bounds)
        with self.assertRaises(KeyError):
            F.observe_measurements({})({}, bounds)

    def test_the_record_follows_a_reported_admission_and_a_closed_store(self):
        folder = self.base/'closed'
        folder.mkdir()
        with self.assertRaisesRegex(F.FreshRefused, 'did not report its measurement store'):
            F.measurement_record(folder, binding=self.binding, observed={})
        (folder/F.MEASUREMENT_STORE).write_bytes(b'closed')
        observed = {'statistics': {'snapshots': 1}, 'initial_component_queries': 1}
        self.assertEqual(F.measurement_record(folder, binding=self.binding, observed=observed),
                         {'filename': F.MEASUREMENT_STORE, 'bytes': 6, 'sha256': sha256(b'closed').hexdigest(),
                          'composition': self.binding, **observed})
        for suffix in F.MEASUREMENT_SIDECARS:
            with self.subTest(sidecar=suffix):
                (folder/(F.MEASUREMENT_STORE+suffix)).write_bytes(b'')
                with self.assertRaisesRegex(F.FreshRefused, 'left a journal or WAL'):
                    F.measurement_record(folder, binding=self.binding, observed=observed)
                (folder/(F.MEASUREMENT_STORE+suffix)).unlink()

    def test_the_composition_binds_profile_proof_driver_helpers_and_seed(self):
        row = {'advance_driver': {'sha256': key('driver')}, 'modules': {'b': 'b.py', 'a': 'a.py'}}
        profile = SimpleNamespace(sha256=key('profile'), record=lambda: row)
        sources = SimpleNamespace(files=lambda: {'a.py': key('a'), 'b.py': key('b'), 'c.py': key('c')})
        proof, seed = {'native_source_digest': key('native')}, {'PYTHONHASHSEED': '0', 'hash_randomization': 0}
        binding = F.measurement_composition(profile, sources, proof=proof, interpreter_seed=seed)
        self.assertEqual(binding, {'profile_sha256': key('profile'), 'source_proof': proof,
                                   'advance_driver_sha256': key('driver'),
                                   'helper_sha256': {'a': key('a'), 'b': key('b')}, 'interpreter_seed': seed})
        self.assertEqual(list(binding['helper_sha256']), ['a', 'b'])
        proof['native_source_digest'] = key('changed')
        self.assertEqual(binding['source_proof'], {'native_source_digest': key('native')})

    def test_the_seed_is_refused_early_and_copied_before_the_admission(self):
        import inspect
        source = inspect.getsource(F.run_fresh_interval)
        first = source.index('row = profile.record()')
        self.assertLess(source.index("require(seed is None or mode == 'interval'"), first)
        self.assertLess(source.index('require(SEED_ENVIRONMENT not in os.environ'), first)
        copy = source.index('reused = seed_initial_measurements(')
        self.assertLess(source.index('root_runner = require_promoted_root(store, store_directory)'), copy)
        self.assertLess(copy, source.index('FRESH.reopen_root('))
        self.assertLess(copy, source.index('_advance(record=record'))
        driver = (HERE/'fresh_interval_driver.py').read_text(encoding='utf8')
        self.assertIn("artifacts/'"+F.MEASUREMENT_STORE+"'", driver)


class StartGateArgumentTests(unittest.TestCase):
    """The launcher's start gate decision rides last in the guarded command; --launch refuses without one."""

    def test_the_gate_goes_last(self):
        gate = SG.stage_decision(SG.stage_key('interval', 1), booking_bytes=1 << 30, booking_basis='test booking')
        fixture = ProfileAndSourceTests('test_command_is_mode_specific_and_creates_nothing')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        argv = F.command(fixture.profile, sys.executable, mode='interval', stop_before_advance=True, start_gate=gate)
        self.assertEqual(argv[-3:], ['--stop-before-advance', SG.ARGUMENT, SG.encode(gate)])
        self.assertNotIn(SG.ARGUMENT, F.command(fixture.profile, sys.executable, mode='interval'))

    def test_launch_without_a_gate_refuses_before_anything_is_made(self):
        with tempfile.TemporaryDirectory(prefix='sg-', dir=HERE) as temporary:
            folder = Path(temporary)
            base = ['--profile', str(folder/'missing.json'), '--profile-sha256', key('p'), '--mode', 'root']
            with self.assertRaisesRegex(SG.StartGateRefused, 'no completed PASS record'):
                F.main([*base, '--launch'])
            with self.assertRaisesRegex(SG.StartGateRefused, 'child'):
                F.main([*base, '--workload', '--booking-bytes', '1', '--booking-basis', 'x'])
            with self.assertRaisesRegex(SG.StartGateRefused, 'child'):
                F.main([*base, '--launch', SG.ARGUMENT, '{}'])
            self.assertEqual(list(folder.iterdir()), [])

    def test_the_child_refuses_without_the_launchers_decision(self):
        with self.assertRaisesRegex(SG.StartGateRefused, 'no start gate decision'):
            SG.child_admit(None, 64 << 30)


def rewrite(path, value):
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    Path(path).write_bytes(value if type(value) is bytes else F.canonical(value))


class Lineage:
    """Item 21: one consistent synthetic record set for intervals 0..n-1 and the adopted catalog file.

    ``change[(kind, k)]`` edits one record before it is written and every later pin follows it, so a
    case breaks exactly the link it names. ``approval`` = k makes interval k review-adopted, with
    ``approval_change`` applied to its approval record before it is pinned. Interval 1's producer
    receipt (``interval_one``) is seeded, ordinary or review as interval 1 is, and
    ``receipt_change`` edits it before verdict(1) pins it. runner(k >= 2) records links 0..k-1.
    """

    def __init__(self, directory, n, change=(), approval=None, approval_change=(), receipt_change=None):
        self.directory, self.n = Path(directory), n
        self.links = []
        self.interval_one = {'output': self.directory/'run-interval', 'profile_sha256': key('profile')}
        change = dict(change)
        identities = {'producer_identity': key('producer'), 'runtime_identity': key('runtime')}
        catalog = self.directory/F.CATALOG
        catalog.write_bytes(b'adopted catalog of interval %d' % (n-1))
        self.records, parent_head, adopted_sha = [], key('root'), None
        for k in range(n):
            mode = 'root' if k == 0 else 'interval'
            review = approval == k
            runner = {'schema': F.RUNNER_RECORD_SCHEMA, 'interval': k, 'head': {'segment': key('head %d' % k)},
                      'workflow_id': key('workflow'), 'producer_pid': 10+k, **identities}
            if k == 0:
                runner['root'] = {'workflow_id': key('workflow'), 'root_key': key('root')}
            else:
                runner.update(previous_endpoint={'head': parent_head, 'intervals': k-1},
                              advanced_endpoint={'head': key('key %d' % k), 'intervals': k},
                              root_runner_record_sha256=self.records[0]['runner_sha256'])
                if k >= 2:
                    runner.update(parent_runner_record_sha256=self.records[k-1]['runner_sha256'],
                                  parent_adopted_sha256=adopted_sha,
                                  lineage={'schema': F.LINEAGE_SCHEMA, 'interval': k-1,
                                           'records': [dict(link) for link in self.links]})
            if review:
                runner['review_only'] = True
            runner = change.pop(('runner', k), lambda value: value)(runner)
            runner_sha = F.write_durable(F.runner_record_path(self.directory, k), runner)
            entry = {'interval': k, 'filename': f'interval-{k:04d}.sqlite', 'file_sha256': key('file %d' % k),
                     'logical_seal': key('seal %d' % k), 'head': runner['head'], **identities}
            sealed = {'schema': F.SEALED_SCHEMA, 'interval': k, 'entry': entry, 'runner_record_sha256': runner_sha,
                      'expected_catalog_digest': None if k == 0 else self.records[k-1]['adopted']['catalog_digest']}
            sealed = change.pop(('sealed', k), lambda value: value)(sealed)
            sealed_sha = F.write_durable(F.sealed_record_path(self.directory, k), sealed)
            receipt_sha = key('run A receipt') if k == 0 else key('receipt %d' % k)
            if k == 1:
                receipt_sha = self.receipt(runner_sha, sealed_sha, review, receipt_change)
            verdict = {'schema': F.VERDICT_SCHEMA, 'status': F.READER_PASS[mode], 'interval': k, 'entry': entry,
                       'runner_record_sha256': runner_sha, 'view_digest': key('view %d' % k),
                       'producer_receipt_sha256': receipt_sha}
            if k == 1:
                verdict['width_gate'] = {'schema': 'atlas.exact-width-gate.v1', 'passed': True}
            elif k >= 2:
                verdict['width_gate'] = {'schema': 'atlas.exact-width-gate.v2', 'interval': k, 'next_interval': k+1,
                                         'passed': True}
            if review:
                verdict['review_only'] = True
            verdict = change.pop(('verdict', k), lambda value: value)(verdict)
            verdict_sha = F.write_durable(F.verdict_path(self.directory, k), verdict)
            adopted = {'schema': F.ADOPTED_SCHEMA, 'status': F.ADOPTED_STATUS, 'interval': k, 'entry': entry,
                       'catalog_digest': key('catalog digest %d' % k),
                       'catalog_sha256': RUN.file_hash(catalog) if k == n-1 else key('older catalog %d' % k),
                       'verdict_sha256': verdict_sha, 'runner_record_sha256': runner_sha, 'adopter_pid': 50+k}
            if review:
                adopted['review_approval_sha256'] = self.approve(k, entry, verdict_sha, dict(approval_change))
            adopted = change.pop(('adopted', k), lambda value: value)(adopted)
            adopted_sha = F.write_durable(F.adopted_path(self.directory, k), adopted)
            self.records.append({'runner': runner, 'runner_sha256': runner_sha, 'sealed_sha256': sealed_sha,
                                 'verdict_sha256': verdict_sha, 'adopted': adopted, 'adopted_sha256': adopted_sha,
                                 'entry': entry})
            link = {'interval': k, 'runner_sha256': runner_sha, 'sealed_sha256': sealed_sha,
                    'verdict_sha256': verdict_sha, 'adopted_sha256': adopted_sha}
            if review:
                link.update(review_approval_sha256=adopted.get('review_approval_sha256'),
                            diagnosis_sha256=self.approval['diagnosis']['sha256'])
            self.links.append(link)
            parent_head = runner.get('advanced_endpoint', {}).get('head', key('root'))
        assert not change, 'unused change: %r' % sorted(change)
        self.pin = adopted_sha

    def receipt(self, runner_sha, sealed_sha, review, change):
        root = self.records[0]
        reused = {'schema': F.SEED_SCHEMA, 'status': 'COPIED_BEFORE_ADMISSION' if review else 'FULL_REUSE',
                  'composition_equal': True, 'receipt': {'path': 'run-root/run.json', 'sha256': key('run A receipt')},
                  'verdict_sha256': root['verdict_sha256'], 'adopted_sha256': root['adopted_sha256'],
                  **({} if review else {'counts_agree_with_bytes': True})}
        receipt = {'schema': F.RESULT_SCHEMA, 'mode': 'interval', 'interval': 1, 'profile_sha256': key('profile'),
                   'status': F.REVIEW_STATUS if review else F.SEALED_STATUS['interval'],
                   'errors': [{'type': 'PresealSealedForReview', 'message': 'sealed for review'}] if review else [],
                   'final_reserved_bytes': 0, 'production_acceptance': False,
                   'runner_record': {'path': str(F.runner_record_path(self.directory, 1)), 'sha256': runner_sha},
                   'sealed_awaiting_reader': {'path': str(F.sealed_record_path(self.directory, 1)),
                                              'sha256': sealed_sha},
                   'reused_initial_cache': reused, **({'review_only': {'state': F.REVIEW_STATUS}} if review else {})}
        receipt = receipt if change is None else change(receipt)
        output = self.interval_one['output']
        output.mkdir()
        (output/'run.json').write_bytes(json.dumps(receipt, indent=2).encode())
        return RUN.file_hash(output/'run.json')

    def approve(self, k, entry, verdict_sha, change):
        diagnosis = self.directory/('diagnosis-%d.md' % k)
        diagnosis.write_text('checker defect: draft binding helpers', encoding='utf8')
        self.approval = {'schema': F.REVIEW_APPROVAL_SCHEMA, 'interval': k, 'file_sha256': entry['file_sha256'],
                         'verdict_sha256': verdict_sha, 'approver': 'coordinator', 'approved_at': '2026-10-16T21:50',
                         'cause_class': 'checker-defect',
                         'diagnosis': {'path': str(diagnosis), 'sha256': RUN.file_hash(diagnosis)}, **change}
        return F.write_durable(F.approval_path(self.directory, k), self.approval)


def entry_view(entry, *, interval=None, head=None):
    """A stand-in accepted catalog entry: IntervalEntry's to_wire, interval and head.to_wire."""
    return SimpleNamespace(interval=entry['interval'] if interval is None else interval, to_wire=lambda: entry,
                           head=SimpleNamespace(to_wire=lambda: entry['head'] if head is None else head))


class LineageGateTests(unittest.TestCase):
    """Item 21's sealed-lineage gate: interval N starts only from the adopted interval N-1 of its chain."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lg-', dir=HERE)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(writable_tree, self.temp.name)
        self.count = 0

    def lineage(self, n=3, **options):
        self.count += 1
        directory = Path(self.temp.name)/str(self.count)
        directory.mkdir()
        return Lineage(directory, n, **options)

    def test_a_whole_lineage_passes_and_is_recorded(self):
        import fresh_interval_driver as FD
        import prepared_interval_driver as D
        self.assertEqual(F.LINEAGE_SCHEMA, FD.LINEAGE_SCHEMA)
        self.assertEqual(F.LINEAGE_SCHEMA, D.LINEAGE_SCHEMA)
        chain = self.lineage()
        gate = F.sealed_lineage(chain.directory, 3, chain.pin)
        lineage = gate['lineage']
        self.assertEqual({k: lineage[k] for k in ('schema', 'interval', 'workflow_id', 'root_key', 'head_key')},
                         {'schema': F.LINEAGE_SCHEMA, 'interval': 2, 'workflow_id': key('workflow'),
                          'root_key': key('root'), 'head_key': key('key 2')})
        self.assertEqual((lineage['catalog_digest'], lineage['catalog_sha256']),
                         (key('catalog digest 2'), RUN.file_hash(chain.directory/F.CATALOG)))
        self.assertEqual(lineage['records'], [
            {'interval': k, 'runner_sha256': r['runner_sha256'], 'sealed_sha256': r['sealed_sha256'],
             'verdict_sha256': r['verdict_sha256'], 'adopted_sha256': r['adopted_sha256']}
            for k, r in enumerate(chain.records)])
        self.assertEqual(gate['parent_adopted_sha256'], chain.pin)
        self.assertEqual(gate['root_runner'], chain.records[0]['runner'])
        self.assertEqual(gate['parent_runner'], chain.records[2]['runner'])
        self.assertEqual(gate['parent_adopted'], chain.records[2]['adopted'])
        short = self.lineage(2)
        self.assertEqual(F.sealed_lineage(short.directory, 2, short.pin, interval_one=short.interval_one)['lineage']['head_key'], key('key 1'))

    def test_every_parent_width_gate_must_have_passed(self):
        gate = lambda **new: (lambda value: {**value, 'width_gate': {**value['width_gate'], **new}})
        cases = (
            ({('verdict', 2): gate(passed=False)}, 'interval 2 width gate did not pass before interval 3'),
            ({('verdict', 1): gate(passed=False)}, 'interval 1 width gate did not pass before interval 2'),
            ({('verdict', 2): gate(passed=1)}, 'interval 2 width gate'),
            ({('verdict', 2): lambda v: {k: x for k, x in v.items() if k != 'width_gate'}}, 'interval 2 width gate'),
            ({('verdict', 2): gate(schema='atlas.exact-width-gate.v1')}, 'interval 2 width gate'),
            ({('verdict', 1): gate(schema='atlas.exact-width-gate.v2', interval=1, next_interval=2)},
             'interval 1 width gate'),
            ({('verdict', 2): gate(interval=1)}, 'interval 2 width gate'),
            ({('verdict', 2): gate(next_interval=4)}, 'interval 2 width gate'),
            ({('verdict', 0): lambda v: {**v, 'width_gate': {'schema': 'atlas.exact-width-gate.v1', 'passed': True}}},
             'interval 0 width gate'))
        for change, message in cases:
            with self.subTest(change=sorted(change)), self.assertRaisesRegex(ValueError, message):
                chain = self.lineage(change=change)
                F.sealed_lineage(chain.directory, 3, chain.pin)
        reviewed = self.lineage(approval=2, change={('verdict', 2): gate(passed=False)})
        with self.assertRaisesRegex(ValueError, 'interval 2 width gate did not pass'):
            F.sealed_lineage(reviewed.directory, 3, reviewed.pin)

    def test_only_interval_n_of_two_or_more_with_an_exact_pin(self):
        chain = self.lineage()
        for interval, pin, message in ((1, chain.pin, 'N >= 2'), (0, chain.pin, 'N >= 2'), ('3', chain.pin, 'N >= 2'),
                                       (True, chain.pin, 'N >= 2'), (3, None, 'lowercase SHA-256'),
                                       (3, chain.pin.upper(), 'lowercase SHA-256'),
                                       (3, key('another adoption'), 'recorded SHA-256'),
                                       (4, chain.pin, 'cannot find|No such file')):
            with self.subTest(interval=interval, pin=pin), self.assertRaisesRegex(Exception, message):
                F.sealed_lineage(chain.directory, interval, pin)

    def test_each_broken_link_refuses(self):
        other = lambda name: (lambda value: {**value, name: key('another '+name)})
        edit = lambda part, new: (lambda value: {**value, part: {**value[part], **new}})
        drop = lambda name: (lambda value: {k: x for k, x in value.items() if k != name})
        cases = (
            ('no independent reader PASS', {('verdict', 1): lambda v: {**v, 'status': 'FAILED'}}),
            ('no independent reader PASS', {('verdict', 0): lambda v: {**v, 'status': F.READER_PASS['interval']}}),
            ('no independent reader PASS', {('verdict', 1): edit('entry', {'logical_seal': key('x')})}),
            ('no independent reader PASS', {('verdict', 2): other('runner_record_sha256')}),
            ('no independent reader PASS', {('verdict', 2): lambda v: {**v, 'interval': 1}}),
            ('not adopted from exactly', {('adopted', 1): lambda v: {**v, 'status': 'QUARANTINED'}}),
            ('not adopted from exactly', {('adopted', 1): edit('entry', {'file_sha256': key('x')})}),
            ('not adopted from exactly', {('adopted', 0): other('runner_record_sha256')}),
            ('not adopted from exactly', {('adopted', 1): other('verdict_sha256')}),
            ('not adopted from exactly', {('adopted', 2): lambda v: {**v, 'interval': 1}}),
            ('does not bind its runner', {('sealed', 2): other('runner_record_sha256')}),
            ('does not bind its runner', {('sealed', 1): edit('entry', {'head': {'segment': key('x')}})}),
            ('does not bind its runner', {('sealed', 1): edit('entry', {'interval': 2})}),
            ('does not bind its runner', {('runner', 1): lambda v: {**v, 'interval': 2}}),
            ('sealed against the catalog', {('sealed', 1): other('expected_catalog_digest')}),
            ('sealed against the catalog', {('sealed', 2): other('expected_catalog_digest')}),
            ('sealed against the catalog', {('sealed', 0): other('expected_catalog_digest')}),
            ('does not extend', {('runner', 1): other('workflow_id')}),
            ('does not extend', {('runner', 2): other('root_runner_record_sha256')}),
            ('does not extend', {('runner', 1): edit('previous_endpoint', {'head': key('x')})}),
            ('does not extend', {('runner', 2): edit('previous_endpoint', {'head': key('root')})}),
            ('does not extend', {('runner', 2): edit('previous_endpoint', {'intervals': 0})}),
            ('does not extend', {('runner', 2): edit('advanced_endpoint', {'intervals': 3})}),
            ('does not extend', {('runner', 2): edit('advanced_endpoint', {'head': key('key 1')})}),
            ('parent records', {('runner', 2): other('parent_runner_record_sha256')}),
            ('parent records', {('runner', 2): drop('parent_adopted_sha256')}),
            ('parent records', {('runner', 1): lambda v: {**v, 'parent_adopted_sha256': key('x')}}),
            ('root of this workflow', {('runner', 0): edit('root', {'workflow_id': key('x')})}),
            ('root of this workflow', {('runner', 0): drop('root')}),
            ('review', {('runner', 1): lambda v: {**v, 'review_only': True}}),
            ('review', {('verdict', 2): lambda v: {**v, 'review_only': True}}),
            ('review', {('runner', 1): lambda v: {**v, 'review_only': False}}),
        )
        for index, (message, change) in enumerate(cases):
            with self.subTest(index=index, message=message, change=sorted(change)):
                chain = self.lineage(change=change)
                with self.assertRaisesRegex(F.FreshRefused, message):
                    F.sealed_lineage(chain.directory, 3, chain.pin)

    def test_one_record_changed_alone_after_it_was_written_refuses(self):
        for kind, k, field, message in (('runner', 1, 'producer_pid', 'does not bind its runner'),
                                        ('runner', 0, 'producer_pid', 'does not bind its runner'),
                                        ('verdict', 2, 'view_digest', 'not adopted from exactly'),
                                        ('verdict', 0, 'view_digest', 'not adopted from exactly'),
                                        ('adopted', 1, 'adopter_pid', 'recorded SHA-256'),
                                        ('adopted', 0, 'catalog_digest', 'sealed against the catalog'),
                                        ('sealed', 2, 'expected_catalog_digest', 'sealed against the catalog')):
            with self.subTest(kind=kind, k=k):
                chain = self.lineage()
                path = {'runner': F.runner_record_path, 'verdict': F.verdict_path, 'adopted': F.adopted_path,
                        'sealed': F.sealed_record_path}[kind](chain.directory, k)
                rewrite(path, {**json.loads(path.read_bytes()), field: key('changed')})
                with self.assertRaisesRegex(F.FreshRefused, message):
                    F.sealed_lineage(chain.directory, 3, chain.pin)
        chain = self.lineage()
        rewrite(chain.directory/F.CATALOG, b'another catalog')
        with self.assertRaisesRegex(F.FreshRefused, 'catalog file differs'):
            F.sealed_lineage(chain.directory, 3, chain.pin)
        chain = self.lineage()
        rewrite(F.runner_record_path(chain.directory, 2), json.dumps(chain.records[2]['runner'], indent=1).encode())
        with self.assertRaisesRegex(F.FreshRefused, 'canonical'):
            F.sealed_lineage(chain.directory, 3, chain.pin)

    def test_a_review_adopted_parent_needs_its_pinned_approval(self):
        chain = self.lineage(approval=1)
        records = F.sealed_lineage(chain.directory, 3, chain.pin)['lineage']['records']
        self.assertEqual(records[1]['review_approval_sha256'], RUN.file_hash(F.approval_path(chain.directory, 1)))
        self.assertEqual(records[1]['diagnosis_sha256'], chain.approval['diagnosis']['sha256'])
        self.assertNotIn('review_approval_sha256', records[2])
        short = self.lineage(n=2, approval=1)
        self.assertIn('diagnosis_sha256', F.sealed_lineage(short.directory, 2, short.pin, interval_one=short.interval_one)['lineage']['records'][1])
        for message, change in (('data-integrity cause is quarantined', {'cause_class': 'data-defect'}),
                                ('does not name this sealed file', {'file_sha256': key('x')}),
                                ('does not name this sealed file', {'approver': 'the runner'}),
                                ('does not name this sealed file', {'interval': 2}),
                                ('written diagnosis', {'diagnosis': {'path': 'missing.md', 'sha256': key('x')}})):
            with self.subTest(message=message, change=sorted(change)):
                chain = self.lineage(approval=1, approval_change=change)
                with self.assertRaisesRegex(F.FreshRefused, message):
                    F.sealed_lineage(chain.directory, 3, chain.pin)
        chain = self.lineage(approval=1)
        rewrite(F.approval_path(chain.directory, 1), {**chain.approval, 'approved_at': 'later'})
        with self.assertRaisesRegex(F.FreshRefused, 'recorded SHA-256'):
            F.sealed_lineage(chain.directory, 3, chain.pin)
        for k in (0, 2):
            with self.subTest(review_of=k):
                chain = self.lineage(approval=k) if k == 0 else self.lineage(change={
                    ('adopted', 2): lambda v: {**v, 'review_approval_sha256': key('x')}})
                with self.assertRaisesRegex(F.FreshRefused, 'review'):
                    F.sealed_lineage(chain.directory, 3, chain.pin)

    def gate(self, chain, n=None):
        n = chain.n if n is None else n
        return F.sealed_lineage(chain.directory, n, chain.pin, interval_one=chain.interval_one if n == 2 else None)

    def test_interval_two_authenticates_the_root_by_interval_ones_seeded_receipt(self):
        misses = lambda r: {**r, 'reused_initial_cache': {**r['reused_initial_cache'], 'status': 'MISSES_MEASURED'}}
        for options in ({}, {'receipt_change': misses}, {'approval': 1}):
            with self.subTest(options=sorted(options)):
                chain = self.lineage(n=2, **options)
                self.assertEqual(self.gate(chain)['lineage']['records'], chain.links)
        chain = self.lineage(n=2)
        for interval_one, message in ((None, "only interval 2's gate reads interval 1's receipt"),
                                      ({**chain.interval_one, 'x': 1}, "needs interval 1's output and profile"),
                                      ({'output': chain.interval_one['output']}, "needs interval 1's output"),
                                      ({**chain.interval_one, 'profile_sha256': key('x')}, 'does not bind interval 1')):
            with self.subTest(interval_one=interval_one), self.assertRaisesRegex(F.FreshRefused, message):
                F.sealed_lineage(chain.directory, 2, chain.pin, interval_one=interval_one)
        three = self.lineage()
        with self.assertRaisesRegex(F.FreshRefused, "only interval 2's gate reads interval 1's receipt"):
            F.sealed_lineage(three.directory, 3, three.pin, interval_one=three.interval_one)

    def test_interval_two_refuses_without_a_valid_interval_one_anchor(self):
        seed = lambda **new: (lambda r: {**r, 'reused_initial_cache': {**r['reused_initial_cache'], **new}})
        top = lambda **new: (lambda r: {**r, **new})
        pin = lambda name: (lambda r: {**r, name: {**r[name], 'sha256': key('another record')}})
        review_error = [{'type': 'PresealSealedForReview', 'message': 'sealed for review'}]
        as_review = lambda r: {**r, 'status': F.REVIEW_STATUS, 'errors': review_error,
                               'review_only': {'state': F.REVIEW_STATUS},
                               'reused_initial_cache': {**r['reused_initial_cache'], 'status': 'COPIED_BEFORE_ADMISSION'}}
        as_ordinary = lambda r: {**{k: v for k, v in r.items() if k != 'review_only'},
                                 'status': F.SEALED_STATUS['interval'], 'errors': [],
                                 'reused_initial_cache': {**r['reused_initial_cache'], 'status': 'FULL_REUSE',
                                                          'counts_agree_with_bytes': True}}
        unseeded, outcome = 'unseeded interval 1 cannot continue', 'neither a completed nor an approved review'
        bind, capture = 'does not bind interval 1 of this lineage', "differs from interval 1's seeded capture"
        cases = (
            (unseeded, {}, lambda r: {k: v for k, v in r.items() if k != 'reused_initial_cache'}),
            (unseeded, {}, top(reused_initial_cache=None)),
            (unseeded, {}, seed(schema='atlas.other.v1')),
            (outcome, {}, seed(status='REFUSED_BEFORE_ADMISSION')),
            (outcome, {}, seed(status='COUNTS_DISAGREE_WITH_BYTES')),
            (outcome, {}, seed(counts_agree_with_bytes=False)),
            (outcome, {}, seed(status='COPIED_BEFORE_ADMISSION')),
            (outcome, {}, top(status=F.STOPPED_STATUS)),
            (outcome, {}, top(status='FAILED', errors=[{'type': 'X', 'message': 'x'}])),
            (outcome, {}, top(errors=review_error)),
            (outcome, {}, as_review),
            (outcome, {'approval': 1}, as_ordinary),
            (outcome, {'approval': 1}, top(errors=[*review_error, {'type': 'X', 'message': 'x'}])),
            (outcome, {'approval': 1}, top(errors=['PresealSealedForReview'])),
            (outcome, {'approval': 1}, top(review_only={'state': 'other'})),
            (outcome, {'approval': 1}, top(status=F.SEALED_STATUS['interval'])),
            (outcome, {'approval': 1}, seed(status='FULL_REUSE')),
            (capture, {}, seed(composition_equal=False)),
            (capture, {}, seed(receipt={'path': 'run-root/run.json', 'sha256': key('another run A receipt')})),
            (capture, {}, seed(receipt=None)),
            (capture, {}, seed(verdict_sha256=key('x'))),
            (capture, {}, seed(adopted_sha256=key('x'))),
            (bind, {}, top(schema='atlas.other.v1')), (bind, {}, top(mode='root')), (bind, {}, top(interval=2)),
            (bind, {}, lambda r: {k: v for k, v in r.items() if k != 'interval'}),
            (bind, {}, top(profile_sha256=key('another profile'))),
            (bind, {}, pin('runner_record')), (bind, {}, pin('sealed_awaiting_reader')),
            (bind, {}, top(runner_record=None)),
            (bind, {}, top(final_reserved_bytes=1)), (bind, {}, top(production_acceptance=True)),
        )
        for index, (message, options, change) in enumerate(cases):
            with self.subTest(index=index, message=message):
                chain = self.lineage(n=2, receipt_change=change, **options)
                with self.assertRaisesRegex(F.FreshRefused, message):
                    self.gate(chain)
        chain = self.lineage(n=2)
        path = chain.interval_one['output']/'run.json'
        raw = path.read_bytes()
        path.write_bytes(raw+b' ')
        with self.assertRaisesRegex(Exception, 'pinned configuration changed'):
            self.gate(chain)
        path.unlink()
        with self.assertRaises((OSError, ValueError)):
            self.gate(chain)
        chain = self.lineage(n=2, change={('verdict', 1): lambda v: {k: x for k, x in v.items()
                                                                      if k != 'producer_receipt_sha256'}})
        with self.assertRaisesRegex(Exception, 'lowercase SHA-256'):
            self.gate(chain)

    def test_a_root_verdict_and_adoption_substitution_refuses_at_every_n(self):
        messages = {2: "differs from interval 1's seeded capture",
                    3: 'intervals 0..1 differ from the lineage interval 2 was admitted with',
                    4: 'intervals 0..2 differ from the lineage interval 3 was admitted with'}
        for n, message in messages.items():
            for name in ('paired verdict and adoption', 'adoption audit field'):
                with self.subTest(n=n, name=name):
                    chain = self.lineage(n=n)
                    self.gate(chain)
                    verdict_path, adopted_path = F.verdict_path(chain.directory, 0), F.adopted_path(chain.directory, 0)
                    adopted = json.loads(adopted_path.read_bytes())
                    if name == 'paired verdict and adoption':
                        verdict = {**json.loads(verdict_path.read_bytes()), 'view_digest': key('substituted view')}
                        rewrite(verdict_path, verdict)
                        adopted['verdict_sha256'] = F._record_sha(verdict)
                    else:
                        adopted['adopter_pid'] = 99
                    rewrite(adopted_path, adopted)
                    with self.assertRaisesRegex(F.FreshRefused, message):
                        self.gate(chain)

    def test_from_interval_three_the_earlier_links_must_equal_the_parents_admitted_lineage(self):
        records = lambda change: (lambda v: {**v, 'lineage': {**v['lineage'], 'records': change(v['lineage']['records'])}})
        for index, change in enumerate((lambda v: {k: x for k, x in v.items() if k != 'lineage'},
                                        lambda v: {**v, 'lineage': None},
                                        records(lambda r: r[:1]), records(lambda r: [*r, r[1]]),
                                        records(lambda r: [r[0], {**r[1], 'verdict_sha256': key('x')}]),
                                        records(lambda r: [{**r[0], 'adopted_sha256': key('x')}, r[1]]),
                                        records(lambda r: [{**r[0], 'review_approval_sha256': key('x')}, r[1]]))):
            with self.subTest(index=index):
                chain = self.lineage(change={('runner', 2): change})
                with self.assertRaisesRegex(F.FreshRefused, 'intervals 0..1 differ from the lineage interval 2'):
                    self.gate(chain)
        reviewed = self.lineage(n=4, approval=1)
        self.assertEqual(self.gate(reviewed)['lineage']['records'], reviewed.links)

    def test_the_opened_catalog_must_hold_exactly_the_lineage_head(self):
        chain = self.lineage()
        gate = F.sealed_lineage(chain.directory, 3, chain.pin)
        entry = chain.records[2]['entry']

        def store(digest=key('catalog digest 2'), accepted=entry_view(entry), workflow_id=key('workflow')):
            return SimpleNamespace(store_set=SimpleNamespace(catalog_digest=digest, head=accepted),
                                   workflow_id=workflow_id)
        self.assertEqual(F.require_lineage_head(store(), gate), chain.records[0]['runner'])
        for name, opened in (('digest', store(digest=key('x'))), ('none', store(accepted=None)),
                             ('interval', store(accepted=entry_view(entry, interval=1))),
                             ('entry', store(accepted=entry_view({**entry, 'logical_seal': key('x')}))),
                             ('head', store(accepted=entry_view(entry, head={'segment': key('x')}))),
                             ('workflow', store(workflow_id=key('x')))):
            with self.subTest(name=name), self.assertRaisesRegex(F.FreshRefused, 'adopted interval N-1'):
                F.require_lineage_head(opened, gate)


class SuccessorDigestTests(unittest.TestCase):
    """On real compact stores: interval 1 is sealed against exactly the catalog digest adopting the root left."""

    @unittest.skipUnless(hasattr(IntervalStoreSet, 'adopt_and_promote'), 'Step 9(a) storage primitives not merged yet')
    def test_a_successor_seal_expects_the_digest_its_parent_adoption_recorded(self):
        fixture = StoreRecordTests('test_runner_record_precedes_the_seal_and_nothing_is_promoted')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        catalog, store, head = fixture.new_store('s')
        sealed = fixture.seal(store, head, fixture.root/'s', {})
        entry = sealed['entry']
        from compact_contracts import SegmentRef
        runner = F.read_record(F.runner_record_path(fixture.root/'s', 0), schema=F.RUNNER_RECORD_SCHEMA)
        identity = {'expected_sha256': entry['file_sha256'], 'expected_logical_seal': entry['logical_seal'],
                    'head': SegmentRef.from_wire(runner['head']), 'producer_identity': runner['producer_identity'],
                    'runtime_identity': runner['runtime_identity']}
        view = IntervalStoreSet.open_pending(catalog, entry['filename'], scope=fixture.scope,
                                             workflow_id=key('workflow'), expected_catalog_digest=None, **identity)
        try:
            digest = view.catalog_digest
        finally:
            view.close()
        store.close()
        stores = IntervalStoreSet.create_migration(catalog, workflow_id=key('workflow'), scope=fixture.scope)
        try:
            stores.adopt_and_promote(entry['filename'], expected_catalog_digest=None, reader_view_digest=digest,
                                     **identity)
            adopted_digest = stores.catalog_digest
        finally:
            stores.close()
        adopted_file = RUN.file_hash(catalog)
        reopened = CompactRestartStore.open_catalog(catalog, scope=fixture.scope)
        fixture.stores.append(reopened)
        self.assertEqual(reopened.store_set.catalog_digest, adopted_digest)
        reopened.start_next_interval(**fixture.identities)
        successor = key('successor')
        reopened.put(successor, {'b': np.arange(1024, dtype='<i8')}, {'kind': 'successor', 'sequence': 1})
        sealed_next = F.seal_with_records(reopened, successor, store_directory=fixture.root/'s', interval=1,
            identities=fixture.identities, record={}, save=lambda: None, extra={'workflow_id': key('workflow')})
        self.assertEqual(sealed_next['expected_catalog_digest'], adopted_digest)
        # The reader re-runs the sealed-lineage gate after this seal: the catalog file must be unchanged.
        self.assertEqual(RUN.file_hash(catalog), adopted_file)
        self.assertFalse(any(Path(str(catalog)+suffix).exists() for suffix in ('-wal', '-journal')))


class IntervalNCommandTests(unittest.TestCase):
    """Item 21's explicit interval number and parent pin on the runner's command line."""

    def setUp(self):
        self.fixture = ProfileAndSourceTests('test_command_is_mode_specific_and_creates_nothing')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.profile, self.attempt = self.fixture.profile, self.fixture.attempt

    def test_interval_n_names_its_own_output_and_carries_its_pin_before_the_gate(self):
        gate = SG.stage_decision(SG.stage_key('interval', 2), booking_bytes=1 << 30, booking_basis='test booking')
        argv = F.command(self.profile, sys.executable, mode='interval', interval=2, parent_adopted_sha256=key('a'),
                         start_gate=gate)
        self.assertEqual(argv[argv.index('--output')+1], str(self.attempt/'run-interval-0002'/'run.json'))
        self.assertEqual(argv[-6:], ['--interval', '2', '--parent-adopted-sha256', key('a'), SG.ARGUMENT,
                                     SG.encode(gate)])
        for interval in (None, 1):
            argv = F.command(self.profile, sys.executable, mode='interval', interval=interval)
            self.assertNotIn('--interval', argv)
            self.assertNotIn('--parent-adopted-sha256', argv)
            self.assertEqual(argv[argv.index('--output')+1], str(self.attempt/'run-interval'/'run.json'))
        self.assertEqual(F.mode_output(self.fixture.row, 'interval', 12), self.attempt/'run-interval-0012')
        self.assertEqual(F.mode_output(self.fixture.row, 'interval', 1), self.attempt/'run-interval')
        self.assertEqual(F.mode_output(self.fixture.row, 'root'), self.attempt/'run-root')
        # Interval 2's gate reads interval 1's receipt where interval 1 wrote it, under this profile.
        self.assertEqual(F.interval_one_route(self.profile), {'output': self.attempt/'run-interval',
                                                              'profile_sha256': self.profile.sha256})
        for k in (0, -1, True, 1.0):
            with self.subTest(k=k), self.assertRaisesRegex(F.FreshRefused, 'belongs to interval k >= 1'):
                F.width_gate_passed({'schema': F.WIDTH_GATE_V1, 'passed': True}, k)
        self.assertFalse(list(self.attempt.iterdir()))

    def test_refusals(self):
        cases = (('N >= 1 of the interval mode', dict(mode='root', interval=1)),
                 ('N >= 1 of the interval mode', dict(mode='root', interval=0)),
                 ('N >= 1 of the interval mode', dict(mode='interval', interval=0)),
                 ('N >= 1 of the interval mode', dict(mode='interval', interval=True)),
                 ('N >= 1 of the interval mode', dict(mode='interval', interval='2')),
                 ('adopted\\(N-1\\) pin', dict(mode='interval', interval=2)),
                 ('adopted\\(N-1\\) pin', dict(mode='interval', parent_adopted_sha256=key('a'))),
                 ('adopted\\(N-1\\) pin', dict(mode='interval', interval=1, parent_adopted_sha256=key('a'))),
                 ('lowercase SHA-256', dict(mode='interval', interval=2, parent_adopted_sha256=key('a').upper())),
                 ('no smoke', dict(mode='interval', interval=2, parent_adopted_sha256=key('a'),
                                   stop_before_advance=True)))
        for message, arguments in cases:
            with self.subTest(arguments=arguments), self.assertRaisesRegex(RUN.RestartRefused, message):
                F.command(self.profile, sys.executable, **arguments)
        row = dict(self.fixture.row, store_directory=str(self.attempt/'run-interval-0002'/'store'))
        with self.assertRaisesRegex(F.FreshRefused, 'outlive'):
            F.mode_output(row, 'interval', 2)
        self.assertFalse(list(self.attempt.iterdir()))

    def test_main_passes_the_interval_and_pin_to_the_gate_key_and_the_child(self):
        base = ['--profile', str(self.fixture.path), '--profile-sha256', self.profile.sha256, '--mode', 'interval']
        with mock.patch.object(F, '_workload', return_value=0) as workload:
            F.main([*base, '--workload', '--interval', '3', '--parent-adopted-sha256', key('a')])
            F.main([*base, '--workload'])
        self.assertEqual([(c.kwargs['interval'], c.kwargs['parent_adopted_sha256']) for c in workload.call_args_list],
                         [(3, key('a')), (None, None)])
        with mock.patch.object(SG, 'stage_decision', side_effect=SG.StartGateRefused('stop')) as decision:
            for extra, interval in ((['--interval', '3', '--parent-adopted-sha256', key('a')], 3), ([], 1)):
                with self.assertRaises(SG.StartGateRefused):
                    F.main([*base, '--launch', *extra])
                self.assertEqual(decision.call_args.args[0], SG.stage_key('interval', interval))
        with mock.patch.object(SG, 'admit'), mock.patch.object(F.subprocess, 'call', return_value=0) as call:
            F.main([*base, '--launch', '--booking-bytes', '1', '--booking-basis', 'test booking',
                    '--interval', '2', '--parent-adopted-sha256', key('a')])
        output = self.attempt/'run-interval-0002'
        self.assertEqual(call.call_args.kwargs['cwd'], output)
        self.assertEqual(call.call_args.args[0][call.call_args.args[0].index('--output')+1], str(output/'run.json'))
        self.assertEqual(list(self.attempt.iterdir()), [output])


class IntervalNFlowTests(unittest.TestCase):
    """Item 21 inside the runner: the gate before the open, the head after it, the successor advance and records."""

    def source(self, name):
        tree = ast.parse(Path(F.__file__).read_text(encoding='utf8'))
        return ast.unparse(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name))

    def test_the_gate_reads_records_before_the_catalog_opens_and_binds_the_head_after(self):
        text = self.source('run_fresh_interval')
        gate = text.index('sealed_lineage(store_directory, number, parent_adopted_sha256, '
                          'interval_one=interval_one_route(profile) if number == 2 else None)')
        opened = text.index('CRS.CompactRestartStore.open_catalog(catalog')
        head = text.index('require_lineage_head(store, lineage)')
        self.assertLess(gate, opened)
        self.assertLess(opened, head)
        self.assertLess(head, text.index('seed_initial_measurements('))
        self.assertIn("record['lineage'] = lineage['lineage']", text)
        self.assertIn("require(not stop_before_advance or number == 1", text)

    def test_the_gate_assigns_the_sealed_lineage_unconditionally_at_interval_n(self):
        tree = ast.parse(self.source('run_fresh_interval'))
        gates = [node for node in ast.walk(tree) if isinstance(node, ast.If) and ast.unparse(node.test) == 'number >= 2'
                 and any(isinstance(s, ast.Assign) and ast.unparse(s.targets[0]) == 'lineage' for s in node.body)]
        self.assertEqual(len(gates), 1)
        self.assertEqual([ast.unparse(s) for s in gates[0].body],
                         ["guard.phase('sealed-lineage-gate')",
                          'lineage = sealed_lineage(store_directory, number, parent_adopted_sha256, '
                          'interval_one=interval_one_route(profile) if number == 2 else None)',
                          "record['lineage'] = lineage['lineage']", 'save()'])

    def test_interval_n_advances_through_the_successor_seam_and_records_its_parents(self):
        text = self.source('_advance')
        self.assertIn("FRESH.advance_successor_interval(m, store=store, expected_root=root_runner['root'], "
                      "lineage=lineage['lineage']", text)
        self.assertEqual(text.count('interval=number'), 2)
        for name in ('parent_runner_record_sha256', 'parent_adopted_sha256'):
            self.assertIn(name, text)

    def test_the_successor_driver_takes_what_the_runner_passes(self):
        import inspect
        import fresh_interval_driver as FD
        parameters = inspect.signature(FD.advance_successor_interval).parameters
        first = inspect.signature(FD.advance_first_interval).parameters
        self.assertEqual(set(parameters)-{'lineage'}, set(first))


if __name__ == '__main__':
    unittest.main()
