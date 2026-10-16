#!/usr/bin/env bash
# Progress hooks (proposed runner option): byte parity vs RC1 with the sink unset (IV1 surfaces
# and endpoints, all) and with a recorder installed (IV1 surfaces, all; slow threshold 2 s so
# the recorder actually writes). Queued after the r3 confirmation. PYTHONHASHSEED=0.
set -u
export PYTHONHASHSEED=0
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
B="$G/evidence/wp23-seed0"
OUT="$G/evidence/progress-parity-r1"
RT="test:$T/gg/progress-r1"
W1="0x2f00cbfcd7c08aad8918ab19af 0x4e3bbe22f900000000000000000000000000000000000"
while ! grep -q '^end ' "$G/work/r3-confirm.log"; do sleep 20; done
mkdir -p "$OUT"
cd "$G/scripts"
for arm in off on; do
  pids=()
  for i in 0 1 2 3 4 5; do
    extra=()
    [ $arm = on ] && extra=(--progress "$OUT/progress-on-s$i.jsonl" --progress-slow 2 --progress-heartbeat 5)
    timeout 5400 "$PY" -B replay_surfaces.py --supports "$G/work/iv1-supports.jsonl.gz" --partition "$G/work/next-iv1-rc1-r1.json.gz" \
      --interval "$G/work/iv1-interval-r1.json.gz" --stream-width $W1 --runtime "$RT" --cap-cpu 60 --shard $i --shards 6 \
      --output "$OUT/iv1-surfaces-$arm-s$i.jsonl" "${extra[@]}" > "$OUT/iv1-surfaces-$arm-s$i.log" 2>&1 &
    pids+=($!)
  done
  for p in "${pids[@]}"; do wait "$p"; done
  "$PY" -B -I compare_surfaces.py --baseline "$B/iv1-surfaces-rc1-s*.jsonl" --candidate "$OUT/iv1-surfaces-$arm-s*.jsonl" > "$OUT/cmp-iv1-surfaces-$arm.json"; echo "iv1 surfaces sink $arm exit $?"
done
timeout 3000 "$PY" -B replay_queries.py --supports "$G/work/iv1-supports.jsonl.gz" --runtime "$RT" --cap-cpu 120 \
  --output "$OUT/iv1-endpoints-off-s0.jsonl" > "$OUT/iv1-endpoints-off.log" 2>&1
"$PY" -B -I compare_parity.py --by-cell --baseline "$B/iv1-endpoints-rc1-s*.jsonl" --candidate "$OUT/iv1-endpoints-off-s*.jsonl" > "$OUT/cmp-iv1-endpoints-off.json"; echo "iv1 endpoints sink off exit $?"
echo "end $(date +%H:%M:%S)"
