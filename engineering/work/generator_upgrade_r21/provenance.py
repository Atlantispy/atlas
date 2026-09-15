"""Bind actual R21 execution, isolated native files and unchanged cache adapter."""
import hashlib
from pathlib import Path
import sys
from work.generator_runtime_r12 import provenance as common
from work.generator_upgrade_r20 import provenance as cache_parent
from work.generator_upgrade_r13 import provenance as soil_parent
from . import ROOT, NATIVE

HERE = Path(__file__).resolve().parent
encoded, sha, checked = common.encoded, common.sha, common.checked


def identity():
    paths = list(HERE.glob('*.py'))
    for relative, expected in NATIVE.values():
        path = ROOT/relative
        checked(path, expected)
        paths.append(path)
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest() for path in sorted(set(paths))}
    for module in tuple(sys.modules.values()):
        path = getattr(module, '__file__', None)
        if path in sources and getattr(module, '_R12_EXECUTED_SHA256', None) != sources[path]:
            raise ValueError('agriculture executed source differs: '+str(path))
    return {'schema': 'diadem.agriculture-execution-binding.r21', 'sources': sources,
            'storage_runtime': cache_parent.identity(), 'coupled_soil': soil_parent.identity()}


def verify(expected):
    if identity() != expected:
        raise ValueError('agriculture source/runtime binding changed; no repin')
