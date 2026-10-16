"""S7: how much of each existing cProfile is the source-identity guard?  READ-ONLY.

Only pstats / stdlib.  Reads the profile files named in PROFILES (plus any *.prof / *.pstats
under T/hs and T/ps modified on 16 Oct 2026) and writes ONE text file (argv[1]).

Guard families (entry points), identified by file name + function name:
  REUSE    reuse.py  ExecutionContext.verify, ExecutionContext.verify_boundary
  HEAT     private_heat_native_issuer_r*.py  _verified_call, _verify_call_record, _verify_call,
           _verify_implementation;  private_heat_loaded_identity_r*.py  verify
  HEATSRC  private_heat_*.py (not the issuer/loaded-identity files above)  verify_sources, _verify_sources,
           _verify, verified_private: small per-module source-hash checks used by the heat stack
  CAPTURE  reuse.py  ExecutionContext._capture  (building a context; includes one verify_boundary, which is
           reported with the context capture and NOT counted as a per-call verify)

De-nesting.  cProfile cumtime of an inner call is contained in the outer call's cumtime.
For a family F the guard total is the sum, over every member f of F, of the caller-edge
cumtime of the edges (c -> f) whose caller c is NOT itself in F ("outermost entries").
Time under c -> f is then counted once, however deeply verify() calls verify_boundary().
Across families (REUSE inside HEAT) a gprof-style estimate is used: p(c) = fraction of c's
time that already lies under some family member, propagated down the caller edges
(p = 1 for members, p(x) = sum_c ct(c->x) p(c) / sum_c ct(c->x)); an outer edge is
counted as ct * (1 - p(c)).  That union figure is an estimate; the single-family figures are exact.
"""
import glob
import os
import re
import sys
import time
import pstats

T = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10'
R = T + '/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
E = R + '/geometry-growth-r1/evidence'

PROFILES = [
    ('Admission / initial metrics', 'initial-metrics', E + '/admission-profile-r1/initial-metrics.prof'),
    ('Heat advance (W4 same-call)', 'heat-w4-p1 advance', E + '/heat-w4-p1/advance.prof'),
    ('Heat advance (W4 same-call)', 'heat-w4-p3 advance', E + '/heat-w4-p3/advance.prof'),
]
for _p in sorted(glob.glob(E + '/heat-w4-p4w/worker-*.prof')):
    PROFILES.append(('Heat workers (W4 p4w)', os.path.basename(_p)[:-5], _p))
PROFILES += [
    ('Heat tail', 'heat-tail-w4', R + '/probes/step8/claude-20261015/heat-tail-w4.pstats'),
    ('Interfaces / deep surface', 'profile-interfaces-iv2-r1', E + '/profile-interfaces-iv2-r1.prof'),
    ('Interfaces / deep surface', 'profile-interfaces-iv2-wp23-r1', E + '/profile-interfaces-iv2-wp23-r1.prof'),
    ('Interfaces / deep surface', 'profile-iv2-rc1-858-r1', E + '/profile-iv2-rc1-858-r1.prof'),
    ('Interfaces / deep surface', 'surface-deep-iv2-s0-r2', E + '/surface-deep-iv2-s0-r2.prof'),
    ('Interfaces / deep surface', 'wp22 cand-deep-s0', E + '/wp22-profile/cand-deep-s0.prof'),
    ('Interfaces / deep surface', 'stall-880 profile-rc1', E + '/stall-880/profile-rc1.prof'),
    ('Pressure', 'ps small5 admission', T + '/ps/small5/admission.prof'),
    ('Pressure', 'ps small5 pressure-stage', T + '/ps/small5/pressure-stage.prof'),
]


def norm(p):
    return p.replace('\\', '/')


def base(p):
    return norm(p).rsplit('/', 1)[-1]


def short(path):
    p = norm(path)
    for marker in ('resumability-r1/', 'the-diadem-local-tasks-10/', 'Users/LOCAL_USER/'):
        i = p.find(marker)
        if i >= 0:
            return p[i + len(marker):]
    return p


def label(k):
    fn, ln, name = k
    if fn == '~':
        return name
    return '%s:%s %s' % (short(fn), ln, name)


def add_extra_profiles():
    """Any *.prof / *.pstats under T/hs and T/ps modified on or after 16 Oct 2026, not already listed."""
    cut = time.mktime((2026, 10, 16, 0, 0, 0, 0, 0, -1))
    seen = {norm(os.path.abspath(p[2])) for p in PROFILES}
    found = []
    for root in (T + '/hs', T + '/ps'):
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                if f.endswith(('.prof', '.pstats')):
                    full = os.path.join(dirpath, f)
                    key = norm(os.path.abspath(full))
                    if key not in seen and os.path.getmtime(full) >= cut:
                        found.append(full)
    for full in sorted(found):
        PROFILES.append(('Other 16 Oct profile', short(full), full))
    return found


# ---------------------------------------------------------------- classification
HEAT_NAME = re.compile(r'^(_verified_call|_verify_call_record|_verify_call|_verify_implementation|verify_identity)$')
REUSE_INTERNAL = {'_verify_callable_inventory', '_source_bytes', '_source_walk', 'check', '_file_id',
                  '_directory_id', '_callable_inventory', '_capture_sources', '_identity_modules',
                  '_runtime_record'}
THIN = {'identity', 'provenance', '__enter__', '__exit__', 'close', '_verify'}


def family(k):
    fn, ln, name = k
    b = base(fn)
    if b == 'reuse.py':
        if name in ('verify', 'verify_boundary'):
            return 'REUSE'
        if name == '_capture':
            return 'CAPTURE'
    if re.match(r'private_heat_native_issuer_r\d+\.py$', b) and HEAT_NAME.match(name):
        return 'HEAT'
    if re.match(r'private_heat_loaded_identity_r\d+\.py$', b) and name == 'verify':
        return 'HEAT'
    if b.startswith('private_heat_') and re.match(r'^_?verif(y|ied)', name):
        return 'HEATSRC'
    return None


def guard_named(k):
    """Rows for the raw table: verif*-named functions in reuse.py, private_heat_*, *execution* files."""
    fn, ln, name = k
    b = base(fn)
    if re.search(r'verif', name) and (b == 'reuse.py' or b.startswith('private_heat_') or 'execution' in b):
        return True
    return b == 'reuse.py' and name in REUSE_INTERNAL | {'_capture'}


def wrapper(k):
    """Domain-level _verify/verify methods in other package modules (call ExecutionContext.verify)."""
    fn, ln, name = k
    b = base(fn)
    if b == 'reuse.py' or b.startswith('private_heat_'):
        return False
    return bool(re.match(r'^_?verify(_[a-z]+)?$', name)) and 'atlas_tectonics' in norm(fn)


# ---------------------------------------------------------------- graph helpers
def edges_of(S):
    """callee -> {caller: (ncalls, cumtime)} from the pstats caller dicts."""
    out = {}
    for k, val in S.items():
        d = {}
        for c, v in val[4].items():
            if isinstance(v, tuple):
                d[c] = (v[0], v[3])
            else:
                d[c] = (v, 0.0)
        out[k] = d
    return out


def callees_of(edges):
    out = {}
    for callee, cs in edges.items():
        for c, (nc, ct) in cs.items():
            out.setdefault(c, {})[callee] = (nc, ct)
    return out


def outer_entries(S, edges, fam):
    """Outermost entries into the family: edges (caller -> member) with the caller outside the family."""
    rows = []
    for f in fam:
        cs = edges.get(f, {})
        if not cs:  # profile root: no caller recorded, take the member's own totals
            rows.append((None, f, S[f][1], S[f][3]))
        for c, (nc, ct) in cs.items():
            if c not in fam:
                rows.append((c, f, nc, ct))
    return rows


