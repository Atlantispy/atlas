"""Reuse one explicitly reviewed historical reader pass, without replaying it.

The public issuer has ONE fixed historical review profile. It accepts no caller
PASS flags, replacement source pins, old permits or self-hashed recovery bundle.
Every pinned evidence/source/input byte and the ENTIRE original database must
still match. Admission always reads the immutable ORIGINAL, not its successor
copy. Every original snapshot manifest is authenticated, preserving the store as a
conservative superset of the historical dependency closure. Full database byte
equality authenticates every original chunk without inflating every array again.
Only the required original source audit is decoded into a retained typed object.

This issues historical evidence only. It never accepts a new runtime, rewrites
the FAILED producer, runs a solver, opens a workflow, or authorises continuation.
RuntimeCompatibilityAdmission remains separate. Public use requires the existing
actual Windows-job guard (at most 12 GiB RSS, at least 1 GiB free) and strict
current ExecutionContext. Tests exercise the same core with a deliberately tiny
fixture review profile; that profile is not an option on the public API.
H itself is named explicitly by the caller (historical_root); importing this module
locates nothing, so a composed or folded copy imports with no historical tree.
"""
from contextlib import contextmanager
from collections import OrderedDict
from dataclasses import asdict, dataclass
from hashlib import sha256
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import stat
import sqlite3
import sys
import threading
import types


HERE = Path(__file__).resolve().parent
HISTORICAL_RELATIVE = 'fidelity-integration-20261005/heat-repair-20261007'
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()
MAX_EVIDENCE = 16 << 20
MAX_CAPSULE = 8 << 20
MAX_DATABASE = 4 << 30
MAX_SOURCES = 4096
MAX_AUDIT = 128 << 20
# The live fence binds the reviewed successor guard (resource_guard_patch output);
# the historical r3 guard stays bound by its own pinned receipts and evidence.
GUARD_PIN = '9a2d7e8bcafe725ea861ebd455014fd50e25d152cb38cc709c3dba3347c42772'
HISTORICAL_GUARD_PIN = '2d23f4bbc3b31b5aad3d68ef6e9b1a9800042fc75b12475b51dff468492ad796'
JOB_PIN = '56f66b8826b148a31b85d490c75766422eb210fdfb35c665c449d2e73788f0b4'
DIAGNOSTICS_PIN = 'c0430517414e7b8aa2bc3a7a9e82143be8351bd0a03f3fd08daa993b64e5ee72'
_READONLY = object()
_SUCCESSOR_READONLY = object()


class HistoricalAdmissionRefused(ValueError):
    pass


def historical_root(explicit):
    """The one reviewed historical tree H, named explicitly by the caller.

    No parent is searched: the caller (the prepared restart profile's historical_root)
    names H. It must be an absolute, existing directory reached through no link or
    reparse point (one name for one tree) whose final parts are HISTORICAL_RELATIVE.
    Evidence identities are root-relative content pins, so none changes.
    """
    _require(isinstance(explicit, (str, Path)) and Path(explicit).is_absolute(),
             'explicit absolute historical root required')
    path = Path(explicit)
    _require(path.is_dir(), 'historical root must be an existing directory')
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise HistoricalAdmissionRefused('linked/reparsed historical root refused')
    relative = tuple(part.casefold() for part in Path(HISTORICAL_RELATIVE).parts)
    _require(len(path.parts) > len(relative) and
             tuple(part.casefold() for part in path.parts[-len(relative):]) == relative,
             'historical root must be the reviewed tree '+HISTORICAL_RELATIVE)
    return path.resolve()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise HistoricalAdmissionRefused('exact lowercase SHA-256 required')
    return value


def _require(test, message):
    if not test:
        raise HistoricalAdmissionRefused(message)


@dataclass(frozen=True)
class _Review:
    metadata_sources: tuple
    evidence: tuple
    database_name: str
    database_sha256: str


_REVIEWED_ORIGINAL = _Review(
    metadata_sources=(
        ('private_heat_reader_memory_r3', 'cfec1f1ea62e3bf0fc2e3d1d9d9ca7d7be408fa1949e571baaf443dc4a324155'),
        ('private_heat_recovery_consumer_r4', 'f78b73eb28b172dbb82f357d1373f08434707a6b1bc885d2062d7cfdec219485'),
        ('private_heat_recovery_admission_r1', '8da3151edd7e624b2453d2c170db93371d9694c51e1d65e212d1100aff9fbe36')),
    evidence=(
        ('heat-original-connected-20261013-r9.json', 'ca35700a8106d46eb67c876cd15fb5bf86d6abee7480cc94a23acbef68bb4f0d'),
        ('heat-original-connected-20261013-r9.guard.json', 'c60db8c1d74c4ec48bf65d7e65e277aa4c2871f71b1fb2419b8a2b8dd85584eb'),
        ('reader-memory-20261013-r3.json', 'd85b8d4fd5f90326feb6bc393b559b80612ca9420da4ba8bf2649458a7f57904'),
        ('reader-memory-20261013-r3.guard.json', '0aeb93a08365675ded06e542dc5c00dc315725bf1f2abf8bc4828a6ec17d42a3'),
        ('reader-memory-preparation-r3.json', 'a4cfde7c46070b0fd0dd79cf6b2dcf13d7c4ea2a358e9ba7726ff11eaeb2973a')),
    database_name='heat-original-connected-20261013-r9.artifacts/native-joined.sqlite',
    database_sha256='3f70c26de17535a96b7ddd494aee72900decee272ae0f88edab3a42af1548899')


