#!/usr/bin/env bash
# ONE-COMMAND PARITY for the geometry chat's Step 10 transforms.
#   reference = RC1 + items_11_15_off            (the decided D1 baseline)
#   candidate = RC1 + growth -> WP20 -> items_off -> WP23 rotation -> complementary-cut certificate (+ its parallel adoption) + q2 zero test + jet convolution (digest-only record changes, D-b)
# Usage: run_final_parity.sh <tag> [candidate-composition-folder] [reference-folder]
# With folder arguments (e.g. the Step 10 composed runtime-src, which must contain
# TEST_COMPOSITION.json or be passed via rc1_env's test: route) they are used as given.
# Inputs: the saved IV1 capture, the IV1 store copy, the exact IV2 rebuild (work/).
# Outputs: evidence/final-<tag>/*. Exit status 0 only if every comparison passes.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
D="$T/fidelity-integration-20261005"
G="$D/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
A="$D/heat-repair-20261007/heat-original-continued-20261013-r4.artifacts"
PY="$T/.r44-env/Scripts/python.exe"
TAG="$1"
CAND="${2:-$T/gg/final-$TAG}"
REF="${3:-$T/gg/ref-$TAG}"
OUT="$G/evidence/final-$TAG"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
mkdir -p "$OUT"
cd "$G/scripts"
[ -d "$CAND" ] || "$PY" -B -I compose_test_runtime.py "$CAND" growth wp20 items_off wp23rot cpcut cpadopt q2fast jetsfast > "$OUT/compose-candidate.json"
[ -d "$REF" ] || "$PY" -B -I compose_test_runtime.py "$REF" items_off > "$OUT/compose-reference.json"
fail=0
check () { "$@" > "$OUT/$NAME.json"; s=$?; echo "$NAME exit $s"; [ $s -eq 0 ] || fail=1; }
shards () {  # script supports partition-or-dash runtime cap tag extra...
  local script=$1 sup=$2 part=$3 rt=$4 cap=$5 tag=$6; shift 6; local pids=()
  for i in 0 1 2 3 4 5; do
    if [ "$script" = q ]; then
      timeout 7200 "$PY" -B replay_queries.py --supports "$sup" --runtime "$rt" --cap-cpu "$cap" --shard $i --shards 6 \
        --output "$OUT/$tag-s$i.jsonl" "$@" > "$OUT/$tag-s$i.log" 2>&1 &
    else
      timeout 7200 "$PY" -B replay_surfaces.py --supports "$sup" --partition "$part" --runtime "$rt" --cap-cpu "$cap" \
        --shard $i --shards 6 --output "$OUT/$tag-s$i.jsonl" "$@" > "$OUT/$tag-s$i.log" 2>&1 &
    fi
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done $tag $(date +%H:%M:%S)"
}
echo "start $(date +%H:%M:%S)"
# ---- static -> IV1
"$PY" -B rebuild_next.py --transition iv1 --store "$G/work/r9-native-joined.copy.sqlite" --capture "$A/continuation-trace-inputs-02.json.gz" \
  --runtime "test:$CAND" --growth --output "$OUT/iv1-partition.json.gz" > "$OUT/iv1-rebuild.json" 2>&1
