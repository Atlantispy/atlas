@AGENTS.md

# Claude Code in Atlas

Follow the shared instructions above; do not duplicate them or run a broad audit
just to start a session. The active future-work plan is `docs/ATLAS_ROADMAP.md`.
Tectonics source, tools and focused tests are in `tectonics/`.

## Working alongside Codex

- Inspect the branch and working-tree changes before editing. Existing edits may
  belong to Codex or the owner; preserve them and never reset or clean them away.
- Work only on the files and task assigned to you. Do not edit the same files
  concurrently. Use an isolated worktree for overlapping work, then review and
  integrate its changes explicitly; worktrees do not include uncommitted fixes.
- Do not switch the shared checkout's branch, commit, push, merge or publish
  without the owner's request. Cloud changes are not local changes until applied.
- Coordinate before changing `tectonics/src/atlas_tectonics`: its execution
  identity covers the whole package, so edits invalidate an in-flight test or
  benchmark even when a different module is being tested.
- Run proportionate, focused tests once against stable sources. Reuse valid
  results; no full suite, full-world simulation or repeated polling by default.
- Report changed files, actual test results, unresolved issues and the next action.
  Do not claim another agent has received or integrated a handoff without evidence.

Keep account credentials, user-specific paths and private environment settings out
of tracked files. Use normal tool permissions; do not bypass approval controls.
