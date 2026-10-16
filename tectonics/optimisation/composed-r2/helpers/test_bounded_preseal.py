"""R2 option A tests (revision 3): bounded pre-seal checks and the publication-token rule.

Revision 3 (rebased on the live hotfix 7221c402): R2's input is transform_v2's output on
RC1 (D2); G8 keeps the hotfix's storage-delegated recomputation and adds the refusal of an
accumulator offered without the storage recomputation functions.
Revision 4 (coordinator-accepted Step 10 chain): R2's input is the live workflow stages'
output (RC1 -> transform_v2 -> transform_v3 -> spatial records -> spatial validation ->
compact_restart_patch); the transform tests follow that chain.

Small synthetic fixtures only. Run from a copy whose layout mirrors the-diadem-local-tasks-10
(this file sits in .../resumability-r1/compact-geometry-r1). Temporary stores go under
R/L/r2, where R is this file's parent folder (resumability-r1), unless R2T_TEMP names
another root; every test removes its own folder.
"""
import ast
import gc
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
R = HERE.parent
RUNTIME = HERE.parents[1] / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(HERE), str(RUNTIME), str(R)]
TEMP_ROOT = Path(os.environ.get('R2T_TEMP', str(R / 'L' / 'r2')))

import numpy as np
from atlas_tectonics import storage as NATIVE
from atlas_tectonics.resources import WorkBudget

# The two modules under R, loaded by name so each import block below holds modules of
# one folder only (the block order is then the same whatever Ruff counts as first-party).
B = importlib.import_module('bounded_preseal')
CRS = importlib.import_module('compact_restart_store')
CRP = importlib.import_module('compact_restart_patch')

import interval_store_set as ISS
import partition_store as PS
import partition_workflow_patch as PW
import partition_workflow_transform as PWT
import publication_token_transform as T
import segment_store as S
import spatial_indexed_patch as SI
import spatial_records_patch as SRP
import spatial_validation_patch as SVP
import spatial_workflow_patch as SWP
from compact_contracts import LogicalIdentity
from compact_store import V3_SCHEMA, CompactMeshStoreV3
from content_cache import ChargeSpec, OwnedStream, create_retained_scope

WF = 'a' * 64
PRODUCER, RUNTIME_ID = 'b' * 64, 'c' * 64
ROOT_KEY = sha256(b'r2-root').hexdigest()
HEAD_KEY = sha256(b'r2-head').hexdigest()
KINDS = ('state', 'exchange', 'graph', 'transport', 'heat')
ALL_KINDS = (*KINDS, 'certification', 'differential')
RC1 = R / 'composed-r1' / 'runtime-src' / 'atlas_tectonics' / 'integration_regional_workflow.py'
NATIVE_I = RUNTIME / 'atlas_tectonics' / 'integration_regional_workflow.py'
# Rev4 (Step 10 chain): R2 takes compact_restart_patch's output on RC1 -> transform_v2 ->
# transform_v3 -> spatial records -> spatial validation (pinned here independently of the
# module's own pins). Re-pin if RC1 or any of those stages changes before the freeze.
V2_OUTPUT = '834a1aa7603222d22ce8ca4aacaf3075b3e0446b16d95668251775dfb2738207'
RESTART_OUTPUT = 'db8505f67bf2dba1d722a87906823feab344a9f419cae34a7b71b66000225106'
CHAINED_OUTPUT = '4ef1894f29aa992ac3c89a0f3f04ddf8021d494b37a9cb3dcb3c463d9cb00538'
# Test-only: the native reference I text exercises the same seams; never a production stage.
NATIVE_I_INPUT = 'ddb8d1b20aab4898e8b3a3ed3a0242b4bec538b5f902beea8b32778ed27b007a'
NATIVE_I_OUTPUT = '86f62f8cde19d86d15acd4bd6070b5b1e12c32b3d859483c8de1bdb0052b9f4d'


def native_seam_transform(source):
    """Test-only entry point: the R2 seams on the native reference I text only."""
    if type(source) is not str or sha256(source.encode('utf8')).hexdigest() != NATIVE_I_INPUT:
        raise T.TransformRefused('test-only seam entry point accepts only the native reference I text')
    result = T.apply_seams(source)
    compile(result, 'integration_regional_workflow.py', 'exec')
    return result


def identity_of(stream):
    digest, size = sha256(), 0
    for block in stream:
        digest.update(block)
        size += len(block)
    return {'sha256': digest.hexdigest(), 'nbytes': size}


def fake_identities(_workflow, _head, descriptors):
    """A complete production identity set (record descriptors plus partition and mesh)."""
    result = {k: {'sha256': v['sha256'], 'nbytes': v['bytes']} for k, v in descriptors.items()}
    result['partition'] = {'sha256': 'e' * 64, 'nbytes': 11}
    result['mesh'] = {'sha256': 'f' * 64, 'nbytes': 12}
    return result


