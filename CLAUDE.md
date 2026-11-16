@AGENTS.md

# Claude Code in Atlas

Follow the shared instructions above; no duplication and no broad audit to start a session. Future-work plan:
`docs/ATLAS_ROADMAP.md`. Tectonics source, tools and focused tests: `tectonics/`.

## Working alongside Codex

- Inspect the branch and working-tree changes before editing. Existing edits may be Codex's or the owner's:
  preserve them; never reset or clean them away.
- Work only on your assigned files and task; no concurrent edits to the same files. Overlapping work goes in an
  isolated worktree, then explicit review and integration; worktrees lack uncommitted fixes.
- No branch switch in the shared checkout, commit, push, merge or publish without the owner's request. Cloud
  changes are not local until applied.
- Coordinate before changing `tectonics/src/atlas_tectonics`: its execution identity covers the whole package,
  so any edit invalidates an in-flight test or benchmark, even of another module.
- Run proportionate, focused tests once against stable sources; reuse valid results; no full suite, full-world
  simulation or repeated polling by default.
- Report changed files, actual test results, unresolved issues and the next action. Never claim another agent
  received or integrated a handoff without evidence.

Keep account credentials, user-specific paths and private environment settings out of tracked files. Use
normal tool permissions; do not bypass approval controls.
