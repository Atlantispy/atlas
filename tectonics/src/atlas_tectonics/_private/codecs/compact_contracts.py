"""Pure, immutable Step 3 wire contracts; no storage or scientific authority.

These records describe references, not verified capabilities. A later resolver
must authenticate catalogs, manifests, seals and payloads. Construction performs
no I/O, hashing, codec work, publication or runtime imports.
"""
from __future__ import annotations

from atlas_shared.errors import AtlasError
from contextlib import contextmanager
from dataclasses import dataclass
import json
from typing import cast
from atlas_tectonics.integration.resources import _sha256_pattern as _SHA256


SEGMENT_REF_SCHEMA = 'atlas.segment-ref.v1'
BINDING_INDEX_SCHEMA = 'atlas.binding-index.v1'
NATIVE_CHUNK_BYTES = 64 * 1024
SEGMENT_BYTES = 128 * 1024 * 1024
SEGMENT_CHUNK_REFERENCES = 2048
SEGMENT_MANIFEST_BYTES = 256 * 1024
ROOT_METADATA_MAX = 64 * 1024
SEGMENT_REF_BYTES = 4096
INDEX_FANOUT = 256
INDEX_MAX_DEPTH = 8
CATALOG_BYTES = 1024 * 1024
MAX_OPEN_FILES = 8
RETAINED_BYTES = 256 * 1024 * 1024
SUPPORT_CACHE_BYTES = 128 * 1024 * 1024
FACT_CACHE_BYTES = 64 * 1024 * 1024
PAGE_CACHE_BYTES = 64 * 1024 * 1024
UINT64_MAX = (1 << 64) - 1


class ContractError(ValueError, AtlasError):
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
    return cast(dict, value)


def _canonical(value: dict) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('ascii')
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ContractError('contract is not canonical finite JSON') from exc


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
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
        row = cast(dict, value)
        return cls(row['workflow_id'], row['interval'], row['snapshot_key'])


@dataclass(frozen=True, slots=True)
class LogicalIdentity:
    """Logical schema admission belongs to its caller, not a domain registry here."""

    record_schema: str
    sha256: str
    canonical_bytes: int

    def __post_init__(self) -> None:
        try:
            len(self.record_schema.encode('utf-8'))
        except UnicodeError as exc:
            raise ContractError('record_schema must be valid UTF-8 text') from exc
        _sha(self.sha256, 'logical identity sha256')
        _uint(self.canonical_bytes, 'canonical_bytes')

    def to_wire(self) -> dict:
        return dict(record_schema=self.record_schema, sha256=self.sha256,
                    canonical_bytes=self.canonical_bytes)

    @classmethod
    def from_wire(cls, value: object) -> LogicalIdentity:
        row = cast(dict, value)
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
        _sha(self.digest, 'binding index digest')
        _uint(self.count, 'binding count')

    def to_wire(self) -> dict:
        return dict(schema=self.schema, root_key=self.root_key.to_wire(),
                    digest=self.digest, count=self.count)

    @classmethod
    def from_wire(cls, value: object) -> BindingIndexRef:
        row = cast(dict, value)
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
        _uint(self.logical_bytes, 'logical_bytes')
        _sha(self.merkle_root, 'merkle_root')
        self.to_json()

    def to_wire(self) -> dict:
        """Return a detached mutable wire value without exposing mutable DTO state."""
        return dict(schema=self.schema, root_key=self.root_key.to_wire(),
                    identity=self.identity.to_wire(), logical_bytes=self.logical_bytes,
                    array_bindings=self.array_bindings.to_wire(), merkle_root=self.merkle_root)

    def to_json(self) -> bytes:
        raw = _canonical(self.to_wire())
        return raw

    @classmethod
    def from_wire(cls, value: object) -> SegmentRef:
        row = cast(dict, value)
        return cls(row['schema'], SnapshotLocator.from_wire(row['root_key']),
                   LogicalIdentity.from_wire(row['identity']), row['logical_bytes'],
                   BindingIndexRef.from_wire(row['array_bindings']), row['merkle_root'])

    @classmethod
    def from_json(cls, raw: bytes | str) -> SegmentRef:
        """Accept only bounded canonical UTF-8 JSON, including exact key ordering."""
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
        return result


# Decision 542 (designs/next-producer-open-r1.md): the open of an adopted head proves only while this is true.
# Set true for good by a producer in proof mode (--open-proofs) and by the reader's full core; the tests use
# proofs(). Lower-case: a run-time value, never part of a module's identity.
open_proofs = False


def proving():
    return open_proofs


@contextmanager
def proofs(on=True):
    """Set the switch, then put the old value back. For a caller whose opens run on one thread."""
    global open_proofs
    old, open_proofs = open_proofs, on
    try:
        yield
    finally:
        open_proofs = old
