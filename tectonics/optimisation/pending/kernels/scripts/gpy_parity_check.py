"""q11 fail-closed parity check of one G-PY stage (coordinator, 16 Oct: review before queue).

Usage: python -B -I gpy_parity_check.py OUT STAGE SHARDS BASE_RT CAND_RT CAPS [ROWS]
  SHARDS: comma list of shard ids. Reads OUT/STAGE-ARM-s<i>.jsonl and OUT/STAGE-ARM-s<i>.exit (the
  shard's exit code, written by gpy_parity.sh) for ARM in base, gpy. Runs geometry's compare_surfaces.py
  (pinned) --except-digests on exactly those files, writes OUT/cmp-STAGE.json and OUT/check-STAGE.json,
  and exits 0 only if every check holds. compare_surfaces alone passes an empty or partial BASELINE
  (both arms missing the same shard, or no files at all) and an all-capped stage, and nothing checks a
  shard's exit code: these are the holes closed here.
  CAPS (r2, 16 Oct refuter RISK: a capped row is compared nowhere): 'none' = any row capped in either arm
          fails (IV1 at 60 s: 0 of 40,968 capped; deep at 120 s: 216 of 216 met in jets-r1 base/jets and
          final-f1); 'defer:LIST[,LIST...]' = rows capped in either arm are re-run at the deep cap: those on
          the deep lists by the deep stage, the rest are written to OUT/STAGE-extra-list.jsonl for the extra
          stage (final-f2's 2 s IV2 run capped 216 rows, 1 of them not on final-f1's deep list).
          r3 (16 Oct, delta refuter RISK C: the deferred rows were covered by construction only): defer
          also writes the deferred rows to OUT/STAGE-deferred-list.jsonl; 'cover:LIST' = as 'none', and every
          row on LIST must be among both arms' rows (the deep stage gets the sample's deferred list, so a
          deferred row the deep stage did not replay, e.g. a wall under --kinds interface, fails).
  ROWS: if given, each arm must have exactly this many data rows (the extra stage: one per listed row).
  shards  each expected shard of both arms exists and exited 0; its last row is its only done row;
          done.queries equals its data rows; done.runtime is the arm's runtime; no other shard files.
  arms    one package digest per arm, and the arms' digests differ (a gpy arm that loaded the base
          runtime would make the parity vacuous).
  compare exit 0; no VIOLATION; missing-in-candidate 0; candidate-extra 0; baseline == candidate == the
          shards' data rows > 0; identical (digest-only included) > 0; identical + capped == baseline.
"""
import glob
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

G = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/'
         'continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1')
COMPARE = G/'scripts'/'compare_surfaces.py'
COMPARE_SHA = 'bc2fa87807381a1c1dd79222d1c06b415434a2b53f109450307b12eb5122cd10'
ARMS = ('base', 'gpy')


def job(r):
    """replay_surfaces --only-list job of a row: (support index, cell, constraint name or (axis, end), other)."""
    other = r.get('other')
    return (r['support_index'], r['cell'][:16], r.get('constraint_name') or (r.get('axis'), r.get('end')),
            other[:16] if other else None)


def entry(k):
    """A job key as a replay --only-list entry line."""
    e = dict(support_index=k[0], cell=k[1], other=k[3])
    e.update({'constraint_name': k[2]} if isinstance(k[2], str) else dict(axis=k[2][0], end=k[2][1]))
    return json.dumps(e)+'\n'


def shard(path, exit_path, runtime, errors, capped, seen=None):
    """(data rows, package digest) of one shard; every problem is appended to errors, capped rows to capped,
    each data row's job key to seen (if given)."""
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
            if seen is not None:
                try:
                    seen.add(job(r))
                except (KeyError, TypeError) as e:
                    errors.append('%s line %d has no job key: %r' % (name, k+1, e))
            if r.get('status') == 'capped':
                capped[job(r)] = r
    if done != [len(parsed)-1]:
        errors.append('%s done rows at %s of %d lines (want exactly one, last)' % (name, done, len(parsed)))
        return rows, None
    tail = parsed[-1]
    if tail.get('queries') != rows:
        errors.append('%s done.queries %r != %d data rows' % (name, tail.get('queries'), rows))
    if tail.get('runtime') != runtime:
        errors.append('%s runtime %r, want %r' % (name, tail.get('runtime'), runtime))
    return rows, tail.get('package_digest')


def main(out, stage, shards, base_rt, cand_rt, caps, want_rows=None):
    out = Path(out)
    ids = [int(x) for x in shards.split(',')]
    errors, rows, digests, files, capped = [], {}, {}, {}, {}
    if len(set(ids)) != len(ids) or not ids:
        errors.append('bad shard list %r' % shards)
    cover = caps[len('cover:'):] if caps.startswith('cover:') and len(caps) > len('cover:') else None
    if caps != 'none' and cover is None and not (caps.startswith('defer:') and len(caps) > len('defer:')):
        errors.append('CAPS must be none, defer:LIST[,LIST...] or cover:LIST, not %r' % caps)
    seen = {arm: set() for arm in ARMS} if cover is not None else {}
    digest = sha256(COMPARE.read_bytes()).hexdigest()
    if digest != COMPARE_SHA:
        errors.append('compare_surfaces.py is %s, not the reviewed %s' % (digest, COMPARE_SHA))
    for arm, runtime in zip(ARMS, (base_rt, cand_rt), strict=True):
        files[arm] = [out/('%s-%s-s%d.jsonl' % (stage, arm, i)) for i in ids]
        extra = sorted(set(map(Path, glob.glob(str(out/('%s-%s-s*.jsonl' % (stage, arm)))))) - set(files[arm]))
        if extra:
            errors.append('%s: unexpected shard files %s' % (arm, [p.name for p in extra]))
        n, ds = 0, set()
        for p in files[arm]:
            k, d = shard(p, p.with_suffix('.exit'), runtime, errors, capped, seen.get(arm))
            n += k
            ds.add(d)
        rows[arm] = n
        if len(ds) != 1 or None in ds:
            errors.append('%s: package digests %s (want one)' % (arm, sorted(map(str, ds))))
        digests[arm] = sorted(map(str, ds))
    if digests['base'] == digests['gpy']:
        errors.append('both arms report package digest %s: the gpy arm did not load its runtime' % digests['base'])
    cmp_path = out/('cmp-%s.json' % stage)
    have = [str(p) for arm in ARMS for p in files[arm] if p.is_file()]
    if errors or len(have) != 2*len(ids):
        cmp_code, cmp = None, None
        errors.append('compare not run (shard checks failed)')
    else:
        run = subprocess.run([sys.executable, '-B', '-I', str(COMPARE), '--except-digests',
                              '--baseline', *map(str, files['base']), '--candidate', *map(str, files['gpy'])],
                             capture_output=True, text=True)
        cmp_path.write_text(run.stdout + run.stderr, encoding='utf8')
        cmp_code = run.returncode
        try:
            cmp = json.loads(run.stdout)
        except ValueError:
            cmp = None
        if cmp_code != 0:
            errors.append('compare_surfaces exit %d: %s' % (cmp_code, (run.stdout+run.stderr).strip()[-200:]))
    identical = capped_count = 0
    if cmp is not None:
        tally = cmp.get('tally', {})
        for k, v in tally.items():
            if k.startswith('VIOLATION'):
                errors.append('%s %d' % (k, v))
            elif k.endswith(':identical') or k.endswith(':identical-except-source-digests'):
                identical += v
            elif ':capped ' in k:
                capped_count += v
            elif k not in ('missing-in-candidate', 'candidate-extra'):
                errors.append('unexpected tally %s %d' % (k, v))
        for k in ('missing-in-candidate', 'candidate-extra'):
            if tally.get(k, 0):
                errors.append('%s %d' % (k, tally[k]))
        if not (cmp.get('baseline') == cmp.get('candidate') == rows['base'] == rows['gpy'] > 0):
            errors.append('row counts: compare %s/%s, shards %s/%s (want equal, > 0)' % (
                cmp.get('baseline'), cmp.get('candidate'), rows['base'], rows['gpy']))
        if identical <= 0:
            errors.append('no identical pair (vacuous: all capped or empty)')
        if identical + capped_count != cmp.get('baseline'):
            errors.append('identical %d + capped %d != baseline %s' % (identical, capped_count, cmp.get('baseline')))
        if capped_count != len(capped):
            errors.append('compare tallies %d capped pairs, the shards %d capped rows' % (capped_count, len(capped)))
    elif cmp_code is not None:
        errors.append('compare output is not JSON')
    if want_rows is not None and not (rows.get('base') == rows.get('gpy') == int(want_rows)):
        errors.append('rows %s, want %s per arm' % (rows, want_rows))
    deferred, extra, lists, written, covered = 0, [], {}, {}, None
    if caps == 'none' or cover is not None:
        if capped:
            errors.append('%d row(s) capped in an arm; none allowed at this stage: %s' % (
                len(capped), sorted(map(str, capped))[:3]))
    elif caps.startswith('defer:'):
        deep = set()
        for name in caps[len('defer:'):].split(','):
            try:
                raw = Path(name).read_bytes()
                deep.update(job(json.loads(line)) for line in raw.decode('utf8').splitlines() if line.strip())
                lists[name] = sha256(raw).hexdigest()
            except (OSError, UnicodeDecodeError, ValueError, KeyError) as e:
                errors.append('deep list %s unreadable: %s' % (name, str(e)[:120]))
        if not deep:
            errors.append('no deep-list rows: deferral would be vacuous')
        extra = sorted((k for k in capped if k not in deep), key=str)
        kept = sorted((k for k in capped if k in deep), key=str)
        deferred = len(kept)
        for kind, keys in (('extra', extra), ('deferred', kept)):
            path = out/('%s-%s-list.jsonl' % (stage, kind))
            path.write_text(''.join(map(entry, keys)), encoding='utf8')
            written[path.name] = sha256(path.read_bytes()).hexdigest()
    if cover is not None:
        try:
            raw = Path(cover).read_bytes()
            want = [job(json.loads(line)) for line in raw.decode('utf8').splitlines() if line.strip()]
            lists[cover] = sha256(raw).hexdigest()
        except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as e:
            errors.append('cover list %s unreadable: %s' % (cover, str(e)[:120]))
            want = None
        if want is not None:
            covered = len(want)
            for arm in ARMS:
                miss = [k for k in want if k not in seen[arm]]
                if miss:
                    errors.append('%s: %d listed row(s) not replayed: %s' % (
                        arm, len(miss), sorted(map(str, miss))[:3]))
    result = dict(stage=stage, shards=ids, rows=rows, package_digests=digests, compare_exit=cmp_code,
                  identical=identical, capped=capped_count, capped_rows=len(capped), caps=caps,
                  deferred_to_deep=deferred, extra=len(extra), deep_lists=lists, written_lists=written,
                  covered=covered, compare_sha=digest,
                  errors=errors, status='PASS' if not errors else 'FAIL')
    (out/('check-%s.json' % stage)).write_text(json.dumps(result, indent=1), encoding='utf8')
    print('%s %s identical %d capped %d (deferred %d, extra %d) rows %s%s' % (
        stage, result['status'], identical, capped_count, deferred, len(extra), rows,
        '' if not errors else ' | ' + '; '.join(errors)[:600]))
    return 0 if not errors else 1


if __name__ == '__main__':
    if len(sys.argv) not in (7, 8):
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