def _ordinary(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise HistoricalAdmissionRefused('linked/reparsed historical path refused')
    _require(path.is_file(), 'ordinary historical file required')
    return path.resolve()


def _inside(root, name):
    path = root / name
    _require(not Path(name).is_absolute() and '..' not in Path(name).parts,
             'relative contained historical source required')
    path = _ordinary(path)
    _require(path.is_relative_to(root), 'historical source escaped its root')
    return path


def _hash_file(path, limit, check):
    path = _ordinary(path)
    info = path.stat()
    _require(info.st_size <= limit, 'historical file exceeds bounded input size')
    result, count = sha256(), 0
    with path.open('rb') as stream:
        identity = os.fstat(stream.fileno())
        _require((identity.st_dev, identity.st_ino, identity.st_size) ==
                 (info.st_dev, info.st_ino, info.st_size), 'file replaced before read')
        while block := stream.read(1 << 20):
            check()
            count += len(block)
            _require(count <= limit, 'historical file grew beyond input bound')
            result.update(block)
        after = os.fstat(stream.fileno())
    final = path.stat()
    identity_tuple = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    _require(count == info.st_size and identity_tuple(info) == identity_tuple(after) ==
             identity_tuple(final), 'historical file changed during read')
    return result.hexdigest()


def _json_file(path, pin, check):
    _require(_hash_file(path, MAX_EVIDENCE, check) == pin, 'pinned evidence changed: '+str(path))
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_EVIDENCE+1)
    _require(len(raw) <= MAX_EVIDENCE and sha256(raw).hexdigest() == pin, 'evidence replaced after hash')
    def pairs(rows):
        result = {}
        for key, value in rows:
            _require(key not in result, 'duplicate historical JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(HistoricalAdmissionRefused('nonfinite JSON')))


def _loaded_source_fence(module, pin, check):
    """A loaded guard cannot acquire its source identity from changed code."""
    path = _ordinary(module.__file__)
    _require(_hash_file(path, MAX_EVIDENCE, check) == pin, 'loaded guard source bytes differ')
    with path.open('rb') as stream:
        raw = stream.read(MAX_EVIDENCE+1)
    _require(len(raw) <= MAX_EVIDENCE and sha256(raw).hexdigest() == pin,
             'loaded guard source changed before compilation')
    codes = {}
    def collect(code):
        codes[code.co_qualname] = code
        for value in code.co_consts:
            if isinstance(value, types.CodeType):
                collect(value)
    collect(compile(raw, str(module.__file__), 'exec', dont_inherit=True))
    for name, code in codes.items():
        if '<' in name or not code.co_flags & inspect.CO_NEWLOCALS:
            continue  # module/class bodies and function-local closures
        value = module
        for part in name.split('.'):
            value = inspect.getattr_static(value, part, None)
        if isinstance(value, (staticmethod, classmethod)):
            value = value.__func__
        if isinstance(value, property):
            value = value.fget
        _require(inspect.isfunction(value) and value.__code__ == code,
                 'loaded guarded function differs from pinned source: '+name)


@contextmanager
def _metadata_validator(root, review, check):
    _require(not any(name in sys.modules for name, _ in review.metadata_sources),
             'historical metadata module names occupied; fresh process required')
    modules = {}
    try:
        for name, pin in review.metadata_sources:
            path = _inside(root, name+'.py')
            _require(_hash_file(path, MAX_EVIDENCE, check) == pin, 'metadata validator source changed')
            with path.open('rb') as stream:
                raw = stream.read(MAX_EVIDENCE+1)
            _require(sha256(raw).hexdigest() == pin, 'metadata validator source replaced')
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            modules[name] = module
            exec(compile(raw, str(path), 'exec'), module.__dict__)
        yield modules['private_heat_recovery_admission_r1']
        for name, pin in review.metadata_sources:
            _require(sys.modules.get(name) is modules[name] and
                     _hash_file(_inside(root, name+'.py'), MAX_EVIDENCE, check) == pin,
                     'historical metadata source/module changed')
    finally:
        for name, module in modules.items():
            if sys.modules.get(name) is module:
                del sys.modules[name]


def _authenticate(root, review, check, budget):
    """Exact original validate_records plus its previously omitted full closure."""
    pins = dict(review.evidence)
    records = {name: _json_file(_inside(root, name), pin, check) for name, pin in review.evidence}
    producer = records['heat-original-connected-20261013-r9.json']
    reader = records['reader-memory-20261013-r3.json']
    preparation = records['reader-memory-preparation-r3.json']
    with _metadata_validator(root, review, check) as validator:
        _require(validator.PINS == pins and validator.DATABASE_SHA == review.database_sha256,
                 'reviewed evidence profile differs from actual validator')
        expected = validator.validate_records(producer,
            records['heat-original-connected-20261013-r9.guard.json'], reader,
            records['reader-memory-20261013-r3.guard.json'], os.getpid())
    original = _inside(root, review.database_name)
    closed = lambda path: not any(Path(str(path)+suffix).exists() for suffix in ('-wal', '-journal'))
    _require(closed(original), 'original checkpoint must be closed without WAL/journal')
    producer_manifest = preparation['producer_manifest']
    preparation_path = _inside(root, producer_manifest['path'])
    preparation_size = preparation_path.stat().st_size
    _require(preparation_size <= MAX_EVIDENCE, 'producer preparation exceeds bound')
    preparation_scratch = _Allocation(budget, 12*preparation_size+65536)
    producer_preparation = _json_file(preparation_path,
                                     producer_manifest['sha256'], check)
    _require(producer['preparation_manifest_sha256'] == producer_manifest['sha256'],
             'original producer preparation differs')
    closure = {}
    def add(name, pin):
        _sha(pin)
        _require(name not in closure or closure[name] == pin, 'historical source pins conflict')
        closure[name] = pin
        _require(len(closure) <= MAX_SOURCES, 'source closure exceeds bound')
    for mapping in (producer['participating_imported_helper_sources'], preparation['files'],
                    producer_preparation['files'], reader['participating_imported_helper_sources']):
        _require(type(mapping) is dict and mapping, 'complete participating source closure required')
        for name, pin in mapping.items():
            add(name, pin)
    native = producer['native_source']['clone_source_hashes']
    _require(type(native) is dict and native and digest(native) == producer['native_source_digest'],
             'complete original native source digest differs')
    native_root = root/'native-composed-r7/tectonics/src'
    actual_names = set()
    for path in (native_root/'atlas_tectonics').rglob('*.py'):
        check()
        actual_names.add(_ordinary(path).relative_to(native_root).as_posix())
        _require(len(actual_names) <= MAX_SOURCES, 'native source membership exceeds bound')
    _require(actual_names == set(native), 'original native source membership changed')
    for name, pin in native.items():
        add('native-composed-r7/tectonics/src/'+name, pin)
    bindings = {_inside(root, name): pin for name, pin in closure.items()}
    bindings.update({_inside(root, name): pin for name, pin in review.evidence})
    bindings.update({_inside(root, name+'.py'): pin for name, pin in review.metadata_sources})
    bindings[_inside(root, producer_manifest['path'])] = producer_manifest['sha256']
    inputs = reader['inputs']
    _require(type(inputs) is dict and str(original) in inputs and
             inputs[str(original)] == review.database_sha256, 'reader did not bind this entire original database')
    for name, pin in inputs.items():
        path = _ordinary(name)
        _require(path.is_relative_to(root), 'recorded input outside historical root')
        _sha(pin)
        _require(path not in bindings or bindings[path] == pin, 'historical input/source pins conflict')
        bindings[path] = pin
    for path, pin in bindings.items():
        _require(_hash_file(path, MAX_DATABASE if path == original else MAX_EVIDENCE, check) == pin,
                 'historical source/input changed: '+str(path))
    _ = preparation_scratch
    return expected, producer, reader, records, bindings, original, producer_manifest['sha256']


class _Allocation:
    def __init__(self, budget, size):
        self.guard = None
        guard = budget.reserve(size, category='historical-admission-retained')
        guard.__enter__()
        self.guard = guard

    def __del__(self):
        guard = getattr(self, 'guard', None)
        if guard is not None:
            self.guard = None
            guard.__exit__(None, None, None)


class _OwnedBytes(bytes):
    def __new__(cls, value, owner):
        result = super().__new__(cls, value)
        object.__setattr__(result, '_owner', owner)
        return result

    def __setattr__(self, name, value):
        raise HistoricalAdmissionRefused('historical retained bytes are immutable')


def _open_readonly(path, limits, compression, budget, *, marker=_READONLY):
    """Native ArrayStore read side, never its write-capable constructor.

    This deliberately narrow additive adapter preserves the native schema,
    settings, codec, limits, workspaces, caches and chunk validation. It opens
    SQLite mode=ro AND query_only. No workflow or scientific acceptance occurs.
    Only the _READONLY marker can be admitted; a successor view never can.
    """
    from atlas_tectonics import storage as S
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.reuse import release_boundary
    release_boundary()
    _require(type(limits) is S.StoreLimits and type(compression) is S.Compression and
             type(budget) is WorkBudget, 'typed native readonly storage configuration required')
    _require(marker is _READONLY or marker is _SUCCESSOR_READONLY, 'known readonly role required')
    path = _ordinary(path)
    _require(not any(Path(str(path)+s).exists() for s in ('-wal', '-journal', '-shm')),
             'historical readonly input must have no SQLite sidecars')
    result = object.__new__(S.ArrayStore)
    result.path, result.limits, result.compression = path, limits, compression
    result._blosc = None
    if compression.codec == 'zstd':
        import blosc2
        result._blosc = blosc2
    result._lock, result._preparing = threading.RLock(), threading.Lock()
    result._cache, result._verified = OrderedDict(), OrderedDict()
    result._cached_bytes = 0
    result._cache_version, result._cache_changes, result._retained = None, -1, None
    result._stats = dict(payload_reads=0, decoded_hits=0, verified_hits=0, encodes=0,
        staged_bytes=0, prepare_seconds=0., writer_seconds=0., insert_batches=0, peak_prepared_bytes=0)
    result._budget = budget
    result._resident_bytes = (limits.decoded_cache_bytes + limits.sqlite_cache_bytes +
                             1024*limits.verified_cache_entries + 16384)
    result._resident_reservation = budget.reserve(result._resident_bytes, category='store-retained')
    result._resident_reservation.__enter__()
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=5,
                                     isolation_level=None, check_same_thread=False)
        result._db = connection
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, S._MAX_SQL)
        ticks = [0]
        def bounded():
            ticks[0] += 1
            return ticks[0] > S._OPEN_TICKS
        connection.set_progress_handler(bounded, S._TICK_OPS)
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute(f'PRAGMA cache_size=-{max(1, limits.sqlite_cache_bytes // 1024)}')
        connection.execute('BEGIN')
        _require(set(connection.execute('SELECT type,name,tbl_name,sql FROM sqlite_master')) ==
                 S._SCHEMA_OBJECTS, 'original readonly database schema differs')
        row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
        _require(row == (S._json({'schema': S._SCHEMA, 'chunk_bytes': limits.chunk_bytes}),),
                 'original readonly database settings differ')
        page = connection.execute('PRAGMA page_size').fetchone()[0]
        count = connection.execute('PRAGMA page_count').fetchone()[0]
        _require(count*page <= limits.max_store_bytes, 'readonly original exceeds store byte bound')
        connection.execute('ROLLBACK')
        connection.set_progress_handler(None, 0)
        result._closed = False
        result._historical_readonly = marker
        return result
    except BaseException:
        if connection is not None:
            connection.close()
        result._resident_reservation.__exit__(None, None, None)
        raise


def open_original_readonly(*, root, limits, compression, budget):
    """Open the one reviewed ORIGINAL only; use as an ordinary store context.

    This grants no admission. Limits/compression must subsequently match the
    authenticated original preparation when admit_historical_endpoint is used.
    ``root`` names H explicitly (historical_root).
    """
    return _open_readonly(_inside(historical_root(root), _REVIEWED_ORIGINAL.database_name),
                          limits, compression, budget)


def open_successor_readonly(path, *, expected_sha256, limits, compression, budget, check=None):
    """Independent reader's view of a closed successor copy; grants no admission.

    The whole closed file must equal expected_sha256 BEFORE SQLite sees it and
    keep that identity through the open, so the reader inspects exactly the
    authenticated bytes. mode=ro plus query_only: no write, journal or sidecar.
    Its marker is never admissible, and the historical tree (including the
    reviewed ORIGINAL) is refused wherever it lives, by its reviewed relative name:
    use open_original_readonly plus admission.
    ``check`` is the caller's guard/cancellation boundary during hashing.
    """
    from atlas_tectonics import storage as S
    from atlas_tectonics.resources import WorkBudget
    check = (lambda: None) if check is None else check
    _sha(expected_sha256)
    _require(type(limits) is S.StoreLimits and type(compression) is S.Compression and
             type(budget) is WorkBudget, 'typed native readonly storage configuration required')
    path = _ordinary(path)
    relative = tuple(part.casefold() for part in Path(HISTORICAL_RELATIVE).parts)
    parts = tuple(part.casefold() for part in path.parts)
    _require(not any(parts[i:i+len(relative)] == relative for i in range(len(parts))),
             'successor reader refuses the historical tree')
    _require(not any(Path(str(path)+s).exists() for s in ('-wal', '-journal', '-shm')),
             'successor readonly input must have no SQLite sidecars')
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    before = path.stat()
    _require(_hash_file(path, limits.max_store_bytes, check) == expected_sha256,
             'successor checkpoint bytes differ from the expected hash')
    store = _open_readonly(path, limits, compression, budget, marker=_SUCCESSOR_READONLY)
    try:
        _require(identity(path.stat()) == identity(before), 'successor checkpoint changed while opening')
        return store
    except BaseException:
        store.close()
        raise


