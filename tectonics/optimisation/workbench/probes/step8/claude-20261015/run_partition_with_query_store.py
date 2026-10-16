"""Run a w1a compact-parent test module with a chosen endpoint companion.

Usage: python -B run_partition_with_query_store.py SECONDS MODE test.name [...]
MODE reviewed: replace the composed companion with the reviewed bytes 4a835dc3
(R/composed-r1, read only; hash-checked), as assemble_resumable records it.
MODE query-store: keep WP10's live companion and add its compact_query_store.py
(16 Oct 00:50: refused, the two modules import each other circularly).

R/endpoint-checkpoints/integration_endpoint_checkpoints.py (WP10's, changed
15 Oct 19:45, now 9b6f2fe1) imports .compact_query_store, which the staged seam
test_geometry_transfer_compact composes from does not emit, so the two w1a test
modules cannot set up against WP10's in-progress companion. This disposable
wrapper composes exactly as that test does and then swaps only the companion
inside the temporary package. No file outside the temporary package changes.
"""
import faulthandler
import hashlib
import os
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
QUERY_STORE = R/'endpoint-checkpoints'/'compact_query_store.py'
REVIEWED = R/'composed-r1'/'runtime-src'/'atlas_tectonics'/'integration_endpoint_checkpoints.py'
REVIEWED_PREFIX = '4a835dc3'


def main():
    seconds, mode = float(sys.argv[1]), sys.argv[2]
    if mode not in ('reviewed', 'query-store'):
        raise SystemExit('MODE must be reviewed or query-store')
    os.chdir(C)
    sys.path[:0] = [str(C), str(R)]
    import test_geometry_transfer_compact as GC
    original = GC.compose

    def compose(package, PN):
        stages = original(package, PN)
        companion = package/'integration_endpoint_checkpoints.py'
        if mode == 'reviewed':
            raw = REVIEWED.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if not digest.startswith(REVIEWED_PREFIX):
                raise RuntimeError('reviewed companion copy changed: '+digest)
            print('wrapper replaced companion', hashlib.sha256(companion.read_bytes()).hexdigest()[:8],
                  'with reviewed', digest, flush=True)
            companion.write_bytes(raw)
        elif 'from .compact_query_store import' in companion.read_text(encoding='utf8'):
            shutil.copyfile(QUERY_STORE, package/'compact_query_store.py')
            print('wrapper added compact_query_store.py sha256',
                  hashlib.sha256(QUERY_STORE.read_bytes()).hexdigest(), flush=True)
        return stages

    GC.compose = compose
    faulthandler.dump_traceback_later(seconds, exit=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[3:])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    faulthandler.cancel_dump_traceback_later()
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
