#!/usr/bin/env bash
# G-PY r2 re-check (16 Oct): refuter reproducer + fuzz (2 seeds), 300-case identity/timing, zero identity
# + pickle bytes (r2 must pass; r1 copy must fail = the check sees the difference). 1 core, sequential.
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"; CK="$T/ck"; PY="$T/.r44-env/Scripts/python.exe"
ROOT="$T/gg/final-f2"; NEW="$CK/gpy-f2/atlas_tectonics/integration_moving_face_moments.py"; O="$CK/gpy-r2-check"
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
"$PY" -B -I "$CK/proto/check_gpy_identity.py" "$ROOT" "$NEW" > "$O/identity-r2.log" 2>&1 || s=1
echo "identity r2 (want exit 0): $(tail -n 1 "$O/identity-r2.log")"
"$PY" -B -I "$CK/proto/check_gpy_identity.py" "$ROOT" "$O/r1_moving_face.py" > "$O/identity-r1.log" 2>&1 && { echo "identity r1 PASSED: check is blind"; s=1; }
echo "identity r1 (want exit 1): $(tail -n 1 "$O/identity-r1.log")"
echo "end exit $s"
exit $s
