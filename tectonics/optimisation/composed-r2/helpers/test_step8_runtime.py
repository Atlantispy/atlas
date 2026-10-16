"""Step 8 composed admission and real compact-envelope controls.

Synthetic storage/component evidence only; no real historical migration/IV2.
The complete owner fixture is kept separate from these bounded controls.
"""
import ast
from copy import deepcopy
import gc
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
COMPACT = HERE / 'compact-geometry-r1'
RUNTIME = HERE.parent / 'runtime-integration-r1' / 'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import numpy as np
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import StoreConflict
from compact_contracts import ContractError
from content_cache import create_retained_scope
from compact_restart_store import CompactRestartStore
import compact_restart_patch as P
import workflow_transfer as W
import spatial_records_patch as S
import spatial_workflow_patch as Y
import partition_workflow_transform as PT
import spatial_validation_patch as V
from segment_store import SegmentView
import partition_tables as T
from partition_store import publish_partition_v2
from test_partition_tables import tiny_partition, D
from test_run_prepared_restart import SuccessorWorkflow
import run_prepared_restart as R


def key(value):
    return sha256(value.encode()).hexdigest()


def step6_workflow_source():
    source = (RUNTIME / 'atlas_tectonics/integration_regional_workflow.py').read_text(encoding='utf8')
    source = Y.transform(W.nonzero_cursor_source(source))
    source = PT.transform_v2(PT.transform(source))
    source = Y.transform_v3(source)
    return V.workflow_source(S.transform(source))


def compose_live_fixture(directory):
    """Extend the existing actual-owner fixture in a new test-only tree."""
    import test_partition_workflow_fresh_process as PF
    import exchange_record_patch as E
    import mimetic_patch as MP
    import exterior_mesh_patch as EM
    PF.compose(directory)
    package = directory / 'src/atlas_tectonics'
    workflow = package / 'integration_regional_workflow.py'
    source = PT.transform_v2(workflow.read_text(encoding='utf8'))
    workflow.write_text(P.workflow_source(V.workflow_source(S.transform(Y.transform_v3(source)))), encoding='utf8')
    owner = package / 'integration_spatial_owner.py'
    owner.write_text(V.owner_source(E.holder_source(owner.read_text(encoding='utf8'))), encoding='utf8')
    for filename, transform in (
            ('integration_mimetic_heat.py', MP.mimetic_source),
            ('integration_extremum_heat.py', MP.extremum_source),
            ('integration_exterior_mesh.py', EM.transform)):
        path = package / filename
        path.write_text(transform(path.read_text(encoding='utf8')), encoding='utf8')
    # Explicit local helper package: both children import identical saved bytes.
    helpers = directory / 'helpers'
    for source in COMPACT.glob('*.py'):
        if not source.name.startswith(('test_', 'probe_')):
            shutil.copy2(source, helpers / source.name)
    for name in ('test_spatial_workflow_patch.py', 'test_partition_workflow_fresh_process.py'):
        shutil.copy2(COMPACT / name, helpers / name)
    for name in ('compact_restart_store.py', 'compact_restart_patch.py', 'test_step8_materialise.py',
                 'test_workflow_fresh_process.py', 'run_prepared_restart.py', 'reopen_prepared_restart.py',
                 'initial_workload.py', 'runtime_compatibility.py'):
        shutil.copy2(HERE / name, helpers / name)
    return {str(path.relative_to(directory)): sha256(path.read_bytes()).hexdigest()
            for folder in (directory / 'src', helpers) for path in sorted(folder.rglob('*.py'))}


class TransformTests(unittest.TestCase):
    def test_complete_step6_layer_compiles_once_and_preserves_cold_validation(self):
        before = step6_workflow_source()
        after = P.workflow_source(before)
        compile(after, '<step8-native-workflow>', 'exec')
        self.assertEqual(after.count('import compact_restart_patch as _RESTART'), 1)
        self.assertEqual(after.count('_RESTART.postpublication(self, parent, row, cancel=cancel)'), 1)
        def method(text, name):
            tree = ast.parse(text)
            cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'CollarWorkflow')
            return ast.dump(next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == name))
        for name in ('_refresh', '_saved_certification_expected', '_check_certification_records'):
            self.assertEqual(method(before, name), method(after, name), name)
        with self.assertRaisesRegex(ValueError, 'seams differ'):
            P.workflow_source(after)
        with self.assertRaisesRegex(ValueError, 'seams differ'):
            P.workflow_source(before.replace('_COMPACT_RECORDS.publication_check', '_missing.publication_check'))

    def test_store_guard_rejects_lookalikes(self):
        self.assertFalse(P.accepts_store(SimpleNamespace(scope=object(), readonly=False)))


class PostpublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='step8-runtime-', dir=HERE.parents[3] / '_t')
        self.path = Path(self.temp.name)
        self.budget = WorkBudget(1 << 30)
        self.scope = create_retained_scope(self.budget, process_epoch='step8-runtime')
        self.store = CompactRestartStore.create_migration(self.path / 'catalog.json', workflow_id=key('catalog'),
            scope=self.scope, producer_identity=key('producer'), runtime_identity=key('runtime'))
        body, rows = tiny_partition(self.budget, count=2, depth=0)
        partition = T.pack_partition_v2(body, iter(rows), expected_partition_id=D._record_hash(body), scope=self.scope)
        self.partition = publish_partition_v2(self.store, partition, producer=key('producer'))
        partition.close()
        self.root = dict(schema=W.WORKFLOW_SCHEMA, kind='migrated-root', key=key('root'),
            sequence=3, workflow_id=key('workflow'), funding_id=key('funding'),
            state=dict(fields=dict(time_s=12.5)))
        self.row = dict(schema=W.WORKFLOW_SCHEMA, kind='successor', key=W.workflow_key('successor', self.root['key']),
            sequence=4, parent_key=self.root['key'], parent_digest=W.digest(self.root),
            workflow_id=self.root['workflow_id'], funding_id=self.root['funding_id'],
            state=dict(fields=dict(time_s=25.)),
            differential_partition={'compact_partition': self.partition.to_wire()})
        refs = S.publish_records(self.store, {
            'state': {'cells': [{'cell_id': key('cell'), 'q': ['0x1', '0x3']}]},
            'mesh': {'cells': []}, 'exchange': {'exact': ['0x5', '0x7']},
            'graph': {'faces': []}, 'transport': {'fields': []}, 'heat': {'fixture': True}},
            budget=self.budget, source_producer={'fixture': 'step8-runtime'})
        self.row['exterior_state'] = {'record_blobs': {k: refs[k] for k in ('state', 'mesh')}}
        self.row['exterior_advance'] = {'record_blobs': {k: refs[k] for k in ('exchange', 'graph', 'transport', 'heat')}}
        self.store.put(self.root['key'], {'marker': np.empty(0, dtype='u1')}, self.root)
        self.workflow = SuccessorWorkflow(self.store, W.canonical(self.root), self.row,
            time_s=25., funding_id=self.root['funding_id'], workflow_id=self.root['workflow_id'])
        self.workflow._budget = self.budget
        self.workflow._token = 'unverified'

    def tearDown(self):
        self.workflow = None
        self.store.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0, self.budget.statistics())
        self.temp.cleanup()

    def publish(self, row=None):
        value = self.row if row is None else row
        self.store.put(value['key'], {'marker': np.empty(0, dtype='u1')}, value)
        self.workflow._head = deepcopy(value)

    def test_actual_compact_refs_and_eleven_runner_checks_are_metadata_only(self):
        self.publish()
        token = self.store.change_token()
        before = dict(workflow_id=self.root['workflow_id'], funding_id=self.root['funding_id'],
                      head=self.root['key'], intervals=3, time_s=12.5)
        with (patch.object(SegmentView, 'read', side_effect=AssertionError('payload read')),
                patch.object(SegmentView, 'iter', side_effect=AssertionError('payload iteration')),
                patch.object(CompactRestartStore, 'get', side_effect=AssertionError('native payload expansion'))):
            P.postpublication(self.workflow, self.root, self.row)
            after = R._successor_checks(self.workflow, store=self.store, before=before,
                parent=self.root, root_bytes=self.workflow._root, budget=self.budget)
        self.assertEqual(self.workflow._token, token)
        self.assertEqual(after['head'], self.row['key'])
        self.assertEqual(len(R.SUCCESSOR_CHECKS), 11)

    def test_corrupt_reference_refuses_before_token_adoption(self):
        bad = deepcopy(self.row)
        bad['exterior_state']['record_blobs']['state']['sha256'] = '0' * 64
        self.publish(bad)
        with self.assertRaises(ContractError):
            P.postpublication(self.workflow, self.root, bad)
        self.assertEqual(self.workflow._token, 'unverified')

    def test_further_successor_refuses_before_token_adoption(self):
        self.publish()
        self.store.put(W.workflow_key('successor', self.row['key']), {'marker': np.empty(0, dtype='u1')}, {'later': True})
        with self.assertRaisesRegex(StoreConflict, 'envelope differs'):
            P.postpublication(self.workflow, self.root, self.row)
        self.assertEqual(self.workflow._token, 'unverified')

    def test_changed_store_during_manifest_validation_refuses(self):
        self.publish()
        ordinary = W.compact_references_verified
        def changed(*args, **kwargs):
            result = ordinary(*args, **kwargs)
            self.store.put(key('concurrent-effect'), {'marker': np.empty(0, dtype='u1')}, {'added': True})
            return result
        with patch.object(W, 'compact_references_verified', changed):
            with self.assertRaisesRegex(StoreConflict, 'changed during bounded validation'):
                P.postpublication(self.workflow, self.root, self.row)
        self.assertEqual(self.workflow._token, 'unverified')

    def test_actual_transformed_native_entry_accepts_only_the_explicit_store_type(self):
        # Compile the real native entrypoint with all required source layers.
        # This intentionally stops at missing-root admission, before any owner.
        namespace = {'__name__': 'atlas_tectonics._step8_workflow_fixture', '__package__': 'atlas_tectonics'}
        exec(compile(P.workflow_source(step6_workflow_source()), '<step8-native-workflow>', 'exec'), namespace)
        cls = namespace['RegionalWorkflow']
        with self.assertRaisesRegex(Exception, 'regional workflow root is absent or incompatible'):
            cls.open(self.store, key('missing'), None, budget=self.budget)
        with self.assertRaisesRegex(Exception, 'store|Store'):
            cls.open(SimpleNamespace(scope=self.scope), key('missing'), None, budget=self.budget)


