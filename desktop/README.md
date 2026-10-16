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
The 3 October 2026 refresh packages commit `30a79e6`: the I01/I02 backend,
R7 repairs, newer 3-D solver and reviewed I03 spherical network, bridges and events,
including K1-K5 and the N1 follow-up. It retains the existing UI. I02's
coupled-column workflow and I03's supplied-motion spherical history are included
in the backend; the existing evolution controls still run the regional route,
not whole-planet I03 evolution. Native source and runtime compatibility checks remain active when opening
or continuing old work; an older job is not silently rebound to the new code.

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

## Current Windows acceptance (3 October build)

The refresh contains all 389 native payload files from `30a79e6`, with matching
hashes, and the unchanged pinned UI and CPython runtime. Two targeted I03
path/mesh/event save-reopen-continue regressions passed using the bundled Python
and packaged source (4.858 s). Existing scientific acceptance was reused.

The real executable created, exported, loaded and saved a six-plate, 192-cell
world with identical reloaded fields (20.837 s). The hidden-window test now waits
for painted globe content rather than a fixed delay. Its reopen check explicitly
opens Your world from the intentional start page. After installation, that check
passed in 4.676 s, preserving the isolated profile, origin and saved world.
The globe screenshot was inspected. The user's normal profile and projects were
not opened or modified; the 2 October application is retained as a recovery copy.

## Earlier Windows acceptance (2 October build)

The 2 October refresh passed its real executable check in an isolated profile:
six plates and 192 support cells were generated, exported, loaded through the UI
file input, saved with Save World and reloaded with identical world-view fields.
This took 20.397 s after the initial window load. After installation, a fresh
process restored the same origin, profile and saved native world in 2.524 s.
The globe/interface screenshot was inspected and both processes exited normally.
The user's normal profile and saved projects were not opened or changed.

All 380 delivered native payload files matched the committed source snapshot,
including all 280 Python files. The retained CPython 3.12.14 runtime matched all
39 dependency pins; five build guards and three launcher/security tests passed.
The packaged I02 command workflow separately created and inspected its initial
state with zero accepted advancement steps. The first invocation correctly
refused an absent test root; creating that root resolved the invocation error.
Existing scientific evidence was reused, not replaced by this packaging check.

That application was approximately 801 MB, with Electron 44.4.5, the relocatable
Python runtime and the unchanged UI snapshot. The previous 26 September build
was retained as a recovery copy; the existing Start-menu shortcut targets the
updated application. This is Windows packaging/lifecycle coverage, not new
whole-world scientific acceptance or native Linux coverage.

## Design and security

Implementation references: [Electron distribution](https://www.electronjs.org/docs/latest/tutorial/distribution-overview)
and [Electron security](https://www.electronjs.org/docs/latest/tutorial/security).
The renderer has no Node access, is sandboxed and cannot navigate to remote
content. A random per-launch token protects the loopback backend. Network assets,
telemetry and automatic updates are not enabled.
