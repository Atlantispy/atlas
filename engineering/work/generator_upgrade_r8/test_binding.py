"""Focused loader/source/envelope guards; no full-stage acceptance claim."""
import copy
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from . import binding as b, provenance as p


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=b.load()

    def test_exact_parent_seal(self):
        self.assertEqual(p.sha(p.checked(p.R7_SEAL)),p.R7_SEAL_SHA256)

    def test_exact_eighteen_r7_sources(self):
        self.assertEqual(len(p.retained_record()['source_identity']['r7_sources']),18)

    def test_actual_parent_identity(self):
        self.assertEqual(self.bundle.parent.verify(),p.R7_SOURCE_SHA256)
        self.assertEqual(self.bundle.identity['retained_source_identity'],p.retained_record()['source_identity'])

    def test_six_reviewed_external_sources_preserve_roles(self):
        records=self.bundle.identity['external_reference_bindings']
        sources=self.bundle.identity['external_reference_sources']
        self.assertEqual(len(records),6)
        self.assertEqual({row['path']:row['sha256'] for row in records},sources)
        for row in records:
            self.assertTrue(row['role'].strip())
            self.assertEqual(p.sha(p.checked(row['path'])),row['sha256'])

    def test_external_ledger_ignores_preloaded_biomes(self):
        name='work.generator_upgrade_r8.biomes'; fake=types.ModuleType(name)
        fake.source_bindings=lambda:[]
        with patch.dict(sys.modules,{name:fake}):
            records,sources=p.reference_bindings(self.bundle.parent,self.bundle.identity['r8_sources'])
        self.assertEqual(sources,self.bundle.identity['external_reference_sources'])
        self.assertEqual(records,self.bundle.identity['external_reference_bindings'])

    def test_external_ledger_provider_source_must_be_captured(self):
        with self.assertRaisesRegex(ValueError,'provider required'):
            p.reference_bindings(self.bundle.parent,{})

    def test_external_ledger_live_source_change_rejected(self):
        original=p.checked
        target=next(iter(self.bundle.identity['external_reference_sources']))
        def checked(path,expected=None):
            if str(Path(path).resolve())==target: raise ValueError('external bytes changed')
            return original(path,expected)
        with patch.object(p,'checked',side_effect=checked):
            with self.assertRaisesRegex(ValueError,'external bytes changed'):
                p.reference_bindings(self.bundle.parent,self.bundle.identity['r8_sources'])

    def test_actual_nested_solver_and_climate_graph(self):
        parent=self.bundle.parent.parent
        self.assertIs(parent.r3.sw,parent.solver)
        self.assertEqual(Path(parent.solver.__file__),p.TASK/'work/generator_upgrade_r6/soil_water.py')
        self.assertEqual(Path(parent.pipeline.__file__),p.TASK/'work/generator_upgrade_r4/pipeline.py')

    def test_r7_graph_executes_exact_source(self):
        parent=self.bundle.parent
        actual=parent.pipeline
        self.assertEqual(Path(actual.__file__),p.R7_ROOT/'pipeline.py')
        record=parent.graph.executed['work.generator_upgrade_r7.pipeline']
        self.assertEqual(record['sha256'],parent.identity['r7_sources'][record['path']])

    def test_no_global_predecessor_modules(self):
        self.assertFalse(any(k.startswith(('work.generator_upgrade_r7.','work.generator_upgrade_r6.')) for k in sys.modules))

    def test_no_private_namespace_leak(self):
        self.assertFalse(any(k.startswith(('_diadem_r6_','_r8_exact_r7_')) for k in sys.modules))

    def test_public_graph_ignores_preloaded_module(self):
        name='work.generator_upgrade_r8.provenance'
        fake=types.ModuleType(name); fake.stale_marker=True
        with patch.dict(sys.modules,{name:fake}): actual=self.bundle.graph.load(name)
        self.assertIsNot(actual,fake)
        self.assertFalse(hasattr(actual,'stale_marker'))
        self.assertEqual(self.bundle.graph.executed[name]['sha256'],self.bundle.identity['r8_sources'][str(p.HERE/'provenance.py')])

    def test_undeclared_project_import_refused(self):
        with self.assertRaises(ValueError): self.bundle.graph.import_module('work.not_declared',fromlist=('x',))

    def test_changed_source_hash_rejected(self):
        with self.assertRaises(ValueError): p.checked(p.HERE/'binding.py','0'*64)

    def test_relative_source_path_refused(self):
        with self.assertRaises(ValueError): p.plain_path('binding.py')

    def test_traversal_source_path_refused(self):
        with self.assertRaises(ValueError): p.plain_path(p.HERE/'..'/'binding.py')

    def test_missing_source_refused(self):
        with self.assertRaises(ValueError): p.checked(p.HERE/'no-such-source.py')

    def test_directory_is_not_source(self):
        with self.assertRaises(ValueError): p.checked(p.HERE)

    def test_oversize_source_refused(self):
        with patch.object(p,'MAX_BYTES',1):
            with self.assertRaises(ValueError): p.checked(p.HERE/'binding.py')

    def test_reparse_directory_checked_before_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); original=Path.lstat
            def mocked(path,*args,**kwargs):
                if path==root: return types.SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
                return original(path,*args,**kwargs)
            with patch.object(Path,'lstat',mocked):
                with self.assertRaisesRegex(ValueError,'linked/reparse'): p.source_snapshot(root)

    def test_empty_inventory_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): p.source_snapshot(Path(directory))

    def test_changed_r7_inventory_rejected(self):
        with patch.object(p,'source_snapshot',return_value={}):
            with self.assertRaises(ValueError): p.retained_record()

    def test_changed_r8_inventory_rejected(self):
        altered=copy.deepcopy(self.bundle.identity); altered['r8_sources']['unexpected']='0'*64
        with patch.object(p,'source_identity',return_value=(altered,self.bundle.source_sha256)):
            with self.assertRaises(ValueError): self.bundle.verify()

    def test_nested_python_basename_alias_refused(self):
        with self.assertRaisesRegex(ValueError,'flat'):
            b.module_nodes({str(p.HERE/'nested'/'binding.py'):'0'*64})

    def test_nested_document_is_not_python_module(self):
        self.assertEqual(b.module_nodes({str(p.HERE/'notes'/'README.md'):'0'*64}),{})

    def test_checkpoint_reverifies_live_sources(self):
        with patch.object(self.bundle,'verify',side_effect=ValueError('changed')):
            with self.assertRaisesRegex(ValueError,'changed'): self.bundle.checkpoint({})

    def test_checkpoint_refuses_r7_envelope(self):
        with self.assertRaises(ValueError): self.bundle.checkpoint({'schema':'diadem.soil-formation-result.r7'})

    def test_checkpoint_refuses_different_source(self):
        with self.assertRaises(ValueError): self.bundle.checkpoint({'schema':b.RESULT_SCHEMA,'source_sha256':'0'*64})

    def test_checkpoint_detaches_stage_state(self):
        row={'schema':b.RESULT_SCHEMA,'source_sha256':self.bundle.source_sha256,
            'recipe_sha256':'1'*64,'state':{'completed_stages':0}}
        result=self.bundle.checkpoint(row); row['state']['completed_stages']=1
        self.assertEqual(result['state'],{'completed_stages':0})
        self.assertEqual(result['schema'],b.CHECKPOINT_SCHEMA)
        self.assertEqual(result['state_sha256'],self.bundle.storage.sha(self.bundle.storage.encoded(result['state'])))

    def test_checkpoint_requires_recipe_digest(self):
        row={'schema':b.RESULT_SCHEMA,'source_sha256':self.bundle.source_sha256,'recipe_sha256':'bad','state':{}}
        with self.assertRaises(ValueError): self.bundle.checkpoint(row)

    def test_run_checks_sources_before_dispatch(self):
        with patch.object(self.bundle,'verify',side_effect=ValueError('changed')):
            with self.assertRaisesRegex(ValueError,'changed'): self.bundle.run({})

    def test_duplicate_json_refused(self):
        with self.assertRaises(ValueError): self.bundle.storage.decoded(b'{"x":1,"x":2}')

    def test_nonfinite_json_refused(self):
        with self.assertRaises(ValueError): self.bundle.storage.decoded(b'{"x":NaN}')

    def test_current_flags_are_reportable(self):
        self.assertIn(sys.flags.optimize,(0,2))


if __name__=='__main__': unittest.main()