class Source:
    """One typed array streamed in owned blocks (as the production sources do)."""
    def __init__(self, scope, name, values):
        self.scope, self.raw = scope, np.ascontiguousarray(values).tobytes()
        self.info = S.ArrayInfo(name, values.dtype.str, tuple(values.shape), len(self.raw))

    def blocks(self, *, max_owned_bytes):
        def generate():
            for start in range(0, len(self.raw), max_owned_bytes):
                part = self.raw[start:start + max_owned_bytes]
                yield self.scope.reserve(ChargeSpec('r2-fixture-input', len(part))).commit(part)
        return OwnedStream(generate(), scope=self.scope)


class Fixture:
    """Sealed interval 0 (migrated root) + unsealed interval 1 with a bundle and a head."""
    def __init__(self, folder):
        self.budget = WorkBudget(768 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='r2-preseal-tests')
        catalog = Path(folder) / 'interval-catalog.json'
        self.store = CRS.CompactRestartStore.create_migration(catalog, workflow_id=WF, scope=self.scope,
            producer_identity=PRODUCER, runtime_identity=RUNTIME_ID)
        self.root = {'key': ROOT_KEY, 'kind': 'migrated-root', 'sequence': 1, 'workflow_id': WF,
                     'funding_id': 'f1', 'state': {'fields': {'time_s': 1.0}}}
        self.store.put(ROOT_KEY, {'shared': np.arange(9000, dtype='<f8'), 'root-only': np.ones(7)}, self.root)
        self.store.seal_and_promote(ROOT_KEY)
        self.store.start_next_interval(producer_identity=PRODUCER, runtime_identity=RUNTIME_ID)
        candidate = self.store.candidate
        # A bundle-like compact record: its first 64 KiB chunk equals interval 0's first
        # 'shared' chunk, so one leaf is owned by the sealed ancestor (reference closure).
        column = np.concatenate([np.arange(8192, dtype='<f8'), np.full(300, 2.5)])
        self.records = {k: {'bytes': 100 + i, 'sha256': sha256(k.encode()).hexdigest()}
                        for i, k in enumerate(ALL_KINDS)}
        metadata = S.canonical({'schema': B.BUNDLE_SCHEMA, 'codec': {}, 'records': self.records})
        identity = LogicalIdentity(B.BUNDLE_SCHEMA, sha256(b'bundle').hexdigest(), 4242)
        self.bundle = S.SegmentBackend().publish(candidate, record_schema=B.BUNDLE_SCHEMA, identity=identity,
            metadata=metadata, arrays=lambda: iter([Source(self.scope, 'col', column)]), producer='d' * 64,
            representation_profile='atlas.r2-fixture.v1', scope=self.scope)
        # A plain native manifest with local chunk references (raw sidecar style).
        raw = bytes(range(10))
        desc = S.canonical({'dtype': '|u1', 'count': 10})
        _, cid = candidate.put_chunk(desc, raw)
        candidate.put_manifest(sha256(b'r2-plain').hexdigest(), {'schema': 'r2.fixture.native.v1'},
                               arrays={'a': {'dtype': '|u1', 'shape': [10], 'chunks': [cid]}})

        def blob(kind):
            compact = {'schema': B.REFERENCE_SCHEMA, 'segment': self.bundle.to_wire(), 'field': kind}
            return dict(self.records[kind], compact=compact)
        self.head = {'schema': 'atlas.collar-workflow.fixture', 'key': HEAD_KEY, 'kind': 'successor',
                     'sequence': 2, 'workflow_id': WF, 'funding_id': 'f1', 'parent_key': ROOT_KEY,
                     'parent_digest': B.workflow_hash(self.root), 'state': {'fields': {'time_s': 2.0}},
                     'exterior_state': {'record_blobs': {'state': blob('state')}},
                     'exterior_advance': {'record_blobs': {k: blob(k) for k in KINDS[1:]}},
                     'differential_certification': {'record_blob': blob('certification')},
                     'differential_geometry': {'record_blob': blob('differential')}, 'shape': [2, 3]}
        self.production = B.workflow_hash(self.head)
        self.store.put(HEAD_KEY, {'collar': np.linspace(0.0, 1.0, 50), 'spatial-audit:x': np.zeros(3)}, self.head)
        self.links = {'parent_key': ROOT_KEY, 'parent_sha256': B.workflow_hash(self.root),
                      'root_key': ROOT_KEY, 'root_sha256': B.workflow_hash(self.root)}

    def check(self, **overrides):
        kwargs = {'head_key': HEAD_KEY, 'budget': self.budget, 'production_head_sha256': self.production,
                  'links': self.links}
        kwargs.update(overrides)
        return B.check_candidate(self.store, **kwargs)

    def close(self):
        self.store.close()


class FixtureCase(unittest.TestCase):
    prefix = 'r2-preseal-'

    def setUp(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix=self.prefix, dir=TEMP_ROOT)
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(TEMP_ROOT.resolve()))
        self.fx = Fixture(self.temp.name)

    def tearDown(self):
        self.fx.close()
        self.temp.cleanup()


