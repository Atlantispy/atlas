#!/usr/bin/env bash
# Item 7's before and after on the same input (16 Oct 2026). Route (1)'s admission on composed-r2:
# - miss arm: a fresh measurement store, so every initial query is computed;
# - hit arm: run A's closed s2 store seeded, so every query is read back; a hit re-checks each stored
#   field's consistency with the request (it does not certify the geometry again).
# FAIL CLOSED (coordinator, 16 Oct 13:10). time_admission_parts.py exits non-zero unless every check
# is True, a missing field counting as a failure:
# - both arms: final store SHA-256 = PIN (e337fc20), no sidecars, workflow_id and published-root
#   preparation_ids equal to run A's run.json (the spatial owner ID hashes initial_bounds_id and
#   initial_mesh_id, and each arm checks its owner definition holds its own bounds_id/geometry_id);
# - hit arm: store byte-unchanged from the seed, seed source unchanged, and every identity
#   (bounds.bounds_id, mesh.geometry_id, ...), workflow_id, preparation_ids and the store SHA equal to
#   the miss arm's report, over the union of both reports' keys; the miss report must have passed.
# The hit arm runs only if the miss arm passed; this script exits with the failing arm's status.
# Each arm is single-threaded, peak working set about 0.35 GiB (adm1).
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
H="$T/fidelity-integration-20261005/heat-repair-20261007"
P="$T/.r44-env/Scripts/python.exe"
PIN="e337fc205071fc6754b47b18f1c990fbfaec2162ae55cc3a1210cdbc9872ce81"
SEED="$R/s2/attempt-1/run-root/initial-measurements.sqlite@$PIN"
RUN_A="$R/s2/attempt-1/run-root/run.json"
ROOTS=("$R/composed-r2/src" "$R/composed-r2/helpers" "$H/source/tectonics/tests")
export PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
log="$S/item7-arms.log"
date '+=== start %H:%M:%S (fail-closed r2)' >> "$log"
"$P" -B "$S/time_admission_parts.py" "--expect-store=$PIN" "--expect-run=$RUN_A" "$R/L/adm7m" \
    "${ROOTS[@]}" >> "$log" 2>&1
miss=$?
echo "=== miss exit $miss $(date '+%H:%M:%S')" >> "$log"
if [ "$miss" -ne 0 ]; then
    echo "=== FAILED: miss arm exit $miss; hit arm not run" >> "$log"
    grep -E "^===|phase_equivalent|FAILED" "$log" | tail -8
    exit "$miss"
fi
"$P" -B "$S/time_admission_parts.py" "--seed-store=$SEED" "--expect=$R/L/adm7m/report.json" \
    "--expect-store=$PIN" "--expect-run=$RUN_A" "$R/L/adm7h" "${ROOTS[@]}" >> "$log" 2>&1
hit=$?
echo "=== hit exit $hit $(date '+%H:%M:%S')" >> "$log"
if [ "$hit" -eq 0 ]; then
    echo "=== PASSED: both arms, every check True" >> "$log"
else
    echo "=== FAILED: hit arm exit $hit" >> "$log"
fi
grep -E "^===|phase_equivalent|FAILED" "$log" | tail -8
exit "$hit"
