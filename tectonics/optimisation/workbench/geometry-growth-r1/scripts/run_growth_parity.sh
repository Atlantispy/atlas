#!/usr/bin/env bash
# (a)+(b)+WP20 parity on both transitions with the combined test runtime gw-r1.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
D="$T/fidelity-integration-20261005"
G="$D/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
A="$D/heat-repair-20261007/heat-original-continued-20261013-r4.artifacts"
PY="$T/.r44-env/Scripts/python.exe"
RT="test:$T/gg/gw-r1"
cd "$G/scripts"
echo "start $(date +%H:%M:%S)"
# IV1 candidate supports (growth): already rebuilt by next-iv1-growth-r1; replay them on gw-r1.
"$PY" -B -I split_partition.py --store "$G/work/r9-native-joined.copy.sqlite" --rebuild "$G/work/next-iv1-growth-r1.json.gz" --output "$G/work/iv1-growth-supports.jsonl.gz"
timeout 3000 "$PY" -B replay_queries.py --supports "$G/work/iv1-growth-supports.jsonl.gz" --runtime "$RT" --output "$G/evidence/replay-iv1-gw-r1-s0.jsonl" --cap-cpu 120 > "$G/work/replay-iv1-gw-r1.log" 2>&1 &
p1=$!
timeout 3600 "$PY" -B rebuild_next.py --transition iv2 --store "$G/work/r9-native-joined.copy.sqlite" --capture "$A/continuation-trace-inputs-02.json.gz" --iv2-interval "$G/work/iv2-interval-only-r1.json.gz" --proposal "$A/differential-proposal-02.json" --runtime "$RT" --growth --output "$G/work/next-iv2-gw-r1.json.gz" > "$G/work/next-iv2-gw-r1.log" 2>&1
echo "rebuild iv2 exit $? $(date +%H:%M:%S)"
wait $p1; echo "iv1 replay exit $? $(date +%H:%M:%S)"
"$PY" -B -I split_partition.py --store "$G/work/r9-native-joined.copy.sqlite" --rebuild "$G/work/next-iv2-gw-r1.json.gz" --output "$G/work/iv2-gw-supports.jsonl.gz"
pids=()
for i in 0 1 2 3 4 5; do
  timeout 7200 "$PY" -B replay_queries.py --supports "$G/work/iv2-gw-supports.jsonl.gz" --runtime "$RT" --output "$G/evidence/replay-iv2-gw-r1-s$i.jsonl" --cap-cpu 2 --shard $i --shards 6 > "$G/work/replay-iv2-gw-r1-s$i.log" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do wait $p; done
echo "iv2 replay done $(date +%H:%M:%S)"
