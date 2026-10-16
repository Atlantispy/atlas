"""Read-only: list tables, row counts and record kinds of a COPIED native store.

Opens the copy with mode=ro&immutable=1; writes nothing; stdout only.
"""
import hashlib
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
h = hashlib.sha256()
with path.open('rb') as f:
    while block := f.read(1 << 22):
        h.update(block)
print('sha256', h.hexdigest(), 'bytes', path.stat().st_size)
uri = path.as_uri().replace('file:///', 'file:/') + '?mode=ro&immutable=1'
con = sqlite3.connect(uri, uri=True)
for (name, sql) in con.execute("select name, sql from sqlite_master where type='table' order by name"):
    n = con.execute(f'select count(*) from "{name}"').fetchone()[0]
    print('TABLE', name, 'rows', n)
    print('   ', (sql or '')[:300].replace('\n', ' '))
    cols = [r[1] for r in con.execute(f'pragma table_info("{name}")')]
    for c in cols:
        if c in ('kind', 'record_kind', 'schema', 'name', 'key', 'category', 'type'):
            rows = con.execute(f'select "{c}", count(*) from "{name}" group by "{c}" order by 2 desc limit 40').fetchall()
            print('    by', c, rows)
con.close()
