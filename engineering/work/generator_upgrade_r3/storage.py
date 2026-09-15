"""Bounded strict JSON checkpoints and exclusive local reference artefacts."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import stat

MAX_BYTES=8*1024*1024
MAX_DEPTH=48
MAX_ITEMS=200000
TASK=Path(__file__).resolve().parents[2]
OUTPUT_ROOT=TASK/'outputs/generator-upgrade-r3'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def digest(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('exact SHA256 required')
    return value


def _structure(value,depth=0,budget=None):
    if budget is None:budget=[MAX_ITEMS]
    budget[0]-=1
    if depth>MAX_DEPTH or budget[0]<0:raise ValueError('JSON resource envelope exceeded')
    if type(value) is dict:
        if any(type(k) is not str for k in value):raise ValueError('string JSON keys required')
        for child in value.values():_structure(child,depth+1,budget)
    elif type(value) is list:
        for child in value:_structure(child,depth+1,budget)
    elif type(value) not in (str,int,float,bool,type(None)):
        raise ValueError('only explicit JSON values are serialisable')


def encoded(value):
    _structure(value)
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=True).encode('utf-8')
    if len(raw)>MAX_BYTES:raise ValueError('JSON byte envelope exceeded')
    return raw


def decoded(raw):
    if type(raw) is not bytes or len(raw)>MAX_BYTES:raise ValueError('bounded JSON bytes required')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate JSON key')
            result[key]=value
        return result
    def bad(value):raise ValueError('nonfinite JSON constant')
    try:value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=bad)
    except (RecursionError,UnicodeError) as exc:raise ValueError('invalid JSON representation') from exc
    # Also rejects numeric exponent overflow (1e999), not just NaN literals.
    encoded(value)
    return value


def plain_path(path):
    path=Path(path)
    if not path.is_absolute():raise ValueError('absolute path required')
    for p in (path,*path.parents):
        if p.exists() or p.is_symlink():
            info=p.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('linked/reparse path refused')
    return path


def read_json(path):
    path=plain_path(path)
    if not path.is_file() or path.stat().st_size>MAX_BYTES:raise ValueError('bounded regular JSON file required')
    return decoded(path.read_bytes())


def write_json(path,value):
    path=plain_path(path);raw=encoded(value)
    # Exclusive creation preserves completed and interrupted predecessors alike.
    with path.open('xb') as f:f.write(raw)
    if path.read_bytes()!=raw:raise IOError('saved JSON readback differs')
    return sha(raw)


def checkpoint(state,*,recipe_sha256,source_sha256):
    return {'schema':'diadem.terrain-water-soil-checkpoint.r3','recipe_sha256':digest(recipe_sha256),
        'source_sha256':digest(source_sha256),'state_sha256':sha(encoded(state)),'state':state}


def restore(envelope,*,recipe_sha256,source_sha256):
    expected={'schema','recipe_sha256','source_sha256','state_sha256','state'}
    if type(envelope) is not dict or set(envelope)!=expected or envelope['schema']!='diadem.terrain-water-soil-checkpoint.r3':
        raise ValueError('checkpoint schema differs')
    if envelope['recipe_sha256']!=digest(recipe_sha256) or envelope['source_sha256']!=digest(source_sha256):
        raise ValueError('checkpoint belongs to different recipe or actual source')
    if digest(envelope['state_sha256'])!=sha(encoded(envelope['state'])):raise ValueError('checkpoint state checksum differs')
    # A checksum detects damage, not dishonest authority. The model revalidates
    # restored quantities, identities and cumulative conservation before use.
    return decoded(encoded(envelope['state']))


def save_reference(run_id,*,recipe,result,checkpoint_record,evidence):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',run_id):raise ValueError('bounded new run ID required')
    root=plain_path(OUTPUT_ROOT/run_id)
    items={'recipe.json':recipe,'result.json':result,'checkpoint.json':checkpoint_record}
    # Validate everything before materialising a directory.
    for item in (*items.values(),evidence):encoded(item)
    root.mkdir(parents=True,exist_ok=False)
    files={name:write_json(root/name,value) for name,value in items.items()}
    receipt={'schema':'diadem.terrain-water-soil-artifact.r3','files':files,'evidence':evidence,
             'production_installed':False,'canon_changed':False}
    write_json(root/'RECEIPT.json',receipt)
    checked=read_reference(root)
    if checked['receipt']!=receipt:raise IOError('reference receipt readback mismatch')
    return root,receipt


def read_reference(root):
    root=plain_path(root);receipt=read_json(root/'RECEIPT.json')
    if {p.name for p in root.iterdir()}!={'RECEIPT.json','recipe.json','result.json','checkpoint.json'}:
        raise ValueError('reference artifact inventory differs')
    if (type(receipt) is not dict or set(receipt)!={'schema','files','evidence','production_installed','canon_changed'}
            or receipt['schema']!='diadem.terrain-water-soil-artifact.r3'
            or receipt['production_installed'] is not False or receipt['canon_changed'] is not False
            or type(receipt['files']) is not dict or set(receipt['files'])!={'recipe.json','result.json','checkpoint.json'}):
        raise ValueError('invalid reference artifact receipt')
    values={}
    for name,expected in receipt['files'].items():
        path=plain_path(root/name)
        if not path.is_file() or path.stat().st_size>MAX_BYTES:raise ValueError('missing/oversize reference product')
        raw=path.read_bytes()
        if sha(raw)!=digest(expected):raise ValueError('reference product checksum differs: '+name)
        values[name]=decoded(raw)
    return {'receipt':receipt,**values}
