"""Observe a folded runtime through its checked, strict fresh-runner route.

This print-only adapter runs in the explicitly pinned interpreter with -B -s -P.
It writes no policy, dispatches no worker and confers no runtime admission or
scientific acceptance. The constructor owns launching this fresh process and
retaining its single JSON result. Source-stage observations remain separate.
"""
from contextlib import redirect_stdout
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import types


REQUEST_SCHEMA = 'atlas.plan31.folded-identity-request.v1'
SCHEMA = 'atlas.execution-identity-probe.v2'
REQUEST_FIELDS = frozenset(('schema', 'workspace', 'source_manifest', 'fresh_profile',
    'bootstrap', 'fresh_runner', 'prepared_runner', 'interpreter', 'backend'))
RELATIVE_REFS = ('source_manifest', 'fresh_profile', 'bootstrap', 'fresh_runner', 'prepared_runner')
PYTHON_ENV = {'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
THREAD_ENV = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
LAUNCH_ENV = dict(PYTHON_ENV, **THREAD_ENV)
PRIVATE = 'atlas_tectonics._private'
MAX_REQUEST = 1 << 20
MAX_JSON = 8 << 20


class CaptureRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise CaptureRefused(message)


def _pin(value):
    require(type(value) is str and len(value) == 64 and
            all(letter in '0123456789abcdef' for letter in value),
            'complete lower-case SHA-256 required')
    return value


def _ordinary(path, *, directory=False):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and
            'bridge' not in (part.lower() for part in path.parts),
            'explicit absolute non-bridge path required')
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and
                not getattr(info, 'st_file_attributes', 0) & 0x400,
                'linked or reparse path refused')
    require(path.is_dir() if directory else path.is_file(),
            'ordinary directory required' if directory else 'ordinary file required')
    return path.resolve(strict=True)


def _relative(workspace, value, *, directory=False):
    require(type(value) is str and value and '\\' not in value and ':' not in value,
            'canonical contained workspace-relative path required')
    portable = PurePosixPath(value)
    require(not portable.is_absolute() and '..' not in portable.parts and
            portable.as_posix() == value and value != '.',
            'canonical contained workspace-relative path required')
    path = _ordinary(workspace / value, directory=directory)
    require(path.is_relative_to(workspace), 'source escaped selected workspace')
    return path


def _raw(path, pin, *, limit=None):
    pin = _pin(pin)
    path = _ordinary(path)
    with path.open('rb') as stream:
        raw = stream.read() if limit is None else stream.read(limit + 1)
    require(limit is None or len(raw) <= limit, 'pinned input exceeds its size bound')
    require(sha256(raw).hexdigest() == pin, 'pinned input digest mismatch: ' + path.name)
    _ordinary(path)
    return raw


def _file_hash(path):
    path = _ordinary(path)
    digest = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    _ordinary(path)
    return digest.hexdigest()


def _pairs(values):
    result = {}
    for key, value in values:
        require(key not in result, 'duplicate JSON key refused')
        result[key] = value
    return result


def _json(raw):
    def invalid(value):
        raise CaptureRefused('non-finite JSON refused: ' + value)
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _binding(value):
    require(type(value) is dict and set(value) == {'path', 'sha256'},
            'closed path/SHA-256 binding required')
    require(type(value['path']) is str and value['path'], 'explicit binding path required')
    _pin(value['sha256'])
    return value


