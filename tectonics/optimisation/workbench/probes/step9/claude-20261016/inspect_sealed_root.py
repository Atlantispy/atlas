"""Read-only look at a sealed interval file's manifest for one key (smoke diagnosis, 16 Oct 2026).

Usage: python -B inspect_sealed_root.py INTERVAL_FILE KEY [DOTTED.PATH ...]
Opens the SQLite file with mode=ro (immutable=1), lists its tables once, finds the
manifest row whose id is KEY, decodes its JSON body and prints the top-level keys
and the value at each dotted path (truncated). Nothing is written.
"""
import json
import sqlite3
import sys
from pathlib import Path


def lookup(value, path):
    for part in path.split('.'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def main():
    path, key, paths = Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3:]
    db = sqlite3.connect(f'file:{path.as_posix()}?mode=ro&immutable=1', uri=True)
    try:
        tables = {name: [row[1] for row in db.execute(f'PRAGMA table_info({name})')]
                  for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        print(json.dumps(tables, indent=1))
        table = 'manifests' if 'manifests' in tables else 'snapshots'
        columns = tables[table]
        id_column = 'id' if 'id' in columns else columns[0]
        body_column = next(name for name in ('body', 'manifest', 'value', 'metadata') if name in columns)
        row = db.execute(f'SELECT {body_column} FROM {table} WHERE {id_column}=?', (key,)).fetchone()
        if row is None:
            print('no manifest with id', key)
            return
        raw = row[0]
        body = json.loads(raw if isinstance(raw, str) else bytes(raw).decode('utf8'))
        print('top-level keys:', sorted(body) if isinstance(body, dict) else type(body).__name__)
        for dotted in paths:
            try:
                text = json.dumps(lookup(body, dotted), indent=1, sort_keys=True)
            except (KeyError, IndexError, ValueError, TypeError) as error:
                text = 'missing: ' + repr(error)
            print('== ' + dotted)
            print(text[:4000])
    finally:
        db.close()


if __name__ == '__main__':
    main()
