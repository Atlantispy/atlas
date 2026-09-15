"""Exact sealed R8 preservation and its recursively bound scientific parents.

The R8 validation-only source references remain separately labelled inside the
retained identity. They are not promoted to active R9 biological trait or population evidence.
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
R8_ROOT = TASK/'work/generator_upgrade_r8'
R8_SEAL = TASK/'outputs/generator-upgrade-r8/biomes-reference-01/VERIFICATION.json'
R8_SEAL_SHA256 = 'b97457835f284cd434f16dbc97a6471c4bb5923cd16736f4eb150a5e17c946dd'
R8_SOURCE_SHA256 = '47da686fbcf2bbbd9542db79e936bec619f38449ca53768dcd04c99aafcd094f'
R8_SOURCE_COUNT = 20
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
    record = json.loads(checked(R8_SEAL,R8_SEAL_SHA256))
    identity = record.get('source_identity')
    if (record.get('source_sha256')!=R8_SOURCE_SHA256 or sha(encoded(identity))!=R8_SOURCE_SHA256
            or record.get('source_snapshot')!=identity['r8_sources']
            or len(identity['r8_sources'])!=R8_SOURCE_COUNT
            or source_snapshot(R8_ROOT)!=identity['r8_sources']
            or record.get('status')!='BOUNDED_BIOMES_VEGETATION_REFERENCE_VERIFIED'):
        raise ValueError('retained R8 seal/source identity differs')
    return record


def load_parent():
    """Fresh exact R8 bootstrap, retaining the actual nested private graph.

    Only R8's declared bootstrap import is resolved here. Its unchanged loader
    independently verifies and executes the sealed R6/R4/R3 scientific parents.
    No canonical module, global import hook or predecessor object is patched.
    """
    record = retained_record()
    pins = record['source_identity']['r8_sources']
    loaded = {}
    for name in ('provenance','binding'):
        path = R8_ROOT/(name+'.py')
        raw = checked(path,pins[str(path)])
        module = types.ModuleType('_r9_exact_r8_'+name)
        module.__file__ = str(path)
        module.__package__ = 'work.generator_upgrade_r8'
        def local_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level:
                if level!=1 or name!='' or tuple(fromlist)!=('provenance',):
                    raise ValueError('undeclared R8 bootstrap import')
                return types.SimpleNamespace(provenance=loaded['provenance'])
            if name=='work' or name.startswith('work.'):
                raise ValueError('undeclared project bootstrap import')
            return builtins.__import__(name,globals,locals,fromlist,level)
        module.__builtins__ = dict(vars(builtins),__import__=local_import)
        exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__)
        loaded[name] = module
        checked(path,pins[str(path)])
    parent = loaded['binding'].load()
    if parent.identity!=record['source_identity'] or parent.verify()!=R8_SOURCE_SHA256:
        raise ValueError('actual R8 execution differs from preserved seal')
    return parent


def source_identity(parent):
    record = retained_record()
    if parent.verify()!=R8_SOURCE_SHA256 or parent.identity!=record['source_identity']:
        raise ValueError('inherited actual R8 execution identity differs')
    sources=source_snapshot()
    references,external=reference_bindings(parent,sources)
    identity = {'schema':'diadem.species-spatial-binding.r9','r9_sources':sources,
        'retained_r8_seal':{'path':str(R8_SEAL),'sha256':R8_SEAL_SHA256,'source_sha256':R8_SOURCE_SHA256},
        'retained_source_identity':parent.identity,
        'external_reference_bindings':references,'external_reference_sources':external,
        'dependency_binding':'exact unchanged isolated R8 biomes/vegetation parent and nested R7 soil plus R6/R4/R3 climate/terrain/water; separately captured R9 spatial ecology modules; no global patch or source rewrite',
        'runtime':parent.identity['runtime']}
    return identity,sha(encoded(identity))


def reference_bindings(parent,sources):
    """Review/reference roles from actual captured R9 code, never old GIS runs."""
    nodes={}
    for name in ('sources','owner_inputs'):
        path=HERE/(name+'.py')
        if str(path) not in sources: raise ValueError('captured species source ledger provider required: '+name)
        nodes['work.generator_upgrade_r9.'+name]=(path,sources[str(path)])
    graph=parent.graph.__class__(nodes)
    rows=[graph.load(name).source_bindings() for name in nodes]
    references,external=merge_reference_bindings(rows)
    graph.verify()
    return references,external


def merge_reference_bindings(providers):
    """Deduplicate shared evidence bytes while retaining both declared roles."""
    if type(providers) is not list or not providers: raise ValueError('explicit source providers required')
    references=[]; external={}
    roles={}
    for rows in providers:
        if type(rows) is not list or not 1<=len(rows)<=256:
            raise ValueError('bounded explicit external reference ledger required')
        seen=set()
        for row in rows:
            if type(row) is not dict or set(row)!={'path','sha256','role'}:
                raise ValueError('exact external path/hash/role fields required')
            if (type(row['path']) is not str or type(row['sha256']) is not str
                    or not re.fullmatch('[0-9a-f]{64}',row['sha256'])
                    or type(row['role']) is not str or not row['role'].strip() or len(row['role'])>4096):
                raise ValueError('explicit external source identity and review role required')
            source=plain_path(row['path']); key=str(source.resolve())
            if key in seen: raise ValueError('duplicate entry within a source provider')
            seen.add(key)
            if key in external and external[key]!=row['sha256']: raise ValueError('conflicting external source binding')
            checked(source,row['sha256'])
            external[key]=row['sha256']; roles.setdefault(key,set()).add(row['role'])
    if len(external)>256: raise ValueError('combined external reference inventory exceeds bound')
    for key in sorted(external):
        references.append({'path':key,'sha256':external[key],'role':' | '.join(sorted(roles[key]))})
    return references,external
