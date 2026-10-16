"""R3 tests: the workflow store token kept across its OWN heat checkpoint save (finding X1).

Small synthetic fixtures only. Run from a copy whose layout mirrors the-diadem-local-tasks-10
(this file sits in .../resumability-r1/compact-geometry-r1). Temporary stores go under
R/L/r3, where R is this file's parent folder, unless R3T_TEMP names another root; every
test removes its own folder.
"""
import ast
import gc
import importlib
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
R = HERE.parent
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(HERE), str(RUNTIME), str(R)]
TEMP_ROOT = Path(os.environ.get('R3T_TEMP', str(R / 'L' / 'r3')))

import numpy as np
from atlas_tectonics.resources import WorkBudget

# The three modules under R, loaded by name so each import block holds one folder only.
CRS = importlib.import_module('compact_restart_store')
CRP = importlib.import_module('compact_restart_patch')
WT = importlib.import_module('workflow_transfer')

import heat_token_transform as H
import partition_workflow_transform as PWT
import publication_token_transform as T
import segment_store as S
import spatial_records_patch as SRP
import spatial_validation_patch as SVP
import spatial_workflow_patch as SWP
from compact_contracts import ContractError, LogicalIdentity
from content_cache import ChargeSpec, OwnedStream, create_retained_scope

WF = 'a' * 64
PRODUCER, RUNTIME_ID = 'b' * 64, 'c' * 64
R4_SCHEMA = 'atlas.private.exact-snapshot-compact-store.r4'
RC1 = R / 'composed-r1' / 'runtime-src' / 'atlas_tectonics' / 'integration_regional_workflow.py'
NATIVE_I = RUNTIME / 'atlas_tectonics' / 'integration_regional_workflow.py'
# Independent pins (the modules carry their own): the coordinator-accepted Step 10 chain
# (16 Oct 2026). Re-pin if RC1 or any stage before R3 changes before the freeze.
I_INPUT = 'ddb8d1b20aab4898e8b3a3ed3a0242b4bec538b5f902beea8b32778ed27b007a'
I_NONZERO = '61888439a0acd5484279cce374f23939550e81b38da73991d4f82c7c5e3c9916'
I_SPATIAL = '26ebf01ad7c5ecbdb2170092b8899d6c174e9c0169641426ade69449ee48cdc7'
RC1_SHA = 'b81752611b3860b26666467227582c3decee1ef7a1e91e5977ea6b04133542f9'
V2_OUTPUT = '834a1aa7603222d22ce8ca4aacaf3075b3e0446b16d95668251775dfb2738207'
Y3_OUTPUT = '4442ab250869b0b2aed12cf19cca1d0fbf6581f7cd047c1d5b6fab5a398d895e'
RECORDS_OUTPUT = 'e0eb3516b7939bb48fc7db909922914af4ef4152ee19006996491a63acd29e95'
VALIDATION_OUTPUT = '59d438f09535bbea0fcbe5f73be51d7c47bccc9b7577ce3027862eac6b89d49b'
RESTART_OUTPUT = 'db8505f67bf2dba1d722a87906823feab344a9f419cae34a7b71b66000225106'   # = the s1 smoke text (LF)
R2_OUTPUT = '4ef1894f29aa992ac3c89a0f3f04ddf8021d494b37a9cb3dcb3c463d9cb00538'
R3_OUTPUT = '7914531e1118c31b2a11dd24b5087fa76a4a1aa726078866d074e9a95e079dc5'
I_R2_R3_TEST_ONLY = '28238af49547c2d6e762469f55778f107288aca71f9a06db05a92c367a33f23a'
NEW_METHODS = {'_r3_write_mark', '_r3_heat_checkpoint_reason', '_r3_after_heat_checkpoint'}


def digest(text):
    return sha256(text.encode('utf8')).hexdigest()


# An empty index page body (segment_store._IndexBuilder._page with no entries).
EMPTY_PAGE = {'schema': S.PAGE_SCHEMA, 'kind': 'leaves', 'first_ordinal': 0, 'leaf_count': 0, 'entries': []}
# The interval-0 alias value of Fixture(alias=True) (what a by-key restore read expects).
ALIAS_VALUE = {'binding': 'history'}


def lookup(store, key):
    """What a by-key restore read of `key` sees now (a value, or the refusal it raises)."""
    try:
        return store.metadata(key)
    except Exception as error:  # noqa: BLE001 - any refusal differs from the alias value
        return 'raises ' + type(error).__name__


