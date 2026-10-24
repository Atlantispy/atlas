"""Stage-local prospective finisher policy; not allocator/RSS/native admission.

Stages match the fixed finisher: input/pair projection, full correction,
signwise fallback ONLY when entered, closed guard ONLY when entered, and issue.
Neighbouring limiter ratios are propagated through their actual face owners;
unrelated interior denominators are never put into a global product. Only the
required public stock/source/exterior audit has an exterior global sum.

The closed guard retains four certificates, not 64 energy generations. Its
search theta lies on the 2**-64 lattice. MPFR enclosures retain dyadic exponent
bounds, while exact fallback keeps the original 65536-bit refusal ceiling.
All stage owners must remain held with the returned sealed bytes/diagnostics.
Calling the result's debug record() creates a NEW caller-owned JSON view; an
unbounded number of such views is not included in this finish-call inventory.
"""
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_low_ledger_inventory_r1 as L
import private_heat_interval_inventory_r1 as E
import private_heat_decimal_inventory_r1 as D
import private_heat_decimal_sparse_core_r1 as P
import private_heat_interval_assembly_kernel_r1 as M

HERE = Path(__file__).resolve().parent
PINS = {'private_heat_finish_kernel_r1.py': '93b48f29ef75abe83ee227c6146c70d9eb2b261d07a7b65507a63fab73496d8b',
        'private_heat_finish_arithmetic_r1.py': 'a5473f2993016d40b13587fd8948ce732f4c8fcd78f1ac61584ba0c8e702da66',
        'private_heat_low_ledger_inventory_r1.py': '810a2b565515012e7ea68fd953ac495dede2d3d881dfe1a96788217fbf213695'}
UNIT = D.CONTAINER_UNIT
ZERO, ONE, TWO = E.Shape(1, 1, True), E.Shape(1, 1, True), E.Shape(2, 1, True)
PUBLIC = L.PUBLIC_BINARY64
THETA = E.Shape(65, 65, True)  # Every 0<=theta<=1 with denominator dividing 2**64.
PRECISION = 2560
_SOURCE_PATHS = (L.__file__, E.__file__, D.__file__, P.__file__, M.__file__,
                 D.POLICY_PATH, HERE/'private_heat_gmp_resources_r1.py')
_SOURCES = {str(Path(path).resolve()): sha256(Path(path).read_bytes()).hexdigest()
            for path in _SOURCE_PATHS}


@dataclass(frozen=True)
class InventoryPlan:
    inventory: M.DiagnosticInventory
    stage: str
    components: tuple
    cell_bits: tuple
    face_bits: tuple
    codec_chars: int = 0
    search_history_entries: int = 0
    simultaneous_certificates: int = 0
    allocator_or_rss_bound: bool = False
    whole_method_admission: bool = False


def _integer_text(value, cancel):
    if type(value) is int:
        return max(1, value.bit_length())
    if type(value) is not str or not value:
        raise ValueError('Owned exact integer component required')
    start = int(value[0] in '+-')
    if start == len(value):
        raise ValueError('Missing integer digits')
    for i in range(start, len(value)):
        if i % 256 == 0:
            L._check(cancel)
        if not '0' <= value[i] <= '9':
            raise ValueError('Only exact decimal integer components supported')
    return L._size(4*(len(value)-start)+1)


