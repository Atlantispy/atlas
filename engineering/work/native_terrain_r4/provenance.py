"""Explicit R4 integrity meaning; unchanged numerical/scientific source binding."""
import hashlib
from pathlib import Path
import sys
from work.generator_runtime_r12 import _raw
from work.native_terrain_r3 import provenance as retained
from work.native_terrain_r3.history import History
from . import HERE, integrity

RUNTIME_FILES = ('__init__.py', 'integrity.py', 'trials.py', 'scheduling.py',
                 'provenance.py', 'session.py', 'runner.py')
INTEGRITY_SCHEMA = integrity.SCHEMA
plain, encoded, policy, verify = retained.plain, retained.encoded, retained.policy, retained.verify


def sha(value):
    if type(value) is dict and 'history' in value:
        return integrity.commitment(value)
    return retained.sha(value)


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
            raise ValueError('executed native R4 source differs: ' + name)
    return {'schema': 'diadem.native-execution.r4', 'sources': sources,
            'integrity_schema': INTEGRITY_SCHEMA, 'retained_history': retained.identity()}


def verify_execution(binding):
    if identity() != binding:
        raise ValueError('native R4 execution changed; no silent source adoption')
