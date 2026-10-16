"""Quick subset of harness_sanity.py (2 seeds) - run directly, ~1 s CPU."""
import random
import time

import common
import fuzz_targeted as F
from harness_sanity_mutants import MUTANTS

t = time.process_time()
for name, (old, new) in MUTANTS.items():
    mutant = common.load('mutant_'+name.replace('-', '_'), common.AFTER_C.replace(old, new))
    caught = []
    for seed in range(2):
        for scen, off in (('identity', 0), ('reentrant', 1000)):
            fn = getattr(F, 'scenario_'+scen)
            if fn(random.Random(off+seed), common.OLD) != fn(random.Random(off+seed), mutant):
                caught.append((scen, seed))
    for scen in ('bounds', 'refusal', 'operations'):
        fn = getattr(F, 'scenario_'+scen)
        if fn(common.OLD) != fn(mutant):
            caught.append(scen)
    print('%-30s caught: %s' % (name, caught))
print('cpu s', round(time.process_time()-t, 2))
