"""Fixed projection with canonical equality and prospective exact ownership.

The failed R1 symbolic inventory is preserved. This successor admits each
exact operation from its ACTUAL reduced operands, tracks each live array
entry, and settles only after the numerical frame returns. It reuses the
frozen fixed-operation owner; it does not infer shared denominators, reduce
the installed GMP 128*bits policy or raise its ceiling. Codec admission remains
a separate actual-output-width stage. No allocator/RSS/native guarantee.

GMP6.3 canonical mpq has coprime numerator/denominator, positive denominator
and unique0/1. Equality is EXACT equality of both canonical integer parts,
not a cross product. The installed gmpy2 v2.3.2 getters copy mpz parts using
mpz_set: their copies remain prospectively covered by the existing64 scalar
slots and unchanged128*bits native policy. No ambient precision is involved.
https://gmplib.org/manual/Rational-Number-Functions
https://raw.githubusercontent.com/gmpy2/gmpy2/v2.3.2/src/gmpy2_mpq_misc.c
Only old/cap/per-cell-outward arrays are explicitly dropped after their last
use; every output and failed frame retains its owner. Global O is unchanged.
"""
import sys

from atlas_tectonics._private import private_heat_issuer_resources_r1 as BASE
from atlas_tectonics._private.integration.heat import correction_owned as O

A, D, L, P, UNIT = BASE.A, BASE.D, BASE.L, BASE.P, BASE.UNIT
check, workspace, decoded = BASE.check, BASE.workspace, BASE.decoded
stream_hash, target_bytes = BASE.stream_hash, BASE.target_bytes
verified_private = BASE.verified_private
owner_projection_bytes = BASE.owner_projection_bytes
projection_output_plan = BASE.projection_output_plan


def _equality_rank(evidence):
    return (evidence['required_part_bits'], evidence['unused_cross_product_bits'],
            evidence['part_bits'])


class _ProjectionArithmetic(O._Arithmetic):
    def reserve(self, bits):
        try:
            super().reserve(bits)
        except Exception as error:
            # Width/count evidence only. Never capture frames or exact values.
            error.projection_resource_failure = dict(
                attempted_scalar_peak_bits=max(self.peak_bits, bits, 1),
                previous_scalar_peak_bits=self.peak_bits, live_array_bytes=self.live,
                containers_bytes=self.containers, operation_count=self.operations,
                equality=getattr(self, 'equality_evidence', None),
                encoded_array=getattr(self, 'encoded_location', None))
            raise

    def equal(self, left, right):
        if any(type(v) not in (int, self.G.mpq) for v in (left, right)):
            raise TypeError('Already owned canonical mpq or exact int equality operands required')
        # mpq operands come only from this fixed route's admitted decoder or
        # arithmetic. First renew their EXISTING envelope before getter copies.
        self.reserve(max((self.peak_bits, *(v.bit_length() for v in (left, right) if type(v) is int))))
        ln, ld = (left, 1) if type(left) is int else (left.numerator, left.denominator)
        rn, rd = (right, 1) if type(right) is int else (right.numerator, right.denominator)
        parts = (max(1, ln.bit_length()), ld.bit_length(), max(1, rn.bit_length()), rd.bit_length())
        evidence = dict(part_bits=parts, required_part_bits=max(parts),
            unused_cross_product_bits=max(parts[0]+parts[3], parts[2]+parts[1]))
        # Export one actual peak canonical-part witness, rather than whichever
        # cell happened to be visited last. Physical row permutations must not
        # change sealed resource evidence. Rank by required width first, then
        # use deterministic ties; every retained number comes from that one
        # real equality, not synthetic component-wise maxima.
        previous = getattr(self, 'equality_evidence', None)
        if previous is None or _equality_rank(evidence) > _equality_rank(previous):
            self.equality_evidence = evidence
        self.reserve(max(parts))
        self.operations += 1
        return ln == rn and ld == rd

    def release_arrays(self, *values):
        """Fixed caller has reached last use; clear refs BEFORE charge credit."""
        self.check()
        wanted = {id(v) for v in values}
        selected = [(v, charges) for v, charges in self.arrays if id(v) in wanted]
        if len(selected) != len(wanted):
            raise ValueError('Only exact owned arrays may be released at last use')
        freed = sum(sum(charges) for _, charges in selected)
        for v, charges in selected:
            v.clear()
            charges.clear()
        self.live -= freed
        self.released_scratch_bytes = getattr(self, 'released_scratch_bytes', 0)+freed
        self.reserve(self.peak_bits)

    def decode(self, value):
        if type(value) in (tuple, list):
            shape = BASE.pair_shape(value)
            self.reserve(max(shape.numerator, shape.denominator))
            return self.G.mpq(self.G.mpz(value[0]), self.G.mpz(value[1]))
        if type(value) is float:
            self.reserve(max(self.peak_bits, 1075))
            return self.G.mpq(value)
        if type(value) is self.G.mpq:
            self.reserve(max(self.peak_bits, 8*sys.getsizeof(value)+64))
            return value
        if type(value) is BASE.L.Fraction or type(value) is int:
            self.reserve(max(self.peak_bits, value.numerator.bit_length(), value.denominator.bit_length()))
            return self.G.mpq(value.numerator, value.denominator)
        raise TypeError('Original binary64 or exact owned rational/pair required')

    def decoded_array(self, values, count):
        if len(values) != count:
            raise ValueError('Complete original projection array required')
        result = self.array(count)
        for at, value in enumerate(values):
            self.put(result, at, self.decode(value))
        return result[1]

    def encoded_equal(self, values, encoded, label):
        if len(values) != len(encoded):
            raise ValueError('Complete original '+label+' array required')
        mpz, mpq = self.G.mpz, self.G.mpq
        for at, (value, pair) in enumerate(zip(values, encoded, strict=True)):
            self.encoded_location = dict(array=label, index=at)
            if type(pair) in (tuple, list) and type(value) in (int, mpq):
                # The writer encodes a canonical pair as decimal digits (private_heat_finish_kernel_r3
                # _encode_rational): equal strings are equal numbers. decode's reservation stays, its
                # parse is skipped; equal(value, value) makes the same reservations, evidence and count.
                shape = BASE.pair_shape(pair)
                self.reserve(max(shape.numerator, shape.denominator))
                if pair[0] == mpz(value.numerator).digits(10) and pair[1] == mpz(value.denominator).digits(10):
                    self.equal(value, value)
                    continue
            if not self.equal(value, self.decode(pair)):
                raise ValueError('Returned '+label+' differs from the actual original values')

    def total(self, values):
        total = self.G.mpq(0)
        for value in values:
            total = self.op('add', total, value)
        return total


