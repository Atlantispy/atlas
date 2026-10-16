"""Owned unchanged complete-shell support and incrementally owned cubic basis.

Inputs are already owned exact physical coordinates/moments. Support admits
all possible cached distances and full-ranking generations before the original
screen, including its deferred rank-expansion path. Basis storage grows before
each returned vector and every exact scalar operation. Borrowed support/basis
values must not outlive their owners. This is an accounted policy, not an
allocator/RSS bound or admission of decoded geometry, CERT or complete rows.
"""
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_functionals_kernel_r1 as F
import private_heat_certification_resources_r1 as I
import private_heat_decimal_sparse_core_r1 as P
import private_heat_exact_growth_r1 as E
import private_heat_low_ledger_inventory_r1 as L

G = F.G
FUNCTIONALS_SHA = 'a48f115e8018b9c2d831ce1442cba1060a22d0a5fdbc39b6c8165674a0b0ab56'


def _verify(cancelled):
    I.verify_sources(cancelled)
    if sha256(Path(F.__file__).read_bytes()).hexdigest() != FUNCTIONALS_SHA:
        raise ValueError('Reviewed support/basis source changed')


def _coordinate(value):
    if type(value) not in (int, Fraction, G.mpq):
        raise TypeError('Already owned int/Fraction/GMP physical coordinate required')
    return max(sys.getsizeof(value), sys.getsizeof(value.numerator),
               sys.getsizeof(value.denominator)) if type(value) is Fraction else sys.getsizeof(value)


