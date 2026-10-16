import json, sys
if sys.flags.hash_randomization:
    raise SystemExit('set PYTHONHASHSEED=0')
sys.path[:0] = [sys.argv[2]+'/runtime-src', sys.argv[2]+'/helpers']
import private_heat_certification_kernel_r1 as kernel
json.dump(dict(kernel=kernel.__file__, h3=kernel.h3_status()), open(sys.argv[1], 'w'), indent=1, default=str)
