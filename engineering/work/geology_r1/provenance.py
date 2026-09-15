"""Geology successor identity; retained inputs, physics and guards remain bound."""
import hashlib
import sys
from work.generator_upgrade_r18 import provenance as parent
from work.generator_upgrade_r24.verification import Reader, _Clones
from work.generator_upgrade_r24 import verification
from work.generator_upgrade_r28 import preflight
from . import HERE

encoded, sha, checked = parent.encoded, parent.sha, parent.checked


def sources(reader=None):
    own = reader is None
    reader = Reader() if own else reader
    primary = None
    try:
        paths = tuple(sorted(HERE.glob('*.py')))
        current = {str(path): hashlib.sha256(reader.checked(path)).hexdigest() for path in paths}
        if tuple(sorted(HERE.glob('*.py'))) != paths:
            raise ValueError('Geology R1 source inventory changed')
        for module in (verification, preflight,
                       sys.modules['work.generator_upgrade_r24'],
                       sys.modules['work.generator_upgrade_r28']):
            path = module.__file__
            digest = hashlib.sha256(reader.checked(path)).hexdigest()
            if getattr(module, '_R12_EXECUTED_SHA256', None) != digest:
                raise ValueError('Geology helper executed source differs: '+path)
            current[path] = digest
        for name, module in tuple(sys.modules.items()):
            path = getattr(module, '__file__', None)
            if name == 'work.geology_r1' or name.startswith('work.geology_r1.') or path in current:
                if path not in current or getattr(module, '_R12_EXECUTED_SHA256', None) != current[path]:
                    raise ValueError('Geology R1 executed source differs: '+str(path))
        return current
    except BaseException as error:
        primary = error
        raise
    finally:
        if own:
            try:
                reader.finish()
            except BaseException as error:
                if primary is not None:
                    primary.geology_source_cleanup_errors = [str(error)]
                else:
                    raise


def _pass(expected=None):
    # Retain every ancestor identity and verifier. Sharing only duplicate reads
    # within this pass cannot authenticate a subsequent job or result.
    from .native import ground
    ground.backend()
    reader, primary = Reader(), None
    try:
        previous = _Clones(reader).module(parent)
        if expected is not None:
            previous.verify(expected['retained'])
        current = {'schema': 'diadem.geology-optimisation-execution.r1',
                   'sources': sources(reader), 'retained': previous.identity()}
        if expected is not None and current != expected:
            raise ValueError('Geology R1 source/runtime binding changed; no repin')
        return current
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            reader.finish()
        except BaseException as error:
            if primary is not None:
                primary.geology_source_cleanup_errors = [str(error)]
            else:
                raise


def identity():
    return _pass()


def verify(expected):
    _pass(expected)
