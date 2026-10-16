"""One-off: extract the small grid part of a partition file for replay shards (memory rule, 16 Oct).

replay_surfaces.py needs only native_cells, grid_lines, grid_origin_m and grid_basis from a
partition, but parsing the whole interval-2 RC1 partition JSON costs about 4 GB per process.
This reads a partition file ONCE (run it alone) and writes {"partition": {those four keys},
"grid_only": true, "source_sha256": <sha256 of the partition file>} as gzip JSON.
Usage: make_grid_file.py PARTITION.json.gz OUT.grid.json.gz
"""
import gzip
import json
import sys
from hashlib import sha256
from pathlib import Path

KEYS = ('native_cells', 'grid_lines', 'grid_origin_m', 'grid_basis')


def main():
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    if out.exists():
        raise SystemExit('output exists')
    raw = source.read_bytes()
    digest = sha256(raw).hexdigest()
    partition = json.loads(gzip.decompress(raw))['partition']
    del raw
    grid = {k: partition[k] for k in KEYS}
    del partition
    body = json.dumps(dict(partition=grid, grid_only=True, source_sha256=digest,
                           source=str(source).replace('\\', '/')), separators=(',', ':')).encode()
    with open(out, 'xb') as f:
        f.write(gzip.compress(body))
    print(json.dumps(dict(out=str(out), source_sha256=digest, bytes=out.stat().st_size,
                          native_cells=len(grid['native_cells']))))


if __name__ == '__main__':
    main()
