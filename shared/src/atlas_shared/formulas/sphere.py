"""Spherical direction angles and Cartesian components in binary64."""

import math

import numpy as np


def angle_scalar_from_chords(difference, total):
    """Use one binary64 dot product per chord for a pair of directions."""
    return 2 * math.atan2(math.sqrt(difference.dot(difference)), math.sqrt(total.dot(total)))


def angle_scalar(a, b):
    """Unsigned minor-arc angle between two binary64 directions."""
    return angle_scalar_from_chords(a - b, a + b)


def angle_array_from_chords(difference, total):
    """Evaluate one angle per vector along the last axis."""
    return 2 * np.arctan2(np.sqrt(np.add.reduce(difference * difference, axis=-1)),
                         np.sqrt(np.add.reduce(total * total, axis=-1)))


def angle_array(a, b):
    """Unsigned minor-arc angles, broadcasting over leading dimensions."""
    return angle_array_from_chords(a - b, a + b)


def angle_driving_cross(a, b, cross):
    """Preserve the driving moment's improper-arc refusal."""
    return math.atan2(float(np.linalg.norm(cross)), float(a @ b))


def angle_family_cross(a, b):
    """Preserve the Voronoi edge's choice of construction at 120 degrees."""
    cross = np.cross(a, b)
    return math.atan2(math.sqrt(cross[0]*cross[0]+cross[1]*cross[1]+cross[2]*cross[2]),
                      a[0]*b[0]+a[1]*b[1]+a[2]*b[2])


def angle_ring_sampling_cross(a, b):
    """Preserve the numerical arc lengths used to count and place samples."""
    return np.arctan2(np.linalg.norm(np.cross(a+b, b-a), axis=1)/2, np.sum(a*b, axis=1))


def lonlat_cartesian(lon, lat, *, sin, cos):
    """Convert radians using the caller's scalar or array trigonometry."""
    cos_lat = cos(lat)
    return np.stack((cos_lat * cos(lon), cos_lat * sin(lon), sin(lat)), axis=-1)
