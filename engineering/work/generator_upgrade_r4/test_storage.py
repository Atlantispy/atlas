import copy
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import storage as s

H = 'a' * 64
J = 'b' * 64


class StorageTests(unittest.TestCase):
    def fixture(self):
        recipe = {'periods': [{'days': 31}], 'source_status': 'SYNTHETIC TEST'}
        state = {'swe': {'low': ['1/3']}, 'water': {'heads': [-.1, .5]},
                 'elapsed_seconds': '23', 'completed_periods': 1, 'consumed': ['interval:0']}
        return recipe, s.checkpoint(state, recipe_sha256=s.sha(s.encoded(recipe)), source_sha256=H)

    def saved(self):
        recipe, envelope = self.fixture()
        return s.save_reference('case', recipe=recipe, result={'liquid': '2/7'},
                                checkpoint_record=envelope, evidence={'status': 'SYNTHETIC TEST'})[0]

    def test_joint_checkpoint_roundtrip_preserves_exact_stocks_and_heads(self):
        recipe, envelope = self.fixture()
        actual = s.restore(s.decoded(s.encoded(envelope)), recipe_sha256=s.sha(s.encoded(recipe)), source_sha256=H)
        self.assertEqual(actual, envelope['state'])
        self.assertIsNot(actual, envelope['state'])

    def test_checkpoint_detaches_input_state(self):
        state = {'swe': [1]}
        envelope = s.checkpoint(state, recipe_sha256=H, source_sha256=J)
        state['swe'][0] = 2
        self.assertEqual(envelope['state'], {'swe': [1]})

    def test_different_recipe_rejected(self):
        envelope = s.checkpoint({}, recipe_sha256=H, source_sha256=J)
        with self.assertRaises(ValueError):
            s.restore(envelope, recipe_sha256=J, source_sha256=J)

    def test_different_source_rejected(self):
        envelope = s.checkpoint({}, recipe_sha256=H, source_sha256=J)
        with self.assertRaises(ValueError):
            s.restore(envelope, recipe_sha256=H, source_sha256=H)

    def test_mutated_snow_consumption_and_state_checksum_rejected(self):
        _, envelope = self.fixture()
        envelope['state']['consumed'] = []
        with self.assertRaises(ValueError):
            s.restore(envelope, recipe_sha256=envelope['recipe_sha256'], source_sha256=H)

    def test_unknown_missing_or_old_schema_fields_rejected(self):
        _, envelope = self.fixture()
        for mutation in ('unknown', 'missing', 'old'):
            changed = copy.deepcopy(envelope)
            if mutation == 'unknown':
                changed['adopted'] = True
            elif mutation == 'missing':
                del changed['state_sha256']
            else:
                changed['schema'] = 'diadem.terrain-water-soil-checkpoint.r3'
            with self.assertRaises(ValueError):
                s.restore(changed, recipe_sha256=envelope['recipe_sha256'], source_sha256=H)

    def test_invalid_digest_forms_rejected(self):
        for value in (None, 1, H.upper(), 'a' * 63, H + '\n', 'z' * 64):
            with self.assertRaises(ValueError):
                s.checkpoint({}, recipe_sha256=value, source_sha256=J)

    def test_nonfinite_duplicate_and_exponent_overflow_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'[NaN]', b'[Infinity]', b'[1e999]'):
            with self.assertRaises(ValueError):
                s.decoded(raw)

    def test_non_json_and_non_string_keys_rejected(self):
        for value in ({1: 2}, {'a': (1, 2)}, {'a': object()}, float('inf')):
            with self.assertRaises(ValueError):
                s.encoded(value)

    def test_invalid_utf8_bom_and_non_bytes_rejected(self):
        for raw in (b'\xff', b'\xef\xbb\xbf{}', '{}', bytearray(b'{}')):
            with self.assertRaises(ValueError):
                s.decoded(raw)

    def test_depth_and_item_limits_rejected(self):
        value = []
        for _ in range(s.MAX_DEPTH + 1):
            value = [value]
        with self.assertRaises(ValueError):
            s.encoded(value)
        with patch.object(s, 'MAX_ITEMS', 2):
            with self.assertRaises(ValueError):
                s.decoded(b'[1,2]')

    def test_byte_bound_checked_for_both_directions(self):
        with patch.object(s, 'MAX_BYTES', 2):
            with self.assertRaises(ValueError):
                s.decoded(b'[0]')
            with self.assertRaises(ValueError):
                s.encoded([0])

    def test_encoding_canonical_and_fraction_string_not_coerced(self):
        self.assertEqual(s.encoded({'b': '1/3', 'a': 1}), b'{"a":1,"b":"1/3"}')

    def test_exclusive_file_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            s.write_json(path, {'water': 1})
            with self.assertRaises(FileExistsError):
                s.write_json(path, {'water': 2})
            self.assertEqual(s.read_json(path), {'water': 1})

    def test_saved_four_file_roundtrip_and_exclusive_directory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'OUTPUT_ROOT', Path(tmp)):
            path = self.saved()
            actual = s.read_reference(path)
            self.assertEqual(actual['result.json'], {'liquid': '2/7'})
            self.assertEqual(set(item.name for item in path.iterdir()), s.PRODUCT_NAMES | {'RECEIPT.json'})
            with self.assertRaises(FileExistsError):
                self.saved()

    def test_damaged_product_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'OUTPUT_ROOT', Path(tmp)):
            path = self.saved()
            (path / 'result.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):
                s.read_reference(path)

    def test_extra_artefact_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'OUTPUT_ROOT', Path(tmp)):
            path = self.saved()
            (path / 'unclaimed.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):
                s.read_reference(path)

    def test_receipt_cannot_claim_production_or_hide_unknown_field(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'OUTPUT_ROOT', Path(tmp)):
            path = self.saved()
            original = s.read_json(path / 'RECEIPT.json')
            for key, value in (('production_installed', True), ('canon_changed', 0), ('unexpected', True)):
                changed = dict(original)
                changed[key] = value
                (path / 'RECEIPT.json').write_bytes(s.encoded(changed))
                with self.assertRaises(ValueError):
                    s.read_reference(path)

    def test_cross_recipe_save_rejected_before_directory_creation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'OUTPUT_ROOT', Path(tmp)):
            _, envelope = self.fixture()
            with self.assertRaises(ValueError):
                s.save_reference('bad', recipe={}, result={}, checkpoint_record=envelope, evidence={})
            self.assertFalse((Path(tmp) / 'bad').exists())

    def test_resigned_different_recipe_rejected_on_readback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'OUTPUT_ROOT', Path(tmp)):
            path = self.saved()
            raw = s.encoded({'replacement': True})
            (path / 'recipe.json').write_bytes(raw)
            receipt = s.read_json(path / 'RECEIPT.json')
            receipt['files']['recipe.json'] = s.sha(raw)
            (path / 'RECEIPT.json').write_bytes(s.encoded(receipt))
            with self.assertRaises(ValueError):
                s.read_reference(path)

    def test_resigned_source_receipt_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s, 'OUTPUT_ROOT', Path(tmp)):
            path = self.saved()
            receipt = s.read_json(path / 'RECEIPT.json')
            receipt['source_sha256'] = J
            (path / 'RECEIPT.json').write_bytes(s.encoded(receipt))
            with self.assertRaises(ValueError):
                s.read_reference(path)

    def test_invalid_run_id_cannot_escape_output_root(self):
        for value in ('../escape', '/root', 'a/b', '', None, 'a' * 65):
            with self.assertRaises(ValueError):
                s.save_reference(value, recipe={}, result={}, checkpoint_record={}, evidence={})

    def test_absolute_traversing_and_relative_paths_rejected(self):
        for path in ('relative.json', s.TASK / '..' / 'unexpected.json'):
            with self.assertRaises(ValueError):
                s.plain_path(path)

    def test_reparse_path_rejected_without_following(self):
        with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)):
            with self.assertRaises(ValueError):
                s.plain_path(s.TASK)

    def test_oversize_input_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'big.json'
            path.write_bytes(b'{}')
            with patch.object(s, 'MAX_BYTES', 1):
                with self.assertRaises(ValueError):
                    s.read_json(path)


if __name__ == '__main__':
    unittest.main()
