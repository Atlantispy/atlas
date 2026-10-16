"""Focused WP10 exactness, refusal, identity and lifetime checks on new stores."""
from __future__ import annotations

from concurrent.futures import CancelledError
import hashlib
import importlib
import math
import os
import pathlib
import struct
import sys
import tempfile
import threading
import types
import unittest
import weakref
from unittest import mock

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
FROZEN = HERE.parent / 'composed-r1' / 'runtime-src'
SCRATCH = pathlib.Path('C:/Users/LOCAL_USER/Documents/Codex/2026-10-15/c-Users-LOCAL_USER-documents-codex-2026-2/work/wp10-storage')
sys.path.insert(0, str(FROZEN))
sys.path.insert(0, str(HERE))
import storage_codec_patch as patch
import storage_codec_runtime as codec
import codec_tradeoff as tradeoff


def load_storage():
    source = (FROZEN / 'atlas_tectonics' / 'storage.py').read_text(encoding='utf-8')
    old = importlib.import_module('atlas_tectonics.storage')
    original = types.ModuleType('wp10_original_storage')
    original.__package__ = 'atlas_tectonics'
    sys.modules[original.__name__] = original
    exec(compile(source, str(FROZEN / 'atlas_tectonics' / 'storage.py'), 'exec'), original.__dict__)
    candidate = types.ModuleType(old.__name__)
    candidate.__package__ = 'atlas_tectonics'
    sys.modules[candidate.__name__] = candidate
    exec(compile(patch.transform(source), '<wp10-transformed-storage>', 'exec'), candidate.__dict__)
    return original, candidate


OLD, STORAGE = load_storage()
from atlas_tectonics.resources import MemoryLimitError, WorkBudget

NATIVE_DLL = os.environ.get('WP10_ZSTD_TEST_DLL')


def policy(default='raw', *, workers=1, prefetch=False, arrays=None):
    # Explicit synthetic-only fixture, never normal production activation.
    # Plain ArrayStore snapshot arrays are keyed '<store schema>/<array name>'.
    return codec.CodecPolicy(codec.CodecRule(default, default != 'raw'),
                             tuple((f'{STORAGE._SCHEMA}/{name}', codec.CodecRule(value, True))
                                   for name, value in sorted((arrays or {}).items())),
                             workers, prefetch)


class CodecTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.root = pathlib.Path(self.temp.name)
        self.budget = WorkBudget(128 * 1024 * 1024)
        self.limits = STORAGE.StoreLimits(4096, 4*1024*1024, 16*1024*1024,
            max_manifest_bytes=65536, verified_cache_entries=16, sqlite_cache_bytes=4096)
        self.store = STORAGE.ArrayStore(self.root/'store.sqlite', self.limits,
                                        STORAGE.Compression(codec='raw'), budget=self.budget)

    def tearDown(self):
        self.store.close()
        self.assertEqual(self.budget.reserved_bytes, 0)
        self.temp.cleanup()

    def roundtrip(self, array, name):
        raw, dt = array.tobytes(), array.dtype
        label, payload = codec.encode_candidate(self.store, raw, dt, {'codec':name, 'enabled':True})
        self.assertEqual(codec.decode_candidate(self.store, label, payload, dt, array.size), raw)
        descriptor = STORAGE._json({'dtype':dt.str, 'count':array.size})
        self.assertEqual(self.store._blob_id(descriptor, raw),
                         self.store._blob_id(descriptor, codec.decode_candidate(self.store, label, payload, dt, array.size)))
        return label, payload

    def test_exact_delta_signed_unsigned_limits(self):
        for size in (1, 2, 4, 8):
            for kind in ('u', 'i'):
                with self.subTest(kind=kind, size=size):
                    dtype = np.dtype(f'<{kind}{size}')
                    limits = np.iinfo(dtype)
                    words = np.arange(0, 128, dtype=f'<u{size}')
                    words = words + np.array(limits.max-63, dtype=f'<u{size}')
                    self.roundtrip(words.view(dtype), 'delta-v1')
                    self.roundtrip(np.array([limits.min, limits.max, 0, -1 if kind=='i' else 1]*64, dtype=dtype), 'delta-v1')

    def test_delta_label_and_malformed_headers_before_allocation(self):
        array = np.arange(128, dtype='<u8')
        label, payload = self.roundtrip(array, 'delta-v1')
        self.assertEqual(label, 'delta-v1')
        damaged = bytearray(payload)
        struct.pack_into('<Q', damaged, 6, 2**63)
        with mock.patch.object(np, 'empty', side_effect=AssertionError('allocated')):
            with self.assertRaisesRegex(STORAGE.StoreError, 'delta dimensions'):
                codec.decode_candidate(self.store, label, bytes(damaged), array.dtype, array.size)
            with self.assertRaisesRegex(STORAGE.StoreError, 'dtype/count'):
                codec.decode_candidate(self.store, label, payload, array.dtype, 2**63)
        with self.assertRaises(STORAGE.StoreError):
            codec.decode_candidate(self.store, label, payload[:-1], array.dtype, array.size)

    def test_raw_palette_nonfinite_bit_patterns(self):
        for dtype in ('u1','<u2','<u4','<u8','i1','<i2','<i4','<i8','?'):
            self.roundtrip(np.tile(np.array([0,1], dtype=dtype), 128), 'palette')
        bits = np.array([0x7ff8000000000042, 0x8000000000000000, 0x7ff0000000000000,
                         0xfff0000000000000], dtype='<u8')
        for name in ('raw', 'palette', 'delta-v1', 'zstd'):
            self.roundtrip(bits.view('<f8'), name)
        with self.assertRaisesRegex(STORAGE.StoreError, 'nonfinite'):
            self.store.put('1'*64, {'field':bits.view('<f8')})

    def test_native_fallback_and_legacy_reader(self):
        import blosc2 as b
        raw = np.arange(256, dtype='<u4').tobytes()
        for shuffle in ('none', 'byte', 'bit'):
            label, payload = codec.encode_candidate(self.store,raw,np.dtype('<u4'),
                dict(codec='zstd',enabled=True,shuffle=shuffle,level=3))
            self.assertEqual((label,payload), ('raw',raw))
            native = b.compress2(raw, codec=b.Codec.ZSTD, clevel=3, typesize=4,nthreads=1,
                filters=[b.Filter.NOFILTER]*5+[{'none':b.Filter.NOFILTER,'byte':b.Filter.SHUFFLE,'bit':b.Filter.BITSHUFFLE}[shuffle]])
            self.assertEqual(codec.decode_candidate(self.store,'blosc2-zstd-'+shuffle+':3:legacy',bytes(native),np.dtype('<u4'),256),raw)
            with mock.patch.object(b,'decompress2',side_effect=AssertionError('allocated')):
                with self.assertRaisesRegex(STORAGE.StoreError, 'size before allocation'):
                    codec.decode_candidate(self.store,'blosc2-zstd-'+shuffle,bytes(native),np.dtype('<u4'),255)
        self.assertIn('native codec workspace', next(iter(self.store.codec_statistics()['fallbacks'])))

    def test_dictionary_label_refuses(self):
        with self.assertRaisesRegex(STORAGE.StoreError,'unsupported bounded codec'):
            codec.decode_candidate(self.store,'trained-zstd-v1:'+'a'*64,b'ignored',np.dtype('u1'),4)

    def test_backend_admission_precedes_native_allocation(self):
        observations=[]
        owner=self
        class Backend:
            def encode_workspace_bound(self,nbytes,dt,rule):
                return 8192
            def encode(self,raw,dt,rule):
                observations.append(owner.store._codec_state.budget.reserved_bytes)
                return 'wp10-zstd-test',raw
            def owns_label(self,label):
                return label=='wp10-zstd-test'
            def inspect_decode(self,label,payload,dt,count):
                return 8192
            def decode(self,label,payload,dt,count):
                observations.append(owner.store._codec_state.budget.reserved_bytes)
                return payload
        backend=Backend()
        self.store._codec_backend=backend
        raw=np.arange(128,dtype='<u4').tobytes()
        result=codec.encode_candidate(self.store,raw,np.dtype('<u4'),{'codec':'zstd','enabled':True})
        self.assertEqual(codec.decode_candidate(self.store,*result,np.dtype('<u4'),128),raw)
        self.assertEqual(observations,[8192,8192])
        with mock.patch.object(backend,'inspect_decode',return_value=self.limits.codec_workspace_bytes+1):
            with mock.patch.object(backend,'decode',side_effect=AssertionError('native allocation')):
                with self.assertRaisesRegex(STORAGE.StoreError,'exceeds codec_workspace_bytes'):
                    codec.decode_candidate(self.store,*result,np.dtype('<u4'),128)

    def test_prefetch_legacy_zstd_uses_serial_fallback(self):
        import blosc2 as b
        array=np.arange(512,dtype='<u4')
        self.store._codec_policy=policy('raw')
        self.store.put('7'*64,{'field':array})
        key,descriptor=self.store._db.execute('SELECT id,descriptor FROM chunks').fetchone()
        label='blosc2-zstd-byte:1:legacy'
        payload=bytes(b.compress2(array.tobytes(),codec=b.Codec.ZSTD,clevel=1,typesize=4,nthreads=1))
        stored=STORAGE._hash(descriptor+b'\0'+label.encode()+b'\0'+payload)
        self.store._db.execute('UPDATE chunks SET codec=?,payload=?,stored_sha=? WHERE id=?',(label,payload,stored,key))
        self.store._codec_policy=policy('raw',workers=2,prefetch=True)
        result=list(self.store.iter_chunks('7'*64,'field'))
        np.testing.assert_array_equal(result[0][1],array)
        self.assertEqual(self.store.codec_statistics()['workspace']['reserved_bytes'],0)

    def test_immutable_identity_dedup_and_old_reader_refusal(self):
        array = np.arange(512,dtype='<u4')
        self.store._codec_policy = policy('raw')
        self.store.put('2'*64, {'offsets':array})
        raw_row = self.store._db.execute('SELECT id,codec,payload FROM chunks').fetchone()
        self.store._codec_policy = policy('delta-v1')  # fixture deliberately changes producer only
        self.store.put('3'*64, {'offsets':array})
        self.assertEqual(self.store._db.execute('SELECT id,codec,payload FROM chunks').fetchone(),raw_row)
        self.assertEqual(self.store.statistics()['unique_chunks'],1)
        label,payload = self.roundtrip(array,'delta-v1')
        self.assertEqual(label,'delta-v1')
        with self.assertRaisesRegex(OLD.StoreError,'unsupported stored codec'):
            OLD.ArrayStore._decode(self.store,label,payload,array.dtype,array.size)

    def test_serial_parallel_manifest_and_prefetch_equal(self):
        arrays={'offsets':np.arange(4096,dtype='<u4'),'tags':np.arange(4096,dtype='u1')%3}
        self.store._codec_policy=policy('delta-v1',workers=2,prefetch=True,arrays={'tags':'palette'})
        self.store.put('4'*64,arrays)
        expected=self.store._db.execute('SELECT body FROM snapshots').fetchone()[0]
        other=STORAGE.ArrayStore(self.root/'serial.sqlite',self.limits,STORAGE.Compression(codec='raw'),budget=self.budget)
        try:
            other._codec_policy=policy('delta-v1',arrays={'tags':'palette'})
            other.put('4'*64,arrays)
            self.assertEqual(other._db.execute('SELECT body FROM snapshots').fetchone()[0],expected)
            for name, array in arrays.items():
                np.testing.assert_array_equal(np.concatenate([part for _,part in self.store.iter_chunks('4'*64,name)]),array)
        finally:
            other.close()
        self.assertLessEqual(self.store.codec_statistics()['workspace']['peak_reserved_bytes'],self.limits.codec_workspace_bytes)
        self.assertEqual(self.store.codec_statistics()['workspace']['reserved_bytes'],0)

    def test_direct_budget_failure_releases(self):
        small=types.SimpleNamespace(limits=self.limits,_budget=WorkBudget(1024))
        with self.assertRaises(MemoryLimitError):
            codec.encode_candidate(small,b'1234',np.dtype('u1'),{'codec':'raw'})
        self.assertEqual(small._budget.reserved_bytes,0)
        self.assertEqual(small._codec_state.budget.reserved_bytes,0)

    def test_parallel_decode_order_and_cancel_joins(self):
        arrays=[np.arange(i,i+128,dtype='<u4') for i in range(4)]
        records=[]
        for array in arrays:
            label,payload=self.roundtrip(array,'delta-v1')
            records.append((label,payload,array.dtype,array.size))
        with codec.decode_many(self.store,records,workers=2) as results:
            self.assertEqual(list(results),[array.tobytes() for array in arrays])
        cancel=threading.Event()
        active=threading.Event()
        exited=threading.Event()
        def worker(_):
            active.set()
            cancel.set()
            try:
                raise RuntimeError('synthetic worker failure')
            finally:
                exited.set()
        with self.assertRaises((CancelledError,RuntimeError)):
            with codec._ordered_map(self.store,worker,[1,2],workers=2,retained_per_task=4096,cancel=cancel) as results:
                list(results)
        self.assertTrue(active.is_set())
        self.assertTrue(exited.is_set())
        self.assertEqual(self.store.codec_statistics()['workspace']['reserved_bytes'],0)

    def test_configuration_and_policy_validation(self):
        base=dict(schema=codec.POLICY_SCHEMA,default={},arrays={},parallel_workers=1,prefetch=False)
        self.store.configure_codec_policy(base)
        with self.assertRaisesRegex(STORAGE.StoreError,'immutable'):
            self.store.configure_codec_policy(base)
        bad=dict(base,default={'codec':'delta-v1','enabled':True})
        with self.assertRaisesRegex(ValueError,'adoption evidence'):
            codec.normalise_policy(bad)
        for bad in (dict(base,parallel_workers=True),dict(base,unknown=1),dict(base,parallel_workers=3)):
            with self.assertRaises(ValueError):
                codec.normalise_policy(bad)

    def test_source_drift_refuses(self):
        raw=(FROZEN/'atlas_tectonics'/'storage.py').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),patch.SOURCE_SHA256)
        with self.assertRaisesRegex(ValueError,'source drift'):
            patch.transform_bytes(raw+b'\n')


