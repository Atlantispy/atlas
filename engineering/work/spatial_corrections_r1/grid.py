"""Axis-aligned, cell-centred spatial operations with explicit support semantics.

Origins are outer pixel corners, never centres. Strides carry axis direction.
Intensive interpolation is point evaluation, NOT conservative downsampling.
Extensive values are totals per source cell, uniform within that cell. Categorical
lookup selects the containing source cell; cell_fractions handles mixed coverage.
These are Cartesian grids; geographic degrees/rotated affines require another API.
"""
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np
from scipy import ndimage, sparse


class SpatialError(ValueError):
    pass


@dataclass(frozen=True)
class Grid:
    shape: tuple[int, int]
    origin_x: float
    origin_y: float
    step_x: float
    step_y: float
    units: str = "km"

    def __post_init__(self):
        if (not isinstance(self.shape, tuple) or len(self.shape) != 2 or
                any(isinstance(n, bool) or not isinstance(n, Integral) or n < 1
                    for n in self.shape)):
            raise SpatialError("shape must be two positive integer cell counts")
        if not all(isinstance(v, Real) and not isinstance(v, (bool, np.bool_)) and np.isfinite(v)
                   for v in (self.origin_x, self.origin_y, self.step_x, self.step_y)):
            raise SpatialError("grid transform must be finite")
        if not self.step_x or not self.step_y or self.units not in ("m", "km"):
            raise SpatialError("nonzero Cartesian strides and explicit m/km units required")
        area = float(self.step_x) * float(self.step_y)
        if not np.isfinite(area) or area == 0:
            raise SpatialError("cell area must be finite, nonzero and representable")
        # Check both ends, where binary64 spacing is largest on a monotonic axis.
        # Two distinct half-cell intervals ensure corners AND centres remain
        # representable. This deliberately rejects unresolved sub-ULP grids.
        for n, origin, step in ((self.shape[1], self.origin_x, self.step_x),
                                (self.shape[0], self.origin_y, self.step_y)):
            span = float(n)*float(step)
            end = float(origin)+span
            if not np.isfinite(span) or not np.isfinite(end) or span == 0:
                raise SpatialError("grid extent must be finite and representable")
            positions = [float(origin), float(origin)+.5*step, float(origin)+step,
                         end-step, end-.5*step, end]
            if (not all(np.isfinite(v) for v in positions) or
                    any((b-a)*np.sign(step) <= 0 for a, b in
                        ((positions[0], positions[1]), (positions[1], positions[2]),
                         (positions[3], positions[4]), (positions[4], positions[5])))):
                raise SpatialError("grid corners/centres collapse at binary64 precision")

    @property
    def area(self):
        return abs(self.step_x * self.step_y)

    @property
    def bounds(self):
        xe = self.origin_x + self.shape[1] * self.step_x
        ye = self.origin_y + self.shape[0] * self.step_y
        return (min(self.origin_x, xe), min(self.origin_y, ye),
                max(self.origin_x, xe), max(self.origin_y, ye))

    def centres(self):
        return (self.origin_x + (np.arange(self.shape[1]) + .5) * self.step_x,
                self.origin_y + (np.arange(self.shape[0]) + .5) * self.step_y)

    def crop(self, r0, r1, c0, c1):
        if not (0 <= r0 < r1 <= self.shape[0] and 0 <= c0 < c1 <= self.shape[1]):
            raise SpatialError("crop must select complete in-frame cells")
        return Grid((r1-r0, c1-c0), self.origin_x+c0*self.step_x,
                    self.origin_y+r0*self.step_y, self.step_x, self.step_y, self.units)


@dataclass(frozen=True)
class RemapResult:
    values: np.ndarray
    valid: np.ndarray
    support_fraction: np.ndarray


def _compatible(source, target):
    if source.units != target.units:
        raise SpatialError("unit conversion must be explicit before remapping")


def _field(values, grid, valid=None):
    a = np.asarray(values)
    if a.ndim < 2 or a.shape[-2:] != grid.shape or a.dtype.kind not in "buif":
        raise SpatialError("numeric field trailing dimensions must match the grid")
    if valid is None:
        mask = np.ones(a.shape, dtype=bool)
    else:
        v = np.asarray(valid)
        if v.dtype != np.bool_:
            raise SpatialError("validity mask must be boolean (unknown is not zero)")
        try:
            mask = np.broadcast_to(v, a.shape)
        except ValueError as exc:
            raise SpatialError("mask cannot broadcast to field") from exc
    if not np.isfinite(a[mask]).all():
        raise SpatialError("nonfinite valid values require an explicit missing-data mask")
    return a, mask


