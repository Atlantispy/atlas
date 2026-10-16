#!/usr/bin/env bash
# q2_zero_test + jets_convolution (coordinator D-b): field-by-field parity with only source-digest
# fields allowed to differ, and the CPU effect. PYTHONHASHSEED=0. One arm at a time, 6 processes.
#  1. IV1 surfaces, all: RC1 vs RC1+q2fast+jetsfast.
#  2. IV2 candidate 1-in-10 sample (cap 2 s): candidate f1 vs candidate f1 + q2fast + jetsfast.
#  3. IV2 candidate deep set (every candidate-capped sample interface, cap 120 s): same two arms.
# Usage: run_jets_parity.sh <new evidence folder name, e.g. jets-r2>
# Fail closed (16 Oct, Exact kernels found r1 fail-open): every shard's exit code is kept in
# <stage>-<arm>-s<i>.exit, and each stage is judged by surfaces_stage_check.py, which fails a missing,
# empty or all-capped stage, a non-zero or missing shard exit, a done/runtime/digest mismatch, and a
# capped query that no deeper stage re-runs (round 2, 16 Oct: deep count and capped lists pinned;
# round 3: the run reads hashed copies of the lists, and the deep rows must be exactly those queries).
# The script exits 0 only if all three stages pass. evidence/jets-r1 (bare wait, unchecked) is UNVERIFIED.
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
F="$G/evidence/final-f1"
# The name starts and ends with a letter or digit: Windows drops a trailing dot, so 'jets-r2.' would
# be a new folder to bash but jets-r2 to Python, and the checker would read jets-r2's old shards
# (refuter 16 Oct, P2). Python (Windows rules) must also agree that the folder does not exist.
[ $# -eq 1 ] && [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$ ]] || { echo "usage: run_jets_parity.sh <new evidence folder name>"; exit 2; }
OUT="$G/evidence/$1"
[ -e "$OUT" ] && { echo "exists: $OUT (never rewritten)"; exit 2; }
"$PY" -B -I -c "import os,sys; sys.exit(1 if os.path.lexists(sys.argv[1]) else 0)" "$OUT" || { echo "exists to Windows: $OUT (never rewritten)"; exit 2; }
# Inputs first: an empty reference list would turn --only-cells-from off and run whole shards.
REFS=$(ls "$F"/ref-iv2-surfaces-s*.jsonl 2>/dev/null | paste -sd, -)
[ -n "$REFS" ] || { echo "no reference shards in $F"; exit 2; }
for f in "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.json.gz" "$G/work/iv1-interval-r1.json.gz" \
         "$F/iv2-supports.jsonl.gz" "$F/iv2-partition.json.gz" "$G/work/iv2-interval-only-r1.json.gz" \
         "$F"/capped-list-{0,1,2,3,4,5}.jsonl; do
  [ -s "$f" ] || { echo "missing or empty input $f"; exit 2; }
done
# Query counts per arm, fixed by those pinned inputs (r1 wrote exactly these on both arms):
# IV1 all surfaces; IV2 sample (6 shards of 60, cells of the reference run); deep = the 216 lines of
# the six capped lists, pinned with their bytes (refuter 16 Oct, P3-b: a count read from the lists
# would follow a truncated or edited list).
EXPECT_IV1=40968; EXPECT_SAMPLE=901; EXPECT_DEEP=216
CAPPED_SHA=1981300315d474de6aa88fff0d82d9bc0e728c9b060f302312d0b426722f8373   # lists 0..5 concatenated
got=$(cat "$F"/capped-list-{0,1,2,3,4,5}.jsonl | sha256sum | cut -c1-64)
[ "$got" = "$CAPPED_SHA" ] || { echo "capped lists are $got, not the pinned $CAPPED_SHA"; exit 2; }
mkdir "$OUT" || exit 2
# The deep stage and both checks read copies of the lists, hashed again once copied (refuter round 3:
# a list edited after the check above would otherwise be the one run and judged).
L="$OUT/inputs"
mkdir "$L" && cp "$F"/capped-list-{0,1,2,3,4,5}.jsonl "$L"/ || exit 2
got=$(cat "$L"/capped-list-{0,1,2,3,4,5}.jsonl | sha256sum | cut -c1-64)
[ "$got" = "$CAPPED_SHA" ] || { echo "copied capped lists are $got, not the pinned $CAPPED_SHA"; exit 2; }
LISTS="$L/capped-list-0.jsonl,$L/capped-list-1.jsonl,$L/capped-list-2.jsonl,$L/capped-list-3.jsonl,$L/capped-list-4.jsonl,$L/capped-list-5.jsonl"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
RT_IV1_BASE=rc1; RT_IV1_JETS="test:$T/gg/jets-r1"
RT_IV2_BASE="test:$T/gg/final-f1"; RT_IV2_JETS="test:$T/gg/cand-jets-r1"
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
check () {  # stage shards base_rt jets_rt expected_rows cap_rule
  "$PY" -B -I surfaces_stage_check.py "$OUT" "$1" "$2" base "$3" jets "$4" "$5" "$6"
  local s=$?; echo "$1 check exit $s"; [ $s = 0 ] || failed=1
}
echo "start $(date +%H:%M:%S)"
for arm in base jets; do
  rt=$RT_IV1_BASE; [ $arm = jets ] && rt=$RT_IV1_JETS
  run6 iv1-surfaces-$arm "$rt" "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" 60 6 0 1 2 3 4 5
done
check iv1-surfaces 0,1,2,3,4,5 "$RT_IV1_BASE" "$RT_IV1_JETS" "$EXPECT_IV1" none
for arm in base jets; do
  rt=$RT_IV2_BASE; [ $arm = jets ] && rt=$RT_IV2_JETS
  run6 iv2-sample-$arm "$rt" "$F/iv2-supports.jsonl.gz" "$F/iv2-partition.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" 2 60 0 10 20 30 40 50 -- --only-cells-from "$REFS"
done
# A sample cap counts only for a query the deep stage re-runs (P3-a); IV1 and deep accept no cap, and
# the deep stage's rows must be exactly the listed queries (round 3).
check iv2-sample 0,10,20,30,40,50 "$RT_IV2_BASE" "$RT_IV2_JETS" "$EXPECT_SAMPLE" "list:$LISTS"
for arm in base jets; do
  rt=$RT_IV2_BASE; [ $arm = jets ] && rt=$RT_IV2_JETS
  pairs=()
  for i in 0 1 2 3 4 5; do
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$F/iv2-supports.jsonl.gz" --partition "$F/iv2-partition.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "$rt" --cap-cpu 120 --kinds interface \
      --only-list "$L/capped-list-$i.jsonl" --output "$OUT/iv2-deep-$arm-s$i.jsonl" > "$OUT/iv2-deep-$arm-s$i.log" 2>&1 &
    pairs+=($! "$i")
  done
  waitall "iv2-deep-$arm" "${pairs[@]}"
  echo "done iv2-deep-$arm $(date +%H:%M:%S)"
done
check iv2-deep 0,1,2,3,4,5 "$RT_IV2_BASE" "$RT_IV2_JETS" "$EXPECT_DEEP" "exactly:$LISTS"
echo "end $(date +%H:%M:%S)"
if [ $failed = 0 ]; then echo "JETS PARITY PASSED"; exit 0; fi
echo "JETS PARITY FAILED"; exit 1