@unittest.skipUnless(NATIVE_DLL, 'private native DLL required for delta-zstd acceptance')
class DeltaZstdTests(unittest.TestCase):
    tearDown = CodecTests.tearDown
    roundtrip = CodecTests.roundtrip

    def setUp(self):
        CodecTests.setUp(self)
        from storage_zstd_backend import ZstdBackend
        digest = os.environ.get('WP10_ZSTD_TEST_DLL_SHA256') or hashlib.sha256(pathlib.Path(NATIVE_DLL).read_bytes()).hexdigest()
        self.backend = ZstdBackend(NATIVE_DLL, expected_sha256=digest)
        self.store.configure_codec_backend(self.backend)

    def test_signed_unsigned_modular_limits_all_shuffles(self):
        for width in (1,2,4,8):
            for kind in ('i','u'):
                dt=np.dtype(f'<{kind}{width}')
                limits=np.iinfo(dt)
                arrays=[np.array([limits.min,limits.max,0,1]*64,dtype=dt),
                        (np.arange(128,dtype=f'<u{width}')+np.array(limits.max-63,dtype=f'<u{width}')).view(dt)]
                for shuffle in ('none','byte','bit'):
                    for array in arrays:
                        with self.subTest(dtype=dt.str,shuffle=shuffle):
                            raw=array.tobytes()
                            label,payload=codec.encode_candidate(self.store,raw,dt,
                                dict(codec='delta-zstd-v1',enabled=True,shuffle=shuffle,level=3))
                            self.assertTrue(label.startswith('delta-zstd-v1:'))
                            self.assertEqual(codec.decode_candidate(self.store,label,payload,dt,array.size),raw)
                            self.assertEqual(payload[14:14+width],raw[:width])
                            descriptor=STORAGE._json({'dtype':dt.str,'count':array.size})
                            self.assertEqual(self.store._blob_id(descriptor,raw),
                                self.store._blob_id(descriptor,codec.decode_candidate(self.store,label,payload,dt,array.size)))
        self.assertLessEqual(self.store.codec_statistics()['workspace']['peak_reserved_bytes'],self.limits.codec_workspace_bytes)

    def test_header_frame_and_dictionary_policy_refusals(self):
        array=np.arange(256,dtype='<i8')
        label,payload=self.roundtrip(array,'delta-zstd-v1')
        cases=[]
        for offset,value in ((0,0),(4,1),(5,1)):
            damaged=bytearray(payload); damaged[offset]=value
            cases.append((label,bytes(damaged),array.dtype,array.size))
        damaged=bytearray(payload); struct.pack_into('<Q',damaged,6,2**63)
        cases.extend([(label,bytes(damaged),array.dtype,array.size),
                      (label,payload[:22],array.dtype,array.size),
                      (label+':dictionary',payload,array.dtype,array.size),
                      (label,payload,np.dtype('<f8'),array.size)])
        with mock.patch.object(np,'empty',side_effect=AssertionError('NumPy allocation')):
            with mock.patch.object(type(self.backend),'inspect_decode',side_effect=AssertionError('native inspection')):
                for args in cases:
                    with self.assertRaisesRegex(STORAGE.StoreError,'before allocation'):
                        codec.decode_candidate(self.store,*args)
        with mock.patch.object(type(self.backend),'_allocate_arena',side_effect=AssertionError('native arena allocation')):
            for damaged in (payload[:-1],payload+b'extra'):
                with self.assertRaises(ValueError):
                    codec.decode_candidate(self.store,label,damaged,array.dtype,array.size)
        with self.assertRaisesRegex(ValueError,'dictionary policy identity'):
            codec.encode_candidate(self.store,array.tobytes(),array.dtype,
                dict(codec='delta-zstd-v1',enabled=True,dictionary_sha256='a'*64))
        base=dict(schema=codec.POLICY_SCHEMA,default={'codec':'delta-zstd-v1','enabled':False},
                  arrays={},parallel_workers=1,prefetch=False)
        self.assertEqual(codec.normalise_policy(base).default.codec,'delta-zstd-v1')
        base['default']['enabled']=True
        with self.assertRaisesRegex(ValueError,'adoption evidence'):
            codec.normalise_policy(base)

    def test_raw_fallbacks_and_maximum_chunk(self):
        for array in (np.array([17],dtype='<u8'),np.array([True,False]*64),
                      np.array([0x7ff8000000000042,0x8000000000000000]*64,dtype='<u8').view('<f8')):
            raw=array.tobytes()
            self.assertEqual(codec.encode_candidate(self.store,raw,array.dtype,
                dict(codec='delta-zstd-v1',enabled=True)),('raw',raw))
        raw=np.random.default_rng(73).integers(0,256,4096,dtype='u1').tobytes()
        self.assertEqual(codec.encode_candidate(self.store,raw,np.dtype('u1'),
            dict(codec='delta-zstd-v1',enabled=True)),('raw',raw))
        limits=STORAGE.StoreLimits(65536,65536,65536)
        receiver=types.SimpleNamespace(limits=limits,_budget=self.budget,_codec_backend=self.backend)
        array=np.arange(8192,dtype='<u8')
        label,payload=codec.encode_candidate(receiver,array.tobytes(),array.dtype,
            dict(codec='delta-zstd-v1',enabled=True))
        self.assertEqual(codec.decode_candidate(receiver,label,payload,array.dtype,array.size),array.tobytes())
        larger=types.SimpleNamespace(limits=STORAGE.StoreLimits(131072,131072,131072),
                                    _budget=self.budget,_codec_backend=self.backend)
        huge=np.arange(16384,dtype='<u8').tobytes()
        self.assertEqual(codec.encode_candidate(larger,huge,np.dtype('<u8'),
            dict(codec='delta-zstd-v1',enabled=True)),('raw',huge))

    def test_combined_budget_is_checked_before_native_or_numpy_allocation(self):
        from dataclasses import replace
        array=np.arange(256,dtype='<u4'); raw=array.tobytes()
        rule=dict(codec='delta-zstd-v1',enabled=True)
        bound=codec.workspace_bound(len(raw),array.dtype,rule,backend=self.backend)
        limited=types.SimpleNamespace(limits=replace(self.limits,codec_workspace_bytes=bound-1),
                                     _budget=self.budget,_codec_backend=self.backend)
        with mock.patch.object(type(self.backend),'encode',side_effect=AssertionError('native encoder called')):
            self.assertEqual(codec.encode_candidate(limited,raw,array.dtype,rule),('raw',raw))
        label,payload=self.roundtrip(array,'delta-zstd-v1')
        native='wp10-zstd-v1:byte:1:-'
        copy_need=65536+len(payload)
        native_need=self.backend.inspect_decode(native,payload[18:],array.dtype,array.size-1)
        cap=copy_need+native_need+3*len(raw)+65536-1
        limited=types.SimpleNamespace(limits=replace(self.limits,codec_workspace_bytes=cap),
                                     _budget=self.budget,_codec_backend=self.backend)
        with mock.patch.object(np,'empty',side_effect=AssertionError('NumPy allocation')):
            with mock.patch.object(type(self.backend),'_allocate_arena',side_effect=AssertionError('native arena allocation')):
                with self.assertRaisesRegex(ValueError,'combined codec_workspace_bytes'):
                    codec.decode_candidate(limited,label,payload,array.dtype,array.size)
        self.assertEqual(limited._codec_state.budget.reserved_bytes,0)

    def test_failure_tracebacks_release_delta_arrays_and_native_arenas(self):
        array=np.arange(256,dtype='<u4'); raw=array.tobytes()
        label,payload=self.roundtrip(array,'delta-zstd-v1')
        original_empty=np.empty
        original_arena=self.backend._allocate_arena
        references=[]; failures=[]
        def track_empty(*args,**kwargs):
            value=original_empty(*args,**kwargs); references.append(weakref.ref(value)); return value
        def track_arena(nbytes):
            value,pointer=original_arena(nbytes); references.append(weakref.ref(value)); return value,pointer
        def fail_sum(*args,**kwargs):
            raise RuntimeError('synthetic reconstruction failure')
        def retain_failure(function):
            try:
                function()
            except (ValueError,RuntimeError) as failure:
                failures.append(failure)
            else:
                self.fail('expected failure')
            self.assertIsNotNone(failures[-1].__traceback__)
            self.assertTrue(all(reference() is None for reference in references))
            self.assertEqual(self.store.codec_statistics()['workspace']['reserved_bytes'],0)
        with mock.patch.object(np,'empty',new=track_empty):
            with mock.patch.object(type(self.backend),'_allocate_arena',new=staticmethod(track_arena)):
                with mock.patch.object(self.backend._lib,'wp10_zstd_encode',return_value=1):
                    retain_failure(lambda:codec.encode_candidate(self.store,raw,array.dtype,
                        dict(codec='delta-zstd-v1',enabled=True)))
                with mock.patch.object(np,'cumsum',new=fail_sum):
                    retain_failure(lambda:codec.decode_candidate(self.store,label,payload,array.dtype,array.size))
                damaged=payload[:-1]+bytes([payload[-1]^1])
                retain_failure(lambda:codec.decode_candidate(self.store,label,damaged,array.dtype,array.size))
        self.assertGreaterEqual(len(references),5)

    def test_store_raw_dedup_old_reader_refusal_and_parallel_manifest(self):
        array=np.arange(512,dtype='<u4')
        self.store._codec_policy=policy('raw')
        self.store.put('8'*64,{'offsets':array})
        original=self.store._db.execute('SELECT id,codec,payload FROM chunks').fetchone()
        self.store._codec_policy=policy('delta-zstd-v1',workers=2,prefetch=True)
        self.store.put('9'*64,{'offsets':array})
        self.assertEqual(self.store._db.execute('SELECT id,codec,payload FROM chunks').fetchone(),original)
        self.assertEqual(self.store.statistics()['unique_chunks'],1)
        many=np.arange(8192,dtype='<u4')+19
        self.store.put('a'*64,{'offsets':many})
        expected=self.store._db.execute('SELECT body FROM snapshots WHERE id=?',('a'*64,)).fetchone()[0]
        label,payload=self.roundtrip(array,'delta-zstd-v1')
        with self.assertRaisesRegex(OLD.StoreError,'unsupported stored codec'):
            OLD.ArrayStore._decode(self.store,label,payload,array.dtype,array.size)
        other=STORAGE.ArrayStore(self.root/'combined-serial.sqlite',self.limits,
                                 STORAGE.Compression(codec='raw'),budget=self.budget)
        try:
            other.configure_codec_backend(self.backend)
            other._codec_policy=policy('delta-zstd-v1')
            other.put('a'*64,{'offsets':many})
            self.assertEqual(other._db.execute('SELECT body FROM snapshots').fetchone()[0],expected)
            np.testing.assert_array_equal(np.concatenate([chunk for _,chunk in
                self.store.iter_chunks('a'*64,'offsets')]),many)
        finally:
            other.close()
        self.assertLessEqual(self.store.codec_statistics()['workspace']['peak_reserved_bytes'],self.limits.codec_workspace_bytes)


