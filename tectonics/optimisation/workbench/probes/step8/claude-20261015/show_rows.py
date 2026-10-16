"""Print full audit rows by id from workflow results JSON.

Usage: python -B show_rows.py RESULTS.json id [id ...]
"""
import json
import sys


def main():
    with open(sys.argv[1], encoding='utf-8') as f:
        results = json.load(f)
    wanted = set(sys.argv[2:])
    sys.stdout.reconfigure(encoding='utf-8')
    for label, result in results.items():
        if isinstance(result, dict) and 'rows' in result:
            for row in result['rows']:
                if row['id'] in wanted or 'all' in wanted:
                    print('=' * 100)
                    print(f"[{label}] {row['id']} ({row['source']}): {row['status']}")
                    for key in ('evidence', 'remaining_work', 'other_writer_files',
                                'exception_lifetime_note', 'measurement_needed'):
                        value = row.get(key)
                        if isinstance(value, list):
                            print(f"-- {key}:")
                            for item in value:
                                print('   *', item)
                        else:
                            print(f"-- {key}: {value}")


if __name__ == '__main__':
    main()