class BoundedPresealTests(FixtureCase):
    # (a) clean interval
    def test_clean_interval_passes_with_bounded_evidence(self):
        token = self.fx.store.change_token()
        evidence = self.fx.check()
        stats = self.fx.store.candidate.local_statistics()
        self.assertEqual(evidence['schema'], 'atlas.r2-bounded-preseal.v2')
        self.assertEqual(evidence['chunks_read_and_hashed'], stats['local_chunks'])
        self.assertEqual(evidence['encoded_payload_bytes_hashed'], stats['encoded_payload_bytes'])
        self.assertEqual(evidence['manifests'], stats['manifests'])
        self.assertEqual((evidence['decoded_chunks'], evidence['whole_record_exports']), (0, 0))
        # The merged storage keeps the G8 accumulator, so the real comparison runs and passes.
        self.assertEqual(evidence['chunk_binding'], 'storage-accumulator')
        self.assertEqual(evidence['aliases'], 1)
        self.assertEqual(evidence['native'], 1)
        self.assertGreaterEqual(evidence['roots'], 2)
        self.assertEqual(evidence['record_bindings'], dict.fromkeys(ALL_KINDS, 'bundle'))
        self.assertEqual(evidence['head_array_names'], ['collar', 'spatial-audit:x'])
        self.assertEqual(self.fx.store.change_token(), token)
        self.assertIn(0, self.fx.store.candidate._references)
        # The candidate is still sealable after the check.
        self.fx.store.seal_and_promote(HEAD_KEY)

    # (b) refusals
    def test_tampered_chunk_byte_is_refused_by_read_and_hash(self):
        db = self.fx.store.candidate._db
        cid, payload = db.execute('SELECT id,payload FROM chunks ORDER BY id LIMIT 1').fetchone()
        flipped = bytes([payload[0] ^ 1]) + payload[1:]
        db.execute('UPDATE chunks SET payload=? WHERE id=?', (flipped, cid))
        with self.assertRaisesRegex(B.PresealRefused, 'read-and-hash'):
            self.fx.check()

    def test_tampered_manifest_digest_is_refused(self):
        db = self.fx.store.candidate._db
        key = db.execute('SELECT id FROM snapshots ORDER BY id LIMIT 1').fetchone()[0]
        db.execute('UPDATE snapshots SET digest=? WHERE id=?', ('0' * 64, key))
        # The native validator inside resolve_manifest already checks the digest column
        # (storage.py:709-711); the bounded check repeats it explicitly.
        with self.assertRaisesRegex((B.PresealRefused, NATIVE.StoreError), 'checksum mismatch|stored digest'):
            self.fx.check()

    def test_wrong_production_head_identity_is_refused(self):
        with self.assertRaisesRegex(B.PresealRefused, 'produced in this process'):
            self.fx.check(production_head_sha256='f' * 64)

    def test_foreign_record_identity_is_refused(self):
        descriptors = B.head_record_descriptors(self.fx.head)
        descriptors['graph'] = dict(descriptors['graph'], sha256='9' * 64)
        with self.assertRaisesRegex(B.PresealRefused, 'bundle index: graph'):
            self.fx.check(record_descriptors=descriptors)
        wanted = {k: {'sha256': v['sha256'], 'nbytes': v['bytes']} for k, v in self.fx.records.items()}
        wanted['heat'] = dict(wanted['heat'], nbytes=1)
        with self.assertRaisesRegex(B.PresealRefused, 'computed at production: heat'):
            self.fx.check(production_records=wanted)

    def test_broken_head_parent_root_links_are_refused(self):
        for change, message in (({'parent_key': HEAD_KEY}, 'head/parent link'),
                                ({'parent_sha256': '0' * 64}, 'head/parent link'),
                                ({'root_sha256': '0' * 64}, 'parent or root differs')):
            with self.subTest(change=change), self.assertRaisesRegex(B.PresealRefused, message):
                self.fx.check(links=dict(self.fx.links, **change))

    def test_head_not_written_in_this_interval_is_refused(self):
        with self.assertRaisesRegex(B.PresealRefused, 'not a record written in this interval'):
            self.fx.check(head_key=ROOT_KEY)

    @unittest.skipUnless(hasattr(CRS, 'EXTERNAL_PROFILE'), 'store without externalised root metadata')
    def test_externalised_root_metadata_alias_is_refused_not_decoded(self):
        # Store route (1): an oversized root-kind row keeps 'funding' in a compact record that
        # only a decoding read rebuilds. A successor interval writes none; refuse, never decode.
        key = sha256(b'r2-external-root').hexdigest()
        self.fx.store.put(key, {'a': np.zeros(3)}, {'key': key, 'kind': 'migrated-root', 'workflow_id': WF,
                                                    'funding': 'x' * 70000})
        with patch.object(CRS.CompactRestartStore, '_external_field', side_effect=AssertionError('decoded')), \
                self.assertRaisesRegex(B.PresealRefused, 'externalised root metadata'):
            self.fx.check()

    def test_head_record_descriptors_require_every_successor_header(self):
        # Fix 4: the same complete selection as endpoint_record_identities (RO 242-252).
        self.assertEqual(set(B.head_record_descriptors(self.fx.head)), set(ALL_KINDS))
        for missing in ('differential_certification', 'differential_geometry', 'exterior_advance'):
            head = {k: v for k, v in self.fx.head.items() if k != missing}
            with self.subTest(missing=missing), self.assertRaisesRegex(B.PresealRefused, 'record headers required'):
                B.head_record_descriptors(head)
        with self.assertRaisesRegex(B.PresealRefused, 'successor head required'):
            B.head_record_descriptors(dict(self.fx.head, kind='migrated-root'))

    # (c) no per-scalar decode and no whole-record export
    def test_no_decode_and_no_export_paths_are_touched(self):
        def forbid(name):
            def refuse(*_args, **_kwargs):
                raise AssertionError('forbidden during bounded pre-seal: ' + name)
            return refuse
        targets = [(ISS.UnlistedCandidate, 'resolve_chunk'), (ISS.IntervalStoreSet, 'resolve_chunk'),
                   (ISS.ReadOnlyNative, 'chunk'), (NATIVE.ArrayStore, '_decode'),
                   (S.SegmentView, 'read'), (S.SegmentView, 'scan'), (S.SegmentView, 'iter'),
                   (CRS.CompactRestartStore, 'read_chunk'), (CRS.CompactRestartStore, 'iter_chunks')]
        optional = {'record_views': ('CompactRecord.from_segment', 'LogicalExchange.from_records'),
                    'spatial_records_patch': ('open_records', 'export_record', 'restore_records',
                                              'restore_certification', 'restore_differential'),
                    'partition_workflow_patch': ('restore',),
                    'private_heat_snapshot_store_r4': ()}
        patched_optional = []
        for module_name, names in optional.items():
            try:
                module = importlib.import_module(module_name)
            except ImportError as error:      # heavy modules: reported, lower layers still patched
                patched_optional.append((module_name, 'not importable: ' + type(error).__name__))
                continue
            if module_name == 'private_heat_snapshot_store_r4':
                names = tuple(n for n in dir(module) if n.startswith(('restore', 'open', 'load')) and
                              callable(getattr(module, n)))
            for dotted in names:
                owner, attr = module, dotted
                if '.' in dotted:
                    cls, attr = dotted.split('.')
                    owner = getattr(module, cls)
                targets.append((owner, attr))
                patched_optional.append((module_name, dotted))
        with ExitStack() as stack:
            for owner, attr in targets:
                stack.enter_context(patch.object(owner, attr, forbid(f'{getattr(owner, "__name__", owner)}.{attr}')))
            evidence = self.fx.check()
            with self.assertRaisesRegex(AssertionError, 'forbidden'):
                self.fx.store.get(HEAD_KEY)      # the patches do intercept a decoding read
        self.assertEqual(evidence['decoded_chunks'], 0)
        print('\n[r2] optional decode/export patches:', patched_optional)

    def test_cancellation_is_honoured(self):
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) > 1
        with self.assertRaisesRegex(B.PresealRefused, 'cancelled'):
            self.fx.check(cancel=cancel, check_every=1)
        self.assertEqual(len(calls), 2)

    def test_array_inventory_names_only(self):
        names = ['collar', 'exterior-fv:t', 'spatial-audit:x', 'partition-record:p']
        self.assertEqual(B.array_inventory(names, exterior=True, spatial=True, differential=True), sorted(names))
        with self.assertRaisesRegex(B.PresealRefused, 'unowned differential partition'):
            B.array_inventory(names, exterior=True, spatial=True, differential=False)
        with self.assertRaisesRegex(B.PresealRefused, 'unowned exterior arrays'):
            B.array_inventory(names, exterior=False, spatial=True, differential=True)


