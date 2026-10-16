"""Hotspots of the compact partition support path (test_live_partition.measure).

Usage: python -B profile_partition_support.py MODE COUNT OUT.txt
MODE is candidate or baseline. Runs the existing matched measurement under
cProfile (attribution only; cProfile inflates absolute times, so no timing
claim is taken from it) with the fixture's temporary runtime copy placed in
R/L instead of T, so every write stays inside R.
"""
import cProfile
import io
import pstats
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
C = R/'compact-geometry-r1'
I = R.parent/'runtime-integration-r1'/'runtime-src'


def main():
    mode, count, out = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
    sys.path[:0] = [str(C), str(R), str(I)]
    import test_partition_native_patch as F
    # parents[4] of this stand-in is R/L: the fixture's transient copy lives there.
    F.HERE = R/'L'/'p1'/'p2'/'p3'/'p4'/'p5'
    (R/'L').mkdir(exist_ok=True)
    import test_live_partition as TLP
    TLP.setUpModule()
    try:
        profile = cProfile.Profile()
        profile.enable()
        result = TLP.measure(mode, count)
        profile.disable()
    finally:
        TLP.tearDownModule()
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative')
    stats.print_stats(45)
    stream.write('\n\n==== by internal time ====\n')
    stats.sort_stats('tottime').print_stats(35)
    out.write_text(f"mode={mode} count={count} wall_under_profile={result['wall_seconds']:.3f}s "
                   f"partition_id={result['partition_id']}\n\n"+stream.getvalue(), encoding='utf8')
    print(out)


if __name__ == '__main__':
    main()
