"""Source-captured regional geological construction; preserves R1--R15."""
import hashlib as _hashlib
import importlib.abc as _abc
import importlib.util as _util
from pathlib import Path as _Path
import sys as _sys
from work.generator_runtime_r12 import _CapturedLoader, _raw

_ROOT = _Path(__file__).resolve().parent
_BOOTSTRAP_RAW = _raw(_Path(__file__))
if _sys._getframe().f_code != compile(_BOOTSTRAP_RAW, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R16 bootstrap differs from current source')
_R12_EXECUTED_SHA256 = _hashlib.sha256(_BOOTSTRAP_RAW).hexdigest()


class _Finder(_abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix = __name__ + '.'
        if not fullname.startswith(prefix):
            return None
        name = fullname[len(prefix):]
        if not name.isidentifier():
            raise ImportError('flat R16 module identity required')
        source = _ROOT / (name + '.py')
        if not source.is_file():
            raise ImportError('undeclared R16 module: ' + fullname)
        return _util.spec_from_file_location(fullname, source, loader=_CapturedLoader(source))


_sys.meta_path.insert(0, _Finder())
