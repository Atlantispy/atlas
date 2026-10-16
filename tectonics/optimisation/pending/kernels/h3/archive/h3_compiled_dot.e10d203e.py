"""H3 (WP24): compiled batches of the heat certificate's interval dots, layered on H2.

Source transforms on helpers already transformed by T/hs/transforms/h2_fused_dot.py
(reviewed inputs below are H2's outputs). File names stay the same; one NEW helper file,
private_heat_compiled_dot_r1.py (T/ck/h3/), is copied beside them.
- transform(source): private_heat_certification_kernel_r1.py. solve_enclosure's four dot
  loops (Gram, inverse defect row by row, residual, eta) and physical_bounds' dots each
  call one compiled batch. A batch that declines returns None and the UNCHANGED original
  expression runs, so exceptions, their order and every number are r1's. The batch is
  used only for a plain Arithmetic (not a subclass, no instance-level check/dot/mul/add)
  whose contexts are the reviewed directed pair.
- repin(source, kernel_before, kernel_after): private_heat_certification_resources_r1.py,
  the kernel's single pin, exactly once (as H2's repin).
check() phases: each batch is preceded by check('interval-product'); where r1's loop ends
on a dot, check('interval-add') follows the batch, so evidence['phase'] after every
replaced statement equals r1's. An empty batch is never sent (r1 makes no check() for an
empty dot). Cancellation is observed at batch granularity: under cancellation the
CancelledError can come later than in r1 and its message may name 'interval-add' where r1
would name 'interval-product'; a declined batch costs one extra cancelled() call.
Memory: the Gram batch holds what r1's final Gram holds plus 8 scratch values; the defect
is batched one row (n values) at a time; physical_bounds converts its m x n points before
its batch (r1 converts one row at a time), inside interval_plan's 4mn observation slots
because solve_enclosure's own m x n generation is gone by then.
The compiled module is imported lazily on first use. ImportError (numba missing or not
0.65.1, gmpy2/MPFR not the reviewed build, unexpected object layout) selects the Python
route for the process; a module whose loaded source digest is not the pinned one is
refused with RuntimeError. h3_status() reports the route and build info for the runner.
Record identity: numbers byte-identical; kernel digest and its pin change (D-b).
"""
from hashlib import sha256
from pathlib import Path
import re

KERNEL_INPUT_SHA256 = {
    '3be44650802e629bedeaf20ce2b70cd88a14f12ee83571e8560e10a5b1157241':
        'private_heat_certification_kernel_r1.py after H2 (T/hs/transforms/h2_fused_dot.py)',
}
RESOURCES_INPUT_SHA256 = {
    '8b451aa8d4e44175ecf24508a88245b00778a40a693111d5bfed5d8860cf167e':
        'private_heat_certification_resources_r1.py after H2 repin',
}
COMPILED_NAME = 'private_heat_compiled_dot_r1.py'
COMPILED_SHA256 = 'e10d203edb1832d7773b2423b5c62781ec4e17239c9cb917398f3d4aa21d08eb'  # reviewed T/ck/h3/private_heat_compiled_dot_r1.py
COMPILED_SOURCE = Path(__file__).resolve().parents[1]/'h3'/COMPILED_NAME
MARK = '# H3: compiled interval dot batches'

HELPER = MARK + ''' (private_heat_compiled_dot_r1, pinned below).
_H3_SHA256 = '@SHA@'
_H3 = []


def _h3_module():
    """The pinned compiled module, or None (the original Python route) if it cannot load."""
    if not _H3:
        try:
            import private_heat_compiled_dot_r1 as module
        except ImportError as error:
            _H3.append((None, 'unavailable: %s' % error))
        else:
            from pathlib import Path as _Path
            if (module._LOADED_SHA256 != _H3_SHA256
                    or _Path(module.__file__).resolve().parent != _Path(__file__).resolve().parent):
                raise RuntimeError('compiled interval dot module is not the pinned helper beside this kernel')
            _H3.append((module, 'compiled'))
    return _H3[0][0]


def h3_status():
    module = _h3_module()
    return dict(route=_H3[0][1], pinned_sha256=_H3_SHA256,
                build=None if module is None else module.build_info())


def _h3_batch(ar, x_rows, y_rows, gram=False):
    """[[ar.dot(x, y) for y in y_rows] for x in x_rows] compiled, or None to run the original."""
    if type(ar) is not Arithmetic or any(name in ar.__dict__ for name in ('check', 'dot', 'mul', 'add')):
        return None
    if not x_rows or not y_rows or not len(x_rows[0]):
        return None  # r1 makes no check() call for an empty dot
    module = _h3_module()
    if module is None:
        return None
    ar.check('interval-product')
    try:
        return module.pair_dots(x_rows, y_rows, ar.down, ar.up, gram=gram)
    except module.Unavailable:
        return None


class Arithmetic:
'''

