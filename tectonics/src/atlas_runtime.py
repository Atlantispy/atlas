"""Explicit source-bound fresh/prepared runtime commands; no default workload.

Profiles and native dependencies are supplied and authenticated by the existing
runner contracts. An ordinary invocation prints a command only. --launch keeps
the runner's existing admission gate; this adapter grants no scientific approval.
"""
import argparse
import importlib
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import stat
import types


from contextlib import ExitStack, nullcontext
import sys
import threading


APPLICATION_SCHEMA = 'atlas.application-sources.v1'
APPLICATION_MANIFEST = 'atlas_tectonics/_application_sources.json'
APPLICATION_PIN = 'atlas_tectonics/_application_sources.sha256'
_application_lock = threading.RLock()
_application_state = threading.local()
_application_seen = None


def _application_shared_root(root):
    if root.name == 'src' and root.parent.name == 'tectonics':
        return root.parent.parent / 'shared' / 'src'
    return root


@lru_cache(maxsize=1)
def _application_declaration(root):
    manifest_path = root / APPLICATION_MANIFEST
    pin_path = root / APPLICATION_PIN
    # Existing source checkouts without packaged fixtures keep their existing
    # ExecutionContext checks. A partial installed declaration never falls back.
    if not manifest_path.exists() and not pin_path.exists():
        if any((root / 'atlas_tectonics/_fixtures').rglob('*.py')):
            raise ValueError('packaged fixtures require an installed application declaration')
        return None
    for item in (pin_path, *pin_path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('linked application declaration pin')
    raw_pin = pin_path.read_bytes()
    if (len(raw_pin) != 65 or raw_pin[-1:] != b'\n'
            or any(c not in b'0123456789abcdef' for c in raw_pin[:-1])):
        raise ValueError('invalid application declaration pin')
    pin = raw_pin[:-1].decode('ascii')
    if manifest_path.stat().st_size > 8 * 1024**2:
        raise ValueError('application declaration is too large')
    def nonfinite(value):
        raise ValueError('nonfinite application declaration: ' + value)
    record = json.loads(_checked(manifest_path, pin), object_pairs_hook=_pairs, parse_constant=nonfinite)
    if (type(record) is not dict or set(record) != {
            'schema', 'files', 'data_only', 'source_hashes', 'fixture_source_map', 'origin', 'application_files'}
            or record['schema'] != APPLICATION_SCHEMA
            or any(type(record[k]) is not dict for k in ('files', 'data_only', 'source_hashes'))
            or not record['files'] or record['files'].keys() & record['data_only'].keys()):
        raise ValueError('invalid installed application declaration')
    if (type(record['application_files']) is not dict
            or set(record['application_files']) != {'atlas_runtime.py'}):
        raise ValueError('explicit installed application adapter required')
    if record['source_hashes'] != record['files']:
        raise ValueError('application source declaration differs')
    return pin, record


@lru_cache(maxsize=1)
def _application_source_rows(root):
    from atlas_tectonics.integration.reuse import _declared_source_rows
    _, record = _application_declaration(root)
    return _declared_source_rows(record, root, root)


def _application_verify(active):
    if active['thread'] is not threading.current_thread():
        raise ValueError('application source scope belongs to another thread')
    if 'shared' in active and active['shared'][1] not in sys.meta_path:
        raise ValueError('application shared source finder is no longer installed')
    if active['reuse']._fixture_identity_sources() is not active['selection']:
        raise ValueError('application fixture selection changed')

class _ApplicationSources:
    """One same-thread declaration lease; the final lease closes the finder."""
    def __init__(self):
        self._active = None
        self._entered = False

    def __enter__(self):
        global _application_seen
        with _application_lock:
            if self._entered:
                raise ValueError('application source lease already entered')
            root = Path(__file__).resolve().parent
            active = getattr(_application_state, 'active', None)
            if active is not None:
                if active['root'] != root:
                    raise ValueError('another application package is selected')
                _application_verify(active)
                active['leases'] += 1
            else:
                declared = _application_declaration(root)
                identity = (root, None if declared is None else declared[0])
                if _application_seen is not None and identity != _application_seen:
                    raise ValueError('changed application declaration requires a fresh interpreter')
                if declared is None:
                    _application_seen = identity
                    self._entered = True
                    return self
                pin, record = declared
                active = dict(root=root, pin=pin, record=record,
                              thread=threading.current_thread(), leases=1, stack=ExitStack())
                try:
                    files = record['files']
                    if 'atlas_shared/__init__.py' in files:
                        helper = importlib.import_module('atlas_tectonics.integration.parallel.worker_bootstrap')
                        finder = helper.application_shared_finder(root, files)
                        sys.meta_path.insert(0, finder)
                        active['stack'].callback(sys.meta_path.remove, finder)
                        active['stack'].enter_context(helper.public_import_scope(root, finder))
                        active['shared'] = helper, finder
                        importlib.import_module('atlas_shared')
                    selection = helper.public_import_scope(root, finder) if 'shared' in active else nullcontext()
                    with selection:
                        reuse = importlib.import_module('atlas_tectonics.integration.reuse')
                    if Path(reuse.__file__).resolve() != root / 'atlas_tectonics/integration/reuse.py':
                        raise ValueError('application loaded a different native package')
                    active['reuse'] = reuse
                    active['stack'].enter_context(reuse.fixture_identity_context(
                        root / APPLICATION_MANIFEST, pin, root, manifest=record,
                        source_rows=_application_source_rows(root)))
                    active['selection'] = reuse._fixture_identity_sources()
                    if 'shared' in active:
                        helper.verify_installed_modules(root, files, root, shared_only=True,
                                                        shared_root=_application_shared_root(root))
                except BaseException:
                    active['stack'].close()
                    raise
                _application_state.active = active
                _application_seen = identity
            self._active = active
            self._entered = True
            return self

    def close(self):
        with _application_lock:
            if not self._entered:
                return
            active = self._active
            if active is None:
                self._entered = False
                return
            if active['thread'] is not threading.current_thread():
                raise ValueError('application source lease must close on its owning thread')
            self._entered = False
            self._active = None
            active['leases'] -= 1
            if active['leases'] == 0:
                try:
                    active['stack'].close()
                finally:
                    _application_state.active = None

    def __exit__(self, *args):
        self.close()


def application_sources():
    """Bind installed executable fixtures only; no workload/profile selection.

    The scope retains selection across the enclosing operation. Native contexts
    retain a declaration token and select it again at source-check boundaries.
    Nested scopes reuse only the same declaration on the owning thread; the
    native fixture context is entered once. A changed package requires a fresh
    interpreter and new saved-request identities; this API never repins.
    """
    return _ApplicationSources()


def _checked(path, pin):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('runtime source path must be absolute')
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('runtime refuses linked source paths')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError('runtime source digest mismatch')
    return raw


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError('duplicate runtime binding key')
        result[key] = value
    return result


def _checked_bootstrap(root, workspace, files):
    helper_path = root / 'atlas_tectonics/integration/parallel/worker_bootstrap.py'
    if helper_path.relative_to(workspace).as_posix() not in files:
        raise ValueError('selected package has no installed startup helper')
    raw = helper_path.read_bytes()
    helper = types.ModuleType('_installed_runner_bootstrap')
    helper.__file__ = str(helper_path)
    exec(compile(raw, str(helper_path), 'exec', dont_inherit=True), helper.__dict__)
    return helper


def _load_engine(name, profile_path, profile_pin):
    # No atlas import may precede authentication: even a genuine-path module
    # object could contain stale or foreign executed code.
    profile_path = Path(profile_path).absolute()
    profile = json.loads(_checked(profile_path, profile_pin), object_pairs_hook=_pairs)
    workspace = Path(profile['workspace'])
    def contained(relative):
        path = workspace / relative
        if (not workspace.is_absolute() or Path(relative).is_absolute()
                or '..' in Path(relative).parts or ':' in relative or '\\' in relative
                or not path.resolve().is_relative_to(workspace.resolve())):
            raise ValueError('runtime binding escaped its workspace')
        return path
    root = contained(profile['native_root'])
    if root.resolve() != Path(__file__).resolve().parent:
        raise ValueError('profile must select this installed native package')
    binding = profile['source_manifest']
    manifest = json.loads(_checked(contained(binding['path']), binding['sha256']), object_pairs_hook=_pairs)
    helper = _checked_bootstrap(root, workspace, manifest['files'])
    selection = profile, manifest, None, workspace.resolve(), root.resolve()
    helper.prepare_installed_runner(profile_path.resolve(), profile_pin,
        helper._runner_path(root, name), runner_modules=(name,), source_selection=selection)
    return importlib.import_module(helper._INSTALLED_PACKAGE + '.' + name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('route', choices=('fresh', 'prepared'))
    parser.add_argument('--production-release',action='store_true',help='explicit authenticated packaged production only')
    args, remaining = parser.parse_known_args(argv)
    if args.production_release:
        remaining.append('--production-release')
    name = 'run_fresh_interval' if args.route == 'fresh' else 'run_prepared_restart'
    # The underlying runners use argparse's long-option abbreviations. Refuse
    # those spellings too, before any authenticated runner import/delegation.
    internal = ('--workload', '--start-gate')
    if any(value.startswith('--') and value.split('=',1)[0] != '--'
           and any(flag.startswith(value.split('=',1)[0]) for flag in internal)
           for value in remaining):
        parser.error('internal workload/start-gate arguments belong to the admitted runner child')
    # An abbreviated opt-in must not become a production choice downstream.
    if any(value.startswith('--') and value.split('=', 1)[0] != '--production-release'
           and '--production-release'.startswith(value.split('=', 1)[0])
           for value in remaining):
        parser.error('production Release requires the exact --production-release flag')
    declared = argparse.ArgumentParser(add_help=False)
    declared.add_argument('--profile', type=Path, required=True)
    declared.add_argument('--profile-sha256', required=True)
    profile_args, _ = declared.parse_known_args(remaining)
    engine = _load_engine(name, profile_args.profile, profile_args.profile_sha256)
    return engine.main(remaining)


if __name__ == '__main__':
    raise SystemExit(main())
