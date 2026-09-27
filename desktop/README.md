# Atlas for Windows

Open **Atlas.exe**. Keep it with the accompanying `resources`, runtime files and
licence notices; the executable is not a single-file distribution. No Python,
Node, terminal command or administrator installation is required to run it.

Use **New World**, **Save World** and **Load World** in the application. Saved
`.atlas` files are portable project exports. Internal working files and UI drafts
are stored under `%APPDATA%/Atlas`, not in the application folder. Closing the
window cancels active calculations and closes the owned backend; saved exports
are not deleted. The existing browser-based Atlas workspace is separate.

This is an unsigned development build: Windows may display a publisher warning.
It packages the current experimental tectonics capability; it does not complete
I01 or claim a scientifically accepted whole-world generator. Native source and
runtime compatibility checks remain active when opening or continuing old work.

## Rebuild

From the repository root, use `desktop/fetch_electron.mjs CACHE_DIRECTORY` with
Node to fetch the pinned official Electron archive and verify its SHA-256.
`desktop/prepare_python.py --help` prepares the separately staged Python payload
from the tested environment without modifying that environment.

Run `python -B desktop/build.py --electron ARCHIVE --python PYTHON_PAYLOAD
--ui UI_PROTOTYPE_DIRECTORY --output NEW_OUTPUT_DIRECTORY`. Existing destinations
are refused. The build includes the UI owner's source snapshot and unchanged
native Python sources, not personal projects, caches or coordination records.
`build-manifest.json` records delivered file hashes. Keep it with the build.

Focused checks: `node --test desktop/runtime.test.cjs`. The packaged executable's
`--smoke-test NEW_DIRECTORY` mode exercises the real isolated desktop/backend
route and exits, saving a report and screenshot. It never opens the user's
normal profile. Do not call this a full scientific test suite.

Implementation references: [Electron distribution](https://www.electronjs.org/docs/latest/tutorial/distribution-overview)
and [Electron security](https://www.electronjs.org/docs/latest/tutorial/security).
The renderer has no Node access, is sandboxed and cannot navigate to remote
content. A random per-launch token protects the loopback backend. Network assets,
telemetry and automatic updates are not enabled.
