"""Private exact prefix-reusing subdivision of an already clipped convex cell.

This changes neither physical support nor the planar radial approximation. The
input is an outward-oriented convex polyhedron contained in ``voxel``. Tiles
are Cartesian in that voxel's exact rational orthogonal chart. All clipping
and positive-volume decisions use the existing exact geometry predicates.

Only the live recursion path retains clip scratch. Completed predicate work
is still charged cumulatively to the caller's arena, including generator
close or failure. A caller retaining a yielded polyhedron after advancing the
generator must reserve its storage, just as for other borrowed geometry.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import contextmanager
from fractions import Fraction as Q

from . import integration_volume as V
from . import integration_volume_bounds as B
from . import integration_volume_overlap as O


@contextmanager
def _scratch(account):
    """Release transient geometry, retaining exactly its predicate charge."""
    scratch = B._Arena(account.resource)
    try:
        with scratch:
            yield scratch
    finally:
        # ExitStack has returned both scratch and temporary work reservations.
        # Transfer only this arena's own operations, not nested child work.
        account.work(scratch.work_units)


def clipped_tiles(voxel, angular_poly, *, subdivisions=1, shared_lines=None,
                  arena):
    """Yield exact positive-volume ``(tile, angular_poly intersect tile)``.

    ``shared_lines`` is the existing full shared grid: each axis is strictly
    increasing and includes both voxel endpoints. No missing endpoint is
    inserted. Without it, ``subdivisions`` equal intervals divide each axis.
    Empty and boundary-only intersections are discarded by exact predicates,
    never by a size threshold. The uncut one-tile route returns ``voxel``.
    """
    if type(voxel) is not V.CartesianCell or not isinstance(arena, B._Arena):
        raise V.VolumeError('tile subdivision requires a CartesianCell and geometry arena')
    if type(subdivisions) is not int or subdivisions < 1:
        raise V.VolumeError('tile subdivisions must be a positive integer')
    if shared_lines is not None and (type(shared_lines) not in (tuple, list)
                                    or len(shared_lines) != 3
                                    or any(type(axis) not in (tuple, list) for axis in shared_lines)):
        raise V.VolumeError('shared tile lines require three explicit axes')
    if not angular_poly:
        return
    with _scratch(arena) as setup:
        if shared_lines is None:
            # Reserve the new coordinate rows before constructing them.
            with arena.resource.reserve(1024+3*(subdivisions+1)*256,
                                        category='curved-volume-scratch'):
                with V._work(voxel.lower_m+voxel.upper_m, arena.resource):
                    lines = tuple(tuple(a+(b-a)*Q(i, subdivisions)
                                        for i in range(subdivisions+1))
                                  for a, b in zip(voxel.lower_m, voxel.upper_m))
                setup.keep(tuple(q for axis in lines for q in axis))
        else:
            values = tuple(q for axis in shared_lines for q in axis)
            setup.work(6+len(values))
            with V._work(values+voxel.lower_m+voxel.upper_m, arena.resource):
                if any(any(a >= b for a, b in zip(axis, axis[1:])) for axis in shared_lines):
                    raise V.VolumeError('shared tile axes must be strictly increasing')
                lines = tuple(tuple(Q(q) for q in shared_lines[j]
                                    if voxel.lower_m[j] <= q <= voxel.upper_m[j])
                              for j in range(3))
                if any(len(axis) < 2 or axis[0] != voxel.lower_m[j]
                       or axis[-1] != voxel.upper_m[j] for j, axis in enumerate(lines)):
                    raise V.VolumeError('shared tile axes must include both voxel endpoints')
            setup.keep(tuple(q for axis in lines for q in axis))

        points = B._points(angular_poly)
        coordinates = tuple(q for p in points for q in p)
        setup.work(8+24*len(points))
        with V._work(coordinates+voxel.origin_m+tuple(q for row in voxel.basis for q in row),
                     arena.resource):
            normals = tuple(tuple(voxel.basis[i][j] for i in range(3)) for j in range(3))
            offsets = tuple(O._dot(n, voxel.origin_m) for n in normals)
            if any(not voxel.lower_m[j] <= O._dot(normals[j], p)-offsets[j] <= voxel.upper_m[j]
                   for p in points for j in range(3)):
                raise V.VolumeError('angular polyhedron is not contained in its parent voxel')
        setup.keep(tuple(q for n in normals for q in n)+offsets)
        indices = [0, 0, 0]

        def visit(poly, axis, first, stop):
            if not poly:
                return
            if axis == 3:
                with _scratch(arena) as leaf:
                    if B._volume(poly, leaf) > 0:
                        if all(len(row) == 2 for row in lines):
                            tile = voxel
                        else:
                            tile = V.CartesianCell(
                                tuple(lines[j][indices[j]] for j in range(3)),
                                tuple(lines[j][indices[j]+1] for j in range(3)),
                                voxel.origin_m, voxel.basis, budget=arena.resource)
                        yield tile, poly
                return
            if stop-first == 1:
                indices[axis] = first
                yield from visit(poly, axis+1, 0, len(lines[axis+1])-1 if axis < 2 else 0)
                return
            middle = (first+stop)//2
            with V._work(normals[axis]+(lines[axis][middle], offsets[axis]), arena.resource):
                plane = normals[axis]+(lines[axis][middle]+offsets[axis],)
                opposite = tuple(-q for q in plane)
            # Compute the right child only after the left child's geometry has
            # been released. Parent prefixes, rather than whole input clips,
            # are reused; no unbounded tile cache is retained.
            with _scratch(arena) as branch:
                yield from visit(B._clip(poly, plane, branch), axis, first, middle)
            with _scratch(arena) as branch:
                yield from visit(B._clip(poly, opposite, branch), axis, middle, stop)

        yield from visit(angular_poly, 0, 0, len(lines[0])-1)
