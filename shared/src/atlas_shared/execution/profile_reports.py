"""Offline views of a collapsed raw stack capture."""
import ast
from collections import Counter, defaultdict
import os
import re

FRAME = re.compile(r'^(?P<func>.+?) \((?P<file>[^()]*?)(?::(?P<line>\d+))?\)$')
CHECK = re.compile(r'verif|check|guard|refus|hash|digest|identity|validat|_checked|release_boundary|tree_digest|sha|pin\b|_pin|require', re.I)
ACTIVE_WAIT = {'Popen._wait', 'wait', 'supervise', '_receive', '_drain', '_write', '_worker', '_collect', 'Condition.wait',
        '_Child.serve', 'Event.wait', 'Thread.join', '_wait_for_tstate_lock', 'select', 'sleep', 'Connection._recv'}
WAIT = {'Popen._wait', 'wait', 'supervise', '_receive', '_drain', '_write', '_worker', '_collect', 'Condition.wait', '_Child.serve'}
STD = re.compile(r'(^|[/\\])(pathlib|decoder|encoder|fractions|ntpath|genericpath|subprocess|threading|contextlib).py$|<frozen|(^|[/\\])json[/\\]|site-packages')
PROCESS = re.compile(r'process (\d+):"(.*?)";(.*)$')


def samples(path, *, process=False):
    with open(path, encoding='utf-8', errors='replace') as stream:
        for raw in stream:
            head, _, count = raw.rstrip('\n').rpartition(' ')
            if not count.isdigit():
                continue
            pid = command = None
            if process:
                match = PROCESS.match(head)
                if match is None:
                    continue
                pid, command, head = match.groups()
            frames = [match for frame in head.split(';') if (match := FRAME.match(frame))]
            yield frames, int(count), pid, command


def name(frame):
    return frame['func'], base(frame['file'])

REF = re.compile(r'(?:([A-Za-z_][\w./]*\.py|\b[A-Za-z_]\w*)(?=:\d))?:(\d+)(?:-(\d+))?')
ABBR = {'DG': 'integration_differential_geometry.py'}


def base(p):
    return p.replace(chr(92), '/').rsplit('/', 1)[-1]


def fname(tok, known):
    if tok.endswith('.py'):
        return base(tok)
    if tok in ABBR:
        return ABBR[tok]
    for c in (f'integration_{tok}.py', f'{tok}.py'):
        if c in known:
            return c
    return None


def rows_of(code, path, known):
    out, idx = [], 0
    with open(path, encoding='utf-8') as stream:
        for ln in stream:
            if code == 'r3' and ln.startswith('## Measured ceilings'):
                break
            if not ln.startswith('|') or ln.startswith('|---'):
                continue
            cells = [c.strip() for c in ln.strip().strip('|').split('|')]
            site = cells[1] if code == 'r3' or re.match(r'^[A-Z]+\d*-?\d+$', cells[0]) else cells[0]
            rid = cells[0] if site is not cells[0] else None
            refs, cur = set(), None
            for m in REF.finditer(site.replace('`', ' ')):
                tok, a, b = m.groups()
                if tok:
                    f = fname(tok, known)
                    cur = f if f else (None if tok.endswith('.py') or tok in ABBR else cur)
                    if tok and not f and not tok.endswith('.py'):
                        continue
                if cur:
                    a = int(a); b = int(b) if b else a
                    if b - a <= 200:
                        refs.update((cur, x) for x in range(a, b + 1))
            if refs:
                idx += 1
                out.append((rid or f'{code}-{idx}', site[:90], refs))
    return out


def defs(path):
    """line -> innermost def qualname, py-spy style."""
    with open(path, encoding='utf-8', errors='replace') as stream:
        tree = ast.parse(stream.read())
    span = {}

    def walk(node, q, in_def):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = (q + ('.<locals>.' if in_def else '.') if q else '') + ch.name
                isdef = not isinstance(ch, ast.ClassDef)
                if isdef:
                    for x in range(ch.lineno, (ch.end_lineno or ch.lineno) + 1):
                        span[x] = name                 # inner defs overwrite (walked later)
                walk(ch, name, isdef)
            else:
                walk(ch, q, in_def)
    walk(tree, '', False)
    return span


def rows(raw, root, out, notes):
    paths = defaultdict(list)
    for d, _, fs in os.walk(root):
        for f in fs:
            if f.endswith('.py'):
                paths[f].append(os.path.join(d, f))
    known = set(paths)
    rows = []
    for spec in notes:
        code, p = spec.split('=', 1)
        rows += rows_of(code, p, known)
    want_line, want_func, rfunc, amb = defaultdict(set), defaultdict(set), {}, {}
    cache = {}
    for i, (rid, site, refs) in enumerate(rows):
        fs = set()
        for f, x in refs:
            want_line[(f, x)].add(i)
            if f in paths:
                ps = sorted(paths[f], key=lambda p: ('working-snapshot-20261113' not in p, len(p)))
                amb[f] = len(ps)
                if f not in cache:
                    try:
                        cache[f] = defs(ps[0])
                    except (SyntaxError, OSError):
                        cache[f] = {}
                q = cache[f].get(x)
                if q:
                    fs.add((f, q))
        rfunc[i] = fs
        for k in fs:
            want_func[k].add(i)
    line_n, func_n, active = Counter(), Counter(), 0
    for fr, n, _, _ in samples(raw):
        if not fr or fr[-1]['func'] in WAIT:
            continue
        active += n
        hit_l, hit_f = set(), set()
        for m in fr:
            b = base(m['file'])
            if m['line']:
                hit_l |= want_line.get((b, int(m['line'])), set())
            hit_f |= want_func.get((b, m['func']), set())
        for i in hit_l:
            line_n[i] += n
        for i in hit_f:
            func_n[i] += n
    with open(out, 'w', encoding='utf-8') as o:
        o.write(f'# active samples {active} (= {active/100:.0f} CPU s); seconds = samples/100; one captured run\n')
        o.write('row\tline_s\tfunc_s\tfuncs\tfile_copies\tsite\n')
        for i, (rid, site, refs) in enumerate(rows):
            files = sorted({f for f, _ in refs})
            o.write(f'{rid}\t{line_n[i]/100:.2f}\t{func_n[i]/100:.2f}\t'
                    f'{";".join(sorted(q for _, q in rfunc[i])) or "-"}\t'
                    f'{",".join(f"{f}:{amb.get(f, 0)}" for f in files)}\t{site}\n')
    print(f'rows {len(rows)}; active {active}; out {out}')

