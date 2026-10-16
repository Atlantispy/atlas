"""Mutant proof of gpy_parity_check.py (q11 review before queue). Small lane, no runtime loaded.

Usage: python -B -I gpy_parity_proof.py WORK
WORK must not exist. Each case is a synthetic OUT built from real IV1 surface shards (geometry's
evidence/final-f2/cand-iv1-surfaces-s0/s1.jsonl, read-only; first 1,500 data rows of each plus its done
row, queries set to match): base = those rows; gpy = the same rows with the done row's runtime and
package digest of the gpy arm, as a real G-PY arm would write them. The real pair and a digest-only
change must PASS; every planted defect must FAIL. Writes WORK/proof.json; exit 0 only if all as expected.
r2 (16 Oct): the checker's CAPS argument. 'none' must fail any capped row; 'defer:LIST' must pass a capped
row on the list (extra list empty) and one off it (extra list = exactly that row), and fail an empty or
missing list; ROWS must fail a count mismatch.
r3 (16 Oct, delta refuter RISK C): defer must also write the deferred rows (deferred list); 'cover:LIST' must
pass when every listed row is in both arms (incl. the deferred list a defer case wrote, and an empty list) and
fail a listed row not replayed (another cell; the wall form axis/end), a missing list, a capped row, and an
empty 'cover:'. FAIL cases with a reason must fail for that reason (check-STAGE.json errors).
"""
import json
import subprocess
import sys
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
SRC = (T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/'
       'geometry-growth-r1/evidence/final-f2')
CHECK = T/'ck'/'scripts'/'gpy_parity_check.py'
STAGE, IDS, N = 'iv1-surfaces', (0, 1), 1500
BASE_RT, CAND_RT = 'test:%s/gg/final-f2' % T.as_posix(), 'test:%s/ck/gpy-f2' % T.as_posix()
WORK = Path(sys.argv[1])
results = {}


def real(i):
    rows, done = [], None
    for line in open(SRC/('cand-iv1-surfaces-s%d.jsonl' % i), encoding='utf8'):
        r = json.loads(line)
        if r.get('done'):
            done = r
        elif 'job_counts' not in r and len(rows) < N:
            rows.append(r)
    assert done is not None and len(rows) == N and done['runtime'] == BASE_RT
    return rows, dict(done, queries=N)


REAL = {i: real(i) for i in IDS}


def arms():
    """{(arm, i): [rows..., done]} for the clean pair (deep copies)."""
    data = {}
    for i in IDS:
        rows, done = REAL[i]
        data['base', i] = [dict(r) for r in rows] + [dict(done)]
        data['gpy', i] = [dict(r) for r in rows] + [dict(done, runtime=CAND_RT, package_digest='c'*64)]
    return data


def write(out, data, exits):
    out.mkdir(parents=True)
    for (arm, i), lines in data.items():
        p = out/('%s-%s-s%d.jsonl' % (STAGE, arm, i))
        p.write_text(''.join(line if isinstance(line, str) else json.dumps(line)+'\n' for line in lines),
                     encoding='utf8')
        if exits.get((arm, i), '0') is not None:
            p.with_suffix('.exit').write_text(exits.get((arm, i), '0')+'\n', encoding='utf8')


def job_entry(r):
    """The row as a replay --only-list / deep-list entry."""
    e = dict(support_index=r['support_index'], cell=r['cell'], other=r.get('other'))
    if r.get('constraint_name'):
        e['constraint_name'] = r['constraint_name']
    else:
        e.update(axis=r.get('axis'), end=r.get('end'))
    return e


def case(name, want_pass, mutate=None, exits=None, caps='none', rows=None, deep=None, post=None, cover=None):
    """deep: list of rows for a deep-list file (caps 'defer' then names it); cover: list of rows for a
    cover-list file, or a path (caps 'cover'); post(out) -> bool: extra check."""
    data = arms()
    if mutate:
        mutate(data)
    out = WORK/''.join(c if c.isalnum() else '-' for c in name)  # p1 stopped on '>' (invalid on Windows)
    write(out, data, exits or {})
    if deep is not None:
        listed = WORK/(out.name+'-deep.jsonl')
        listed.write_text(''.join(json.dumps(job_entry(r))+'\n' for r in deep), encoding='utf8')
        caps = 'defer:%s' % listed
    if isinstance(cover, list):
        listed = WORK/(out.name+'-cover.jsonl')
        listed.write_text(''.join(json.dumps(job_entry(r))+'\n' for r in cover), encoding='utf8')
        caps = 'cover:%s' % listed
    elif cover is not None:
        caps = 'cover:%s' % cover
    run = subprocess.run([sys.executable, '-B', '-I', str(CHECK), str(out), STAGE, ','.join(map(str, IDS)),
                          BASE_RT, CAND_RT, caps, *([] if rows is None else [str(rows)])],
                         capture_output=True, text=True)
    ok = (run.returncode == 0) == want_pass and (post is None or post(out))
    tail = (run.stdout+run.stderr).strip()[-220:]
    results[name] = dict(exit=run.returncode, want='PASS' if want_pass else 'FAIL', ok=ok, tail=tail)
    print('%-40s exit %d  %s  %s' % (name, run.returncode, 'as expected' if ok else 'WRONG', tail[:150]))


def drop(*keys):
    def m(data):
        for k in keys:
            del data[k]
    return m


def row_edit(fn, arm='gpy', i=1, k=700):
    def m(data):
        fn(data[arm, i], k)
    return m


def set_field(field, value):
    return lambda lines, k: lines[k].update({field: value})


def remove_row(lines, k):
    del lines[k]
    lines[-1]['queries'] -= 1


def extra_row(lines, k):
    r = dict(lines[k], cell='ffffffffffffffff')
    lines.insert(k, r)
    lines[-1]['queries'] += 1


