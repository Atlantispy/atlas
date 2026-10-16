"""Fail-closed parity check of one surfaces stage (two arms of replay_surfaces.py shards).

Copied from Exact kernels' q11 gpy_parity_check.py (T/ck/scripts, 16 Oct) with the arm names made
arguments, so geometry's parity harnesses (run_jets_parity.sh first) close the same holes:
compare_surfaces alone passes an empty or partial BASELINE (both arms missing the same shard, or no
files at all) and an all-capped stage, and nothing checked a shard's exit code.

Usage: python -B -I surfaces_stage_check.py OUT STAGE SHARDS BASE_ARM BASE_RT CAND_ARM CAND_RT EXPECT_ROWS CAPS
  SHARDS: comma list of shard ids. EXPECT_ROWS: the stage's query count per arm (fixed by its pinned
  inputs). CAPS: 'none' (no capped row in either arm is accepted: the IV1 stage),
  'list:<file>[,<file>...]' (capped-list jsonl files: a capped row is accepted only if it is an
  interface query whose (support_index, cell, other, constraint_name) is listed, i.e. a later deeper
  stage re-runs it; refuter 16 Oct P3-a: a cap anywhere else is a query nobody compared), or
  'exactly:<file>[,<file>...]' (the deep stage, which re-runs those lists: no capped row is accepted,
  and each arm's data rows must be exactly the listed interface queries, the same keys as often as
  listed; refuter round 3: a row count alone passes the right number of wrong rows).
  Reads OUT/STAGE-ARM-s<i>.jsonl and OUT/STAGE-ARM-s<i>.exit (the shard's exit code, written
  by the harness) for both arms. Runs compare_surfaces.py (pinned) --except-digests on exactly those
  files, writes OUT/cmp-STAGE.json and OUT/check-STAGE.json, and exits 0 only if every check holds:
  shards  each expected shard of both arms exists and exited 0; its last row is its only done row;
          done.queries equals its data rows, which are > 0; done.runtime is the arm's runtime; no
          other shard files.
  arms    each arm's data rows == EXPECT_ROWS; one package digest per arm, and the arms' digests
          differ (a candidate arm that loaded the base runtime would make the parity vacuous).
  compare exit 0; no VIOLATION; missing-in-candidate 0; candidate-extra 0; baseline == candidate ==
          the shards' data rows; identical (digest-only included) > 0; identical + capped == baseline;
          a capped pair counts only if the BASE capped and the candidate capped or finished (met or
          unmet): a candidate cap where the base finished (a candidate hang or slowdown) and any
          error row fail (refuter 16 Oct: wholesale caps let a jets hang or exception pass).
  caps    every capped row of either arm is allowed by CAPS.
"""
import glob
import json
import subprocess
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPARE = HERE/'compare_surfaces.py'
COMPARE_SHA = 'bc2fa87807381a1c1dd79222d1c06b415434a2b53f109450307b12eb5122cd10'


def key(r):
    """compare_surfaces.py's row key."""
    return (r.get('kind'), r.get('support_index'), r.get('cell'), r.get('other'),
            r.get('constraint_name') or (r.get('axis'), r.get('end')))


def cap_rule(spec, errors):
    """(mode, Counter of the listed (support_index, cell, other, constraint_name) keys) of CAPS."""
    if spec == 'none':
        return 'none', Counter()
    mode, _, names = spec.partition(':')
    if mode not in ('list', 'exactly') or not names:
        errors.append('bad cap rule %r (want none, list:<files> or exactly:<files>)' % spec)
        return 'bad', Counter()
    keys = Counter()
    for p in names.split(','):
        try:
            for line in Path(p).read_text(encoding='utf8').splitlines():
                if line.strip():
                    r = json.loads(line)
                    keys[r['support_index'], r['cell'], r['other'], r['constraint_name']] += 1
        except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
            errors.append('cap list %s unreadable: %s' % (p, str(e)[:120]))
    if not keys:
        errors.append('cap rule %r lists no query' % spec)
    return mode, keys