def _text(value, cancel):
    # Counter-only metadata parsing; no giant split/int/Fraction/Decimal copy.
    if '/' in value:
        slash = value.find('/')
        # Slices are avoided; scan the two integer spans directly.
        result = []
        for begin, end in ((0, slash), (slash+1, len(value))):
            if begin < end and value[begin] in '+-':
                begin += 1
            if begin == end:
                raise ValueError('Missing rational component digits')
            for i in range(begin, end):
                if i % 256 == 0:
                    L._check(cancel)
                if not '0' <= value[i] <= '9':
                    raise ValueError('Malformed exact rational component')
            result.append(L._size(4*(end-begin)+1))
        return E.Shape(result[0], result[1], False)
    start = int(bool(value) and value[0] in '+-')
    digits = fractional = exponent = exponent_digits = 0
    dot = exp_mode = exp_sign_seen = False
    exponent_sign = 1
    for at in range(start, len(value)):
        if at % 256 == 0:
            L._check(cancel)
        char = value[at]
        if not exp_mode:
            if '0' <= char <= '9':
                digits += 1
                fractional += int(dot)
            elif char == '.' and not dot:
                dot = True
            elif char in 'eE' and digits:
                exp_mode = True
            else:
                raise ValueError('Unsupported exact decimal representation')
        elif char in '+-' and not exp_sign_seen and not exponent_digits:
            exp_sign_seen = True
            exponent_sign = -1 if char == '-' else 1
        elif '0' <= char <= '9':
            exponent_digits += 1
            exponent = exponent*10+ord(char)-48
            if exponent > D.MAX_DECIMAL_EXPONENT:
                raise OverflowError('Exact decimal exponent exceeds reviewed metadata range')
        else:
            raise ValueError('Malformed exact decimal exponent')
    if not digits or exp_mode and not exponent_digits:
        raise ValueError('Finite exact decimal required')
    scale = exponent_sign*exponent-fractional
    return E.Shape(L._size(4*(digits+max(0, scale))+1), L._size(4*max(0, -scale)+1), scale >= 0)


def _q(ar, value):
    if type(value) is str:
        return _text(value, ar.cancel)
    if type(value) in (list, tuple):
        if len(value) != 2:
            raise ValueError('Two exact rational components required')
        return E.Shape(_integer_text(value[0], ar.cancel), _integer_text(value[1], ar.cancel), False)
    return ar.q(value)


def _binary(ar, value):
    # The original public entry point calls float on these already-owned
    # scalars. Its conversion/getters are covered by the metadata lease; no
    # extended precision is substituted for the represented binary64 value.
    return ar.binary(float(value))


def _slots(ar, values, copies=1):
    return L._size(copies*sum(ar.slot(v) for v in values))


def _residual(ar, energy, faces, load):
    result = [ar.op('subtract', e, b) for e, b in zip(energy, load, strict=True)]
    for i, j, amount in faces:
        result[i] = ar.op('add', result[i], amount)
        if j is not None:
            result[j] = ar.op('subtract', result[j], amount)
    return result


def _faces(ar, values):
    return [(i, j, _q(ar, q)) for i, j, q in values]


def _bound_work(ar, energy, cap, bounds):
    for e, c in zip(energy, cap, strict=True):
        for b in bounds:
            ar.op('subtract', e, ar.op('multiply', c, b))
            ar.op('subtract', PUBLIC, b)


def _project(ar, predictor, n):
    faces, parts = [], []
    target = _q(ar, predictor['evidence']['absolute_target_decimal'])
    for raw in predictor['evidence']['raw_outward_energy_decimal']:
        L._check(ar.cancel)
        if len(raw) not in (1, 2):
            raise ValueError('One/two original physical owners required')
        i, _, first = raw[0]
        if type(i) is not int or not 0 <= i < n:
            raise ValueError('Original bounded physical owner required')
        first = _q(ar, first)
        parts.append(first)
        if len(raw) == 2:
            j, _, second = raw[1]
            if type(j) is not int or not 0 <= j < n or j == i:
                raise ValueError('Original distinct bounded second owner required')
            second = _q(ar, second)
            parts.append(second)
            defect = ar.op('add', first, second)
            ar.op('subtract', defect, target)
            amount = ar.op('divide', ar.op('subtract', first, second), TWO, divisor_power_two=True)
        else:
            j, amount = None, first
        faces.append((i, j, amount))
    return faces, parts


