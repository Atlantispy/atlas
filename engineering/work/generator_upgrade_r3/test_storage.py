import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from . import storage as s

H='a'*64
J='b'*64


class StorageTests(unittest.TestCase):
    def test_checkpoint_roundtrip_preserves_float_and_nested_state(self):
        state={'head':[-.1,.5],'solid':[[1,3]],'cursor':2}
        e=s.decoded(s.encoded(s.checkpoint(state,recipe_sha256=H,source_sha256=J)))
        r=s.restore(e,recipe_sha256=H,source_sha256=J)
        self.assertEqual(r,state);self.assertIsNot(r,state)

    def test_different_recipe_rejects_restart(self):
        e=s.checkpoint({},recipe_sha256=H,source_sha256=J)
        with self.assertRaises(ValueError):s.restore(e,recipe_sha256=J,source_sha256=J)

    def test_different_source_rejects_restart(self):
        e=s.checkpoint({},recipe_sha256=H,source_sha256=J)
        with self.assertRaises(ValueError):s.restore(e,recipe_sha256=H,source_sha256=H)

    def test_tampered_state_rejected(self):
        e=s.checkpoint({'water':1},recipe_sha256=H,source_sha256=J);e['state']['water']=2
        with self.assertRaises(ValueError):s.restore(e,recipe_sha256=H,source_sha256=J)

    def test_unknown_checkpoint_fields_rejected(self):
        e=s.checkpoint({},recipe_sha256=H,source_sha256=J);e['adopted']=True
        with self.assertRaises(ValueError):s.restore(e,recipe_sha256=H,source_sha256=J)

    def test_nonfinite_and_duplicate_input_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"v":NaN}',b'{"v":Infinity}',b'{"v":1e999}'):
            with self.assertRaises(ValueError):s.decoded(raw)

    def test_non_json_and_non_string_keys_rejected(self):
        for value in ({1:2},{'a':(1,2)},{'a':object()}):
            with self.assertRaises(ValueError):s.encoded(value)

    def test_depth_and_item_budget_rejected(self):
        value=[]
        for _ in range(s.MAX_DEPTH+1):value=[value]
        with self.assertRaises(ValueError):s.encoded(value)
        with patch.object(s,'MAX_ITEMS',2):
            with self.assertRaises(ValueError):s.encoded([1,2])

    def test_byte_bound_applies_before_json_parse(self):
        with patch.object(s,'MAX_BYTES',2):
            with self.assertRaises(ValueError):s.decoded(b'[0]')
            with self.assertRaises(ValueError):s.encoded([0])

    def test_exclusive_checkpoint_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'state.json';s.write_json(p,{'water':1})
            with self.assertRaises(FileExistsError):s.write_json(p,{'water':2})
            self.assertEqual(s.read_json(p),{'water':1})

    def test_actual_saved_reference_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'OUTPUT_ROOT',Path(tmp)):
            p,_=s.save_reference('case',recipe={'r':1},result={'x':[.1]},checkpoint_record={},evidence={'source':H})
            self.assertEqual(s.read_reference(p)['result.json'],{'x':[.1]})
            with self.assertRaises(FileExistsError):s.save_reference('case',recipe={},result={},checkpoint_record={},evidence={})

    def test_saved_product_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'OUTPUT_ROOT',Path(tmp)):
            p,_=s.save_reference('case',recipe={},result={},checkpoint_record={},evidence={})
            (p/'result.json').write_bytes(b'{"other":1}')
            with self.assertRaises(ValueError):s.read_reference(p)

    def test_invalid_run_id_cannot_escape_output_root(self):
        for name in ('../escape','/root','a/b','',None):
            with self.assertRaises(ValueError):s.save_reference(name,recipe={},result={},checkpoint_record={},evidence={})

    def test_relative_paths_are_not_context_dependent(self):
        with self.assertRaises(ValueError):s.plain_path('relative.json')


if __name__=='__main__':unittest.main()
