"""Plan 04 r3 point-2 controls for the two compact root routes.

Real producer stores: the selected base's own publishers write a sealed compact root (a v2
partition, a v3 thermal mesh and compact state records), which is reopened read-only and read
by the dump's own route functions (head_records, head_partition). Each chunk corruption,
mis-join, substitution or changed logical field must refuse in the dump, and the comparator's
r3 bindings (array_bindings_r5) must FAIL on the matching dump-level tampering. Synthetic rows
only: no runtime run, no interval data.

State record: chunk corruption (SR-1), dropped mesh join (SR-2), substituted mesh record (SR-3),
one changed logical field (SR-4). Partition: chunk corruption (P-1), one changed logical field
(P-2), substituted segment ref (P-3). The decoder list the dump names is checked against the
comparator's closed set (D-1).

Comparator structural guards (G-1 to G-10): each control makes one change to a valid read so that it
reaches one array_bindings_r5 guard on these routes, which must FAIL with its own message or return its
own REVIEW reason (G-3, G-4). G-8 to G-10 run bind_root on the read wrapped as an r5 dump (root_dump),
which adds the collar state the compact fixture root lacks; G-9 and G-10 first assert that bind_root
accepts it. evidence/route-guard-mutants-plan.json lists one planted mutant per guard.

usage: ATLAS_T=<private task root> python -B test_routes_r3.py [-v]   (PYTHONHASHSEED=0; skips without ATLAS_T)
Temporary stores go under PLAN04_T3 (default: the system temporary directory; never inside the candidate).
"""
import copy
import gc
import importlib.util
import json
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV = HERE.parent/'n9-tools-r21'
T = Path(os.environ.get('ATLAS_T', '.'))
CAND = T/'ac'/'p1820c-r4'
RUNTIME = T/'ac'/'runtime-integration-r1'/'runtime-src'
TEMP_ROOT = Path(os.environ.get('PLAN04_T3', tempfile.gettempdir()))
AVAILABLE = (CAND/'helpers'/'compact_restart_store.py').is_file() and (CAND/'src'/'atlas_tectonics').is_dir()
WF = 'a'*64
PRODUCER = {'fixture': 'plan04-r3-routes'}
OUTCOMES = []          # (control, refusal type, message): which guard refused, for the r3 report


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if AVAILABLE:
    # The base's own package first: the producer tests' path inserts must not shadow it.
    sys.path[:0] = [str(CAND/'src'), str(CAND/'helpers'), str(RUNTIME)]
    import atlas_tectonics  # noqa: E402
    assert Path(atlas_tectonics.__file__).resolve().is_relative_to((CAND/'src').resolve())
    D = load('dump_arm_r5_r3', DEV/'dump_arm_r5.py')
    C = load('compare_arms_r21_r3', DEV/'compare_arms_r21.py')
    B = C.component('array_bindings_r5')
    REFUSED = (D.DumpRefused, ValueError)     # every producer refusal on these routes is a ValueError


def origins_are_pinned():
    """Every loaded atlas_tectonics module comes from the selected base."""
    bad = []
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if type(filename) is not str:
            continue
        path = Path(filename).resolve()
        if name == 'atlas_tectonics' or name.startswith('atlas_tectonics.'):
            if not path.is_relative_to((CAND/'src').resolve()):
                bad.append(name)
    return bad


