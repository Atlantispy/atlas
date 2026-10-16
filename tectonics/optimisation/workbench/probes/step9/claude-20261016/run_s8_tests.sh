#!/usr/bin/env bash
# S8 integration tests (retained_producer, observation only) on top of item 7: one process per module,
# -B, PYTHONHASHSEED=0. Full logs: $S/s8-<module>.log. One line per module; a failing log follows whole.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
P="$T/.r44-env/Scripts/python.exe"
export PYTHONHASHSEED=0
status=0
for module in test_s8_producer test_reopen_prepared_restart test_reopen_fresh_restart test_launch_fresh_interval \
              test_launch_monitored_interval test_step8_reader; do
  log="$S/s8-$module.log"
  start=$(date +%s)
  "$P" -B "$R/$module.py" > "$log" 2>&1
  code=$?
  summary=$(grep -E '^(Ran [0-9]+ tests|OK|FAILED)' "$log" | tr '\n' ' ')
  echo "$module exit=$code $(( $(date +%s) - start ))s $summary"
  if [ $code -ne 0 ]; then
    status=1
    cat "$log"
  fi
done
echo "s8 tests exit=$status $(date '+%H:%M:%S')"
exit $status
