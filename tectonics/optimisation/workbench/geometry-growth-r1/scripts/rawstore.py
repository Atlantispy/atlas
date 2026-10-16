"""Read-only raw-record access to a COPIED native-joined store.

Every chunk is verified against its typed-chunk key and stored digest, and every
record against its manifest sha256, as in continuation-repair's
inspect_pressure_support.py. Opens with mode=ro&immutable=1. Writes nothing.
"""
from hashlib import sha256
import json
import sqlite3
from pathlib import Path


class RawStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro&immutable=1', uri=True)

    def close(self):
        self.db.close()

    def snapshots(self):
        rows = self.db.execute('SELECT id, body, digest FROM snapshots').fetchall()
        result = {}
        for key, body, digest in rows:
            if sha256(body).hexdigest() != digest:
                raise ValueError('snapshot manifest digest differs: ' + key)
            result[key] = json.loads(body)
        return result

    def array_chunks(self, manifest, ref):
        array = manifest['arrays'][ref['array']]
        if array['dtype'] != '|u1' or array['shape'] != [ref['bytes']]:
            raise ValueError('unexpected raw byte-array layout')
        count, digest = 0, sha256()
        for key in array['chunks']:
            desc, codec, stored, raw = self.db.execute(
                'SELECT descriptor,codec,stored_sha,payload FROM chunks WHERE id=?', (key,)).fetchone()
            if codec != 'raw' or json.loads(desc) != {'dtype': '|u1', 'count': len(raw)}:
                raise ValueError('only exact raw chunks are supported')
            if (sha256(desc + b'\0' + codec.encode() + b'\0' + raw).hexdigest() != stored or
                    sha256(b'atlas-typed-chunk-v1\0' + desc + b'\0' + raw).hexdigest() != key):
                raise ValueError('chunk digest differs')
            count += len(raw)
            digest.update(raw)
            yield raw
        if count != ref['bytes'] or digest.hexdigest() != ref['sha256']:
            raise ValueError('complete record digest differs')

    def record_bytes(self, manifest, ref):
        return b''.join(self.array_chunks(manifest, ref))

    def record(self, manifest, ref):
        return json.loads(self.record_bytes(manifest, ref))

    def numeric_array(self, manifest, name, decode=None):
        """Numeric array by manifest array name, chunk-verified.

        decode(codec, payload, dtype, count) -> raw bytes handles non-raw
        codecs (pass the runtime's own ArrayStore._decode logic). The typed
        chunk key binds the DECODED bytes, so it is checked after decoding.
        """
        import numpy as np
        array = manifest['arrays'][name]
        parts = []
        for key in array['chunks']:
            desc, codec, stored, payload = self.db.execute(
                'SELECT descriptor,codec,stored_sha,payload FROM chunks WHERE id=?', (key,)).fetchone()
            if sha256(desc + b'\0' + codec.encode() + b'\0' + payload).hexdigest() != stored:
                raise ValueError('stored chunk digest differs')
            d = json.loads(desc)
            if codec == 'raw':
                raw = payload
            elif decode is not None:
                raw = decode(codec, payload, np.dtype(d['dtype']), d['count'])
            else:
                raise ValueError('codec needs a decoder: ' + codec)
            if sha256(b'atlas-typed-chunk-v1\0' + desc + b'\0' + raw).hexdigest() != key:
                raise ValueError('decoded chunk identity differs')
            parts.append(np.frombuffer(raw, dtype=d['dtype']))
        flat = np.concatenate(parts) if parts else np.zeros(0, dtype=array['dtype'])
        return flat.reshape(array['shape'])


def refs(value, path=''):
    """Yield (path, ref) for every record-blob reference in manifest metadata."""
    if isinstance(value, dict):
        if set(value) >= {'array', 'bytes', 'sha256'}:
            yield path, value
            return
        for k, v in value.items():
            yield from refs(v, path + '.' + str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from refs(v, path + '[%d]' % i)
