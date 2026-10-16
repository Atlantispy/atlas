"""WP22/WP23 (profile-ranked): the rounded-interval jet convolution without per-product overhead.

Source transform of atlas_tectonics/integration_moving_face_moments.py. `_Jets.mul` on
rounded intervals (ORDER 32: up to 561 interval products per jet product) is about half of
the hardest IV2 interfaces' CPU. Its generic route

    tuple(self._sum(self.I.mul(a[i], b[k-i]) for i in range(k+1)
                    if a[i] != self.zero and b[k-i] != self.zero) for k in range(ORDER+1))

re-compares each coefficient with zero for every k and pays a generator and a `_sum` call
per coefficient. The replacement, used only when type(self) is _Jets (custom subclasses
keep the original line), tests each coefficient against zero once, then for every k adds
the SAME products, in the SAME order (i ascending), starting from the same zero, with the
same self.I.mul / self.I.add: every Decimal operation, its rounding and its order are
unchanged, so every jet is identical.
Record identity: numbers byte-identical; this module's source digest (written into wall
temporal-integration and, via the moving-interface digest, interface records) changes.
Coordinator D-b (16 Oct 2026) allows that for new intervals, judged per change.
"""
from hashlib import sha256

KNOWN_INPUT_SHA256 = {
    '42f2777f4f514b0c34036357aebc7a020aa431b46a43e7c23653897dcdd07dd3': 'RC1 composed-r1 runtime-src',
}
OLD = ('        return tuple(self._sum(self.I.mul(a[i], b[k-i]) for i in range(k+1)\n'
       '                     if a[i] != self.zero and b[k-i] != self.zero) for k in range(ORDER+1))\n')
NEW = ('        if type(self) is not _Jets:\n'
       '            return tuple(self._sum(self.I.mul(a[i], b[k-i]) for i in range(k+1)\n'
       '                         if a[i] != self.zero and b[k-i] != self.zero) for k in range(ORDER+1))\n'
       '        # Same products, same order, same zero start as the line above; each\n'
       '        # coefficient is compared with zero once instead of once per k.\n'
       '        zero, multiply, add = self.zero, self.I.mul, self.I.add\n'
       '        live_a = [x != zero for x in a]\n'
       '        live_b = [y != zero for y in b]\n'
       '        result = []\n'
       '        for k in range(ORDER+1):\n'
       '            value = zero\n'
       '            for i in range(k+1):\n'
       '                if live_a[i] and live_b[k-i]:\n'
       '                    value = add(value, multiply(a[i], b[k-i]))\n'
       '            result.append(value)\n'
       '        return tuple(result)\n')


def transform(source, *, allow_unreviewed_input=False):
    if 'live_a = [x != zero for x in a]' in source:
        raise ValueError('jet convolution transform already applied')
    if not allow_unreviewed_input and sha256(source.encode()).hexdigest() not in KNOWN_INPUT_SHA256:
        raise ValueError('moving-face input is not the reviewed module; pass allow_unreviewed_input and re-run parity')
    if source.count(OLD) != 1:
        raise ValueError('jet convolution anchor must occur exactly once')
    return source.replace(OLD, NEW)
