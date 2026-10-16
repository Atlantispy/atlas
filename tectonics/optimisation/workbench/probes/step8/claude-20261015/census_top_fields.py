"""Top-level field sizes of authentic IV1 records from the structure census.

Usage: python -B census_top_fields.py RECORD_NAME [RECORD_NAME ...]
Prints each top-level field's kind, item count and canonical bytes, largest
first, so caps can be audited against real record sizes.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CENSUS = HERE.parents[1]/'structure-census-r3'/'structure-census.json'


def main():
    census = json.loads(CENSUS.read_text(encoding='utf8'))['census']['records']
    for name in sys.argv[1:]:
        record = census[name]
        rows = [f for f in record['fields'] if len(f['path']) == 1]
        print('==', name, 'canonical', record['filebytes'])
        for f in sorted(rows, key=lambda f: -f['bytes']):
            print('  %-40s %-7s items=%-8s bytes=%d' % (f['path'][0], f['kind'], f.get('items'), f['bytes']))


if __name__ == '__main__':
    main()
