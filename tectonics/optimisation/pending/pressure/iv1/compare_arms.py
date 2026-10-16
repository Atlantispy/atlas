"""IV1 replay: compare the before and after arms field by field and write one verdict file.

Usage: compare_arms.py --before ATTEMPT DUMPS PROFILE_SHA256 --after ATTEMPT DUMPS PROFILE_SHA256 --out NEW_JSON
  ATTEMPT  the arm's route (1) output directory (stage-root.json, stage-interval.json, run-*/, reader-*/)
  DUMPS    folder with i0/ and i1/, the dump_arm.py outputs for intervals 0 and 1
  PROFILE_SHA256  the arm's pinned profile; every dump of the arm must have been taken from it
Imports nothing from the runtime (json and numpy only), so it may run with -I.

Verdict, most severe first:
  FAIL    a refusal flip between the arms at a stage; the after arm's interval width gate failed or is
          missing; a dump that is missing, changed since it was taken, from another profile, or not bound to
          the adopted stage record (reader receipt, verdict and adopted file sha256); the stage record's width
          gate disagrees with the dump's; a key-paired value changed by at least its certified radius; any
          compare error.
  VOID    an arm has no usable outcome for an environment reason (stage record missing or incomplete, guard
          abort, cancel or guard stop reason), or both arms refused at the same stage; rerun, nothing concluded.
  REVIEW  structure or label changes, boolean changes, changed values under positional (weak) pairing of a
          list of objects, a ratio above the DESIGN bound 2**-11, a binary64 change above 2**9 ulps, a radius
          field without its own radius changing by more than 2**-11 relative, any other exact value without a
          radius changing by more than 2**-20 relative to its scale, a changed non-float array.
  PASS    none of the above.
Radius of a value: inside a key containing 'bounds' (two rationals lo < hi), the before arm's half-width;
otherwise the smallest positive same-unit sibling whose name says error/deviation/radius/tolerance/uncertainty
(min over both arms). Relative changes of numeric lists (vectors) are taken against the list's largest
magnitude. 64-hex identities (alone or inside a string) that change are expected and only counted.
Pairing: dicts by key (64-hex keys translated through identities learnt earlier); lists of objects by the
first key, ids first, that is unique on both sides with the same value set (translated if needed); other
lists by position. A list of objects paired by position only is WEAK: its changes never PASS.
"""
import argparse
import json
import math
import re
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np

SCHEMA = 'atlas.private.iv1-arm-compare.r1'
KINDS = ('mesh', 'state')
STAGES = (('root', 0), ('interval', 1))
ADOPTED = 'ADOPTED'
GATE_STOP = 'ADOPTED_WIDTH_GATE_STOP_BEFORE_INTERVAL_2'
PRESEAL_REFUSED = 'FAILED_PRESEAL_SEALED_FOR_REVIEW'
DESIGN_RATIO = 2.0**-11
REVIEW_REL = 2.0**-20
REVIEW_ULPS = 2**9
MAX_FIELDS = 20000
MAX_ITEMS = 200
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
HEX64_ANY = re.compile(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])')
HEXINT = re.compile(r'-?0x[0-9a-f]+\Z')
RADIUS = re.compile(r'error|deviation|radius|tolerance|uncertainty')
UNITS = ('_rad_s', '_s_inv', '_n_m', '_m3', '_m2', '_kg', '_j', '_m', '_s')
BIG = sys.float_info.max


class CompareError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CompareError(message)


def file_sha(path):
    digest = sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 22), b''):
            digest.update(block)
    return digest.hexdigest()


def unit(key):
    return next((u for u in UNITS if key.endswith(u)), None)


def rational(value):
    if (type(value) is list and len(value) == 2 and type(value[0]) is str and type(value[1]) is str
            and HEXINT.match(value[0]) and HEXINT.match(value[1])):
        den = int(value[1], 16)
        if den > 0:
            return int(value[0], 16), den
    return None


def number(value):
    """An exact (num, den) for a rational, int or finite binary64 leaf; None otherwise."""
    r = rational(value)
    if r is not None:
        return r
    if type(value) is int:
        return value, 1
    if type(value) is float and math.isfinite(value):
        return value.as_integer_ratio()
    return None


