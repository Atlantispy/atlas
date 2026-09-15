"""Archive-backed accepted history with unchanged canonical logical rows.

Only closed immutable records are compressed. Iteration returns fresh compact
validation summaries, not full scientific receipts. iter_raw rereads and checks
every requested frame; materialize is an explicit compatibility operation.
Zstandard repetition references provide lossless deduplication, never a science edit.
"""
from dataclasses import dataclass
from fractions import Fraction as F
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from . import compression

MAX_ROWS = 256
MAX_RAW_BYTES = 32*1024*1024
MAX_SUMMARY_BYTES = 64*1024
REF_SCHEMA = 'diadem.closed-native-history-reference.r3'
RAW_SCHEMA = 'diadem.canonical-json-record.r1'
_HEX = re.compile(r'[0-9a-f]{64}\Z')


def _verify_source():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != globals().get('_R12_EXECUTED_SHA256'):
        raise ValueError('executed archive history source differs; no repin')


def _plain(value):
    if type(value) is F:
        return str(value)
    if type(value) is dict:
        return {str(key): _plain(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_plain(item) for item in value]
    return value


def _direct_json(value):
    """Check the producer shape without copying its shared dict/list objects.

    Each distinct container is visited once. Unusual subclasses and non-string
    keys retain the original normalisation path, including key collisions.
    The JSON encoder itself still rejects circular or nonfinite values.
    """
    seen = set()
    def visit(item):
        kind = type(item)
        if kind in (dict, list, tuple):
            identity = id(item)
            if identity in seen:
                return True
            seen.add(identity)
            if kind is dict:
                return all(type(key) is str and visit(child) for key, child in item.items())
            return all(visit(child) for child in item)
        return kind in (str, int, float, bool, type(None), F)
    return visit(value)


def _fraction_json(value):
    if type(value) is F:
        return str(value)
    raise TypeError('unsupported direct canonical JSON value: '+type(value).__name__)


def _canonical(value, limit):
    direct = _direct_json(value)
    if direct:
        # The C encoder consumes the original shared containers directly; only
        # Fraction leaves need conversion. No expanded intermediate tree exists.
        text = json.dumps(value, default=_fraction_json, sort_keys=True, separators=(',', ':'), allow_nan=False)
    else:
        text = json.dumps(_plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False)
    raw = text.encode('utf-8')
    if len(raw) > limit:
        raise ValueError('canonical record exceeds its explicit byte limit')
    return raw, direct


def _encoded(value, limit=MAX_RAW_BYTES):
    return _canonical(value, limit)[0]


def _parse(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON key in archived record')
            value[key] = item
        return value
    def invalid(value):
        raise ValueError('nonfinite JSON record: '+value)
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid or over-deep UTF-8 JSON record') from error


def _safe(path, *, required=False, directory=False):
    path = Path(path).absolute()
    if '..' in path.parts or any(':' in part for part in path.parts[1:]):
        raise ValueError('archive path traversal or alternate stream refused')
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('archive symlink or reparse point refused')
        if cursor != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError('archive parent is not a directory')
    if required:
        info = path.lstat()
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise ValueError('archive target has the wrong file type')
    return path


def _read(path, size):
    path = _safe(path, required=True)
    before = path.stat()
    if before.st_size != size or not 0 < size <= compression.MAX_FRAME_BYTES:
        raise ValueError('compressed record size differs or exceeds its byte limit')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(size+1)
        after = os.fstat(stream.fileno())
    following = _safe(path, required=True).stat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if len(raw) != size or not identity(before) == identity(opened) == identity(after) == identity(following):
        raise ValueError('compressed record changed during read')
    return raw


def _immutable(path, raw):
    """Publish a complete closed row exclusively; never replace old evidence."""
    path = _safe(path)
    if path.exists():
        if _read(path, len(raw)) != raw:
            raise ValueError('existing immutable archive differs')
        return
    _safe(path.parent, required=True, directory=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix='.native-history-', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _safe(path.parent, required=True, directory=True)
        _safe(path)
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if _read(path, len(raw)) != raw:
                raise ValueError('existing immutable archive differs')
    finally:
        temporary.unlink(missing_ok=True)


def _summary(row):
    if type(row) is not dict:
        raise ValueError('complete accepted-history dictionary required')
    try:
        summary = {key: row[key] for key in ('operation_id', 'start_year', 'duration_years',
                   'parent_state_sha256', 'state_sha256', 'diagnostics')}
        if type(row['substeps']) not in (tuple, list) or len(row['substeps']) != 2:
            raise ValueError('accepted history requires exactly two substeps')
        summary['substeps'] = [{
            'hillslope': {key: substep['hillslope'][key] for key in ('duration_years', 'total_bulk_allocation_error_m3')},
            'surface_runoff_m3': substep['surface_runoff_m3'],
            'surface_water_exported_m3': substep['surface_water_exported_m3'],
            'numeric_compaction': {'total_l1_units': substep['numeric_compaction']['total_l1_units']}}
            for substep in row['substeps']]
    except (KeyError, TypeError) as error:
        raise ValueError('accepted history lacks a required validation-summary field') from error
    return _encoded(summary, MAX_SUMMARY_BYTES)


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
            or any(type(ref[key]) is not str or not _HEX.fullmatch(ref[key]) for key in ('raw_sha256', 'frame_sha256'))
            or ref['path'] != f"history/{sequence:06d}-{ref['raw_sha256']}.json.zst"
            or ref['storage_schema'] != RAW_SCHEMA
            or _encoded(ref['codec']) != codec_bytes):
        raise ValueError('archive reference identity/order/path/codec differs')
    for name, limit in (('raw_size_bytes', MAX_RAW_BYTES), ('storage_size_bytes', MAX_RAW_BYTES),
                        ('frame_size_bytes', compression.MAX_FRAME_BYTES)):
        if type(ref[name]) is not int or not 0 < ref[name] <= limit:
            raise ValueError('archive reference size exceeds explicit byte bounds')
    return _Entry(sequence, ref['path'], ref['raw_sha256'], ref['raw_size_bytes'],
                  ref['frame_sha256'], ref['frame_size_bytes'], ref['storage_schema'],
                  ref['storage_size_bytes'], _encoded(ref['summary'], MAX_SUMMARY_BYTES), codec_bytes)


class History:
    """Independent appendable container over immutable authenticated entries."""
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

    def _raw(self, entry, *, authenticate_summary=False):
        if self._codec_bytes != entry.codec_bytes:
            raise ValueError('archive compression identity changed')
        frame = _read(self._root/entry.path, entry.frame_size_bytes)
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
        # Direct producer records need no full encoded/decoded copy merely to
        # select their small summary. Legacy key coercion still authenticates
        # the normalised logical record, not the original mixed-key container.
        logical = row if direct else _parse(raw)
        summary = _summary(logical)
        frame = compression.encode(raw)
        sequence = len(self._entries)+1
        digest = hashlib.sha256(raw).hexdigest()
        entry = _Entry(sequence, f'history/{sequence:06d}-{digest}.json.zst', digest, len(raw),
            hashlib.sha256(frame).hexdigest(), len(frame), RAW_SCHEMA, len(raw), summary, self._codec_bytes)
        folder = _safe(self._root/'history')
        folder.mkdir(exist_ok=True)
        _safe(folder, required=True, directory=True)
        # Check our encoded representation before publication; existing paths
        # must also match exactly, including the complete compressed frame.
        if compression.decode(frame, len(raw)) != raw:
            raise ArithmeticError('lossless archive encoding failed exact reconstruction')
        _immutable(self._root/entry.path, frame)
        object.__setattr__(self, '_entries', (*self._entries, entry))
