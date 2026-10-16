"""Run unittest names with a candidate folder's modules ahead of the compact-geometry helpers.

Usage: python -B run_with.py CANDIDATE_DIR HELPERS_DIR NAME [NAME...]
HELPERS_DIR is compact-geometry-r1 (its parent and ../runtime-integration-r1/runtime-src follow it).
Prints the loaded spatial_validation_patch and test module files with their sha256 prefixes,
then the unittest result. Exit 1 on any failure. Writes nothing.
"""
import hashlib
import os
import sys
import unittest
from pathlib import Path


def sha8(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]


def main():
    candidate, helpers = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    # The helpers' own test layout: the runtime source and the helpers' parent, as
    # test_spatial_compact_cells inserts them (after the candidate and the helpers).
    runtime = helpers.parent.parent/'runtime-integration-r1'/'runtime-src'
    sys.path[:0] = [str(candidate), str(helpers), str(helpers.parent), str(runtime)]
    os.chdir(helpers)
    import spatial_validation_patch as V
    print('loaded spatial_validation_patch', V.__file__, sha8(V.__file__), flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[3:])
    for name in sorted({n.split('.')[0] for n in sys.argv[3:]}):
        print('loaded', name, sys.modules[name].__file__, sha8(sys.modules[name].__file__), flush=True)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
