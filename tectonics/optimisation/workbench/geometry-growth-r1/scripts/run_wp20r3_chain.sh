#!/usr/bin/env bash
# One sequential chain (same machine hour): WP20 r3 parity on IV2 and IV1, then
# IV2 item-11 / item-15 ablations on the same WP20 r3 runtime, then an RC1 IV2 rerun
# as a same-hour baseline for timing.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
RT="test:$T/gg/wp20-r3"
run_set () {  # supports runtime shards cap tag ablate
  pids=()
  for ((i=0; i<$3; i++)); do
    timeout 7200 "$PY" -B "$G/scripts/replay_queries.py" --supports "$1" --runtime "$2" \
      --output "$G/evidence/replay-$5-s$i.jsonl" --cap-cpu "$4" --shard "$i" --shards "$3" --ablate "$6" \
      > "$G/work/replay-$5-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  echo "done $5 $(date +%H:%M:%S)"
}
echo "start $(date +%H:%M:%S)"
run_set "$G/work/iv2-supports.jsonl.gz" "$RT" 6 2 iv2-wp20-r3 ""
run_set "$G/work/iv1-supports.jsonl.gz" "$RT" 1 120 iv1-wp20-r3 ""
run_set "$G/work/iv2-supports.jsonl.gz" "$RT" 6 2 iv2-wp20-r3-item11off item11
run_set "$G/work/iv2-supports.jsonl.gz" "$RT" 6 2 iv2-wp20-r3-item15off item15
run_set "$G/work/iv2-supports.jsonl.gz" "$RT" 6 2 iv2-wp20-r3-again ""