def quotient(num, den):
    """|num/den| as a finite float (capped, may underflow to 0.0) and a log2 estimate (None for 0)."""
    num = abs(num)
    if num == 0:
        return 0.0, None
    try:
        value = num/den
    except OverflowError:
        value = BIG
    return min(value, BIG), num.bit_length()-den.bit_length()


def ident(value):
    """Hashable form of an id-like value (strings and ints only; None if it holds numbers or rationals)."""
    if type(value) is str:
        return None if HEXINT.match(value) else value
    if value is None or type(value) in (int, bool):
        return value
    if type(value) is list:
        parts = tuple(ident(v) for v in value)
        return None if any(p is None and v is not None for p, v in zip(parts, value, strict=True)) else ('L',)+parts
    if type(value) is dict:
        parts = tuple((k, ident(v)) for k, v in sorted(value.items()))
        return None if any(p is None and value[k] is not None for k, p in parts) else ('D',)+parts
    return None


class Comparer:
    def __init__(self, ids):
        self.fields, self.overflow = {}, 0
        self.ids, self.id_conflicts = ids, 0
        self.structure, self.labels = [], []
        self.counts = {'structure': 0, 'labels': 0, 'identity_changes': 0, 'weak_pairings': 0,
                       'keyed_pairings': 0}

    # ---- bookkeeping
    def field(self, path, kind):
        name = '.'.join(path)
        entry = self.fields.get(name)
        if entry is None and len(self.fields) >= MAX_FIELDS:
            self.overflow += 1
            name, entry = '<overflow>', self.fields.get('<overflow>')
        if entry is None:
            entry = self.fields[name] = {
                'kind': kind, 'radius_field': bool(path and RADIUS.search(path[-1])), 'compared': 0,
                'changed': 0, 'weak_changed': 0, 'max_abs': 0.0, 'max_abs_log2': None, 'max_rel': 0.0,
                'max_ulps': 0, 'radius': None, 'max_ratio': None, 'max_ratio_weak': None,
                'unassociated_changes': 0}
        return entry

    def note(self, bucket, path, message):
        self.counts[bucket] += 1
        items = self.structure if bucket == 'structure' else self.labels
        if len(items) < MAX_ITEMS:
            items.append({'path': '.'.join(path), 'what': message})

    def learn(self, before, after):
        """Record before -> after for changed 64-hex identities; True if the pair differs in identities only."""
        if type(before) is not str or type(after) is not str:
            return False
        if HEX64.match(before) and HEX64.match(after):
            if before != after and self.ids.setdefault(before, after) != after:
                self.id_conflicts += 1
            return True
        xs, ys = HEX64_ANY.findall(before), HEX64_ANY.findall(after)
        if xs and len(xs) == len(ys) and HEX64_ANY.sub('#', before) == HEX64_ANY.sub('#', after):
            for x, y in zip(xs, ys, strict=True):
                if x != y and self.ids.setdefault(x, y) != y:
                    self.id_conflicts += 1
            return True
        return False

    def translate(self, value):
        if type(value) is str:
            return self.ids.get(value, value)
        if type(value) is tuple:
            return tuple(self.translate(v) for v in value)
        return value

    # ---- walk
    def compare(self, a, b, path, weak=False, radius=None, scale=None):
        if type(a) is type(b) and a == b:
            if type(a) not in (dict, list):
                self.field(path, type(a).__name__)['compared'] += 1
            return
        if type(a) is dict and type(b) is dict:
            return self.dicts(a, b, path, weak)
        if type(a) is list and type(b) is list:
            ra, rb = rational(a), rational(b)
            if ra and rb:
                return self.exact(ra, rb, path, weak, radius, scale, 'rational')
            if ra or rb:
                return self.note('structure', path, 'rational on one side only')
            return self.lists(a, b, path, weak, radius)
        if type(a) is str and type(b) is str:
            if self.learn(a, b):
                self.counts['identity_changes'] += 1
                return
            if HEXINT.match(a) and HEXINT.match(b):
                return self.exact((int(a, 16), 1), (int(b, 16), 1), path, weak, radius, scale, 'hex-int')
            return self.note('labels', path, 'string %r -> %r' % (a[:80], b[:80]))
        if type(a) in (int, float) and type(b) in (int, float):
            if type(a) is int and type(b) is int:
                return self.exact((a, 1), (b, 1), path, weak, radius, scale, 'int')
            return self.binary64(float(a), float(b), path, weak, radius, scale)
        if type(a) is bool and type(b) is bool:
            return self.note('labels', path, 'boolean %s -> %s' % (a, b))
        self.note('structure', path, 'type %s -> %s' % (type(a).__name__, type(b).__name__))

    @staticmethod
    def segment(key):
        if HEX64.match(key):
            return '#'
        return re.sub(r':\d+$', ':#', key)

    def dicts(self, a, b, path, weak):
        keyed = bool(a) and bool(b) and all(HEX64.match(k) for k in a) and all(HEX64.match(k) for k in b)
        pairs = None
        if keyed and set(a) != set(b):
            moved = {self.ids.get(k, k): k for k in a}
            if len(moved) == len(a) and set(moved) == set(b):
                pairs = [(moved[k], k) for k in sorted(b)]
        if pairs is None:
            only = sorted(set(a) ^ set(b))
            for k in (only[:3] if keyed else only):
                self.note('structure', path+(self.segment(k),), 'key only in %s' % ('before' if k in a else 'after'))
            if keyed and len(only) > 3:
                self.counts['structure'] += len(only)-3
            pairs = [(k, k) for k in sorted(set(a) & set(b))]
        for ka, kb in pairs:                       # learn sibling identities before pairing nested lists
            self.learn(a[ka], b[kb])
        common = [kb for _, kb in pairs]
        for ka, kb in pairs:
            radius = None if keyed else self.radius_of(kb, a, b, common)
            self.compare(a[ka], b[kb], path+(self.segment(kb),), weak, radius)

    def radius_of(self, key, a, b, common):
        u = unit(key)
        if u is None or 'bounds' in key:
            return None          # no unit to match, or an enclosure, which carries its own radius
        best = None
        for other in common:
            if other == key or unit(other) != u or not RADIUS.search(other):
                continue
            for side in (a, b):
                r = number(side[other])
                if r and r[0] > 0 and (best is None or r[0]*best[1][1] < best[1][0]*r[1]):
                    best = (other, r)
        return best

    def lists(self, a, b, path, weak, radius):
        sub = path+('[]',)
        if (len(a) == 2 and len(b) == 2 and radius is None and path and 'bounds' in path[-1]
                and rational(a[0]) and rational(a[1])):
            (n0, d0), (n1, d1) = rational(a[0]), rational(a[1])
            if n0*d1 < n1*d0:
                radius = ('enclosure half-width', (n1*d0-n0*d1, 2*d0*d1))
        if a and b and all(type(x) is dict for x in a) and all(type(x) is dict for x in b):
            found = self.pair(a, b)
            if found is not None:
                self.counts['keyed_pairings'] += 1
                for x, y in found:
                    self.compare(x, y, sub, weak, None)
                return
            if len(a) != len(b):
                return self.note('structure', sub, 'list of objects %d -> %d, no stable key' % (len(a), len(b)))
            self.counts['weak_pairings'] += 1
            for x, y in zip(a, b, strict=True):
                self.compare(x, y, sub, True, None)
            return
        if len(a) != len(b):
            return self.note('structure', sub, 'list length %d -> %d' % (len(a), len(b)))
        scale = None
        values = [number(x) for x in a+b if type(x) is not bool]
        if values and len(values) == len(a)+len(b) and all(values):
            top = max(values, key=lambda v: quotient(v[0], v[1])[0])
            scale = (abs(top[0]), top[1]) if top[0] else None
        for x, y in zip(a, b, strict=True):
            self.compare(x, y, sub, weak, radius, scale)

    def pair(self, a, b):
        if len(a) != len(b):
            return None
        keys = set(a[0]).intersection(*a[1:], *b)
        order = sorted(keys, key=lambda k: (not k.endswith('id'), k))
        for key in order:
            va, vb = [ident(x[key]) for x in a], [ident(x[key]) for x in b]
            if None in va or None in vb or len(set(va)) != len(va) or len(set(vb)) != len(vb):
                continue
            index = dict(zip(vb, b, strict=True))
            for before in (va, [self.translate(v) for v in va]):
                if all(v in index for v in before):
                    return [(x, index[v]) for v, x in zip(before, a, strict=True)]
        return None

    # ---- leaves
    def exact(self, ra, rb, path, weak, radius, scale, kind):
        (na, da), (nb, db) = ra, rb
        entry = self.field(path, kind)
        entry['compared'] += 1
        num = na*db-nb*da
        if num == 0:
            return
        den = da*db
        entry['changed'] += 1
        if weak:
            entry['weak_changed'] += 1
        value, log2 = quotient(num, den)
        entry['max_abs'] = max(entry['max_abs'], value)
        if log2 is not None and (entry['max_abs_log2'] is None or log2 > entry['max_abs_log2']):
            entry['max_abs_log2'] = log2
        if scale is not None:
            rel = quotient(num*scale[1], den*scale[0])[0]
        else:
            top = max(abs(na)*db, abs(nb)*da)
            rel = quotient(num, top)[0] if top else BIG
        entry['max_rel'] = max(entry['max_rel'], rel)
        if radius is None:
            entry['unassociated_changes'] += 1
            return
        name, (nr, dr) = radius
        ratio = quotient(num*dr, den*nr)[0]
        entry['radius'] = name
        slot = 'max_ratio_weak' if weak else 'max_ratio'
        entry[slot] = ratio if entry[slot] is None else max(entry[slot], ratio)

    def binary64(self, x, y, path, weak, radius, scale):
        if x == y or (math.isnan(x) and math.isnan(y)):
            self.field(path, 'binary64')['compared'] += 1
            return
        if not (math.isfinite(x) and math.isfinite(y)):
            self.field(path, 'binary64')['compared'] += 1
            return self.note('labels', path, 'non-finite binary64 %r -> %r' % (x, y))
        self.exact(x.as_integer_ratio(), y.as_integer_ratio(), path, weak, radius, scale, 'binary64')
        entry = self.field(path, 'binary64')
        entry['max_ulps'] = max(entry['max_ulps'], ulps(x, y))