def _inputs(ar, d):
    cap, old, src = [[_binary(ar, v) for v in d[name]] for name in ('capacity', 'old', 'source')]
    n = len(cap)
    if not n or len(old) != n or len(src) != n:
        raise ValueError('Complete original finisher inputs required')
    delta, target = _binary(ar, d['dt']), _q(ar, d['absolute_residual_target'])
    source = [ar.op('multiply', delta, s) for s in src]
    load = [ar.op('add', e, s) for e, s in zip(old, source, strict=True)]
    low = [_q(ar, e) for e in d['low']['energy']]
    lo_faces, lo_parts = _project(ar, d['low'], n)
    hi_faces, hi_parts = _project(ar, d['high'], n)
    if len(low) != n or len(lo_faces) != len(hi_faces) or len(d['face_ids']) != len(lo_faces):
        raise ValueError('Complete original predictor coverage required')
    loaded, fixed, prescribed = load[:], [], []
    for f, fid in enumerate(d['face_ids']):
        if fid in d['normalized_boundary']:
            kind, value = d['normalized_boundary'][fid]
            if kind == 'temperature':
                fixed.append(_binary(ar, value))
            elif kind == 'power':
                q = ar.op('multiply', delta, _binary(ar, value))
                prescribed.append(q)
                loaded[lo_faces[f][0]] = ar.op('subtract', loaded[lo_faces[f][0]], q)
            else:
                raise ValueError('Original normalised boundary kind required')
    hull = [ar.op('divide', e, c) for e, c in zip(loaded, cap, strict=True)]+fixed
    bounds = ar.choice(hull)
    values = cap+old+src+source+load+low+lo_parts+hi_parts+loaded+fixed+prescribed+hull+[delta, target, bounds]
    values += [q for _, _, q in lo_faces+hi_faces]
    units = 64+24*n+16*len(lo_faces)
    return [('input_conversions_pair_projection_hull', _slots(ar, values, 2)), ('input_containers', UNIT*units)], low, lo_faces, 0, 0, 0


def _full(ar, d):
    low, cap, bounds = [[_q(ar, v) for v in d[name]] for name in ('low', 'cap', 'bounds')]
    lo_faces, hi_faces = _faces(ar, d['low_faces']), _faces(ar, d['high_faces'])
    full, faces, corrections = low[:], [], []
    permitted = set(d['permitted'])
    for f, ((i, j, lo), (hi, hj, high)) in enumerate(zip(lo_faces, hi_faces, strict=True)):
        if (i, j) != (hi, hj):
            raise ValueError('Original face owner/order mismatch')
        delta = ar.op('subtract', lo, high) if j is not None or f in permitted else ZERO
        corrections.append(delta)
        full[i] = ar.op('add', full[i], delta)
        if j is not None:
            full[j] = ar.op('subtract', full[j], delta)
        faces.append((i, j, ar.op('subtract', lo, delta)))
    _bound_work(ar, full, cap, bounds)
    residual = _residual(ar, full, faces, [ZERO]*len(low))
    prior_residual = _residual(ar, low, lo_faces, [ZERO]*len(low))
    for x, y in zip(residual, prior_residual, strict=True):
        ar.op('subtract', x, y)
    values = full+corrections+residual+prior_residual+[q for _, _, q in faces]
    units = 80+18*len(low)+20*len(faces)
    return [('full_candidate_faces_and_residuals', _slots(ar, values, 3)),
            ('full_public_checks_and_containers', UNIT*units+6*len(low)*ar.slot(PUBLIC))], full, faces, 0, 0, 0


