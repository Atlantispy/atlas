#!/usr/bin/env bash
# The frozen heat control's third criterion (Coordinator D-l, 16 Oct 2026): re-run the W4
# same-call heat control on four routes, saving each r13 result's arrays and each cell's keys
# (heat_control_on_frozen.py child ... SAVE_DIR), then match cells by logical_cell_id
# (primary, required) and by cell_id (contrast, reported) with check_cell_keys.py. One run at a
# time, each about 85 s and 1.7 GB with the default six heat workers (under the 2 GiB heavy-run threshold).
#
# Usage: bash run_cell_keys.sh [OUT [ROUTE ...]]
#   OUT defaults to R/L and the ROUTEs to g13l1 g13l0 d1 r2; the queued ticket uses both defaults.
#   g13l1 must come first: it is the base of the key match and the only route given the reference
#   (D/g13-same-call-live1.json, its own reviewed output: D-l keeps positional digests for
#   same-composition reruns). Outputs: OUT/ck-ROUTE.json, OUT/ck-ROUTE/, OUT/ck-check-KEY.json, OUT/ck-run.log.
#
# FAIL CLOSED (review 16 Oct 2026). Refuses (exit 2, nothing run) unless every input exists, the
# reference has its pinned SHA-256 and no output exists. Then every route runs, even after a failure,
# and the exit is 1 unless every child exits 0 (control PASS, nothing loaded outside its layout, frozen
# inputs unchanged, arrays and keys saved and equal to the control's own digests, and for g13l1 the
# reference arrays), the primary check exits 0 (PASS) and the contrast check exits 0 (valid evidence on
# every route; its verdict is reported, not required). Nothing is overwritten (noclobber, exclusive creation).
set -u
set -C
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
D="$R/probes/step8/claude-20261015"
P="$T/.r44-env/Scripts/python.exe"
REF="$D/g13-same-call-live1.json"
REF_SHA256="2561b092830d005e32f08ef5c7d79de67ccae430a6f3a0bfa00c576ce099ceed"
export PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1

refuse() { echo "=== REFUSED: $*"; exit 2; }
layout_of() {
    case "$1" in
        g13l1) echo "$R/probes/step8/g13l1" ;;
        g13l0) echo "$R/probes/step8/g13l0" ;;
        d1) echo "$R/L/d1" ;;
        r2) echo "$R/composed-checks/hc-r2" ;;
        *) return 1 ;;
    esac
}

OUT="${1:-$R/L}"
if [ "$#" -gt 0 ]; then shift; fi
if [ "$#" -gt 0 ]; then routes=("$@"); else routes=(g13l1 g13l0 d1 r2); fi

[ -d "$OUT" ] || refuse "no output folder $OUT"
[ -f "$P" ] || refuse "no interpreter $P"
for path in "$S/heat_control_on_frozen.py" "$S/check_cell_keys.py" "$REF"; do
    [ -f "$path" ] || refuse "missing $path"
done
got=$(sha256sum "$REF" | cut -c1-64)
[ "$got" = "$REF_SHA256" ] || refuse "reference $REF is $got, pinned $REF_SHA256"
[ "${routes[0]}" = g13l1 ] || refuse "the first route must be g13l1, not ${routes[0]}"
dirs=()
seen=" "
for route in "${routes[@]}"; do
    case "$seen" in *" $route "*) refuse "a route is given twice: ${routes[*]}" ;; esac
    seen="$seen$route "
    layout=$(layout_of "$route") || refuse "unknown route $route"
    [ -f "$layout/control.json" ] || refuse "no layout $layout"
    for path in "$OUT/ck-$route.json" "$OUT/ck-$route"; do
        [ -e "$path" ] && refuse "output exists: $path"
    done
    dirs+=("$OUT/ck-$route")
done
for path in "$OUT/ck-check-logical_cell_id.json" "$OUT/ck-check-cell_id.json" "$OUT/ck-run.log"; do
    [ -e "$path" ] && refuse "output exists: $path"
done
log="$OUT/ck-run.log"
: > "$log" || refuse "cannot create $log"
say() { echo "$*" | tee -a "$log"; }

fail=0
say "=== start $(date '+%H:%M:%S') out=$OUT routes=${routes[*]} reference=$REF sha256=$REF_SHA256"
for route in "${routes[@]}"; do
    layout=$(layout_of "$route")
    reference=-
    [ "$route" = g13l1 ] && reference="$REF"
    began=$(date +%s)
    "$P" -B "$S/heat_control_on_frozen.py" child "$layout" "$OUT/ck-$route.json" "$reference" "$OUT/ck-$route" \
        >> "$log" 2>&1
    code=$?
    [ "$code" -eq 0 ] || fail=1
    say "=== $route exit $code after $(( $(date +%s)-began )) s at $(date '+%H:%M:%S')"
done
"$P" -B "$S/check_cell_keys.py" "${dirs[@]}" --key logical_cell_id --report "$OUT/ck-check-logical_cell_id.json" \
    2>> "$log"
code=$?
[ "$code" -eq 0 ] || fail=1
say "=== check logical_cell_id (primary, required) exit $code at $(date '+%H:%M:%S')"
"$P" -B "$S/check_cell_keys.py" "${dirs[@]}" --key cell_id --contrast --report "$OUT/ck-check-cell_id.json" \
    2>> "$log"
code=$?
[ "$code" -eq 0 ] || fail=1
say "=== check cell_id (contrast, reported) exit $code at $(date '+%H:%M:%S')"
grep '^check_cell_keys:' "$log"
if [ "$fail" -eq 0 ]; then
    say "=== PASSED: every route and both checks"
else
    say "=== FAILED: see $log"
fi
exit "$fail"