def ulps(x, y):
    def ordered(v):
        bits = int(np.float64(v).view(np.int64))
        return bits if bits >= 0 else -(bits & 0x7fffffffffffffff)
    return abs(ordered(x)-ordered(y))


def array_ulps(u, v):
    """Largest ulp distance between two float64 arrays of equal shape (exact, no int64 overflow)."""
    iu, iv = u.view(np.int64), v.view(np.int64)
    mask = iu != iv
    if not mask.any():
        return 0
    iu, iv = iu[mask], iv[mask]
    low = np.int64(0x7fffffffffffffff)
    ou = np.where(iu < 0, -(iu & low), iu)
    ov = np.where(iv < 0, -(iv & low), iv)
    same = (ou >= 0) == (ov >= 0)
    best = 0
    if same.any():
        best = int(np.max(np.abs(ou[same]-ov[same])))
    if (~same).any():
        best = max(best, max(abs(int(p))+abs(int(q)) for p, q in zip(ou[~same], ov[~same], strict=True)))
    return best


def outcome(attempt, stage):
    """Class of one stage of one arm: adopted, gate_stop, refused, environment, incomplete or missing."""
    path = attempt/('stage-%s.json' % stage)
    if not path.is_file():
        return {'class': 'missing', 'path': str(path)}
    record = json.loads(path.read_bytes())
    status = record.get('status')
    row = {'class': None, 'status': status, 'failed_step': record.get('failed_step'), 'reason': record.get('reason'),
           'path': str(path), 'sha256': file_sha(path), 'width_gate_passed': record.get('width_gate_passed'),
           'steps': {s.get('name'): {k: v for k, v in s.items() if k.endswith('sha256') or k in ('ok', 'exit')}
                     for s in record.get('steps', [])}}
    environment = []
    for folder, stem in (('run-'+stage, 'run'), ('reader-'+stage, 'reopen')):
        for suffix in ('.guard-abort.json', '.cancel'):
            if (attempt/folder/(stem+suffix)).exists():
                environment.append(folder+'/'+stem+suffix)
        guard = attempt/folder/(stem+'.guard.json')
        if guard.is_file():
            reason = (json.loads(guard.read_bytes()) or {}).get('reason')
            if reason:
                environment.append('%s/%s.guard.json reason %s' % (folder, stem, str(reason)[:160]))
    row['environment'] = environment
    if status == ADOPTED:
        row['class'] = 'adopted'
    elif status == GATE_STOP:
        row['class'] = 'gate_stop'
    elif status in (PRESEAL_REFUSED, 'FAILED'):
        row['class'] = 'environment' if environment else 'refused'
    else:
        row['class'] = 'incomplete'
    return row


