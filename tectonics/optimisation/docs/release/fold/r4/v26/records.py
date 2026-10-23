"""Records check for one fold run (v25; R2 decisions 3-5): B's hash journal derived from A's, constructively, fail closed.

    python -B records.py check A_LAYOUT A_OBS B_LAYOUT B_OBS OVERLAY OUT_JSON
    python -B records.py noise A_OBS A2_OBS
    python -B records.py replay-child PACKAGE_PARENT KIND MODULE INPUT OUT_JSON      (run by check, see below)

check translates every entry of A's journal into B's terms and requires the derived digest to be a B journal digest.
Nothing is matched by value against B; the translation is built from
  seeds    the fold manifest the overlay pins (file shas, f5 re-pins, A paths -> package keys), a code table and string
           pairs from compiling both arms' changed modules, and the identity member's records (F4 inventories). Each
           sha_map row is re-derived from the files (A's loaded file or a checked f5 spelling -> B's package file), and
           the fold's own manifest, pinned by B's arm record, must agree with it; each string pair must be the fold's
           declared rewrite of the A string (paths -> keys, digests -> their seeds, bare helper names -> package
           names). Self IDs, and external IDs or bookings declared outside the overlay, fail;
  rules    the overlay's declared records rules, applied to A's parsed value before it is hashed:
             sort        a list kept in ID order is re-sorted by the translated IDs. The order (pi) comes from the IDs
                         only: A's list must be strictly sorted, the translated IDs distinct, every ID a journalled A
                         digest whose image is a B digest;
             items       per-item lists follow a sort list of the same entry, or the cell order of the records that
                         consume the entry;
             face_rows   [cell, neighbour or null, [num, den]] rows renumbered by the cell order; a pair is stored
                         lower cell first, so a swapped pair negates its numerator; rows follow the entry's face IDs;
             ordered_by  per-item lists in the order of a referenced record's sorted list;
             cell_words  per-cell fixed-width words in the consuming records' cell order;
           where several consuming records give different orders, the rule holds only if every order gives the same
           result;
  replay   re-encode sites (decision 4a): the folded producer runs on A's input entry and on B's and must reproduce
           each arm's journal at every declared producer site exactly; outputs used outside the producer pair by
           role; the producer's other unmapped outputs must sit at a declared internal qual (or the token site) and
           must not be consumed outside it;
  token    record_tables keys a token exactly when its encoding is within EXACT_KEY_BYTES, so an A token hashed only
           because its absolute path was long must translate to within the bound.
Then: no A entry outside a producer is unmapped, every declared rule was used, D(A record) == B record, arrays pair by
name, declared bookings are equal, external IDs are journalled, private sources A == B, and B's record names no
absolute path. Rounds run in journal order to a fixpoint (at most max_rounds).

noise compares two runs of one arm (A and A'): canonical record equality and equal journal digest sets.

The replay child runs `python -s -P -B` with a minimal environment (PYTHONHASHSEED=0 and system variables only), the
folded package parent first on sys.path; the producer module's sha256 is replaced by a recorder that logs (caller
qualname, digest, length). Exit 0 = PASS; otherwise one FAIL JSON line {status, stage, reason, detail}. Roots come from
the arguments and the arms' arm.json only.

r3 (v26, 23 Oct; fold_r5 data keys): a key_map path that is not a drive or UNC path is a task key, which arm A's
helpers find as task_file does: the one ancestor of A's helpers folder (itself included) holding it. It may only name a
data file the fold carries unchanged (sha_map old = new, not a .py key), must be a plain relative path (no '..', no
backslash, no leading '/'), and is never read relative to the working directory. Everything else is v25's.
"""
import ast
import difflib
import hashlib
import json
import marshal
import os
import re
import subprocess
import sys
import time
import types
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

HEX = re.compile(r'^(sha256:)?([0-9a-f]{64})$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
HEXS = re.compile(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])')
ABS = re.compile(r'^([A-Za-z]:[\\/]|\\\\)')     # r3: a drive or UNC path, as parity's _is_abs
INT = re.compile(r'^(0|-?[1-9][0-9]*)$')
LEAK = re.compile(r'(?<![A-Za-z])[A-Za-z]:[\\/]|^\\\\|[\\/]Users[\\/]')
OVERLAY_SCHEMA = 'rm.fold.records-overlay.r1'
REPORT_SCHEMA = 'rm.fold.records-check.r1'
PRIVATE = 'atlas_tectonics._private.'
CHILD_ENV = ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP')


class Fail(Exception):
    def __init__(self, stage, reason, detail=None):
        super().__init__(stage, reason, detail)
        self.stage, self.reason, self.detail = stage, reason, detail


class RuleFail(Exception):
    pass


def sha(raw):
    return sha256(raw).hexdigest()


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def parse(pre):
    """The value of a canonical JSON preimage, else None."""
    try:
        v = json.loads(pre)
    except Exception:
        return None
    return v if canon(v) == pre else None


def load_json(path):
    return json.loads(Path(path).read_bytes())


def leaves(v, path=()):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from leaves(x, path + (k,))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from leaves(x, path + (i,))
    else:
        yield path, v


def strings(v):
    """Every dict key and string value."""
    if isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)
    elif isinstance(v, str):
        yield v


def dict_keys(v):
    if isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from dict_keys(x)
    elif isinstance(v, list):
        for x in v:
            yield from dict_keys(x)


def matches(pattern, path):
    return len(pattern) == len(path) and all(p == '*' or p == q for p, q in zip(pattern, path, strict=True))


def get(v, path):
    for k in path:
        if isinstance(v, dict) and k in v:
            v = v[k]
        elif isinstance(v, list) and type(k) is int and 0 <= k < len(v):
            v = v[k]
        else:
            return None
    return v


def load_arm(obs, name):
    """One arm's observer output, checked: journal intact, every entry's preimage hashes to its digest, the record and
    arrays are journal entries."""
    arm = load_json(obs/'arm.json')
    if arm.get('status') != 'PASS' or arm.get('problems') or arm.get('leaks'):
        raise Fail('integrity', 'arm did not pass', [name, arm.get('status')])
    idx = load_json(obs/'journal.json')
    raw = (obs/'journal.bin').read_bytes()
    if sha(raw) != idx.get('journal_sha256'):
        raise Fail('integrity', 'journal.bin sha256 differs from journal.json', name)
    if idx.get('over_journal_cap') or idx.get('over_stream_cap'):
        raise Fail('integrity', 'journal over cap', name)
    entries, seen = [], set()
    for dg, ln, off, _count, sites in idx['entries']:
        if off is None:
            raise Fail('integrity', 'entry without a preimage', [name, dg])
        pre = raw[off:off + ln]
        if len(pre) != ln or sha(pre) != dg:
            raise Fail('integrity', 'preimage does not hash to its digest', [name, dg])
        if dg in seen:
            raise Fail('integrity', 'digest journalled twice', [name, dg])
        seen.add(dg)
        entries.append((dg, pre, tuple(sites)))
    meta = (obs/'metadata.json').read_bytes()
    if sha(meta) != arm.get('metadata_sha256') or sha(meta) not in seen:
        raise Fail('integrity', 'metadata.json is not the journalled record', name)
    for k, d in (arm.get('arrays') or {}).items():
        if d not in seen:
            raise Fail('integrity', 'array digest not journalled', [name, k])
    return arm, entries, json.loads(meta)


