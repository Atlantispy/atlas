"""Read-only: one line per entry of a compare_trees.py report (differing files, then one-side-only files).

Usage: python -B summarise_tree_diff.py REPORT_JSON [SUBSTRING ...]
With SUBSTRINGs, only file names containing one of them are listed.
"""
import json
import sys


def main():
    report = json.loads(open(sys.argv[1], encoding='utf8').read())
    wanted = sys.argv[2:]

    def shown(name):
        return not wanted or any(text in name for text in wanted)
    print(f"a {report['files_a']} files, b {report['files_b']} files; differ {len(report['differ'])}, "
          f"only a {len(report['only_a'])}, only b {len(report['only_b'])}")
    for name, (left, right) in report['differ'].items():
        if shown(name):
            print(f'  differ  {name}  {left} -> {right}')
    for side in ('only_a', 'only_b'):
        names = [name for name in report[side] if shown(name)]
        if names:
            print(f'  {side}: '+' '.join(names))


if __name__ == '__main__':
    main()
