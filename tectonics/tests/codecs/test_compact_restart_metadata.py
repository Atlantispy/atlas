"""Metadata of a snapshot with externalised root fields (wave 5-6 unit T-3).

`metadata` returns the bounded fields plus each external field read against its own reference hash; the rebuilt
native manifest (`_manifest`, which keeps its identity test) must give the same metadata.
"""
import gc
import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest import mock

import numpy as np

from atlas_tectonics.codecs import storage as N
from atlas_tectonics.integration.resources import WorkBudget
from atlas_tectonics._private.codecs import compact_restart_store as CRS
from atlas_tectonics._private.codecs.compact_contracts import ContractError
from atlas_tectonics._private.codecs.content_cache import create_retained_scope


def key(text):
    return sha256(text.encode()).hexdigest()


def descriptor(name, size):
    rows, total, i = [], 0, 0
    while total < size:
        row = {'id': f'{name}:{i}', 'value': i * 0.125 + 1e-9 * i, 'count': i, 'nested': {'y': [i, None, True]}}
        total += len(json.dumps(row, separators=(',', ':')))
        rows.append(row)
        i += 1
    return {'schema': f'synthetic.{name}.v1', 'rows': rows}


def root_metadata():
    return {'schema': 'atlas.private.collar-workflow.r1', 'workflow_id': key('workflow'), 'key': key('root'),
            'kind': 'root', 'sequence': 0, 'funding': descriptor('funding', 40_000),
            'exterior_owner': descriptor('exterior-owner', 30_000), 'collar_plan': descriptor('collar-plan', 20_000),
            'exterior_remainder': descriptor('exterior-remainder', 8_000), 'state': {'small': [1, 2, 3]}}


class Flipped(bytearray):
    """The field bytes read back differ from the field's reference hash (first byte of each chunk flipped)."""
    def __setitem__(self, index, value):
        value = bytes(value)
        super().__setitem__(index, bytes([value[0] ^ 1]) + value[1:])


class ExternalMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='crs-metadata-')
        self.budget = WorkBudget(768 << 20)
        self.scope = create_retained_scope(self.budget, process_epoch='crs-metadata')
        self.store = CRS.CompactRestartStore.create_migration(
            Path(self.temp.name) / 'catalog.json', workflow_id=key('workflow'), scope=self.scope,
            producer_identity=key('producer'), runtime_identity=key('runtime'))
        self.metadata = root_metadata()
        self.store.put(self.metadata['key'], {'values': np.arange(900, dtype='<i8')}, self.metadata)

    def tearDown(self):
        self.store.close()
        gc.collect()
        self.scope.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def test_metadata_equals_the_rebuilt_manifest_metadata(self):
        with self.store._read_scope(), self.store._segment(self.metadata['key']) as view:
            self.assertEqual(view._owner.value['representation_profile'], CRS.EXTERNAL_PROFILE)
        direct = self.store.metadata(self.metadata['key'])
        self.assertEqual(direct, self.store._manifest(self.metadata['key'])['metadata'])
        self.assertEqual(N._json(direct), N._json(self.metadata))

    def test_a_field_whose_bytes_differ_from_its_reference_still_refuses(self):
        with mock.patch.object(CRS, 'bytearray', Flipped, create=True), \
                self.assertRaisesRegex(ContractError, 'differ from their reference'):
            self.store.metadata(self.metadata['key'])


if __name__ == '__main__':
    unittest.main()
