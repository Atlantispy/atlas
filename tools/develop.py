#!/usr/bin/env python3
"""Atlas public development launcher. Use CPython with -I -B; see the runbook."""
import atexit
import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile

# Refuse stale execution bytes in this entry point. Fresh private bytecode paths
# also prevent reading old timestamp-based caches; no cache files are written.
_raw = Path(__file__).read_bytes()
if sys._getframe().f_code != compile(_raw, __file__, "exec", dont_inherit=True):
    raise RuntimeError("development launcher differs from current source")
_EXECUTED_SHA256 = hashlib.sha256(_raw).hexdigest()
if not sys.flags.isolated or not sys.dont_write_bytecode:
    raise SystemExit("Use: python -I -B tools/develop.py <command>")
_cache = tempfile.mkdtemp(prefix="atlas-public-no-bytecode-")
atexit.register(shutil.rmtree, _cache, ignore_errors=True)
sys.pycache_prefix = _cache
sys._xoptions["pycache_prefix"] = _cache  # Retained spawned workers inherit it.
_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_root / "development"))
sys.path.insert(1, str(_root / "engineering"))

class _SourceLoader(importlib.abc.Loader):
    """Capture the exact public-package bytes executed, ignoring old bytecode."""
    def __init__(self, path):
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raw = self.path.read_bytes()
        module.__file__ = str(self.path)
        exec(compile(raw, str(self.path), "exec", dont_inherit=True), module.__dict__)
        if self.path.read_bytes() != raw:
            raise RuntimeError("public development source changed during import")
        module._ATLAS_DEV_EXECUTED_SHA256 = hashlib.sha256(raw).hexdigest()


class _DevelopmentFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "atlas_dev":
            source = _root / "development/atlas_dev/__init__.py"
        elif fullname.startswith("atlas_dev."):
            name = fullname[len("atlas_dev."):]
            if not name.isidentifier():
                raise ImportError("flat public development module required")
            source = _root / "development/atlas_dev" / (name + ".py")
        else:
            return None
        return importlib.util.spec_from_file_location(fullname, source, loader=_SourceLoader(source),
                submodule_search_locations=[str(source.parent)] if fullname == "atlas_dev" else None)


sys.meta_path.insert(0, _DevelopmentFinder())
from atlas_dev.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
