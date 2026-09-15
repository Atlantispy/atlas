"""Retain scientific canonical bytes; stream immutable history instead of expanding it."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw
from work.native_terrain_r2 import provenance as retained
from . import HERE
from .history import History
from . import compression

RUNTIME_FILES = ('__init__.py', 'compression.py', 'history.py', 'provenance.py', 'session.py', 'runner.py')
policy = retained.policy


def plain(value):
    if type(value) is History:
        return value
    if type(value) is Fraction:
        return str(value)
    if type(value) is dict:
        return {str(k): plain(v) for k, v in value.items()}
    if type(value) in (tuple, list):
        return [plain(v) for v in value]
    return value


def chunks(value):
    """Same canonical R2 body, including every original logical history byte."""
    if type(value) is dict and type(value.get('history')) is History:
        yield b'{'
        for i, key in enumerate(sorted(value)):
            if i:
                yield b','
            yield retained.encoded(key)
            yield b':'
            if key == 'history':
                yield b'['
                for j, raw in enumerate(value[key].iter_raw()):
                    if j:
                        yield b','
                    yield raw
                yield b']'
            else:
                yield retained.encoded(value[key])
        yield b'}'
    else:
        yield retained.encoded(value)


def encoded(value):
    """Explicit materialisation API; hot body hashing uses chunks directly."""
    return b''.join(chunks(value))


def sha(value):
    result = hashlib.sha256()
    for raw in chunks(value):
        result.update(raw)
    return result.hexdigest()


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
            raise ValueError('executed native history source differs: ' + name)
    return {'schema': 'diadem.native-history-execution.r3', 'sources': sources,
            'compression': compression.identity(), 'retained_numerical': retained.identity()}


def verify_execution(binding):
    if identity() != binding:
        raise ValueError('native history execution binding changed; no silent repin')


def verify(binding):
    # The scientific envelope still describes the unchanged R2 physics/numerics.
    retained.verify(binding)
