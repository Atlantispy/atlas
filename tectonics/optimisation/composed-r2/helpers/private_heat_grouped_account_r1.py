"""Prospectively owned exact global account for a validated physical heat ledger.

This is an algebraic consumer, NOT a ledger validator or heat solver. Its caller
has validated EVERY public cell residual and paired physical face amount. With
R_i = Epublic_i - Einput_i + outward_i - source_i, the native heat contribution
sum(Etransport_i - Einput_i - R_i) is exactly
sum(Etransport_i - Epublic_i) + source_total - exterior_outward_total.
Interior amounts cancel by their validated incidence, not by being omitted
from validation. In particular this includes stock projection, not only the
solver residual. All nonzero source/exterior/prior-account arithmetic is owned.

The supplied arrays/encoded pairs remain caller-owned. The returned owner must
remain live while its canonical hex account is borrowed. Installed GMP work
policy is an accounted bound, not an allocator/RSS or native-admission proof.
"""
from hashlib import sha256
from pathlib import Path
import sys

import private_heat_issuer_resources_r3 as R

_RESOURCE_SHA = '6517cc80b676a7a66a0ab573899d2e6e6beadf20af5fd7f9b6987962f35621cd'
_SELF_SHA = sha256(Path(__file__).read_bytes()).hexdigest()


def _calculate(ar, prior, transport_residuals, transported, public, source, outward):
    value = ar.decode(prior)
    for encoded in transport_residuals:
        value = ar.op('add', value, ar.decode(encoded))
    for old, new in zip(transported, public, strict=True):
        if type(new) is not float:
            raise TypeError('Actual public binary64 enthalpy values required')
        value = ar.op('add', value, ar.op('subtract', ar.decode(old), ar.decode(new)))
    value = ar.op('add', value, ar.decode(source))
    return ar.op('subtract', value, ar.decode(outward))


def calculate(prior, transport_residuals, transported, public, source, outward, *, budget, cancel=None):
    """Return owned canonical hex account; no copy of the full physical ledger.

transport_residuals includes all ORIGINAL physical graph cells (not appended
finite-stock nodes). transported/public cover each positive physical cell once
in identical order. Zero-volume cells must already have been checked stockless.
"""
    R.check(cancel)
    if (R.source_hash(R.__file__, cancel) != _RESOURCE_SHA
            or R.source_hash(__file__, cancel) != _SELF_SHA):
        raise ValueError('Frozen grouped-account arithmetic source changed')
    if len(transported) != len(public):
        raise ValueError('Complete matching physical stock arrays required')
    G = R.A.exact_library()
    import private_heat_gmp_resources_r1 as GMP
    outer = R.workspace(budget, 65536, cancel=cancel, category='private-heat-grouped-account')
    outer.__enter__()
    try:
        work = GMP.OwnedWorkspace(budget, 65536, category='private-heat-grouped-exact', cancelled=cancel)
        work.__enter__()
        numerical = R.O._OwnerWorkspace(work)
        outer.stack.enter_context(R.P.OwnedSolve(None, numerical))
        ar = R._ProjectionArithmetic(work, G, GMP, 0, 0, 1075, lambda: R.check(cancel))
        numerical.arithmetic = ar
        value = _calculate(ar, prior, transport_residuals, transported, public, source, outward)
        # Numerical frame has returned. Exact scalar stays owned until close.
        ar.settle(value)
        # settle credited scalar/getter work. Fund shallow-size-derived GMP
        # numerator/denominator copies before the output planner inspects them.
        with R.workspace(budget, 65536+4*sys.getsizeof(value), cancel=cancel,
                         category='private-heat-grouped-output-inspection'):
            plan = R.projection_output_plan(((value,),), budget=budget, cancel=cancel)
        outer.stack.enter_context(R.workspace(budget, plan['bytes'], cancel=cancel,
                                             category='private-heat-grouped-codec'))
        # GMP hex conversion is independent of Python's decimal integer limit.
        n, d = value.numerator, value.denominator
        pair = ('-0x'+(-n).digits(16) if n < 0 else '0x'+n.digits(16), '0x'+d.digits(16))
        R.check(cancel)
        return R.P.OwnedSolve(dict(account=pair, proof=dict(
            rule='validated paired-face cancellation; TOTAL public residual',
            physical_transport_rows=len(transport_residuals), positive_cells=len(public),
            source_and_exterior_retained=True, exact_operations=ar.operations,
            scalar_peak_bits=ar.peak_bits, codec_bytes=plan['bytes'],
            native_admission=False, allocator_or_rss_bound=False)), outer)
    except BaseException:
        outer.__exit__(*sys.exc_info())
        raise