def _array_bytes(store, description, owner, budget, check, *, byte_type=_OwnedBytes):
    """One native validated array; caller holds the pinned native read scope."""
    from atlas_tectonics.storage import _dtype
    dtype = _dtype(description['dtype'])
    count = math.prod(description['shape'])
    total = count*dtype.itemsize
    _require(total <= store.limits.max_array_bytes, 'selected array exceeds original bound')
    scratch = _Allocation(budget, total + store.limits.chunk_bytes + 4096)
    raw, chunk = bytearray(total), None
    try:
        width, offset = store.limits.chunk_bytes // dtype.itemsize, 0
        for index, key in enumerate(description['chunks']):
            check()
            chunk = store._chunk(key, expected_dtype=dtype.str,
                                 expected_count=min(width, count-index*width))
            _require(offset+len(chunk) <= total, 'selected array exceeded its exact shape')
            raw[offset:offset+len(chunk)] = chunk
            offset += len(chunk)
            chunk = None
        _require(offset == total, 'selected array chunk coverage is incomplete')
        return byte_type(raw, owner)
    finally:
        raw = chunk = None
        # A held error frame retains scratch until no borrowed buffer survives.
        _ = scratch


def read_selected_arrays(store, key, names, *, admission, budget, check):
    """Read only named authenticated original arrays, also from a successor copy.

    Each immutable ndarray buffer retains its own allocation AND admission.
    Every chunk is checked by the native decoder, and the complete containing
    manifest must still equal the admission's original manifest. Additional
    successor snapshots are allowed; they convey no historical authority.
    ``check`` must be the caller's existing guard/cancellation boundary.
    """
    import numpy as np
    from atlas_tectonics.storage import ArrayStore, _dtype
    from atlas_tectonics.resources import WorkBudget
    import workflow_transfer as W
    import native_transfer as N
    _require(type(store) is ArrayStore and type(budget) is WorkBudget and store._budget is budget and
             type(admission) is W.HistoricalEndpointAdmission, 'typed admission/store/shared budget required')
    _require(type(names) in (tuple, list) and 0 < len(names) <= 1024 and
             all(type(name) is str for name in names) and len(set(names)) == len(names),
             'bounded unique selected array names required')
    scratch = _Allocation(budget, 16*len(admission._record)+8*len(admission._binding)+(1 << 16))
    capsule, binding = admission.record(), admission.binding()
    _require(binding['capsule_sha256'] == digest(capsule), 'historical capsule binding changed')
    admitted = capsule['snapshot_manifests'].get(key)
    _require(admitted is not None and set(names) <= set(admitted['arrays']),
             'selected array absent from authenticated original inventory')
    size = sum(math.prod(admitted['arrays'][name]['shape'])*_dtype(admitted['arrays'][name]['dtype']).itemsize
               for name in names)
    owner = N._Allocation(budget, size+512*len(names)+4096, category='historical-selected-arrays-retained')
    arrays = {}
    with store._read_scope(budget=budget):
        token = store.change_token()
        _require(store._manifest(key) == admitted, 'preserved original manifest differs')
        for name in names:
            description = admitted['arrays'][name]
            # Use the same immutable record-byte holder as native transfer, so
            # even an escaped ndarray view owns admission plus its reservation.
            owned = _array_bytes(store, description, (owner, admission), budget, check,
                                 byte_type=N._RecordBytes)
            arrays[name] = np.frombuffer(owned, dtype=_dtype(description['dtype'])).reshape(description['shape'])
            owned = None
        check()
        _require(store.change_token() == token and store._manifest(key) == admitted,
                 'preserved original store changed during selected read')
    _ = scratch
    return arrays


