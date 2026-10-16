"""Private sparse HIGH/LOW sizing, not a complete heat allocation model.

The structural L+U ceiling n*(n+1) is valid for general pivoted square LU,
including both diagonals. It does not rely on symmetry or an empirical fill
multiplier. Native LU uses the EXISTING _native_factor_bytes policy unchanged;
that policy is accounted admission, not an allocator/RSS proof. Exported L/U,
permutation arrays and construction generations are charged separately.

Reuse R.OwnedWorkspace before allocating. The caller supplies separately
justified simultaneous Decimal/GMP/MPFR/Python/input/codec/result charges via
other_live_bytes. This helper neither invents those charges nor admits a solve
merely because a caller passes zero. Keep the factor charge until its last
owner drops it, or reserve a retained owner BEFORE transferring it. Failure
tracebacks retain R.OwnedWorkspace charges. No solver/equation is wrapped here.
"""
from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import private_heat_gmp_resources_r1 as R
from atlas_tectonics.regional_multigrid3d import _native_factor_bytes
from atlas_tectonics.resources import MemoryLimitError

INT32_MAX = (1 << 31)-1
MIB = 1 << 20
SOURCE_SCOPE = (str(Path(__file__).resolve()), str(Path(R.__file__).resolve()),
                str(Path(sys.modules[_native_factor_bytes.__module__].__file__).resolve()))


def _size(value, name, *, positive=False):
    if type(value) is not int or value < int(positive):
        raise ValueError(name+' must be a '+('positive' if positive else 'nonnegative')+' integer')
    if value > sys.maxsize:
        raise OverflowError(name+' exceeds the platform addressable byte/index range')
    return value


def _total(*values):
    value = sum(values)
    if value > sys.maxsize:
        raise OverflowError('Prospective storage exceeds the platform addressable byte range')
    return value


def binary_array_payload(elements, *, itemsize, copies):
    """Exact declared flat-array payload; no header/cache/allocator assertion."""
    _size(elements, 'elements')
    _size(itemsize, 'itemsize', positive=True)
    _size(copies, 'copies')
    return _total(elements*itemsize*copies)


def compressed_payload(n, nnz, *, index_bytes=4, copies=1):
    """Exact canonical square binary64 CSR/CSC payload for declared capacities."""
    _size(n, 'n', positive=True)
    _size(nnz, 'nnz')
    _size(copies, 'copies')
    if index_bytes not in (4, 8) or type(index_bytes) is not int:
        raise ValueError('Sparse index width must be exactly 4 or 8 bytes')
    if n > (1 << (8*index_bytes-1))-1 or nnz > (1 << (8*index_bytes-1))-1:
        raise OverflowError('Sparse dimensions exceed the declared signed index range')
    if nnz > n*n:
        raise ValueError('Canonical square sparse support cannot exceed n*n')
    return _total(copies*((8+index_bytes)*nnz+index_bytes*(n+1)))


@dataclass(frozen=True)
class SparseLUEnvelope:
    n: int
    input_nnz_bound: int
    factor_nnz_bound: int
    compressed_generation_bytes: int
    input_array_generation_bytes: int
    conversion_work_bytes: int
    native_factor_policy_bytes: int
    cached_factor_payload_bytes: int
    exported_permutation_bytes: int
    binary_vector_payload_bytes: int
    other_live_bytes: int

    @property
    def retained_factor_bytes(self):
        # Deliberately retain the full native construction policy: this helper
        # has no independent proof permitting release of native capacity.
        return _total(self.native_factor_policy_bytes, self.cached_factor_payload_bytes,
                      self.exported_permutation_bytes)

    @property
    def total_bytes(self):
        return _total(self.compressed_generation_bytes, self.input_array_generation_bytes,
                      self.conversion_work_bytes, self.retained_factor_bytes,
                      self.binary_vector_payload_bytes, self.other_live_bytes)


def sparse_lu_envelope(n, nnz_bound, *, binary64_vectors, other_live_bytes):
    """Before-allocation envelope for either nonsymmetric HIGH or sparse LOW.

    Requires canonical input support and the installed float64/int32 LU route.
    Three full compressed generations cover simultaneous construction/copy/
    conversion without relying on aliasing; incoming ndarray data/int64 index
    buffers are separately counted. The 64*n+4096 conversion allowance reuses
    the existing sparse ordering-work policy in subduction_linear._factor.
    Python assembly lists/tuples and Decimal rows remain caller inventory.

    ``other_live_bytes`` is mandatory and must describe all other concurrently
    owned objects; it is NOT automatically validated as a complete inventory.
    No source/exact/stencil arrays may be silently considered freed here.
    """
    _size(n, 'n', positive=True)
    _size(nnz_bound, 'nnz_bound')
    _size(binary64_vectors, 'binary64_vectors')
    _size(other_live_bytes, 'other_live_bytes')
    if np.dtype(np.intp).itemsize != 8 or np.dtype(np.float64).itemsize != 8:
        raise RuntimeError('Sparse heat accounting requires the reviewed 64-bit host')
    sparse = compressed_payload(n, nnz_bound)
    fill = n*(n+1)
    if fill > INT32_MAX:
        raise OverflowError('Worst-case L+U fill exceeds the reviewed int32 sparse route')
    native = _total(MIB, _native_factor_bytes(n, nnz_bound, fill))
    result = SparseLUEnvelope(n, nnz_bound, fill,
        _total(3*sparse), compressed_payload(n, nnz_bound, index_bytes=8),
        _total(64*n, 4096), native, _total(12*fill, 8*(n+1)),
        _total(8*n), binary_array_payload(n, itemsize=8, copies=binary64_vectors), other_live_bytes)
    result.total_bytes  # Reject combined overflow before any sized allocation.
    return result


def check_factor_fill(envelope, lower_nnz, upper_nnz):
    """Realised count guard; failure is not a request to enlarge the budget."""
    if type(envelope) is not SparseLUEnvelope:
        raise TypeError('Declared sparse LU envelope required')
    _size(lower_nnz, 'lower_nnz')
    _size(upper_nnz, 'upper_nnz')
    triangle = envelope.n*(envelope.n+1)//2
    if lower_nnz > triangle or upper_nnz > triangle or lower_nnz+upper_nnz > envelope.factor_nnz_bound:
        raise MemoryLimitError('Realised nonsymmetric factor fill exceeds the pre-admitted structural envelope')
    return _total(MIB, _native_factor_bytes(envelope.n, envelope.input_nnz_bound, lower_nnz+upper_nnz))


def _active_workspace(envelope, workspace):
    if (type(envelope) is not SparseLUEnvelope or type(workspace) is not R.OwnedWorkspace
            or not workspace.entered or workspace.finished or workspace.lease.count < envelope.total_bytes):
        raise RuntimeError('Full sparse envelope must already be reserved before inspection')
    workspace.checkpoint()


def audit_sparse_input(matrix, envelope, *, workspace):
    """Check declared compressed input BEFORE invoking native factorisation.

    The caller must bound support before constructing this matrix in the same
    admitted scope. A failed realised check never retrospectively permits an
    oversized construction and never silently widens the reservation.
    """
    _active_workspace(envelope, workspace)
    if (matrix.shape != (envelope.n, envelope.n) or matrix.format not in ('csr', 'csc')
            or matrix.dtype != np.dtype('float64') or matrix.indices.dtype != np.dtype('int32')
            or matrix.indptr.dtype != np.dtype('int32') or not matrix.has_canonical_format):
        raise ValueError('Canonical declared float64/int32 compressed matrix required')
    if matrix.nnz > envelope.input_nnz_bound:
        raise MemoryLimitError('Sparse input exceeds its pre-admitted support bound')
    payload = sum(a.nbytes for a in (matrix.data, matrix.indices, matrix.indptr))
    if payload > compressed_payload(envelope.n, envelope.input_nnz_bound):
        raise MemoryLimitError('Sparse input payload exceeds its pre-admitted bound')
    workspace.checkpoint()
    return dict(input_nnz=int(matrix.nnz), payload_bytes=int(payload), support_bound=envelope.input_nnz_bound)


def audit_factor(factor, envelope, *, workspace):
    """Inspect exported factors ONLY inside the already reserved full envelope.

    SciPy L/U properties may allocate cached CSC arrays. Their WORST payloads
    were included before factor construction. nbytes validates exposed logical
    buffer payloads, NOT retained capacity/native storage or its policy.
    """
    _active_workspace(envelope, workspace)
    lower, upper = factor.L, factor.U
    if lower.shape != (envelope.n, envelope.n) or upper.shape != lower.shape:
        raise ValueError('Factor shape changed from declared input')
    native = check_factor_fill(envelope, int(lower.nnz), int(upper.nnz))
    payload = 0
    for matrix in (lower, upper):
        if (matrix.format != 'csc' or matrix.dtype != np.dtype('float64')
                or matrix.indices.dtype != np.dtype('int32') or matrix.indptr.dtype != np.dtype('int32')):
            raise ValueError('Factor differs from reviewed float64/int32 CSC storage')
        payload += sum(array.nbytes for array in (matrix.data, matrix.indices, matrix.indptr))
    permutation = factor.perm_r.nbytes+factor.perm_c.nbytes
    if (native > envelope.native_factor_policy_bytes or payload > envelope.cached_factor_payload_bytes
            or permutation > envelope.exported_permutation_bytes):
        raise MemoryLimitError('Realised factor accounting exceeds the pre-admitted envelope')
    workspace.checkpoint()
    return dict(factor_L_plus_U_nnz=int(lower.nnz+upper.nnz), factor_nnz_bound=envelope.factor_nnz_bound,
        native_policy_bytes=native, exported_csc_payload_bytes=int(payload),
        permutation_payload_bytes=int(permutation), admitted_bytes=envelope.total_bytes,
        retained_factor_admitted_bytes=envelope.retained_factor_bytes,
        preallocation_admission=True, allocator_or_rss_guarantee=False,
        whole_heat_inventory_certified=False)