def load_dump(folder, interval, attempt, stage_row, profile_sha256):
    """A PASS dump of the interval, unchanged since it was taken, from the arm's profile, bound to its stage."""
    record = json.loads((folder/'dump.json').read_bytes())
    require(record.get('status') == 'PASS' and record.get('interval') == interval, 'dump did not pass: '+str(folder))
    require(record['profile']['sha256'] == profile_sha256, 'dump is from another profile: '+str(folder))
    bindings = record['bindings']
    receipt = Path(bindings['reader_receipt']['path'])
    require(receipt.parent.parent.resolve() == attempt.resolve(), 'dump belongs to another attempt: '+str(folder))
    steps = stage_row['steps']
    for binding, step, key in (('reader_receipt', 'reader', 'receipt_sha256'),
                               ('verdict', 'finalise', 'verdict_sha256'),
                               ('adopted', 'adopt', 'adopted_sha256')):
        require(bindings[binding]['sha256'] == (steps.get(step) or {}).get(key),
                'dump %s does not match the stage record: %s' % (binding, folder))
    for name, identity in record['records'].items():
        path = folder/'records'/(name+'.json')
        require(path.stat().st_size == identity['nbytes'] and file_sha(path) == identity['sha256'],
                'dumped record changed since the dump: '+str(path))
    for array in record['arrays']:
        path = folder/'arrays'/array['file']
        require(path.stat().st_size == array['nbytes'] and file_sha(path) == array['sha256'],
                'dumped array changed since the dump: '+str(path))
    return record


