"""Fresh full native identities using isolated provenance-function namespaces.

No native verifier is skipped or edited. One verification pass reads each exact
file once, checks any declared digest on every request and shares lexical parent
inspections. The next pass starts empty. Returned native identities are unchanged.
"""
import hashlib
import os
from pathlib import Path
import stat
from types import FunctionType, ModuleType, SimpleNamespace
from work.generator_runtime_r12 import provenance as common
from work.generator_upgrade_r22 import provenance as r22
from work.generator_upgrade_r22 import registry as native

_PROVENANCE = {'work.generator_runtime_r12.provenance'} | {
    'work.generator_upgrade_r'+str(n)+'.provenance' for n in (13,14,16,17,18,20,21,22)}


class Reader:
    """Per-pass byte snapshot, never persistent content/mtime reuse."""
    def __init__(self):
        self.raw = {}
        self.parents = {}
        self.cached_bytes = 0

    @staticmethod
    def info(path, directory):
        item = path.lstat()
        if stat.S_ISLNK(item.st_mode) or getattr(item, 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked/reparse source path refused: '+str(path))
        if directory and not stat.S_ISDIR(item.st_mode):
            raise ValueError('source parent is not a directory')
        if not directory and (not stat.S_ISREG(item.st_mode) or item.st_size > common.LIMIT):
            raise ValueError('bounded source file required')
        return item

    def checked(self, path, expected=None):
        path = Path(path)
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('absolute non-traversing source path required')
        if path not in self.raw:
            for parent in reversed(path.parents):
                if parent not in self.parents:
                    self.parents[parent] = self.info(parent, True)
            before = self.info(path, False)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0)
                                 | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'rb') as handle:
                opened = os.fstat(handle.fileno())
                if (not stat.S_ISREG(opened.st_mode) or opened.st_size > common.LIMIT
                        or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
                    raise ValueError('source changed while opening')
                raw = handle.read(opened.st_size+1)
                after = os.fstat(handle.fileno())
            current = self.info(path, False)
            if (len(raw) != opened.st_size or after.st_size != opened.st_size
                    or current.st_size != opened.st_size
                    or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)):
                raise ValueError('source changed while reading')
            # Bound temporary deduplication storage; larger closures simply
            # reread uncached files on repeated requests within this pass.
            if self.cached_bytes+len(raw) <= common.LIMIT:
                self.raw[path] = raw
                self.cached_bytes += len(raw)
        else:
            raw = self.raw[path]
        if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('source changed; no silent rebind: '+str(path))
        return raw

    def finish(self):
        for path, before in self.parents.items():
            after = self.info(path, True)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise ValueError('source parent changed during verification')


class _Clones:
    def __init__(self, reader):
        self.reader, self.modules = reader, {}

    def module(self, source):
        if source.__name__ in self.modules:
            return self.modules[source.__name__]
        result = SimpleNamespace(**vars(source))
        self.modules[source.__name__] = result
        env = dict(vars(source))
        for name, value in tuple(env.items()):
            if isinstance(value, ModuleType) and value.__name__ in _PROVENANCE:
                env[name] = self.module(value)
        env['checked'] = self.reader.checked
        for name in ('identity', 'verify', 'execution_identity', 'verify_execution'):
            value = env.get(name)
            if isinstance(value, FunctionType):
                cloned = FunctionType(value.__code__, env, value.__name__,
                    value.__defaults__, value.__closure__)
                cloned.__kwdefaults__ = value.__kwdefaults__
                env[name] = cloned
        for name, value in env.items():
            setattr(result, name, value)
        return result


def _identity(operation, clones):
    if operation not in native.OPERATIONS:
        raise ValueError('unknown implemented operation')
    own = clones.module(r22)
    if operation.startswith('terrain_'):
        from work.generator_upgrade_r22 import terrain
        return {'r22': own.identity(moving_ground=True),
            'r18': clones.module(terrain.consumer.p).identity(),
            'physical_decision': {'path': str(terrain.DECISION), 'sha256': terrain.DECISION_SHA}}
    return own.identity(moving_ground=operation == 'moving_roots')


def native_binding(operation):
    reader = Reader()
    try:
        return _identity(operation, _Clones(reader))
    finally:
        reader.finish()


def verify_native(operation, expected):
    reader = Reader()
    try:
        clones = _Clones(reader)
        if operation.startswith('terrain_'):
            from work.generator_upgrade_r22 import terrain
            clones.module(r22).verify(expected['r22'])
            clones.module(terrain.consumer.p).verify(expected['r18'])
        elif operation == 'moving_roots':
            clones.module(r22).verify(expected)
        if _identity(operation, clones) != expected:
            raise ValueError('native source/runtime binding changed; no repin')
    finally:
        reader.finish()