def shard(path, exit_path, runtime, errors, capped, keys=None):
    """(data rows, package digest) of one shard; every problem is appended to errors, the key of
    every capped data row is added to capped and, if keys is a Counter, every data row's key is counted."""
    name = path.name
    if not path.is_file():
        errors.append('%s missing' % name)
        return 0, None
    try:
        code = exit_path.read_text(encoding='utf8').strip()
    except OSError:
        code = None
    if code != '0':
        errors.append('%s exit %r' % (name, code))
    rows, done = 0, []
    try:
        lines = path.read_text(encoding='utf8').splitlines()
        parsed = [json.loads(line) for line in lines]
    except (OSError, UnicodeDecodeError, ValueError) as e:
        errors.append('%s unreadable: %s' % (name, str(e)[:120]))
        return 0, None
    for k, r in enumerate(parsed):
        if r.get('done'):
            done.append(k)
        elif 'job_counts' not in r:
            rows += 1
            if keys is not None:
                keys[key(r)] += 1
            if r.get('status') == 'capped':
                capped.add(key(r))
    if done != [len(parsed)-1]:
        errors.append('%s done rows at %s of %d lines (want exactly one, last)' % (name, done, len(parsed)))
        return rows, None
    tail = parsed[-1]
    if rows <= 0:
        errors.append('%s has no data rows (an empty shard proves nothing)' % name)
    if tail.get('queries') != rows:
        errors.append('%s done.queries %r != %d data rows' % (name, tail.get('queries'), rows))
    if tail.get('runtime') != runtime:
        errors.append('%s runtime %r, want %r' % (name, tail.get('runtime'), runtime))
    return rows, tail.get('package_digest')


ACCEPTED_CAPS = {('capped', 'capped'), ('capped', 'met'), ('capped', 'unmet')}   # (baseline, candidate)


