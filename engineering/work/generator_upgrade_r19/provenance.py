"""Bind the coastal code and unchanged R18 finite material/native machinery."""
import hashlib
from pathlib import Path
import sys
from work.generator_upgrade_r18 import provenance as parent

HERE = Path(__file__).resolve().parent
encoded, sha, checked = parent.encoded, parent.sha, parent.checked


def identity():
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest()
               for path in sorted(HERE.glob('*.py'))}
    for name, module in tuple(sys.modules.items()):
        if (name == 'work.generator_upgrade_r19' or name.startswith('work.generator_upgrade_r19.')
                or name == '__main__' and getattr(module, '__file__', None) == str(HERE/'__main__.py')):
            path = getattr(module, '__file__', None)
            if getattr(module, '_R12_EXECUTED_SHA256', None) != sources.get(path):
                raise ValueError('R19 executed source differs: '+str(path))
    return {'schema': 'diadem.coastal-execution-binding.r19',
            'sources': sources, 'geological': parent.identity()}


def verify(expected):
    parent.verify(expected['geological'])
    if identity() != expected:
        raise ValueError('coastal source/runtime binding changed; no repin')
