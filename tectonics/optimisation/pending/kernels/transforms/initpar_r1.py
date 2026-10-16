"""Item 19 (T/ck initpar r1): the parallel route for the initial relative-error queries.

Source transforms of five RC1 runtime files, plus the new module
integration_initial_parallel.py (T/ck/initpar), which holds the pass, the
session subclass and the record validator. With no pass opened by a caller,
every transformed function runs exactly its original statements: the only
additions are a None default, a lookup that returns None, and branches keyed
on a request field the existing families never carry.

- integration_dual_geometry: measure_initial_component and
  cached_initial_component take a private `_volume=None`. Inside query(), a
  pass may supply the adopted DifferentialMeasure of exactly that call, in
  place of the unchanged G.component_volume_bounds(...) call; the record(),
  the checks, the diagnostics and the store payload are the original code's.
  cached_initial_component passes it only on a miss.
- integration_differential_geometry: enclose_initial_partition asks
  integration_initial_parallel.active() before its loop (relative-error
  queries only), hands the started pass to each measure call, and finishes
  it after the loop.
- integration_parallel_binding: a separate request family,
  INITIAL_VOLUME_REQUEST_FIELDS = VOLUME_REQUEST_FIELDS | {'relative_error'},
  start endpoint only. VOLUME_REQUEST_FIELDS and its check are unchanged.
- integration_parallel_results: records carrying relative_error are admitted
  by integration_initial_parallel.validated_initial_volume; claim_measure
  takes no certificate digests for either volume family.
- integration_component_volume_parallel: component_answers passes the
  request's relative error to the unchanged ComponentVolumeQueries.measure.
Record identity: every issued record and store byte is the original route's;
the source digests change (D-b).
"""
from hashlib import sha256

MARK = '# initpar r1 (T/ck/transforms/initpar_r1.py)'

