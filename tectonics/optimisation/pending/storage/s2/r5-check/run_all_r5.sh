#!/bin/bash
# S2 r5: build, local driver wiring copy, carried tests copied unchanged, then base / r5 / driver-wiring runs and mutants.
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
S=$T/so/s2
R=$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1
export PYTHONHASHSEED=0
cd $S/r5-check
set -e
# build_s2_r5.py, patch_drivers.py and the carried-test copies (5c07cb3b, 69a4dda0) ran at 15:11: r5-check/build-r5.log.
$P -B $S/r5-check/make_mutants_r5.py
set +e
echo "== base (s2/base: CRP/LG before S2)"; $P -B run_tests_r5.py "$S/base" test_step8_coverage test_ledger_fresh_interval 2>&1 | tail -12
echo "== r5"; $P -B run_tests_r5.py "$S/r5" test_step8_coverage test_ledger_fresh_interval test_wp16_preadvance test_s2_route_wiring.CheckerTests 2>&1 | tail -16
echo "== DriverTests on R drivers (expected: FAIL 2)"; $P -B run_tests_r5.py "$R;$S/r5" test_s2_route_wiring.DriverTests 2>&1 | grep -E "^(Ran|OK|FAILED|AssertionError)"
echo "== DriverTests on r5-check/drivers (expected: OK 2)"; $P -B run_tests_r5.py "$S/r5-check/drivers;$S/r5" test_s2_route_wiring.DriverTests 2>&1 | grep -E "^(Ran|OK|FAILED|AssertionError)"
echo "== mutants (each must FAIL)"
for m in $S/r5-check/mutants/*/; do
  name=$(basename $m)
  out=$($P -B run_tests_r5.py "$m" test_step8_coverage test_ledger_fresh_interval test_wp16_preadvance 2>&1); rc=$?
  loaded=$(echo "$out" | grep -c "loaded .*mutants.$name")
  if [ $rc -ne 0 ]; then echo "KILLED $name ($(echo "$out" | grep -E '^FAILED' | head -1)) loaded-from-mutant=$loaded"; else echo "SURVIVED $name loaded-from-mutant=$loaded"; fi
done
