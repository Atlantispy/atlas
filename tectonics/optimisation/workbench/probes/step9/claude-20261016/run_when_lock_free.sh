#!/usr/bin/env bash
# Start one heavy command as soon as the cooperative heavy-run lock is free (16 Oct 2026).
# Usage: run_when_lock_free.sh MAX_WAIT_SECONDS LOG -- OWNER PEAK WHAT -- COMMAND...
# Retries run_with_heavy_lock.py while it exits 75 (lock held or lost race), checking
# once a minute; gives up after MAX_WAIT_SECONDS. The wrapper itself takes the lock.
set -u
max_wait=$1; log=$2; shift 3
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
lock="$T/fidelity-integration-20261005/heavy-run.lock.json"
waited=0
while true; do
  if [ ! -f "$lock" ]; then
    PYTHONHASHSEED=0 "$T/.r44-env/Scripts/python.exe" -B "$R/probes/step8/claude-20261015/run_with_heavy_lock.py" "$@" >> "$log" 2>&1
    code=$?
    if [ "$code" -ne 75 ]; then
      echo "exit $code after waiting ${waited}s" >> "$log"
      exit "$code"
    fi
  fi
  if [ "$waited" -ge "$max_wait" ]; then
    echo "gave up after ${waited}s: heavy-run lock still held" >> "$log"
    exit 75
  fi
  sleep 60
  waited=$((waited+60))
done
