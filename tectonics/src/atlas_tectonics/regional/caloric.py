"""Ordered represented component reduction with caller-owned storage."""
from contextlib import contextmanager
from itertools import product
import math

import numpy as np


@contextmanager
def component_workspace(shape, components, budget, *, scratch=None):
    """Yield the private sort buffer and its caller-retained failure owner."""
    if scratch is not None:
        yield scratch, None
        return
    count = math.prod(shape)
    overhead = 65536+32*np.getbufsize()
    rows = min(count, max(1, (budget.available_bytes-overhead)//(8*components)))
    from atlas_tectonics._private.codecs.record_tables import Scratch
    owner = Scratch(budget, overhead+8*components*rows)
    try:
        work = np.empty((rows, components), dtype=np.float64)
        yield work, owner
    except BaseException:
        raise
    else:
        del work, owner


def component_sum(values, *, out, scratch, weights=None):
    """Sort rounded terms by value, then add complete component vectors."""
    if (type(values) is not np.ndarray or values.dtype != np.dtype(np.float64)
            or values.ndim < 2 or values.shape[0] == 0):
        raise TypeError('Component-first binary64 cell array required')
    shape = values.shape[1:]
    if not out.size:
        return out
    remaining = scratch.shape[0]
    block_shape = [1]*len(shape)
    for axis in range(len(shape)-1, -1, -1):
        block_shape[axis] = min(shape[axis], remaining)
        remaining = max(1, remaining//block_shape[axis])
    origins = product(*(range(0, n, width) for n, width in zip(shape, block_shape, strict=True)))
    for origin in origins:
        slices = tuple(slice(start, min(start+width, n))
                       for start, width, n in zip(origin, block_shape, shape, strict=True))
        target = out[slices]
        work = scratch[:target.size].reshape((*target.shape, values.shape[0]))
        for component in range(values.shape[0]):
            source = values[(component, *slices)]
            if weights is None:
                np.copyto(work[..., component], source)
            else:
                np.multiply(source, weights[component], out=work[..., component])
        work.sort(axis=-1, kind='heapsort')
        target.fill(0.0)
        for component in range(values.shape[0]):
            np.add(target, work[..., component], out=target)
    return out
