"""H3 (WP24): compiled batches of the heat certificate's interval dots, layered on H2.

Source transforms on helpers already transformed by T/hs/transforms/h2_fused_dot.py
(reviewed inputs below are H2's outputs). File names stay the same; one NEW helper file,
private_heat_compiled_dot_r1.py (T/ck/h3/), is copied beside them.
- transform(source): private_heat_certification_kernel_r1.py. solve_enclosure's four dot
  loops (Gram, inverse defect row by row, residual, eta) and physical_bounds' dots each
  call one compiled batch. A batch that declines returns None and the UNCHANGED original
  expression runs, so exceptions, their order and every number are r1's. The batch is
  used only for a plain Arithmetic (not a subclass, no instance-level
  check/point/dot/mul/add) whose contexts have exactly Arithmetic's settings.
- repin(source, kernel_before, kernel_after): private_heat_certification_resources_r1.py,
  the kernel's single pin, exactly once (as H2's repin).
check() phases: each batch is preceded by check('interval-product'); where r1's loop ends
on a dot, check('interval-add') follows the batch, so evidence['phase'] after every
replaced statement equals r1's. An empty batch is never sent (r1 makes no check() for an
empty dot). Cancellation is observed at block granularity: a batch calls
check('interval-product') again before each block of at most 2**20 interval products
(about 0.2 s), so under a sticky cancellation the CancelledError comes at most one block
later than in r1 and its message may name another phase than r1's ('interval-add',
'interval-product', or 'directed-input' for physical_bounds' conversions); a declined
batch costs extra cancelled() calls. A CancelledError from physical_bounds' conversions
propagates; any other exception there reruns r1's interleaved expression.
Memory: the Gram batch holds what r1's final Gram holds plus 8 scratch values; the defect
is batched one row (n values) at a time; physical_bounds converts its m x n points before
its batch (r1 converts one row at a time), inside interval_plan's 4mn observation slots
because solve_enclosure's own m x n generation is gone by then. Per process the compiled
route adds numba's import and one compilation (about 1.2 s and 50-75 MiB, measured).
The compiled module is loaded lazily on first use: the kernel reads the helper beside it,
refuses (RuntimeError) a file whose digest is not the pinned one, and executes exactly
the bytes it hashed. Any exception while executing it (ImportError: numba, gmpy2 or MPFR
not the reviewed build, unexpected object layout, failed self-test; or any failure to
bind or compile) selects the Python route for the process. h3_status() reports the
route and build info for the runner.
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
COMPILED_SHA256 = '62c100cff79742d4254d291b40c529794b857894e1fd2d41e1aa28db8699682a'  # reviewed T/ck/h3/private_heat_compiled_dot_r1.py
COMPILED_SOURCE = Path(__file__).resolve().parents[1]/'h3'/COMPILED_NAME
MARK = '# H3: compiled interval dot batches'

HELPER = MARK + ''' (private_heat_compiled_dot_r1, pinned below).
_H3_NAME = 'private_heat_compiled_dot_r1'
_H3_SHA256 = '@SHA@'
_H3 = []


def _h3_module():
    """The pinned compiled module, or None (the original Python route) if it cannot load.

    The helper beside this kernel is read once, hashed, and exactly those bytes run.
    """
    if not _H3:
        import sys as _sys
        import types as _types
        from hashlib import sha256 as _sha256
        from pathlib import Path as _Path
        path = _Path(__file__).resolve().parent/(_H3_NAME+'.py')
        try:
            data = path.read_bytes()
        except OSError as error:
            _H3.append((None, 'unavailable: %s' % error))
            return None
        if _sha256(data).hexdigest() != _H3_SHA256:
            raise RuntimeError('compiled interval dot helper beside this kernel is not the pinned file')
        seal = (str(path), _H3_SHA256)
        module = _sys.modules.get(_H3_NAME)
        if module is not None:
            if getattr(module, '_H3_SEAL', None) != seal:
                raise RuntimeError('another compiled interval dot module is already loaded')
        else:
            module = _types.ModuleType(_H3_NAME)
            module.__file__ = str(path)
            _sys.modules[_H3_NAME] = module
            try:
                exec(compile(data, str(path), 'exec'), module.__dict__)
            except Exception as error:  # ImportError: not the reviewed build; or it cannot be built
                del _sys.modules[_H3_NAME]
                _H3.append((None, 'unavailable: %s: %s' % (type(error).__name__, error)))
                return None
            module._H3_SEAL = seal
        _H3.append((module, 'compiled'))
    return _H3[0][0]


def h3_status():
    module = _h3_module()
    return dict(route=_H3[0][1], pinned_sha256=_H3_SHA256,
                build=None if module is None else module.build_info())


def _h3_plain(ar):
    """A plain Arithmetic: not a subclass, no instance-level replacement of a method used."""
    return type(ar) is Arithmetic and not any(name in ar.__dict__ for name in ('check', 'point', 'dot', 'mul', 'add'))


def _h3_batch(ar, x_rows, y_rows, gram=False):
    """[[ar.dot(x, y) for y in y_rows] for x in x_rows] compiled, or None to run the original."""
    if not _h3_plain(ar):
        return None
    if not x_rows or not y_rows or not len(x_rows[0]):
        return None  # r1 makes no check() call for an empty dot
    module = _h3_module()
    if module is None:
        return None
    ar.check('interval-product')
    try:
        return module.pair_dots(x_rows, y_rows, ar.down, ar.up, gram=gram,
                                check=lambda: ar.check('interval-product'))
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
    if _h3_plain(ar) and _h3_module() is not None:
        try:
            rows = [[ar.point(q) for q in row] for row in matrix]
        except CancelledError:
            raise  # observed at a conversion, as r1's first check is one
        except Exception:
            # r1 interleaves these conversions with its dots: any other exception reruns
            # r1's own interleaved expression below, so the first exception is r1's.
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
    if (source.count(anchor) != 1 or '# H2: mul() then add()' not in source
            or '\nfrom concurrent.futures import CancelledError\n' not in source):
        raise ValueError('H3 expects exactly one Arithmetic class, the H2 dot and CancelledError')
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
