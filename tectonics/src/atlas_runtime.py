"""Explicit source-bound fresh/prepared runtime commands; no default workload.

Profiles and native dependencies are supplied and authenticated by the existing
runner contracts. An ordinary invocation prints a command only. --launch keeps
the runner's existing admission gate; this adapter grants no scientific approval.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import stat


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


def _load_engine(name, profile_path, profile_pin):
    profile_path = Path(profile_path).absolute()
    profile = json.loads(_checked(profile_path, profile_pin), object_pairs_hook=_pairs)
    workspace = Path(profile['workspace'])
    relative = profile['native_root']
    root = workspace / relative
    if (not workspace.is_absolute() or Path(relative).is_absolute()
            or '..' in Path(relative).parts or ':' in relative or '\\' in relative
            or not root.resolve().is_relative_to(workspace.resolve())):
        raise ValueError('runtime binding escaped its workspace')
    if root.resolve() != Path(__file__).resolve().parent:
        raise ValueError('profile must select this installed native package')
    return importlib.import_module('atlas_tectonics._private.integration.' + name)


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
