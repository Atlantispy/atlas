"""Independent atomic JSON controls referencing one immutable shared frame store.

Only explicit import/fork/export creates a new owner. Normal save is compare and
replace with the retained exclusive writer lock, unchanged prefix and store.
Store location is operational, outside the location-independent body commitment.
An export uses exactly the relative path 'store' and can move as one directory.
No deletion/garbage collection or writable aliases to predecessor files.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from work.native_terrain_r2 import evolve as numerical
from work.native_terrain_r3 import session as io
from work.native_terrain_r3.history import _safe
from work.native_terrain_r4 import session as retained
from work.native_terrain_r4 import integrity as old_integrity
from . import provenance as p, integrity
from .history import History

SCHEMA = 'diadem.connected-native-terrain.r5'
STORAGE_SCHEMA = 'diadem.native-shared-history-controls.r5'
STORE_SCHEMA = 'diadem.native-shared-history-store.r5'
_adapt = io._adapt
_validate = _adapt(numerical.validate, p=p, SCHEMA=SCHEMA)
_base_seal = _adapt(numerical._seal, p=p, SCHEMA=SCHEMA)
validate = _adapt(retained.validate, p=p, History=History, _validate=_validate)
_seal = _adapt(retained._seal, p=p, History=History, _base_seal=_base_seal)


class Executor(numerical.Executor):
    advance = _adapt(numerical.Executor.advance, p=p, validate=validate, _seal=_seal,
                     deepcopy=io._copy_for_advance)


from_executor = _adapt(retained.from_executor, Executor=Executor)


@dataclass(frozen=True)
class Session(io.Session):
    validate = _adapt(retained.Session.validate, p=p, History=History, validate=validate)

    def advance(self, executor, duration, acceptance, *, operation_id):
        p.verify_execution(self.execution_binding)
        following = from_executor(executor).advance(self.wrapper['envelope'], duration,
                                                    acceptance, operation_id=operation_id)
        p.verify_execution(self.execution_binding)
        return Session(dict(self.wrapper, envelope=following), deepcopy(self.execution_binding),
                       self.control_path, self.control_sha256)


def _store_ref(history, control):
    root = _safe(history.root, required=True, directory=True).resolve()
    location = 'store' if root == control.parent.resolve() / 'store' else str(root)
    return {'schema': STORE_SCHEMA, 'path': location}


def _store_root(reference, control):
    if (type(reference) is not dict or set(reference) != {'schema', 'path'}
            or reference['schema'] != STORE_SCHEMA or type(reference['path']) is not str):
        raise ValueError('explicit unambiguous shared store required')
    location = reference['path']
    if location == 'store':
        root = control.parent / 'store'
    elif Path(location).is_absolute():
        root = Path(location)
    else:
        raise ValueError('absolute shared store or self-contained store required')
    return _safe(root, required=True, directory=True)


def load(path):
    codec = io._legacy()
    path = codec._safe(Path(path), required=True)
    raw = codec._read_raw(path)
    stored = codec._parse(raw)
    keys = {'storage_schema', 'execution_binding', 'wrapper', 'history_refs', 'history_store'}
    if type(stored) is not dict or set(stored) != keys or stored['storage_schema'] != STORAGE_SCHEMA:
        raise ValueError('complete unambiguous R5 control required')
    p.verify_execution(stored['execution_binding'])
    wrapper = stored['wrapper']
    body = wrapper['envelope']['body']
    if 'history' in body:
        raise ValueError('control must not duplicate archived history')
    history = History.from_refs(_store_root(stored['history_store'], path), stored['history_refs'])
    wrapper['envelope']['body'] = dict(body, history=history)
    result = Session(wrapper, stored['execution_binding'], str(path.resolve()), hashlib.sha256(raw).hexdigest())
    result.validate()
    if codec._read_raw(path) != raw:
        raise ValueError('control changed while loading history')
    return result


def save(path, session):
    codec = io._legacy()
    session.validate()
    path = codec._safe(Path(path))
    body = session.wrapper['envelope']['body']
    history = body['history']
    refs = integrity.verify_history(history, full=True)
    store = _store_ref(history, path)
    if path.exists():
        old = codec._read_raw(path)
        if session.control_path != str(path.resolve()) or hashlib.sha256(old).hexdigest() != session.control_sha256:
            raise ValueError('control changed or not owned by this session')
        previous = codec._parse(old)
        if refs[:len(previous['history_refs'])] != previous['history_refs']:
            raise ValueError('accepted history prefix changed or truncated')
        if previous['history_store'] != store:
            raise ValueError('shared store changed; explicit fork or export required')
    elif session.control_path is not None:
        raise ValueError('previously loaded control disappeared or changed destination')
    wrapper = dict(session.wrapper, envelope=dict(session.wrapper['envelope'],
                   body={key: value for key, value in body.items() if key != 'history'}))
    stored = {'storage_schema': STORAGE_SCHEMA, 'execution_binding': session.execution_binding,
              'wrapper': wrapper, 'history_refs': refs, 'history_store': store}
    raw = codec.encoded(stored)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = codec._temporary(path.parent, raw)
    try:
        with io._control_lock(path):
            if path.exists():
                if session.control_sha256 is None or hashlib.sha256(codec._read_raw(path)).hexdigest() != session.control_sha256:
                    raise ValueError('control changed before commit')
            elif session.control_sha256 is not None:
                raise ValueError('control disappeared before commit')
            p.verify_execution(session.execution_binding)
            codec._safe(path)
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return Session(session.wrapper, session.execution_binding, str(path.resolve()), hashlib.sha256(raw).hexdigest())


def import_r4(path, store_root):
    """Explicit lossless import; retains old archive, reuses published objects."""
    source = retained.load(path)
    old = source.wrapper['envelope']
    destination = _safe(store_root)
    original_root = old['body']['history'].root.resolve()
    target = destination.resolve()
    if target == original_root or original_root in target.parents or target in original_root.parents:
        raise ValueError('shared store must be separate from predecessor archive')
    copied = History.from_history(old['body']['history'], destination)
    body = dict(old['body'], history=copied)
    legacy_sha = old_integrity.scientific_sha(old['body'])
    if integrity.scientific_sha(body) != legacy_sha:
        raise ValueError('lossless R4 import body differs')
    wrapper = dict(source.wrapper, envelope=_seal(body, old['binding']))
    wrapper['r5_migration'] = {'source_control_sha256': source.control_sha256,
        'source_body_commitment_sha256': old['body_sha256'], 'source_schema': old['schema'],
        'legacy_scientific_body_sha256': legacy_sha, 'science_changed': False,
        'integrity_change': 'R5 ordered content-addressed references; location-independent commitment'}
    if hashlib.sha256(io._legacy()._read_raw(Path(path))).hexdigest() != source.control_sha256:
        raise ValueError('R4 source control changed during import')
    result = Session(wrapper, p.identity())
    result.validate()
    return result


def fork(session, path):
    """Publish only a new control sharing authenticated immutable records."""
    path = _safe(path)
    if path.exists():
        raise ValueError('fork requires a new control path')
    # Detached dictionaries and descriptor tuple; the actual closed bytes are shared.
    child = Session(deepcopy(session.wrapper), deepcopy(session.execution_binding))
    return save(path, child)


def export(session, directory):
    """Create a new self-contained, relocatable directory with no shared dependency."""
    session.validate()
    destination = _safe(directory)
    root = session.wrapper['envelope']['body']['history'].root.resolve()
    target = destination.resolve()
    if destination.exists() or target == root or root in target.parents or target in root.parents:
        raise ValueError('export requires a new separate directory')
    destination.mkdir(parents=True)
    wrapper = deepcopy(session.wrapper)
    wrapper['envelope']['body']['history'] = History.from_history(
        wrapper['envelope']['body']['history'], destination / 'store')
    child = Session(wrapper, deepcopy(session.execution_binding))
    return save(destination / 'checkpoint.json', child)
