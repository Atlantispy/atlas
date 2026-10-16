"""Recreate a pre-edit base copy for the Ruff pair gate by removing one added block.

Usage: python -B base_without_block.py CURRENT OUT START_LINE_TEXT END_LINE_TEXT EXPECTED_SHA256_PREFIX

Removes the lines from the first line equal to START_LINE_TEXT (plus the one
blank line before it) through the next line equal to END_LINE_TEXT, writes the
rest to OUT (exclusive) and refuses unless its SHA-256 starts with the expected
prefix, so the base is exactly the earlier recorded file.
"""
import hashlib
import sys
from pathlib import Path


def main():
    current, out, start, end, prefix = sys.argv[1:6]
    trailing = len(sys.argv) > 6 and sys.argv[6] == '--trailing-blanks'
    lines = Path(current).read_bytes().split(b'\n')
    first = lines.index(start.encode())
    last = lines.index(end.encode(), first)
    if trailing:
        # A block added before an existing definition: drop the blank separators after it.
        while last+1 < len(lines) and lines[last+1] == b'':
            last += 1
    elif first and lines[first-1] == b'':
        first -= 1
    base = b'\n'.join(lines[:first]+lines[last+1:])
    digest = hashlib.sha256(base).hexdigest()
    if not digest.startswith(prefix):
        raise SystemExit('reconstructed base differs from the recorded file: '+digest)
    with open(out, 'xb') as stream:
        stream.write(base)
    print(out, digest)


if __name__ == '__main__':
    main()
