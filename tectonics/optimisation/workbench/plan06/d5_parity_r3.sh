#!/usr/bin/env bash
# D5 (T/ck/transforms/d5_wall_hooks.py: GMP-resident twins of the wall-measure kernels) parity, the G-PY
# harness (scripts/gpy_parity.sh r5) with the D5 runtimes: D-b, only source-digest fields may differ.
#  1. IV1 surfaces: jets-r1 vs T/ck/d5-jets (jets-r1 + d5).
#  2. IV2 1-in-10 sample (cap 2 s) and 2b extra rows: final-f2 vs T/ck/d5-f2 (final-f2 + d5).
#  3. IV2 deep set (cap 120 s): the same two arms.
# Judged by the unchanged, proven checker scripts/gpy_parity_check.py (proof r3 41/41), whose candidate arm is
# named gpy: here the gpy files are the D5 arm. Same fail-closed rules, freeze and lists as gpy_parity.sh.
# Usage (clean environment, PYTHONHASHSEED=0): bash d5_parity_r3.sh TAG [full|smoke]
# Optional four tree arguments: IV1_BASE IV1_CAND IV2_BASE IV2_CAND (absolute paths).
# Alternatively set all four D5_IV1_BASE/D5_IV1_CAND/D5_IV2_BASE/D5_IV2_CAND.
# Tree overrides support future test-only compositions; they imply no N9 or scientific acceptance.
#   smoke = one shard per stage, one process at a time (small lane); full = 6 processes (an EXCLUSIVE ticket).
set -uo pipefail
[ "${PYTHONHASHSEED-}" = 0 ] || { echo "PYTHONHASHSEED must already be 0"; exit 2; }
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
MEASURES="$(dirname "$SELF")/parity_measurements.py"
T="${ATLAS_T:?set ATLAS_T to the task root}"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
CK="$T/ck"
F="$G/evidence/final-f1"
TAG="${1:?tag}"; MODE="${2:-full}"
OUT="$CK/d5-parity-r3-$TAG"
[[ "$TAG" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "unsafe tag"; exit 2; }
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
case "$MODE" in
  full)  N1=6;   L1="0 1 2 3 4 5"; N2=60;  L2="0 10 20 30 40 50"; LD="0 1 2 3 4 5";;
  smoke) N1=600; L1="0";           N2=600; L2="0";                LD="0";;
  *) echo "mode must be full or smoke"; exit 2;;
esac
[ -e "$OUT" ] && { echo "$OUT exists"; exit 2; }
if [ "$#" = 6 ]; then
  D1B="$3"; D1G="$4"; D2B="$5"; D2G="$6"
elif [ "$#" -le 2 ]; then
  if [ -n "${D5_IV1_BASE-}${D5_IV1_CAND-}${D5_IV2_BASE-}${D5_IV2_CAND-}" ]; then
    D1B="${D5_IV1_BASE:?all four tree overrides required}"
    D1G="${D5_IV1_CAND:?all four tree overrides required}"
    D2B="${D5_IV2_BASE:?all four tree overrides required}"
    D2G="${D5_IV2_CAND:?all four tree overrides required}"
  else
    D1B="$T/gg/jets-r1"; D1G="$CK/d5-jets-r3"
    D2B="$T/gg/final-f2"; D2G="$CK/d5-f2-r3"
  fi
else
  echo "supply TAG MODE and exactly four tree paths, or no tree paths"; exit 2
