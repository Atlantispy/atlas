"""Read-only: every exact-width statistic in the IV1 structural census, widest first.

Usage: python -B census_widths.py CENSUS_JSON OUT_JSON

Walks the census JSON and reports each object that carries
max_numerator_bits / max_denominator_bits, with its JSON path and any sibling
count fields, sorted by the wider of the two. Nothing else is read or written.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path

EXPECTED = '02f0a05a7f05855d7ef578b879666489e8b2711405da2031204df372b5e379ae'


def walk(value, path, rows):
    if isinstance(value, dict):
        if 'max_numerator_bits' in value or 'max_denominator_bits' in value:
            row = {'path': '/'.join(path)}
            for key, item in value.items():
                if not isinstance(item, (dict, list)):
                    row[key] = item
            rows.append(row)
        for key, item in value.items():
            walk(item, path+[str(key)], rows)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            walk(item, path+[str(index)], rows)


def main():
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    raw = source.read_bytes()
    if sha256(raw).hexdigest() != EXPECTED:
        raise SystemExit('census differs from the reviewed IV1 census')
    rows = []
    walk(json.loads(raw), [], rows)
    rows.sort(key=lambda r: -max(r.get('max_numerator_bits') or 0, r.get('max_denominator_bits') or 0))
    out.write_text(json.dumps(rows, indent=1), encoding='utf8')
    for row in rows[:40]:
        print(max(row.get('max_numerator_bits') or 0, row.get('max_denominator_bits') or 0), row['path'],
              {k: v for k, v in row.items() if k not in ('path',) and 'bits' not in k})


if __name__ == '__main__':
    main()
