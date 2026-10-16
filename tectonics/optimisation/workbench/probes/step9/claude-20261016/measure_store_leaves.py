"""Read-only: leaf work of the initial measurements saved in route (1) measurement stores.

Usage: python -B measure_store_leaves.py LABEL=STORE.sqlite [LABEL=...]

Each admission writes one cached record per initial exterior component
(integration_dual_geometry.cached_initial_component): a raw-codec JSON payload with
'cumulative_leaf_units' and its 'queries'. The sqlite file is opened read-only and immutable
(nothing is written); every chunk payload that parses as such a record is counted. Prints per
store: records, total leaves, leaves per record (mean, quantiles), queries, and the records
whose payload did not parse alone (multi-chunk). Rows are matched across stores by the
component's logical cell id when the payload carries one.
"""
import json
import sqlite3
import sys
from pathlib import Path


def records(path):
    uri = Path(path).resolve().as_uri()+'?mode=ro&immutable=1'
    found, unparsed = {}, 0
    with sqlite3.connect(uri, uri=True) as db:
        for codec, payload in db.execute('SELECT codec, payload FROM chunks'):
            if codec != 'raw':
                unparsed += 1
                continue
            try:
                value = json.loads(bytes(payload))
            except (ValueError, UnicodeDecodeError):
                unparsed += 1
                continue
            if type(value) is dict and 'cumulative_leaf_units' in value:
                key = value.get('logical_cell_id') or value.get('cell_id') or len(found)
                found[key] = value
    return found, unparsed


def quantiles(values, points=(.5, .9, .99, 1.)):
    ordered = sorted(values)
    return [ordered[min(len(ordered)-1, int(p*(len(ordered)-1)))] for p in points]


def main():
    stores = {}
    for item in sys.argv[1:]:
        label, path = item.split('=', 1)
        stores[label], unparsed = records(path)
        leaves = [row['cumulative_leaf_units'] for row in stores[label].values()]
        queries = sum(row.get('query_count', 0) for row in stores[label].values())
        print(f'{label:8s} records {len(leaves):5d} leaves {sum(leaves):9d} mean {sum(leaves)/max(1, len(leaves)):8.1f} '
              f'p50/p90/p99/max {quantiles(leaves) if leaves else None} queries {queries} unparsed_chunks {unparsed}')
    labels = list(stores)
    if len(labels) >= 2:
        first, *others = labels
        for other in others:
            shared = set(stores[first]) & set(stores[other])
            if not shared:
                print(f'{first} vs {other}: no shared record keys (keys are identity-bound)')
                continue
            ratio = [stores[other][k]['cumulative_leaf_units']/max(1, stores[first][k]['cumulative_leaf_units'])
                     for k in shared]
            print(f'{first} vs {other}: {len(shared)} shared keys, leaf ratio p50/p90/max {quantiles(ratio, (.5, .9, 1.))}')


if __name__ == '__main__':
    main()
