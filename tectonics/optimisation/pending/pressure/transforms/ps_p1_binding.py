"""T/ps P1: the batch binding accepts pressure-wall requests (integration_parallel_binding.py).

request_fields gains one branch, first, for schema 'atlas.private.pressure-wall.r1'.
That request shape is checked by integration_pressure_walls.check_request, which the
parent also runs when binding and the worker runs before computing. Every other request
takes the unchanged path: the branch matches only that schema value.
Stacks on Exact kernels' initpar_r1 output (anchor: the docstring line only).
Record identity: no record carries this module; execution identity changes (D-b).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '70db056ac59c4ebb06a66c72f12eabf99f0cdbb645434928f75a356c09e6310e': 'RC1 = composed-r2 = workers6-r6',
    '4eb627dc4e8cac50ceae74413c44c770974f21d55e0d19ea72172a41e74e0529': 'T/ck initpar_r1 output',
}
OLD = '    """Exactly one supported request shape; walls are full-interval rigid flux."""\n'
NEW = (OLD +
       '    if type(request) is dict and request.get(\'schema\') == \'atlas.private.pressure-wall.r1\':\n'
       '        # T/ps P1: the pressure-wall shape is checked by its own module.\n'
       '        from .integration_pressure_walls import check_request\n'
       '        return check_request(request)\n')


def transform(source, *, allow_unreviewed_input=False):
    if 'atlas.private.pressure-wall.r1' in source:
        raise ValueError('P1 binding hook already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('parallel binding input is not a reviewed module')
    if source.count(OLD) != 1:
        raise ValueError('P1 binding anchor must occur exactly once')
    return source.replace(OLD, NEW)
