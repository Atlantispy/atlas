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
from contextlib import contextmanager; import atlas_tectonics._identity as _atlas_identity
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import threading

from atlas_shared.errors import AtlasError
from atlas_tectonics.integration.resources import _retained_charge, _release_retained_charge
from atlas_tectonics.integration.resources import json_sha256 as digest
from atlas_tectonics.integration.resources import canonical_json as canonical


HERE = Path(__file__).resolve().parent
MAX_EVIDENCE = 16 << 20
MAX_SOURCES = 4096
_READONLY = object()
_SUCCESSOR_READONLY = object()


class HistoricalAdmissionRefused(ValueError, AtlasError):
    pass


def historical_root(explicit, *, historical_inputs=None):
    """The explicitly selected current-workspace historical tree, with no discovery."""
    inputs = _historical_inputs(historical_inputs)
    try:
        return inputs.historical_root(explicit)
    except _historical_inputs_api().HistoricalInputsRefused as error:
        raise HistoricalAdmissionRefused(str(error)) from error


def _sha(value):
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




def _ordinary(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        item.lstat()
    return path.resolve()


def _inside(root, name):
    path = root / name
    path = _ordinary(path)
    return path


def _json_file(path, pin, check):
    with _atlas_identity.as_path(path).open('rb') as stream:
        raw = stream.read(MAX_EVIDENCE+1)
    def pairs(rows):
        result = {}
        for key, value in rows:
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(HistoricalAdmissionRefused('nonfinite JSON')))




@contextmanager
def _metadata_validator(root, review, check):
    modules = {}
    try:
        for name, pin in review.metadata_sources:
            path = _inside(root, name+'.py')
            with path.open('rb') as stream:
                raw = stream.read(MAX_EVIDENCE+1)
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            modules[name] = module
            exec(compile(raw, str(path), 'exec'), module.__dict__)
        yield modules['private_heat_recovery_admission_r1']
    finally:
        for name, module in modules.items():
            if sys.modules.get(name) is module:
                del sys.modules[name]


def _authenticate(root, review, check, budget, *, historical_inputs=None):
    """Exact original validate_records plus its previously omitted full closure."""
    records = {name: _json_file(_inside(root, name), pin, check) for name, pin in review.evidence}
    producer = records[_review_name(review, 'producer')]
    reader = records[_review_name(review, 'reader')]
    preparation = records[_review_name(review, 'preparation')]
    with _metadata_validator(root, review, check) as validator:
        expected = validator.validate_records(producer,
            records[_review_name(review, 'producer_guard')], reader,
            records[_review_name(review, 'reader_guard')], os.getpid())
    original = _inside(root, review.database_name)
    closed = lambda path: not any(Path(str(path)+suffix).exists() for suffix in ('-wal', '-journal'))
    _require(closed(original), 'original checkpoint must be closed without WAL/journal')
    producer_manifest = preparation['producer_manifest']
    preparation_path = _inside(root, producer_manifest['path'])
    preparation_size = preparation_path.stat().st_size
    preparation_scratch = _Allocation(budget, 12*preparation_size+65536)
    producer_preparation = _json_file(preparation_path,
                                     producer_manifest['sha256'], check)
    closure = {}
    def add(name, pin):
        closure[name] = pin
    for mapping in (producer['participating_imported_helper_sources'], preparation['files'],
                    producer_preparation['files'], reader['participating_imported_helper_sources']):
        for name, pin in mapping.items():
            add(name, pin)
    native = producer['native_source']['clone_source_hashes']
    native_relative = (historical_inputs.historical_native_relative if historical_inputs is not None
                       else 'native-composed-r7/tectonics/src')
    native_root = root/native_relative
    actual_names = set()
    for path in (native_root/'atlas_tectonics').rglob('*.py'):
        check()
        actual_names.add(_ordinary(path).relative_to(native_root).as_posix())
    for name, pin in native.items():
        add(native_relative+'/'+name, pin)
    bindings = {_inside(root, name): pin for name, pin in closure.items()}
    bindings.update({_inside(root, name): pin for name, pin in review.evidence})
    bindings.update({_inside(root, name+'.py'): pin for name, pin in review.metadata_sources})
    bindings[_inside(root, producer_manifest['path'])] = producer_manifest['sha256']
    inputs = reader['inputs']
    for name, pin in inputs.items():
        path = _ordinary(name)
        bindings[path] = pin
    _ = preparation_scratch
    return expected, producer, reader, records, bindings, original, producer_manifest['sha256']


class _Allocation:
    _retained_category = 'historical-admission-retained'
    __init__ = _retained_charge

    __del__ = _release_retained_charge


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
    from atlas_tectonics.codecs import storage as S
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
        row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
        chunk_bytes = limits.chunk_bytes
        expected_settings = S._json({'schema': S._SCHEMA, 'chunk_bytes': chunk_bytes})
        _require(row == (expected_settings,), 'original readonly database settings differ')
        result._initial_settings = (S._SCHEMA, chunk_bytes, expected_settings)
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


