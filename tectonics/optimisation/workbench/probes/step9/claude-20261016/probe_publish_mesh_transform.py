"""Apply publish_mesh_patch.transform to the Step 10 chain's R3 output and to the smoke tree's
composed workflow; print input/output SHA-256 and the changed lines. Read-only.

Usage: python -B probe_publish_mesh_transform.py
"""
import difflib
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parents[2]
T = R.parents[3]
INPUTS = {
    'step10-chain-r3': T/'fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/r3/final/generated/gen_r3/'
                         'integration_regional_workflow.py',
    'smoke-s1': R/'s1/src/atlas_tectonics/integration_regional_workflow.py',
}


def main():
    sys.path[:0] = [str(R/'compact-geometry-r1'), str(R)]
    import publish_mesh_patch as P
    for label, path in INPUTS.items():
        raw = path.read_bytes()
        # The smoke tree was written with CRLF; the Step 10 chain text is LF, as the stage expects.
        source = raw.decode('utf8').replace('\r\n', '\n')
        result = P.transform(source)
        print('==', label, 'in', sha256(raw).hexdigest()[:8], 'out', sha256(result.encode('utf8')).hexdigest())
        for line in difflib.unified_diff(source.splitlines(), result.splitlines(), lineterm='', n=0):
            if line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
                print('   ', line[:150])
        try:
            P.transform(result)
        except P.PublishMeshRefused as error:
            print('    re-application refused:', error)


if __name__ == '__main__':
    main()
