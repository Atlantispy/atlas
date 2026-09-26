#!/usr/bin/env python3
"""Read-only check of an explicit current-evidence register.

Standard library only. Never imports Atlas, runs a campaign, edits a receipt,
repins a digest, regenerates the register or writes a file. A pass means every
registered receipt is byte-identical to its classified version and, for each
*current* record, every repository file its receipt binds still has the
recorded SHA-256. It is not runtime, native-execution, platform or scientific
verification. Trusted local checkout only: links and reparse points are refused,
but this is not a sandbox against concurrent hostile renames.
See docs/CURRENT_EVIDENCE.md.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterator

SCHEMA = 'atlas.current-evidence-register.v1'
DEFAULT_REGISTER = 'tectonics/evidence/current-evidence.json'
STATUSES = ('current', 'historical', 'superseded', 'invalid')
KINDS = ('runtime', 'artefact', 'historical')
CAPTURE = '{key}'
MAX_FILE_BYTES = 16_000_000
MAX_DEPTH = 64
DIGEST = re.compile(r'[0-9a-f]{64}')
DIGEST_LIKE = re.compile(r'[0-9A-Fa-f]{64}')
RECORD_ID = re.compile(r'[a-z0-9][a-z0-9.-]{0,127}')
SEGMENT = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.+-]{0,254}')
DEVICE = re.compile(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)', re.I)
INDEX = re.compile(r'0|[1-9][0-9]*')
REPARSE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
COMMON = {'id', 'path', 'sha256', 'status', 'note'}
FIELDS = {'current': {'bindings', 'not_checked', 'limits'}, 'historical': set(),
          'superseded': {'superseded_by'}, 'invalid': set()}


class RegisterError(ValueError):
    """An unreadable, ambiguous or invalid register: always a failure, never a pass."""


class EvidenceError(ValueError):
    """A declared repository file that cannot be read safely or parsed strictly."""


def _parts(relative: Any) -> list[str]:
    # Portable POSIX-relative names only: no traversal, drive, stream or device.
    if type(relative) is not str or not relative or len(relative) > 1024:
        raise EvidenceError(f'refused repository-relative path {relative!r}')
    parts = relative.split('/')
    for part in parts:
        if not SEGMENT.fullmatch(part) or part.endswith('.') or DEVICE.match(part):
            raise EvidenceError(f'refused repository-relative path {relative!r}')
    return parts


def _unsafe(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & REPARSE)


def read_file(root: Path, relative: str) -> bytes:
    """Read one bounded regular file below root without following links or reparse points."""
    path, info = root, None
    for part in _parts(relative):
        path = path / part
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            raise EvidenceError(f'{relative}: missing file') from None
        except OSError as error:
            raise EvidenceError(f'{relative}: cannot be inspected ({error.strerror})') from None
        if _unsafe(info):
            raise EvidenceError(f'{relative}: symlink or reparse point refused')
    if not stat.S_ISREG(info.st_mode):
        raise EvidenceError(f'{relative}: not a regular file')
    try:
        with open(path, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise EvidenceError(f'{relative}: replaced while being checked')
            data = stream.read(MAX_FILE_BYTES + 1)
    except OSError as error:
        raise EvidenceError(f'{relative}: cannot be read ({error.strerror})') from None
    if len(data) > MAX_FILE_BYTES:
        raise EvidenceError(f'{relative}: exceeds the {MAX_FILE_BYTES}-byte check limit')
    return data


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


def parse_json(data: bytes, label: str) -> Any:
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_unique,
                          parse_constant=_nonfinite, parse_float=_finite_float)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise EvidenceError(f'{label}: invalid strict JSON ({error})') from None


def load_register(root: Path, relative: str = DEFAULT_REGISTER) -> Any:
    try:
        return parse_json(read_file(root.resolve(strict=True), relative), relative)
    except EvidenceError as error:
        raise RegisterError(str(error)) from None


def _escape(key: str) -> str:
    return key.replace('~', '~0').replace('/', '~1')


def _pattern(value: Any, label: str) -> tuple[str, ...]:
    """JSON pointer; a whole segment of * matches one level, {key} also captures it."""
    if type(value) is not str or not value.startswith('/') or len(value) > 512:
        raise RegisterError(f'{label}: pointer must be a JSON-pointer pattern starting with /')
    segments = []
    for raw in value[1:].split('/'):
        wildcard = raw in ('*', CAPTURE)
        if not raw or re.search(r'~(?![01])', raw) or (not wildcard and re.search(r'[*{}]', raw)):
            raise RegisterError(f'{label}: invalid pointer segment {raw!r}')
        segments.append(raw if wildcard else raw.replace('~1', '/').replace('~0', '~'))
    if segments.count(CAPTURE) > 1:
        raise RegisterError(f'{label}: at most one {CAPTURE} capture is supported')
    return tuple(segments)


def _children(value: Any, head: str) -> list[tuple[str, Any]]:
    wildcard = head in ('*', CAPTURE)
    if isinstance(value, dict):
        return list(value.items()) if wildcard else ([(head, value[head])] if head in value else [])
    if isinstance(value, list):
        if wildcard:
            return [(str(index), item) for index, item in enumerate(value)]
        if INDEX.fullmatch(head) and int(head) < len(value):
            return [(head, value[int(head)])]
    return []


def _match(value: Any, segments: tuple[str, ...], pointer: str = '',
           key: str | None = None) -> Iterator[tuple[str, Any, str | None]]:
    if not segments:
        yield pointer, value, key
        return
    head = segments[0]
    for name, child in _children(value, head):
        yield from _match(child, segments[1:], f'{pointer}/{_escape(name)}',
                          name if head == CAPTURE else key)


def _leaves(value: Any, pointer: str = '', depth: int = 0) -> Iterator[tuple[str, Any]]:
    if depth > MAX_DEPTH:
        raise EvidenceError(f'{pointer}: nesting exceeds {MAX_DEPTH} levels')
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaves(child, f'{pointer}/{_escape(key)}', depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, f'{pointer}/{index}', depth + 1)
    else:
        yield pointer, value


def _digest_bearing(pointer: str, value: Any) -> bool:
    return 'sha256' in pointer.lower() or (type(value) is str and bool(DIGEST_LIKE.fullmatch(value)))


def _text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise RegisterError(f'{label}: explicit non-empty text is required')
    return value


def _path(value: Any, label: str) -> str:
    try:
        _parts(value)
    except EvidenceError as error:
        raise RegisterError(f'{label}: {error}') from None
    return value


def _rules(value: Any, label: str, fields: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RegisterError(f'{label}: expected a list')
    rules = []
    for index, rule in enumerate(value):
        where = f'{label}[{index}]'
        if type(rule) is not dict or set(rule) != fields:
            raise RegisterError(f'{where}: requires exactly {sorted(fields)}')
        segments = _pattern(rule['pointer'], where)
        if 'file' in fields:
            template = rule['file']
            if type(template) is not str or template.count(CAPTURE) != int(CAPTURE in segments):
                raise RegisterError(f'{where}: file must use {CAPTURE} exactly when the pointer captures it')
            _path(template.replace(CAPTURE, 'key'), where)
            if segments[-1] != CAPTURE and segments[-1].lower().endswith('_id'):
                raise RegisterError(f'{where}: an identity field is not a source-file digest; '
                                    'declare it under not_checked')
        else:
            if rule['kind'] not in KINDS:
                raise RegisterError(f'{where}: kind must be one of {", ".join(KINDS)}')
            _text(rule['reason'], where + '.reason')
        rules.append(dict(rule, segments=segments))
    return rules


def validate(register: Any) -> list[dict[str, Any]]:
    """Return normalised records. Any ambiguity is a RegisterError, never a skipped record."""
    if type(register) is not dict or register.get('schema') != SCHEMA:
        raise RegisterError('unsupported or missing register schema')
    if set(register) != {'schema', 'scope', 'records'}:
        raise RegisterError('unexpected or missing register fields')
    _text(register['scope'], 'scope')
    if not isinstance(register['records'], list) or not register['records']:
        raise RegisterError('records must be a non-empty list')
    records: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    for index, record in enumerate(register['records']):
        label = f'records[{index}]'
        if type(record) is not dict or record.get('status') not in STATUSES:
            raise RegisterError(f'{label}: status must be one of {", ".join(STATUSES)}')
        status = record['status']
        if set(record) != COMMON | FIELDS[status]:
            raise RegisterError(f'{label}: a {status} record requires exactly '
                                f'{sorted(COMMON | FIELDS[status])}')
        rid = record['id']
        if type(rid) is not str or not RECORD_ID.fullmatch(rid) or rid in records:
            raise RegisterError(f'{label}: id must be unique lowercase text')
        path = _path(record['path'], rid)
        if path in paths:
            raise RegisterError(f'{rid}: {path} is registered twice')
        paths.add(path)
        if type(record['sha256']) is not str or not DIGEST.fullmatch(record['sha256']):
            raise RegisterError(f'{rid}: sha256 must be 64 lowercase hexadecimal characters')
        _text(record['note'], rid + '.note')
        entry = dict(record)
        if status == 'current':
            entry['bindings'] = _rules(record['bindings'], rid + '.bindings', {'pointer', 'file'})
            if not entry['bindings']:
                raise RegisterError(f'{rid}: a current record needs at least one checked binding')
            entry['not_checked'] = _rules(record['not_checked'], rid + '.not_checked',
                                          {'pointer', 'kind', 'reason'})
            if not isinstance(record['limits'], list):
                raise RegisterError(f'{rid}.limits: expected a list')
            for number, limit in enumerate(record['limits']):
                _text(limit, f'{rid}.limits[{number}]')
        records[rid] = entry
    for rid, entry in records.items():
        if entry['status'] != 'superseded':
            continue
        seen, successor = {rid}, entry['superseded_by']
        while True:
            if type(successor) is not str or successor not in records:
                raise RegisterError(f'{rid}: superseded_by names no registered record ({successor!r})')
            if successor in seen:
                raise RegisterError(f'{rid}: supersession cycle through {successor}')
            target = records[successor]
            if target['status'] == 'invalid':
                raise RegisterError(f'{rid}: invalid evidence ({successor}) cannot supersede a record')
            if target['status'] != 'superseded':
                break
            seen.add(successor)
            successor = target['superseded_by']
    return list(records.values())


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_endings(data: bytes, expected: str) -> str:
    """Explain a CRLF/LF-only mismatch; the mismatch still fails."""
    if b'\r\n' in data and _sha(data.replace(b'\r\n', b'\n')) == expected:
        return (' Only CRLF line endings differ: restore the repository LF bytes of this'
                ' file after review; do not edit the receipt.')
    if b'\r' not in data and _sha(data.replace(b'\n', b'\r\n')) == expected:
        return (' The recorded value is the digest of a CRLF rendering: correct it only'
                ' through an explicit correction trail, never by silent repinning.')
    return ''


def _check_current(record: dict[str, Any], data: bytes, read, registered: dict[str, dict[str, Any]],
                   register_path: str, failures: list[str], summary: dict[str, Any]) -> None:
    rid, path = record['id'], record['path']
    try:
        receipt = parse_json(data, path)
        leaves = dict(_leaves(receipt))
    except EvidenceError as error:
        failures.append(f'{rid}: {error}')
        return
    owner: dict[str, str] = {}
    groups: dict[tuple[str, str], list[str]] = {}
    unverified: Counter[str] = Counter()
    for section in ('bindings', 'not_checked'):
        for rule in record[section]:
            label = f"{section} {rule['pointer']}"
            matches = list(_match(receipt, rule['segments']))
            if not matches:
                failures.append(f'{rid}: {label} matches nothing in {path}; review '
                                f'{register_path} against the receipt layout')
            for pointer, value, key in matches:
                if pointer in owner:
                    failures.append(f'{rid}: {path}{pointer} is classified by both '
                                    f'{owner[pointer]} and {label}')
                    continue
                owner[pointer] = label
                if type(value) is not str or not DIGEST.fullmatch(value):
                    failures.append(f'{rid}: {path}{pointer} holds a malformed digest {str(value)[:80]!r}; '
                                    'expected 64 lowercase hexadecimal characters. It cannot '
                                    'support a current claim; do not repair the receipt in place.')
                elif section == 'not_checked':
                    unverified[rule['kind']] += 1
                elif pointer.rsplit('/', 1)[-1].lower().endswith('_id'):
                    # Execution/result identities are never reinterpreted as file hashes.
                    failures.append(f'{rid}: {path}{pointer} is an identity, not a source-file '
                                    'digest; declare it under not_checked')
                else:
                    target = rule['file'].replace(CAPTURE, key) if key is not None else rule['file']
                    groups.setdefault((target, value), []).append(pointer)
    for pointer, value in leaves.items():
        if pointer not in owner and _digest_bearing(pointer, value):
            failures.append(f'{rid}: {path}{pointer} is an unclassified digest-bearing field; add a '
                            f'checked binding or an explicit not_checked entry to {register_path}')
    checked, files = 0, set()
    for (target, expected), pointers in groups.items():
        where = (f"{len(pointers)} location{'s' if len(pointers) != 1 else ''} in {path}, "
                 f'first {pointers[0]}')
        try:
            current = read(target)
        except EvidenceError as error:
            failures.append(f'{rid}: {error}; bound by {where}. Restore the file, or reclassify '
                            f'{rid} as historical in {register_path}.')
            continue
        other = registered.get(target)
        if other is not None and other['status'] in ('superseded', 'invalid'):
            failures.append(f"{rid}: relies on {other['status']} evidence {target} ({other['id']}) "
                            f'at {where}; a current claim cannot rest on it')
        actual = _sha(current)
        if actual != expected:
            failures.append(f'{rid}: {target} changed after {path} was recorded: {where} expects '
                            f'{expected}, the file now hashes to {actual}.{_line_endings(current, expected)} '
                            f'Produce a successor receipt, or reclassify {rid} as historical in '
                            f'{register_path}; never edit a recorded digest.')
            continue
        checked += len(pointers)
        files.add(target)
    summary.update(bindings=checked, files=len(files), not_checked=dict(unverified),
                   limits=list(record['limits']))


def check(root: Path, register: Any, register_path: str = DEFAULT_REGISTER
          ) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Return (failures, visited records). Only current records have their bindings checked."""
    root = root.resolve(strict=True)
    records = validate(register)
    registered = {record['path']: record for record in records}
    cache: dict[str, bytes | EvidenceError] = {}

    def read(relative: str) -> bytes:
        if relative not in cache:
            try:
                cache[relative] = read_file(root, relative)
            except EvidenceError as error:
                cache[relative] = error
        value = cache[relative]
        if isinstance(value, EvidenceError):
            raise value
        return value

    failures: list[str] = []
    visited: dict[str, dict[str, Any]] = {}
    for record in records:
        rid, path, status = record['id'], record['path'], record['status']
        before = len(failures)
        summary = visited[rid] = dict(status=status, path=path)
        if status == 'superseded':
            summary['superseded_by'] = record['superseded_by']
        try:
            data = read(path)
        except EvidenceError as error:
            failures.append(f'{rid}: {error}; restore the registered evidence or reclassify it '
                            f'explicitly in {register_path}')
            data = None
        if data is not None:
            actual = _sha(data)
            if actual != record['sha256']:
                failures.append(f"{rid}: {path} is not the classified version (registered "
                                f"{record['sha256']}, now {actual}).{_line_endings(data, record['sha256'])} "
                                'Review the change; record any correction explicitly before '
                                f'updating {register_path}. Evidence must not be rewritten silently.')
            if status == 'current':
                _check_current(record, data, read, registered, register_path, failures, summary)
        summary['ok'] = len(failures) == before
    return failures, visited


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _describe(rid: str, summary: dict[str, Any]) -> list[str]:
    status = summary['status']
    if status != 'current':
        tail = f"; superseded by {summary['superseded_by']}" if status == 'superseded' else ''
        return [f'{status:<10} {rid}: file bytes intact; bindings not checked, '
                f'no current claim{tail}']
    skipped = ', '.join(f'{count} {kind}' for kind, count in sorted(summary['not_checked'].items()))
    lines = [f"current    {rid}: matched {_count(summary['bindings'], 'recorded digest')} against "
             f"{_count(summary['files'], 'repository file')}; not checked: {skipped or 'none'}"]
    return lines + [f'           limit: {limit}' for limit in summary['limits']]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='repository root; defaults to the directory containing tools/')
    parser.add_argument('--register', default=DEFAULT_REGISTER,
                        help=f'repository-relative register path (default {DEFAULT_REGISTER})')
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        failures, visited = check(root, load_register(root, args.register), args.register)
    except (RegisterError, EvidenceError, OSError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    for rid, summary in visited.items():
        if summary['ok']:
            print('\n'.join(_describe(rid, summary)))
    if failures:
        for failure in failures:
            print(f'FAIL: {failure}', file=sys.stderr)
        print('No receipt, register or source file was modified.', file=sys.stderr)
        return 1
    counts = Counter(summary['status'] for summary in visited.values())
    digests = sum(summary.get('bindings', 0) for summary in visited.values())
    print(f"PASS: {_count(counts['current'], 'current record')} ({_count(digests, 'recorded digest')} "
          f"matched); {counts['historical']} historical, {counts['superseded']} superseded and "
          f"{counts['invalid']} invalid records intact. Byte-level SHA-256 check only: "
          'no runtime, native-execution, platform or scientific verification.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
