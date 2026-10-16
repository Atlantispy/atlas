"""Read-only check of width_gate's streamed scanner on the real r9 IV1 records.

Usage: python -B validate_width_gate.py OUT_JSON

Streams the authenticated census records (heat:metadata_utf8, spatial-record:mesh,
root:spatial-record:mesh) from the reviewed ORIGINAL through
historical_admission.open_original_readonly (query-only), feeds the chunks to
width_gate.WidthTable, and compares every field's widest bits and pair count with
the reviewed structural census (structure-census-r3). It also records the scan
throughput and the trajectory step counts. Nothing is written except OUT_JSON.
"""
import json
import sys
import time
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[3]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'
RECORDS = ('heat:metadata_utf8', 'spatial-record:mesh', 'root:spatial-record:mesh')


def main():
    out = Path(sys.argv[1])
    sys.path[:0] = [str(C), str(R), str(I)]
    import historical_admission as H
    import measure_live_capacity as CAP
    import width_gate as G
    from atlas_tectonics.resources import WorkBudget
    from atlas_tectonics.storage import Compression, StoreLimits
    value = CAP.read_census()
    census = value['census']
    endpoint = census['endpoint']
    budget = WorkBudget(4 << 30)
    result = {'records': {}, 'checks': [], 'census_sha256': CAP.CENSUS_SHA256}
    with H.open_original_readonly(limits=StoreLimits(**endpoint['store_limits']),
                                  compression=Compression(**endpoint['store_compression']),
                                  budget=budget) as source:
        for name in RECORDS:
            binding = census['records'][name]
            table, digest, size = G.WidthTable(name), sha256(), 0
            scanner = G.StreamScanner()
            started = time.perf_counter()
            for _, chunk in source.iter_chunks(binding['snapshot'], binding['array'], budget=budget):
                block = memoryview(chunk).cast('B')
                digest.update(block)
                size += len(block)
                scanner.feed(block)
            fields = scanner.finish()
            seconds = time.perf_counter()-started
            if digest.hexdigest() != binding['sha256'] or size != binding['filebytes']:
                raise SystemExit('record differs from its census binding: '+name)
            table.records[name] = fields
            result['records'][name] = {'bytes': size, 'seconds': round(seconds, 3),
                                       'mb_per_second': round(size/seconds/1e6, 1),
                                       'trajectory_steps': scanner.trajectory_steps, 'fields': fields}
            for entry in binding['fields']:
                strings = entry.get('rational_strings') or {}
                if not strings.get('count'):
                    continue
                bits = max(strings['max_numerator_bits'], strings['max_denominator_bits'])
                match = [key for key, row in fields.items()
                         if max(row['max_numerator_bits'], row['max_denominator_bits']) == bits
                         and row['count'] == strings['pair_count']]
                result['checks'].append({'record': name, 'census_bits': bits, 'census_pairs': strings['pair_count'],
                                         'scanner_fields': match, 'ok': len(match) >= 1})
            print(name, size, 'bytes', round(seconds, 1), 's', flush=True)
    result['all_ok'] = all(check['ok'] for check in result['checks'])
    out.write_text(json.dumps(result, indent=1), encoding='utf8')
    for check in result['checks']:
        print(check)
    print('all_ok', result['all_ok'])


if __name__ == '__main__':
    main()
