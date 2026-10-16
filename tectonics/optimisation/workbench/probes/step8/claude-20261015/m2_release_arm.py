"""Same-call heat control layout with RELEASE_SOLVE_RESULT set explicitly (A/B arm).

Usage: python -B m2_release_arm.py LAYOUT_DIR LIVE_MEMORY(0|1) RELEASE(0|1)
Sets the test-only live_spatial_patch.RELEASE_SOLVE_RESULT switch, then runs
step7_same_call_heat_control.prepare unchanged, so the composed issuer either
keeps or omits the post-projection release; everything else is identical.
Run the control's own `--child LAYOUT_DIR OUT.json` afterwards.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = HERE.parents[2]/'compact-geometry-r1'


def main():
    # The same order step7_same_call_heat_control.prepare uses.
    R = C.parent
    sys.path[:0] = [str(R.parent/'runtime-integration-r1'/'runtime-src'), str(R),
                    str(R/'endpoint-checkpoints'), str(C)]
    import live_spatial_patch as LIVE
    import step7_same_call_heat_control as M2
    LIVE.RELEASE_SOLVE_RESULT = sys.argv[3] == '1'
    M2.prepare(Path(sys.argv[1]), sys.argv[2] == '1')
    print('release_solve_result', LIVE.RELEASE_SOLVE_RESULT)


if __name__ == '__main__':
    main()
