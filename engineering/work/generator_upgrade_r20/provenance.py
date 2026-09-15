"""Bind the political producer and actual storage/runtime dependencies only."""
import hashlib
from pathlib import Path
import platform
import sys
import numpy
import scipy
import shapely
from work.generator_runtime_r12 import provenance as common, store

HERE = Path(__file__).resolve().parent
encoded, sha, checked = common.encoded, common.sha, common.checked


def identity():
    paths = list(HERE.glob('*.py'))
    paths.append(HERE.parent/'generator_upgrade_r11'/'snapshot.py')
    paths += [Path(sys.modules[name].__file__) for name in
              ('work.generator_runtime_r12', 'work.generator_runtime_r12.provenance',
               'work.generator_runtime_r12.store')]
    sources = {str(path): hashlib.sha256(checked(path)).hexdigest() for path in sorted(paths)}
    for name, module in tuple(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path in sources and getattr(module, '_R12_EXECUTED_SHA256', None) != sources[path]:
            raise ValueError('political executed source differs: '+str(path))
    libraries = {name: sys.modules[name].__version__ for name in ('shapely', 'numpy', 'scipy')}
    libraries['geos'] = shapely.geos_version_string
    return {'schema': 'diadem.political-execution-binding.r20', 'sources': sources,
            'runtime': {'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
                        'platform': platform.platform(), 'optimisation_flag': sys.flags.optimize,
                        'libraries': libraries}}


def verify(expected):
    if identity() != expected:
        raise ValueError('political source/runtime binding changed; no repin')
