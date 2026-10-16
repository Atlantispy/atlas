#!/bin/bash
# S2 r9b: R's own driver tests (all classes), base vs r9, re-pinned to R's test_fresh_interval_driver.py
# as changed at 18:19 (60fba3c7). Everything else as run_all_r9.sh's last section.
S=$(cd "$(dirname "$0")/.." && pwd -W)
T=$(cd "$S/../.." && pwd -W)
P=$T/.r44-env/Scripts/python.exe
export PYTHONHASHSEED=0
cd $S/r9-check
$P -B -c "import sys; sys.exit(sys.flags.hash_randomization != 0)" || { echo "refusing: the string-hash seed is not 0"; exit 3; }
date
echo "== R driver tests: base, r9 (test_fresh 60fba3c7)"
for v in base r9; do
  $P -B -P $S/r9-check/drv/drivers_r9b.py fresh $v 2>&1 | tail -12
  $P -B -P $S/r9-check/drv/drivers_r9b.py prepared $v 2>&1 | tail -12
done
date
