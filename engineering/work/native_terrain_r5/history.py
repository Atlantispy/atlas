"""Independent ordered histories over shared immutable R3 Zstandard frames.

Only closed frame storage changes: one objects/<frame SHA256>.zst object may
serve multiple independently appendable histories. Every reference retains its
logical hash, sequence, codec and authenticated summary. Existing objects must
match exact bytes and are never replaced. No source-file hard links, deletion,
garbage collection, recompression at import or persisted verification cache.
The explicit store is a shared checkpoint dependency, not a self-contained
checkpoint directory; the session/export layer owns that distinction.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys

from work.native_terrain_r3 import history as retained


compression = retained.compression
MAX_ROWS, MAX_RAW_BYTES = retained.MAX_ROWS, retained.MAX_RAW_BYTES
MAX_SUMMARY_BYTES = retained.MAX_SUMMARY_BYTES
RAW_SCHEMA = retained.RAW_SCHEMA
REF_SCHEMA = 'diadem.shared-native-history-reference.r5'
_encoded, _parse, _summary = retained._encoded, retained._parse, retained._summary
_safe, _read, _immutable = retained._safe, retained._read, retained._immutable
_canonical = retained._canonical


def _verify_source():
    module = sys.modules.get(__name__)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != getattr(module, '_R12_EXECUTED_SHA256', None):
        raise ValueError('executed shared-history source differs; no repin')
    retained._verify_source()


def _object_path(frame_sha256):
    return 'objects/' + frame_sha256 + '.zst'


@dataclass(frozen=True, slots=True)
class _Entry:
    sequence: int
    path: str
    raw_sha256: str
    raw_size_bytes: int
    frame_sha256: str
    frame_size_bytes: int
    storage_schema: str
    storage_size_bytes: int
    summary_bytes: bytes
    codec_bytes: bytes

    def reference(self):
        return {'schema': REF_SCHEMA, 'sequence': self.sequence, 'path': self.path,
            'raw_sha256': self.raw_sha256, 'raw_size_bytes': self.raw_size_bytes,
            'frame_sha256': self.frame_sha256, 'frame_size_bytes': self.frame_size_bytes,
            'storage_schema': self.storage_schema, 'storage_size_bytes': self.storage_size_bytes,
            'summary': _parse(self.summary_bytes), 'codec': _parse(self.codec_bytes)}


def _entry(ref, sequence, codec_bytes):
    expected = {'schema', 'sequence', 'path', 'raw_sha256', 'raw_size_bytes',
        'frame_sha256', 'frame_size_bytes', 'storage_schema', 'storage_size_bytes', 'summary', 'codec'}
    if (type(ref) is not dict or set(ref) != expected or ref['schema'] != REF_SCHEMA
            or type(ref['sequence']) is not int or ref['sequence'] != sequence
            or any(type(ref[key]) is not str or not retained._HEX.fullmatch(ref[key])
                   for key in ('raw_sha256', 'frame_sha256'))
            or ref['path'] != _object_path(ref['frame_sha256'])
            or ref['storage_schema'] != RAW_SCHEMA
            or _encoded(ref['codec']) != codec_bytes):
        raise ValueError('shared archive reference identity/order/path/codec differs')
    for name, limit in (('raw_size_bytes', MAX_RAW_BYTES), ('storage_size_bytes', MAX_RAW_BYTES),
                        ('frame_size_bytes', compression.MAX_FRAME_BYTES)):
        if type(ref[name]) is not int or not 0 < ref[name] <= limit:
            raise ValueError('archive reference size exceeds explicit byte bounds')
    if ref['storage_size_bytes'] != ref['raw_size_bytes']:
        raise ValueError('canonical raw storage size differs from logical row size')
    return _Entry(sequence, ref['path'], ref['raw_sha256'], ref['raw_size_bytes'],
        ref['frame_sha256'], ref['frame_size_bytes'], ref['storage_schema'],
        ref['storage_size_bytes'], _encoded(ref['summary'], MAX_SUMMARY_BYTES), codec_bytes)


def _decoded(frame, entry, *, authenticate_summary=False):
    if hashlib.sha256(frame).hexdigest() != entry.frame_sha256:
        raise ValueError('immutable compressed frame hash differs')
    raw = compression.decode(frame, entry.storage_size_bytes)
    if len(raw) != entry.raw_size_bytes or hashlib.sha256(raw).hexdigest() != entry.raw_sha256:
        raise ValueError('canonical logical history SHA256/size differs')
    if authenticate_summary:
        row = _parse(raw)
        if _encoded(row) != raw:
            raise ValueError('archive logical JSON is not canonical')
        if _summary(row) != entry.summary_bytes:
            raise ValueError('archive summary differs from authenticated logical row')
    return raw


class History:
    """Independent appendable order; immutable frame objects may be shared."""
    __slots__ = ('_root', '_entries', '_codec_bytes')

    def __setattr__(self, name, value):
        raise AttributeError('history fields are immutable; use append on an independent container')

    def __delattr__(self, name):
        raise AttributeError('history fields cannot be deleted')

    def __init__(self, root):
        _verify_source()
        object.__setattr__(self, '_root', _safe(root))
        self._root.mkdir(parents=True, exist_ok=True)
        _safe(self._root, required=True, directory=True)
        object.__setattr__(self, '_entries', ())
        object.__setattr__(self, '_codec_bytes', _encoded(compression.identity()))

    @property
    def root(self):
        return self._root

    @property
    def refs(self):
        return self.to_refs()

    def to_refs(self):
        _verify_source()
        return [entry.reference() for entry in self._entries]

    def __len__(self):
        return len(self._entries)

    def __iter__(self):
        _verify_source()
        return (_parse(entry.summary_bytes) for entry in self._entries)

    def __getitem__(self, index):
        _verify_source()
        if type(index) is slice:
            return [_parse(entry.summary_bytes) for entry in self._entries[index]]
        return _parse(self._entries[index].summary_bytes)

    def __deepcopy__(self, memo):
        _verify_source()
        following = object.__new__(type(self))
        object.__setattr__(following, '_root', self._root)
        object.__setattr__(following, '_entries', self._entries)
        object.__setattr__(following, '_codec_bytes', self._codec_bytes)
        memo[id(self)] = following
        return following

    def _objects(self):
        folder = _safe(self._root / 'objects')
        folder.mkdir(exist_ok=True)
        return _safe(folder, required=True, directory=True)

    @classmethod
    def from_rows(cls, root, rows):
        history = cls(root)
        for row in rows:
            history.append(row)
        return history

    @classmethod
    def from_refs(cls, root, refs):
        _verify_source()
        _safe(root, required=True, directory=True)
        if type(refs) not in (tuple, list) or len(refs) > MAX_ROWS:
            raise ValueError('bounded ordered archive references required')
        history = cls(root)
        entries = tuple(_entry(ref, i, history._codec_bytes) for i, ref in enumerate(refs, 1))
        for entry in entries:
            history._raw(entry, authenticate_summary=True)
        object.__setattr__(history, '_entries', entries)
        return history

    @classmethod
    def from_history(cls, source, store_root):
        """Authenticate and copy/reuse exact existing frames, never recompress.

        Input history order and full logical-row/summary association are checked
        before each immutable publication. The caller owns the source control's
        complete scientific/execution binding. Prior objects remain if a later
        row fails; no incomplete History is returned and no evidence is deleted.
        """
        _verify_source()
        if type(source) not in (retained.History, History):
            raise ValueError('exact R3 or R5 history required for shared import')
        destination = _safe(store_root)
        source_root, target_root = source.root.resolve(), destination.resolve()
        if type(source) is retained.History and (source_root == target_root
                or source_root in target_root.parents or target_root in source_root.parents):
            raise ValueError('shared store must not overlap preserved predecessor archive')
        history = cls(destination)
        if source._codec_bytes != history._codec_bytes:
            raise ValueError('incoming archive compression identity changed')
        source_entries = source._entries
        if len(source_entries) > MAX_ROWS:
            raise ValueError('bounded ordered archive references required')
        history._objects()
        entries = []
        entry_reader = retained._entry if type(source) is retained.History else _entry
        for sequence, previous in enumerate(source_entries, 1):
            prior = entry_reader(previous.reference(), sequence, history._codec_bytes)
            frame = _read(source.root / prior.path, prior.frame_size_bytes)
            _decoded(frame, prior, authenticate_summary=True)
            entry = _Entry(sequence, _object_path(prior.frame_sha256), prior.raw_sha256,
                prior.raw_size_bytes, prior.frame_sha256, prior.frame_size_bytes,
                RAW_SCHEMA, prior.storage_size_bytes, prior.summary_bytes, history._codec_bytes)
            _immutable(history.root / entry.path, frame)
            entries.append(entry)
        if source._entries is not source_entries:
            raise ValueError('source history changed during shared import')
        _verify_source()
        object.__setattr__(history, '_entries', tuple(entries))
        return history

    def _raw(self, entry, *, authenticate_summary=False):
        if self._codec_bytes != entry.codec_bytes:
            raise ValueError('archive compression identity changed')
        frame = _read(self._root / entry.path, entry.frame_size_bytes)
        return _decoded(frame, entry, authenticate_summary=authenticate_summary)

    def iter_raw(self):
        _verify_source()
        for entry in self._entries:
            yield self._raw(entry)

    def materialize(self):
        return [_parse(raw) for raw in self.iter_raw()]

    def append(self, row):
        _verify_source()
        if len(self._entries) >= MAX_ROWS:
            raise ValueError('retained 256-row history resource boundary exceeded')
        if _encoded(compression.identity()) != self._codec_bytes:
            raise ValueError('archive compression identity changed')
        raw, direct = _canonical(row, MAX_RAW_BYTES)
        logical = row if direct else _parse(raw)
        summary = _summary(logical)
        frame = compression.encode(raw)
        digest = hashlib.sha256(raw).hexdigest()
        frame_digest = hashlib.sha256(frame).hexdigest()
        entry = _Entry(len(self._entries) + 1, _object_path(frame_digest), digest, len(raw),
            frame_digest, len(frame), RAW_SCHEMA, len(raw), summary, self._codec_bytes)
        self._objects()
        if compression.decode(frame, len(raw)) != raw:
            raise ArithmeticError('lossless archive encoding failed exact reconstruction')
        _immutable(self._root / entry.path, frame)
        object.__setattr__(self, '_entries', (*self._entries, entry))
