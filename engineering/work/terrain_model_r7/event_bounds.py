"""Exact sufficient no-drying proof, independent of any RK error estimate.

For the declared fixed-footprint ODE and exact rational binary64 inputs,
c'=P(c)/V, P=qs-(qw+qs+v*A)c+v*A*c*c. Its physical root is invariant;
c stays between c0 and that root while V>0. Rational sign bisection bounds
the root without evaluating a square root. Thus h'=g-v*c is bounded below.
A strictly positive lower h on the entire interval closes the continuation
argument: occupied V remains positive, so the assumptions cannot fail first.
This is sufficient, not necessary. Failure to prove is NOT proof of drying.
"""
from fractions import Fraction as F


def ratio(q):
    return {'numerator': q.numerator, 'denominator': q.denominator}


def no_drying_bound(*, liquid, solid, area, qw, qs, qo, velocity, duration, depth):
    w,s,a,qw,qs,qo,v,t,h = map(F, (liquid,solid,area,qw,qs,qo,velocity,duration,depth))
    if w <= 0 or s < 0 or a <= 0 or h <= 0 or min(qw,qs,qo,v,t) < 0 or (qs and not qw):
        raise ValueError('valid positive-carrier fixed-footprint inputs required')
    c0=s/(w+s);k=v*a;q=qw+qs
    def polynomial(c):return qs-(q+k)*c+k*c*c
    sign=polynomial(c0)
    if sign == 0:
        lower=upper=c0
    elif sign > 0:
        lo,hi=c0,F(1)
        for _ in range(64):
            mid=(lo+hi)/2
            if polynomial(mid)>0:lo=mid
            else:hi=mid
        lower,upper=c0,hi
    else:
        lo,hi=F(),c0
        for _ in range(64):
            mid=(lo+hi)/2
            if polynomial(mid)>=0:lo=mid
            else:hi=mid
        lower,upper=lo,c0
    if not (0<=lower<=c0<=upper<=1):raise ValueError('concentration invariant failed')
    g=(q-qo)/a
    derivative_lower=g-v*upper
    height_lower=h+min(F(),derivative_lower)*t
    return {'status':'PROVED_POSITIVE_DEPTH' if height_lower>0 else 'NOT_PROVED',
            'method':'EXACT_RATIONAL_CONCENTRATION_INVARIANT',
            'equations':'EXACT_BINARY64_INPUT_RATIONAL_FIXED_FOOTPRINT',
            'concentration_lower':ratio(lower),'concentration_upper':ratio(upper),
            'minimum_depth_lower_m':ratio(height_lower),
            'depth_derivative_lower_m_year':ratio(derivative_lower),
            'duration_years':ratio(t),
            'uses_numerical_trajectory_or_error_estimate':False,
            'is_sufficient_not_necessary':True}
