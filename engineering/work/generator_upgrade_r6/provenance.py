"""Exact R5 preservation and inherited R4/R3 source identity for R6."""
import hashlib
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
R5_ROOT = TASK/'work/generator_upgrade_r5'
R5_SEAL = TASK/'outputs/generator-upgrade-r5/precision-reference-01/VERIFICATION.json'
R5_SEAL_SHA256 = '3978753d861940c185942e1cdaa3797150dfea376a84e21aa1112a0842f5cbd9'
R5_SOURCE_SHA256 = '3e88374637f098563796ffd768185a3a79c2bd0c411a70c5aaaf36d2624a6628'
R4_SOURCE_SHA256 = 'd17c5bb4bf45c07731ed114baddff0a808e9bb6106e4e864eb5aa998b91e41cf'
MAX_BYTES = 8*1024*1024
MAX_SOURCE_FILES = 128


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def canonical(path):
    return str(Path(path).resolve())


def plain_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute bounded source path required')
    for item in (path,*path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('linked/reparse source refused')
    return path


def checked(path,expected=None):
    path = plain_path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('bounded regular source file required')
    raw = path.read_bytes()
    if len(raw)>MAX_BYTES or (expected is not None and sha(raw)!=expected):
        raise ValueError('source changed; no silent repin: '+str(path))
    return raw


def source_snapshot(root):
    root = plain_path(root)
    result = {}
    for path in sorted(root.rglob('*')):
        plain_path(path)  # Directories are checked BEFORE suffix/cache filtering.
        if '__pycache__' in path.parts:
            continue
        if path.is_file() and path.suffix in ('.py','.json','.md'):
            result[str(path)] = sha(checked(path))
    if not result or len(result)>MAX_SOURCE_FILES:
        raise ValueError('bounded nonempty successor source inventory required')
    return result


def retained_record():
    record = json.loads(checked(R5_SEAL,R5_SEAL_SHA256))
    identity = record.get('source_identity')
    if (record.get('status')!='BOUNDED_DIAGNOSTIC_SUCCESSOR_VERIFIED'
            or record.get('source_sha256')!=R5_SOURCE_SHA256
            or sha(encoded(identity))!=R5_SOURCE_SHA256
            or record.get('source_snapshot')!=identity['r5_sources']
            or len(identity['r5_sources'])!=9
            or source_snapshot(R5_ROOT)!=identity['r5_sources']):
        raise ValueError('retained R5 seal/source identity differs')
    prior = identity['retained_r4_seal']
    r4 = json.loads(checked(prior['path'],prior['sha256']))
    if (prior['source_sha256']!=R4_SOURCE_SHA256 or r4['source_sha256']!=R4_SOURCE_SHA256
            or r4['source_identity']!=identity['retained_source_identity']
            or sha(encoded(r4['source_identity']))!=R4_SOURCE_SHA256):
        raise ValueError('inherited R4 seal/source identity differs')
    return record


def source_identity(r6_sources,current_r4,r4_digest):
    record = retained_record()
    if (current_r4!=record['source_identity']['retained_source_identity'] or r4_digest!=R4_SOURCE_SHA256):
        raise ValueError('inherited live R4/R3 sources differ from exact R5 preservation seal')
    identity = {'schema':'diadem.isolated-strict-solver-binding.r6','r6_sources':r6_sources,
        'retained_r5_seal':{'path':str(R5_SEAL),'sha256':R5_SEAL_SHA256,'source_sha256':R5_SOURCE_SHA256},
        'retained_source_identity':record['source_identity'],
        'dependency_binding':{'scientific_replacement':'R3 pipeline .soil_water -> exact R6 solver and explicit local numerical helpers',
            'R4_pipeline':'unchanged source -> private unchanged R3 pipeline',
            'other_dependencies':'fresh private copies of exact preserved sources; no global patch/source rewrite'},
        'runtime':current_r4['runtime']}
    return identity,sha(encoded(identity))
