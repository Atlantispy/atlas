"""Capture current R11 bytes; execute unchanged, independently sealed parents."""
import builtins
import hashlib
import json
from pathlib import Path
import stat
import types

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
PARENT_ROOT = TASK/'work/generator_upgrade_r10'
PARENT_SEAL = TASK/'outputs/generator-upgrade-r10/seasonal-reference-01/VERIFICATION.json'
PARENT_SEAL_SHA256 = '610396bd1e358ac2501059020597482041f73b487655ea062f9a8f478b91e509'
PARENT_SOURCE_SHA256 = 'ee587784a31e162588c77561615f0ff536787a336602517b18e3c2ebcc7e1f35'
MAX_BYTES = 8*1024*1024
MAX_SOURCE_FILES = 128
SPECIES_ROOT = Path(r'C:\Users\LOCAL_USER\Documents\The Diadem - Local Workspace\02_Working_Files\Species_Coordination\Generator_R11_Inputs_2026-09-11')
SPECIES_MANIFEST = SPECIES_ROOT/'DELIVERY_MANIFEST_R1.json'
SPECIES_MANIFEST_SHA256 = '7d91d7c46275581574092f5a3f11dbf0ddb7391a546864a59a9e4433f97ab5d4'
PARENT_FIXTURE = TASK/'outputs/generator-upgrade-r10/seasonal-reference-01/n-worker-reference/full-result.json'
PARENT_FIXTURE_SHA256 = 'f191389d93c411f81e7003e5edf96551b53dc945e359dc705d83d00c64a0930e'
PHYSICAL_FIXTURE = TASK/'outputs/generator-upgrade-r10/seasonal-reference-01/n-worker-reference/physical-parent-result.json'
PHYSICAL_FIXTURE_SHA256 = '19a0975d09d1571e68ed510421b085675753b64ddfba316c8e8e2d68662cb000'
GEO_ROOT = TASK.parent/'the-diadem-local-tasks/work/r11_geo_closure'
GEO_CONTRACT = GEO_ROOT/'CONTRACT_R1.json'
GEO_CONTRACT_SHA256 = 'e38a01dc1c822d7b3e5d780933ee64d3ebe636ff2fa74dd9a424266bd8b0d0b8'
GEO_DELTAS = GEO_ROOT/'OWNER_DELTAS_P1_P2.json'
GEO_DELTAS_SHA256 = 'd6fcb2735606c126deaffbc45ca5655f68f97ae10eb5dcd74a062f0e816d4389'
EXTRA_SEALS = (
    ('outputs/generator-upgrade-r1/integrated-reference-01/VERIFICATION.json',
     '5f34947fcd9d87c62461ef86862af4e05e5d2cf879be3eb1f226ff8f98b5b5d5',
     ('work/generator_upgrade_r1/agroclimate.py',)),
    ('outputs/generator-upgrade-r2/integrated-reference-02/VERIFICATION.json',
     'bbaf37fddfce682cbf52705efa43510705e359299b540bab10a86d9bdd663650',
     ('work/generator_upgrade_r2/multicommodity.py',)),
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def plain_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute non-traversing path required')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0)&0x400:
                raise ValueError('linked/reparse path refused')
    return path


def checked(path, expected=None):
    path = plain_path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('bounded regular source required')
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or expected is not None and sha(raw) != expected:
        raise ValueError('source changed; no repin: '+str(path))
    return raw


def source_snapshot(root=HERE):
    result = {}
    for path in sorted(plain_path(root).rglob('*')):
        plain_path(path)
        if '__pycache__' not in path.parts and path.is_file() and path.suffix in ('.py', '.md', '.json'):
            result[str(path)] = sha(checked(path))
    if not 0 < len(result) <= MAX_SOURCE_FILES:
        raise ValueError('bounded nonempty source inventory required')
    return result


def retained_record():
    record = json.loads(checked(PARENT_SEAL, PARENT_SEAL_SHA256))
    identity = record['source_identity']
    if (record['source_sha256'] != PARENT_SOURCE_SHA256
            or sha(encoded(identity)) != PARENT_SOURCE_SHA256
            or record['status'] != 'BOUNDED_SEASONAL_WORLD_REFERENCE_VERIFIED_WITH_DOWNSTREAM_INPUT_GAPS'
            or record['source_snapshot'] != identity['r10_sources']
            or len(identity['r10_sources']) != 29
            or source_snapshot(PARENT_ROOT) != identity['r10_sources']):
        raise ValueError('sealed R10 identity/source differs')
    return record


def load_parent():
    record = retained_record()
    pins = record['source_snapshot']
    loaded = {}
    for name in ('provenance', 'binding'):
        path = PARENT_ROOT/(name+'.py')
        raw = checked(path, pins[str(path)])
        module = types.ModuleType('_r11_exact_r10_'+name)
        module.__file__ = str(path)
        module.__package__ = 'work.generator_upgrade_r10'
        def local_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level:
                if level != 1 or name != '' or tuple(fromlist) != ('provenance',):
                    raise ValueError('undeclared R10 bootstrap import')
                return types.SimpleNamespace(provenance=loaded['provenance'])
            if name == 'work' or name.startswith('work.'):
                raise ValueError('undeclared project bootstrap import')
            return builtins.__import__(name, globals, locals, fromlist, level)
        module.__builtins__ = dict(vars(builtins), __import__=local_import)
        exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
        loaded[name] = module
        checked(path, pins[str(path)])
    parent = loaded['binding'].load()
    if parent.verify() != PARENT_SOURCE_SHA256 or parent.identity != record['source_identity']:
        raise ValueError('actual R10 parent differs')
    return parent


def extra_sources():
    result = {}
    for seal, digest, modules in EXTRA_SEALS:
        record = json.loads(checked(TASK/seal, digest))
        for module in modules:
            path = TASK/module
            expected = record['source_snapshot'][str(path)]
            checked(path, expected)
            result[str(path)] = expected
    return result


def external_sources():
    """Bind actual delivered owner bytes, not mutable task-message summaries."""
    result = {str(SPECIES_MANIFEST): SPECIES_MANIFEST_SHA256,
              str(PARENT_FIXTURE): PARENT_FIXTURE_SHA256,
              str(PHYSICAL_FIXTURE): PHYSICAL_FIXTURE_SHA256,
              str(GEO_CONTRACT): GEO_CONTRACT_SHA256, str(GEO_DELTAS): GEO_DELTAS_SHA256}
    checked(PARENT_FIXTURE, PARENT_FIXTURE_SHA256)
    checked(PHYSICAL_FIXTURE, PHYSICAL_FIXTURE_SHA256)
    manifest = json.loads(checked(SPECIES_MANIFEST, SPECIES_MANIFEST_SHA256))
    if (manifest['change_id'] != 'ENG-R11-SPECIES-INPUTS-2026-09-11/result'
            or manifest['revision'] != 1 or len(manifest['files']) != 24
            or Path(manifest['destination_directory']) != SPECIES_ROOT):
        raise ValueError('exact biological owner delivery required')
    for row in manifest['files']:
        relative = Path(row['relative_path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('contained biological delivery path required')
        path = plain_path(SPECIES_ROOT/relative)
        if path != Path(row['path']) or str(path) in result:
            raise ValueError('unique owner delivery path required')
        raw = checked(path, row['sha256'])
        if type(row['bytes']) is not int or len(raw) != row['bytes']:
            raise ValueError('owner delivery size differs')
        result[str(path)] = row['sha256']
    entry = manifest['entry_point']
    if result.get(entry['path']) != entry['sha256']:
        raise ValueError('owner entrypoint differs from delivered inventory')
    geo = json.loads(checked(GEO_CONTRACT, GEO_CONTRACT_SHA256))
    if geo['result_id'] != 'ENG-R11-GEO-CLOSURE-2026-09-11/result' or geo['revision'] != 1 or len(geo['artifacts']) != 4:
        raise ValueError('exact GEO input decision required')
    for row in geo['artifacts']:
        path = plain_path(row['path'])
        if str(path) in result:
            raise ValueError('duplicate external reference path')
        raw = checked(path, row['sha256'])
        if len(raw) != row['bytes']:
            raise ValueError('GEO source delivery size differs')
        result[str(path)] = row['sha256']
    delta = json.loads(checked(GEO_DELTAS, GEO_DELTAS_SHA256))
    if (delta['message_id'] != 'ENG-R11-GEO-CLOSURE-2026-09-11/owner-decisions-integrated'
            or delta['revision'] != 1 or delta['predecessor']['sha256'] != GEO_CONTRACT_SHA256):
        raise ValueError('exact GEO resolving delta required')
    for row in delta['artifacts']+delta['source_returns']:
        path = plain_path(row['path']); raw = checked(path, row['sha256'])
        if len(raw) != row['bytes'] or str(path) in result:
            raise ValueError('GEO delta artifact size/uniqueness differs')
        result[str(path)] = row['sha256']
        if 'evidence_path' in row:
            path = plain_path(row['evidence_path']); raw = checked(path, row['evidence_sha256'])
            if len(raw) != row['evidence_bytes'] or str(path) in result:
                raise ValueError('GEO evidence artifact size/uniqueness differs')
            result[str(path)] = row['evidence_sha256']
    return result


def source_identity(parent):
    record = retained_record()
    if parent.verify() != PARENT_SOURCE_SHA256 or parent.identity != record['source_identity']:
        raise ValueError('parent execution identity changed')
    identity = {'schema': 'diadem.seasonal-consequences-binding.r11',
        'r11_sources': source_snapshot(), 'extra_executable_sources': extra_sources(),
        'external_reference_sources': external_sources(),
        'retained_source_identity': parent.identity,
        'retained_seal': {'path': str(PARENT_SEAL), 'sha256': PARENT_SEAL_SHA256},
        'runtime': parent.identity['runtime']}
    return identity, sha(encoded(identity))
