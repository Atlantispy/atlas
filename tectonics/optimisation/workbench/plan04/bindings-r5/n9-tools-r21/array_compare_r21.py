"""Bounded byte comparison with independently supplied row correspondence.

This module supplies no numerical allowance. A changed, otherwise bound array
needs a separately source-bound quantity contract and remains REVIEW here.

Magnitude tables for the structured review: when the caller passes ``magnitudes``, every array
the comparison leaves REVIEW gets a diagnostic row: element and sign counts, the first largest absolute
change with its index (and cell ID where rows are cells), the largest relative change, log2 histograms and
per-arm scale. Rows without a correspondence get per-arm aggregates. Where only the two cell-ID sets
differ, the cells present in both arms are joined by cell ID for diagnostics only (never a correspondence
proof), and the unpaired cells are counted, listed and aggregated per arm; the after arm's are its births.
No verdict reads these rows; without ``magnitudes`` the comparison is unchanged.
"""
from __future__ import annotations

import math
from fractions import Fraction
import numpy as np

BLOCK_BYTES = 1 << 20
SMALL_VALUES = 8          # an array of at most this many elements lists every value pair
MAX_LISTED = 200          # unpaired cell IDs listed per arm (all are counted)
BIG = float(np.finfo(np.float64).max)


def blocks(path, dtype, shape, join=None):
    """Read at most one block per operand; row joins never sort numeric values."""
    count = math.prod(shape)
    step = max(1, BLOCK_BYTES // dtype.itemsize)
    row_size = math.prod(shape[1:]) if shape else 1
    with path.open("rb") as stream:
        for start in range(0, count, step):
            length = min(step, count - start)
            if join is None:
                raw = stream.read(length * dtype.itemsize)
            else:
                parts, cursor, left = [], start, length
                while left:
                    row, column = divmod(cursor, row_size)
                    take = min(left, row_size - column)
                    stream.seek((int(join[row]) * row_size + column) * dtype.itemsize)
                    part = stream.read(take * dtype.itemsize)
                    if len(part) != take * dtype.itemsize:
                        raise ValueError("array shortened during row join")
                    parts.append(part)
                    cursor += take
                    left -= take
                raw = b"".join(parts)
            if len(raw) != length * dtype.itemsize:
                raise ValueError("array shortened during comparison")
            yield np.frombuffer(raw, dtype=dtype)


def correspondence(C, name, x, y, ids_b, ids_a, layouts):
    if name.startswith(C.EXTERIOR_PREFIX):
        return C.cell_pairing(name, x, y, ids_b, ids_a)
    if layouts is None:
        return "legacy-positional", None
    left, right = layouts[0].get(name), layouts[1].get(name)
    if not left or not right:
        return "none", "no independent row-layout evidence"
    if left.get("kind") == right.get("kind") == "scalar":
        return "same", None
    if left.get("kind") == right.get("kind") and left.get("kind") in ("identity", "fixed-domain"):
        a, b = left.get("identity"), right.get("identity")
        if a is not None and a == b and left.get("axis") == right.get("axis"):
            return "same", None
    # The binding module's native layouts can explicitly carry ordered row IDs.
    a, b = (left.get("identity"), right.get("identity")) if (
        left.get("kind") == right.get("kind") and left.get("kind") in ("state-cell", "transport-cell")
    ) else (left.get("rows"), right.get("rows"))
    if a is not None and b is not None and left.get("axis") == right.get("axis") == 0:
        return C.cell_pairing(name, x, y, a, b)
    return "none", "array layout has no independently established correspondence"


# No array field contract exists (D01), so no array change is compared with a certified radius.
NO_RADIUS = {"certified_radius": None, "radius_source": None, "max_ratio": None,
             "radius_status": "none: no array field contract exists (D01)"}


class Magnitude:
    """Streaming diagnostics of after - before over paired elements, in the before arm's order.

    float64 arithmetic: integers are converted (exact below 2**53), and a difference that rounds onto a
    power of two may land in the next log2 bin. Overflowing absolute differences are reported explicitly,
    ordered exactly and supplied as exact rational pairs; they are never silently capped. Per-arm scale
    includes all finite numeric values compared, including unchanged values. Ties keep the first location.
    """

    def __init__(self, dtype, shape, ulps=None):
        self.dtype, self.shape = dtype, tuple(shape)
        self.ulps = ulps                  # float64 arrays only: binary64 steps between paired elements
        self.compared = self.changed = self.increased = self.decreased = self.max_ulps = 0
        self.max_abs = self.max_rel = 0.0
        self.absolute_overflow = 0
        self.overflow_max = None
        self.worst = None
        self.bins = ({}, {})
        self.scale = [0.0, 0.0]
        self.values = []

    def add(self, u, v, changed):
        start = self.compared
        self.compared += len(u)
        if start < SMALL_VALUES and self.dtype.kind in "iufb":
            take = SMALL_VALUES - start
            self.values.extend([x, y] for x, y in zip(u[:take].tolist(), v[:take].tolist(), strict=True))
        if self.dtype.kind in "iuf":
            for arm, values in enumerate((u, v)):
                finite_values = values.astype(np.float64)
                finite_values = finite_values[np.isfinite(finite_values)]
                if len(finite_values):
                    self.scale[arm] = max(self.scale[arm], float(np.max(np.abs(finite_values))))
        where = np.flatnonzero(changed)
        self.changed += len(where)
        if self.dtype.kind not in "iuf" or not len(where):
            return
        uu, vv = u[where].astype(np.float64), v[where].astype(np.float64)
        finite = np.isfinite(uu) & np.isfinite(vv)
        where, uu, vv = where[finite], uu[finite], vv[finite]
        if not len(where):
            return
        if self.ulps is not None:
            self.max_ulps = max(self.max_ulps, self.ulps(uu, vv))
        with np.errstate(over="ignore", invalid="ignore"):
            diff = vv - uu
        size = np.abs(diff)
        top = np.maximum(np.abs(uu), np.abs(vv))
        # Fractions are needed only at the binary64 ceiling: ordinary blocks stay vectorised.
        # Exact ordering distinguishes multiple overflows and retains the first exact tie.
        large = {int(k): abs(Fraction(float(vv[k])) - Fraction(float(uu[k])))
                 for k in np.flatnonzero(size >= BIG)}
        overflow = {k: value for k, value in large.items() if value > Fraction(BIG)}
        overflow_mask = np.zeros(len(size), dtype=bool)
        if overflow:
            overflow_mask[list(overflow)] = True
        self.absolute_overflow += len(overflow)
        rel = np.zeros_like(size)
        np.divide(size, top, out=rel, where=(top > 0) & ~overflow_mask)
        if overflow:
            indices = list(overflow)
            rel[indices] = np.abs(vv[indices] / top[indices] - uu[indices] / top[indices])
        self.increased += int(np.count_nonzero(diff > 0))
        self.decreased += int(np.count_nonzero(diff < 0))
        for values, bins in zip((size[~overflow_mask], rel), self.bins, strict=True):
            positive = values[values > 0]
            if len(positive):
                exponents, counts = np.unique(np.frexp(positive)[1] - 1, return_counts=True)
                for e, n in zip(exponents.tolist(), counts.tolist(), strict=True):
                    bins[e] = bins.get(e, 0) + n
        for value in overflow.values():
            num, den = value.numerator, value.denominator
            e = num.bit_length() - den.bit_length()
            if (num << -e if e < 0 else num) < (den << e if e > 0 else den):
                e -= 1
            self.bins[0][e] = self.bins[0].get(e, 0) + 1
        self.max_rel = max(self.max_rel, float(np.max(rel)))
        if overflow:
            k, value = max(overflow.items(), key=lambda item: item[1])
            if self.overflow_max is None or value > self.overflow_max:
                self.overflow_max = value
                self.max_abs = "overflow"
                self.worst = ("overflow", start + int(where[k]), float(uu[k]), float(vv[k]), float(rel[k]))
        elif self.overflow_max is None:
            k = int(np.argmax(size))
            if self.worst is None or float(size[k]) > self.worst[0]:
                self.worst = (float(size[k]), start + int(where[k]), float(uu[k]), float(vv[k]), float(rel[k]))
                self.max_abs = self.worst[0]

    def row(self, pairing, ids=None):
        out = {"pairing": pairing, "compared": self.compared, "changed": self.changed,
               "increased": self.increased, "decreased": self.decreased,
               "max_abs": self.max_abs, "max_rel": self.max_rel,
               "max_ulps": self.max_ulps if self.ulps is not None else None,
               "scale": {"before": self.scale[0], "after": self.scale[1]},
               "abs_log2_bins": [[e, self.bins[0][e]] for e in sorted(self.bins[0])],
               "rel_log2_bins": [[e, self.bins[1][e]] for e in sorted(self.bins[1])], "worst": None}
        if self.worst is not None:
            size, flat, before, after, rel = self.worst
            index = [int(i) for i in np.unravel_index(flat, self.shape)] if self.shape else []
            out["worst"] = {"index": index, "before": before, "after": after, "abs": size, "rel": rel}
            if ids is not None and index:
                out["worst"]["cell_id"] = ids[index[0]]
        if self.absolute_overflow:
            exact = [hex(self.overflow_max.numerator), hex(self.overflow_max.denominator)]
            out.update(absolute_overflow=self.absolute_overflow, max_abs_exact=exact)
            out["worst"]["abs_exact"] = exact
        if self.compared <= SMALL_VALUES and self.dtype.kind in "iufb":
            out["values"] = self.values
        return out


def row_ids(C, name, x, y, ids_b, ids_a, layouts):
    """The unique per-row cell IDs a cell pairing of this array reads, chosen as correspondence()
    chooses them, or None. Diagnostics only."""
    if name.startswith(C.EXTERIOR_PREFIX):
        pair = ids_b, ids_a
    elif layouts is None:
        return None
    else:
        left, right = layouts[0].get(name), layouts[1].get(name)
        if not left or not right or not left.get("axis") == right.get("axis") == 0:
            return None
        cells = left.get("kind") == right.get("kind") and left.get("kind") in ("state-cell", "transport-cell")
        pair = (left.get("identity"), right.get("identity")) if cells else (left.get("rows"), right.get("rows"))
    if not all(type(ids) is list and all(type(i) in (str, int) for i in ids) and len(set(ids)) == len(ids)
               for ids in pair):
        return None
    if not (x["shape"] and y["shape"] and x["shape"][0] == len(pair[0]) and y["shape"][0] == len(pair[1])):
        return None
    return pair


def partial_sum(values):
    """math.fsum, or 'overflow' when an intermediate sum leaves binary64."""
    try:
        return math.fsum(values)
    except OverflowError:
        return "overflow"


def aggregate(path, dtype, shape, join=None):
    """One arm's (or its joined rows') element count, finite count, min, max and sum.

    Integers sum exactly; floats sum by math.fsum of per-block fsums (deterministic, not necessarily
    correctly rounded overall); other dtypes are counted only.
    """
    stats = {"count": 0, "finite": 0, "min": None, "max": None, "sum": None}
    numeric, partials = dtype.kind in "iuf", []
    for block in blocks(path, dtype, shape, join):
        stats["count"] += len(block)
        if not numeric:
            continue
        if dtype.kind == "f":
            block = block.astype(np.float64)
            block = block[np.isfinite(block)]
        if not len(block):
            continue
        stats["finite"] += len(block)
        low, high = block.min().item(), block.max().item()
        stats["min"] = low if stats["min"] is None else min(stats["min"], low)
        stats["max"] = high if stats["max"] is None else max(stats["max"], high)
        partials.append(sum(block.tolist()) if dtype.kind in "iu" else partial_sum(block.tolist()))
    if numeric:
        stats["sum"] = (sum(partials) if dtype.kind in "iu" else
                        "overflow" if "overflow" in partials else partial_sum(partials))
    return stats


def plain_aggregate(path, x):
    """aggregate() of an array listed by one arm only, or why it cannot be read."""
    try:
        dtype = np.dtype(x["dtype"])
        if dtype.hasobject or dtype.itemsize <= 0:
            return {"unreadable": "non-plain dtype"}
        return aggregate(path, dtype, x["shape"])
    except (OSError, ValueError, TypeError) as error:
        return {"unreadable": str(error)}


def unpaired(C, dtype, x, paths, ids):
    """Rows whose cell-ID sets differ. The cells in both arms are joined by cell ID (diagnostic,
    never a correspondence proof); each arm's other cells are counted, listed and aggregated."""
    ib, ia = ids
    common = set(ib) & set(ia)
    where_a = {cell: i for i, cell in enumerate(ia)}
    rows_b = [i for i, cell in enumerate(ib) if cell in common]
    rows_a = [where_a[ib[i]] for i in rows_b]
    tail = tuple(x["shape"][1:])
    view = (len(rows_b),) + tail
    stat = Magnitude(dtype, view, C.array_ulps if dtype.kind == "f" and dtype.itemsize == 8 else None)
    for u, v in zip(blocks(paths[0], dtype, view, np.asarray(rows_b, dtype=np.int64)),
                    blocks(paths[1], dtype, view, np.asarray(rows_a, dtype=np.int64)), strict=True):
        stat.add(u, v, np.any(u.view(np.uint8).reshape(-1, dtype.itemsize) !=
                              v.view(np.uint8).reshape(-1, dtype.itemsize), axis=1))
    row = stat.row("common-cell (diagnostic join by cell ID, not a correspondence proof)",
                   [ib[i] for i in rows_b])
    row["unpaired"] = {}
    for arm, cells, path in (("before", ib, paths[0]), ("after", ia, paths[1])):
        alone = [i for i, cell in enumerate(cells) if cell not in common]
        row["unpaired"][arm] = {
            "cells": len(alone), "listed": sorted((cells[i] for i in alone), key=str)[:MAX_LISTED],
            "aggregate": aggregate(path, dtype, (len(alone),) + tail, np.asarray(alone, dtype=np.int64))}
    return row


def diagnostics(C, dtype, x, y, paths, pairing, stat, ids, reasons):
    """The magnitude row of one REVIEW array."""
    if stat is not None:
        row = stat.row(pairing, ids[0] if ids is not None and pairing in ("same", "join") else None)
    elif ids is not None and set(ids[0]) != set(ids[1]):
        row = unpaired(C, dtype, x, paths, ids)
    else:
        row = {"pairing": "none", "aggregate": {"before": aggregate(paths[0], dtype, x["shape"]),
                                                "after": aggregate(paths[1], dtype, y["shape"])}}
    row.update(reasons=reasons, dtype=x["dtype"], shape=x["shape"], **NO_RADIUS)
    return row


def compare(C, before, after, fb, fa, bound_b, bound_a,
            ids_b=None, ids_a=None, layouts=None, magnitudes=None):
    rows, review, unbound = {}, [], {}
    a = {x["name"]: x for x in before["arrays"]}
    b = {x["name"]: x for x in after["arrays"]}
    for name in sorted(set(a) ^ set(b)):
        review.append("array only in %s: %s" % ("before" if name in a else "after", name))
        if magnitudes is not None:
            arm, x, folder = ("before", a[name], fb) if name in a else ("after", b[name], fa)
            magnitudes[name] = {"reasons": ["only in the %s arm" % arm], "dtype": x["dtype"], "shape": x["shape"],
                                "aggregate": {arm: plain_aggregate(folder / "arrays" / x["file"], x)},
                                **NO_RADIUS}
    for name in sorted(set(a) & set(b)):
        x, y = a[name], b[name]
        kinds = (bound_b[name], bound_a[name])
        reasons = []
        if any(k[0] != "bound" for k in kinds):
            why = next(k[1] for k in kinds if k[0] != "bound")
            unbound[why] = unbound.get(why, 0) + 1
            reasons.append("unbound: %s" % why)
        if (x["dtype"], x["shape"]) != (y["dtype"], y["shape"]):
            review.append("array %s: %s%s -> %s%s" % (
                name, x["dtype"], x["shape"], y["dtype"], y["shape"]))
            if magnitudes is not None:
                magnitudes[name] = {"reasons": reasons + ["dtype or shape changed"],
                                    "dtype": [x["dtype"], y["dtype"]], "shape": [x["shape"], y["shape"]],
                                    "aggregate": {"before": plain_aggregate(fb / "arrays" / x["file"], x),
                                                  "after": plain_aggregate(fa / "arrays" / y["file"], y)},
                                    **NO_RADIUS}
            continue
        dtype = np.dtype(x["dtype"])
        C.prove(not dtype.hasobject and dtype.itemsize > 0, "non-plain array dtype")
        pairing, join = correspondence(C, name, x, y, ids_b, ids_a, layouts)
        stat = None if magnitudes is None or pairing == "none" else Magnitude(
            dtype, x["shape"], C.array_ulps if dtype.kind == "f" and dtype.itemsize == 8 else None)
        count, nonfinite, max_ulps, max_abs = 0, [0, 0], 0, 0.0
        paths = (fb / "arrays" / x["file"], fa / "arrays" / y["file"])
        for u, v in zip(blocks(paths[0], dtype, x["shape"]),
                        blocks(paths[1], dtype, y["shape"],
                               join if pairing == "join" else None), strict=True):
            changed = np.any(u.view(np.uint8).reshape(-1, dtype.itemsize) !=
                             v.view(np.uint8).reshape(-1, dtype.itemsize), axis=1)
            count += int(np.count_nonzero(changed))
            if stat is not None:
                stat.add(u, v, changed)
            if dtype.kind in "fc":
                finite_u, finite_v = np.isfinite(u), np.isfinite(v)
                nonfinite[0] += int(np.count_nonzero(~finite_u))
                nonfinite[1] += int(np.count_nonzero(~finite_v))
                if dtype.kind == "f" and dtype.itemsize == 8:
                    finite = finite_u & finite_v
                    uu, vv = u[finite].astype("<f8"), v[finite].astype("<f8")
                    max_ulps = max(max_ulps, C.array_ulps(uu, vv))
                    with np.errstate(over="ignore", invalid="ignore"):
                        max_abs = max(max_abs, float(np.max(np.abs(uu - vv), initial=0.0)))
        if any(nonfinite):
            review.append("array %s holds non-finite values (before %d, after %d): no finite equality" %
                          (name, *nonfinite))
            rows[name] = {"equal": None, "nonfinite": nonfinite, "binding": [k[0] for k in kinds]}
            if magnitudes is not None:
                magnitudes[name] = diagnostics(C, dtype, x, y, paths, pairing, stat,
                                               row_ids(C, name, x, y, ids_b, ids_a, layouts),
                                               reasons + ["non-finite values (before %d, after %d)" % tuple(nonfinite)])
            continue
        if pairing == "none":
            review.append("array %s: %s" % (name, join))
            rows[name] = {"equal": None, "bytes_equal": count == 0,
                          "paired": None, "binding": [k[0] for k in kinds]}
            if magnitudes is not None:
                magnitudes[name] = diagnostics(C, dtype, x, y, paths, pairing, stat,
                                               row_ids(C, name, x, y, ids_b, ids_a, layouts),
                                               reasons + ["no correspondence: %s" % join])
            continue
        row = {"equal": count == 0, "binding": [k[0] for k in kinds]}
        if pairing == "join":
            row["paired"] = "cell_id"
        if count:
            row.update(changed=count, dtype=x["dtype"])
            if dtype.kind == "f" and dtype.itemsize == 8:
                row.update(max_ulps=max_ulps, max_abs=max_abs, nonfinite_changes=0)
            review.append("array %s changed in %d elements without an applicable bound" % (name, count))
            reasons.append("changed without an applicable bound")
        rows[name] = row
        if magnitudes is not None and reasons:
            magnitudes[name] = diagnostics(C, dtype, x, y, paths, pairing, stat,
                                           row_ids(C, name, x, y, ids_b, ids_a, layouts), reasons)
    for why, count in sorted(unbound.items()):
        review.append("%d arrays unbound (%s)" % (count, why))
    return rows, review