def _audit(store, head, expected, owner, budget, check):
    from atlas_tectonics.regional_execution import RegionalMechanicalSnapshot
    rows = expected['array_records']['source_audit']
    total_bytes = sum(math.prod(row['shape'])*8 for row in rows)
    _require(total_bytes <= MAX_AUDIT, 'source audit exceeds retained byte bound')
    scratch = _Allocation(budget, len(canonical(head['source_audit']))*8 + 65536)
    manifest = store._manifest(head['key'])
    names = {name.removeprefix('source-audit:') for name in manifest['arrays'] if name.startswith('source-audit:')}
    _require(names == {row['name'] for row in rows}, 'complete original audit array set differs')
    fields, identities = [], {}
    raw = None
    try:
        for row in sorted(rows, key=lambda row: row['name']):
            name = 'source-audit:'+row['name']
            description = manifest['arrays'][name]
            _require(sys.byteorder == 'little' and row['dtype'] in ('float64', '<f8') and
                     description['dtype'] == '<f8' and description['shape'] == row['shape'],
                     'source-audit exact dtype/shape differs')
            raw = _array_bytes(store, description, owner, budget, check)
            _require(len(raw) == math.prod(row['shape'])*8 and sha256(raw).hexdigest() == row['sha256'],
                     'source-audit exact bytes differ')
            fields.append((row['name'], tuple(row['shape']), raw))
            identities[row['name']] = dict(shape=row['shape'], sha256=row['sha256'])
            raw = None
        identity = digest(dict(metadata=head['source_audit'], arrays=identities))
        _require(identity == expected['source_audit_id'] == head['advance']['source_audit_id'],
                 'original source-audit snapshot identity differs')
        # Exactly the native immutable snapshot representation, without new
        # metadata/plan IDs or a constructor's extra all-array copy. Whole byte
        # identities were authenticated above; retained buffers own their budget.
        result = object.__new__(RegionalMechanicalSnapshot)
        object.__setattr__(result, '_metadata', _OwnedBytes(canonical(head['source_audit']), owner))
        object.__setattr__(result, '_fields', tuple(fields))
        object.__setattr__(result, 'result_id', identity)
        return result
    finally:
        raw = None
        # Held exceptions retain this frame and scratch until all borrowed work
        # is released. Normal return drops scratch; output owns exact bytes.
        _ = scratch


