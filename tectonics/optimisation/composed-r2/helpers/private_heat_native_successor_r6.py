"""Private native-r7, exactly native-r6 plus two reviewed pressure modules.
No checkpoints or scientific parameters are migrated. verify is source-only;
modules selects this exact package before any scientific import.
"""
from concurrent.futures import CancelledError
from hashlib import sha256
import importlib
import json
from pathlib import Path
import stat
import sys

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE/'native-composed-r6'/'tectonics'/'src'
CLONE = HERE/'native-composed-r7'/'tectonics'/'src'
TESTS = HERE/'source'/'tectonics'/'tests'
ORIGINAL_COUNT = 230
ORIGINAL_DIGEST = '6dc8a0f65425004801bf6d590d5bbd21bd6f8c7c59bfda23239854c7c5fd4fa2'
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()
PATCH_PINS = {'atlas_tectonics/integration_spatial_pressure.py': '8bbcdd81cae3f7496ad08fb5ecb0f218b085a97e47584f513ac28fdfde7ca83b', 'atlas_tectonics/integration_differential_pressure.py': '8615d60bd46ccb822b7fa1089d487997f40c110bc7c6865d7e16eaebad6663d2'}

def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Private successor source inspection cancelled')


def _ordinary(path):
    """Reject linked files/directories, including Windows junction ancestors."""
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Private successor cannot use linked paths: '+str(item))


def _read(path, cancel=None):
    _check(cancel)
    _ordinary(path)
    if not path.is_file():
        raise ValueError('Private successor source is not a regular file: '+str(path))
    return path.read_bytes()


def _digest(sources):
    return sha256(json.dumps(sources, sort_keys=True, separators=(',', ':')).encode('utf8')).hexdigest()


def source_hashes(root=CLONE, cancel=None):
    root = Path(root)
    _ordinary(root)
    package = root/'atlas_tectonics'
    _ordinary(package)
    return {path.relative_to(root).as_posix(): sha256(_read(path, cancel)).hexdigest()
            for path in sorted(package.rglob('*.py'))}


def candidate(cancel=None):
    source = {path.relative_to(ORIGINAL).as_posix(): _read(path, cancel)
              for path in sorted((ORIGINAL/'atlas_tectonics').rglob('*.py'))}
    hashes = {name: sha256(raw).hexdigest() for name, raw in source.items()}
    if len(hashes) != ORIGINAL_COUNT or _digest(hashes) != ORIGINAL_DIGEST:
        raise ValueError('Frozen native-r6 base changed; no implicit repinning')
    for name, pin in PATCH_PINS.items():
        raw = _read(HERE/'native-successor-r7-inputs'/Path(name).name, cancel)
        if sha256(raw).hexdigest() != pin:
            raise ValueError('Reviewed pressure input changed: '+name)
        if name not in source:
            raise ValueError('Expected existing pressure module missing: '+name)
        compile(raw, name, 'exec')
        source[name] = raw
    _check(cancel)
    return source


def verify(cancel=None):
    if sha256(_read(Path(__file__), cancel)).hexdigest() != _SELF_SHA:
        raise ValueError('Native-r7 builder changed after import')
    expected = {name: sha256(raw).hexdigest() for name, raw in candidate(cancel).items()}
    actual = source_hashes(cancel=cancel)
    if actual != expected:
        raise ValueError('Native-r7 differs from the reviewed construction')
    return dict(schema='atlas.private.normal-open-successor.r6', production_acceptance=False,
        original_source_count=ORIGINAL_COUNT, original_source_digest=ORIGINAL_DIGEST,
        clone_source_count=len(actual), clone_source_digest=_digest(actual),
        clone_source_hashes=actual, changed_existing_files=sorted(PATCH_PINS), added_files=[],
        entrypoint='atlas_tectonics.integration_regional_workflow.CollarWorkflow.open',
        helper_sources={Path(__file__).name: _SELF_SHA}, pressure_candidate_sources=dict(PATCH_PINS))


def modules(bridge_module='private_heat_joined_consumer_r6'):
    """Select verified r2 before any native/heat import; return fixture modules."""
    verify()
    loaded = sys.modules.get('atlas_tectonics')
    if loaded is not None and not Path(loaded.__file__).resolve().is_relative_to(CLONE):
        raise RuntimeError('Fresh process with private native-composed-r7 selected first required')
    if str(CLONE) not in sys.path:
        sys.path.insert(0, str(CLONE))
    atlas = importlib.import_module('atlas_tectonics')
    if not Path(atlas.__file__).resolve().is_relative_to(CLONE):
        raise RuntimeError('Private successor package was not selected')
    if str(TESTS) not in sys.path:
        sys.path.insert(1, str(TESTS))
    ale = importlib.import_module('test_integration_spatial_ale')
    flow = importlib.import_module('test_i04_spatial_workflow')
    bridge = importlib.import_module(bridge_module)
    workflow = importlib.import_module('atlas_tectonics.integration_regional_workflow').CollarWorkflow
    return ale, flow, bridge, workflow

