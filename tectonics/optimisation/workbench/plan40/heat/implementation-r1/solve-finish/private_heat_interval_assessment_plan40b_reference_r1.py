"""Plan40B reference owning receiver with its explicitly pinned inventory successor.

The complete r5 ownership, retained generations and reservations are unchanged.
This additive route is callable independently; no selected production dispatch
or frozen source-map identity is changed.

Automatically inventoried exact assembly assessment, not native heat entry.

No caller byte guess or supplied numerical result is accepted. The fixed r2
arithmetic produces either its complete certificate or complete refinement
request. The new inventory counts the actual nonzero Contribution branch and derives
fast-converter/tie-guard storage. Every numerical call and rounding decision
executes the unchanged A2 arithmetic.

Pass earlier LIVE owners in `retained` to retain their rows, requests and prior
generations under this new lease. Their complete recorded allowances are
charged AGAIN, even for aliases, before references are captured. The earlier
owners can subsequently close without leaving these retained values uncharged.
No partial release is credited while any new-owner generation remains live.
Caller-owned mutable inputs must remain unchanged while borrowed.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_interval_assembly_kernel_r2 as A
import private_heat_interval_inventory_plan40b_reference_r1 as I

CertifiedAssembly = A.CertifiedAssembly
RefinementRequired = A.RefinementRequired
UnresolvedRounding = A.UnresolvedRounding
HERE = Path(__file__).resolve().parent
INVENTORY_SHA = '52ed881ae42706e506084f26ff281d3089327628d254b1308fe92b249b78da06'
SOURCE_PATHS = (str(Path(__file__).resolve()), str(Path(I.__file__).resolve()),
                *(str(path) for path in I.source_paths().values()))


def _verify_sources(cancel):
    I._check(cancel)
    if sha256(Path(I.__file__).read_bytes()).hexdigest() != INVENTORY_SHA:
        raise ValueError('Reviewed assessment inventory changed')
    I.verify_sources(cancel)


@dataclass(frozen=True)
class _RetainedGeneration:
    result: object
    inputs: tuple
    earlier_generations: tuple
    inventory: object
    accounted_bytes: int


class OwnedAssessment(A.OwnedAssessment):
    """Own all rows/request/certificate generations until explicit close."""
    def __init__(self, value, workspace, inputs, retained, plan, accounted, budget):
        super().__init__(value, workspace)
        self._inputs, self._retained, self._plan = inputs, retained, plan
        self._accounted, self._budget = accounted, budget

    @property
    def inventory(self):
        self.value
        return self._plan

    @property
    def accounted_bytes(self):
        self.value
        return self._accounted

    @property
    def retained_generation_count(self):
        self.value
        return len(self._retained)

    def _snapshot(self):
        # Only invoked AFTER the next owner's complete reservation succeeds.
        return _RetainedGeneration(self.value, self._inputs, self._retained,
                                   self._plan, self._accounted)

    def _drop_generations(self):
        self._inputs, self._retained, self._plan = None, (), None

    def close(self):
        self._drop_generations()
        super().close()

    def __exit__(self, kind, error, traceback):
        # Escaping frames retain the workspace, not a separately uncharged
        # owner attribute after its public result has already been invalidated.
        self._drop_generations()
        return super().__exit__(kind, error, traceback)


def assess(rows, cell_count, boundary, *, witness, source_bindings, budget,
           retained=(), cancel=None):
    """Return OwnedAssessment; no guessed refinement/inventory byte inputs.

    `retained` must be a tuple of earlier live owners from this exact wrapper
    with the same budget. It is an ownership/memory operation only: old result
    values are NEVER used in the new assembly's arithmetic or accepted as new
    certificates. New/refined coefficient enclosure proof remains caller-owned.
    The forward owner must fund constructing new rows before passing them here.
    """
    I._check(cancel)
    _verify_sources(cancel)
    if type(retained) is not tuple:
        raise TypeError('Tuple of earlier live assessment owners required')
    retained_bytes = 0
    for owner in retained:
        I._check(cancel)
        if type(owner) is not OwnedAssessment or owner._budget is not budget:
            raise TypeError('Earlier assessment owner must use this exact route and same budget')
        retained_bytes = I._size(retained_bytes+owner.accounted_bytes)
    plan = I.derive(rows, cell_count, boundary, witness=witness,
                    source_bindings=source_bindings, budget=budget, cancel=cancel)
    # Snapshot record/tuple/reference overhead is distinct from the retained
    # earlier generation's already counted entire live inventory.
    retained_headers = I._size(1024*(len(retained)+1))
    amount = I._size(plan.total_bytes+retained_bytes+retained_headers)
    gmp = A.B._library()
    import private_heat_gmp_resources_r1 as R
    workspace = R.OwnedWorkspace(budget, amount, category='heat-derived-aggregate-assessment', cancelled=cancel)
    workspace.__enter__()
    try:
        generations = tuple(owner._snapshot() for owner in retained)
        inputs = (rows, boundary, witness, source_bindings)
        result = A._assemble(rows, cell_count, boundary, witness=witness,
            source_bindings=source_bindings, cancel=cancel, gmp=gmp, collect=True)
        _verify_sources(cancel)
        return OwnedAssessment(result, workspace, inputs, generations, plan, amount, budget)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise
