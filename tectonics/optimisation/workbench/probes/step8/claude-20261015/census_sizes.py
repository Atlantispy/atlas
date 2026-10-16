"""Print per-family IV1 canonical sizes and top fields from the reviewed census."""
import hashlib
import json
import os
import sys

R = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
CENSUS = os.path.join(R, 'probes', 'structure-census-r3', 'structure-census.json')
EXPECTED = '02f0a05a7f05855d7ef578b879666489e8b2711405da2031204df372b5e379ae'


def main():
    raw = open(CENSUS, 'rb').read()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED, 'census changed'
    census = json.loads(raw)['census']
    top = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    for name, record in census['records'].items():
        print(f"{name}: filebytes={record.get('filebytes')} counts={record.get('counts')} depth={record.get('max_depth')}")
        fields = sorted(record.get('fields', []), key=lambda f: -f.get('bytes', 0))
        for f in fields[:top]:
            print(f"    {f.get('path')} kind={f.get('kind')} items={f.get('items')} bytes={f.get('bytes')}")
    print('heat keys:', list(census['heat'].keys()))
    print('graph_overlap keys:', list(census['graph_overlap'].keys()))
    print(json.dumps(census['graph_overlap'], indent=1)[:3000])


if __name__ == '__main__':
    main()
