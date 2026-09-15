"""Reuse immutable R3-bound R2 persistence primitives; never import R3 capture.

Both predecessor release indices and source closures are checked on every
dependency verification. This module owns no output or authority directory.
"""
import hashlib

import r3_bindings


_r3_io = r3_bindings.bound_module('r2_io')
io = _r3_io.io


def _receipt_pin(path, expected, name):
    data = io.read_bytes(path)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError('frozen predecessor release identity changed: '+name)
    return {'name':name, 'bytes':len(data), 'sha256':actual}


def verify_dependencies():
    r3_receipt = _receipt_pin(r3_bindings.INDEX, r3_bindings.INDEX_SHA256,
                             'R3/REFERENCE_VERIFICATION.json')
    r2_receipt = _receipt_pin(_r3_io.INDEX, _r3_io.INDEX_SHA256,
                             'R2/REFERENCE_VERIFICATION.json')
    closure = r3_bindings.verify_predecessor()
    r3_files = [{'name':'R3/'+name, **row} for name,row in sorted(closure.items())]
    return [r3_receipt,r2_receipt,*r3_files,*_r3_io.verify_dependencies()]


verify_dependencies()
