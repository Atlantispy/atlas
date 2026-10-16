"""Read-only: the initial queries of a route (1) measurement store in put order, with their work.

Usage: python -B -I store_profile.py STORE.sqlite OUT.json
Opens the sqlite file read-only/immutable. Chunk rowid order is the put order (one raw chunk per
record here). Writes, per record in order: support_id, cell_id, leaves, work_units; prints totals
and the largest per-query work against the session's default child predicate envelope (2**34).
"""
import json
import sqlite3
import sys
from pathlib import Path

uri = Path(sys.argv[1]).resolve().as_uri()+'?mode=ro&immutable=1'
rows, unparsed = [], 0
with sqlite3.connect(uri, uri=True) as db:
    for (payload,) in db.execute('SELECT payload FROM chunks ORDER BY rowid'):
        try:
            value = json.loads(bytes(payload))
        except (ValueError, UnicodeDecodeError):
            unparsed += 1
            continue
        if type(value) is dict and 'cumulative_leaf_units' in value:
            rows.append(dict(support_id=value['support_id'], cell_id=value['cell_id'],
                             leaves=value['cumulative_leaf_units'], work=value['cumulative_work_units']))
Path(sys.argv[2]).write_text(json.dumps(rows), encoding='utf8')
work = [r['work'] for r in rows]
print(dict(records=len(rows), unparsed=unparsed, supports=len({r['support_id'] for r in rows}),
           leaves=sum(r['leaves'] for r in rows), work_total=sum(work), work_max=max(work),
           over_2_34=sum(w > 1 << 34 for w in work)))
