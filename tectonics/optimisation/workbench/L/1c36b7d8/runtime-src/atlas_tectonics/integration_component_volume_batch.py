"""One support decode for sequential volume queries; no numerical result cache.

Private candidate. The immutable issued support and every numerical query keep
their original contracts. Only this owner's active support is materialised.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack

from . import integration_differential_geometry as D
from . import integration_volume as V
from .integration_routing_views import (
    RoutingArena, _FailureOwner, _decoded_json_capacity, _decode_workspace,
)


class _QueryFailureOwner:
    """Collectable even when retained query frames point back to this owner.

    A weakref.finalize callback would root stack -> cache.close -> cache.owner
    -> arena -> owner forever. This destructor has no global callback root;
    Python's cyclic finalisation closes the same stack after escaped frames
    and payloads die. Normal success releases explicitly and immediately.
    """

    def __init__(self, stack):
        self._stack = stack

    def release(self):
        stack, self._stack = self._stack, None
        if stack is not None:
            stack.close()

    def __del__(self):
        self.release()


class _QueryArena(RoutingArena):
    """An outer RoutingArena must not discard a failed query's ownership."""

    def __init__(self, budget):
        D.B._Arena.__init__(self, budget)
        self._failure_owner = _QueryFailureOwner(self.stack)

    def __exit__(self, kind, error, tb):
        if error is not None:
            owner = self._failure_owner
            # Keep ownership for an extracted traceback/frame independently of
            # the exception attribute overwritten by enclosing RoutingArenas.
            self._retained_query_owner = owner
            # Also cover an error whose traceback is explicitly cleared. A
            # complete diagnostic payload already keeps this same query owner.
            owners = getattr(error, '_component_volume_query_owners', ())
            error._component_volume_query_owners = (*owners, owner)
        return super().__exit__(kind, error, tb)


class ComponentVolumeQueries:
    """Context-bound, lazy input reuse for one immutable issued support.

    A new query arena gives each call its original scratch/cache/work lifetime.
    The input owner survives a normal context exit if a caught query failure
    still retains its record. No global pool, decoded routing row or output
    cache exists. This owner cannot be re-entered, used outside its context or
    reused after a query fails (its caller may still retain that failed query).
    """

    def __init__(self, support, *, budget):
        self._support, self._budget = support, budget
        self._record = self._owner = None
        self._active = self._closed = False

    def __enter__(self):
        if self._active or self._closed:
            raise RuntimeError('component volume query owner cannot be re-entered')
        self._active = True
        return self

    def __exit__(self, kind, error, tb):
        self._active = False
        self._closed = True
        # Do not forcibly release the owner: a failed query can still own its
        # decoded input after the caller catches it and exits normally here.
        # The finalizer closes its stack as soon as the last owner reference dies.
        self._record = None
        self._owner = None
        self._support = None
        self._budget = None
        return False

    def measure(self, logical_cell_id, *, endpoint, max_width_m3, max_leaves,
                positive_witness=False, relative_error=None, _funded=None):
        if not self._active:
            raise RuntimeError('component volume query requires its active owner')
        try:
            return self._measure(logical_cell_id, endpoint=endpoint,
                max_width_m3=max_width_m3, max_leaves=max_leaves,
                positive_witness=positive_witness, relative_error=relative_error, _funded=_funded)
        except BaseException:
            self._active = False
            raise

    def _measure(self, logical_cell_id, *, endpoint, max_width_m3, max_leaves,
                 positive_witness, relative_error, _funded):
        support, budget = self._support, self._budget
        # Match the public wrapper's validation before any decode/admission.
        if (type(support) is not D.DifferentialSupport or support._resource is not budget
                or endpoint not in ('start', 'end')):
            raise V.VolumeError('issued support, same budget and explicit endpoint required')
        with _QueryArena(budget) as arena:
            if self._owner is None:
                stack = ExitStack()
                self._owner = _FailureOwner(stack)
            # Install BEFORE any admission or decode can fail. The query's
            # error, complete payload or retained frame keeps this link alive.
            arena._failure_owner._component_volume_input_owner = self._owner
            if self._record is None:
                stack.enter_context(budget.reserve(
                    4096 + _decoded_json_capacity(support._json),
                    category='component-volume-decoded-input'))
                decoder = ExitStack()
                try:
                    decoder.enter_context(budget.reserve(_decode_workspace(support._json),
                        category='component-volume-decoder'))
                    self._record = support.record()
                except BaseException:
                    stack.callback(decoder.close)
                    raise
                else:
                    decoder.close()
            return D._component_volume_bounds_decoded(support, logical_cell_id,
                self._record, arena, endpoint=endpoint, max_width_m3=max_width_m3,
                max_leaves=max_leaves, positive_witness=positive_witness,
                budget=budget, relative_error=relative_error, _funded=_funded)