def _limited(ar, d):
    low, cap, bounds = [[_q(ar, v) for v in d[name]] for name in ('low', 'cap', 'bounds')]
    corrections, lo_faces = _faces(ar, d['corrections']), _faces(ar, d['low_faces'])
    n = len(low)
    positive, negative, has_positive, has_negative = [ZERO]*n, [ZERO]*n, [False]*n, [False]*n
    for (i, j, shape), (_, _, actual) in zip(corrections, d['corrections'], strict=True):
        for owner, sign in ((i, 1),) if j is None else ((i, 1), (j, -1)):
            # Only signs of already-owned exact values, not an approximate test.
            pos = actual > 0 if sign == 1 else actual < 0
            neg = actual < 0 if sign == 1 else actual > 0
            if pos:
                positive[owner] = ar.op('add', positive[owner], shape)
                has_positive[owner] = True
            if neg:
                negative[owner] = ar.op('add', negative[owner], shape)
                has_negative[owner] = True
    up, down = [], []
    for i, (c, e) in enumerate(zip(cap, low, strict=True)):
        up.append(ar.choice([ONE, ar.op('divide', ar.op('subtract', ar.op('multiply', c, bounds[1]), e), positive[i])]) if has_positive[i] else ONE)
        down.append(ar.choice([ONE, ar.op('divide', ar.op('subtract', ar.op('multiply', c, bounds[0]), e), negative[i])]) if has_negative[i] else ONE)
    energy, faces, alphas = low[:], [], []
    for (i, j, delta), (_, _, lo) in zip(corrections, lo_faces, strict=True):
        choices = [up[i], down[i]] if j is None else [up[i], down[i], up[j], down[j]]
        alpha = ar.choice(choices)
        transfer = ar.op('multiply', alpha, delta)
        energy[i] = ar.op('add', energy[i], transfer)
        if j is not None:
            energy[j] = ar.op('subtract', energy[j], transfer)
        alphas.append(alpha)
        faces.append((i, j, ar.op('subtract', lo, transfer)))
    _bound_work(ar, energy, cap, bounds)
    residual = _residual(ar, energy, faces, [ZERO]*n)
    prior = _residual(ar, low, lo_faces, [ZERO]*n)
    for x, y in zip(residual, prior, strict=True):
        ar.op('subtract', x, y)
    values = positive+negative+up+down+energy+alphas+residual+prior+[q for _, _, q in faces]
    return [('limited_local_ratios_energies_faces', _slots(ar, values, 3)),
            ('limited_public_checks_containers', UNIT*(64+24*n+16*len(faces))+4*n*ar.slot(PUBLIC))], energy, faces, 0, 0, 0


def _point(shape):
    # For nonzero q=n/d and precision p with trapped underflow, directed MPFR
    # rounding has |x|<2**(N+1), |x|>2**(-D-1). Its dyadic quantum exponent is
    # therefore >=-D-p-1. Zero is also covered by this virtual denominator.
    denominator = shape.denominator+PRECISION+2
    return E.Shape(shape.numerator+1+denominator, denominator, True)


def _rounded_product(a, b):
    # Exact dyadic multiplication then p-bit rounding cannot introduce a finer
    # binary quantum; one extra numerator bit bounds outward rounding.
    s = E.multiply_shape(a, b)
    return E.Shape(s.numerator+1, s.denominator, True)


def _quadratic(ar, old, new, cap):
    factors, interval = [], ZERO
    fallback, fallback_peak = ZERO, 1
    for a, b, c in zip(old, new, cap, strict=True):
        delta, sigma = ar.op('subtract', b, a), ar.op('add', b, a)
        inverse = ar.op('divide', ONE, ar.op('multiply', TWO, c))
        factors.extend((delta, sigma, inverse))
        term_bound = E.multiply_shape(E.multiply_shape(delta, sigma), inverse)
        # The existing fallback refuses every nontrivial product/sum whose
        # unreduced components exceed its ceiling. Account that bounded global
        # fallback only, never use it as the physical cell/face size bound.
        term_bound = E.Shape(min(65536, term_bound.numerator), min(65536, term_bound.denominator), False)
        added = E.add_shape(fallback, term_bound)
        fallback = E.Shape(min(65536, added.numerator), min(65536, added.denominator), False)
        fallback_peak = max(fallback_peak, term_bound.numerator, term_bound.denominator,
                            fallback.numerator, fallback.denominator)
        term = _rounded_product(_rounded_product(_point(delta), _point(sigma)), _point(inverse))
        summed = E.add_shape(interval, term)
        interval = E.Shape(summed.numerator+1, summed.denominator, True)
    # A returned sign certificate has no factor array or arithmetic workspace.
    # Four attempts each retain two rational endpoints, plus final bounds and
    # the optional exact fallback. Only the current call retains its factors.
    proof = 12*ar.slot(interval)+3*ar.slot(fallback)+UNIT*48
    fallback_work = ar.resources.native_workspace_allowance(8*fallback_peak, 12)
    # One active Arithmetic has 3 contexts, 2 constants, at most 6 point
    # endpoints, 8 current product candidates, 4 term/total endpoints and 9
    # conversion/bookkeeping slots. MPFR mantissas have <=PRECISION bits, but
    # conversion of a tiny endpoint to mpq also creates its full dyadic power
    # of two denominator: charge that actual bound, not mantissa bits alone.
    mpfr_work = ar.resources.native_workspace_allowance(
        interval.numerator+interval.denominator+PRECISION, 32)
    mpfr_work += 32*ar.slot(E.Shape(PRECISION+1, 1, True))
    work = _slots(ar, factors, 2)+fallback_work+mpfr_work+UNIT*(32+8*len(old))
    return work, proof, interval


