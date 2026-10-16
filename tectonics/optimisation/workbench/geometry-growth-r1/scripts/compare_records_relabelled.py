"""Two issued records are equal up to a consistent relabelling of their content-derived ids.

The execution identity enters many ids (cell, face, funding and plan ids are digests over content
AND the runtime's identity), and records list some children in id order. A runtime change that
alters only the identity therefore renames ids and can reorder id-sorted lists while every number
stays the same. This proves exactly that, or fails:

1. Ids are 64-character lowercase hex strings (values or dict keys). Ids present in both records
   are left alone; the others ("differing ids") must correspond one-to-one.
2. A bijection f from A's differing ids to B's is built by matching: dict fields by key, lists
   without differing ids by position, and lists or id-keyed dicts with differing ids by a unique
   signature (the element with ids already in f substituted and the rest blanked). Rounds repeat
   until no new pair appears. Any pair that contradicts an earlier one fails.
3. Final check: A with f applied equals B, where a list is compared by position unless it holds
   differing ids, in which case as a sorted multiset. Every such list that needed reordering must
   be in sorted order in BOTH raw records (so its order is the id sort, not data); it is counted.
Exit 0 only if f covers every differing id, is one-to-one, and the final check holds.
Usage: compare_records_relabelled.py A.json.gz B.json.gz
"""
import gzip
import json
import re
import sys

ID = re.compile(r'[0-9a-f]{64}\Z')
BLANK = '<ID>'


def ids(x, out):
    if isinstance(x, str):
        if ID.match(x):
            out.add(x)
    elif isinstance(x, dict):
        for k, v in x.items():
            ids(k, out)
            ids(v, out)
    elif isinstance(x, list):
        for v in x:
            ids(v, out)
    return out


def dumps(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'))


class Relabel:
    def __init__(self, a, b):
        self.a, self.b = a, b
        ia, ib = ids(a, set()), ids(b, set())
        common = ia & ib
        self.diff = (ia - common, ib - common)
        self.f, self.g = {}, {}
        self.conflicts = []
        self._holds = ({}, {})

    def holds(self, x, side):
        """Does x contain any differing id of its side (cached by object id)."""
        cache = self._holds[side]
        key = id(x)
        if key not in cache:
            diff = self.diff[side]
            if isinstance(x, str):
                found = x in diff
            elif isinstance(x, dict):
                found = any(k in diff or self.holds(v, side) for k, v in x.items())
            elif isinstance(x, list):
                found = any(self.holds(v, side) for v in x)
            else:
                found = False
            cache[key] = found
        return cache[key]

    def canon(self, x, side, final=False):
        """A side: mapped ids -> their B id; B side: ids in f's range kept; other differing ids blanked
        (final: none may remain). Lists with differing ids sorted; id-keyed dicts as sorted pairs."""
        diff = self.diff[side]
        if isinstance(x, str):
            if x in diff:
                if side == 0:
                    return self.f.get(x, BLANK)
                return x if x in self.g else BLANK
            return x
        if isinstance(x, dict):
            if any(k in diff for k in x):
                items = [[self.canon(k, side, final), self.canon(v, side, final)] for k, v in x.items()]
                return {'<id-keyed>': sorted(items, key=dumps)}
            return {k: self.canon(v, side, final) for k, v in x.items()}
        if isinstance(x, list):
            items = [self.canon(v, side, final) for v in x]
            if self.holds(x, side):
                items.sort(key=dumps)
            return items
        return x

    def pair(self, a, b):
        if a in self.f or b in self.g:
            if self.f.get(a) != b or self.g.get(b) != a:
                self.conflicts.append((a, b, self.f.get(a), self.g.get(b)))
            return False
        self.f[a], self.g[b] = b, a
        return True

    def match(self, a, b):
        """Walk a (side A) and b (side B) in parallel; return the number of new id pairs."""
        new = 0
        if isinstance(a, str) and isinstance(b, str):
            if a in self.diff[0] and b in self.diff[1]:
                new += self.pair(a, b)
            return new
        if isinstance(a, dict) and isinstance(b, dict):
            if any(k in self.diff[0] for k in a) or any(k in self.diff[1] for k in b):
                return new + self.match_items([[k, v] for k, v in a.items()], [[k, v] for k, v in b.items()])
            for k in a.keys() & b.keys():
                new += self.match(a[k], b[k])
            return new
        if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            if not self.holds(a, 0) and not self.holds(b, 1):
                return new + sum(self.match(x, y) for x, y in zip(a, b))
            return new + self.match_items(a, b)
        return new

    def match_items(self, a, b):
        new = 0
        sa, sb = {}, {}
        for x in a:
            sa.setdefault(dumps(self.canon(x, 0)), []).append(x)
        for y in b:
            sb.setdefault(dumps(self.canon(y, 1)), []).append(y)
        for sig, xs in sa.items():
            ys = sb.get(sig)
            if ys is not None and len(xs) == 1 and len(ys) == 1:
                new += self.match(xs[0], ys[0])
        return new

    def run(self):
        rounds = 0
        while True:
            rounds += 1
            if not self.match(self.a, self.b) or self.conflicts or rounds > 50:
                break
        ca, cb = self.canon(self.a, 0, True), self.canon(self.b, 1, True)
        reordered, unexplained = self.reorders(self.a, self.b)
        return dict(
            differing_ids=[len(self.diff[0]), len(self.diff[1])], mapped=len(self.f), rounds=rounds,
            conflicts=len(self.conflicts), conflict_examples=self.conflicts[:3],
            unmapped_a=len(self.diff[0] - self.f.keys()), unmapped_b=len(self.diff[1] - self.g.keys()),
            equal_after_relabelling=dumps(ca) == dumps(cb),
            lists_reordered=reordered, reorders_not_explained_by_id_sort=unexplained)

    def reorders(self, a, b):
        """Count id-bearing lists whose relabelled order differs, and those not sorted in both raw records."""
        reordered = unexplained = 0
        stack = [(a, b)]
        while stack:
            x, y = stack.pop()
            if isinstance(x, dict) and isinstance(y, dict):
                if any(k in self.diff[0] for k in x):
                    continue        # id-keyed dict: key order carries no data
                stack.extend((x[k], y[k]) for k in x.keys() & y.keys())
            elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
                mapped = [dumps(self.canon(v, 0, True)) for v in x]
                raw_b = [dumps(self.canon(v, 1, True)) for v in y]
                if mapped != raw_b and self.holds(x, 0):
                    reordered += 1
                    raw = [dumps(v) for v in x], [dumps(v) for v in y]
                    if raw[0] != sorted(raw[0]) or raw[1] != sorted(raw[1]):
                        unexplained += 1
                    continue
                stack.extend(zip(x, y))
        return reordered, unexplained


def main():
    a = json.loads(gzip.decompress(open(sys.argv[1], 'rb').read()))
    b = json.loads(gzip.decompress(open(sys.argv[2], 'rb').read()))
    result = Relabel(a, b).run()
    ok = (result['equal_after_relabelling'] and not result['conflicts'] and not result['unmapped_a']
          and not result['unmapped_b'] and not result['reorders_not_explained_by_id_sort'])
    print(json.dumps(dict(ok=ok, **result), indent=1, default=str))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
