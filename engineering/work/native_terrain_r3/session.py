"""Archive-backed execution and atomic controls; scientific R2 code is reused verbatim.

Only history ownership/canonical IO changes. Source-captured R2 bytecode retains
the same numerical steps, receipts, refinement decisions and refusal conditions.
"""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import FunctionType

from work.generator_runtime_r12 import _CapturedLoader, _raw
from work.native_terrain_r2 import evolve as numerical
from . import provenance as p
from .history import History

STORAGE_SCHEMA = 'diadem.native-history-controls.r3'
ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = ROOT / 'outputs/native-terrain-r1/checkpoint_io.py'
LEGACY_SHA = '2e6e4546e2417ca5b1bc1cf906f65d20f0b1c55614167cd017ae403d1c4d9d74'


def _legacy():
    if hashlib.sha256(_raw(LEGACY_PATH)).hexdigest() != LEGACY_SHA:
        raise ValueError('retained checkpoint codec changed')
    name = 'native_r3_retained_checkpoint_codec'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, LEGACY_PATH, loader=_CapturedLoader(LEGACY_PATH))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    module = sys.modules[name]
    if getattr(module, '_R12_EXECUTED_SHA256', None) != LEGACY_SHA:
        raise ValueError('executed retained checkpoint codec differs')
    return module


def _adapt(function, **overrides):
    namespace = dict(function.__globals__, **overrides)
    return FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)


# The verified function bytecode is identical to R2, not a rewritten solver.
validate = _adapt(numerical.validate, p=p)
_seal = _adapt(numerical._seal, p=p)


def _copy_for_advance(body):
    """Do not copy old fields the retained advance immediately replaces in full.

    Other fields remain detached, preserving previous-session mutation isolation.
    This helper is bound only to the retained advance's one deepcopy(body) call;
    trial rollback and envelope-binding deepcopy keep their original behaviour.
    """
    replaced = {'state', 'lineage', 'exported_origin_mass_kg', 'numeric_l1_units',
                'surface_water_exported_m3', 'cumulative_allocation_error_m3'}
    memo = {}
    return {key: deepcopy(value, memo) for key, value in body.items() if key not in replaced}


class Executor(numerical.Executor):
    advance = _adapt(numerical.Executor.advance, p=p, validate=validate, _seal=_seal, deepcopy=_copy_for_advance)


def from_executor(executor):
    if type(executor) is not numerical.Executor:
        raise ValueError('exact retained R2 executor required')
    result = object.__new__(Executor)
    result.__dict__.update(executor.__dict__)
    return result


@dataclass(frozen=True)
class Session:
    wrapper: dict
    execution_binding: dict
    control_path: str | None = None
    control_sha256: str | None = None

    def validate(self):
        p.verify_execution(self.execution_binding)
        if type(self.wrapper) is not dict or type(self.wrapper.get('envelope')) is not dict:
            raise ValueError('complete runner wrapper required')
        if type(self.wrapper['envelope']['body'].get('history')) is not History:
            raise ValueError('archive-backed accepted history required')
        return validate(self.wrapper['envelope'])

    def advance(self, executor, duration, acceptance, *, operation_id):
        p.verify_execution(self.execution_binding)
        following = from_executor(executor).advance(self.wrapper['envelope'], duration, acceptance,
                                                     operation_id=operation_id)
        p.verify_execution(self.execution_binding)
        wrapper = dict(self.wrapper, envelope=following)
        return Session(wrapper, deepcopy(self.execution_binding), self.control_path, self.control_sha256)