def configuration(request_path, request_sha256):
    """Read-only request/ref checks. No selected source is executed here."""
    request_path = _ordinary(request_path)
    request = _json(_raw(request_path, request_sha256, limit=MAX_REQUEST))
    require(type(request) is dict and set(request) == REQUEST_FIELDS and
            request['schema'] == REQUEST_SCHEMA, 'closed folded identity request required')
    require(request['backend'] == 'scipy', 'the folded identity backend must be scipy')
    workspace = _ordinary(request['workspace'], directory=True)
    paths = {}
    for name in RELATIVE_REFS:
        binding = _binding(request[name])
        paths[name] = _relative(workspace, binding['path'])
        _raw(paths[name], binding['sha256'], limit=MAX_JSON if name in
             ('source_manifest', 'fresh_profile') else None)
    require(len(set(paths.values())) == len(paths), 'distinct identity inputs required')
    interpreter = _ordinary(_binding(request['interpreter'])['path'])
    require(_file_hash(interpreter) == request['interpreter']['sha256'],
            'selected interpreter digest mismatch')
    profile = _json(_raw(paths['fresh_profile'], request['fresh_profile']['sha256'], limit=MAX_JSON))
    require(type(profile) is dict and profile.get('schema') == 'atlas.fresh-interval-profile.v2',
            'authentic fresh profile schema required')
    require(_ordinary(profile['workspace'], directory=True) == workspace,
            'fresh profile workspace differs from request')
    require(profile['source_manifest'] == request['source_manifest'],
            'fresh profile manifest binding differs from request')
    native = _relative(workspace, profile['native_root'], directory=True)
    require(type(profile['import_roots']) is list and profile['import_roots'],
            'fresh profile requires explicit import roots')
    imports = tuple(_relative(workspace, value, directory=True) for value in profile['import_roots'])
    # Folded layouts legitimately share native_root and an import root. The
    # authenticated FreshSources selector owns their exact ordering and policy.
    expected = {'bootstrap': native / 'atlas_tectonics/integration_worker_bootstrap.py',
                'fresh_runner': native / 'atlas_tectonics/_private/run_fresh_interval.py',
                'prepared_runner': native / 'atlas_tectonics/_private/run_prepared_restart.py'}
    manifest = _json(_raw(paths['source_manifest'], request['source_manifest']['sha256'], limit=MAX_JSON))
    require(type(manifest) is dict and type(manifest.get('files')) is dict and
            manifest['files'] and type(manifest.get('source_hashes')) is dict and
            manifest['source_hashes'] and type(manifest.get('data_only')) is dict,
            'complete folded source/data manifest required')
    for name, expected_path in expected.items():
        require(paths[name] == expected_path, 'request selects a foreign installed ' + name)
        require(manifest['files'].get(request[name]['path']) == request[name]['sha256'],
                'installed input is absent from source closure: ' + name)
    require(_binding(profile['historical_inputs']) is not None,
            'fresh profile historical input binding required')
    return dict(request=request, request_path=request_path, request_sha256=_pin(request_sha256),
                workspace=workspace, paths=paths, interpreter=interpreter,
                native=native, imports=imports, profile=profile, manifest=manifest)


def _interpreter(config):
    require(sys.flags.dont_write_bytecode and sys.dont_write_bytecode and
            sys.flags.no_user_site and sys.flags.safe_path and
            not sys.flags.hash_randomization and not sys.flags.ignore_environment and
            not sys.flags.isolated, 'capture requires fresh -B -s -P and seed zero')
    present = {key: value for key, value in os.environ.items() if key.upper().startswith('PYTHON')}
    require(present == PYTHON_ENV, 'capture Python environment differs from exact allowlist')
    require(all(os.environ.get(key) == value for key, value in THREAD_ENV.items()),
            'capture requires single-threaded BLAS/OpenMP')
    require(_ordinary(sys.executable) == config['interpreter'] and
            _file_hash(sys.executable) == config['request']['interpreter']['sha256'],
            'live interpreter differs from pinned request')
    require(not any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') or
                    name == '_atlas_checked_installed_modules' for name in sys.modules),
            'fresh process required before installed selection')
    require(type(sys.path) is list and sys.path and
            all(type(entry) is str and entry and Path(entry).is_absolute() for entry in sys.path),
            'capture refuses empty or relative import paths')


def _verify_request(config):
    request = config['request']
    require(_json(_raw(config['request_path'], config['request_sha256'], limit=MAX_REQUEST)) == request,
            'request changed during identity capture')
    for name in RELATIVE_REFS:
        _raw(config['paths'][name], request[name]['sha256'], limit=MAX_JSON if name in
             ('source_manifest', 'fresh_profile') else None)
    require(_file_hash(config['interpreter']) == request['interpreter']['sha256'],
            'interpreter changed during identity capture')


