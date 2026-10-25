"""Derived public-rounding contraction stage, reusing all frozen FINISH stages.

No mathematical decision is made here. The new stage is admitted only after
the exact FCT endpoint is valid but its actual public conversion fails. All
earlier stage leases remain held. This stage funds whole-cell upper bounds
even though the numerical predicate selects only endpoint-failing cells.
The 64 scalar refinements retain history, not 64 rational state generations.
Installed Python/GMP accounting remains a policy, not an allocator/RSS proof.
"""
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_finish_inventory_r1 as B

HERE = Path(__file__).resolve().parent
PINS = dict(B.PINS, **{
    'private_heat_finish_inventory_r1.py': '0c02e0dcfae89d186913e50f878d3d0b3a402173c1942b06bdfea9a3fa974ea4',
    'private_heat_finish_kernel_r2.py': '1bb0b5e21c826e6967e9c52c64779e37536560eaf2b846783bbd682e723491df',
    'private_heat_public_float_r1.py': '9ce024ccc0922034b25ea578fadf6e99c403c7132a5f91066d11f0190f1f39a1',
})
_SOURCES = dict(B._SOURCES, **{str(Path(__file__).resolve()): sha256(Path(__file__).read_bytes()).hexdigest(),
    str(Path(B.__file__).resolve()): PINS['private_heat_finish_inventory_r1.py']})
InventoryPlan = B.InventoryPlan


def _contraction(ar, d):
    low, candidate, cap, bounds, alphas = [[B._q(ar, v) for v in d[name]]
        for name in ('low', 'candidate', 'cap', 'bounds', 'alphas')]
    lo_faces, hi_faces = B._faces(ar, d['low_faces']), B._faces(ar, d['faces'])
    if len(low) != len(candidate) or len(low) != len(cap) or len(bounds) != 2:
        raise ValueError('Complete original contraction state required')
    if len(lo_faces) != len(hi_faces) or len(alphas) != len(lo_faces):
        raise ValueError('Complete original contraction faces and alphas required')
    difference = [ar.op('subtract', e, l) for e, l in zip(candidate, low, strict=True)]
    energy = [ar.op('add', l, ar.op('multiply', B.THETA, delta))
              for l, delta in zip(low, difference, strict=True)]
    faces, changes = [], []
    for left, right in zip(lo_faces, hi_faces, strict=True):
        if left[:2] != right[:2]:
            raise ValueError('Contraction preserves original face owner/order')
        change = ar.op('subtract', right[2], left[2])
        changes.append(change)
        faces.append((left[0], left[1], ar.op('add', left[2], ar.op('multiply', B.THETA, change))))
    corrected_alphas = [ar.op('multiply', B.THETA, alpha) for alpha in alphas]
    for values in (low, candidate, energy):
        B._bound_work(ar, values, cap, bounds)
    # The caller immediately verifies the new, theta-bearing exact ledger.
    # Earlier full/signwise checks have smaller shapes and cannot fund this
    # changed arithmetic merely because their arrays remain owned.
    residual = B._residual(ar, energy, faces, [B.ZERO]*len(low))
    prior = B._residual(ar, low, lo_faces, [B.ZERO]*len(low))
    for current, previous in zip(residual, prior, strict=True):
        ar.op('subtract', current, previous)
    # Original/candidate/low/final public checks, an active predicate and its
    # final all-cell check may overlap. Charge every cell, never guess k.
    n, f = len(low), len(faces)
    states = B._slots(ar, difference+energy+changes+corrected_alphas+residual+prior+[q for _, _, q in faces], 4)
    public = 12*n*ar.slot(B.PUBLIC)
    # Six bounds dicts, failing indices/capacity references, selected and full
    # arrays, two bracket endpoints, 66 retained decision records and theta
    # values (denominators divide 2**64). No old generation is released here.
    containers = B.UNIT*(128+36*n+20*f+66*6)
    history = 70*ar.slot(B.THETA)
    components = [('public_contraction_exact_local_generations', states),
        ('public_contraction_actual_float_checks', public),
        ('public_contraction_arrays_checks_and_64_step_history', containers+history)]
    return components, energy, faces


def admit(stage, operands, *, source_bindings, budget, additional_bindings=None, cancel=None):
    """Own a prospective plan; unchanged stages use frozen r1 verbatim."""
    if stage != 'public_rounding_contraction':
        return B.admit(stage, operands, source_bindings=source_bindings, budget=budget,
                       additional_bindings=additional_bindings, cancel=cancel)
    B.L._check(cancel)
    gmp = B.L.A.exact_library()
    import private_heat_gmp_resources_r1 as R
    footprint, objects, _ = B.L._footprint((operands, source_bindings, additional_bindings), gmp, cancel)
    scalar = B._scalar_storage(operands, gmp, cancel)
    maps = (source_bindings, _SOURCES) if additional_bindings is None else (source_bindings, additional_bindings, _SOURCES)
    if any(type(values) is not dict for values in maps):
        raise ValueError('Original source binding dictionaries required')
    path_count = sum(len(values) for values in maps)+len(PINS)
    source_size = max(max((Path(path).stat().st_size for values in maps for path in values), default=0),
                      max((HERE/name).stat().st_size for name in PINS))
    amount = B.L._size(R.native_workspace_allowance(8*max(1, scalar), 4)
                      +B.UNIT*(objects+1)+2*source_size)
    workspace = R.OwnedWorkspace(budget, amount, category='heat-finish-contraction-metadata', cancelled=cancel)
    workspace.__enter__()
    try:
        B.D._runtime(cancel)
        for name, pin in PINS.items():
            B.L._check(cancel)
            if sha256((HERE/name).read_bytes()).hexdigest() != pin:
                raise ValueError('Reviewed contraction inventory source changed')
        for path, pin in _SOURCES.items():
            B.L._check(cancel)
            if sha256(Path(path).read_bytes()).hexdigest() != pin:
                raise ValueError('Contraction inventory dependency changed since import')
        ar = B.L.RationalGrowth(gmp, R, cancel)
        components, cells, faces = _contraction(ar, operands)
        components += [('source_read_and_binding_work', 2*source_size+B.UNIT*(4*path_count+16)),
                       ('scalar_native_fraction_work', ar.scalar_work(rational_slots=24))]
        work = B.L._size(sum(value for _, value in components))
        retained = B.L._size(work+B.UNIT*(objects+32))
        inventory = B.M.DiagnosticInventory(max(1, footprint), work, retained,
            'Derived conservative public-rounding contraction local growth and installed policy; '
            'all old stages retained; not allocator/RSS or whole-method admission.')
        inventory.total()
        plan = InventoryPlan(inventory, stage, tuple(components),
            tuple((s.numerator, s.denominator) for s in cells),
            tuple((q.numerator, q.denominator) for _, _, q in faces),
            search_history_entries=66, simultaneous_certificates=6)
        B.L._check(cancel)
        return B.P.OwnedSolve(plan, workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise
