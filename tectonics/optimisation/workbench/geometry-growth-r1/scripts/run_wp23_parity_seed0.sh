#!/usr/bin/env bash
# WP23 rotation parity with PYTHONHASHSEED=0 (as production): RC1 vs RC1+wp23rot.
# IV1 surfaces (all), IV1 endpoints (all), IV2 1-in-10 surface sample. One arm at a
# time, 6 processes each (under 2 GiB, no lock). Evidence: evidence/wp23-seed0/.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
OUT="$G/evidence/wp23-seed0"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
mkdir -p "$OUT"
cd "$G/scripts"
surfaces () {  # runtime tag supports partition interval width cap shards shardlist
  local rt=$1 tag=$2 sup=$3 part=$4 iv=$5 w=$6 cap=$7 n=$8; shift 8; local pids=()
  for i in "$@"; do
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$sup" --partition "$part" --interval "$iv" --stream-width $w \
      --runtime "$rt" --cap-cpu "$cap" --shard $i --shards "$n" --output "$OUT/$tag-s$i.jsonl" > "$OUT/$tag-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done $tag $(date +%H:%M:%S)"
}
echo "start $(date +%H:%M:%S)"
for arm in rc1 wp23; do
  rt=rc1; [ $arm = wp23 ] && rt="test:$T/gg/wp23-r2"
  surfaces "$rt" iv1-surfaces-$arm "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" 60 6 0 1 2 3 4 5
  timeout 3000 "$PY" -B replay_queries.py --supports "$G/work/iv1-supports.jsonl.gz" --runtime "$rt" --cap-cpu 120 \
    --output "$OUT/iv1-endpoints-$arm-s0.jsonl" > "$OUT/iv1-endpoints-$arm.log" 2>&1
  echo "done iv1-endpoints-$arm $(date +%H:%M:%S)"
  surfaces "$rt" iv2-sample-$arm "$G/work/iv2-supports.jsonl.gz" "$G/work/iv2-partition-r1.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" 2 60 0 10 20 30 40 50
done
"$PY" -B -I compare_surfaces.py --baseline "$OUT/iv1-surfaces-rc1-s*.jsonl" --candidate "$OUT/iv1-surfaces-wp23-s*.jsonl" > "$OUT/cmp-iv1-surfaces.json"; echo "iv1 surfaces exit $?"
"$PY" -B -I compare_parity.py --by-cell --baseline "$OUT/iv1-endpoints-rc1-s*.jsonl" --candidate "$OUT/iv1-endpoints-wp23-s*.jsonl" > "$OUT/cmp-iv1-endpoints.json"; echo "iv1 endpoints exit $?"
"$PY" -B -I compare_surfaces.py --baseline "$OUT/iv2-sample-rc1-s*.jsonl" --candidate "$OUT/iv2-sample-wp23-s*.jsonl" > "$OUT/cmp-iv2-sample.json"; echo "iv2 sample exit $?"
echo "end $(date +%H:%M:%S)"