def dup_row(lines, k):
    lines.insert(k, dict(lines[k]))
    lines[-1]['queries'] += 1


def digest_only(data):
    for i in IDS:
        for r in data['gpy', i][:100]:
            r['measure_sha'] = 'f'*16 if r['measure_sha'] != 'f'*16 else 'e'*16


def all_capped(data):
    for lines in data.values():
        for r in lines[:-1]:
            r['status'] = 'capped'


WORK.mkdir(parents=True, exist_ok=False)
case('real pair', True)
case('real pair, digest-only change', True, digest_only)
case('gpy shard missing', False, drop(('gpy', 1)))
case('base shard missing', False, drop(('base', 1)))
case('both arms miss the same shard', False, drop(('base', 1), ('gpy', 1)))
case('no shard files at all', False, drop(*[(a, i) for a in ('base', 'gpy') for i in IDS]))
case('gpy shard timed out (exit 124)', False, exits={('gpy', 0): '124'})
case('base exit file missing', False, exits={('base', 1): None})
case('gpy done row missing', False, lambda d: d['gpy', 1].pop())
case('gpy last line cut mid-row', False, lambda d: d['gpy', 1].__setitem__(-1, json.dumps(d['gpy', 1][-1])[:40]))
case('two done rows', False, lambda d: d['gpy', 0].insert(5, dict(d['gpy', 0][-1])))
case('done.queries off by one', False, lambda d: d['gpy', 0][-1].update(queries=N+1))
case('nodigest hash changed (VIOLATION)', False, row_edit(set_field('measure_sha_nodigest', '0'*16)))
case('nodigest hash None in gpy', False, row_edit(set_field('measure_sha_nodigest', None)))
case('status met -> unmet, same hash', False, row_edit(set_field('status', 'unmet')))
case('gpy row removed (queries kept true)', False, row_edit(remove_row))
case('gpy extra row (queries kept true)', False, row_edit(extra_row))
case('gpy duplicate row', False, row_edit(dup_row))
case('every pair capped', False, all_capped)
CAP = row_edit(set_field('status', 'capped'), arm='base')
ROW, OTHER_ROW = REAL[1][0][700], REAL[0][0][5]


def extra_is(rows_wanted, kind='extra'):
    def post(out):
        p = out/('%s-%s-list.jsonl' % (STAGE, kind))
        got = [json.loads(line) for line in p.read_text(encoding='utf8').splitlines()] if p.is_file() else None
        return got == [job_entry(r) for r in rows_wanted]
    return post


def both(*posts):
    return lambda out: all(p(out) for p in posts)


def check_json(out):
    p = out/('check-%s.json' % STAGE)
    return json.loads(p.read_text(encoding='utf8')) if p.is_file() else {}


def reason(text):
    """The case's check-STAGE.json errors include text (a FAIL for the intended reason)."""
    return lambda out: any(text in e for e in check_json(out).get('errors', []))


def covered(n):
    return lambda out: check_json(out).get('covered') == n


case('one base row capped, caps none', False, CAP)
case('one gpy row capped, caps none', False, row_edit(set_field('status', 'capped')))
case('capped row on the deep list (defer)', True, CAP, deep=[OTHER_ROW, ROW],
     post=both(extra_is([]), extra_is([ROW], 'deferred')))
case('capped row off the deep list (defer)', True, CAP, deep=[OTHER_ROW],
     post=both(extra_is([ROW]), extra_is([], 'deferred')))
case('every pair capped (defer)', False, all_capped, deep=[ROW])
case('defer with an empty deep list', False, CAP, deep=[])
case('defer with a missing deep list', False, CAP, caps='defer:%s' % (WORK/'no-such-list.jsonl'))
case('unknown CAPS value', False, caps='some')
DEFERRED = WORK/'capped-row-on-the-deep-list--defer-'/('%s-deferred-list.jsonl' % STAGE)
case('cover: the deferred list a defer case wrote', True, cover=DEFERRED, post=covered(1))
case('cover: two listed rows, both replayed', True, cover=[ROW, OTHER_ROW], post=covered(2))
case('cover: empty list', True, cover=[], post=covered(0))
case('cover: a listed row not replayed', False, cover=[ROW, dict(ROW, cell='ffffffffffffffff')],
     post=reason('not replayed'))
case('cover: a listed wall not replayed', False, cover=[dict(ROW, constraint_name=None, axis=0, end='lo')],
     post=reason('not replayed'))
case('cover: missing list', False, cover=WORK/'no-such-list.jsonl', post=reason('unreadable'))
case('cover: a capped row', False, CAP, cover=[ROW], post=reason('none allowed'))
case('cover: empty CAPS value', False, caps='cover:', post=reason('CAPS must be'))
case('ROWS matches', True, rows=2*N)
case('ROWS mismatch', False, rows=2*N+1)
case('same package digest both arms', False,
     lambda d: [d['gpy', i][-1].update(package_digest=d['base', i][-1]['package_digest']) for i in IDS])
case('gpy arm ran the base runtime', False, lambda d: d['gpy', 0][-1].update(runtime=BASE_RT))
case('two package digests in one arm', False, lambda d: d['gpy', 1][-1].update(package_digest='d'*64))
case('stray shard file', False, lambda d: d.__setitem__(('gpy', 7), list(d['gpy', 0])))
ok = all(r['ok'] for r in results.values())
(WORK/'proof.json').write_text(json.dumps(dict(source=str(SRC), check=str(CHECK), results=results, ok=ok), indent=1),
                               encoding='utf8')
print('PROOF', 'PASS' if ok else 'FAIL', '%d/%d as expected' % (sum(r['ok'] for r in results.values()), len(results)))
sys.exit(0 if ok else 1)
