#!/usr/bin/env bash
# G-PY r3 re-check (16 Oct, delta refuter DEFECT A fixed): the r2 check on r3 (refuter r1 reproducer, fuzz 2
# seeds, 300-case identity/timing, zero identity + pickle bytes with r1 as the blind-check control), plus the
# delta refuter's reproducer (r3 must show 0 differing; r2 must show 3 = the reproducer sees the defect) and
# its identity fuzz at two seeds. 1 core, sequential.
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"; CK="$T/ck"; PY="$T/.r44-env/Scripts/python.exe"
ROOT="$T/gg/final-f2"; NEW="$CK/gpy-f2/atlas_tectonics/integration_moving_face_moments.py"; O="$CK/gpy-r3-check"
export PYTHONHASHSEED=0
s=0
sha256sum "$NEW" | cut -c1-12
"$PY" -B -I "$CK/refuter-gpy/repro_nonsequence.py" "$ROOT" "$NEW" > "$O/repro.log" 2>&1; echo "repro exit $? $(tail -n 1 "$O/repro.log")"
for seed in 1 2; do
  "$PY" -B -I "$CK/refuter-gpy/fuzz_gpy.py" "$ROOT" "$NEW" 2000 $seed > "$O/fuzz-$seed.log" 2>&1 || s=1
  echo "fuzz $seed: $(tail -n 1 "$O/fuzz-$seed.log")"
done
"$PY" -B -I "$CK/proto/test_gpy_transform.py" "$ROOT" "$NEW" 300 5 > "$O/test-300.log" 2>&1 || s=1
echo "test-300: $(tail -n 1 "$O/test-300.log")"
"$PY" -B -I "$CK/proto/check_gpy_identity.py" "$ROOT" "$NEW" > "$O/identity-r3.log" 2>&1 || s=1
echo "identity r3 (want exit 0): $(tail -n 1 "$O/identity-r3.log")"
"$PY" -B -I "$CK/proto/check_gpy_identity.py" "$ROOT" "$O/r1_moving_face.py" > "$O/identity-r1.log" 2>&1 && { echo "identity r1 PASSED: check is blind"; s=1; }
echo "identity r1 (want exit 1): $(tail -n 1 "$O/identity-r1.log")"
"$PY" -B -I "$CK/refuter-gpy/r2/repro_zero_replaced.py" "$ROOT" "$NEW" > "$O/zero-r3.log" 2>&1
z3=$(tail -n 1 "$O/zero-r3.log"); echo "zero-replaced r3 (want 0): $z3"
[ "$z3" = "differing cases: 0" ] || s=1
"$PY" -B -I "$CK/refuter-gpy/r2/repro_zero_replaced.py" "$ROOT" "$O/r2_moving_face.py" > "$O/zero-r2.log" 2>&1
z2=$(tail -n 1 "$O/zero-r2.log"); echo "zero-replaced r2 (want 3): $z2"
[ "$z2" = "differing cases: 3" ] || s=1
for seed in 3 4; do
  "$PY" -B -I "$CK/refuter-gpy/r2/fuzz_identity.py" "$ROOT" "$NEW" 3000 $seed > "$O/fuzz-identity-$seed.log" 2>&1 || s=1
  f=$(tail -n 1 "$O/fuzz-identity-$seed.log"); echo "fuzz identity $seed: $f"
  [ "$f" = "cases 3000 differing 0" ] || s=1
done
echo "end exit $s"
exit $s
