"""Supplied finite shortening/folding geometry, not a force or time solver.

Quarter-wave anchors are recognised by EXACT rational modulo only. Else cosine
and sine are binary64 evaluations, converted to represented Fractions; no near-
anchor/contact snapping. Inverse and stock accounts use those same coordinates.
"""
from dataclasses import dataclass
from fractions import Fraction as F
import math

from .columns import _q

SCHEMA = 'diadem.finite-fold-planation.r16'


@dataclass(frozen=True)
class FiniteMap:
    shortening_ratio: object
    centre_m: tuple
    z0_m: object
    amplitude_m: object
    wavelength_m: object
    tilt: object

    def __post_init__(self):
        if type(self.centre_m) is not tuple or len(self.centre_m) != 2:
            raise ValueError('explicit two-coordinate centre tuple required')
        object.__setattr__(self, 'centre_m', tuple(_q(v, 'centre coordinate') for v in self.centre_m))
        for name in ('shortening_ratio', 'z0_m', 'amplitude_m', 'wavelength_m', 'tilt'):
            object.__setattr__(self, name, _q(getattr(self, name), name,
                                           positive=name in {'shortening_ratio', 'wavelength_m'}))

    def _trig(self, u):
        turn = _q(u/self.wavelength_m, 'wave phase') % 1
        quarter = 4*turn
        if quarter.denominator == 1:
            index = int(quarter) % 4
            return F((1, 0, -1, 0)[index]), F((0, 1, 0, -1)[index]), 'EXACT_RATIONAL_QUARTER_WAVE'
        angle = math.tau*float(turn)
        return F(math.cos(angle)), F(math.sin(angle)), 'BINARY64_TRIG_REPRESENTED_AS_FRACTION'

    def _offset(self, u, v):
        cosine, _, mode = self._trig(u)
        return _q(self.amplitude_m*cosine+self.tilt*v, 'fold/tilt displacement'), mode

    def forward(self, X, Y, Z):
        """Reference local material coordinates -> current global scenario XYZ."""
        X, Y, Z = (_q(value, 'reference coordinate') for value in (X, Y, Z))
        u = _q(self.shortening_ratio*X, 'shortened x')
        offset, _ = self._offset(u, Y)
        return (_q(self.centre_m[0]+u, 'current x'), _q(self.centre_m[1]+Y, 'current y'),
                _q(self.z0_m+Z/self.shortening_ratio+offset, 'current z'))

    def inverse(self, x, y, z):
        """Current global scenario coordinates -> local material coordinates."""
        x, y, z = (_q(value, 'current coordinate') for value in (x, y, z))
        u, v = _q(x-self.centre_m[0], 'local x'), _q(y-self.centre_m[1], 'local y')
        offset, _ = self._offset(u, v)
        return (_q(u/self.shortening_ratio, 'reference X'), v,
                _q(self.shortening_ratio*(z-self.z0_m-offset), 'reference Z'))

    def jacobian(self, X, Y):
        """Analytic d(x,y,z)/d(X,Y,Z), with represented trig/pi; det=1 exactly."""
        X, Y = _q(X, 'reference X'), _q(Y, 'reference Y')
        _, sine, _ = self._trig(_q(self.shortening_ratio*X, 'shortened x'))
        du = _q(-self.amplitude_m*F(math.tau)*sine/self.wavelength_m, 'fold gradient')
        ratio = self.shortening_ratio
        return ((ratio, F(), F()), (F(), F(1), F()),
                (_q(ratio*du, 'reference fold gradient'), self.tilt, _q(1/ratio, 'thickening ratio')))

    def column(self, x, y, reference_contacts, cap_m, current_area_m2):
        """Centre-point contact/cap construction and exact prismatic accounts.

        Volume preservation is against reference area A/lambda, NOT the same
        Eulerian box. Retained volumes sample the cap at the support centre;
        they are not a cell-integrated cap intersection or conservative raster.
        """
        x, y = _q(x, 'support x'), _q(y, 'support y')
        cap = _q(cap_m, 'prescribed cap')
        area = _q(current_area_m2, 'current support area', positive=True)
        if type(reference_contacts) not in (list, tuple) or not 2 <= len(reference_contacts) <= 2049:
            raise ValueError('two to2049 explicit ordered finite contacts required')
        contacts = tuple(_q(value, 'reference contact') for value in reference_contacts)
        if any(a >= b for a, b in zip(contacts, contacts[1:])):
            raise ValueError('reference contacts must be strictly bottom-to-top')
        u, v = _q(x-self.centre_m[0], 'local x'), _q(y-self.centre_m[1], 'local y')
        ratio = self.shortening_ratio
        offset, mode = self._offset(u, v)
        pre = tuple(_q(self.z0_m+c/ratio+offset, 'mapped contact') for c in contacts)
        top = min(pre[-1], cap)
        if top < pre[0]:
            raise ValueError('prescribed cap below finite mapped base')
        reference_top = _q(ratio*(top-self.z0_m-offset), 'retained reference contact')
        original = [_q((b-a)/ratio, 'pre-stripping thickness', positive=True)
                    for a, b in zip(contacts, contacts[1:])]
        retained = [_q(max(F(), min(b, reference_top)-a)/ratio, 'retained thickness', nonnegative=True)
                    for a, b in zip(contacts, contacts[1:])]
        reference_area = _q(area/ratio, 'reference preimage area', positive=True)
        reference_volumes = [_q(reference_area*(b-a), 'reference bulk volume', positive=True)
                             for a, b in zip(contacts, contacts[1:])]
        volumes = [_q(area*thickness, 'current bulk volume', positive=True) for thickness in original]
        kept = [_q(area*thickness, 'retained bulk volume', nonnegative=True) for thickness in retained]
        exported = [_q(before-after, 'exported bulk volume', nonnegative=True) for before, after in zip(volumes, kept)]
        if reference_volumes != volumes or any(a != b+c for a, b, c in zip(volumes, kept, exported)):
            raise ArithmeticError('exact reference/current/retained/exported volume account failed')
        exposed = next((index for index in range(len(retained)-1, -1, -1) if retained[index]), None)
        return {'schema': SCHEMA, 'displacement_m': str(offset), 'pre_contacts_m': list(map(str, pre)),
            'retained_thicknesses_m': list(map(str, retained)), 'reference_preimage_area_m2': str(reference_area),
            'reference_bulk_volumes_m3': list(map(str, reference_volumes)), 'current_bulk_volumes_m3': list(map(str, volumes)),
            'retained_bulk_volumes_m3': list(map(str, kept)), 'exported_bulk_volumes_m3': list(map(str, exported)),
            'final_base_m': str(pre[0]), 'final_top_m': str(top), 'exposed_index': exposed,
            'exhausted': exposed is None, 'stripping_applied': top < pre[-1],
            'reference_contacts_m': list(map(str, contacts)), 'current_area_m2': str(area),
            'reference_xy_m': [str(_q(u/ratio, 'reference support X')), str(v)],
            'horizontal_displacement_m': [str(_q(u-u/ratio, 'horizontal shortening displacement')), '0'],
            'contact_vertical_displacements_m': [str(_q(h-self.z0_m-c, 'contact vertical displacement')) for h, c in zip(pre, contacts)],
            'jacobian_determinant': '1', 'volume_residuals_m3': ['0']*len(retained),
            'trigonometric_evaluation': mode, 'anchor_policy': 'EXACT_RATIONAL_MODULO_ONLY; NO_NEAR_ANCHOR_OR_CONTACT_SNAPPING',
            'general_coordinate_comparison_tolerance': {'absolute_m': '1e-8', 'relative': '1e-12'},
            'sampling': 'CENTRE_POINT_FINITE_PRISM; NOT_CELL_AVERAGE_OR_CONSERVATIVE_RASTER_REMAP',
            'exposure_convention': 'MATERIAL_IMMEDIATELY_BELOW_RETAINED_TOP; ZERO_THICKNESS_OMITTED',
            'scope': 'PRESCRIBED_VOLUME_PRESERVING_FINITE_MAP_AND_CAP; NO_CLOCK_FORCES_OR_CALIBRATION'}
