"""Independent regression, lossless-storage and optional-kernel verification.

Temporary directories only. No geological simulation, repository writes, automatic
installation, performance threshold or historical checkpoint acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from decimal import Decimal, localcontext
import copy
import errno
import hashlib
import json
import math
from pathlib import Path
import pickle
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_allclose, assert_array_equal

from atlas_tectonics import (Rotation, boundary_motion, ThermalParameters,
    FlexureParameters, PeriodicGrid1D, PeriodicFlexure, half_space_temperature,
    advect_thickness, TectonicsError)
from atlas_tectonics._validation import array
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics.reuse import CachePolicy
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression, StoreError, StoreConflict
from atlas_tectonics.reuse import cached_temperature, cached_flexure, invocation_identity

THERMAL = ThermalParameters('synthetic', 'test only', 300, 1300, 1)
ELASTIC = FlexureParameters('synthetic', 'test only', 12, 1, 0, 1, 1)


def key(text):
    return hashlib.sha256(text.encode()).hexdigest()


class FoundationHardening(unittest.TestCase):
    def test_masked_input_refused_everywhere(self):
        m = np.ma.array([1., 999.], mask=[0, 1])
        for value in (m, [m], np.ma.masked, np.ma.array([1,2],mask=False)):
            with self.subTest(value=str(value)), self.assertRaises(TectonicsError):
                array(value, 'field')
        with self.assertRaises(TectonicsError):
            advect_thickness(np.ma.array(np.ones(8), mask=[0]*7+[1]), np.zeros(8), PeriodicGrid1D(8,8), 0)

    def test_subnormal_and_huge_quaternions_preserve_length(self):
        for scale in (float(np.nextafter(0.,1.)), 1e-250, 1, 1e300):
            r=Rotation((0,scale,scale,scale))
            assert_allclose(np.linalg.norm(r.apply(np.eye(3)),axis=1),np.ones(3),atol=1e-14)
            self.assertAlmostEqual(np.linalg.det(r.apply(np.eye(3))),1)

    def test_axis_and_tangent_scale_invariance(self):
        tiny=float(np.nextafter(0.,1.))
        assert_allclose(Rotation.from_axis_angle([tiny]*3,1).apply(np.eye(3)),
                        Rotation.from_axis_angle([1]*3,1).apply(np.eye(3)),atol=1e-14)
        a=boundary_motion([0,0],[1,0],[tiny,tiny],[0,0])
        b=boundary_motion([0,0],[1,0],[1,1],[0,0])
        self.assertEqual(a,b)

    def test_flexure_extreme_same_discrete_equation(self):
        fp=FlexureParameters('extreme','not Earth',12,1e100,0,1e-30,1e-30)
        g=PeriodicGrid1D(16,1e90)
        actual=PeriodicFlexure(g,fp).solve(1e-60*np.cos(np.arange(16)*2*np.pi/16))[0]
        with localcontext() as c:
            c.prec=100
            eig=(Decimal.from_float(2*math.sin(math.pi/16))/Decimal.from_float(g.spacing_m))**4
            expected=float(Decimal.from_float(1e-60)/(Decimal.from_float(fp.rigidity_n_m)*eig+Decimal.from_float(fp.restoring_pa_per_m)))
        self.assertAlmostEqual(actual/expected,1,places=12)

    def test_operator_restore_rebuilds_immutable_coefficients(self):
        op=PeriodicFlexure(PeriodicGrid1D(16,16),ELASTIC)
        for restored in (copy.deepcopy(op),pickle.loads(pickle.dumps(op))):
            self.assertEqual(op.operator_id,restored.operator_id)
            with self.assertRaises(ValueError):
                restored._gain.setflags(write=True)
            assert_array_equal(restored.solve(np.ones(16)),op.solve(np.ones(16)))

    def test_transport_restore_refreezes_arrays(self):
        r=advect_thickness(np.ones(8),np.zeros(8),PeriodicGrid1D(8,8),1)
        restored=pickle.loads(pickle.dumps(r))
        for a in (restored.thickness_m, restored.face_flux_m2_s):
            with self.assertRaises(ValueError): a.setflags(write=True)

    def test_broadcast_refused_before_large_allocation(self):
        depth=np.zeros((32768,1));age=np.ones((1,32768))
        with mock.patch('numpy.zeros',side_effect=AssertionError('allocation attempted')):
            with self.assertRaises(MemoryLimitError):
                half_space_temperature(depth,age,THERMAL,budget=WorkBudget(1<<20))

    def test_shape_refused_before_conversion(self):
        rotation=Rotation((1,0,0,0))
        with mock.patch('numpy.array',side_effect=AssertionError('converted')):
            with self.assertRaises(TectonicsError):
                rotation.apply(np.zeros((2,2)))

    def test_explicit_budget_all_bulk_kernels(self):
        b=WorkBudget(16)
        calls=[lambda:Rotation((1,0,0,0)).apply(np.ones((8,3)),budget=b),
               lambda:half_space_temperature(np.ones(8),1,THERMAL,budget=b),
               lambda:advect_thickness(np.ones(8),np.zeros(8),PeriodicGrid1D(8,8),1,budget=b),
               lambda:PeriodicFlexure(PeriodicGrid1D(8,8),ELASTIC).solve(np.ones(8),budget=b)]
        for call in calls:
            with self.assertRaises(MemoryLimitError):call()
            self.assertEqual(b.reserved_bytes,0)

    def test_budget_release_on_error_and_parallel_admission(self):
        b=WorkBudget(100)
        with b.reserve(80):
            with ThreadPoolExecutor(1) as pool:
                def attempt():
                    with b.reserve(30):pass
                with self.assertRaises(MemoryLimitError):pool.submit(attempt).result()
        with self.assertRaises(RuntimeError):
            with b.reserve(50):raise RuntimeError('cancel')
        self.assertEqual(b.reserved_bytes,0)
        self.assertEqual(b.peak_reserved_bytes,80)

    def test_bulk_cooling_matches_reference_and_limits(self):
        depth=np.linspace(0,10,1000)[:,None];age=np.array([0.,1.,4.,1e20])[None,:]
        expected=half_space_temperature(depth,age,THERMAL)
        actual=half_space_temperature(depth,age,THERMAL,backend='scipy')
        assert_allclose(actual,expected,rtol=2e-15,atol=1e-12)
        with self.assertRaises(ValueError):actual.setflags(write=True)
        for value in ([0,0,0],[-1,1,2]):
            if min(value)<0:
                with self.assertRaises(TectonicsError):half_space_temperature(value,1,THERMAL,backend='scipy')
        with self.assertRaises(TectonicsError):half_space_temperature(1,1,THERMAL,backend='gpu')

    def test_transport_array_reuse_preserves_original_order(self):
        rng=np.random.default_rng(813)
        h=rng.uniform(0,100,128);u=rng.uniform(-1,1,128);dt=.2;dx=1
        ro=np.maximum(u,0)*dt/dx;lo=np.maximum(-np.roll(u,1),0)*dt/dx
        expected=(1-ro-lo)*h+np.roll(ro*h,1)+np.roll(lo*h,-1)
        actual=advect_thickness(h,u,PeriodicGrid1D(128,128),dt)
        assert_allclose(actual.thickness_m,expected,rtol=5e-16,atol=1e-14)
        self.assertLess(abs(actual.balance_residual_m2),1e-10)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'store.sqlite'
        self.limits=StoreLimits(1024,1<<20,4<<20,4096)
        # This fixture deliberately tests the raw/legacy-compatible storage path.
        self.store=ArrayStore(self.path,self.limits,Compression(codec='raw',palette=False))

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def test_all_numeric_types_strides_and_empty(self):
        values={}
        for dt in ('?','i1','u1','i2','u2','i4','u4','i8','u8','f2','f4','f8','>f8'):
            values[dt]=np.arange(60).astype(dt).reshape(6,10)[:,::2]
        values['empty']=np.zeros((0,3));values['scalar']=np.array(3.)
        self.store.put(key('types'),values)
        out=self.store.get(key('types'))
        for name,a in values.items():
            assert_array_equal(a,out[name]);self.assertEqual(a.shape,out[name].shape)
            with self.assertRaises(ValueError):out[name].setflags(write=True)

    def test_uniform_and_signed_zero_lossless(self):
        a=np.array([0.,-0.]*128)
        self.store.put(key('zeros'),{'mixed':a,'uniform':np.ones(1024)})
        self.assertEqual(self.store.get(key('zeros'))['mixed'].tobytes(),a.tobytes())
        codecs=dict(self.store._db.execute('SELECT codec,count(*) FROM chunks GROUP BY codec'))
        self.assertIn('uniform',codecs)

    def test_deduplicated_snapshots_and_changed_chunk(self):
        a=np.arange(512,dtype=float)
        self.store.put(key('parent'),{'x':a})
        initial=self.store.statistics()['unique_chunks']
        self.store.put(key('branch'),{'x':a.copy()})
        self.assertEqual(self.store.statistics()['unique_chunks'],initial)
        b=a.copy();b[5]+=1
        self.store.put(key('changed'),{'x':b})
        self.assertEqual(self.store.statistics()['unique_chunks'],initial+1)
        assert_array_equal(self.store.get(key('parent'))['x'],a)

    def test_same_key_conflict_rolls_back_new_chunks(self):
        a=np.arange(512,dtype=float);k=key('same')
        self.store.put(k,{'a':a});stats=self.store.statistics()
        with self.assertRaises(StoreConflict):self.store.put(k,{'a':a+1000})
        self.assertEqual(stats['unique_chunks'],self.store.statistics()['unique_chunks'])
        assert_array_equal(self.store.get(k)['a'],a)

    def test_schema_and_limits(self):
        for args in ((0,100,65536),(1<<25,100,65536),(32,100,1024)):
            with self.assertRaises(StoreError):StoreLimits(*args)
        with self.assertRaises(StoreError):ArrayStore(self.path,replace(self.limits,chunk_bytes=2048))
        for value in (np.array([np.nan]),np.array([object()]),np.ma.array([1]),[1,2,3]):
            with self.assertRaises(StoreError):self.store.put(key('bad'),{'a':value})
        self.assertEqual(self.store.statistics()['snapshots'],0)

    def test_random_chunk_read_avoids_other_chunks(self):
        a=np.arange(1024.)
        self.store.put(key('random'),{'a':a})
        with mock.patch.object(self.store,'_chunk',wraps=self.store._chunk) as spy:
            offset,part=self.store.read_chunk(key('random'),'a',3)
            self.assertEqual(spy.call_count,1)
        self.assertEqual(offset,384);assert_array_equal(part,a[384:512])

    def test_decoder_rejects_oversized_header_before_decompress(self):
        with ArrayStore(Path(self.tmp.name)/'header.db',self.limits,Compression('zstd')) as s:
            s.put(key('header'),{'a':np.arange(512.)})
            cid,desc,codec,payload=s._db.execute("SELECT id,descriptor,codec,payload FROM chunks WHERE codec LIKE 'blosc2%' LIMIT 1").fetchone()
            import struct
            payload=payload[:4]+struct.pack('<I',1_000_000_000)+payload[8:]
            checksum=hashlib.sha256(desc+b'\0'+codec.encode()+b'\0'+payload).hexdigest()
            s._db.execute('UPDATE chunks SET payload=?,stored_sha=? WHERE id=?',(payload,checksum,cid))
            with mock.patch('blosc2.decompress2',side_effect=AssertionError('decoder allocated')):
                with self.assertRaises(StoreError):s.get(key('header'))

    def test_raw_store_round_trip_without_blosc_import(self):
        import builtins
        original=builtins.__import__
        def guarded(name,*a,**k):
            if name=='blosc2':raise ImportError('absent')
            return original(name,*a,**k)
        with mock.patch('builtins.__import__',side_effect=guarded):
            self.store.put(key('raw'),{'a':np.arange(200.)})
            assert_array_equal(self.store.get(key('raw'))['a'],np.arange(200.))
            with self.assertRaises(StoreError):ArrayStore(Path(self.tmp.name)/'missing.db',self.limits,Compression('zstd'))

    def test_zstd_filters_round_trip(self):
        for shuffle in ('none','byte','bit'):
            with self.subTest(shuffle=shuffle),ArrayStore(Path(self.tmp.name)/(shuffle+'.db'),self.limits,Compression('zstd',3,shuffle)) as s:
                a=np.sin(np.linspace(0,10,5000))
                s.put(key('zstd'),{'a':a})
                self.assertEqual(s.get(key('zstd'))['a'].tobytes(),a.tobytes())
                self.assertTrue(any('blosc2-zstd' in r[0] for r in s._db.execute('SELECT codec FROM chunks')))

    def test_palette_index_round_trip(self):
        with ArrayStore(Path(self.tmp.name)/'pal.db',self.limits,Compression(codec='raw',palette=True,categorical='legacy')) as s:
            a=np.resize(np.array([9,21,8000],dtype='u4'),2000)
            s.put(key('p'),{'material':a})
            assert_array_equal(s.get(key('p'))['material'],a)
            self.assertIn('palette8',[r[0] for r in s._db.execute('SELECT codec FROM chunks')])

    def test_corruption_is_not_a_cache_miss(self):
        self.store.put(key('a'),{'a':np.arange(512.)});self.store.get(key('a'))
        other=sqlite3.connect(self.path)
        other.execute("UPDATE chunks SET payload=? WHERE id=(SELECT id FROM chunks LIMIT 1)",(b'bad',));other.commit();other.close()
        with self.assertRaises(StoreError):self.store.get(key('a'))

    def test_missing_chunk_refuses(self):
        self.store.put(key('a'),{'a':np.arange(512.)})
        self.store._db.execute('DELETE FROM chunks WHERE id=(SELECT id FROM chunks LIMIT 1)')
        with self.assertRaises(StoreError):self.store.get(key('a'))
        self.assertIsNone(self.store.get(key('absent')))

    def test_manifest_corruption(self):
        self.store.put(key('a'),{'a':np.ones(8)})
        self.store._db.execute('UPDATE snapshots SET body=?',(b'{}',))
        with self.assertRaises(StoreError):self.store.get(key('a'))

    def test_full_restore_budget_and_chunk_streaming(self):
        a=np.arange(2048.)
        self.store.put(key('a'),{'a':a})
        with self.assertRaises(MemoryLimitError):self.store.get(key('a'),budget=WorkBudget(100))
        restored=np.concatenate([part for _,part in self.store.iter_chunks(key('a'),'a')])
        assert_array_equal(restored,a)
        self.assertLessEqual(self.store.statistics()['decoded_cache_bytes'],4096)

    def test_write_failure_rollback_and_previous_state(self):
        self.store.put(key('parent'),{'a':np.arange(128.)})
        original=self.store._encode
        count=[0]
        def failure(*a):
            count[0]+=1
            if count[0]==2:raise OSError('disk write failed')
            return original(*a)
        with mock.patch.object(self.store,'_encode',side_effect=failure):
            with self.assertRaises(OSError):self.store.put(key('failure'),{'a':np.arange(1024.)+500})
        self.assertFalse(self.store.contains(key('failure')))
        assert_array_equal(self.store.get(key('parent'))['a'],np.arange(128.))
        self.assertEqual(self.store.statistics()['unique_chunks'],1)

    def test_database_full_preserves_prior_snapshot(self):
        limits=StoreLimits(1024,1<<20,65536)
        with ArrayStore(Path(self.tmp.name)/'small.db',limits) as s:
            s.put(key('parent'),{'x':np.ones(8)})
            with self.assertRaises(StoreError):s.put(key('huge'),{'x':np.arange(100000.)})
            self.assertFalse(s.contains(key('huge')))
            assert_array_equal(s.get(key('parent'))['x'],np.ones(8))

    def test_concurrent_writers_share_chunks(self):
        a=np.arange(512.)
        def worker(i):
            with ArrayStore(self.path,self.limits) as s:s.put(key(str(i)),{'a':a})
        with ThreadPoolExecutor(4) as pool:list(pool.map(worker,range(8)))
        self.assertEqual(self.store.statistics()['snapshots'],8)
        self.assertEqual(self.store.statistics()['unique_chunks'],4)

    def test_backup_independent_and_no_overwrite(self):
        a=np.arange(512.);self.store.put(key('b'),{'a':a})
        target=self.store.backup_to(Path(self.tmp.name)/'backup.db')
        with self.assertRaises(FileExistsError):self.store.backup_to(target)
        self.store.close();self.path.unlink()
        with ArrayStore(target,self.limits) as s:assert_array_equal(s.get(key('b'))['a'],a)

    def test_unrelated_db_refused(self):
        path=Path(self.tmp.name)/'unrelated.db'
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute('CREATE TABLE unrelated(x)')
        with self.assertRaises(StoreError):ArrayStore(path,self.limits)

    def test_publication_refuses_a_snapshot_get_could_not_load(self):
        # Every array fits max_array_bytes (1 MiB); the 1.2 MB snapshot does not, so get() would refuse it.
        parts={name:np.full(50000,float(i)) for i,name in enumerate('abc')}
        with self.assertRaisesRegex(StoreError,'full read limit'):self.store.put(key('total'),parts)
        self.assertFalse(self.store.contains(key('total')))
        self.assertEqual(self.store.statistics()['unique_chunks'],0)
        self.store.put(key('parent'),{'a':parts['a'],'b':parts['b']})
        self.assertEqual(set(self.store.get(key('parent'))),{'a','b'})
        # A referenced array counts at its declared size, like the arrays get() would load with it.
        with self.assertRaisesRegex(StoreError,'full read limit'):
            self.store.put(key('ref'),{'a':self.store.reference(key('parent'),'a'),'b':parts['b'],'c':parts['c']})
        self.assertFalse(self.store.contains(key('ref')))
        self.store.put_incremental(key('edit'),key('parent'),{'a':{0:np.ones(128)}})
        self.assertEqual(self.store.get(key('edit'))['a'][0],1.)

    def test_only_the_exact_store_schema_opens(self):
        wanted=json.dumps({'schema':'atlas.array-store.v1','chunk_bytes':1024},sort_keys=True,separators=(',',':'))
        # The statements every storage.py revision (0590774, ecac085, 6285d4a, 5da042b) executed.
        genuine=("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL)",
                 "CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, descriptor BLOB NOT NULL, codec TEXT NOT NULL, stored_sha TEXT NOT NULL, payload BLOB NOT NULL)",
                 "CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, body BLOB NOT NULL, digest TEXT NOT NULL)")
        def build(name,statements):
            path=Path(self.tmp.name)/(name+'.db')
            with closing(sqlite3.connect(path)) as conn, conn:
                for statement in statements:conn.execute(statement)
                if name!='views':conn.execute('INSERT INTO settings VALUES(1,?)',(wanted.encode(),))
            return path
        historical=build('historical',genuine)
        with ArrayStore(historical,self.limits) as s:
            s.put(key('h'),{'a':np.arange(10.)});assert_array_equal(s.get(key('h'))['a'],np.arange(10.))
        hostile=dict(
            views=("CREATE VIEW settings AS SELECT 1 AS id, CAST('%s' AS BLOB) AS body" % wanted,
                   "CREATE VIEW chunks AS SELECT 1 AS id, 2 AS descriptor, 3 AS codec, 4 AS stored_sha, 5 AS payload",
                   "CREATE VIEW snapshots AS SELECT 1 AS id, 2 AS body, 3 AS digest"),
            trigger=genuine+("CREATE TRIGGER t BEFORE INSERT ON settings BEGIN SELECT 1; END",),
            generated=genuine[:2]+("CREATE TABLE snapshots (id TEXT PRIMARY KEY, x INTEGER, body BLOB GENERATED ALWAYS AS (zeroblob(16)) VIRTUAL, digest TEXT NOT NULL)",),
            default=(genuine[0],"CREATE TABLE chunks (id TEXT PRIMARY KEY, descriptor BLOB NOT NULL, codec TEXT NOT NULL DEFAULT (hex(randomblob(8))), stored_sha TEXT NOT NULL, payload BLOB NOT NULL)",genuine[2]),
            index=genuine+("CREATE INDEX extra ON chunks(codec)",))
        for name,statements in hostile.items():
            with self.subTest(schema=name):
                path=build(name,statements);before=path.read_bytes()
                with self.assertRaisesRegex(StoreError,'unrelated database'):ArrayStore(path,self.limits)
                self.assertEqual(path.read_bytes(),before)

    def test_hostile_schema_refuses_at_open_without_running_its_sql(self):
        # Probe-style databases: recursive views and triggers would never finish, a generated column would
        # allocate about 0.9 GB. A child process bounds the check, so a regression fails instead of hanging.
        import os,subprocess,sys,time
        loop="(WITH RECURSIVE r(n) AS (SELECT 0 UNION ALL SELECT n+1 FROM r) SELECT count(*) FROM r)"
        genuine=("CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL)",
                 "CREATE TABLE chunks (id TEXT PRIMARY KEY, descriptor BLOB NOT NULL, codec TEXT NOT NULL, stored_sha TEXT NOT NULL, payload BLOB NOT NULL)",
                 "CREATE TABLE snapshots (id TEXT PRIMARY KEY, body BLOB NOT NULL, digest TEXT NOT NULL)")
        wanted=json.dumps({'schema':'atlas.array-store.v1','chunk_bytes':1024},sort_keys=True,separators=(',',':'))
        files=dict(
            views=("CREATE VIEW settings AS SELECT 1 AS id, CAST('%s' AS BLOB) AS body" % wanted,
                   "CREATE VIEW chunks AS SELECT %s AS id, 2 AS descriptor, 3 AS codec, 4 AS stored_sha, 5 AS payload" % loop,
                   "CREATE VIEW snapshots AS SELECT %s AS id, 1 AS body, 1 AS digest" % loop),
            trigger=genuine+("CREATE TRIGGER t BEFORE INSERT ON settings BEGIN SELECT %s; END" % loop,),
            generated=genuine[:2]+("CREATE TABLE snapshots (id TEXT PRIMARY KEY, x INTEGER, body BLOB GENERATED ALWAYS AS (hex(zeroblob(450000000))) VIRTUAL, digest TEXT NOT NULL)",),
            # SQLite parses the whole schema at the first statement: about 90 bytes of memory per schema byte.
            huge=genuine+("CREATE VIEW huge AS SELECT 1 IN (%s) AS x" % ','.join(['1234567']*120000),),
            crowded=genuine)
        expected=dict(views='unrelated database',trigger='unrelated database',generated='unrelated database',
                      huge='corrupt',crowded='bounded opening work')
        paths=[]
        for name,statements in files.items():
            path=Path(self.tmp.name)/(name+'-hostile.db');paths.append(str(path))
            with closing(sqlite3.connect(path)) as conn, conn:
                for statement in statements:conn.execute(statement)
                if name=='crowded':      # 20,000 small views, written straight into the schema table
                    conn.execute('PRAGMA writable_schema=ON')
                    conn.executemany("INSERT INTO sqlite_master VALUES('view',?,?,0,?)",
                                     (('v%d'%i,'v%d'%i,'CREATE VIEW v%d AS SELECT %d AS x'%(i,i)) for i in range(20000)))
        code="""import sys,time