def _closed(ar, d):
    old, cap, low, candidate, bounds = [[_q(ar, v) for v in d[name]]
        for name in ('old', 'cap', 'low', 'candidate', 'bounds')]
    lo_faces, hi_faces = _faces(ar, d['low_faces']), _faces(ar, d['candidate_faces'])
    difference = [ar.op('subtract', hi, lo) for hi, lo in zip(candidate, low, strict=True)]
    dq = [ar.op('subtract', hi[2], lo[2]) for hi, lo in zip(hi_faces, lo_faces, strict=True)]
    energy = [ar.op('add', e, ar.op('multiply', THETA, delta)) for e, delta in zip(low, difference, strict=True)]
    faces = [(lo[0], lo[1], ar.op('add', lo[2], ar.op('multiply', THETA, change)))
             for lo, change in zip(lo_faces, dq, strict=True)]
    n = len(low)
    t_energy = [ar.op('multiply', c, PUBLIC) for c in cap]
    exact_work, exact_proof, exact_interval = _quadratic(ar, old, energy, cap)
    public_work, public_proof, public_interval = _quadratic(ar, [PUBLIC]*n, [PUBLIC]*n, cap)
    t_work, t_proof, t_interval = _quadratic(ar, t_energy, t_energy, cap)
    _bound_work(ar, energy, cap, bounds)
    residual = _residual(ar, energy, faces, old)
    prior = _residual(ar, low, lo_faces, old)
    for x, y in zip(residual, prior, strict=True):
        ar.op('subtract', x, y)
    states = _slots(ar, energy+difference+dq+residual+prior+[q for _, _, q in faces], 4)
    certificates = 4*(exact_proof+public_proof+t_proof)+max(exact_work, public_work, t_work)+UNIT*(4*96+66*4)
    values = (exact_interval, public_interval, t_interval)
    costs = [('closed_endpoint_current_final_states', states),
             ('four_certificates_mpfr_and_bounded_fallback', certificates),
             ('closed_public_arrays_history_containers', UNIT*(64+24*n+12*len(faces))+66*ar.slot(THETA)),
             ('retained_sign_bounds', _slots(ar, values, 4*3*4*2))]
    return costs, energy, faces, 0, 66, 4


def _rational_chars(shape):
    # A bit per decimal digit is conservative; two signs/quotes/list syntax.
    return L._size(shape.numerator+shape.denominator+12)


