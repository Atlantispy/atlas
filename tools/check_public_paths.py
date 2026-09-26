#!/usr/bin/env python3
"""Read-only home-path guard for public tectonics evidence and documentation.

Scans regular UTF-8 JSON, Markdown, log and text files. This is a narrow privacy
tripwire, not general secret detection or historical evidence authentication.
Diagnostics contain only repository-relative locations and generic reasons.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import sys

SCAN_ROOTS = ('tectonics/evidence', 'tectonics/docs')
TEXT_SUFFIXES = frozenset({'.json', '.md', '.log', '.txt'})
PLACEHOLDER = 'LOCAL_USER'
# Repeated separators cover literal and JSON-escaped Windows paths. Windows
# directory names are case-insensitive; the permitted placeholder is exact.
_USERNAME = r'''([^\\/\r\n"'`<>|:]+)'''
_WINDOWS = re.compile(r'(?<![\w])[a-z]:[\\/]+users[\\/]+' + _USERNAME, re.I)
_POSIX = re.compile(r'(?<![\w/])/(?:home|Users)/' + _USERNAME)


class ScanError(ValueError):
    """The requested public trees could not be completely inspected."""


def has_personal_home_path(line: str) -> bool:
    # JSON permits escaped forward slashes as well as escaped backslashes.
    line = line.replace(r'\/', '/')
    return any(match.group(1) != PLACEHOLDER
               for pattern in (_WINDOWS, _POSIX)
               for match in pattern.finditer(line))


def check(root: Path) -> list[str]:
    """Return one generic finding per affected line; never change public files."""
    try:
        root = root.resolve(strict=True)
    except OSError:
        raise ScanError('.:0: repository root missing or inaccessible') from None
    findings = []

    def walk_error(error: OSError) -> None:
        try:
            location = Path(error.filename).relative_to(root).as_posix()
        except (TypeError, ValueError):
            location = '.'
        raise ScanError(f'{location}:0: scan directory inaccessible') from None

    for relative in SCAN_ROOTS:
        tree = root / relative
        try:
            mode = tree.lstat().st_mode
        except OSError:
            raise ScanError(f'{relative}:0: scan root missing or inaccessible') from None
        if not stat.S_ISDIR(mode):
            raise ScanError(f'{relative}:0: scan root is not a regular directory')
        for directory, dirs, files in os.walk(tree, onerror=walk_error, followlinks=False):
            dirs.sort()
            for name in sorted(files):
                path = Path(directory) / name
                if path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                location = path.relative_to(root).as_posix()
                try:
                    if not stat.S_ISREG(path.lstat().st_mode):
                        continue
                    with path.open(encoding='utf-8-sig') as stream:
                        for number, line in enumerate(stream, 1):
                            if has_personal_home_path(line):
                                findings.append(
                                    f'{location}:{number}: personal home path; '
                                    'use LOCAL_USER for the username')
                except (OSError, UnicodeError):
                    raise ScanError(f'{location}:0: text file unreadable as UTF-8') from None
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='repository root (defaults to this checkout)')
    args = parser.parse_args(argv)
    try:
        findings = check(args.root)
    except ScanError as error:
        print(str(error), file=sys.stderr)
        return 2
    if findings:
        print('\n'.join(findings))
        return 1
    print('PASS: no personal home paths in public tectonics evidence or docs')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