# file -> (reviewed input sha256 -> where it comes from, replacements (old, new) each exactly once)
FILES = {
    'integration_dual_geometry.py': ({
        '67c4daec9108ef1368da187b2bdeb5d2cc4e7da259e981e1e484982d162d553b': 'composed-r2 src',
        'a48347c0f1d49f3f9d4a745700a553c5b7c2ea17a24e7faec566c09c91e90e69': 'gg/workers6-r6',
    }, (
        ('''\
def measure_initial_component(support, cell_id, *, relative_error, absolute_width_m3,
                              max_leaves_per_query, budget):
''', '''\
def measure_initial_component(support, cell_id, *, relative_error, absolute_width_m3,
                              max_leaves_per_query, budget, _volume=None):
'''),
        ('''\
        def query(target):
            result = G.component_volume_bounds(support, cell_id, endpoint='start',
                max_width_m3=target, max_leaves=max_leaves_per_query,
                positive_witness=True, budget=budget, relative_error=r).record()
''', '''\
        def query(target):
            ''' + MARK + ''': a worker's measure of exactly this call, adopted at
            # this serial position by an opened pass, else the unchanged call.
            adopted = None if _volume is None else _volume.claim(support, cell_id, raw,
                max_width_m3=target, max_leaves=max_leaves_per_query, relative_error=r, budget=budget)
            result = (G.component_volume_bounds(support, cell_id, endpoint='start',
                max_width_m3=target, max_leaves=max_leaves_per_query,
                positive_witness=True, budget=budget, relative_error=r) if adopted is None else adopted).record()
            adopted = None
'''),
        ('''\
def cached_initial_component(support, cell_id, *, relative_error, absolute_width_m3,
                             max_leaves_per_query, budget, store, context):
''', '''\
def cached_initial_component(support, cell_id, *, relative_error, absolute_width_m3,
                             max_leaves_per_query, budget, store, context, _volume=None):
'''),
        ('''\
            result = measure_initial_component(support, cell_id, relative_error=r,
                absolute_width_m3=width, max_leaves_per_query=max_leaves_per_query, budget=budget)
''', '''\
            result = measure_initial_component(support, cell_id, relative_error=r,
                absolute_width_m3=width, max_leaves_per_query=max_leaves_per_query, budget=budget,
                _volume=_volume)
'''),
    )),
    'integration_differential_geometry.py': ({
        'ee930406f8fa7a52652ed85afc257a90644fb05c385ff9be97261b215417c816': 'composed-r2 src',
        'b4d95389bb93cd19a515c7b0d5889206ae2e0cb82feb973bd86e0be34c28c102': 'gg/workers6-r6',
    }, (
        ('''\
    count = sum(len(s.record()['components']) for s in partition.supports)
    local_width = width/max(1, count)
    cells = []
''', '''\
    count = sum(len(s.record()['components']) for s in partition.supports)
    local_width = width/max(1, count)
    ''' + MARK + ''': None unless a caller opened a pass.
    prefetch = None
    if relative_error is not None:
        from .integration_initial_parallel import active as _initial_parallel
        prefetch = _initial_parallel()
        if prefetch is not None:
            prefetch = prefetch.start(partition, budget=budget, relative_error=relative_error,
                                      max_width_m3=local_width, max_leaves=max_leaves)
    cells = []
'''),
        ('''\
                reuse = {} if measurement_store is None else dict(store=measurement_store, context=measurement_context)
''', '''\
                reuse = {} if measurement_store is None else dict(store=measurement_store, context=measurement_context)
                if prefetch is not None:
                    reuse['_volume'] = prefetch
'''),
        ('''\
                cells[-1]['positive_witness_point_rule'] = measured['positive_witness_point_rule']
    result = dict(schema='atlas.differential-initial-bounds.v1', scope='initial-current',
''', '''\
                cells[-1]['positive_witness_point_rule'] = measured['positive_witness_point_rule']
    if prefetch is not None:
        prefetch.finish()
    result = dict(schema='atlas.differential-initial-bounds.v1', scope='initial-current',
'''),
    )),
    'integration_parallel_binding.py': ({
        '70db056ac59c4ebb06a66c72f12eabf99f0cdbb645434928f75a356c09e6310e': 'composed-r2 src = gg/workers6-r6',
    }, (
        ('''\
# This dispatch family is positive_witness=True, relative_error=None only.
# Its reviewed worker and serial-prefix hook enforce those unencoded constants.
''', '''\
# This dispatch family is positive_witness=True, relative_error=None only.
# Its reviewed worker and serial-prefix hook enforce those unencoded constants.
''' + MARK + ''': the initial-query family, start endpoint, with its exact
# relative error carried; positive_witness=True as above.
INITIAL_VOLUME_REQUEST_FIELDS = VOLUME_REQUEST_FIELDS | {'relative_error'}
'''),
        ('''\
    """Exactly one supported request shape; walls are full-interval rigid flux."""
    if type(request) is dict and request.get('schema') == VOLUME_SCHEMA:
''', '''\
    """Exactly one supported request shape; walls are full-interval rigid flux."""
    if type(request) is dict and request.get('schema') == VOLUME_SCHEMA and 'relative_error' in request:
        from .integration_parallel_results import _wall_scalar
        if (request.keys() != INITIAL_VOLUME_REQUEST_FIELDS
                or not _digest(request['support_id'])
                or not _digest(request['logical_cell_id'])
                or request['endpoint'] != 'start'
                or not _wall_scalar(request['time_s'])
                or not _wall_scalar(request['max_width_m3'])
                or request['max_width_m3'][0].startswith('-')
                or not _wall_scalar(request['relative_error'])
                or request['relative_error'][0].startswith('-')
                or type(request['max_leaves']) is not int or request['max_leaves'] < 1):
            raise ValueError('complete exact initial-volume request required')
        return INITIAL_VOLUME_REQUEST_FIELDS
    if type(request) is dict and request.get('schema') == VOLUME_SCHEMA:
'''),
    )),
    'integration_parallel_results.py': ({
        'f48cda05e182f226c67fe8abcedfb51e4e53360e3470f6ce1c015800d06154ea': 'composed-r2 src = gg/workers6-r6',
    }, (
        ('''\
from .integration_parallel_binding import (REQUEST_FIELDS, WALL_KIND, WALL_REQUEST_FIELDS,
    request_fields, VOLUME_SCHEMA, VOLUME_REQUEST_FIELDS)
''', '''\
from .integration_parallel_binding import (REQUEST_FIELDS, WALL_KIND, WALL_REQUEST_FIELDS,
    request_fields, VOLUME_SCHEMA, VOLUME_REQUEST_FIELDS, INITIAL_VOLUME_REQUEST_FIELDS)
'''),
        ('''\
        if record.get('schema') == VOLUME_SCHEMA:
            return _validated_volume(record, request, fit)
''', '''\
        if record.get('schema') == VOLUME_SCHEMA and 'relative_error' in record:
            ''' + MARK + '''
            from .integration_initial_parallel import validated_initial_volume
            return validated_initial_volume(record, request, fit)
        if record.get('schema') == VOLUME_SCHEMA:
            return _validated_volume(record, request, fit)
'''),
        ('''\
        digest_keys = (frozenset() if fields == VOLUME_REQUEST_FIELDS else
''', '''\
        digest_keys = (frozenset() if fields in (VOLUME_REQUEST_FIELDS, INITIAL_VOLUME_REQUEST_FIELDS) else
'''),
    )),
    'integration_component_volume_parallel.py': ({
        'fafc76fb866e37b5ea98b321bbd78a5e4ea75355e1aedef869401d936cf233df': 'composed-r2 src = gg/workers6-r6',
    }, (
        ('''\
                raw = queries.measure(request['logical_cell_id'], endpoint=request['endpoint'],
                    max_width_m3=G.W._decode(request['max_width_m3']), max_leaves=request['max_leaves'],
                    positive_witness=True)._json
''', '''\
                ''' + MARK + ''': the initial family carries its relative error.
                relative = G.W._decode(request['relative_error']) if 'relative_error' in request else None
                raw = queries.measure(request['logical_cell_id'], endpoint=request['endpoint'],
                    max_width_m3=G.W._decode(request['max_width_m3']), max_leaves=request['max_leaves'],
                    positive_witness=True, relative_error=relative)._json
'''),
    )),
}


def transform(name, source, *, allow_unreviewed_input=False):
    inputs, replacements = FILES[name]
    if MARK in source:
        raise ValueError('initpar r1 already applied to ' + name)
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in inputs:
        raise ValueError(name + ' is not a reviewed input')
    for old, _ in replacements:
        if source.count(old) != 1:
            raise ValueError('%s: anchor must occur exactly once: %r' % (name, old.splitlines()[0]))
    for old, new in replacements:
        source = source.replace(old, new)
    return source


if __name__ == '__main__':
    # python -B -I initpar_r1.py SRC_DIR DST_DIR: writes the five transformed files (DST must not hold them).
    import sys
    from pathlib import Path
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    for name in FILES:
        if (dst/name).exists():
            raise SystemExit('%s exists' % (dst/name))
    for name in FILES:
        before = (src/name).read_bytes()
        after = transform(name, before.decode('utf8')).encode('utf8')
        (dst/name).write_bytes(after)
        print(name, sha256(before).hexdigest(), '->', sha256(after).hexdigest())
