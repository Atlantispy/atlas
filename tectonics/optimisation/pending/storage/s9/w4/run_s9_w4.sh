#!/usr/bin/env bash
# S9 before/after on the W4 same-call heat control (Runner's heat_control_on_frozen.py child, unchanged).
# Layouts (prepared by heat_control_on_frozen.py prepare, read-only here):
#   base = composed-r2/src + composed-r2/helpers (private_heat_indexed_runtime 997277d8)
#   cand = T/so/s9/w4/cand-src first (the S9 runtime ec170fc4 only), then the same composed-r2 helpers
# Usage: run_s9_w4.sh OUTDIR ARM [ARM ...]    ARM is base or cand; give a symmetric order (base cand cand base).
# OUTDIR must not exist. One fresh child process an arm, one at a time (about 85 s and 1.7 GB each with
# the default six heat workers). Each child must PASS its own frozen check against the reviewed reference
# and save its arrays; summarise_s9_w4.py then fails closed unless every arm agrees and the cand arms ran
# the S9 file. Exit 0 only if every arm and the summary pass.
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
REF="$R/probes/step8/claude-20261015/g13-same-call-live1.json"
W="$T/so/s9/w4"
P="$T/.r44-env/Scripts/python.exe"
out=${1:?OUTDIR}; shift
[ "$#" -ge 1 ] || { echo "give at least one arm"; exit 2; }
for arm in "$@"; do
    case "$arm" in base|cand) ;; *) echo "bad arm: $arm"; exit 2 ;; esac
done
[ -e "$out" ] && { echo "the output exists: $out"; exit 2; }
mkdir -p "$out" || exit 2
export PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
fail=0; k=0
for arm in "$@"; do
    k=$((k+1))
    echo "=== $k $arm start $(date '+%H:%M:%S')"
    "$P" -B "$S/heat_control_on_frozen.py" child "$W/$arm" "$out/$k-$arm.json" "$REF" "$out/$k-$arm" \
        > "$out/$k-$arm.log" 2>&1
    code=$?
    echo "=== $k $arm exit $code $(date '+%H:%M:%S')"
    [ "$code" -ne 0 ] && fail=1
done
"$P" -B "$W/summarise_s9_w4.py" "$out" "$W" "$REF" "$@" || fail=1
echo "=== done exit $fail $(date '+%H:%M:%S')"
exit $fail
