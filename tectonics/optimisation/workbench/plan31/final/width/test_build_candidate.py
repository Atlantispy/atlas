"""Actual source receiving only; no IV or runtime/scientific execution."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[5]
spec=importlib.util.spec_from_file_location('width_receiving_under_test',HERE/'build_candidate.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class WidthReceiving(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='p31w-')
        cls.root=Path(cls.temp.name)
        cls.out=cls.root/'source'
        cls.result=M.materialise(REPO,cls.out)
        cls.parent,cls.utilities,cls.mapping,cls.payloads,cls.applier=M.contract(REPO)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_three_native_and_seven_tools(self):
        self.assertEqual(len(self.result['files']),697)
        self.assertEqual(len(self.result['receiving_changes']),10)
        for name,row in self.mapping['rows'].items():
            self.assertEqual(self.result['files'][name],row['public_output_sha256'])
            self.assertEqual(M.digest((self.out/name).read_bytes()),row['public_output_sha256'])
        self.assertEqual(self.result['files']['helpers/width_gate.py'],self.mapping['width_gate_sha256'])
        self.parent.verify_inventory(self.out,self.result['files'],self.utilities)
        self.assertTrue(self.result['N9_width_selected'])
        for name in ['IV_permitted','full_C4_accepted','reader_width_tables_accepted','runtime_admission','scientific_acceptance','default_changed','interval_authority','public_guards_enabled']:
            self.assertIs(self.result[name],False)

    def test_wrong_map_refuses_before_output(self):
        before=M.MAP_SHA
        try:
            M.MAP_SHA='0'*64
            with self.assertRaisesRegex(ValueError,'width source map pin differs'):
                M.materialise(REPO,self.root/'wrong-map')
            self.assertFalse((self.root/'wrong-map').exists())
        finally:M.MAP_SHA=before

    def test_actual_wrong_tool_bytes_refuse(self):
        fixture=self.root/'copied-input'
        fixture.mkdir()
        for name in ['SOURCE-MAP.json','N9-SOURCE-MAP.json']:
            shutil.copyfile(HERE/name,fixture/name)
        for row in self.mapping['rows'].values():
            for key in ['payload','diff']:
                if row[key] is not None:
                    target=fixture/row[key];target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(HERE/row[key],target)
        tool=fixture/'source/helpers/n9-tools-r21/dump_arm_r5.py'
        tool.write_bytes(tool.read_bytes()+b'\n# disposable wrong tool bytes\n')
        before=M.HERE
        try:
            M.HERE=fixture
            with self.assertRaisesRegex(ValueError,'actual N9/native tool pin differs'):
                M.materialise(REPO,self.root/'wrong-tool')
            self.assertFalse((self.root/'wrong-tool').exists())
        finally:M.HERE=before

    def test_parent_pin_refuses(self):
        before=M.PARENT['sha256']
        try:
            M.PARENT['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'parent builder pin differs'):
                M.materialise(REPO,self.root/'wrong-parent')
            self.assertFalse((self.root/'wrong-parent').exists())
        finally:M.PARENT['sha256']=before

    def test_occupied_output_preserved(self):
        with self.assertRaises(FileExistsError):M.materialise(REPO,self.out)
        self.parent.verify_inventory(self.out,self.result['files'],self.utilities)

    def test_source_overlap_refuses(self):
        with self.assertRaisesRegex(ValueError,'overlaps read-only source'):
            M.materialise(REPO,HERE/'not-an-output')
        self.assertFalse((HERE/'not-an-output').exists())


if __name__=='__main__':unittest.main(verbosity=2)