def active(path, focus, top=30, *, exclude=None):
    excluded = re.compile(exclude) if exclude is not None else None
    leafline, act_self, act_incl, under, chk = Counter(), Counter(), Counter(), Counter(), Counter()
    total = active = focus_n = 0
    for frames, n, _, _ in samples(path):
        total += n
        if not frames:
            continue
        ks = [name(frame) for frame in frames]
        leaf = ks[-1]
        if leaf[0] in ACTIVE_WAIT:
            m = frames[-1]
            leafline[f"{leaf[1]}:{leaf[0]}:{m['line']}"] += n
            continue
        active += n
        act_self[leaf] += n
        for k in set(ks):
            act_incl[k] += n
        hit = next((k for k in ks if CHECK.search(k[0]) and not (excluded and excluded.search(k[0]))), None)
        if hit:
            chk[hit] += n
        if any(k[0] == focus for k in ks):
            focus_n += n
            i = max(i for i, k in enumerate(ks) if k[0] == focus)
            under[ks[i + 1] if i + 1 < len(ks) else ('<self>', '')] += n
    print(f'samples {total}; wait-leaf {total-active}; active {active}; check-stack active {sum(chk.values())} '
          f'({100*sum(chk.values())/max(active,1):.1f}% of active)')
    print('\nwait leaves (file:func:line samples):')
    for k, n in leafline.most_common(15): print(f'  {n:>8}  {k}')
    print('\ntop outermost check (active):')
    for k, n in chk.most_common(top): print(f'  {n:>8} {100*n/active:5.2f}%  {k[1]}:{k[0]}')
    print(f'\nfocus {focus}: {focus_n} active; direct children:')
    for k, n in under.most_common(12): print(f'  {n:>8} {100*n/max(focus_n,1):5.1f}%  {k[1]}:{k[0]}')
    print(f'\ntop {top} active self:')
    for k, n in act_self.most_common(top): print(f'  {n:>8} {100*n/active:5.2f}%  {k[1]}:{k[0]}')
    print(f'\ntop {2*top} active inclusive:')
    for k, n in act_incl.most_common(2 * top): print(f'  {n:>8} {100*n/active:5.2f}%  {k[1]}:{k[0]}')

def check_share(path, top=25):
    proc_total, proc_check, cmds = Counter(), Counter(), {}
    self_t, incl, check_self = Counter(), Counter(), Counter()
    sites = defaultdict(Counter)                       # outermost check frame -> samples
    for frames, n, pid, cmd in samples(path, process=True):
        cmds[pid] = cmd[:160]
        proc_total[pid] += n
        keys = [name(f) for f in frames]
        if keys:
            self_t[keys[-1]] += n
        for k in set(keys):
            incl[k] += n
        hit = next((k for k in keys if CHECK.search(k[0])), None)  # outermost (frames run root -> leaf)
        if hit:
            proc_check[pid] += n
            sites[hit][keys[-1]] += n
            check_self[hit] += n
    total = sum(proc_total.values())
    print(f'samples {total}; check-stack samples {sum(proc_check.values())} '
          f'({100*sum(proc_check.values())/max(total,1):.1f}%)')
    print('\nper process (samples, check %, cmd):')
    for pid, n in proc_total.most_common():
        print(f'  {pid:>6} {n:>8} {100*proc_check[pid]/n:5.1f}%  {cmds[pid]}')
    print(f'\ntop {top} outermost check functions (samples, % of all):')
    for k, n in check_self.most_common(top):
        print(f'  {n:>8} {100*n/total:5.2f}%  {k[1]}:{k[0]}')
    print(f'\ntop {top} functions by self samples:')
    for k, n in self_t.most_common(top):
        print(f'  {n:>8} {100*n/total:5.2f}%  {k[1]}:{k[0]}')

def callers(path, names):
    names = names.split(',')
    cal, tot = defaultdict(Counter), Counter()
    for fr, n, _, _ in samples(path):
        if not fr or fr[-1]['func'] in WAIT:
            continue
        seen = set()
        for i in range(len(fr) - 1, -1, -1):
            f = fr[i]['func']
            if f in names and f not in seen:
                seen.add(f); tot[f] += n
                j = i - 1
                while j >= 0 and STD.search(fr[j]['file']): j -= 1
                if j >= 0:
                    m = fr[j]; cal[f][f"{m['file'].replace(chr(92),'/').rsplit('/',1)[-1]}:{m['line']} {m['func']}"] += n
    for f in names:
        print(f'{f}: {tot[f]} incl')
        for k, n in cal[f].most_common(5): print(f'   {n:>7}  {k}')
