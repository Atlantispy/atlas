"""Read-only scan of a real dump's records with compare_arms' path rules (json only; never imports the runtime).

Usage: scan_real.py DUMP_DIR OUT_JSON
Reports, per normalised field path: leaf kinds seen, standalone hex-int strings with exactly 64 hex digits,
largest |int|, radius siblings compare_arms would associate, and the key pair() would choose for lists of objects.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HEX64 = re.compile(r'[0-9a-f]{64}\Z')
HEX64_ANY = re.compile(r'(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])')
HEXINT = re.compile(r'-?0x[0-9a-f]+\Z')
RADIUS = re.compile(r'error|deviation|radius|tolerance|uncertainty')
UNITS = ('_rad_s', '_s_inv', '_n_m', '_m3', '_m2', '_kg', '_j', '_m', '_s')


def unit(key):
    return next((u for u in UNITS if key.endswith(u)), None)


def rational(v):
    return (type(v) is list and len(v) == 2 and all(type(x) is str and HEXINT.match(x) for x in v)
            and int(v[1], 16) > 0)


def segment(key):
    if HEX64.match(key):
        return '#'
    return re.sub(r':\d+$', ':#', key)


def ident(value):
    if type(value) is str:
        return None if HEXINT.match(value) else value
    if value is None or type(value) in (int, bool):
        return value
    if type(value) is list:
        parts = tuple(ident(v) for v in value)
        return None if any(p is None and v is not None for p, v in zip(parts, value)) else ('L',)+parts
    if type(value) is dict:
        parts = tuple((k, ident(v)) for k, v in sorted(value.items()))
        return None if any(p is None and value[k] is not None for k, p in parts) else ('D',)+parts
    return None


kinds = defaultdict(set)
hex64int = defaultdict(int)
hexint_digits = defaultdict(int)
max_int = defaultdict(int)
radius_assoc = defaultdict(set)
pair_key = defaultdict(set)
hex64_values = defaultdict(int)
hex64_embedded = defaultdict(set)
first_kind = {}
leaf_order = defaultdict(list)


def leaf(path, kind):
    name = '.'.join(path)
    kinds[name].add(kind)
    first_kind.setdefault(name, kind)


def walk(v, path):
    if type(v) is dict:
        keys = list(v)
        for k in keys:
            u = unit(k)
            if u and 'bounds' not in k:
                sib = [o for o in keys if o != k and unit(o) == u and RADIUS.search(o)]
                if sib:
                    radius_assoc['.'.join(path+(segment(k),))].add(tuple(sorted(sib)))
            walk(v[k], path+(segment(k),))
        return
    if type(v) is list:
        if rational(v):
            leaf(path, 'rational')
            return
        if v and all(type(x) is dict for x in v):
            keys = set(v[0]).intersection(*v[1:])
            order = sorted(keys, key=lambda k: (not k.endswith('id'), k))
            chosen = None
            for key in order:
                va = [ident(x[key]) for x in v]
                if None in va or len(set(va)) != len(va):
                    continue
                chosen = key
                break
            pair_key['.'.join(path+('[]',))].add((chosen, len(v), tuple(order[:4])))
        for x in v:
            walk(x, path+('[]',))
        return
    if type(v) is str:
        if HEXINT.match(v):
            leaf(path, 'hex-int')
            d = len(v.lstrip('-')) - 2
            hexint_digits['.'.join(path)] = max(hexint_digits['.'.join(path)], d)
            if HEX64_ANY.search(v):
                hex64int['.'.join(path)] += 1
        elif HEX64.match(v):
            leaf(path, 'hex64')
            hex64_values['.'.join(path)] += 1
        elif HEX64_ANY.search(v):
            leaf(path, 'str+hex64')
            hex64_embedded['.'.join(path)].add(HEX64_ANY.sub('#', v)[:80])
        else:
            leaf(path, 'str')
        return
    if type(v) is bool:
        leaf(path, 'bool')
    elif type(v) is int:
        leaf(path, 'int')
        name = '.'.join(path)
        max_int[name] = max(max_int[name], abs(v))
    elif type(v) is float:
        leaf(path, 'float')
    elif v is None:
        leaf(path, 'None')
    else:
        leaf(path, type(v).__name__)


def main():
    dump_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    report = {}
    for f in sorted((dump_dir/'records').glob('*.json')):
        kinds.clear(); hex64int.clear(); max_int.clear(); radius_assoc.clear(); pair_key.clear()
        hex64_values.clear(); hex64_embedded.clear(); first_kind.clear(); hexint_digits.clear()
        data = json.loads(f.read_bytes())
        walk(data, (f.stem,))
        report[f.stem] = {
            'distinct_fields': len(kinds),
            'mixed_kinds': {k: sorted(v) for k, v in kinds.items() if len(v - {'None'}) > 1},
            'standalone_hexint_with_64_digit_run': dict(hex64int),
            'hexint_max_digits': dict(hexint_digits),
            'ints_over_2_20': {k: v for k, v in max_int.items() if v >= 2**20},
            'radius_assoc': {k: [list(s) for s in v] for k, v in radius_assoc.items()},
            'pair_key': {k: [list(map(str, s)) for s in v] for k, v in pair_key.items()},
            'hex64_value_fields': dict(hex64_values),
            'hex64_embedded': {k: sorted(v)[:5] for k, v in hex64_embedded.items()},
            'all_fields': {k: sorted(v) for k, v in kinds.items()},
        }
        del data
    out.write_text(json.dumps(report, indent=1, default=str), encoding='utf8')
    for name, r in report.items():
        print(name, 'fields', r['distinct_fields'], 'mixed', len(r['mixed_kinds']),
              'hex64-in-hexint', sum(r['standalone_hexint_with_64_digit_run'].values()),
              'radius_assoc', len(r['radius_assoc']), 'pair_key', len(r['pair_key']))


if __name__ == '__main__':
    main()
