"""Exact sealed R7 preservation and its recursively bound scientific parents.

The R7 validation-only source references remain separately labelled inside the
retained identity. They are not promoted to active R8 biome/vegetation drivers.
"""
import builtins
import hashlib
import json
from pathlib import Path
import re
import stat
import types

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
R7_ROOT = TASK/'work/generator_upgrade_r7'
R7_SEAL = TASK/'outputs/generator-upgrade-r7/soil-reference-02/VERIFICATION.json'
R7_SEAL_SHA256 = 'a30fff2286386f045902296f461a65042d2c8dd56bd538c5f0ad1ae0bf2ebe5c'
R7_SOURCE_SHA256 = '1aa2010e3d9a43327811ada27557528ed4bb1af1a774c864ba62ad7e85511008'
R7_SOURCE_COUNT = 18
MAX_BYTES = 8*1024*1024
MAX_SOURCE_FILES = 128


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def plain_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute bounded source path required')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0)&0x400:
                raise ValueError('linked/reparse source refused')
    return path


def checked(path, expected=None):
    path = plain_path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('bounded regular source required')
    raw = path.read_bytes()
    if len(raw)>MAX_BYTES or (expected is not None and sha(raw)!=expected):
        raise ValueError('source changed; no silent repin: '+str(path))
    return raw


def source_snapshot(root=HERE):
    root = plain_path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        plain_path(path)  # Check directories before suffix/cache filtering.
        if '__pycache__' not in path.parts and path.is_file() and path.suffix in ('.py','.json','.md'):
            result[str(path)] = sha(checked(path))
    if not 0<len(result)<=MAX_SOURCE_FILES:
        raise ValueError('bounded nonempty source inventory required')
    return result


def retained_record():
    record = json.loads(checked(R7_SEAL,R7_SEAL_SHA256))
    identity = record.get('source_identity')
    if (record.get('source_sha256')!=R7_SOURCE_SHA256 or sha(encoded(identity))!=R7_SOURCE_SHA256
            or record.get('source_snapshot')!=identity['r7_sources']
            or len(identity['r7_sources'])!=R7_SOURCE_COUNT
            or source_snapshot(R7_ROOT)!=identity['r7_sources']
            or record.get('status')!='BOUNDED_SOIL_FORMATION_REFERENCE_VERIFIED'):
        raise ValueError('retained R7 seal/source identity differs')
    return record


def load_parent():
    """Fresh exact R7 bootstrap, retaining the actual nested private graph.

    Only R7's declared bootstrap import is resolved here. Its unchanged loader
    independently verifies and executes the sealed R6/R4/R3 scientific parents.
    No canonical module, global import hook or predecessor object is patched.
    """
    record = retained_record()
    pins = record['source_identity']['r7_sources']
    loaded = {}
    for name in ('provenance','binding'):
        path = R7_ROOT/(name+'.py')
        raw = checked(path,pins[str(path)])
        module = types.ModuleType('_r8_exact_r7_'+name)
        module.__file__ = str(path)
        module.__package__ = 'work.generator_upgrade_r7'
        def local_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level:
                if level!=1 or name!='' or tuple(fromlist)!=('provenance',):
                    raise ValueError('undeclared R7 bootstrap import')
                return types.SimpleNamespace(provenance=loaded['provenance'])
            if name=='work' or name.startswith('work.'):
                raise ValueError('undeclared project bootstrap import')
            return builtins.__import__(name,globals,locals,fromlist,level)
        module.__builtins__ = dict(vars(builtins),__import__=local_import)
        exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__)
        loaded[name] = module
        checked(path,pins[str(path)])
    parent = loaded['binding'].load()
    if parent.identity!=record['source_identity'] or parent.verify()!=R7_SOURCE_SHA256:
        raise ValueError('actual R7 execution differs from preserved seal')
    return parent


def source_identity(parent):
    record = retained_record()
    if parent.verify()!=R7_SOURCE_SHA256 or parent.identity!=record['source_identity']:
        raise ValueError('inherited actual R7 execution identity differs')
    sources=source_snapshot()
    references,external=reference_bindings(parent,sources)
    identity = {'schema':'diadem.biomes-vegetation-binding.r8','r8_sources':sources,
        'retained_r7_seal':{'path':str(R7_SEAL),'sha256':R7_SEAL_SHA256,'source_sha256':R7_SOURCE_SHA256},
        'retained_source_identity':parent.identity,
        'external_reference_bindings':references,'external_reference_sources':external,
        'dependency_binding':'exact unchanged isolated R7 soil parent and nested R6/R4/R3 climate/terrain/water; separately captured R8 biome/vegetation modules; no global patch or source rewrite',
        'runtime':parent.identity['runtime']}
    return identity,sha(encoded(identity))


def reference_bindings(parent,sources):
    """Review/reference roles from actual captured R8 code, never old GIS runs."""
    path=HERE/'biomes.py'
    if str(path) not in sources: raise ValueError('captured biome source ledger provider required')
    graph=parent.graph.__class__({'work.generator_upgrade_r8.biomes':(path,sources[str(path)])})
    provider=graph.load('work.generator_upgrade_r8.biomes')
    rows=provider.source_bindings()
    if type(rows) is not list or not 1<=len(rows)<=16:
        raise ValueError('bounded explicit external reference ledger required')
    references=[]; external={}
    for row in rows:
        if type(row) is not dict or set(row)!={'path','sha256','role'}:
            raise ValueError('exact external path/hash/role fields required')
        if (type(row['path']) is not str or type(row['sha256']) is not str
                or not re.fullmatch('[0-9a-f]{64}',row['sha256'])
                or type(row['role']) is not str or not row['role'].strip() or len(row['role'])>4096):
            raise ValueError('explicit external source identity and review role required')
        source=plain_path(row['path']); key=str(source.resolve())
        if key in external: raise ValueError('duplicate external source ledger entry')
        checked(source,row['sha256'])
        references.append(dict(row,path=key)); external[key]=row['sha256']
    graph.verify()
    return references,external