class ProjectionNumerics(O.OwnedSolve):
    @property
    def inventory(self):
        self.value
        ar = self._workspace.arithmetic
        return dict(route='ACTUAL_REDUCED_OPERAND_CANONICAL_EQUALITY_PROJECTION', operations=ar.operations,
            actual_retained_rational_bytes=ar.live, scalar_peak_bits=ar.peak_bits,
            scalar_slots=64, retained_reserved_bytes=ar.workspace.lease.count,
            released_last_use_scratch_bytes=getattr(ar, 'released_scratch_bytes', 0),
            exact_canonical_part_equality=True, equality_evidence=getattr(ar, 'equality_evidence', None),
            allocator_or_rss_bound=False, native_admission=False)


def _checked_face_arrays(ar, record, n, nf):
    if len(record['physical_faces']) != nf:
        raise ValueError('Complete original physical face inventory required')
    return ar.array(n), ar.array(nf)


def _issued_face_arrays(ar, _record, n, nf):
    return ar.array(n), ar.array(nf)


def _check_temperatures(ar, temperatures, stored, cap):
    if temperatures != [e/ar.public(c) for e, c in zip(stored, cap, strict=True)]:
        raise ValueError('Public temperature must be actual stored energy / original capacity')


def _reserve_issued_temperatures(ar, _temperatures, _stored, cap):
    # The sealed producer used these exact represented binary64 capacities.
    # Keep the original reservation and live poll for each one.
    for _ in cap:
        ar.reserve(1075)