def open_original_readonly(*, root=None, historical_inputs=None, limits, compression, budget):
    """Open the fixed ORIGINAL only; this still grants no historical admission."""
    inputs = _historical_inputs(historical_inputs)
    root = historical_root(root, historical_inputs=inputs)
    review = _fixed_review(inputs)
    return _open_readonly(_inside(root, review.database_name), limits, compression, budget)


def open_successor_readonly(path, *, expected_sha256, limits, compression, budget, check=None, historical_inputs=None):
    """Independent reader's view of a closed successor copy; grants no admission.

    The whole closed file must equal expected_sha256 BEFORE SQLite sees it and
    keep that identity through the open, so the reader inspects exactly the
    authenticated bytes. mode=ro plus query_only: no write, journal or sidecar.
    Its marker is never admissible, and the historical tree (including the
    reviewed ORIGINAL) is refused wherever it lives, by its reviewed relative name:
    use open_original_readonly plus admission.
    ``check`` is the caller's guard/cancellation boundary during hashing.
    """
    _historical_inputs(historical_inputs)
    check = (lambda: None) if check is None else check
    path = _ordinary(path)
    store = _open_readonly(path, limits, compression, budget, marker=_SUCCESSOR_READONLY)
    try:
        return store
    except BaseException:
        store.close()
        raise


def _array_bytes(store, description, owner, budget, check, *, byte_type=_OwnedBytes):
    """One native validated array; caller holds the pinned native read scope."""
    from atlas_tectonics.codecs.storage import _dtype
    dtype = _dtype(description['dtype'])
    count = math.prod(description['shape'])
    total = count*dtype.itemsize
    scratch = _Allocation(budget, total + store.limits.chunk_bytes + 4096)
    raw, chunk = bytearray(total), None
    try:
        width, offset = store.limits.chunk_bytes // dtype.itemsize, 0
        for index, key in enumerate(description['chunks']):
            check()
            chunk = store._chunk(key, expected_dtype=dtype.str,
                                 expected_count=min(width, count-index*width))
            raw[offset:offset+len(chunk)] = chunk
            offset += len(chunk)
            chunk = None
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
    from atlas_tectonics.codecs.storage import _dtype
    from atlas_tectonics._private.integration import native_transfer as N
    scratch = _Allocation(budget, 16*len(admission._record)+8*len(admission._binding)+(1 << 16))
    capsule, _ = admission.record(), admission.binding()
    admitted = capsule['snapshot_manifests'].get(key)
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


def _audit(store, head, expected, owner, budget, check, *, source_audit_size=None):
    from atlas_tectonics.regional.execution import RegionalMechanicalSnapshot
    rows = expected['array_records']['source_audit']
    if source_audit_size is None:
        source_audit_size = len(canonical(head['source_audit']))
    scratch = _Allocation(budget, source_audit_size*8 + 65536)
    manifest = store._manifest(head['key'])
    fields, identities = [], {}
    raw = None
    try:
        for row in sorted(rows, key=lambda row: row['name']):
            name = 'source-audit:'+row['name']
            description = manifest['arrays'][name]
            raw = _array_bytes(store, description, owner, budget, check)
            fields.append((row['name'], tuple(row['shape']), raw))
            identities[row['name']] = dict(shape=row['shape'], sha256=row['sha256'])
            raw = None
        from atlas_tectonics.regional.execution import identity_metadata
        identity = digest(dict(metadata=identity_metadata(head['source_audit']), arrays=identities))
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


