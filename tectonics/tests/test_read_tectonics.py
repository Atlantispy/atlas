"""Read-only bridge guards; optional retained-result check never generates data."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import read_tectonics as reader


def hashes(root):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}


class ReaderGuards(unittest.TestCase):
    def test_report_selector_and_missing_input_are_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('../run-00001.json','C:/private.json','run-1.json','run-00001.json/extra'):
                result=reader.response(tmp,name)
                self.assertEqual(result['error']['code'],'INVALID_REPORT')
                self.assertNotIn(tmp,json.dumps(result))
            self.assertEqual(reader.response(tmp)['error']['code'],'MISSING_INPUT')
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_duplicate_nonfinite_and_oversized_json_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'test.json'
            for body in ('{"a":1,"a":2}','{"a":NaN}'):
                source.write_text(body)
                with self.assertRaises(reader.ReadError):reader._read_json(source,64)
            source.write_text(' '*65)
            with self.assertRaises(reader.ReadError):reader._read_json(source,64)

    def test_incompatible_case_refuses_without_opening_native_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'case.json').write_text('{}')
            (root/'run-00001.json').write_text('{}')
            result=reader.response(root)
            self.assertEqual(result['error']['code'],'SOURCE_MISMATCH')
            self.assertFalse((root/'native.sqlite').exists())

    def test_snapshot_is_exact_read_only_and_rejects_busy_or_unrelated_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.sqlite';dest=root/'copy.sqlite'
            with closing(sqlite3.connect(source)) as db:
                for name in ('settings','snapshots','chunks'):
                    db.execute('CREATE TABLE '+name+' (test TEXT)')
                db.execute("INSERT INTO chunks VALUES ('retained')");db.commit()
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            reader._snapshot(source,dest)
            self.assertEqual(before,hashlib.sha256(source.read_bytes()).hexdigest())
            with closing(sqlite3.connect(dest)) as db:
                self.assertEqual(db.execute('SELECT test FROM chunks').fetchall(),[('retained',)])
            (root/'source.sqlite-wal').write_bytes(b'busy')
            with self.assertRaisesRegex(reader.ReadError,'Close the native run'):
                reader._snapshot(source,root/'other.sqlite')
            with closing(sqlite3.connect(root/'unrelated.sqlite')) as db:
                db.execute('CREATE TABLE wrong (x)')
            with self.assertRaisesRegex(reader.ReadError,'not a native ArrayStore'):
                reader._snapshot(root/'unrelated.sqlite',root/'bad-copy.sqlite')
            self.assertFalse((root/'bad-copy.sqlite').exists())


@unittest.skipUnless(os.environ.get('ATLAS_UI_TEST_RUN'),'Set ATLAS_UI_TEST_RUN to an existing compatible W12 run; never generate one here')
class RetainedResultTests(unittest.TestCase):
    def test_actual_result_fields_masks_rows_identity_and_original_files_unchanged(self):
        import numpy as np
        root=Path(os.environ['ATLAS_UI_TEST_RUN'])
        name=os.environ.get('ATLAS_UI_TEST_REPORT','run-00002.json')
        before=hashes(root)
        original=json.loads((root/name).read_text())['product']
        answer=reader.response(root,name)
        self.assertEqual(answer['status'],'ok',answer)
        result=answer['result']
        self.assertEqual(result['product_id'],original['product_id'])
        self.assertEqual(answer['capabilities'],dict(inspect=True,generate=False,cancel=False,resume=False))
        self.assertEqual(set(result['fields']),set(original['fields']))
        for name,field in result['fields'].items():
            self.assertEqual(field['spec'],original['fields'][name])
            array=np.asarray(field['values'],dtype=field['spec']['dtype'])
            self.assertEqual(list(array.shape),field['spec']['shape'])
            self.assertEqual(hashlib.sha256(array.tobytes()).hexdigest(),field['spec']['sha256'])
        support=result['support']
        self.assertEqual(len(support['cell_ids']),8)
        self.assertEqual(support['cell_edges_m'],[n*.5 for n in range(9)])
        self.assertEqual(len(support['material_cohorts']),3)
        self.assertEqual(len(support['compaction_rows']),10)
        self.assertEqual(result['fields']['support.values']['spec']['columns'][-1]['known']['mask_field'],
                         'support.reservoir_surface_known')
        self.assertFalse(result['provenance']['simulation_run'])
        self.assertEqual(before,hashes(root))
        print('retained read seconds:',result['provenance']['read_seconds'])

    def test_changed_report_and_missing_native_dependency_fail_closed(self):
        root=Path(os.environ['ATLAS_UI_TEST_RUN'])
        name=os.environ.get('ATLAS_UI_TEST_REPORT','run-00002.json')
        with tempfile.TemporaryDirectory() as tmp:
            temp=Path(tmp)
            for file in ('case.json','native.sqlite',name):shutil.copyfile(root/file,temp/file)
            original=json.loads((temp/name).read_text())
            changed=json.loads(json.dumps(original));changed['product']['context']['world_id']='other'
            (temp/name).write_text(json.dumps(changed))
            answer=reader.response(temp,name)
            self.assertEqual(answer['status'],'error')
            self.assertEqual(answer['error']['code'],'VERIFICATION_FAILED')
            self.assertNotIn(str(temp),json.dumps(answer))
            (temp/name).write_text(json.dumps(original))
            with closing(sqlite3.connect(temp/'native.sqlite')) as db:
                db.execute('DELETE FROM snapshots WHERE id=?',(original['product']['native_state_id'],));db.commit()
            answer=reader.response(temp,name)
            self.assertEqual(answer['status'],'error')
            self.assertEqual(answer['error']['code'],'INCOMPLETE_RESULT')


if __name__=='__main__':unittest.main()
