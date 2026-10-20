"""Bounded byte comparison with independently supplied row correspondence.

This module supplies no numerical allowance. A changed, otherwise bound array
needs a separately source-bound quantity contract and remains REVIEW here.
"""
from __future__ import annotations

import math
import numpy as np

BLOCK_BYTES = 1 << 20


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


def compare(C, before, after, fb, fa, bound_b, bound_a,
            ids_b=None, ids_a=None, layouts=None):
    rows, review, unbound = {}, [], {}
    a = {x["name"]: x for x in before["arrays"]}
    b = {x["name"]: x for x in after["arrays"]}
    for name in sorted(set(a) ^ set(b)):
        review.append("array only in %s: %s" % ("before" if name in a else "after", name))
    for name in sorted(set(a) & set(b)):
        x, y = a[name], b[name]
        kinds = (bound_b[name], bound_a[name])
        if any(k[0] != "bound" for k in kinds):
            why = next(k[1] for k in kinds if k[0] != "bound")
            unbound[why] = unbound.get(why, 0) + 1
        if (x["dtype"], x["shape"]) != (y["dtype"], y["shape"]):
            review.append("array %s: %s%s -> %s%s" % (
                name, x["dtype"], x["shape"], y["dtype"], y["shape"]))
            continue
        dtype = np.dtype(x["dtype"])
        C.prove(not dtype.hasobject and dtype.itemsize > 0, "non-plain array dtype")
        pairing, join = correspondence(C, name, x, y, ids_b, ids_a, layouts)
        count, nonfinite, max_ulps, max_abs = 0, [0, 0], 0, 0.0
        paths = (fb / "arrays" / x["file"], fa / "arrays" / y["file"])
        for u, v in zip(blocks(paths[0], dtype, x["shape"]),
                        blocks(paths[1], dtype, y["shape"],
                               join if pairing == "join" else None), strict=True):
            changed = np.any(u.view(np.uint8).reshape(-1, dtype.itemsize) !=
                             v.view(np.uint8).reshape(-1, dtype.itemsize), axis=1)
            count += int(np.count_nonzero(changed))
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
            continue
        if pairing == "none":
            review.append("array %s: %s" % (name, join))
            rows[name] = {"equal": None, "bytes_equal": count == 0,
                          "paired": None, "binding": [k[0] for k in kinds]}
            continue
        row = {"equal": count == 0, "binding": [k[0] for k in kinds]}
        if pairing == "join":
            row["paired"] = "cell_id"
        if count:
            row.update(changed=count, dtype=x["dtype"])
            if dtype.kind == "f" and dtype.itemsize == 8:
                row.update(max_ulps=max_ulps, max_abs=max_abs, nonfinite_changes=0)
            review.append("array %s changed in %d elements without an applicable bound" % (name, count))
        rows[name] = row
    for why, count in sorted(unbound.items()):
        review.append("%d arrays unbound (%s)" % (count, why))
    return rows, review
