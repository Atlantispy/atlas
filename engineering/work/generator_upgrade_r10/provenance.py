"""Exact sealed R9 preservation and its recursively bound scientific parents.

The R9 biological roster, scoped stocks, physical parents and explicit input
gaps retain their sealed meanings. New seasonal owner evidence is separate;
neither numerical engine verification nor this successor adopts domain canon.
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
R9_ROOT = TASK/'work/generator_upgrade_r9'
R9_SEAL = TASK/'outputs/generator-upgrade-r9/species-reference-01/VERIFICATION.json'
R9_SEAL_SHA256 = '4a91c1427e12bcfd594f3a5a2c2ab1811fc88889d89037e1c16e625a9cce1055'
R9_SOURCE_SHA256 = 'b192d3eaa2ef8def21041892a4db0a5b71a0b62e9ec812cb6e28edd1290c609e'
R9_SOURCE_COUNT = 27
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
    record = json.loads(checked(R9_SEAL,R9_SEAL_SHA256))
    identity = record.get('source_identity')
    if (record.get('source_sha256')!=R9_SOURCE_SHA256 or sha(encoded(identity))!=R9_SOURCE_SHA256
            or record.get('source_snapshot')!=identity['r9_sources']
            or len(identity['r9_sources'])!=R9_SOURCE_COUNT
            or source_snapshot(R9_ROOT)!=identity['r9_sources']
            or record.get('status')!='BOUNDED_SPECIES_SPATIAL_ENGINE_VERIFIED_WITH_INPUT_GAPS'):
        raise ValueError('retained R9 seal/source identity differs')
    return record


def load_parent():
    """Fresh exact R9 bootstrap, retaining the actual nested private graph.

    Only R9's declared bootstrap import is resolved here. Its unchanged loader
    independently verifies and executes the sealed R6/R4/R3 scientific parents.
    No canonical module, global import hook or predecessor object is patched.
    """
    record = retained_record()
    pins = record['source_identity']['r9_sources']
    loaded = {}
    for name in ('provenance','binding'):
        path = R9_ROOT/(name+'.py')
        raw = checked(path,pins[str(path)])
        module = types.ModuleType('_r10_exact_r9_'+name)
        module.__file__ = str(path)
        module.__package__ = 'work.generator_upgrade_r9'
        def local_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level:
                if level!=1 or name!='' or tuple(fromlist)!=('provenance',):
                    raise ValueError('undeclared R9 bootstrap import')
                return types.SimpleNamespace(provenance=loaded['provenance'])
            if name=='work' or name.startswith('work.'):
                raise ValueError('undeclared project bootstrap import')
            return builtins.__import__(name,globals,locals,fromlist,level)
        module.__builtins__ = dict(vars(builtins),__import__=local_import)
        exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__)
        loaded[name] = module
        checked(path,pins[str(path)])
    parent = loaded['binding'].load()
    if parent.identity!=record['source_identity'] or parent.verify()!=R9_SOURCE_SHA256:
        raise ValueError('actual R9 execution differs from preserved seal')
    return parent


def source_identity(parent):
    record = retained_record()
    if parent.verify()!=R9_SOURCE_SHA256 or parent.identity!=record['source_identity']:
        raise ValueError('inherited actual R9 execution identity differs')
    sources=source_snapshot()
    references,external=reference_bindings(parent,sources)
    identity = {'schema':'diadem.seasonal-world-binding.r10','r10_sources':sources,
        'retained_r9_seal':{'path':str(R9_SEAL),'sha256':R9_SEAL_SHA256,'source_sha256':R9_SOURCE_SHA256},
        'retained_source_identity':parent.identity,
        'external_reference_bindings':references,'external_reference_sources':external,
        'numerical_implementation':numerical_sources(parent,sources),
        'dependency_binding':'exact unchanged isolated R9 spatial-species parent, R8 biomes/vegetation, R7 soil plus R6/R4/R3 climate/terrain/water; R10-local saturation-branch numerical correction retains exact R6 physical types/constitutive APIs, not unchanged R6 numerical execution; separately captured seasonal/plant/carbon modules; saved R8 output is validation-only evidence, not a replacement for release execution; no global patch or source rewrite',
        'runtime':parent.identity['runtime']}
    return identity,sha(encoded(identity))


def numerical_sources(parent,sources):
    adapter=HERE/'richards_numerics.py'; predecessor=TASK/'work/generator_upgrade_r6/soil_water.py'
    kernel=TASK/'work/generator_upgrade_r6/hydraulic_jacobian.py'
    if str(adapter) not in sources: raise ValueError('captured R10 saturation numerical adapter required')
    retained=parent.identity
    for _ in range(3): retained=retained['retained_source_identity']
    bound={str(adapter):sources[str(adapter)]}
    for path in (predecessor,kernel): bound[str(path)]=retained['r6_sources'][str(path)]
    for path,digest in bound.items(): checked(path,digest)
    return {'name':'R10_SATURATION_BRANCH_RESOLUTION',
        'sources':bound,
        'runtime_binding':{'implementation':'R10_SATURATION_BRANCH_RESOLUTION',
            'adapter':{'path':str(adapter),'sha256':bound[str(adapter)]},
            'retained_solver':{'path':str(predecessor),'sha256':bound[str(predecessor)]},
            'retained_hydraulic_kernel':{'path':str(kernel),'sha256':bound[str(kernel)]}},
        'physical_api':'EXACT_INHERITED_R6_TYPES_AND_CONSTITUTIVE_LAWS',
        'predecessor_modified':False,'retained_result_schema_is_not_an_unchanged_algorithm_claim':True}


def reference_bindings(parent,sources):
    """Review/reference roles from actual captured R10 code, never old GIS runs."""
    nodes={}
    for name in ('owner_inputs','fixtures'):
        path=HERE/(name+'.py')
        if str(path) not in sources: raise ValueError('captured seasonal owner source ledger provider required: '+name)
        nodes['work.generator_upgrade_r10.'+name]=(path,sources[str(path)])
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
