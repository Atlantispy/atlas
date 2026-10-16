"""WP10 exact-source transform; never edits or repins its input.

Place the reviewed compact-helper directory on sys.path before import.
Only the frozen composed-r1 source is accepted. Runtime integration is opt-in.
"""
from __future__ import annotations

import hashlib

SOURCE_SHA256 = '181180bc5c90ca7c47ca8b13a82d1d352d9c23a32acff85f6f485eb8a953524d'


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('WP10 storage source anchor is absent or ambiguous')
    return source.replace(old, new, 1)


def transform(source: str) -> str:
    if type(source) is not str or hashlib.sha256(source.encode('utf-8')).hexdigest() != SOURCE_SHA256:
        raise ValueError('WP10 storage source drift: frozen SHA-256 required')
    source = _replace(source,
        '            def capture(value, dtype=None, count=None):',
        '            def capture(value, dtype=None, count=None, prepared=None):')
    source = _replace(source,
        "                raw = np.asarray(a, dtype=dt, order='C').tobytes()",
        "                raw = (np.asarray(a, dtype=dt, order='C').tobytes()\n"
        "                       if prepared is None else prepared[0])")
    source = _replace(source,
        '                codec, payload = self._encode(raw, dt)',
        '                codec, payload = (self._encode(raw, dt, array_name=name)\n'
        '                                  if prepared is None else prepared[1:])')
    source = _replace(source,
        '                    for start in range(0, a.size, width):\n'
        '                        ids.append(capture(flat[start:start+width]))',
        '                    if self._codec_parallel_enabled():\n'
        '                        pieces = (flat[start:start+width] for start in range(0, a.size, width))\n'
        '                        with self._codec_prepare(pieces, dt, name, cancel) as prepared_chunks:\n'
        '                            for piece, prepared in prepared_chunks:\n'
        '                                ids.append(capture(piece, prepared=prepared))\n'
        '                    else:\n'
        '                        for start in range(0, a.size, width):\n'
        '                            ids.append(capture(flat[start:start+width]))')
    return source + '\n\n# WP10: separately reviewable, bounded optional codec runtime.\nfrom storage_codec_runtime import install_storage as _install_wp10_codecs\n_install_wp10_codecs(globals())\n'


def transform_bytes(source: bytes) -> bytes:
    if type(source) is not bytes or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('WP10 storage source drift: frozen SHA-256 required')
    return transform(source.decode('utf-8')).encode('utf-8')
