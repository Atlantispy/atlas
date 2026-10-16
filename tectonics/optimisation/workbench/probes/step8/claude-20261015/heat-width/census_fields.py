"""Read-only: per-field exact widths of chosen census records (IV1 and its root).

Usage: python -B census_fields.py CENSUS_JSON RECORD [RECORD ...]

For each named census record, prints every field entry with its name/path keys
and the max numerator/denominator bits and counts of its rational strings, so
the root (interval 0) and interval-1 records of the same kind can be compared
field by field. Nothing is written.
"""
import json
import sys
from hashlib import sha256
from pathlib import Path

EXPECTED = '02f0a05a7f05855d7ef578b879666489e8b2711405da2031204df372b5e379ae'


def label(entry):
    return {k: v for k, v in entry.items() if not isinstance(v, (dict, list))}


def main():
    raw = Path(sys.argv[1]).read_bytes()
    if sha256(raw).hexdigest() != EXPECTED:
        raise SystemExit('census differs from the reviewed IV1 census')
    records = json.loads(raw)['census']['records']
    for name in sys.argv[2:]:
        record = records[name]
        print('==', name, {k: v for k, v in label(record).items()})
        fields = record.get('fields', [])
        for index, entry in enumerate(fields):
            strings = entry.get('rational_strings') or {}
            bits = max(strings.get('max_numerator_bits') or 0, strings.get('max_denominator_bits') or 0)
            print(f'  [{index}] bits={bits} count={strings.get("count")}', label(entry))


if __name__ == '__main__':
    main()