def compare_arrays(before, after, fb, fa):
    rows, review = {}, []
    a = {x['name']: x for x in before['arrays']}
    b = {x['name']: x for x in after['arrays']}
    for name in sorted(set(a) ^ set(b)):
        review.append('array only in %s: %s' % ('before' if name in a else 'after', name))
    for name in sorted(set(a) & set(b)):
        x, y = a[name], b[name]
        if (x['dtype'], x['shape']) != (y['dtype'], y['shape']):
            review.append('array %s: %s%s -> %s%s' % (name, x['dtype'], x['shape'], y['dtype'], y['shape']))
            continue
        if x['sha256'] == y['sha256']:
            rows[name] = {'equal': True}
            continue
        dtype = np.dtype(x['dtype'])
        u = np.fromfile(fb/'arrays'/x['file'], dtype=dtype)
        v = np.fromfile(fa/'arrays'/y['file'], dtype=dtype)
        width = dtype.itemsize
        changed = np.any(u.view(np.uint8).reshape(-1, width) != v.view(np.uint8).reshape(-1, width), axis=1)
        row = {'equal': False, 'changed': int(np.count_nonzero(changed)), 'dtype': x['dtype']}
        if dtype == np.dtype('<f8'):
            finite = np.isfinite(u) & np.isfinite(v)
            row.update(max_ulps=array_ulps(u[finite], v[finite]),
                       max_abs=float(np.max(np.abs(u[finite]-v[finite]), initial=0.0)),
                       nonfinite_changes=int(np.count_nonzero(~finite & changed)))
            if row['max_ulps'] > REVIEW_ULPS or row['nonfinite_changes']:
                review.append('array %s: %d ulps, %d non-finite changes' % (name, row['max_ulps'],
                                                                             row['nonfinite_changes']))
        else:
            review.append('non-float array %s changed in %d elements' % (name, row['changed']))
        rows[name] = row
    return rows, review


