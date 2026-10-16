#!/usr/bin/env bash
# Launcher for smoke_r3.sh. It waits OUTSIDE runq until 10.5 GiB are free (ab_heat's 10 GiB start gate plus
# 0.5 GiB margin), sleeping 30 s between checks and using no CPU, then enters runq small. runq small refuses
# to launch while an exclusive ticket runs or is about to start. smoke_r3 exits 75 if memory fell again
# during runq's own wait; this loop then waits again. Any other exit code is final.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
while true; do
  until "$PY" -B -c "import psutil, sys; sys.exit(psutil.virtual_memory().available < 10.5*2**30)"; do sleep 30; done
  echo "$(date +%H:%M:%S) 10.5 GiB free; entering runq small"
  # --gib 1.1: q03's measured tree peak for one lw proof arm was 1.03 GiB (bookkeeping = real cost).
  "$PY" -B -I "$T/q/runq.py" small --cores 7 --gib 1.1 -- bash "$T/hs/scripts/smoke_r3.sh"
  rc=$?
  [ "$rc" -eq 75 ] || exit "$rc"
done
