"""Completed-stage output custody; no heat arithmetic or early failure credit.

Call only after the fixed producer has returned. All input graphs must already
be owned. A new complete output charge is reserved BEFORE the old owner closes.
Aliasing is counted repeatedly; no source data, precision, ordering or numerical
output is changed. Projecting to a fixed container/dataclass path requires the
caller to have dropped, or separately transferred, EVERY omitted borrowed value.

Outputs are immutable-by-contract while borrowed. Mutation/addition after this
inspection is not admitted. Callback-retained producer temporaries are forbidden
by the producer contracts. Import/runtime, caller native geometry and debug JSON
views remain caller-owned. Policies are not an allocator/RSS or native theorem.

R2 charges each object of a completed output at the blocks it occupies (counted
blocks r1) where that module supports the runtime. An exact number that exists
reports the limbs allocated for it, so R1's recycled-slot allowance per number,
and the scratch R1 reserved for reading each number's parts, are not needed.
On any other runtime R1's figures are used unchanged.

R3 counts by counted blocks r2. That module also refuses an interpreter with a
debug or replaced allocator and one that is tracing. R1's figure alone is
below the blocks of an object that is not an exact number, so there each
object is charged the larger of R1's figure for it and its blocks as those
allocators make them (that module's ``refused_bytes``): never less than R1
held. It counts a block that may have shrunk from the C heap at the C-heap
figure, and each transfer adds that module's allowance for every record
instance with a dictionary that it meets, up to what all the early instances
of one class can hold.
"""

from concurrent.futures import CancelledError
from dataclasses import fields
from decimal import Decimal
from fractions import Fraction
import sys
from typing import cast

from atlas_tectonics._private.integration.heat import counted_blocks as COUNT
from atlas_tectonics._private import private_heat_decimal_sparse_core_r1 as P
from atlas_tectonics._private.integration.heat import owned_interval_assessment as A
from atlas_tectonics._private import private_heat_geometry_inventory_r1 as GEOMETRY
from atlas_tectonics._private import private_heat_finish_kernel_r3 as RESULT

MAX_DEPTH = 64
TRAVERSAL_BYTES = 1024*(2*(MAX_DEPTH+1)+32)
RECORD_TYPES = (A.CertifiedAssembly, A.A.CertifiedFace, A.RefinementRequired,
    A.A.AmbiguousAggregate, A.A.Contribution, P.RoundedSystem, P.RoundedFace,
    GEOMETRY.PreparationPlan, RESULT.PrivateNumericalResult)


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Completed heat stage transfer cancelled')


def _size(value):
    return value


def _sources(cancel):
    pass


class OwnedValue(P.OwnedSolve):
    @property
    def accounted_bytes(self):
        self.value
        return self._workspace.lease.count

    @property
    def retention(self):
        self.value
        return self._retention

    def close(self):
        self._retention = None
        super().close()

    def __exit__(self, kind, error, traceback):
        self._retention = None
        return super().__exit__(kind, error, traceback)


class OwnedAssessment(OwnedValue):
    """A completed assessment and at most ONE pre-admitted rounded-system view."""
    def __init__(self, value, work, system, boundary_items):
        super().__init__(value, work)
        self._system, self._boundary_items = system, boundary_items

    def rounded_system(self, boundary, *, cancel=None):
        _check(cancel)
        for key, kind, value in self._boundary_items:
            _check(cancel)
        return self._system

    def close(self):
        self._system, self._boundary_items = None, None
        super().close()

    def __exit__(self, kind, error, traceback):
        self._system, self._boundary_items = None, None
        return super().__exit__(kind, error, traceback)


def _select(value, path):
    for key in path:
        if type(value) is dict and type(key) in (str, int):
            value = value[key]
        elif type(value) in (tuple, list) and type(key) is int:
            value = value[key]
        elif type(value) in RECORD_TYPES and type(key) is str and key in {f.name for f in fields(value)}:
            value = getattr(value, key)
        else:
            raise TypeError('Projection must use plain output containers or fixed record fields')
    return value