def _admit(store, *, root, review, budget, check):
    """Shared implementation; fixture profiles are deliberately private."""
    from atlas_tectonics.storage import ArrayStore
    from atlas_tectonics.resources import WorkBudget
    import workflow_transfer as W
    _require(type(store) is ArrayStore and type(budget) is WorkBudget and store._budget is budget,
             'actual ArrayStore on the shared budget required')
    _require(not store._db.in_transaction, 'unowned active transaction refused')
    root = Path(root).resolve()
    original = _inside(root, review.database_name)
    _require(_ordinary(store.path) == original and getattr(store, '_historical_readonly', None) is _READONLY
             and store._db.execute('PRAGMA query_only').fetchone() == (1,),
             'admission requires the unchanged ORIGINAL readonly store, never a working copy')
    # Size metadata before decoding; schema ceilings are limits, not allocated
    # demand. SQLite's own existing read workspace remains unchanged.
    with store._read_scope(budget=budget):
        catalogue_bytes, largest_manifest, count = store._db.execute(
            'SELECT COALESCE(sum(length(body)),0),COALESCE(max(length(body)),0),count(*) FROM snapshots').fetchone()
    _require(catalogue_bytes <= MAX_CAPSULE and largest_manifest <= store.limits.max_manifest_bytes
             and count <= 4096, 'actual catalogue exceeds bounded capsule')
    evidence_bytes = sum(_inside(root, name).stat().st_size for name, _ in review.evidence)
    metadata_bytes = sum(_inside(root, name+'.py').stat().st_size for name, _ in review.metadata_sources)
    _require(evidence_bytes <= len(review.evidence)*MAX_EVIDENCE, 'evidence exceeds bound')
    scratch = _Allocation(budget, 12*evidence_bytes + 16*catalogue_bytes + 12*metadata_bytes + (1 << 20))
    expected = producer = reader = bindings = manifests = capsule = None
    try:
        check()
        expected, producer, reader, _records, bindings, original, producer_manifest = _authenticate(root, review, check, budget)
        _require(asdict(store.limits) == expected['store_limits'] and
                 asdict(store.compression) == expected['store_compression'],
                 'original store limits/compression differ from authenticated preparation')
        with store._read_scope(budget=budget):
            live_token = store.change_token()
            chain = [store.metadata(expected['root_key']), store.metadata(expected['head_key'])]
            _require(chain[0] == expected['root_metadata'], 'historical root metadata differs')
            W.validate_historical_chain(chain)
            head = chain[-1]
            _require(head['key'] == expected['head_key'] and head['workflow_id'] == expected['workflow_id'],
                     'historical endpoint identity differs')
            for field, value in (('collar_result_id', head['state']['result_id']),
                    ('native_result_id', head['native_state_id']), ('exterior_state_id', head['exterior_state']['state_id']),
                    ('source_audit_id', head['advance']['source_audit_id']),
                    ('joined_heat_id', head['exterior_advance']['joined_heat_id'])):
                _require(expected[field] == value, 'historical endpoint field identity differs')
            manifests, size = {}, 0
            inventory = dict(scope='complete-source-store', snapshots=0, arrays=0, chunk_references=0, raw_bytes=0)
            inventory_hash = sha256()
            for (key,) in store._db.execute('SELECT id FROM snapshots ORDER BY id'):
                check()
                manifest = store._manifest(key)
                size += len(canonical(manifest))
                _require(size <= MAX_CAPSULE and inventory['snapshots'] < 4096, 'complete catalogue exceeds bounded capsule')
                for name, desc in manifest['arrays'].items():
                    inventory['arrays'] += 1
                    inventory['chunk_references'] += len(desc['chunks'])
                    _require(inventory['arrays'] <= 65536 and inventory['chunk_references'] <= 1000000,
                             'complete inventory exceeds bounded counts')
                    # The pinned whole-file hash includes every chunk payload,
                    # descriptor, index and manifest. The original successful
                    # reader already checked the scientific closure. Decode no
                    # physical field merely to reconfirm those identical bytes.
                    from atlas_tectonics.storage import _dtype
                    inventory['raw_bytes'] += math.prod(desc['shape'])*_dtype(desc['dtype']).itemsize
                manifests[key] = manifest
                inventory['snapshots'] += 1
                inventory_hash.update(key.encode()); inventory_hash.update(bytes.fromhex(digest(manifest)))
            inventory['manifest_inventory_sha256'] = inventory_hash.hexdigest()
            inventory['payload_validation'] = 'exact-full-database-equality-with-complete-original-reader'
            _require(inventory['snapshots'] == store.statistics()['snapshots'], 'complete snapshot inventory differs')
            # Neither receipt saved the old connection token, only the checked
            # unchanged-token condition. Do NOT invent it or let a new process's
            # connection token change historical IDs. This explicitly tagged
            # content token binds exact authenticated evidence, not SQLite state.
            token = dict(schema='atlas.historical-store-content-token.v1',
                database_sha256=review.database_sha256,
                reader_receipt_sha256=dict(review.evidence)['reader-memory-20261013-r3.json'])
            source = dict(workflow_id=expected['workflow_id'], root_key=expected['root_key'],
                head_key=expected['head_key'], sequence=1, time_s=head['state']['fields']['time_s'],
                store_token=token, database_sha256=review.database_sha256)
            helper_sources = {Path(__file__).name: _SELF_SHA,
                              Path(W.__file__).name: _hash_file(W.__file__, MAX_EVIDENCE, check)}
            capsule = dict(schema='atlas.restart-historical-endpoint.v1', source=source,
                chain_metadata=chain, snapshot_manifests=manifests, inventory=inventory,
                validation_receipt=dict(sha256=dict(review.evidence)['reader-memory-20261013-r3.json'], record=reader),
                producer=dict(expected['execution_provenance'], source_manifest_sha256=producer_manifest,
                    native_source_digest=producer['native_source_digest'], original_status=producer['status'],
                    original_finalisation_not_certified=True, array_records=expected['array_records'],
                    preparation_ids=expected['preparation_ids'],
                    participating_source_pins=producer['participating_imported_helper_sources']),
                adapter=dict(source_sha256=_SELF_SHA, source_manifest_sha256=digest(helper_sources)))
            raw = canonical(capsule)
            _require(len(raw) <= MAX_CAPSULE, 'complete historical capsule exceeds bound')
            binding = dict(schema='atlas.restart-historical-admission.v1', capsule_sha256=sha256(raw).hexdigest(),
                original_database_path=str(original), database_sha256=review.database_sha256,
                source_pins={str(p.relative_to(root)): pin for p, pin in bindings.items() if p != original},
                metadata_source_pins=dict(review.metadata_sources), evidence_pins=dict(review.evidence),
                issuer_sources=helper_sources,
                origin=dict(producer_receipt_sha256=dict(review.evidence)['heat-original-connected-20261013-r9.json'],
                            store_token_sha256=digest(token), endpoint_lineage_sha256=digest(chain)),
                historical_scientific_checks_reused=True, historical_scientific_checks_replayed=False,
                original_producer_status='FAILED', original_finalisation_not_certified=True,
                new_runtime_accepted=False, production_acceptance=False, continuation_authorised=False)
            binding_raw = canonical(binding)
            audit_bytes = sum(math.prod(row['shape'])*8 for row in expected['array_records']['source_audit'])
            _require(audit_bytes <= MAX_AUDIT, 'source audit exceeds retained byte bound')
            owner = _Allocation(budget, len(raw)+len(binding_raw)+audit_bytes+
                len(canonical(head['source_audit']))+len(expected['array_records']['source_audit'])*512+8192)
            audit = _audit(store, head, expected, owner, budget, check)
            # Same pins at exit, including full DB bytes. Tokens are additional
            # race checks only, never substitutes for authenticated file hashes.
            for path, pin in bindings.items():
                _require(_hash_file(path, MAX_DATABASE if path == original else MAX_EVIDENCE, check) == pin,
                         'historical binding changed during admission')
            _require(store.change_token() == live_token, 'original store changed during admission')
            _require(_hash_file(__file__, MAX_EVIDENCE, check) == _SELF_SHA and
                     _hash_file(W.__file__, MAX_EVIDENCE, check) == helper_sources[Path(W.__file__).name],
                     'admission helper source changed')
            check()
            result = object.__new__(W.HistoricalEndpointAdmission)
            object.__setattr__(result, '_record', _OwnedBytes(raw, owner))
            object.__setattr__(result, '_binding', _OwnedBytes(binding_raw, owner))
            object.__setattr__(result, '_source_audit', audit)
            return result
    finally:
        expected = producer = reader = bindings = manifests = capsule = None
        _ = scratch


def guardian_fence(guard, *, budget, check):
    """Exact live successor guardian, its job module and its passive diagnostics.

    Code-level fences on the LOADED modules: the reviewed successor guard
    (GUARD_PIN), the unchanged job (JOB_PIN) and the diagnostics helper
    (DIAGNOSTICS_PIN) bound to that same job module. The original r3 guard bytes
    are refused here; they remain historical evidence only. ``check`` runs only
    after the guard's own type and live check method are established.
    """
    module = sys.modules.get('private_heat_continuation_guard_r3')
    job = sys.modules.get('windows_workload_job')
    _require(module is not None and job is not None and type(guard) is module.ContinuationGuard,
             'actual launch-bound continuation guard required')
    _require(inspect.getattr_static(type(guard), 'check') is module.ContinuationGuard.check and
             'check' not in vars(guard) and not guard.closed and guard.budget is budget,
             'actual live shared-budget guardian check required')
    limits = guard._control['limits']
    _require(0 < limits['rss_bytes'] <= 12 << 30 and limits['free_floor_bytes'] >= 1 << 30,
             '12 GiB ceiling and 1 GiB free-floor safeguards must remain')
    _loaded_source_fence(module, GUARD_PIN, check)
    _loaded_source_fence(job, JOB_PIN, check)
    diagnostics = sys.modules.get('private_heat_resource_diagnostics_r1')
    _require(diagnostics is not None and
             inspect.getattr_static(module, 'RESOURCE_DIAGNOSTICS', None) is diagnostics and
             inspect.getattr_static(diagnostics, 'WJ', None) is job,
             'guardian diagnostics binding replaced')
    _loaded_source_fence(diagnostics, DIAGNOSTICS_PIN, check)
    _require(module.verify_current_membership is job.verify_current_membership,
             'guardian Windows-job membership verifier was replaced')
    context = json.loads(os.environ[module.ENV])
    _require(context['nonce'] == guard.nonce and context['output'] == str(guard.output) and
             job.verify_current_membership(context['job_name']) == guard.identity,
             'current process is not the actual guarded original launch member')
    receipt = guard._sync()
    _require(receipt['status'] == 'RUNNING' and receipt['limits'] == limits,
             'current independent guardian is not running with exact limits')
    return receipt