def _issue(ar, d, fixed_source_chars):
    old, cap, new, source, retained = [[_q(ar, v) for v in d[name]]
        for name in ('old', 'cap', 'new', 'source', 'retained')]
    faces = _faces(ar, d['faces'])
    n = len(old)
    fixed, powers = ({key: _q(ar, value) for key, value in d[name].items()} for name in ('fixed', 'powers'))
    target = _q(ar, d['target'])
    load = [ar.op('add', e, s) for e, s in zip(old, source, strict=True)]
    loaded = load[:]
    for f, (i, j, q) in enumerate(faces):
        if j is None and f not in fixed:
            loaded[i] = ar.op('subtract', loaded[i], q)
    hull = [ar.op('divide', e, c) for e, c in zip(loaded, cap, strict=True)]+list(fixed.values())
    bound = ar.choice(hull)
    _bound_work(ar, new, cap, (bound, bound))
    exact = _residual(ar, new, faces, load)
    public = _residual(ar, [PUBLIC]*n, faces, load)
    projection = [ar.op('subtract', PUBLIC, e) for e in new]
    for r, p, measured, previous in zip(exact, projection, public, retained, strict=True):
        ar.op('subtract', ar.op('add', r, p), measured)
        ar.op('subtract', r, previous)
        ar.op('subtract', r, target)
    maximum = ar.choice(exact)
    stock_delta = ar.total(ar.op('subtract', PUBLIC, b) for b in load)
    outward = ar.total(q for _, j, q in faces if j is None)
    total, source_total = ar.op('add', stock_delta, outward), ar.total(source)
    scale = ar.choice([ar.total(old), ar.total(PUBLIC for _ in range(n)), source_total, outward])
    relative = ar.op('divide', total, scale)
    ar.op('subtract', relative, ar.q(Fraction(1, 10**11)))
    globals_ = [stock_delta, outward, total, source_total, scale, relative, maximum, target, bound]
    values = old+cap+new+source+retained+load+loaded+hull+exact+public+projection+globals_
    values += list(fixed.values())+list(powers.values())+[q for _, _, q in faces]
    record_values = old+cap+source+new+exact+public+projection+list(fixed.values())+list(powers.values())
    record_values += [q for _, _, q in faces]+[bound, bound, target, maximum, source_total, outward, total]
    # Every constant key/literal in the sealed record occurs in the pinned
    # source; 12 ASCII chars/source byte also covers JSON Unicode escaping.
    # Variable identifiers/bindings and fixed-size binary64/index fields add
    # their own counts. No rational is formatted merely to estimate its size.
    metadata_chars = 0
    for value in d['face_ids']:
        metadata_chars += 12*len(value)+4
    for path, digest in d['bindings'].items():
        metadata_chars += 12*(len(path)+len(digest))+8
    chars = L._size(fixed_source_chars+metadata_chars+sum(map(_rational_chars, record_values))
                   +128*n+128*len(faces)+64*len(d['bindings']))
    # Simultaneous component strings, quoted chunk, UTF-8 chunk, bytearray
    # capacity, immutable copy and first hash input: eight full-size copies.
    codec = 8*(chars+1)
    costs = [('final_local_and_public_audits', _slots(ar, values, 3)+4*n*ar.slot(PUBLIC)),
             ('record_and_projection_containers', UNIT*(96+32*n+16*len(faces)+4*len(d['bindings']))),
             ('exact_component_json_codec_generations', codec)]
    return costs, exact, faces, chars, 0, 0


def _metadata_inputs(stage, operands):
    if stage != 'inputs':
        return operands
    # Fixed-size borrowed views only. Predictor diagnostic JSON, saved solver
    # histories and HIGH stocks are never read by the numerical finisher.
    # Their existing owners remain the caller's responsibility; they are not
    # new FINISH allocations and must not become a GMP scratch bit estimate.
    return (operands['old'], operands['capacity'], operands['dt'], operands['source'],
        operands['normalized_boundary'], operands['face_ids'], operands['low']['energy'],
        operands['absolute_residual_target'],
        operands['low']['evidence']['absolute_target_decimal'],
        operands['high']['evidence']['absolute_target_decimal'],
        operands['low']['evidence']['raw_outward_energy_decimal'],
        operands['high']['evidence']['raw_outward_energy_decimal'])


