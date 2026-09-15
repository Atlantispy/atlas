from copy import deepcopy
import base64
import hashlib
import zlib
import unittest
from . import payloads as p


class BoundedRecordTests(unittest.TestCase):
    def test_lossless_canonical_roundtrip(self):
        value={'b':[1,1.25,None],'a':{'exact':'1/3'}}
        packed=p.pack(value)
        self.assertEqual(p.unpack(packed),value)
        self.assertEqual(p.pack(deepcopy(value)),packed)
    def test_changed_scientific_value_changes_identity(self):
        self.assertNotEqual(p.pack({'x':1})['sha256'],p.pack({'x':2})['sha256'])
    def test_checksum_forgery(self):
        r=p.pack({'a':1});r['sha256']='0'*64
        with self.assertRaises(ValueError):p.unpack(r)
    def test_raw_size_forgery(self):
        r=p.pack({'a':1});r['byte_length']-=1
        with self.assertRaises(ValueError):p.unpack(r)
    def test_zip_bomb_bounded_by_declared_length(self):
        raw=b' '*100000;r={'schema':p.SCHEMA,'encoding':'ZLIB_BASE64','byte_length':2,'sha256':hashlib.sha256(raw).hexdigest(),'data':base64.b64encode(zlib.compress(raw)).decode()}
        with self.assertRaises(ValueError):p.unpack(r)
    def test_second_compressed_stream_refused(self):
        r=p.pack({'a':1});r['data']=base64.b64encode(base64.b64decode(r['data'])+zlib.compress(b'{}')).decode()
        with self.assertRaises(ValueError):p.unpack(r)
    def test_trailing_raw_garbage_refused(self):
        r=p.pack({'a':1});r['data']=base64.b64encode(base64.b64decode(r['data'])+b'x').decode()
        with self.assertRaises(ValueError):p.unpack(r)
    def test_truncated_zlib_refused(self):
        r=p.pack({'a':1});r['data']=base64.b64encode(base64.b64decode(r['data'])[:-2]).decode()
        with self.assertRaises(ValueError):p.unpack(r)
    def test_duplicate_json_keys_refused(self):
        raw=b'{"x":1,"x":2}';r={'schema':p.SCHEMA,'encoding':'ZLIB_BASE64','byte_length':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'data':base64.b64encode(zlib.compress(raw)).decode()}
        with self.assertRaises(ValueError):p.unpack(r)
    def test_nonfinite_pack_refused(self):
        with self.assertRaises(ValueError):p.pack({'x':float('nan')})
    def test_noncanonical_json_refused(self):
        raw=b'{ "x": 1 }';r={'schema':p.SCHEMA,'encoding':'ZLIB_BASE64','byte_length':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'data':base64.b64encode(zlib.compress(raw)).decode()}
        with self.assertRaises(ValueError):p.unpack(r)
    def test_unknown_envelope_fields_refused(self):
        r=p.pack({'x':1});r['extra']=1
        with self.assertRaises(ValueError):p.unpack(r)
    def test_boolean_length_refused(self):
        r=p.pack({'x':1});r['byte_length']=True
        with self.assertRaises(ValueError):p.unpack(r)
    def test_nonobject_payload_refused(self):
        with self.assertRaises(ValueError):p.pack([1])
    def test_raw_guard_unchanged(self):
        self.assertEqual(p.MAX_BYTES,8*1024*1024)
        r=p.pack({'x':1});r['byte_length']=p.MAX_BYTES+1
        with self.assertRaises(ValueError):p.unpack(r)
    def test_base64_junk_refused(self):
        r=p.pack({'x':1});r['data']='!!!'
        with self.assertRaises(ValueError):p.unpack(r)
    def test_nested_numeric_key_not_silently_coerced(self):
        with self.assertRaises(ValueError):p.pack({'a':{1:'x'}})
    def test_nested_boolean_key_not_silently_coerced(self):
        with self.assertRaises(ValueError):p.pack({'a':{True:'x'}})
    def test_nested_none_key_not_silently_coerced(self):
        with self.assertRaises(ValueError):p.pack({'a':{None:'x'}})
    def test_tuple_not_silently_coerced(self):
        with self.assertRaises(ValueError):p.pack({'a':(1,2)})


if __name__=='__main__':unittest.main()
