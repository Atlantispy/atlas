"""Actual native codec through sealed intervals and an independent cold reader."""
import gc
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

import test_wp10_integration as I
from codec_dictionaries import publish_dictionary, load_dictionary
from storage_zstd_backend import ZstdBackend
from storage_codec_runtime import decode_many, CodecRule, encode_candidate

DLL = os.environ.get('WP10_ZSTD_TEST_DLL')
DICTIONARY = os.environ.get('WP10_ZSTD_TEST_DICTIONARY')
DLL_SHA = 'a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28'

def backend(budget, data):
    sha = hashlib.sha256(data).hexdigest()
    return ZstdBackend(DLL, expected_sha256=DLL_SHA, dictionaries={sha:data},
                       dictionary_sha256=sha, dictionary_budget=budget)

@unittest.skipUnless(DLL and DICTIONARY, 'built codec and real trained dictionary required')
class NativeIntervalTests(unittest.TestCase):
    setUp = I.WP10IntegrationTests.setUp
    tearDown = I.WP10IntegrationTests.tearDown
    promote = I.WP10IntegrationTests.promote
    publish = I.WP10IntegrationTests.publish

    def test_combined_delta_zstd_seals_and_reopens_without_writer_policy(self):
        self.stores.configure_codec_backend(ZstdBackend(DLL, expected_sha256=DLL_SHA))
        offsets = I.np.cumsum(I.np.random.default_rng(10).integers(
            0, 1024, size=3*8192, dtype='<u8'), dtype='<u8')
        policy = I.fixture_policy()
        policy['arrays'][I.FIXTURE_SCHEMA + '/offsets'].update(codec='delta-zstd-v1', level=1, shuffle='byte')
        candidate, reference = self.publish(offsets, key='combined', policy=policy)
        labels = [row[0] for row in candidate._db.execute('SELECT codec FROM chunks')]
        self.assertIn('delta-zstd-v1:byte:1', labels)
        self.promote(candidate, reference)
        expected = hashlib.sha256(offsets.tobytes()).hexdigest()
        self.assertEqual(I._read_hash(self.stores, reference, self.scope, 'offsets'), expected)
        candidate.close()
        self.stores.close()
        result = subprocess.run([sys.executable, '-B', __file__, '--fresh-combined',
            str(self.root/'catalog.json'), json.dumps(reference.to_wire()), expected],
            capture_output=True, text=True, env=dict(os.environ), timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('native-combined-cold-pass', result.stdout)

    def test_zstd_identity_dedup_old_reader_and_parallel_manifest(self):
        arrays = {'offsets': I.np.arange(3*8192,dtype='<u8')}
        limits = I.candidate_storage.StoreLimits(chunk_bytes=65536,max_array_bytes=1<<20,max_store_bytes=16<<20)
        bodies = []
        for mode in ('raw','serial','parallel'):
            path = self.root / (mode+'.sqlite')
            with I.candidate_storage.ArrayStore(path,limits,I.candidate_storage.Compression(codec='raw'),budget=self.budget) as store:
                # A plain ArrayStore snapshot array is keyed by the store schema.
                policy = I.fixture_policy(I.candidate_storage._SCHEMA)
                policy['arrays'][I.candidate_storage._SCHEMA+'/offsets'].update(codec='zstd',level=1,shuffle='byte')
                if mode == 'parallel':
                    policy.update(parallel_workers=2,prefetch=True)
                store.configure_codec_backend(ZstdBackend(DLL,expected_sha256=DLL_SHA))
                if mode != 'raw':
                    store.configure_codec_policy(policy)
                store.put('d'*64,arrays,metadata={})
                bodies.append(store._db.execute('SELECT body FROM snapshots WHERE id=?',('d'*64,)).fetchone()[0])
                count = store._db.execute('SELECT count(*) FROM chunks').fetchone()[0]
                if mode == 'raw':
                    store.configure_codec_policy(policy)
                store.put('e'*64,arrays,metadata={})
                self.assertEqual(store._db.execute('SELECT count(*) FROM chunks').fetchone()[0],count)
                self.assertEqual(b''.join(chunk.tobytes() for _,chunk in store.iter_chunks('d'*64,'offsets',budget=self.budget)),arrays['offsets'].tobytes())
                if mode != 'raw':
                    row = store._db.execute('SELECT codec,payload FROM chunks LIMIT 1').fetchone()
                    self.assertTrue(row[0].startswith('wp10-zstd-v1:'))
                    with self.assertRaises(Exception):
                        I.original_storage.ArrayStore._decode(store,row[0],row[1],I.np.dtype('<u8'),8192)
                self.assertLessEqual(store.codec_statistics()['workspace']['peak_reserved_bytes'],limits.codec_workspace_bytes)
        self.assertEqual(bodies[0],bodies[1])
        self.assertEqual(bodies[0],bodies[2])

    def test_native_parallel_decode_order_and_workspace(self):
        limits = I.candidate_storage.StoreLimits(chunk_bytes=65536,max_array_bytes=1<<20,max_store_bytes=16<<20)
        with I.candidate_storage.ArrayStore(self.root/'decode.sqlite',limits,
                I.candidate_storage.Compression(codec='raw'),budget=self.budget) as store:
            store.configure_codec_backend(ZstdBackend(DLL,expected_sha256=DLL_SHA))
            expected = [(I.np.arange(8192,dtype='<u8')+i).tobytes() for i in range(8)]
            records = []
            for raw in expected:
                label,payload = encode_candidate(store,raw,I.np.dtype('<u8'),CodecRule('zstd',True))
                records.append((label,payload,I.np.dtype('<u8'),8192))
            with decode_many(store,iter(records),workers=2) as results:
                self.assertEqual(list(results),expected)
            self.assertLessEqual(store.codec_statistics()['workspace']['peak_reserved_bytes'],8<<20)

    def test_trained_dictionary_publish_seal_cold_reopen_and_fresh_process(self):
        data = Path(DICTIONARY).read_bytes()
        metadata = json.loads(Path(DICTIONARY).with_suffix('.json').read_text())
        trained = SimpleNamespace(data=data, metadata=metadata)
        self.stores.configure_codec_backend(backend(self.budget, data))
        schema = 'wp10.native.fixture.v1'
        policy = I.fixture_policy(schema)
        policy['arrays'][schema+'/offsets'].update(codec='trained-zstd-v1', level=1, shuffle='byte',
                                                   dictionary_sha256=metadata['sha256'])
        policy['arrays'][schema+'/values'] = dict(policy['arrays'][schema+'/offsets'])
        policy['arrays'][schema+'/values'].update(codec='zstd', dictionary_sha256=None)
        candidate = self.stores.begin_interval(None,producer_identity='b'*64,runtime_identity='c'*64,
                                               codec_policy=policy)
        dictionary_ref = publish_dictionary(candidate, trained)
        offsets = I.np.arange(3*8192,dtype='<u8')
        values = I.np.arange(3*8192,dtype='<f8')*.25
        identity = I.LogicalIdentity('wp10.native.fixture.v1',hashlib.sha256(b'native-fixture').hexdigest(),offsets.nbytes)
        ref = I.segments.SegmentBackend().publish(candidate, record_schema=identity.record_schema,
            identity=identity, metadata=I.segments.canonical({'dictionary':dictionary_ref}),
            arrays=lambda: iter([I.Source(self.scope,'offsets',offsets),I.Source(self.scope,'values',values)]),
            producer='b'*64, representation_profile='wp10.native.columns.v1',scope=self.scope)
        labels = [row[0] for row in candidate._db.execute('SELECT codec FROM chunks')]
        self.assertTrue(any(label.endswith(metadata['sha256']) for label in labels))
        self.assertIn('wp10-zstd-v1:byte:1:-', labels)
        self.promote(candidate, ref)
        candidate.close()
        del candidate
        self.stores.close()
        del self.stores
        gc.collect()
        self.stores = I.intervals.IntervalStoreSet.open_catalog(self.root/'catalog.json',scope=self.scope)
        with load_dictionary(self.stores, dictionary_ref, expected_class=metadata['array_class'],
                expected_dtype='<u8',expected_shuffle='byte',requester_interval=0) as loaded:
            self.stores.configure_codec_backend(backend(self.budget,loaded.data))
        expected = hashlib.sha256(offsets.tobytes()).hexdigest()
        self.assertEqual(I._read_hash(self.stores,ref,self.scope,'offsets'),expected)
        self.assertTrue(self.stores.verify_file_sha256(0))
        command=[sys.executable,__file__,'--fresh',str(self.root/'catalog.json'),
                 json.dumps(dictionary_ref),json.dumps(ref.to_wire()),expected,metadata['array_class']]
        result=subprocess.run(command,capture_output=True,text=True,env=dict(os.environ),timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('native-dictionary-cold-pass',result.stdout)
        # Closed store references no longer retain dictionary leases.
        self.stores.close()
        del self.stores
        gc.collect()
        self.stores = I.intervals.IntervalStoreSet.open_catalog(self.root/'catalog.json',scope=self.scope)

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--fresh-combined':
        budget = I.WorkBudget(512 << 20)
        scope = I.create_retained_scope(budget, process_epoch='wp10-combined-cold')
        stores = I.intervals.IntervalStoreSet.open_catalog(sys.argv[2], scope=scope)
        stores.configure_codec_backend(ZstdBackend(DLL, expected_sha256=DLL_SHA))
        try:
            ref = I.SegmentRef.from_wire(json.loads(sys.argv[3]))
            assert I._read_hash(stores, ref, scope, 'offsets') == sys.argv[4]
            assert stores.verify_file_sha256(0)
        finally:
            stores.close()
            scope.close()
        assert budget.reserved_bytes == 0
        print('native-combined-cold-pass')
    elif len(sys.argv)>1 and sys.argv[1]=='--fresh':
        budget=I.WorkBudget(512<<20)
        scope=I.create_retained_scope(budget,process_epoch='wp10-native-cold')
        stores=I.intervals.IntervalStoreSet.open_catalog(sys.argv[2],scope=scope)
        ref=I.SegmentRef.from_wire(json.loads(sys.argv[4]))
        with load_dictionary(stores,json.loads(sys.argv[3]),expected_class=sys.argv[6],
                expected_dtype='<u8',expected_shuffle='byte',requester_interval=0) as loaded:
            stores.configure_codec_backend(backend(budget,loaded.data))
        assert I._read_hash(stores,ref,scope,'offsets')==sys.argv[5]
        assert stores.verify_file_sha256(0)
        stores.close()
        del stores
        gc.collect()
        scope.close()
        assert budget.reserved_bytes==0
        print('native-dictionary-cold-pass')
    else:
        unittest.main()