def judge_fields(fields, review, fail, where):
    for name, f in fields.items():
        if f['max_ratio'] is not None and f['max_ratio'] >= 1:
            fail.append('%s %s: change %.3g x its radius (%s)' % (where, name, f['max_ratio'], f['radius']))
        elif f['max_ratio'] is not None and f['max_ratio'] > DESIGN_RATIO:
            review.append('%s %s: ratio %.3g above 2**-11' % (where, name, f['max_ratio']))
        if f['max_ratio_weak'] is not None and f['max_ratio_weak'] > DESIGN_RATIO:
            review.append('%s %s: weakly paired ratio %.3g' % (where, name, f['max_ratio_weak']))
        if f['weak_changed']:
            review.append('%s %s: %d changes under positional pairing' % (where, name, f['weak_changed']))
        if f['max_ulps'] > REVIEW_ULPS:
            review.append('%s %s: %d ulps' % (where, name, f['max_ulps']))
        if f['unassociated_changes'] and f['kind'] != 'binary64':
            limit = DESIGN_RATIO if f['radius_field'] else REVIEW_REL
            if f['max_rel'] > limit:
                review.append('%s %s: relative change %.3g with no radius (limit %.3g)' % (where, name, f['max_rel'],
                                                                                          limit))


def width_rows(before, after):
    """Per record field: the widest numerator or denominator in bits, before -> after."""
    rows = []
    wb = (before.get('widths') or {}).get('records', {})
    wa = (after.get('widths') or {}).get('records', {})
    for kind in sorted(set(wb) | set(wa)):
        for name in sorted(set(wb.get(kind, {})) | set(wa.get(kind, {}))):
            x, y = wb.get(kind, {}).get(name) or {}, wa.get(kind, {}).get(name) or {}
            bits = [max(r.get('max_numerator_bits', 0), r.get('max_denominator_bits', 0)) if r else None
                    for r in (x, y)]
            rows.append({'record': kind, 'field': name, 'bits_before': bits[0], 'bits_after': bits[1],
                         'count_before': x.get('count'), 'count_after': y.get('count')})
    return rows


