"""Explicit shared-storage identity; unchanged R4 physics and proposal policy."""
import hashlib
from fractions import Fraction
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw
from work.native_terrain_r3 import provenance as logical
from work.native_terrain_r3.session import _adapt
from work.native_terrain_r4 import provenance as retained
from . import HERE, integrity
from .history import History

RUNTIME_FILES = ('__init__.py', 'history.py', 'integrity.py', 'provenance.py', 'session.py', 'runner.py')
INTEGRITY_SCHEMA = integrity.SCHEMA
policy, verify = retained.policy, retained.verify
chunks = _adapt(logical.chunks, History=History)


def plain(value):
    if type(value) is History:
        return value
    if type(value) is Fraction:
        return str(value)
    if type(value) is dict:
        return {str(k): plain(v) for k, v in value.items()}
    if type(value) in (list, tuple):
        return [plain(v) for v in value]
    return value


def encoded(value):
    return b''.join(chunks(value))


def scientific_sha(value):
    result = hashlib.sha256()
    for raw in chunks(value):
        result.update(raw)
    return result.hexdigest()


def sha(value):
    if type(value) is dict and 'history' in value:
        return integrity.commitment(value)
    return logical.sha(value)


def identity():
    sources = {}
    for name in RUNTIME_FILES:
        digest = hashlib.sha256(_raw(HERE / name)).hexdigest()
        sources[name] = digest
        module_name = __package__ + ('' if name == '__init__.py' else '.' + name[:-3])
        module = sys.modules.get(module_name)
        if name == 'runner.py':
            main = sys.modules.get('__main__')
            if getattr(main, '__file__', None) and Path(main.__file__).resolve() == HERE / name:
                module = main
        if module is not None and getattr(module, '_R12_EXECUTED_SHA256', None) != digest:
            raise ValueError('executed native R5 source differs: ' + name)
    return {'schema': 'diadem.native-shared-storage-execution.r5', 'sources': sources,
            'integrity_schema': INTEGRITY_SCHEMA, 'retained_execution': retained.identity()}


def verify_execution(binding):
    if identity() != binding:
        raise ValueError('native R5 execution changed; no silent source adoption')