def codes(code):
    yield code
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            yield from codes(c)


def normal(code):
    return code.replace(co_filename='<atlas>', co_consts=tuple(
        normal(c) if isinstance(c, types.CodeType) else c for c in code.co_consts))


def code_digest(c):
    return sha(marshal.dumps(normal(c), 2))


def by_qualname(cs):
    seen, out = Counter(), {}
    for c in cs:
        out[(c.co_qualname, seen[c.co_qualname])] = c
        seen[c.co_qualname] += 1
    return out


def flat_strs(consts):
    for c in consts:
        if type(c) is str:
            yield c
        elif isinstance(c, frozenset):
            yield from flat_strs(sorted((x for x in c if type(x) is str)) + [x for x in c if type(x) is not str])
        elif isinstance(c, tuple):
            yield from flat_strs(c)


def a_module(orig):
    if orig.startswith('helpers/'):
        return Path(orig).stem
    name = orig[len('src/'):-len('.py')].replace('/', '.')
    return name[:-len('.__init__')] if name.endswith('.__init__') else name


def literal_defaults(fn):
    args = fn.args
    pos = None if not args.defaults else [ast.literal_eval(x) for x in args.defaults]
    kw = {a.arg: ast.literal_eval(d) for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True)
          if d is not None} or None
    return [pos, kw]


def module_int(path, name):
    for node in ast.parse(path.read_bytes()).body:
        if isinstance(node, ast.Assign) and [getattr(x, 'id', None) for x in node.targets] == [name]:
            v = ast.literal_eval(node.value)
            if type(v) is int:
                return v
    raise Fail('manifest', 'no int %s in the folded module' % name, str(path.name))


def negate(num):
    return num[1:] if num.startswith('-') else ('0' if num == '0' else '-' + num)


def permuted(xs, perm):
    if len(xs) != len(perm):
        raise RuleFail('list of %d items under an order of %d' % (len(xs), len(perm)))
    out: list[Any] = [None] * len(xs)
    for k, x in enumerate(xs):
        out[perm[k]] = x
    return out


def keyed(xs, key):
    """Whether a list at a sort path is the declared ID list: every item an ID (a digest string, or a dict holding
    `key`). One site hashes several record shapes, so a list of other items (cell counts, say) is a different list and
    the rule does not apply; its entry then translates unsorted and stays unmapped if the order mattered. A list that
    mixes the two fails."""
    if not isinstance(xs, list):
        return False
    hits = [isinstance(x, str) and HEX64.match(x) is not None if key is None else isinstance(x, dict) and key in x
            for x in xs]
    if any(hits) and not all(hits):
        raise RuleFail('list mixes IDs and other items')
    return all(hits)


def walk(v, t, path, at=()):
    """(A value, translated value, concrete path) for each match of a rule path; '*' is any dict key or list index.
    Translation keeps dict order, so the translated container is found by position. Rules act on matched lists only:
    one site hashes several record shapes, and a per-item list in one is a digest reference in another."""
    if not path:
        if isinstance(v, list) and (not isinstance(t, list) or len(v) != len(t)):
            raise RuleFail('%r translated to a different shape' % (list(at)[:6],))
        yield v, t, at
        return
    k, rest = path[0], path[1:]
    if isinstance(v, dict):
        if not isinstance(t, dict) or len(t) < len(v):
            raise RuleFail('translated keys collide at %r' % (list(at)[:6],))
        tk = list(t)
        if k == '*':
            for n, (ka, x) in enumerate(v.items()):
                yield from walk(x, t[tk[n]], rest, at + (ka,))
        elif k in v:
            yield from walk(v[k], t[tk[list(v).index(k)]], rest, at + (k,))
    elif isinstance(v, list) and k == '*':
        for n, x in enumerate(v):
            yield from walk(x, t[n], rest, at + (n,))


