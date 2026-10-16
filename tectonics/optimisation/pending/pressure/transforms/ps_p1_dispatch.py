"""T/ps P1: the batch worker routes pressure-wall batches (integration_parallel_dispatch.py).

_batch_worker gains one branch right after the validated binding's requests are read: a
batch of schema 'atlas.private.pressure-wall.r1' goes to
integration_pressure_walls.batch_worker. That function loads its own digest-checked
inputs and answers through the same batch_worker_complete and resource report. Every
other batch takes the unchanged path: the branch matches only that schema value.
Record identity: no record carries this module; execution identity changes (D-b).
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '2545cb43b9dfac6a47b8b6c99147206c3542ea945bdde460534bf37043347782': 'RC1 = composed-r2 = workers6-r6',
}
OLD = ('    requests = BatchBinding(binding_bytes).record()[\'requests\']\n'
       '    wall = requests[0].get(\'kind\') == WALL_KIND\n')
NEW = ('    requests = BatchBinding(binding_bytes).record()[\'requests\']\n'
       '    if requests[0].get(\'schema\') == \'atlas.private.pressure-wall.r1\':\n'
       '        # T/ps P1: pressure walls load and answer their own digest-checked inputs.\n'
       '        from .integration_pressure_walls import batch_worker\n'
       '        return batch_worker(directory, process, binding_bytes, requests)\n'
       '    wall = requests[0].get(\'kind\') == WALL_KIND\n')


def transform(source, *, allow_unreviewed_input=False):
    if 'atlas.private.pressure-wall.r1' in source:
        raise ValueError('P1 dispatch hook already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('parallel dispatch input is not the reviewed module')
    if source.count(OLD) != 1:
        raise ValueError('P1 dispatch anchor must occur exactly once')
    return source.replace(OLD, NEW)
