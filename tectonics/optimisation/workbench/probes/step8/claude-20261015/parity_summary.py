"""Summarise parity.json: identities equal, and old vs new route costs.

Usage: python -B parity_summary.py PARITY_JSON
"""
import json
import sys


def main():
    with open(sys.argv[1], encoding='utf-8') as f:
        result = json.load(f)
    print('small_import_bytes', result['small_import_bytes'])
    for seam in result['seams']:
        if seam['seam'] == 'compose' and 'old' in seam:
            print(f"compose {seam['holder']:<16} logical={seam['logical_bytes']:>10} equal={seam['identity_equal']} "
                  f"borrowed={seam['borrowed_keys']}")
        elif seam['seam'] == 'publish':
            print(f"publish kinds={seam['kinds']} v2={seam['v2_kinds']} equal={seam['identity_equal']}")
            print(f"        logical={seam['logical_bytes']}")
        else:
            print('seam', seam)
            continue
        for route in ('old', 'new'):
            row = seam[route]
            print(f"   {row['route']:<14} {row['seconds']:8.3f}s builder_peak={row['builder_peak_bytes']:>11} "
                  f"retained_delta={row['retained_delta_bytes']:>10} rss_delta={row['rss_delta_bytes']:>10} "
                  f"store_growth={row.get('store_growth_bytes', '-')} builders={len(row['builders'])}")


if __name__ == '__main__':
    main()