class ChunkBindingTests(FixtureCase):
    """Gap G8: the row hash does not cover the chunk id; an optional storage-side
    accumulator closes it before the seal, the fresh reader's decode closes it after."""
    prefix = 'r2-binding-'

    @staticmethod
    def without_accumulator():
        """A store that predates G8: the candidate offers no accumulator."""
        return patch.object(ISS.UnlistedCandidate, B.CHUNK_BINDING_API, None)

    def add_twin(self):
        """A second local chunk row with the descriptor of the head's collar chunk."""
        store = self.fx.store
        cid = store._manifest(HEAD_KEY)['arrays']['collar']['chunks'][0]
        descriptor = store.candidate._db.execute('SELECT descriptor FROM chunks WHERE id=?', (cid,)).fetchone()[0]
        _, other = store.candidate.put_chunk(descriptor, np.linspace(5.0, 6.0, 50).astype('<f8').tobytes())
        return cid, other

    def swap(self, cid, other):
        """Swap (codec, stored_sha, payload) between the two same-descriptor rows."""
        db = self.fx.store.candidate._db
        first = db.execute('SELECT codec,stored_sha,payload FROM chunks WHERE id=?', (cid,)).fetchone()
        second = db.execute('SELECT codec,stored_sha,payload FROM chunks WHERE id=?', (other,)).fetchone()
        db.execute('UPDATE chunks SET codec=?,stored_sha=?,payload=? WHERE id=?', (*second, cid))
        db.execute('UPDATE chunks SET codec=?,stored_sha=?,payload=? WHERE id=?', (*first, other))

    def test_swap_passes_without_accumulator_and_a_decoding_read_refuses(self):
        self.swap(*self.add_twin())
        with self.without_accumulator():                 # a store without G8: not caught before the seal
            evidence = self.fx.check()
        self.assertEqual(evidence['chunk_binding'], B.CHUNK_BINDING_ABSENT)
        # What the fresh reader's decode refuses. The store's read path closes its segment
        # view while the refusal still holds a borrow, so the checksum refusal may arrive
        # as the context of a RuntimeError('owner has live child borrows').
        with self.assertRaises((ValueError, RuntimeError)) as caught:
            self.fx.store.get(HEAD_KEY)
        chain, error = [], caught.exception
        while error is not None:
            chain.append(str(error))
            error = error.__context__
        self.assertTrue(any('typed chunk checksum mismatch' in text for text in chain), chain)

    def test_helpers_are_the_storage_functions(self):
        """bounded_preseal keeps no private formula: its binding equals the storage accumulator."""
        candidate = self.fx.store.candidate
        rows = candidate._db.execute('SELECT id,stored_sha FROM chunks').fetchall()
        mine = B.chunk_binding_digest(sum(B.chunk_binding_term(cid, stored) for cid, stored in rows), len(rows))
        self.assertEqual(mine, candidate.local_chunk_binding_digest())
        self.assertEqual(mine, candidate.recompute_local_chunk_binding_digest())
        self.assertIs(type(mine), str)

    def test_real_accumulator_passes_a_clean_interval(self):
        cid, other = self.add_twin()                     # a real put_chunk updates the real accumulator
        self.assertNotEqual(cid, other)
        self.assertEqual(self.fx.check()['chunk_binding'], 'storage-accumulator')

    def test_real_accumulator_refuses_an_id_content_swap(self):
        cid, other = self.add_twin()
        self.swap(cid, other)                            # row hashes and counters still agree
        with self.assertRaisesRegex(B.PresealRefused, 'id/content binding'):
            self.fx.check()

    def test_accumulator_without_its_recomputation_is_refused(self):
        # Rev3 rule on the hotfix route: this module recomputes the binding with the storage
        # layer's own term and digest functions; an accumulator offered without them is
        # refused (PresealRefused), never trusted and never an AttributeError mid-loop.
        self.assertTrue(all(callable(getattr(ISS, name)) for name in B.CHUNK_BINDING_RECOMPUTE_FUNCTIONS))
        for name in B.CHUNK_BINDING_RECOMPUTE_FUNCTIONS:
            with self.subTest(missing=name), patch.object(ISS, name, None), \
                    self.assertRaisesRegex(B.PresealRefused, 'without its recomputation'):
                self.fx.check()
        with patch.object(ISS.UnlistedCandidate, B.CHUNK_BINDING_API, 'not callable'), \
                self.assertRaisesRegex(B.PresealRefused, 'without its recomputation'):
            self.fx.check()
        self.assertEqual(self.fx.check()['chunk_binding'], 'storage-accumulator')


