"""Uninstalled diagnostic context for authenticated common-material pose.

Only issuer-derived incidence inventory can authorise expected families. This
context does not establish completeness, preserve a mesh, or confer IV GO.
"""
from fractions import Fraction as Q


class FamilyPose:
    def __init__(self, support_record, budget, arena, D, W, V, E, start_selector):
        self.D, self.W, self.start_selector, self.arena = D, W, start_selector, arena
        self.omega = tuple(map(W._decode, support_record['material_angular_velocity_rad_s']))
        self.start = W._decode(support_record['start_time_s'])
        self.end = W._decode(support_record['end_time_s'])
        self.duration = W._decode(support_record['duration_s'])
        self.frame = support_record['grid_id']
        if self.end-self.start != self.duration or self.duration < 0:
            raise ValueError('inconsistent issued segment')
        segment = dict(angular_velocity_rad_s=support_record['material_angular_velocity_rad_s'],
                       start_time_s=V._encoded(0),end_time_s=V._encoded(self.duration))
        quat,self.error=E._representative_pose([segment], Q(1,1<<48), arena)
        self.matrix=V.CartesianCell((0,0,0),(1,1,1),budget=budget).rotated(quat,budget=budget).basis
        if not all(sum(self.matrix[k][i]*self.matrix[k][j] for k in range(3)) == (1 if i==j else 0)
                   for i in range(3) for j in range(3)):
            raise ValueError('nonorthogonal material representative')
        m=self.matrix
        det=m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])-m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])+m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0])
        if det != 1: raise ValueError('material pose is not proper')

    def start_and_key(self, constraint):
        start=self.start_selector(constraint,self.omega,self.D,self.W,self.arena)
        if start is None: return None
        b,d=start
        first=next((q for q in b if q),None)
        if first is None or d != 0: raise ValueError('invalid material start plane')
        key=(self.frame,self.start,self.end,self.omega,tuple(q/first for q in b))
        return key,tuple(q/abs(first) for q in b)

    def place(self, constraint, families, old_pose, *, expected=False):
        result=self.start_and_key(constraint)
        if result is None or result[0] not in families:
            if expected: raise ValueError('unproved expected material incidence')
            return old_pose,False
        _,base=result
        normal=tuple(sum(self.matrix[i][j]*base[j] for j in range(3)) for i in range(3))
        return (normal,self.error*sum(map(abs,base)),Q(0)),True
