"""Exact R6 preservation, including its recursively bound scientific parents."""
import builtins
import hashlib
import json
from pathlib import Path
import stat
import types

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
R6_ROOT = TASK/'work/generator_upgrade_r6'
R6_SEAL = TASK/'outputs/generator-upgrade-r6/strict-reference-01/VERIFICATION.json'
R6_SEAL_SHA256 = '6ef91119e8d108bd4816472973763653dccf0588b2d38e0b019adf177ce3f46c'
R6_SOURCE_SHA256 = 'd1800a7a1f75528c3e8df02d5e26281e851512e37cc7344cd85ffc55add1e008'
MAX_BYTES = 8*1024*1024
TEST_REFERENCE_SOURCES = {
    str(TASK/'work/terrain_model_r2/materials.py'):'097f7f3ca8c5dd2af9f06e1b7478aa3081c55e22f1dba4384159ad471cc4f961',
    'C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/02_Working_Files/Geography/Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-10-R1/CLIMATE_SOILS_OWNER_DECISION_2026-09-10_R1.md':'ba909d8a3e34a1722cba51925d602eca28d749a91a7bbf2162baf99221b4de19',
}


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
        plain_path(path)  # Inspect directories before extension/cache filtering.
        if '__pycache__' not in path.parts and path.is_file() and path.suffix in ('.py','.json','.md'):
            result[str(path)] = sha(checked(path))
    if not 0<len(result)<=128:
        raise ValueError('bounded nonempty source inventory required')
    return result


def retained_record():
    record = json.loads(checked(R6_SEAL,R6_SEAL_SHA256))
    identity = record.get('source_identity')
    if (record.get('source_sha256')!=R6_SOURCE_SHA256 or sha(encoded(identity))!=R6_SOURCE_SHA256
            or record.get('source_snapshot')!=identity['r6_sources']
            or len(identity['r6_sources'])!=12 or source_snapshot(R6_ROOT)!=identity['r6_sources']
            or record.get('status')!='BOUNDED_STRICT_SOLVER_SUCCESSOR_VERIFIED'):
        raise ValueError('retained R6 seal/source identity differs')
    return record


def load_parent():
    """Fresh exact R6 bootstrap; no global predecessor import or module mutation."""
    record = retained_record()
    pins = record['source_identity']['r6_sources']
    loaded = {}
    for name in ('provenance','binding'):
        path = R6_ROOT/(name+'.py')
        raw = checked(path,pins[str(path)])
        module = types.ModuleType('_r7_exact_r6_'+name)
        module.__file__ = str(path)
        module.__package__ = 'work.generator_upgrade_r6'
        def local_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level:
                if level!=1 or name!='' or tuple(fromlist)!=('provenance',):
                    raise ValueError('undeclared R6 bootstrap import')
                return types.SimpleNamespace(provenance=loaded['provenance'])
            if name.startswith('work'):
                raise ValueError('undeclared project bootstrap import')
            return builtins.__import__(name,globals,locals,fromlist,level)
        module.__builtins__ = dict(vars(builtins),__import__=local_import)
        exec(compile(raw,str(path),'exec',dont_inherit=True),module.__dict__)
        loaded[name] = module
        checked(path,pins[str(path)])
    parent = loaded['binding'].load()
    if parent.identity!=record['source_identity'] or parent.verify()!=R6_SOURCE_SHA256:
        raise ValueError('actual R6 execution differs from its preserved seal')
    return parent


def source_identity(parent):
    record = retained_record()
    if parent.verify()!=R6_SOURCE_SHA256 or parent.identity!=record['source_identity']:
        raise ValueError('inherited execution identity differs')
    # Explicit new regression references, NOT silently added to the inherited
    # protected inventory or used as active soil-production dependencies.
    test_sources={str(plain_path(path)):digest for path,digest in TEST_REFERENCE_SOURCES.items()}
    for path,digest in test_sources.items(): checked(path,digest)
    identity = {'schema':'diadem.soil-formation-binding.r7','r7_sources':source_snapshot(),
        'retained_r6_seal':{'path':str(R6_SEAL),'sha256':R6_SEAL_SHA256,'source_sha256':R6_SOURCE_SHA256},
        'retained_source_identity':parent.identity,
        'external_test_reference_sources':test_sources,
        'dependency_binding':'exact unchanged isolated R6 climate/terrain/water producer; explicit one-way R7 fixed-exposure soil process; no source rewrite/global patch',
        'runtime':parent.identity['runtime']}
    return identity,sha(encoded(identity))
