"""Independent, bounded, lossless Zstandard frames for immutable JSON records.

Reuse the installed Zstd library, not the older array/segment/tar container.
The active control remains plain JSON. No dictionaries, concatenated frames,
streaming output growth, codec fallback or package installation is performed.

Stable C API and frame layout: facebook/zstd v1.5.7 lib/zstd.h and
doc/zstd_compression_format.md. The single-pass decoder writes only into the
explicit bounded destination; it allocates no streaming history buffer.
"""
import ctypes as ct
import hashlib
from pathlib import Path
import sys


MAX_RAW_BYTES = 32 * 1024 * 1024
COMPRESSION_LEVEL = 5
_MAGIC = b'\x28\xb5\x2f\xfd'
_CONTENTSIZE_UNKNOWN = 2**64 - 1
_CONTENTSIZE_ERROR = 2**64 - 2
# Public ZSTD_cParameter enum values (lib/zstd.h, v1.5.7).
_PARAMETERS = ((100, COMPRESSION_LEVEL), (200, 1), (201, 1), (202, 0), (400, 0))
_LIBRARY_PATH = (Path(sys.executable).resolve().parent.parent /
                 'native/poppler/Library/bin/zstd.dll')


class CompressionError(ValueError):
    """Malformed/out-of-scope input or an unavailable/changed pinned codec."""


def _digest(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise CompressionError('installed Zstandard library unavailable') from error


_LOADED_SHA256 = _digest(_LIBRARY_PATH)
try:
    _LIBRARY = ct.CDLL(str(_LIBRARY_PATH))
except OSError as error:
    raise CompressionError('installed Zstandard library cannot be loaded') from error


def _bind(name, result, arguments):
    try:
        function = getattr(_LIBRARY, name)
    except AttributeError as error:
        raise CompressionError('installed Zstandard library lacks required stable API: ' + name) from error
    function.restype, function.argtypes = result, arguments
    return function


_version = _bind('ZSTD_versionString', ct.c_char_p, [])
_is_error = _bind('ZSTD_isError', ct.c_uint, [ct.c_size_t])
_error_name = _bind('ZSTD_getErrorName', ct.c_char_p, [ct.c_size_t])
_compress_bound = _bind('ZSTD_compressBound', ct.c_size_t, [ct.c_size_t])
_create_compressor = _bind('ZSTD_createCCtx', ct.c_void_p, [])
_free_compressor = _bind('ZSTD_freeCCtx', ct.c_size_t, [ct.c_void_p])
_set_parameter = _bind('ZSTD_CCtx_setParameter', ct.c_size_t,
                       [ct.c_void_p, ct.c_int, ct.c_int])
_compress = _bind('ZSTD_compress2', ct.c_size_t,
                  [ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.c_char_p, ct.c_size_t])
_create_decompressor = _bind('ZSTD_createDCtx', ct.c_void_p, [])
_free_decompressor = _bind('ZSTD_freeDCtx', ct.c_size_t, [ct.c_void_p])
_decompress = _bind('ZSTD_decompressDCtx', ct.c_size_t,
                    [ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.c_char_p, ct.c_size_t])
_frame_content_size = _bind('ZSTD_getFrameContentSize', ct.c_ulonglong,
                           [ct.c_char_p, ct.c_size_t])
_frame_compressed_size = _bind('ZSTD_findFrameCompressedSize', ct.c_size_t,
                              [ct.c_char_p, ct.c_size_t])
_LOADED_VERSION = _version().decode('ascii')


def _checked(value, operation):
    if _is_error(value):
        raise CompressionError(operation + ': ' + _error_name(value).decode('utf-8'))
    return value


MAX_FRAME_BYTES = _checked(_compress_bound(MAX_RAW_BYTES), 'compressed size bound')
if _digest(_LIBRARY_PATH) != _LOADED_SHA256:
    raise CompressionError('Zstandard library changed while loading')


def identity():
    """Fresh file check against the loaded codec; suitable for parent provenance."""
    if _digest(_LIBRARY_PATH) != _LOADED_SHA256 or _version().decode('ascii') != _LOADED_VERSION:
        raise CompressionError('loaded Zstandard codec differs from installed library')
    return {'schema': 'diadem.native-record-compression.r3',
        'codec': 'zstandard', 'api': 'stdlib-ctypes-stable-single-pass-C-API',
        'version': _LOADED_VERSION, 'library_path': str(_LIBRARY_PATH),
        'library_sha256': _LOADED_SHA256, 'compression_level': COMPRESSION_LEVEL,
        'workers': 0, 'content_checksum': True, 'frame_content_size': True,
        'dictionary': None, 'independent_frames': True,
        'maximum_raw_bytes': MAX_RAW_BYTES, 'maximum_frame_bytes': MAX_FRAME_BYTES}


def encode(raw: bytes) -> bytes:
    """Encode exact bytes as one deterministic checksum/content-size frame."""
    if type(raw) is not bytes or len(raw) > MAX_RAW_BYTES:
        raise CompressionError('raw record must be bytes within the 32 MiB limit')
    identity()
    capacity = _checked(_compress_bound(len(raw)), 'compressed size bound')
    destination = ct.create_string_buffer(capacity)
    context = _create_compressor()
    if not context:
        raise CompressionError('cannot allocate bounded Zstandard compressor context')
    try:
        for parameter, value in _PARAMETERS:
            _checked(_set_parameter(context, parameter, value), 'compression parameter')
        size = _checked(_compress(context, destination, capacity, raw, len(raw)), 'compression')
        if size > capacity or size > MAX_FRAME_BYTES:
            raise CompressionError('compressed frame exceeded declared capacity')
        return destination.raw[:size]
    finally:
        _free_compressor(context)


def decode(frame: bytes, expected_size: int) -> bytes:
    """Decode exactly one bounded frame; reject malformed or extra content."""
    if type(expected_size) is not int or not 0 <= expected_size <= MAX_RAW_BYTES:
        raise CompressionError('expected raw size must be an integer within the 32 MiB limit')
    if type(frame) is not bytes or not 6 <= len(frame) <= MAX_FRAME_BYTES:
        raise CompressionError('compressed frame byte limit or minimum header violated')
    if frame[:4] != _MAGIC:
        raise CompressionError('one standard Zstandard frame required; no skippable frame')
    # Format descriptor bit 2 is the checksum flag, bits 1..0 the dictionary ID.
    if not frame[4] & 4 or frame[4] & 3:
        raise CompressionError('independent frame checksum and absent dictionary ID required')
    identity()
    declared = _frame_content_size(frame, len(frame))
    if declared in (_CONTENTSIZE_UNKNOWN, _CONTENTSIZE_ERROR) or declared != expected_size:
        raise CompressionError('frame content size differs from explicit bounded raw size')
    size = _checked(_frame_compressed_size(frame, len(frame)), 'complete frame required')
    if size != len(frame):
        raise CompressionError('trailing bytes or concatenated frames are not permitted')
    # The destination capacity, not untrusted header content, bounds all output.
    # A one-byte physical buffer permits the valid zero-length frame case.
    destination = ct.create_string_buffer(max(1, expected_size))
    context = _create_decompressor()
    if not context:
        raise CompressionError('cannot allocate bounded Zstandard decompressor context')
    try:
        actual = _checked(_decompress(context, destination, expected_size, frame, len(frame)),
                          'bounded decompression')
        if actual != expected_size:
            raise CompressionError('decoded size differs from expected record size')
        return destination.raw[:actual]
    finally:
        _free_decompressor(context)
