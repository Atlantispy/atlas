"""An exact great-circle ridge-transform staircase on a closed two-plate sphere.

Authored bounded control: the northern ridge is at longitude 0 degrees, the southern ridge at 20 degrees, and
their two actual ridge/transform corners are joined westwards along the equator. A distant trench at -120 degrees
closes the two plates and receives the area produced by spreading. This is one equatorial offset, not a model of
off-equator small-circle transforms. The sphere/material values and rotated-axis control reuse i03_fixtures.
SPDX-License-Identifier: AGPL-3.0-only
"""
import math

import i03_fixtures as F
from atlas_tectonics import integration_sphere as S
from atlas_tectonics import integration_transfer as T


SOURCE = 'test: tectonics/tests/i03_staircase_fixtures.py (authored equatorial staircase)'
RIDGES = ('ridge-north', 'ridge-south')
TRANSFORM = 'transform-step'
TRENCH = 'trench'
LONGITUDES = (-120., -60., 0., 20., 60., 120., 180.)
LATITUDES = (-60., -30., 0., 30., 60.)


def network(*, fraction=.5, tilt=None, longitudes_deg=LONGITUDES, latitudes_deg=LATITUDES):
    """A lies west of each ridge, B east; A carries the equatorial transform and overrides B at the trench.

    Mesh refinements may insert longitudes/latitudes, preserving the three declared meridians and the equator.
    Both ridge records have the same accretion fraction, so under coaxial plate rotations their equatorial ends
    move at the same ridge rate and the 20-degree transform length remains constant.
    """
    lons, lats = tuple(longitudes_deg), tuple(latitudes_deg)
    if (tuple(sorted(lons)) != lons or tuple(sorted(lats)) != lats
            or not {-120., 0., 20.} <= set(lons) or 0. not in lats or lons[0] != -120.):
        raise ValueError('the ordered fixture mesh retains -120, 0, 20 degree meridians and the equator')
    north, south, trench = lons.index(0.), lons.index(20.), lons.index(-120.)
    equator, bands = lats.index(0.), len(lats)
    vertices, rings = F.sector_mesh(lons, lats, tilt=tilt)

    def owner(name):
        southern = name.endswith('south') or ('-b' in name and int(name[-2:]) < equator)
        cut = south if southern else north
        return 'A' if F.sector_of(name) < cut else 'B'

    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    origin = F.origin(SOURCE)
    boundaries = (
        S.Boundary('ridge-north', S.RIDGE, 'A', 'B',
                   tuple(F.vertex(north, j) for j in range(equator, bands))+('N',), origin,
                   accretion_fraction=fraction),
        S.Boundary('ridge-south', S.RIDGE, 'A', 'B',
                   ('S',)+tuple(F.vertex(south, j) for j in range(equator+1)), origin,
                   accretion_fraction=fraction),
        S.Boundary(TRANSFORM, S.TRANSFORM, 'A', 'B',
                   tuple(F.vertex(i, equator) for i in range(south, north-1, -1)), origin,
                   carrier_side='left'),
        S.Boundary(TRENCH, S.TRENCH, 'B', 'A', F.chain(trench, bands), origin,
                   subducting_side='left'),
    )
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('A', 'B'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates,
                           boundaries=boundaries, epoch_id=F.EPOCH, time_s=F.START)


def state(**changes):
    return F.crust(network(**changes))


def supplies(**changes):
    return tuple(supply for name in RIDGES for supply in F.both_sides(name, **changes))


def motion(degrees, *, step=0, tilt=None, **changes):
    """A fixed, B eastward about the fixture's pole; no supplied junction path or external transform account."""
    values = dict(start_step=step, end_step=step+1, rotations={'A': F.IDENTITY, 'B': F.spin(degrees, tilt)},
                  supplies=supplies(), sinks=(F.sink(TRENCH),))
    values.update(changes)
    return T.Motion(**values)


def expected_birth_area(degrees):
    """Both hemispherical ridge lengths together: 2 R^2 delta, equal to the opposite full-meridian trench sweep."""
    return 2*F.RADIUS_M**2*math.radians(degrees)


PAIRED_RIDGES = tuple('ridge-%s-%d' % (side, copy) for copy in range(2) for side in ('north', 'south'))
PAIRED_TRANSFORMS = ('transform-step-0', 'transform-step-1')
PAIRED_TRENCHES = ('trench-0', 'trench-1')


def paired_network(*, fraction=.5, tilt=None, latitudes_deg=LATITUDES):
    """Two copies related by a half-turn about the Euler axis, using the same rigid A/B plate IDs.

    These are explicitly multipart plates, a manufactured force-balance control rather than geological output.
    Each plate and its material/force declarations retain C2 symmetry, so the full resistance tensor has the axis
    as an eigenvector and paired belt forces have no transverse resultant. No solved velocity is projected.
    """
    lons, lats = (0., 20., 60., 120., 180., 200., 240., 300.), tuple(latitudes_deg)
    equator, bands = lats.index(0.), len(lats)
    vertices, rings = F.sector_mesh(lons, lats, tilt=tilt)

    def owner(name):
        southern = name.endswith('south') or ('-b' in name and int(name[-2:]) < equator)
        sector = F.sector_of(name) % 4
        return 'B' if (1 if southern else 0) <= sector < 3 else 'A'

    faces = tuple(S.Face(name, owner(name), ring) for name, ring in rings.items())
    origin = F.origin(SOURCE+'#C2-multipart')
    boundaries = []
    for copy in range(2):
        north, south, trench = 4*copy, 4*copy+1, 4*copy+3
        boundaries.extend((
            S.Boundary('ridge-north-%d' % copy, S.RIDGE, 'A', 'B',
                       tuple(F.vertex(north, j) for j in range(equator, bands))+('N',), origin,
                       accretion_fraction=fraction),
            S.Boundary('ridge-south-%d' % copy, S.RIDGE, 'A', 'B',
                       ('S',)+tuple(F.vertex(south, j) for j in range(equator+1)), origin,
                       accretion_fraction=fraction),
            S.Boundary(PAIRED_TRANSFORMS[copy], S.TRANSFORM, 'A', 'B',
                       (F.vertex(south, equator), F.vertex(north, equator)), origin, carrier_side='left'),
            S.Boundary(PAIRED_TRENCHES[copy], S.TRENCH, 'B', 'A', F.chain(trench, bands), origin,
                       subducting_side='left'),
        ))
    plates = tuple(S.Plate(name, F.IDENTITY) for name in ('A', 'B'))
    return S.build_network(sphere=F.sphere(), vertices=vertices, faces=faces, plates=plates,
                           boundaries=tuple(boundaries), epoch_id=F.EPOCH, time_s=F.START)
