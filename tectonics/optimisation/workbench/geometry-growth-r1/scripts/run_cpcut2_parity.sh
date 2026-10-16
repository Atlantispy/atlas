#!/usr/bin/env bash
# Complementary-cut certificate r2 (+ adoption): parity and the all-query IV2 interface projection.
# Waits for the r1 chain to end (its deep-rc1 arm is the RC1 baseline reused here), so arms never
# overlap on the shared machine. PYTHONHASHSEED=0. One arm at a time, 6 processes (< 2 GiB, no lock).
#  1. IV1 surfaces, all: RC1+cpcut r2+adopt vs RC1 (byte).
#  2. IV2 1-in-10 sample, cap 2 s: RC1+cpcut r2 vs RC1 (byte); RC1+wp23+cpcut r2 vs RC1+wp23 (byte).
#  3. Every RC1-capped sample interface at cap 120 s under RC1+cpcut r2 and RC1+wp23+cpcut r2.
#  4. Comparisons and the projection (project_interfaces.py) for RC1, cpcut r2, wp23+cpcut r2.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
R1="$G/evidence/cpcut-r1"
OUT="$G/evidence/cpcut-r2"
B="$G/evidence/wp23-seed0"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
W2="0xef6aca6e197d9db2f69d62da0b 0xc6ae51dc48000000000000000000000000000000000000"
CP="test:$T/gg/cpcut-r2"
CPW="test:$T/gg/cpcut-wp23-r2"
while ! grep -q '^end ' "$G/work/cpcut-parity.log"; do sleep 20; done
mkdir -p "$OUT"
cd "$G/scripts"
surf () {  # tag runtime supports partition interval width cap shards shardlist...
  local tag=$1 rt=$2 sup=$3 part=$4 iv=$5 w=$6 cap=$7 n=$8; shift 8; local pids=()
  for i in "$@"; do
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$sup" --partition "$part" --interval "$iv" --stream-width $w \
      --runtime "$rt" --cap-cpu "$cap" --shard $i --shards "$n" --output "$OUT/$tag-s$i.jsonl" > "$OUT/$tag-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done $tag $(date +%H:%M:%S)"
}
deep () {  # tag runtime
  local pids=()
  for i in 0 1 2 3 4 5; do
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$G/work/iv2-supports.jsonl.gz" --partition "$G/work/iv2-partition-r1.json.gz" \
      --interval "$G/work/iv2-interval-only-r1.json.gz" --stream-width $W2 --runtime "$2" --cap-cpu 120 --kinds interface \
      --only-list "$R1/capped-list-$i.jsonl" --output "$OUT/deep-$1-s$i.jsonl" > "$OUT/deep-$1-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done deep-$1 $(date +%H:%M:%S)"
}
echo "start $(date +%H:%M:%S)"
surf iv1-surfaces-cpcut2 "$CP" "$G/work/iv1-supports.jsonl.gz" "$G/work/next-iv1-rc1-r1.json.gz" "$G/work/iv1-interval-r1.json.gz" "$W1" 60 6 0 1 2 3 4 5
"$PY" -B -I compare_surfaces.py --baseline "$B/iv1-surfaces-rc1-s*.jsonl" --candidate "$OUT/iv1-surfaces-cpcut2-s*.jsonl" > "$OUT/cmp-iv1-surfaces.json"; echo "iv1 surfaces exit $?"
surf iv2-sample-cpcut2 "$CP" "$G/work/iv2-supports.jsonl.gz" "$G/work/iv2-partition-r1.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" 2 60 0 10 20 30 40 50
"$PY" -B -I compare_surfaces.py --baseline "$B/iv2-sample-rc1-s*.jsonl" --candidate "$OUT/iv2-sample-cpcut2-s*.jsonl" > "$OUT/cmp-iv2-sample.json"; echo "iv2 sample exit $?"
surf iv2-sample-cpcut2-wp23 "$CPW" "$G/work/iv2-supports.jsonl.gz" "$G/work/iv2-partition-r1.json.gz" "$G/work/iv2-interval-only-r1.json.gz" "$W2" 2 60 0 10 20 30 40 50
"$PY" -B -I compare_surfaces.py --baseline "$B/iv2-sample-wp23-s*.jsonl" --candidate "$OUT/iv2-sample-cpcut2-wp23-s*.jsonl" > "$OUT/cmp-iv2-sample-wp23.json"; echo "iv2 sample (wp23 base) exit $?"
deep cpcut2 "$CP"
deep cpcut2-wp23 "$CPW"
deep wp23 "test:$T/gg/wp23-r2"
"$PY" -B -I compare_surfaces.py --baseline "$R1/deep-rc1-s*.jsonl" --candidate "$OUT/deep-cpcut2-s*.jsonl" > "$OUT/cmp-deep-rc1-cpcut2.json"; echo "deep rc1 vs cpcut2 exit $?"
"$PY" -B -I compare_surfaces.py --baseline "$R1/deep-cpcut-s*.jsonl" --candidate "$OUT/deep-cpcut2-s*.jsonl" > "$OUT/cmp-deep-cpcut1-cpcut2.json"; echo "deep cpcut r1 vs r2 exit $?"
"$PY" -B -I compare_surfaces.py --baseline "$OUT/deep-cpcut2-s*.jsonl" --candidate "$OUT/deep-cpcut2-wp23-s*.jsonl" > "$OUT/cmp-deep-cpcut2-wp23.json"; echo "deep cpcut2 vs +wp23 exit $?"
"$PY" -B -I project_interfaces.py --total-jobs 63752 \
  --arm rc1 "$B/iv2-sample-rc1-s*.jsonl" "$R1/deep-rc1-s*.jsonl" \
  --arm cpcut2 "$OUT/iv2-sample-cpcut2-s*.jsonl" "$OUT/deep-cpcut2-s*.jsonl" \
  --arm wp23 "$B/iv2-sample-wp23-s*.jsonl" "$R1/deep-cpcut-wp23-s*.jsonl" \
  --arm cpcut2-wp23 "$OUT/iv2-sample-cpcut2-wp23-s*.jsonl" "$OUT/deep-cpcut2-wp23-s*.jsonl" > "$OUT/projection.json"; echo "projection exit $?"
echo "end $(date +%H:%M:%S)"
