"""Check that fuzz_targeted's scenarios are sensitive: each mutant must be caught."""
import random

import common
import fuzz_targeted as F

MUTANTS = {
    'store-before-overflow-check': (
        "            if total > sys.maxsize:\n"
        "                raise OverflowError('Exact scalar envelope exceeds addressable storage')\n"
        "            self._envelope = ((peak, slots, containers, total)\n"
        "                              if type(peak) is int and type(slots) is int and type(containers) is int else None)\n",
        "            self._envelope = ((peak, slots, containers, total)\n"
        "                              if type(peak) is int and type(slots) is int and type(containers) is int else None)\n"
        "            if total > sys.maxsize:\n"
        "                raise OverflowError('Exact scalar envelope exceeds addressable storage')\n"),
    'ignore-containers-identity': (
        "                and envelope[2] is containers):", "                and True):"),
    'add-without-carry': (
        "width = max(max(p+t, s+r)+1, r+t)", "width = max(max(p+t, s+r), r+t)"),
    'skip-lease-check-on-hit': (
        "            total = envelope[3]\n",
        "            total = envelope[3]\n            self.peak_bits = peak\n            return\n"),
}

for name, (old, new) in MUTANTS.items():
    assert common.AFTER_C.count(old) == 1, name
    mutant = common.load('mutant_'+name.replace('-', '_'), common.AFTER_C.replace(old, new))
    caught = []
    for seed in range(40):
        for scen, off in (('identity', 0), ('reentrant', 1000), ('subclasses', 2000)):
            fn = getattr(F, 'scenario_'+scen)
            if fn(random.Random(off+seed), common.OLD) != fn(random.Random(off+seed), mutant):
                caught.append((scen, seed))
    for scen in ('bounds', 'refusal', 'operations', 'order'):
        fn = getattr(F, 'scenario_'+scen)
        if fn(common.OLD) != fn(mutant):
            caught.append(scen)
    print('%-30s caught by %d scenario runs, e.g. %s' % (name, len(caught), caught[:4]))

steps = sum(len(F.scenario_identity(random.Random(s), common.NEW)) for s in range(40))
raises = sum(1 for s in range(40) for r in F.scenario_identity(random.Random(s), common.NEW)
             if isinstance(r, tuple) and r and r[0] == 'raise')
print('identity scenario entries:', steps, 'raises:', raises, 'order entries:', len(F.scenario_order(common.NEW)))
