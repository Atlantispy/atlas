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

HERE = Path(__file__).resolve().parent
COMPACT = HERE/'compact-geometry-r1'
RUNTIME = HERE.parent/'runtime-integration-r1'/'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import numpy as np
import run_fresh_interval as F
import run_prepared_restart as RUN
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


if __name__ == '__main__':
    unittest.main()
