"""Bind the new numerical input connection and unchanged R15/R16 consumers."""
import hashlib
from pathlib import Path
import sys
from work.generator_upgrade_r15 import regional as sampler
from work.generator_upgrade_r16 import provenance as parent

HERE = Path(__file__).resolve().parent
encoded, sha, checked = parent.encoded, parent.sha, parent.checked


def identity():
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest()
               for path in sorted(HERE.glob('*.py'))}
    for name, module in tuple(sys.modules.items()):
        if name == 'work.generator_upgrade_r17' or name.startswith('work.generator_upgrade_r17.'):
            path = getattr(module, '__file__', None)
            if getattr(module, '_R12_EXECUTED_SHA256', None) != sources.get(path):
                raise ValueError('R17 executed source differs: '+str(path))
    sampler_sha = hashlib.sha256(checked(Path(sampler.__file__))).hexdigest()
    if sampler_sha != sampler._SOURCE_SHA:
        raise ValueError('R15 executed field sampler differs from source')
    return {'schema': 'diadem.regional-input-execution-binding.r17',
            'sources': sources, 'sampler_source': sampler.__file__,
            'sampler_sha256': sampler_sha, 'construction': parent.identity()}


def verify(expected):
    parent.verify(expected['construction'])
    if identity() != expected:
        raise ValueError('regional input source/runtime binding changed; no repin')
