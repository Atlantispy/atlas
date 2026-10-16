for m in no_sha no_loop_check no_iterjson_guard no_owner_count skip_last_blob no_loop_rcheck no_source_check; do
  C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe -B C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/refute/s9/run_mutant.py C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/refute/s9/mutants/$m 2>&1 | tail -1
done
C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe -B C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/refute/s9/run_mutant.py C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/s9 2>&1 | tail -1