class FreshProcessTests(unittest.TestCase):
    def test_actual_compact_root_publish_and_readonly_cold_reopen(self):
        with tempfile.TemporaryDirectory(prefix='step8-live-', dir=HERE.parents[3] / '_t') as temporary:
            directory = Path(temporary)
            sources = compose_live_fixture(directory)
            script = '''
import faulthandler, gc, json, os, sys
from pathlib import Path
faulthandler.dump_traceback_later(120, repeat=True)
directory = Path(sys.argv[2])
sys.path[:0] = [str(directory/'helpers'), str(directory/'src'), sys.argv[3], sys.argv[4]]
import test_workflow_fresh_process as F
F.HERE = Path(sys.argv[3])
F.INTEGRATION = F.HERE.parent/'runtime-integration-r1'
F.PACKAGE = F.INTEGRATION/'runtime-src/atlas_tectonics'
F.HEAT = F.HERE.parents[2]/'heat-repair-20261007'
TS, TG = F.initialise_child(directory)
from test_step8_materialise import step8_live_child
budget = TS.SpatialTransferTests.budget
result = step8_live_child(sys.argv[1], directory, TS, TG)
TS.SpatialTransferTests.tearDownClass()
TS.SpatialTransferTests.collar = TS.SpatialTransferTests.native = None
TS.SpatialTransferTests.old = TS.SpatialTransferTests.current = None
gc.collect()
assert budget.reserved_bytes == 0, budget.statistics()
print('STEP8_LIVE_RESULT '+json.dumps(dict(pid=os.getpid(), reserved_after_close=0, result=result),
    sort_keys=True, separators=(',', ':')), flush=True)
'''
            reports = []
            for operation in ('publish', 'reopen'):
                try:
                    completed = subprocess.run([sys.executable, '-B', '-c', script, operation,
                        str(directory), str(HERE), str(COMPACT)], capture_output=True, text=True, timeout=360,
                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
                except subprocess.TimeoutExpired as error:
                    def tail(value):
                        return (value.decode(errors='replace') if isinstance(value, bytes) else value or '')[-15000:]
                    self.fail(f'{operation} child exceeded 360 seconds\n{tail(error.stdout)}\n{tail(error.stderr)}')
                self.assertEqual(completed.returncode, 0, completed.stdout[-2000:] + completed.stderr[-10000:])
                lines = [line for line in completed.stdout.splitlines() if line.startswith('STEP8_LIVE_RESULT ')]
                self.assertEqual(len(lines), 1, completed.stdout[-2000:])
                reports.append(json.loads(lines[0].removeprefix('STEP8_LIVE_RESULT ')))
            self.assertNotEqual(reports[0]['pid'], reports[1]['pid'])
            self.assertEqual(reports[0]['result'], reports[1]['result'])
            for path, identity in sources.items():
                self.assertEqual(sha256((directory / path).read_bytes()).hexdigest(), identity, path)


if __name__ == '__main__':
    unittest.main()
