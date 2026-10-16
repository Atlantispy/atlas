"""Print chosen per-stage fields for every route label in a comparison JSON.

Usage: python -B stage_fields.py COMPARISON.json STAGE[,STAGE...] FIELD[,FIELD...]
Fields are those in compare_guarded_routes.py by_route stages (mean values);
byte fields are shown in MB, seconds as s.
"""
import json
import sys


def main():
    report = json.loads(open(sys.argv[1], encoding='utf-8').read())
    stages, fields = sys.argv[2].split(','), sys.argv[3].split(',')
    for label, route in sorted(report['by_route'].items()):
        short = label if len(label) < 60 else label[:57]+'...'
        print('==', short, 'repeats', route['repeats'])
        for stage in stages:
            row = route['stages'].get(stage, {})
            cells = []
            for field in fields:
                span = row.get(field)
                if span is None:
                    cells.append(field+'=-')
                elif field.endswith('seconds'):
                    cells.append('%s=%.3fs' % (field, span['mean']))
                else:
                    cells.append('%s=%.2fMB' % (field, span['mean']/1e6))
            print('  ', stage.ljust(28), ' '.join(cells))


if __name__ == '__main__':
    main()
