"""Step 10 composition check: the composed interval writer reproduces today's legacy bytes.

Usage: python -B check_legacy_encode.py COMPOSED_ROOT FIXTURE_DIR WORK_DIR [--mutant-blocked-blosc2]

COMPOSED_ROOT holds the composed package as src/atlas_tectonics/ and the helper modules in
helpers/ (the route (1) layout). FIXTURE_DIR holds index.json + chunks.bin (real chunks of the
IV1-scale sealed file, with the stored codec label and payload sha256 of each row). WORK_DIR
must be a new empty directory; only it is written.

For every fixture chunk: put_chunk(descriptor, raw) on a fresh interval candidate created
from the COMPOSED interval_store_set (no codec policy), then the stored row must carry the
same codec label and payload sha256 as the sealed file's row, and the same chunk id. Before
that, the check proves interval_store_set and atlas_tectonics.storage were imported from
COMPOSED_ROOT (a wrong path or a missing module would otherwise test the wrong code).

Coordinator, 16 Oct 2026 ~10:10, after WP0c: blocking Blosc2 on the no-rule path costs +16%
disk at IV1 (about +540 MB per interval at IV3); this check must make that unreachable
through a wrong pin or a missing module. --mutant-blocked-blosc2 forces the candidate's
compression to palette/RLE/uniform-else-raw (what the pre-follow-up WP10 no-rule path did)
and must FAIL; it shows the check detects the regression.
Exit 0 with 'legacy-encode-check-pass' only when every chunk matches (normal mode), or with
'legacy-encode-mutant-detected' when the mutant is caught.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    mutant = '--mutant-blocked-blosc2' in sys.argv[1:]
    root, fixture, work = (Path(a).resolve() for a in args[:3])
    if work.exists() and any(work.iterdir()):
        raise SystemExit('work directory must be new or empty')
    work.mkdir(parents=True, exist_ok=True)
    src, helpers = root / 'src', root / 'helpers'
    sys.path[:0] = [str(helpers), str(src)]
    sys.dont_write_bytecode = True
    import atlas_tectonics.storage as native
    import interval_store_set as I
    from atlas_tectonics.resources import WorkBudget
    from content_cache import create_retained_scope
    for module in (native, I):
        path = Path(module.__file__).resolve()
        if not path.is_relative_to(root):
            raise SystemExit(f'{module.__name__} was not imported from the composed root: {path}')
    index = json.loads((fixture / 'index.json').read_text(encoding='utf8'))
    blob = (fixture / 'chunks.bin').read_bytes()
    if sha256(blob).hexdigest() != index['chunks_bin_sha256']:
        raise SystemExit('fixture chunks.bin differs from its index')
    budget = WorkBudget(512 << 20)
    scope = create_retained_scope(budget, process_epoch='step10-legacy-encode-check')
    stores = I.IntervalStoreSet.create_migration(work / 'catalog.json', workflow_id='a' * 64, scope=scope)
    candidate = stores.begin_interval(None, producer_identity='b' * 64, runtime_identity='c' * 64)
    if mutant:
        candidate.compression = native.Compression(codec='raw', palette=True, categorical='auto')
    mismatches = []
    try:
        for row in index['chunks']:
            raw = blob[row['offset']:row['offset'] + row['length']]
            if sha256(raw).hexdigest() != row['raw_sha256']:
                raise SystemExit('fixture chunk bytes differ: ' + row['chunk_id'])
            descriptor = row['descriptor'].encode('ascii')
            _owner, chunk_id = candidate.put_chunk(descriptor, raw)
            codec, payload = candidate._db.execute('SELECT codec, payload FROM chunks WHERE id=?',
                                                   (chunk_id,)).fetchone()
            got = (chunk_id, codec, sha256(payload).hexdigest())
            want = (row['chunk_id'], row['expected_codec'], row['expected_payload_sha256'])
            if got != want:
                mismatches.append(dict(chunk=row['chunk_id'], family=row['family'], cls=row['record'] + '/' + row['array'],
                                       want_codec=want[1], got_codec=got[1], want_bytes=row['expected_payload_bytes'],
                                       got_bytes=len(payload)))
    finally:
        candidate.close()
        stores.close()
        scope.close()
    summary = dict(chunks=len(index['chunks']), mismatches=len(mismatches), families=index['families'],
                   storage=str(Path(native.__file__).resolve()), interval_store_set=str(Path(I.__file__).resolve()),
                   mutant=mutant)
    print(json.dumps(summary, indent=1))
    for m in mismatches[:10]:
        print(json.dumps(m))
    if mutant:
        if not mismatches:
            raise SystemExit('MUTANT NOT DETECTED: blocked-Blosc2 compression reproduced every row')
        print('legacy-encode-mutant-detected')
        return
    if mismatches:
        raise SystemExit(f'LEGACY ENCODE DIFFERS on {len(mismatches)} of {len(index["chunks"])} real chunks')
    print('legacy-encode-check-pass')


if __name__ == '__main__':
    main()