REPLACEMENTS = (
    ('''\
    columns = list(zip(*m, strict=True))
    a = [[ar.dot(x, y) for y in columns] for x in columns]
''', '''\
    columns = list(zip(*m, strict=True))
    a = _h3_batch(ar, columns, columns, gram=True)
    if a is None:
        a = [[ar.dot(x, y) for y in columns] for x in columns]
    else:
        ar.check('interval-add')
'''),
    ('''\
    for i, row in enumerate(ri):
        total = ar.zero
        for j, column in enumerate(a_columns):
            eye = ar.one if i == j else ar.zero
            item = ar.sub((eye, eye), ar.dot(row, column))
            total = ar.up.add(total, ar.absmax(item))
        rho = max(rho, total)
''', '''\
    for i, row in enumerate(ri):
        total = ar.zero
        dots = _h3_batch(ar, [row], a_columns)
        dots = None if dots is None else dots[0]
        for j, column in enumerate(a_columns):
            eye = ar.one if i == j else ar.zero
            item = ar.sub((eye, eye), ar.dot(row, column) if dots is None else dots[j])
            total = ar.up.add(total, ar.absmax(item))
        rho = max(rho, total)
'''),
    ('''\
    residual = [ar.sub(v, ar.dot(row, [(x, x) for x in xhat]))
                for row, v in zip(a, b, strict=True)]
    eta = max(ar.absmax(ar.dot(row, residual)) for row in ri)
''', '''\
    dots = _h3_batch(ar, a, [[(x, x) for x in xhat]])
    if dots is None:
        residual = [ar.sub(v, ar.dot(row, [(x, x) for x in xhat]))
                    for row, v in zip(a, b, strict=True)]
    else:
        residual = [ar.sub(v, dot[0]) for dot, v in zip(dots, b, strict=True)]
    dots = _h3_batch(ar, ri, [residual])
    if dots is None:
        eta = max(ar.absmax(ar.dot(row, residual)) for row in ri)
    else:
        ar.check('interval-add')
        eta = max(ar.absmax(dot[0]) for dot in dots)
'''),
    ('''\
    result = {key: ar.dot([ar.point(q) for q in row], dual)
              for key, row in zip(keys, matrix, strict=True)}
''', '''\
    rows = dots = None
    if type(ar) is Arithmetic and _h3_module() is not None:
        try:
            # r1 interleaves these conversions with its dots: any exception here reruns
            # r1's own interleaved expression below, so the first exception is r1's.
            rows = [[ar.point(q) for q in row] for row in matrix]
        except Exception:
            rows = None
    if rows is not None:
        dots = _h3_batch(ar, rows, [dual])
    if dots is None:
        result = {key: ar.dot([ar.point(q) for q in row], dual)
                  for key, row in zip(keys, matrix, strict=True)}
    else:
        ar.check('interval-add')
        result = {key: dot[0] for key, dot in zip(keys, dots, strict=True)}
'''),
)


def compiled_sha256():
    return sha256(COMPILED_SOURCE.read_bytes()).hexdigest()


def transform(source, *, allow_unreviewed_input=False):
    if MARK in source:
        raise ValueError('H3 transform already applied')
    if not allow_unreviewed_input and compiled_sha256() != COMPILED_SHA256:
        raise ValueError('compiled helper is not the reviewed file')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KERNEL_INPUT_SHA256:
        raise ValueError('certification kernel input is not the reviewed H2 output; pass '
                         'allow_unreviewed_input and re-run the same-call control')
    anchor = '\nclass Arithmetic:\n'
    if source.count(anchor) != 1 or '# H2: mul() then add()' not in source:
        raise ValueError('H3 expects exactly one Arithmetic class and the H2 dot')
    for old, _ in REPLACEMENTS:
        if source.count(old) != 1:
            raise ValueError('H3 anchor must occur exactly once: %r' % old.splitlines()[0])
    source = source.replace(anchor, '\n' + HELPER.replace('@SHA@', compiled_sha256()))
    for old, new in REPLACEMENTS:
        source = source.replace(old, new)
    return source


def repin(source, kernel_before, kernel_after, *, allow_unreviewed_input=False):
    """Replace the kernel's pin in certification_resources_r1, exactly once."""
    for value in (kernel_before, kernel_after):
        if not re.fullmatch('[0-9a-f]{64}', value):
            raise ValueError('sha256 hex digests required')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in RESOURCES_INPUT_SHA256:
        raise ValueError('certification resources input is not the reviewed H2 output')
    old = "    'private_heat_certification_kernel_r1.py': '%s',\n" % kernel_before
    if source.count(old) != 1 or source.count(kernel_before) != 1:
        raise ValueError('kernel pin must occur exactly once')
    return source.replace(old, "    'private_heat_certification_kernel_r1.py': '%s',\n" % kernel_after)


if __name__ == '__main__':
    import shutil
    import sys
    helpers = Path(sys.argv[1])  # a helpers folder holding the two H2 outputs; rewritten in place
    kp, rp = helpers/'private_heat_certification_kernel_r1.py', helpers/'private_heat_certification_resources_r1.py'
    cp = helpers/COMPILED_NAME
    if cp.exists():
        raise SystemExit('%s already present' % cp)
    kin, rin = kp.read_bytes(), rp.read_bytes()
    kout = transform(kin.decode('utf8')).encode('utf8')
    rout = repin(rin.decode('utf8'), sha256(kin).hexdigest(), sha256(kout).hexdigest()).encode('utf8')
    shutil.copyfile(COMPILED_SOURCE, cp)
    kp.write_bytes(kout)
    rp.write_bytes(rout)
    for name, a, b in ((kp.name, kin, kout), (rp.name, rin, rout)):
        print(name, sha256(a).hexdigest(), '->', sha256(b).hexdigest())
    print(cp.name, 'new', compiled_sha256())