def main(out, stage, shards, base_arm, base_rt, cand_arm, cand_rt, expect_rows, caps):
    out = Path(out)
    arms = (base_arm, cand_arm)
    errors, rows, digests, files, capped = [], {}, {}, {}, {}
    mode, listed = cap_rule(caps, errors)
    allowed = set(listed) if mode == 'list' else set()
    exact = Counter({('interface',)+q: n for q, n in listed.items()}) if mode == 'exactly' else None
    try:
        ids = [int(x) for x in shards.split(',')]
    except ValueError:
        ids = []
    if len(set(ids)) != len(ids) or not ids:
        errors.append('bad shard list %r' % shards)
    try:
        expect = int(expect_rows)
    except ValueError:
        expect = 0
    if expect <= 0:
        errors.append('bad expected row count %r' % expect_rows)
    if base_arm == cand_arm or not base_arm or not cand_arm:
        errors.append('arms must be two different names, got %r %r' % arms)
    digest = sha256(COMPARE.read_bytes()).hexdigest()
    if digest != COMPARE_SHA:
        errors.append('compare_surfaces.py is %s, not the reviewed %s' % (digest, COMPARE_SHA))
    for arm, runtime in zip(arms, (base_rt, cand_rt), strict=True):
        files[arm] = [out/('%s-%s-s%d.jsonl' % (stage, arm, i)) for i in ids]
        extra = sorted(set(map(Path, glob.glob(str(out/('%s-%s-s*.jsonl' % (stage, arm)))))) - set(files[arm]))
        if extra:
            errors.append('%s: unexpected shard files %s' % (arm, [p.name for p in extra]))
        n, ds, capped[arm], seen = 0, set(), set(), None if exact is None else Counter()
        for p in files[arm]:
            k, d = shard(p, p.with_suffix('.exit'), runtime, errors, capped[arm], seen)
            n += k
            ds.add(d)
        rows[arm] = n
        if exact is not None and seen is not None and seen != exact:
            errors.append('%s: data rows are not exactly the listed queries (%d listed not run, %d run but '
                          'not listed or repeated)' % (arm, sum((exact-seen).values()), sum((seen-exact).values())))
        refused = sorted((q for q in capped[arm] if not (q[0] == 'interface' and q[1:] in allowed)), key=str)
        if refused:
            errors.append('%s: %d capped row(s) the cap rule %s does not accept, e.g. %s'
                          % (arm, len(refused), caps[:40], refused[:2]))
        if n != expect:
            errors.append('%s: %d data rows, want %s' % (arm, n, expect_rows))
        if len(ds) != 1 or None in ds:
            errors.append('%s: package digests %s (want one)' % (arm, sorted(map(str, ds))))
        digests[arm] = sorted(map(str, ds))
    if digests.get(base_arm) == digests.get(cand_arm):
        errors.append('both arms report package digest %s: the %s arm did not load its runtime'
                      % (digests.get(base_arm), cand_arm))
    cmp_path = out/('cmp-%s.json' % stage)
    have = [str(p) for arm in arms for p in files.get(arm, []) if p.is_file()]
    if errors or len(have) != 2*len(ids):
        cmp_code, cmp = None, None
        errors.append('compare not run (shard checks failed)')
    else:
        run = subprocess.run([sys.executable, '-B', '-I', str(COMPARE), '--except-digests',
                              '--baseline', *map(str, files[base_arm]), '--candidate', *map(str, files[cand_arm])],
                             capture_output=True, text=True)
        cmp_path.write_text(run.stdout + run.stderr, encoding='utf8')
        cmp_code = run.returncode
        try:
            cmp = json.loads(run.stdout)
        except ValueError:
            cmp = None
        if cmp_code != 0:
            errors.append('compare_surfaces exit %d: %s' % (cmp_code, (run.stdout+run.stderr).strip()[-200:]))
    identical = capped_pairs = 0
    if cmp is not None:
        tally = cmp.get('tally', {})
        for k, v in tally.items():
            if k.startswith('VIOLATION'):
                errors.append('%s %d' % (k, v))
            elif k.endswith(':identical') or k.endswith(':identical-except-source-digests'):
                identical += v
            elif ':capped ' in k:
                pair = dict(x.split('=', 1) for x in k.split(':capped ', 1)[1].split() if '=' in x)
                if (pair.get('baseline'), pair.get('candidate')) in ACCEPTED_CAPS:
                    capped_pairs += v
                else:
                    errors.append('refused cap pair %s %d' % (k, v))
            elif k not in ('missing-in-candidate', 'candidate-extra'):
                errors.append('unexpected tally %s %d' % (k, v))
        for k in ('missing-in-candidate', 'candidate-extra'):
            if tally.get(k, 0):
                errors.append('%s %d' % (k, tally[k]))
        if not (cmp.get('baseline') == cmp.get('candidate') == rows[base_arm] == rows[cand_arm] == expect > 0):
            errors.append('row counts: compare %s/%s, shards %s/%s (want equal, > 0)' % (
                cmp.get('baseline'), cmp.get('candidate'), rows[base_arm], rows[cand_arm]))
        if identical <= 0:
            errors.append('no identical pair (vacuous: all capped or empty)')
        if identical + capped_pairs != cmp.get('baseline'):
            errors.append('identical %d + capped %d != baseline %s' % (identical, capped_pairs, cmp.get('baseline')))
    elif cmp_code is not None:
        errors.append('compare output is not JSON')
    result = dict(stage=stage, arms=list(arms), shards=ids, expect_rows=expect, rows=rows, package_digests=digests,
                  compare_exit=cmp_code, identical=identical, capped=capped_pairs, cap_rule=caps,
                  capped_rows={a: len(v) for a, v in capped.items()}, compare_sha=digest, errors=errors,
                  status='PASS' if not errors else 'FAIL')
    (out/('check-%s.json' % stage)).write_text(json.dumps(result, indent=1), encoding='utf8')
    print('%s %s identical %d capped %d rows %s%s' % (stage, result['status'], identical, capped_pairs, rows,
                                                    '' if not errors else ' | ' + '; '.join(errors)[:600]))
    return 0 if not errors else 1


if __name__ == '__main__':
    if len(sys.argv) != 10:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
