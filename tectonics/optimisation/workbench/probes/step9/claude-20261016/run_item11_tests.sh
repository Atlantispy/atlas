#!/usr/bin/env bash
# Item 11 unit tests (observed commit-window stages): one process per module, -B, PYTHONHASHSEED=0,
# then ruff F,E9 on the changed files. Full logs: $S/item11-<module>.log. One line per module; on a
# failure the whole failing log follows (never trimmed).
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
P="$T/.r44-env/Scripts/python.exe"
export PYTHONHASHSEED=0
status=0
for module in test_fresh_interval_driver test_run_fresh_interval; do
  log="$S/item11-$module.log"
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
ruff check --select F,E9 --no-fix "$R/fresh_interval_driver.py" "$R/test_fresh_interval_driver.py" > "$S/item11-ruff.log" 2>&1
code=$?
echo "ruff F,E9 exit=$code $(tail -n 1 "$S/item11-ruff.log")"
[ $code -ne 0 ] && { status=1; cat "$S/item11-ruff.log"; }
sha256sum "$R/fresh_interval_driver.py" "$R/test_fresh_interval_driver.py" | sed -E 's#^(........)[^ ]* \*?.*/#\1 #'
echo "item11 tests exit=$status $(date '+%H:%M:%S')"
exit $status
