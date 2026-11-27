"""Explicit private recovery factory for the frozen I12/J6 endpoint.

All provenance, original-input, exact ledger and endpoint checks are the frozen
B1 factory, except its collar index is read with the actual native flat-int or
XYZ-list policy. This factory legitimately issues the existing B1 detached
binding after those checks; it constructs neither a live heat call nor a new
heat result. Native runtime/producer source identity is never rewritten.

Additive RAM recovery successor; historical producer source identity is
separate from the immutable original producer identity.
JSON views follow resources r4, exactly as in the B1 successor it wraps.
"""
import atlas_tectonics._identity as _atlas_identity
from atlas_tectonics._private.integration.heat import restored_binding_ram_context as B1

R, I, C, STORE = B1.R, B1.I, B1.C, B1.STORE
EXCHANGE_SCHEMA = B1.EXCHANGE_SCHEMA
ExteriorMesh = B1.ExteriorMesh
RestoredHeatBinding = B1.RestoredHeatBinding
_BINDING_SHA = 'b3b58c0cd4b721bca1e8d745fb7eb0cc1ee85f2c3dd09a2f34e2f91bdc655d8e'
_SELF_SHA = R.source_hash(__file__)
_binding_verified = False


def source_bindings(cancel=None):
    global _binding_verified
    R.check(cancel)
    binding = _atlas_identity.relkey(B1.__file__)
    if not _binding_verified:
        if B1._SELF_SHA != _BINDING_SHA:
            raise ValueError('Explicit recovery binding source changed: '+binding)
        _binding_verified = True
    return {binding: _BINDING_SHA, _atlas_identity.relkey(__file__): _SELF_SHA}


def restore(store, receipt, *, owner, parent_spatial_state, parent_collar_state, spatial_state,
            collar_state, mesh, transport_snapshot, source_audit, exchange, execution,
            absolute_residual_target, expected_heat_result_id, budget, cancel=None):
    """Authenticate stored I12 heat against separately restored committed state.

    The workflow reader must provide its committed parent/head and expected ID;
    this is not a replacement for native workflow source/transaction recovery.
    No producer is called. Returned ownership includes every decoded heat view.
    """
    source_bindings(cancel)
    B1._verify(execution, cancel)
    return B1._restore(store, receipt, owner, parent_spatial_state, parent_collar_state, spatial_state,
                       collar_state, mesh, transport_snapshot, source_audit, exchange, execution,
                       absolute_residual_target, expected_heat_result_id, budget, cancel,
                       context_for=B1._context, binding_type=RestoredHeatBinding,
                       collar_value=B1._collar_value, finish_verify=B1._verify)
