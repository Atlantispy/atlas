"""Executed successor identity plus unchanged native predecessor bindings."""
import hashlib
import json
import sys
from . import HERE
from work.native_terrain_r1 import provenance as retained

plain, encoded, sha = retained.plain, retained.encoded, retained.sha
RUNTIME_FILES = ('__init__.py', 'numerics.py', 'channel.py', 'evolve.py', 'migration.py', 'provenance.py')


def policy():
    return json.loads((HERE / 'POLICY.json').read_bytes())


def identity():
    sources = {}
    for name in RUNTIME_FILES:
        raw = (HERE / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        sources[name] = digest
        module_name = __package__ + ('' if name == '__init__.py' else '.' + name[:-3])
        module = sys.modules.get(module_name)
        if module is not None and getattr(module, '_R12_EXECUTED_SHA256', None) != digest:
            raise ValueError('executed numerical successor differs from source: ' + name)
    raw = (HERE / 'POLICY.json').read_bytes()
    return {'schema': 'diadem.native-numerical-execution.r2', 'sources': sources,
            'policy_sha256': hashlib.sha256(raw).hexdigest(), 'policy': json.loads(raw),
            'retained_native': retained.identity()}


def verify(binding):
    if identity() != binding:
        raise ValueError('native numerical source/runtime binding changed; no silent repin')