class WrapperTests(FixtureCase):
    """bounded_preseal() with a fake workflow: the runner-level composition."""
    prefix = 'r2-wrapper-'

    def setUp(self):
        super().setUp()
        fx = self.fx
        self.workflow = SimpleNamespace(
            _published_identity={'key': HEAD_KEY, 'sha256': fx.production, 'token_adopted': True},
            _r2_metadata_chain=lambda: fx.store.metadata(HEAD_KEY), _root=json.dumps(fx.root),
            _exterior_owner=object(), _is_spatial=lambda: True, _is_differential=lambda: False)
        self.verified = []
        self.kwargs = {'store': fx.store, 'before': {'head': ROOT_KEY}, 'after': {'head': HEAD_KEY},
                       'budget': fx.budget,
                       'verify_references': lambda store, head, **kw: self.verified.append(head['key']),
                       'live_identities': fake_identities}

    def test_wrapper_passes_and_reports_adoption(self):
        evidence = B.bounded_preseal(self.workflow, **self.kwargs)
        self.assertTrue(evidence['token_adopted'])
        self.assertEqual(set(evidence['record_identities']), {*ALL_KINDS, 'partition', 'mesh'})
        self.assertEqual(self.verified, [HEAD_KEY])

    def test_wrapper_refuses_missing_transform_or_wrong_chain(self):
        missing = SimpleNamespace(**dict(vars(self.workflow), _published_identity=None))
        with self.assertRaisesRegex(B.PresealRefused, 'R2 transform not composed'):
            B.bounded_preseal(missing, **self.kwargs)
        wrong = SimpleNamespace(**dict(vars(self.workflow), _r2_metadata_chain=lambda: self.fx.root))
        with self.assertRaisesRegex(B.PresealRefused, 'metadata chain'):
            B.bounded_preseal(wrong, **self.kwargs)
        closed = SimpleNamespace(**dict(vars(self.workflow), _is_spatial=lambda: False))
        with self.assertRaisesRegex(B.PresealRefused, 'unowned spatial'):
            B.bounded_preseal(closed, **self.kwargs)

    def test_wrapper_closes_production_identities_like_the_reader(self):
        # Fix 4: reader.canonical_record_identities(successor=True) on what is recorded.
        for drop in ('mesh', 'partition', 'certification'):
            def partial(workflow, head, descriptors, drop=drop):
                result = fake_identities(workflow, head, descriptors)
                del result[drop]
                return result
            with self.subTest(drop=drop), self.assertRaisesRegex(B.PresealRefused, 'identities are incomplete'):
                B.bounded_preseal(self.workflow, **dict(self.kwargs, live_identities=partial))

        def zero(workflow, head, descriptors):
            return dict(fake_identities(workflow, head, descriptors), mesh={'sha256': 'f' * 64, 'nbytes': 0})
        with self.assertRaisesRegex(B.PresealRefused, 'identities are incomplete'):
            B.bounded_preseal(self.workflow, **dict(self.kwargs, live_identities=zero))


