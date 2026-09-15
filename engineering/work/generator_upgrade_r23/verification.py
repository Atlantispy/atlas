"""Deduplicated fresh-byte checks for the ordinary R22 execution closure.

Only the known non-moving R22/R21/R20/R13 closure is supported. The caller
retains the original complete identity comparison at entry and completion.
Every intermediate check rereads every source; filesystem metadata is used
only to reject unsafe paths and replacement during a read, never as a digest.
"""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import platform
import stat
import sys

from work.generator_upgrade_r22 import provenance as r22

LIMIT = 8 * 1024 * 1024


def _path(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute non-traversing source path required')
    return path


def _pins(groups):
    result = {}
    for group in groups:
        if type(group) is not dict:
            raise ValueError('exact source mapping required')
        for name, digest in group.items():
            path = _path(name)
            if (type(digest) is not str or len(digest) != 64
                    or any(c not in '0123456789abcdef' for c in digest)):
                raise ValueError('exact source digest required')
            if path in result and result[path] != digest:
                raise ValueError('conflicting source pins: '+str(path))
            result[path] = digest
    if not result:
        raise ValueError('nonempty source closure required')
    return result


def _info(path, *, directory):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('linked/reparse source path refused: '+str(path))
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('source ancestor must be a directory: '+str(path))
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT:
        raise ValueError('bounded unlinked regular source file required: '+str(path))
    return info


def _same_file(left, right):
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _inventories(expected):
    for root, paths in expected:
        actual = tuple(sorted(str(path) for path in root.glob('*.py')))
        if actual != paths:
            raise ValueError('source inventory changed: '+str(root))


def verify_files(source_pins, inventories=None):
    """Fresh bounded reads with one pre/post inspection per unique ancestor."""
    _Files(source_pins, inventories).verify()


class _Files:
    """Immutable check structure only: no saved file contents or trusted stats."""
    def __init__(self, source_pins, inventories=None):
        pins = _pins([source_pins])
        inventories = {_path(root): tuple(sorted(str(_path(path)) for path in paths))
                       for root, paths in (inventories or {}).items()}
        ancestors = {ancestor for path in pins for ancestor in path.parents}
        ancestors.update(inventories)
        for root in inventories:
            ancestors.update(root.parents)
        self._pins = tuple(sorted(pins.items()))
        self._inventories = tuple(sorted(inventories.items()))
        self._ancestors = tuple(sorted(ancestors, key=lambda path: (len(path.parts), str(path))))

    def verify(self):
        before = tuple(_info(path, directory=True) for path in self._ancestors)
        _inventories(self._inventories)
        for path, expected in self._pins:
            initial = _info(path, directory=False)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0)
                                 | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'rb') as handle:
                opened = os.fstat(handle.fileno())
                if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                        or opened.st_size > LIMIT or not _same_file(initial, opened)):
                    raise ValueError('source changed while opening: '+str(path))
                # The size chooses only an allocation bound. Every byte is
                # still read/hashed, and one extra byte detects file growth.
                raw = handle.read(opened.st_size+1)
                final_open = os.fstat(handle.fileno())
            current = _info(path, directory=False)
            if (len(raw) > LIMIT or len(raw) != opened.st_size
                    or final_open.st_size != opened.st_size
                    or not _same_file(opened, final_open) or not _same_file(opened, current)):
                raise ValueError('source changed while reading: '+str(path))
            actual = hashlib.sha256(raw).hexdigest()
            if actual != expected:
                raise ValueError('source changed; no silent rebind: '+str(path)
                                 +'; expected_sha256='+expected+'; actual_sha256='+actual)
        _inventories(self._inventories)
        for path, initial in zip(self._ancestors, before):
            if not _same_file(initial, _info(path, directory=True)):
                raise ValueError('source ancestor changed during verification: '+str(path))


def _shape(value, schema, keys):
    if type(value) is not dict or value.get('schema') != schema or set(value) != set(keys):
        raise ValueError('unsupported source binding shape: '+schema)
    return value


