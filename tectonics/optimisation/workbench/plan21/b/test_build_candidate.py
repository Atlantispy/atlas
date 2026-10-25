"""Bounded B/current-L3/S3 contracts with the exact real Plan39/S1A source fixture."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('b_receiving_r4_checks',HERE/'build_candidate.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
REPO=Path(os.environ['ATLAS_B_SOURCE_REPO'])
S3_TOOL=Path(os.environ['ATLAS_B_S3_TOOL'])
S3_REPO=Path(os.environ['ATLAS_B_S3_REPO'])
L3_PACKAGE=Path(os.environ['ATLAS_B_L3_PACKAGE'])
REAL_PARENT=None


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def put(root,relative,raw):
    target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)


def mini_repo(root):
    paths=[builder.BASE_TOOL,builder.BASE_MAP,
           'tectonics/optimisation/workbench/plan39/build_selection.py',
           'tectonics/optimisation/workbench/plan18/build_selection.py',
           builder.S3_UPGRADE['historical_source_map']['path'],builder.S3_UPGRADE['parent_source_map']['path']]
    for relative in paths:put(root,relative,(REPO/relative).read_bytes())
    put(root,builder.S3_UPGRADE['tool']['path'],S3_TOOL.read_bytes())
    new_map=builder.S3_UPGRADE['source_map']['path']
    put(root,new_map,(S3_REPO/new_map).read_bytes())
    for entry in json.loads((root/new_map).read_text())['entries']:
        put(root,entry['public_path'],(S3_REPO/entry['public_path']).read_bytes())
    l3_map=builder.S3_UPGRADE['l3_source_map']['path']
    put(root,l3_map,(L3_PACKAGE/'L3-SOURCE-MAP-r3.json').read_bytes())
    for entry in json.loads((root/l3_map).read_text())['entries']:
        if entry['member']=='source/helpers/mesh_tables.py':
            assert entry['public_path']=='tectonics/optimisation/workbench/plan22/source/helpers/mesh_tables.py'
            content=(REPO/entry['public_path']).read_bytes()
        else:
            relative=entry['public_path'].split('/plan21/',1)[1]
            content=(L3_PACKAGE/relative).read_bytes()
        assert digest(content)==entry['public_sha256']
        put(root,entry['public_path'],content)


def parent_payloads():
    global REAL_PARENT
    if REAL_PARENT is None:
        parent=REPO/builder.S3_UPGRADE['parent_source_map']['path']
        raw=parent.read_bytes();assert digest(raw)==builder.S3_UPGRADE['parent_source_map']['sha256']
        entries=json.loads(raw)['entries'];payloads={};files={}
        for entry in entries:
            row=entry['member'].removeprefix('source/');content=(REPO/entry['public_path']).read_bytes()
            assert digest(content)==entry['public_sha256'],row
            payloads[row]=content;files[row]=entry['public_sha256']
        s1a_raw=(REPO/builder.BASE_MAP).read_bytes();assert digest(s1a_raw)==builder.BASE_MAP_SHA
        for entry in json.loads(s1a_raw)['entries']:
            row=entry['member'].removeprefix('source/');content=(REPO/entry['public_path']).read_bytes()
            assert digest(content)==entry['public_sha256'],row
            payloads[row]=content;files[row]=entry['public_sha256']
        assert len(files)==694 and sum(row.startswith('src/') for row in files)==287
        assert sum(row.startswith('helpers/') for row in files)==407
        assert not builder.UPGRADE_ADDITIONS & set(files)
        assert files['helpers/record_views.py']=='a6bbb81dcc88c7f4b84272929922a8e4f702694163b18d18c26d3b76a86f89bd'
        assert files['helpers/mesh_tables.py']=='076f691085aa0e15bf3851d9a21b259421f6e9ba719f2ce4f26985caab12b181'
        assert files['helpers/spatial_validation_patch.py']=='45a992b8bb685c1c3938e6e769754fb4993b99baeac348df92a790358dc4a3c3'
        assert files['helpers/test_d1b_carried_start.py']=='aef680d2b7d6a69723930c1e3ded0b90ea5951793fdb4b434f98ed92d8d6978a'
        REAL_PARENT=(files,payloads)
    return dict(REAL_PARENT[0]),dict(REAL_PARENT[1])


class ConstructorChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=HERE);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';mini_repo(self.repo)
    def test_changed_parent_builder_refuses_before_output(self):
        put(self.repo,builder.BASE_TOOL,b'changed builder')
        with self.assertRaisesRegex(ValueError,'Pinned source changed'):
            builder.materialise(self.repo,self.root/'out',arm='b3')
        self.assertFalse((self.root/'out').exists())
    def test_changed_overlay_map_refuses_before_output(self):
        package=self.root/'package';put(package,'SOURCE-MAP.json',(HERE/'SOURCE-MAP.json').read_bytes()+b'\n')
        with patch.object(builder,'HERE',package),self.assertRaisesRegex(ValueError,'B source map'):
            builder.materialise(self.repo,self.root/'out',arm='b3')
        self.assertFalse((self.root/'out').exists())
    def test_changed_row_bytes_refuse_before_output(self):
        package=self.root/'package';put(package,'SOURCE-MAP.json',(HERE/'SOURCE-MAP.json').read_bytes())
        relative='source/b3/helpers/interval_store_set.py';put(package,relative,(HERE/relative).read_bytes()+b'\n')
        with patch.object(builder,'HERE',package),self.assertRaisesRegex(ValueError,'helpers/interval_store_set.py'):
            builder.materialise(self.repo,self.root/'out',arm='b3')
        self.assertFalse((self.root/'out').exists())
    def test_existing_destination_is_preserved(self):
        output=self.root/'out';output.mkdir();marker=output/'marker';marker.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):builder.materialise(self.repo,output,arm='b3')
        self.assertEqual(marker.read_bytes(),b'keep')
    def test_unknown_arm_refuses(self):
        with self.assertRaisesRegex(ValueError,'explicit B arm'):
            builder.materialise(self.repo,self.root/'out',arm='selected')
        self.assertFalse((self.root/'out').exists())
    def test_both_arm_contracts_exact_three_rows_without_activation(self):
        mapping=json.loads((HERE/'SOURCE-MAP.json').read_text())
        for arm in ('b1b2','b3'):
            with self.subTest(arm=arm):
                _,_,rows,payloads,s3=builder.contract(self.repo,arm)
                self.assertEqual(set(rows),set(builder.BEFORE));self.assertEqual(set(payloads),set(rows))
                self.assertEqual(len(rows),3);self.assertTrue(callable(s3.upgrade_selected_payloads))
                self.assertTrue(all(mapping[key] is False for key in builder.FLAGS))
                self.assertEqual((mapping['parent_source_members'],mapping['source_members']),(694,697))
    def test_cli_failure_exit_and_message(self):
        message=io.StringIO()
        with patch('sys.argv',['build_candidate.py','--repo',str(self.repo),'--output','unused','--arm','b3']),patch.object(builder,'materialise',side_effect=ValueError('injected source drift')),contextlib.redirect_stderr(message),self.assertRaises(SystemExit) as caught:
            builder.main()
        self.assertEqual(caught.exception.code,1);self.assertIn('B source construction refused: injected source drift',message.getvalue())
    def test_s3_tool_drift_refuses(self):
        relative=builder.S3_UPGRADE['tool']['path'];put(self.repo,relative,(self.repo/relative).read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'S3 upgrade tool'):
            builder.materialise(self.repo,self.root/'out',arm='b3')
        self.assertFalse((self.root/'out').exists())
    def test_s3_maps_drift_refuse(self):
        for key in ('parent_source_map','historical_source_map','l3_source_map','source_map'):
            with self.subTest(map=key):
                relative=builder.S3_UPGRADE[key]['path'];original=(self.repo/relative).read_bytes()
                put(self.repo,relative,original+b'\n')
                with self.assertRaisesRegex(ValueError,'S3 '+key):builder.contract(self.repo,'b3')
                put(self.repo,relative,original)
    def upgrade_inputs(self):
        _,utilities,_,_,s3=builder.contract(self.repo,'b3')
        files,payloads=parent_payloads()
        return files,payloads,utilities,s3
    def test_actual_l3_s3_upgrade_changes_only_seven_rows_and_keeps_inputs(self):
        files,payloads,u,s3=self.upgrade_inputs();before_files=dict(files);before_payloads=dict(payloads)
        upgraded,selected,receipt=builder.upgrade_parent(self.repo,files,payloads,u,s3)
        self.assertEqual(len(selected),697);self.assertEqual(set(receipt['changed_rows']),builder.UPGRADE_ROWS)
        self.assertEqual(files,before_files);self.assertEqual(payloads,before_payloads)
        self.assertNotEqual(receipt['changed_rows']['helpers/test_d1b_carried_start.py']['before'],receipt['changed_rows']['helpers/test_d1b_carried_start.py']['after'])
        self.assertEqual(receipt['parent_source_map_sha256'],builder.S3_UPGRADE['parent_source_map']['sha256'])
        self.assertEqual(receipt['l3_source_map_sha256'],builder.S3_UPGRADE['l3_source_map']['sha256'])
        self.assertEqual(set(selected)-set(files),builder.UPGRADE_ADDITIONS)
        self.assertEqual(selected['helpers/mesh_tables.py'],'75a3e282ad2e5c376572275d27810ce116fa59a50c5cf85f874745646d15eeb2')
        self.assertNotIn(b'\r\n',upgraded['helpers/mesh_tables.py'])
        for row in set(files)-builder.UPGRADE_ROWS:self.assertEqual(upgraded[row],payloads[row]);self.assertEqual(selected[row],files[row])
    def test_s3_predecessor_drift_refuses_even_with_self_consistent_manifest(self):
        files,payloads,u,s3=self.upgrade_inputs();row='helpers/spatial_validation_patch.py'
        payloads[row]+=b'\n';files[row]=digest(payloads[row])
        with self.assertRaisesRegex(ValueError,'Complete Plan39/S1A parent differs'):
            builder.upgrade_parent(self.repo,files,payloads,u,s3)
    def test_parent_manifest_drift_refuses(self):
        files,payloads,u,s3=self.upgrade_inputs();row=next(row for row in files if row not in builder.UPGRADE_ROWS);payloads[row]+=b'\n'
        with self.assertRaisesRegex(ValueError,'historical receiving '):
            builder.upgrade_parent(self.repo,files,payloads,u,s3)
    def test_s3_unrelated_change_is_rejected_at_caller_boundary(self):
        files,payloads,u,s3=self.upgrade_inputs()
        def corrupt(*args):
            changed,selected,receipt=s3.upgrade_selected_payloads(*args)
            row=next(row for row in files if row not in builder.UPGRADE_ROWS)
            changed[row]=b'unrelated = False\n';selected[row]=digest(changed[row])
            return changed,selected,receipt
        with self.assertRaisesRegex(ValueError,'changed unrelated parent source'):
            builder.upgrade_parent(self.repo,files,payloads,u,SimpleNamespace(upgrade_selected_payloads=corrupt))

    def test_l3_payload_drift_refuses(self):
        files,payloads,u,s3=self.upgrade_inputs()
        relative='tectonics/optimisation/workbench/plan21/receiving-l3-r3/helpers/record_views.py'
        put(self.repo,relative,(self.repo/relative).read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'Receiving payload changed: helpers/record_views.py'):
            builder.upgrade_parent(self.repo,files,payloads,u,s3)
    def test_real_l3_predecessor_drift_refuses(self):
        files,payloads,u,s3=self.upgrade_inputs();row='helpers/record_views.py'
        payloads[row]+=b'\n';files[row]=digest(payloads[row])
        with self.assertRaisesRegex(ValueError,'Complete Plan39/S1A parent differs'):
            builder.upgrade_parent(self.repo,files,payloads,u,s3)
        with self.assertRaisesRegex(ValueError,'Plan39 receiving predecessor differs'):
            s3.upgrade_selected_payloads(self.repo,files,payloads,u)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(__import__('__main__')))
    print(json.dumps(dict(run=result.testsRun,failures=len(result.failures),errors=len(result.errors),success=result.wasSuccessful(),full_source_build=False)))
    raise SystemExit(not result.wasSuccessful())