from atlas_tectonics.storage import ArrayStore,StoreLimits,StoreError
for path in sys.argv[1:]:
    start=time.perf_counter()
    try:
        ArrayStore(path,StoreLimits(1024,1<<20,4<<20)).close();print('accepted',path)
    except StoreError as exc:
        print('refused %.3f %s' % (time.perf_counter()-start,exc))
    except Exception as exc:
        print('failed',type(exc).__name__,exc)
    sys.stdout.flush()
"""
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
        try:
            proc=subprocess.run([sys.executable,'-B','-c',code,*paths],env=env,text=True,capture_output=True,timeout=60)
        except subprocess.TimeoutExpired:
            self.fail('opening a hostile database did not finish')
        self.assertEqual(proc.returncode,0,proc.stderr)
        lines=proc.stdout.strip().splitlines()
        self.assertEqual(len(lines),len(files),proc.stdout)
        for name,line in zip(files,lines):
            with self.subTest(schema=name):
                self.assertTrue(line.startswith('refused') and expected[name] in line,line)
                self.assertLess(float(line.split()[1]),5.)

    def test_sqlite_failures_are_store_errors_and_contention_is_distinguished(self):
        junk=Path(self.tmp.name)/'junk.db';junk.write_bytes(b'not a database'*100)
        with self.assertRaisesRegex(StoreError,'corrupt') as caught:ArrayStore(junk,self.limits)
        self.assertNotIn('locked',str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__,sqlite3.DatabaseError)
        self.store.put(key('before'),{'a':np.arange(10.)})
        real=sqlite3.connect
        with closing(sqlite3.connect(self.path,timeout=0,isolation_level=None)) as other:
            other.execute('BEGIN EXCLUSIVE')
            with mock.patch.object(sqlite3,'connect',lambda *a,**k:real(*a,**dict(k,timeout=.05))):
                with self.assertRaisesRegex(StoreError,'locked by another connection'):ArrayStore(self.path,self.limits)
            self.store._db.execute('PRAGMA busy_timeout=50')
            with self.assertRaisesRegex(StoreError,'locked by another connection'):
                self.store.put(key('during'),{'b':np.arange(20.)})
            other.execute('ROLLBACK')
        self.store._db.execute('PRAGMA busy_timeout=5000')
        self.store.put(key('during'),{'b':np.arange(20.)})
        assert_array_equal(self.store.get(key('during'))['b'],np.arange(20.))
        # A writer holding its reservation blocks publication: still reported as contention.
        with closing(sqlite3.connect(self.path,timeout=0,isolation_level=None)) as other:
            other.execute('BEGIN IMMEDIATE');other.execute("INSERT INTO chunks VALUES('x',x'00','raw','y',x'00')")
            self.store._db.execute('PRAGMA busy_timeout=50')
            with self.assertRaisesRegex(StoreError,'storage transaction failed; no snapshot published: .*locked'):
                self.store.put(key('writer'),{'c':np.arange(30.)})
            other.execute('ROLLBACK')
        self.store._db.execute('PRAGMA busy_timeout=5000')
        # A reader does not stop another connection opening an existing store: opening writes nothing.
        with closing(sqlite3.connect(self.path,timeout=0,isolation_level=None)) as reader:
            reader.execute('BEGIN');reader.execute('SELECT count(*) FROM chunks').fetchone()
            with mock.patch.object(sqlite3,'connect',lambda *a,**k:real(*a,**dict(k,timeout=.05))):
                ArrayStore(self.path,self.limits).close()
            reader.execute('ROLLBACK')
        # A read-only file is an access failure, not damage.
        copy_path=Path(self.tmp.name)/'readonly.db';copy_path.write_bytes(self.path.read_bytes())
        copy_path.chmod(stat.S_IREAD)
        try:
            with self.assertRaisesRegex(StoreError,r'could not be read or written \(SQLITE_READONLY'):ArrayStore(copy_path,self.limits)
        finally:
            copy_path.chmod(stat.S_IREAD|stat.S_IWRITE)

    def test_rows_of_the_wrong_sqlite_type_refuse_as_store_errors(self):
        # Column affinity lets a crafted genuine-schema store hold text or numbers where the store wrote blobs.
        a=np.arange(512.)
        for name,update in (('manifest-text',"UPDATE snapshots SET body=CAST(body AS TEXT)"),
                            ('manifest-integer',"UPDATE snapshots SET body=7"),
                            ('descriptor-text',"UPDATE chunks SET descriptor=CAST(descriptor AS TEXT)"),
                            ('codec-blob',"UPDATE chunks SET codec=CAST(codec AS BLOB)")):
            with self.subTest(update=name):
                path=Path(self.tmp.name)/(name+'.db')
                with ArrayStore(path,self.limits) as s:
                    s.put(key(name),{'a':a})
                    s._db.execute(update)
                    with self.assertRaisesRegex(StoreError,'record types'):s.get(key(name))
                    if name.startswith('manifest'):
                        with self.assertRaisesRegex(StoreError,'record types'):s.metadata(key(name))

    def test_links_refused(self):
        link=Path(self.tmp.name)/'link.db'
        try:link.symlink_to(self.path)
        except OSError as exc:
            if getattr(exc,'winerror',None)==1314:
                self.skipTest('Windows account lacks symbolic-link privilege')
            raise
        with self.assertRaises(StoreError):ArrayStore(link,self.limits)

    def test_metadata_identity_and_closed_store(self):
        self.store.put(key('m'),{'a':np.ones(10)},{'unit':'m','time':0})
        self.assertEqual(self.store.metadata(key('m')),{'unit':'m','time':0})
        with self.assertRaises(StoreConflict):self.store.put(key('m'),{'a':np.ones(10)},{'unit':'km'})
        self.store.close()
        with self.assertRaises(StoreError):self.store.statistics()


class StorePathTests(unittest.TestCase):
    """Store paths: links are refused, and a path is absent exactly where pathlib's exists() says so."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.target=Path(self.tmp.name)/'absent'/'store.db'
        self.real=Path.lstat

    def raising(self,code):
        def lstat(path,*args,**kwargs):
            if path==self.target:raise OSError(code,'injected')
            return self.real(path,*args,**kwargs)
        return mock.patch.object(Path,'lstat',lstat)

    def linked(self,links):
        def lstat(path,*args,**kwargs):
            if path==self.target:return mock.Mock(st_mode=stat.S_IFREG|0o600,st_nlink=links,st_file_attributes=0)
            return self.real(path,*args,**kwargs)
        return mock.patch.object(Path,'lstat',lstat)

    def test_pathlib_absent_errors_are_absent_and_others_propagate(self):
        from atlas_tectonics import storage
        for code in (errno.ENOENT,errno.ENOTDIR,errno.EBADF,errno.ELOOP):
            with self.subTest(errno=errno.errorcode[code]),self.raising(code):storage._path(self.target)
        with self.raising(errno.EACCES):
            with self.assertRaises(PermissionError):storage._path(self.target)
            storage._path(self.target,sidecar=True)          # a sidecar being deleted refuses access: absent
        with self.raising(errno.EIO),self.assertRaises(OSError):storage._path(self.target,sidecar=True)

    def test_pathlib_absent_windows_errors_are_absent(self):
        from atlas_tectonics import storage
        def raising(winerror,code=errno.EINVAL):
            def lstat(path,*args,**kwargs):
                if path==self.target:
                    exc=OSError(code,'injected');exc.winerror=winerror;raise exc
                return self.real(path,*args,**kwargs)
            return mock.patch.object(Path,'lstat',lstat)
        for winerror in (21,123,1921):                      # not ready, invalid name, cannot resolve the name
            with self.subTest(winerror=winerror),raising(winerror):storage._path(self.target)
        with raising(5,errno.EACCES),self.assertRaises(PermissionError):storage._path(self.target)

    def test_only_a_sidecar_may_show_no_remaining_link(self):
        from atlas_tectonics import storage
        with self.linked(0):
            storage._path(self.target,sidecar=True)
            with self.assertRaises(StoreError):storage._path(self.target)
        with self.linked(2),self.assertRaises(StoreError):storage._path(self.target,sidecar=True)


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'c.db'
        self.limits=StoreLimits(1024,1<<20,4<<20)
        self.store=ArrayStore(self.path,self.limits)

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def test_temperature_reuse_and_explicit_disable(self):
        args=(np.arange(10.),1.,THERMAL)
        a=cached_temperature(*args,store=self.store,cache_policy=CachePolicy(mode="always"))
        b=cached_temperature(*args,store=self.store,cache_policy=CachePolicy(mode="always"))
        assert_array_equal(a,b);assert_array_equal(a,cached_temperature(*args))
        self.assertEqual(self.store.statistics()['snapshots'],1)

    def test_source_and_loaded_instructions_participate(self):
        from atlas_tectonics.reuse import execution_identity
        import atlas_tectonics.thermal as thermal
        before=execution_identity()
        fn=thermal.half_space_temperature
        replacement=lambda *args,**kwargs: np.array([2.])
        replacement.__module__=thermal.__name__
        with mock.patch.object(thermal,'half_space_temperature',replacement):
            self.assertNotEqual(before,execution_identity())
        self.assertEqual(before,execution_identity())

    def test_parameter_input_and_backend_invalidation(self):
        d=np.arange(10.)
        for age,params,backend in ((1,THERMAL,'reference'),(2,THERMAL,'reference'),
                (1,replace(THERMAL,diffusivity_m2_s=2),'reference'),(1,THERMAL,'scipy')):
            cached_temperature(d,age,params,backend=backend,store=self.store,cache_policy=CachePolicy(mode="always"))
        self.assertEqual(self.store.statistics()['snapshots'],4)

    def test_flexure_load_and_operator_invalidation(self):
        g=PeriodicGrid1D(16,16);op=PeriodicFlexure(g,ELASTIC)
        for load,operator in ((1,op),(1,op),(2,op),(1,PeriodicFlexure(g,replace(ELASTIC,gravity_m_s2=2)))):
            a=cached_flexure(operator,np.full(16,float(load)),store=self.store,cache_policy=CachePolicy(mode="always"))
            assert_array_equal(a,operator.solve(np.full(16,float(load))))
        self.assertEqual(self.store.statistics()['snapshots'],3)

    def test_cache_reopen_returns_immutable_arrays(self):
        a=cached_temperature(np.arange(10.),1,THERMAL,store=self.store,cache_policy=CachePolicy(mode="always"))
        self.store.close();self.store=ArrayStore(self.path,self.limits)
        b=cached_temperature(np.arange(10.),1,THERMAL,store=self.store,cache_policy=CachePolicy(mode="always"))
        assert_array_equal(a,b)
        with self.assertRaises(ValueError):b.setflags(write=True)
        self.assertEqual(self.store.statistics()['snapshots'],1)

    def test_cache_identity_across_fresh_process(self):
        import os,subprocess,sys
        a=cached_temperature(np.arange(10.),1,THERMAL,store=self.store,cache_policy=CachePolicy(mode="always"))
        code="""import numpy as np
from atlas_tectonics.storage import ArrayStore,StoreLimits
from atlas_tectonics.parameters import ThermalParameters
from atlas_tectonics.reuse import cached_temperature, CachePolicy
import sys
with ArrayStore(sys.argv[1],StoreLimits(1024,1<<20,4<<20)) as s:
 r=cached_temperature(np.arange(10.),1.,ThermalParameters('synthetic','test only',300,1300,1),store=s,cache_policy=CachePolicy(mode="always"))
 print(s.statistics()['snapshots'])
"""
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),PYTHONDONTWRITEBYTECODE='1')
        proc=subprocess.run([sys.executable,'-B','-c',code,str(self.path)],env=env,text=True,capture_output=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(proc.stdout.strip(),'1')

    def test_verifier_refuses_local_bytecode(self):
        import importlib.util
        p=Path(__file__).resolve().parents[1]/'verify.py'
        spec=importlib.util.spec_from_file_location('atlas_local_verifier_test',p)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        root=Path(self.tmp.name)/'source';(root/'src').mkdir(parents=True)
        (root/'src/invalid.pyc').write_bytes(b'not executable')
        with self.assertRaisesRegex(ValueError,'bytecode'):module.source_inventory(root)

    def test_cache_does_not_hide_invalid_input(self):
        cached_temperature(np.ones(4),1,THERMAL,store=self.store,cache_policy=CachePolicy(mode="always"))
        with self.assertRaises(TectonicsError):cached_temperature(np.ma.array(np.ones(4)),1,THERMAL,store=self.store,cache_policy=CachePolicy(mode="always"))
        with self.assertRaises(MemoryLimitError):cached_temperature(np.ones((100,1)),np.ones((1,100)),THERMAL,store=self.store,cache_policy=CachePolicy(mode="always"),budget=WorkBudget(1000))


if __name__=='__main__':unittest.main()