class Binding:
    """Compiled default R22 verifier; identities returned to callers are copies."""
    def __init__(self, expected_identity, extra_sources=None, extra_inventory=None):
        self._identity = deepcopy(expected_identity)
        base = _shape(self._identity, 'diadem.biophysical-successor-binding.r22',
                      ('schema', 'sources', 'agriculture_soil_runtime', 'moving_ground'))
        if base['moving_ground'] is not None:
            raise ValueError('moving-ground binding requires original full verifier')
        agriculture = _shape(base['agriculture_soil_runtime'], 'diadem.agriculture-execution-binding.r21',
                             ('schema', 'sources', 'storage_runtime', 'coupled_soil'))
        political = _shape(agriculture['storage_runtime'], 'diadem.political-execution-binding.r20',
                           ('schema', 'sources', 'runtime'))
        soil = _shape(agriculture['coupled_soil'], 'diadem.soil-execution-binding.r13',
                     ('schema', 'sources', 'runtime'))
        self._r21 = r22.parent
        self._r20 = self._r21.cache_parent
        self._r13 = self._r21.soil_parent
        self._modules = (r22, self._r21, self._r20, self._r13, self._r13.shared)
        self._roots = tuple(module.HERE for module in self._modules)
        self._native = (deepcopy(r22.NATIVE), deepcopy(self._r21.NATIVE))
        self._native_roots = (r22.ROOT, self._r21.ROOT)
        self._sources = _pins([part['sources'] for part in (base, agriculture, political, soil)]
                             + [extra_sources or {}])
        self._source_strings = {str(path): digest for path, digest in self._sources.items()}
        self._inventory = {root: tuple(sorted(str(path) for path in self._sources if path.parent == root))
                           for root in self._roots}
        for root, paths in (extra_inventory or {}).items():
            root = _path(root)
            paths = tuple(sorted(str(_path(path)) for path in paths))
            if root in self._inventory and self._inventory[root] != paths:
                raise ValueError('conflicting source inventory')
            if any(Path(path).parent != root or Path(path) not in self._sources for path in paths):
                raise ValueError('extra inventory requires exact pinned children')
            self._inventory[root] = paths
        self._runtime = (deepcopy(political['runtime']), deepcopy(soil['runtime']))
        self._files = _Files(self._sources, self._inventory)
        self._prefixes = ('work.generator_upgrade_r22', 'work.generator_upgrade_r13',
                          'work.generator_runtime_r12')
        if any(path.parent == Path(__file__).parent for path in self._sources):
            self._prefixes += ('work.generator_upgrade_r23',)
        self._checks = 0

    @property
    def identity(self):
        return deepcopy(self._identity)

    @property
    def metrics(self):
        return {'verification_calls': self._checks, 'unique_source_files': len(self._sources)}

    def _verify_runtime(self):
        common = {'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
                  'platform': platform.platform()}
        political = dict(common, optimisation_flag=sys.flags.optimize,
                         libraries={name: sys.modules[name].__version__
                                    for name in ('shapely', 'numpy', 'scipy')})
        political['libraries']['geos'] = self._r20.shapely.geos_version_string
        soil = dict(common, numpy=self._r13.numpy.__version__, scipy=self._r13.scipy.__version__,
                    optimisation=sys.flags.optimize,
                    environment={key: os.environ.get(key) for key in
                                 ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                                  'PYTHONHASHSEED', 'MKL_CBWR')})
        if (political, soil) != self._runtime:
            raise ValueError('R23 source runtime changed; no silent rebind')

    def _verify_modules(self):
        for name, module in tuple(sys.modules.items()):
            path = getattr(module, '__file__', None)
            expected = self._source_strings.get(path) if type(path) is str else None
            required = expected is not None or any(name == prefix or name.startswith(prefix+'.')
                                                  for prefix in self._prefixes)
            required |= (name == '__main__' and path == str(self._r13.HERE/'__main__.py'))
            if required and (expected is None or getattr(module, '_R12_EXECUTED_SHA256', None) != expected):
                raise ValueError('executed source differs: '+str(path))

    def verify(self):
        if tuple(module.HERE for module in self._modules) != self._roots:
            raise ValueError('source inventory root changed')
        if ((r22.NATIVE, self._r21.NATIVE) != self._native
                or (r22.ROOT, self._r21.ROOT) != self._native_roots):
            raise ValueError('native source declarations changed')
        self._files.verify()
        self._verify_modules()
        self._verify_runtime()
        self._checks += 1