def capture(config):
    """Actual strict context only; call once in a fresh pinned child process."""
    _interpreter(config)
    request, paths = config['request'], config['paths']
    raw = _raw(paths['bootstrap'], request['bootstrap']['sha256'])
    bootstrap = types.ModuleType('_plan31_folded_identity_bootstrap')
    bootstrap.__file__ = str(paths['bootstrap'])
    exec(compile(raw, str(paths['bootstrap']), 'exec', dont_inherit=True), bootstrap.__dict__)
    bootstrap._validate_interpreter()
    package = bootstrap.prepare_installed_runner(
        str(paths['fresh_profile']), request['fresh_profile']['sha256'],
        str(paths['fresh_runner']), runner_modules=(
            'start_gate', 'route2_gate', 'run_prepared_restart', 'run_fresh_interval'))
    require(package == PRIVATE, 'checked installed package differs')
    fresh = sys.modules.get(package + '.run_fresh_interval')
    prepared = sys.modules.get(package + '.run_prepared_restart')
    require(fresh is not None and prepared is not None and
            _ordinary(fresh.__file__) == paths['fresh_runner'] and
            _ordinary(prepared.__file__) == paths['prepared_runner'],
            'checked installed runner identity differs')
    profile = fresh.FreshProfile.read(paths['fresh_profile'], request['fresh_profile']['sha256'])
    sources = fresh.FreshSources(profile)
    require(sources.workspace == config['workspace'] and sources.native_root == config['native'] and
            sources.import_roots == config['imports'] and sources.manifest_path == paths['source_manifest'] and
            sources.manifest_pin == request['source_manifest']['sha256'],
            'actual FreshSources selection differs from pinned request')
    inventory_digest = sha256(_canonical(config['manifest']['source_hashes'])).hexdigest()
    expected = dict(source_manifest_sha256=request['source_manifest']['sha256'],
                    native_source_digest=inventory_digest)
    before = sources.verify()
    require(before == expected, 'initial selected source proof differs')
    try:
        with sources.selected():
            # The checked installed loader has authenticated package parents;
            # selected() supplies the sole fixture_identity_context lifetime.
            from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
            require_strict_execution()
            prepared.interpreter_gate()
            with ExecutionContext(request['backend']) as execution:
                provenance = dict(execution.provenance)
                require(provenance.get('execution_mode') == 'strict', 'strict execution provenance required')
                _pin(provenance.get('execution_identity'))
                execution.verify_boundary()
                sources.check_imported()
            # Successful __exit__ verifies and closes inside the fixture scope.
            sources.check_imported()
            loaded_count = sum(
                1 for module in tuple(sys.modules.values())
                if type(getattr(module, '__file__', None)) is str
                and Path(module.__file__).resolve().is_relative_to(sources.workspace)
                and Path(module.__file__).suffix == '.py'
                and not Path(module.__file__).resolve().is_relative_to(sources.workspace / '.r44-env'))
        after = sources.verify()
        require(after == before, 'selected source proof changed during capture')
    finally:
        _verify_request(config)
        require(sources.verify() == before, 'source/runtime finality differs after capture')
    history = dict(profile.record()['historical_inputs'])
    require(history['path'] == sources.historical_inputs.relative_path and
            history['sha256'] == prepared.HISTORICAL_INPUTS_SHA256,
            'actual historical input selection differs from fresh profile')
    result = dict(schema=SCHEMA, status='MEASURED_NOT_REVIEWED', backend=request['backend'],
        request_sha256=config['request_sha256'], historical_inputs=history,
        execution_provenance=provenance, source_manifest_sha256=request['source_manifest']['sha256'],
        native_source_digest=inventory_digest,
        native_root=sources.native_root.relative_to(sources.workspace).as_posix(),
        import_roots=[path.relative_to(sources.workspace).as_posix() for path in sources.import_roots],
        interpreter=dict(executable=str(config['interpreter']), sha256=request['interpreter']['sha256'],
            version=sys.version, hash_randomization=sys.flags.hash_randomization,
            flags={name: getattr(sys.flags, name) for name in (
                'dont_write_bytecode', 'no_user_site', 'safe_path', 'hash_randomization',
                'ignore_environment', 'isolated')},
            xoptions=dict(sys._xoptions), warnoptions=list(sys.warnoptions),
            prefix=sys.prefix, base_prefix=sys.base_prefix),
        launch_environment={name: os.environ.get(name) for name in sorted(LAUNCH_ENV)},
        loaded_workspace_sources=loaded_count, fresh_process=True, policy_written=False,
        worker_dispatched=False, source_verification_before=before, source_verification_after=after,
        execution_context_closed=True, strict_execution=True)
    for name in RELATIVE_REFS:
        result[name] = dict(request[name])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--request-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        # Imported runtime diagnostics may use stderr; stdout remains one JSON
        # measurement and is empty on every refusal.
        with redirect_stdout(sys.stderr):
            result = capture(configuration(args.request, args.request_sha256))
        print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        print('REFUSED ' + type(error).__name__ + ': ' + str(error), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

