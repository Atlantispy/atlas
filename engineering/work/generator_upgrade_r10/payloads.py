"""Bounded lossless scientific unit records; no relaxed JSON/decompression limits."""
import base64
import hashlib
import json
import math
import zlib

MAX_BYTES=8*1024*1024
SCHEMA='diadem.bounded-seasonal-unit.r10'


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def native(value):
    if type(value) is dict:
        if any(type(k) is not str for k in value): raise ValueError('lossless records require string object keys')
        for child in value.values(): native(child)
    elif type(value) is list:
        for child in value: native(child)
    elif value is None or type(value) in (bool,str,int): return
    elif type(value) is float and math.isfinite(value): return
    else: raise ValueError('lossless JSON-native records required, without tuple/key/type coercion')


def pack(value):
    if type(value) is not dict: raise ValueError('one scientific unit object required')
    native(value)
    raw=encoded(value)
    if len(raw)>MAX_BYTES: raise ValueError('scientific unit exceeds unchanged8MiB bound')
    data=base64.b64encode(zlib.compress(raw,level=6)).decode('ascii')
    if len(data)>MAX_BYTES: raise ValueError('encoded unit exceeds unchanged8MiB bound')
    return {'schema':SCHEMA,'encoding':'ZLIB_BASE64','byte_length':len(raw),
        'sha256':hashlib.sha256(raw).hexdigest(),'data':data}


def unpack(record):
    if type(record) is not dict or set(record)!={'schema','encoding','byte_length','sha256','data'} or record['schema']!=SCHEMA or record['encoding']!='ZLIB_BASE64': raise ValueError('exact bounded unit record required')
    length=record['byte_length']; data=record['data']; digest=record['sha256']
    if type(length) is not int or not 1<=length<=MAX_BYTES or type(data) is not str or not 1<=len(data)<=MAX_BYTES: raise ValueError('bounded explicit compressed and raw lengths required')
    if type(digest) is not str or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest): raise ValueError('exact unit SHA256 required')
    try:
        compressed=base64.b64decode(data,validate=True)
        decoder=zlib.decompressobj(); raw=decoder.decompress(compressed,length+1)
        if len(raw)!=length or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data: raise ValueError('truncated/oversized/trailing compressed unit refused')
    except (ValueError,zlib.error) as exc: raise ValueError('invalid bounded lossless unit') from exc
    if hashlib.sha256(raw).hexdigest()!=digest: raise ValueError('scientific unit checksum mismatch')
    try: value=json.loads(raw)
    except (ValueError,UnicodeError) as exc: raise ValueError('invalid scientific JSON unit') from exc
    if type(value) is not dict or encoded(value)!=raw: raise ValueError('canonical finite scientific JSON object required')
    return value
