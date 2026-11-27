"""One conservative conduction solve for a box and finite adjacent cells.

Each declared exterior cell is an orthogonal prism over one complete box face
cell. Its other faces are insulated. This is a finite-volume thermal boundary,
not a prescribed-temperature reservoir or a claim of curved-cell support.
SPDX-License-Identifier: AGPL-3.0-only
"""
from fractions import Fraction as Q





def _exact(value):
    q = value if type(value) is Q else Q(float(value))
    return [hex(q.numerator), hex(q.denominator)]