class Root:
    """A sealed compact root written by the producer's publishers, reopened read-only."""

    def __init__(self, folder, *, count=3, extra=False):
        from atlas_tectonics.resources import WorkBudget
        from content_cache import create_retained_scope
        import compact_restart_store as CRS
        import mesh_tables as M
        import partition_workflow_patch as PW
        import spatial_records_patch as SR
        import spatial_workflow_patch as SWP
        import workflow_transfer as WT
        from compact_store import CompactMeshStoreV3
        from test_mesh_v3 import fixture
        from test_spatial_records_patch import fixture_records
        self.folder = Path(folder)
        self.catalog = self.folder/'interval-catalog.json'
        budget = WorkBudget(768 << 20)
        scope = create_retained_scope(budget, process_epoch='plan04-r3-writer')
        store = CRS.CompactRestartStore.create_migration(self.catalog, workflow_id=WF, scope=scope,
                                                         producer_identity='b'*64, runtime_identity='c'*64)
        try:
            candidate = store.candidate
            mesh, _record, source, view, partition_ref = fixture(scope, candidate, count=count)
            adapter = CompactMeshStoreV3(candidate, scope=scope, support_source=source)
            ref = adapter.publish(mesh, producer=M.digest(PRODUCER))
            opened = adapter.open(ref, expected_geometry_id=mesh.geometry_id)
            envelope = SWP.persist_mesh(candidate, opened, PRODUCER, budget=budget)
            rows = fixture_records(8)
            state = dict(rows['state'], thermal_mesh_id=envelope['geometry_id'])
            refs = SR.publish_records(candidate, {'state': state}, budget=budget, source_producer=PRODUCER)
            header, _ = SR.headers(state, None, refs, mesh_reference=envelope)
            partition = PW.compact_header(view, {}, partition_ref.to_wire())
            self.mesh_identity = {'sha256': ref.identity.sha256, 'nbytes': ref.identity.canonical_bytes}
            self.state_identity = {'sha256': refs['state']['sha256'], 'nbytes': refs['state']['bytes']}
            self.partition_identity = {'sha256': partition_ref.identity.sha256,
                                       'nbytes': partition_ref.identity.canonical_bytes}
            # The identities a root reader proves for this head (compact roots prove no partition identity).
            self.targets = {'state': self.state_identity, 'mesh': self.mesh_identity}
            self.alternates = {}
            if extra:
                # A second, valid record set in the same store for the substitution controls.
                other_mesh, _r, other_source, other_view, other_partition = fixture(scope, candidate, count=count+1)
                other_adapter = CompactMeshStoreV3(candidate, scope=scope, support_source=other_source)
                other_ref = other_adapter.publish(other_mesh, producer=M.digest(PRODUCER))
                other_opened = other_adapter.open(other_ref, expected_geometry_id=other_mesh.geometry_id)
                other_envelope = SWP.persist_mesh(candidate, other_opened, PRODUCER, budget=budget)
                changed = dict(state, time_s=3.0)
                other_refs = SR.publish_records(candidate, {'state': changed}, budget=budget,
                                                source_producer=PRODUCER)
                self.alternates = {'mesh': json.loads(json.dumps(other_envelope)),
                                   'state_refs': json.loads(json.dumps(other_refs)),
                                   'partition': json.loads(json.dumps(dict(
                                       PW.compact_header(other_view, {}, other_partition.to_wire()))))}
                del other_mesh, other_source, other_view, other_adapter, other_opened
            self.root_key = WT.workflow_key('root', WF)
            self.metadata = json.loads(json.dumps({
                'key': self.root_key, 'kind': 'root', 'sequence': 0, 'workflow_id': WF,
                'exterior_state': dict(header), 'differential_partition': dict(partition)}))
            del mesh, source, view, adapter, opened, partition, header
            import numpy as np
            store.put(self.root_key, {'fixture': np.arange(3, dtype='<f8')}, self.metadata)
            store.seal_and_promote(self.root_key)
        finally:
            store.close()
            gc.collect()
            scope.close()

    def open(self):
        """Read-only reopen, as the dump does; returns (store, scope, budget)."""
        from atlas_tectonics.resources import WorkBudget
        from content_cache import create_retained_scope
        import compact_restart_store as CRS
        budget = WorkBudget(768 << 20)
        scope = create_retained_scope(budget, process_epoch='plan04-r3-reader')
        store = CRS.CompactRestartStore.open_catalog(self.catalog, scope=scope)
        return store, scope, budget


