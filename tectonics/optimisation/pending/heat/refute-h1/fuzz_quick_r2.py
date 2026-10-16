"""3-seed subset of fuzz_targeted_r2.py, run directly (well under a few seconds of CPU)."""
import random
import sys
import time

import common_r2
sys.modules['common'] = common_r2
import fuzz_targeted as F  # noqa: E402

t = time.process_time()
for seed in range(3):
    F.check(('identity', seed), [F.scenario_identity(random.Random(seed), m) for m in F.MODS])
    F.check(('reentrant', seed), [F.scenario_reentrant(random.Random(1000+seed), m) for m in F.MODS])
    F.check(('subclasses', seed), [F.scenario_subclasses(random.Random(2000+seed), m) for m in F.MODS])
for name in ('bounds', 'refusal', 'operations', 'order'):
    F.check(name, [getattr(F, 'scenario_'+name)(m) for m in F.MODS])
print('failures:', len(F.FAIL), F.FAIL, 'inline verified:', common_r2.NEW._INLINE_RESOURCES[0] is common_r2.RES,
      'cpu s', round(time.process_time()-t, 2))
