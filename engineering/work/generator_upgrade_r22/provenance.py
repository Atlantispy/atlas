"""Bind actual successor execution and its unchanged numerical predecessors."""
import hashlib
from pathlib import Path
import sys
from work.generator_upgrade_r21 import provenance as parent
from work.generator_upgrade_r14 import provenance as ground
from . import ROOT, NATIVE

HERE = Path(__file__).resolve().parent
encoded, sha, checked = parent.encoded, parent.sha, parent.checked


def identity(*, moving_ground=False):
    paths = list(HERE.glob('*.py'))
    for relative, expected in NATIVE.values():
        path = ROOT/relative
        checked(path, expected)
        paths.append(path)
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest() for path in sorted(set(paths))}
    for name, module in tuple(sys.modules.items()):
        if name == 'work.generator_upgrade_r22' or name.startswith('work.generator_upgrade_r22.'):
            path = getattr(module, '__file__', None)
            if getattr(module, '_R12_EXECUTED_SHA256', None) != sources.get(path):
                raise ValueError('R22 executed source differs: '+str(path))
    return {'schema': 'diadem.biophysical-successor-binding.r22', 'sources': sources,
            'agriculture_soil_runtime': parent.identity(),
            'moving_ground': ground.identity() if moving_ground else None}


def verify(expected):
    if identity(moving_ground=expected['moving_ground'] is not None) != expected:
        raise ValueError('R22 source/runtime changed; no silent repin')
