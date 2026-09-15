import importlib.machinery
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

import r4_io as binding


class PredecessorBindingTests(unittest.TestCase):
    def test_mutated_same_path_global_core_cannot_be_the_producer(self):
        source = """
import sys
sys.path.insert(0,sys.argv[1])
import core
core.number=lambda *a,**k:424242
sys.path.pop(0)
sys.path.insert(0,sys.argv[2])
import r4_io
if r4_io.io.number(1,'probe') != 1.:
    raise RuntimeError('foreign global core executed')
if r4_io.io.number is core.number:
    raise RuntimeError('global core alias admitted')
r4_io.verify_dependencies()
import shoreline_fixtures
prepared=shoreline_fixtures.near_flat()
if prepared['initial_state'].size != prepared['grid']['rows']*prepared['grid']['cols']:
    raise RuntimeError('wrong retained fixture')
"""
        result = subprocess.run([sys.executable,'-B','-c',source,str(binding._R2),str(binding._HERE)],
                                capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_dependencies_never_use_path_loader_or_pyc(self):
        modules = {}
        try:
            with patch.object(binding,'_R2_MODULES',modules), \
                 patch.object(binding,'_R2_NAMESPACE','_r5_binding_test_'+uuid.uuid4().hex+'_'), \
                 patch.object(importlib.machinery.SourceFileLoader,'get_code',side_effect=AssertionError('path loader used')):
                io = binding._load_r2('workflow')
                self.assertEqual(io.number(1,'probe'),1.)
                self.assertEqual(set(modules),{'core','workflow','constructive','materials','water','basin_topology'})
                self.assertEqual(len(binding._verify_r2()),8)
        finally:
            for module in modules.values():
                if sys.modules.get(module.__name__) is module:del sys.modules[module.__name__]

    def test_changed_capture_rejects_before_compilation(self):
        with patch.object(binding,'_R2_MODULES',{}), \
             patch.object(binding,'_read_checked',return_value=b'raise RuntimeError("untrusted executed")'):
            with self.assertRaisesRegex(ValueError,'changed before private compilation'):
                binding._load_r2('workflow')

    def test_changed_contract_cannot_pass_dependency_verification(self):
        core = binding._R2_MODULES['core']
        with patch.object(core,'CONTRACT',{}):
            with self.assertRaisesRegex(ValueError,'executed R2 contract differs'):
                binding._verify_r2()

    def test_private_module_replacement_is_detected(self):
        module = binding._R2_MODULES['core']
        with patch.dict(sys.modules,{module.__name__:object()}):
            with self.assertRaisesRegex(ValueError,'module identity changed'):
                binding._verify_r2()

    def test_capture_hash_is_checked_not_only_path_or_size(self):
        with self.assertRaisesRegex(ValueError,'captured predecessor source mismatch'):
            binding._read_checked(binding._R2/'core.py','0'*64)

    def test_actual_graph_uses_private_core_and_materials(self):
        self.assertIs(binding.io.number,binding._R2_MODULES['core'].number)
        self.assertIs(binding.io.materials,binding._R2_MODULES['materials'])
        self.assertTrue(all(module.__name__.startswith(binding._R2_NAMESPACE)
                            for module in binding._R2_MODULES.values()))


if __name__ == '__main__':unittest.main()
