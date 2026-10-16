#!/usr/bin/env bash
# WP23 rotation parity: IV1 all surfaces (RC1 vs WP23), IV1 all endpoints (WP23),
# IV2 1-in-10 surface sample (WP23, same selection as the RC1 sample). One chain.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
RT="test:$T/gg/wp23-r2"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
cd "$G/scripts"
surfaces_iv1 () {  # runtime tag
  pids=()
  for i in 0 1 2 3 4 5; do
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$G/work/iv1-supports.jsonl.gz" --partition "$G/work/next-iv1-rc1-r1.json.gz" \
      --interval "$G/work/iv1-interval-r1.json.gz" --stream-width $W1 --runtime "$1" --cap-cpu 60 --shard $i --shards 6 \
      --output "$G/evidence/surfaces-iv1-$2-s$i.jsonl" > "$G/work/surfaces-iv1-$2-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done iv1 surfaces $2 $(date +%H:%M:%S)"
}
echo "start $(date +%H:%M:%S)"
surfaces_iv1 rc1 rc1-r1
surfaces_iv1 "$RT" wp23-r1
timeout 3000 "$PY" -B replay_queries.py --supports "$G/work/iv1-supports.jsonl.gz" --runtime "$RT" --output "$G/evidence/replay-iv1-wp23-r1-s0.jsonl" --cap-cpu 120 > "$G/work/replay-iv1-wp23.log" 2>&1
echo "done iv1 endpoints $(date +%H:%M:%S)"
bash run_surfaces_sample.sh "$G/work/iv2-supports.jsonl.gz" "$G/work/iv2-partition-r1.json.gz" "$RT" 2 wp23