class Chunks:
    """Record the chunk ids the reads inside the block resolve through segment_store; results unchanged."""

    def __enter__(self):
        import segment_store as S
        self.module, self.original, self.ids = S, S._chunk, []

        def recording(resolver, owner, key, descriptor, cancel):
            self.ids.append(key)
            return self.original(resolver, owner, key, descriptor, cancel)
        S._chunk = recording
        return self

    def __exit__(self, *exc):
        self.module._chunk = self.original


def read(root, change=None, *, records=True, partition=True, targets=None):
    """Reopen the sealed root read-only and run the dump's own route functions on its (changed) head."""
    out = Path(tempfile.mkdtemp(prefix='o', dir=root.folder))
    (out/'records').mkdir()
    targets = root.targets if targets is None else targets
    store, scope, budget = root.open()
    try:
        with store:
            head = json.loads(json.dumps(store.metadata(root.root_key)))
            if change:
                change(head)
            found = entry = None
            if records:
                found = D.head_records(store, root.root_key, head, 0, targets, out, budget=budget, scope=scope)
            if partition:
                entry = D.head_partition(store, head, 0, targets, out, scope=scope)
    except BaseException as error:
        del store
        D.close_scope(scope, error)       # the dump's own handling: the refusal, not the scope close, surfaces
        raise
    del store
    D.close_scope(scope)
    return head, found, entry, out


def state_chunks(root):
    """The chunk ids the root state record's own read resolves (its mesh and partition reads excluded)."""
    import spatial_records_patch as SR
    store, scope, budget = root.open()
    try:
        with store, Chunks() as seen:
            state = store.metadata(root.root_key)['exterior_state']
            with SR.open_records(store, state['record_blobs'], budget=budget, scope=scope,
                                 source_producer=state['compact_mesh']['source_producer']) as opened:
                for child in opened.values():
                    for _ in D.owned_parts(child.iter_json()):
                        pass
                    child.close()
    except BaseException as error:
        del store
        D.close_scope(scope, error)
        raise
    del store
    D.close_scope(scope)
    return seen.ids


def partition_chunks(root):
    with Chunks() as seen:
        read(root, records=False)
    return seen.ids