def _admit(store, *, root, review, budget, check, historical_inputs=None):
    """Shared implementation; fixture profiles are deliberately private."""
    from atlas_tectonics._private.integration import workflow_transfer as W
    root = Path(root).resolve()
    original = _inside(root, review.database_name)
    # Size metadata before decoding; schema ceilings are limits, not allocated
    # demand. SQLite's own existing read workspace remains unchanged.
    with store._read_scope(budget=budget):
        catalogue_bytes, largest_manifest, count = store._db.execute(
            'SELECT COALESCE(sum(length(body)),0),COALESCE(max(length(body)),0),count(*) FROM snapshots').fetchone()
    evidence_bytes = sum(_inside(root, name).stat().st_size for name, _ in review.evidence)
    metadata_bytes = sum(_inside(root, name+'.py').stat().st_size for name, _ in review.metadata_sources)
    scratch = _Allocation(budget, 12*evidence_bytes + 16*catalogue_bytes + 12*metadata_bytes + (1 << 20))
    expected = producer = reader = bindings = manifests = capsule = None
    try:
        check()
        expected, producer, reader, _records, bindings, original, producer_manifest = (_authenticate(root, review, check, budget) if historical_inputs is None else
            _authenticate(root, review, check, budget, historical_inputs=historical_inputs))
        with store._read_scope(budget=budget):
            chain = [store.metadata(expected['root_key']), store.metadata(expected['head_key'])]
            W.validate_historical_chain(chain)
            head = chain[-1]
            manifests, size = {}, 0
            inventory = dict(scope='complete-source-store', snapshots=0, arrays=0, chunk_references=0, raw_bytes=0)
            inventory_hash = sha256()
            for (key,) in store._db.execute('SELECT id FROM snapshots ORDER BY id'):
                check()
                manifest = store._manifest(key)
                size += len(canonical(manifest))
                for name, desc in manifest['arrays'].items():
                    inventory['arrays'] += 1
                    inventory['chunk_references'] += len(desc['chunks'])
                    # The pinned whole-file hash includes every chunk payload,
                    # descriptor, index and manifest. The original successful
                    # reader already checked the scientific closure. Decode no
                    # physical field merely to reconfirm those identical bytes.
                    from atlas_tectonics.codecs.storage import _dtype
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
                reader_receipt_sha256=dict(review.evidence)[_review_name(review, 'reader')])
            source = dict(workflow_id=expected['workflow_id'], root_key=expected['root_key'],
                head_key=expected['head_key'], sequence=1, time_s=head['state']['fields']['time_s'],
                store_token=token, database_sha256=review.database_sha256)
            capsule = dict(schema='atlas.restart-historical-endpoint.v1', source=source,
                chain_metadata=chain, snapshot_manifests=manifests, inventory=inventory,
                validation_receipt=dict(sha256=dict(review.evidence)[_review_name(review, 'reader')], record=reader),
                producer=dict(expected['execution_provenance'], source_manifest_sha256=producer_manifest,
                    native_source_digest=producer['native_source_digest'], original_status=producer['status'],
                    original_finalisation_not_certified=True, array_records=expected['array_records'],
                    preparation_ids=expected['preparation_ids'],
                    participating_source_pins=producer['participating_imported_helper_sources']))
            raw = canonical(capsule)
            binding = dict(schema='atlas.restart-historical-admission.v1', capsule_sha256=sha256(raw).hexdigest(),
                original_database_path=str(original), database_sha256=review.database_sha256,
                source_pins={str(p.relative_to(root)): pin for p, pin in bindings.items() if p != original},
                metadata_source_pins=dict(review.metadata_sources), evidence_pins=dict(review.evidence),
                origin=dict(producer_receipt_sha256=dict(review.evidence)[_review_name(review, 'producer')],
                            store_token_sha256=digest(token), endpoint_lineage_sha256=digest(chain)),
                historical_scientific_checks_reused=True, historical_scientific_checks_replayed=False,
                original_producer_status='FAILED', original_finalisation_not_certified=True,
                new_runtime_accepted=False, production_acceptance=False, continuation_authorised=False)
            binding_raw = canonical(binding)
            audit_bytes = sum(math.prod(row['shape'])*8 for row in expected['array_records']['source_audit'])
            source_audit_size = len(canonical(head['source_audit']))
            owner = _Allocation(budget, len(raw)+len(binding_raw)+audit_bytes+
                source_audit_size+len(expected['array_records']['source_audit'])*512+8192)
            audit = _audit(store, head, expected, owner, budget, check, source_audit_size=source_audit_size)
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

    ``check`` runs only after the guard's own type and live check method are established.
    """
    receipt = guard._sync()
    return receipt


def admit_historical_endpoint(store, *, root=None, historical_inputs=None, execution, budget, guard, cancel=None):
    """Usable fixed-profile historical issuer under the existing guarded launch.

    Pass open_original_readonly's already-open ORIGINAL ArrayStore, actual current
    strict ExecutionContext, one shared budget and live ContinuationGuard. No
    fixture/profile/pin override is accepted by this public entry point; ``root``
    only names where the reviewed H lives (historical_root), and its pins stay fixed.
    """
    inputs = _historical_inputs(historical_inputs)
    root = historical_root(root, historical_inputs=inputs)

    def check():
        if cancel is not None and cancel.is_set():
            from concurrent.futures import CancelledError
            raise CancelledError('historical admission cancelled')
        guard.check(force=True)
    guardian_fence(guard, budget=budget, check=check)
    result = _admit(store, root=root, review=_fixed_review(inputs), historical_inputs=inputs,
                    budget=budget, check=check)
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
    from atlas_tectonics._private.integration import native_transfer as N
    capsule, _ = admission.record(), admission.binding()
    N._scientific_graph(actual_current_graph)
    graph = json.loads(canonical(actual_current_graph))
    old_execution = capsule['producer']['execution_identity']
    root = capsule['chain_metadata'][0]
    old_collar = root['collar_plan']
    ids = capsule['producer']['preparation_ids']
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
    N._scientific_graph(graph)
    return graph


def _historical_inputs_api():
    from atlas_tectonics._private.integration import historical_input_contract
    return historical_input_contract


def _historical_inputs(value):
    api = _historical_inputs_api()
    try:
        return api.verified(value)
    except api.HistoricalInputsRefused as error:
        raise HistoricalAdmissionRefused(str(error)) from error


def _fixed_review(inputs):
    return _Review(**inputs.reviewed_original())


def _review_name(review, role):
    """The original fixed evidence order, also retained by the private fixture seam."""
    roles = ('producer', 'producer_guard', 'reader', 'reader_guard', 'preparation')
    return review.evidence[roles.index(role)][0]
