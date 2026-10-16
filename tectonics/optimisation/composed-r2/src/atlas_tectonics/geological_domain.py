"""Plate-independent support for R2 initial geology (not a physical plate mesh).

A bounded planar/spherical surface, or an entire explicitly framed sphere, may
carry geology before any plate interior is identified. There are deliberately no
plate/region ownership records. Existing stage-3 networks remain separate APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .coordinates import SphericalFrame
from .geometry import PlanarGeometry
from .spherical_geometry import SphericalGeometry
from .geological_records import GeologyError, _name


@dataclass(frozen=True, slots=True)
class GeologicalDomain:
    """A shared immutable surface; depths are specified by the containing case.

    Planar depths are measured perpendicular to the declared local surface.
    Spherical depths are radial inward from ``sphere.radius_m``. The sphere is
    a reference surface, not an ellipsoid or a volumetric dynamics grid.
    ``source_id`` identifies how this support was specified, not its acceptance.
    """
    surface: PlanarGeometry | SphericalGeometry | SphericalFrame
    source_id: str

    def __post_init__(self):
        _name(self.source_id, 'domain source')
        if type(self.surface) not in (PlanarGeometry, SphericalGeometry, SphericalFrame):
            raise GeologyError('a typed planar area, spherical patch or full sphere is required')
        if type(self.surface) is not SphericalFrame:
            if self.surface.is_empty or self.surface.kind not in ('Polygon', 'MultiPolygon'):
                raise GeologyError('geological domain must have nonempty areal support')

    @property
    def sphere(self):
        if type(self.surface) is SphericalFrame:
            return self.surface
        if type(self.surface) is SphericalGeometry:
            return self.surface.chart.sphere
        return None

    @property
    def frame_id(self):
        return self.surface.frame_id if type(self.surface) is PlanarGeometry else self.sphere.frame_id

    @property
    def full_sphere(self):
        return type(self.surface) is SphericalFrame

    @property
    def domain(self):
        """Bounded geometry only; a full sphere must never become a fake polygon."""
        if self.full_sphere:
            raise GeologyError('full sphere has no single conditioned surface polygon')
        return self.surface

    @property
    def plate_ids(self):
        return ()

    @property
    def region_ids(self):
        return ()

    @property
    def regions(self):
        return ()

    @property
    def vertex_count(self):
        return 0 if self.full_sphere else self.surface.vertex_count

    @property
    def edge_count(self):
        # Used only as an upper-bound setup allowance, not physical boundaries.
        return self.vertex_count

    @property
    def retained_bytes(self):
        return 1024 + (0 if self.full_sphere else self.surface.retained_bytes)

    def descriptor(self):
        return {'schema': 'atlas.geological-domain.v1', 'source_id': self.source_id,
                'support': 'full-sphere' if self.full_sphere else 'bounded-surface',
                'surface': self.surface.descriptor()}

    @property
    def domain_id(self):
        raw = json.dumps(self.descriptor(), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        return hashlib.sha256(raw).hexdigest()


def restore_geological_domain(descriptor, geometries):
    """Rebuild from already verified geometry bytes; never generate new support."""
    if type(descriptor) is not dict or set(descriptor) != {'schema', 'source_id', 'support', 'surface'}:
        raise GeologyError('invalid geological domain descriptor')
    if descriptor['schema'] != 'atlas.geological-domain.v1':
        raise GeologyError('unsupported geological domain version')
    try:
        d = descriptor['surface']
        if descriptor['support'] == 'full-sphere':
            surface = SphericalFrame(d['radius_m'], d['frame_id'])
        elif descriptor['support'] == 'bounded-surface':
            surface = geometries[d['geometry_id']]
        else:
            raise GeologyError('unknown domain support')
        result = GeologicalDomain(surface, descriptor['source_id'])
        if result.descriptor() != descriptor:
            raise GeologyError('geological domain identity mismatch')
        return result
    except (KeyError, TypeError) as exc:
        raise GeologyError('malformed geological domain descriptor') from exc
