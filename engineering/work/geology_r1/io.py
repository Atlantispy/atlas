"""Bounded authenticated numeric inputs; unchanged numeric/UNKNOWN semantics."""
import hashlib
import io
import math
from pathlib import Path
import zipfile

import numpy as np
from work.generator_upgrade_r15 import regional

MAX_SOURCE_BYTES = regional.MAX_SOURCE_BYTES
MAX_ARRAY_BYTES = regional.MAX_ARRAY_BYTES
CHUNK_BYTES = 1024**2


def _read(path, sha256, size_bytes, limit, retain):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('absolute source path required')
    if type(limit) is not int or limit < 0:
        raise ValueError('nonnegative byte budget required')
    if size_bytes is not None and (type(size_bytes) is not int or not 0 <= size_bytes <= limit):
        raise ValueError('source exceeds declared byte budget')
    total, digest, parts = 0, hashlib.sha256(), []
    with path.open('rb') as stream:
        if path.stat().st_size > limit:
            raise ValueError('regional source file exceeds byte budget')
        while True:
            # At most one extra byte is requested at the cap to detect growth.
            part = stream.read(min(CHUNK_BYTES, limit-total+1))
            if not part:
                break
            total += len(part)
            if total > limit:
                raise ValueError('regional source file exceeds byte budget')
            digest.update(part)
            if retain:
                parts.append(part)
    if (size_bytes is not None and total != size_bytes) or digest.hexdigest() != sha256:
        raise ValueError('regional source changed; no automatic repin')
    return b''.join(parts) if retain else None


def read_bound(path, sha256, size_bytes=None, *, limit=MAX_SOURCE_BYTES):
    return _read(path, sha256, size_bytes, limit, True)


def verify_bound(path, sha256, size_bytes=None, *, limit=MAX_SOURCE_BYTES):
    """Fresh raw hash/size authentication, not a persistent validation result."""
    _read(path, sha256, size_bytes, limit, False)


def _checked_array(stream, max_array_bytes):
    version = np.lib.format.read_magic(stream)
    readers = {(1, 0): np.lib.format.read_array_header_1_0,
               (2, 0): np.lib.format.read_array_header_2_0}
    if version not in readers:
        raise ValueError('supported NPY numeric header required')
    shape, _, dtype = readers[version](stream)
    if (len(shape) != 2 or min(shape) < 1 or dtype.kind not in 'fi'
            or math.prod(shape)*dtype.itemsize > max_array_bytes):
        raise ValueError('regional decoded array exceeds shape/type/byte budget')
    stream.seek(0)
    return np.load(stream, allow_pickle=False)


def read_field(record, *, max_array_bytes=MAX_ARRAY_BYTES):
    """Decode exactly authenticated bytes with header-first allocation limits."""
    regional.contract.exact(record, ('path', 'sha256', 'array_key', 'grid', 'registration',
                            'unit', 'role', 'reference', 'evidence', 'source_status'), 'regional field')
    regional.label(record['evidence'])
    if record['source_status'] not in regional.STATUSES:
        raise ValueError('regional field is unresolved')
    if type(max_array_bytes) is not int or not 0 <= max_array_bytes <= MAX_ARRAY_BYTES:
        raise ValueError('bounded decoded array allowance required')
    path = Path(record['path'])
    if not path.is_absolute() or path.suffix.lower() not in ('.npy', '.npz'):
        raise ValueError('explicit absolute NPY/NPZ field path required')
    raw = read_bound(path, record['sha256'])
    if path.suffix.lower() == '.npz':
        with zipfile.ZipFile(io.BytesIO(raw)) as loaded:
            if not isinstance(record['array_key'], str):
                raise ValueError('explicit NPZ array key required')
            name = record['array_key']+'.npy'
            if loaded.namelist().count(name) != 1 or loaded.getinfo(name).file_size > max_array_bytes+16384:
                raise ValueError('unique bounded NPZ member required')
            with loaded.open(name) as member:
                return _checked_array(member, max_array_bytes)
    if record['array_key'] is not None:
        raise ValueError('NPY input cannot select an archive key')
    return _checked_array(io.BytesIO(raw), max_array_bytes)


def immutable_array(array):
    """Bytes own storage: callers cannot re-enable writeability on an owner."""
    return np.frombuffer(array.tobytes(order='C'), dtype=array.dtype).reshape(array.shape)
