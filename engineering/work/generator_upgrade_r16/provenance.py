"""Bind the new constructor and its unchanged native R14 numerical consumers."""
import hashlib
from pathlib import Path
import sys
from work.generator_upgrade_r14 import provenance as parent

HERE = Path(__file__).resolve().parent
encoded, sha, checked = parent.encoded, parent.sha, parent.checked
backend = parent.backend


def identity():
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest()
               for path in sorted(HERE.glob('*.py'))}
    for name, module in tuple(sys.modules.items()):
        if name == 'work.generator_upgrade_r16' or name.startswith('work.generator_upgrade_r16.'):
            path = getattr(module, '__file__', None)
            if getattr(module, '_R12_EXECUTED_SHA256', None) != sources.get(path):
                raise ValueError('R16 executed source differs: '+str(path))
    return {'schema': 'diadem.regional-execution-binding.r16', 'sources': sources,
            'terrain': parent.identity()}


def verify(expected):
    parent.verify(expected['terrain'])
    if identity() != expected:
        raise ValueError('regional source/runtime binding changed; no repin')
