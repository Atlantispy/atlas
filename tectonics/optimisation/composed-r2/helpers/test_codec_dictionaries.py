"""Raw dictionary artefacts through actual candidate/seal/reopen boundaries.

Run separately: the imported integration fixture loads reviewed transformed
modules in memory. Mock dictionary bytes test persistence, not native training.
"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
import unittest

import numpy as np

import test_wp10_integration as I
import codec_dictionaries as D
from compact_contracts import ContractError


def training_fixture():
    data = b'\x37\xa4\x30\xec\x01\0\0\0' + bytes(range(248))
    provenance = dict(schema='atlas.trained-dictionary.v1', sha256=sha256(data).hexdigest(),
        array_class='metadata', dtype='|u1', shuffle='none', source_identity='a'*64,
        training_sample_sha256=['b'*64]*16, transformed_sample_sha256=['c'*64]*16,
        trainer_executable_sha256='d'*64,
        job_helper_sha256='56f66b8826b148a31b85d490c75766422eb210fdfb35c665c449d2e73788f0b4',
        training_sample_count=16, training_raw_bytes=16384, training_transformed_bytes=16384,
        capacity_bytes=16384, dictionary_bytes=len(data),
        limits=dict(process_memory_limit_bytes=128 << 20, job_memory_limit_bytes=128 << 20,
                    kill_on_close=True, breakaway=False, suspended_launch_owned=True),
        metrics=dict(peak_job_memory_used_bytes=12 << 20, peak_process_memory_used_bytes=11 << 20,
                     elapsed_seconds=.2, exit_code=0, dictionary_physical_bytes=len(data)),
        status='TRAINED_NOT_ADOPTED', production_enabled=False)
    return SimpleNamespace(data=data, metadata=provenance)


class DictionaryArtifactTests(unittest.TestCase):
    def setUp(self):
        self.fixture = I.WP10IntegrationTests(methodName='runTest')
        self.fixture.setUp()
        self.stores, self.scope = self.fixture.stores, self.fixture.scope

    def tearDown(self):
        self.fixture.stores = self.stores
        self.fixture.tearDown()

    def candidate(self, key):
        policy = dict(schema='atlas.codec-policy.v1', default=dict(codec='raw', enabled=False),
                      arrays={}, parallel_workers=1, prefetch=False)
        return self.fixture.publish(np.arange(3*8192, dtype='<u8'), key=key, policy=policy)

    def load(self, resolver, reference, **kwargs):
        defaults = dict(expected_class='metadata', expected_dtype='|u1', expected_shuffle='none')
        defaults.update(kwargs)
        return D.load_dictionary(resolver, reference, **defaults)

    def test_raw_roundtrip_unlisted_sealed_cold_reopen_and_owned_copy(self):
        trained = training_fixture()
        candidate, head = self.candidate('dictionary-head')
        reference = D.publish_dictionary(candidate, trained)
        descriptor = I.candidate_storage._json({'dtype': '|u1', 'count': len(trained.data)})
        chunk = I.candidate_storage.ArrayStore._blob_id(None, descriptor, trained.data)
        self.assertEqual(candidate._db.execute('SELECT codec FROM chunks WHERE id=?', (chunk,)).fetchone(), ('raw',))
        with self.load(candidate, reference) as loaded:
            self.assertEqual(loaded.data, trained.data)
            self.assertEqual(loaded.metadata, trained.metadata)
        self.fixture.promote(candidate, head)
        self.stores.close()
        self.stores = I.intervals.IntervalStoreSet.open_catalog(self.fixture.root/'catalog.json', scope=self.scope)
        self.fixture.stores = self.stores
        loaded = self.load(self.stores, reference, requester_interval=0)
        self.stores.close()
        self.assertEqual(loaded.data, trained.data)
        self.assertEqual(loaded.metadata['source_identity'], trained.metadata['source_identity'])
        loaded.close()

    def test_retained_dictionary_child_prevents_early_release(self):
        candidate, _ = self.candidate('child-owner')
        reference = D.publish_dictionary(candidate, training_fixture())
        loaded = self.load(candidate, reference)
        child = loaded.retain()
        with self.assertRaisesRegex(RuntimeError, 'live child'):
            loaded.close()
        child.close()
        loaded.close()

    def test_existing_compressed_dictionary_refuses_bootstrap_without_rewriting(self):
        from storage_codec_runtime import encode_candidate
        trained = training_fixture()
        trained.data = trained.data[:8] + b'x'*248
        trained.metadata['sha256'] = sha256(trained.data).hexdigest()
        candidate, _ = self.candidate('compressed-bootstrap')
        descriptor = I.candidate_storage._json({'dtype':'|u1','count':len(trained.data)})
        _, key = candidate.put_chunk(descriptor,trained.data)
        codec,payload = encode_candidate(candidate,trained.data,np.dtype('|u1'),{'codec':'palette','enabled':True})
        self.assertNotEqual(codec,'raw')
        stored = sha256(descriptor+b'\0'+codec.encode()+b'\0'+payload).hexdigest()
        candidate._db.execute('UPDATE chunks SET codec=?,payload=?,stored_sha=? WHERE id=?',
                              (codec,payload,stored,key))
        with self.assertRaisesRegex(ContractError,'bootstrap requires an existing raw chunk'):
            D.publish_dictionary(candidate,trained)
        self.assertEqual(candidate._db.execute('SELECT codec FROM chunks WHERE id=?',(key,)).fetchone(),(codec,))

    def test_binding_and_metadata_authentication_refusals(self):
        candidate, _ = self.candidate('binding-check')
        reference = D.publish_dictionary(candidate, training_fixture())
        for key, value in (('expected_class', 'string_pool'), ('expected_dtype', '<u8'), ('expected_shuffle', 'byte')):
            with self.subTest(key=key), self.assertRaisesRegex(ContractError, 'class/dtype/shuffle'):
                self.load(candidate, reference, **{key: value})
        for key in ('metadata_sha256', 'dictionary_sha256'):
            tampered = dict(reference, **{key: '0'*64})
            with self.subTest(key=key), self.assertRaises(ContractError):
                self.load(candidate, tampered)

    def test_corrupt_raw_payload_is_refused(self):
        candidate, _ = self.candidate('corruption')
        trained = training_fixture()
        reference = D.publish_dictionary(candidate, trained)
        descriptor = I.candidate_storage._json({'dtype': '|u1', 'count': len(trained.data)})
        chunk = I.candidate_storage.ArrayStore._blob_id(None, descriptor, trained.data)
        candidate._db.execute('UPDATE chunks SET payload=? WHERE id=?', (trained.data[:-1]+b'!', chunk))
        with self.assertRaisesRegex(ContractError, 'checksum'):
            self.load(candidate, reference)

    def test_provenance_refused_before_any_new_chunk(self):
        candidate, _ = self.candidate('provenance')
        initial = candidate.local_statistics()['local_chunks']
        for field, value in (('source_identity', 'not-a-hash'), ('dictionary_bytes', 999),
                             ('training_sample_count', 257), ('production_enabled', True)):
            trained = training_fixture()
            trained.metadata = deepcopy(trained.metadata)
            trained.metadata[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                D.publish_dictionary(candidate, trained)
        self.assertEqual(candidate.local_statistics()['local_chunks'], initial)

    def test_second_interval_reuses_raw_dictionary_content(self):
        trained = training_fixture()
        first, head = self.candidate('first-dictionary')
        first_ref = D.publish_dictionary(first, trained)
        self.fixture.promote(first, head)
        second, next_head = self.candidate('second-dictionary')
        before = second.local_statistics()['local_chunks']
        second_ref = D.publish_dictionary(second, trained)
        self.assertEqual(second.local_statistics()['local_chunks'], before)
        self.assertEqual(second_ref['dictionary_sha256'], first_ref['dictionary_sha256'])
        with self.load(second, second_ref) as loaded:
            self.assertEqual(loaded.data, trained.data)
        self.fixture.promote(second, next_head)
        with self.load(self.stores, second_ref, requester_interval=1) as loaded:
            self.assertEqual(loaded.data, trained.data)


if __name__ == '__main__':
    unittest.main()
