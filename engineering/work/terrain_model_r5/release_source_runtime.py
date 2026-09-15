"""Exact-source release bootstrap; no numerical imports or bytecode loading.

The release entry point executes this helper from captured bytes under a private
name. Every local Python import is then compiled from the captured source tree.
This is source provenance, not a sandbox for hostile Python or physical approval.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import stat
import sys

EXTENSIONS = {'.py', '.json', '.md', '.ps1'}
MAX_SOURCE_BYTES = 16*1024*1024
ACTIVE = None


def _plain(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked/reparse release source rejected')
    return path


def read_source(path):
    path = _plain(path)
    before = path.stat()
    def signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                info.st_nlink, getattr(info, 'st_file_attributes', 0))
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_SOURCE_BYTES:
        raise ValueError('bounded singly-linked regular release source required')
    with path.open('rb') as stream:
        if signature(os.fstat(stream.fileno())) != signature(before):
            raise ValueError('release source changed before read')
        raw = stream.read(MAX_SOURCE_BYTES+1)
        if signature(os.fstat(stream.fileno())) != signature(before):
            raise ValueError('release source changed during read')
    _plain(path)
    if len(raw) > MAX_SOURCE_BYTES or signature(path.stat()) != signature(before):
        raise ValueError('release source changed after read')
    return raw


def source_pin(name, raw):
    return {'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


class SourceRuntime(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Fresh process only; captured bytes are the only local execution source."""
    def __init__(self, root):
        self.root = _plain(root)
        self.raw = {path.name: read_source(path) for path in self._paths()}
        self.pins = [source_pin(name, raw) for name, raw in self.raw.items()]
        self.modules = {Path(name).stem: name for name in self.raw if name.endswith('.py')}
        self.loaded = {}
        self.installed = False
        self.check()  # Detect inventory/content changes during capture itself.

    def _paths(self):
        return [path for path in sorted(self.root.iterdir()) if path.suffix in EXTENSIONS]

    def check(self):
        paths = self._paths()
        if [path.name for path in paths] != list(self.raw):
            raise ValueError('release source inventory changed after capture')
        for path in paths:
            if read_source(path) != self.raw[path.name]:
                raise ValueError('release source bytes changed after capture')
        if self.installed and self not in sys.meta_path:
            raise ValueError('exact-source import guard was removed')
        for name, (module, pin) in self.loaded.items():
            if sys.modules.get(name) is not module:
                raise ValueError('loaded release module identity was replaced')
        return [value for name, value in sorted({pin['name']: pin
                for module, pin in self.loaded.values()}.items())]

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.modules:
            return importlib.util.spec_from_loader(fullname, self,
                origin=str(self.root/self.modules[fullname]))
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = self.modules[module.__name__]
        path, raw = self.root/name, self.raw[name]
        if read_source(path) != raw:
            raise ValueError('release source changed before compilation')
        module.__file__ = str(path)
        # Compile the captured bytes, never a path-based loader or __pycache__.
        exec(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0), module.__dict__)
        if read_source(path) != raw:
            raise ValueError('release source changed during execution')
        self.loaded[module.__name__] = (module, source_pin(name, raw))

    def install(self):
        if self.installed or set(self.modules) & set(sys.modules):
            raise ValueError('fresh process required; local release module already loaded')
        self.check()
        sys.meta_path.insert(0, self)
        self.installed = True

    def uninstall(self):
        if self in sys.meta_path:
            sys.meta_path.remove(self)
        self.installed = False


def launch(root):
    global ACTIVE
    if ACTIVE is not None:
        raise ValueError('release bootstrap already active')
    runtime = SourceRuntime(root)
    raw = globals().get('EXECUTED_SOURCE_BYTES')
    if type(raw) is not bytes or runtime.raw.get('release_source_runtime.py') != raw:
        raise ValueError('executed bootstrap helper bytes differ from captured sources')
    runtime.loaded[__name__] = (sys.modules[__name__], source_pin('release_source_runtime.py', raw))
    runtime.install()
    ACTIVE = runtime
    try:
        import release_shoreline_reference
        return release_shoreline_reference.main()
    finally:
        runtime.uninstall()
        ACTIVE = None
