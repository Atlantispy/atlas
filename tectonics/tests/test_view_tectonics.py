"""Bounded saved-time adapter guards; retained native data is opt-in only.

SPDX-License-Identifier: AGPL-3.0-only
No simulation, checkpoint migration or writes to the nominated source run.
"""
from contextlib import closing, contextmanager, nullcontext
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import read_tectonics as reader
import tectonics_job as jobs
import view_tectonics as view


def file_hashes(root):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.iterdir() if path.is_file()}


class MetadataStore:
    """Only the metadata and zero-length checkpoint markers exist in this store."""

    def __init__(self, completed=3):
        context = dict(world_id='test-world', snapshot_id='test-snapshot',
                       calendar_id='test-calendar', spatial_frame_id='test-frame',
                       vertical_reference='test-datum', scenario_id='test-scenario')
        self.definition = dict(context=context, schedule=[dict(time_s=10.), dict(time_s=20.)])
        self.plan_id = view._hash(self.definition)
        self.records, self.arrays, self.products, self.keys, self.get_calls = {}, {}, [], [], []
        for index, time_s in enumerate((0., 10., 20.)):
            key = view._hash(dict(schema='atlas.w12-column-checkpoint.v1',
                                  plan_id=self.plan_id, index=index))
            self.keys.append(key)
            product = dict(schema='atlas.tectonics-product.v1',
                producer='atlas-tectonics-column-assembly-v1', route='w04-support.v1',
                execution_id='test-execution', context=deepcopy(context),
                definition=deepcopy(self.definition), plan_id=self.plan_id,
                output_index=index, time_s=time_s, epoch_id='test-epoch',
                source_status='WORKING NON-CANON', native_state_id=str(index + 1) * 64,
                native_state_descriptor=dict(binding=dict(reference_time_s=0.),
                    parent_state_id=None if index == 0 else str(index) * 64),
                restart=dict(checkpoint_id=key), fields={})
            product['product_id'] = view._hash(product)
            self.products.append(product)
            if index < completed:
                self.records[product['product_id']] = product
                self.records[key] = dict(schema='atlas.w12-column-checkpoint.v1',
                    plan_id=self.plan_id, output_index=index, product_id=product['product_id'])
                self.arrays[key] = {'commit': np.empty((0,), dtype='u1')}

    def reseal(self, index):
        """Keep identity consistent so a semantic corruption reaches its own guard."""
        product = self.products[index]
        old = product.pop('product_id')
        self.records.pop(old, None)
        product['product_id'] = view._hash(product)
        self.records[product['product_id']] = product
        self.records[self.keys[index]]['product_id'] = product['product_id']

    def metadata(self, key):
        return self.records.get(key)

    def get(self, key, *, budget):
        self.get_calls.append(key)
        return self.arrays.get(key)


class FakeExecution:
    identity = 'test-execution'

    def __init__(self):
        self.verified = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def verify(self):
        self.verified = True