def admit_historical_endpoint(store, *, root, execution, budget, guard, cancel=None):
    """Usable fixed-profile historical issuer under the existing guarded launch.

    Pass open_original_readonly's already-open ORIGINAL ArrayStore, actual current
    strict ExecutionContext, one shared budget and live ContinuationGuard. No
    fixture/profile/pin override is accepted by this public entry point; ``root``
    only names where the reviewed H lives (historical_root), and its pins stay fixed.
    """
    from atlas_tectonics.reuse import ExecutionContext
    from atlas_tectonics.resources import WorkBudget
    _require(type(execution) is ExecutionContext and type(budget) is WorkBudget and
             budget.max_bytes <= 16 << 30, 'strict execution and existing 16 GiB logical ledger required')
    root = historical_root(root)

    def check():
        if cancel is not None and cancel.is_set():
            from concurrent.futures import CancelledError
            raise CancelledError('historical admission cancelled')
        guard.check(force=True)
    guardian_fence(guard, budget=budget, check=check)
    execution.verify_boundary()
    _require(execution.provenance['execution_mode'] == 'strict', 'strict current recorder required')
    result = _admit(store, root=root, review=_REVIEWED_ORIGINAL,
                    budget=budget, check=check)
    execution.verify_boundary()
    check()
    return result


def derive_historical_plan_graph(actual_current_graph, admission):
    """Reconstruct definitions whose IDs are independently bound by admission.

    This does not mutate saved/current objects or issue runtime compatibility.
    Only the five explicit execution fields and their named graph edges change
    in a separate candidate dictionary. Every resulting native/collar/transport
    identity must match authenticated old evidence. Native heat has no separate
    saved ID: this narrow implementation requires zero padding and exact equality
    to the COMPLETE authenticated nested collar-heat definition, or refuses.
    """
    import native_transfer as N
    import workflow_transfer as W
    _require(type(admission) is W.HistoricalEndpointAdmission,
             'authenticated historical endpoint admission required')
    capsule, binding = admission.record(), admission.binding()
    _require(binding['capsule_sha256'] == digest(capsule), 'historical admission capsule changed')
    N._scientific_graph(actual_current_graph)
    graph = json.loads(canonical(actual_current_graph))
    old_execution = capsule['producer']['execution_identity']
    root = capsule['chain_metadata'][0]
    old_collar = root['collar_plan']
    ids = capsule['producer']['preparation_ids']
    _require(old_collar['padding'] == [[0, 0], [0, 0], [0, 0]],
             'native-heat reconstruction currently requires authenticated zero padding')
    for name in ('native_transport', 'native_heat', 'native', 'collar_transport', 'collar_heat'):
        graph[name]['definition']['execution'] = old_execution
    for name in ('native_transport', 'native_heat', 'collar_transport', 'collar_heat'):
        graph[name]['plan_id'] = N._hash(graph[name]['definition'])
    graph['native']['definition']['transport_plan_id'] = graph['native_transport']['plan_id']
    graph['native']['plan_id'] = N._hash(graph['native']['definition'])
    collar = graph['collar']['definition']
    collar['native_plan_id'] = graph['native']['plan_id']
    collar['transport_plan_id'] = graph['collar_transport']['plan_id']
    collar['heat_plan'] = graph['collar_heat']['definition']
    graph['collar']['plan_id'] = N._hash(collar)
    _require(graph['native']['plan_id'] == ids['native'] == old_collar['native_plan_id'] and
             graph['collar']['plan_id'] == ids['collar'] == N._hash(old_collar) and
             graph['collar_transport']['plan_id'] == old_collar['transport_plan_id'] and
             collar['volume_map_id'] == ids['map'] and canonical(collar) == canonical(old_collar),
             'reconstructed original plan IDs/complete collar definition differ')
    _require(canonical(graph['native_heat']['definition']) == canonical(old_collar['heat_plan']) ==
             canonical(graph['collar_heat']['definition']),
             'native heat lacks an independently authenticated original definition')
    N._scientific_graph(graph)
    return graph
