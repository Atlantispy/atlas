#!/usr/bin/env bash
# H3 r2 on the genuine W4 call, ONE queue ticket: T/q/runq.py run qNN -- bash job_h3r2.sh <tag> [6|4]
# ARMS 6 (default, as reviewed): proof h2, proof h3, time h2,h3,h3,h2. ARMS 4: proof h2, proof h3,
# time h3, time h2 (ABBA over 4 arms; the proof observer is parent-only, recon runs in the 6 workers).
# Each arm is the whole W4 control: q03 measured 1,171 s / 1,304 s per arm, tree 1.03 GiB.
# 1. W4 call on h13l1 (production r1 kernels) with the read-only worker input capture
#    (capture/sitecustomize.py, sys.monitoring) -> T/ck/<tag>-cap. Inputs for the offline per-call
#    r1/H2/H3 replay; not timed and not a proof.
# 2. ab_heat_r5.py (T/hs, read-only; r2's sys.monitoring proof observer, coordinator 16 Oct: no setprofile
#    in long arms; r5 = r2 + per-arm predicted start gate, Michael 14:05/14:08: no l2/l3 history, so each
#    route's first arm gates on the ticket's RUNQ_PRED_PEAK_GIB x 1.2 + 2 GiB, and refuses without it):
#    proof:h2 on T/ck/l2 (the baseline, same run and code it is compared with: q03's
#    arm 2 never ran), proof:h3 on T/ck/l3, then time h2,h3,h3,h2 (l2 == T/hs/ld, l3 = l2 + H3).
#    Every arm starts fresh processes, so each timing arm pays numba's import and compilation in
#    every worker. No PYTHONPATH here (the harness's leak check stays meaningful).
# 3. check_arms.py OUT 6 (all PASS, no leaks, 6 workers on both heat calls, no serial fallback) and
#    compare_ab_r2.py: my h2 proof arm (arm-0) vs my h3 proof arm (arm-1), D-b, roots W(l2) W(l3)
#    (arguments proven on q03's real pair + mutants: T/ck/q06p2/proof.json, 21/21).
# 4. Route record: h3_status() of l3's kernel in a fresh process of the same interpreter.
# Heat's three scripts are pinned to the reviewed digests (children re-read ab_heat_r5.py per arm),
# and they and l2/l3 must be byte-unchanged at the end; otherwise exit 1.
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
CK="$T/ck"
TAG=$1
ARMS=${2:-6}
OUT="$CK/$TAG"
W() { cygpath -w "$1"; }
export PYTHONHASHSEED=0
unset PYTHONPATH CK_CAPTURE_DIR
s=0
[ -e "$OUT" ] && { echo "$OUT exists"; exit 2; }
case "$ARMS" in
  6) SPECS=(time:h2:"$CK/l2" time:h3:"$CK/l3" time:h3:"$CK/l3" time:h2:"$CK/l2");;
  4) SPECS=(time:h3:"$CK/l3" time:h2:"$CK/l2");;
  *) echo "ARMS must be 6 or 4"; exit 2;;
esac
HSS="$T/hs/scripts"
cat > "$CK/$TAG-pins.sha256" <<EOF
790be9283501d49b15dcea9cf64ac60641532691d4a58ca67fbbdb74e37e807a *$HSS/ab_heat_r5.py
f67dbb662b66fc0c8559a5df7f92c3f8789210fbe4cf3892a57f7bdb26f5e7da *$HSS/compare_ab_r2.py
b8e7fe7f29ee50c49886b0dba125760678311381a17cf3c3e09a64be85587139 *$HSS/check_arms.py
EOF
sha256sum -c --quiet "$CK/$TAG-pins.sha256" || { echo "FAIL: Heat's harness differs from the reviewed pins"; exit 2; }
frozen () { (cd "$CK" && find l2 l3 -type f ! -name '*.pyc' -print0 | sort -z | xargs -0 sha256sum); }
frozen > "$CK/$TAG-frozen-start.sha256"

mkdir -p "$CK/$TAG-cap"
(
  export CK_CAPTURE_DIR="$CK/$TAG-cap" PYTHONPATH="$CK/capture"
  cd "$G/scripts" && "$PY" -B profile_w4_heat.py --layout C:/Users/LOCAL_USER/h13l1 --output-dir "$CK/$TAG-w4" --no-profile
) > "$CK/$TAG-capture.log" 2>&1
c=$?
echo "$(date +%H:%M:%S) capture exit $c, files $(ls "$CK/$TAG-cap" | wc -l)"
[ $c = 0 ] || s=1

echo "$(date +%H:%M:%S) arms start"
"$PY" -B "$HSS/ab_heat_r5.py" run "$OUT" proof:h2:"$CK/l2" proof:h3:"$CK/l3" "${SPECS[@]}" || exit 2
echo "$(date +%H:%M:%S) arms end"

"$PY" -B "$HSS/check_arms.py" "$OUT" "$ARMS" > "$OUT/check-arms.txt"
c=$?
echo "check_arms exit $c: $(tail -n 1 "$OUT/check-arms.txt")"
[ $c = 0 ] || s=1
"$PY" -B "$HSS/compare_ab_r2.py" "$OUT/arm-0" "$OUT/arm-1" "$(W "$CK/l2")" "$(W "$CK/l3")" > "$OUT/compare-h2-h3.txt"
c=$?
echo "compare exit $c: $(tail -n 1 "$OUT/compare-h2-h3.txt")"
[ $c = 0 ] || s=1

"$PY" -B -I -c "
import json, sys
sys.path[:0] = [sys.argv[2]+'/runtime-src', sys.argv[2]+'/helpers']
import private_heat_certification_kernel_r1 as kernel
json.dump(dict(kernel=kernel.__file__, h3=kernel.h3_status()), open(sys.argv[1], 'w'), indent=1, default=str)
" "$OUT/h3-route.json" "$CK/l3" || s=1
echo "route: $(tr -d '\n ' < "$OUT/h3-route.json" | cut -c1-160)"
sha256sum -c --quiet "$CK/$TAG-pins.sha256" || { echo "FAIL: Heat's harness changed during the run"; s=1; }
frozen > "$CK/$TAG-frozen-end.sha256"
cmp -s "$CK/$TAG-frozen-start.sha256" "$CK/$TAG-frozen-end.sha256" || { echo "FAIL: l2/l3 changed during the run"; s=1; }
echo "$(date +%H:%M:%S) end exit $s"
exit $s
