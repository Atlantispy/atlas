"""solve_enclosure / physical_bounds of private_heat_certification_kernel_r1 with batched dots.

Line for line the r1 functions, except that the four dot loops (Gram, inverse defect,
residual, eta) and physical_bounds' dots call one compiled batch each. A batch that
declines (Unavailable) is discarded and the ORIGINAL r1 expression runs instead, so
exceptions and their order are those of r1. ``check`` phases: the batch is preceded by
check('interval-product') and the last phase each r1 loop leaves is reproduced.
"""


def _batch(dots, ar, x_rows, y_rows, *, gram=False):
    ar.check('interval-product')
    try:
        if dots.__name__.endswith('2'):
            return dots.pair_dots(x_rows, y_rows, ar.down.precision, gram=gram)
        return dots.pair_dots(x_rows, y_rows, ar.down.precision)[0]
    except dots.Unavailable:
        return None


def solve_enclosure(K, dots, matrix, rhs, *, precision, cancelled=None, evidence=None):
    """Return bounds on the exact full-rank Gram dual; no exact Gram created."""
    ar = K.Arithmetic(precision, cancelled, evidence)
    n = len(rhs)
    if not n or not matrix or any(len(row) != n for row in matrix):
        raise ValueError('Nonempty rectangular observations and matching target required')
    m = [[ar.point(q) for q in row] for row in matrix]
    b = [ar.point(q) for q in rhs]
    columns = list(zip(*m, strict=True))
    a = _batch(dots, ar, columns, columns, gram=True)
    if a is None:
        a = [[ar.dot(x, y) for y in columns] for x in columns]
    else:
        ar.check('interval-add')
    r = K.approximate_inverse(a, ar)
    ri = [[(v, v) for v in row] for row in r]
    xhat = []
    for row in r:
        value = ar.zero
        for v, bound in zip(row, b, strict=True):
            value = ar.near.add(value, ar.near.mul(v, ar.midpoint(bound)))
        xhat.append(value)
    a_columns = list(zip(*a, strict=True))
    rho = ar.zero
    defect = _batch(dots, ar, ri, a_columns)
    if defect is None:
        for i, row in enumerate(ri):
            total = ar.zero
            for j, column in enumerate(a_columns):
                eye = ar.one if i == j else ar.zero
                item = ar.sub((eye, eye), ar.dot(row, column))
                total = ar.up.add(total, ar.absmax(item))
            rho = max(rho, total)
    else:
        for i, row in enumerate(ri):
            total = ar.zero
            for j, column in enumerate(a_columns):
                eye = ar.one if i == j else ar.zero
                item = ar.sub((eye, eye), defect[i][j])
                total = ar.up.add(total, ar.absmax(item))
            rho = max(rho, total)
    if not K.G.is_finite(rho) or rho >= ar.one:
        raise K.Unresolved('Inverse defect norm is not certified below one')
    point_xhat = [(x, x) for x in xhat]
    products = _batch(dots, ar, a, [point_xhat])
    if products is None:
        residual = [ar.sub(v, ar.dot(row, [(x, x) for x in xhat]))
                    for row, v in zip(a, b, strict=True)]
    else:
        residual = [ar.sub(v, p[0]) for p, v in zip(products, b, strict=True)]
    products = _batch(dots, ar, ri, [residual])
    if products is None:
        eta = max(ar.absmax(ar.dot(row, residual)) for row in ri)
    else:
        ar.check('interval-add')
        eta = max(ar.absmax(p[0]) for p in products)
    radius = ar.up.div(eta, ar.down.sub(ar.one, rho))
    if not K.G.is_finite(radius):
        raise K.Unresolved('Nonfinite proved error radius')
    bounds = [(ar.down.sub(x, radius), ar.up.add(x, radius)) for x in xhat]
    ar.check('dual-certified')
    return bounds, ar, dict(precision_bits=precision, rank=n,
                            inverse_defect_upper=rho, dual_radius_upper=radius)


def physical_bounds(K, dots, matrix, dual, keys, base_keys, signed_tau, conversion, ar):
    if len(keys) != len(matrix) or len(conversion) != len(keys) or len(set(keys)) != len(keys):
        raise ValueError('Unique matching observation identities and conversions required')
    if len(base_keys) != 2 or base_keys[0] == base_keys[1]:
        raise ValueError('Distinct owner/base keys required')
    try:
        # r1 interleaves these conversions with the dots; any refusal here reruns r1's
        # own interleaved expression so that the first exception raised is r1's.
        rows = [[ar.point(q) for q in row] for row in matrix]
    except Exception:
        rows = None
    products = None if rows is None else _batch(dots, ar, rows, [dual])
    if products is None:
        result = {key: ar.dot([ar.point(q) for q in row], dual)
                  for key, row in zip(keys, matrix, strict=True)}
    else:
        ar.check('interval-add')
        result = {key: p[0] for key, p in zip(keys, products, strict=True)}
    tau = ar.point(signed_tau)
    zero = (ar.zero, ar.zero)
    result[base_keys[0]] = ar.add(result.get(base_keys[0], zero), tau)
    result[base_keys[1]] = ar.sub(result.get(base_keys[1], zero), tau)
    factors = dict(zip(keys, conversion, strict=True))
    for key in base_keys:
        if key[0] not in ('cell', 'wall'):
            raise ValueError('Base jump must use declared temperature observations')
        factors.setdefault(key, K.G.mpq(1))
    return {key: ar.mul(bound, ar.point(factors[key])) for key, bound in result.items()}
