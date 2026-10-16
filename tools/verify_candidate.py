#!/usr/bin/env python3
"""Verify a candidate patch set in a scratch clone: one command for the coordinator's and Codex's checks.

WORKING NON-CANON development tool (docs/DEVELOPMENT_TOOLS.md). Standard library only; tests run with the tested
interpreter given by ``--python`` (no private path is recorded in the tree). Nothing is written to the source
repository: it is only cloned from, without hard links.

Steps (each recorded in the summary JSON; the exit code is 0 only when every requested step passes):

1. clone ``--repo`` at ``--base`` into a scratch folder outside it (two working trees: chain and combined);
2. apply the incremental ``--chain`` patches in order to one tree and the ``--combined`` patch to the other, stage
   each with ``git add --all`` (in the scratch clone) and require equal tree hashes (and ``--expect-tree``);
3. byte checks: no CR byte in any patch or in any changed file of the result; every patch path is relative, inside
   the tree and not under ``.atlas-dev/``; the combined patch names exactly the paths the chain changes; optional
   ``--forbid-paths FILE`` (one path per line) and ``--expect-paths FILE`` (the exact changed-path list);
4. static checks in the combined tree: tools/check_coding_safety.py, check_public_paths.py,
   check_current_evidence.py, their tests (tests/test_coding_safety.py, test_public_paths.py,
   test_current_evidence.py) and the default tools/check_before_commit.py;
5. a test tier through run_tests_parallel.py: ``quick`` (registered slow tests omitted), ``full``, ``impact``
   (the candidate is committed in the scratch clone and test_impact.py selects BASE..HEAD from ``--impact-map``;
   selected units run one per fresh process, as recorded; everything when the selector says so; the
   repository-root ``tests/`` suite also runs when a change lies outside what the recorded suite covers) or ``none``.

A pass is the same evidence those commands give when run by hand, gathered once; even the full parallel tier is not
the verify.py gate, and it is not scientific acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time

SCHEMA = 'atlas.dev.candidate-verification.v1'
HERE = Path(__file__).resolve().parent
STATIC = (
    ('check_coding_safety', ['tools/check_coding_safety.py']),
    ('check_public_paths', ['tools/check_public_paths.py']),
    ('check_current_evidence', ['tools/check_current_evidence.py']),
    ('test_coding_safety', ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_coding_safety.py']),
    ('test_public_paths', ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_public_paths.py']),
    ('test_current_evidence', ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_current_evidence.py']),
    ('check_before_commit', ['tools/check_before_commit.py']),
)


def git(cwd, *args, check=True):
    proc = subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false', *args], cwd=str(cwd),
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and proc.returncode:
        raise RuntimeError('git %s: %s' % (' '.join(args), (proc.stderr or proc.stdout)[-2000:]))
    return proc.stdout


def patch_paths(data):
    """Paths named by ``diff --git`` headers (both sides), in order, without duplicates."""
    out = []
    for line in data.split(b'\n'):
        if line.startswith(b'diff --git '):
            parts = line[len(b'diff --git '):].decode('utf-8', errors='replace').split(' ')
            for part in (parts[0], parts[-1]):
                path = part[2:] if part[:2] in ('a/', 'b/') else part
                if path not in out:
                    out.append(path)
    return out


def path_problems(paths):
    problems = []
    for path in paths:
        pure = PurePosixPath(path)
        if pure.is_absolute() or '..' in pure.parts or ':' in path or '\\' in path:
            problems.append('not a relative tree path: ' + path)
        elif pure.parts and pure.parts[0] == '.atlas-dev':
            problems.append('coordination folder in a patch: ' + path)
    return problems


def apply_all(tree, patches):
    for patch in patches:
        git(tree, 'apply', '--check', str(patch))
        git(tree, 'apply', '--whitespace=nowarn', str(patch))
    git(tree, 'add', '--all')
    return git(tree, 'write-tree').strip()


def child_env(scratch):
    env = dict(os.environ)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPYCACHEPREFIX'] = str(Path(scratch)/'pycache')
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def run_step(name, command, cwd, env, log_dir):
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True, encoding='utf-8',
                          errors='replace')
    log = Path(log_dir)/(name+'.log')
    log.write_text('$ %s\n\n--- stdout\n%s\n--- stderr\n%s' % (' '.join(command), proc.stdout, proc.stderr),
                   encoding='utf-8')
    return dict(name=name, exit=proc.returncode, passed=proc.returncode == 0, seconds=round(time.perf_counter()-started, 1),
                log=str(log), tail=(proc.stdout+proc.stderr)[-1200:])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--repo', required=True, help='the repository to clone from (read only)')
    parser.add_argument('--base', required=True, help='the base commit')
    parser.add_argument('--chain', nargs='*', default=[], help='incremental patches, applied in order')
    parser.add_argument('--combined', help='the combined patch against the base')
    parser.add_argument('--expect-tree', help='expected tree hash (a prefix is enough)')
    parser.add_argument('--forbid-paths', help='a file of paths the patches must not touch (one per line)')
    parser.add_argument('--expect-paths', help='a file of exactly the paths the candidate changes')
    parser.add_argument('--python', required=True, help='the tested interpreter (static checks and tests)')
    parser.add_argument('--tier', choices=('quick', 'full', 'impact', 'none'), default='quick')
    parser.add_argument('--slow-file', help='a JSON slow-test registry when the candidate tree has none')
    parser.add_argument('--impact-map', help='test_impact.py map recorded at the base (for --tier impact)')
    parser.add_argument('--pattern', action='append',
                        help="test discovery patterns (default: the candidate's verify.py full discovery)")
    parser.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2)-2))
    parser.add_argument('--skip-static', action='store_true', help='byte and tree checks only, then the tier')
    parser.add_argument('--work', help='scratch folder (default: a new short temporary folder); must not exist')
    parser.add_argument('--summary', help='summary JSON (default: WORK/summary.json)')
    args = parser.parse_args(argv)
    if args.tier == 'impact' and not args.impact_map:
        parser.error('--tier impact needs --impact-map')

    repo = Path(args.repo).resolve()
    work = Path(args.work).resolve() if args.work else Path(tempfile.mkdtemp(prefix='atvc-'))
    if repo == work or repo in work.parents:
        raise SystemExit('the scratch folder must lie outside the source repository')
    if args.work:
        if work.exists():
            raise SystemExit('the scratch folder exists already: ' + str(work))
        work.mkdir(parents=True)
    if not args.chain and not args.combined:
        raise SystemExit('give --chain and/or --combined')
    logs = work/'logs'
    logs.mkdir()
    started = time.perf_counter()
    summary = dict(schema=SCHEMA, base=args.base, work=str(work), steps={}, passed=False, completed=False,
                   patches={str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                            for p in [*args.chain, *([args.combined] if args.combined else [])]})
    steps = summary['steps']
    summary_path = Path(args.summary) if args.summary else work/'summary.json'

    def save():
        summary['wall_seconds'] = round(time.perf_counter()-started, 1)
        summary['passed'] = summary['completed'] and bool(steps) and all(s.get('passed') for s in steps.values())
        temporary = summary_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(summary, indent=1), encoding='utf-8')
        os.replace(temporary, summary_path)

    try:
        # 1-2. Clone, apply, compare trees.
        clone = work/'chain'
        subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', str(repo), str(clone)],
                       check=True, capture_output=True)
        git(clone, 'checkout', '--quiet', '--detach', args.base)
        base = git(clone, 'rev-parse', 'HEAD').strip()
        summary['base_commit'] = base
        combined = work/'combined'
        git(clone, 'worktree', 'add', '--quiet', '--detach', str(combined), base)
        trees = {}
        if args.chain:
            trees['chain'] = apply_all(clone, [Path(p).resolve() for p in args.chain])
        if args.combined:
            trees['combined'] = apply_all(combined, [Path(args.combined).resolve()])
        else:
            combined = clone
        ok = len(set(trees.values())) == 1 and (not args.expect_tree or
                                                 all(t.startswith(args.expect_tree) for t in trees.values()))
        steps['trees'] = dict(passed=ok, trees=trees, expected=args.expect_tree)
        save()

        # 3. Bytes and paths.
        problems = []
        all_paths = set()
        for patch in summary['patches']:
            data = Path(patch).read_bytes()
            if b'\r' in data:
                problems.append('CR byte in patch: ' + patch)
            paths = patch_paths(data)
            problems += path_problems(paths)
            all_paths.update(paths)
        changed = [line for line in git(combined, 'diff', '--name-only', '--cached', base).splitlines() if line]
        for path in changed:
            full = combined/path
            if full.is_file() and b'\r' in full.read_bytes():
                problems.append('CR byte in a changed file: ' + path)
        if args.combined and args.chain:
            chain_changed = set(git(clone, 'diff', '--name-only', '--cached', base).splitlines()) - {''}
            named = set(patch_paths(Path(args.combined).read_bytes()))
            if named != chain_changed:
                problems.append('the combined patch paths differ from what the chain changes: missing %s, extra %s'
                                % (sorted(chain_changed - named), sorted(named - chain_changed)))
        if args.forbid_paths:
            forbidden = {l.strip() for l in Path(args.forbid_paths).read_text(encoding='utf-8').splitlines()
                         if l.strip() and not l.lstrip().startswith('#')}
            problems += ['forbidden path touched: ' + p for p in sorted(all_paths & forbidden)]
        if args.expect_paths:
            expected = {l.strip() for l in Path(args.expect_paths).read_text(encoding='utf-8').splitlines()
                        if l.strip() and not l.lstrip().startswith('#')}
            if expected != set(changed):
                problems.append('changed paths differ from --expect-paths: missing %s, extra %s'
                                % (sorted(expected - set(changed)), sorted(set(changed) - expected)))
        steps['bytes_and_paths'] = dict(passed=not problems, problems=problems, changed_paths=changed)
        save()

        env = child_env(work)
        # 4. Static checks.
        if not args.skip_static:
            for name, command in STATIC:
                steps['static:'+name] = run_step(name, [args.python, '-B', *command], combined, env, logs)
                save()

        # 5. A test tier.
        if args.tier != 'none':
            runner = [args.python, '-B', str(HERE/'run_tests_parallel.py'), '--root', str(combined), '--python',
                      args.python, '--workers', str(args.workers), '--run-dir', str(work/'tests'),
                      '--pycache', str(work/'pycache')]
            for pattern in args.pattern or ():         # default: the candidate's verify.py full discovery
                runner += ['--pattern', pattern]
            tier = dict(tier=args.tier)
            if args.tier == 'quick':
                runner.append('--quick')
                if args.slow_file:
                    runner += ['--slow-file', str(Path(args.slow_file).resolve())]
            elif args.tier == 'impact':
                # Commit the candidate in the scratch clone so the selector sees exact add/delete/rename status
                # (never in the source repository), then select BASE..HEAD under the tested interpreter.
                git(combined, '-c', 'user.name=verify_candidate', '-c', 'user.email=verify@example.invalid',
                    'commit', '--quiet', '--allow-empty', '-m', 'candidate')
                selection = subprocess.run([args.python, '-B', str(HERE/'test_impact.py'), 'select', '--map',
                                            str(Path(args.impact_map).resolve()), '--root', str(combined),
                                            '--python', args.python, base, 'HEAD'],
                                           capture_output=True, text=True, env=env)
                if selection.returncode:
                    raise RuntimeError('impact selection failed: ' + selection.stderr[-2000:])
                chosen = json.loads(selection.stdout)
                tier.update(all=chosen['all'], reasons=chosen['all_reasons'] or chosen['reasons'],
                            selected_units=chosen['selected_units'], total_units=chosen['total_units'],
                            outside_scope=chosen['outside_scope'], untouched=chosen['untouched'])
                # The recorded suite is tectonics/tests. Changes it cannot see run the repository-root tests too.
                if chosen['outside_scope'] or chosen['untouched'] or any(
                        not p.startswith('tectonics/') for p in changed):
                    steps['root_tests'] = run_step('root_tests', [args.python, '-B', '-m', 'unittest', 'discover',
                                                                  '-s', 'tests'], combined, env, logs)
                    save()
                runner.append('--fresh')          # the composition the map was recorded with: one unit per process
                if not chosen['all']:
                    names = chosen['units'] + chosen['modules']
                    if not names:
                        tier.update(passed=True, note='no recorded test can be affected')
                        steps['tier'] = tier
                        summary['completed'] = True
                        save()
                        return 0 if summary['passed'] else 1
                    for name in names:
                        runner += ['--only', name]
            step = run_step('tier-'+args.tier, runner, combined, env, logs)
            test_summary = work/'tests'/'summary.json'
            if test_summary.is_file():
                data = json.loads(test_summary.read_text(encoding='utf-8'))
                tier.update(counts=data['counts'], tests_selected=data['tests_selected'],
                            omitted_slow=len(data['omitted_slow']), wall_seconds=round(data['wall_seconds'], 1),
                            local_bytecode=data['local_bytecode'], summary=str(test_summary))
            tier.update(passed=step['passed'], exit=step['exit'], log=step['log'], tail=step['tail'])
            steps['tier'] = tier
            save()
    except Exception as error:                       # recorded, then reported as a failure
        steps['error'] = dict(passed=False, error='%s: %s' % (type(error).__name__, error))
        save()
        print(json.dumps(dict(summary=str(summary_path), passed=False, error=steps['error']['error'])))
        return 1
    summary['completed'] = True
    save()
    print(json.dumps(dict(summary=str(summary_path), passed=summary['passed'],
                          steps={k: v.get('passed') for k, v in steps.items()}, wall_seconds=summary['wall_seconds'])))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
