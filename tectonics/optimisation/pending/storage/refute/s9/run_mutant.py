import os, sys, unittest
C = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/compact-geometry-r1'
S = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/s9'
sys.path[:0] = [sys.argv[1], C, S]
suite = unittest.defaultTestLoader.loadTestsFromNames(['test_s9_seal_reuse'])
r = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, 'w')).run(suite)
import private_heat_indexed_runtime as P
where = os.path.basename(os.path.dirname(P.__file__))
print(os.path.basename(sys.argv[1]), 'loaded', where, 'ran', r.testsRun,
      'fail', [t.id().rsplit('.', 1)[-1] for t, _ in r.failures + r.errors])
