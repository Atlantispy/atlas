"""Exact-rational clean-leaf sphere enclosure for private integration.

SPDX-License-Identifier: AGPL-3.0-only

The caller MUST have proved the entire cell satisfies every true angular
halfspace. This helper proves only radial containment and measure. A Cartesian
cell is x=o+Bq with exactly orthogonal B. In w=B^T x=q+B^T o the sphere is
centred at zero and the cell is still a box; reflection of one axis preserves
both volume and the squared radius.

For a clean positive-k box, g(y)=sqrt(S-|y|^2) lies between alpha and beta on
every column. Average its centred quadratic Taylor polynomial as T(r)=r-C/r,
r=sqrt(G), G=S-|yc|^2. T increases for positive r. The directional fourth
derivative along a unit vector is -3*A*(A+4*tau^2)/(A-tau^2)^(7/2). Thus with
m=alpha, M4=3*S*(S+4*Ymax)/m^7 bounds its absolute value everywhere in D.
Odd terms and the quadratic cross term integrate to zero. The remainder is
non-positive and its average magnitude is bounded by
M4/24*((hi^4+hj^4)/5+2*hi^2*hj^2/9). Positive rational root brackets are refined
until their T-width is at most E/8; no fixed physical tolerance is introduced.

An independent sqrt-free inner box supplies an existential positive witness.
Its volume is never inferred from the quadrature lower bound. A zero-thickness
inner box offers no witness and does NOT assert zero volume for the leaf.
"""
from fractions import Fraction as Q
from math import isqrt

from atlas_tectonics import integration_volume as V


