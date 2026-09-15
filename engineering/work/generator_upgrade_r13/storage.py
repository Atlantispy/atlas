"""Bounded event records with a small manifest; exclusive, short-path output."""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
from . import provenance as p
from .year import plain


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate soil JSON key: '+key)
        result[key] = value
    return result


def read_json(path, expected=None):
    return plain(json.loads(p.checked(path, expected), object_pairs_hook=_pairs,
                            parse_constant=lambda value: (_ for _ in ()).throw(
                                ValueError('nonfinite soil JSON: '+value))))


def safe_output(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or path == Path(path.anchor):
        raise ValueError('absolute non-root, non-traversing result directory required')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked/reparse result path refused')
    if path.exists():
        raise ValueError('new result directory required; existing outputs preserved')
    if not path.parent.is_dir():
        raise ValueError('existing result parent directory required')
    return path


def save(output, spec, result):
    root = safe_output(output)
    value = deepcopy(result)
    scientific = value['scientific']
    rows = scientific['events']
    if scientific['checkpoint']['state']['accepted_events'] != rows:
        raise ValueError('saved coupled event/checkpoint inventory differs')
    files = {'recipe.json': spec, 'execution.json': value['execution']}
    refs = []
    for index, row in enumerate(rows):
        name = f'e{index:04d}.json'
        files[name] = row
        refs.append({'file': name, 'sha256': p.sha(row)})
    scientific['events'] = refs
    scientific['checkpoint']['state']['accepted_events'] = refs
    files['science.json'] = scientific
    raw_files = {name: p.encoded(plain(item)) for name, item in files.items()}
    manifest = {'schema': 'diadem.coupled-soil-files.r13',
                'files': {name: p.sha(item) for name, item in files.items()}}
    if any(len(raw) > p.shared.LIMIT for raw in raw_files.values()) or len(p.encoded(manifest)) > p.shared.LIMIT:
        Journal(root, spec).commit(result)
        if load(root) != {'recipe': spec, **result}:
            raise ValueError('coupled soil persisted readback differs')
        return root
    safe_output(root)
    root.mkdir(exist_ok=False)
    for name, raw in raw_files.items():
        with (root / name).open('xb') as stream:
            stream.write(raw)
    with (root / 'manifest.json').open('xb') as stream:
        stream.write(p.encoded(manifest))
    if load(root) != {'recipe': spec, **result}:
        raise ValueError('coupled soil persisted readback differs')
    return root


def load(root):
    root = Path(root)
    if (root / 'latest.json').exists() or (root / 'latest.json').is_symlink():
        return _load_journal(root)
    manifest = read_json(root / 'manifest.json')
    if (type(manifest) is not dict or set(manifest) != {'schema', 'files'}
            or manifest['schema'] != 'diadem.coupled-soil-files.r13'
            or type(manifest['files']) is not dict):
        raise ValueError('exact soil file manifest required')
    files = manifest['files']
    required = {'recipe.json', 'execution.json', 'science.json'}
    if not required <= set(files) or len(files) > 8195:
        raise ValueError('bounded complete soil file inventory required')
    if any(name not in required and not re.fullmatch(r'e\d{4}\.json', name) for name in files):
        raise ValueError('safe direct soil event filenames required')
    values = {name: read_json(root / name, digest) for name, digest in files.items()}
    scientific = values['science.json']
    refs = scientific['events']
    if (scientific['checkpoint']['state']['accepted_events'] != refs
            or [row['file'] for row in refs] != [f'e{i:04d}.json' for i in range(len(refs))]
            or set(files) != required | {row['file'] for row in refs}
            or any(set(row) != {'file', 'sha256'} or files[row['file']] != row['sha256'] for row in refs)):
        raise ValueError('saved soil event reference inventory differs')
    rows = [values[row['file']] for row in refs]
    scientific['events'] = rows
    scientific['checkpoint']['state']['accepted_events'] = deepcopy(rows)
    cp = scientific['checkpoint']
    if cp['state_sha256'] != p.sha(cp['state']) or cp['recipe_sha256'] != p.sha(values['recipe.json']):
        raise ValueError('saved coupled soil checkpoint/recipe differs')
    return {'recipe': values['recipe.json'], 'scientific': scientific,
            'execution': values['execution.json']}


JOURNAL = 'diadem.coupled-soil-journal.r13'
CHUNKS = JOURNAL + '.chunks'
MAX_PAYLOAD = 2**31
MAX_RECORDS = 1000000


def _decode(raw):
    return plain(json.loads(raw, object_pairs_hook=_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite soil JSON: '+value))))


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _read_blob(root, ref, depth=0):
    if depth > 24 or type(ref) is not dict or not _hash(ref.get('sha256')):
        raise ValueError('bounded exact journal reference required')
    if set(ref) == {'file', 'sha256'}:
        if type(ref['file']) is not str or not re.fullmatch(r'f\d{8}\.json', ref['file']):
            raise ValueError('safe direct journal filename required')
        return p.checked(root / ref['file'], ref['sha256'])
    if set(ref) != {'tree', 'sha256', 'byte_length'} or type(ref['byte_length']) is not int or not 0 < ref['byte_length'] <= MAX_PAYLOAD:
        raise ValueError('bounded exact chunk-tree reference required')
    index = _decode(_read_blob(root, ref['tree'], depth+1))
    if (type(index) is not dict or set(index) != {'schema', 'sha256', 'byte_length', 'chunks'}
            or index['schema'] != CHUNKS or index['sha256'] != ref['sha256']
            or index['byte_length'] != ref['byte_length'] or type(index['chunks']) is not list
            or not 1 <= len(index['chunks']) <= MAX_RECORDS):
        raise ValueError('chunk index binding differs')
    parts, length = [], 0
    for part in index['chunks']:
        if type(part) is not dict or set(part) != {'file', 'sha256'}:
            raise ValueError('direct bounded chunk records required')
        item = _decode(_read_blob(root, part, depth+1))
        if type(item) is not dict or set(item) != {'data'} or type(item['data']) is not str:
            raise ValueError('exact encoded chunk required')
        try:
            raw = base64.b64decode(item['data'], validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError('invalid encoded soil chunk') from exc
        if not raw or base64.b64encode(raw).decode('ascii') != item['data']:
            raise ValueError('canonical nonempty encoded soil chunk required')
        length += len(raw)
        if length > ref['byte_length']:
            raise ValueError('chunk payload length exceeded')
        parts.append(raw)
    raw = b''.join(parts)
    if len(raw) != ref['byte_length'] or _digest(raw) != ref['sha256']:
        raise ValueError('reconstructed soil payload differs')
    return raw


def _read_value(root, ref):
    raw = _read_blob(root, ref)
    value = _decode(raw)
    if p.encoded(value) != raw:
        raise ValueError('canonical journal JSON required')
    return value


def _checkpoint(spec, scientific):
    rows, cp = scientific['events'], scientific['checkpoint']
    if (type(rows) is not list or len(rows) > 8192
            or cp['state']['accepted_events'] != rows
            or cp['state'].get('completed_events') != len(rows)
            or scientific.get('completed_events') != len(rows)
            or cp['state_sha256'] != p.sha(cp['state'])
            or cp['recipe_sha256'] != p.sha(spec)):
        raise ValueError('saved coupled soil checkpoint/recipe/event inventory differs')
    return rows


def _load_journal(root):
    pointer = read_json(root / 'latest.json')
    if (type(pointer) is not dict or set(pointer) != {'schema', 'generation', 'manifest'}
            or pointer['schema'] != JOURNAL or type(pointer['generation']) is not int
            or not 0 <= pointer['generation'] < MAX_RECORDS):
        raise ValueError('exact journal latest pointer required')
    manifest = _read_value(root, pointer['manifest'])
    if (type(manifest) is not dict or set(manifest) != {'schema', 'generation', 'recipe', 'scientific', 'execution'}
            or manifest['schema'] != JOURNAL or manifest['generation'] != pointer['generation']):
        raise ValueError('journal snapshot manifest differs')
    spec = _read_value(root, manifest['recipe'])
    scientific = _read_value(root, manifest['scientific'])
    execution = _read_value(root, manifest['execution'])
    refs = scientific['events']
    if type(refs) is not list or len(refs) > 8192 or scientific['checkpoint']['state']['accepted_events'] != refs:
        raise ValueError('journal event reference inventory differs')
    rows = [_read_value(root, ref) for ref in refs]
    scientific['events'] = rows
    scientific['checkpoint']['state']['accepted_events'] = deepcopy(rows)
    _checkpoint(spec, scientific)
    return {'recipe': spec, 'scientific': scientific, 'execution': execution}


class Journal:
    """Single-owner append-only event payloads with atomic snapshot publication.

    Commit verifies each newly written immutable record; earlier verified event
    receipts are reused by this instance. Public load always verifies the whole
    selected snapshot. A failed commit may leave unreferenced immutable records,
    but never replaces the previous good pointer or rewrites an earlier event.
    No constructor opens an existing run, so separate writers cannot share it.
    """
    def __init__(self, output, spec):
        self.root = safe_output(output)
        if len(str(self.root / 'f99999999.json').encode('utf-16-le'))//2 >= 260:
            raise ValueError('shorter journal output path required')
        self.spec = deepcopy(plain(spec))
        self._next = 0
        self._generation = 0
        self._refs, self._hashes = [], []
        self._lock = threading.Lock()
        self.root.mkdir(exist_ok=False)
        info = self.root.stat()
        self._owner = (info.st_dev, info.st_ino)
        self._recipe = self._write_value(self.spec)

    def _owned(self):
        for path in (self.root, *self.root.parents):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked/reparse journal path refused')
        info = self.root.stat()
        if (info.st_dev, info.st_ino) != self._owner:
            raise ValueError('journal output directory ownership changed')

    def _write_raw(self, raw):
        self._owned()
        if len(raw) > p.shared.LIMIT or self._next >= MAX_RECORDS:
            raise ValueError('bounded journal record inventory required')
        name = f'f{self._next:08d}.json'
        self._next += 1
        with (self.root / name).open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        ref = {'file': name, 'sha256': _digest(raw)}
        if p.checked(self.root / name, ref['sha256']) != raw:
            raise ValueError('journal new record readback differs')
        return ref

    def _write_blob(self, raw):
        if not 0 < len(raw) <= MAX_PAYLOAD or p.shared.LIMIT < 512:
            raise ValueError('bounded journal payload/record capacity required')
        if len(raw) <= p.shared.LIMIT:
            return self._write_raw(raw)
        # ASCII base64 keeps arbitrary UTF-8 code points and JSON scalar values
        # exact even when a byte cut lands inside an escape or Unicode sequence.
        size = (p.shared.LIMIT-32)//4*3
        refs = [self._write_raw(p.encoded({'data': base64.b64encode(raw[i:i+size]).decode('ascii')}))
                for i in range(0, len(raw), size)]
        digest = _digest(raw)
        index = {'schema': CHUNKS, 'sha256': digest, 'byte_length': len(raw), 'chunks': refs}
        return {'tree': self._write_blob(p.encoded(index)), 'sha256': digest, 'byte_length': len(raw)}

    def _write_value(self, value):
        raw = p.encoded(plain(value))
        ref = self._write_blob(raw)
        if _read_blob(self.root, ref) != raw:
            raise ValueError('new reconstructed journal record differs')
        return ref

    def _publish(self, pointer):
        # Both paths belong to this exclusively created directory. The unique
        # staging name is never reused after an interrupted/failed replacement.
        ref = self._write_value(pointer)
        if set(ref) != {'file', 'sha256'}:
            raise ValueError('compact journal pointer required')
        self._owned()
        os.replace(self.root / ref['file'], self.root / 'latest.json')

    def commit(self, result):
        if not self._lock.acquire(blocking=False):
            raise ValueError('one journal commit at a time required')
        try:
            self._owned()
            if type(result) is not dict or set(result) != {'scientific', 'execution'}:
                raise ValueError('exact coupled result required')
            plain(result)
            rows = _checkpoint(self.spec, result['scientific'])
            if len(rows) < len(self._refs):
                raise ValueError('journal accepted event prefix cannot shrink')
            hashes = [p.sha(row) for row in rows]
            if hashes[:len(self._hashes)] != self._hashes:
                raise ValueError('journal accepted event prefix changed')
            refs = self._refs + [self._write_value(row) for row in rows[len(self._refs):]]
            scientific = {key: deepcopy(value) for key, value in result['scientific'].items()
                          if key not in ('events', 'checkpoint')}
            scientific['events'] = deepcopy(refs)
            cp = result['scientific']['checkpoint']
            scientific['checkpoint'] = {key: deepcopy(value) for key, value in cp.items() if key != 'state'}
            scientific['checkpoint']['state'] = {key: deepcopy(value) for key, value in cp['state'].items() if key != 'accepted_events'}
            scientific['checkpoint']['state']['accepted_events'] = deepcopy(refs)
            manifest = {'schema': JOURNAL, 'generation': self._generation, 'recipe': self._recipe,
                        'scientific': self._write_value(scientific),
                        'execution': self._write_value(result['execution'])}
            pointer = {'schema': JOURNAL, 'generation': self._generation,
                       'manifest': self._write_value(manifest)}
            self._publish(pointer)
            self._refs, self._hashes = refs, hashes
            self._generation += 1
            return self.root
        finally:
            self._lock.release()
