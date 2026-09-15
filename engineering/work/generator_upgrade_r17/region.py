"""Lazy native-grid support scheduling, not connected regional model execution."""
import math


def _finite(value):
    if type(value) not in (int, float):
        raise ValueError('explicit finite native-grid number required')
    try:
        valid = math.isfinite(value)
    except OverflowError as exc:
        raise ValueError('finite native-grid number required') from exc
    if not valid:
        raise ValueError('finite native-grid number required')
    return value


def _pair(value):
    if type(value) not in (list, tuple) or len(value) != 2:
        raise ValueError('explicit native-grid pair required')
    return tuple(value)


def support_batches(grid, window, batch_size=32):
    """Return a lazy iterator of row-major support dictionaries, at most 32 each.

``grid`` has exactly ``first_sample_m``, ``step_m`` (XY pairs) and ``shape``
(rows, columns). ``window`` has exactly row_start/row_stop/col_start/col_stop,
with nonempty half-open bounds. Extra keys are rejected. All grid coordinates
are already metres; first_sample_m identifies the actual first sample, with no
implicit half-cell shift, frame transformation or edge extension.

Each batch maps ``r{row}_c{col}`` to ``{'xy_m': [x, y], 'area_m2': area}``.
Area is the supplied native rectangular spacing product, not a geodetic area
conversion. Geometry is validated immediately and captured before iteration;
only one batch is constructed at a time. No arrays or physical models are read.
"""
    if type(grid) is not dict or set(grid) != {'first_sample_m', 'step_m', 'shape'}:
        raise ValueError('exact native-grid fields required')
    if type(window) is not dict or set(window) != {'row_start', 'row_stop', 'col_start', 'col_stop'}:
        raise ValueError('exact half-open region window required')
    if type(batch_size) is not int or not 1 <= batch_size <= 32:
        raise ValueError('native support batch size must be an integer from 1 to 32')
    rows, cols = _pair(grid['shape'])
    if any(type(value) is not int or value <= 0 for value in (rows, cols)):
        raise ValueError('positive integer native-grid shape required')
    x0, y0 = map(_finite, _pair(grid['first_sample_m']))
    dx, dy = map(_finite, _pair(grid['step_m']))
    if dx == 0 or dy == 0:
        raise ValueError('nonzero signed native-grid spacing required')
    area = _finite(abs(dx*dy))
    if area <= 0:
        raise ValueError('positive representable native-grid area required')
    # Check extrema without enumerating the grid; retain integer coordinates
    # exactly when its supplied origin/spacing are integers.
    _finite(x0+(cols-1)*dx)
    _finite(y0+(rows-1)*dy)
    r0, r1, c0, c1 = (window[key] for key in ('row_start', 'row_stop', 'col_start', 'col_stop'))
    if any(type(value) is not int for value in (r0, r1, c0, c1)):
        raise ValueError('integer half-open region bounds required')
    if not (0 <= r0 < r1 <= rows and 0 <= c0 < c1 <= cols):
        raise ValueError('nonempty region window must lie inside native-grid bounds')

    def batches():
        batch = {}
        for row in range(r0, r1):
            y = y0+row*dy
            for col in range(c0, c1):
                batch[f'r{row}_c{col}'] = {'xy_m': [x0+col*dx, y], 'area_m2': area}
                if len(batch) == batch_size:
                    yield batch
                    batch = {}
        if batch:
            yield batch

    return batches()
