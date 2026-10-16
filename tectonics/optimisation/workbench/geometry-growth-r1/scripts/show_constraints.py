"""Diagnostic: print named constraint records of one support (and which components use them)."""
import gzip
import json
import sys


def main():
    path, index = sys.argv[1], int(sys.argv[2])
    names = sys.argv[3:]
    with gzip.open(path, 'rt', encoding='utf8') as f:
        f.readline()
        for i, line in enumerate(f):
            if i != index:
                continue
            r = json.loads(line)
            for name in names:
                print('==', name)
                print(json.dumps(r['constraints'].get(name), indent=1)[:3000])
                users = [(p['logical_cell_id'][:16], s) for p in r['components'] for n, s in p['constraints'] if n == name]
                print('used by', users)
            break


if __name__ == '__main__':
    main()
