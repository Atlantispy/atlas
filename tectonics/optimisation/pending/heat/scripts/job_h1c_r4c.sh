#!/usr/bin/env bash
# q10 split, part B, FULL symmetric order (coordinator ~15:50: "full ABBA as job r4c ... replaces the reduced q10b";
# job_h1c_r4b.sh is not used). Run: T/q/runq.py run <ticket> -- bash job_h1c_r4c.sh. Starts only if part A
# (job_h1c_r4a.sh) wrote evidence/h1c-r4a/RESULT = PASS, so nothing is timed until every D-b holds.
# Arms: time lw ld3 le3 lf3 lh lh lf3 le3 ld3 lw (each layout once in each half, mirrored, so a steady drift in machine
# load cancels in each step's pair difference), then prof lh (cProfile in the workers, for the next re-profile).
# Per step: lw->ld3 = H1a r3 + H2, ld3->le3 = H1c r3, le3->lf3 = L1 r4, lf3->lh = H5a; lw->lh = the whole stack.
# Measured basis (16 Oct 15:44, evidence/dry-r4a-r1): lw proof arm 119.18 s wall under the r5 observer; time arms run
# without an observer, so 11 arms ~ 22 min.
# Harness ab_heat_r5.py (790be928). Time and prof routes have no measured record, so they gate on the ticket's
# RUNQ_PRED_PEAK_GIB (pred x 1.2 + 2 GiB). check_arms: every arm PASS, no leaks, 6 workers on both calls, no
# fallback.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
A="$HS/evidence/h1c-r4a"
OUT="$HS/evidence/h1c-r4c"
export PYTHONHASHSEED=0
[ "$(cat "$A/RESULT" 2>/dev/null)" = PASS ] || { echo "part A has not passed ($A/RESULT)"; exit 4; }
for L in lw ld3 le3 lf3 lh; do [ -f "$HS/$L/control.json" ] || { echo "layout $L missing"; exit 4; }; done
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 5; }
echo "job_h1c_r4c start $(date +%H:%M:%S)"
ARMS=(time:base:"$HS/lw" time:h12:"$HS/ld3" time:h12c:"$HS/le3" time:h12cl1:"$HS/lf3" time:h5a:"$HS/lh"
      time:h5a:"$HS/lh" time:h12cl1:"$HS/lf3" time:h12c:"$HS/le3" time:h12:"$HS/ld3" time:base:"$HS/lw"
      prof:h5a:"$HS/lh")
"$PY" -B "$HS/scripts/ab_heat_r5.py" run "$OUT" --history "$HS/evidence/h12-r1/summary.json" \
  --history "$A/summary.json" "${ARMS[@]}" || exit $?
s=0
"$PY" -B "$HS/scripts/check_arms.py" "$OUT" "${#ARMS[@]}" > "$OUT/check-arms.txt" || s=1
tail -n 1 "$OUT"/check-arms.txt
echo "job_h1c_r4c end $(date +%H:%M:%S) exit $s"
exit $s
