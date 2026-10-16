"""r2 refuter: does the checker's extra list / deferral select the rows replay_surfaces --only-list runs?

Usage: python -B sim_lists.py WORK [all-capped]
Builds a synthetic iv2-sample OUT from final-f2's real 2 s IV2 run (cand-iv2-surfaces-s0..s5; gpy = same rows,
gpy done row), runs the REAL gpy_parity_check.py with defer:<final-f1 capped lists>, then replays
replay_surfaces.py's --only-list parse (lines 95-103) and match (lines 281-284) verbatim over every row:
  - each extra-list entry must select exactly one row, a capped one, and every capped off-list row once;
  - each deferred row must be selected by the deep lists AND be an interface (the deep stage runs --kinds interface).
With 'all-capped', every row is marked capped in the base arm (stress: the extra list then lists every off-list row).
"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
G = T/('fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/'
       'geometry-growth-r1')
SRC, F = G/'evidence'/'final-f2', G/'evidence'/'final-f1'
CHECK = T/'ck'/'scripts'/'gpy_parity_check.py'
WORK = Path(sys.argv[1])
ALL = len(sys.argv) > 2 and sys.argv[2] == 'all-capped'
STAGE, IDS = 'iv2-sample', range(6)
RT2G = 'test:%s/ck/gpy-f2' % T.as_posix()

WORK.mkdir(parents=True)
rows_all, base_rt = [], None
for i in IDS:
    lines = [json.loads(l) for l in open(SRC/('cand-iv2-surfaces-s%d.jsonl' % i), encoding='utf8')]
    done = lines[-1]
    assert done.get('done')
    base_rt = done['runtime']
    data = lines[:-1]
    if ALL:
        data = [dict(r, status='capped') if 'job_counts' not in r else r for r in data]
    rows_all += [r for r in data if 'job_counts' not in r]
    for arm, d in (('base', done), ('gpy', dict(done, runtime=RT2G, package_digest='c'*64))):
        body = data if arm == 'base' else lines[:-1]
        p = WORK/('%s-%s-s%d.jsonl' % (STAGE, arm, i))
        p.write_text(''.join(json.dumps(r)+'\n' for r in body + [d]), encoding='utf8')
        p.with_suffix('.exit').write_text('0\n', encoding='utf8')
deep_lists = [F/('capped-list-%d.jsonl' % i) for i in range(6)]
run = subprocess.run([sys.executable, '-B', '-I', str(CHECK), str(WORK), STAGE, '0,1,2,3,4,5', base_rt, RT2G,
                      'defer:' + ','.join(map(str, deep_lists))], capture_output=True, text=True)
print('checker exit', run.returncode, (run.stdout+run.stderr).strip()[-300:])


def parse_only_list(path):
    """replay_surfaces.py lines 95-103, verbatim."""
    only_list, only_pairs = set(), set()
    for line in open(path, encoding='utf8'):
        if line.strip():
            s = json.loads(line)
            job = (s['support_index'], s['cell'][:16], s.get('constraint_name') or (s.get('axis'), s.get('end')))
            if 'other' in s:
                only_pairs.add((*job, s['other'][:16] if s['other'] else None))
            else:
                only_list.add(job)
    return only_list, only_pairs


def selected(r, only_list, only_pairs, kinds=('wall', 'interface')):
    """replay_surfaces.py lines 281-284, verbatim, on a row's job."""
    if r['kind'] not in kinds:
        return None
    index, key, other = r['support_index'], r['cell'], r.get('other')
    where = dict(constraint_name=r['constraint_name']) if r['kind'] == 'interface' else dict(axis=r['axis'], end=r['end'])
    job = (index, key[:16], where.get('constraint_name') or (where.get('axis'), where.get('end')))
    if job not in only_list and (*job, other[:16] if other else None) not in only_pairs:
        return None
    return (*job, other)


capped = [r for r in rows_all if r['status'] == 'capped']
xl = WORK/('%s-extra-list.jsonl' % STAGE)
ol, op = parse_only_list(xl)
n_entries = sum(1 for l in open(xl, encoding='utf8') if l.strip())
hits = [r for r in rows_all if selected(r, ol, op)]
dl, dp = set(), set()
for p in deep_lists:
    a, b = parse_only_list(p)
    dl |= a
    dp |= b
deep_hit = [r for r in capped if selected(r, dl, dp, kinds=('interface',))]
deep_any = [r for r in capped if selected(r, dl, dp)]
chk = json.loads((WORK/('check-%s.json' % STAGE)).read_text(encoding='utf8'))
dupe = Counter(selected(r, ol, op) for r in hits)
print('rows', len(rows_all), 'capped', len(capped), 'extra entries', n_entries, 'rows replay selects', len(hits),
      '(capped %d)' % sum(r['status'] == 'capped' for r in hits),
      'entries selecting >1 row', sum(v > 1 for v in dupe.values()))
print('checker deferred', chk['deferred_to_deep'], 'extra', chk['extra'],
      '| capped rows the deep stage (--kinds interface) runs', len(deep_hit), 'any kind', len(deep_any))
H, D = set(map(id, hits)), set(map(id, deep_hit))
print('capped rows covered by neither 2b nor deep:', len([r for r in capped if id(r) not in H and id(r) not in D]))
print('kinds in extra:', Counter(r['kind'] for r in hits))
