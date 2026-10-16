"""Quick mutant sensitivity of fuzz_targeted's scenarios on the r3 text (2 seeds, ~0.1 s CPU)."""
import random
import sys

import common_r3 as C
sys.modules['common'] = C
import fuzz_targeted as F  # noqa: E402

MUTANTS = {
    'add-without-carry': ('width = max(max(p+t, s+r)+1, r+t)', 'width = max(max(p+t, s+r), r+t)'),
    'hit-skips-lease-check': ('                total = envelope[3]\n',
                              '                total = envelope[3]\n                self.peak_bits = peak\n'
                              '                return\n'),
    'hit-ignores-containers': ('if envelope[1] is slots and envelope[2] is containers:',
                               'if envelope[1] is slots:'),
    'q-int-width-plus-one': ('width = max(1, value.bit_length())\n', 'width = max(1, value.bit_length())+1\n'),
    'mpq-den-dropped': ('p, r = max(1, a.numerator.bit_length()), a.denominator.bit_length()',
                        'p, r = max(1, a.numerator.bit_length()), 1'),
}
for name, (old, new) in MUTANTS.items():
    assert C.AFTER_C.count(old) == 1, name
    mutant = C.load('mut3_'+name.replace('-', '_'), C.AFTER_C.replace(old, new))
    caught = []
    for seed in range(2):
        for scen, off in (('identity', 0), ('reentrant', 1000), ('subclasses', 2000)):
            fn = getattr(F, 'scenario_'+scen)
            if fn(random.Random(off+seed), C.OLD) != fn(random.Random(off+seed), mutant):
                caught.append((scen, seed))
    for scen in ('bounds', 'refusal', 'operations', 'order'):
        if getattr(F, 'scenario_'+scen)(C.OLD) != getattr(F, 'scenario_'+scen)(mutant):
            caught.append(scen)
    print('%-26s caught: %s' % (name, caught))