def _root_terms(g, coefficient, error, arena):
    """Return positive rational T endpoints with width <= error/8.

If n=floor(sqrt(floor(g*2^(2b)))), n/2^b <= sqrt(g) < (n+1)/2^b.
An exact square collapses the bracket. Memory is admitted before constructing
the shifted integers, and every refinement participates in cancellation/work
admission. All reservations unwind on refusal or caller cancellation.
"""
    bits = max(8, (g.denominator.bit_length()-g.numerator.bit_length()+1)//2+2)
    input_bits = V._bits(g)+V._bits(coefficient)+V._bits(error)
    while True:
        arena.work(32+bits)
        with arena.resource.reserve(65536+128*(input_bits+4*bits),
                                    category='sphere-quadrature-root-scratch'):
            denominator = 1 << bits
            scaled = g.numerator << (2*bits)
            n = isqrt(scaled//g.denominator)
            if n:
                root_low = Q(n, denominator)
                root_high = (root_low if n*n*g.denominator == scaled else
                             Q(n+1, denominator))
                low = root_low-coefficient/root_low
                high = root_high-coefficient/root_high
                if high-low <= error/8:
                    return low, high, bits
        bits *= 2


def enclose(layer, cell, arena):
    """Return (bounds, witness_volume, world_point_or_none, detail), or None.

Precondition: the caller has certified whole-cell angular containment. Only
strict single-sphere crossings with clean columns are accepted. Returned
detail gives the reflected sphere-frame witness box (when positive), allowing
its eight world vertices to be reconstructed as B times the unreflected
corners. Returned values become caller-owned; no cache or scratch is retained.
"""
    arena.work(128)
    with V._work((*layer._geometry(), *cell._geometry()), arena.resource):
        offset = tuple(sum(cell.basis[k][j]*cell.origin_m[k] for k in range(3))
                       for j in range(3))
        ends = tuple((a+o, b+o) for a, b, o in
                     zip(cell.lower_m, cell.upper_m, offset))
        minima = tuple(Q(0) if a <= 0 <= b else min(a*a, b*b) for a, b in ends)
        maxima = tuple(max(a*a, b*b) for a, b in ends)
        minimum, maximum = sum(minima, Q(0)), sum(maxima, Q(0))
        lower2 = (layer.radius_m-layer.bottom_depth_m)**2
        upper2 = (layer.radius_m-layer.top_depth_m)**2
        if minimum >= lower2 and minimum < upper2 < maximum:
            branch, sphere = 'upper', upper2
        elif maximum <= upper2 and minimum < lower2 < maximum:
            branch, sphere = 'lower', lower2
        else:
            return None

        axes = tuple(j for j, (a, b) in enumerate(ends) if not a <= 0 <= b)
        if not axes:
            return None
        axis = max(axes, key=lambda j: min(abs(ends[j][0]), abs(ends[j][1])))
        reflected = ends[axis][1] < 0
        alpha, beta = ((-ends[axis][1], -ends[axis][0]) if reflected else ends[axis])
        lateral = tuple(j for j in range(3) if j != axis)
        ymin = sum((minima[j] for j in lateral), Q(0))
        ymax = sum((maxima[j] for j in lateral), Q(0))
        if not alpha*alpha <= sphere-ymax or not sphere-ymin <= beta*beta:
            # Plan19: preserve every existing successful preferred-axis
            # choice. Only its decline admits a bounded alternate search.
            preferred_axis = axis
            for alternate_axis in axes:
                if alternate_axis == preferred_axis:
                    continue
                arena.work(64)
                with V._work((*minima, *maxima,
                              *(q for pair in ends for q in pair)), arena.resource):
                    axis = alternate_axis
                    reflected = ends[axis][1] < 0
                    alpha, beta = ((-ends[axis][1], -ends[axis][0])
                                   if reflected else ends[axis])
                    lateral = tuple(j for j in range(3) if j != axis)
                    ymin = sum((minima[j] for j in lateral), Q(0))
                    ymax = sum((maxima[j] for j in lateral), Q(0))
                    if alpha*alpha <= sphere-ymax and sphere-ymin <= beta*beta:
                        break
            else:
                return None
            del preferred_axis, alternate_axis

        arena.work(96)
        centres = tuple((ends[j][0]+ends[j][1])/2 for j in lateral)
        halves = tuple((ends[j][1]-ends[j][0])/2 for j in lateral)
        area = 4*halves[0]*halves[1]
        volume = area*(beta-alpha)
        g = sphere-sum((v*v for v in centres), Q(0))
        coefficient = sum(((g+c*c)*h*h for c, h in zip(centres, halves)), Q(0))/(6*g)
        m4 = 3*sphere*(sphere+4*ymax)/alpha**7
        hi, hj = halves
        error = m4*((hi**4+hj**4)/5+2*hi*hi*hj*hj/9)/24
        if error <= 0:
            raise V.VolumeError('clean nondegenerate sphere leaf requires positive remainder bound')

        # Derived rationals remain charged while the root and output stages run.
        with V._work((alpha, beta, ymin, ymax, area, volume, g, coefficient, m4, error,
                      *centres, *halves), arena.resource):
            t_low, t_high, root_bits = _root_terms(g, coefficient, error, arena)
            arena.work(96)
            with V._work((t_low, t_high, error, area, volume, alpha, beta,
                          sphere, ymin, ymax, *cell._geometry()), arena.resource):
                integral_low, integral_high = area*(t_low-error), area*t_high
                if branch == 'upper':
                    low, high = integral_low-alpha*area, integral_high-alpha*area
                    delta = (sphere-ymax-alpha*alpha)/(alpha+beta)
                    axial = (alpha, alpha+delta)
                else:
                    low, high = beta*area-integral_high, beta*area-integral_low
                    delta = (beta*beta-sphere+ymin)/(2*beta)
                    axial = (beta-delta, beta)
                if not 0 <= delta <= beta-alpha:
                    raise V.VolumeError('inner witness box escaped its clean leaf')
                witness_volume = area*delta
                low, high = max(Q(0), low, witness_volume), min(volume, high)
                if not 0 <= low <= high <= volume:
                    raise V.VolumeError('inconsistent clean-sphere enclosure or inner witness')
                point, witness_box = None, None
                if delta:
                    witness_box = tuple(axial if j == axis else ends[j] for j in range(3))
                    centre = tuple((a+b)/2 for a, b in witness_box)
                    unreflected = tuple(-v if reflected and j == axis else v
                                        for j, v in enumerate(centre))
                    # w=B^T x already includes B^T origin: adding origin again is wrong.
                    point = tuple(sum(b*v for b, v in zip(row, unreflected))
                                  for row in cell.basis)
                detail = dict(branch=branch, axis=axis, reflected=reflected,
                              root_bits=root_bits, error=error,
                              root_t_width=t_high-t_low, witness_box=witness_box)
                return (low, high), witness_volume, point, detail