def _transfer(owner, *, path, boundary, assessment, budget, cancelled, category, source=None):
    _check(cancelled)
    _sources(cancelled)
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    from atlas_tectonics._exact_runtime import selected
    G = selected.library()
    owner.value
    # Recursion/iteration/owner metadata is funded before creating projection
    # or snapshot containers. Scalar getters grow this lease before they run.
    extra = 1024*(len(boundary)+8) if assessment and type(boundary) is dict else 0
    work = R.OwnedWorkspace(budget, TRAVERSAL_BYTES+extra, category=category, cancelled=cancelled)
    work.__enter__()
    try:
        system, snapshot = None, ()
        value = _select(owner.value, path)
        if assessment:
            if type(value) is A.CertifiedAssembly:
                for key, entry in boundary.items():
                    _check(cancelled)
                # The old assessment inventory funds the one newly-created
                # rounded view. Its producer method validates exact binding.
                system = owner.rounded_system(boundary, cancel=cancelled)
                snapshot = tuple((key, entry[0], entry[1]) for key, entry in boundary.items())
            elif type(value) is not A.RefinementRequired:
                raise TypeError('Complete certificate or refinement request required')
        # Inspection includes the view/snapshot retained by the specialised
        # assessment owner, not just its public .value field.
        graph = (value, system, snapshot) if assessment else value
        total = visits = largest_getter = 0
        np = sys.modules.get('numpy')
        counted, classes = COUNT.supported(G), {}
        # Where the count is refused: what the allocators in use add to a block, asked once for the
        # walk, and the kinds of object for which more of R1's figure follows further down.
        padding, later = (None, ()) if counted else (
            COUNT.padding(), (G.mpq, G.mpz, Fraction, *RECORD_TYPES, *(() if np is None else (np.ndarray,))))
        plain = (dict, list, tuple, G.mpq, G.mpz, Fraction, str, bytes, int, bool, float, Decimal, type(None))
        def visit(item, depth=0):
            nonlocal total, visits, largest_getter
            _check(cancelled)
            visits += 1
            shallow = sys.getsizeof(item)
            if not counted:
                # R1's figure for the object is added as it was, here and further down. Once it is
                # complete the object is charged the larger of it and its blocks as they are made.
                base, total = total, (total+shallow)
                if type(item) in plain:
                    need = COUNT.refused_bytes(item, G, padding)
                elif np is not None and type(item) is np.ndarray:
                    need = COUNT.refused_array(shallow, item.nbytes, padding)
                else:
                    need = COUNT.refused_block(shallow, padding)
                if type(item) not in later:
                    total = max(total, base+need)
            elif type(item) in plain:
                # The object exists: its own blocks, as it reports them.
                total = (total+COUNT.own_bytes(item, G))
            elif np is not None and type(item) is np.ndarray:
                total = (total+COUNT.array_bytes(shallow, item.nbytes))
            else:
                total = (total+COUNT.block(shallow))
            if type(item) is dict:
                for key, child in item.items():
                    visit(key, depth+1)
                    visit(child, depth+1)
            elif type(item) in (tuple, list):
                for child in item:
                    visit(child, depth+1)
            elif type(item) in RECORD_TYPES:
                if hasattr(item, '__dict__'):
                    # An early instance of a class holds more than its dictionary reports.
                    total = (total+(COUNT.own_bytes(item.__dict__, G)+COUNT.record_instance(type(item), classes)
                                         if counted else sys.getsizeof(item.__dict__)))
                    if not counted:
                        need += (COUNT.refused_bytes(item.__dict__, G, padding)
                                 +COUNT.record_instance(type(item), classes))
                if not counted:
                    total = max(total, cast(int, base)+cast(int, need))
                for field in fields(item):
                    visit(field.name, depth+1)
                    visit(getattr(item, field.name), depth+1)
            elif counted and type(item) in (G.mpq, G.mpz):
                pass
            elif counted and type(item) is Fraction:
                total = (total+COUNT.own_bytes(item.numerator, G)+COUNT.own_bytes(item.denominator, G))
            elif type(item) in (G.mpq, G.mpz, Fraction):
                # mpq getters allocate integer copies. Reported source size
                # bounds the two represented parts; add the installed recycled
                # small-block floor and simultaneous local/getter generations.
                getter = 4*max(2048, shallow)
                if getter > largest_getter:
                    largest_getter = getter
                    work.resize_before_allocation_or_after_drop(TRAVERSAL_BYTES+extra+getter)
                if type(item) is G.mpz:
                    n, d = item, 1
                else:
                    n, d = item.numerator, item.denominator
                total = (total+R.native_slot_allowance(R.RationalShape(max(1, n.bit_length()), d.bit_length())))
                if type(item) is Fraction:
                    total = (total+sys.getsizeof(n)+sys.getsizeof(d))
                    need += COUNT.refused_bytes(n, G, padding)+COUNT.refused_bytes(d, G, padding)
                total = max(total, cast(int, base)+cast(int, need))             # only a refused count comes this way
            elif np is not None and type(item) is np.ndarray:
                if not counted:
                    total = (total+item.nbytes)  # no implicit backing-store credit
                    total = max(total, cast(int, base)+cast(int, need))
            elif np is not None and type(item) is np.float64:
                pass
            elif type(item) not in (str, bytes, int, bool, float, Decimal, type(None)):
                raise TypeError('Unsupported stage output object '+type(item).__name__)
        visit(graph)
        visit(path)
        # Complete persistent workspace structures, plus bounded new owner,
        # dictionary, count metadata and method/cache references. Budget/runtime
        # objects and code are already separately owned, not recursively copied.
        structures = (work, work.__dict__, work.stack, work.stack.__dict__,
            work.stack._exit_callbacks, work.lease, work.lease.__dict__,
            work.lease.budgets, work.lease.charged, work.lease.category)
        headers = 8192+sum(map(sys.getsizeof, structures))
        for entry in work.stack._exit_callbacks:
            headers += sys.getsizeof(entry)+sys.getsizeof(entry[1])
        for entry in work.lease.charged:
            headers += sys.getsizeof(entry)
        retained = (total+headers)
        # All complete output values overlap in both leases during admission.
        # No old owner is closed on refused/cancelled admission.
        work.resize_before_allocation_or_after_drop(max(work.lease.count, retained))
        _check(cancelled)
        owner.close()
        # No producer/traversal frame survives success. Only the complete graph
        # and fixed metadata remain; failures below still preserve the new lease.
        structures = None
        work.resize_before_allocation_or_after_drop(retained)
        answer = (OwnedAssessment(value, work, system, snapshot) if assessment else OwnedValue(value, work))
        answer._retention = dict(output_graph_bytes=total, owner_bytes=headers,
            retained_bytes=retained, visited_objects=visits, aliases_counted_repeatedly=True,
            getter_scratch_bytes=largest_getter, projection=path,
            numerical_objects_copied=False, producer_workspace_released=True,
            allocator_or_rss_bound=False, whole_method_admission=False)
        return answer
    except BaseException:
        work.__exit__(*sys.exc_info())
        raise


def compact(owner, *, budget, path=(), cancelled=None, category='heat-completed-stage-output', source=None):
    """Own a complete output (or fixed projection), atomically retire producer.

    For example FUNCTIONS.value=(rows,proof): compact(...,path=(1,)) retains
    only proof AFTER rows have independent merged-row custody. Projecting a
    request to ('selected_face_ids',) retires its obsolete contribution census.
    Drop every omitted borrow first. The returned value keeps original identity.
    Use compact_assessment for a certificate whose rounded-system view is needed.
    """
    return _transfer(owner, path=path, boundary=None, assessment=False, budget=budget,
                     cancelled=cancelled, category=category, source=source)


def compact_assessment(owner, boundary, *, budget, cancelled=None):
    """Retain certificate/request plus one exact-bound checked cached system.

    Boundary must be the fixed forward's already normalised binary64 dictionary.
    Repeated rounded_system calls share one view; all borrows expire on close.
    No exact input row, aggregate scratch or obsolete contribution map is kept
    after successful certificate transfer; its proof remains in witness_json.
    """
    return _transfer(owner, path=(), boundary=boundary, assessment=True, budget=budget,
        cancelled=cancelled, category='heat-completed-assessment-output')
