"""Per-put store figures of a capacity run against the plan's targets.

Usage: python -B audit_store_limits.py CAPACITY_DIR [CAPACITY_DIR ...]
Collects every published segment reference recorded in capacity.json (any
dict carrying identity, logical_bytes and root_key), then reports the largest
put's logical bytes and its 64 KiB chunk count against the plan section 4
targets (128 MiB, 25% of the 512 MiB array put; 2,048 chunk references), and
the candidate's manifest statistics where the run recorded them (256 KiB per
manifest target). The interval store itself refuses any put or manifest above
these targets at write time (interval_store_set.put_manifest), so this audit
reports the actual maxima and the margin, not a pass the store did not check.
"""
import json
import sys
from pathlib import Path

TARGET_SEGMENT = 128 << 20
TARGET_CHUNKS = 2048
TARGET_MANIFEST = 256 << 10
CHUNK = 65536


def references(value, path=''):
    if isinstance(value, dict):
        if 'logical_bytes' in value and 'root_key' in value and 'identity' in value:
            yield path, value
        for key, item in value.items():
            yield from references(item, path+'/'+str(key))
    elif isinstance(value, list):
        for at, item in enumerate(value):
            yield from references(item, path+'['+str(at)+']')


def audit(directory):
    record = json.loads((Path(directory)/'capacity.json').read_text(encoding='utf8'))
    seen, rows = set(), []
    for path, ref in references(record):
        key = (ref['root_key'].get('snapshot_key'), ref['logical_bytes'])
        if key in seen:
            continue
        seen.add(key)
        rows.append((ref['logical_bytes'], -(-ref['logical_bytes']//CHUNK), ref['identity'].get('record_schema'), path))
    rows.sort(reverse=True)
    stats = record.get('candidate_statistics') or record.get('candidate_statistics_at_overlap') or {}
    out = {'directory': str(directory), 'status': record.get('status'), 'puts': len(rows),
           'largest_put_logical_bytes': rows[0][0] if rows else None,
           'largest_put_chunks': rows[0][1] if rows else None,
           'largest_put_schema': rows[0][2] if rows else None,
           'segment_target_bytes': TARGET_SEGMENT, 'chunk_target': TARGET_CHUNKS,
           'segment_margin_fraction': (1-rows[0][0]/TARGET_SEGMENT) if rows else None,
           'top_puts': [{'logical_bytes': b, 'chunks': c, 'schema': s, 'path': p} for b, c, s, p in rows[:8]],
           'candidate_statistics': stats,
           'mean_manifest_bytes': (stats['manifest_bytes']/stats['manifests']) if stats.get('manifests') else None,
           'manifest_target_bytes': TARGET_MANIFEST}
    return out


def main():
    print(json.dumps([audit(directory) for directory in sys.argv[1:]], indent=1))


if __name__ == '__main__':
    main()