class ProductionIdentityTests(FixtureCase):
    """Fix 1: partition and mesh production identities come from the head, never from a
    live stream; they equal the streams the fresh reader recomputes."""
    prefix = 'r2-identity-'

    def setUp(self):
        super().setUp()
        from test_mesh_v3 import fixture as mesh_fixture
        fx = self.fx
        candidate = fx.store.candidate
        self.mesh, _, source, self.view, self.partition_ref = mesh_fixture(fx.scope, candidate)
        self.adapter = CompactMeshStoreV3(candidate, scope=fx.scope, support_source=source)
        self.mesh_ref = self.adapter.publish(self.mesh, producer='b' * 64)
        header = dict(PW.compact_header(self.view, {}, self.partition_ref.to_wire()))
        mesh_reference = {'schema': V3_SCHEMA, 'segment': self.mesh_ref.to_wire(),
                          'geometry_id': self.mesh.geometry_id, 'source_producer': {'fixture': 'r2'}}
        self.head = dict(fx.head, differential_partition=header,
                         exterior_state=dict(fx.head['exterior_state'], compact_mesh=mesh_reference))

    def tearDown(self):
        # Views and the support source go before the store and its files close.
        del self.mesh, self.view, self.adapter, self.mesh_ref, self.partition_ref, self.head
        gc.collect()
        super().tearDown()

    @staticmethod
    def workflow(mesh):
        """Only exterior_state exists: any read of the live partition would raise."""
        held = SimpleNamespace(value={'thermal_mesh': mesh})
        return SimpleNamespace(exterior_state=SimpleNamespace(indexed_record=lambda: held))

    def identities(self, mesh, head=None):
        head = self.head if head is None else head
        return B.production_record_identities(self.workflow(mesh), head, B.head_record_descriptors(head))

    def sealed(self):
        """Seal the interval and return its sealed resolver, as the fresh reader reads it."""
        self.fx.store.seal_and_promote(HEAD_KEY)
        return self.fx.store.store_set

    def test_partition_identity_equals_descriptor_stats_fresh_and_reopened(self):
        found = self.identities(self.mesh)
        self.assertEqual(found['partition'], PW.descriptor_stats(self.view))
        reopened = PS.open_partition_v2(self.sealed(), self.partition_ref, scope=self.fx.scope)
        self.assertEqual(found['partition'], PW.descriptor_stats(reopened))
        reopened.close()

    def test_mesh_identity_equals_the_logical_stream_fresh_and_reopened(self):
        found = self.identities(self.mesh)
        self.assertEqual(found['mesh'], identity_of(SI.iter_logical_json(self.mesh)))
        sealed = CompactMeshStoreV3(self.sealed(), scope=self.fx.scope)
        reopened = sealed.open(self.mesh_ref, expected_geometry_id=self.mesh.geometry_id)
        self.assertEqual(found['mesh'], identity_of(SI.iter_logical_json(reopened)))

    def test_candidate_backed_live_mesh_is_not_read(self):
        # A fresh mesh is reopened from the interval resolver (differential_mesh_patch.produce),
        # so its pages are candidate pages; production identities must not touch them (G5).
        reopened = self.adapter.open(self.mesh_ref, expected_geometry_id=self.mesh.geometry_id)
        expected = identity_of(SI.iter_logical_json(reopened))

        def refuse(*_args, **_kwargs):
            raise AssertionError('candidate read during production identities')
        with patch.object(ISS.UnlistedCandidate, 'resolve_chunk', refuse), \
                patch.object(ISS.UnlistedCandidate, 'resolve_manifest', refuse):
            found = self.identities(reopened)
        self.assertEqual(found['mesh'], expected)

    def test_refusals(self):
        legacy = dict(self.head['differential_partition'], record_blobs={'partition': {}})
        foreign = dict(self.head['differential_partition'], compact_partition=self.mesh_ref.to_wire())
        for header, message in ((legacy, 'compact v2 partition header'),
                                (foreign, 'partition v2 descriptor identity')):
            with self.subTest(message=message), self.assertRaisesRegex(B.PresealRefused, message):
                self.identities(self.mesh, dict(self.head, differential_partition=header))
        mesh_reference = dict(self.head['exterior_state']['compact_mesh'], geometry_id='0' * 64)
        head = dict(self.head, exterior_state=dict(self.head['exterior_state'], compact_mesh=mesh_reference))
        with self.assertRaisesRegex(B.PresealRefused, 'identity differs from its geometry'):
            self.identities(self.mesh, head)
        with self.assertRaisesRegex(B.PresealRefused, 'live compact mesh differs'):
            self.identities(object())


