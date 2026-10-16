#!/usr/bin/env bash
# D1 incidence_constant + D2 rotated_hoist, stacked with the kernel twin G-PY r4 (D-b): field-by-field
# parity with only source-digest fields allowed to differ. PYTHONHASHSEED=0. One arm at a time, 6 processes.
# The stages, inputs, pins and fail-closed checks are those of run_jets_parity.sh (310cdf70); only the arms differ:
#  1. IV1 surfaces, all: RC1+q2fast+jetsfast (gg/jets-r1) vs the same + d1det + d2rot + gpy4 (gg/d12g-iv1).
#  2. IV2 candidate 1-in-10 sample (cap 2 s): candidate f2 (gg/final-f2) vs f2 + d1det + d2rot + gpy4 (gg/d12g-iv2).
#  3. IV2 candidate deep set (every candidate-capped sample interface, cap 120 s): same two arms.
# Before any run, check_composition.py compares each runtime folder with its manifest, byte for byte, and
# pins the two moment files (the test: loader itself compares nothing).
# Usage: run_d12_parity.sh <new evidence folder name, e.g. d12-r1>
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
F="$G/evidence/final-f1"
[ $# -eq 1 ] && [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$ ]] || { echo "usage: run_d12_parity.sh <new evidence folder name>"; exit 2; }
OUT="$G/evidence/$1"
[ -e "$OUT" ] && { echo "exists: $OUT (never rewritten)"; exit 2; }
"$PY" -B -I -c "import os,sys; sys.exit(1 if os.path.lexists(sys.argv[1]) else 0)" "$OUT" || { echo "exists to Windows: $OUT (never rewritten)"; exit 2; }
REFS=$(ls "$F"/ref-iv2-surfaces-s*.jsonl 2>/dev/null | paste -sd, -)
[ -n "$REFS" ] || { echo "no reference shards in $F"; exit 2; }
for f in "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.grid.json.gz" "$G/work/iv1-interval-r1.json.gz" \
         "$F/iv2-supports.jsonl.gz" "$F/iv2-partition.grid.json.gz" "$G/work/iv2-interval-only-r1.json.gz" \
         "$F"/capped-list-{0,1,2,3,4,5}.jsonl; do
  [ -s "$f" ] || { echo "missing or empty input $f"; exit 2; }
done
EXPECT_IV1=40968; EXPECT_SAMPLE=901; EXPECT_DEEP=216
CAPPED_SHA=1981300315d474de6aa88fff0d82d9bc0e728c9b060f302312d0b426722f8373   # lists 0..5 concatenated
got=$(cat "$F"/capped-list-{0,1,2,3,4,5}.jsonl | sha256sum | cut -c1-64)
[ "$got" = "$CAPPED_SHA" ] || { echo "capped lists are $got, not the pinned $CAPPED_SHA"; exit 2; }
# Runtime pre-flight: base arms carry jetsfast's MFM and RC1's MIM; candidate arms carry gpy4's MFM and d1det's MIM.
MFM=atlas_tectonics/integration_moving_face_moments.py; MIM=atlas_tectonics/integration_moving_interface_moments.py
BASE_PINS=("$MFM=c5f2a1230f9e13633ad92f9a251ee01e08bac0b2905d9fed90c042402adb8075" "$MIM=23fb1565e2d1d11e9d29835ad99e4ca63a24af53843149f47dd01f8357906c9b")
CAND_PINS=("$MFM=52f8cc158657302e15f08e8fae8d3be5f1ec505f1fe311b176a58cdf24421f44" "$MIM=4f7d224f03e224f4819c9f741f583fbc49f00c2d92186c9d2885203b96eff4da")
for d in jets-r1 final-f2; do "$PY" -B -I "$G/scripts/check_composition.py" "$T/gg/$d" "${BASE_PINS[@]}" || exit 2; done
for d in d12g-iv1 d12g-iv2; do "$PY" -B -I "$G/scripts/check_composition.py" "$T/gg/$d" "${CAND_PINS[@]}" || exit 2; done
mkdir "$OUT" || exit 2
L="$OUT/inputs"
mkdir "$L" && cp "$F"/capped-list-{0,1,2,3,4,5}.jsonl "$L"/ || exit 2
got=$(cat "$L"/capped-list-{0,1,2,3,4,5}.jsonl | sha256sum | cut -c1-64)
[ "$got" = "$CAPPED_SHA" ] || { echo "copied capped lists are $got, not the pinned $CAPPED_SHA"; exit 2; }
LISTS="$L/capped-list-0.jsonl,$L/capped-list-1.jsonl,$L/capped-list-2.jsonl,$L/capped-list-3.jsonl,$L/capped-list-4.jsonl,$L/capped-list-5.jsonl"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
RT_IV1_BASE="test:$T/gg/jets-r1"; RT_IV1_CAND="test:$T/gg/d12g-iv1"
RT_IV2_BASE="test:$T/gg/final-f2"; RT_IV2_CAND="test:$T/gg/d12g-iv2"
failed=0
cd "$G/scripts"
waitall () {  # tag pid shard pid shard ...: record each shard's own exit code
  local tag=$1; shift
  while [ $# -ge 2 ]; do
    wait "$1"; echo $? > "$OUT/$tag-s$2.exit"; shift 2
  done
}
run6 () {  # tag runtime supports partition interval width cap shards shardlist... -- extra
  local tag=$1 rt=$2 sup=$3 part=$4 iv=$5 w=$6 cap=$7 n=$8; shift 8; local list=() extra=() seen=0
  for x in "$@"; do if [ "$x" = "--" ]; then seen=1; elif [ $seen = 0 ]; then list+=("$x"); else extra+=("$x"); fi; done
  local pairs=()
  for i in "${list[@]}"; do
    local more=()
    [ ${#extra[@]} -gt 0 ] && more=("${extra[@]//@I@/$i}")
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$sup" --partition "$part" --interval "$iv" --stream-width $w \
      --runtime "$rt" --cap-cpu "$cap" --shard $i --shards "$n" --output "$OUT/$tag-s$i.jsonl" "${more[@]}" > "$OUT/$tag-s$i.log" 2>&1 &
    pairs+=($! "$i")
  done
  waitall "$tag" "${pairs[@]}"
  echo "done $tag $(date +%H:%M:%S)"
}
check () {  # stage shards base_rt cand_rt expected_rows cap_rule
  "$PY" -B -I surfaces_stage_check.py "$OUT" "$1" "$2" base "$3" cand "$4" "$5" "$6"
  local s=$?; echo "$1 check exit $s"; [ $s = 0 ] || failed=1
}
echo "start $(date +%H:%M:%S)"
for arm in base cand; do
  rt=$RT_IV1_BASE; [ $arm = cand ] && rt=$RT_IV1_CAND
  run6 iv1-surfaces-$arm "$rt" "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.grid.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" 60 6 0 1 2 3 4 5
done
check iv1-surfaces 0,1,2,3,4,5 "$RT_IV1_BASE" "$RT_IV1_CAND" "$EXPECT_IV1" none
for arm in base cand; do
  rt=$RT_IV2_BASE; [ $arm = cand ] && rt=$RT_IV2_CAND
  run6 iv2-sample-$arm "$rt" "$F/iv2-supports.jsonl.gz" "$F/iv2-partition.grid.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" 2 60 0 10 20 30 40 50 -- --only-cells-from "$REFS"
done
check iv2-sample 0,10,20,30,40,50 "$RT_IV2_BASE" "$RT_IV2_CAND" "$EXPECT_SAMPLE" "list:$LISTS"
for arm in base cand; do
  rt=$RT_IV2_BASE; [ $arm = cand ] && rt=$RT_IV2_CAND
  pairs=()
  for i in 0 1 2 3 4 5; do
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.grid.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "$rt" --cap-cpu 120 --kinds interface \
      --only-list "$L/capped-list-$i.jsonl" --output "$OUT/iv2-deep-$arm-s$i.jsonl" > "$OUT/iv2-deep-$arm-s$i.log" 2>&1 &
    pairs+=($! "$i")
  done
  waitall "iv2-deep-$arm" "${pairs[@]}"
  echo "done iv2-deep-$arm $(date +%H:%M:%S)"
done
check iv2-deep 0,1,2,3,4,5 "$RT_IV2_BASE" "$RT_IV2_CAND" "$EXPECT_DEEP" "exactly:$LISTS"
echo "end $(date +%H:%M:%S)"
if [ $failed = 0 ]; then echo "D12 PARITY PASSED"; exit 0; fi
echo "D12 PARITY FAILED"; exit 1
