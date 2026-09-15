"""Bind data-driven rules and the unchanged R15--R17 source/native machinery."""
import hashlib
from pathlib import Path
import sys
from work.generator_upgrade_r17 import provenance as parent

HERE = Path(__file__).resolve().parent
encoded, sha, checked = parent.encoded, parent.sha, parent.checked


def identity():
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest()
               for path in sorted(HERE.glob('*.py'))}
    for name, module in tuple(sys.modules.items()):
        if name == 'work.generator_upgrade_r18' or name.startswith('work.generator_upgrade_r18.'):
            path = getattr(module, '__file__', None)
            if getattr(module, '_R12_EXECUTED_SHA256', None) != sources.get(path):
                raise ValueError('R18 executed source differs: '+str(path))
    return {'schema': 'diadem.geological-coverage-execution-binding.r18',
            'sources': sources, 'regional': parent.identity()}


def verify(expected):
    parent.verify(expected['regional'])
    if identity() != expected:
        raise ValueError('geological coverage source/runtime binding changed; no repin')
