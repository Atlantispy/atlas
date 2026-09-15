"""Bind current captured R13 code, shared machinery and numerical runtime."""
import hashlib
import os
from pathlib import Path
import platform
import sys
import numpy
import scipy
from work.generator_runtime_r12 import provenance as shared

HERE = Path(__file__).resolve().parent
encoded, sha, checked = shared.encoded, shared.sha, shared.checked


def identity():
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest()
               for root in (HERE, shared.HERE) for path in sorted(root.glob('*.py'))}
    for name, module in tuple(sys.modules.items()):
        if (name in ('work.generator_upgrade_r13', 'work.generator_runtime_r12')
                or name.startswith(('work.generator_upgrade_r13.', 'work.generator_runtime_r12.'))
                or name == '__main__' and getattr(module, '__file__', None) == str(HERE / '__main__.py')):
            path = getattr(module, '__file__', None)
            actual = getattr(module, '_R12_EXECUTED_SHA256', None)
            if path not in sources or actual != sources[path]:
                raise ValueError(f'R13 execution source mismatch: {path}; '
                                 f'expected={sources.get(path)}; actual={actual}')
    return {'schema': 'diadem.soil-execution-binding.r13', 'sources': sources,
            'runtime': {'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
                        'platform': platform.platform(), 'numpy': numpy.__version__,
                        'scipy': scipy.__version__, 'optimisation': sys.flags.optimize,
                        'environment': {k: os.environ.get(k) for k in
                            ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                             'PYTHONHASHSEED', 'MKL_CBWR')}}}


def verify(expected):
    if identity() != expected:
        raise ValueError('R13 code/runtime changed during execution; no silent rebind')
