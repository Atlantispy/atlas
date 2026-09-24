"""Items 9–11: exact encoding, verified reuse and short storage transactions.

Synthetic data and temporary stores only. Expected encodings are independently
unpacked where useful. No numerical tolerance changes or performance assertions.
"""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from dataclasses import replace
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import struct
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_array_equal

from atlas_tectonics.storage import (ArrayStore, ArrayReference, StoreLimits,
    Compression, StoreError, StoreConflict, storage_profile)
from atlas_tectonics.resources import WorkBudget, MemoryLimitError


def key(text):
    return hashlib.sha256(text.encode()).hexdigest()


class StorageProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.limits = StoreLimits(4096, 2<<20, 8<<20, 32768)
        self.store = ArrayStore(self.root/'s.db', self.limits)

    def tearDown(self):
        self.store.close(); self.tmp.cleanup()

    def assert_bytes(self, a, b):
        self.assertEqual(a.shape, b.shape)
        self.assertEqual(a.astype(a.dtype.newbyteorder('<')).tobytes(), b.tobytes())
        with self.assertRaises(ValueError): b.setflags(write=True)

    def test_optimised_default_and_named_profiles(self):
        self.assertEqual(self.store.compression.codec, 'zstd')
        self.assertTrue(self.store.compression.palette)
        for name in ('fast','balanced','compact'):
            profile=storage_profile(name)
            self.assertEqual(profile.name,name+'-v1')
            self.assertGreater(profile.chunk_bytes,0)
            with ArrayStore(self.root/(name+'.db'),replace(self.limits,chunk_bytes=profile.chunk_bytes),profile.compression) as s:
                a=np.sin(np.arange(1000.)/30)
                s.put(key(name),{'a':a}); self.assert_bytes(a,s.get(key(name))['a'])
        with self.assertRaises(StoreError):storage_profile('maximum-magic')

    def test_explicit_raw_and_legacy_defaults_remain_available(self):
        with ArrayStore(self.root/'legacy.db',self.limits,Compression('raw',palette=True,categorical='legacy')) as s:
            a=np.resize(np.array([1,8,9000],dtype='<i4'),1000)
            codec,encoded=s._encode(a.tobytes(),a.dtype)
            self.assertEqual(codec,'palette8')
            self.assertEqual(s._decode(codec,encoded,a.dtype,a.size),a.tobytes())

    def test_packed_indices_independent_decode(self):
        rng=np.random.default_rng(911)
        with ArrayStore(self.root/'packed.db',self.limits,Compression('raw')) as s:
            for n,bits in ((2,1),(3,2),(4,2),(8,4),(16,4),(17,8),(256,8)):
                with self.subTest(n=n):
                    indices=np.concatenate((np.arange(n),rng.integers(n,size=2003)))
                    a=(indices*1001-90000).astype('<i8')
                    codec,data=s._encode(a.tobytes(),a.dtype)
                    self.assertEqual(codec,'palette-packed-v1')
                    size,b=struct.unpack('<HB',data[:3]);self.assertEqual((size,b),(n,bits))
                    vals=np.frombuffer(data,dtype='<i8',offset=3,count=n)
                    raw=data[3+8*n:]
                    decoded=[vals[(raw[(i*bits)//8]>>((i*bits)%8))&((1<<bits)-1)] for i in range(a.size)]
                    assert_array_equal(a,decoded)
                    self.assertEqual(s._decode(codec,data,a.dtype,a.size),a.tobytes())

    def test_packed_uint64_and_boolean(self):
        with ArrayStore(self.root/'unsigned.db',self.limits,Compression('raw')) as s:
            for a in (np.resize(np.array([2**63,2**64-1],dtype='<u8'),1001),
                      np.resize(np.array([False,True]),1001)):
                codec,data=s._encode(a.tobytes(),a.dtype)
                self.assertEqual(s._decode(codec,data,a.dtype,a.size),a.tobytes())

    def test_run_length_round_trip_and_independent_format(self):
        a=np.repeat(np.array([-4,17,9000],dtype='<i4'),[250,300,450])
        with ArrayStore(self.root/'rle.db',self.limits,Compression('raw')) as s:
            codec,p=s._encode(a.tobytes(),a.dtype);self.assertEqual(codec,'rle-v1')
            self.assertEqual(struct.unpack('<I',p[:4])[0],3)
            self.assertEqual(struct.unpack('<IiIiIi',p[4:]),(250,-4,300,17,450,9000))
            self.assertEqual(s._decode(codec,p,a.dtype,a.size),a.tobytes())

    def test_packed_decoder_rejects_header_indices_and_padding(self):
        dt=np.dtype('<i4');valid=struct.pack('<HB',3,2)+np.array([1,2,3],dtype=dt).tobytes()+b'\x24'
        self.assertEqual(self.store._decode('palette-packed-v1',valid,dt,3),np.array([1,2,3],dtype=dt).tobytes())
        for p in (valid[:-1],valid[:-1]+b'\x27',valid[:-1]+b'\xe4',b'\x03\x00\x03'+valid[3:],b''):
            with self.subTest(p=p),self.assertRaises(StoreError):
                self.store._decode('palette-packed-v1',p,dt,3)

    def test_rle_decoder_rejects_oversized_counts_before_repeat(self):
        dt=np.dtype('<i4')
        for payload in (struct.pack('<IIi',1,0,4),struct.pack('<IIi',1,2**32-1,4),
                        struct.pack('<I',1000),b''):
            with mock.patch('numpy.repeat',side_effect=AssertionError('allocated')):
                with self.assertRaises(StoreError):self.store._decode('rle-v1',payload,dt,4)

    def test_signed_zero_float_and_strided_categorical_exact(self):
        arrays={'z':np.array([0.,-0.]*500),'s':np.arange(100).reshape(10,10)[:,::2],
                'empty':np.zeros((0,2)),'scalar':np.array(7,dtype='u4')}
        self.store.put(key('types'),arrays)
        for name,a in arrays.items():self.assert_bytes(a,self.store.get(key('types'))[name])

    def test_multichunk_layouts_preserve_c_order_bytes_and_detach_input(self):
        base=np.arange(2054.,dtype='f8').reshape(13,158)
        arrays={'contiguous':base.copy(), 'fortran':np.asfortranarray(base),
                'reversed':base[::-1,::-1], 'strided':base[:,::2],
                'big_endian':base.astype('>f8'),
                'signed_zeros':np.resize(np.array([0.,-0.]),base.shape)}
        expected={k:a.astype(a.dtype.newbyteorder('<')).tobytes(order='C')
                  for k,a in arrays.items()}
        shapes={k:a.shape for k,a in arrays.items()}
        self.store.put(key('layouts'),arrays)
        for a in arrays.values():a[...] = 99
        restored=self.store.get(key('layouts'))
        for name,a in restored.items():
            self.assertEqual(a.shape,shapes[name])
            self.assertEqual(a.tobytes(),expected[name])
            with self.assertRaises(ValueError):a.setflags(write=True)

    def test_dictionary_frames_are_self_contained(self):
        a=np.sin(np.linspace(0,10,32768))
        compression=Compression(use_dict=True)
        with ArrayStore(self.root/'dict.db',replace(self.limits,chunk_bytes=65536),compression) as s:
            s.put(key('dict'),{'a':a})
        with ArrayStore(self.root/'dict.db',replace(self.limits,chunk_bytes=65536),Compression('raw')) as s:
            self.assert_bytes(a,s.get(key('dict'))['a'])

    def test_no_external_dictionary_or_silent_dependency_fallback(self):
        with self.assertRaises(StoreError):Compression('raw',use_dict=True)
        import builtins
        original=builtins.__import__
        def blocked(name,*a,**kw):
            if name=='blosc2':raise ImportError('deliberately absent')
            return original(name,*a,**kw)
        with mock.patch('builtins.__import__',side_effect=blocked):
            with self.assertRaises(StoreError):ArrayStore(self.root/'absent.db',self.limits)
            with ArrayStore(self.root/'raw.db',self.limits,Compression('raw',palette=False)) as s:
                s.put(key('raw'),{'a':np.arange(40.)});self.assert_bytes(np.arange(40.),s.get(key('raw'))['a'])

    def parent(self):
        arrays={'a':np.arange(4096.),'b':np.resize(np.array([4,8,12],dtype='<i4'),4096)}
        self.store.put(key('parent'),arrays,{'unit':'m','time':0})
        return arrays

    def test_reference_reuses_without_materialising_arrays(self):
        arrays=self.parent(); before=self.store.statistics()
        ref=self.store.reference(key('parent'),'a')
        with mock.patch.object(self.store,'_encode',side_effect=AssertionError('encoded')):
            self.store.put(key('child'),{'a':ref},{'time':1})
        after=self.store.statistics()
        self.assertEqual(before['unique_chunks'],after['unique_chunks'])
        self.assertEqual(before['operations']['payload_reads'],after['operations']['payload_reads'])
        self.assert_bytes(arrays['a'],self.store.get(key('child'))['a'])

    def test_incremental_one_chunk_only(self):
        arrays=self.parent();before=self.store.statistics();part=arrays['a'][512:1024].copy();part[2]=-88
        original=self.store._encode
        with mock.patch.object(self.store,'_encode',wraps=original) as enc:
            self.store.put_incremental(key('child'),key('parent'),{'a':{1:part}},{'time':1})
            self.assertEqual(enc.call_count,1)
        self.assertEqual(self.store.statistics()['unique_chunks'],before['unique_chunks']+1)
        expected=arrays['a'].copy();expected[512:1024]=part
        self.assert_bytes(expected,self.store.get(key('child'))['a'])
        self.assert_bytes(arrays['a'],self.store.get(key('parent'))['a'])
        self.assert_bytes(arrays['b'],self.store.get(key('child'))['b'])
        self.assertEqual(self.store.metadata(key('child')),{'time':1})

    def test_branch_has_direct_chunks_not_parent_chain(self):
        arrays=self.parent();self.store.put_incremental(key('child'),key('parent'),{})
        self.store._db.execute('DELETE FROM snapshots WHERE id=?',(key('parent'),))
        self.assert_bytes(arrays['a'],self.store.get(key('child'))['a'])

    def test_reference_rejected_for_another_store_or_changed_descriptor(self):
        self.parent();ref=self.store.reference(key('parent'),'a')
        for bad in (replace(ref,store_path=str(self.root/'other.db')),replace(ref,descriptor_sha256='0'*64),
                    replace(ref,invocation=key('absent')),replace(ref,array_name='absent')):
            with self.assertRaises((StoreError,KeyError)):self.store.put(key('bad'),{'a':bad})
        self.assertFalse(self.store.contains(key('bad')))

    def test_bad_replacement_shapes_types_and_indices(self):
        self.parent()
        for changes in ({'absent':{}},{'a':{-1:np.zeros(512)}},{'a':{99:np.zeros(512)}},
                        {'a':{1:np.zeros(511)}},{'a':{1:np.zeros(512,dtype='f4')}},
                        {'a':{True:np.zeros(512)}},{'a':{1:np.zeros((2,256))}}):
            with self.subTest(changes=str(changes)[:70]),self.assertRaises(StoreError):
                self.store.put_incremental(key('bad'),key('parent'),changes)
        self.assertFalse(self.store.contains(key('bad')))

    def test_reference_corruption_rechecked_after_external_commit(self):
        self.parent();ref=self.store.reference(key('parent'),'a')
        with closing(sqlite3.connect(self.store.path)) as conn, conn:
            conn.execute("UPDATE chunks SET payload=? WHERE id=(SELECT id FROM chunks LIMIT 1)",(b'bad',))
        with self.assertRaises(StoreError):self.store.put_incremental(key('child'),key('parent'),{})
        self.assertFalse(self.store.contains(key('child')))

    def test_reference_dependency_changed_during_preparation(self):
        arrays=self.parent();ref=self.store.reference(key('parent'),'a')
        old=self.store._encode;done=[False]
        def mutate(*args):
            if not done[0]:
                done[0]=True
                with closing(sqlite3.connect(self.store.path)) as conn, conn:
                    body=conn.execute('SELECT body FROM snapshots WHERE id=?',(key('parent'),)).fetchone()[0]
                    m=json.loads(body);m['arrays']['a']['shape']=[2048,2]
                    body=json.dumps(m,sort_keys=True,separators=(',',':')).encode()
                    conn.execute('UPDATE snapshots SET body=?,digest=? WHERE id=?',(body,hashlib.sha256(body).hexdigest(),key('parent')))
            return old(*args)
        with mock.patch.object(self.store,'_encode',side_effect=mutate):
            with self.assertRaises(StoreError):self.store.put(key('bad'),{'a':ref,'z':np.arange(512.)+999})
        self.assertFalse(self.store.contains(key('bad')))

    def test_cold_references_verify_then_reuse(self):
        self.parent();self.store.close();self.store=ArrayStore(self.root/'s.db',self.limits)
        self.store.put_incremental(key('child1'),key('parent'),{})
        first=self.store.statistics()['operations']['payload_reads'];self.assertGreater(first,0)
        self.store.put_incremental(key('child2'),key('child1'),{})
        self.assertEqual(first,self.store.statistics()['operations']['payload_reads'])

    def test_verified_metadata_is_bounded_without_decoded_cache(self):
        limits=replace(self.limits,decoded_cache_bytes=0,verified_cache_entries=2)
        with ArrayStore(self.root/'bounded.db',limits) as s:
            s.put(key('many'),{'x':np.arange(4096.)});s.get(key('many'))
            stats=s.statistics();self.assertLessEqual(stats['verified_cache_entries'],2)
            self.assertEqual(stats['decoded_cache_bytes'],0)

    def test_encoding_holds_no_writer_transaction(self):
        other=ArrayStore(self.store.path,self.limits)
        old=self.store._encode;done=[False]
        def encode(*a):
            self.assertFalse(self.store._db.in_transaction)
            if not done[0]:
                done[0]=True
                with ThreadPoolExecutor(1) as pool:
                    pool.submit(other.put,key('other'),{'x':np.ones(20)}).result(timeout=3)
            return old(*a)
        try:
            with mock.patch.object(self.store,'_encode',side_effect=encode):self.store.put(key('a'),{'x':np.arange(1024.)})
        finally:other.close()
        self.assertTrue(self.store.contains(key('other')))

    def test_preparation_failure_publishes_nothing(self):
        old=self.store._encode;n=[0]
        def fail(*args):
            n[0]+=1
            if n[0]==2:raise OSError('preparation failed')
            return old(*args)
        with mock.patch.object(self.store,'_encode',side_effect=fail):
            with self.assertRaises(OSError):self.store.put(key('bad'),{'x':np.arange(4096.)})
        self.assertEqual(self.store.statistics()['unique_chunks'],0)
        self.assertFalse(self.store.contains(key('bad')))

    def test_spool_limits_and_disk_spill_are_bounded(self):
        with ArrayStore(self.root/'tiny.db',replace(self.limits,max_staging_bytes=100,staging_memory_bytes=64),Compression('raw',palette=False)) as s:
            with self.assertRaises(StoreError):s.put(key('bad'),{'x':np.arange(4096.)})
            self.assertEqual(s.statistics()['snapshots'],0)
        with ArrayStore(self.root/'spill.db',replace(self.limits,staging_memory_bytes=64),Compression('raw',palette=False)) as s:
            a=np.arange(4096.);s.put(key('ok'),{'x':a});self.assert_bytes(a,s.get(key('ok'))['x'])
            self.assertGreater(s.statistics()['operations']['staged_bytes'],64)
        self.assertFalse(any(p.suffix not in ('.db',) for p in self.root.iterdir()))

    def test_store_work_budget_refuses_before_encoding_and_releases(self):
        budget=WorkBudget(100)
        with mock.patch.object(self.store,'_encode',side_effect=AssertionError('encoded')):
            with self.assertRaises(MemoryLimitError):self.store.put(key('large'),{'x':np.arange(1024.)},budget=budget)
        self.assertEqual(budget.reserved_bytes,0)

    def test_cancellation_during_encoding_and_before_commit(self):
        cancel=threading.Event();old=self.store._encode
        def cancel_encoding(*a):
            cancel.set();return old(*a)
        with mock.patch.object(self.store,'_encode',side_effect=cancel_encoding):
            with self.assertRaises(CancelledError):self.store.put(key('cancel'),{'x':np.arange(512.)},cancel=cancel)
        self.assertFalse(self.store.contains(key('cancel')))
        def reject():raise CancelledError('late')
        with self.assertRaises(CancelledError):self.store.put(key('late'),{'x':np.arange(512.)},publication_check=reject)
        self.assertEqual(self.store.statistics()['unique_chunks'],0)

    def test_broken_encoder_cannot_attest_or_publish_wrong_data(self):
        with mock.patch.object(self.store,'_encode',return_value=('uniform',np.array([7.]).tobytes())):
            with self.assertRaises(StoreError):self.store.put(key('bad'),{'x':np.arange(512.)})
        self.assertFalse(self.store.contains(key('bad')))
        self.assertEqual(self.store.statistics()['unique_chunks'],0)

    def test_same_key_conflict_and_concurrent_encoding(self):
        self.parent();before=self.store.statistics()['unique_chunks']
        with self.assertRaises(StoreConflict):self.store.put(key('parent'),{'a':np.ones(2)})
        self.assertEqual(before,self.store.statistics()['unique_chunks'])
        a=np.arange(2048.)
        def worker(i):
            with ArrayStore(self.store.path,self.limits,Compression('raw' if i%2 else 'zstd')) as s:s.put(key('w'+str(i)),{'a':a})
        with ThreadPoolExecutor(4) as pool:list(pool.map(worker,range(8)))
        for i in range(8):self.assert_bytes(a,self.store.get(key('w'+str(i)))['a'])

    def test_insert_batches_and_one_manifest_parse(self):
        a=np.arange(4096.)
        self.store.put(key('b'),{'a':a,'b':a+1})
        stats=self.store.statistics()['operations'];self.assertGreater(stats['insert_batches'],0)
        self.assertLess(stats['insert_batches'],16)
        with mock.patch.object(self.store,'_manifest',wraps=self.store._manifest) as parse:
            self.store.get(key('b'));self.assertEqual(parse.call_count,1)

    def test_warm_decoded_hit_reads_no_payload_and_validates_manifest(self):
        a=np.arange(1024.);self.store.put(key('a'),{'x':a});self.store.get(key('a'))
        before=self.store.statistics()['operations']['payload_reads']
        self.assert_bytes(a,self.store.get(key('a'))['x'])
        self.assertEqual(before,self.store.statistics()['operations']['payload_reads'])
        self.store._db.execute('UPDATE snapshots SET body=? WHERE id=?',(b'{}',key('a')))
        with self.assertRaises(StoreError):self.store.get(key('a'))

    def test_direct_connection_mutation_invalidates_warm_data(self):
        self.store.put(key('a'),{'x':np.arange(1024.)});self.store.get(key('a'))
        self.store._db.execute('UPDATE chunks SET payload=?',(b'bad',))
        with self.assertRaises(StoreError):self.store.get(key('a'))

    def test_stream_releases_transaction_between_chunks(self):
        a=np.arange(2048.);self.store.put(key('a'),{'x':a})
        stream=self.store.iter_chunks(key('a'),'x');next(stream)
        self.assertFalse(self.store._db.in_transaction)
        with closing(sqlite3.connect(self.store.path)) as conn, conn:conn.execute('UPDATE chunks SET payload=?',(b'bad',))
        with self.assertRaises(StoreError):next(stream)

    def test_live_schema_change_refuses_even_warm_cache(self):
        self.parent();self.store.get(key('parent'))
        with closing(sqlite3.connect(self.store.path)) as conn, conn:
            conn.execute('UPDATE settings SET body=?',(b'{}',))
        with self.assertRaises(StoreError):self.store.get(key('parent'))

    def test_empty_and_short_final_chunk_incremental(self):
        a=np.arange(513.)
        self.store.put(key('parent'),{'a':a,'empty':np.zeros((0,3))})
        self.store.put_incremental(key('child'),key('parent'),{'a':{1:np.array([-7.])}})
        expected=a.copy();expected[-1]=-7
        self.assert_bytes(expected,self.store.get(key('child'))['a'])
        self.assertEqual(self.store.get(key('child'))['empty'].shape,(0,3))

    def test_invalid_replacement_mapping_is_explicit(self):
        self.parent()
        for replacements in (None,{'a':None},{'a':np.zeros(3)}):
            with self.assertRaises(StoreError):self.store.put_incremental(key('bad'),key('parent'),replacements)

    def test_reference_input_rejects_wrong_types(self):
        self.parent();ref=self.store.reference(key('parent'),'a')
        for bad in (replace(ref,array_name=[]),replace(ref,invocation=[]),replace(ref,descriptor_sha256=None)):
            with self.assertRaises(StoreError):self.store.put(key('bad'),{'a':bad})

    def test_incremental_failure_leaves_previous_view_and_cache_usable(self):
        arrays=self.parent()
        def stop():raise RuntimeError('reject candidate')
        with self.assertRaises(RuntimeError):
            self.store.put_incremental(key('bad'),key('parent'),{'a':{0:np.ones(512)}},publication_check=stop)
        self.assertFalse(self.store.contains(key('bad')))
        self.assert_bytes(arrays['a'],self.store.get(key('parent'))['a'])

    def test_cache_wrapper_forwards_storage_budget_and_cancellation(self):
        from atlas_tectonics.reuse import cached_temperature, CachePolicy
        from atlas_tectonics.parameters import ThermalParameters
        budget=WorkBudget(16<<20);cancel=threading.Event()
        parameters=ThermalParameters('synthetic','test only',300,1300,1)
        with mock.patch.object(self.store,'put',wraps=self.store.put) as put:
            cached_temperature(np.arange(32.),1.,parameters,store=self.store,
                budget=budget,cancel=cancel,cache_policy=CachePolicy(mode='always'))
            self.assertIs(put.call_args.kwargs['budget'],budget)
            self.assertIs(put.call_args.kwargs['cancel'],cancel)
        self.assertEqual(budget.reserved_bytes,0)

    def test_closed_store_refuses_new_preparation(self):
        self.store.close()
        with self.assertRaises(StoreError):self.store.put(key('x'),{'x':np.arange(10.)})

    def test_backup_keeps_new_encodings_and_parent_independence(self):
        arrays=self.parent();target=self.store.backup_to(self.root/'backup.db')
        self.store.close();self.store.path.unlink()
        with ArrayStore(target,self.limits) as s:
            self.assert_bytes(arrays['a'],s.get(key('parent'))['a'])
            self.assert_bytes(arrays['b'],s.get(key('parent'))['b'])


if __name__=='__main__':unittest.main()
