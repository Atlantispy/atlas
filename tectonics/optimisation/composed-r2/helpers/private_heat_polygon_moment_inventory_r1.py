"""Prospective owned polygon second moments; unchanged exact numerical helper.

This stage derives rational shape growth from encoded vertex widths before any
vertex int/Fraction decode. Every generated scalar is charged cumulatively,
which overcounts lifetimes deliberately; the maximum expression also funds the
installed GMP/Python exact-work policy. After the numerical helper's transient
frame is gone, admission shrinks to the prospectively bounded 3x3 result/plan.
Polygon validation, expression order and values remain the predecessor's.
No HIGH support/basis/interval/rank/elimination/row admission is implied.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_geometry_inventory_r1 as START
import private_heat_low_ledger_inventory_r1 as L
import private_heat_interval_inventory_r1 as I
import private_heat_decimal_sparse_core_r1 as P

FUNCTIONALS_SHA = 'a48f115e8018b9c2d831ce1442cba1060a22d0a5fdbc39b6c8165674a0b0ab56'
ONE = I.Shape(1, 1, True)


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Polygon moment inventory cancelled')


def _hex_shape(pair):
    # Bounds from text width only: the original decoder retains responsibility
    # for valid integers, nonzero denominators and exact polygon validation.
    if type(pair) not in (tuple, list) or len(pair) != 2 or any(type(v) is not str or not v for v in pair):
        raise ValueError('Owned encoded rational pair required')
    return I.Shape(max(1, 4*len(pair[0])), max(1, 4*len(pair[1])), False)


@dataclass(frozen=True)
class MomentPlan:
    metadata_bytes: int
    components: tuple
    vertices: int
    scalar_operations: int
    output_shapes: tuple
    maximum_expression_bits: int
    prospective_accounted_policy: bool = True
    allocator_or_rss_bound: bool = False
    whole_reconstruction_admission: bool = False

    @property
    def total_bytes(self):
        return START._size(self.metadata_bytes+sum(value for _, value in self.components))

    @property
    def retained_bytes(self):
        return dict(self.components)['owned_result_and_plan']


class _Growth(L.RationalGrowth):
    def __init__(self, gmp, resources, cancel):
        super().__init__(gmp, resources, cancel)
        self.generated_bytes = self.operations = 0

    def retain(self, shape):
        self.generated_bytes = START._size(self.generated_bytes+self.slot(shape))
        return shape

    def op(self, operation, left, right, **kwargs):
        shape = super().op(operation, left, right, **kwargs)
        self.operations += 1
        return self.retain(shape)


def _plan(face, metadata_bytes, ar):
    def vector(raw):
        if type(raw) not in (list, tuple) or len(raw) != 3:
            raise ValueError('Three-dimensional encoded vector required')
        return tuple(ar.retain(_hex_shape(pair)) for pair in raw)

    def sub(a, b):
        return tuple(ar.op('subtract', x, y) for x, y in zip(a, b, strict=True))

    def cross(a, b):
        return tuple(ar.op('subtract', ar.op('multiply', a[i], b[j]),
                          ar.op('multiply', a[j], b[i])) for i, j in ((1, 2), (2, 0), (0, 1)))

    def dot(a, b):
        return ar.total(ar.op('multiply', x, y) for x, y in zip(a, b, strict=True))

    two, three, twelve = (ar.q(value) for value in (2, 3, 12))
    points = [vector(p) for p in face['vertices_m']]
    centre, normal = vector(face['centroid_m']), vector(face['area_vector_m2'])
    count = len(points)
    dot(normal, normal)
    shifted = [sub(p, centre) for p in points]
    for p in shifted:
        dot(p, normal)
    fan = [(shifted[0], a, b) for a, b in zip(shifted[1:-1], shifted[2:], strict=True)]
    areas = [tuple(ar.op('divide', v, two) for v in cross(sub(b, a), sub(c, a))) for a, b, c in fan]
    for j in range(3):
        ar.total(v[j] for v in areas)
    # Both possible orientations are magnitude-one multipliers; neither can
    # enlarge value bits. Charge their exact products as in the original code.
    for a, b in zip(shifted, shifted[1:]+shifted[:1], strict=True):
        for p in shifted:
            ar.op('multiply', ONE, dot(cross(sub(b, a), sub(p, a)), normal))
    weights = [ar.op('divide', ar.op('multiply', ONE, dot(a, normal)), dot(normal, normal)) for a in areas]
    ar.total(weights)
    for j in range(3):
        ar.total(ar.op('divide', ar.op('multiply', w, ar.total(v[j] for v in triangle)), three)
                 for w, triangle in zip(weights, fan, strict=True))
    output = []
    for i in range(3):
        row = []
        for j in range(3):
            terms = []
            for w, tri in zip(weights, fan, strict=True):
                diagonal = ar.total(ar.op('multiply', v[i], v[j]) for v in tri)
                product = ar.op('multiply', ar.total(v[i] for v in tri), ar.total(v[j] for v in tri))
                terms.append(ar.op('divide', ar.op('multiply', w, ar.op('add', diagonal, product)), twelve))
            shape = ar.total(terms)
            row.append((shape.numerator, shape.denominator))
        output.append(tuple(row))
    # Width-derived parsing is funded too: int(base16), Fraction normalisation,
    # comparisons/hash temporaries, and all separately retained output values.
    components = (('all_generated_exact_scalars', ar.generated_bytes),
        ('polygon_containers_and_validation', L.CONTAINER_UNIT*(80*count+128)),
        ('maximum_expression_workspace', ar.scalar_work(rational_slots=32)),
        ('owned_result_and_plan', L.CONTAINER_UNIT*128+sum(ar.slot(I.Shape(nb, db, False))
             for row in output for nb, db in row)))
    plan = MomentPlan(metadata_bytes, components, count, ar.operations, tuple(output), ar.expression_bits)
    plan.total_bytes
    return plan


def admit(face, *, budget, cancel=None):
    """An owned shape plan; supplied encoded face remains caller-owned."""
    _check(cancel)
    if type(face) is not dict or type(face.get('vertices_m')) is not list or len(face['vertices_m']) < 3:
        raise ValueError('Owned face with at least three declared vertices required')
    from atlas_tectonics import exact_arithmetic
    import private_heat_gmp_resources_r1 as R
    G = exact_arithmetic.library()
    if G is None:
        raise RuntimeError('Selected GMP backend required')
    metadata = START._size(262144+L.CONTAINER_UNIT*(100*len(face['vertices_m'])+512))
    work = R.OwnedWorkspace(budget, metadata, category='heat-polygon-moment-inventory', cancelled=cancel)
    work.__enter__()
    try:
        START._verify_sources(cancel)
        import private_heat_functionals_kernel_r1 as F
        # This source is small and its complete bytes fit the fixed admitted
        # source-read buffers. It is not the geometry or any captured operands.
        if sha256(Path(F.__file__).read_bytes()).hexdigest() != FUNCTIONALS_SHA:
            raise ValueError('Reviewed polygon expression source changed')
        plan = _plan(face, metadata, _Growth(G, R, cancel))
        return P.OwnedSolve(plan, work)
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


def second_moment(face, *, budget, cancel=None):
    """Return owner of {'moment', 'inventory'}; no geometry is rounded.

    Cancellation checkpoints surround the frozen numerical helper; its Python
    polygon loops are not yet scalar-cancellable. The metadata pass is checked
    per expression. Caller must keep this owner live with all borrowed moments.
    """
    owner = admit(face, budget=budget, cancel=cancel)
    work = owner._workspace
    try:
        plan = owner.value
        work.resize_before_allocation_or_after_drop(plan.total_bytes)
        _check(cancel)
        import private_heat_functionals_kernel_r1 as F
        moment = F.face_second_moment(face)
        _check(cancel)
        owner._value = dict(moment=moment, inventory=plan)
        # The original helper and metadata arithmetic frames have returned, so
        # their points/fans/scalars are no longer live. Only the independently
        # bounded moment/plan is borrowed from this owner on successful return.
        work.resize_before_allocation_or_after_drop(plan.retained_bytes)
        return owner
    except BaseException:
        owner._workspace = None
        owner._value = None
        work.__exit__(*sys.exc_info())
        raise
