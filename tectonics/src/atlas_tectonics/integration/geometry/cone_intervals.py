"""Isolated exact endpoint helpers for _common_ray_cone_zero_volume only.

Input contract: ordered pairs of Python int/Fraction values; vector boxes
have exactly three axes. These are the existing cone predicate's inputs.
No float conversion, changed bound, retained cache or new backend is involved.
SPDX-License-Identifier: AGPL-3.0-only
"""


def _cone_product(first, second):
    """The same min/max of four products, with sign-proved endpoint selection.

    Canonical exact rationals have positive denominators, so numerator signs
    suffice. The nine closed sign cases also cover point and zero intervals.
    Only the strictly straddling/straddling case needs all four products.
    """
    lo, hi = first
    left, right = second
    if lo.numerator >= 0:
        if left.numerator >= 0:
            return lo*left, hi*right
        if right.numerator <= 0:
            return hi*left, lo*right
        return hi*left, hi*right
    if hi.numerator <= 0:
        if left.numerator >= 0:
            return lo*right, hi*left
        if right.numerator <= 0:
            return hi*right, lo*left
        return lo*right, lo*left
    if left.numerator >= 0:
        return lo*right, hi*right
    if right.numerator <= 0:
        return hi*left, lo*left
    return min(lo*right, hi*left), max(lo*left, hi*right)


def _cone_minus(first, second):
    return first[0]-second[1], first[1]-second[0]


def _cone_cross_bounds(a, b):
    """Same reference allocation shape and cross-product interval."""
    return tuple(_cone_minus(_cone_product(a[(j+1) % 3], b[(j+2) % 3]),
                             _cone_product(a[(j+2) % 3], b[(j+1) % 3]))
                 for j in range(3))


def _cone_dot_bounds(a, b):
    """Exactly the reference dot-product interval, on three-axis boxes."""
    first = _cone_product(a[0], b[0])
    second = _cone_product(a[1], b[1])
    third = _cone_product(a[2], b[2])
    return (first[0]+second[0]+third[0], first[1]+second[1]+third[1])
