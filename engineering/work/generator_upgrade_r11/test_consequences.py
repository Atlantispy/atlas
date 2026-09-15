"""Bounded partition storage and unchanged canonical checkpoint semantics."""
from copy import deepcopy
import base64
import hashlib
import json
import random
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch
from . import binding, consequences as c, snapshot as s

H = 'a'*64


class ConsequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = binding.load()
        cls.codec = cls.bundle.parent.graph.load('work.generator_upgrade_r10.payloads')

    def result(self):
        return {'schema': c.RESULT_SCHEMA, 'source_sha256': H, 'recipe_sha256': H,
            'state': {'completed_scenarios': 2, 'parent_result_sha256': H,
                'results': {'a/group': self.codec.pack({'status': 'MODELLED', 'number': '1/3'}),
                    'b/group': self.codec.pack({'status': 'MODELLED', 'number': '2/3'})}},
            'biological_owner_inputs': self.codec.pack({'status': 'UNKNOWN', 'coefficient': None}),
            'source_status': 'WORKING NON-CANON', 'whole_generator_complete': False}

    def test_exact_roundtrip_and_no_aliases(self):
        value = self.result(); manifest, units = c.split(value, self.codec)
        restored = c.join(manifest, units, self.codec)
        self.assertEqual(restored, value)
        restored['state']['results']['a/group']['data'] = 'changed'
        self.assertNotEqual(restored, value)
        self.assertEqual(c.join(manifest, units, self.codec), value)

    def test_canonical_state_and_whole_digest_unchanged(self):
        value = self.result()
        self.assertEqual(c.state_digest(value['state'], self.codec), s.sha(value['state']))
        self.assertEqual(c.digest(value, self.codec), s.sha(value))

    def test_checkpoint_exact_roundtrip(self):
        value = self.result()
        checkpoint = {'schema': c.CHECKPOINT_SCHEMA, 'recipe_sha256': H, 'source_sha256': H,
            'state': value['state'], 'state_sha256': s.sha(value['state'])}
        self.assertEqual(c.clone(checkpoint, self.codec), checkpoint)

    def test_checkpoint_forged_digest_rejects(self):
        value = self.result()
        checkpoint = {'schema': c.CHECKPOINT_SCHEMA, 'recipe_sha256': H, 'source_sha256': H,
            'state': value['state'], 'state_sha256': 'b'*64}
        with self.assertRaisesRegex(ValueError, 'state digest'):
            c.split(checkpoint, self.codec)

    def test_missing_or_orphan_record_rejects(self):
        for missing in (True, False):
            manifest, units = c.split(self.result(), self.codec)
            if missing:
                units.pop(next(iter(units)))
            else:
                extra = self.codec.pack({'orphan': True}); units[extra['sha256']] = extra
            with self.assertRaisesRegex(ValueError, 'inventory'):
                c.join(manifest, units, self.codec)

    def test_rehashed_orphan_inventory_rejects(self):
        manifest, units = c.split(self.result(), self.codec)
        extra = self.codec.pack({'orphan': True}); units[extra['sha256']] = extra
        manifest['unit_sha256s'] = sorted(units)
        with self.assertRaisesRegex(ValueError, 'unreferenced'):
            c.join(manifest, units, self.codec)

    def test_modified_reference_digest_or_size_rejects(self):
        for field, replacement in (('scientific_sha256', 'b'*64), ('record_sha256', 'b'*64), ('byte_length', 1), ('byte_length', True)):
            manifest, units = c.split(self.result(), self.codec)
            manifest['envelope']['state']['results']['a/group'][field] = replacement
            manifest['envelope_sha256'] = s.sha(manifest['envelope'])
            with self.assertRaises(ValueError):
                c.join(manifest, units, self.codec)

    def test_changed_packed_record_rejects(self):
        manifest, units = c.split(self.result(), self.codec)
        units[next(iter(units))]['data'] = 'AAAA'
        with self.assertRaises(ValueError):
            c.join(manifest, units, self.codec)

    def test_duplicate_or_non_digest_inventory_rejects(self):
        for bad in ([H, H], ['not-a-hash'], [True]):
            manifest, units = c.split(self.result(), self.codec); manifest['unit_sha256s'] = bad
            with self.assertRaises(ValueError):
                c.join(manifest, units, self.codec)

    def test_manifest_extra_field_or_changed_kind_rejects(self):
        for key, value in (('extra', True), ('kind', 'checkpoint'), ('schema', 'other')):
            manifest, units = c.split(self.result(), self.codec); manifest[key] = value
            with self.assertRaises(ValueError):
                c.join(manifest, units, self.codec)

    def test_envelope_change_requires_matching_digest(self):
        manifest, units = c.split(self.result(), self.codec)
        manifest['envelope']['source_status'] = 'CANON'
        with self.assertRaisesRegex(ValueError, 'envelope digest'):
            c.join(manifest, units, self.codec)

    def test_cursor_cannot_count_modelled_groups_instead_of_records(self):
        value = self.result(); value['state']['completed_scenarios'] = 0
        with self.assertRaisesRegex(ValueError, 'cursor'):
            c.clone(value, self.codec)

    def test_optional_biology_none_absence_and_dedup_are_exact(self):
        for mode in ('none', 'absent', 'duplicate'):
            value = self.result()
            if mode == 'none': value['biological_owner_inputs'] = None
            elif mode == 'absent': value.pop('biological_owner_inputs')
            else: value['biological_owner_inputs'] = deepcopy(value['state']['results']['a/group'])
            manifest, units = c.split(value, self.codec)
            self.assertEqual(len(units), 2)
            self.assertEqual(c.join(manifest, units, self.codec), value)

    def test_non_native_metadata_or_invalid_state_rejects(self):
        for mutation in ('tuple', 'nonfinite', 'count', 'bool_count', 'extra_state', 'key'):
            value = self.result()
            if mutation == 'tuple': value['metadata'] = (1, 2)
            elif mutation == 'nonfinite': value['metadata'] = float('nan')
            elif mutation == 'count': value['state']['completed_scenarios'] = 3
            elif mutation == 'bool_count': value['state']['completed_scenarios'] = True
            elif mutation == 'extra_state': value['state']['unbounded'] = []
            else: value['state']['results'][1] = value['state']['results'].pop('a/group')
            with self.assertRaises(ValueError):
                c.split(value, self.codec)

    def test_scenario_inventory_bound_preserved(self):
        value = self.result(); row = value['state']['results']['a/group']
        value['state']['results'] = {str(i): row for i in range(c.MAX_SCENARIOS+1)}
        value['state']['completed_scenarios'] = c.MAX_SCENARIOS+1
        with self.assertRaisesRegex(ValueError, 'bounded exact'):
            c.split(value, self.codec)

    def test_individual_science_metadata_and_manifest_bounds_not_relaxed(self):
        with self.assertRaisesRegex(ValueError, 'unchanged8MiB'):
            self.codec.pack({'oversized': 'x'*s.MAX_BYTES})
        value = self.result(); value['oversized_metadata'] = 'x'*s.MAX_BYTES
        with self.assertRaisesRegex(ValueError, 'byte bound'):
            c.split(value, self.codec)
        manifest, units = c.split(self.result(), self.codec)
        manifest['envelope']['oversized'] = 'x'*s.MAX_BYTES
        with self.assertRaisesRegex(ValueError, 'byte bound'):
            c.join(manifest, units, self.codec)

    def test_large_aggregate_roundtrip_checkpoint_and_public_entrypoints(self):
        value = self.result(); rows = {}
        for seed in (1903, 1904):
            data = base64.b64encode(random.Random(seed).randbytes(3*1024*1024)).decode('ascii')
            rows[str(seed)] = self.codec.pack({'data': data})
        value['state']['results'] = rows
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        self.assertGreater(len(raw), s.MAX_BYTES)
        with self.assertRaisesRegex(ValueError, 'byte bound'):
            s.encoded(value)
        self.assertEqual(c.clone(value, self.codec), value)
        self.assertEqual(c.digest(value, self.codec), hashlib.sha256(raw).hexdigest())
        # Public source/recipe guards remain; only aggregate transport is split.
        fake = N(source_sha256=H, verify=lambda: None, storage=self.bundle.storage,
            parent=self.bundle.parent, module=lambda name: c if name == 'consequences' else N(run=lambda *a, **kw: deepcopy(value)))
        checkpoint = binding.Bundle.checkpoint(fake, value)
        self.assertEqual(c.clone(checkpoint, self.codec), checkpoint)
        self.assertEqual(binding.Bundle.run(fake, {}, resume=checkpoint), value)


if __name__ == '__main__':
    unittest.main()