# (d) token adoption rule: fixture-level model built by the SAME seam function.
MINI = '''import hashlib
import json


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


class StoreConflict(Exception):
    pass


class RegionalOwnerRefused(Exception):
    pass


class Mini:
    def __init__(self, store, root):
        self._store, self._root = store, json.dumps(root)
        self._head, self._state, self._token = root, 'root-state', None
        self._initial_current_geometry = 'root-geometry'
        self.refreshes = 0

    def _verify(self):
        pass

    def _refresh(self):
        self._verify()
        token = self._store.change_token()
        if token == self._token:
            return
        root = json.loads(self._root)
        if self._store.metadata(root['key']) != root:
            raise RegionalOwnerRefused('funded collar root changed')
        previous, accepted_parent = root, None
        while True:
            current = self._store.metadata('succ:' + previous['key'])
            if current is None:
                break
            if current['parent_digest'] != _hash(previous):
                raise RegionalOwnerRefused('funded collar chain changed or is out of order')
            accepted_parent, previous = previous, current
        self.refreshes += 1
        self._head, self._state, self._token = previous, 'restored-state', token
        self._initial_current_geometry = None

    def inspect(self):
        self._refresh()
        return self._head['key']

    def publish(self, result):
        self._refresh()
        parent = self._head
        row = dict(key='succ:' + parent['key'], parent_digest=_hash(parent), shape=(2, 3))

        def check():
            self._verify()
            root = json.loads(self._root)
            if self._store.metadata(parent['key']) != parent or self._store.metadata(root['key']) != root:
                raise StoreConflict('funded collar parent/admission changed before publication')

        self._store.put(row['key'], row, publication_check=check)
        self._head, self._state, self._token = row, result.state, None
        return row
'''


class FakeStore:
    """(data_version, total_changes) like ArrayStore; hooks model other writers."""
    def __init__(self, root):
        self.rows, self.version, self.changes = {root['key']: json.dumps(root)}, 0, 0
        self.write_in_txn_after_check = self.other_commit_after = self.double_check = False
        self.alter_persisted = False

    def change_token(self):
        return (self.version, self.changes)

    def metadata(self, key):
        raw = self.rows.get(key)
        return None if raw is None else json.loads(raw)

    def put(self, key, row, *, publication_check):
        stored = dict(row, altered=True) if self.alter_persisted else row
        self.rows[key] = json.dumps(stored)
        self.changes += 1
        publication_check()
        if self.double_check:
            publication_check()
        if self.write_in_txn_after_check:
            self.rows['other'] = '{}'
            self.changes += 1
        # COMMIT: our own commit leaves data_version unchanged.
        if self.other_commit_after:
            self.version += 1


class TokenAdoptionModelTests(unittest.TestCase):
    def setUp(self):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='r2-model-', dir=TEMP_ROOT)
        self.loaded = 0

    def tearDown(self):
        self.temp.cleanup()

    def load_model(self):
        """The seamed model text written as a module file and imported like composed code."""
        self.loaded += 1
        path = Path(self.temp.name) / f'r2_mini_workflow_{self.loaded}.py'
        path.write_text(T.apply_seams(MINI), encoding='utf8')
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def make(self, **flags):
        root = {'key': 'root'}
        store = FakeStore(root)
        for name, value in flags.items():
            setattr(store, name, value)
        workflow = self.load_model().Mini(store, root)
        workflow.inspect()
        self.assertEqual(workflow.refreshes, 1)
        return workflow, store

    def test_adopts_in_transaction_token_when_nothing_intervened(self):
        workflow, store = self.make()
        row = workflow.publish(SimpleNamespace(state='live-state'))
        self.assertEqual(workflow._token, store.change_token())
        self.assertTrue(workflow._published_identity['token_adopted'])
        self.assertEqual(workflow._head, store.metadata(row['key']))      # persisted form adopted
        self.assertIsNot(workflow._head, row)
        self.assertEqual(workflow._state, 'live-state')
        self.assertIsNone(workflow._initial_current_geometry)
        workflow.inspect()
        self.assertEqual(workflow.refreshes, 1)                            # no full refresh
        # The tuple in the live row would have failed the next parent comparison; the
        # adopted persisted head passes it (why the head, not the row, is adopted).
        self.assertNotEqual(store.metadata(row['key']), row)
        workflow.publish(SimpleNamespace(state='live-2'))
        self.assertEqual(workflow.refreshes, 1)

    def test_falls_back_to_full_refresh_when_a_write_intervened(self):
        for flag in ('other_commit_after', 'write_in_txn_after_check', 'double_check', 'alter_persisted'):
            with self.subTest(flag=flag):
                workflow = self.make(**{flag: True})[0]
                workflow.publish(SimpleNamespace(state='live-state'))
                self.assertIsNone(workflow._token)
                self.assertFalse(workflow._published_identity['token_adopted'])
                if flag != 'alter_persisted':
                    workflow.inspect()
                    self.assertEqual(workflow.refreshes, 2)                # today's full _refresh
                    self.assertEqual(workflow._state, 'restored-state')

    def test_rule_never_sets_a_token_after_the_fact(self):
        workflow, store = self.make(other_commit_after=True)
        workflow.publish(SimpleNamespace(state='live-state'))
        self.assertIsNone(workflow._token)                                  # not the post-commit token
        self.assertNotEqual(store.change_token(), (0, 1))