def _points(source, target):
    _compatible(source, target)
    x, y = target.centres()
    qx = (x-source.origin_x)/source.step_x
    qy = (y-source.origin_y)/source.step_y
    inside = ((qy[:, None] >= 0) & (qy[:, None] < source.shape[0]) &
              (qx[None, :] >= 0) & (qx[None, :] < source.shape[1]))
    yy, xx = np.meshgrid(qy-.5, qx-.5, indexing="ij")
    return np.array([yy, xx]), inside


def intensive(values, source, target, *, order=1, valid=None):
    """Pointwise linear/cubic interpolation; nearest-centre edge extension only
    inside source cell extent. Cubic is refused with missing cells because spline
    prefilter support is nonlocal. No implicit clipping of scientific field values.
    """
    if isinstance(order, (bool, np.bool_)) or not isinstance(order, Integral) or order not in (1, 3):
        raise SpatialError("intensive order must be 1 or 3; use categorical for labels")
    a, mask = _field(values, source, valid)
    coords, inside = _points(source, target)
    if order == 3 and not mask.all():
        raise SpatialError("cubic with missing data is unsupported; supply complete data or linear")
    shape = a.shape[:-2] + target.shape
    out, support = np.empty(shape, float), np.empty(shape, float)
    unknown = np.empty(shape, float)
    for idx in np.ndindex(a.shape[:-2]):
        safe = np.where(mask[idx], a[idx], 0).astype(float)
        out[idx] = ndimage.map_coordinates(safe, coords, order=order,
                                           mode="nearest", prefilter=order > 1)
        support[idx] = ndimage.map_coordinates(mask[idx].astype(float), coords,
                                               order=1, mode="nearest", prefilter=False)
        unknown[idx] = ndimage.map_coordinates((~mask[idx]).astype(float), coords,
                                               order=1, mode="nearest", prefilter=False)
    support *= inside
    # Do not confuse roundoff of known weights with a small POSITIVE contribution
    # from an unknown cell. The latter must remain unknown, however small.
    good = inside & (unknown == 0)
    out[~good] = np.nan
    return RemapResult(out, good, support)


def sample_cells(values, grid, x, y, *, valid=None, outside="raise"):
    """Sample cells by affine-inverse pixel coverage [0,n), not round(x/cell).
    Supports leading band dimensions and broadcast point coordinates. For negative
    strides the half-open interval is defined in pixel space (origin edge included).
    """
    if outside not in ("raise", "mask"):
        raise SpatialError("outside must be raise or mask; silent clamping is forbidden")
    a, mask = _field(values, grid, valid)
    try:
        x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    except ValueError as exc:
        raise SpatialError("point coordinates cannot broadcast") from exc
    qx, qy = (x-grid.origin_x)/grid.step_x, (y-grid.origin_y)/grid.step_y
    inside = (np.isfinite(qx) & np.isfinite(qy) & (qx >= 0) & (qy >= 0) &
              (qx < grid.shape[1]) & (qy < grid.shape[0]))
    if outside == "raise" and not inside.all():
        raise SpatialError("point is outside grid cell coverage or nonfinite")
    # Clipped indices are used only to avoid indexing errors; outside values remain
    # unavailable and are never reported as the boundary cell's evidence.
    c = np.floor(np.where(inside, qx, 0)).astype(np.int64)
    r = np.floor(np.where(inside, qy, 0)).astype(np.int64)
    out = a[..., r, c].copy()
    good = mask[..., r, c] & inside
    return RemapResult(out, good, good.astype(float))


def categorical(values, source, target, *, valid=None):
    """Containing-cell labels. Invalid output values are placeholders; always use
    the returned validity mask. Integer labels are never interpolated or fabricated.
    """
    a = np.asarray(values)
    if a.dtype.kind not in "bui":
        raise SpatialError("categorical values must be integer labels or booleans")
    _compatible(source, target)
    x, y = target.centres()
    xx, yy = np.meshgrid(x, y)
    return sample_cells(a, source, xx, yy, valid=valid, outside="mask")


