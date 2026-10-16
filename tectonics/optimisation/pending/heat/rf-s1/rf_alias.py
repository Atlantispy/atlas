"""Aliasing, theta-type, independent call counts (sys.setprofile) for r4 vs r5."""
import sys
import rf_common as c
import rf_systems as S

# --- (a) aliasing
for kind in ('full', 'zero', 'bisect'):
    args = S.author(kind)
    for label, mod in (('r4', c.Q4), ('r5', c.Q5)):
        owner = mod.closed_guard(*args, budget=c.WorkBudget(1 << 34))
        v = owner.value
        cert, full, low = v['certificate'], v['full_endpoint_certificate'], v['low_endpoint_certificate']
        print(kind, label, 'theta', c.canon(v['theta'])[1:],
              '| cert is endpoint dict:', cert is full or cert is low,
              '| endpoint has stock_conservation key:', 'stock_conservation_certificate' in full or 'stock_conservation_certificate' in low,
              '| cert has key:', 'stock_conservation_certificate' in cert,
              '| nested exact_h shared with full:', cert['exact_h_change_certificate'] is full['exact_h_change_certificate'],
              '| with low:', cert['exact_h_change_certificate'] is low['exact_h_change_certificate'],
              '| flags shared:', cert['flags'] is full['flags'] or cert['flags'] is low['flags'])
        owner.close()

# --- (b) theta type: wrap feasible_scalar to return a Python int theta equal to 0/1
orig = c.A.feasible_scalar
def int_theta(pred):
    theta, sel = orig(pred)
    return (int(theta) if theta in (0, 1) else theta), sel
c.A.feasible_scalar = int_theta
try:
    for kind in ('full', 'zero'):
        args = S.author(kind)
        for label, mod in (('r4', c.Q4), ('r5', c.Q5)):
            out, used = c.call(mod, args)
            print('INT-THETA', kind, label, out[0], out[1] if out[0] != 'passed' else dict(out[1][1])['theta'], (out[2] if out[0] == 'exc' else ''))
finally:
    c.A.feasible_scalar = orig

# --- (c) independent call counts via sys.setprofile
def counts(mod, args):
    n = {}
    fn = mod.__file__.replace(chr(92), '/')
    def prof(frame, event, arg):
        if event == 'call' and frame.f_code.co_filename.replace(chr(92), '/') == fn and \
                frame.f_code.co_name in ('certificate', 'admissible', 'state', '_quadratic', '_reused_certificate'):
            n[frame.f_code.co_name] = n.get(frame.f_code.co_name, 0)+1
    sys.setprofile(prof)
    try:
        owner = mod.closed_guard(*args, budget=c.WorkBudget(1 << 34))
        owner.close()
    finally:
        sys.setprofile(None)
    return n
for kind in ('full', 'same', 'bisect', 'zero', 'refused'):
    args = S.author(kind)
    try:
        print('COUNT', kind, 'r4', counts(c.Q4, args), 'r5', counts(c.Q5, args))
    except Exception as e:  # refused escapes via exception from closed_guard
        print('COUNT', kind, 'raised', type(e).__name__)
