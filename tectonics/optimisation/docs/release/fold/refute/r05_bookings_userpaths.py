"""Bookings that are bool/negative, and user paths the USER_PATH regex misses."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import parity as P  # noqa: E402

m = dict(key_map={}, sha_map={}, bookings=[['path_bytes'], ['ram_bytes']], external=[], self_ids=[], modules={})
a = {'path_bytes': 412, 'ram_bytes': 8 * 2**30}
for label, b in (('int -> False', {'path_bytes': False, 'ram_bytes': 8 * 2**30}),
                 ('int -> -1 (sentinel)', {'path_bytes': 412, 'ram_bytes': -1})):
    try:
        print('booking %-22s -> %s' % (label, P.check_records(a, b, m)['status']))
    except P.ParityError as e:
        print('booking %-22s -> FAIL %s' % (label, e))

m0 = dict(m, bookings=[])
for leak in ('\\\\fileserver\\share\\LOCAL_USER\\helpers\\tree_r1.py', '\\\\wsl$\\Ubuntu\\home\\LOCAL_USER\\x.py',
             '~/w/composed-r2/helpers/tree_r1.py', '..\\..\\users\\LOCAL_USER\\x.py', '%USERPROFILE%\\x.py'):
    rec = {'note': leak, leak: 1}
    print('user path %-48r found=%-5s check_records -> %s' % (leak, bool(P.user_paths(rec)),
                                                              P.check_records(rec, dict(rec), m0)['status']))
