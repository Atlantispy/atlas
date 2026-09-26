#!/usr/bin/env python3
"""Read-only check of installed package metadata against a pinned tectonics environment.

Standard library only. importlib.metadata reads installed distribution metadata;
no Atlas or numerical package is imported, and nothing is installed, upgraded,
repinned or written. Run it with the interpreter being checked. A pass means that
interpreter is inside the record's Python/platform scope and the selected routes'
installed versions equal their pins. It is not native-binary identity, CPU-feature
equality or checkpoint-continuation compatibility. See docs/TECTONICS_ENVIRONMENT.md.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.metadata as metadata
import json
import math
from pathlib import Path
import platform
import re
import struct
import sys
from typing import Any, Iterable

SCHEMA = 'atlas.tectonics-environment.v1'
DEFAULT_LOCK = 'tectonics/requirements/windows-amd64-cp312.json'
SCOPE = ('implementation', 'python', 'sys_platform', 'machine', 'pointer_bits')
OBSERVATION = ('system', 'release', 'os_version', 'compiler', 'build')
FIELDS = {'schema', 'status', 'observed', 'declared_by', 'provenance', 'scope', 'observation',
          'routes', 'not_pinned', 'unpinned_tools', 'limits'}
ROUTE_FIELDS = {'requirements', 'declared', 'includes', 'note', 'packages'}
PIN_FIELDS = {'version', 'wheel', 'status', 'direct', 'required_by', 'evidence'}
STATUSES = ('tested', 'installed')
ONLY_BINARY = '--only-binary=:all:'
MAX_FILE_BYTES = 1_000_000
MAX_INCLUDE_DEPTH = 4
MAX_INCLUDE_FILES = 32
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
VERSION = re.compile(r'[0-9][0-9A-Za-z.+!_-]*')
PART = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*')
PIN = re.compile(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][0-9A-Za-z.+!_-]*)')
INCLUDE = re.compile(r'-r\s+([A-Za-z0-9_][A-Za-z0-9_.-]*\.txt)')


class LockError(ValueError):
    """An unreadable or inconsistent pinned-environment record: a failure, never a pass."""


def normal(name: str) -> str:
    """PEP 503 distribution-name normalisation."""
    return re.sub(r'[-_.]+', '-', name).lower()


def _read(root: Path, relative: Any) -> str:
    if type(relative) is not str or not all(PART.fullmatch(part) for part in relative.split('/')):
        raise LockError(f'invalid repository-relative path {relative!r}')
    try:
        with root.joinpath(*relative.split('/')).open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError as error:
        raise LockError(f'{relative}: cannot be read ({error.strerror or error})') from None
    if len(data) > MAX_FILE_BYTES:
        raise LockError(f'{relative}: exceeds the {MAX_FILE_BYTES}-byte limit')
    try:
        return data.decode('utf-8')
    except UnicodeError:
        raise LockError(f'{relative}: not UTF-8 text') from None


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _nonfinite(name: str) -> Any:
    raise ValueError(f'non-finite number {name}')


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'non-finite number {value}')
    return result


def load_lock(root: Path, relative: str = DEFAULT_LOCK) -> dict[str, Any]:
    try:
        lock = json.loads(_read(root, relative), object_pairs_hook=_unique,
                          parse_constant=_nonfinite, parse_float=_finite_float)
    except (ValueError, RecursionError) as error:
        if isinstance(error, LockError):
            raise
        raise LockError(f'{relative}: invalid strict JSON ({error})') from None
    validate(lock)
    return lock


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise LockError(f'{label}: explicit non-empty text is required')
    return value


def _strings(value: Any, label: str) -> list[str]:
    if type(value) is not list or not value or any(type(item) is not str or not item.strip()
                                                   for item in value):
        raise LockError(f'{label}: expected a non-empty list of text')
    return value


def validate(lock: Any) -> None:
    """Refuse any record the check could misread; unknown fields are never skipped."""
    if type(lock) is not dict or lock.get('schema') != SCHEMA or set(lock) != FIELDS:
        raise LockError(f'the record must use schema {SCHEMA} with exactly {sorted(FIELDS)}')
    for key in ('status', 'observed', 'declared_by', 'provenance'):
        _text(lock[key], key)
    scope, observation = lock['scope'], lock['observation']
    if type(scope) is not dict or set(scope) != set(SCOPE) or type(scope['pointer_bits']) is not int:
        raise LockError(f'scope requires exactly {list(SCOPE)}, with integer pointer_bits')
    for key in SCOPE[:-1]:
        _text(scope[key], 'scope.' + key)
    if type(observation) is not dict or set(observation) != set(OBSERVATION):
        raise LockError(f'observation requires exactly {list(OBSERVATION)}')
    for key in OBSERVATION:
        _text(observation[key], 'observation.' + key)
    for key in ('not_pinned', 'unpinned_tools'):
        if type(lock[key]) is not dict:
            raise LockError(f'{key}: expected an object')
        for name, reason in lock[key].items():
            _text(reason, f'{key}.{name}')
    _strings(lock['limits'], 'limits')
    routes = lock['routes']
    if type(routes) is not dict or not routes or any(
            type(spec) is not dict or set(spec) != ROUTE_FIELDS for spec in routes.values()):
        raise LockError(f'routes must be a non-empty object; each requires exactly {sorted(ROUTE_FIELDS)}')
    owner: dict[str, str] = {}
    for route, spec in routes.items():
        for key in ('requirements', 'declared', 'note'):
            _text(spec[key], f'{route}.{key}')
        includes = spec['includes']
        if type(includes) is not list or any(type(name) is not str or name == route or name not in routes
                                             or routes[name]['includes'] for name in includes):
            raise LockError(f'route {route}: includes must name other routes that include nothing')
        if type(spec['packages']) is not dict or not spec['packages']:
            raise LockError(f'route {route}: packages must be a non-empty object')
        for name, pin in spec['packages'].items():
            label = f'{route} {name}'
            if not NAME.fullmatch(name):
                raise LockError(f'{label}: use the normalised distribution name')
            if name in owner:
                raise LockError(f'{label}: already pinned by route {owner[name]}')
            owner[name] = route
            keys = set(pin) if type(pin) is dict else set()
            if not {'version', 'wheel', 'status'} <= keys <= PIN_FIELDS:
                raise LockError(f'{label}: requires version, wheel and status; optional '
                                'direct, required_by and evidence only')
            if type(pin['version']) is not str or not VERSION.fullmatch(pin['version']):
                raise LockError(f"{label}: invalid pinned version {pin['version']!r}")
            _text(pin['wheel'], label + ' wheel')
            if pin['status'] not in STATUSES:
                raise LockError(f'{label}: status must be tested or installed')
            if ('direct' in keys) == ('required_by' in keys) or pin.get('direct', True) is not True:
                raise LockError(f'{label}: declare exactly one of direct: true or required_by')
            if (pin['status'] == 'tested') != ('evidence' in keys):
                raise LockError(f'{label}: tested pins need evidence; installed-only pins must not claim any')
            if 'evidence' in keys:
                _strings(pin['evidence'], label + ' evidence')
    for route, spec in routes.items():
        visible = set(spec['packages']).union(*(routes[name]['packages'] for name in spec['includes']))
        for name, pin in spec['packages'].items():
            if 'required_by' in pin:
                unknown = sorted(set(_strings(pin['required_by'], f'{route} {name} required_by')) - visible)
                if unknown:
                    raise LockError(f'{route} {name}: required_by names unpinned packages {unknown}')


def requirement_pins(root: Path, relative: str) -> dict[str, str]:
    """Exact pins from a pip requirements file and its -r includes; other syntax refuses."""
    pins: dict[str, str] = {}
    visited: set[str] = set()
    wheel_only = False

    def visit(path: str, chain: tuple[str, ...]) -> None:
        nonlocal wheel_only
        if path in chain or len(chain) >= MAX_INCLUDE_DEPTH:
            raise LockError(f'{path}: include cycle or excessive include depth')
        if path in visited:
            raise LockError(f'{path}: repeated include')
        if len(visited) >= MAX_INCLUDE_FILES:
            raise LockError(f'{path}: exceeds the {MAX_INCLUDE_FILES}-file include file limit')
        visited.add(path)
        folder = path.rsplit('/', 1)[0] + '/' if '/' in path else ''
        for number, raw in enumerate(_read(root, path).splitlines(), 1):
            line = re.split(r'(?:^|\s)#', raw, maxsplit=1)[0].strip()
            if not line:
                continue
            if line == ONLY_BINARY:
                wheel_only = True
                continue
            include = INCLUDE.fullmatch(line)
            if include:
                visit(folder + include.group(1), chain + (path,))
                continue
            pin = PIN.fullmatch(line)
            if pin is None:
                raise LockError(f'{path}:{number}: only exact name==version pins, -r includes '
                                f'and {ONLY_BINARY} are allowed')
            name = normal(pin.group(1))
            if name in pins:
                raise LockError(f'{path}:{number}: {name} is pinned twice')
            pins[name] = pin.group(2)

    visit(relative, ())
    if not wheel_only:
        raise LockError(f'{relative}: wheel-only policy {ONLY_BINARY} is required '
                        'in this file or an included file')
    return pins


def selected_routes(lock: dict[str, Any], requested: Iterable[str]) -> list[str]:
    """Requested routes preceded by the routes they include, each once."""
    chosen: list[str] = []
    for route in requested:
        if route not in lock['routes']:
            raise LockError(f"unknown route {route!r}; choose from {', '.join(lock['routes'])}")
        for name in lock['routes'][route]['includes'] + [route]:
            if name not in chosen:
                chosen.append(name)
    return chosen


def check_files(root: Path, lock: dict[str, Any], routes: list[str]) -> list[str]:
    """Each selected route's pip input must list exactly the record's pins."""
    failures = []
    for route in routes:
        spec = lock['routes'][route]
        expected = {name: pin['version'] for part in spec['includes'] + [route]
                    for name, pin in lock['routes'][part]['packages'].items()}
        actual = requirement_pins(root, spec['requirements'])
        different = sorted(name for name in set(actual) | set(expected)
                           if actual.get(name) != expected.get(name))
        if different:
            failures.append(f"lock {route}: {spec['requirements']} disagrees with the record for "
                            f"{', '.join(different)}; correct both together from one observation")
    return failures


def interpreter_facts() -> dict[str, Any]:
    """Facts about the running interpreter, which is the environment being checked."""
    return dict(implementation=sys.implementation.name, python=platform.python_version(),
                sys_platform=sys.platform, machine=platform.machine(),
                pointer_bits=struct.calcsize('P') * 8, system=platform.system(),
                release=platform.release(), os_version=platform.version(),
                compiler=platform.python_compiler(), build=' '.join(platform.python_build()))


def _wheel_tags(text: str | None) -> str:
    groups: dict[tuple[str, str], set[str]] = {}
    for line in (text or '').splitlines():
        parts = line[4:].strip().split('-') if line.startswith('Tag:') else []
        if len(parts) == 3:
            groups.setdefault((parts[1], parts[2]), set()).add(parts[0])
    return ' '.join(f"{'.'.join(sorted(tags))}-{abi}-{plat}"
                    for (abi, plat), tags in sorted(groups.items())) or 'none'


def installed(distributions: Iterable[Any]) -> dict[str, dict[str, set[str]]]:
    """Installed versions and wheel tags by normalised name, read from metadata only."""
    found: dict[str, dict[str, set[str]]] = {}
    for dist in distributions:
        name = dist.metadata.get('Name')
        if not name:
            continue
        entry = found.setdefault(normal(name), dict(versions=set(), wheels=set()))
        entry['versions'].add(dist.version)
        entry['wheels'].add(_wheel_tags(dist.read_text('WHEEL')))
    return found


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def check(lock: dict[str, Any], routes: list[str], facts: dict[str, Any],
          found: dict[str, dict[str, set[str]]], failures: Iterable[str] = ()
          ) -> tuple[list[str], list[str], list[str]]:
    """Return (failures, notes, report lines). A note never turns a mismatch into a pass."""
    failures, notes, lines = list(failures), [], []
    scope = lock['scope']
    wrong = [key for key in SCOPE if facts.get(key) != scope[key]]
    failures += [f'scope {key}: running {facts.get(key)!r}, pinned {scope[key]!r}; the pins were '
                 'observed only inside the pinned scope' for key in wrong]
    if not wrong:
        lines.append(f"scope      {scope['implementation']} {scope['python']}, {scope['sys_platform']}, "
                     f"{scope['machine']}, {scope['pointer_bits']}-bit: inside the pinned scope")
    for key in OBSERVATION:
        if facts.get(key) != lock['observation'][key]:
            notes.append(f"{key} is {facts.get(key)!r}, observed {lock['observation'][key]!r}: provenance "
                         'only, but native binaries and execution identities may differ')
    checked: set[str] = set()
    for route in routes:
        packages = lock['routes'][route]['packages']
        matched: Counter[str] = Counter()
        for name, pin in packages.items():
            checked.add(name)
            entry = found.get(name)
            if entry is None:
                failures.append(f"{route} {name}: not installed; pinned {pin['version']}")
            elif len(entry['versions']) > 1:
                failures.append(f"{route} {name}: several installed versions "
                                f"({', '.join(sorted(entry['versions']))}); pinned {pin['version']}")
            elif pin['version'] not in entry['versions']:
                failures.append(f"{route} {name}: installed {min(entry['versions'])}, "
                                f"pinned {pin['version']}")
            else:
                matched[pin['status']] += 1
                if entry['wheels'] != {pin['wheel']}:
                    notes.append(f"{name} {pin['version']}: installed wheel tag "
                                 f"{', '.join(sorted(entry['wheels']))}, observed {pin['wheel']}; "
                                 'same version, different build')
        if sum(matched.values()) == len(packages):
            lines.append(f"{route:<10} matched {_count(len(packages), 'pinned distribution')} "
                         f"({matched['tested']} tested, {matched['installed']} installed only)")
    others = len(set(found) - checked)
    if others:
        notes.append(f"{_count(others, 'other installed distribution')} outside the checked "
                     'routes, not checked')
    return failures, notes, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='repository root; defaults to the directory containing tools/')
    parser.add_argument('--lock', default=DEFAULT_LOCK,
                        help=f'repository-relative environment record (default {DEFAULT_LOCK})')
    parser.add_argument('--route', action='append',
                        help='route to check; repeatable (default core); included routes are added')
    parser.add_argument('--all', action='store_true', help='check every route in the record')
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        lock = load_lock(root, args.lock)
        routes = selected_routes(lock, list(lock['routes']) if args.all else args.route or ['core'])
        file_failures = check_files(root, lock, routes)
    except (LockError, OSError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    failures, notes, lines = check(lock, routes, interpreter_facts(),
                                   installed(metadata.distributions()), file_failures)
    for line in lines:
        print(line)
    for note in notes:
        print(f'note: {note}')
    if failures:
        for failure in failures:
            print(f'FAIL: {failure}', file=sys.stderr)
        print('Nothing was installed, upgraded or repinned. Recreate the environment from the '
              'pins, or record a new observation explicitly; never edit pins to match an '
              'unverified environment.', file=sys.stderr)
        return 1
    print(f"PASS: installed metadata matches {args.lock} for {', '.join(routes)}. Version "
          'metadata only: not native-binary identity, CPU features or checkpoint-continuation '
          'compatibility. No Atlas or numerical package was imported; nothing was installed or changed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
