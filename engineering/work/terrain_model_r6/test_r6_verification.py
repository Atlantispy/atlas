"""R6 evidence cannot promote omitted, skipped, substituted or stale execution."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
import uuid
from unittest.mock import patch

import release_source_runtime as source
import verify_r6 as verify


class R6VerificationTests(unittest.TestCase):
    def test_empty_missing_duplicate_reordered_or_substituted_ids_fail(self):
        expected=['one','two']
        self.assertTrue(verify.execution_complete(expected,expected,expected,expected))
        for values in ([],['one'],['one','one'],['two','one'],['one','other']):
            for index in range(3):
                rows=[expected,expected,expected];rows[index]=values
                self.assertFalse(verify.execution_complete(expected,*rows))
        self.assertFalse(verify.execution_complete([],[],[],[]))

    def test_unbound_verification_refuses_before_writes(self):
        with self.assertRaisesRegex(ValueError,'fresh exact-source'):verify.main([])

    def test_captured_source_change_prevents_execution(self):
        with tempfile.TemporaryDirectory(prefix='r6-binding-') as temporary:
            root=Path(temporary);path=root/'r6_probe.py';path.write_text('VALUE=1\n')
            runtime=source.SourceRuntime(root);path.write_text('raise RuntimeError("wrong bytes")\n')
            with self.assertRaisesRegex(ValueError,'bytes changed'):runtime.check()

    def test_same_path_preloaded_module_cannot_authorise_source_receipt(self):
        with tempfile.TemporaryDirectory(prefix='r6-binding-') as temporary:
            root=Path(temporary);path=root/'r6_probe.py';path.write_text('VALUE=1\n')
            runtime=source.SourceRuntime(root)
            fake=types.ModuleType('r6_probe');fake.__file__=str(path)
            with patch.dict(sys.modules,{'r6_probe':fake}),self.assertRaisesRegex(ValueError,'fresh process'):
                runtime.install()

    def test_exact_compilation_ignores_stale_pyc_and_enforces_assertions(self):
        with tempfile.TemporaryDirectory(prefix='r6-binding-') as temporary:
            root=Path(temporary);name='r6_probe_'+uuid.uuid4().hex
            path=root/(name+'.py');path.write_text('assert False, "assertion retained"\n')
            runtime=source.SourceRuntime(root);runtime.install()
            try:
                with self.assertRaisesRegex(AssertionError,'assertion retained'):__import__(name)
            finally:
                runtime.uninstall();sys.modules.pop(name,None)


if __name__=='__main__':unittest.main()