class TradeoffPolicyTests(unittest.TestCase):
    def evidence(self):
        # A deliberately synthetic unit-test record labelled real exercises the
        # validator only. It is never written as policy or adoption evidence.
        return dict(report_sha256='a'*64, scope='real', compression_ratio=.2,
            added_decode_fraction=.05, cold_saving_bytes=42949673,
            baseline_total_seconds=.08, candidate_total_seconds=.087,
            tradeoff_id=tradeoff.TRADEOFF_ID, comparator_codec='zstd',
            comparator_level=1, comparator_shuffle='byte',
            comparator_physical_bytes=1000, candidate_physical_bytes=800)

    def rule(self, evidence=None, **changes):
        result = dict(codec='delta-zstd-v1', enabled=True, level=1, shuffle='byte',
                      evidence=self.evidence() if evidence is None else evidence)
        result.update(changes)
        return result

    def test_exact_boundary_accepts_and_normalised_evidence_is_immutable(self):
        evidence = self.evidence()
        self.assertTrue(tradeoff.time_gate_passes('delta-zstd-v1', 1, 'byte', evidence))
        key = 'atlas.private.heat-ledger.logical.v1/int.offset'
        source = dict(schema=codec.POLICY_SCHEMA, default={'codec':'raw','enabled':False},
                      arrays={key:self.rule(evidence)}, parallel_workers=1, prefetch=False)
        frozen = codec.normalise_policy(source)
        self.assertEqual(codec.normalise_policy(frozen), frozen)
        evidence['candidate_total_seconds'] = 999.
        self.assertEqual(dict(frozen.for_array(key).evidence)['candidate_total_seconds'], .087)
        self.assertFalse(frozen.default.enabled)
        self.assertFalse(frozen.prefetch)
        self.assertEqual(frozen.parallel_workers, 1)

    def test_greater_slowdown_or_less_physical_saving_fails(self):
        for field, value in (('candidate_total_seconds', math.nextafter(.087, math.inf)),
                             ('candidate_physical_bytes', 801)):
            with self.subTest(field=field):
                evidence = self.evidence(); evidence[field] = value
                self.assertFalse(tradeoff.time_gate_passes('delta-zstd-v1', 1, 'byte', evidence))
                with self.assertRaisesRegex(ValueError, 'per-class adoption gates'):
                    codec._rule(self.rule(evidence))

    def test_wrong_candidate_and_comparator_profiles_refuse(self):
        for field, value in (('codec','zstd'), ('codec','delta-v1'), ('codec','raw'),
                             ('level',3), ('level',True), ('shuffle','bit'), ('shuffle','none')):
            with self.subTest(candidate_field=field, value=value):
                rule = self.rule(**{field:value})
                with self.assertRaises(ValueError):
                    tradeoff.time_gate_passes(rule['codec'], rule['level'], rule['shuffle'], rule['evidence'])
                with self.assertRaises(ValueError):
                    codec._rule(rule)
        for field, value in (('comparator_codec','delta-v1'), ('comparator_level',3),
                             ('comparator_level',True), ('comparator_shuffle','bit'),
                             ('tradeoff_id','another-decision'), ('tradeoff_id',True)):
            with self.subTest(evidence_field=field, value=value):
                evidence = self.evidence(); evidence[field] = value
                with self.assertRaises(ValueError):
                    tradeoff.time_gate_passes('delta-zstd-v1', 1, 'byte', evidence)
                with self.assertRaises(ValueError):
                    codec._rule(self.rule(evidence))

    def test_incomplete_or_unknown_evidence_fields_refuse(self):
        for missing in tradeoff.TRADEOFF_FIELDS:
            with self.subTest(missing=missing):
                evidence = self.evidence(); del evidence[missing]
                with self.assertRaisesRegex(ValueError, 'complete accepted-tradeoff'):
                    tradeoff.time_gate_passes('delta-zstd-v1', 1, 'byte', evidence)
                with self.assertRaisesRegex(ValueError, 'complete real-class adoption evidence'):
                    codec._rule(self.rule(evidence))
        evidence = dict(self.evidence(), blanket_slowdown_allowed=True)
        with self.assertRaisesRegex(ValueError, 'complete real-class adoption evidence'):
            codec._rule(self.rule(evidence))

    def test_malformed_numeric_exception_fields_refuse(self):
        bad_values = {
            'baseline_total_seconds': (True, False, 0, -1, math.inf, math.nan, '0.08', None),
            'candidate_total_seconds': (True, False, -1, math.inf, math.nan, '0.087', None),
            'comparator_physical_bytes': (True, False, 0, -1, 1000., math.inf, math.nan, '1000'),
            'candidate_physical_bytes': (True, False, 0, -1, 800., math.inf, math.nan, '800'),
        }
        for field, values in bad_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    evidence = self.evidence(); evidence[field] = value
                    with self.assertRaises(ValueError):
                        tradeoff.time_gate_passes('delta-zstd-v1', 1, 'byte', evidence)
                    with self.assertRaises(ValueError):
                        codec._rule(self.rule(evidence))

    def test_synthetic_or_missing_report_identity_cannot_enable(self):
        for field, value in (('scope','synthetic'), ('scope',True),
                             ('report_sha256','A'*64), ('report_sha256','bad'),
                             ('report_sha256',None), ('report_sha256',True)):
            with self.subTest(field=field, value=value):
                evidence = self.evidence(); evidence[field] = value
                with self.assertRaises(ValueError):
                    tradeoff.time_gate_passes('delta-zstd-v1', 1, 'byte', evidence)
                with self.assertRaises(ValueError):
                    codec._rule(self.rule(evidence))

    def test_other_adoption_gates_remain_required(self):
        for field, value in (('compression_ratio',.800001), ('added_decode_fraction',.050001),
                             ('cold_saving_bytes',42949672), ('cold_saving_bytes',True)):
            with self.subTest(field=field):
                evidence = self.evidence(); evidence[field] = value
                self.assertTrue(tradeoff.time_gate_passes('delta-zstd-v1', 1, 'byte', evidence))
                with self.assertRaisesRegex(ValueError, 'per-class adoption gates'):
                    codec._rule(self.rule(evidence))

    def test_without_exception_every_codec_keeps_strict_time_gain(self):
        evidence = {k:v for k,v in self.evidence().items() if k not in tradeoff.TRADEOFF_FIELDS}
        for name in ('raw', 'palette', 'delta-v1', 'zstd', 'delta-zstd-v1', 'trained-zstd-v1'):
            for candidate, expected in ((.079,True), (.08,False), (.087,False)):
                with self.subTest(codec=name, candidate=candidate):
                    evidence['candidate_total_seconds'] = candidate
                    self.assertEqual(tradeoff.time_gate_passes(name, 1, 'byte', evidence), expected)
                    rule = self.rule(evidence, codec=name)
                    if name == 'trained-zstd-v1':
                        rule['dictionary_sha256'] = 'b'*64
                    if expected:
                        self.assertEqual(codec._rule(rule).codec, name)
                    else:
                        with self.assertRaisesRegex(ValueError, 'per-class adoption gates'):
                            codec._rule(rule)


if __name__=='__main__':
    unittest.main()