def _calculate(ar, record, incidence, old_values, cap_values, source_values, dt, target_value, *,
               face_arrays=_checked_face_arrays, check_temperatures=_check_temperatures):
    n, nf = len(old_values), len(incidence)
    old, cap, source = [ar.decoded_array(values, n) for values in (old_values, cap_values, source_values)]
    if any(not ar.less(0, e) or not ar.less(0, c) for e, c in zip(old, cap, strict=True)):
        raise ValueError('Positive original stocks and capacities required')
    delta, target = ar.decode(float(dt)), ar.decode(target_value)
    src = ar.array(n)
    for i, value in enumerate(source):
        ar.put(src, i, ar.op('multiply', delta, value))
    source = src[1]
    for values, key in ((old, 'old_energy'), (cap, 'capacity'), (source, 'source_energy')):
        ar.encoded_equal(values, record[key], 'original stocks/capacities/sources')
    if not ar.less(0, target) or not ar.equal(target, ar.decode(record['independently_supplied_absolute_residual_target'])):
        raise ValueError('Original independently supplied residual target differs')
    out, canonical = face_arrays(ar, record, n, nf)
    zero = ar.G.mpq(0)
    plus, minus = [[zero] for _ in range(n)], [[] for _ in range(n)]    # out = 0 + inflow - outflow
    outward = ar.G.mpq(0)
    for f, ((i, j, pair), linked) in enumerate(zip(record['physical_faces'], incidence, strict=True)):
        ar.check()
        expected = (linked[0][0], linked[1][0] if len(linked) == 2 else None)
        if type(i) is not int or j is not None and type(j) is not int or (i, j) != expected:
            raise ValueError('Actual face owner order differs at face '+str(f))
        amount = ar.decode(pair)
        signed = amount if linked[0][1] == 1 else ar.neg(amount)
        ar.put(canonical, f, signed)
        for owner, sign in linked:
            (plus if sign == 1 else minus)[owner].append(signed)
        if j is None:
            outward = ar.op('add', outward, amount)
    ar.cell_sums(plus, minus, into=out)
    del plus, minus
    new = ar.decoded_array(record['corrected_energy_exact'], n)
    stored, temperatures = record['enthalpy_j'], record['temperature_k']
    if len(stored) != n or len(temperatures) != n:
        raise ValueError('Complete returned stock and temperature arrays required')
    if stored != [ar.public(value) for value in new]:
        raise ValueError('Public energy is not the single correctly rounded exact stock projection')
    check_temperatures(ar, temperatures, stored, cap)
    retained, projection, public = ar.array(n), ar.array(n), ar.array(n)
    for i in range(n):
        ar.put(retained, i, ar.op('subtract', ar.op('add', ar.op('subtract', new[i], old[i]), out[1][i]), source[i]))
        represented = ar.decode(float(stored[i]))
        ar.put(projection, i, ar.op('subtract', represented, new[i]))
        ar.put(public, i, ar.op('subtract', ar.op('add', ar.op('subtract', represented, old[i]), out[1][i]), source[i]))
        del represented
        absolute = ar.neg(retained[1][i]) if ar.less(retained[1][i], 0) else retained[1][i]
        if ar.less(target, absolute):
            raise ValueError('Original retained solver residual target failed')
    # Last use is established above: public T used cap; all retained/public
    # residuals used old/out. Clear exact entries before releasing admission.
    # Source values stay live for the unchanged final source-total operation.
    ar.release_arrays(old, cap, out[1])
    for key, values in (('exact_cell_residual', retained[1]), ('stock_projection_residual', projection[1]),
                        ('public_cell_residual', public[1])):
        ar.encoded_equal(values, record[key], key)
    for a, b, c in zip(retained[1], projection[1], public[1], strict=True):
        if not ar.equal(ar.op('add', a, b), c):
            raise ArithmeticError('Total public residual must include retained and projection terms')
    # Retained for the issuer's independent physical declaration check. It
    # must not decode the same potentially large rationals again unaccounted.
    boundary = {}
    for name in ('boundary_temperature', 'prescribed_boundary_energy'):
        values = ar.decoded_array(list(record[name].values()), len(record[name]))
        boundary[name] = dict(zip(record[name], values, strict=True))
    return dict(new=new, retained=retained[1], projection=projection[1], public=public[1],
        canonical=canonical[1], target=target, source_total=ar.total(source), outward=outward, boundary=boundary)


def calculate(record, geometry, old, cap, source, dt, target, *, budget, cancel=None):
    """Own exact projection values; only the fixed arithmetic above runs."""
    return _calculate_owned(record, geometry, old, cap, source, dt, target, budget=budget, cancel=cancel,
                            face_arrays=_checked_face_arrays, check_temperatures=_check_temperatures)


def _calculate_issued(record, geometry, old, cap, source, dt, target, *, budget, cancel=None):
    """Project the record decoded from the exact seal issued on the fixed forward route."""
    return _calculate_owned(record, geometry, old, cap, source, dt, target, budget=budget, cancel=cancel,
                            face_arrays=_issued_face_arrays, check_temperatures=_reserve_issued_temperatures)


def _calculate_owned(record, geometry, old, cap, source, dt, target, *, budget, cancel,
                     face_arrays, check_temperatures):
    check(cancel)
    G = A.exact_library()
    from atlas_tectonics._private.integration.heat import gmp_resources as GMP
    n, nf = len(geometry._cells), len(geometry._face_ids)
    if not n or any(len(v) != n for v in (old, cap, source)):
        raise ValueError('Complete original represented arrays required')
    work = GMP.OwnedWorkspace(budget, 65536, category='private-heat-projection-actual', cancelled=cancel)
    work.__enter__()
    owned = O._OwnerWorkspace(work)
    try:
        # Only the first binary64 conversions exist yet. Each later decimal
        # pair is admitted from its character widths before GMP parsing.
        ar = _ProjectionArithmetic(work, G, GMP, n, nf, 1075, lambda: check(cancel))
        owned.arithmetic = ar
        result = _calculate(ar, record, geometry._incidence, old, cap, source, dt, target,
                            face_arrays=face_arrays, check_temperatures=check_temperatures)
        # The operation frame and its temporary products are gone. Preserve
        # actual final values, not fictitious unreduced expression arrays.
        ar.settle(result)
        return ProjectionNumerics(result, owned)
    except BaseException:
        owned.__exit__(*sys.exc_info())
        raise