class Check:
    def __init__(self, a_layout, a_obs, b_layout, b_obs, overlay):
        self.a_layout, self.a_obs, self.b_layout, self.b_obs, self.overlay = a_layout, a_obs, b_layout, b_obs, overlay
        self.stats, self.t0 = {}, time.perf_counter()

    def lap(self, name):
        self.stats.setdefault('seconds', {})[name] = round(time.perf_counter() - self.t0, 1)

    # ------------------------------------------------------------ inputs
    def load(self):
        ov = load_json(self.overlay)
        if ov.get('schema') != OVERLAY_SCHEMA:
            raise Fail('manifest', 'overlay schema', ov.get('schema'))
        base_raw = (self.b_layout/ov['base_manifest']).read_bytes()
        if sha(base_raw) != ov['base_sha256']:
            raise Fail('manifest', 'fold manifest differs from the overlay pin', ov['base_manifest'])
        self.ov, self.man = ov, json.loads(base_raw)
        for name, src in (('overlay', ov), ('fold manifest', self.man)):
            if src.get('self_ids'):
                raise Fail('manifest', '%s declares self IDs; no rule reads them' % name)
        for k in ('external', 'bookings'):
            if self.man.get(k):
                raise Fail('manifest', 'fold manifest declares %s; only the overlay is read' % k)
        rr = ov.get('records_rules') or {}
        self.rules = rr.get('rules', [])
        self.replays = rr.get('replay', [])
        self.token = rr.get('token')
        self.max_rounds = rr.get('max_rounds', 50)
        if len({r['id'] for r in self.rules}) != len(self.rules):
            raise Fail('manifest', 'rule ids repeat')
        self.composed = Path(load_json(self.a_layout/'arm.json')['composed_root'])
        self.b_root = Path(load_json(self.b_layout/'arm.json')['package_parent'])
        self.arm_a, self.JA, self.rec_a = load_arm(self.a_obs, 'A')
        self.arm_b, self.JB, self.rec_b = load_arm(self.b_obs, 'B')
        self.INDEX = {d: i for i, (d, _, _) in enumerate(self.JA)}
        self.INDEX_B = {d: i for i, (d, _, _) in enumerate(self.JB)}
        self.Aset, self.Bset = set(self.INDEX), set(self.INDEX_B)
        self.stats['entries'] = dict(A=len(self.JA), B=len(self.JB))
        self.lap('load')

    def records_static(self):
        """The two records alone: external IDs, bookings, private sources, B's record free of absolute paths."""
        ext = self.ov.get('external', [])
        for name, rec, jset in (('A', self.rec_a, self.Aset), ('B', self.rec_b, self.Bset)):
            hex_keys = [k for k in dict_keys(rec) if isinstance(k, str) and HEX.match(k)]
            if hex_keys:
                raise Fail('external', 'hex dict key in a record', [name, hex_keys[0][:16], len(hex_keys)])
            used = Counter()
            for path, v in leaves(rec):
                m = HEX.match(v) if isinstance(v, str) else None
                if m is None:
                    continue
                hits = [k for k, e in enumerate(ext) if matches(e['path'], path)]
                if len(hits) != 1:
                    raise Fail('external', 'hex leaf matches %d declared patterns' % len(hits), [name, list(path)[:8]])
                if ext[hits[0]].get('preimage') != 'journal' or m.group(2) not in jset:
                    raise Fail('external', 'external ID not journalled', [name, list(path)[:8]])
                used[hits[0]] += 1
            unused = [ext[k]['path'] for k in range(len(ext)) if not used[k]]
            if unused:
                raise Fail('external', 'declared external pattern unused', [name, unused[:4]])
            self.stats.setdefault('external_leaves', {})[name] = sum(used.values())
        for b in self.ov.get('bookings', []):
            xa, xb = get(self.rec_a, b['path']), get(self.rec_b, b['path'])
            if b.get('rule') != 'equal':
                raise Fail('manifest', 'unknown booking rule', b.get('rule'))
            if type(xa) is not int or type(xb) is not int or xa < 0 or xb < 0:
                raise Fail('bookings', 'booking is not a non-negative int', [b['path'], xa, xb])
            if xa != xb:
                raise Fail('bookings', 'booking differs', [b['path'], xa, xb])
        self.stats['bookings'] = len(self.ov.get('bookings', []))
        sp = self.ov.get('private_sources_path')
        if sp:
            pa, pb = get(self.rec_a, sp), get(self.rec_b, sp)
            if not isinstance(pa, dict) or not isinstance(pb, dict) or len(pa) != len(pb):
                raise Fail('records', 'private sources differ in number',
                           [len(pa) if isinstance(pa, dict) else None, len(pb) if isinstance(pb, dict) else None])
            self.stats['private_sources'] = len(pa)
        bad = [s for s in strings(self.rec_b) if LEAK.search(s)]
        if bad:
            raise Fail('leak', 'B record names an absolute path', len(bad))
        self.lap('records')

    # ------------------------------------------------------------ seeds
    def a_file(self, orig):
        if orig.startswith('helpers/'):
            return self.a_layout/'helpers'/orig[len('helpers/'):]
        return self.composed/orig

    def seeds(self):
        man = self.man
        D = self.D = {}
        key_map = dict(man['key_map'])
        pm = {a_copy: key_map.get(comp, comp) for a_copy, comp in man['a_layout'].items()}
        for old, new in key_map.items():
            pm.setdefault(old, new)
        for key, row in man.get('f5_repins', {}).items():
            pm.update({p: key for p in row['spellings']})
        self.path_map = pm
        self.helpers = {Path(old).stem: new[:-3].replace('/', '.') for old, new in man['modules'].items()
                        if new.startswith('atlas_tectonics/_private/') and new.endswith('.py')}
        self.b_prefix = str(self.b_root) + '\\'
        for key, old, new in self.file_rows():
            if D.setdefault(old, new) != new:
                raise Fail('seeds', 'sha_map conflict', key)
        for key, row in man.get('f5_repins', {}).items():
            for s in row['spellings'].values():
                if D.setdefault(s, row['new']) != row['new']:
                    raise Fail('seeds', 'f5 re-pin conflict', key)
        self.SIZE = {}
        code, pairs, own = {}, defaultdict(set), defaultdict(lambda: defaultdict(set))
        changed = 0
        for orig, new in sorted(man['modules'].items()):
            fa, fb = self.a_file(orig), self.b_root/new
            ra, rb = fa.read_bytes(), fb.read_bytes()
            self.SIZE.setdefault(sha(ra), len(rb))
            if ra == rb:
                continue
            changed += 1
            if D.get(sha(ra)) != sha(rb):
                raise Fail('seeds', 'changed file pair not in sha_map', orig)
            qa = by_qualname(codes(compile(ra, str(fa), 'exec', dont_inherit=True)))
            qb = by_qualname(codes(compile(rb, str(fb), 'exec', dont_inherit=True)))
            if set(qa) != set(qb):
                raise Fail('seeds', 'code objects differ in shape', [orig, sorted(set(qa) ^ set(qb))[:4]])
            for q in qa:
                x, y = qa[q], qb[q]
                dx, dy = code_digest(x), code_digest(y)
                if code.setdefault(dx, dy) != dy:
                    raise Fail('seeds', 'code table conflict', [orig, q[0]])
                sx = [c for c in x.co_consts if type(c) is str]
                sy = [c for c in y.co_consts if type(c) is str]
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sx, sy, autojunk=False).get_opcodes():
                    if tag == 'replace' and i2 - i1 == j2 - j1:
                        for s1, s2 in zip(sx[i1:i2], sy[j1:j2], strict=True):
                            pairs[s1].add(s2)
                    elif tag != 'equal':
                        raise Fail('seeds', 'unpaired string constants', [orig, q[0], tag])
                fx, fy = list(flat_strs(x.co_consts)), list(flat_strs(y.co_consts))
                for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, fx, fy, autojunk=False).get_opcodes():
                    if tag in ('equal', 'replace') and i2 - i1 == j2 - j1:
                        for s1, s2 in zip(fx[i1:i2], fy[j1:j2], strict=True):
                            own[a_module(orig)][s1].add(s2)
        ambiguous = sorted(k for k, v in pairs.items() if len(v) > 1)
        if ambiguous:
            raise Fail('seeds', 'ambiguous string pairs', ambiguous[:4])
        self.STRMAP = {k: next(iter(v)) for k, v in pairs.items()}
        self.STRMOD = own
        for a, b in code.items():
            if D.setdefault(a, b) != b:
                raise Fail('seeds', 'code digest conflicts with a file seed', a)
        self.declared_pairs()
        self.SEEDED = set(D)
        self.stats['seeds'] = dict(changed_modules=changed, code_pairs=len(code),
                                   code_changed=sum(a != b for a, b in code.items()), string_pairs=len(self.STRMAP),
                                   seeded=len(self.SEEDED))
        self.identity()
        self.lap('seeds')

    def file_rows(self):
        """Each sha_map row re-derived from files: a manifest row is a claim, not evidence (refuter r1, P0-B).
        MANIFEST-h's rows: new is B's package file; old is the file A loads, a checked f5 spelling, or new itself for a
        file the fold adds. The fold's own manifest, pinned by B's arm record, must equal MANIFEST-h apart from a_layout
        and the rows of files the harness patched; its rows are checked against the fold output and the original
        sources. A patched file (B's package differs from the fold output) must be patched in A too, and also seeds its
        fold row: the pins the fold rewrote name the unpatched files. key_map and a_layout paths are checked as well,
        since they seed the path translation."""
        man, barm = self.man, load_json(self.b_layout/'arm.json')
        if not barm.get('fold_out') or not barm.get('manifest_sha256'):
            raise Fail('seeds', 'B arm record names no fold output')
        fold = Path(barm['fold_out'])
        fraw = (fold/'MANIFEST.json').read_bytes()
        if sha(fraw) != barm['manifest_sha256']:
            raise Fail('seeds', "fold manifest differs from B's arm pin")
        fman = json.loads(fraw)

        def rest(m):
            return {k: x for k, x in m.items() if k not in ('a_layout', 'sha_map')}
        if 'a_layout' in fman or rest(man) != rest(fman) or set(man['sha_map']) != set(fman['sha_map']):
            raise Fail('seeds', 'MANIFEST-h is not the fold manifest plus the harness rows')
        digests = {}

        def h(p):
            p = Path(p)
            if p not in digests:
                digests[p] = sha(p.read_bytes()) if p.is_file() else None
            return digests[p]
        loads, originals, f5 = defaultdict(set), defaultdict(set), defaultdict(set)
        for orig, key in man['modules'].items():
            loads[key].add(self.a_file(orig))
        for path, key in man['key_map'].items():
            if not ABS.match(path):
                originals[key].add(self.task_key(path, key))    # r3: a data key, found as A's task_file finds it
                continue
            if key not in man['sha_map']:
                if not (Path(path).is_dir() and (self.b_root/key).is_dir()):
                    raise Fail('seeds', 'key_map names a key with no sha_map row', key)
                continue
            originals[key].add(Path(path))
        for key, paths in originals.items():
            if key not in loads:
                loads[key] |= paths         # a data file (the native DLL): A loads it where key_map names it
        for a_copy, comp in man['a_layout'].items():
            key = man['key_map'].get(comp)
            if key is None or Path(a_copy) not in loads[key]:
                raise Fail('seeds', "a_layout pairs an A copy with another file's original", Path(a_copy).name)
        for key, row in man.get('f5_repins', {}).items():
            for p, d in row['spellings'].items():
                if h(p) != d or self.path_map.get(p) != key:
                    raise Fail('seeds', 'f5 spelling is not its file', [key, d[:16]])
                f5[key].add(d)
            if row['new'] != man['sha_map'].get(key, [None, None])[1]:
                raise Fail('seeds', 'f5 re-pin is not the B file', key)
        out = []
        for key in sorted(man['sha_map']):
            (old, new), (fo, fn) = man['sha_map'][key], fman['sha_map'][key]
            la, oa = {h(p) for p in loads[key]}, {h(p) for p in originals[key]}
            if h(self.b_root/key) != new:
                raise Fail('seeds', 'sha_map row: new is not the B package file', key)
            if None in la or la - {old} - f5[key] or not (old in la | f5[key] or (not la and old == new)):
                raise Fail('seeds', 'sha_map row: old is not the file A loads', key)
            if h(fold/'folded'/key) != fn:
                raise Fail('seeds', 'fold row: new is not the fold output file', key)
            if None in oa or oa - {fo} - f5[key] or not (fo in oa | f5[key] or (not oa and fo == fn)):
                raise Fail('seeds', 'fold row: old is not the original source', key)
            out.append((key, old, new))
            if new == fn:
                if (old, new) != (fo, fn):
                    raise Fail('seeds', 'rows differ on a file the harness did not patch', key)
            elif la == oa:
                raise Fail('seeds', 'B package differs from the fold output on a file A runs unpatched', key)
            else:
                out.append((key, fo, fn))
                self.stats.setdefault('harness_patched', []).append(key)
        self.stats['file_rows'] = len(out)
        return out

    def task_key(self, path, key):
        """r3: the file a relative key_map path names for arm A: the one ancestor of A's helpers folder (itself
        included) that holds it, as the original task_file finds it. Only a carried data file may be named so."""
        row = self.man['sha_map'].get(key)
        parts = Path(path).parts
        if row is None or row[0] != row[1] or key.endswith('.py') or not parts or '..' in parts or '\\' in path \
                or path.startswith('/') or Path(path).is_absolute():
            raise Fail('seeds', 'relative key_map path is not a carried data file key', [path[:80], key])
        start = (self.a_layout/'helpers').resolve()
        found = [parent/path for parent in (start, *start.parents) if (parent/path).is_file()]
        if len(found) != 1:
            raise Fail('seeds', "a data key is not under exactly one ancestor of A's helpers", [path[:80], len(found)])
        self.stats.setdefault('task_keys', {})[path] = key
        return found[0]

    def declared_pairs(self):
        """A string constant a changed module pairs with another must be the fold's declared rewrite of it (refuter r1,
        P0-A): absolute paths to package keys, then digests through the file-derived seeds, then bare helper module
        names to their package names (not a file name). Anything else, such as 'K' -> 'C', fails."""
        pm = self.path_map
        path_re = re.compile('|'.join(sorted(map(re.escape, pm), key=len, reverse=True)))
        qual_re = re.compile(r'(?<![\w.])(' + '|'.join(sorted(map(re.escape, self.helpers), key=len, reverse=True))
                             + r')(?!\w|\.py\b)')

        def rewrite(s):
            s = path_re.sub(lambda m: pm[m.group(0)], s)
            s = HEXS.sub(lambda m: self.D.get(m.group(0), m.group(0)), s)
            return qual_re.sub(lambda m: self.helpers[m.group(1)], s)
        n = 0
        for where, table in [('', list(self.STRMAP.items()))] + [(m, [(s, t) for s, ts in own.items() for t in ts])
                                                                for m, own in self.STRMOD.items()]:
            for s, t in table:
                if s != t:
                    n += 1
                    if rewrite(s) != t:
                        raise Fail('seeds', 'string pair is not a declared fold rewrite', [where, s[:80], t[:80]])
        self.stats['declared_pairs'] = n

    def identity(self):
        """The identity member the fold adds: its inventory record, function digests and literal constants (F4)."""
        idn = self.ov.get('identity')
        self.F4, self.ID_DIGESTS = None, set()
        if not idn:
            return
        raw = (self.b_root/idn['key']).read_bytes()
        self.F4, self.ID_NAME = idn['f4_schema'], Path(idn['key']).name
        self.ID_RECORD = b'{"bytes":' + str(len(raw)).encode() + b',"sha256":"' + sha(raw).encode() + b'"}'
        dotted = idn['key'][:-len('.py')].replace('/', '.') + '.'
        tree = ast.parse(raw)
        code = by_qualname(codes(compile(raw, str(self.b_root/idn['key']), 'exec', dont_inherit=True)))
        self.ID_DIGESTS = {sha(raw), sha(self.ID_RECORD)} | {code_digest(c) for c in code.values()}
        self.ID_FUNCTIONS, self.ID_CONSTANTS = {}, {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self.ID_FUNCTIONS[dotted + node.name] = dict(code=code_digest(code[(node.name, 0)]),
                                                             defaults=sha(canon(literal_defaults(node))))
            elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and node.targets[0].id.isupper():
                try:
                    self.ID_CONSTANTS[dotted + node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:
                    pass    # a computed value: reuse binds only captured types, and B shows whether it bound it

    # ------------------------------------------------------------ translation
    def qualify_key(self, k):
        if k in self.helpers:
            return self.helpers[k]
        head, dot, rest = k.partition('.')
        if dot and head in self.helpers and rest != 'py':
            return self.helpers[head] + '.' + rest
        return k

    def site_b(self, site):
        head, _, rest = site.partition(':')
        return self.qualify_key(head) + ':' + rest

    def tr_str(self, v):
        if v in self.path_map:
            return self.path_map[v]
        m = HEX.match(v)
        if m:
            return (m.group(1) or '') + self.D.get(m.group(2), m.group(2))
        if v[:1] in ('{', '[') and v.isascii():
            inner = parse(v.encode('ascii'))
            if inner is not None:
                return canon(self.tr(inner)).decode()
        if self.CTX:
            own = self.CTX[-1].get(v)
            if own is not None and len(own) == 1:
                return next(iter(own))
        return self.STRMAP.get(v, v)

    def constant_module(self, k):
        """A captured constant's key 'module.NAME' (or 'module.Class.NAME') -> that module's own string pairs."""
        if not isinstance(k, str):
            return None
        for head in (k.rsplit('.', 1)[0], k.rsplit('.', 2)[0]):
            if head in self.STRMOD:
                return self.STRMOD[head]
        return None

    def is_inventory(self, v):
        """reuse's package inventory: relative *.py names -> records (as digests or canonical strings)."""
        return (self.F4 is not None and '__init__.py' in v and 'reuse.py' in v
                and all(isinstance(k, str) and k.endswith('.py') for k in v)
                and all(isinstance(x, str) for x in v.values()))

    def tr(self, v) -> Any:
        if isinstance(v, dict):
            if set(v) == {'bytes', 'sha256'} and type(v['bytes']) is int and isinstance(v['sha256'], str):
                return self.size_record(v)
            out = {}
            for k, x in v.items():
                own = self.constant_module(k)
                if own is not None:
                    self.CTX.append(own)
                try:
                    nk = self.qualify_key(self.tr_str(k))
                    if nk in out:
                        raise RuleFail('two A keys translate to one B key')
                    out[nk] = self.tr(x)
                finally:
                    if own is not None:
                        self.CTX.pop()
            if self.is_inventory(v):
                if self.ID_NAME in v or self.ID_NAME in out:
                    raise RuleFail('A inventory already names the identity member')
                digests = all(HEX.match(x) for x in v.values())
                out[self.ID_NAME] = sha(self.ID_RECORD) if digests else self.ID_RECORD.decode()
            return out
        if isinstance(v, list):
            return [self.tr(x) for x in v]
        if isinstance(v, str):
            return self.tr_str(v)
        return v

    def size_record(self, v):
        """reuse's per-source record: a changed file's record takes the folded file's size."""
        old = v['sha256']
        if old in self.D and self.D[old] != old:
            if self.SIZE.get(old) is None:
                raise RuleFail('changed source record without a size')
            return dict(bytes=self.SIZE[old], sha256=self.D[old])
        return v

    def f4(self, v):
        t = self.tr(v)
        if not isinstance(t.get('sources'), dict) or t['sources'].get(self.ID_NAME) != sha(self.ID_RECORD):
            raise RuleFail('F4 sources not read as an inventory')
        if not isinstance(t.get('loaded_code'), dict):
            raise RuleFail('F4 record without loaded_code')
        if set(t['loaded_code']) & set(self.ID_FUNCTIONS):
            raise RuleFail('A loaded_code already names an identity function')
        t['loaded_code'].update(self.ID_FUNCTIONS)
        c = v.get('constants')
        j = self.INDEX.get(c)
        if j is None or self.KIND[j] != 'json':
            raise RuleFail('F4 constants not a journalled JSON entry')
        consts = self.tr(json.loads(self.JA[j][1]))
        if not isinstance(consts, dict) or set(consts) & set(self.ID_CONSTANTS):
            raise RuleFail('F4 constants not a dict without the identity constants')
        consts.update(self.ID_CONSTANTS)
        h = sha(canon(consts))
        new = self.NB.get(h, h)
        if self.D.get(c) != new:
            self.D[c] = new
            self.bumped += 1
        self.special.add(c)
        t['constants'] = new
        return t

    def norm_b(self, v):
        """B's absolute paths under its package parent read as package keys."""
        if isinstance(v, dict):
            out = {self.norm_b(k): self.norm_b(x) for k, x in v.items()}
            if len(out) != len(v):
                raise Fail('integrity', 'B keys collide once B paths read as keys')
            return out
        if isinstance(v, list):
            return [self.norm_b(x) for x in v]
        if isinstance(v, str) and v.startswith(self.b_prefix):
            return v[len(self.b_prefix):].replace('\\', '/')
        return v

    # ------------------------------------------------------------ index: kinds, references, consumers
    def index(self):
        self.CTX = []
        K = self.Aset | set(self.D)
        raws = sorted(bytes.fromhex(k) for k in K)
        self.KRAW = set(raws)
        self.PFX = np.unique(np.array([int.from_bytes(r[:8], 'little') for r in raws], dtype=np.uint64))
        self.KIND, self.REFS, self.POS, self.CONS = [], [], {}, defaultdict(list)
        f4 = set()
        for i, (d, pre, _sites) in enumerate(self.JA):
            v = parse(pre)
            if v is not None:
                kind, text = 'json', pre.decode('ascii')
                if self.F4 is not None and isinstance(v, dict) and v.get('schema') == self.F4:
                    f4.add(i)
            else:
                try:
                    kind, text = 'text', pre.decode('ascii')
                except UnicodeDecodeError:
                    kind, text = 'bin', pre.decode('latin-1')
            refs = set(HEXS.findall(text)) & K
            if kind == 'bin':
                pos = self.raw_hits(pre)
                if pos:
                    self.POS[i] = pos
                refs.update(h for _, h in pos)
            refs.discard(d)
            self.KIND.append(kind)
            self.REFS.append(tuple(sorted(refs)))
            for r in refs:
                self.CONS[r].append(i)
        self.NB, collide = {}, 0
        for d, pre, _sites in self.JB:
            v = parse(pre)
            h = sha(canon(self.norm_b(v)) if v is not None else pre)
            if self.NB.setdefault(h, d) != d:
                collide += 1
        if collide:
            raise Fail('integrity', 'B entries collide once B paths read as keys', collide)
        by_site = defaultdict(list)
        for r in self.rules:
            by_site[r['site']].append(r)
        self.by_site = by_site
        live = {r['site'] for r in self.rules if r['rule'] in ('face_rows', 'ordered_by', 'cell_words')
                or r.get('by') == 'consumers'}
        self.always = f4 | {i for i, (_, _, sites) in enumerate(self.JA) if live & set(sites)}
        self.stats['kinds'] = dict(Counter(self.KIND))
        self.stats['always'] = len(self.always)
        self.lap('index')

    def raw_hits(self, pre):
        """Positions of raw 32-byte A digests (or seeds) inside a binary preimage: 8-byte prefix window, then the
        whole digest; overlapping hits fail."""
        n = len(pre) - 31
        if n <= 0 or not len(self.PFX):
            return []
        arr = np.ndarray(shape=(n,), dtype='<u8', buffer=pre, strides=(1,))
        k = np.searchsorted(self.PFX, arr)
        k[k == len(self.PFX)] = 0
        hits, last = [], -32
        for p in np.nonzero(self.PFX[k] == arr)[0].tolist():
            w = pre[p:p + 32]
            if w in self.KRAW:
                if p < last + 32:
                    raise Fail('integrity', 'overlapping raw digests in a binary preimage', p)
                hits.append((p, w.hex()))
                last = p
        return hits

    # ------------------------------------------------------------ declared rules
    def rules_for(self, sites):
        """The entry's rules over all its sites. One rule declared at several sites (the same value hashed at each)
        applies once and counts as used under every id; two different rules on one list still fail."""
        out = {}
        for s in sites:
            for r in self.by_site.get(s, ()):
                body = canon({k: x for k, x in r.items() if k not in ('id', 'site', 'why')})
                if body in out:
                    out[body]['ids'].append(r['id'])
                else:
                    out[body] = dict(r, ids=[r['id']])
        return list(out.values())

    def sort_perm(self, lst, key):
        """pi from the keyed IDs only: A strictly sorted, the translated IDs distinct; A index -> B index."""
        ids = []
        for x in lst:
            v = x if key is None else (x.get(key) if isinstance(x, dict) else None)
            if not (isinstance(v, str) and HEX64.match(v)):
                raise RuleFail('sort ID is not a digest')
            ids.append(v)
        if any(a >= b for a, b in pairwise(ids)):
            raise RuleFail('A list not strictly sorted by its IDs')
        self.sort_ids.update(ids)
        new = [self.D.get(x, x) for x in ids]
        if len(set(new)) != len(new):
            raise RuleFail('pi not a bijection')
        perm = [0] * len(new)
        for rank, k in enumerate(sorted(range(len(new)), key=new.__getitem__)):
            perm[k] = rank
        return perm

    def cons_lists(self, j, paths):
        key = (j, tuple(tuple(p) for p in paths))
        if key not in self.cons_cache:
            lists = []
            if self.KIND[j] == 'json':
                v = json.loads(self.JA[j][1])
                for p in paths:
                    x = get(v, p)
                    if isinstance(x, list):
                        lists.append(x)
            self.cons_cache[key] = lists
        return self.cons_cache[key]

    def consumer_perms(self, i, paths):
        """The cell orders of the records that consume entry i (their declared cell-ID lists), distinct."""
        out = []
        for j in self.CONS.get(self.JA[i][0], ()):
            for lst in self.cons_lists(j, paths):
                p = tuple(self.sort_perm(lst, None))
                if p not in out:
                    out.append(p)
        return out

    def ref_perm(self, i, r):
        key = (i, r['id'])
        if key not in self.ref_cache:
            found = []
            for dg in self.REFS[i]:
                j = self.INDEX.get(dg)
                if j is None or r['ref_site'] not in self.JA[j][2] or self.KIND[j] != 'json':
                    continue
                lst = get(json.loads(self.JA[j][1]), r['ref_path'])
                if isinstance(lst, list):
                    found.append(lst)
            if len(found) != 1:
                raise RuleFail('%d referenced records at %s' % (len(found), r['ref_site']))
            self.ref_cache[key] = found[0]
        return self.sort_perm(self.ref_cache[key], r['ref_key'])

    def face_rows(self, vl, tl, cells, rows):
        n = len(cells)
        if len(vl) != len(rows):
            raise RuleFail('%d rows for %d face IDs' % (len(vl), len(rows)))
        out: list[Any] = [None] * len(vl)
        for k, (a, x) in enumerate(zip(vl, tl, strict=True)):
            if not (isinstance(a, list) and len(a) == 3 and type(a[0]) is int and 0 <= a[0] < n
                    and (a[1] is None or (type(a[1]) is int and a[0] < a[1] < n))
                    and isinstance(a[2], list) and len(a[2]) == 2 and all(isinstance(q, str) for q in a[2])
                    and INT.match(a[2][0])):
                raise RuleFail('row %d is not [cell, higher neighbour or null, [num, den]]' % k)
            c, m = cells[a[0]], None if a[1] is None else cells[a[1]]
            num, den = x[2]
            if m is not None and m < c:
                c, m, num = m, c, negate(num)
            out[rows[k]] = [c, m, [num, den]]
        return out

    def apply_rules(self, v, t, rules, used, i):
        claimed, perms = {}, {}

        def claim(r, at):
            if at in claimed:
                raise RuleFail('list %r matched by %s and %s' % (list(at)[:6], claimed[at], r['id']))
            claimed[at] = r['id']

        for r in rules:
            if r['rule'] != 'sort':
                continue
            try:
                for vl, tl, at in list(walk(v, t, r['path'])):
                    if not keyed(vl, r['key']):
                        continue
                    claim(r, at)
                    perm = self.sort_perm(vl, r['key'])
                    tl[:] = permuted(tl, perm)
                    perms[tuple(r['path'])] = perm
                    used.update(r['ids'])
            except RuleFail as e:
                raise RuleFail('%s: %s' % (r['id'], e)) from None
        for r in rules:
            kind = r['rule']
            if kind not in ('items', 'face_rows', 'ordered_by'):
                continue
            try:
                hits = [h for h in walk(v, t, r['path']) if isinstance(h[0], list)]
                if not hits:
                    continue
                if kind == 'ordered_by':
                    orders = [self.ref_perm(i, r)]
                elif r.get('by') == 'consumers' or r.get('cells') == 'consumers':
                    orders = self.consumer_perms(i, r['consumer_paths'])
                    if not orders:
                        raise RuleFail('no consuming record has cell IDs')
                else:
                    if tuple(r['by']) not in perms:
                        raise RuleFail('no sort list %r in the entry' % (r['by'],))
                    orders = [perms[tuple(r['by'])]]
                rows = None
                if kind == 'face_rows':
                    rows = perms.get(tuple(r['rows_by']))
                    if rows is None:
                        raise RuleFail('no sort list %r in the entry' % (r['rows_by'],))
                for vl, tl, at in hits:
                    claim(r, at)
                    outs = [self.face_rows(vl, tl, o, rows) if kind == 'face_rows' else permuted(tl, o)
                            for o in orders]
                    if any(x != outs[0] for x in outs[1:]):
                        raise RuleFail('consuming records disagree on the order')
                    tl[:] = outs[0]
                used.update(r['ids'])
            except RuleFail as e:
                raise RuleFail('%s: %s' % (r['id'], e)) from None

    def cell_words(self, i, r, out, used):
        orders = self.consumer_perms(i, r['consumer_paths'])
        if not orders:
            return out      # not a per-cell entry of any record
        w, outs = r['width'], []
        for o in orders:
            if len(out) != w * len(o):
                raise RuleFail('%s: %d bytes for %d cells' % (r['id'], len(out), len(o)))
            buf = bytearray(len(out))
            for k, p in enumerate(o):
                buf[p * w:(p + 1) * w] = out[k * w:(k + 1) * w]
            outs.append(bytes(buf))
        if any(x != outs[0] for x in outs[1:]):
            raise RuleFail('%s: consuming records disagree on the cell order' % r['id'])
        used.update(r['ids'])
        return outs[0]

    def translate(self, i, used):
        d, pre, sites = self.JA[i]
        rules = self.rules_for(sites)
        kind = self.KIND[i]
        if kind == 'json':
            v = json.loads(pre)
            if self.F4 is not None and isinstance(v, dict) and v.get('schema') == self.F4:
                return canon(self.f4(v))
            t = self.tr(v)
            if rules:
                self.apply_rules(v, t, rules, used, i)
            return canon(t)
        sub = lambda m: self.D.get(m.group(0), m.group(0))      # noqa: E731
        if kind == 'text':
            out = HEXS.sub(sub, pre.decode('ascii')).encode('ascii')
        else:
            buf = bytearray(pre)
            for p, old in self.POS.get(i, ()):
                new = self.D.get(old, old)
                if new != old:
                    buf[p:p + 32] = bytes.fromhex(new)
            out = HEXS.sub(sub, buf.decode('latin-1')).encode('latin-1')
        for r in rules:
            if r['rule'] == 'cell_words':
                out = self.cell_words(i, r, out, used)
        return out

    def rounds(self, phase):
        D = self.D
        for rnd in range(self.max_rounds):
            changed, self.bumped = 0, 0
            for i, (d, _pre, _sites) in enumerate(self.JA):
                if d in self.SEEDED or d in self.special or d in self.pinned:
                    continue
                sig = tuple(D.get(r) for r in self.REFS[i])
                if i not in self.always and self.sig.get(i) == sig:
                    continue
                used = set()
                try:
                    out = self.translate(i, used)
                except RuleFail as e:
                    self.errors[i] = str(e)
                    self.sig.pop(i, None)
                    if D.pop(d, None) is not None:
                        changed += 1
                    continue
                self.errors.pop(i, None)
                self.sig[i], self.tlen[i], self.used[i] = sig, len(out), used
                h = sha(out)
                new = self.NB.get(h, h)
                if D.get(d) != new:
                    D[d] = new
                    changed += 1
            changed += self.bumped
            self.stats.setdefault('rounds', []).append([phase, rnd, changed])
            if not changed:
                self.lap(phase)
                return
        raise Fail('derive', 'no fixpoint after %d rounds' % self.max_rounds, phase)

    # ------------------------------------------------------------ re-encode replay (decision 4a)
    def run_child(self, module, kind, pre, base):
        inp, out = base.with_suffix('.in'), base.with_suffix('.json')
        inp.write_bytes(pre)
        env = {k: os.environ[k] for k in CHILD_ENV if k in os.environ}
        env['PYTHONHASHSEED'] = '0'
        cmd = [sys.executable, '-s', '-P', '-B', str(Path(__file__).resolve()), 'replay-child', str(self.b_root),
               kind, module, str(inp), str(out)]
        done = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env,
                              cwd=str(base.parent), check=False)
        if done.returncode:
            raise Fail('replay', 'producer replay failed', [kind, done.stderr[-600:]])
        return load_json(out)

    def replay(self, r, work):
        mod, quals, kind = r['module'], r['quals'], r['kind']
        a_sites = {mod + ':' + q for q in quals}
        b_sites = {self.site_b(s) for s in a_sites}
        ins = [i for i, (_, pre, sites) in enumerate(self.JA)
               if r['input_site'] in sites and self.KIND[i] == 'json' and pre[:1] == b'{']
        if len(ins) != 1:
            raise Fail('replay', 'producer input entry not unique', [kind, len(ins)])
        ia = ins[0]
        da = self.JA[ia][0]
        db = self.D.get(da, da)
        jb = self.INDEX_B.get(db)
        if jb is None:
            raise Fail('replay', 'input translation is not a B digest', [kind, self.errors.get(ia)])
        if self.site_b(r['input_site']) not in self.JB[jb][2]:
            raise Fail('replay', 'B input not at the producer site', kind)
        module = self.helpers.get(mod, mod)
        res = dict(A=self.run_child(module, kind, self.JA[ia][1], work/(kind + '-a')),
                   B=self.run_child(module, kind, self.JB[jb][1], work/(kind + '-b')))
        per = {}
        for arm, J in (('A', self.JA), ('B', self.JB)):
            for q in quals:
                site = mod + ':' + q if arm == 'A' else self.site_b(mod + ':' + q)
                got = {dg for qq, dg, _n in res[arm]['log'] if qq == q}
                want = {dg for dg, _pre, sites in J if site in sites}
                if got != want:
                    raise Fail('replay', 'replay does not reproduce the journal at a producer site',
                               [kind, arm, q, len(got - want), len(want - got)])
                per.setdefault(q, []).append(len(want))
        owned = {i for i, (_, _, sites) in enumerate(self.JA) if a_sites & set(sites)} - {ia}
        owned_b = {d for d, _, sites in self.JB if b_sites & set(sites)} - {db}
        owned_d = {self.JA[i][0] for i in owned}
        roles_a, roles_b = res['A']['roles'], res['B']['roles']
        if bool(r.get('roles')) != bool(roles_a) or set(roles_a) != set(roles_b):
            raise Fail('replay', 'producer roles differ', [kind, sorted(set(roles_a) ^ set(roles_b))[:4]])
        for role in sorted(roles_a):
            x, y = roles_a[role], roles_b[role]
            if (x == da) != (y == db):
                raise Fail('replay', 'role is the input in one arm only', [kind, role])
            if x == da:
                continue        # the producer's ID is its input's digest (geometry_id); D(input) == B input above
            if x not in owned_d or y not in owned_b:
                raise Fail('replay', 'role output not journalled at the producer', [kind, role])
            cur = self.D.get(x, x)
            if (x in self.SEEDED or cur in self.Bset) and cur != y:
                raise Fail('replay', 'role conflicts with the translation', [kind, role])
            self.D[x] = y
            self.pinned.add(x)
        self.rounds('replay-' + kind)
        if self.D.get(da, da) != db:
            raise Fail('replay', 'input translation moved after the roles were pinned', kind)
        self.owned |= owned
        self.owned_b |= owned_b
        self.internal |= {mod + ':' + q for q in r.get('internal', [])}
        self.replayed.append(dict(kind=kind, module=module, input_a=da, input_b=db, roles=len(roles_a),
                                  a_sites=sorted(a_sites),
                                  sites={q: n for q, n in per.items()}))

    # ------------------------------------------------------------ final
    def final(self):
        if self.errors:
            first = sorted(self.errors.items())[:6]
            raise Fail('rules', 'declared rule failed', [[self.JA[i][2][0], e] for i, e in first])
        used = set().union(*self.used.values()) if self.used else set()
        unused = [r['id'] for r in self.rules if r['id'] not in used]
        if unused:
            raise Fail('rules', 'declared rule never used', unused[:8])
        for x in sorted(self.sort_ids):
            if x not in self.Aset:
                raise Fail('rules', 'sort ID is not a journalled A digest', x[:16])
            if self.D.get(x, x) not in self.Bset:
                raise Fail('rules', 'id maps to nothing', x[:16])
        D, Bset = self.D, self.Bset
        unmapped = [i for i, (d, _, _) in enumerate(self.JA) if D.get(d, d) not in Bset]
        outside = [i for i in unmapped if i not in self.owned]
        if outside:
            raise Fail('derive', 'A entries unmapped outside the producers',
                       [len(outside), Counter(self.JA[i][2][0] for i in outside).most_common(6)])
        owned_d = {self.JA[i][0] for i in self.owned}
        exact = module_int(self.b_root/self.token['module_file'], self.token['name']) if self.token else None
        cls = Counter()
        for i in unmapped:
            d, pre, sites = self.JA[i]
            leak = [j for j in self.CONS.get(d, ()) if self.JA[j][0] not in owned_d]
            if leak:
                raise Fail('replay', 'unmapped producer output consumed outside its producer',
                           [sites[0], self.JA[leak[0]][2][0]])
            if self.token and self.token['site'] in sites:
                got = self.tlen.get(i)
                if exact is None or got is None or not (len(pre) > exact >= got):
                    raise Fail('token', 'token not explained by the exact-key bound', [len(pre), got])
                cls['token-exact-key'] += 1
            elif self.internal & set(sites):
                cls['replay-internal'] += 1
            else:
                raise Fail('replay', 'unmapped producer output at no declared site', sites[0])
        ma, mb = self.arm_a['metadata_sha256'], self.arm_b['metadata_sha256']
        if D.get(ma, ma) != mb:
            raise Fail('records', 'D(A record) is not the B record')
        aa, ab = self.arm_a.get('arrays') or {}, self.arm_b.get('arrays') or {}
        if set(aa) != set(ab):
            raise Fail('records', 'array names differ', sorted(set(aa) ^ set(ab)))
        for k in sorted(aa):
            if D.get(aa[k], aa[k]) != ab[k]:
                raise Fail('records', 'array does not pair', k)
        census = self.census({D.get(d, d) for d, _, _ in self.JA})
        for i, (d, _, _) in enumerate(self.JA):
            if i in self.owned or i in unmapped:
                continue
            cls['seeded' if d in self.SEEDED else 'pinned' if d in self.pinned
                else 'unchanged' if D.get(d, d) == d else 'translated'] += 1
        cls['producer-mapped'] = len(self.owned) - cls['token-exact-key'] - cls['replay-internal']
        sites_of = {s for r in self.replayed for s in r['a_sites']}
        per_site = defaultdict(Counter)
        for i in sorted(self.owned):
            d, pre, sites = self.JA[i]
            how = ('token-exact-key' if self.token and self.token['site'] in sites else 'replay-internal') \
                if i in unmapped else 'role' if d in self.pinned else 'translated'
            per_site[min(sites_of & set(sites))][how + ':' + self.KIND[i]] += 1
        self.stats.update(classes=dict(cls), producer_sites={s: dict(c) for s, c in sorted(per_site.items())},
                          b_only=dict(census), b_only_total=sum(census.values()),
                          rules_used={r['id']: sum(r['id'] in u for u in self.used.values()) for r in self.rules},
                          sort_ids=len(self.sort_ids), replay=self.replayed, exact_key_bytes=exact)
        self.lap('final')

    def census(self, image):
        """B entries no A entry derives: the identity member's own hashes (its source, its size record and its code
        objects, computed here from the folded file), then the overlay's declared B-only files, each by its exact
        digest at its site and each needed. Anything else fails."""
        rest = {d: sites for d, _, sites in self.JB if d not in image and d not in self.owned_b}
        out = Counter()
        for d in sorted(set(rest) & self.ID_DIGESTS):
            del rest[d]
            out['identity'] += 1
        for b in self.ov.get('b_only', []):
            d = sha((self.b_root/b['key']).read_bytes())
            if d not in rest or self.site_b(b['site']) not in rest[d]:
                raise Fail('census', 'declared B-only file is not B-only at its site', b['key'])
            del rest[d]
            out['declared:' + b['key']] += 1
        if rest:
            raise Fail('census', 'B entries no A entry derives', Counter(s[0] for s in rest.values()).most_common(6))
        return out

    def run(self, out):
        report = dict(schema=REPORT_SCHEMA, status=None, stats=self.stats)
        self.sig, self.tlen, self.used, self.errors = {}, {}, {}, {}
        self.special, self.pinned, self.owned, self.owned_b, self.internal = set(), set(), set(), set(), set()
        self.sort_ids, self.cons_cache, self.ref_cache, self.replayed, self.bumped = set(), {}, {}, [], 0
        try:
            self.load()
            report['overlay_sha256'] = sha(self.overlay.read_bytes())
            self.records_static()
            self.seeds()
            self.index()
            self.rounds('initial')
            work = out.parent/(out.stem + '-replay')
            work.mkdir(parents=True, exist_ok=True)
            for r in self.replays:
                self.replay(r, work)
            self.final()
        except Fail as e:
            report.update(status='FAIL', fail=dict(stage=e.stage, reason=e.reason, detail=e.detail))
            out.write_text(json.dumps(report, indent=1, default=str) + '\n', encoding='utf8', newline='\n')
            raise
        report['status'] = 'PASS'
        out.write_text(json.dumps(report, indent=1, default=str) + '\n', encoding='utf8', newline='\n')
        print(json.dumps(dict(status='PASS', out=out.name, classes=self.stats['classes'],
                              b_only=self.stats['b_only_total'], seconds=self.stats['seconds'].get('final'))))
        return 0


def noise(a_obs, a2_obs):
    """Two runs of one arm: the same record and the same journal digests."""
    _, j1, r1 = load_arm(a_obs, 'A')
    _, j2, r2 = load_arm(a2_obs, "A'")
    diff = []
    if canon(r1) != canon(r2):
        l1, l2 = dict(leaves(r1)), dict(leaves(r2))
        diff = [list(p)[:8] for p in sorted(set(l1) | set(l2), key=repr) if l1.get(p) != l2.get(p)]
    s1, s2 = {d: s[0] for d, _, s in j1}, {d: s[0] for d, _, s in j2}
    only1 = Counter(s1[d] for d in set(s1) - set(s2))
    only2 = Counter(s2[d] for d in set(s2) - set(s1))
    if diff or only1 or only2:
        raise Fail('noise', 'runs differ', dict(record_leaves=len(diff), first=diff[:12],
                                                only_first=only1.most_common(8), only_second=only2.most_common(8)))
    print(json.dumps(dict(status='PASS', entries=len(s1), record_sha256=sha(canon(r1)))))
    return 0


def replay_child(parent, kind, module_name, inp, out):
    sys.path.insert(0, parent)
    log = []

    class Recorder:
        def __init__(self, data=b''):
            self._h, self._n = hashlib.sha256(), 0
            if data:
                self.update(data)

        def update(self, data):
            view = memoryview(data)
            self._n += view.nbytes
            self._h.update(view)

        def _log(self, value):
            log.append((sys._getframe(2).f_code.co_qualname, self._h.hexdigest(), self._n))
            return value

        def hexdigest(self):
            return self._log(self._h.hexdigest())

        def digest(self):
            return self._log(self._h.digest())

        def copy(self):
            other = Recorder()
            other._h, other._n = self._h.copy(), self._n
            return other

    import importlib

    import atlas_tectonics
    from atlas_tectonics.resources import WorkBudget
    module = importlib.import_module(module_name)
    root = Path(parent).resolve()
    for m in (atlas_tectonics, module):
        if m.__file__ is None or not Path(m.__file__).resolve().is_relative_to(root):
            raise SystemExit('not loaded from the package parent: %r' % m.__file__)
    setattr(module, 'sha256', Recorder)
    value = json.loads(Path(inp).read_bytes())
    roles = {}
    if kind == 'mesh':
        metadata, frozen = module.pack_mesh(value, support_writer=lambda content, raw: None,
                                            budget=WorkBudget(2 << 30))
        roles = {'geometry_id': metadata['geometry_id']}
        roles.update({'array:' + k: v['sha256'] for k, v in metadata['arrays'].items()})
        del frozen
    elif kind == 'record':
        from atlas_tectonics._private.content_cache import create_retained_scope
        scope = create_retained_scope(WorkBudget(2 << 30), process_epoch='replay')
        record = module.RecordCodec().pack_record(value, record_schema='atlas.json-value.v1', scope=scope,
                                                  check=lambda: None)
        record.close()
    else:
        raise SystemExit('unknown replay kind %r' % kind)
    Path(out).write_text(json.dumps(dict(kind=kind, roles=roles, log=log)), encoding='utf8')


def main(argv):
    cmd = argv[0] if argv else ''
    if cmd == 'replay-child' and len(argv) == 6:
        replay_child(*argv[1:6])
        return 0
    try:
        if cmd == 'check' and len(argv) == 7:
            return Check(*map(Path, argv[1:6])).run(Path(argv[6]))
        if cmd == 'noise' and len(argv) == 3:
            return noise(Path(argv[1]), Path(argv[2]))
    except Fail as e:
        print(json.dumps(dict(status='FAIL', stage=e.stage, reason=e.reason, detail=e.detail), default=str)[:4000])
        return 1
    print((__doc__ or '').split('\n\n')[1])
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
