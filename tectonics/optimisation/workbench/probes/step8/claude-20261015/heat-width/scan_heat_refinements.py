"""Read-only: the LOW/HIGH sparse-solve diagnostics recorded in the real r9 IV1 heat record (WP25 evidence).

Usage: python -B scan_heat_refinements.py OUT_JSON

Streams heat:metadata_utf8 from the reviewed ORIGINAL through
historical_admission.open_original_readonly (query-only), checks its census SHA-256 and size,
and collects every occurrence, in byte order, of the sparse cores' recorded diagnostics:
refinements, residual_history, factor_seconds, factor_L_plus_U_nnz, factor_precision_bits and
high_backend. A 64 KiB overlap between chunks keeps a key and its value from being split.
Nothing is written except OUT_JSON.
"""
import json
import re
import sys
import time
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[3]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'
NAME = 'heat:metadata_utf8'
OVERLAP = 64 << 10
PATTERNS = {
    'refinements': re.compile(rb'"refinements":\s*(\d+)'),
    'residual_history': re.compile(rb'"residual_history":\s*\[([^\]]{0,4000})\]'),
    'factor_seconds': re.compile(rb'"factor_seconds":\s*([0-9.eE+-]+)'),
    'factor_L_plus_U_nnz': re.compile(rb'"factor_L_plus_U_nnz":\s*(\d+)'),
    'factor_precision_bits': re.compile(rb'"factor_precision_bits":\s*(\d+)'),
    'high_backend': re.compile(rb'"high_backend":\s*"([^"]{0,200})"'),
}


def main():
    out = Path(sys.argv[1])
    sys.path[:0] = [str(C), str(R), str(I)]
    import historical_admission as H
    import measure_live_capacity as CAP
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    census = CAP.read_census()['census']
    endpoint, binding = census['endpoint'], census['records'][NAME]
    budget = WorkBudget(4 << 30)
    found = {key: [] for key in PATTERNS}
    digest, size, tail, base = sha256(), 0, b'', 0
    started = time.perf_counter()
    with H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
                                  compression=Compression(**endpoint['store_compression']),
                                  budget=budget) as source:
        for _, chunk in source.iter_chunks(binding['snapshot'], binding['array'], budget=budget):
            block = bytes(memoryview(chunk).cast('B'))
            digest.update(block)
            window = tail+block
            for key, pattern in PATTERNS.items():
                for match in pattern.finditer(window):
                    offset = base+match.start()
                    # A match wholly inside the previous overlap was already taken.
                    if match.end() <= len(tail):
                        continue
                    found[key].append((offset, match.group(1).decode('ascii', 'replace')))
            size += len(block)
            tail = window[-OVERLAP:]
            base = size-len(tail)
    seconds = time.perf_counter()-started
    if digest.hexdigest() != binding['sha256'] or size != binding['filebytes']:
        raise SystemExit('record differs from its census binding')
    result = {'record': NAME, 'bytes': size, 'sha256': binding['sha256'], 'seconds': round(seconds, 2),
              'occurrences': {key: [{'offset': offset, 'value': value} for offset, value in rows]
                              for key, rows in found.items()}}
    out.write_text(json.dumps(result, indent=1), encoding='utf8')
    for key, rows in found.items():
        print(key, len(rows), [value[:120] for _, value in rows[:12]])


if __name__ == '__main__':
    main()