def chain_stages():
    """Rev4: RC1 -> transform_v2 -> transform_v3 -> spatial records -> spatial validation ->
    compact_restart_patch (P); P's output is the one accepted R2 input."""
    v2 = PWT.transform_v2(RC1.read_text(encoding='utf8'))
    y3 = SWP.transform_v3(v2)
    records = SRP.transform(y3)
    validation = SVP.workflow_source(records)
    return v2, y3, records, validation, CRP.workflow_source(validation)


def chained_input():
    return chain_stages()[-1]


class TransformTests(unittest.TestCase):
    def _check(self, path, entry, expected_output, source=None):
        source = path.read_text(encoding='utf8') if source is None else source
        result = entry(source)
        tree = ast.parse(result)
        collar = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and
                      any(isinstance(f, ast.FunctionDef) and f.name == '_r2_metadata_chain' for f in node.body))
        methods = {f.name: f for f in collar.body if isinstance(f, ast.FunctionDef)}
        chain, refresh = methods['_r2_metadata_chain'], methods['_refresh']
        body = chain.body[2:-1]           # docstring, self._verify() ... return previous
        self.assertEqual([ast.dump(s) for s in body], [ast.dump(s) for s in refresh.body[3:3 + len(body)]])
        self.assertEqual(ast.dump(chain.body[1]), ast.dump(refresh.body[0]))
        self.assertEqual(result.count('_r2_tokens.append(self._store.change_token())'), 1)
        self.assertEqual(result.count('row, result.state, None'), 1)
        with self.assertRaises(T.TransformRefused):
            entry(result)
        with self.assertRaises(T.TransformRefused):
            entry(source + '\n')
        self.assertEqual(sha256(result.encode('utf8')).hexdigest(), expected_output)
        print(f'\n[r2] {path.name} {sha256(source.encode()).hexdigest()[:12]} -> output sha256 {expected_output}')

    def test_rc1_composed_workflow_after_the_live_stages(self):
        # Rev4: the seams on the chained text RC1 -> transform_v2 -> ... -> P.
        stages = chain_stages()
        self.assertEqual(sha256(stages[0].encode('utf8')).hexdigest(), V2_OUTPUT)
        source = stages[-1]
        self.assertEqual(sha256(source.encode('utf8')).hexdigest(), RESTART_OUTPUT)
        self._check(RC1, T.transform, CHAINED_OUTPUT, source=source)

    def test_native_reference_seams_through_the_test_only_entry(self):
        self._check(NATIVE_I, native_seam_transform, NATIVE_I_OUTPUT)

    def test_production_transform_accepts_only_the_pinned_chained_text(self):
        # Fix 5 + rev4: neither I, RC1 nor any earlier stage's text is a production
        # predecessor; only P's output on the Step 10 chain is. The test-only entry takes
        # nothing but I.
        rc1, native = RC1.read_text(encoding='utf8'), NATIVE_I.read_text(encoding='utf8')
        self.assertEqual(sha256(rc1.encode('utf8')).hexdigest(), PWT.WORKFLOW_OUTPUT_SHA256)
        self.assertEqual(T.PREDECESSOR, RESTART_OUTPUT)
        self.assertEqual(T.OUTPUT, CHAINED_OUTPUT)
        for text in (rc1, native, *chain_stages()[:-1]):
            with self.subTest(text=sha256(text.encode('utf8')).hexdigest()[:8]), \
                    self.assertRaisesRegex(T.TransformRefused, 'reviewed R2 predecessor'):
                T.transform(text)
        with self.assertRaisesRegex(T.TransformRefused, 'test-only'):
            native_seam_transform(rc1)
        self.assertFalse(hasattr(T, 'PREDECESSORS'))

    def test_adoption_precedes_the_compact_restart_postpublication(self):
        # Rev4: on the Step 10 chain R2's token adoption runs inside _publish before
        # compact_restart_patch's postpublication, which then re-verifies the persisted
        # envelope and sets the same token (extra checking, never weaker). Each occurs once.
        result = T.transform(chained_input())
        tree = ast.parse(result)
        collar = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'CollarWorkflow')
        publish = next(f for f in collar.body if isinstance(f, ast.FunctionDef) and f.name == '_publish')
        text = ast.get_source_segment(result, publish)
        self.assertIsNotNone(text)
        adopt, post = text.find('token_adopted'), text.find('_RESTART.postpublication(self, parent, row, cancel=cancel)')
        self.assertGreaterEqual(adopt, 0)
        self.assertGreater(post, adopt)
        self.assertEqual(result.count('_RESTART.postpublication(self, parent, row, cancel=cancel)'), 1)


if __name__ == '__main__':
    unittest.main()