class Source:
    """One typed array streamed in owned blocks (as the production sources do)."""
    def __init__(self, scope, name, values):
        self.scope, self.raw = scope, np.ascontiguousarray(values).tobytes()
        self.info = S.ArrayInfo(name, values.dtype.str, tuple(values.shape), len(self.raw))

    def blocks(self, *, max_owned_bytes):
        def generate():
            for start in range(0, len(self.raw), max_owned_bytes):
                part = self.raw[start:start + max_owned_bytes]
                yield self.scope.reserve(ChargeSpec('r3-fixture-input', len(part))).commit(part)
        return OwnedStream(generate(), scope=self.scope)


# A model workflow carrying the EXACT RC1 anchors of both stages (R2: _refresh head lines,
# chain-loop end, publication check, post-put assignment; R3: the private-heat call and the
# _publish signature line). It is seamed by the same apply_seams functions as production.
MINI = '''import hashlib
import json
from types import SimpleNamespace

import numpy as np


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


class StoreConflict(Exception):
    pass


class RegionalOwnerRefused(ValueError):
    pass


class CollarWorkflow:
    def __init__(self, store, root, owner, budget):
        self._store, self._root, self._exterior_owner, self._budget = store, _json(root), owner, budget
        self._head, self._state, self._token = None, None, None
        self._initial_current_geometry = None
        self.refreshes = 0

    def _verify(self):
        pass

    @staticmethod
    def _key(kind, identity):
        return _hash(dict(kind=kind, identity=identity))

    def _refresh(self):
        self._verify()
        token = self._store.change_token()
        if token == self._token:
            return
        root = json.loads(self._root)
        if self._store.metadata(root['key']) != root:
            raise RegionalOwnerRefused('funded collar root changed')
        previous, accepted_parent = root, None
        for _sequence in range(1, 9):
            current = self._store.metadata(self._key('successor', previous['key']))
            if current is None:
                break
            if current['parent_digest'] != _hash(previous):
                raise RegionalOwnerRefused('funded collar chain changed or is out of order')
            accepted_parent, previous = previous, current
        # Stands for the full restore (restore_migrated_root / the cold successor restore).
        self.refreshes += 1
        self._head, self._state, self._token = previous, 'restored-state', token
        self._initial_current_geometry = None

    @property
    def current_geometry(self):
        self._refresh()
        return 'current-geometry'

    def inspect(self):
        self._refresh()
        return self._head['key']

    def advance_spatial(self, step, mesh, *, heat_boundary=None, cancel=None, heat_execution=None,
                        absolute_heat_residual_target=None):
        self._refresh()
        private_heat = True
        parent = self._head
        if private_heat:
            heat = self._exterior_owner.heat(step, mesh, boundary=heat_boundary, cancel=cancel,
                execution=heat_execution, absolute_residual_target=absolute_heat_residual_target,
                checkpoint_store=self._store)
        return self._publish(parent, SimpleNamespace(state='live-' + step), heat)

    def _publish(self, parent, result, exterior_advance, *, differential_interval=None,
                 differential_partition=None, differential_solution=None, cancel=None):
        # X1: _validate_differential_solution -> current_geometry -> _refresh()
        assert self.current_geometry == 'current-geometry'
        row = dict(key=self._key('successor', parent['key']), parent_digest=_hash(parent), kind='successor')

        def check():
            self._verify()
            root = json.loads(self._root)
            if self._store.metadata(parent['key']) != parent or self._store.metadata(root['key']) != root:
                raise StoreConflict('funded collar parent/admission changed before publication')

        self._store.put(row['key'], {'collar': np.linspace(0.0, 1.0, 40)}, row, publication_check=check)
        self._head, self._state, self._token = row, result.state, None
        return row
'''