class ViewGuards(unittest.TestCase):
    @contextmanager
    def saved(self, store, anchor=2):
        budget = Mock()
        budget.statistics.return_value = {'peak_reserved_bytes': 0}
        execution = FakeExecution()
        with patch.object(view, '_adapters', return_value={'test.py': 'a' * 64}), \
             patch.object(view, '_inputs', return_value=(Path('unused'), {'cells': 8}, store.products[anchor])), \
             patch.object(view, '_store', return_value=nullcontext((store, budget))), \
             patch('atlas_tectonics.reuse.ExecutionContext', return_value=execution):
            yield execution

    def test_catalogue_reads_only_committed_markers_and_does_not_claim_array_verification(self):
        store = MetadataStore()
        with self.saved(store) as execution, patch.object(reader, '_result') as result:
            answer = view.response('unused')
        self.assertEqual(answer['status'], 'ok', answer)
        self.assertEqual(store.get_calls, store.keys)
        self.assertEqual([item['availability'] for item in answer['catalogue']['times']], ['committed'] * 3)
        self.assertEqual(answer['capabilities'], dict(catalogue=True, section=True, generate=False, globe=False))
        self.assertFalse(answer['provenance']['selected_output_full_verification'])
        self.assertIn('checked on selection', answer['catalogue']['verification'])
        self.assertNotIn('view', answer)
        self.assertTrue(execution.verified)
        result.assert_not_called()

    def test_missing_final_time_is_visible_and_selection_never_starts_work(self):
        store = MetadataStore(completed=2)
        with self.saved(store, anchor=1), patch.object(reader, '_result') as result:
            answer = view.response('unused')
            self.assertEqual(answer['status'], 'ok', answer)
            self.assertEqual(answer['catalogue']['times'][2], dict(output_index=2,
                time_s=20., availability='missing', product_id=None))
            missing = view.response('unused', action='section', output_index=2)
        self.assertEqual(missing['error']['code'], 'MISSING_OUTPUT')
        self.assertNotIn('view', missing)
        result.assert_not_called()

    def test_gaps_tampered_metadata_context_parent_time_and_commit_refuse(self):
        for corruption in ('gap', 'identity', 'context', 'execution', 'parent', 'time', 'marker', 'commit'):
            with self.subTest(corruption=corruption):
                store = MetadataStore()
                if corruption == 'gap':
                    del store.records[store.keys[1]]
                elif corruption == 'identity':
                    store.products[1]['time_s'] = 11.
                elif corruption in ('context', 'execution', 'parent', 'time'):
                    product = store.products[1]
                    if corruption == 'context':
                        product['context']['world_id'] = 'other-world'
                    elif corruption == 'execution':
                        product['execution_id'] = 'other-runtime'
                    elif corruption == 'parent':
                        product['native_state_descriptor']['parent_state_id'] = 'f' * 64
                    else:
                        product['time_s'] = 11.
                    store.reseal(1)
                elif corruption == 'marker':
                    store.records[store.keys[1]]['output_index'] = 2
                else:
                    store.arrays[store.keys[1]] = {'commit': np.empty((1,), dtype='u1')}
                with self.saved(store), patch.object(reader, '_result') as result:
                    answer = view.response('unused')
                self.assertEqual(answer['status'], 'error', answer)
                self.assertNotIn('catalogue', answer)
                self.assertNotIn('view', answer)
                result.assert_not_called()

    def test_selection_and_source_plan_guards_refuse_before_full_decode(self):
        invalid = [dict(action='generate'), dict(field='temperature'), dict(output_index=-1),
            dict(output_index=3), dict(output_index=True), dict(output_index=1.0),
            dict(cell_start=-1), dict(cell_start=True), dict(cell_start=8),
            dict(cell_start=2, cell_stop=2), dict(cell_stop=9), dict(cell_stop=False),
            dict(expected_plan_id='../plan'), dict(expected_plan_id='A' * 64)]
        for selection in invalid:
            with self.subTest(selection=selection), self.saved(MetadataStore()), \
                 patch.object(reader, '_result') as result:
                arguments = dict(action='section', **{k: v for k, v in selection.items() if k != 'action'})
                arguments['action'] = selection.get('action', 'section')
                answer = view.response('unused', **arguments)
                self.assertEqual(answer['error']['code'], 'INVALID_SELECTION', answer)
                result.assert_not_called()
        with self.saved(MetadataStore()), patch.object(reader, '_result') as result:
            answer = view.response('unused', expected_plan_id='0' * 64)
        self.assertEqual(answer['error']['code'], 'CONTEXT_MISMATCH')
        result.assert_not_called()

    def test_section_decodes_one_output_and_passes_only_selected_field_and_interval(self):
        store = MetadataStore()
        native = dict(product_id=store.products[1]['product_id'], native_state_id='2' * 64,
                      time_s=10., epoch_id='test-epoch', explanation={'fixture': True},
                      provenance={'verified': {'product': True}})
        geometry = dict(selection=dict(cell_start=2, cell_stop=5),
                        field=dict(name='porosity', values=[[.25, .5, .75]]))
        with self.saved(store), patch.object(reader, '_result', return_value=native) as result, \
             patch('w12_section_geometry.build_section', return_value=geometry) as build:
            answer = view.response('unused', action='section', output_index=1,
                field='porosity', cell_start=2, cell_stop=5, expected_plan_id=store.plan_id)
        self.assertEqual(answer['status'], 'ok', answer)
        result.assert_called_once()
        self.assertIs(result.call_args.args[0], store)
        self.assertIs(result.call_args.args[1], store.products[1])
        build.assert_called_once_with(native, field='porosity', cell_start=2, cell_stop=5)
        self.assertEqual(answer['view']['output_index'], 1)
        self.assertEqual(answer['view']['geometry'], geometry)
        self.assertTrue(answer['provenance']['selected_output_full_verification'])
        self.assertFalse(answer['provenance']['simulation_run'])
        self.assertNotIn('fields', answer['view'])

    def test_report_paths_and_stale_case_sources_refuse_without_store_access(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(view, '_store') as store, \
             patch.object(view, '_adapters', return_value={}):
            root = Path(tmp)
            for name in ('../run-00001.json', 'C:/private.json', 'run-1.json', 'run-00001.json/extra'):
                answer = view.response(root, name)
                self.assertEqual(answer['error']['code'], 'INVALID_REPORT', answer)
                self.assertNotIn(tmp, json.dumps(answer))
            answer = view.response(root / '..' / root.name)
            self.assertEqual(answer['error']['code'], 'INVALID_PATH', answer)
            configuration = dict(schema='atlas.w12-public-run.v1', cells=8,
                example_sources={path.relative_to(view.ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (view.ROOT/'tools/run_tectonics.py', view.ROOT/'examples/w12_column_case.py')})
            configuration['example_sources']['tools/run_tectonics.py'] = '0' * 64
            (root/'case.json').write_text(json.dumps(configuration), encoding='utf-8')
            (root/'run-00001.json').write_text('{}', encoding='utf-8')
            answer = view.response(root)
            self.assertEqual(answer['error']['code'], 'SOURCE_MISMATCH', answer)
            store.assert_not_called()
            self.assertFalse((root/'native.sqlite').exists())

    def test_active_managed_job_lock_refuses_before_request_or_native_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_id = 'a' * 32
            job = root/job_id
            job.mkdir()
            with jobs._lock(job/'worker.lock'), patch.object(jobs, '_request') as request, \
                 patch.object(view, 'read_view') as read:
                answer = view.response(root=root, job_id=job_id)
            self.assertEqual(answer['error']['code'], 'RUN_BUSY', answer)
            request.assert_not_called()
            read.assert_not_called()
            self.assertFalse((job/'run').exists())

    def test_store_opens_original_read_only_and_removes_writable_snapshot(self):
        copied_paths = []
        original_connect = sqlite3.connect

        class SnapshotStore:
            def __init__(self, path, **kwargs):
                self.path = Path(path)
                copied_paths.append(self.path)

            def __enter__(self):
                with closing(original_connect(self.path)) as db:
                    db.execute("INSERT INTO chunks VALUES ('temporary-only')")
                    db.commit()
                return self

            def __exit__(self, *args):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'native.sqlite'
            with closing(original_connect(source)) as db:
                for table in ('settings', 'snapshots', 'chunks'):
                    db.execute('CREATE TABLE ' + table + ' (test TEXT)')
                db.execute("INSERT INTO chunks VALUES ('retained')")
                db.commit()
            before = file_hashes(root)
            with patch('atlas_tectonics.storage.ArrayStore', SnapshotStore), \
                 patch.object(sqlite3, 'connect', wraps=original_connect) as connect:
                with view._store(root) as (store, budget):
                    self.assertNotEqual(store.path, source)
                    self.assertTrue(store.path.exists())
                self.assertEqual(budget.reserved_bytes, 0)
            originals = [call for call in connect.call_args_list if str(call.args[0]).startswith(source.as_uri())]
            self.assertEqual(len(originals), 1)
            self.assertEqual(originals[0].args[0], source.as_uri() + '?mode=ro')
            self.assertTrue(originals[0].kwargs['uri'])
            self.assertEqual(file_hashes(root), before)
            self.assertTrue(copied_paths)
            self.assertTrue(all(not path.exists() for path in copied_paths))


@unittest.skipUnless(os.environ.get('ATLAS_UI_TEST_RUN'),
    'Set ATLAS_UI_TEST_RUN to an existing compatible W12 run; no data is generated here')
class RetainedViewTests(unittest.TestCase):
    def test_selected_saved_time_geometry_matches_verified_native_fields_without_source_writes(self):
        root = Path(os.environ['ATLAS_UI_TEST_RUN'])
        report = os.environ.get('ATLAS_UI_TEST_REPORT', 'run-00002.json')
        before = file_hashes(root)
        catalogue = view.response(root, report)
        self.assertEqual(catalogue['status'], 'ok', catalogue)
        entry = catalogue['catalogue']['times'][1]
        self.assertEqual(entry['availability'], 'committed')
        selected = view.response(root, report, action='section', output_index=1,
            field='porosity', cell_start=1, cell_stop=5,
            expected_plan_id=catalogue['catalogue']['plan_id'])
        self.assertEqual(selected['status'], 'ok', selected)
        with view._store(root) as (store, budget):
            product = store.metadata(entry['product_id'])
            native = reader._result(store, product, {'cells': catalogue['catalogue']['source_cells']}, budget)
        for name, field in native['fields'].items():
            self.assertEqual(field['spec'], product['fields'][name])
            array = np.asarray(field['values'], dtype=field['spec']['dtype'])
            self.assertEqual(list(array.shape), field['spec']['shape'])
            self.assertEqual(hashlib.sha256(array.tobytes()).hexdigest(), field['spec']['sha256'])
        result = selected['view']
        self.assertEqual(result['product_id'], product['product_id'])
        self.assertEqual(result['native_state_id'], native['native_state_id'])
        self.assertEqual(result['time_s'], native['time_s'])
        self.assertEqual(result['epoch_id'], native['epoch_id'])
        geometry = result['geometry']
        grain = np.asarray(native['fields']['grain_volume_m3']['values'])
        void = np.asarray(native['fields']['void_ratio']['values'])
        support = native['support']
        areas = support['width_m'] * np.diff(support['cell_edges_m'])
        thickness = (grain + grain * void) / areas
        bottoms = np.cumsum(thickness, axis=0)
        tops = np.vstack([np.zeros((1, grain.shape[1])), bottoms[:-1]])
        np.testing.assert_array_equal(geometry['field']['values'], (void / (1 + void))[:, 1:5])
        np.testing.assert_array_equal(geometry['top_depth_m'], tops[:, 1:5])
        np.testing.assert_array_equal(geometry['bottom_depth_m'], bottoms[:, 1:5])
        np.testing.assert_array_equal(geometry['column_bulk_thickness_m'], bottoms[-1, 1:5])
        self.assertEqual(geometry['parcels'], support['compaction_rows'])
        self.assertEqual(geometry['support']['cell_ids'], support['cell_ids'][1:5])
        packed = native['fields']['support.values']
        for column in range(5, 8):
            spec = packed['spec']['columns'][column]
            curve = geometry['signed_curves'][spec['name']]
            self.assertEqual(curve['spec'], spec)
            self.assertEqual(curve['values'], [row[column] for row in packed['values'][1:5]])
            known = native['fields']['support.reservoir_surface_known']['values'][1:5] if column == 7 else [True] * 4
            self.assertEqual(curve['known'], known)
        self.assertTrue(selected['provenance']['read_only'])
        self.assertFalse(selected['provenance']['simulation_run'])
        self.assertEqual(file_hashes(root), before)


if __name__ == '__main__':
    unittest.main()
