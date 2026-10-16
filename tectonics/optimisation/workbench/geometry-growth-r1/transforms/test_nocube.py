"""TEST-ONLY attribution switch: disable RC1's approved positive-cuboid (loose witness) stop.

Never composed into a production runtime. Used only to attribute RC1-versus-r7
endpoint differences on saved IV1 queries for the interval-1 difference ledger.
"""
OLD = ('    loose_witness = (positive_witness and relative_error is None and\n'
       '                     width >= 2*cell.volume_m3)\n')
NEW = '    loose_witness = False  # TEST-ONLY: cuboid stop disabled for attribution\n'


def transform(source):
    if source.count(OLD) != 1:
        raise ValueError('cuboid anchor must occur exactly once')
    return source.replace(OLD, NEW)