# Fail fast (queue time): without a rebuilt partition every later step is void.
s=$?; [ $s -eq 0 ] && [ -s "$OUT/iv1-partition.json.gz" ] || { echo "FAIL: iv1 rebuild exit $s, no partition"; tail -c 1500 "$OUT/iv1-rebuild.json"; exit 1; }
"$PY" -B -I split_partition.py --store "$G/work/r9-native-joined.copy.sqlite" --rebuild "$OUT/iv1-partition.json.gz" --output "$OUT/iv1-supports.jsonl.gz" > /dev/null
NAME=iv1-structure check "$PY" -B -I compare_partitions.py "$G/work/next-iv1-rc1-r1.json.gz" "$OUT/iv1-partition.json.gz" "$OUT/iv1-dropped.json"
shards q "$G/work/iv1-supports.jsonl.gz" - "test:$REF" 120 ref-iv1-endpoints
shards q "$OUT/iv1-supports.jsonl.gz" - "test:$CAND" 120 cand-iv1-endpoints
NAME=iv1-endpoints check "$PY" -B -I compare_parity.py --by-cell --baseline "$OUT/ref-iv1-endpoints-s*.jsonl" --candidate "$OUT/cand-iv1-endpoints-s*.jsonl"
# Memory rule (16 Oct): surface shards read a small grid file, never a whole partition
# (a whole interval-2 RC1 partition costs about 4 GB per process to parse).
"$PY" -B -I make_grid_file.py "$OUT/iv1-partition.json.gz" "$OUT/iv1-partition.grid.json.gz" > /dev/null
shards s "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.grid.json.gz" "test:$REF" 60 ref-iv1-surfaces --interval "$G/work/iv1-interval-r1.json.gz" --stream-width $W1
shards s "$OUT/iv1-supports.jsonl.gz" "$OUT/iv1-partition.grid.json.gz" "test:$CAND" 60 cand-iv1-surfaces --interval "$G/work/iv1-interval-r1.json.gz" --stream-width $W1
NAME=iv1-surfaces check "$PY" -B -I compare_surfaces.py --numbers --baseline "$OUT/ref-iv1-surfaces-s*.jsonl" --candidate "$OUT/cand-iv1-surfaces-s*.jsonl"
# ---- IV1 -> IV2
"$PY" -B rebuild_next.py --transition iv2 --store "$G/work/r9-native-joined.copy.sqlite" --capture "$A/continuation-trace-inputs-02.json.gz" \
  --iv2-interval "$G/work/iv2-interval-only-r1.json.gz" --proposal "$A/differential-proposal-02.json" \
  --runtime "test:$CAND" --growth --output "$OUT/iv2-partition.json.gz" > "$OUT/iv2-rebuild.json" 2>&1
s=$?; [ $s -eq 0 ] && [ -s "$OUT/iv2-partition.json.gz" ] || { echo "FAIL: iv2 rebuild exit $s, no partition"; tail -c 1500 "$OUT/iv2-rebuild.json"; exit 1; }
"$PY" -B -I split_partition.py --store "$G/work/r9-native-joined.copy.sqlite" --rebuild "$OUT/iv2-partition.json.gz" --output "$OUT/iv2-supports.jsonl.gz" > /dev/null
NAME=iv2-structure check "$PY" -B -I compare_partitions.py "$G/work/iv2-partition-r1.json.gz" "$OUT/iv2-partition.json.gz" "$OUT/iv2-dropped.json"
shards q "$G/work/iv2-supports.jsonl.gz" - "test:$REF" 2 ref-iv2-endpoints
shards q "$OUT/iv2-supports.jsonl.gz" - "test:$CAND" 2 cand-iv2-endpoints
NAME=iv2-endpoints check "$PY" -B -I compare_parity.py --by-cell --dropped "$OUT/iv2-dropped.json" --baseline "$OUT/ref-iv2-endpoints-s*.jsonl" --candidate "$OUT/cand-iv2-endpoints-s*.jsonl"
# IV2 surfaces: the reference 1-in-10 support sample, and exactly the same cells on the candidate.
pids=()
for i in 0 10 20 30 40 50; do
  timeout 7200 "$PY" -B replay_surfaces.py --supports "$G/work/iv2-supports.jsonl.gz" --partition "$G/work/iv2-partition-r1.grid.json.gz" \
    --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "test:$REF" --cap-cpu 2 --shard $i --shards 60 \
    --output "$OUT/ref-iv2-surfaces-s$i.jsonl" > "$OUT/ref-iv2-surfaces-s$i.log" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
cells=$(ls "$OUT"/ref-iv2-surfaces-s*.jsonl | paste -sd, -)
"$PY" -B -I make_grid_file.py "$OUT/iv2-partition.json.gz" "$OUT/iv2-partition.grid.json.gz" > /dev/null
shards s "$OUT/iv2-supports.jsonl.gz" "$OUT/iv2-partition.grid.json.gz" "test:$CAND" 2 cand-iv2-surfaces --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --only-cells-from "$cells"
NAME=iv2-surfaces check "$PY" -B -I compare_surfaces.py --numbers --dropped "$OUT/iv2-dropped.json" --baseline "$OUT/ref-iv2-surfaces-s*.jsonl" --candidate "$OUT/cand-iv2-surfaces-s*.jsonl"
echo "end $(date +%H:%M:%S) fail=$fail"
exit $fail
