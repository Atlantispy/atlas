"""B1 successor: fund newly borrowed wide GMP getters before scalar inspection.

Support selection and all basis arithmetic are unchanged. A later face moment,
normal or conductivity may have more limbs than the initial point/frame inputs.
The already-owned object's footprint provides a conservative bit bound before
copying its GMP numerator/denominator into the arena's inspected expression.
"""
import sys

import private_heat_support_basis_resources_r1 as B

support = B.support


class Basis(B.Basis):
    def q(self, value):
        if type(value) in (int, B.G.mpq):
            self.arena.reserve(max(1, 8*sys.getsizeof(value)))
        return super().q(value)


def basis(centre, sample_points, *, budget, cancelled=None):
    B.F.K._require_gmp()
    B.I.check(cancelled)
    if type(sample_points) not in (list, tuple) or not sample_points or len(centre) != 3:
        raise ValueError('Explicit initial support points and centre required')
    largest = 1
    for point in (centre, *sample_points):
        if type(point) not in (list, tuple) or len(point) != 3:
            raise ValueError('Exact 3D point required')
        for value in point:
            largest = max(largest, B._coordinate(value))
    import private_heat_gmp_resources_r1 as R
    metadata = 262144+B.L.CONTAINER_UNIT*(8*len(sample_points)+256)
    work = R.OwnedWorkspace(budget, metadata, category='heat-cubic-basis-growth', cancelled=cancelled)
    work.__enter__()
    try:
        B._verify(cancelled)
        ar = B.E.Arithmetic(work, B.G, scalar_slots=128, container_bytes=metadata,
            initial_bits=max(2200, 8*largest), cancelled=cancelled)
        result = Basis(ar, centre, sample_points)
        return B.P.OwnedSolve(result, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise
