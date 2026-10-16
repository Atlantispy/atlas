"""Summarise sampled stacks from profile_mesh_pack.py.

Usage: python -B stack_summary.py STACKS.json [DEPTH]
Each sample is a ' <- '-joined stack, innermost first. Prints the share of
samples per (a) innermost function and (b) each frame anywhere in the stack
(inclusive time), plus the total sample count.
"""
import json
import sys
from collections import Counter


def main():
    rows = json.loads(open(sys.argv[1], encoding='utf-8').read())
    depth = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    total = sum(count for _, count in rows)
    inner, inclusive = Counter(), Counter()
    for stack, count in rows:
        frames = stack.split(' <- ')[:depth]
        inner[frames[0].split(' ', 1)[1] + ' @ ' + frames[0].split(' ', 1)[0]] += count
        for frame in set(f.split(' ', 1)[1] + ' @ ' + f.split(' ', 1)[0].rsplit(':', 1)[0] for f in frames):
            inclusive[frame] += count
    print('samples', total)
    print('-- innermost')
    for name, count in inner.most_common(15):
        print('%5.1f%%  %s' % (100*count/total, name))
    print('-- inclusive (any of the top %d frames)' % depth)
    for name, count in inclusive.most_common(25):
        print('%5.1f%%  %s' % (100*count/total, name))


if __name__ == '__main__':
    main()