def run(args):
    arms = {arm: (Path(v[0]), Path(v[1]), v[2]) for arm, v in (('before', args.before), ('after', args.after))}
    fail, void, review, info = [], [], [], []
    stages, gates, records, arrays, widths = {}, {}, {}, {}, {}
    ids, id_conflicts = {}, 0
    usable = True
    for stage, interval in STAGES:
        rows = {arm: outcome(attempt, stage) for arm, (attempt, _, _) in arms.items()}
        stages[stage] = rows
        if not usable:
            continue
        classes = {arm: row['class'] for arm, row in rows.items()}
        good = ('adopted', 'gate_stop')
        if any(c in ('missing', 'incomplete', 'environment') for c in classes.values()):
            void.append('%s: no usable outcome %s' % (stage, classes))
            usable = False
            continue
        if (classes['before'] in good) != (classes['after'] in good):
            fail.append('%s: refusal flip %s -> %s' % (stage, rows['before']['status'], rows['after']['status']))
            usable = False
            continue
        if classes['before'] not in good:
            void.append('%s: both arms refused (%s / %s)' % (stage, rows['before']['status'], rows['after']['status']))
            usable = False
            continue
        if stage == 'root' and 'gate_stop' in classes.values():
            fail.append('root stage reports a width gate stop')
        folders = {arm: dumps/('i%d' % interval) for arm, (_, dumps, _) in arms.items()}
        dumps = {arm: load_dump(folders[arm], interval, attempt, rows[arm], sha)
                 for arm, (attempt, _, sha) in arms.items()}
        if stage == 'interval':
            for arm in arms:
                gate = dumps[arm].get('width_gate')
                passed = None if gate is None else gate.get('passed')
                gates[arm] = {'verdict': dumps[arm]['bindings']['verdict'], 'passed': passed,
                              'stage_record_passed': rows[arm]['width_gate_passed'], 'width_gate': gate}
                if passed is not rows[arm]['width_gate_passed'] or (passed is False) != (classes[arm] == 'gate_stop'):
                    fail.append('%s arm: the stage record and the dump disagree on the width gate' % arm)
            if gates['after']['passed'] is not True:
                fail.append('after arm interval width gate %s' % gates['after']['passed'])
            info.append('interval width gate: before %s, after %s' % (gates['before']['passed'],
                                                                       gates['after']['passed']))
        widths['i%d' % interval] = width_rows(dumps['before'], dumps['after'])
        names = [k for k in KINDS if k in dumps['before']['records'] or k in dumps['after']['records']]
        names += sorted((set(dumps['before']['records']) | set(dumps['after']['records'])) - set(names))
        for kind in names:
            where = 'i%d/%s' % (interval, kind)
            ib, ia = dumps['before']['records'].get(kind), dumps['after']['records'].get(kind)
            if ib is None or ia is None:
                review.append('%s present in one arm only' % where)
                continue
            if ib == ia:
                records[where] = {'bytes_equal': True, 'nbytes': ib['nbytes']}
                continue
            sub = Comparer(ids)
            a = json.loads((folders['before']/'records'/(kind+'.json')).read_bytes())
            b = json.loads((folders['after']/'records'/(kind+'.json')).read_bytes())
            sub.compare(a, b, (kind,))
            del a, b
            id_conflicts += sub.id_conflicts
            records[where] = {'bytes_equal': False, 'nbytes': [ib['nbytes'], ia['nbytes']], 'counts': sub.counts,
                              'structure': sub.structure, 'labels': sub.labels, 'field_overflow': sub.overflow,
                              'fields': dict(sorted(sub.fields.items(), key=lambda kv: (
                                  -(kv[1]['max_ratio'] or 0), -kv[1]['changed'], kv[0])))}
            if sub.counts['structure'] or sub.counts['labels']:
                review.append('%s: %d structure, %d label changes' % (where, sub.counts['structure'],
                                                                       sub.counts['labels']))
            judge_fields(sub.fields, review, fail, where)
        arrays['i%d' % interval], found = compare_arrays(dumps['before'], dumps['after'], folders['before'],
                                                         folders['after'])
        review.extend('i%d %s' % (interval, r) for r in found)
    if id_conflicts:
        review.append('%d conflicting identity translations' % id_conflicts)
    status = 'FAIL' if fail else 'VOID' if void else 'REVIEW' if review else 'PASS'
    return {'schema': SCHEMA, 'status': status, 'fail': fail, 'void': void, 'review': review[:MAX_ITEMS],
            'review_count': len(review), 'info': info, 'stages': stages, 'width_gate': gates, 'widths': widths,
            'records': records, 'arrays': arrays, 'identity_translations': len(ids),
            'thresholds': {'fail_ratio': 1, 'design_ratio': DESIGN_RATIO, 'review_rel': REVIEW_REL,
                           'review_ulps': REVIEW_ULPS},
            'inputs': {arm: {'attempt': str(a), 'dumps': str(d), 'profile_sha256': s}
                       for arm, (a, d, s) in arms.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description='IV1 replay: per-field compare of the before and after arms')
    parser.add_argument('--before', nargs=3, required=True, metavar=('ATTEMPT', 'DUMPS', 'PROFILE_SHA256'))
    parser.add_argument('--after', nargs=3, required=True, metavar=('ATTEMPT', 'DUMPS', 'PROFILE_SHA256'))
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise SystemExit('verdict file exists')
    try:
        verdict = run(args)
    except Exception as error:  # noqa: BLE001 - any compare error is a FAIL verdict, never a silent pass
        verdict = {'schema': SCHEMA, 'status': 'FAIL', 'fail': ['compare error %s: %s' % (type(error).__name__, error)],
                   'inputs': {'before': args.before, 'after': args.after}}
    here = Path(__file__).resolve()
    verdict['compare_tool'] = {'path': str(here), 'sha256': file_sha(here)}
    with open(out, 'x', encoding='utf8') as stream:
        json.dump(verdict, stream, indent=1, allow_nan=False, default=str)
    print(json.dumps({'status': verdict['status'], 'fail': verdict.get('fail', [])[:5],
                      'void': verdict.get('void', []), 'review_count': verdict.get('review_count'),
                      'review': verdict.get('review', [])[:8]}), flush=True)
    return {'PASS': 0, 'REVIEW': 3, 'VOID': 4}.get(verdict['status'], 1)


if __name__ == '__main__':
    sys.exit(main())