fi
for d in "$D1B" "$D1G" "$D2B" "$D2G"; do
  [[ "$d" = /* || "$d" =~ ^[A-Za-z]:/ ]] || { echo "tree must be absolute: $d"; exit 2; }
  [ -f "$d/TEST_COMPOSITION.json" ] || { echo "missing TEST_COMPOSITION.json: $d"; exit 2; }
done
mkdir -p "$OUT" || exit 2
RT1B="test:$D1B"; RT1G="test:$D1G"; RT2B="test:$D2B"; RT2G="test:$D2G"
SAMPLE=("$F"/ref-iv2-surfaces-s*.jsonl)
SAMPLEC=$(IFS=,; echo "${SAMPLE[*]}")
DEEP=()
for i in $LD; do DEEP+=("$F/capped-list-$i.jsonl"); done
# Smoke deep row: capped-list-0 line 2, not line 1. The 1/600 sample's only capped row (s2) is line 1's, so
# with line 2 it is off the deep list and goes through stage 2b: the smoke runs every stage.
if [ "$MODE" = smoke ]; then sed -n 2p "$F/capped-list-0.jsonl" > "$OUT/smoke-list-0.jsonl"; DEEP=("$OUT/smoke-list-0.jsonl"); fi
DEEPC=$(IFS=,; echo "${DEEP[*]}")
frozen () {
  sha256sum "$SELF" "$MEASURES" "$CK/scripts/gpy_parity_check.py" "$CK/scripts/run1.py" \
    "$G/scripts/replay_surfaces.py" "$G/scripts/compare_surfaces.py" "$G/scripts/rc1_env.py" \
    "${DEEP[@]}" "${SAMPLE[@]}" \
    "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.grid.json.gz" "$G/work/iv1-interval-r1.json.gz" \
    "$F/iv2-supports.jsonl.gz" "$F/iv2-partition.grid.json.gz" "$G/work/iv2-interval-only-r1.json.gz" || return 1
  for d in "$D1B" "$D1G" "$D2B" "$D2G"; do
    sha256sum "$d/TEST_COMPOSITION.json" || return 1
    (cd "$d" && find . -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sed "s|^|$d |") || return 1
  done
}
frozen > "$OUT/frozen-start.sha256" || exit 2
cd "$G/scripts" || exit 2
run6 () {  # tag runtime supports partition interval width cap shards shardlist... -- extra
  local tag=$1 rt=$2 sup=$3 part=$4 iv=$5 w=$6 cap=$7 n=$8; shift 8; local list=() extra=() seen=0
  for x in "$@"; do if [ "$x" = "--" ]; then seen=1; elif [ $seen = 0 ]; then list+=("$x"); else extra+=("$x"); fi; done
  local pids=() ids=() k
  for i in "${list[@]}"; do
    local more=()
    [ ${#extra[@]} -gt 0 ] && more=("${extra[@]//@I@/$i}")
    "$PY" -B -I "$CK/scripts/run1.py" 5400 "$PY" -B replay_surfaces.py --supports "$sup" --partition "$part" --interval "$iv" --stream-width $w \
      --runtime "$rt" --cap-cpu "$cap" --shard $i --shards "$n" --output "$OUT/$tag-s$i.jsonl" "${more[@]}" > "$OUT/$tag-s$i.log" 2>&1 &
    pids+=($!); ids+=($i)
  done
  for k in "${!pids[@]}"; do wait "${pids[$k]}"; echo $? > "$OUT/$tag-s${ids[$k]}.exit"; done
  echo "done $tag $(date +%H:%M:%S) exits $(for i in "${ids[@]}"; do cat "$OUT/$tag-s$i.exit"; done | paste -sd' ')"
}
check () {  # stage shardlist base_runtime gpy_runtime caps [rows]
  "$PY" -B -I "$CK/scripts/gpy_parity_check.py" "$OUT" "$1" "$(echo $2 | tr ' ' ',')" "$3" "$4" "${@:5}" || s=1
}
s=0
echo "start $(date +%H:%M:%S) mode $MODE"
for arm in base gpy; do
  rt=$RT1B; [ $arm = gpy ] && rt=$RT1G
  run6 iv1-surfaces-$arm "$rt" "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.grid.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" 60 $N1 $L1
done
check iv1-surfaces "$L1" "$RT1B" "$RT1G" none
for arm in base gpy; do
  rt=$RT2B; [ $arm = gpy ] && rt=$RT2G
  run6 iv2-sample-$arm "$rt" "$F/iv2-supports.jsonl.gz" "$F/iv2-partition.grid.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" 2 $N2 $L2 -- --only-cells-from "$SAMPLEC"
done
check iv2-sample "$L2" "$RT2B" "$RT2G" "defer:$DEEPC"
XL="$OUT/iv2-sample-extra-list.jsonl"; DL="$OUT/iv2-sample-deferred-list.jsonl"
sha256sum "$XL" "$DL" > "$OUT/lists.sha256" || { echo "FAIL: sample extra/deferred lists not written"; s=1; }
if [ ! -f "$XL" ]; then
  echo "FAIL: $XL not written"; s=1
elif [ -s "$XL" ]; then
  NX=$(wc -l < "$XL")
  for arm in base gpy; do
    rt=$RT2B; [ $arm = gpy ] && rt=$RT2G
    "$PY" -B -I "$CK/scripts/run1.py" 5400 "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.grid.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "$rt" --cap-cpu 120 \
      --only-list "$XL" --output "$OUT/iv2-extra-$arm-s0.jsonl" > "$OUT/iv2-extra-$arm-s0.log" 2>&1
    echo $? > "$OUT/iv2-extra-$arm-s0.exit"
  done
  check iv2-extra 0 "$RT2B" "$RT2G" none "$NX"
else
  echo "iv2-extra: every capped sample row is on the deep lists"
fi
for arm in base gpy; do
  rt=$RT2B; [ $arm = gpy ] && rt=$RT2G
  pids=(); ids=()
  for i in $LD; do
    list="$F/capped-list-$i.jsonl"; [ "$MODE" = smoke ] && list="$OUT/smoke-list-$i.jsonl"
    "$PY" -B -I "$CK/scripts/run1.py" 5400 "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.grid.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "$rt" --cap-cpu 120 --kinds interface \
      --only-list "$list" --output "$OUT/iv2-deep-$arm-s$i.jsonl" > "$OUT/iv2-deep-$arm-s$i.log" 2>&1 &
    pids+=($!); ids+=($i)
  done
  for k in "${!pids[@]}"; do wait "${pids[$k]}"; echo $? > "$OUT/iv2-deep-$arm-s${ids[$k]}.exit"; done
  echo "done iv2-deep-$arm $(date +%H:%M:%S)"
done
check iv2-deep "$LD" "$RT2B" "$RT2G" "cover:$DL"
"$PY" -B -I "$MEASURES" "$OUT" "$MODE" || s=1
frozen > "$OUT/frozen-end.sha256" || s=1
cmp -s "$OUT/frozen-start.sha256" "$OUT/frozen-end.sha256" || { echo "FAIL: scripts, lists or runtimes changed during the run"; s=1; }
sha256sum -c --quiet "$OUT/lists.sha256" || { echo "FAIL: sample extra/deferred lists changed during the run"; s=1; }
echo "end $(date +%H:%M:%S) exit $s"
exit $s
