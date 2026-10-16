"""Measure the current execution identity of a frozen composed runtime.

Store-free and print-only. The composer runs this after freezing the composed
tree and before writing the runtime-compatibility policy, and again after ANY
native change. The measurement happens in a fresh child interpreter started
with exactly the restart launch environment (PYTHONHASHSEED=0, one BLAS/OMP
thread, -B), the same .r44-env interpreter and the selected import roots in
profile order (native root first; no historical H root, H src or H native
trees). Every loaded workspace source must equal its manifest pin before and
after ExecutionContext capture, and the native package must be the selected one.
The printed provenance is a measurement, not a reviewed policy or admission.
"""
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import run_prepared_restart as RUN


SCHEMA = 'atlas.execution-identity-probe.v1'
BACKENDS = ('reference', 'scipy')
CHILD_TIMEOUT_SECONDS = 3600


class ProbeRefused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ProbeRefused(message)


def _relative(workspace, name, *, directory):
    require(type(name) is str and name and '\\' not in name and ':' not in name and
            not Path(name).is_absolute() and '..' not in Path(name).parts,
            'canonical contained workspace-relative path required')
    path = RUN.ordinary(workspace/name, directory=directory)
    require(path.is_relative_to(workspace), 'probe path escaped the workspace')
    return path


def configuration(*, workspace, manifest, manifest_sha256, native_root, import_roots, backend, python):
    """Store-free validation of exactly what the child will select."""
    workspace = RUN.ordinary(workspace, directory=True)
    require(backend in BACKENDS, 'explicit execution backend required')
    RUN._sha(manifest_sha256)
    interpreter = Path(python).absolute()
    require(interpreter.is_relative_to(workspace/'.r44-env'),
            'the isolated .r44-env interpreter of this workspace is required')
    roots = [_relative(workspace, native_root, directory=True),
             *(_relative(workspace, name, directory=True) for name in import_roots)]
    require(len(import_roots) >= 1 and len(set(roots)) == len(roots), 'explicit distinct import roots required')
    for root in roots:
        require(not RUN.historical_import_path(workspace, str(root)),
                'historical import root refused for the current identity: '+str(root))
    require((roots[0]/'atlas_tectonics/__init__.py').is_file(), 'native root must hold the atlas_tectonics package')
    manifest_path = _relative(workspace, manifest, directory=False)
    RUN.pinned_json(manifest_path, manifest_sha256)
    return dict(workspace=workspace, manifest=manifest_path, manifest_sha256=manifest_sha256,
                roots=roots, backend=backend, python=interpreter)


def child_command(config, *, manifest, native_root, import_roots):
    return [str(config['python']), '-B', str(Path(__file__).resolve()), '--child',
        '--workspace', str(config['workspace']), '--manifest', manifest,
        '--manifest-sha256', config['manifest_sha256'], '--native-root', native_root,
        *(item for name in import_roots for item in ('--import-root', name)),
        '--backend', config['backend']]


def _verify(config):
    """Manifest files, data-only references and the complete native inventory."""
    manifest = RUN.pinned_json(config['manifest'], config['manifest_sha256'])
    require(type(manifest.get('files')) is dict and manifest['files'] and
            type(manifest.get('source_hashes')) is dict and manifest['source_hashes'] and
            type(manifest.get('data_only')) is dict,
            'whole native inventory, participating helpers and data-only references required')
    workspace, native = config['workspace'], config['roots'][0]
    for name, pin in (*manifest['files'].items(), *manifest['data_only'].items()):
        require(RUN.file_hash(_relative(workspace, name, directory=False)) == RUN._sha(pin),
                'pinned source changed: '+name)
    actual = {path.relative_to(native).as_posix(): RUN.file_hash(path)
              for path in sorted((native/'atlas_tectonics').rglob('*.py'))}
    require(actual == manifest['source_hashes'], 'complete native package inventory differs from the manifest')
    return manifest, actual


def _loaded(config, manifest):
    workspace, native = config['workspace'], config['roots'][0]/'atlas_tectonics'
    count = 0
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if name == 'atlas_tectonics' or name.startswith('atlas_tectonics.'):
            require(type(filename) is str and Path(filename).resolve().is_relative_to(native),
                    'native module outside the selected runtime: '+name)
        if not filename:
            continue
        path = Path(filename).resolve()
        if not path.is_relative_to(workspace) or path.suffix != '.py' or path.is_relative_to(workspace/'.r44-env'):
            continue
        relative = path.relative_to(workspace).as_posix()
        require(manifest['files'].get(relative) == RUN.file_hash(path), 'unbound loaded source: '+relative)
        count += 1
    for entry in tuple(sys.path):
        require(not RUN.historical_import_path(workspace, entry), 'historical import root on sys.path: '+str(entry))
    return count


def child(config):
    """Fresh interpreter only: identity under the exact launch environment."""
    require(sys.dont_write_bytecode, 'run with -B to preserve frozen sources')
    require({name: os.environ.get(name) for name in RUN.LAUNCH_ENV} == RUN.LAUNCH_ENV and
            sys.flags.hash_randomization == 0, 'the probe child requires the exact restart launch environment')
    require(not any(name == 'atlas_tectonics' or name.startswith('atlas_tectonics.') for name in sys.modules),
            'fresh interpreter required before native selection')
    manifest, inventory = _verify(config)
    sys.path[:0] = [str(root) for root in config['roots']]
    from atlas_tectonics.reuse import ExecutionContext, require_strict_execution
    require_strict_execution()
    with ExecutionContext(config['backend']) as execution:
        provenance = dict(execution.provenance)
        execution.verify_boundary()
    loaded = _loaded(config, manifest)
    require(_verify(config) == (manifest, inventory), 'sources changed during the identity measurement')
    return dict(schema=SCHEMA, status='MEASURED_NOT_REVIEWED', backend=config['backend'],
        execution_provenance=provenance, source_manifest_sha256=config['manifest_sha256'],
        native_source_digest=sha256(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        native_root=config['roots'][0].relative_to(config['workspace']).as_posix(),
        import_roots=[root.relative_to(config['workspace']).as_posix() for root in config['roots'][1:]],
        interpreter=dict(executable=str(config['python']), version=sys.version,
            hash_randomization=sys.flags.hash_randomization),
        launch_environment={name: os.environ.get(name) for name in sorted(RUN.LAUNCH_ENV)},
        loaded_workspace_sources=loaded, fresh_process=True, policy_written=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--native-root', required=True)
    parser.add_argument('--import-root', action='append', default=[])
    parser.add_argument('--backend', choices=BACKENDS, default='scipy')
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args(argv)
    config = configuration(workspace=args.workspace, manifest=args.manifest,
        manifest_sha256=args.manifest_sha256, native_root=args.native_root,
        import_roots=args.import_root, backend=args.backend, python=sys.executable)
    if args.child:
        print(json.dumps(child(config), sort_keys=True), flush=True)
        return 0
    argv = child_command(config, manifest=args.manifest, native_root=args.native_root,
                         import_roots=args.import_root)
    result = subprocess.run(argv, env=RUN.launch_environment(), cwd=config['roots'][0],
                            capture_output=True, text=True, timeout=CHILD_TIMEOUT_SECONDS)
    lines = result.stdout.strip().splitlines()
    require(result.returncode == 0 and lines, 'identity child failed: '+result.stderr[-4000:])
    measured = RUN._json(lines[-1])
    require(type(measured) is dict and measured.get('schema') == SCHEMA and
            measured.get('source_manifest_sha256') == args.manifest_sha256, 'identity child returned no measurement')
    print(json.dumps(measured, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