class HeatOwner:
    """Saves a two-segment compact checkpoint into the candidate, as private heat r4 does
    (SegmentBackend.publish of the ledger and of the field payload), and returns an object
    whose reference() carries the r4-shaped receipt."""
    def __init__(self, fx):
        self.fx, self.intervene, self.tamper = fx, None, None

    def _segment(self, candidate, name, values):
        fx = self.fx
        schema = 'atlas.r3-fixture.' + name
        metadata = S.canonical({'schema': schema})
        identity = LogicalIdentity(schema, sha256(values.tobytes()).hexdigest(), values.nbytes)
        return S.SegmentBackend().publish(candidate, record_schema=schema, identity=identity, metadata=metadata,
            arrays=lambda: iter([Source(fx.scope, 'col', values)]), producer='d' * 64,
            representation_profile='atlas.r3-fixture.v1', scope=fx.scope)

    def heat(self, step, mesh, *, boundary, cancel, execution, absolute_residual_target, checkpoint_store):
        candidate = checkpoint_store.candidate
        shift = float(len(step))
        ledger = self._segment(candidate, 'ledger', np.arange(20000, dtype='<f8') + shift)
        fields = self._segment(candidate, 'fields', np.linspace(0.0, shift, 3000))
        if self.intervene is not None:
            self.intervene()
        metadata = {'schema': R4_SCHEMA, 'result_id': 'e' * 64, 'ledger': ledger.to_wire(),
                    'field_payload': fields.to_wire()}
        receipt = {'invocation': sha256(S.canonical(metadata)).hexdigest(), 'metadata': metadata}
        if self.tamper is not None:
            receipt = self.tamper(receipt)
        reference = json.dumps({'checkpoint': receipt})
        return SimpleNamespace(reference=lambda: json.loads(reference))


class Fixture:
    """Sealed interval 0 holding the root; unsealed interval 1 written by the model.

    With alias=True interval 0 also holds one restart alias under a derived key that the
    metadata chain does not reach. It stands for the aliases today's full restore reads by
    key, candidate-first: in IV1 the compact history and heat-history aliases and the compact
    partition lookup (workflow_transfer.migrated_root_payload), from IV2 on
    spatial_workflow_patch.existing_mesh (compact_migration_reference is the same class)."""
    ALIAS = sha256(b'r3-history-alias').hexdigest()
    # Route (1) (G-R3-7): the IV1 parent is the FRESH root Workflow.create writes, kind 'root',
    # sequence 0, under RC1's derived key _key('root', workflow_id) = sha256(json(binding)),
    # an alias-class key that today's restore reads by bare key, candidate-first.
    FRESH_ROOT = sha256(json.dumps({'identity': WF, 'kind': 'root'}, sort_keys=True,
                                   separators=(',', ':')).encode()).hexdigest()

    def __init__(self, folder, *, seams, alias=False, fresh=False):
        self.folder = Path(folder)
        self.budget = WorkBudget(512 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='r3-heat-token-tests')
        self.catalog = self.folder / 'interval-catalog.json'
        self.store = CRS.CompactRestartStore.create_migration(self.catalog, workflow_id=WF, scope=self.scope,
            producer_identity=PRODUCER, runtime_identity=RUNTIME_ID)
        if fresh:
            # The native sequence-0 exterior state, as record blobs (state and mesh).
            self.root = {'key': self.FRESH_ROOT, 'kind': 'root', 'sequence': 0}
            self.store.put(self.root['key'], {'state': np.arange(300, dtype='<f8'),
                                              'mesh': np.linspace(0.0, 1.0, 900)}, self.root)
        else:
            self.root = {'key': sha256(b'r3-root').hexdigest(), 'kind': 'migrated-root', 'sequence': 1}
            self.store.put(self.root['key'], {'root': np.arange(500, dtype='<f8')}, self.root)
        if alias:
            self.store.put(self.ALIAS, {'h': np.arange(7, dtype='<f8')}, ALIAS_VALUE)
        self.store.seal_and_promote(self.root['key'])
        self.store.start_next_interval(producer_identity=PRODUCER, runtime_identity=RUNTIME_ID)
        self.owner = HeatOwner(self)
        module = load(seams, self.folder)
        self.module = module
        self.workflow = module.CollarWorkflow(self.store, self.root, self.owner, self.budget)
        self.workflow.inspect()                     # the process-start full refresh

    def close(self):
        del self.workflow, self.module
        gc.collect()
        self.store.close()


