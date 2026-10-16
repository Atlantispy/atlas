#!/usr/bin/env bash
# Item 21 unit tests: one process per module, -B, PYTHONHASHSEED=0. Full logs: $S/item21-<tag>-<module>.log.
# Usage: run_item21_tests.sh <tag> <module> [<module> ...]
# Prints one line per module; on a failure, the whole failing log follows (never trimmed).
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
P="$T/.r44-env/Scripts/python.exe"
export PYTHONHASHSEED=0
tag="$1"
shift
status=0
for module in "$@"; do
  log="$S/item21-$tag-$module.log"
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
echo "item21 $tag tests exit=$status $(date '+%H:%M:%S')"
exit $status