def propagate(edges, members, iters=80):
    p = {k: 0.0 for k in edges}
    for g in members:
        p[g] = 1.0
    for _ in range(iters):
        moved = 0.0
        for k, cs in edges.items():
            if k in members or not cs:
                continue
            tot = sum(ct for nc, ct in cs.values())
            if tot <= 0:
                continue
            val = sum(ct * p.get(c, 0.0) for c, (nc, ct) in cs.items()) / tot
            moved = max(moved, abs(val - p[k]))
            p[k] = val
        if moved < 1e-9:
            break
    return p


def union_total(S, edges, members, exclude=frozenset()):
    p = propagate(edges, members)
    tot = 0.0
    ncalls = 0
    for f in members:
        cs = edges.get(f, {})
        if not cs:
            tot += S[f][3]
            ncalls += S[f][1]
        for c, (nc, ct) in cs.items():
            if c in members or c in exclude:
                continue
            tot += ct * (1.0 - p.get(c, 0.0))
            ncalls += nc * (1.0 - p.get(c, 0.0))
    return tot, ncalls


def chain(edges, k, limit=4):
    """k <- top caller <- ... while the current function is a thin wrapper (identity, _verify, ...)."""
    parts = [label(k)]
    cur = k
    for _ in range(limit):
        name = cur[2]
        if cur is not k and name not in THIN:
            break
        cs = edges.get(cur, {})
        if not cs:
            break
        nxt = max(cs.items(), key=lambda it: it[1][1])[0]
        parts.append(label(nxt))
        cur = nxt
        if cur[2] not in THIN:
            break
    return ' <- '.join(parts)


BLOCKING = re.compile(r"(acquire|\bread\b|readinto|readline|recv|wait|sleep|select|poll|WaitFor|_queue\.SimpleQueue)", re.I)


def analyse(stage, name, path, out):
    st = pstats.Stats(path)
    S = st.stats
    total = st.total_tt
    root_ct = max(v[3] for v in S.values())
    edges = edges_of(S)
    callees = callees_of(edges)
    blocking = sum(v[2] for k, v in S.items() if (k[0] == '~' or k[0].startswith('<')) and BLOCKING.search(k[2]))
    reuse_paths = sorted({short(k[0]) for k in S if base(k[0]) == 'reuse.py'})
    heat_paths = sorted({short(k[0]) for k in S if family(k) == 'HEAT'})

    w = out.write
    w('=' * 118 + '\n')
    w('STAGE   : %s\nPROFILE : %s\nFILE    : %s\n' % (stage, name, norm(path)))
    w('reuse.py     : %s\n' % ('; '.join(reuse_paths) or '(none in profile)'))
    w('heat issuer  : %s\n' % ('; '.join(sorted({p for p in heat_paths})) or '(none in profile)'))
    reuse_keys = [k for k in S if base(k[0]) == 'reuse.py']
    w('reuse.py functions executed in this profile: %d, own time %.3f s\n'
      % (len(reuse_keys), sum(S[k][2] for k in reuse_keys)))
    w('total own time (sum of tottime) = %.3f s | root cumtime = %.3f s | functions = %d | '
      'blocking/wait tottime (heuristic) = %.3f s (%.1f%%)\n'
      % (total, root_ct, len(S), blocking, 100 * blocking / total if total else 0))
    top = sorted(S.items(), key=lambda kv: kv[1][2], reverse=True)[:4]
    w('top tottime : ' + ' | '.join('%s %.2fs' % (label(k)[-60:], v[2]) for k, v in top) + '\n\n')

    # --- raw rows
    keys = [k for k in S if guard_named(k) or wrapper(k) or family(k)]
    keys.sort(key=lambda k: S[k][3], reverse=True)
    w('%-9s %-9s %8s %9s %9s %7s %8s  %s\n' % ('class', 'role', 'ncalls', 'tottime', 'cumtime', 'cum%', 'ms/call', 'function'))
    for k in keys:
        cc, nc, tt, ct, _ = S[k]
        fam = family(k)
        if fam:
            role, cls = 'ENTRY', fam
        elif wrapper(k):
            role, cls = 'wrapper', 'DOMAIN'
        elif base(k[0]) == 'reuse.py' and k[2] in REUSE_INTERNAL:
            role, cls = 'internal', 'REUSE'
        else:
            role, cls = 'other', 'OTHER'
        w('%-9s %-9s %8d %9.3f %9.3f %6.2f%% %8.2f  %s\n'
          % (cls, role, nc, tt, ct, 100 * ct / total if total else 0, 1000 * ct / nc if nc else 0, label(k)))
        if role == 'ENTRY':
            cs = sorted(edges[k].items(), key=lambda it: it[1][1], reverse=True)[:3]
            for c, (cnc, cct) in cs:
                w('            <- %7d calls %9.3f s  %s\n' % (cnc, cct, chain(edges, c)))
    if not keys:
        w('(no verify-named function in reuse.py / private_heat_* / *execution* / domain wrappers)\n')

    # --- families
    res = {'stage': stage, 'name': name, 'total': total, 'root': root_ct, 'blocking': blocking,
           'reuse_path': ';'.join(reuse_paths)}
    cap_callers = {k for k in S if base(k[0]) == 'reuse.py' and k[2] in ('_capture', '_capture_sources')}
    for fam_name in ('REUSE', 'HEAT', 'HEATSRC', 'CAPTURE'):
        fam = {k for k in S if family(k) == fam_name}
        rows = outer_entries(S, edges, fam) if fam else []
        cap_rows = []
        if fam_name == 'REUSE':
            # verify_boundary called from inside a context capture belongs to that capture, not to a per-call verify
            cap_rows = [r for r in rows if r[0] in cap_callers]
            rows = [r for r in rows if r[0] not in cap_callers]
        o_nc = sum(r[2] for r in rows)
        o_ct = sum(r[3] for r in rows)
        all_nc = sum(S[k][1] for k in fam)
        all_ct = sum(S[k][3] for k in fam)
        res[fam_name] = dict(n=len(fam), o_nc=o_nc, o_ct=o_ct, all_nc=all_nc, all_ct=all_ct,
                             cap_nc=sum(r[2] for r in cap_rows), cap_ct=sum(r[3] for r in cap_rows))
        busy = total - blocking
        w('\n[%s] members=%d | OUTERMOST entries: %d calls, cum %.3f s = %.2f%% of total own time (%.2f%% of non-waiting), '
          '%.2f ms/call | (sum over all members incl. nested: %d calls, %.3f s)\n'
          % (fam_name, len(fam), o_nc, o_ct, 100 * o_ct / total if total else 0,
             100 * o_ct / busy if busy > 0 else 0, 1000 * o_ct / o_nc if o_nc else 0, all_nc, all_ct))
        if cap_rows:
            w('    (excluded above: %d verify_boundary calls made inside context capture, %.3f s)\n'
              % (res[fam_name]['cap_nc'], res[fam_name]['cap_ct']))
        agg = {}
        for c, f, nc, ct in rows:
            agg.setdefault(c, [0, 0.0])
            agg[c][0] += nc
            agg[c][1] += ct
        for c, (nc, ct) in sorted(agg.items(), key=lambda it: it[1][1], reverse=True)[:3]:
            w('    outer caller: %7d calls %9.3f s  %s\n' % (nc, ct, chain(edges, c) if c else '(profile root)'))

    # --- what verify_boundary spends its time on (source re-read vs inventory walk vs handle check)
    vb = [k for k in S if family(k) == 'REUSE' and k[2] == 'verify_boundary']
    for k in vb:
        w('\n[REUSE breakdown] direct callees of %s (share of its cumtime)\n' % label(k))
        for callee, (nc, ct) in sorted(callees.get(k, {}).items(), key=lambda it: it[1][1], reverse=True)[:6]:
            w('    %7d calls %9.3f s  %5.1f%%  %s\n' % (nc, ct, 100 * ct / S[k][3] if S[k][3] else 0, label(callee)))
        res['vb_callees'] = {label(c): (nc, ct) for c, (nc, ct) in callees.get(k, {}).items()}
        res['vb_ct'] = S[k][3]

    # --- union of every per-call guard (REUSE + HEAT + HEATSRC), de-nested estimate
    members_all = {k for k in S if family(k) in ('REUSE', 'HEAT', 'HEATSRC')}
    members_rh = {k for k in S if family(k) in ('REUSE', 'HEAT')}
    u_all = union_total(S, edges, members_all, cap_callers) if members_all else (0.0, 0)
    u_rh = union_total(S, edges, members_rh, cap_callers) if members_rh else (0.0, 0)
    res['UNION'] = dict(ct=u_all[0], nc=u_all[1])
    w('\n[UNION REUSE+HEAT+HEATSRC, de-nested estimate, capture excluded] %.3f s = %.2f%% of total own time '
      '(%.2f%% of non-waiting) (calls ~%.0f)\n'
      % (u_all[0], 100 * u_all[0] / total if total else 0,
         100 * u_all[0] / (total - blocking) if total - blocking > 0 else 0, u_all[1]))

    # --- heat issuer: what _verify_call_record spends time on, and a source-identity vs data-hash split
    for k in S:
        if family(k) == 'HEAT' and k[2] == '_verify_call_record':
            w('\n[HEAT breakdown] direct callees of %s (cumtime within this function)\n' % label(k))
            for callee, (nc, ct) in sorted(callees.get(k, {}).items(), key=lambda it: it[1][1], reverse=True)[:10]:
                w('    %7d calls %9.3f s  %5.1f%% of verify_call_record  %s\n'
                  % (nc, ct, 100 * ct / S[k][3] if S[k][3] else 0, label(callee)))
    heat_outer = res['HEAT']['o_ct']
    if heat_outer > 0:
        reuse_outside = max(0.0, u_rh[0] - heat_outer)
        reuse_nested = max(0.0, res['REUSE']['o_ct'] - reuse_outside)
        impl = sum(S[k][3] for k in S if family(k) == 'HEAT' and k[2] == '_verify_implementation')
        srcfiles = 0.0
        for k in S:
            if family(k) == 'HEAT' and k[2] == '_verify_call_record':
                for callee, (nc, ct) in callees.get(k, {}).items():
                    if callee[2] in ('source_hash', 'read_bytes'):
                        srcfiles += ct
        src_part = reuse_nested + impl + srcfiles
        res['HEAT_SPLIT'] = dict(reuse_nested=reuse_nested, impl=impl, srcfiles=srcfiles, src=src_part,
                                 data=max(0.0, heat_outer - src_part), outer=heat_outer)
        w('\n[HEAT split, approximate] of %.3f s heat-issuer guard: source-identity part = %.3f s '
          '(ExecutionContext.verify nested %.3f + _verify_implementation %.3f + source file hashes %.3f) = %.0f%%; '
          'rest (snapshot/mesh/origin data hashing, owner checks) = %.3f s\n'
          % (heat_outer, src_part, reuse_nested, impl, srcfiles, 100 * src_part / heat_outer,
             max(0.0, heat_outer - src_part)))
    # --- any other verif-named functions anywhere (catches guards outside the three file classes)
    anyv = sorted((k for k in S if re.search(r'verif', k[2]) and not guard_named(k) and not wrapper(k)),
                  key=lambda k: S[k][3], reverse=True)[:8]
    if anyv:
        w('\n[other verif-named functions in any file, top by cumtime]\n')
        for k in anyv:
            w('    %7d calls %9.3f s  %s\n' % (S[k][1], S[k][3], label(k)))
    w('\n')
    return res


