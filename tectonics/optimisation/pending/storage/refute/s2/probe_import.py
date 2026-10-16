"""Refuter probe (read-only on sources): ledger reader in its historical stdlib-only invocation."""
import sys
S2 = 'C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/s2'
sys.path.insert(0, S2)
import ledger_fresh_interval as LG
row = {'format': LG.CAPTURE_FORMAT, 'path': 'preadvance-bounds.capture', 'raw_bytes': 1,
       'raw_sha256': '0'*64, 'container_sha256': '0'*64}
caught = (LG.LedgerRefused, KeyError, TypeError, ValueError, OSError)
try:
    LG.capture('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/so/refute/s2', row)
except BaseException as error:
    print('raised', type(error).__name__, error, '| caught by main():', isinstance(error, caught))