def support(observations, centre, *, budget, minimum=40, cancelled=None, resource_evidence=None):
    """Owner of original ScreenedSupport; .full_ranking() is already funded."""
    F.K._require_gmp()
    I.check(cancelled)
    if type(observations) not in (list, tuple) or not observations or type(centre) not in (list, tuple) or len(centre) != 3:
        raise ValueError('Owned explicit observation pool and 3D centre required')
    largest, text = 1, 0
    for key, point in observations:
        I.check(cancelled)
        if type(key) is not tuple or len(key) != 2 or key[0] not in ('cell', 'wall', 'power'):
            raise ValueError('Declared cell/wall/power observation keys required')
        if (key[0] == 'cell' and (type(key[1]) is not int or key[1] < 0)) or (key[0] != 'cell' and type(key[1]) is not str):
            raise ValueError('Original typed observation identity required')
        # str(tuple) uses repr: string escapes can expand one character to ten.
        text += 64+40*(len(key[1]) if type(key[1]) is str else max(1, key[1].bit_length()))
        if type(point) not in (tuple, list) or len(point) != 3:
            raise ValueError('Three-dimensional exact observation point required')
        for value in point:
            largest = max(largest, _coordinate(value))
    for value in centre:
        largest = max(largest, _coordinate(value))
    import private_heat_gmp_resources_r1 as R
    m = len(observations)
    metadata = I.size(262144+L.CONTAINER_UNIT*(24*m+128)+text+R.native_workspace_allowance(8*largest, 32))
    work = R.OwnedWorkspace(budget, metadata, category='heat-complete-support', cancelled=cancelled)
    work.__enter__()
    try:
        _verify(cancelled)
        ar = L.RationalGrowth(G, R, cancelled)
        c = [ar.q(value) for value in centre]
        cached, shapes = 0, []
        for _, point in observations:
            difference = [ar.op('subtract', ar.q(a), b) for a, b in zip(point, c, strict=True)]
            distance = ar.total(ar.op('multiply', d, d) for d in difference)
            cached += ar.slot(distance)
            shapes.append(distance)
            # Adjacent binary64 enclosure comparisons use <=1075-bit parts.
            for value in point:
                ar.op('subtract', ar.q(value), L.PUBLIC_BINARY64)
        for value in c:
            ar.op('subtract', value, L.PUBLIC_BINARY64)
        ar.choice(shapes)  # bound all exact distance comparison products
        # Original points/ties/cache/full+shell/ordered/seed/retained/lower,
        # list and tuple generations, sort keys/scratch all counted together.
        containers = L.CONTAINER_UNIT*(48*m+128)+text
        total = I.size(metadata+cached+containers+ar.scalar_work(rational_slots=48))
        work.resize_before_allocation_or_after_drop(total)
        result = F.nearest_complete_shell(observations, centre, minimum=minimum, cancelled=cancelled)
        if resource_evidence is not None:
            resource_evidence.update(observations=m, admitted_bytes=total,
                maximum_expression_bits=ar.expression_bits, deferred_full_ranking_admitted=True,
                support_selection_unchanged=True, prospective_accounted_policy=True,
                allocator_or_rss_bound=False, whole_reconstruction_admission=False)
        return P.OwnedSolve(result, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


class Basis:
    """Borrowed owned builder. Every output remains charged until owner closes."""
    def __init__(self, arena, centre, points):
        self.arena = arena
        self.vectors = 0
        self.origin = tuple(self.q(F.G.mpq(float(value))) for value in centre)
        extent = G.mpq(0)
        for point in points:
            for a, b in zip(point, self.origin, strict=True):
                candidate = abs(self.op('subtract', self.q(a), b))
                if candidate > extent:
                    extent = candidate
        if not extent:
            raise ValueError('Distinct geometric observations required')
        exponent = extent.numerator.bit_length()-extent.denominator.bit_length()
        arena.reserve(abs(exponent)+2)
        self.scale = G.mpq(2)**exponent
        if self.scale < extent:
            self.scale = self.op('multiply', self.scale, 2)

    def q(self, value):
        if type(value) is Fraction:
            self.arena.reserve(max(1, value.numerator.bit_length(), value.denominator.bit_length()))
            self.arena.operations += 1
            return G.mpq(value.numerator, value.denominator)
        return self.arena.q(value)

    def op(self, operation, a, b):
        return self.arena.rational(operation, a, b)

    def total(self, values):
        result = self.q(0)
        for value in values:
            result = self.op('add', result, value)
        return result

    def _vector(self):
        # Three normalised coordinates, powers/averages and arithmetic locals
        # live in the fixed128 scratch slots; each retained vector has20 values.
        self.arena.slots += 20
        self.arena.containers += 24*L.CONTAINER_UNIT
        self.arena.reserve(self.arena.peak_bits)
        self.vectors += 1

    def point(self, point):
        self._vector()
        coordinate = [self.op('divide', self.op('subtract', self.q(a), b), self.scale)
                      for a, b in zip(point, self.origin, strict=True)]
        result = []
        for exponent in F.EXPONENTS:
            product = self.q(1)
            for value, power in zip(coordinate, exponent, strict=True):
                factor = self.q(1)
                for _ in range(power):
                    factor = self.op('multiply', factor, value)
                product = self.op('multiply', product, factor)
            result.append(product)
        return result

    def flux(self, face_point, normal, moment, conductivity):
        self._vector()
        mean = [self.op('divide', self.op('subtract', self.q(a), b), self.scale)
                for a, b in zip(face_point, self.origin, strict=True)]
        def average(exponent):
            indices = [i for i, power in enumerate(exponent) for _ in range(power)]
            if not indices:
                return self.q(1)
            if len(indices) == 1:
                return mean[indices[0]]
            i, j = indices
            return self.op('add', self.op('multiply', mean[i], mean[j]),
                self.op('divide', self.q(moment[i][j]), self.op('multiply', self.scale, self.scale)))
        return [self.op('multiply', -self.q(conductivity), self.total(
                    self.op('divide', self.op('multiply', self.op('multiply', self.q(normal[j]), power),
                        average(tuple(p-int(i == j) for i, p in enumerate(exponent)))), self.scale)
                    for j, power in enumerate(exponent) if power))
                for exponent in F.EXPONENTS]

    def multiply(self, values, factor):
        if len(values) != 20:
            raise ValueError('Twenty original cubic actions required')
        self._vector()
        return [self.op('multiply', self.q(factor), value) for value in values]

    def target(self, gradient, left, right, signed_tau):
        if any(len(row) != 20 for row in (gradient, left, right)):
            raise ValueError('Twenty original cubic actions required')
        self._vector()
        return [self.op('subtract', g, self.op('multiply', signed_tau, self.op('subtract', a, b)))
                for g, a, b in zip(gradient, left, right, strict=True)]


def basis(centre, sample_points, *, budget, cancelled=None):
    """Owner of a growing Basis; only source-identical frame and exact actions."""
    F.K._require_gmp()
    I.check(cancelled)
    if type(sample_points) not in (list, tuple) or not sample_points or len(centre) != 3:
        raise ValueError('Explicit initial support points and centre required')
    largest = 1
    for point in (centre, *sample_points):
        if type(point) not in (list, tuple) or len(point) != 3:
            raise ValueError('Exact 3D point required')
        for value in point:
            largest = max(largest, _coordinate(value))
    import private_heat_gmp_resources_r1 as R
    metadata = 262144+L.CONTAINER_UNIT*(8*len(sample_points)+256)
    work = R.OwnedWorkspace(budget, metadata, category='heat-cubic-basis-growth', cancelled=cancelled)
    work.__enter__()
    try:
        _verify(cancelled)
        ar = E.Arithmetic(work, G, scalar_slots=128, container_bytes=metadata,
                          initial_bits=max(2200, 8*largest), cancelled=cancelled)
        result = Basis(ar, centre, sample_points)
        return P.OwnedSolve(result, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise
