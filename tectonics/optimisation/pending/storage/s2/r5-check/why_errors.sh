#!/bin/bash
cd /c/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/s2/r5-check
for m in c2_checks_every_store c5_subclass_accepted l1_no_raw_ceiling l5_allocate_first l6_legacy_eof_uncaught l7_legacy_zlib_uncaught l8_hex_any_case; do
  echo "== $m"; PYTHONHASHSEED=0 /c/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe -B run_tests_r5.py "/c/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/s2/r5-check/mutants/$m" test_wp16_preadvance test_ledger_fresh_interval test_step8_coverage 2>&1 | grep -E "^(ERROR|FAIL):|^[A-Za-z.]*(Error|Exception|Refused)[:(]" | head -6
done
