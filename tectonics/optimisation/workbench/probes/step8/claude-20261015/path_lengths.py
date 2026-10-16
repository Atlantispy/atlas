"""Windows path lengths of the catalog temporary file in given folders.

Usage: python -B path_lengths.py FOLDER [FOLDER ...]
publish_catalog writes <folder>/catalog.json.tmp-<32 hex> (32 hex = uuid4().hex).
Without long-path support the usable limit is 259 characters (MAX_PATH 260
including the terminator). Read-only.
"""
import sys
from pathlib import Path


def main():
    for folder in sys.argv[1:]:
        path = str(Path(folder).resolve()/('catalog.json.tmp-'+'0'*32))
        print(len(path), 'OK' if len(path) <= 259 else 'TOO LONG', path[-80:])


if __name__ == '__main__':
    main()
