"""Separately versioned execution/checkpoints; no predecessor overwrites."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path

from work.native_terrain_r2 import evolve as numerical
from work.native_terrain_r3 import session as retained
from work.native_terrain_r3.history import History, _safe, _read
from . import provenance as p, integrity

SCHEMA = 'diadem.connected-native-terrain.r4'
STORAGE_SCHEMA = 'diadem.native-history-controls.r4'
_adapt = retained._adapt
_validate = _adapt(numerical.validate, p=p, SCHEMA=SCHEMA)
_base_seal = _adapt(numerical._seal, p=p, SCHEMA=SCHEMA)


def validate(envelope):
    if type(envelope) is not dict or envelope.get('integrity_schema') != p.INTEGRITY_SCHEMA:
        raise ValueError('explicit R4 commitment meaning required')
    if type(envelope.get('body')) is not dict or type(envelope['body'].get('history')) is not History:
        raise ValueError('R4 envelope requires authenticated archive-backed history')
    return _validate(envelope)


def _seal(body, binding):
    if type(body) is not dict or type(body.get('history')) is not History:
        raise ValueError('R4 sealing requires authenticated archive-backed history')
    result = _base_seal(body, binding)
    result['integrity_schema'] = p.INTEGRITY_SCHEMA
    return result


class Executor(numerical.Executor):
    # Mapping reuse was measured but had no reliable gain; retain the kernel.
    advance = _adapt(numerical.Executor.advance, p=p, validate=validate, _seal=_seal,
                     deepcopy=retained._copy_for_advance)


def from_executor(executor):
    if type(executor) is not numerical.Executor:
        raise ValueError('exact retained numerical executor required')
    result = object.__new__(Executor)
    result.__dict__.update(executor.__dict__)
    return result


@dataclass(frozen=True)
class Session(retained.Session):
    def validate(self):
        p.verify_execution(self.execution_binding)
        if type(self.wrapper) is not dict or type(self.wrapper.get('envelope')) is not dict:
            raise ValueError('complete runner wrapper required')
        if type(self.wrapper['envelope']['body'].get('history')) is not History:
            raise ValueError('authenticated archive-backed history required')
        return validate(self.wrapper['envelope'])

    def advance(self, executor, duration, acceptance, *, operation_id):
        p.verify_execution(self.execution_binding)
        following = from_executor(executor).advance(self.wrapper['envelope'], duration,
                                                     acceptance, operation_id=operation_id)
        p.verify_execution(self.execution_binding)
        return Session(dict(self.wrapper, envelope=following), deepcopy(self.execution_binding),
                       self.control_path, self.control_sha256)


# Retain strict shape/codec/source checks and exclusive compare-and-replace lock.
load = _adapt(retained.load, p=p, STORAGE_SCHEMA=STORAGE_SCHEMA, Session=Session)
_save = _adapt(retained.save, p=p, STORAGE_SCHEMA=STORAGE_SCHEMA, Session=Session)


def save(path, session):
    p.verify_execution(session.execution_binding)
    integrity.verify_history(session.wrapper['envelope']['body']['history'], full=True)
    return _save(path, session)


def import_r3(path, archive_root):
    """Explicit lossless source migration; old files never become writable aliases."""
    source = retained.load(path)
    destination = _safe(archive_root)
    original = source.wrapper['envelope']
    history = original['body']['history']
    resolved, source_root = destination.resolve(), history.root.resolve()
    if (destination.exists() or resolved == source_root or source_root in resolved.parents
            or resolved in source_root.parents):
        raise ValueError('R4 migration requires a new separate archive root')
    destination.mkdir(parents=True)
    (destination / 'history').mkdir()
    refs = history.refs
    for ref in refs:
        frame = _read(history.root / ref['path'], ref['frame_size_bytes'])
        if hashlib.sha256(frame).hexdigest() != ref['frame_sha256']:
            raise ValueError('source archive changed during migration')
        with (destination / ref['path']).open('xb') as stream:
            stream.write(frame)
    copied = History.from_refs(destination, refs)
    body = dict(original['body'], history=copied)
    wrapper = dict(source.wrapper, envelope=_seal(body, original['binding']))
    wrapper['r4_migration'] = {'source_control_sha256': source.control_sha256,
        'source_body_sha256': original['body_sha256'],
        'source_schema': original['schema'], 'science_changed': False,
        'integrity_change': 'Ordered authenticated record commitment, not legacy whole-body SHA256'}
    if integrity.scientific_sha(body) != original['body_sha256']:
        raise ValueError('lossless R3 migration body differs')
    if hashlib.sha256(retained._legacy()._read_raw(Path(path))).hexdigest() != source.control_sha256:
        raise ValueError('R3 source control changed during migration')
    result = Session(wrapper, p.identity())
    result.validate()
    return result
