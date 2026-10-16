"""Tiny evidence-reuse fixtures, never the real large DB or old cold reader.

Fixture metadata validator conditional logic is the actual original source.
Only the fixture's source/native/database/evidence constants are rebound in its
own temporary files. The public issuer has no such profile override. No fixture
is represented as original historical scientific acceptance.
"""
import ast
from copy import deepcopy
from dataclasses import asdict
import gc
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent/'runtime-integration-r1'
HEAT = HERE.parents[2]/'heat-repair-20261007'
sys.path[:0] = [str(RUNTIME/'runtime-src'), str(RUNTIME/'ram'), str(RUNTIME/'helpers'),
               str(HEAT), str(HEAT/'source/tectonics/tests')]

import numpy as np
from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression, StoreError
import historical_admission as A
import workflow_transfer as W
import native_transfer as N


def write_json(path, record):
    path.write_bytes(A.canonical(record))
    return sha256(path.read_bytes()).hexdigest()


def fixture_graph(execution):
    """Complete graph-shaped metadata only; no claimed physical plan creation."""
    graph = {}
    for name in N._NODES:
        if name.endswith('transport'):
            keys, schema = N._TRANSPORT_KEYS, 'atlas.regional3d-transport-plan.v1'
        elif name.endswith('heat'):
            keys, schema = N._HEAT_KEYS, 'atlas.regional-heat3d-plan.v1'
        elif name == 'native':
            keys, schema = N._NATIVE_KEYS, 'atlas.regional-evolution3d-plan.v1'
        else:
            keys, schema = N._COLLAR_KEYS, 'atlas.regional-collar-plan.v1'
        definition = dict.fromkeys(keys, None)
        definition['schema'] = schema
        if name != 'collar':
            definition['execution'] = execution
        graph[name] = dict(definition=definition, plan_id='0'*64)
    for name in ('native_transport', 'native_heat', 'collar_transport', 'collar_heat'):
        graph[name]['plan_id'] = N._hash(graph[name]['definition'])
    graph['native']['definition']['transport_plan_id'] = graph['native_transport']['plan_id']
    graph['native']['plan_id'] = N._hash(graph['native']['definition'])
    graph['collar']['definition'].update(native_plan_id=graph['native']['plan_id'],
        transport_plan_id=graph['collar_transport']['plan_id'], heat_plan=graph['collar_heat']['definition'],
        volume_map_id='5'*64, padding=[[0, 0], [0, 0], [0, 0]])
    graph['collar']['plan_id'] = N._hash(graph['collar']['definition'])
    return graph


class HistoricalAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='.historical-admission-', dir=HERE.parents[3])
        self.root = Path(self.temporary.name)
        self.budget = WorkBudget(256 << 20)
        self.limits = StoreLimits(chunk_bytes=128, max_array_bytes=1 << 20,
            max_store_bytes=8 << 20, max_manifest_bytes=65536,
            verified_cache_entries=32, sqlite_cache_bytes=65536, codec_workspace_bytes=65536)
        native_root = self.root/'native-composed-r7/tectonics/src/atlas_tectonics'
        native_root.mkdir(parents=True)
        (native_root/'fixture.py').write_text('FIXTURE_ONLY = True\n', encoding='utf8')
        native_sources = {'atlas_tectonics/fixture.py': sha256((native_root/'fixture.py').read_bytes()).hexdigest()}
        self.native_digest = A.digest(native_sources)
        self.helper = self.root/'fixture_helper.py'
        self.helper.write_text('FIXTURE_ONLY = True\n', encoding='utf8')
        helper_sources = {'fixture_helper.py': sha256(self.helper.read_bytes()).hexdigest()}
        self.producer_preparation = {'files': helper_sources}
        producer_preparation_sha = write_json(self.root/'continuation-preparation-r3.json', self.producer_preparation)
        ident, funding = 'a'*64, 'f'*64
        self.old_graph = fixture_graph('6'*64)
        self.current_graph = fixture_graph('7'*64)
        self.root_record = dict(schema=W.WORKFLOW_SCHEMA, kind='root', sequence=0,
            workflow_id=ident, key=W.workflow_key('root', ident), funding_id=funding,
            collar_plan=self.old_graph['collar']['definition'],
            state=dict(result_id='b'*64, fields=dict(time_s=0., parent_id=None),
                       native=dict(time_s=0., parent_state_id=None)),
            native_state_id='c'*64, exterior_state=dict(state_id='d'*64, intervals=0, time_s=0.))
        audit_meta = dict(parent_state_id='c'*64, start_time_s=0., duration_s=2.5)
        self.audit_arrays = {'energy': np.array([1.25, 2.5]), 'mass': np.array([3., 4.])}
        audit = RegionalMechanicalSnapshot(audit_meta, self.audit_arrays)
        self.audit_rows = [dict(name=name, dtype='float64', shape=list(array.shape),
            sha256=sha256(memoryview(array).cast('B')).hexdigest()) for name, array in self.audit_arrays.items()]
        state = dict(result_id='e'*64, fields=dict(time_s=2.5, parent_id='b'*64, plan_id='2'*64),
                     native=dict(time_s=2.5, parent_state_id='c'*64, plan_id='1'*64))
        self.head = dict(schema=W.WORKFLOW_SCHEMA, kind='successor', sequence=1, workflow_id=ident,
            key=W.workflow_key('successor', self.root_record['key']), parent_key=self.root_record['key'],
            parent_digest=W.digest(self.root_record), funding_id=funding, state=state, native_state_id='3'*64,
            advance=dict(duration_s=2.5, source_audit_id=audit.result_id), source_audit=audit_meta,
            exterior_state=dict(state_id='5'*64, parent_state_id='d'*64, time_s=2.5,
                                intervals=1, collar_state_id='e'*64),
            exterior_advance=dict(joined_heat_id='6'*64),
            differential_geometry=dict(interval_id='7'*64),
            differential_partition=dict(partition_id='8'*64),
            differential_certification=dict(endpoint_current_geometry_id='9'*64))
        self.original = self.root/'original.sqlite'
        with ArrayStore(self.original, self.limits, budget=self.budget) as original_store:
            original_store.put(self.root_record['key'], {'initial': np.array([1.])},
                               self.root_record, budget=self.budget)
            fields = {'source-audit:'+name: value for name, value in self.audit_arrays.items()}
            fields['retained-physical-history'] = np.arange(32, dtype=np.float64)
            fields['complete-geometry'] = np.frombuffer(b'geometry', dtype=np.uint8)
            original_store.put(self.head['key'], fields, self.head, budget=self.budget)
            original_store.put('0'*64, {'heat-ledger': np.arange(3, dtype=np.float64)},
                {'fixture': 'complete original heat artifact'}, budget=self.budget)
        database_sha = sha256(self.original.read_bytes()).hexdigest()
        generic_row = dict(name='field', shape=[1], dtype='float64', sha256='0'*64)
        self.expected = dict(workflow_id=ident, root_key=self.root_record['key'], root_metadata=self.root_record,
            head_key=self.head['key'], producer_pid=123,
            store_limits=asdict(self.limits), store_compression=asdict(Compression()),
            collar_result_id='e'*64, native_result_id='3'*64, exterior_state_id='5'*64,
            source_audit_id=audit.result_id, joined_heat_id='6'*64,
            array_records={name: deepcopy(self.audit_rows if name == 'source_audit' else [generic_row])
                for name in ('collar', 'native', 'exterior', 'source_audit', 'full_collar', 'spatial_audit')},
            preparation_ids=dict(owner='1'*64, spatial_owner='2'*64, native=self.old_graph['native']['plan_id'],
                                 collar=self.old_graph['collar']['plan_id'], map='5'*64, funding=funding),
            execution_provenance=dict(execution_identity='6'*64, execution_mode='strict'))
        failure = 'Independent continuation guard: free_memory_floor'
        self.producer = dict(schema='atlas.private.heat-original-connected.r1', status='FAILED',
            stage='actual-heat-endpoint-committed', production_acceptance=False, failure=failure,
            errors=[dict(source='continuation_guard', failure=failure)], pid=123,
            native_source_digest=self.native_digest, native_source={'clone_source_hashes': native_sources},
            preheat_gate={'duration_s': 2.5}, completed_endpoint=self.expected,
            participating_imported_helper_sources=helper_sources,
            preparation_manifest_sha256=producer_preparation_sha)
        original_guard = dict(schema='atlas.private.continuation-guard.r3', status='HARD_STOPPED',
            reason='free_memory_floor', phase='actual-heat-endpoint-committed', workload_exit_confirmed=True,
            cleanup=dict(remaining=[], action_errors=[]), main_output_update={'updated': True},
            parent={'pid': 123}, limits=dict(rss_bytes=12 << 30, free_floor_bytes=1 << 30))
        producer_pin = write_json(self.root/'heat-original-connected-20261013-r9.json', self.producer)
        guard_pin = write_json(self.root/'heat-original-connected-20261013-r9.guard.json', original_guard)
        prep = dict(files=helper_sources, producer_manifest=dict(path='continuation-preparation-r3.json',
                                                               sha256=producer_preparation_sha))
        prep_pin = write_json(self.root/'reader-memory-preparation-r3.json', prep)
        flags = ('measurement_complete', 'saved_checkpoint_checks_passed', 'original_producer_remains_failed',
            'original_finalisation_not_certified', 'input_hashes_unchanged', 'participating_sources_unchanged',
            'consumer_database_unchanged', 'native_operations_unchanged', 'snapshot_count_unchanged',
            'store_token_unchanged', 'all_six_field_groups_identical')
        self.reader = dict.fromkeys(flags, True)
        self.reader.update(schema='atlas.private.reader-memory-measurement.r3',
            status='PASS_COMPLETE_READER_MEMORY_MEASUREMENT_ONLY', checkpoint_acceptance=False,
            production_acceptance=False, errors=[], final_reserved_bytes=0, native_source_digest=self.native_digest,
            recovered_endpoint=self.expected, database_sha256=database_sha,
            preparation_manifest_sha256=prep_pin, recovery_account_checks=dict(attempted=1, completed=1),
            recovery_accounts={'status': 'PASS_PERSISTED_OPERAND_ACCOUNTS_ONLY'}, pid=456,
            recovery_interval=dict(intervals=1, start_time_s=0., duration_s=2.5, endpoint_time_s=2.5,
                                   exterior_time_s=2.5, global_background_advanced=False),
            workflow_id=ident, endpoint={name: self.expected[name] for name in
                ('collar_result_id', 'native_result_id', 'exterior_state_id', 'source_audit_id')},
            heat_read_memory=dict(metered=True, failed_call=None, returned_call_count=1,
                returned_calls=[dict(scope='fresh-process-recovery-reopen', closed=True, failed=False, refusal=None)]),
            final_logical_budget=dict(reserved_bytes=0, refusals=0),
            participating_imported_helper_sources=helper_sources,
            inputs={str(self.original): database_sha,
                str(self.root/'heat-original-connected-20261013-r9.json'): producer_pin,
                str(self.root/'heat-original-connected-20261013-r9.guard.json'): guard_pin,
                str(self.root/'continuation-preparation-r3.json'): producer_preparation_sha})
        write_json(self.root/'reader-memory-20261013-r3.json', self.reader)
        reader_guard = dict(schema='atlas.private.continuation-guard.r3', status='STOPPED', reason=None,
            workload_exit_confirmed=True, workload_exit_code=0, parent={'pid': 456},
            cleanup=dict(action_errors=[], remaining=[]), limits=dict(rss_bytes=10 << 30, free_floor_bytes=1 << 30))
        write_json(self.root/'reader-memory-20261013-r3.guard.json', reader_guard)
        pins = {name: sha256((self.root/name).read_bytes()).hexdigest() for name, _ in A._REVIEWED_ORIGINAL.evidence}
        sources = []
        for name, _ in A._REVIEWED_ORIGINAL.metadata_sources:
            source = (HEAT/(name+'.py')).read_text(encoding='utf8')
            if name == 'private_heat_recovery_consumer_r4':
                source = source.replace("NATIVE_DIGEST = '746eea53c8dc9c9c89c8f7db8474e579fd5d2a2b919615b287358ddd4cb29d28'",
                                        'NATIVE_DIGEST = '+repr(self.native_digest))
            if name == 'private_heat_recovery_admission_r1':
                node = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign) and
                            any(isinstance(t, ast.Name) and t.id == 'PINS' for t in n.targets))
                lines = source.splitlines(keepends=True)
                source = ''.join(lines[:node.lineno-1])+'PINS = '+repr(pins)+'\n'+''.join(lines[node.end_lineno:])
                source = source.replace("DATABASE_SHA = '3f70c26de17535a96b7ddd494aee72900decee272ae0f88edab3a42af1548899'",
                                        'DATABASE_SHA = '+repr(database_sha))
            path = self.root/(name+'.py')
            path.write_text(source, encoding='utf8', newline='\n')
            sources.append((name, sha256(path.read_bytes()).hexdigest()))
        self.review = A._Review(tuple(sources), tuple(pins.items()), 'original.sqlite', database_sha)
        copied = self.root/'working.sqlite'
        shutil.copyfile(self.original, copied)
        self.copied = ArrayStore(copied, self.limits, budget=self.budget)
        self.store = A._open_readonly(self.original, self.limits, Compression(), self.budget)

    def tearDown(self):
        self.store.close()
        self.copied.close()
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temporary.cleanup()

    def admit(self, **changes):
        args = dict(root=self.root, review=self.review, budget=self.budget,
                    check=lambda: None)
        args.update(changes)
        return A._admit(self.store, **args)

    def test_genuine_byte_bound_protocol_issues_only_historical_admission(self):
        before = self.budget.reserved_bytes
        calls = []
        original = A._array_bytes
        def stream(store, description, *args, **kwargs):
            calls.append(description)
            return original(store, description, *args, **kwargs)
        with patch.object(self.store, 'get', side_effect=AssertionError('whole-payload get forbidden')), \
                patch.object(A, '_array_bytes', side_effect=stream):
            admission = self.admit()
        self.assertIs(type(admission), W.HistoricalEndpointAdmission)
        self.assertEqual(len(calls), len(self.audit_arrays))
        capsule, binding = admission.record(), admission.binding()
        self.assertEqual(capsule['chain_metadata'], [self.root_record, self.head])
        self.assertEqual(len(capsule['snapshot_manifests']), 3)
        self.assertEqual(capsule['validation_receipt']['record'], self.reader)
        self.assertEqual(binding['capsule_sha256'], W.digest(capsule))
        self.assertEqual(binding['original_database_path'], str(self.original))
        self.assertEqual(binding['origin']['endpoint_lineage_sha256'], W.digest([self.root_record, self.head]))
        self.assertTrue(binding['historical_scientific_checks_reused'])
        self.assertFalse(binding['new_runtime_accepted'])
        self.assertFalse(binding['continuation_authorised'])
        self.assertEqual(capsule['producer']['original_status'], 'FAILED')
        self.assertEqual(admission._source_audit.result_id, self.expected['source_audit_id'])
        self.assertLess(self.budget.peak_reserved_bytes, 16 << 20)
        del admission
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_escaped_audit_array_retains_funding_and_exact_original_metadata(self):
        admission = self.admit()
        view = admission._source_audit.array('energy')
        np.testing.assert_array_equal(view, self.audit_arrays['energy'])
        before = self.budget.reserved_bytes
        del admission
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)
        del view
        gc.collect()

    def test_modified_pinned_evidence_is_not_rescued_by_pass_flags(self):
        self.reader['all_six_field_groups_identical'] = False
        write_json(self.root/'reader-memory-20261013-r3.json', self.reader)
        with self.assertRaises(A.HistoricalAdmissionRefused):
            self.admit()

    def test_actual_original_validator_rejects_incomplete_guard_and_accounting(self):
        with A._metadata_validator(self.root, self.review, lambda: None) as validator:
            original_guard = json.loads((self.root/'heat-original-connected-20261013-r9.guard.json').read_bytes())
            guardian = json.loads((self.root/'reader-memory-20261013-r3.guard.json').read_bytes())
            for field, value in (('measurement_complete', False), ('final_reserved_bytes', 1),
                                 ('recovery_account_checks', {'attempted': 1, 'completed': 0})):
                changed = dict(self.reader, **{field: value})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    validator.validate_records(self.producer, original_guard, changed, guardian, 789)
            with self.assertRaises(ValueError):
                validator.validate_records(self.producer, original_guard, self.reader,
                                           dict(guardian, workload_exit_confirmed=False), 789)

    def test_source_drift_or_added_native_member_refuses(self):
        self.helper.write_text('FIXTURE_ONLY = False\n', encoding='utf8')
        with self.assertRaises(A.HistoricalAdmissionRefused):
            self.admit()
        self.helper.write_text('FIXTURE_ONLY = True\n', encoding='utf8')
        (self.root/'native-composed-r7/tectonics/src/atlas_tectonics/extra.py').write_text('x=1\n')
        with self.assertRaises(A.HistoricalAdmissionRefused):
            self.admit()

    def test_original_readonly_and_copy_cannot_issue_admission(self):
        before = sha256(self.original.read_bytes()).hexdigest()
        with self.assertRaises(sqlite3.OperationalError):
            self.store._db.execute('DELETE FROM chunks')
        with self.assertRaises(A.HistoricalAdmissionRefused):
            A._admit(self.copied, root=self.root, review=self.review, budget=self.budget, check=lambda: None)
        self.assertEqual(before, sha256(self.original.read_bytes()).hexdigest())

    def test_stable_original_admission_survives_successor_copy_and_connection_changes(self):
        first = self.admit()
        record, binding = bytes(first._record), bytes(first._binding)
        self.copied.put('9'*64, {'new': np.array([7.])}, {'successor': True}, budget=self.budget)
        self.store.close()
        self.store = A._open_readonly(self.original, self.limits, Compression(), self.budget)
        second = self.admit()
        self.assertEqual(record, second._record)
        self.assertEqual(binding, second._binding)
        self.assertEqual(second.record()['source']['store_token']['schema'],
                         'atlas.historical-store-content-token.v1')
        self.assertNotIn('recorder', second.binding())

    def test_fresh_fixture_process_reissues_identical_historical_bytes(self):
        admission = self.admit()
        profile = dict(metadata_sources=self.review.metadata_sources, evidence=self.review.evidence,
                       database_name=self.review.database_name, database_sha256=self.review.database_sha256)
        code = '''
import gc,json,sys
from pathlib import Path
import test_historical_admission as T
A=T.A
root=Path(sys.argv[1]); profile=json.loads(sys.argv[2])
profile['metadata_sources']=tuple(map(tuple,profile['metadata_sources']))
profile['evidence']=tuple(map(tuple,profile['evidence']))
budget=T.WorkBudget(256 << 20)
limits=T.StoreLimits(**json.loads(sys.argv[3]))
with A._open_readonly(root/'original.sqlite', limits, T.Compression(), budget) as store:
    admission=A._admit(store,root=root,review=A._Review(**profile),budget=budget,check=lambda:None)
    result=dict(record=T.sha256(admission._record).hexdigest(),binding=T.sha256(admission._binding).hexdigest())
    del admission
gc.collect()
result['reserved_bytes']=budget.reserved_bytes
print(json.dumps(result))
'''
        process = subprocess.run([sys.executable, '-B', '-c', code, str(self.root),
            A.canonical(profile).decode(), A.canonical(asdict(self.limits)).decode()],
            cwd=HERE, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), dict(record=sha256(admission._record).hexdigest(),
            binding=sha256(admission._binding).hexdigest(), reserved_bytes=0))

    def test_selected_arrays_own_admission_and_reject_changed_chunks_or_manifest(self):
        admission = self.admit()
        key = self.head['key']
        name = 'retained-physical-history'
        self.copied.put('9'*64, {'new': np.array([7.])}, {'successor': True}, budget=self.budget)
        with patch.object(self.copied, 'get', side_effect=AssertionError('whole payload forbidden')):
            result = A.read_selected_arrays(self.copied, key, [name], admission=admission,
                                           budget=self.budget, check=lambda: None)
        view = result[name][1:]
        np.testing.assert_array_equal(view, np.arange(1, 32, dtype=np.float64))
        self.assertFalse(view.flags.writeable)
        retained = self.budget.reserved_bytes
        del result, admission
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, retained)
        del view
        gc.collect()
        admission = self.admit()
        with self.copied._read_scope():
            chunk = self.copied._manifest(key)['arrays'][name]['chunks'][0]
        self.copied._db.execute('UPDATE chunks SET payload=? WHERE id=?', (b'changed', chunk))
        with self.assertRaises(StoreError):
            A.read_selected_arrays(self.copied, key, [name], admission=admission,
                                   budget=self.budget, check=lambda: None)

    def test_selected_arrays_refuse_changed_metadata_even_with_unchanged_payload(self):
        admission = self.admit()
        key = self.head['key']
        with self.copied._read_scope():
            manifest = self.copied._manifest(key)
        manifest['metadata']['changed'] = True
        raw = A.canonical(manifest)
        self.copied._db.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?',
                                (raw, sha256(raw).hexdigest(), key))
        with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'manifest differs'):
            A.read_selected_arrays(self.copied, key, ['retained-physical-history'],
                admission=admission, budget=self.budget, check=lambda: None)

    def test_selected_array_cancelled_frame_retains_allocations_until_released(self):
        admission = self.admit()
        before = self.budget.reserved_bytes
        held = None
        def fail():
            from concurrent.futures import CancelledError
            raise CancelledError('held fixture')
        try:
            A.read_selected_arrays(self.copied, self.head['key'], ['retained-physical-history'],
                                   admission=admission, budget=self.budget, check=fail)
        except BaseException as error:
            held = error
        self.assertIsNotNone(held)
        self.assertGreater(self.budget.reserved_bytes, before)
        held = None
        gc.collect()
        self.assertEqual(self.budget.reserved_bytes, before)

    def test_original_database_change_refuses_even_when_copy_is_intact(self):
        with self.original.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(A.HistoricalAdmissionRefused):
            self.admit()

    def test_late_source_change_refuses_before_capability_issue(self):
        original = A._audit
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            self.helper.write_text('changed after audit\n', encoding='utf8')
            return result
        with patch.object(A, '_audit', side_effect=changed), self.assertRaises(A.HistoricalAdmissionRefused):
            self.admit()

    def test_cancel_and_public_guard_refusal_never_open_historical_store(self):
        def cancelled():
            from concurrent.futures import CancelledError
            raise CancelledError('fixture cancellation')
        from concurrent.futures import CancelledError
        with self.assertRaises(CancelledError):
            self.admit(check=cancelled)
        with self.assertRaises(A.HistoricalAdmissionRefused):
            A.admit_historical_endpoint(self.store, execution=object(), budget=self.budget, guard=object())

    def test_metadata_source_pin_and_name_occupation_refuse(self):
        path = self.root/'private_heat_recovery_admission_r1.py'
        with path.open('a', encoding='utf8') as stream:
            stream.write('\n# drift\n')
        with self.assertRaises(A.HistoricalAdmissionRefused):
            self.admit()

    def test_loaded_guard_code_cannot_borrow_unchanged_source_hash(self):
        path = self.root/'fenced_guard.py'
        raw = b'def check():\n    return 17\nclass Guard:\n    def check(self):\n        return 23\n'
        path.write_bytes(raw)
        module = types.ModuleType('fixture_fenced_guard')
        module.__file__ = str(path)
        exec(compile(raw, str(path), 'exec'), module.__dict__)
        pin = sha256(raw).hexdigest()
        A._loaded_source_fence(module, pin, lambda: None)
        module.Guard.check = lambda self: 99
        with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'loaded guarded function'):
            A._loaded_source_fence(module, pin, lambda: None)

    def test_plan_reconstruction_uses_independently_bound_ids_and_nested_heat(self):
        admission = self.admit()
        original = deepcopy(self.current_graph)
        found = A.derive_historical_plan_graph(self.current_graph, admission)
        self.assertEqual(found, self.old_graph)
        self.assertEqual(self.current_graph, original)
        changed = deepcopy(self.current_graph)
        changed['native_heat']['definition']['energy_relative_tolerance'] = 123
        changed['native_heat']['plan_id'] = N._hash(changed['native_heat']['definition'])
        with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'native heat'):
            A.derive_historical_plan_graph(changed, admission)
        changed = deepcopy(self.current_graph)
        changed['native']['definition']['material'] = {'changed': True}
        changed['native']['plan_id'] = N._hash(changed['native']['definition'])
        changed['collar']['definition']['native_plan_id'] = changed['native']['plan_id']
        changed['collar']['plan_id'] = N._hash(changed['collar']['definition'])
        with self.assertRaisesRegex(A.HistoricalAdmissionRefused, 'plan IDs'):
            A.derive_historical_plan_graph(changed, admission)


if __name__ == '__main__':
    unittest.main(verbosity=2)
