"""Strict bounded joint checkpoints and exclusive R4 reference artefacts.

Checksums bind a representation, not scientific validity. The R4 driver must
replay the complete joint state before accepting a restored checkpoint.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat

MAX_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 48
MAX_ITEMS = 200000
TASK = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = TASK / 'outputs/generator-upgrade-r4'
CHECKPOINT_SCHEMA = 'diadem.climate-terrain-water-soil-checkpoint.r4'
ARTIFACT_SCHEMA = 'diadem.climate-terrain-water-soil-artifact.r4'
PRODUCT_NAMES = frozenset(('recipe.json', 'result.json', 'checkpoint.json'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('exact SHA256 required')
    return value


def _structure(value, depth=0, budget=None):
    if budget is None:
        budget = [MAX_ITEMS]
    budget[0] -= 1
    if depth > MAX_DEPTH or budget[0] < 0:
        raise ValueError('JSON resource envelope exceeded')
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise ValueError('string JSON keys required')
        for child in value.values():
            _structure(child, depth + 1, budget)
    elif type(value) is list:
        for child in value:
            _structure(child, depth + 1, budget)
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ValueError('only explicit JSON values are serialisable')


def encoded(value):
    _structure(value)
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                     allow_nan=False, ensure_ascii=True).encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('JSON byte envelope exceeded')
    return raw


def decoded(raw):
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise ValueError('bounded JSON bytes required')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def bad(value):
        raise ValueError('nonfinite JSON constant')

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=bad)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('invalid JSON representation') from exc
    encoded(value)  # Includes exponent overflow and the post-parse shape limit.
    return value


def plain_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute non-traversing path required')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked/reparse path refused')
    return path


def read_json(path):
    path = plain_path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('bounded regular JSON file required')
    return decoded(path.read_bytes())


def write_json(path, value):
    path = plain_path(path)
    raw = encoded(value)
    with path.open('xb') as stream:
        stream.write(raw)
    if path.read_bytes() != raw:
        raise IOError('saved JSON readback differs')
    return sha(raw)


def checkpoint(state, *, recipe_sha256, source_sha256):
    # Own the representation; mutating the caller's dictionary cannot silently
    # invalidate a checkpoint already constructed in memory.
    state = decoded(encoded(state))
    return {'schema': CHECKPOINT_SCHEMA, 'recipe_sha256': digest(recipe_sha256),
            'source_sha256': digest(source_sha256), 'state_sha256': sha(encoded(state)),
            'state': state}


def _validate_checkpoint(envelope):
    expected = {'schema', 'recipe_sha256', 'source_sha256', 'state_sha256', 'state'}
    if type(envelope) is not dict or set(envelope) != expected or envelope['schema'] != CHECKPOINT_SCHEMA:
        raise ValueError('checkpoint schema differs')
    digest(envelope['recipe_sha256'])
    digest(envelope['source_sha256'])
    if digest(envelope['state_sha256']) != sha(encoded(envelope['state'])):
        raise ValueError('checkpoint state checksum differs')
    return envelope


def restore(envelope, *, recipe_sha256, source_sha256):
    _validate_checkpoint(envelope)
    if (envelope['recipe_sha256'] != digest(recipe_sha256)
            or envelope['source_sha256'] != digest(source_sha256)):
        raise ValueError('checkpoint belongs to different recipe or actual source')
    return decoded(encoded(envelope['state']))


def save_reference(run_id, *, recipe, result, checkpoint_record, evidence):
    if type(run_id) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}', run_id):
        raise ValueError('bounded new run ID required')
    root = plain_path(OUTPUT_ROOT / run_id)
    items = {'recipe.json': recipe, 'result.json': result, 'checkpoint.json': checkpoint_record}
    for item in (*items.values(), evidence):
        encoded(item)
    _validate_checkpoint(checkpoint_record)
    if checkpoint_record['recipe_sha256'] != sha(encoded(recipe)):
        raise ValueError('saved recipe and checkpoint binding differ')
    receipt = {'schema': ARTIFACT_SCHEMA, 'files': {name: sha(encoded(value)) for name, value in items.items()},
               'recipe_sha256': checkpoint_record['recipe_sha256'],
               'source_sha256': checkpoint_record['source_sha256'], 'evidence': evidence,
               'production_installed': False, 'canon_changed': False}
    encoded(receipt)
    root.mkdir(parents=True, exist_ok=False)
    for name, value in items.items():
        if write_json(root / name, value) != receipt['files'][name]:
            raise IOError('saved product hash differs')
    write_json(root / 'RECEIPT.json', receipt)
    if read_reference(root)['receipt'] != receipt:
        raise IOError('reference receipt readback mismatch')
    return root, receipt


def read_reference(root):
    root = plain_path(root)
    if not root.is_dir():
        raise ValueError('reference directory required')
    if {path.name for path in root.iterdir()} != PRODUCT_NAMES | {'RECEIPT.json'}:
        raise ValueError('reference artefact inventory differs')
    receipt = read_json(root / 'RECEIPT.json')
    keys = {'schema', 'files', 'recipe_sha256', 'source_sha256', 'evidence', 'production_installed', 'canon_changed'}
    if (type(receipt) is not dict or set(receipt) != keys or receipt['schema'] != ARTIFACT_SCHEMA
            or receipt['production_installed'] is not False or receipt['canon_changed'] is not False
            or type(receipt['files']) is not dict or set(receipt['files']) != PRODUCT_NAMES):
        raise ValueError('invalid reference artefact receipt')
    digest(receipt['recipe_sha256'])
    digest(receipt['source_sha256'])
    values = {}
    for name, expected in receipt['files'].items():
        path = plain_path(root / name)
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError('missing/oversize reference product')
        raw = path.read_bytes()
        if sha(raw) != digest(expected):
            raise ValueError('reference product checksum differs: ' + name)
        values[name] = decoded(raw)
    envelope = _validate_checkpoint(values['checkpoint.json'])
    if (envelope['recipe_sha256'] != receipt['recipe_sha256']
            or envelope['source_sha256'] != receipt['source_sha256']
            or sha(encoded(values['recipe.json'])) != receipt['recipe_sha256']):
        raise ValueError('recipe/checkpoint/receipt binding differs')
    return {'receipt': receipt, **values}
