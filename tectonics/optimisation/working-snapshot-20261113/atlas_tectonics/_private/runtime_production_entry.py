"""Authenticated opt-in packaged production admission; no source-checkout or booking fallback."""
import json
from hashlib import sha256
from pathlib import Path
import stat
import sys

SCHEMA = 'atlas.production-release-entry.v1'
ROUTES = ('fresh-root', 'fresh-interval', 'prepared')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate production metadata key')
        result[key] = value
    return result


def _plain(path, *, directory=False):
    path = Path(path)
    require(path.is_absolute(), 'absolute production path required')
    for part in (path, *path.parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'linked production path refused')
    require(path.is_dir() if directory else path.is_file(), 'ordinary production path required')
    return path.resolve()


def _hex(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _package(sources, *, entry):
    sources.verify()
    root = _plain(sources.native_root, directory=True)
    own = _plain(__file__)
    require(__package__ == 'atlas_tectonics._private'
            and own == root/'atlas_tectonics/_private/runtime_production_entry.py',
            'production policy must be this installed private package member')
    tectonics = root.parent
    resources = tectonics.parent.parent
    require(root.name == 'src' and tectonics.name == 'tectonics' and tectonics.parent.name == 'atlas'
            and resources.name == 'resources', 'installed desktop production layout required')
    marker = _plain(tectonics/'.desktop-runtime.json')
    require(marker.stat().st_size <= 1024
            and json.loads(marker.read_bytes(), object_pairs_hook=_pairs)
                == {'schema':'atlas.desktop-runtime.v1','identity_mode':'release'},
            'qualified Release desktop marker required')
    _plain(resources.parent/'Atlas.exe')
    if entry:
        executable = _plain(sys.executable)
        require(executable.parent == resources/'python'
                and executable.name.lower() in ('python.exe','pythonw.exe'),
                'production requires the packaged interpreter')
        current = _plain(Path(sys.argv[0]).absolute())
        allowed = (root/'atlas_runtime.py',root/'atlas_tectonics/_private/run_fresh_interval.py',
                   root/'atlas_tectonics/_private/run_prepared_restart.py')
        require(current in allowed and '--production-release' in sys.argv,
                'explicit production Release entry required')
        require(not sys.flags.optimize, 'production Release refuses -O/PYTHONOPTIMIZE')
    return tectonics


def _packet(sources, route, gate, *, entry):
    require(route in ROUTES, 'named production route required')
    tectonics = _package(sources, entry=entry)
    manifest = json.loads(sources._manifest, object_pairs_hook=_pairs)
    composition = manifest.get('composition')
    require(type(composition) is dict and _hex(composition.get('composition_sha256')),
            'pinned manifest code-composition SHA-256 required')
    table = _plain(tectonics/'release-peaks.json')
    relative = table.relative_to(sources.workspace).as_posix()
    pin = manifest.get('data_only',{}).get(relative)
    require(_hex(pin) and relative not in manifest.get('files',{}),
            'shipped strict-peak table must be authenticated as manifest DATA')
    require(table.stat().st_size <= 1 << 20, 'shipped strict-peak table exceeds its metadata bound')
    with table.open('rb') as stream:
        raw = stream.read((1 << 20) + 1)
    require(len(raw) <= 1 << 20 and sha256(raw).hexdigest() == pin,
            'shipped strict-peak table source changed')
    measured = json.loads(raw, object_pairs_hook=_pairs)
    decision = gate.release_decision(route, composition['composition_sha256'], measured)
    return {'schema':SCHEMA,'route':route,'source_manifest_sha256':sources.manifest_pin,
            'composition_sha256':composition['composition_sha256'],
            'peak_table':{'path':relative,'sha256':pin},'decision':decision}


def packet(sources, route, gate):
    """Parent source-authenticated decision. Missing authentic current peaks refuses before any output."""
    return _packet(sources,route,gate,entry=True)


def _admit(value, sources, route, gate, memory, *, entry):
    expected = _packet(sources,route,gate,entry=entry)
    require(type(value) is dict and canonical(value) == canonical(expected),
            'production decision differs from the authenticated current source/table/route')
    admitted = gate.release_admit(expected['decision'],memory.available,memory.total)
    return {'production_release':expected,'start_gate':admitted,
            'guard_limits':gate.release_guard_limits(admitted)}


def child_admit(text, sources, route, gate, memory):
    require(type(text) is str, 'production child requires its explicit parent decision')
    return _admit(json.loads(text,object_pairs_hook=_pairs),sources,route,gate,memory,entry=True)


def producer_policy(receipt, *, sources, gate, expected_route):
    """Strict reader authenticates a Release producer's DATA decision and actual recorded machine cap."""
    require(type(receipt) is dict and receipt.get('execution_mode') == 'release',
            'explicit Release producer mode required')
    value = receipt.get('production_release')
    require(type(value) is dict and value.get('schema') == SCHEMA, 'source-bound production packet required')
    memory = receipt.get('memory_at_start')
    require(type(memory) is dict and type(memory.get('available_bytes')) is int
            and type(memory.get('physical_bytes')) is int, 'producer machine-memory observation required')
    class Memory:
        available = memory['available_bytes']
        total = memory['physical_bytes']
    result = _admit(value,sources,expected_route,gate,Memory,entry=False)
    require(receipt.get('start_gate') == result['start_gate']
            and receipt.get('guard_limits') == result['guard_limits'],
            'producer decision or machine-sized guard limits differ')
    proof = receipt.get('source_proof')
    require(type(proof) is dict and proof.get('source_manifest_sha256') == sources.manifest_pin,
            'producer source proof differs from selected manifest')
    return {'execution_mode':'release','guard_limits':result['guard_limits']}
