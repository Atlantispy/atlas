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
The [current delivery summary](../docs/CURRENT_STATE.md) records the accepted
build and its backend scope. The regional UI does not supply whole-planet
advancement. Native source and runtime checks remain active when opening or
continuing old work; an older job is not silently rebound to new code.

## Rebuild

A rebuild needs four inputs. Three can be reproduced from this repository:

1. The official Electron 44.4.5 archive: `node desktop/fetch_electron.mjs CACHE_DIRECTORY`
   fetches it, and `build.py` verifies its pinned SHA-256.
2. The Python payload: `desktop/prepare_python.py --help` stages it from the tested
   Windows CPython 3.12 environment without modifying that environment.
3. The native tectonics sources, cases and requirements from this checkout, copied
   unchanged.
4. The UI owner's source snapshot: exactly the 33 files named by `UI_FILES` in
   `build.py`, from `index.html`, `styles.css` and `app.mjs` to `serve.mjs` and the
   view, data, reader and manager modules. **It is not in this repository**, so a
   reviewer cannot rebuild the accepted application from a clone. The build refuses
   a snapshot unless every file matches `desktop/ui-snapshot.json`, a
   name-to-SHA-256 pin of those 33 files with schema `atlas.desktop-ui-snapshot.v1`.
   The tracked pin was recovered from the accepted 26 September build's
   `build-manifest.json` and checked against all 33 delivered UI files. It holds
   digests, not UI content. Use that matching source snapshot, or the unchanged
   `resources/app/ui` directory from that accepted build. A clone alone still
   does not contain the UI files needed to rebuild.

Run `python -B desktop/build.py --electron ARCHIVE --python PYTHON_PAYLOAD
--ui UI_SNAPSHOT_DIRECTORY --output NEW_OUTPUT_DIRECTORY`. Existing destinations
are refused. The build includes the pinned UI snapshot and unchanged native Python
sources, not personal projects, caches or coordination records.
`build-manifest.json` records delivered file hashes. Keep it with the build.

New full builds also create `tectonics/.desktop-runtime.json` in the native
payload. Together with the packaged interpreter and allowed desktop entry point,
this enables release identity checking: full capture once per backend, full checks
at persistence/reuse boundaries, cheap inner checks. It never changes the physical
calculation or scientific identity. Checkout and evidence runs remain strict.
See [execution policy](../docs/CODING_SAFETY.md#strict-checkout-and-packaged-release-execution).
This source integration does not alter the installed 3 October EXE; a separate
authorised rebuild and installed-app check are still required.

## Checks

- `node --test desktop/runtime.test.cjs` runs wherever Node is available.
- `python -B -m unittest discover -s desktop -p "test_*.py" -v` runs the copy,
  UI-pin and payload guards. The two payload tests that call
  `prepare_python.prepare` run only on Windows CPython 3.12, the supported
  packaging platform. Elsewhere they are skipped with that reason, and a separate
  test checks that `prepare` refuses the platform before touching any file. A skip
  or pass on another platform is not validation of the Windows executable.
- The packaged executable's `--smoke-test NEW_DIRECTORY` mode exercises the real
  isolated desktop/backend route and exits, saving a report and screenshot. It
  never opens the user's normal profile.

None of these is a full scientific test suite.

## Obtained Windows qualification

The recorded 3 October build packaged all 389 native files from `30a79e6`, with
the unchanged pinned UI and CPython runtime. Two I03 path/mesh/event
save-reopen-continue regressions passed using that packaged source/interpreter
(4.858 s). The executable created, exported, loaded and saved a six-plate,
192-cell world with identical reloaded fields (20.837 s); the installed reopen
check passed in 4.676 s and the globe screenshot was inspected. The hidden-window
check waits for painted globe content and opens the saved world from the start
page. These checks used an isolated profile and preserved the normal user data.

The preceding 2 October build supplied the 39-dependency runtime-pin and
copy/launcher/security qualification at its own bindings. Its packaged I02
workflow reached initial state only, with zero accepted advances. Old timing and
delivery chronology remain in
[Git history](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/desktop/README.md).
Packaging/lifecycle coverage does not replace scientific evidence, qualify Linux,
or establish that later source edits are installed. A new build needs its own
actual affected packaging and installed-route checks.

## Design and security

Implementation references: [Electron distribution](https://www.electronjs.org/docs/latest/tutorial/distribution-overview)
and [Electron security](https://www.electronjs.org/docs/latest/tutorial/security).
The renderer has no Node access, is sandboxed and cannot navigate to remote
content. A random per-launch token protects the loopback backend. Network assets,
telemetry and automatic updates are not enabled.
