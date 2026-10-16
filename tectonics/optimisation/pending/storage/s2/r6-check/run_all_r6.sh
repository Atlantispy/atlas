#!/bin/bash
# S2 r6: base / r6 / driver-wiring runs, mutants, then R's own driver tests (all classes) base vs patched.
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
S=$T/so/s2
R=$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1
export PYTHONHASHSEED=0
cd $S/r6-check
set -e
# build_s2_r6.py ran at 15:35 (s2/build-r6.log).
$P -B $S/r6-check/make_mutants_r6.py | tail -1
set +e
echo "== base (s2/base: CRP/LG before S2)"; $P -B run_tests_r6.py "$S/base" test_step8_coverage test_ledger_fresh_interval 2>&1 | grep -E "^(Ran|OK|FAILED)"
echo "== r6"; $P -B run_tests_r6.py "$S/r6" test_step8_coverage test_ledger_fresh_interval test_wp16_preadvance test_s2_route_wiring.CheckerTests 2>&1 | grep -E "^(Ran|OK|FAILED|FAIL:|ERROR:|loaded (compact_restart_patch|ledger))"
echo "== DriverTests on R drivers (expected: FAIL 2)"; $P -B run_tests_r6.py "$R;$S/r6" test_s2_route_wiring.DriverTests 2>&1 | grep -E "^(Ran|OK|FAILED)"
echo "== DriverTests on r5-check/drivers (expected: OK 2)"; $P -B run_tests_r6.py "$S/r5-check/drivers;$S/r6" test_s2_route_wiring.DriverTests 2>&1 | grep -E "^(Ran|OK|FAILED)"
echo "== mutants (each must FAIL)"
for m in $S/r6-check/mutants/*/; do
  name=$(basename $m)
  out=$($P -B run_tests_r6.py "$m" test_step8_coverage test_ledger_fresh_interval test_wp16_preadvance 2>&1); rc=$?
  loaded=$(echo "$out" | grep -c "loaded .*mutants.$name")
  why=$(echo "$out" | grep -E '^(FAIL|ERROR):' | sed 's/ (test_[a-z0-9_]*\.[A-Za-z]*)//' | tr '\n' ';' | cut -c1-160)
  if [ $rc -ne 0 ]; then echo "KILLED $name loaded-from-mutant=$loaded :: $why"; else echo "SURVIVED $name loaded-from-mutant=$loaded"; fi
done
echo "== R driver tests: base, r5 (control: the P2), r6"
for v in base r5 r6; do
  $P -B -P $S/r6-check/drv/drivers_r6.py fresh $v 2>&1 | tail -12
  $P -B -P $S/r6-check/drv/drivers_r6.py prepared $v 2>&1 | tail -12
done
