"""Rebuild the pre-edit live_spatial_patch.py by reversing the 16 Oct release edit.

Usage: python -B reconstruct_before.py EXPECTED_SHA256 OUT.py
Reverses exactly the three textual changes of the RELEASE_SOLVE_RESULT edit
and writes OUT only if the result hashes to EXPECTED_SHA256 (the 00:47 R hash
snapshot), so the before copy is proven, not assumed.
"""
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]/'compact-geometry-r1'/'live_spatial_patch.py'

NEW_HEAD = '''def issuer_source(source):
    """End the original call-list lifetime once projection owns its capture.

    Under RELEASE_SOLVE_RESULT the forward solve's result owner also closes
    right after projection instead of after packaging: projection's private
    verification decoded its own independent copy and diagnostics are never
    read, so only a lifetime ends; no value, ID or account changes.
    """
    release = ('        # The solve result and its unread diagnostics end here: projection\\n'
               '        # verified and decoded its own independent copy (verified_private).\\n'
               '        del produced, diagnostics\\n'
               '        numerical_owner.close()\\n') if RELEASE_SOLVE_RESULT else ''
    source = _once(source,
        '            cancel=cancel, record_scope=HEAT_LEDGER.verify_scope(call))\\n        with projection_owner:\\n',
        '            cancel=cancel, record_scope=HEAT_LEDGER.verify_scope(call))\\n'
        '        del values\\n'+release+
        '        with projection_owner:\\n')
    if RELEASE_SOLVE_RESULT:
        source = _once(source,
            '            del produced, diagnostics, projected, private, record, fixed, powers, actual_fixed, actual_power\\n',
            '            del projected, private, record, fixed, powers, actual_fixed, actual_power\\n')
'''
OLD_HEAD = '''def issuer_source(source):
    """End the original call-list lifetime once projection owns its capture."""
    source = _once(source,
        '            cancel=cancel, record_scope=HEAT_LEDGER.verify_scope(call))\\n        with projection_owner:\\n',
        '            cancel=cancel, record_scope=HEAT_LEDGER.verify_scope(call))\\n'
        '        del values\\n'
        '        with projection_owner:\\n')
'''
NEW_SWITCH = '''STREAM_CELLS = True
# Step 8 (inventory rows handoff-4, heat-ledger): the heat issuer closes the
# forward solve's result owner (solve result and unread diagnostics) right
# after projection instead of holding it through compact packaging and the
# checkpoint save. Lifetime only. Test-only switch, captured like the above.
RELEASE_SOLVE_RESULT = True'''
OLD_SWITCH = 'STREAM_CELLS = True'


def main():
    expected, out = sys.argv[1], Path(sys.argv[2])
    text = SOURCE.read_bytes().decode('utf8')
    for new, old in ((NEW_HEAD, OLD_HEAD), (NEW_SWITCH, OLD_SWITCH)):
        if text.count(new) != 1:
            raise SystemExit('edit not found exactly once')
        text = text.replace(new, old)
    actual = sha256(text.encode('utf8')).hexdigest()
    if actual != expected:
        raise SystemExit('reconstruction differs: '+actual)
    out.write_bytes(text.encode('utf8'))
    print('reconstructed', actual, '->', out)


if __name__ == '__main__':
    main()
