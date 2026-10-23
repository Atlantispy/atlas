"""C13 exact polygon successor: norm/edge reuse and symmetric output.

Stateless numerical helper; callers must use the prospective native owner.
Original validation and Fraction evaluation order for retained expressions remain.
No triangle-sum cache, rounding, geometry simplification or global state.
"""
from fractions import Fraction as Q


def decode(pair):
    return Q(int(pair[0], 16), int(pair[1], 16))


def vector(raw):
    if len(raw) != 3:
        raise ValueError('Three-dimensional exact face vector required')
    return tuple(map(decode, raw))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b, strict=True))


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b, strict=True))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def face_second_moment(face):
    """Return area-average (x-centroid)(x-centroid)^T; reject missing geometry.

    The declared centroid and normal are independently checked against polygon
    integrals. Either ring orientation is accepted. Convex half-plane checks
    reject self-crossing/nonconvex rings; no simplification or vertex snapping.
    """
    if 'vertices_m' not in face:
        raise ValueError('Exact face vertices required for second moments')
    points = [vector(p) for p in face['vertices_m']]
    centre, normal = vector(face['centroid_m']), vector(face['area_vector_m2'])
    if len(points) < 3 or len(set(points)) != len(points) or not (normal_squared := dot(normal, normal)):
        raise ValueError('Nondegenerate face polygon required')
    shifted = [sub(p, centre) for p in points]
    if any(dot(p, normal) for p in shifted):
        raise ValueError('Face vertices are not on the declared centroid plane')
    fan = [(shifted[0], a, b) for a, b in zip(shifted[1:-1], shifted[2:], strict=True)]
    area_vectors = [tuple(v/2 for v in cross(sub(b, a), sub(c, a))) for a, b, c in fan]
    area = tuple(sum(v[j] for v in area_vectors) for j in range(3))
    if area == normal:
        orientation = 1
    elif area == tuple(-v for v in normal):
        orientation = -1
    else:
        raise ValueError('Polygon area does not match declared face area')
    for a, b in zip(shifted, shifted[1:]+shifted[:1], strict=True):
        edge = sub(b, a)
        if any(orientation*dot(cross(edge, sub(p, a)), normal) < 0 for p in shifted):
            raise ValueError('Convex non-crossing face ring required')
    weights = [orientation*dot(a, normal)/normal_squared for a in area_vectors]
    if sum(weights) != 1 or any(w < 0 for w in weights):
        raise ValueError('Invalid polygon fan')
    first = [sum(w*sum(v[j] for v in triangle)/3 for w, triangle in zip(weights, fan, strict=True))
             for j in range(3)]
    if any(first):
        raise ValueError('Polygon centroid does not match declared face centroid')
    # Triangle barycentric integrals: E[lambda_i^2]=1/6 and
    # E[lambda_i lambda_j]=1/12. Stable exact shifted coordinates avoid large
    # origin cancellation even for a nanometre face far from the origin.
    result = []
    for i in range(3):
        row = []
        for j in range(3):
            value = result[j][i] if j < i else sum(
                w*(sum(v[i]*v[j] for v in tri)+sum(v[i] for v in tri)*sum(v[j] for v in tri))/12
                for w, tri in zip(weights, fan, strict=True))
            row.append(value)
        result.append(row)
    return result
