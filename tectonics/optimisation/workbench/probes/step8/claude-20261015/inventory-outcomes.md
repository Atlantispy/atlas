# Step 8 inventory outcomes (30 rows), working copy

Source of the rows: `scouting/inventory-audit.json` (23 WP0a rows and handoff items 1-7). Outcome is one of
REMOVED (the copy or lifetime is gone, exactness proved), BOUNDED (kept on purpose or by an unchanged
reference, with its size measured and its lifetime correct), PENDING (named next action and owner).
Decision entries are in `decision-0*.md` (times on 15-16 October). Updated as items land.

| Row | Outcome | What was done or measured | Evidence |
|---|---|---|---|
| partition-preparation | REMOVED | preparation drops its own geometry decode before assembly; assembly drops scientific scratch with the result on both branches | decision-04 00:10; bench-assembly-* |
| partition-supports | REMOVED | native route takes each support row once as an owned value, issues it once and keeps only contact and identity IDs; composition keeps the compact producer (46.0 s, 34.3 MB booked at 1,820 supports, against 52.2 s and 161.4 MB native plus conversion) | decision-04 00:10, 00:20 |
| partition-body | REMOVED | successor drops decoded interval, finite stocks and parent header before assembly; issues once with the final fields; compact finish releases the body through a one-slot holder | decision-04 00:10 |
| parent-support-exports | REMOVED | carried charts re-booked instead of kept as export charges (REBOOK_CHARTS): booked 1,978.5 -> 168.6 MB at 2,016 supports, real 23.0 MB, time 3.36 -> 3.48 s | decision-04 00:15 |
| partition-publication | BOUNDED | convert_native releases the decoded body before validation; 8,064-support successor published in 278 s with its records on the live-producer child | decision-04 00:10; capacity-claude-overlaps-a2, a3 |
| mesh-inputs | REMOVED | EARLY_RELEASE: dead chart, pose, cache and index structures dropped at last use | decision-04 23:50 |
| mesh-topology | REMOVED | assembly consumes candidates through drain (one polygon released per step) | decision-04 23:50 |
| ordinary-mesh-production | REMOVED | same EARLY_RELEASE seams on the ordinary route | decision-04 23:50 |
| mesh-compact-production | PENDING (BOUNDED meanwhile) | one authentic IV1 mesh: 34.5 MB of columns held, 1,219.5 s to pack, 4.72 GB scratch booked for 30.8 MB of columns; the review chat's wave-2 fast path (M12) fixes speed and booking; my CompactMesh per-column transfer follows that merge | decision-05 01:15; profile-mesh-pack-3 |
| geometry-transfer | REMOVED | decoded transfer record and current plan graph released after the contract check, with their scratch; binding bytes identical | decision-05 02:00; geometry-transfer-{before,after}.json |
| bounds | REMOVED | bounds fields borrowed by composition, not repacked; stored once at publication | decision-02 22:15, 22:20 |
| graph | REMOVED | cross-holder repack removed; honest builder (wave 1) builds the authentic 104.7 MB graph in the unchanged 256 MiB child; IV2-shaped probe peaks at 83.1% | decision-02 22:15; decision-05 01:00, 01:49 |
| transport | REMOVED | exact rational tables dropped once encoded; finish releases each transport column after last use; authentic IV1 solve replays exactly (advance 27.6 s) | decision-03 23:30; capacity-claude-overlaps-a3 |
| state | REMOVED | cells streamed into one exact builder; composed state issue reproduces the authentic IV1 state ID | decision-04 23:45; capacity-claude-overlaps-a4 |
| exchange | REMOVED | exchange composed from borrowed graph, transport and proposal records | decision-02 22:15 |
| publication | REMOVED | publication by reference (v2 recipes): 4.50 -> 0.57 s, builder 19.5 -> 1.46 MB on the W4 owner, disk unchanged | decision-02 22:20; decision-03 22:52 |
| heat-ledger | PARTIAL | solve result released after projection (RELEASE_SOLVE_RESULT); one field at a time in from_components waits for the wave-2 heat_ledger_tables merge; compact IV1 ledger 166 MB held (live-producer child) | decision-05 02:36, 02:24 |
| heat-reference | BOUNDED | LiveJoinedHeat keeps result and call on purpose (identity re-verification); W4 job tree 1.09 GB with six polygon workers, parent 0.28 GB; plan bytes booked twice (over-booking, safe) | decision-03 23:12 |
| certification | REMOVED | booking width from holder_bytes for live compact holders | decision-04 23:52 |
| geometry-publication | PENDING | exception-funding test for differential_payload; IV1 differential record is 42,225 B, so the transient is about 0.4 MB | census |
| restore-migration | PENDING (BOUNDED meanwhile) | heat restore at IV1 adds 0.7 MB retained but took 2,402 s unsealed; I:1135 interval decode is 42,225 B canonical (tiny, uncharged); bounded pre-seal checks (R2) and the sealed reopen time are next | decision-05 02:38; profile-heat-restore-1 |
| validation-caches | PENDING | caches evictable inside 256 MiB; carried parent cells over-booked 49.8x (D1): R1a honest small-row bound (fix chat), then lazy rows (D1-B, mine) | decision-05 02:08 |
| diagnostics | EXCLUDED | diagnostic captures are not enabled in the Step 8 composition; WP16 (Step 13) must count them when enabled | plan section 4 |
| handoff-1 | BOUNDED | parent plus 8,064 distinct successor supports measured; capture-shaped (depth 2) variant added | capacity-claude-overlaps-a2, a3, a5 |
| handoff-2 | BOUNDED | actual transport matrix, GMRES and exact workspaces measured in the authentic IV1 replay (advance 27.6 s, exact result ID) | capacity-claude-overlaps-a3 |
| handoff-3 | REMOVED | state staging list removed (streamed cells) | decision-04 23:45 |
| handoff-4 | PARTIAL | solve-result release done; heat call/geometry/solver/projection overlap measured at W4 and bracketed at IV1 from the r9 receipt for the forecast | decision-05 02:36; decision-03 23:12 |
| handoff-5 | REMOVED | exchange and publication repacks removed; producers re-issued at full overlap in 0.3 s | decision-02; capacity-claude-overlaps-a3 |
| handoff-6 | BOUNDED | heat restore field buffers at IV1: 5 fields, 34,200 B, +0.7 MB retained | capacity-claude-overlaps-a3 |
| handoff-7 | REMOVED | transport columns released after last use | decision-03 23:30 |