def corrupt(root, ids, *, rehash):
    """Flip one payload byte of the first raw chunk among `ids` in the sealed file, optionally re-checksummed."""
    from interval_catalog import digest
    path = root.folder/'interval-0000.sqlite'
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IWRITE)        # sealing leaves the interval file read-only; restored below
    db = sqlite3.connect(path)
    try:
        for chunk_id in dict.fromkeys(ids):
            row = db.execute('SELECT descriptor, codec, payload FROM chunks WHERE id=?', (chunk_id,)).fetchone()
            if row is not None and row[1] == 'raw' and row[2]:
                break
        else:
            raise AssertionError('no raw chunk among the chunk ids the read resolved')
        desc, codec, payload = row
        changed = bytearray(payload)
        changed[len(changed)//2] ^= 1
        stored = digest(desc+b'\0'+codec.encode()+b'\0'+bytes(changed)) if rehash else None
        db.execute('UPDATE chunks SET payload=?, stored_sha=coalesce(?, stored_sha) WHERE id=?',
                   (bytes(changed), stored, chunk_id))
        db.commit()
    finally:
        db.close()
        path.chmod(mode)
    return chunk_id


def bump(value):
    """A different value of the same JSON type."""
    if type(value) is str:
        return value[:-1]+('0' if value[-1:] != '0' else '1')
    if type(value) in (int, float):
        return value+1
    return ['changed', value]


# bind_root on a root_dump of the fixture root: bound, with one exterior-route REVIEW (the fixture's state
# record is synthetic, not a spatial exterior state).
BOUND_ROOT = ({}, ['exterior route: state record is not a spatial exterior state'])


def root_dump(head, found, entry, *, kind='root'):
    """A read root head as bind_root's r5 dump and published-root proof (synthetic proof files, no runtime).

    bind_root binds a whole native root, and the compact fixture root carries no collar state: a minimal one
    over no collar arrays is added, with the result_id the comparator recomputes for it.
    """
    fields, native = {'plan_id': 'f'*64}, 'e'*64
    collar = {'fields_id': C.snapshot_id(fields, {}, None, 'root collar'), 'native_state_id': native}
    metadata = dict(copy.deepcopy(head), kind=kind, native_state_id=native, state={
        'schema': C.COLLAR_STATE_SCHEMA, 'fields': fields, 'result_id': sha256(C.producer_json(collar)).hexdigest()})
    published = {'kind': kind, 'root_key': head['key'],
                 'root_metadata_sha256': sha256(C.producer_json(metadata)).hexdigest()}
    dump = {'schema': B.SCHEMA, 'interval': 0, 'arrays': [], 'records': found, 'partition': entry,
            'head': {'key': head['key'], 'kind': kind, 'sequence': 0, 'root_metadata': metadata}}
    return dump, {'root': {'files': {'runner_record': {'root': published}}}}


@unittest.skipUnless(AVAILABLE, 'private source root (ATLAS_T) not supplied')
class Routes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='r3-', dir=TEMP_ROOT)
        cls.count = 0
        cls.shared = None           # the guard controls' one sealed root, built on first use

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        cls.temp.cleanup()

    def root(self, **kw):
        type(self).count += 1
        folder = Path(self.temp.name)/('s%d' % self.count)
        folder.mkdir()
        return Root(folder, **kw)

    def refused(self, label, call, pattern=None):
        with self.assertRaises(REFUSED) as caught:
            call()
        message = str(caught.exception)
        OUTCOMES.append((label, type(caught.exception).__name__, message[:110]))
        if pattern:
            self.assertRegex(message, pattern)

    def failed(self, label, call, pattern):
        with self.assertRaisesRegex(C.ProofError, pattern):
            call()
        OUTCOMES.append((label, 'ProofError', pattern))

    def reviewed(self, label, call, reason):
        try:
            outcome = call()
        except C.CompareError as error:     # a refusal where REVIEW is due is an assertion failure, not an error
            self.fail('%s refused instead of REVIEW: %s' % (label, error))
        self.assertEqual(outcome, reason)
        OUTCOMES.append((label, 'REVIEW', reason))

    def guarded(self):
        """A fresh read (its own output folder) of the one sealed root the comparator guard controls share."""
        if type(self).shared is None:
            type(self).shared = self.root()
        return read(type(self).shared)

    def test_00_positive_routes_and_bindings(self):
        root = self.root(extra=True)
        head, found, entry, out = read(root)
        self.assertEqual(found, root.targets)
        self.assertEqual({k: entry[k] for k in ('dumped', 'route', 'sha256', 'nbytes')},
                         dict(dumped=True, route=B.PARTITION_ROUTE, **root.partition_identity))
        self.assertEqual(entry['reference'], head['differential_partition']['compact_partition'])
        dump = {'records': found, 'partition': entry}
        B.mesh_join(C, head['exterior_state'])
        B.root_mesh_v3(C, dump, head['exterior_state'], out)
        self.assertIsNone(B.root_partition_v2(C, dump, head['differential_partition'], out))
        self.assertEqual(B.compare_root_partitions({'before': dump, 'after': dump}), [])
        self.assertEqual(origins_are_pinned(), [])

    def test_sr1_state_chunk_corruption(self):
        for rehash in (False, True):
            with self.subTest(rehash=rehash):
                root = self.root()
                ids = state_chunks(root)
                self.assertTrue(ids, 'the state read resolved no stored chunk')
                corrupt(root, ids, rehash=rehash)
                self.refused('SR-1 rehash=%s' % rehash, lambda root=root: read(root, partition=False),
                             'checksum mismatch')

    def test_sr2_dropped_mesh_join(self):
        root = self.root()
        for label, change in (
                ('no compact_mesh', lambda h: h['exterior_state'].pop('compact_mesh')),
                ('no thermal_mesh_id', lambda h: h['exterior_state'].pop('thermal_mesh_id')),
                ('another thermal_mesh_id', lambda h: h['exterior_state'].update(thermal_mesh_id='0'*64))):
            with self.subTest(label):
                self.refused('SR-2 '+label, lambda change=change: read(root, change, partition=False))
        head, found, entry, out = read(root)
        dump, exterior = {'records': found, 'partition': entry}, head['exterior_state']
        self.failed('SR-2 header without compact_mesh', lambda: B.mesh_join(
            C, {k: v for k, v in exterior.items() if k != 'compact_mesh'}), 'without their v3 thermal mesh join')
        self.failed('SR-2 another thermal_mesh_id', lambda: B.root_mesh_v3(
            C, dump, dict(exterior, thermal_mesh_id='0'*64), out), 'dumped mesh differ')
        self.failed('SR-2 mesh record not dumped', lambda: B.root_mesh_v3(
            C, {'records': {'state': found['state']}, 'partition': entry}, exterior, out), 'dumped mesh differ')

    def test_sr3_substituted_mesh_record(self):
        root = self.root(extra=True)
        other = root.alternates['mesh']
        self.refused('SR-3 mesh reference only', lambda: read(root, lambda h: h['exterior_state'].update(
            compact_mesh=copy.deepcopy(other)), partition=False))

        def consistent(h):
            h['exterior_state'].update(compact_mesh=copy.deepcopy(other), thermal_mesh_id=other['geometry_id'])
        self.refused('SR-3 reference and join', lambda: read(root, consistent, partition=False),
                     'differ from the proved identities: mesh')
        # A dump taken against the substituted identities binds within itself, but not to the state record.
        identity = other['segment']['identity']
        swapped = {'state': root.state_identity, 'mesh': {'sha256': identity['sha256'],
                                                          'nbytes': identity['canonical_bytes']}}
        head, found, entry, out = read(root, consistent, targets=swapped)
        self.failed('SR-3 comparator', lambda: B.root_mesh_v3(C, {'records': found, 'partition': entry},
                                                              head['exterior_state'], out),
                    'state header differs from the dumped state record')

    def test_sr4_one_changed_logical_field(self):
        root = self.root(extra=True)
        refs = root.alternates['state_refs']

        def swap(h):
            h['exterior_state']['record_blobs'].update(state=copy.deepcopy(refs['state']))
        self.refused('SR-4 changed state record', lambda: read(root, swap, partition=False),
                     'differ from the proved identities: state')
        changed = {'state': {'sha256': refs['state']['sha256'], 'nbytes': refs['state']['bytes']},
                   'mesh': root.mesh_identity}
        head, found, entry, out = read(root, swap, targets=changed)
        self.failed('SR-4 comparator: record field', lambda: B.root_mesh_v3(
            C, {'records': found, 'partition': entry}, head['exterior_state'], out),
            'state header differs from the dumped state record')
        head, found, entry, out = read(root)
        dump, exterior = {'records': found, 'partition': entry}, head['exterior_state']
        self.failed('SR-4 comparator: header field', lambda: B.root_mesh_v3(
            C, dump, dict(exterior, time_s=bump(exterior['time_s'])), out),
            'state header differs from the dumped state record')
        blobs = copy.deepcopy(exterior['record_blobs'])
        blobs['state'].update(sha256=refs['state']['sha256'], bytes=refs['state']['bytes'])
        self.failed('SR-4 comparator: header record blob', lambda: B.root_mesh_v3(
            C, dump, dict(exterior, record_blobs=blobs), out), 'record blob is not the dumped state record')

    def test_p1_partition_chunk_corruption(self):
        for rehash in (False, True):
            with self.subTest(rehash=rehash):
                root = self.root()
                ids = partition_chunks(root)
                self.assertTrue(ids, 'the partition read resolved no stored chunk')
                corrupt(root, ids, rehash=rehash)
                self.refused('P-1 rehash=%s' % rehash, lambda root=root: read(root, records=False),
                             'checksum mismatch')

    def test_p2_one_changed_logical_field(self):
        root = self.root()
        head, found, entry, out = read(root)
        header = head['differential_partition']
        names = [k for k in B.PARTITION_HEADER_KEYS[1:] if k in header]
        self.assertTrue(names, 'the fixture header carries no optional partition field')
        for name in names:
            with self.subTest(name):
                self.refused('P-2 header '+name, lambda name=name: read(
                    root, lambda h: h['differential_partition'].update({name: bump(header[name])}), records=False),
                    'header differs from its stored descriptor')
                self.failed('P-2 comparator header '+name, lambda name=name: B.root_partition_v2(
                    C, {'records': found, 'partition': entry}, dict(header, **{name: bump(header[name])}), out),
                    'header differs from its dumped descriptor')
        self.refused('P-2 a reader-proved partition identity', lambda: read(
            root, records=False, targets=dict(root.targets, partition=root.partition_identity)),
            'proves no partition identity')
        # A changed descriptor file with a re-hashed entry is not the header reference's identity ...
        path = out/'records'/'partition.json'
        descriptor = json.loads(path.read_bytes())
        descriptor[names[0]] = bump(descriptor[names[0]])
        raw = C.producer_json(descriptor)
        path.write_bytes(raw)
        forged = dict(entry, sha256=sha256(raw).hexdigest(), nbytes=len(raw))
        self.failed('P-2 comparator: re-hashed descriptor', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': forged}, header, out), 'differs from the reader-proved header reference')
        # ... and the original entry no longer matches the file.
        self.failed('P-2 comparator: changed descriptor', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': entry}, header, out), 'changed since the dump')

    def test_p3_substituted_segment_ref(self):
        root = self.root(extra=True)
        other = root.alternates['partition']

        def swap(h):
            h['differential_partition'].update(compact_partition=copy.deepcopy(other['compact_partition']))
        self.refused('P-3 reference only', lambda: read(root, swap, records=False),
                     'header differs from its stored descriptor')
        head, found, entry, out = read(root)
        header = head['differential_partition']
        self.failed('P-3 comparator: entry reference', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': entry}, dict(header, compact_partition=other['compact_partition']), out),
            'differs from the reader-proved header reference')
        # A whole valid alternate header dumps and binds to itself; across arms it is REVIEW, never a PASS.
        _, _, alternate, _ = read(root, lambda h: h.update(differential_partition=copy.deepcopy(other)),
                                  records=False)
        self.assertEqual(B.compare_root_partitions({'before': {'partition': entry}, 'after': {'partition': alternate}}),
                         ['root v2 partition descriptors differ between arms: no field contract covers them'])

    def test_d1_decoder_list(self):
        # The dump's decoder list is the comparator's closed set; each must load from its pinned source.
        self.assertEqual(set(D.DECODER_MODULES), set(B.DECODER_PATHS))

        class Fence:
            workspace = CAND.resolve()

            @staticmethod
            def resolve(filename):
                return Path(filename).resolve()
        Fence.imported = set(B.DECODER_PATHS.values())
        Fence.pins = {rel: D.file_sha(CAND/rel) for rel in Fence.imported}
        found = D.decoders(Fence)
        self.assertEqual({name: entry['path'] for name, entry in found.items()}, B.DECODER_PATHS)
        self.assertTrue(all(entry['sha256'] == Fence.pins[entry['path']] for entry in found.values()))
        for label, change in (('not loaded through the fence', lambda: Fence.imported.discard('helpers/record_views.py')),
                              ('another pin', lambda: Fence.pins.update({'helpers/partition_v2.py': '0'*64}))):
            with self.subTest(label):
                saved = (set(Fence.imported), dict(Fence.pins))
                change()
                self.refused('D-1 '+label, lambda: D.decoders(Fence), 'not loaded from its pinned source')
                Fence.imported, Fence.pins = saved

    # Comparator structural guards (G-1 to G-10): one change to a valid read of the shared root reaches exactly
    # one array_bindings_r5 guard, and its own message (or REVIEW reason) is asserted.
    def test_guard_v2_header_not_closed(self):
        head, found, entry, out = self.guarded()
        self.failed('G-1 v2 header not closed', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': entry}, dict(head['differential_partition'], extra=True), out),
            'partition header is not closed')

    def test_guard_v2_reference_identity_malformed(self):
        head, found, entry, out = self.guarded()
        header = head['differential_partition']
        wire = copy.deepcopy(header['compact_partition'])
        wire['identity']['sha256'] = wire['identity']['sha256'][:-1]
        self.failed('G-2 v2 reference identity malformed', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': entry}, dict(header, compact_partition=wire), out),
            'partition reference identity malformed')

    def test_guard_v2_descriptor_not_dumped(self):
        head, found, entry, out = self.guarded()
        self.reviewed('G-3 v2 descriptor not dumped', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': dict(entry, dumped=False)}, head['differential_partition'], out),
            'root v2 partition descriptor not dumped: its header stays unbound')

    def test_guard_v2_descriptor_over_limit(self):
        # One size over the reader-side limit, on which the header reference and the entry agree.
        head, found, entry, out = self.guarded()
        header, size = head['differential_partition'], C.MAX_PROOF_BYTES+1
        wire = copy.deepcopy(header['compact_partition'])
        wire['identity']['canonical_bytes'] = size
        self.reviewed('G-4 v2 descriptor over the limit', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': dict(entry, reference=wire, nbytes=size)},
            dict(header, compact_partition=wire), out),
            'root v2 partition descriptor exceeds the reader-side recomputation limit')

    def test_guard_v2_descriptor_not_canonical(self):
        # The dumped descriptor plus a trailing newline, re-hashed through the entry and the header reference:
        # every byte and identity check passes, but the bytes are not the canonical producer encoding.
        head, found, entry, out = self.guarded()
        header = head['differential_partition']
        raw = (out/'records'/'partition.json').read_bytes()+b'\n'
        folder = out/'forged'
        (folder/'records').mkdir(parents=True)
        (folder/'records'/'partition.json').write_bytes(raw)
        wire = copy.deepcopy(header['compact_partition'])
        wire['identity'].update(sha256=sha256(raw).hexdigest(), canonical_bytes=len(raw))
        forged = dict(entry, reference=wire, sha256=sha256(raw).hexdigest(), nbytes=len(raw))
        self.failed('G-5 descriptor not canonical', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': forged}, dict(header, compact_partition=wire), folder),
            'not canonical producer JSON')

    def test_guard_v3_mesh_reference_not_closed(self):
        head, found, entry, out = self.guarded()
        exterior = head['exterior_state']
        self.failed('G-6 v3 mesh reference not closed', lambda: B.root_mesh_v3(
            C, {'records': found, 'partition': entry},
            dict(exterior, compact_mesh=dict(exterior['compact_mesh'], extra=True)), out),
            'mesh reference is not closed')

    def test_guard_exterior_record_blobs_malformed(self):
        exterior = self.guarded()[0]['exterior_state']
        self.failed('G-7 exterior record blob not an object', lambda: B.mesh_join(
            C, dict(exterior, record_blobs=dict(exterior['record_blobs'], state=[]))),
            'exterior record blobs malformed')

    def test_guard_partition_on_migrated_or_unproved_root(self):
        # A dumped v2 descriptor on a migrated root, or on a root whose metadata is unproved, binds no header.
        head, found, entry, out = self.guarded()
        dump, proofs = root_dump(head, found, entry, kind='migrated-root')
        self.failed('G-8 migrated root', lambda: B.bind_root(C, dump, proofs, out, None),
                    'on a root route with no v2 header')
        dump, proofs = root_dump(head, found, entry)
        del dump['head']['root_metadata']
        self.failed('G-8 unproved root metadata', lambda: B.bind_root(C, dump, proofs, out, None),
                    'on a root route with no v2 header')

    def test_guard_v2_partition_alias_arrays(self):
        head, found, entry, out = self.guarded()
        dump, proofs = root_dump(head, found, entry)
        self.assertEqual(B.bind_root(C, dump, proofs, out, None), BOUND_ROOT)
        dump['arrays'].append({'name': C.PARTITION_ALIAS+'faces'})     # one alias array beside the v2 header
        self.failed('G-9 v2 partition alias array', lambda: B.bind_root(C, dump, proofs, out, None),
                    'v2 root partition with alias arrays')

    def test_guard_v3_mesh_alias_arrays(self):
        head, found, entry, out = self.guarded()
        dump, proofs = root_dump(head, found, entry)
        self.assertEqual(B.bind_root(C, dump, proofs, out, None), BOUND_ROOT)
        dump['arrays'].append({'name': C.MESH_ALIAS+'cells'})          # one alias array beside the v3 mesh
        self.failed('G-10 v3 mesh alias array', lambda: B.bind_root(C, dump, proofs, out, None),
                    'v3 root mesh with spatial-mesh alias arrays')


    def test_tc_partition_dump_written_bytes_identity(self):
        # The old corruption case fails at stored-chunk checksum verification,
        # before this independent post-write identity seam can be reached.
        from unittest import mock
        root = self.root()
        _head, _found, entry, _out = read(root, records=False)
        self.assertEqual({k: entry[k] for k in ('sha256', 'nbytes')}, root.partition_identity)
        write = D.write_stream
        observed = []

        def altered_stream(path, chunks):
            self.assertEqual(path.name, 'partition.json')

            def altered_chunks():
                yield from chunks
                yield b' '
            value = write(path, altered_chunks())
            observed.append(value)
            return value

        with mock.patch.object(D, 'write_stream', side_effect=altered_stream):
            self.refused('TC P-1 post-write bytes', lambda: read(root, records=False),
                         'root partition descriptor bytes differ from the reference identity')
        self.assertEqual(len(observed), 1)
        self.assertNotEqual(observed[0], root.partition_identity)

    def test_tc_partition_entry_reference_only(self):
        # Change only the dumped entry's reference. Header/bytes/sha/size stay
        # valid, so a different identity comparison cannot mask this guard.
        root = self.root()
        head, found, entry, out = read(root, records=False)
        header = head['differential_partition']
        self.assertIsNone(B.root_partition_v2(C, {'records': found, 'partition': entry}, header, out))
        changed = copy.deepcopy(entry)
        digest = changed['reference']['identity']['sha256']
        changed['reference']['identity']['sha256'] = ('0' if digest[0] != '0' else '1') + digest[1:]
        self.assertNotEqual(changed['reference'], entry['reference'])
        self.assertEqual(changed['sha256'], entry['sha256'])
        self.assertEqual(changed['nbytes'], entry['nbytes'])
        self.failed('TC P-3 entry reference only', lambda: B.root_partition_v2(
            C, {'records': found, 'partition': changed}, header, out),
            'differs from the reader-proved header reference')



def tearDownModule():
    if OUTCOMES:
        print('\nr3 control refusals (control | type | message):')
        for row in OUTCOMES:
            print(' | '.join(row))


if __name__ == '__main__':
    unittest.main()
