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
   That pin is not yet in the repository either; `build.py` refuses until it is added.
   Create that pin once from the accepted build's `build-manifest.json`, whose
   `resources/app/ui/NAME` entries record the delivered digests; the pin holds
   digests, not UI content. Obtaining the snapshot itself remains the open dependency.

Run `python -B desktop/build.py --electron ARCHIVE --python PYTHON_PAYLOAD
--ui UI_SNAPSHOT_DIRECTORY --output NEW_OUTPUT_DIRECTORY`. Existing destinations
are refused. The build includes the pinned UI snapshot and unchanged native Python
sources, not personal projects, caches or coordination records.
`build-manifest.json` records delivered file hashes. Keep it with the build.

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

## Recorded Windows acceptance

The actual executable created a six-plate/192-support-cell world, exported it,
loaded it through the UI file input, saved it with Save World and reopened it with
identical world-view fields, 20.009 s after the initial window load. A second
process restored the same origin, profile and world in a 2.539 s check. The
globe/interface screenshot was inspected; both processes exited and no Atlas
process remained. The first restricted-runner attempt could not launch Chromium's
renderer; normal desktop execution passed with sandboxing retained. That build was
about 799 MB, with Electron 44.4.5, relocatable CPython 3.12.14 and all 39 pinned
distributions, and it packaged the UI owner's snapshot without redesign; its
saved-result reader waits for child exit during shutdown. This is one Windows
observation of an unsigned build, not scientific acceptance or a check on other
platforms, and it cannot be repeated without the UI snapshot.

## Design and security

Implementation references: [Electron distribution](https://www.electronjs.org/docs/latest/tutorial/distribution-overview)
and [Electron security](https://www.electronjs.org/docs/latest/tutorial/security).
The renderer has no Node access, is sandboxed and cannot navigate to remote
content. A random per-launch token protects the loopback backend. Network assets,
telemetry and automatic updates are not enabled.
