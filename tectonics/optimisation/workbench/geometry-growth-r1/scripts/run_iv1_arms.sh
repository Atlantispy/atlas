#!/usr/bin/env bash
# One sequential chain of same-input IV1 endpoint replays (same harness, same machine hour):
# RC1 production route, r7 (the r4 run's runtime) public route, RC1 public route.
set -u
export PYTHONHASHSEED=0   # production pins it; interface work units follow set order
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
IN="$G/work/iv1-supports.jsonl.gz"
TAG="$1"
for arm in "rc1 batch" "r7 public" "rc1 public"; do
  set -- $arm
  out="$G/evidence/replay-iv1-$1-$2-$TAG.jsonl"
  echo "start $1 $2 $(date +%H:%M:%S)"
  timeout 3000 "$PY" -B "$G/scripts/replay_queries.py" --supports "$IN" --output "$out" --cap-cpu 120 --runtime "$1" --route "$2"
  echo "exit $1 $2 $? $(date +%H:%M:%S)"
done
