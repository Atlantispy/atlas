#!/usr/bin/env bash
# W4 heat call (unchanged production chain, layout h13l1) with the read-only worker capture.
# Usage: run_w4_capture.sh <tag>   (outputs T/ck/<tag>/ and captures T/ck/<tag>-cap/)
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
TAG=$1
mkdir -p "$T/ck/$TAG-cap"
export CK_CAPTURE_DIR="$T/ck/$TAG-cap" PYTHONPATH="$T/ck/capture" PYTHONHASHSEED=0
cd "$G/scripts"
"$PY" -B profile_w4_heat.py --layout C:/Users/LOCAL_USER/h13l1 --output-dir "$T/ck/$TAG" --no-profile
status=$?
echo "captured files: $(ls "$T/ck/$TAG-cap" | wc -l)"
exit $status