def import_legacy(path, archive_root):
    """Stream/authenticate original rows without expanding their complete history."""
    codec = _legacy()
    path = codec._safe(Path(path), required=True)
    raw = codec._read_raw(path)
    record = codec._parse(raw)
    if type(record) is not dict:
        raise ValueError('explicit legacy runner wrapper required')
    binding = p.identity()
    if 'storage_schema' in record:
        refs = codec._stored_refs(record)
        body = codec._body(record)
        def rows():
            for ref in refs:
                payload = codec._read_raw(path.parent / ref['path'])
                if len(payload) != ref['size_bytes'] or hashlib.sha256(payload).hexdigest() != ref['sha256']:
                    raise ValueError('legacy immutable history differs')
                yield codec._parse(payload)
        history = History.from_rows(archive_root, rows())
        wrapper = {key: value for key, value in record.items() if key not in codec.RESERVED}
        wrapper['envelope'] = dict(record['envelope'], body=dict(body, history=history))
    else:
        codec._validate(record)
        wrapper = deepcopy(record)
        wrapper['envelope']['body']['history'] = History.from_rows(archive_root, record['envelope']['body']['history'])
    if codec._read_raw(path) != raw:
        raise ValueError('legacy control changed during import')
    result = Session(wrapper, binding)
    result.validate()
    return result


def load(path):
    codec = _legacy()
    path = codec._safe(Path(path), required=True)
    raw = codec._read_raw(path)
    stored = codec._parse(raw)
    if type(stored) is not dict or set(stored) != {'storage_schema', 'execution_binding', 'wrapper', 'history_refs'}:
        raise ValueError('complete unambiguous R3 control required')
    if stored['storage_schema'] != STORAGE_SCHEMA:
        raise ValueError('unsupported native history control')
    p.verify_execution(stored['execution_binding'])
    wrapper = stored['wrapper']
    body = wrapper['envelope']['body']
    if 'history' in body:
        raise ValueError('control must not duplicate archived history')
    history = History.from_refs(path.parent, stored['history_refs'])
    wrapper['envelope']['body'] = dict(body, history=history)
    result = Session(wrapper, stored['execution_binding'], str(path.resolve()), hashlib.sha256(raw).hexdigest())
    result.validate()
    if codec._read_raw(path) != raw:
        raise ValueError('control changed while loading history')
    return result


@contextmanager
def _control_lock(path):
    """Serialise cooperating writers; stale locks require explicit recovery."""
    codec = _legacy()
    lock = codec._safe(path.with_name(path.name + '.lock'))
    token = os.urandom(24)
    stream = lock.open('xb')
    try:
        stream.write(token)
        stream.flush()
        os.fsync(stream.fileno())
        yield
    finally:
        stream.close()
        # Never remove a substituted or another writer's lock.
        if codec._read_raw(lock) != token:
            raise ValueError('checkpoint writer lock changed; retained for recovery')
        lock.unlink()


def save(path, session):
    """Verify unchanged old payloads; atomically publish a plain JSON control."""
    codec = _legacy()
    session.validate()
    path = codec._safe(Path(path))
    body = session.wrapper['envelope']['body']
    history = body['history']
    if history.root.resolve() != path.parent.resolve():
        raise ValueError('control and closed history must share one owned root')
    if path.exists():
        if session.control_path != str(path.resolve()) or hashlib.sha256(codec._read_raw(path)).hexdigest() != session.control_sha256:
            raise ValueError('control changed or not owned by this session')
        previous = codec._parse(codec._read_raw(path))['history_refs']
        if history.refs[:len(previous)] != previous:
            raise ValueError('accepted history prefix changed or truncated')
    elif session.control_path is not None:
        raise ValueError('previously loaded control disappeared or changed destination')
    wrapper = dict(session.wrapper, envelope=dict(session.wrapper['envelope'],
                   body={key: value for key, value in body.items() if key != 'history'}))
    stored = {'storage_schema': STORAGE_SCHEMA, 'execution_binding': session.execution_binding,
              'wrapper': wrapper, 'history_refs': history.refs}
    raw = codec.encoded(stored)
    temporary = codec._temporary(path.parent, raw)
    try:
        with _control_lock(path):
            # The lock covers compare and replace, not merely the byte write.
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