def _overlap_axis(n_source, origin_source, step_source,
                  n_target, origin_target, step_target):
    """Sparse physical overlap lengths, O(N+M+nonzero overlaps), either orientation."""
    def intervals(n, origin, step):
        for i in (range(n) if step > 0 else range(n-1, -1, -1)):
            a, b = origin+i*step, origin+(i+1)*step
            yield min(a, b), max(a, b), i
    ss, tt = list(intervals(n_source, origin_source, step_source)), list(
        intervals(n_target, origin_target, step_target))
    i = j = 0
    rows, cols, data = [], [], []
    while i < len(ss) and j < len(tt):
        sl, sh, si = ss[i]
        tl, th, ti = tt[j]
        length = min(sh, th)-max(sl, tl)
        if length > 0:
            rows.append(ti); cols.append(si); data.append(length)
        if sh <= th:
            i += 1
        if th <= sh:
            j += 1
    return sparse.csr_matrix((data, (rows, cols)), shape=(n_target, n_source))


def _overlaps(source, target, allow_partial_domain):
    _compatible(source, target)
    if type(allow_partial_domain) is not bool:
        raise SpatialError("allow_partial_domain must be an explicit boolean")
    if not allow_partial_domain and not np.allclose(source.bounds, target.bounds,
                                                    rtol=0, atol=1e-10):
        raise SpatialError("conservative full-domain remap requires identical outer bounds")
    oy = _overlap_axis(source.shape[0], source.origin_y, source.step_y,
                       target.shape[0], target.origin_y, target.step_y)
    ox = _overlap_axis(source.shape[1], source.origin_x, source.step_x,
                       target.shape[1], target.origin_x, target.step_x)
    return oy, ox


def extensive(values, source, target, *, valid=None, allow_partial_domain=False):
    """Conservative source-cell totals, assuming uniform density within each cell.
    A partially unknown/uncovered target is NaN, never a silently reduced total.
    Partial-domain remapping is explicit and cannot imply whole-domain conservation.
    """
    a, mask = _field(values, source, valid)
    oy, ox = _overlaps(source, target, allow_partial_domain)
    out = np.empty(a.shape[:-2]+target.shape, float)
    support = np.empty_like(out)
    unknown_area = np.empty_like(out)
    for idx in np.ndindex(a.shape[:-2]):
        out[idx] = (ox @ (oy @ np.where(mask[idx], a[idx], 0)/source.area).T).T
        support[idx] = (ox @ (oy @ mask[idx].astype(float)).T).T/target.area
        unknown_area[idx] = (ox @ (oy @ (~mask[idx]).astype(float)).T).T
    support = np.clip(support, 0, 1)
    # Exact geometric containment is separate from floating-point support sums;
    # even a tiny positive out-of-frame sliver is not complete known coverage.
    sx0, sy0, sx1, sy1 = source.bounds
    xe = target.origin_x+np.arange(target.shape[1]+1)*target.step_x
    ye = target.origin_y+np.arange(target.shape[0]+1)*target.step_y
    inside = ((np.minimum(ye[:-1], ye[1:])[:, None] >= sy0) &
              (np.maximum(ye[:-1], ye[1:])[:, None] <= sy1) &
              (np.minimum(xe[:-1], xe[1:])[None, :] >= sx0) &
              (np.maximum(xe[:-1], xe[1:])[None, :] <= sx1))
    good = inside & (unknown_area == 0)
    out[~good] = np.nan
    return RemapResult(out, good, support)


def cell_fractions(labels, source, target, classes, *, valid=None,
                   allow_partial_domain=False):
    """Area fraction occupied by each requested class, not majority-label guessing.
    Complete class lists sum to one only where the full target is known/covered.
    """
    a, mask = _field(labels, source, valid)
    if a.ndim != 2 or a.dtype.kind not in "bui":
        raise SpatialError("cell_fractions requires a 2D integer/bool label field")
    classes = tuple(classes)
    if not classes or len(set(classes)) != len(classes):
        raise SpatialError("classes must be a nonempty unique sequence")
    totals = np.stack([(a == k).astype(float)*source.area for k in classes])
    result = extensive(totals, source, target, valid=mask,
                       allow_partial_domain=allow_partial_domain)
    return RemapResult(result.values/target.area, result.valid, result.support_fraction)
