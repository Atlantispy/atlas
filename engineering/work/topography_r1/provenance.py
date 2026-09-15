"""Topography successor source identities; no persistent verification trust."""
import hashlib
import sys
from work.generator_upgrade_r18 import provenance as old_geology
from work.generator_upgrade_r22 import provenance as old_terrain
from work.generator_upgrade_r24.verification import Reader, _Clones
from work.geology_r1 import provenance as geology
from work.geology_r1.native import ground
from . import HERE

encoded, sha, checked = geology.encoded, geology.sha, geology.checked


def _sources(reader):
    paths = tuple(sorted(HERE.glob('*.py')))
    current = {str(path): hashlib.sha256(reader.checked(path)).hexdigest() for path in paths}
    if tuple(sorted(HERE.glob('*.py'))) != paths:
        raise ValueError('Topography R1 source inventory changed')
    for name, module in tuple(sys.modules.items()):
        if name == 'work.topography_r1' or name.startswith('work.topography_r1.'):
            path = getattr(module, '__file__', None)
            if path not in current or getattr(module, '_R12_EXECUTED_SHA256', None) != current[path]:
                raise ValueError('Topography R1 executed source differs: '+str(path))
    # Bind the existing source reader, cloning helpers and their captured loaders
    # through G1's explicit source closure as well as its numerical/accounting code.
    current.update(geology.sources(reader))
    return current


def _finish(reader, primary):
    try:
        reader.finish()
    except BaseException as error:
        if primary is None:
            raise
        primary.topography_source_cleanup_errors = [str(error)]


def sources():
    reader, primary = Reader(), None
    try:
        return _sources(reader)
    except BaseException as error:
        primary = error
        raise
    finally:
        _finish(reader, primary)


def verify_sources(expected):
    if sources() != expected:
        raise ValueError('Topography source changed; no silent repin')


def _pass(expected=None):
    ground.backend()
    reader, primary = Reader(), None
    try:
        clones = _Clones(reader)
        terrain = clones.module(old_terrain)
        regional = clones.module(old_geology)
        if expected is not None:
            terrain.verify(expected['retained_terrain'])
            regional.verify(expected['retained_geology'])
        current = {'schema': 'diadem.topography-execution-binding.r1',
                   'sources': _sources(reader),
                   'retained_terrain': terrain.identity(moving_ground=True),
                   'retained_geology': regional.identity()}
        if expected is not None and current != expected:
            raise ValueError('Topography source/runtime binding changed; no repin')
        return current
    except BaseException as error:
        primary = error
        raise
    finally:
        _finish(reader, primary)


def identity():
    return _pass()


def verify(expected):
    _pass(expected)
