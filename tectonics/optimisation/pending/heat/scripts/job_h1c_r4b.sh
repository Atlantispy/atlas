#!/usr/bin/env bash
# q10 split, part B (16 Oct ~15:45): timing and the worker profile. Run: T/q/runq.py run <ticket> -- bash
# job_h1c_r4b.sh. Starts only if part A (job_h1c_r4a.sh) wrote evidence/h1c-r4a/RESULT = PASS, so nothing is
# timed until every D-b holds.
# Reduced timing (proposed ~15:45, under 2 h): time lw lh lh lw (symmetric), then prof lh. It measures the total
# of H1a r3 + H2 + H1c r3 + L1 r4 + H5a against the base on the genuine W4 call. Per-step timing comes from part A's
# proof arms: one sample per layout (legacy_s, compact_s, recon_s). Their sys.monitoring observer turns each
# return site off after its first return, so its overhead is negligible; one sample is still noisy.
# The full symmetric order (10 time arms + prof) is about 4 h at the measured 1,304 s per arm; that would be a
# separate decision.
# Harness ab_heat_r5.py (790be928). Time and prof routes have no measured record, so they gate on the ticket's
# RUNQ_PRED_PEAK_GIB (pred x 1.2 + 2 GiB). check_arms: every arm PASS, no leaks, 6 workers on both calls, no
# fallback.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
A="$HS/evidence/h1c-r4a"
OUT="$HS/evidence/h1c-r4b"
export PYTHONHASHSEED=0
[ "$(cat "$A/RESULT" 2>/dev/null)" = PASS ] || { echo "part A has not passed ($A/RESULT)"; exit 4; }
for L in lw lh; do [ -f "$HS/$L/control.json" ] || { echo "layout $L missing"; exit 4; }; done
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 5; }
echo "job_h1c_r4b start $(date +%H:%M:%S)"
ARMS=(time:base:"$HS/lw" time:h5a:"$HS/lh" time:h5a:"$HS/lh" time:base:"$HS/lw" prof:h5a:"$HS/lh")
"$PY" -B "$HS/scripts/ab_heat_r5.py" run "$OUT" --history "$HS/evidence/h12-r1/summary.json" \
  --history "$A/summary.json" "${ARMS[@]}" || exit $?
s=0
"$PY" -B "$HS/scripts/check_arms.py" "$OUT" "${#ARMS[@]}" > "$OUT/check-arms.txt" || s=1
tail -n 1 "$OUT"/check-arms.txt
echo "job_h1c_r4b end $(date +%H:%M:%S) exit $s"
exit $s
