"""Pure, immutable Step 3 wire contracts; no storage or scientific authority.

These records describe references, not verified capabilities. A later resolver
must authenticate catalogs, manifests, seals and payloads. Construction performs
no I/O, hashing, codec work, publication or runtime imports.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re


SEGMENT_REF_SCHEMA = 'atlas.segment-ref.v1'
BINDING_INDEX_SCHEMA = 'atlas.binding-index.v1'
NATIVE_CHUNK_BYTES = 64 * 1024
SEGMENT_BYTES = 128 * 1024 * 1024
SEGMENT_CHUNK_REFERENCES = 2048
SEGMENT_MANIFEST_BYTES = 256 * 1024
ROOT_METADATA_MAX = 64 * 1024
SEGMENT_REF_BYTES = 4096
RECORD_SCHEMA_BYTES = 256
BINDING_PAGE_BYTES = 64 * 1024
INDEX_FANOUT = 256
INDEX_MAX_DEPTH = 8
CATALOG_BYTES = 1024 * 1024
MAX_OPEN_FILES = 8
RETAINED_BYTES = 256 * 1024 * 1024
SUPPORT_CACHE_BYTES = 128 * 1024 * 1024
FACT_CACHE_BYTES = 64 * 1024 * 1024
PAGE_CACHE_BYTES = 64 * 1024 * 1024
UINT64_MAX = (1 << 64) - 1
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')


class ContractError(ValueError):
    """Malformed, incompatible or over-bound contract; never a cache miss."""


def _uint(value: object, name: str) -> None:
    if type(value) is not int or not 0 <= value <= UINT64_MAX:
        raise ContractError(name + ' must be an unsigned 64-bit integer')


def _sha(value: object, name: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ContractError(name + ' must be a lowercase SHA-256 digest')


def _schema(value: object, expected: str) -> None:
    if type(value) is not str or value != expected:
        raise ContractError('unknown contract schema')


def _fields(value: object, fields: frozenset[str], name: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ContractError(name + ' requires exactly its declared fields')
    return value


def _canonical(value: dict) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('ascii')
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ContractError('contract is not canonical finite JSON') from exc


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('duplicate JSON key')
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise ContractError('nonfinite JSON number: ' + value)


@dataclass(frozen=True, slots=True)
class SnapshotLocator:
    """Catalog-relative identity; deliberately contains no path or file seal."""

    workflow_id: str
    interval: int
    snapshot_key: str

    def __post_init__(self) -> None:
        _sha(self.workflow_id, 'workflow_id')
        _uint(self.interval, 'interval')
        _sha(self.snapshot_key, 'snapshot_key')

    def to_wire(self) -> dict:
        return dict(workflow_id=self.workflow_id, interval=self.interval,
                    snapshot_key=self.snapshot_key)

    @classmethod
    def from_wire(cls, value: object) -> SnapshotLocator:
        row = _fields(value, frozenset(('workflow_id', 'interval', 'snapshot_key')),
                      'snapshot locator')
        return cls(row['workflow_id'], row['interval'], row['snapshot_key'])


@dataclass(frozen=True, slots=True)
class LogicalIdentity:
    """Logical schema admission belongs to its caller, not a domain registry here."""

    record_schema: str
    sha256: str
    canonical_bytes: int

    def __post_init__(self) -> None:
        if type(self.record_schema) is not str or not self.record_schema:
            raise ContractError('record_schema must be nonempty UTF-8 text')
        try:
            length = len(self.record_schema.encode('utf-8'))
        except UnicodeError as exc:
            raise ContractError('record_schema must be valid UTF-8 text') from exc
        if length > RECORD_SCHEMA_BYTES:
            raise ContractError('record_schema exceeds its UTF-8 byte bound')
        _sha(self.sha256, 'logical identity sha256')
        _uint(self.canonical_bytes, 'canonical_bytes')

    def to_wire(self) -> dict:
        return dict(record_schema=self.record_schema, sha256=self.sha256,
                    canonical_bytes=self.canonical_bytes)

    @classmethod
    def from_wire(cls, value: object) -> LogicalIdentity:
        row = _fields(value, frozenset(('record_schema', 'sha256', 'canonical_bytes')),
                      'logical identity')
        return cls(row['record_schema'], row['sha256'], row['canonical_bytes'])


@dataclass(frozen=True, slots=True)
class BindingIndexRef:
    """One bounded index root, not an inline inventory or authentication result."""

    schema: str
    root_key: SnapshotLocator
    digest: str
    count: int

    def __post_init__(self) -> None:
        _schema(self.schema, BINDING_INDEX_SCHEMA)
        if type(self.root_key) is not SnapshotLocator:
            raise ContractError('binding root requires a SnapshotLocator')
        _sha(self.digest, 'binding index digest')
        _uint(self.count, 'binding count')

    def to_wire(self) -> dict:
        return dict(schema=self.schema, root_key=self.root_key.to_wire(),
                    digest=self.digest, count=self.count)

    @classmethod
    def from_wire(cls, value: object) -> BindingIndexRef:
        row = _fields(value, frozenset(('schema', 'root_key', 'digest', 'count')),
                      'binding index reference')
        return cls(row['schema'], SnapshotLocator.from_wire(row['root_key']),
                   row['digest'], row['count'])


@dataclass(frozen=True, slots=True)
class SegmentRef:
    """Portable six-field reference; format validity is not content verification."""

    schema: str
    root_key: SnapshotLocator
    identity: LogicalIdentity
    logical_bytes: int
    array_bindings: BindingIndexRef
    merkle_root: str

    def __post_init__(self) -> None:
        _schema(self.schema, SEGMENT_REF_SCHEMA)
        if type(self.root_key) is not SnapshotLocator:
            raise ContractError('segment root requires a SnapshotLocator')
        if type(self.identity) is not LogicalIdentity:
            raise ContractError('segment identity requires a LogicalIdentity')
        _uint(self.logical_bytes, 'logical_bytes')
        if type(self.array_bindings) is not BindingIndexRef:
            raise ContractError('array_bindings requires a BindingIndexRef')
        _sha(self.merkle_root, 'merkle_root')
        binding_root = self.array_bindings.root_key
        if binding_root.workflow_id != self.root_key.workflow_id:
            raise ContractError('binding root belongs to a different workflow')
        if binding_root.interval > self.root_key.interval:
            raise ContractError('binding root cannot refer to a future interval')
        self.to_json()

    def to_wire(self) -> dict:
        """Return a detached mutable wire value without exposing mutable DTO state."""
        return dict(schema=self.schema, root_key=self.root_key.to_wire(),
                    identity=self.identity.to_wire(), logical_bytes=self.logical_bytes,
                    array_bindings=self.array_bindings.to_wire(), merkle_root=self.merkle_root)

    def to_json(self) -> bytes:
        raw = _canonical(self.to_wire())
        if len(raw) > SEGMENT_REF_BYTES:
            raise ContractError('SegmentRef exceeds 4096 encoded bytes')
        return raw

    @classmethod
    def from_wire(cls, value: object) -> SegmentRef:
        row = _fields(value, frozenset(('schema', 'root_key', 'identity', 'logical_bytes',
                                       'array_bindings', 'merkle_root')), 'segment reference')
        return cls(row['schema'], SnapshotLocator.from_wire(row['root_key']),
                   LogicalIdentity.from_wire(row['identity']), row['logical_bytes'],
                   BindingIndexRef.from_wire(row['array_bindings']), row['merkle_root'])

    @classmethod
    def from_json(cls, raw: bytes | str) -> SegmentRef:
        """Accept only bounded canonical UTF-8 JSON, including exact key ordering."""
        if type(raw) not in (bytes, str):
            raise ContractError('SegmentRef JSON must be immutable bytes or text')
        if len(raw) > SEGMENT_REF_BYTES:
            raise ContractError('SegmentRef exceeds 4096 encoded bytes')
        try:
            encoded = raw.encode('utf-8') if type(raw) is str else raw
            if len(encoded) > SEGMENT_REF_BYTES:
                raise ContractError('SegmentRef exceeds 4096 encoded bytes')
            value = json.loads(encoded.decode('utf-8'), object_pairs_hook=_pairs,
                               parse_constant=_nonfinite)
        except (UnicodeError, ValueError, RecursionError) as exc:
            if isinstance(exc, ContractError):
                raise
            raise ContractError('invalid SegmentRef JSON') from exc
        result = cls.from_wire(value)
        if result.to_json() != encoded:
            raise ContractError('SegmentRef JSON is not in canonical form')
        return result


def validate_segment_budget(*, logical_bytes: int, chunk_references: int,
                            manifest_bytes: int, metadata_bytes: int) -> None:
    """Check declared per-put totals; callers must measure complete encoded data.

    Logical bytes and references include external data and every repeated mention.
    This neither authenticates those totals nor bounds a whole segmented record.
    """
    for value, name, maximum in (
            (logical_bytes, 'logical_bytes', SEGMENT_BYTES),
            (chunk_references, 'chunk_references', SEGMENT_CHUNK_REFERENCES),
            (manifest_bytes, 'manifest_bytes', SEGMENT_MANIFEST_BYTES),
            (metadata_bytes, 'metadata_bytes', ROOT_METADATA_MAX)):
        _uint(value, name)
        if value > maximum:
            raise ContractError(name + ' exceeds the per-put contract')
    if metadata_bytes > manifest_bytes:
        raise ContractError('metadata cannot exceed its complete manifest')
    if logical_bytes > chunk_references * NATIVE_CHUNK_BYTES:
        raise ContractError('chunk references cannot cover the declared logical bytes')