def main(argv):
    outpath = argv[1]
    extras = add_extra_profiles()
    results = []
    FAMS = ('REUSE', 'HEAT', 'HEATSRC', 'CAPTURE')
    with open(outpath, 'w', encoding='utf-8', newline='\n') as out:
        out.write('S7 guard scan (read-only), generated %s\n' % time.strftime('%Y-%m-%d %H:%M:%S'))
        out.write('Extra 16 Oct profiles found under T/hs and T/ps (not in the named list): %s\n\n'
                  % (', '.join(norm(e) for e in extras) or 'none'))
        for stage, name, path in PROFILES:
            if not os.path.isfile(path):
                out.write('MISSING: %s %s\n\n' % (stage, norm(path)))
                continue
            results.append(analyse(stage, name, path, out))

        # worker sum
        workers = [r for r in results if r['stage'].startswith('Heat workers')]
        if workers:
            out.write('=' * 118 + '\nHEAT WORKERS SUM over %d worker profiles\n' % len(workers))
            tt = sum(r['total'] for r in workers)
            bl = sum(r['blocking'] for r in workers)
            for fam in FAMS:
                o_nc = sum(r[fam]['o_nc'] for r in workers)
                o_ct = sum(r[fam]['o_ct'] for r in workers)
                out.write('  %-8s outermost %d calls, %.3f s = %.2f%% of summed own time %.3f s, %.2f ms/call\n'
                          % (fam, o_nc, o_ct, 100 * o_ct / tt if tt else 0, tt, 1000 * o_ct / o_nc if o_nc else 0))
            u = sum(r['UNION']['ct'] for r in workers)
            out.write('  UNION    %.3f s = %.2f%% of summed own time\n' % (u, 100 * u / tt if tt else 0))
            out.write('  summed blocking/wait tottime (heuristic) %.3f s\n\n' % bl)
            summed = dict(stage='Heat workers (W4 p4w)', name='SUM of %d workers' % len(workers), total=tt,
                          root=sum(r['root'] for r in workers), blocking=bl, reuse_path='',
                          UNION={k: sum(r['UNION'][k] for r in workers) for k in ('ct', 'nc')})
            for fam in FAMS:
                summed[fam] = {k: sum(r[fam][k] for r in workers) for k in workers[0][fam]}
            results.append(summed)

        # summary table
        out.write('=' * 118 + '\nSUMMARY (outermost entries, de-nested; share = cumtime / total own time of the profile;\n'
                  'REUSE calls exclude the one verify_boundary inside each context capture, shown under capt)\n')
        out.write('%-27s %-30s %9s %7s | %7s %9s %7s %8s | %5s %9s %7s %8s | %5s %9s %7s | %9s %7s %7s | %5s %9s %9s\n' % (
            'stage', 'profile', 'own s', 'wait%',
            'REUSEn', 'cum s', 'share', 'ms/call',
            'HEATn', 'cum s', 'share', 'ms/call',
            'SRCn', 'cum s', 'share', 'union s', 'share', 'u/busy', 'capn', 'capt s', 'capt+vb s'))
        for r in results:
            t = r['total']

            def f(fam):
                d = r[fam]
                return (d['o_nc'], d['o_ct'], 100 * d['o_ct'] / t if t else 0,
                        1000 * d['o_ct'] / d['o_nc'] if d['o_nc'] else 0)
            a, b, c = f('REUSE'), f('HEAT'), f('HEATSRC')
            u = r['UNION']['ct']
            busy = t - r['blocking']
            out.write('%-27s %-30s %9.2f %6.1f%% | %7d %9.3f %6.2f%% %8.2f | %5d %9.3f %6.2f%% %8.2f | %5d %9.3f %6.2f%% '
                      '| %9.3f %6.2f%% %6.2f%% | %5d %9.3f %9.3f\n' % (
                          r['stage'][:27], r['name'][:30], t, 100 * r['blocking'] / t if t else 0,
                          a[0], a[1], a[2], a[3], b[0], b[1], b[2], b[3], c[0], c[1], c[2],
                          u, 100 * u / t if t else 0, 100 * u / busy if busy > 0 else 0,
                          r['CAPTURE']['o_nc'], r['CAPTURE']['o_ct'], r['REUSE']['cap_ct']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
