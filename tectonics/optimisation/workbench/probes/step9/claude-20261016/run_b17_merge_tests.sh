#!/usr/bin/env bash
# B17 rev4 + item 14 merge: the focused test modules in ONE process on the live compact folder, the way the
# storage package's combined harness runs them on its mirrors (w1run.py, cwd = the compact folder, -B,
# PYTHONHASHSEED=0), so test-order effects match.
# Usage: run_b17_merge_tests.sh <tag> <module> [<module> ...]
# Logs: $S/b17m-<tag>.out.txt and .err.txt (unittest reports on stderr); refuses to overwrite either.
# Prints the exit, the wall, unittest's totals, every FAIL/ERROR header, and every file under the compact
# folder (depth 3) written during the run, so a test writing into the live tree cannot pass unseen.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
C="$R/compact-geometry-r1"
S="$R/probes/step9/claude-20261016"
P="$T/.r44-env/Scripts/python.exe"
W1="$T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/w1-storage/w1run.py"
export PYTHONHASHSEED=0
tag="$1"
shift
out="$S/b17m-$tag.out.txt"
err="$S/b17m-$tag.err.txt"
marker="$S/b17m-$tag.start"
for f in "$out" "$err" "$marker"; do
  if [ -e "$f" ]; then
    echo "$f exists; refusing to overwrite it"
    exit 2
  fi
done
: > "$marker"
start=$(date +%s)
(cd "$C" && "$P" -B "$W1" "$@") > "$out" 2> "$err"
code=$?
echo "b17m $tag exit=$code wall_s=$(( $(date +%s) - start )) end $(date '+%H:%M:%S') modules=$#"
grep -hE '^(Ran [0-9]+ test|OK|FAILED)' "$out" "$err"
grep -hE '^(FAIL|ERROR): ' "$out" "$err"
echo "written under the compact folder during the run (depth 3):"
find "$C" -maxdepth 3 -newer "$marker" -type f | head -50
exit $code
