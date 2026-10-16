"""Durable restart references, not scientific admission or migration permits.

Reuse ArrayStore's immutable chunks and atomic transactions. A saved restart
reference retains its producer identity separately from its scientific contract.
Inspection under another implementation never changes either identity and never
grants permission to advance. Actual native/spatial/heat validators still decide
whether the referenced state is a usable starting point.

This module is a private successor candidate, not wired into a production run.
"""
from contextlib import contextmanager
import hashlib

import numpy as np

from atlas_tectonics.reuse import ExecutionContext
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreError, _json, _parse, _sha


SCHEMA = 'atlas.restart-reference.v1'
STAGES = frozenset(('prepared-interval', 'geometry-complete', 'heat-complete',
                    'interval-published'))
REQUIRED = frozenset(('schema', 'scientific_contract_id', 'state_format',
    'recorder', 'source_producer', 'sequence', 'time_s', 'stage', 'source_snapshot',
    'source_manifest_sha256', 'source_metadata_sha256', 'array_descriptors',
    'parent_reference', 'authority'))
AUTHORITY = 'stored evidence only; requires actual state and equation validation'


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


class RestartRefused(StoreError):
    pass


class RestartCatalog:
    """Single-store restart index, bounded by the store's existing resource limits.

    No mutable latest pointer: callers retain an exact content-addressed key.
    Existing history is never overwritten, repinned, or declared accepted here.
    The one-byte marker lets the existing nonempty-array store transaction carry
    metadata; scientific payloads remain in their existing immutable snapshots.
    """

    def __init__(self, store, execution, *, budget):
        if (type(store) is not ArrayStore or type(execution) is not ExecutionContext
                or type(budget) is not WorkBudget or store._budget is not budget):
            raise RestartRefused('actual store, execution and shared budget required')
        self.store, self.execution, self.budget = store, execution, budget

    def _verify(self):
        self.execution.verify_boundary()

    def _manifest(self, key):
        _sha(key)
        # This private successor deliberately uses the store's one canonical
        # manifest validator rather than maintaining a second decoder/schema.
        with self.store._read_scope(budget=self.budget):
            value = self.store._manifest(key)
            if value is None:
                raise RestartRefused('referenced snapshot is missing')
            return value

    @staticmethod
    def _position(sequence, time_s, stage, state_format):
        if type(sequence) is not int or sequence < 0:
            raise RestartRefused('nonnegative completed interval count required')
        if (type(time_s) is not str or not time_s or len(time_s) > 128
                or stage not in STAGES or type(state_format) is not str
                or not state_format or len(state_format) > 128):
            raise RestartRefused('explicit bounded format, clock and stage required')
        # The clock is opaque canonical scientific data, not a float conversion.
        # Its physical meaning is checked by the format-specific state importer.

    def _source(self, record):
        source = self._manifest(record['source_snapshot'])
        if (type(source['metadata']) is not dict
                or source['metadata'].get('schema') != record['state_format']
                or _digest(source) != record['source_manifest_sha256']
                or _digest(source['metadata']) != record['source_metadata_sha256']
                or source['arrays'] != record['array_descriptors']
                or source['metadata'].get('producer') != record['source_producer']):
            raise RestartRefused('restart source manifest or array inventory changed')
        return source

    @staticmethod
    def _provenance(value):
        if (type(value) is not dict
                or set(value) != {'execution_identity', 'execution_mode'}
                or value['execution_mode'] not in ('strict', 'release')):
            raise RestartRefused('complete execution provenance required')
        _sha(value['execution_identity'])

    def _record(self, key):
        manifest = self._manifest(key)
        record = manifest['metadata']
        if (type(record) is not dict or set(record) != REQUIRED
                or record['schema'] != SCHEMA or _digest(record) != key
                or record['authority'] != AUTHORITY
                or set(manifest['arrays']) != {'restart-marker'}):
            raise RestartRefused('invalid restart reference')
        self._position(record['sequence'], record['time_s'], record['stage'],
                       record['state_format'])
        _sha(record['scientific_contract_id'])
        _sha(record['source_manifest_sha256'])
        _sha(record['source_metadata_sha256'])
        self._provenance(record['recorder'])
        if record['source_producer'] is not None:
            self._provenance(record['source_producer'])
        if record['parent_reference'] is not None:
            _sha(record['parent_reference'])
        marker_description = manifest['arrays']['restart-marker']
        if (marker_description['dtype'] != '|u1' or marker_description['shape'] != [1]
                or len(marker_description['chunks']) != 1):
            raise RestartRefused('restart marker has an invalid size or type')
        marker = list(self.store.iter_chunks(key, 'restart-marker', budget=self.budget))
        if (len(marker) != 1 or marker[0][0] != 0
                or marker[0][1].dtype.str != '|u1'
                or marker[0][1].shape != (1,) or marker[0][1][0] != 1):
            raise RestartRefused('restart marker is corrupt')
        self._source(record)
        return record

    def publish(self, source_snapshot, *, scientific_contract_id, state_format,
                sequence, time_s, stage, parent_reference=None, cancel=None):
        """Publish a restart reference after authenticating every source chunk.

        Completion of this operation proves storage integrity only. It does not
        turn a partly completed stage into an accepted interval. Source objects
        must already be immutable ArrayStore snapshots, not caller assertions.
        """
        self._verify()
        _sha(scientific_contract_id)
        self._position(sequence, time_s, stage, state_format)
        with self.budget.reserve(8 * self.store.limits.max_manifest_bytes,
                                 category='restart-reference-metadata'):
            source = self._manifest(source_snapshot)
            if not isinstance(source['metadata'], dict):
                raise RestartRefused('scientific snapshot metadata must be an object')
            if source['metadata'].get('schema') == SCHEMA:
                raise RestartRefused('a restart reference cannot stand in for scientific data')
            if source['metadata'].get('schema') != state_format:
                raise RestartRefused('state format differs from the actual stored schema')
            producer = source['metadata'].get('producer')
            if producer is not None:
                self._provenance(producer)
            if parent_reference is not None:
                parent = self._record(parent_reference)
                if (parent['scientific_contract_id'] != scientific_contract_id
                        or parent['state_format'] != state_format
                        or sequence < parent['sequence'] or sequence > parent['sequence'] + 1):
                    raise RestartRefused('restart parent contract or interval position differs')
            record = dict(schema=SCHEMA, scientific_contract_id=scientific_contract_id,
                state_format=state_format, recorder=self.execution.provenance,
                source_producer=producer,
                sequence=sequence, time_s=time_s, stage=stage,
                source_snapshot=source_snapshot,
                source_manifest_sha256=_digest(source),
                source_metadata_sha256=_digest(source['metadata']),
                array_descriptors=source['arrays'], parent_reference=parent_reference,
                authority=AUTHORITY)
            # Chunk iteration verifies decoded identities without accumulating
            # physical arrays. A cancelled validation publishes no marker.
            for name in sorted(source['arrays']):
                for _offset, _chunk in self.store.iter_chunks(source_snapshot, name,
                                                              budget=self.budget):
                    if cancel is not None and cancel.is_set():
                        from concurrent.futures import CancelledError
                        raise CancelledError('restart reference validation cancelled')
                    del _chunk
            key = _digest(record)

            def check():
                self._verify()
                self._source(record)
                if parent_reference is not None:
                    self._record(parent_reference)

            self.store.put(key, {'restart-marker': np.array([1], dtype=np.uint8)},
                record, budget=self.budget, publication_check=check, cancel=cancel)
            return key

    @contextmanager
    def inspect(self, key, *, scientific_contract_id):
        """Yield bounded metadata only; no live state or compatibility decision.

        The caller may use stream() within this scope to read physical data.
        The actual reader source and complete immutable manifest are checked
        both before and after use, including exceptional exits.
        """
        self._verify()
        _sha(scientific_contract_id)
        with self.budget.reserve(8 * self.store.limits.max_manifest_bytes,
                                 category='restart-reference-inspection'):
            record = self._record(key)
            if record['scientific_contract_id'] != scientific_contract_id:
                raise RestartRefused('scientific contract differs; explicit transformation required')
            current = self.execution.provenance
            producer = record['source_producer']
            result = dict(reference=key, record=_parse(_json(record)), reader=current,
                status=('HISTORICAL_PRODUCER_VALIDATION_REQUIRED' if producer is None else
                    'SAME_RUNTIME_STATE_VALIDATION_REQUIRED' if producer == current else
                    'COMPATIBILITY_VALIDATION_REQUIRED'),
                may_advance=False)
            try:
                yield result
            finally:
                self._verify()
                if self._record(key) != record:
                    raise RestartRefused('restart reference changed while inspected')

    def stream(self, key, name, *, scientific_contract_id):
        """Yield immutable original chunks; the consumer owns retained outputs.

        Chunk decoder workspace remains the existing ArrayStore contract. This
        API never builds, retains or returns a whole-world array dictionary.
        """
        with self.inspect(key, scientific_contract_id=scientific_contract_id) as view:
            record = view['record']
            if name not in record['array_descriptors']:
                raise RestartRefused('array absent from complete restart inventory')
            yield from self.store.iter_chunks(record['source_snapshot'], name,
                                               budget=self.budget)