def load(seams, folder):
    text = MINI
    if seams in ('r2', 'r3'):
        text = T.apply_seams(text)
    if seams == 'r3':
        text = H.apply_seams(text)
    path = Path(folder) / f'r3_mini_workflow_{seams}.py'
    path.write_text(text, encoding='utf8')
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixtureCase(unittest.TestCase):
    seams = 'r3'

    def setUp(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temps = []

    def fixture(self, seams=None, *, alias=False, fresh=False):
        temp = tempfile.TemporaryDirectory(prefix='r3-heat-', dir=TEMP_ROOT)
        self.assertTrue(Path(temp.name).resolve().is_relative_to(TEMP_ROOT.resolve()))
        fx = Fixture(temp.name, seams=self.seams if seams is None else seams, alias=alias, fresh=fresh)
        self.temps.append((fx, temp))
        return fx

    def tearDown(self):
        for fx, temp in reversed(self.temps):
            fx.close()
            temp.cleanup()


class KeepTokenTests(FixtureCase):
    def test_token_kept_on_the_clean_path(self):
        fx = self.fixture()
        wf = fx.workflow
        self.assertEqual(wf.refreshes, 1)
        row = wf.advance_spatial('s1', 'mesh')
        state = wf._r3_heat_checkpoint
        self.assertTrue(state['token_kept'], state)
        self.assertIsNone(state['reason'])
        self.assertGreater(state['rows']['chunks'], 0)
        self.assertGreater(state['rows']['manifests'], 1)
        self.assertEqual(wf.refreshes, 1)                  # X1: no full refresh before the put
        self.assertTrue(wf._published_identity['token_adopted'])
        self.assertEqual(fx.store.metadata(row['key']), row)

    def test_behaviour_identical_otherwise(self):
        # The same scenario with R2 only (today's composition) and with R2 + R3: same
        # published head, same candidate rows, same reference set, same logical seal; only
        # the number of full refreshes differs (1 with R3, 2 without).
        results = {}
        for seams in ('r2', 'r3'):
            fx = self.fixture(seams)
            row = fx.workflow.advance_spatial('s1', 'mesh')
            db = fx.store.candidate._db
            rows = db.execute('SELECT id,descriptor,codec,stored_sha,payload FROM chunks ORDER BY id').fetchall()
            manifests = db.execute('SELECT id,body,digest FROM snapshots ORDER BY id').fetchall()
            stats = fx.store.candidate.local_statistics()
            references = sorted(fx.store.candidate._references)
            refreshes = fx.workflow.refreshes
            entry = fx.store.seal_and_promote(row['key'])
            results[seams] = {'row': row, 'rows': rows, 'manifests': manifests, 'stats': stats,
                              'references': references, 'seal': entry.logical_seal,
                              'file_sha256': entry.file_sha256, 'refreshes': refreshes}
        a, b = results['r2'], results['r3']
        for name in ('row', 'rows', 'manifests', 'stats', 'references', 'seal', 'file_sha256'):
            self.assertEqual(a[name], b[name], name)
        self.assertEqual((a['refreshes'], b['refreshes']), (2, 1))

    def test_an_unreferenced_page_under_its_own_derived_key_is_harmless(self):
        # Contrast to the shadow tests: a page stored under the key segment_store derives
        # from its content is reached only through a locator whose digest is checked, and no
        # by-key read can name it, so the alias still reads as before and the token is kept.
        fx = self.fixture(alias=True)
        key = S.h('atlas.binding-page-key.v1', {'digest': S.h(S.PAGE_SCHEMA, EMPTY_PAGE)})
        fx.owner.intervene = lambda: fx.store.candidate.put_manifest(key, EMPTY_PAGE)
        fx.workflow.advance_spatial('s1', 'mesh')
        self.assertTrue(fx.workflow._r3_heat_checkpoint['token_kept'], fx.workflow._r3_heat_checkpoint)
        self.assertEqual(fx.workflow.refreshes, 1)
        self.assertEqual(lookup(fx.store, Fixture.ALIAS), ALIAS_VALUE)

    def test_two_intervals_in_sequence(self):
        # After R2 adopted its publication token the workflow is current again, so the next
        # interval's heat save keeps it too (one interval per process in production; G3).
        fx = self.fixture()
        wf = fx.workflow
        wf.advance_spatial('s1', 'mesh')
        wf.advance_spatial('s22', 'mesh')
        self.assertTrue(wf._r3_heat_checkpoint['token_kept'], wf._r3_heat_checkpoint)
        self.assertEqual(wf.refreshes, 1)


class FallbackTests(FixtureCase):
    """Every other case keeps today's behaviour: no token is set, the next _refresh is full."""

    def run_with(self, intervene=None, tamper=None, expect='', before=None, alias=False):
        fx = self.fixture(alias=alias)
        if before is not None:
            before(fx)
        fx.owner.intervene = None if intervene is None else (lambda: intervene(fx))
        fx.owner.tamper = tamper
        fx.workflow.advance_spatial('s1', 'mesh')
        state = fx.workflow._r3_heat_checkpoint
        self.assertFalse(state['token_kept'], state)
        self.assertIn(expect, state['reason'])
        self.assertEqual(fx.workflow.refreshes, 2)         # today's full refresh before the put
        return fx

    def test_another_put(self):
        def put(fx):
            fx.store.put(sha256(b'other-put').hexdigest(), {'x': np.ones(9)}, {'other': True})
        self.run_with(put, expect='a write other than the heat checkpoint')

    def test_a_raw_sidecar_manifest(self):
        def sidecar(fx):
            candidate = fx.store.candidate
            _, cid = candidate.put_chunk(S.canonical({'dtype': '|u1', 'count': 10}), bytes(range(10)))
            candidate.put_manifest(sha256(b'r3-sidecar').hexdigest(), {'schema': 'r3.fixture.native.v1'},
                                   arrays={'a': {'dtype': '|u1', 'shape': [10], 'chunks': [cid]}})
        self.run_with(sidecar, expect='a write other than the heat checkpoint')

    def test_a_page_row_under_a_derived_alias_key(self):
        # Refuter shadow probe (MEDIUM): an index-page-schema row under a chosen key that
        # shadows an interval-0 alias (the candidate is searched first). Today's full
        # restore would read the shadow; R3 must not keep the token.
        def shadow(fx):
            fx.store.candidate.put_manifest(Fixture.ALIAS, EMPTY_PAGE)
        fx = self.run_with(shadow, expect='a write other than the heat checkpoint', alias=True)
        self.assertNotEqual(lookup(fx.store, Fixture.ALIAS), ALIAS_VALUE)   # it does shadow

    def test_a_root_row_under_a_chosen_key_named_by_the_receipt(self):
        # The same shadow with a segment-root row: a copy of the field-payload root under
        # the alias key, named by the receipt. The step's own field root already exists (an
        # idempotent publish adds no row), so every new row is a page or a receipt root and
        # only the key derivation tells the planted root apart.
        fx = self.fixture(alias=True)
        fields = fx.owner._segment(fx.store.candidate, 'fields', np.linspace(0.0, 2.0, 3000))  # step 's1'
        planted = {}

        def plant():
            with fx.store.candidate.resolve_manifest(fields.root_key) as held:
                row = json.loads(held.value)['metadata']
            wire = fields.to_wire()
            wire['root_key']['snapshot_key'] = Fixture.ALIAS
            row['reference'] = planted['wire'] = wire
            fx.store.candidate.put_manifest(Fixture.ALIAS, row)

        def name_it(receipt):
            meta = dict(receipt['metadata'], field_payload=planted['wire'])
            return {'invocation': sha256(S.canonical(meta)).hexdigest(), 'metadata': meta}
        fx.owner.intervene, fx.owner.tamper = plant, name_it
        fx.workflow.advance_spatial('s1', 'mesh')
        state = fx.workflow._r3_heat_checkpoint
        self.assertFalse(state['token_kept'], state)
        self.assertIn('a write other than the heat checkpoint', state['reason'])
        self.assertEqual(state['rows']['manifests'], state['rows']['changes'] - state['rows']['chunks'])
        # Opening refresh after the pre-published field root, then today's full refresh.
        self.assertEqual(fx.workflow.refreshes, 3)
        self.assertNotEqual(lookup(fx.store, Fixture.ALIAS), ALIAS_VALUE)

    def test_another_segment_publication(self):
        def mesh(fx):
            fx.owner._segment(fx.store.candidate, 'mesh', np.full(700, 3.25))
        self.run_with(mesh, expect='a write other than the heat checkpoint')

    def test_a_catalog_change(self):
        # Another connection/process can change the catalog (promotion, quarantine): its file
        # token is part of the store token.
        def touch(fx):
            info = fx.catalog.stat()
            os.utime(fx.catalog, ns=(info.st_atime_ns, info.st_mtime_ns + 10**9))
        self.run_with(touch, expect='catalog or interval changed')

    def test_an_uncounted_change(self):
        def update(fx):
            fx.store.candidate._db.execute('UPDATE chunks SET codec=codec WHERE rowid=1')
        self.run_with(update, expect='not counted as inserted rows')

    def test_another_connection_cannot_write_the_candidate(self):
        # The candidate holds BEGIN IMMEDIATE for the whole interval, so a second connection
        # is refused; "another connection" can only reach the catalog (test above).
        fx = self.fixture()
        other = sqlite3.connect(fx.store.candidate.path, timeout=0, isolation_level=None)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                other.execute("INSERT INTO snapshots VALUES('x', x'00', 'y')")
        finally:
            other.close()

    def test_persisted_record_hash_mismatch(self):
        def other_reference(receipt):
            # Same root key, different produced identity: the persisted root does not bind it.
            meta = json.loads(json.dumps(receipt['metadata']))
            meta['ledger']['identity']['sha256'] = '0' * 64
            return {'invocation': sha256(S.canonical(meta)).hexdigest(), 'metadata': meta}
        self.run_with(tamper=other_reference, expect='persisted heat checkpoint root differs')

    def test_receipt_not_self_consistent(self):
        def bad_invocation(receipt):
            return dict(receipt, invocation='1' * 64)
        self.run_with(tamper=bad_invocation, expect='receipt is not the compact record')

    def test_tampered_persisted_root_bytes(self):
        def tamper_root(fx):
            fx.store.candidate._db.execute("UPDATE snapshots SET digest='0' WHERE rowid=(SELECT max(rowid) FROM snapshots)")
        self.run_with(tamper_root, expect='not counted as inserted rows')

    def test_root_outside_this_interval(self):
        holder = {}

        def foreign(receipt):
            # A well-formed reference to a segment of sealed interval 0 (the root snapshot).
            meta = json.loads(json.dumps(receipt['metadata']))
            meta['ledger'] = holder['fx'].store._alias(holder['fx'].root['key']).to_wire()
            return {'invocation': sha256(S.canonical(meta)).hexdigest(), 'metadata': meta}

        def remember(fx):
            holder['fx'] = fx
        self.run_with(intervene=None, tamper=foreign, expect='not in this interval', before=remember)

    def test_malformed_reference_falls_back(self):
        def malformed(receipt):
            meta = json.loads(json.dumps(receipt['metadata']))
            meta['ledger']['root_key']['interval'] = 0      # inconsistent wire: from_wire refuses
            return {'invocation': sha256(S.canonical(meta)).hexdigest(), 'metadata': meta}
        self.run_with(tamper=malformed, expect='check refused: ContractError')

    def test_workflow_not_current_or_not_compact(self):
        fx = self.fixture()
        wf = fx.workflow
        wf._token = None
        self.assertIsNone(wf._r3_write_mark())
        wf._refresh()
        self.assertIsNotNone(wf._r3_write_mark())
        stale = fx.module.CollarWorkflow(fx.store, fx.root, fx.owner, fx.budget)
        stale._token = ('stale',)
        self.assertIsNone(stale._r3_write_mark())
        native = fx.module.CollarWorkflow(SimpleNamespace(candidate=fx.store.candidate,
                                                          change_token=fx.store.change_token),
                                          fx.root, fx.owner, fx.budget)
        native._token = fx.store.change_token()
        self.assertIsNone(native._r3_write_mark())        # not the compact restart facade
        native._r3_after_heat_checkpoint(None, None)
        self.assertFalse(native._r3_heat_checkpoint['token_kept'])

    def test_heat_without_reference(self):
        fx = self.fixture()
        wf = fx.workflow
        mark = wf._r3_write_mark()
        fx.owner.heat('s1', 'mesh', boundary=None, cancel=None, execution=None, absolute_residual_target=None,
                      checkpoint_store=fx.store)
        token = wf._token
        wf._r3_after_heat_checkpoint(object(), mark)
        self.assertFalse(wf._r3_heat_checkpoint['token_kept'])
        self.assertIn('AttributeError', wf._r3_heat_checkpoint['reason'])
        self.assertEqual(wf._token, token)                 # unchanged (stale): full refresh next


class FreshRootTests(FixtureCase):
    """G-R3-7: under route (1) the IV1 parent is the fresh `kind: root`, sequence 0, read by its
    derived key candidate-first. The rule is the same; these pin it for that parent shape."""

    def test_fresh_root_parent_keeps_the_token_with_identical_results(self):
        results = {}
        for seams in ('r2', 'r3'):
            fx = self.fixture(seams, fresh=True)
            self.assertEqual(fx.store.metadata(Fixture.FRESH_ROOT), fx.root)
            row = fx.workflow.advance_spatial('s1', 'mesh')
            if seams == 'r3':
                self.assertTrue(fx.workflow._r3_heat_checkpoint['token_kept'], fx.workflow._r3_heat_checkpoint)
            refreshes = fx.workflow.refreshes
            entry = fx.store.seal_and_promote(row['key'])
            results[seams] = (row, entry.logical_seal, entry.file_sha256, refreshes)
        a, b = results['r2'], results['r3']
        self.assertEqual(a[:3], b[:3])
        self.assertEqual((a[3], b[3]), (2, 1))

    def test_a_shadow_under_the_fresh_root_key_falls_back(self):
        # A row in the candidate under the fresh root's own key: today's restore reads it
        # first and the store refuses it as an alias; R3 must not keep the token, so that
        # refusal comes from the full refresh rather than being skipped by a kept token.
        fx = self.fixture(fresh=True)
        fx.owner.intervene = lambda: fx.store.candidate.put_manifest(Fixture.FRESH_ROOT, EMPTY_PAGE)
        with self.assertRaisesRegex(ContractError, 'does not resolve to a bounded restart alias'):
            fx.workflow.advance_spatial('s1', 'mesh')
        state = fx.workflow._r3_heat_checkpoint
        self.assertFalse(state['token_kept'], state)
        self.assertIn('a write other than the heat checkpoint', state['reason'])
        self.assertNotEqual(lookup(fx.store, Fixture.FRESH_ROOT), fx.root)   # it does shadow


def live_stages(v2):
    """The live workflow stages between transform_v2 and R2 (the route (1) smoke tree's
    order): transform_v3 -> spatial records -> spatial validation -> compact restart (P)."""
    y3 = SWP.transform_v3(v2)
    records = SRP.transform(y3)
    validation = SVP.workflow_source(records)
    return y3, records, validation, CRP.workflow_source(validation)


def chain(text):
    """The Step 10 order: transform_v2 -> the live stages -> R2 -> R3, each authenticated.
    Returns (v2, P output, R2 output, R3 output)."""
    v2 = PWT.transform_v2(text)
    restart = live_stages(v2)[-1]
    r2 = T.transform(restart)
    return v2, restart, r2, H.transform(r2)


class TransformTests(unittest.TestCase):
    def test_composition_order_and_every_pin(self):
        native = NATIVE_I.read_text(encoding='utf8')
        rc1 = RC1.read_text(encoding='utf8')
        self.assertEqual(digest(native), I_INPUT)
        stage1 = WT.nonzero_cursor_source(native)
        self.assertEqual(digest(stage1), I_NONZERO)
        stage2 = SWP.transform(stage1)
        self.assertEqual(digest(stage2), I_SPATIAL)
        self.assertEqual(digest(stage2), PWT.WORKFLOW_INPUT_SHA256)
        stage3 = PWT.transform(stage2)
        self.assertEqual(stage3, rc1)
        self.assertEqual(digest(stage3), RC1_SHA)
        self.assertEqual(PWT.WORKFLOW_OUTPUT_SHA256, RC1_SHA)
        v2 = PWT.transform_v2(stage3)
        stages = live_stages(v2)
        self.assertEqual([digest(text) for text in (v2, *stages)],
                         [V2_OUTPUT, Y3_OUTPUT, RECORDS_OUTPUT, VALIDATION_OUTPUT, RESTART_OUTPUT])
        _, restart, r2, r3 = chain(stage3)
        self.assertEqual((digest(restart), digest(r2), digest(r3)), (RESTART_OUTPUT, R2_OUTPUT, R3_OUTPUT))
        self.assertEqual((T.PREDECESSOR, T.OUTPUT, H.PREDECESSOR, H.OUTPUT),
                         (RESTART_OUTPUT, R2_OUTPUT, R2_OUTPUT, R3_OUTPUT))
        print(f'\n[r3] chain {RC1_SHA[:8]} -> v2 {V2_OUTPUT[:8]} -> Y3/S/V/P {RESTART_OUTPUT[:8]} '
              f'-> R2 {R2_OUTPUT[:8]} -> R3 {R3_OUTPUT[:8]}')

    def test_every_other_order_is_refused(self):
        rc1 = RC1.read_text(encoding='utf8')
        v2, restart, r2, r3 = chain(rc1)
        refused = (
            (T.transform, rc1, T.TransformRefused),            # R2 before transform_v2
            (T.transform, v2, T.TransformRefused),             # R2 before the live stages
            (H.transform, rc1, H.TransformRefused),            # R3 straight on RC1
            (H.transform, v2, H.TransformRefused),             # R3 before R2
            (H.transform, restart, H.TransformRefused),        # R3 before R2, after the live stages
            (PWT.transform_v2, r2, PWT.PartitionWorkflowTransformRefused),   # v2 after R2
            (PWT.transform_v2, r3, PWT.PartitionWorkflowTransformRefused),
            (T.transform, r3, T.TransformRefused),             # R2 after R3
            (T.transform, r2, T.TransformRefused),             # R2 twice
            (H.transform, r3, H.TransformRefused),             # R3 twice
            (H.transform, r2 + '\n', H.TransformRefused))
        for entry, text, error in refused:
            with self.subTest(entry=entry.__module__ + '.' + entry.__name__, text=digest(text)[:8]), \
                    self.assertRaises(error):
                entry(text)
        with self.assertRaisesRegex(H.TransformRefused, 'requires the R2 stage'):
            H.apply_seams(v2)

    def check_output(self, before, after):
        """Compile + AST: only advance_spatial changed, three methods added, rest identical."""
        compile(after, 'integration_regional_workflow.py', 'exec')
        a, b = H.functions(ast.parse(before)), H.functions(ast.parse(after))
        self.assertEqual(set(b) - set(a), {'CollarWorkflow.' + n for n in NEW_METHODS})
        self.assertEqual({n for n in a if a[n] != b[n]}, {'CollarWorkflow.advance_spatial'})
        self.assertEqual(after.count('self._r3_write_mark()'), 1)
        self.assertEqual(after.count('self._r3_after_heat_checkpoint(heat, _r3_mark)'), 1)
        self.assertEqual(after.count('checkpoint_store=self._store)'), before.count('checkpoint_store=self._store)'))
        # The kept token is only ever set from the value the reason check returned.
        self.assertEqual(after.count('self._token = after'), 1)

    def test_rc1_chain_ast_and_compile(self):
        rc1 = RC1.read_text(encoding='utf8')
        _, _, r2, r3 = chain(rc1)
        self.check_output(r2, r3)

    def test_metadata_chain_checks_the_fresh_root_like_refresh(self):
        # G-R3-7: the chain walk R3's reason check calls (R2's _r2_metadata_chain) carries
        # RC1 _refresh's root-kind branch verbatim, so a fresh `kind: root` at sequence 0 is
        # accepted, and anything else refused, exactly as the full refresh does.
        rc1 = RC1.read_text(encoding='utf8')
        _, _, _, r3 = chain(rc1)
        tree = ast.parse(r3)
        methods = {node.name: ast.get_source_segment(r3, node)
                   for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name == 'CollarWorkflow'
                   for node in cls.body if isinstance(node, ast.FunctionDef)}
        branch = ("        if root.get('kind') == 'migrated-root':\n"
                  "            from workflow_transfer import verify_migrated_workflow\n"
                  "            verify_migrated_workflow(self)\n"
                  "            if root.get('migration') != self._migration.record() or base_sequence != self._migration.record()['sequence']:\n"
                  "                raise RegionalOwnerRefused('migration root is not its actual admitted base')\n"
                  "        elif root.get('kind') != 'root' or base_sequence != 0:\n"
                  "            raise RegionalOwnerRefused('ordinary root must retain sequence zero')\n")
        for name in ('_refresh', '_r2_metadata_chain'):
            with self.subTest(method=name):
                self.assertEqual(methods[name].count(branch), 1)

    def test_native_reference_through_test_only_seams(self):
        # Test-only, like R2: the same seams on I after R2's seams (never a production input).
        native = NATIVE_I.read_text(encoding='utf8')
        r2 = T.apply_seams(native)
        r3 = H.apply_seams(r2)
        self.check_output(r2, r3)
        self.assertEqual(digest(r3), I_R2_R3_TEST_ONLY)

    def test_seams_exactly_once(self):
        rc1 = RC1.read_text(encoding='utf8')
        _, _, r2, _ = chain(rc1)
        self.assertEqual(r2.count(H.HEAT_OLD), 1)
        renamed = H.PUBLISH_ANCHOR.replace('differential_interval=None,', 'differential_interval=None,  ')
        moved = H.HEAT_OLD.replace('checkpoint_store=self._store)', 'checkpoint_store=self._store )')
        for text, message in ((r2.replace(H.HEAT_OLD, moved), 'seam missing'),
                              (r2.replace(H.PUBLISH_ANCHOR, renamed), 'seam missing'),
                              (r2.replace(H.HEAT_OLD, H.HEAT_OLD + H.HEAT_OLD), 'ambiguous')):
            with self.subTest(message=message), self.assertRaisesRegex(H.TransformRefused, message):
                H.apply_seams(text)


if __name__ == '__main__':
    unittest.main()
