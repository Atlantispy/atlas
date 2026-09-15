#!/usr/bin/env python3
"""Read-only AST tripwires for Atlas's documented active adapter routes.

Standard library only. Never imports Atlas, loads checkpoints, installs packages,
executes a recipe, or rewrites the review inventory. A pass is not runtime,
scientific, provenance or checkpoint-compatibility validation.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any

SCHEMA = 'atlas.coding-safety-map.v1'
ADAPTER_NAMES = frozenset({'_adapt', 'clone', '_module', '_function', 'FunctionType'})
MAX_FILE_BYTES = 2_000_000


class MapError(ValueError):
    """An unreadable, ambiguous or invalid review inventory."""


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(type(item) is not str for item in value):
        raise MapError(f'{label}: expected a list of strings')
    return value


def _file(root: Path, relative: str) -> Path:
    if type(relative) is not str or not relative or '\\' in relative or ':' in relative:
        raise MapError(f'invalid repository-relative path: {relative!r}')
    parts = relative.split('/')
    if any(part in ('', '.', '..') for part in parts) or PurePosixPath(relative).is_absolute():
        raise MapError(f'invalid repository-relative path: {relative!r}')
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise MapError(f'{relative}: symlink is not a reviewed source file')
    if not path.is_file():
        raise MapError(f'{relative}: missing file')
    return path


def _text(path: Path) -> str:
    with path.open('rb') as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise MapError(f'{path.name}: exceeds the source-only size limit')
    return raw.decode('utf-8')


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MapError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_map(root: Path) -> dict[str, Any]:
    path = _file(root, 'tools/coding_safety_manifest.json')
    value = json.loads(_text(path), object_pairs_hook=_unique_object)
    if type(value) is not dict:
        raise MapError('review inventory must be a JSON object')
    return value


def _normalise(snippet: str, expression: bool) -> str:
    parsed = ast.parse(snippet, mode='eval' if expression else 'exec')
    if expression:
        node = parsed.body
    else:
        if len(parsed.body) != 1:
            raise MapError('each import/anchor must contain exactly one statement')
        node = parsed.body[0]
    return ast.dump(node, include_attributes=False)


def _is_local_import(node: ast.AST) -> bool:
    if isinstance(node, ast.ImportFrom):
        return bool(node.level or (node.module or '').startswith('work.'))
    return isinstance(node, ast.Import) and any(a.name.startswith('work.') for a in node.names)


def _is_adapter(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    name = function.id if isinstance(function, ast.Name) else (
        function.attr if isinstance(function, ast.Attribute) else None)
    return name in ADAPTER_NAMES


def _compare(expected: list[str], actual: list[ast.AST], *, expression: bool) -> bool:
    # Ignore formatting, not multiplicity: removing one of two calls is drift.
    return Counter(_normalise(s, expression) for s in expected) == Counter(
        ast.dump(node, include_attributes=False) for node in actual)


def check(root: Path, inventory: dict[str, Any]) -> list[str]:
    """Return review failures. Invalid inventory is also failure, never a pass."""
    root = root.resolve(strict=True)
    if type(inventory) is not dict or inventory.get('schema') != SCHEMA:
        raise MapError('unsupported or missing review-inventory schema')
    fields = {'schema', 'reviewed_public_commit', 'scope', 'required_files', 'source_checks'}
    if set(inventory) != fields:
        raise MapError('unexpected or missing review-inventory fields')
    commit = inventory['reviewed_public_commit']
    if type(commit) is not str or len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise MapError('reviewed_public_commit must identify a public Git commit')
    if type(inventory['scope']) is not str or not inventory['scope'].strip():
        raise MapError('review scope must be explicit')
    required = _strings(inventory['required_files'], 'required_files')
    specs = inventory['source_checks']
    if not required or len(set(required)) != len(required):
        raise MapError('required_files must be non-empty and unique')
    if not isinstance(specs, list) or not specs:
        raise MapError('source_checks must be a non-empty list')
    failures: list[str] = []
    for path in required:
        try:
            _file(root, path)
        except (MapError, OSError) as error:
            failures.append(str(error))
    seen: set[str] = set()
    for spec in specs:
        if type(spec) is not dict or set(spec) != {'path', 'imports', 'adapters', 'anchors'}:
            raise MapError('each source check requires path, imports, adapters and anchors')
        path = spec['path']
        if type(path) is not str or path in seen:
            raise MapError('source check paths must be strings and unique')
        seen.add(path)
        imports = _strings(spec['imports'], path + ': imports')
        adapters = _strings(spec['adapters'], path + ': adapters')
        anchors = _strings(spec['anchors'], path + ': anchors')
        try:
            tree = ast.parse(_text(_file(root, path)), filename=path)
            nodes = list(ast.walk(tree))
            if not _compare(imports, [n for n in nodes if _is_local_import(n)], expression=False):
                failures.append(f'{path}: direct import map changed')
            if not _compare(adapters, [n for n in nodes if _is_adapter(n)], expression=True):
                failures.append(f'{path}: adapter target/overrides/call count changed')
            statements = {ast.dump(n, include_attributes=False) for n in nodes if isinstance(n, ast.stmt)}
            for anchor in anchors:
                if _normalise(anchor, False) not in statements:
                    failures.append(f'{path}: reviewed helper/default/alias contract changed')
        except (MapError, OSError, UnicodeError, SyntaxError) as error:
            failures.append(f'{path}: {error}')
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='repository root; defaults to the directory containing tools/')
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        inventory = load_map(root)
        failures = check(root, inventory)
    except (MapError, OSError, UnicodeError, SyntaxError, json.JSONDecodeError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(f'FAIL: {failure}', file=sys.stderr)
        print('Review the affected wiring, route map and tests. No inventory was rewritten.', file=sys.stderr)
        return 1
    print(f'PASS: {len(inventory["source_checks"])} selected source maps; '
          f'{len(inventory["required_files"])} required paths. '
          'Static review only; Atlas was not imported or executed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