def _scalar_storage(value, gmp, cancel):
    """Largest owned exact getter/conversion scalar, never container/text size.

    Metadata text is counter-scanned; its characters are not converted into
    represented giant numbers. Fraction integer parts already exist. mpq
    numerator/denominator getters can allocate at most their original payload
    widths. The native policy covers one such getter/conversion at a time.
    """
    L._check(cancel)
    if type(value) is dict:
        return max((_scalar_storage(v, gmp, cancel) for pair in value.items() for v in pair), default=1)
    if type(value) in (list, tuple):
        return max((_scalar_storage(v, gmp, cancel) for v in value), default=1)
    if type(value) is Fraction:
        return max(sys.getsizeof(value.numerator), sys.getsizeof(value.denominator))
    if type(value) in (int, float, Decimal, gmp.mpq, gmp.mpz):
        return sys.getsizeof(value)
    return 1


def admit(stage, operands, *, source_bindings, budget, additional_bindings=None, cancel=None):
    """Return an owned plan; reserve inventory before the named stage begins.

    All input objects already exist under caller/stage leases. Keep this
    metadata owner with the stage work owner; escaped frames retain both.
    No stage performs the finisher's rational arithmetic or changes its data.
    """
    L._check(cancel)
    gmp = L.A.exact_library()
    import private_heat_gmp_resources_r1 as R
    inspected = _metadata_inputs(stage, operands)
    footprint, objects, _ = L._footprint((inspected, source_bindings, additional_bindings), gmp, cancel)
    scalar_storage = _scalar_storage(inspected, gmp, cancel)
    binding_sets = (source_bindings, _SOURCES) if additional_bindings is None else (source_bindings, additional_bindings, _SOURCES)
    if any(type(values) is not dict for values in binding_sets):
        raise ValueError('Original source binding dictionaries required')
    path_count = sum(len(values) for values in binding_sets)+len(PINS)
    source_size = max(max((Path(path).stat().st_size for values in binding_sets for path in values), default=0),
                      max((HERE/name).stat().st_size for name in PINS))
    scan_bytes = L._size(R.native_workspace_allowance(8*max(1, scalar_storage), 4)
                        +UNIT*(objects+1)+2*source_size)
    workspace = R.OwnedWorkspace(budget, scan_bytes, category='heat-finish-inventory-metadata', cancelled=cancel)
    workspace.__enter__()
    try:
        D._runtime(cancel)
        for name, pin in PINS.items():
            L._check(cancel)
            if sha256((HERE/name).read_bytes()).hexdigest() != pin:
                raise ValueError('Reviewed finisher inventory source changed')
        for path, pin in _SOURCES.items():
            L._check(cancel)
            if sha256(Path(path).read_bytes()).hexdigest() != pin:
                raise ValueError('Finisher inventory dependency changed since import')
        ar = L.RationalGrowth(gmp, R, cancel)
        if stage == 'inputs':
            result = _inputs(ar, operands)
        elif stage == 'full_correction':
            result = _full(ar, operands)
        elif stage == 'limited_correction':
            result = _limited(ar, operands)
        elif stage == 'closed_guard':
            result = _closed(ar, operands)
        elif stage == 'issue':
            fixed = 12*(HERE/'private_heat_finish_kernel_r1.py').stat().st_size
            result = _issue(ar, operands, fixed)
        else:
            raise ValueError('Unknown fixed finisher resource stage')
        components, cells, faces, chars, history, certificates = result
        components += [('source_read_and_binding_work', 2*source_size+UNIT*(4*path_count+16)),
                       ('scalar_native_fraction_work', ar.scalar_work(rational_slots=24))]
        work = L._size(sum(value for _, value in components))
        # Stage live results are retained to the outer owner's close. No early
        # release credit: charge another full work generation for result views.
        retained = L._size(work+chars+UNIT*(objects+32))
        inventory = M.DiagnosticInventory(max(1, footprint), work, retained,
            'Derived actual-stage local rational growth and installed Fraction/GMP/MPFR/container/codec policy; '
            'not allocator/RSS, debug record-view or whole-method admission.')
        inventory.total()
        plan = InventoryPlan(inventory, stage, tuple(components),
            tuple((s.numerator, s.denominator) for s in cells),
            tuple((q.numerator, q.denominator) for _, _, q in faces), chars, history, certificates)
        L._check(cancel)
        return P.OwnedSolve(plan, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise
