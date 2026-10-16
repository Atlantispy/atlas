#!/bin/bash
# S2 r9: base / r9 / wiring runs, mutants, then R's own driver tests (all classes) base vs r8.
# Roots come from this file's place (T/so/s2/r9-check); the wiring checks reuse r8-check/drivers (unchanged).
S=$(cd "$(dirname "$0")/.." && pwd -W)
T=$(cd "$S/../.." && pwd -W)
P=$T/.r44-env/Scripts/python.exe
R=$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1
export PYTHONHASHSEED=0
cd $S/r9-check
$P -B -c "import sys; sys.exit(sys.flags.hash_randomization != 0)" || { echo "refusing: the string-hash seed is not 0"; exit 3; }
G="^(Ran|OK|FAILED|FAIL:|ERROR:)"
echo "== base (s2/base: CRP/LG before S2)"; $P -B run_tests_r9.py "$S/base" test_step8_coverage test_ledger_fresh_interval 2>&1 | grep -E "$G"
echo "== r9"; $P -B run_tests_r9.py "$S/r9" test_step8_coverage test_ledger_fresh_interval test_wp16_preadvance test_s2_route_wiring.CheckerTests 2>&1 | grep -E "$G|^loaded (compact_restart_patch|ledger)"
echo "== DriverTests on R drivers (expected: FAIL 3)"; $P -B run_tests_r9.py "$R;$S/r9" test_s2_route_wiring.DriverTests 2>&1 | grep -E "$G"
echo "== DriverTests on r8-check/drivers (expected: OK 3)"; $P -B run_tests_r9.py "$S/r8-check/drivers;$S/r9" test_s2_route_wiring.DriverTests 2>&1 | grep -E "$G"
echo "== DriverTests on r8-check/drivers-no-successor, the r7 placement (expected: FAIL 1, the successor)"; $P -B run_tests_r9.py "$S/r8-check/drivers-no-successor;$S/r9" test_s2_route_wiring.DriverTests 2>&1 | grep -E "$G"
echo "== mutants (each must FAIL)"
for m in $S/r9-check/mutants/*/; do
  name=$(basename $m)
  out=$($P -B run_tests_r9.py "$m" test_step8_coverage test_ledger_fresh_interval test_wp16_preadvance 2>&1); rc=$?
  loaded=$(echo "$out" | grep -c "loaded .*mutants.$name")
  why=$(echo "$out" | grep -E '^(FAIL|ERROR):' | sed 's/ (test_[a-z0-9_]*\.[A-Za-z]*)//' | tr '\n' ';' | cut -c1-160)
  if [ $rc -ne 0 ]; then echo "KILLED $name loaded-from-mutant=$loaded :: $why"; else echo "SURVIVED $name loaded-from-mutant=$loaded"; fi
done
echo "== R driver tests: base, r9"
for v in base r9; do
  $P -B -P $S/r9-check/drv/drivers_r9.py fresh $v 2>&1 | tail -12
  $P -B -P $S/r9-check/drv/drivers_r9.py prepared $v 2>&1 | tail -12
done
