"""Quality-preserving execution adapters over unchanged sealed R11 science.

Capture actual execution bytes, including this bootstrap. R12 modules never use
timestamp-based bytecode reuse: an identity must describe the code that ran.
"""
import hashlib as _hashlib
import importlib.abc as _abc
import importlib.util as _util
from pathlib import Path as _Path
import stat as _stat
import sys as _sys

_ROOT = _Path(__file__).resolve().parent


def _raw(path):
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if _stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked execution source refused')
    if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('bounded execution source required')
    return path.read_bytes()


_BOOTSTRAP_RAW = _raw(_Path(__file__))
if _sys._getframe().f_code != compile(_BOOTSTRAP_RAW, __file__, 'exec', dont_inherit=True):
    raise ValueError('executed R12 bootstrap differs from current source')
_R12_EXECUTED_SHA256 = _hashlib.sha256(_BOOTSTRAP_RAW).hexdigest()


class _CapturedLoader(_abc.Loader):
    def __init__(self, path):
        self.path = path

    def create_module(self, spec):
        return None

    def get_code(self, fullname):
        return compile(_raw(self.path), str(self.path), 'exec', dont_inherit=True)

    def exec_module(self, module):
        raw = _raw(self.path)
        code = compile(raw, str(self.path), 'exec', dont_inherit=True)
        module.__file__ = str(self.path)
        exec(code, module.__dict__)
        if _raw(self.path) != raw:
            raise ValueError('execution source changed during import')
        module._R12_EXECUTED_SHA256 = _hashlib.sha256(raw).hexdigest()


class _CapturedFinder(_abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        prefix = __name__ + '.'
        if not fullname.startswith(prefix):
            return None
        name = fullname[len(prefix):]
        if '.' in name or not name.isidentifier():
            raise ImportError('flat R12 module identity required')
        source = _ROOT / (name + '.py')
        if not source.is_file():
            raise ImportError('undeclared R12 module: ' + fullname)
        return _util.spec_from_file_location(fullname, source, loader=_CapturedLoader(source))


_sys.meta_path.insert(0, _CapturedFinder())
