#!/usr/bin/env bash
# Step 10 checkpoint smoke on a FROZEN composition (16 Oct 2026): the launcher, runner and reader
# run from the frozen helpers; root stage, then the interval stage stopped before the advance.
# Usage: run_frozen_smoke.sh FROZEN PROFILE LOG
set -u
frozen=$1; profile=$2; log=$3
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
pin=$(sha256sum "$profile" | cut -c1-64)
export PYTHONHASHSEED=0
for stage in root interval; do
  extra=""
  [ "$stage" = interval ] && extra="--stop-before-advance"
  echo "=== $stage start $(date '+%H:%M:%S')" >> "$log"
  started=$(date +%s)
  "$PY" -B "$frozen/helpers/launch_fresh_interval.py" --profile "$profile" --profile-sha256 "$pin" \
      --stage "$stage" --dev-timing $extra >> "$log" 2>&1
  code=$?
  echo "=== $stage exit $code after $(( $(date +%s)-started )) s at $(date '+%H:%M:%S')" >> "$log"
  [ "$code" -ne 0 ] && exit "$code"
done
echo "=== done $(date '+%H:%M:%S')" >> "$log"
