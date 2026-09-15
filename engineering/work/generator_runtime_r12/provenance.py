"""Exact R11 bootstrap and independently identified R12 execution code."""
import builtins
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys
import types

HERE = Path(__file__).resolve().parent
TASK = HERE.parents[1]
R11 = TASK / 'work/generator_upgrade_r11'
SEAL = TASK / 'outputs/generator-upgrade-r11/connected-reference-04/VERIFICATION.json'
SEAL_SHA = '0c255070852a198662f1022e24a1e4c7176de25ff6738f93dead339a2b48dd8a'
SCIENCE_SHA = '140539b98ecb96ecbe31067165111d07266f5aee775f572d987c433c255c8665'
LIMIT = 8 * 1024 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def checked(path, expected=None):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute non-traversing source path required')
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('linked/reparse source path refused')
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError('bounded source file required')
    raw = path.read_bytes()
    if len(raw) > LIMIT:
        raise ValueError('bounded source file required after read: ' + str(path))
    if expected is not None:
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise ValueError(f'source changed; no silent rebind: {path}; '
                             f'expected_sha256={expected}; actual_sha256={actual}')
    return raw


def load_science():
    seal = json.loads(checked(SEAL, SEAL_SHA))
    identity = seal['source_identity']
    pins = identity['r11_sources']
    if seal['source_sha256'] != SCIENCE_SHA or sha(identity) != SCIENCE_SHA or len(pins) != 49:
        raise ValueError('exact sealed R11 identity required')
    actual = {str(p): hashlib.sha256(checked(p)).hexdigest()
              for p in sorted(R11.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
              and p.suffix in ('.py', '.md', '.json')}
    if actual != pins:
        path = next(path for path in sorted(set(actual) | set(pins))
                    if actual.get(path) != pins.get(path))
        raise ValueError(f'sealed R11 inventory changed: first mismatch path={path}; '
                         f'expected_sha256={pins.get(path, "<not inventoried>")}; '
                         f'actual_sha256={actual.get(path, "<missing file>")}')
    loaded = {}
    for name in ('provenance', 'binding'):
        path = R11 / (name + '.py')
        raw = checked(path, pins[str(path)])
        module = types.ModuleType('_r12_exact_r11_' + name)
        module.__file__ = str(path)
        module.__package__ = 'work.generator_upgrade_r11'

        def local_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level:
                if level != 1 or name != '' or tuple(fromlist) != ('provenance',):
                    raise ValueError('undeclared R11 bootstrap import')
                return types.SimpleNamespace(provenance=loaded['provenance'])
            if name == 'work' or name.startswith('work.'):
                raise ValueError('undeclared project bootstrap import')
            return builtins.__import__(name, globals, locals, fromlist, level)

        module.__builtins__ = dict(vars(builtins), __import__=local_import)
        exec(compile(raw, str(path), 'exec', dont_inherit=True), module.__dict__)
        loaded[name] = module
        checked(path, pins[str(path)])
    bundle = loaded['binding'].load()
    if bundle.verify() != SCIENCE_SHA or bundle.identity != identity:
        raise ValueError('actual R11 scientific binding differs')
    return bundle


def execution_identity(bundle):
    """Conservative invalidation: all adapter code and actual runtime are bound."""
    files = {str(path): hashlib.sha256(checked(path)).hexdigest()
             for path in sorted(HERE.glob('*.py'))}
    if not 1 <= len(files) <= 128:
        raise ValueError('bounded execution source inventory required')
    for name, module in tuple(sys.modules.items()):
        if (name == 'work.generator_runtime_r12' or name.startswith('work.generator_runtime_r12.')
                or name == '__main__' and getattr(module, '__file__', None) == str(HERE / '__main__.py')):
            path = getattr(module, '__file__', None)
            loaded_sha = getattr(module, '_R12_EXECUTED_SHA256', None)
            if path not in files or loaded_sha != files[path]:
                raise ValueError(f'actually loaded R12 source differs: module={name}; '
                                 f'path={path}; '
                                 f'expected_sha256(current file)={files.get(path, "<not inventoried>")}; '
                                 f'actual_sha256(loaded module)={loaded_sha if loaded_sha is not None else "<missing capture>"}')
    return {'schema': 'diadem.shared-execution-binding.r12',
            'science_sha256': bundle.source_sha256, 'science_seal_sha256': SEAL_SHA,
            'sources': files, 'scientific_runtime': bundle.identity['runtime'],
            'runtime': {'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
                        'implementation': platform.python_implementation(),
                        'platform': platform.platform(), 'machine': platform.machine(),
                        'optimisation_flag': sys.flags.optimize,
                        'numerical_environment': {key: os.environ.get(key) for key in
                            ('PYTHONHASHSEED', 'OMP_NUM_THREADS', 'OMP_DYNAMIC',
                             'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'MKL_CBWR',
                             'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}}}


def python_pins(identity):
    """Deduplicate exact executable pins, including private bootstrap sources."""
    pins = {}

    def visit(value):
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is str and key.endswith('.py'):
                    path = Path(key)
                    if (not path.is_absolute() or '..' in path.parts
                            or type(item) is not str or len(item) != 64
                            or any(c not in '0123456789abcdef' for c in item)):
                        raise ValueError('exact absolute Python source pin required')
                    name = str(path)
                    if name in pins and pins[name] != item:
                        raise ValueError('conflicting executable source pins')
                    pins[name] = item
                else:
                    visit(item)
        elif type(value) is list:
            for item in value:
                visit(item)

    visit(identity)
    if not 1 <= len(pins) <= 2048:
        raise ValueError('bounded nonempty executable source inventory required')
    return pins


def verify_execution(bundle, identity, *, full=True):
    # Never accept a mutable in-memory identity as permission to repin sources.
    if (bundle.source_sha256 != SCIENCE_SHA or sha(bundle.identity) != SCIENCE_SHA
            or identity.get('science_sha256') != SCIENCE_SHA):
        raise ValueError('sealed scientific identity changed')
    if full:
        bundle.verify()
    else:
        # Workers already performed full recursive seal/data/inventory checks at
        # initialisation. Before and after every job still read/hash all pinned
        # executable bytes, without rebuilding the same nested evidence tree.
        # No timestamp-based trust or cached file digest is involved.
        pins = python_pins(bundle.identity)
        for path, expected in pins.items():
            checked(path, expected)
        current_bundle = bundle
        seen = set()
        while current_bundle is not None:
            if id(current_bundle) in seen:
                raise ValueError('cyclic scientific bundle ancestry')
            seen.add(id(current_bundle))
            for row in current_bundle.graph.executed.values():
                if pins.get(row['path']) != row['sha256']:
                    raise ValueError('actual executed source is not sealed')
            current_bundle.graph.verify()
            current_bundle = getattr(current_bundle, 'parent', None)
    current = execution_identity(bundle)
    if current != identity:
        changed = sorted(key for key in set(current) | set(identity) if current.get(key) != identity.get(key))
        raise ValueError('execution source/runtime changed during run: ' + ', '.join(changed))
