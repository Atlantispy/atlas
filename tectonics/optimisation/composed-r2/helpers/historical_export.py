"""Two-phase historical endpoint export; NOT a historical admission issuer.

The source transform adds a capture point after the original recovery reader's
native/heat/geometry/accounts and six-group checks. Native Atlas source is never
modified, relabelled or imported here at module load. The successor helper and
this adapter must have their own pins in an additive reader preparation.

Capture writes an unfinished .partial file, streaming the complete ArrayStore
catalogue and authenticating existing chunks. It copies no physical payloads.
The original closed database remains necessary; a connection token is NOT a
database identity. The exact source-fenced, guarded export harness has not yet
been composed. Consequently publish_authenticated() ALWAYS refuses. Private
_commit_protocol exercises atomic I/O only; neither it nor exported JSON issues
workflow_transfer.HistoricalEndpointAdmission.

Required harness: bootstrap checked successor helper/adapter source bytes;
validate the original producer receipt/guard/preparation and closed database;
run the transformed recovery_consumer_r3/r4 under its actual original native-r7
ExecutionContext and unchanged continuous memory/cancellation guard; capture;
finish all existing frame retirement, zero-reservation, source/import, original
and copied database byte-hash checks; save the complete successful reader
receipt; require the independent guardian's confirmed clean terminal outcome.
Only then may a separately composed fenced controller call the private commit
protocol, rechecking its source pins and receipt/guard/database bytes immediately
before publication. It must retain the whole reader receipt, not success flags.
No public API currently mints that controller or a scientific admission.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import uuid


SCHEMA = 'atlas.restart-historical-endpoint.v1'
NATIVE_R7_DIGEST = '746eea53c8dc9c9c89c8f7db8474e579fd5d2a2b919615b287358ddd4cb29d28'
AUTHORITY = 'exported evidence only; original-reader fenced admission required'


class HistoricalExportRefused(ValueError):
    pass


@dataclass(frozen=True)
class ExportLimits:
    max_capsule_bytes: int = 8 << 20
    max_record_bytes: int = 2 << 20
    max_snapshots: int = 4096
    max_arrays: int = 65536
    max_chunk_references: int = 1000000
    max_raw_bytes: int = 128 << 30

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise HistoricalExportRefused('positive finite export limits required')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, ensure_ascii=True).encode('ascii')


def _sha(value):
    if (type(value) is not str or len(value) != 64 or
            any(c not in '0123456789abcdef' for c in value)):
        raise HistoricalExportRefused('lowercase SHA-256 identity required')
    return value


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('historical export interrupted')


def _file_hash(path, *, maximum, cancel=None):
    digest, count = sha256(), 0
    with Path(path).open('rb') as stream:
        while block := stream.read(65536):
            _check_cancel(cancel)
            count += len(block)
            if count > maximum:
                raise HistoricalExportRefused('staged capsule exceeds byte limit')
            digest.update(block)
    return digest.hexdigest(), count


class _Writer:
    def __init__(self, stream, limits, cancel):
        self.stream, self.limits, self.cancel = stream, limits, cancel
        self.size, self.digest = 0, sha256()

    def raw(self, raw):
        _check_cancel(self.cancel)
        if self.size + len(raw) > self.limits.max_capsule_bytes:
            raise HistoricalExportRefused('capsule byte limit exceeded')
        self.stream.write(raw)
        self.digest.update(raw)
        self.size += len(raw)

    def value(self, value):
        # iterencode avoids a second complete serialized manifest allocation.
        count = 0
        for piece in json.JSONEncoder(sort_keys=True, separators=(',', ':'),
                allow_nan=False, ensure_ascii=True).iterencode(value):
            raw = piece.encode('ascii')
            count += len(raw)
            if count > self.limits.max_record_bytes:
                raise HistoricalExportRefused('one exported record exceeds limit')
            self.raw(raw)


@dataclass(frozen=True)
class StagedEndpoint:
    """An unfinished file reference, explicitly not a validation capability."""
    path: Path
    prefix_sha256: str
    prefix_bytes: int
    source: dict
    inventory: dict
    limits: ExportLimits


def _chain_keys(store, source, limits):
    keys, current = [], source['head_key']
    while True:
        if len(keys) > 256 or current in keys:
            raise HistoricalExportRefused('cyclic or excessive historical chain')
        _sha(current)
        row = store.metadata(current)
        if (type(row) is not dict or row.get('key') != current or
                row.get('workflow_id') != source['workflow_id']):
            raise HistoricalExportRefused('historical chain identity differs')
        keys.append(current)
        if current == source['root_key']:
            if row.get('kind') != 'root' or row.get('sequence') != 0:
                raise HistoricalExportRefused('historical root differs')
            break
        if row.get('kind') != 'successor':
            raise HistoricalExportRefused('non-successor in historical chain')
        current = row.get('parent_key')
    keys.reverse()
    if len(keys) != source['sequence'] + 1 or len(keys) > limits.max_snapshots:
        raise HistoricalExportRefused('historical chain has missing sequence')
    previous = None
    for sequence, key in enumerate(keys):
        row = store.metadata(key)
        if row['sequence'] != sequence or (previous is not None and
                row.get('parent_digest') != sha256(canonical(previous)).hexdigest()):
            raise HistoricalExportRefused('historical chain metadata link differs')
        previous = row
    if previous['state']['fields']['time_s'] != source['time_s']:
        raise HistoricalExportRefused('historical endpoint clock differs')
    return keys


def _stage_protocol(directory, store, *, source, producer, adapter, budget,
                    limits=ExportLimits(), cancel=None):
    """I/O protocol only. Caller assertions never become scientific authority.

    The full source-store catalogue deliberately preserves a superset of the
    endpoint's CAS closure, including original heat and certification artifacts.
    No guessed recursive IDs or selected-array-only export can omit a dependency.
    One manifest and one decoded chunk are live at a time; existing ArrayStore
    read scopes fund decode work. No snapshot payload dictionary is constructed.
    """
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import ArrayStore
    if type(store) is not ArrayStore or type(budget) is not WorkBudget or store._budget is not budget:
        raise HistoricalExportRefused('actual ArrayStore and shared WorkBudget required')
    directory = Path(directory).resolve(strict=True)
    if not directory.is_dir() or directory.is_symlink():
        raise HistoricalExportRefused('existing local export directory required')
    if (set(source) != {'workflow_id', 'root_key', 'head_key', 'sequence', 'time_s',
                        'store_token', 'database_sha256'} or
            type(source['sequence']) is not int or not 1 <= source['sequence'] <= 256):
        raise HistoricalExportRefused('complete nonzero source endpoint required')
    for name in ('workflow_id', 'root_key', 'head_key', 'database_sha256'):
        _sha(source[name])
    for name in ('execution_identity', 'source_manifest_sha256', 'native_source_digest'):
        _sha(producer[name])
    if producer.get('execution_mode') != 'strict':
        raise HistoricalExportRefused('original strict execution provenance required')
    for name in ('source_sha256', 'source_manifest_sha256'):
        _sha(adapter[name])
    path = directory / ('endpoint.partial-' + uuid.uuid4().hex)
    manifest = chunk = None
    inventory = dict(scope='complete-source-store', snapshots=0, arrays=0,
                     chunk_references=0, raw_bytes=0)
    manifest_digest = sha256()
    # Bound metadata working memory independently of total catalogue size.
    with budget.reserve(12 * store.limits.max_manifest_bytes +
                        8 * limits.max_record_bytes + 65536,
                        category='historical-export-metadata'):
        try:
            with store._read_scope(budget=budget), path.open('xb') as output:
                if list(store.change_token()) != list(source['store_token']):
                    raise HistoricalExportRefused('store changed before capture')
                keys = _chain_keys(store, source, limits)
                writer = _Writer(output, limits, cancel)
                writer.raw(b'{"adapter":'); writer.value(adapter)
                writer.raw(b',"authority":'); writer.value(AUTHORITY)
                writer.raw(b',"chain_metadata":[')
                for index, key in enumerate(keys):
                    if index:
                        writer.raw(b',')
                    writer.value(store.metadata(key))
                writer.raw(b'],"producer":'); writer.value(producer)
                writer.raw(b',"schema":'); writer.value(SCHEMA)
                writer.raw(b',"snapshot_manifests":{')
                # Read-only cursor over the schema already authenticated by
                # ArrayStore. Do not fetchall or copy all manifests into RAM.
                cursor = store._db.execute('SELECT id FROM snapshots ORDER BY id')
                for (key,) in cursor:
                    _check_cancel(cancel)
                    inventory['snapshots'] += 1
                    if inventory['snapshots'] > limits.max_snapshots:
                        raise HistoricalExportRefused('snapshot inventory limit exceeded')
                    manifest = store._manifest(key)
                    if manifest is None:
                        raise HistoricalExportRefused('catalogue snapshot missing')
                    for name, description in sorted(manifest['arrays'].items()):
                        inventory['arrays'] += 1
                        inventory['chunk_references'] += len(description['chunks'])
                        if (inventory['arrays'] > limits.max_arrays or
                                inventory['chunk_references'] > limits.max_chunk_references):
                            raise HistoricalExportRefused('array/chunk inventory limit exceeded')
                        offset, size = 0, 0
                        for start, chunk in store.iter_chunks(key, name, budget=budget):
                            _check_cancel(cancel)
                            if start != offset or chunk.dtype.str != description['dtype']:
                                raise HistoricalExportRefused('streamed array layout differs')
                            offset += chunk.size
                            size += chunk.nbytes
                            chunk = None
                        if offset != math.prod(description['shape']):
                            raise HistoricalExportRefused('incomplete streamed array')
                        inventory['raw_bytes'] += size
                        if inventory['raw_bytes'] > limits.max_raw_bytes:
                            raise HistoricalExportRefused('raw-byte inventory limit exceeded')
                    if inventory['snapshots'] > 1:
                        writer.raw(b',')
                    writer.value(key); writer.raw(b':'); writer.value(manifest)
                    manifest_digest.update(key.encode('ascii'))
                    manifest_digest.update(sha256(canonical(manifest)).digest())
                    manifest = None
                if inventory['snapshots'] != store.statistics()['snapshots']:
                    raise HistoricalExportRefused('snapshot catalogue coverage differs')
                inventory['manifest_inventory_sha256'] = manifest_digest.hexdigest()
                writer.raw(b'},"source":'); writer.value(source)
                writer.raw(b',"inventory":'); writer.value(inventory)
                # Intentionally incomplete JSON until final reader/guard proof.
                if list(store.change_token()) != list(source['store_token']):
                    raise HistoricalExportRefused('store changed during capture')
                output.flush(); os.fsync(output.fileno())
                return StagedEndpoint(path, writer.digest.hexdigest(), writer.size,
                                      dict(source), dict(inventory), limits)
        finally:
            # Escaping metadata frames must not retain decoded scientific arrays.
            manifest = chunk = None


def _commit_protocol(staged, validation_receipt, *, final_check, cancel=None):
    """Atomic file mechanics ONLY; final_check is not an admission issuer.

    Kept private until the independently pinned reader/guardian harness exists.
    Returned content-addressed files remain evidence, not live state authority.
    A failed/interrupted append keeps only a .partial file; never repair/reuse it.
    """
    if type(staged) is not StagedEndpoint or not callable(final_check):
        raise HistoricalExportRefused('staged protocol record and final fence required')
    _check_cancel(cancel)
    if _file_hash(staged.path, maximum=staged.limits.max_capsule_bytes, cancel=cancel) != (
            staged.prefix_sha256, staged.prefix_bytes):
        raise HistoricalExportRefused('staged capsule changed')
    raw = canonical(validation_receipt)
    if len(raw) > staged.limits.max_record_bytes:
        raise HistoricalExportRefused('reader receipt exceeds export limit')
    receipt = dict(sha256=sha256(raw).hexdigest(), record=validation_receipt)
    final_check()  # must raise on any failed native-reader finalisation boundary
    with staged.path.open('ab') as output:
        writer = _Writer(output, staged.limits, cancel)
        writer.size = staged.prefix_bytes
        writer.raw(b',"validation_receipt":'); writer.value(receipt); writer.raw(b'}')
        output.flush(); os.fsync(output.fileno())
    digest, size = _file_hash(staged.path, maximum=staged.limits.max_capsule_bytes, cancel=cancel)
    final_check()
    _check_cancel(cancel)
    destination = staged.path.parent / (digest + '.capsule.json')
    # Windows rename is atomic and refuses an existing destination. POSIX
    # rename can replace one, so use exclusive link publication there instead.
    if os.name == 'nt':
        os.rename(staged.path, destination)
    else:
        os.link(staged.path, destination)
        staged.path.unlink()
    return dict(path=str(destination), sha256=digest, bytes=size, authority=AUTHORITY)


class HistoricalExportStaging:
    """Live native reader capture sink. It cannot publish or issue admission."""
    def __init__(self, directory, *, producer, adapter, database_sha256,
                 limits=ExportLimits(), cancel=None):
        self.directory, self.producer, self.adapter = directory, producer, adapter
        self.database_sha256, self.limits, self.cancel = _sha(database_sha256), limits, cancel
        self.staged = None

    def capture(self, *, workflow, store, expected, execution, budget):
        from atlas_tectonics.integration_regional_workflow import CollarWorkflow
        from atlas_tectonics.reuse import ExecutionContext
        if (type(workflow) is not CollarWorkflow or type(execution) is not ExecutionContext
                or self.staged is not None):
            raise HistoricalExportRefused('one actual original native workflow capture required')
        execution.verify_boundary()
        if (execution.provenance != expected['execution_provenance'] or
                self.producer.get('native_source_digest') != NATIVE_R7_DIGEST or
                any(self.producer.get(k) != v for k, v in execution.provenance.items())):
            raise HistoricalExportRefused('original native producer/execution identity differs')
        root, head = json.loads(workflow._root), workflow._head
        if (root != expected['root_metadata'] or head['key'] != expected['head_key'] or
                workflow.workflow_id != expected['workflow_id']):
            raise HistoricalExportRefused('checked reader endpoint differs')
        source = dict(workflow_id=workflow.workflow_id, root_key=root['key'],
            head_key=head['key'], sequence=head['sequence'],
            time_s=head['state']['fields']['time_s'], store_token=list(store.change_token()),
            database_sha256=self.database_sha256)
        self.staged = _stage_protocol(self.directory, store, source=source,
            producer=self.producer, adapter=self.adapter, budget=budget,
            limits=self.limits, cancel=self.cancel)
        execution.verify_boundary()

    def publish_authenticated(self, *args, **kwargs):
        raise HistoricalExportRefused('original-reader source-fenced terminal guardian harness is not composed')


def transform_recovery_consumer(source):
    """Exact additive r3/r4 helper transform; return text, never mutate source.

    A successor preparation must pin this changed helper and adapter separately.
    Original native-r7 identity stays untouched. The default path is unchanged.
    """
    signature = 'def consume(receipt, database, phase, evidence, *, sources=None, guard=None):'
    anchor = '                            del endpoint, exterior, arrays\n'
    if source.count(signature) != 1 or source.count(anchor) != 1 or '_historical_export' in source:
        raise HistoricalExportRefused('original recovery-consumer seam missing or ambiguous')
    required = ('                            _completed_interval(receipt, expected, workflow, evidence)',
                "raise ValueError('Saved reopening replayed an operator or changed the store')")
    if any(source.count(text) != 1 for text in required):
        raise HistoricalExportRefused('mandatory original-reader checks missing')
    source = source.replace(signature, signature[:-2] + ', _historical_export=None):')
    return source.replace(anchor,
        '                            if _historical_export is not None:\n'
        '                                from historical_export import HistoricalExportStaging\n'
        '                                if type(_historical_export) is not HistoricalExportStaging:\n'
        "                                    raise TypeError('exact historical export staging sink required')\n"
        '                                _historical_export.capture(workflow=workflow, store=store,\n'
        '                                    expected=expected, execution=execution, budget=budget)\n' + anchor)
