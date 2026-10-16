"""Q2 self-test on tiny synthetic fixtures; never opens the historical database.

The codecs, legacy decoders, ArrayStore and compact stores are the real ones.
Fixtures come from test_partition_tables.tiny_partition and test_mesh_tables.
Manifest projections are compared with manifests the real ArrayStore wrote.
Only a dry --prepare runs; the guard is never launched.
"""
from concurrent.futures import CancelledError
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
import gc
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
R = HERE.parent
C = R / 'compact-geometry-r1'
RUNTIME = R.parent / 'runtime-integration-r1' / 'runtime-src'
for entry in (RUNTIME, R, C, HERE):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import numpy as np
import probe_codec_census as Q
import compact_store as CS
import historical_admission as H
import mesh_tables as M
import native_transfer as N
import partition_native_patch as PN
import partition_routing_transform as RT
import partition_store as PS
import partition_tables as P
import resource_guard_patch as RG
import run_prepared_restart as RPR
import spatial_workflow_patch as Y
from test_mesh_tables import compact_fixture, small_mesh_record
from test_partition_tables import tiny_partition
from atlas_tectonics import integration_differential_geometry as D
from atlas_tectonics.integration_regional_workflow import CollarWorkflow
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreError, StoreLimits


SCRATCH = Q.T / '_t' / 'q2'
LIMITS = StoreLimits(chunk_bytes=256, max_array_bytes=2 << 20, max_store_bytes=16 << 20,
    max_manifest_bytes=256 << 10, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
HISTORICAL_LIMITS = StoreLimits(chunk_bytes=65536, max_array_bytes=64 << 20, max_store_bytes=256 << 20,
    max_manifest_bytes=1 << 20, sqlite_cache_bytes=65536, codec_workspace_bytes=1 << 20)
PRODUCER = dict(role='q2 self-test producer', execution_identity={'fixture': True})


def ident(value):
    return sha256(value.encode()).hexdigest()


def bounds(report):
    return {row['name']: row for row in report['bounds']}


def stored(store, key):
    """Actual stored manifest body length and per-array chunk counts."""
    with store._read_scope():
        size = store._db.execute('SELECT length(body) FROM snapshots WHERE id=?', (key,)).fetchone()[0]
        manifest = store._manifest(key)
    return size, {name: len(desc['chunks']) for name, desc in manifest['arrays'].items()}


def deepest(value, depth=0):
    """Independent recursive reference for pack_partition's value depth."""
    if type(value) is list and len(value) == 2 and all(type(v) is str and v.startswith(('0x', '-0x')) for v in value):
        return depth
    children = value.values() if type(value) is dict else value if type(value) is list else ()
    return max([depth, *(deepest(v, depth+1) for v in children)])


def cancelling(at):
    calls = [0]
    def check():
        calls[0] += 1
        if calls[0] == at:
            raise CancelledError('bounded cancellation control')
    return check, calls


class PartitionCensusTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.budget = WorkBudget(256 << 20)
        self.body, self.supports = tiny_partition(self.budget)
        self.pid = D._record_hash(self.body)

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def census(self, body=None, supports=None, **kwargs):
        body = self.body if body is None else body
        supports = self.supports if supports is None else supports
        return Q.partition_census(body, supports, expected_partition_id=D._record_hash(body), budget=self.budget,
                                  limits=LIMITS, source_producer=PRODUCER, **kwargs)

    def test_counts_bounds_headers_identity_and_real_manifest(self):
        raw = D._encoded(dict(self.body, partition_id=self.pid, supports=self.supports))
        descriptor = dict(sha256=sha256(raw).hexdigest(), nbytes=len(raw))
        labels = []
        report = self.census(descriptor=descriptor, observe=labels.append)
        self.assertEqual((report['status'], report['schema_gate'], report['refusal'], report['bounds_exceeded'],
                          report['information_exceeded']), ('ACCEPTED', 'pass', None, [], []))
        self.assertEqual(report['descriptor_identity'], dict(expected=descriptor, found=descriptor, match=True))
        self.assertEqual(labels, ['partition-input-scanned', 'partition-packed', 'partition-validated',
            'partition-headers-measured', 'partition-descriptor-identity', 'partition-projected'])
        metadata, arrays = P.pack_partition(self.body, iter(self.supports), expected_partition_id=self.pid, budget=self.budget)
        counts = report['counts']
        self.assertEqual({k: counts[k] for k in ('nodes', 'edges', 'supports', 'integers', 'rationals', 'ids', 'strings', 'floats')},
            dict(nodes=len(arrays['node.kind']), edges=len(arrays['edge.child']), supports=len(self.supports),
                 integers=len(arrays['int.sign']), rationals=len(arrays['q.pair']), ids=len(arrays['id.bytes']),
                 strings=len(arrays['string.offset'])-1, floats=len(arrays['float.value'])))
        self.assertGreater(counts['max_integer_bytes'], 32)  # the fixture's 2**263-wide rationals
        self.assertEqual(counts['array_bytes'], sum(a.nbytes for a in arrays.values()))
        self.assertEqual(counts['array_chunks'], sum(-(-a.nbytes // 256) for a in arrays.values()))
        row = bounds(report)
        self.assertEqual((row['DAG nodes']['value'], row['DAG nodes']['bound']), (counts['nodes'], P.MAX_NODES))
        self.assertEqual((row['DAG edges']['value'], row['DAG edges']['bound']), (counts['edges'], P.MAX_EDGES))
        self.assertEqual(row['builder depth']['value'], max(deepest(self.body), *map(deepest, self.supports)))
        self.assertEqual(row['support_ids entries']['value'], len(self.body['support_ids']))
        self.assertEqual(report['input']['supports'], len(self.supports))
        headers = report['headers']
        self.assertEqual(headers['view_dict_mismatch'], [])
        for name in Q.NAMED_HEADER_FIELDS:
            self.assertEqual(headers['view_bytes'][name], len(D._encoded(self.body[name])))
            self.assertEqual(row[name+' selected bytes']['bound'], PN.MAX_HEADER_BYTES)
            self.assertTrue(row[name+' selected bytes']['within'])
        for label, fields in (('ale', RT.ALE_FIELDS), ('trace', RT.TRACE_FIELDS)):
            self.assertEqual(headers['selections'][label]['bytes'],
                             sum(len(D._encoded(self.body[f])) for f in fields if f in self.body))
        view = P.CompactPartition(metadata, arrays, expected_partition_id=self.pid, budget=self.budget)
        with tempfile.TemporaryDirectory(prefix='pc-', dir=SCRATCH) as directory:
            with ArrayStore(Path(directory)/'p.sqlite', LIMITS, budget=self.budget) as store:
                ref = PS.CompactPartitionStore(store, budget=self.budget).publish(view, source_producer=PRODUCER)
                manifest = report['manifest']
                self.assertEqual(ref['snapshot_key'], manifest['root_key'])
                size, chunks = stored(store, ref['snapshot_key'])
                self.assertEqual(size, manifest['root']['body_bytes'])
                self.assertEqual(chunks, {n: d['chunks'] for n, d in manifest['descriptions'].items()})
                self.assertEqual(sum(chunks.values()), manifest['root']['chunk_references'])
                del ref
        del view, metadata, arrays

    def test_over_bound_inputs_are_reported_not_raised(self):
        deep = 'leaf'
        for _ in range(P.MAX_DEPTH+2):
            deep = {'n': deep}
        report = self.census(dict(self.body, source=deep))
        self.assertEqual((report['status'], report['refusal']['stage'], report['schema_gate']), ('REFUSED', 'pack', 'not-reached'))
        self.assertIn('exceeds bound', report['refusal']['message'])
        self.assertIn('pack_partition', report['refusal']['codec_frames'])
        row = bounds(report)
        self.assertEqual(row['builder depth']['value'], P.MAX_DEPTH+3)
        self.assertFalse(row['builder depth']['within'])
        self.assertIn('builder depth', report['bounds_exceeded'])
        supports = deepcopy(self.supports)
        supports[1]['coverage'] = 'w'*P.MAX_STRING_BYTES
        report = self.census(dict(self.body, support_ids=[D._record_hash(s) for s in supports]), supports)
        self.assertEqual((report['status'], report['refusal']['stage'], report['refusal']['type']),
                         ('REFUSED', 'pack', 'PartitionTablesRefused'))
        self.assertIn('bounded string required', report['refusal']['message'])
        self.assertEqual(report['refusal']['progress_at_refusal']['supports_packed'], 1)
        self.assertGreater(report['refusal']['progress_at_refusal']['nodes'], 0)
        self.assertEqual(bounds(report)['longest string or key width']['value'], P.MAX_STRING_BYTES+2)
        verdict = Q.decision(report, None)
        self.assertTrue(verdict['w2x_indicated'])
        self.assertIn('partition: longest string or key width', verdict['codec_bounds_exceeded'])

    def test_selected_header_over_16_mib_is_reported(self):
        body = deepcopy(self.body)
        # Control characters escape to six bytes: 16 MiB of legacy JSON cheaply.
        big = '\x01'*((P.MAX_STRING_BYTES-2)//6)
        body['native_contacts'][0]['excluded_subfaces'] = [big]*(PN.MAX_HEADER_BYTES//(len(D._encoded(big))+1)+1)
        report = self.census(body)
        self.assertEqual((report['status'], report['refusal']), ('ACCEPTED', None))
        size = report['headers']['view_bytes']['native_contacts']
        self.assertEqual(size, len(D._encoded(body['native_contacts'])))
        self.assertGreater(size, PN.MAX_HEADER_BYTES)
        row = bounds(report)
        for name in ('native_contacts selected bytes', 'ale selection bytes', 'trace selection bytes',
                     'largest native_contacts row bytes'):
            self.assertFalse(row[name]['within'], name)
            self.assertIn(name, report['bounds_exceeded'])
        for name in ('support_ids selected bytes', 'identity_start_cells selected bytes', 'workflow_header selection bytes'):
            self.assertTrue(row[name]['within'], name)
        self.assertEqual(report['headers']['selections']['ale']['first_field_over_bound'], 'native_contacts')
        self.assertEqual(report['information_exceeded'], ['named selection bytes'])
        self.assertEqual(row['largest object keys']['bound'], P.MAX_ROW_ITEMS)
        verdict = Q.decision(report, None)
        self.assertFalse(verdict['w2x_indicated'])
        self.assertIn('partition: native_contacts selected bytes', verdict['other_limits_exceeded'])

    def test_cancellation_propagates_and_releases(self):
        check, calls = cancelling(0)
        self.census(check=check)
        total = calls[0]
        for at in (40, total):
            check, _ = cancelling(at)
            with self.assertRaises(CancelledError):
                self.census(check=check)
            gc.collect()
            self.assertEqual(self.budget.reserved_bytes, 0)


class MeshCensusTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.budget = WorkBudget(1 << 30)
        self.record = small_mesh_record(self.budget)

    def tearDown(self):
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)

    def census(self, record=None, limits=LIMITS, **kwargs):
        record = self.record if record is None else record
        return Q.mesh_census(record, expected_geometry_id=M.digest(record), budget=self.budget, limits=limits,
                             source_producer=PRODUCER, **kwargs)

    def test_counts_bounds_and_manifests_match_real_store(self):
        labels = []
        report = self.census(observe=labels.append)
        self.assertEqual((report['status'], report['refusal'], report['bounds_exceeded']), ('ACCEPTED', None, []))
        self.assertEqual(labels, ['mesh-input-scanned', 'mesh-packed', 'mesh-validated', 'mesh-projected'])
        view, _metadata, arrays, blobs, _reads = compact_fixture(self.record, self.budget)
        counts = report['counts']
        self.assertEqual((counts['cells'], counts['faces']), (2, 11))
        self.assertEqual({k: counts[k] for k in ('incidences', 'vertices', 'owners', 'integers', 'rationals', 'ids', 'tags', 'supports')},
            dict(incidences=len(arrays['c.face']), vertices=len(arrays['f.vertex']), owners=len(arrays['f.owner']),
                 integers=len(arrays['int.sign']), rationals=len(arrays['q.pair']), ids=len(arrays['id.bytes']),
                 tags=len(arrays['tag.offset'])-1, supports=len(self.record['support_tables']['voxels'])))
        shape = report['input']
        self.assertEqual(shape['header_width'], M._width({k: v for k, v in self.record.items() if k not in M.SPECIAL}))
        self.assertEqual((shape['incidences'], shape['vertices']), (counts['incidences'], counts['vertices']))
        self.assertEqual((shape['distinct_support_blobs'], shape['largest_support_bytes']),
                         (len(blobs), max(map(len, blobs.values()))))
        row = bounds(report)
        self.assertEqual((row['rationals pool']['value'], row['rationals pool']['bound']), (counts['rationals'], M.MAX_ITEMS))
        self.assertEqual(row['column rows int.offset']['value'], counts['integers']+1)
        self.assertNotIn('column rows c.face_offset', row)
        manifest = report['manifest']
        with tempfile.TemporaryDirectory(prefix='mc-', dir=SCRATCH) as directory:
            with ArrayStore(Path(directory)/'m.sqlite', LIMITS, budget=self.budget) as store:
                ref = Y.persist_mesh(store, view, PRODUCER, budget=self.budget)
                self.assertEqual(ref['snapshot_key'], manifest['root_key'])
                size, chunks = stored(store, manifest['root_key'])
                self.assertEqual((size, sum(chunks.values()), len(chunks)),
                    (manifest['root']['body_bytes'], manifest['root']['chunk_references'], manifest['root']['arrays']))
                link = sha256(N._json(Y._link_record(view.geometry_id, PRODUCER))).hexdigest()
                self.assertEqual(link, manifest['link_key'])
                self.assertEqual(stored(store, link)[0], manifest['link']['body_bytes'])
                size, content = max((len(raw), c) for c, raw in blobs.items())
                support = CS._digest(CS._support_record(content, size))
                self.assertEqual(support, manifest['largest_support_snapshot']['invocation'])
                self.assertEqual(stored(store, support)[0], manifest['largest_support_snapshot']['body_bytes'])
                del ref
        aliases = manifest['workflow_aliases_lower_bound']
        self.assertFalse(aliases['includes_partition'])
        # Every root array is aliased (one packed support array, compact_store v2);
        # the reference binds descriptor digests, not copied chunk lists.
        self.assertEqual((aliases['arrays'], aliases['chunk_references']),
                         (manifest['root']['arrays'], manifest['root']['chunk_references']))
        self.assertEqual(manifest['root']['arrays'], len(report['arrays'])+1)
        self.assertLess(aliases['metadata_bytes'], manifest['root']['metadata_bytes'])
        del view, arrays, blobs

    def test_over_bound_header_is_reported_not_raised(self):
        record = deepcopy(self.record)
        record['source'] = {'note': '\x01'*(M.MAX_HEADER_BYTES//6+1)}
        report = self.census(record)
        self.assertEqual((report['status'], report['refusal']['stage']), ('REFUSED', 'pack'))
        self.assertIn('header exceeds bound', report['refusal']['message'])
        self.assertFalse(bounds(report)['header width']['within'])
        self.assertTrue(report['refusal']['typed'])
        self.assertTrue(Q.decision(None, report)['w2x_indicated'])
        record = deepcopy(self.record)
        record['cells'].append(['not', 'a', 'cell'])  # an untyped codec exception is reported too
        report = self.census(record)
        self.assertEqual((report['status'], report['refusal']['stage'], report['refusal']['type'], report['refusal']['typed']),
                         ('REFUSED', 'pack', 'TypeError', False))
        self.assertIn('pack_mesh', report['refusal']['codec_frames'])

    def test_manifest_over_1_mib_is_reported_and_real_store_refuses(self):
        record = deepcopy(self.record)
        record['source'] = {'note': '\x01'*180000}  # under the 2 MiB codec header, over 1 MiB of manifest
        report = self.census(record, limits=HISTORICAL_LIMITS)
        self.assertEqual(report['status'], 'ACCEPTED')
        row = bounds(report)
        self.assertTrue(row['header width']['within'])
        for name in ('mesh root manifest body bytes', 'mesh root metadata bytes', 'compact_store root support inventory'):
            self.assertFalse(row[name]['within'], name)
        self.assertTrue(row['mesh link manifest body bytes']['within'])  # the link carries references, not the header
        verdict = Q.decision(None, report)
        self.assertFalse(verdict['w2x_indicated'])
        self.assertIn('mesh: mesh root manifest body bytes', verdict['other_limits_exceeded'])
        view = compact_fixture(record, self.budget)[0]
        with tempfile.TemporaryDirectory(prefix='mo-', dir=SCRATCH) as directory:
            with ArrayStore(Path(directory)/'m.sqlite', HISTORICAL_LIMITS, budget=self.budget) as store:
                with self.assertRaises(StoreError):
                    Y.persist_mesh(store, view, PRODUCER, budget=self.budget)
        del view

    def test_cancellation_propagates_and_releases(self):
        check, calls = cancelling(0)
        self.census(check=check)
        for at in (5, calls[0]):
            check, _ = cancelling(at)
            with self.assertRaises(CancelledError):
                self.census(check=check)
            gc.collect()
            self.assertEqual(self.budget.reserved_bytes, 0)


class StoreReaderTests(unittest.TestCase):
    def test_census_store_reads_a_synthetic_head_without_writes(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        budget = WorkBudget(1 << 30)
        body, supports = tiny_partition(budget)
        pid = D._record_hash(body)
        mesh = small_mesh_record(budget)
        p_raw = D._encoded(dict(body, partition_id=pid, supports=supports))
        m_raw = M.canonical(mesh)
        state = dict(schema='fixture.spatial-state', state_id=ident('state'), owner_id=ident('owner'),
            funding_id=ident('funding'), time_s=12.5, intervals=1, parent_state_id=None, collar_state_id=ident('collar'),
            support_id=ident('support'), trajectory_id=ident('trajectory'), grid_id=ident('grid'),
            thermal_mesh_id=sha256(m_raw).hexdigest())
        s_raw = M.canonical(state)
        def blob(name, raw):
            return dict(array=name, bytes=len(raw), sha256=sha256(raw).hexdigest())
        p_header = CollarWorkflow._partition_header(dict(body, partition_id=pid), {'partition': blob(Q.PARTITION_BLOB, p_raw)})
        s_header = CollarWorkflow._spatial_headers(dict(state, thermal_mesh=mesh), None,
            {'state': blob(Q.STATE_BLOB, s_raw), 'mesh': blob(Q.MESH_BLOB, m_raw)})[0]
        head = ident('head')
        arrays = {name: np.frombuffer(raw, dtype=np.uint8)
                  for name, raw in ((Q.PARTITION_BLOB, p_raw), (Q.STATE_BLOB, s_raw), (Q.MESH_BLOB, m_raw))}
        labels = []
        with tempfile.TemporaryDirectory(prefix='sr-', dir=SCRATCH) as directory:
            with ArrayStore(Path(directory)/'h.sqlite', LIMITS, budget=budget) as store:
                store.put(head, arrays, dict(key=head, workflow_id=ident('workflow'), differential_partition=p_header,
                                             exterior_state=s_header), budget=budget)
                before = store.change_token(), store.statistics()['snapshots']
                result = Q.census_store(store, head, budget=budget, limits=LIMITS, check=lambda: None,
                                        observe=labels.append, source_producer=PRODUCER)
                self.assertEqual((store.change_token(), store.statistics()['snapshots']), before)
        partition, mesh_report = result['partition'], result['mesh']
        self.assertEqual((partition['status'], partition['descriptor_identity']['match'], mesh_report['status']),
                         ('ACCEPTED', True, 'ACCEPTED'))
        self.assertTrue(result['head']['mesh_blob_is_thermal_mesh_id'])
        self.assertEqual(result['head']['partition_id'], pid)
        self.assertLess(labels.index('partition-decoded-released'), labels.index('partition-validated'))
        self.assertEqual(labels[-1], 'mesh-released')
        for report in (partition, mesh_report):
            self.assertEqual(report['logical_budget']['reserved_after_release'], 0)
            self.assertGreater(report['logical_budget']['peak_reserved_bytes'], 0)
            self.assertIn('read', report['seconds'])
            self.assertIn('decode', report['seconds'])
        direct = Q.partition_census(body, supports, expected_partition_id=pid, budget=budget, limits=LIMITS,
                                    source_producer=PRODUCER)
        self.assertEqual(partition['counts'], direct['counts'])
        self.assertEqual(partition['manifest']['root'], direct['manifest']['root'])
        direct = Q.mesh_census(mesh, expected_geometry_id=sha256(m_raw).hexdigest(), budget=budget, limits=LIMITS,
                               source_producer=PRODUCER)
        self.assertEqual(mesh_report['counts'], direct['counts'])
        self.assertEqual(mesh_report['manifest']['root'], direct['manifest']['root'])
        self.assertTrue(mesh_report['manifest']['workflow_aliases_lower_bound']['includes_partition'])
        self.assertFalse(result['decision']['w2x_indicated'])
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)  # the guard's receipt writer rule
        del result, partition, mesh_report, direct, arrays, store
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)


class LaunchSurfaceTests(unittest.TestCase):
    def test_prepare_is_dry_and_prints_the_exact_guarded_command(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='pp-', dir=SCRATCH) as directory:
            out = Path(directory).resolve()/'census'
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(Q.main(['--prepare', '--output', str(out)]), 0)
            plan = json.loads(buffer.getvalue())
            python = str(Q.PYTHON.resolve())
            self.assertEqual(plan['command'], [python, '-B', str(out/'guard'/RG.GUARD_NAME), '--launch', '--output',
                str(out/'run.json'), '--', python, '-B', str(Path(Q.__file__).resolve()), '--workload', '--output', str(out)])
            self.assertEqual((plan['status'], plan['writes'], plan['cwd']), ('PREPARED_COMMAND_ONLY_NOT_LAUNCHED', 'nothing', str(out)))
            self.assertEqual(plan['guard']['files'], {RG.GUARD_NAME: RG.SUCCESSOR_PIN, RG.JOB_NAME: RG.JOB_PIN,
                                                      RG.DIAGNOSTICS_NAME: RG.DIAGNOSTICS_PIN})
            self.assertEqual(RG.SUCCESSOR_PIN, H.GUARD_PIN)
            self.assertEqual(plan['limits'], dict(rss_bytes=12 << 30, free_floor_bytes=1 << 30,
                start_available_bytes=10 << 30, logical_budget_bytes=16 << 30, operational_target_bytes=14 << 30))
            self.assertEqual(plan['environment'], RPR.LAUNCH_ENV)
            self.assertEqual(plan['original']['pinned_sha256'], H._REVIEWED_ORIGINAL.database_sha256)
            for name, digest in plan['sources'].items():
                self.assertEqual(digest, Q._file_sha(Q.T/name), name)
            self.assertFalse(out.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_gates_refuse_before_any_write(self):
        self.assertTrue(Q.start_gate(Q.START_BYTES)['below_operational_target'])
        with self.assertRaises(Q.CensusRefused):
            Q.start_gate(Q.START_BYTES-1)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='pg-', dir=SCRATCH) as directory:
            out = Path(directory)/'census'
            with self.assertRaises(Q.CensusRefused):
                Q.launch(out, available=lambda: Q.START_BYTES-1)
            self.assertFalse(out.exists())
            out.mkdir()
            with self.assertRaises(Q.CensusRefused):
                Q.prepare(out)

    def test_safeguards_equal_the_runner(self):
        self.assertEqual((Q.RSS_BYTES, Q.FREE_BYTES, Q.START_BYTES, Q.LOGICAL_BYTES),
                         (RPR.RSS_BYTES, RPR.FREE_BYTES, RPR.START_BYTES, RPR.LOGICAL_BYTES))
        self.assertEqual(Q.LAUNCH_ENV, RPR.LAUNCH_ENV)

    def test_pinned_receipts_name_the_head_and_store_limits(self):
        endpoint = Q.historical_endpoint()
        self.assertEqual(endpoint['head_key'], 'bc945eedff746d89992e474f4aa089eb333d03298e47a22f10ae6d54e0549bbc')
        self.assertEqual((endpoint['store_limits']['chunk_bytes'], endpoint['store_limits']['max_manifest_bytes']),
                         (65536, 1 << 20))
        self.assertEqual(endpoint['store_compression']['codec'], 'raw')
        self.assertEqual(set(endpoint['receipts']), {Q.READER_RECEIPT, Q.PRODUCER_RECEIPT})


class StructureSurfaceTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)

    def test_cli_forwards_structure_only_in_every_mode(self):
        for flag, function, returned in (('--prepare', 'prepare', {}), ('--launch', 'launch', 0),
                                         ('--workload', 'workload', 0)):
            with self.subTest(flag=flag), patch.object(Q, function, return_value=returned) as called:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(Q.main([flag, '--structure-only', '--output', 'fixture-output']), 0)
                called.assert_called_once_with(Path('fixture-output'), structure_only=True)

    def test_prepare_forwards_child_flag_and_uses_separate_artifact(self):
        with tempfile.TemporaryDirectory(prefix='sp-', dir=SCRATCH) as directory:
            out = Path(directory).resolve()/'census'
            with patch.object(Q, '_structure_source_pins', return_value={'fixture.py': 'a'*64}):
                plan = Q.prepare(out, structure_only=True)
            self.assertEqual(plan['command'][-1], '--structure-only')
            self.assertEqual(plan['census_json'], str(out/'structure-census.json'))
            self.assertTrue(plan['structure_only'])
            self.assertEqual(plan['sources'], {'fixture.py': 'a'*64})
            self.assertFalse(out.exists())

    def test_structure_branch_never_calls_codec_census(self):
        selected = Mock(return_value={'structure': 'fixture'})
        args = dict(budget=object(), limits=object(), check=lambda: None, observe=lambda _: None,
                    result={}, scratch_directory=Path('fixture-scratch'))
        store, endpoint = object(), {'head_key': 'fixture-head'}
        with patch.dict(sys.modules, {'structure_census': SimpleNamespace(census_store=selected)}), \
                patch.object(Q, 'census_store', side_effect=AssertionError('codec branch entered')):
            found = Q._selected_census(store, endpoint, structure_only=True, **args)
        self.assertEqual(found, {'structure': 'fixture'})
        selected.assert_called_once_with(store, endpoint, **args)

    def test_prepared_sources_missing_changed_or_incomplete_are_refused(self):
        with tempfile.TemporaryDirectory(prefix='ss-', dir=SCRATCH) as directory:
            root = Path(directory)
            source, receipt = root/'fixture.py', root/'prepare.json'
            source.write_text('fixture = 1\n', encoding='utf8')
            pins = {'fixture.py': Q._file_sha(source)}
            with patch.object(Q, 'T', root), patch.object(Q, '_structure_source_pins', return_value=pins):
                with self.assertRaisesRegex(Q.CensusRefused, 'prepared source bindings required'):
                    Q._verify_structure_sources(root)
                plan = dict(schema=Q.PREPARE_SCHEMA, structure_only=True, sources=pins)
                receipt.write_text(json.dumps(plan), encoding='utf8')
                self.assertEqual(Q._verify_structure_sources(root)['files'], 1)
                receipt.write_text(json.dumps(dict(plan, sources={})), encoding='utf8')
                with self.assertRaisesRegex(Q.CensusRefused, 'selected-source set differs'):
                    Q._verify_structure_sources(root)
                receipt.write_text(json.dumps(plan), encoding='utf8')
                source.write_text('fixture = 2\n', encoding='utf8')
                with self.assertRaisesRegex(Q.CensusRefused, 'prepared source changed'):
                    Q._verify_structure_sources(root)

    def test_loaded_runtime_outside_frozen_root_is_refused(self):
        with tempfile.TemporaryDirectory(prefix='sl-', dir=SCRATCH) as directory:
            root = Path(directory)
            (root/'prepare.json').write_text(json.dumps(dict(schema=Q.PREPARE_SCHEMA,
                structure_only=True, sources={})), encoding='utf8')
            modules = {'atlas_tectonics.foreign': SimpleNamespace(__file__=str(root/'foreign.py'))}
            with patch.object(Q, '_structure_source_pins', return_value={}), \
                    patch.object(Q, 'sys', SimpleNamespace(modules=modules)):
                with self.assertRaisesRegex(Q.CensusRefused, 'outside frozen I'):
                    Q._verify_structure_sources(root, loaded=True)

    def test_frozen_runtime_manifest_drift_is_refused(self):
        with patch.object(Q, '_file_sha', return_value='0'*64):
            with self.assertRaisesRegex(Q.CensusRefused, 'frozen I manifest changed'):
                Q._structure_source_pins()

    def test_historical_mapping_inputs_are_fixed_data_only_pins(self):
        self.assertIn(Q.R/'initial_workload.py', Q.STRUCTURE_SOURCES)
        before = set(sys.modules)
        with patch.object(Q, 'STRUCTURE_SOURCES', ()):
            pins = Q._structure_source_pins()
        for name, digest in Q.H_STRUCTURE_PINS.items():
            path = Q.O.parents[1]/'heat-repair-20261007'/name
            self.assertEqual(pins[str(path.relative_to(Q.T)).replace('\\', '/')], digest)
        self.assertEqual(set(sys.modules), before)
        name = next(iter(Q.H_STRUCTURE_PINS))
        with patch.object(Q, 'STRUCTURE_SOURCES', ()), \
                patch.object(Q, 'H_STRUCTURE_PINS', {name: '0'*64}):
            with self.assertRaisesRegex(Q.CensusRefused, 'historical mapping source changed'):
                Q._structure_source_pins()

    def test_compact_inventory_dependencies_are_required_and_bound(self):
        required = {Q.HERE/'compact_structure.py', Q.C/'compact_store.py', Q.C/'partition_store.py',
            Q.C/'spatial_workflow_patch.py', Q.C/'partition_workflow_patch.py', Q.C/'spatial_indexed_patch.py',
            Q.C/'mesh_tables.py', Q.C/'partition_tables.py'}
        self.assertTrue(required <= set(Q.STRUCTURE_SOURCES))
        pins = Q._structure_source_pins()
        for path in required:
            self.assertEqual(pins[str(path.relative_to(Q.T)).replace('\\', '/')], Q._file_sha(path))
        with tempfile.TemporaryDirectory(prefix='sm-', dir=SCRATCH) as directory:
            with patch.object(Q, 'STRUCTURE_SOURCES', (Path(directory)/'missing-compact-helper.py',)):
                with self.assertRaises(FileNotFoundError):
                    Q._structure_source_pins()

    def test_original_verification_runs_on_failure_and_retains_primary_error(self):
        import psutil
        from atlas_tectonics import reuse
        with tempfile.TemporaryDirectory(prefix='sf-', dir=SCRATCH) as directory:
            original = Path(directory)/'fixture.bin'
            original.write_bytes(b'original')
            pin = Q._file_sha(original)
            endpoint = dict(head_key='fixture', store_limits=dict(chunk_bytes=256, max_array_bytes=2 << 20,
                max_store_bytes=16 << 20), store_compression={})
            store = SimpleNamespace(_historical_readonly=H._READONLY,
                _db=SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: (1,))),
                change_token=lambda: 'unchanged')
            guard = SimpleNamespace(_control={'limits': dict(rss_bytes=Q.RSS_BYTES, free_floor_bytes=Q.FREE_BYTES)},
                                    check=lambda **_: None)
            for final_hash, token_failure, expected in ((pin, False, 'PASS'), ('0'*64, False, 'INCOMPLETE'),
                                                        (pin, True, 'INCOMPLETE')):
                with self.subTest(final_hash=final_hash, token_failure=token_failure):
                    store.change_token = Mock(side_effect=['unchanged', RuntimeError('token read failed')]) if token_failure \
                        else lambda: 'unchanged'
                    record = dict(census={}, errors=[])
                    primary = ValueError('primary measurement failure')
                    with patch.object(H, '_inside', return_value=original), \
                            patch.object(H, '_REVIEWED_ORIGINAL', SimpleNamespace(database_name='fixture.bin', database_sha256=pin)), \
                            patch.object(H, 'guardian_fence'), \
                            patch.object(H, '_hash_file', side_effect=[pin, final_hash]) as hashes, \
                            patch.object(H, 'open_original_readonly', return_value=nullcontext(store)), \
                            patch.object(Q, 'historical_endpoint', return_value=endpoint), \
                            patch.object(Q, '_observer', return_value=lambda _: None), \
                            patch.object(Q, '_selected_census', side_effect=primary), \
                            patch.object(psutil, 'virtual_memory', return_value=SimpleNamespace(available=Q.START_BYTES)), \
                            patch.object(reuse, 'execution_mode', return_value='strict'):
                        with self.assertRaises(ValueError) as caught:
                            Q._guarded_census(guard, record, structure_only=True, output=Path(directory))
                    self.assertIs(caught.exception, primary)
                    self.assertEqual(hashes.call_count, 2)
                    self.assertEqual(record['census']['original']['verification_status'], expected)
                    self.assertEqual(record['census']['store_token_unchanged'], None if token_failure else True)
                    self.assertEqual(len(record['errors']), 0 if expected == 'PASS' else 1)


def publish_arrays(candidate, scope, schema, arrays, *, profile='atlas.test.wp0b-census-profile.v1'):
    """A plain segment through the live SegmentBackend (unknown-to-census profile)."""
    from compact_contracts import LogicalIdentity
    from segment_store import SegmentBackend
    raw = Q.canonical_json({'fixture': schema})
    identity = LogicalIdentity(schema, sha256(raw).hexdigest(), len(raw))
    return SegmentBackend().publish(candidate, record_schema=schema, identity=identity, metadata=raw,
        arrays=lambda: (CS._ArraySource(scope, name, arrays[name]) for name in sorted(arrays)),
        producer='b'*64, representation_profile=profile, scope=scope)


def chunk_ids(array):
    """Independent native chunk IDs of one array (64 KiB typed chunks)."""
    from interval_store_set import chunk_id
    raw = memoryview(np.ascontiguousarray(array).reshape(-1)).cast('B')
    width = 65536 // array.dtype.itemsize * array.dtype.itemsize
    ids = []
    for start in range(0, len(raw), width):
        part = bytes(raw[start:start+width])
        descriptor = Q.canonical_json({'dtype': array.dtype.str, 'count': len(part)//array.dtype.itemsize})
        ids.append(chunk_id(descriptor, part))
    return ids


def stored_rows(path):
    """Oracle: every stored chunk row's payload length, read with plain read-only SQLite."""
    import sqlite3
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
    try:
        return dict(db.execute('SELECT id,length(payload) FROM chunks').fetchall())
    finally:
        db.close()


class CompactCensusTests(unittest.TestCase):
    """WP0b handlers on small synthetic stores built with the live builders."""

    def setUp(self):
        from content_cache import create_retained_scope
        from interval_store_set import IntervalStoreSet
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='wp0b-', dir=SCRATCH)
        self.path = Path(self.temp.name)
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='wp0b-census-test')
        self.stores = IntervalStoreSet.create_migration(self.path/'catalog.json', workflow_id='a'*64, scope=self.scope)

    def tearDown(self):
        self.stores.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())
        self.temp.cleanup()

    def begin(self):
        return self.stores.begin_interval(self.stores.head, producer_identity='b'*64, runtime_identity='c'*64)

    def seal(self, candidate, head):
        sealed = candidate.seal(head)
        self.stores.promote(sealed, expected_catalog_digest=sealed.expected_catalog_digest)
        candidate.close()

    def census(self, **kwargs):
        """Cold reopen, then the census; file bytes and catalog are unchanged by it."""
        from interval_store_set import IntervalStoreSet
        self.stores.close()
        files = sorted(self.path.iterdir())
        before = {p.name: Q._file_sha(p) for p in files}
        self.stores = IntervalStoreSet.open_catalog(self.path/'catalog.json', scope=self.scope)
        result = Q.compact_census(self.stores, verify_files=True, **kwargs)
        self.assertEqual({p.name: Q._file_sha(p) for p in sorted(self.path.iterdir())}, before)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        return result

    def test_chunks_duplicates_codec_and_cross_interval_references(self):
        noise = np.random.default_rng(7).integers(0, 256, 70000, dtype=np.uint8)
        zeros = np.zeros(65536, dtype=np.uint8)
        words = np.arange(1000, dtype='<u4')
        first = self.begin()
        s0 = publish_arrays(first, self.scope, 'atlas.test.wp0b-zero.v1',
                            {'a.first': noise, 'a.second': noise.copy(), 'b.zeros': zeros, 'c.empty': np.zeros(0, np.uint8)})
        self.seal(first, s0)
        second = self.begin()
        s1 = publish_arrays(second, self.scope, 'atlas.test.wp0b-one.v1', {'a.reused': noise, 'd.new': words})
        self.seal(second, s1)
        result = self.census()
        rows0, rows1 = stored_rows(self.path/'interval-0000.sqlite'), stored_rows(self.path/'interval-0001.sqlite')
        noise_ids, zero_ids, word_ids = chunk_ids(noise), chunk_ids(zeros), chunk_ids(words)
        self.assertEqual((len(noise_ids), set(rows0)), (2, set(noise_ids) | set(zero_ids)))
        self.assertEqual(set(rows1), set(word_ids))  # unchanged content is referenced, not stored again
        c = result['classes']
        first_class = c['atlas.test.wp0b-zero.v1/a.first']
        self.assertEqual(first_class['logical'], {'leaves': 2, 'mentions': 2, 'bytes': 70000,
                                                  'cross_interval_mentions': 0, 'cross_interval_bytes': 0})
        self.assertEqual(first_class['unique'], {'chunks': 2, 'bytes': 70000, 'repeated_within_class': 0,
                                                 'shared_with_other_class': 0})
        self.assertEqual((first_class['physical']['rows'], first_class['physical']['payload_bytes']),
                         (2, sum(rows0[i] for i in noise_ids)))
        # Duplicate content: logical > unique, no physical bytes.
        duplicate = c['atlas.test.wp0b-zero.v1/a.second']
        self.assertEqual((duplicate['logical']['mentions'], duplicate['logical']['bytes']), (2, 70000))
        self.assertEqual(duplicate['unique'], {'chunks': 0, 'bytes': 0, 'repeated_within_class': 0,
                                               'shared_with_other_class': 2})
        self.assertEqual((duplicate['physical']['rows'], duplicate['physical']['payload_bytes']), (0, 0))
        # Codec case: physical != logical.
        zero_class = c['atlas.test.wp0b-zero.v1/b.zeros']
        self.assertEqual((zero_class['logical']['bytes'], zero_class['unique']['bytes']), (65536, 65536))
        self.assertEqual(zero_class['physical']['payload_bytes'], rows0[zero_ids[0]])
        self.assertLess(zero_class['physical']['payload_bytes'], 65536)
        self.assertEqual(c['atlas.test.wp0b-zero.v1/c.empty']['logical'],
                         {'leaves': 1, 'mentions': 0, 'bytes': 0, 'cross_interval_mentions': 0,
                          'cross_interval_bytes': 0})
        # Cross-interval reference: a logical mention in interval 1, physical bytes stay in interval 0.
        reused = c['atlas.test.wp0b-one.v1/a.reused']
        self.assertEqual(reused['logical'], {'leaves': 2, 'mentions': 2, 'bytes': 70000, 'cross_interval_mentions': 2,
                                             'cross_interval_bytes': 70000})
        self.assertEqual((reused['unique']['chunks'], reused['unique']['shared_with_other_class'],
                          reused['physical']['rows']), (0, 2, 0))
        new = c['atlas.test.wp0b-one.v1/d.new']
        self.assertEqual((new['logical']['bytes'], new['unique']['bytes'], new['physical']['payload_bytes']),
                         (4000, 4000, rows1[word_ids[0]]))
        totals = result['totals']
        self.assertEqual((totals['logical']['mentions'], totals['logical']['bytes']), (8, 3*70000+65536+4000))
        self.assertEqual((totals['unique']['chunks'], totals['unique']['bytes']), (4, 70000+65536+4000))
        self.assertEqual((totals['physical']['rows'], totals['physical']['payload_bytes']),
                         (4, sum(rows0.values())+sum(rows1.values())))
        files = result['files']
        self.assertEqual([(f['chunk_rows'], f['attributed_chunk_rows'], f['unattributed_chunk_rows'], f['unattributed_snapshots'])
                          for f in files], [(3, 3, 0, 0), (1, 1, 0, 0)])
        self.assertEqual(files[1]['references'], [[0, files[0]['logical_seal']]])
        self.assertEqual([f['file_bytes'] for f in files],
                         [(self.path/name).stat().st_size for name in ('interval-0000.sqlite', 'interval-0001.sqlite')])
        self.assertTrue(all(f['file_sha256_verified'] for f in files))
        self.assertEqual((result['catalog']['entries'], result['catalog']['cross_interval_references']), (2, 1))
        self.assertEqual([r['handler'] for r in result['records']], ['segment', 'segment'])
        self.assertEqual((result['segment_refs']['logical_mentions'], result['segment_refs']['unique']), (2, 2))
        self.assertEqual(result['snapshots']['segment-root']['unique'], 2)
        pages = result['snapshots']['binding-page']
        self.assertEqual(pages['unique'], sum(s['index']['unique'] for s in result['segments']))

    def test_record_tables_pools_and_dag_references(self):
        from record_tables import RecordCodec
        from segment_store import SegmentBackend
        value = {'shared': [[1, 2, 'x'*40]]*3, 'ids': ['d'*64, 'd'*64, 'e'*64], 'q': ['0x3', '0x5'],
                 'f': 1.5, 'big': 3**200, 'dyadic': 2**300, 'n': None, 'b': True}
        schema = 'atlas.test.wp0b-record.v1'
        candidate = self.begin()
        record = RecordCodec().pack_record(value, record_schema=schema, scope=self.scope, check=lambda: None)
        arrays = {name: np.array(a) for name, a in record._columns.arrays.items()}
        identity = record.identity()
        with record.metadata_bytes() as held:
            raw = bytes(held.value)
        ref = SegmentBackend().publish(candidate, record_schema=schema, identity=identity, metadata=raw,
            arrays=record.array_sources, producer='b'*64, representation_profile='atlas.test.wp0b-record-profile.v1',
            scope=self.scope)
        record.close()
        self.seal(candidate, ref)
        result = self.census()
        report = result['records'][0]
        self.assertEqual((report['handler'], report['domain'], report['canonical_bytes'], report['record_metadata_bytes']),
                         ('record-tables', 'record-tables', identity.canonical_bytes, len(raw)))
        kinds = np.bincount(arrays['node.kind'], minlength=10)
        self.assertEqual(report['node_kinds'], dict(zip(Q._KIND_NAMES, map(int, kinds), strict=True)))
        pools = report['pools']
        n, edges, pairs = len(arrays['node.kind']), len(arrays['edge.child']), len(arrays['q.numerator'])
        self.assertEqual((pools['node']['unique_rows'], pools['node']['logical_references']), (n, edges+2*pairs+1))
        self.assertGreater(pools['node']['logical_references'], pools['node']['unique_rows'])  # shared subtrees
        self.assertEqual((pools['token']['unique_rows'], pools['token']['logical_references']),
                         (len(arrays['token.offset'])-1, int(kinds[4])+len(arrays['shape.key'])))
        self.assertEqual(pools['token']['largest_bytes'], int(np.max(np.diff(arrays['token.offset']))))
        self.assertEqual((pools['integer']['unique_rows'], pools['integer']['largest_stored_magnitude_bytes']),
                         (len(arrays['int.sign']), int(np.max(np.diff(arrays['int.offset'])))))
        # 3**200 is stored as 40 magnitude bytes; 2**300 is dyadic (exponent only, 38 binary bytes).
        self.assertEqual((pools['integer']['largest_stored_magnitude_bytes'], pools['integer']['largest_dyadic_exponent'],
                          pools['integer']['largest_magnitude_bytes']), (40, 300, 40))
        self.assertEqual((pools['id']['unique_rows'], pools['id']['logical_references']), (2, int(kinds[5])))
        self.assertEqual((pools['rational']['unique_rows'], pools['float']['unique_rows']), (pairs, 1))
        self.assertEqual(report['column_bytes'], sum(a.nbytes for a in arrays.values()))
        c = result['classes']
        self.assertEqual(set(c), {schema+'/'+name for name in arrays})
        for name, array in arrays.items():
            self.assertEqual(c[schema+'/'+name]['logical']['bytes'], array.nbytes, name)
        self.assertEqual(pools['integer']['physical_bytes'],
                         sum(c[schema+'/'+name]['physical']['payload_bytes']
                             for name in ('int.offset', 'int.bytes', 'int.sign', 'int.mode', 'int.exponent')))

    def mesh_store(self, header_value=None):
        """Partition v2 plus mesh v3 (r2 header column when header_value is IV1-sized)."""
        import test_mesh_v3 as F
        candidate = self.begin()
        mesh, record, source, partition, partition_ref = F.fixture(self.scope, candidate)
        if header_value is not None:
            changed = deepcopy(record)
            changed['support_tables']['differential_supports'] = record['support_tables']['differential_supports']
            changed['geometry_volume_max_deviation_m3'] = header_value
            blobs = {}
            metadata, arrays = M.pack_mesh(changed, support_writer=lambda h, raw: blobs.setdefault(h, raw),
                                           budget=self.budget)
            mesh = M.CompactMesh(metadata, arrays, support_reader=lambda h, n: blobs[h],
                                 expected_geometry_id=metadata['geometry_id'], budget=self.budget)
            record = changed
        ref = CS.CompactMeshStoreV3(candidate, scope=self.scope, support_source=source).publish(mesh, producer='b'*64)
        sizes = [partition.support_identity(partition.support_id(i)).canonical_bytes for i in range(partition.support_count)]
        static = [len(M.canonical(value.record() if hasattr(value, 'record') else value))
                  for table, rows in record['support_tables'].items() if table != 'differential_supports'
                  for value in rows.values()]
        del mesh
        source.close()
        partition.close()
        gc.collect()
        self.seal(candidate, ref)
        return ref, partition_ref, sizes, static

    def check_mesh(self, layout, header_value=None):
        ref, partition_ref, sizes, static = self.mesh_store(header_value)
        result = self.census()
        reports = {r['handler']+':'+str(r.get('domain')): r for r in result['records']}
        partition = reports['record-tables:partition-v2']['partition']
        self.assertEqual(partition['supports']['logical'], {'mentions': len(sizes), 'bytes': sum(sizes)})
        self.assertEqual(partition['supports']['unique'], {'nodes': len(sizes), 'bytes': sum(sizes)})
        mesh = reports['mesh-v3:mesh-v3']
        self.assertEqual((mesh['layout'], mesh['support_entries']), (layout, len(sizes)+len(static)))
        self.assertEqual(mesh['shared']['logical'], {'mentions': len(sizes), 'bytes': sum(sizes)})
        self.assertEqual((mesh['shared']['unique']['supports'], mesh['shared']['physical']['bytes']), (len(sizes), 0))
        self.assertEqual(mesh['static']['logical'], {'mentions': len(static), 'bytes': sum(static)})
        schema = ref.identity.record_schema
        self.assertEqual(mesh['static']['physical']['bytes'], result['classes'][schema+'/static.bytes']['physical']['payload_bytes'])
        self.assertEqual(result['classes'][schema+'/static.bytes']['logical']['bytes'], sum(static))
        # Shared supports: mentioned by the partition and by the mesh, stored once (logical > unique).
        self.assertEqual(result['supports'], {'logical': {'mentions': 2*len(sizes), 'bytes': 2*sum(sizes)},
                                              'unique': {'supports': len(sizes), 'bytes': sum(sizes)}})
        rows = {r['root_key']: r for r in result['segment_refs']['rows']}
        self.assertEqual(rows[partition_ref.root_key.snapshot_key]['roles'], ['mesh-v3-support-source'])
        self.assertEqual(rows[ref.root_key.snapshot_key]['roles'], ['catalog-head:0'])
        self.assertEqual(result['files'][0]['unattributed_chunk_rows'], 0)
        return mesh, result

    def test_partition_v2_and_mesh_v3_shared_supports(self):
        mesh, _ = self.check_mesh('v3')
        self.assertEqual(mesh['header_physical_bytes'], 0)

    def test_mesh_v3_header_column_r2(self):
        pair = [hex((1 << 614_115) | 1), hex(1 << 614_104)]   # the IV1 head's 307,067 B header rational
        mesh, _ = self.check_mesh('header-column-r2', pair)
        self.assertGreater(mesh['header_bytes'], 49152)
        self.assertGreater(mesh['header_physical_bytes'], 0)

    def test_heat_r4_ledger_fields_and_receipt(self):
        import private_heat_snapshot_store_r4 as S
        from compact_contracts import SegmentRef
        from heat_ledger_tables import CompactHeatSnapshot
        data = {'cell_ids': ['d'*64, 'd'*64], 'face_ids': ['e'*64], 'q': ['0x2', '0x4'], 'rows': [1, 2]}
        arrays = {'a': np.array([-0., 1.]), 'empty': np.empty(0)}
        candidate = self.begin()
        snapshot = CompactHeatSnapshot.from_components(data, arrays, scope=self.scope)
        receipt = S.save(candidate, snapshot, bindings={'source': 'f'*64, 'call': '1'*64}, scope=self.scope)
        snapshot.close()
        ledger = SegmentRef.from_wire(receipt['metadata']['ledger'])
        self.seal(candidate, ledger)
        result = self.census(heat_receipts=[{'result_id': receipt['metadata']['result_id'], 'receipt': receipt}])
        by_domain = {r.get('domain'): r for r in result['records']}
        self.assertEqual(set(by_domain), {'heat-ledger-r4', 'heat-fields-r4', 'heat-r4'})
        heat = by_domain['heat-r4']
        self.assertEqual((heat['metadata_bytes'], heat['logical_bytes'], heat['shared_mesh']),
                         (receipt['metadata']['metadata_bytes'], receipt['metadata']['logical_bytes'], None))
        self.assertTrue(heat['ledger_already_counted'])
        self.assertEqual(by_domain['heat-ledger-r4']['canonical_bytes'], receipt['metadata']['metadata_bytes'])
        fields = by_domain['heat-fields-r4']['fields']
        self.assertEqual([(f['name'], f['logical_bytes']) for f in fields], [('a', 16), ('empty', 0)])
        c = result['classes']
        self.assertEqual(c[S.FIELDS_SCHEMA+'/field_0']['logical']['bytes'], 16)
        self.assertEqual(c[S.FIELDS_SCHEMA+'/field_1']['logical'], {'leaves': 1, 'mentions': 0, 'bytes': 0,
                                                                     'cross_interval_mentions': 0,
                                                                     'cross_interval_bytes': 0})
        rows = {r['root_key']: r for r in result['segment_refs']['rows']}
        self.assertEqual(rows[ledger.root_key.snapshot_key]['mentions'], 2)   # catalog head + receipt
        self.assertEqual((result['segment_refs']['logical_mentions'], result['segment_refs']['unique']), (3, 2))
        self.assertEqual(result['files'][0]['unattributed_chunk_rows'], 0)

    def test_unknown_record_metadata_is_refused(self):
        import record_tables as RT
        from compact_contracts import ContractError, LogicalIdentity
        from segment_store import SegmentBackend
        candidate = self.begin()
        raw = Q.canonical_json({'schema': RT.SCHEMA, 'profile': 'atlas.unknown-profile.v9'})
        identity = LogicalIdentity('atlas.test.wp0b-bad.v1', sha256(raw).hexdigest(), len(raw))
        ref = SegmentBackend().publish(candidate, record_schema='atlas.test.wp0b-bad.v1', identity=identity,
            metadata=raw, arrays=lambda: iter(()), producer='b'*64, representation_profile='x', scope=self.scope)
        self.seal(candidate, ref)
        with self.assertRaises(ContractError):
            self.census()


if __name__ == '__main__':
    unittest.main()
