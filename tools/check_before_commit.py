#!/usr/bin/env python3
"""Before-commit guard: run the evidence checks on Git-normalised candidate bytes.

Standard library only; run it with the tested tectonics interpreter, because the
I01/I02 test modules need NumPy and SciPy. A Windows working tree can hold CRLF
copies of files that Git stores with LF, so a check run in place can pass on bytes
that are never committed. This tool builds the commit candidate in a private copy
of the Git index, exports the candidate blobs exactly as Git stores them and runs
the existing guards on that export:

1. tools/check_current_evidence.py: registered receipts and their declared bindings;
2. tectonics/tests/test_digest_line_endings.py: no digest of a CRLF rendering and no
   I01 receipt writer using the platform newline;
3. the I01/I02 test modules, with process-local PYTHONPATH=<export>/tectonics/src.

By default the candidate is what `git add --all` would stage: staged, unstaged and
untracked (not ignored) changes. --staged checks exactly the current index and
names every working-tree change it leaves out. The real index, working tree,
branch and Git settings are never changed; like `git add`, building the candidate
may store Git objects for changed files. This is not an installed hook and makes
no commit. A pass is a byte-binding and focused-test check, not scientific
acceptance. See docs/CODING_SAFETY.md.

Git must not start other programs while the candidate is built. Every Git call,
from the first, disables the fsmonitor hook or daemon and finds hook files only in
an empty private directory: per-command options, not setting changes. Before any
call hashes working-tree files, the guard refuses, checking nothing, a candidate
path with an applicable external clean or process filter (skipping the filter
would not reproduce the committed bytes), a hook configured for post-index-change
or a submodule. This is not a general Git sandbox.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterator, Sequence

EXPORTED = ('tectonics/', 'tools/')
TESTS = 'test_i0[12]_*.py'
REGULAR = ('100644', '100755')
GITLINK = '160000'
# Programs configuration can make these commands start: clean/process filters for content Git hashes, and hooks
# attached to an event by configuration (Git 2.54 and later), which core.hooksPath does not redirect.
PROGRAMS = r'^(filter\..+\.(clean|process)|hook\..+\.event)$'
UNSUPPORTED = 'unsupported, so nothing was checked (docs/CODING_SAFETY.md, "Before every commit")'


class CandidateError(RuntimeError):
    """The commit candidate could not be built or exported; nothing was checked."""


@dataclass(frozen=True)
class Candidate:
    root: Path                   # exported Git-normalised bytes of the EXPORTED trees
    changed: tuple[str, ...]     # 'status path' for each candidate path that differs from HEAD
    excluded: tuple[str, ...]    # working-tree changes a --staged candidate leaves out
    skipped: tuple[str, ...]     # exported-tree index entries that are not regular files


@dataclass(frozen=True)
class _Git:
    """Git in one checkout; the private index copy and an empty hooks directory share one temporary folder."""
    root: Path
    folder: Path

    def command(self, *args: str) -> list[str]:
        # Every call, from the first: no fsmonitor hook or daemon (queried whenever an index is read), and hook files
        # only from the empty directory (an index write, as by git add, runs post-index-change). Per command only.
        return ['git', '-c', 'core.fsmonitor=false', '-c', f'core.hooksPath={(self.folder / "hooks").as_posix()}',
                *args]

    def environment(self, private: bool) -> dict[str, str]:
        env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')     # never refresh an index opportunistically
        env.pop('GIT_INDEX_FILE', None)
        if private:
            env['GIT_INDEX_FILE'] = str(self.folder / 'index')
        return env

    def __call__(self, *args: str, private: bool = False, stdin: bytes | None = None,
                 no_match: int | None = None) -> bytes:
        """Output of one Git command; exit status no_match with no output is an empty result, not a failure."""
        try:
            result = subprocess.run(self.command(*args), cwd=self.root, env=self.environment(private),
                                    input=stdin, capture_output=True)
        except OSError as error:
            raise CandidateError(f'git could not be started ({error.strerror})') from None
        if result.returncode and not (result.returncode == no_match and not result.stdout):
            message = result.stderr.decode('utf-8', 'replace').strip().splitlines()
            raise CandidateError(f'git {" ".join(args[:4])} failed: {message[-1] if message else result.returncode}')
        return result.stdout


def _tokens(output: bytes) -> list[str]:
    return [item.decode('utf-8', 'surrogateescape') for item in output.split(b'\0') if item]


def _entries(git: _Git) -> list[tuple[str, str, str, str]]:
    """(mode, object, stage, path) of every entry in the private index."""
    entries = []
    for record in git('ls-files', '--stage', '-z', private=True).split(b'\0'):
        if record:
            meta, raw = record.split(b'\t', 1)
            mode, blob, stage = meta.decode('ascii').split()
            entries.append((mode, blob, stage, raw.decode('utf-8', 'surrogateescape')))
    return entries


def _refuse_external_programs(git: _Git, entries: Sequence[tuple[str, str, str, str]],
                              hashed: Sequence[str]) -> None:
    """Refuse a candidate whose commands would make Git start another program, before any file is hashed.

    hashed lists the paths whose content those commands may hash, which runs an applicable clean or process
    filter. Skipping the filter would not reproduce the committed bytes, so it is refused, never stripped."""
    values: dict[str, list[str]] = {}
    for record in _tokens(git('config', '-z', '--get-regexp', PROGRAMS, no_match=1)):
        key, _, value = record.partition('\n')
        values.setdefault(key, []).append(value)
    hooks = sorted(key[len('hook.'):-len('.event')] for key, events in values.items()
                   if key.startswith('hook.') and 'post-index-change' in events)
    if hooks:
        raise CandidateError(f"Git hook '{hooks[0]}' is configured for post-index-change, which building the "
                             f'candidate triggers; {UNSUPPORTED}')
    submodules = [name for mode, _, _, name in entries if mode == GITLINK]
    if submodules:                                     # git add and git diff would run git status inside it
        raise CandidateError(f'submodule {submodules[0]}: building the candidate would run Git inside it; '
                             f'{UNSUPPORTED}')
    # As in Git, the last value of a key wins, and an empty command runs nothing.
    drivers = {key[len('filter.'):].rsplit('.', 1)[0] for key, commands in values.items()
               if key.startswith('filter.') and commands[-1]}
    if not drivers or not hashed:
        return
    paths = b''.join(path.encode('utf-8', 'surrogateescape') + b'\0' for path in hashed)
    fields = git('check-attr', '-z', '--stdin', 'filter', private=True, stdin=paths).decode(
        'utf-8', 'surrogateescape').split('\0')[:-1]                  # path, attribute, value for each path
    found = [(value, path) for path, value in zip(fields[::3], fields[2::3]) if value in drivers]
    if found:
        more = f' and {len(found) - 1} more path(s)' if len(found) > 1 else ''
        raise CandidateError(f"external Git filter '{found[0][0]}' applies to {found[0][1]}{more}; building the "
                             f'candidate would run it, and skipping it would not give the committed bytes; '
                             f'{UNSUPPORTED}')


def _changes(git: _Git) -> tuple[str, ...]:
    try:
        git('rev-parse', '--verify', '--quiet', 'HEAD^{commit}')
    except CandidateError:
        return ('A (no HEAD commit: every candidate path is new)',)
    tokens = _tokens(git('diff', '--cached', '--name-status', '--no-renames', '-z', 'HEAD', private=True))
    return tuple(f'{status} {path}' for status, path in zip(tokens[::2], tokens[1::2]))


def _export(git: _Git, target: Path) -> tuple[str, ...]:
    """Write every exported regular-file blob of the candidate index byte for byte; return skipped entries."""
    entries, skipped = [], []
    for mode, blob, stage, name in _entries(git):
        if stage != '0':
            raise CandidateError(f'unmerged index entry {name}; resolve it before checking a commit')
        if not name.startswith(EXPORTED):
            continue
        if mode not in REGULAR:
            skipped.append(f'{mode} {name}')
            continue
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise CandidateError(f'refused index path {name!r}')
        entries.append((blob, target.joinpath(*path.parts)))
    with subprocess.Popen(git.command('cat-file', '--batch'), cwd=git.root, env=git.environment(False),
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE) as process:
        for blob, destination in entries:
            process.stdin.write(blob.encode('ascii') + b'\n')
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b'blob':
                raise CandidateError(f'object {blob} is not a readable blob')
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)                             # the newline after each object
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(data)
        process.stdin.close()
    if process.returncode:
        raise CandidateError('git cat-file failed while exporting the candidate')
    return tuple(skipped)


@contextmanager
def candidate(root: Path, *, staged: bool = False) -> Iterator[Candidate]:
    """Build and export the commit candidate in a private temporary directory, removed afterwards."""
    root = Path(root).resolve()
    with tempfile.TemporaryDirectory(prefix='atlas-candidate-', ignore_cleanup_errors=True) as folder:
        git = _Git(root, Path(folder))
        (git.folder / 'hooks').mkdir()                 # stays empty, so Git finds no hook file
        real = Path(git('rev-parse', '--git-path', 'index').decode('utf-8').strip())
        real = real if real.is_absolute() else root / real
        if not real.is_file():
            raise CandidateError('no Git index to copy: stage or commit something first')
        shutil.copy2(real, git.folder / 'index')     # keeps the stat data and the timestamp of Git's racy-clean check
        entries = _entries(git)
        untracked = _tokens(git('ls-files', '--others', '--exclude-standard', '-z', private=True))
        # git diff (--staged) hashes tracked files and git add also untracked ones; refuse before either runs.
        tracked = list(dict.fromkeys(name for *_, name in entries))
        _refuse_external_programs(git, entries, tracked if staged else tracked + untracked)
        excluded: tuple[str, ...] = ()
        if staged:
            unstaged = _tokens(git('diff', '--name-only', '-z', private=True))
            excluded = tuple([f'unstaged {path}' for path in unstaged] + [f'untracked {path}' for path in untracked])
        else:
            # Per command only: a user's core.safecrlf=true must not abort on the CRLF copies being checked.
            git('-c', 'core.safecrlf=false', 'add', '--all', '--', '.', private=True)
        export = git.folder / 'candidate'
        export.mkdir()
        skipped = _export(git, export)
        yield Candidate(export, _changes(git), excluded, skipped)


def checks(export: Path, pattern: str = TESTS) -> list[tuple[str, list[str], dict[str, str]]]:
    """The existing guards, run on the export with this interpreter: (name, command, environment additions)."""
    python, tests = sys.executable, str(export / 'tectonics' / 'tests')
    return [('current-evidence register', [python, '-B', str(export / 'tools' / 'check_current_evidence.py')], {}),
            ('digest line endings', [python, '-B', '-m', 'unittest', 'discover', '-s', tests,
                                     '-p', 'test_digest_line_endings.py'], {}),
            (f'I01/I02 tests ({pattern})', [python, '-B', '-m', 'unittest', 'discover', '-s', tests, '-p', pattern],
             {'PYTHONPATH': str(export / 'tectonics' / 'src')})]


def run(steps: Sequence[tuple[str, list[str], dict[str, str]]], cwd: Path) -> list[tuple[str, int, float]]:
    """Run every step, even after a failure; return (name, exit code, seconds) for each."""
    results = []
    for name, command, extra in steps:
        print(f'--- {name}', flush=True)
        env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        env.update(extra)
        started = time.perf_counter()
        try:
            code = subprocess.run(command, cwd=cwd, env=env).returncode
        except OSError as error:
            print(f'could not start {name}: {error.strerror}', file=sys.stderr)
            code = 127
        results.append((name, code, time.perf_counter() - started))
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--staged', action='store_true',
                        help='check exactly the current index and list every change it leaves out')
    parser.add_argument('--tests', default=TESTS, metavar='PATTERN',
                        help=f'tectonics test-module pattern for the third check (default {TESTS})')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1],
                        help='repository root; defaults to the directory containing tools/')
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        with candidate(args.root, staged=args.staged) as snapshot:
            scope = 'the index only (--staged)' if args.staged else 'git add --all of the working tree'
            print(f'Candidate: {scope}; {len(snapshot.changed)} path(s) differ from HEAD.')
            for line in snapshot.changed:
                print(f'  {line}')
            for line in snapshot.excluded:
                print(f'  NOT IN CANDIDATE: {line}')
            for line in snapshot.skipped:
                print(f'  not exported (not a regular file): {line}')
            results = run(checks(snapshot.root, args.tests), snapshot.root)
    except (CandidateError, OSError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    for name, code, seconds in results:
        print(f"{'PASS' if code == 0 else 'FAIL'} {name} ({seconds:.1f} s)")
    failed = [name for name, code, _ in results if code]
    print(f"{'FAIL' if failed else 'PASS'}: {len(results) - len(failed)} of {len(results)} checks passed on "
          f'Git-normalised candidate bytes in {time.perf_counter() - started:.1f} s. Not scientific acceptance; '
          'nothing was staged or committed.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
