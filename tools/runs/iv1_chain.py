"""Fast-loop r39 = r38 (e67f5afe) + design diffgeom-phase-optimisation-r1 section MA (G3, G6, G7, G13): the
  package's machine monitor and resources gate, loaded by path from the package root the chain runs, replace
  the driver's own copies. A start waits for the gate's start_need (was gate_bytes, the same bytes); free memory
  is the monitor's; the launch's core reading is one monitor reading over cores_sample_seconds, its free cores the
  physical cores less the busy logical CPUs (the halved idle count and the GetSystemTimes branch go); CHECK3
  holds the guard to the limits its own receipt records and the floor to the gate's (the 12 GiB and 1 GiB go).
Fast-loop r38 = r37 (18c7cfa7) + design driver-r38-heat-width-r1 (0edbd2d9; decisions 1548-1550): the heat pool's
  width is the launch's own. F5 requires the fresh driver to set the pool once, to heat_workers(...), and journals
  'launch'; check_pool takes the width the run recorded and requires every kept call to have run under it. The
  configuration's heat_workers stays as decision 1044's standard count and is compared with nothing (E-4 dropped).
Fast-loop r37 = r36 (2c25ac57) + design end-content-pin-r1 (74842d46) s3 build B: F3 checks the content pairs.
Fast-loop r36 = r33 (ee1224fb) + design interpreter-hash-once-r1 (4e0f2c94; decisions 1093, 1094).
  IH     the bind pins the interpreter copy twice: tree_sha256 (full hash, as before) and listing_sha256 (each
         file's path, size and modification time in nanoseconds; no file opened), from interpreter_pin. At chain
         start and on a resume interpreter_checks makes the listing: equal to the config's, tree_sha256 is the
         config's pin and no file of the tree is opened; otherwise, or with no listing_sha256 in the config, the
         tree is hashed in full as in r33 and a difference stops with r33's message. pre_checks.interpreter keeps
         its fields and gains verified_by ('listing' or 'hash') and listing_sha256; the resume key reads
         tree_sha256 only, so a run verified by listing and one verified by hash resume each other.
         Not caught (Reviewer N-1): a file changed with its size and time both put back; no step hashes the
         installed packages' .py files. A copy or disk that does not keep times only loses the saving (N-3).

Fast-loop r33 = r32 (db9e93c8) + requirements 2f05ebed items 4 and 11 (Designer on N-66) and N-65.
  N-65   the arm's list of saving units is read from M-1 r3's private file atlas_tectonics/_private/
         q297_end_factory_v2.py (the one SAVING_UNITS line, unchanged form), not the public store file.
  item 4 at a pause (PAUSED or STEP_LIMIT_REACHED) the completed-heat folder of an interval producer journaled as
         passed is not a leftover whatever keep_query_leftovers says: it stays in place, is not listed as taken and
         does not brand the pause. A package change still moves it aside (r26 F-5); at any other stop the r24 and
         F-13 rules hold, and the key keeps its meaning for a stopped step's entries.

Fast-loop r32 = r31 (aacfc0bb) + decisions 818 and 821 (design step5-save-as-it-goes-r1 bba06377 s7b).
  B-1    a stop from outside is told by the earlier journal: RUNNING or INTERRUPTED with no failed exit of a step
         (and, through the release, every recorded identity dead). Such a resume on an unchanged package (resume key
         equal) is unbranded only when every kind of save point the arm holds is in OUTSIDE_STOP_PROVED, a table from
         kind to {ticket, arm, revisions}, empty here: a one-line revision enters a kind after its real kill (818, 821).
         The arm holds step boundaries and before-seal, and the kinds of the saving units its list names
         (ARM_UNITS in the package tree, read as text at the resume: the one line SAVING_UNITS = ('U-2 1', ...),
         each 'unit revision', Worker 4's form for M-1). No line, more than one, an unreadable one or an unknown unit:
         a kind no table holds. The brand and journal name the stop and the kinds not proved; an unbranded resume
         journals the stop, the digests and each kind's ticket, arm and unit revisions.
         F-13 (N-20): a saved result (query entries, the completed-heat folder) is listed as taken only when the first
         launch is the interval producer that reads it (the measurement store: step 1, as S-1 already holds); a
         passed step's outputs held in place are not taken beyond the step itself, so they do not brand a pause.
  F-14   the release listing also looks for the package root and the interpreter root; the resuming driver and the
         processes above it are left out by id, a process above only if created before the one below it (831).
  821    an output of a reused step that fails its journaled digest makes that step and every later one run again
         (the outputs of the passed steps from there are moved aside with the leftovers) and the journal names the
         files (resume.torn_outputs); before r32 that stopped for a person. The journal's temporary file is forced to
         disk before its rename.
  B-2    a STEP_LIMIT_REACHED journal (stop_after) is a pause too: its resume is held to the same proof against the
         digests of its own start check. A pause request still in the journal folder at the chain's end is renamed
         .void (pause_void), so a later resume on that home does not pause on it (N-15). A pause exits 75, not 3
         (833: abort() ends with 3 on Windows).

Fast-loop r31 = r30 (70b3de5e) + B-1 and B-2 (decisions 808, 811, 815; ruling 27a; design step5-save-as-it-goes-r1
s7b; Reviewer Addenda 21-23, F-11).
  B-1    once, before the first launched step (or at the end when every step was reused), a resume that took a step
         or left a saved result in place (kept units, query leftovers, the stopped measurement store named, the
         completed-heat folder) is branded resume-after-stop with the change none and what it took, unless it is a
         proved pause (B-2) at a clean boundary. Under a package change today's brand stands. A resume that took
         nothing is a fresh run on the same home: not branded. Until the real kill-and-resume run passes (815) every
         stop that is not a recorded pause is branded; lifting that needs a new revision.
  B-2    a pause request (PAUSE-REQUEST.json, schema atlas.chain-pause-request.r1, reason, utc) in the journal folder
         is looked for before each launch. A valid one: renamed .taken, the pause journaled (request hash, the step it
         stopped before, the package and interpreter tree digests of this run's start check), status PAUSED, exit 75.
         A malformed one is renamed .refused, journaled under pause_refused, and the chain runs on. The resume of a
         PAUSED journal proves both digests equal to the pause record's (new check), else needs a recorded package
         change (then branded as a fix) or stops: a person decides.

Fast-loop r30 = r29 (08356940) + R-2, R-3, R-4 (decision 789; design step5-save-as-it-goes-r1 eec33b8e s7b), F-9
(Reviewer Addendum 20) and the Designer's lead 777:
  R-2    the last step of the earlier journal, passed and without a checkpoint (killed between the two), is reused once
         its outputs equal their journaled digests (reuse's own test); the resume then takes its checkpoint
         (resume.checkpoint_taken). After a kill only (a released journal); its acceptance checks run again on reuse. Not a pair's producer (R-4) and not an earlier step: those stop reuse, as before.
  R-3    a reader-files-only change whose first launch is not step 7 or 8 no longer stops: reader_files_only is dropped
         for this resume (resume.reader_files_only_dropped) and the chain runs as under an ordinary package change
         (D-1b, D-3). A step reused as recorded under reader files only before that point stops: a person decides.
  R-4    an overlapped pair's producer that passed, whose reader did not pass, is reused (outputs to their digests) with
         no checkpoint of its own; its reader runs alone by the sequential route, and r19's K-2 sets the stopped
         reader's files aside (resume.pair_producer_kept).
  F-9    S-1's words go only to a tree that takes them: config member takes_resumed_measurements (default false; a
         ticket sets it for a tree made with make_s1_measurements_r1). Otherwise resume.measurements says so.
  777    package_change_checks takes the package tree's members from package_checks' hash of the same run when its
         digest is the pre-check's (one hash of the package tree per resume, not two).

Fast-loop r29 = r28 (0667eb0f) + R-1 and the driver half of S-1 (decision 764; design
step5-save-as-it-goes-r1 3942586a s7b, s7c; conditions 750, 753, 757):
  R-1a   after a kill, the package tree's time test runs after the resume key; under a recorded package change whose
         checks passed in full for this resume (P-1 earlier tree, new hashes, put-back tree; P-2) those checks stand
         in its place (resume.release.package). The interpreter tree keeps the time test always.
  R-1b   a RUNNING/INTERRUPTED journal without a person's release record: on a diagnostic tree without capture the
         driver releases it itself when (1) the process listing succeeds, is not empty and names no earlier journal
         folder or tree, and (2) every process identity the earlier journal recorded ({pid, created_ticks}: the
         driver's own, each launched step's, each probe's, an overlapped pair's tracking) is gone. A launch with no
         identity (every journal before r29) needs a person's record, as today; so does a proof or real tree and a
         capture. The record (atlas.chain-release.driver.r1: journal hash, the resume's config, listing time,
         identities tested) is written to the new journal folder and pinned in resume.release. The driver records
         its identity at its start, each step's child from Popen, each probe's before it is waited on.
  S-1    a resume whose first launch is step 1 names the stopped attempt's measurement folder, as settle moved it
         aside, to the producer (--resume-measurements, added_argv; resume.measurements): only with an equal resume
         key, no package change (F-6) unless its record says keeps_measurements (with its reason, as keeps_queries),
         a diagnostic tree and no capture. Needs a package with the S-1 patch (make_s1_measurements_r1.py).
  Not built: the heavy lock note (V-4; no lock path in the config); a Release chain (this driver launches none).

Fast-loop r28 = r27 (0769b792) with D-10's refusal text naming a change of reader files only.

Fast-loop r27 = r26 (ae04e8fe) + D-3, driver half (decisions 726, 731; step5-save-as-it-goes-r1 95d8a008 s2):
under a package change other than reader files only step 5 starts seeded and names the earlier profile
(--reuse-previous-run, --reuse-previous-run-sha256) as added_argv; P-5 retired; intervals 2 is refused only after a
change of reader files only (D-10; D-7 lifted). Needs a package with the D-3 patch (make_d3_seed_across_r1.py).

Fast-loop r26 = r25 (b90b6eb5) + F-5 (decision 723; Reviewer Addendum 2): the completed-heat folder is moved
aside under any package change, also one whose record says keeps_queries.

Fast-loop r25 = r24 (251efc5f) + F-4 (Reviewer Addendum 1): under a package change other than reader files only,
a step recorded as failed is not reused; it and the later steps run again.

Fast-loop r24 = r23 (1e044605) + U-1 (decisions 709, 716; step5-save-as-it-goes-r1 098861a9 s2-s3):
  D-1    a resume across a package change keeps a brand file already in the home (it begins with the banner) and
         records the new reason with the earlier one as `also`; another file at that name is refused.
  HEAT   a resume moves the step's completed-heat folder aside unless the query entries are kept.

Fast-loop r23 = r22 (e8a7b524) + U-3 (decision 710; step5-save-as-it-goes-r1 098861a9 s4; review N-6):
  KQ     issue record package_change.keeps_queries (bool, default false) and, when true, keeps_queries_reason (a
         non-empty string: the fix reviewer's reason that no changed file can alter a geometry query's result).
         With it and keep_query_leftovers true, a resume across that change leaves the stopped step's query
         entries in place and journals their count, as MSS does without a change. Both are journaled in
         resume.package_change. Without it, as r22: the query leftovers are set aside.

Fast-loop r22 = r21 (9f981a6d) with one condition (decision 623; next-producer-open-r1 b75a96cd s5a, D-10): with
`intervals` 2 every package change is refused before the first launch, also one of reader files only.

Fast-loop r21 = r20 (4cd88a82) + optional config key `intervals` (1 or 2; decision 593, next-producer-open-r1
s5a): with 2, steps 9-12 run interval 2 (`--interval 2`; the producer gets `--parent-adopted-sha256` = step 8's
journaled digest of adopted-interval-0001.json; folders run-interval-0002 and reader-interval-0002; bookings
interval2 and reader-interval2; CHECK3 under the journal key check3_interval2). Refused with capture, continuation,
stop_after or overlap; refused before any launch when step 5 would run unseeded. A resume step with no earlier
entry says so in resume.reason. Absent or 1: r20. Optional `open_proofs` true: --open-proofs on producer commands
only (steps 1, 5, 9 and their dry runs); refused with resume_from or capture.

Fast-loop r20 = r19 (01349b50) + optional config key `stop_after` = '1-root-producer': step 1 runs and is
checked and checkpointed as before, then the chain ends STEP_LIMIT_REACHED (exit 0); only on a fresh sequential run
(no resume_from, capture or overlap). Decision 568 (Worker 1's step-1 replay).

Fast-loop r19 = r18 (242ee0a6) + settle() holds every leftover when the last reused step is a producer with no
checkpoint, except its reader's own units, which are set aside (decision 467, Reviewer K-2; q462 set aside step 5's
undeclared sealed store member).

Fast-loop r18 = r17 (a9ce45a5) + settle() holds a leftover that is an output of a step reused in this journal
(place 3) instead of refusing it as a passed step's output (decision 458; q460 refused q459's passed, uncheckpointed
step 5 producer). The refusal stands for every other passed step's output.

Fast-loop r17 = r16 (2818f47d) + the CHECK3 reader pin moved to reader r4 (decision 448; equal reread-bracket
stamps accepted, order by sequence): CHECK3_READER_SHA only.

Fast-loop r16 = r15 build r5 (75b7b77f) + recheck-removal-r1 s5 D1-D3 (decision 328; C4, ND26, ND24, ND38):
  D1     no tree hash at a passed step or at a resume: a checkpoint lists each file with its size
         (tree_inventory(hashed=False)); settle tests presence and size. An r14/r15 checkpoint (string digests)
         is tested for presence only. The start checks still hash (package_checks, interpreter_checks).
  D2     unchanged() is gone: the pin validated when the receipt was read is handed on as it is.
  D3     run A's measurement store is not hashed by the driver; the receipt's record of it is still tested.
  D1c    settle_continuation journals files and bytes of the three trees (tree_inventory(hashed=False)); its
         listing test against the earlier journal stays (recheck-removal-r1 5a188a20 s5).
  D4     not built: layout_check_r1.py checks more than the start checks (fast-loop-r16/NOTES.md).

Fast-loop r15 = r14 (3f2a339e) + the recording switch together with the overlap (driver-r15-switch-with-overlap-r1
29462209, decision 322; review W-3, P-1 to P-3, Q-1 to Q-3):
  E1     an overlap with record_failed_steps is no longer refused at configuration (capture still refuses the switch).
  E2     a pair's reader exit code goes through place 1 (recorded when the switch is on); a pair's producer exit code
         is still refused: the pair stops and a resume records it (place 3) and runs the reader as an ordinary step.
  E3     a recorded pair reader gets no checkpoint (r12), so its passed producer gets its own, with the pair's mark:
         a resume still reuses the two together. No route hands it a producer that is itself recorded or reused (P-1).
  E4    no gate for a producer recorded at place 2 while its reader waits: the pair stops; a resume runs the reader.
  E5    step 5's CHECK3 receiving: a refusal is recorded when the switch is on (every step 5); a reused step 5 with no
         receiving file on disk is received for the first time. P-6 (a package change) stays r14's refusal.
  With the switch off nothing changes.

Fast-loop r14 = r13 (2c222b75) + mid-step saving + RUNQ out of the resume key + P-6 + errata 1 s5 B7 + R-5
(mid-step-saving-r1 8565a7f2, decisions 267, 297-300, review M-1, M-4, M-5; resume-after-pin-change-r1 s2 P-6;
end-check-removal-r1 errata 1 s5, decision 275; r12 build review R-5):
  MSS    optional config key `keep_query_leftovers` (bool). True: a resume's settle leaves the stopped step's query
         entries (files of the queries tree beyond the last reused checkpoint) where they are and journals their
         count; the store tests each entry when asked for it (ruling 7). Never across a package change (M-1, taken
         further; decision 299); there, and when absent or false, as r13. The checkpointed query files are still
         required unchanged; `final` still refuses any leftover.
  RUNQ   the resume key compares the audited environment without the queue's own RUNQ_* values (decision 298); they
         are still journaled.
  B7     the package files are hashed once at the start: record_check reads RECORD's digests against tree_digest's
         (S-6b), sizes by stat. C4 (errata 1 s5) is the checkpoint of the three run trees in `passed`, not a package
         hash: no package tree is hashed after a step in r13, so nothing is removed (notes).
  R-5    capture with record_failed_steps is refused at configuration.
  P-6    under a package change (RP) a reused step 5 is not received again: its journaled CHECK3 receiving record is
         read by its journaled hash and used as it is (resume-after-pin-change-r1 s2, decision 300, ruling 7). An
         ordinary resume and a continuation receive again, as r13.

Fast-loop r13 = r12 (08f9543a) + the o4 overlap stage + K43 (wired-arm-r1 s4; end-check-removal-r1 errata 1 s3;
decisions 273, 275, 292):
  O4     optional config key `overlap` {stages, wait_seconds, wait_basis, bookings, helpers} (chain_overlap_r4.py
         86f02d4b): absent, every stage runs as in r12. A listed stage launches its producer and an admitted-ahead
         reader together; the producer's checks (CHECK3 receiving included) run before the gate is published. The
         pair is journaled as its two real steps plus a `<N>-<mode>-overlap` record reuse passes over; one checkpoint,
         taken after both ended, covers both (`pair`); a resume reuses a pair whole or stops. A refused reader start
         gate runs the reader afterwards as an ordinary step. The first-launch work is one method for both routes.
         Refused at configuration: an `interval` overlap with capture.
  K43    no end-of-run re-checks and no profile hash or probe before each launch: the start checks (install_checks
         'pre', the config, profile and driver pins) are the checks. The journal has no post_checks; the resume key
         compares start values only (a journal's post_check_failure still reuses nothing); P-1 and P-4 read the
         earlier journal's start values only.

Fast-loop r12 = r11 (32f1d146) + recording a FAILED earlier step, driver only (failed-step-recording-r1 1256c6f3,
decisions 278, 285, 290; review notes S-5, S-6, S-7):
  REC    config `record_failed_steps` (bool, required; schema r11). Tests of how a step ended go through `prior`: off,
         refused as before; on, recorded neutrally in the journal's `recorded` list and the run branded (brand_recorded:
         an existing brand is kept, S-7). Place 1 a step's exit code; place 2 check_receipt's status, errors and
         reserved bytes; place 3 a resume reuses an ended, non-passed step whose command and outputs hold (no
         checkpoint; its exit recorded). A unit holding a reused step's output is kept (resume.kept). Items a step's
         own record (reopen.json, reopen-final.json) lists as `recorded` are copied into its entry and recorded. A
         recorded step gets no checkpoint. Reader and finalise launches get --record-failed-prior when on, journaled
         as added_argv, never part of the compared command. The end is COMPLETED_RECORDED when anything was recorded.
         A missing output, the data tests and the driver's own readings still stop. No cap test here (decision 290).
  S-5    a resume or continuation from a journal holding `recorded` items or a brand, or from a home holding the brand
         file, is branded before its first step.
  RFO    issue record package_change.reader_files_only true: step 5 compared seeded; a launched finalise gets
         --reuse-previous-run <earlier profile> --reuse-previous-run-sha256 <hash> (added_argv); the first launch must
         be 7-interval-finalise or 8-interval-adopt, else the chain stops before launching anything.

Fast-loop r11 = r10 + resume after a reviewed pin change, driver only (resume-after-pin-change-r1 6f9eda1c + errata 1
4822c40d; errata 2 0fd5dd01 changes the run sequence only):
  RP     a resume whose earlier journal's package tree differs from this run's, and whose pinned issue record's
         `package_change` names that earlier tree, may reuse steps 1-4 only if: P-1 the present table with the
         named files' old hashes put back digests to the earlier tree at its start and end; P-2 the earlier
         profile is the journaled one and equals this profile as data; P-3 each reused
         command is equal once the two profile words are set aside; P-4 reused receipts carry the earlier
         journal's execution identity and the earlier profile as producer identity;
         P-5 step 5 runs unseeded. Any failed test stops the chain; no member, or another earlier tree: today's
         rule. An earlier journal without check3_selection stops. Such a run is branded NOT SCIENTIFICALLY
         PERMISSIBLE (journal key on every save, file in the run's home, printed lines). Not with a continuation.

Fast-loop r10 = r9 + the capture mode, driver only (capture-route-r1 c48a3977 + errata 1 f712b0d0; errata 2
f3ff84cb withdraws its section 5):
  CAP    config `capture` (bool; refused with a continuation). Issue test F3 as in an ordinary run. Before step
         5 starts, the failure record must be absent (C-1). Step 5 exiting 0 stops
         at once, unaccepted. Step 5 exiting non-zero is judged before the closing checks: status CAPTURED and a
         `capture` block only for the provider's own id refusal with ids that differ from the record's; else
         STOPPED with the reason. Exit code stays 1 for all but PASS.

Fast-loop r9 = r8 (266aed41) + two edits, driver only (driver-save-retry-r1 129d4b73 + errata 1 51bb83a6):
  E2     save retries os.replace on PermissionError (any open handle on the journal refuses it), 0.2 s apart for up
         to 30 s, then raises as before; the full text stays in CHAIN-JOURNAL.tmp. Journal key save_retries counts
         saves that had to wait.
  E1     an unexpected exception's stop also journals stop_traceback; a ChainStop gets none.

Fast-loop r8 = r7 (df689a38) + one change, driver only (q405: the job guard kills the tree; the journal stays RUNNING):
  K9     config `resume_release` {path, sha256} (else null): resume_from may name a RUNNING/INTERRUPTED journal only
         with a release record (schema atlas.chain-release.r1: journal_sha256 = resume_from's sha, ticket, killed_utc,
         reason), and only while no live process's command line names the earlier journal directory or the attempt,
         store or queries tree (one process listing; a failed or empty listing refuses). Review C1's end-of-run key,
         which a killed run never writes, is replaced for such a journal by: no file in the package or interpreter
         tree has mtime or ctime at or after the earlier run's start. R1/R2 otherwise unchanged; journaled as
         resume.release.

Fast-loop r7 = r6 (800e6277) + two changes, driver only:
  K7     decision 68: CHECK3 is journaled neutrally: reader r3 (status RECORDED plus measured values) and the journal
         key `check3` = {status RECORDED, measured values}; no NOT_ESTABLISHED/FAIL wording and no CHECK3 final
         label (the run's label is PASS). diagnostic_only true / scientific_acceptance false unless the measured
         heat peak is below the reread peak (heat_peak_below_reread_peak True). Replaces K4's labels.
  K8     Reviewer r2 ruling (DIAGNOSTIC): check_pool's largest-call condition (all configured workers computed faces)
         is journaled as heat_pool.largest_call_all_workers_computed instead of stopping.

Fast-loop r6 = r5 (1ef9203d) + one fix (Reviewer r5 F1): the all-or-none rule reads `covers` from the earlier
journal, so a resume_key difference or a step-1 reuse failure refuses too (r5 read it from the last reused step's
checkpoint, None before the first reuse, and would rerun everything and set the retained trees aside).

Fast-loop r5 = r4 (1bb1c489) + one change, driver only (Reviewer F1, q391-continuation-review-r1.md):
  K5     in continuation, once step 5's acceptance and the CHECK3 receive have passed, one checkpoint of the three
         trees (R2's form) marks every retained step passed (`covers` = steps 1-5), so a stop in steps 6-8 leaves a
         journal that resumes by R1/R2 (from step 6) instead of losing the route. A resume uses that checkpoint for
         all five steps or refuses: reusing only some would settle against a later tree state than theirs. The
         resume re-receives CHECK3 into the journaled check3-received-r2.json and must reproduce it.

Fast-loop r4 = r3 (91bc1f87) + two changes, driver only:
  K3     the CHECK3 reader is r2 (d97d45a0, Michael decision 47): a reread group of < 2 samples or a bracket shorter
         than the cadence is NOT_ESTABLISHED.
  K4     a CHECK3 comparison never stops the chain (Michael decision 48: diagnostic checks do not stop runs). PASS,
         NOT_ESTABLISHED and FAIL are journaled as check3_comparison; steps 6-8 run; the final label names a non-PASS
         status (PASS_DIAGNOSTIC_CHECK3_NOT_ESTABLISHED / PASS_DIAGNOSTIC_CHECK3_FAIL_RECORDED, diagnostic_only true,
         scientific_acceptance false). The reader's integrity refusals still stop (INVALID_EVIDENCE).

Fast-loop r3 = r2 (58a9a1fc) + two changes, driver only:
  K1     config continuation true (with resume_from): continue an r4 journal that STOPPED only at the interval CHECK3
         comparison, with steps 1-5 journaled as passed. Steps 1-5 are reused without checkpoints (r4 has none): each
         one's argv, outputs (re-hashed) and the run-wide key must match, and its acceptance reruns on the bytes on
         disk; the store and attempt trees must list exactly the files and sizes the earlier journal's storage names.
         Nothing is moved aside and no retained step reruns: any mismatch stops. The CHECK3 receive writes a NEW
         check3-received-r2.json; then steps 6-8 launch.
  K2     F3 refuses an issue record whose status is not REVIEWED (decision 45 item 1).

Fast-loop r2 = r1 (770218b2, reviewed) + W4 and review C1, driver only:
  F3     before run B can launch: issue_record (pinned, with the grid path run B reads) names the live issued-label
         pins; each literal is still at its file:line, was issued for this grid, and the
         grid hashes to GRID_SHA with the pinned graph/partition ids.
  F2/F4  on resume, before anything moves: retained receipts of reused steps carry this run's probe identity (run A)
         and its current source proof and profile sha (what each reader compares).
  C1     the resume key must also equal the earlier journal's post_checks (r13 K43: withdrawn); a post_check_failure
         reuses nothing.

Fast-loop r1 (design .atlas-dev/designs/fast-loop-r1.md W1+W2), driver only, on the q389 deferred candidate:
  F5/F6  before the first launch: disk headroom as run_fresh_interval.py:1122 demands, run B's one heat pool
         setting by the launch rule (r38; check_pool), and each remaining producer entry called without --launch
         (it builds and verifies its command, then returns: run_fresh_interval.py:1549-1552).
  R2     after each step's acceptance: the store, attempt and query trees' digests, members in <step>.checkpoint.json.
         The checkpoint is the journaled mark that a step passed.
  R1     config resume_from {path, sha256}: the earlier journal is read, never written. In order, a step is reused
         only if it is journaled exit 0 with its accepted status and a checkpoint, its argv equals the one this
         driver would launch, every journaled output re-hashes, and package tree, interpreter tree, profile sha,
         execution identity and audited environment equal the earlier journal's. The acceptance after each step
         runs unchanged on the bytes on disk; only the launch is skipped. Before the first launch the trees must
         hold every checkpointed file unchanged; anything else is a leftover: journaled with digests, then renamed
         out of the trees into <attempt parent>/resume-aside-N. Never deleted or rewritten. Resume refuses (a
         person decides) if a leftover is an adoption or verdict file or an output of a step journaled as passed,
         or if the earlier journal is RUNNING or INTERRUPTED (step processes may still run).

Additive r3c: the interval producer must cross the accepted CHECK3 recording reader before its independent reader.
The recorder/driver/pool/joined/guard identities come from the pinned profile and actual installed tree;
no journal selects executable code or authorises its own recorder/clock. Root mode keeps its original semantics.
Source/runtime/native clock/bootstrap qualification and final selected input bindings remain prerequisites.

IV1 chain r3b: one admitted ticket, the eight guarded fresh-route steps, fail closed.

    <interpreter root>/python.exe -B -I iv1_chain_r3b.py --config CHAIN-CONFIG.json --config-sha256 SHA

Order (fresh route; the build has no launcher). Both routes come from the config (r5: producer
atlas_runtime.py fresh, reader atlas_tectonics/_private/reopen_fresh_restart.py):
  1 root producer   <producer route> --mode root --launch
  2 root reader     <reader route> --mode root --launch
  3 root finalise   <reader route> --mode root --finalise
  4 root adopt      <reader route> --mode root --adopt
  5-8               the same for --mode interval (run B, seeded by run A)

r2 keeps every r1 rule and binds no build: package, interpreter, .pth, delivery, entries, routes and
the optional layout tool are all pinned in the config. New in r2: any reparse point is refused
(st_file_attributes), roots included; the package top level is exact (RT-1); RECORD maps one-to-one
onto the package tree (pip --target records scripts as ../../bin/) and duplicate rows are refused
(L3); suffix checks ignore case (L1); PYTHONUSERBASE is refused at launch (L2); the steps' python
must be a file of the pinned interpreter tree; the .pth set and its single line are checked, or
their absence required; a producer-style probe (no -I, PYTHON* stripped) must show hash seed 0,
-B, no user site-packages and sys.path inside the two trees; idle cores come from GetSystemTimes
when psutil is absent.

New in r3, for r6's heat call records (keyed on field names; mapped against the fix chat's cand-r1 pool and the
R6-1 changes of its cand-r3, see MAPPED and r3/FIELD-MAP-r1.md): the configuration must declare
ATLAS_HEAT_WORKERS_STRICT=1; run B must record heat_workers_strict true and register the 'heat-worker-fallback'
stage (run A, which advances nothing, is judged only when it records the flag); no pass may fall back (no phase
row or stage naming it; the registered name in observed_stages is not one); the pool must record no worker
problem, event or caller work, and every kept call ran strict in at least two workers (r6 pools no serial call
without a fallback, so r2's serial-by-design branch is gone); H3 rows report NOT_BOUND only while no assembly
observer is bound, and every worker that computes faces must report the compiled route (r3b: boundary-power
faces aside, below). R6-1 (strict passing with no
worker computing): a cand-r1-lineage pool leaves no record of a call that never starts workers, so its records
cannot close R6-1 and the configuration pins the heat pool member reviewed as R6-1-closed at the seal (heat_pool;
refuter F1). cand-r3 records such a call as a worker problem with an event (refused here) and raises under strict
(a FAILED receipt); the backstop stays that every configured worker computed faces in the largest call.

New in r3b (pre-review IV1-r3-1, IV1-r3-2): a worker whose faces in a call were all boundary-power (Neumann) faces
never loads H3, because the kernel returns their prescribed transfer first (kernel_r5 _face :201-205), so it reports
NOT_OBSERVED. Such workers are accepted only while together they computed no more faces than the call has Neumann
faces (faces - to_reconstruct); every other worker that computed faces must report 'compiled'. Scope: the fresh
route, whose driver registers the fallback stage. A prepared migrated interval records no observed_stages (cand-r5
prepared_interval_driver.py :422-436), so run B's stage rule refuses it; IV2+ on that route needs a chain revision.
Line references cite pool r4 144c6386 (cand-r5, the final set) and the fresh driver 1245987e (cand-r1 to cand-r5).

TC conditions (TC-DECISIONS-r1.md): no automatic retry and nothing deleted on a stop; every sha
handed on is re-hashed from disk first; a journal entry per step (command, start/end UTC, exit,
status, output shas, free RAM and cores at launch); install checks before (r13 K43: not after); pool checks
only between steps; a bounded wait for each launch's start-gate RAM. Standard library only.
"""
import argparse
import ast                                               # r32: the arm's list
import copy
import csv
import ctypes
import gzip
import hashlib
import importlib.util                                    # r39: monitor and gate
import json
import math                                              # o4: overlap config
import os
import re
import secrets                                           # o4: gate nonce
import shutil
import stat
import subprocess
import sys
import time
import traceback
import types                                             # o4: helper loading
from base64 import urlsafe_b64encode
from datetime import datetime, timezone
from pathlib import Path

CONFIG_SCHEMA = 'atlas.iv1-chain-config.r11'                           # r12: + record_failed_steps
FIRST_LAUNCH = ('7-interval-finalise', '8-interval-adopt')             # RFO: the only steps a reader-files-only resume launches
CONTINUE_FROM = 'atlas.iv1-chain-journal.r4'                           # K1: the one journal shape continued
CONTINUE_STOP = 'interval CHECK3 sampled comparison failed'            # K1: the one stop continued (r3 and earlier)
CHECK3_MEASURED = {'heat_peak_tree_rss_bytes', 'heat_samples', 'reread_peak_tree_rss_bytes', 'reread_samples',  # K7
                   'reread_bracket_ns', 'sample_interval_ns', 'comparison_decidable', 'heat_peak_below_reread_peak'}
RETAINED = ('1-root-producer', '2-root-reader', '3-root-finalise', '4-root-adopt', '5-interval-producer')
REVIEWED = 'REVIEWED'                                                  # K2: the issue record status F3 accepts
JOURNAL_SCHEMA = 'atlas.iv1-chain-journal.r6'
EARLIER_SCHEMAS = ('atlas.iv1-chain-journal.r4', 'atlas.iv1-chain-journal.r5', JOURNAL_SCHEMA)   # r4 has no checkpoints, so nothing is reused
PLACEHOLDER = '0'*64                     # run B's seed in its pre-launch call before run A exists (_seed checks form)
DRY_STATUS = 'SOURCE_BOUND_COMMAND_ONLY_NOT_ADMISSION'                 # run_fresh_interval.py:1549
WORKERS_SITE = 'atlas_tectonics/_private/integration/fresh_interval_driver.py'  # width configuration site
LIMITS_PROBE = ('import json\nfrom atlas_tectonics._private.integration import run_prepared_restart as R\n'
                'print(json.dumps({k: R.COMPACT_STORE_LIMITS[k] for k in ("max_store_bytes", "max_staging_bytes")}))')
OWNED = ('adopted-', 'reader-verdict-')  # leftovers of these names are never moved: a person decides
SAVE_TRIES, SAVE_WAIT_SECONDS = 150, .2     # 30 s: any open handle on the journal refuses the replace (WinError 5)
REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
BYTECODE = ('.pyc', '.pyo', '.pyd', '.pyw')              # compared casefolded: NTFS lookups ignore case (L1)
SCRIPTS = '../../bin/'      # pip --target RECORD rows are relative to <home>/lib/python; scripts land in <home>/bin
SEED_REUSED = ('FULL_REUSE', 'MISSES_MEASURED')          # run_fresh_interval.py:505
SEALED = {'root': 'SEALED_ROOT_AWAITING_READER', 'interval': 'SEALED_INTERVAL_AWAITING_READER'}
REOPENED = {'root': 'PASS_ROOT_REOPENED_PENDING_FINALISE', 'interval': 'PASS_INTERVAL_REOPENED_PENDING_FINALISE'}
READER_PASS = {'root': 'PASS_ROOT_INDEPENDENT_REOPEN', 'interval': 'PASS_INTERVAL_INDEPENDENT_REOPEN'}
ADOPTED = 'ADOPTED_AFTER_INDEPENDENT_READER'
NUMBER = {'root': 0, 'interval': 1, 'interval2': 2}
MODE = {'root': 'root', 'interval': 'interval', 'interval2': 'interval'}   # r21: a stage's --mode word
STAGES = ('root', 'reader-root', 'interval', 'reader-interval')
STAGES2 = ('interval2', 'reader-interval2')                            # r21: booked only with intervals 2
STRICT = 'ATLAS_HEAT_WORKERS_STRICT'                     # pool strict(): unset or '' off, '1' on, anything else fails
FALLBACK_STAGE = 'heat-worker-fallback'                  # the guard's phase when a pass falls back (driver _stages)
OBSERVERS = ('ATLAS_PLAN15_ASSEMBLY_CONTRACT', 'ATLAS_PLAN15_ASSEMBLY_CONTRACT_SHA256')   # pool _observer_bound()
BOUND_ROW = ('native_binding_costs', 'native_binding_parent')          # a bound worker's admission (pool r4 :1248-1256)
BINDING_ERRORS = ('native_binding_error', 'native_binding_cleanup_error')
MAPPED = ('cand-r1 pool 6402bfca3fa7a4ff8d71187fbf91db4cf997d84ba42233f3570768b029c587fd and driver '
          '1245987e7b2b4ea8587208589d734de7a109aa7d890dbb39237a88a05a4e4d18, with the R6-1 changes of cand-r3 pool '
          'a00568259054b8722638ab334d4c1913017aaabc99971ec293ee76f1a2424a22 (field names; r3/FIELD-MAP-r1.md); '
          're-verified against pool r4 144c6386012b2e4aec9c5d5cb8658df06925cb216265a77573343fa3f886aeb3 (cand-r5)')
FIELDS = {'schema', 'python', 'interpreter', 'package', 'pth', 'delivery', 'entries', 'routes', 'layout_check',
          'environment', 'profile', 'journal_directory', 'bookings', 'heat_workers', 'heat_pool', 'ram_wait_seconds',
          'ram_poll_seconds', 'cores_sample_seconds', 'check3', 'resume_from',
          'issue_record', 'continuation', 'resume_release', 'capture', 'record_failed_steps'}
CAPTURE_FAILURE = 'thermal-mesh-failure-01.json.gz'      # JC:406: the joined control's END failure record (run-interval)
CAPTURE_ERROR = 'issued closure or partition identity differs'          # PRV:151: the provider's own id refusal
AUDITED = ('ATLAS_', 'RUNQ_', 'OMP_', 'OPENBLAS_', 'MKL_', 'NUMEXPR_', 'PYTHONHASHSEED')  # journaled child environment
PROBE = ('import json, os, site, sys; u = site.getusersitepackages(); print(json.dumps({'
         '"executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix, "path": sys.path[1:], '
         '"hash_randomization": sys.flags.hash_randomization, "dont_write_bytecode": sys.flags.dont_write_bytecode, '
         '"enable_user_site": site.ENABLE_USER_SITE, "user_site": u, "user_site_exists": os.path.exists(u)}))')


IDENTITY_PROBE = ('import json, atlas_tectonics.integration.reuse as r\n'
                  'with r.ExecutionContext("scipy") as c: print(json.dumps(c.provenance))')


def folder(kind, stage):
    """r21: the package's run/reader folder of a stage (run_fresh_interval mode_output, reopen reader_output)."""
    n = NUMBER[stage]
    return f'{kind}-{MODE[stage]}' + ('' if n <= 1 else f'-{n:04d}')


class StepLimit(Exception):
    """r20: the configured last step passed; the chain ends here."""


class ChainStop(Exception):
    """A fail-closed stop: recorded, never retried here."""


class Paused(Exception):
    """B-2: a pause by request at a step boundary; the chain ends PAUSED."""


def require(condition, message):
    if not condition:
        raise ChainStop(message)


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def sha_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _unique(pairs):
    keys = [key for key, _ in pairs]
    require(len(keys) == len(set(keys)), 'duplicate JSON member names')
    return dict(pairs)


def read_json(path, pin=None):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    require(pin is None or digest == pin, f'{path} sha256 {digest} differs from its pin {pin}')
    return json.loads(raw, object_pairs_hook=_unique), digest


def retained_receipt_fields(path, receipt, expected):
    counts = dict.fromkeys(expected, 0)
    mismatched = set()

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in expected:
                    counts[key] += 1
                    if value != expected[key]:
                        mismatched.add(key)
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(receipt)
    for key in expected:
        require(key not in mismatched,
                f'{"F2" if key == "execution_identity" else "F4"}: {path} {key} differs from its producer proof')
    return counts


BRAND = 'NOT SCIENTIFICALLY PERMISSIBLE'          # decision 129; banner of reuse-previous-run-identity-r1.md:100-106
BANNER = ('#'*80 + '\n'
          '#  NOT SCIENTIFICALLY PERMISSIBLE                                              #\n'
          '#  This run reuses another run or reports another tree\'s execution identity.   #\n'
          '#  No result may be adopted, published or used as evidence.                    #\n'
          + '#'*80 + '\n')
BRAND_FILE = 'NOT-SCIENTIFICALLY-PERMISSIBLE.txt'


def member(node, *keys):
    for key in keys:
        node = node.get(key) if type(node) is dict else None
    return node


def profile_words(argv, path, digest):
    """P-3: the command with its profile path and hash set aside, or None if they are not exactly `path`, `digest`."""
    if type(argv) is not list or argv.count('--profile') != 1 or argv.count('--profile-sha256') != 1:
        return None
    words = list(argv)
    for flag, value in (('--profile', path), ('--profile-sha256', digest)):
        at = words.index(flag)+1
        if at >= len(words) or words[at] != value:
            return None
        words[at] = None
    return words


def spec_aside(argv):
    """o4: the command with the value after --overlap-spec set aside (None); any other command unchanged."""
    if type(argv) is not list or '--overlap-spec' not in argv:
        return argv
    words = list(argv)
    at = words.index('--overlap-spec')+1
    if at < len(words):
        words[at] = None
    return words


def is_sha(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def folded(name, suffixes):
    """Case-insensitive suffix test (L1)."""
    return name.casefold().endswith(suffixes)


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def relative(path, root):
    """The posix name of path inside the tree at root, or None when it lies outside (lexically: reparse
    points are refused inside the trees, so lexical and real containment agree there)."""
    path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
    if path == root or root not in path.parents:
        return None
    return path.relative_to(root).as_posix()


def inside(path, root):
    return same_path(path, root) or relative(path, root) is not None


def child_environment(declared):
    """Step children: no PYTHON* variable but PYTHONHASHSEED=0 (no -I/-E: the start gate needs hash seed 0), and the
    ATLAS_* variables exactly as the config declares them (r6: ATLAS_HEAT_WORKERS_STRICT); an undeclared one is refused."""
    environment = {k: v for k, v in os.environ.items() if not k.upper().startswith('PYTHON')}
    undeclared = sorted(k for k in environment if k.upper().startswith('ATLAS_') and k.upper() not in declared)
    require(not undeclared, f'undeclared ATLAS_* variables in the environment: {undeclared}')
    environment.update(declared)
    environment['PYTHONHASHSEED'] = '0'
    return environment


def refuse_reparse(path):
    """Any reparse point (symlink, junction, mount point, cloud placeholder, ...) is refused."""
    info = os.lstat(path)
    require(not info.st_file_attributes & REPARSE, f'reparse point: {path}')
    return info


_package_tree = {}                       # 777: package root -> (digest, members) of this run's package_checks


def tree_inventory(root, hashed=True):
    """Exact complete file set: {posix path: sha256}; reparse points refused everywhere, root included.
    r16 (D1): hashed=False gives {posix path: size} and opens no file.
    r36 (IH): hashed='listing' gives {posix path: [size, mtime_ns]} and opens no file."""
    root = Path(root)
    require(os.path.lexists(root), f'tree root missing: {root}')
    require(stat.S_ISDIR(refuse_reparse(root).st_mode), f'tree root is not a directory: {root}')
    members, size, pending = {}, 0, [root]
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as listing:
            names = sorted(entry.name for entry in listing)
        for name in names:
            path = folder/name
            info = refuse_reparse(path)
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
                continue
            require(stat.S_ISREG(info.st_mode), f'not a regular file: {path}')
            members[path.relative_to(root).as_posix()] = (sha_file(path) if hashed is True else
                                                          [info.st_size, info.st_mtime_ns] if hashed == 'listing'
                                                          else info.st_size)
            size += info.st_size
    return len(members), size, members


def tree_digest(root, hashed=True):
    count, size, members = tree_inventory(root, hashed=hashed)
    encoded = json.dumps(members, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest(), count, size, members


def delivery_digest(materialiser, pin, root, *, members=None):
    """The sealed delivery rule: materialiser.delivery_inventory(root), Plan26's encoding (delivery_inventory_r1.py)."""
    raw = Path(materialiser).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == pin, 'materialiser differs from its pin')
    module = type(sys)('_inventory_only')
    exec(compile(raw, str(materialiser), 'exec'), module.__dict__)
    delivery = (module.delivery_inventory(Path(root)) if members is None
                else module.delivery_inventory(Path(root), members=members))
    encoded = json.dumps(delivery, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest(), len(delivery)


def record_check(root, members, top_level):
    """RT-1: the top level is exactly top_level plus one dist-info. RECORD maps one-to-one onto the tree,
    no row twice (L3), and every row but RECORD's own carries its file's sha256 and size."""
    top = {name.split('/', 1)[0] for name in members}
    infos = sorted(name for name in top if folded(name, ('.dist-info',)))
    require(len(infos) == 1, f'the package needs exactly one dist-info folder, found {infos}')
    require(top == set(top_level) | {infos[0]}, f'package top level is {sorted(top)}, not {sorted(top_level)} plus one dist-info')
    own = f'{infos[0]}/RECORD'
    require(own in members, f'{own} is missing')
    with open(Path(root)/infos[0]/'RECORD', newline='', encoding='utf-8') as stream:
        rows = list(csv.reader(stream))
    seen, listed = set(), set()
    for row in rows:
        require(len(row) == 3, 'malformed RECORD row')
        name, digest, size = row
        name = 'bin/' + name[len(SCRIPTS):] if name.startswith(SCRIPTS) else name
        require(name.casefold() not in seen, f'duplicate RECORD row: {row[0]}')
        seen.add(name.casefold())
        listed.add(name)
        if name == own:
            require(digest == '' and size == '', 'RECORD lists a digest for itself')
            continue
        algorithm, _, value = digest.partition('=')
        require(algorithm == 'sha256' and value, f'RECORD digest of {name} is not sha256')
        require(name in members, f'RECORD names a file outside the package tree: {row[0]}')
        require(urlsafe_b64encode(bytes.fromhex(members[name])).rstrip(b'=').decode() == value and   # B7: tree_digest's hash
                str((Path(root)/name).stat().st_size) == size, f'{name} differs from RECORD')
    require(listed == set(members), f'RECORD and the package tree differ: {sorted(listed ^ set(members))[:5]}')
    return {'dist_info': infos[0], 'record_rows': len(rows), 'top_level': sorted(top)}


def package_checks(config):
    """Package tree pin, RT-1 and RECORD, no bytecode, entries are its files, delivery sealed and inside it."""
    package = config['package']
    digest, count, size, members = tree_digest(package['root'])
    _package_tree[package['root']] = (digest, members)                    # 777: package_change_checks reuses it
    require(digest == package['tree_sha256'], f'package tree {digest} differs from its frozen pin')
    record = record_check(package['root'], members, package['top_level'])
    require(not any(folded(name, BYTECODE) or '__pycache__' in name.casefold().split('/') for name in members),
            'bytecode or extension module in the package')
    for name, entry in config['entries'].items():
        require(relative(entry['path'], package['root']) in members,
                f'entry {name} is not a file of the package tree: {entry["path"]}')
        require(sha_file(entry['path']) == entry['sha256'], f'entry differs from its pin: {entry["path"]}')
    # Refuter F1: a cand-r1-lineage pool records nothing for a call that never starts workers, so only the pool's
    # code closes R6-1; the configuration pins the member reviewed as R6-1-closed (cand-r3 lineage) at the seal.
    pool = config['heat_pool']
    require(members.get(pool['member']) == pool['sha256'], f'heat pool {pool["member"]} is not the pinned R6-1-closed pool')
    delivery = config['delivery']
    require(inside(delivery['inventory_root'], package['root']),
            f'delivery inventory root is outside the package: {delivery["inventory_root"]}')
    selected = (members if 'atlas_shared' in package['top_level'] and
                same_path(delivery['inventory_root'], package['root']) else None)
    found, delivered = delivery_digest(delivery['materialiser']['path'], delivery['materialiser']['sha256'],
                                       delivery['inventory_root'], members=selected)
    require(found == delivery['sha256'], f'delivery inventory {found} differs from {delivery["sha256"]}')
    return {'tree_sha256': digest, 'files': count, 'bytes': size, **record,
            'delivery_sha256': found, 'delivery_members': delivered}


def site_pth(members):
    """.pth files Python reads from this tree: its prefix and Lib/site-packages (site.getsitepackages on Windows)."""
    found = []
    for name in members:
        folder, _, leaf = name.rpartition('/')
        if folded(leaf, ('.pth',)) and folder.casefold() in ('', 'lib/site-packages'):
            found.append(name)
    return sorted(found)


def startup_hooks(members):
    """sitecustomize/usercustomize (module or package) in the interpreter's own import folders: site runs them."""
    found = set()
    for name in members:
        lowered = name.casefold()
        for folder in ('', 'dlls/', 'lib/', 'lib/site-packages/'):
            head = lowered[len(folder):].split('/', 1)[0] if lowered.startswith(folder) else ''
            if head.split('.', 1)[0] in ('sitecustomize', 'usercustomize'):
                found.add(name)
    return sorted(found)


def interpreter_pin(root):
    """r36 (IH): the bind's pair for one interpreter copy, the full hash and the listing; the listing is made before
    and after the hash and must not move, so it describes the bytes hashed."""
    listing = tree_digest(root, hashed='listing')[0]
    digest = tree_digest(root)[0]
    require(tree_digest(root, hashed='listing')[0] == listing, f'interpreter tree changed while it was pinned: {root}')
    return {'tree_sha256': digest, 'listing_sha256': listing}


def interpreter_checks(config):
    """Interpreter tree pin, the steps' python is its file, no ._pth, exactly the configured .pth (or none).
    r36 (IH): the bind's listing stands for the full hash when equal; any difference is hashed in full."""
    root, pth, pin = config['interpreter']['root'], config['pth'], config['interpreter']
    listing, count, size, members = tree_digest(root, hashed='listing')
    if listing == pin.get('listing_sha256'):
        digest, verified = pin['tree_sha256'], 'listing'
    else:
        (digest, count, size, members), verified = tree_digest(root), 'hash'
    require(digest == pin['tree_sha256'], f'interpreter tree {digest} differs from its frozen pin')
    require(relative(config['python'], root) in members, f'python is not a file of the interpreter tree: {config["python"]}')
    require(not any(folded(name, ('._pth',)) for name in members), 'a ._pth file is present in the interpreter tree')
    hooks = startup_hooks(members)
    require(not hooks, f'startup hook modules in the interpreter tree: {hooks}')
    found = site_pth(members)
    result = {'tree_sha256': digest, 'files': count, 'bytes': size, 'pth_files': found, 'verified_by': verified,
              'listing_sha256': listing}
    if pth is None:
        require(not found, f'.pth files present where none is expected: {found}')
        return result
    require(found == [relative(pth['path'], root)], f'.pth files are {found}, expected only {pth["path"]}')
    raw = Path(pth['path']).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == pth['sha256'], '.pth differs from its pin')
    lines = [line.rstrip() for line in raw.decode('utf-8-sig').splitlines()]          # as site.py reads it
    paths = [line for line in lines if line.strip() and not line.startswith('#')]
    require(len(paths) == 1 and same_path(os.path.join(os.path.dirname(os.path.abspath(pth['path'])), paths[0]),
                                          config['package']['root']),
            f'.pth must hold exactly one line naming the package root, holds {paths}')
    return {**result, 'pth_sha256': pth['sha256']}


def probe_check(config, environment):
    """Launch the steps' python as the producers are launched (no -I, PYTHON* stripped, PYTHONHASHSEED=0):
    hash seed 0, -B, no user site-packages, prefixes and every sys.path entry inside the two trees, and the
    package root on sys.path exactly when a .pth is configured."""
    root, package = config['interpreter']['root'], config['package']['root']
    done = run_child([config['python'], '-B', '-c', PROBE], env=environment, cwd=root,
                          capture_output=True, text=True, timeout=120)
    require(done.returncode == 0, f'producer-style probe exited {done.returncode}: {done.stderr[-300:]}')
    found = json.loads(done.stdout.strip().splitlines()[-1], object_pairs_hook=_unique)
    outside = [entry for entry in found['path'] if not (inside(entry, root) or inside(entry, package))]
    on_path = any(same_path(entry, package) for entry in found['path'])
    require(found['hash_randomization'] == 0 and found['dont_write_bytecode'] == 1,
            f'producer-style probe: hash seed 0 or -B not in force: {found}')
    require(not found['user_site_exists'] and same_path(found['prefix'], root) and same_path(found['base_prefix'], root)
            and not outside, f'producer-style probe: imports can leave the pinned trees: {found}')
    require(on_path == (config['pth'] is not None),
            f'producer-style probe: package root on sys.path is {on_path}, .pth configured is {config["pth"] is not None}')
    return found


def identity_check(config, environment):
    """q389 preflight: probe and journal the staged package's execution identity (a record, compared with nothing)."""
    done = run_child([config['python'], '-B', '-c', IDENTITY_PROBE], env=environment,
                          cwd=config['interpreter']['root'], capture_output=True, text=True, timeout=120)
    require(done.returncode == 0, f'execution identity probe exited {done.returncode}: {done.stderr[-300:]}')
    lines = done.stdout.strip().splitlines()
    require(lines, 'execution identity probe printed nothing')
    found = json.loads(lines[-1], object_pairs_hook=_unique)
    require(type(found) is dict, f'execution identity probe: {found}')
    return found


def store_limits(config, environment):
    """F5: the compact store limits the producer's disk headroom check adds (run_fresh_interval.py:1122)."""
    done = run_child([config['python'], '-B', '-c', LIMITS_PROBE], env=environment,
                          cwd=config['interpreter']['root'], capture_output=True, text=True, timeout=120)
    require(done.returncode == 0, f'store limits probe exited {done.returncode}: {done.stderr[-300:]}')
    lines = done.stdout.strip().splitlines()
    found = json.loads(lines[-1], object_pairs_hook=_unique) if lines else None
    require(type(found) is dict and all(type(found.get(k)) is int and found[k] > 0
                                        for k in ('max_store_bytes', 'max_staging_bytes')), f'store limits probe: {found}')
    return found


def pool_workers(config):
    """F5 (r38, E-1): run B's fresh driver sets the heat pool once, to the width its launch computes; check_pool
    later requires every kept call to have run under the width the run recorded. A number there is r37's form."""
    text = (Path(config['package']['root'])/WORKERS_SITE).read_text(encoding='utf-8')
    found = re.findall(r'(?<![A-Za-z_])PARALLEL\.configure\(workers=(\w*)', text)
    require(len(found) == 1, f'{WORKERS_SITE} must configure the heat pool exactly once, found {found}')
    require(found[0] == 'heat_workers', f'{WORKERS_SITE} configures the heat pool with {found[0]!r}, not the launch rule '
            'heat_workers(...): a number there is driver r37\'s form')
    return 'launch'


def issue_checks(config):
    """F3 (W4): run B's live issued-label pins named by the pinned issue record still hold, in seconds instead of
    15 minutes into run B: each literal is still at its file:line, it was issued for this grid, and the grid file hashes to
    GRID_SHA with the pinned graph and partition ids.
    r37 (content pin): the grid names the reference capture's ids; the record's 'content' block ties each live id
    to them by content: for the graph and the partition, the captured id's digest equals the reference id's
    digest, both made by one reduction file, each naming the capture receipt it was measured on. A missing or
    unequal pair refuses (a value change needs the long route: new grid, new proof, new reference digests).
    Pins whose issue the record does not know (identity UNKNOWN) or off the live route are journaled, not checked."""
    part = config['issue_record']
    record, digest = read_json(part['path'], part['sha256'])
    pins, grid = record.get('pins'), record.get('grid')
    require(type(pins) is list and type(grid) is dict and is_sha(grid.get('sha256')) and is_sha(grid.get('graph_id'))
            and is_sha(grid.get('partition_id')) and type(grid.get('pinned_as')) is str, 'issue record malformed')
    require(record.get('status') == REVIEWED, f'F3: issue record status is {record.get("status")!r}, not {REVIEWED}')
    content = record.get('content')
    require(type(content) is dict and type(content.get('reduction')) is dict
            and is_sha(content['reduction'].get('sha256')), 'F3: issue record has no content block')
    for kind, grid_key in (('graph', 'graph_id'), ('partition', 'partition_id')):
        pair = content.get(kind)
        require(type(pair) is dict and all(is_sha(pair.get(k)) for k in (
                'id', 'digest', 'receipt_sha256', 'reference_id', 'reference_digest', 'reference_receipt_sha256')),
                f'F3: issue record content pair for the {kind} is missing')
        require(pair['reference_id'] == grid[grid_key], f'F3: the {kind} reference is not the grid\'s id')
        require(pair['digest'] == pair['reference_digest'], f'F3: the {kind} content differs from the reference '
                f'({pair["digest"]} != {pair["reference_digest"]}): a value change takes the long route')
    native = Path(config['package']['root'])

    def at(file, line, name, value, what):
        lines = (native/file).read_text(encoding='utf-8').splitlines()
        text = lines[line-1].strip() if type(line) is int and 0 < line <= len(lines) else ''
        require(text == f"{name} = '{value}'", f'F3: {what} {name} is no longer at {file}:{line}')

    checked, skipped = [], []
    for pin in pins:
        issue = pin.get('issue') if type(pin) is dict else None
        if not (pin.get('live_route') is True and type(issue) is dict and is_sha(issue.get('identity'))):
            skipped.append(f'{pin.get("file")}:{pin.get("line")}' if type(pin) is dict else repr(pin))
            continue
        at(pin['file'], pin['line'], pin['name'], pin['value'], 'issued pin')
        inputs = issue.get('inputs')
        require(type(inputs) is dict and inputs.get('grid_sha256') == grid['sha256'],
                f'F3: {pin["name"]} was issued for another grid')
        require(pin['value'] in (content['graph']['id'], content['partition']['id']),
                f'F3: {pin["name"]} is not the captured id the content pair binds')
        checked.append(f'{pin["file"]}:{pin["line"]} {pin["name"]}')
    require(checked, 'F3: the issue record names no live issued pin')
    sites = re.findall(r'([\w./-]+\.py):(\d+) GRID_SHA', grid['pinned_as'])
    require(sites, 'F3: the issue record names no GRID_SHA site')
    for file, line in sites:
        at('atlas_tectonics/_private/'+file, int(line), 'GRID_SHA', grid['sha256'], 'grid pin')
    data, _ = read_json(part['grid_path'], grid['sha256'])
    require(data.get('graph_id') == grid['graph_id'] and data.get('partition_id') == grid['partition_id'],
            'F3: the grid file names other graph or partition ids')
    result = {'record_sha256': digest, 'record_status': record.get('status'), 'checked': checked, 'skipped': skipped,
              'grid_sites': [f'{file}:{line}' for file, line in sites]}
    return result


def accepted(name):
    """The status a step's acceptance journals, from its name 'N-mode-kind'; None for any other name."""
    parts = name.split('-') if type(name) is str else []
    if len(parts) != 3 or parts[1] not in NUMBER:
        return None
    table = {'producer': SEALED, 'reader': REOPENED, 'finalise': READER_PASS, 'adopt': {parts[1]: ADOPTED}}
    return table[parts[2]][parts[1]] if parts[2] in table else None


def live_processes():
    """K9, F-14: every live process's id, parent id, creation time (FILETIME ticks) and command line, from one
    listing; a failed or empty listing refuses."""
    done = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                           'Get-CimInstance Win32_Process | ForEach-Object { @{p=[int64]$_.ProcessId; '
                           'q=[int64]$_.ParentProcessId; t=$(if ($_.CreationDate) { $_.CreationDate.ToFileTimeUtc() } '
                           'else { 0 }); c=[string]$_.CommandLine} } | ConvertTo-Json -Compress'],
                          capture_output=True, text=True, timeout=120)
    require(done.returncode == 0, f'K9: process listing exited {done.returncode}')
    rows = json.loads(done.stdout or 'null')
    require(type(rows) is list and len(rows) > 1, 'K9: process listing is empty')
    return [row for row in rows if type(row) is dict and type(row.get('c')) is str]


def own_line(rows):
    """F-14 (831): the ids of this process and of the processes above it; a process above is taken only if it was
    created before the one below it (a parent's id may have been used again). Not in the listing: none."""
    by_id = {row.get('p'): row for row in rows}
    mine, row = set(), by_id.get(os.getpid())
    while row is not None and row['p'] not in mine:
        mine.add(row['p'])
        parent = by_id.get(row.get('q'))
        row = parent if parent is not None and parent.get('t', 0) < row.get('t', 0) else None
    return mine


DIAGNOSTIC = 'DIAGNOSTIC_UNCERTIFIED_NO_QUALIFICATION'     # R-1, S-1: as run_fresh_interval's diagnostic_tree reads it
DRIVER_RELEASE = 'atlas.chain-release.driver.r1'          # R-1 (V-3): a release the driver wrote
PAUSE_REQUEST, PAUSE_SCHEMA, PAUSED_EXIT = 'PAUSE-REQUEST.json', 'atlas.chain-pause-request.r1', 75  # B-2; 833: not 3
SAVE_KINDS = ('step-boundary', 'measurements', 'queries', 'mesh-pieces', 'predictor', 'heat-faces', 'before-seal')  # 809
UNIT_KIND = {'S-1': 'measurements', 'U-3': 'queries', 'M-1': 'mesh-pieces', 'L-1': 'predictor', 'U-2': 'heat-faces'}
OUTSIDE_STOP_PROVED = {}     # B-1 (818, 821): kind -> {'ticket', 'arm', 'revisions': {unit: revision}}; empty until a real kill
ARM_UNITS = 'atlas_tectonics/_private/integration/geometry/endpoint_factory.py'  # source of the explicit saving-unit label
UNITS_LINE = 'SAVING_UNITS = '
MEASUREMENT_STORE = 'initial-measurements.sqlite'        # S-1: the producer's store (RFI:128)
_child_hook = [None]                                     # R-1: the chain notes each probe's identity here


def _process_snapshot(pid):
    """R-1: creation FILETIME and running state from one handle (as reader_overlap_gate._native_process_snapshot);
    None when no process has that pid. Any other failure to read it stops."""
    from ctypes import wintypes
    require(type(pid) is int and 0 < pid <= 0xFFFFFFFF, f'R-1: process id {pid!r} is not a native DWORD')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),)*4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000 | 0x00100000, False, pid)        # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
    if not handle:
        error = ctypes.get_last_error()
        require(error in (87, 1168), f'R-1: cannot open process {pid} (Win32 {error})')
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        require(kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)),
                f'R-1: cannot read the creation time of process {pid} (Win32 {ctypes.get_last_error()})')
        ticks = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
        state = kernel.WaitForSingleObject(handle, 0)
        require(ticks > 0 and state in (0, 0x102), f'R-1: process {pid} gives no creation time or exit state')
        return ticks, state == 0x102
    finally:
        kernel.CloseHandle(handle)


def process_identity(pid):
    """R-1: {pid, created_ticks} of a process this driver holds or just started (an exited child's too)."""
    snapshot = _process_snapshot(pid)
    require(snapshot is not None, f'R-1: process {pid} is gone before its identity was read')
    return {'pid': pid, 'created_ticks': snapshot[0]}


def process_alive(identity):
    """R-1 (V-2): that very process (pid and creation ticks) still runs."""
    snapshot = _process_snapshot(identity['pid'])
    return snapshot is not None and snapshot[1] and snapshot[0] == identity['created_ticks']


def is_identity(value):
    return (type(value) is dict and {'pid', 'created_ticks'} <= set(value) and
            all(type(value[k]) is int and value[k] > 0 for k in ('pid', 'created_ticks')))


def _identities_in(value):
    """Every {pid, created_ticks} inside an overlapped pair's tracking."""
    if is_identity(value):
        yield {'pid': value['pid'], 'created_ticks': value['created_ticks']}
    elif type(value) is dict:
        for item in value.values():
            yield from _identities_in(item)
    elif type(value) is list:
        for item in value:
            yield from _identities_in(item)


def recorded_identities(earlier):
    """R-1 (V-2): every identity the earlier journal recorded, and the launches it recorded none for."""
    found, unknown = [], []
    for label, value in [('driver', earlier.get('driver_identity'))] + [
            ('probe', value) for value in earlier.get('child_identities', [])]:
        (found.append(value) if is_identity(value) else unknown.append(label))
    for step in earlier['steps']:
        if 'reused_from' in step:                       # released with the journal that launched it
            continue
        if step['step'].endswith('-overlap'):
            for role in ('producer', 'reader'):
                part = step.get(role)
                if type(part) is dict and 'tracking' in part:
                    ids = list(_identities_in(part['tracking']))
                    (found.extend(ids) if ids else unknown.append(f"{step['step']}:{role}"))
        elif 'start_utc' in step:
            (found.append(step['identity']) if is_identity(step.get('identity')) else unknown.append(step['step']))
    return found, unknown


def run_child(argv, *, timeout, capture_output=False, text=False, **kwargs):
    """subprocess.run, but the child's identity is noted (and journaled) before it is waited on (R-1: probes)."""
    if capture_output:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with subprocess.Popen(argv, text=text, **kwargs) as child:
        try:
            if _child_hook[0] is not None:
                _child_hook[0](process_identity(child.pid))
            out, err = child.communicate(timeout=timeout)
        except BaseException:
            child.kill()
            child.wait()
            raise
        return subprocess.CompletedProcess(argv, child.poll(), out, err)


def diagnostic_profile(profile):
    """R-1, S-1: the profile says a diagnostic tree (rulings 4a, 27). Unreadable: not diagnostic."""
    try:
        return profile['qualification_status'] == DIAGNOSTIC
    except (KeyError, TypeError):
        return False


def newest_before(root, started_utc, label):
    """K9: no file in the tree written or created at or after the earlier run's start; the newest time."""
    latest = max(max(s.st_mtime, s.st_ctime) for s in (p.stat() for p in Path(root).rglob('*') if p.is_file()))
    require(latest < datetime.fromisoformat(started_utc).timestamp(),
            f'K9: a file in the {label} tree was written at or after the earlier run started')
    return datetime.fromtimestamp(latest, timezone.utc).isoformat()


def _key(text):
    return os.path.normcase(text).replace(chr(92), '/')


def release_checks(config, earlier, digest, trees, profile, config_sha):
    """K9 / R-1: a pinned person's release record naming this journal, or (R-1b, diagnostic tree, no capture) none and
    every identity the earlier journal recorded gone; then no live process names its trees, and no file in the
    interpreter tree was written or created at or after the earlier run's start. The package tree's test (or the
    package change checks in its place, R-1a) runs after the resume key: Chain.package_release."""
    if config['resume_release'] is not None:
        record, record_sha = read_json(config['resume_release']['path'], config['resume_release']['sha256'])
        require(type(record) is dict and record.get('schema') == 'atlas.chain-release.r1' and
                record.get('journal_sha256') == digest and
                all(type(record.get(k)) is str and record[k] for k in ('ticket', 'killed_utc', 'reason')),
                'K9: the release record does not name this journal')
        release = {'written_by': 'person', 'record': {'path': config['resume_release']['path'], 'sha256': record_sha},
                   'ticket': record['ticket'], 'killed_utc': record['killed_utc']}
    else:
        require(diagnostic_profile(profile) and not config['capture'],
                f'resume_from journal is {earlier.get("status")}: step processes may still run; a person decides '
                '(R-1: the driver releases a diagnostic chain without capture only)')
        identities, unknown = recorded_identities(earlier)
        require(not unknown, f'R-1: launched with no recorded process identity: {unknown[:3]}: a person decides')
        alive = [identity for identity in identities if process_alive(identity)]
        require(not alive, f'R-1: {len(alive)} recorded process(es) still alive: {alive[:2]}: a person decides')
        release = {'written_by': 'driver', 'identities_tested': len(identities)}
        identities_tested = identities
    names = ([str(Path(config['resume_from']['path']).parent)] + [str(root) for root in trees.values()] +
             [config['package']['root'], config['interpreter']['root']])              # F-14: the home's two roots
    keys = [_key(os.path.normpath(name)) for name in names]
    listed_utc = utc()
    rows = live_processes()
    mine = own_line(rows)
    alive = [row['c'] for row in rows if row.get('p') not in mine and any(key in _key(row['c']) for key in keys)]
    require(not alive, f'K9: {len(alive)} live process(es) still name the earlier trees: a person decides')
    release.update(live_processes_naming_trees=0, left_out_own_line=sorted(mine), earlier_started_utc=earlier['started_utc'],
                   newest_file_utc={'interpreter': newest_before(config['interpreter']['root'], earlier['started_utc'],
                                                                 'interpreter')})
    if release['written_by'] == 'driver':                       # V-3: written to the journal folder at the start
        release['driver_record'] = {'schema': DRIVER_RELEASE, 'journal_sha256': digest,
                                    'resumed_by': {'config_sha256': config_sha, 'journal_directory': config['journal_directory']},
                                    'listing_utc': listed_utc, 'identities_tested': identities_tested}
    return release


def judge_capture(path, issue_part):
    """CAP: a capture's ending (acceptance check). (True, block) only if the failure record is a regular file, decodes as
    the operands probe decodes it (PRB:28-31), holds the provider's own id refusal, and its graph or partition id
    differs from the issue record's. Any failure or exception: (False, block with the reason)."""
    path = Path(path)
    block = {'path': str(path)}
    try:
        record, _ = read_json(issue_part['path'], issue_part['sha256'])
        block.update(old_graph_id=record['grid']['graph_id'], old_partition_id=record['grid']['partition_id'])
        require(path.is_file() and not path.is_symlink(), f'capture: no regular failure record at {path}')
        block.update(sha256=sha_file(path), bytes=path.stat().st_size)
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            data = json.load(stream)
        error = data.get('error') if type(data) is dict else None
        require(error == CAPTURE_ERROR, f"capture: the failure record's error is {error!r}, not the id refusal")
        graph = data['closed_graph']
        require(type(graph) is dict and is_sha(graph.get('partition_id')) and type(graph.get('support_ids')) is list,
                'capture: the failure record holds no closed graph with a partition id and support ids')
        canonical = json.dumps(graph, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        block.update(error=error, graph_id=hashlib.sha256(canonical).hexdigest(),
                     graph_id_source='sha256 of the canonical text of closed_graph',
                     partition_id=graph['partition_id'], partition_id_source='closed_graph.partition_id',
                     support_ids=len(graph['support_ids']))
        require(block['graph_id'] != block['old_graph_id'] or block['partition_id'] != block['old_partition_id'],
                "capture: the failure record's ids equal the issue record's: nothing captured")
    except Exception as error:  # noqa: BLE001 - a judging that raises is a failed capture; the journal is saved
        block['reason'] = f'{type(error).__name__}: {error}'
        return False, block
    return True, block


def passed_in(entry):
    """Journaled as passed: exit 0 and its accepted status (r4 journals included; reuse also needs a checkpoint)."""
    return type(entry) is dict and entry.get('exit') == 0 and entry.get('status') == accepted(entry.get('step'))


def leftover_units(root, before):
    """Outermost names under root that hold no file of the checkpoint (before: posix name -> sha256)."""
    kept = {'/'.join(name.split('/')[:i]) for name in before for i in range(1, name.count('/')+1)}
    units, pending = [], ['']
    while pending:
        folder = pending.pop()
        with os.scandir(Path(root)/folder) as listing:
            names = sorted(entry.name for entry in listing)
        for name in names:
            child = f'{folder}/{name}' if folder else name
            if child in kept:
                pending.append(child)
            elif child not in before:
                units.append(child)
    return sorted(units)


def layout_check(config, environment, out):
    """Optional pinned Plan20 layout tool (r5: layout_check_r1.py): exit 0, printed status PASS, record written."""
    check = config['layout_check']
    if check is None:
        return None
    script = check['script']
    require(sha_file(script['path']) == script['sha256'], 'layout check tool differs from its pin')
    done = run_child([check['python'], '-I', '-B', script['path'], '--out', str(out), *check['args']],
                          env=environment, capture_output=True, text=True, timeout=600)
    lines = done.stdout.strip().splitlines()
    printed = json.loads(lines[-1], object_pairs_hook=_unique) if lines else {}
    require(done.returncode == 0 and printed.get('status') == 'PASS' and out.is_file(),
            f'layout check did not pass: {printed.get("failures") or done.stderr[-300:]}')
    return {'record': str(out), 'record_sha256': sha_file(out), 'printed': printed}


def install_checks(config, when, *, profile=None, source_selection=None):
    """Pre- and post-run checks of the pinned layout (TC condition 3; pre-review a-c; RT-1; L1-L3)."""
    require('PYTHONUSERBASE' not in os.environ, 'PYTHONUSERBASE is set: unset it before launch (L2)')
    environment = child_environment(config['environment'])
    result = {'package': package_checks(config), 'interpreter': interpreter_checks(config),
            'probe': probe_check(config, environment),
            'execution_identity': identity_check(config, environment),
            'layout_check': layout_check(config, environment, Path(config['journal_directory'])/f'layout-{when}.json')}
    if profile is None:
        profile, _ = read_json(config['profile']['path'], config['profile']['sha256'])
    result['check3_selection'] = check3_bindings(config, profile, source_selection=source_selection)
    machine_modules(config)            # r39: the tree's monitor and gate load before any launch
    return result


_machine = {}                            # (package root, tree pin) -> selected monitor and gate


def machine_modules(config):
    """Compile the two selected machine modules once from the checked package."""
    package = config['package']
    root, pin = package['root'], package['tree_sha256']
    key = (root, pin)
    if key not in _machine:
        checked = _package_tree.get(root)
        require(checked is not None and checked[0] == pin, 'machine sources need a checked package tree')
        _machine[key] = shared_modules(root, ('atlas_shared.machine.resources_monitor',
                                              'atlas_shared.machine.resources_gate'))
    return _machine[key]


def machine_at_launch(config):
    """One monitor reading over the configured sample and its free cores by the one rule; journaled, read by none."""
    MM, RG = machine_modules(config)
    machine = MM.reading(seconds=config['cores_sample_seconds'])
    return {**machine, 'free_cores': RG.free_cores(machine, machine['physical_cores'])}


def wait_for_ram(MM, need, limit, poll):
    started = time.monotonic()
    while True:
        available = MM.free_memory()
        if available >= need:
            return round(time.monotonic()-started, 3), available
        require(time.monotonic()-started < limit, f'RAM_WAIT_TIMEOUT: {available} B available < {need} B after {limit} s')
        time.sleep(poll)


def find_key(node, key):
    found = []
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                found.append(value)
            found.extend(find_key(value, key))
    elif isinstance(node, list):
        for value in node:
            found.extend(find_key(value, key))
    return found


def parent_bound(config):
    """The pool binds the Plan15 assembly observer when either contract variable is set (pool r4 :1233-1239);
    the chain passes on only declared ATLAS_* names, so the configuration decides."""
    return any(name in config['environment'] for name in OBSERVERS)


def fallback_rows(node, path='receipt'):
    """Where the receipt names the fallback stage: the guard's phase() appends a phases row and sets stage."""
    found = []
    if isinstance(node, dict):
        if node.get('name') == FALLBACK_STAGE or node.get('stage') == FALLBACK_STAGE:
            found.append(path)
        for key, value in node.items():
            found.extend(fallback_rows(value, f'{path}.{key}'))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(fallback_rows(value, f'{path}[{index}]'))
    return found


def check_heat_record(receipt, mode):
    """r6 producer receipt (fresh driver :235, :323): strict heat workers recorded, and no pass fell back to the
    caller. The fallback stage is always listed in observed_stages (driver _stages); only a phase row means one did."""
    if mode == 'interval' or 'heat_workers_strict' in receipt:
        require(receipt.get('heat_workers_strict') is True, f'run {mode} does not record strict heat workers')
    if mode == 'interval':
        # Refuter F4: the detector below can fire only where the driver registered the stage (fresh driver :360-361).
        stages = receipt.get('observed_stages')
        require(type(stages) is list and FALLBACK_STAGE in stages,
                f'run B does not register the {FALLBACK_STAGE} stage, so a fallback could go unrecorded')
    rows = fallback_rows(receipt)
    require(not rows, f'run {mode} records a heat-worker fallback at {rows}')


def check_rows(rows, bound):
    """H3 rows (pool r4 :1527-1538, :1233-1239): a compiled kernel reports NOT_BOUND only while no assembly
    observer is bound. The bound branch is read from code, not run (FIELD-MAP-r1.md 3.4): re-verify before a bound IV1."""
    for row in rows:
        require(not any(key in row for key in BINDING_ERRORS), 'a heat worker records a native binding error')
        route = row.get('candidate_heat_route')
        if type(route) is dict and route.get('route') == 'compiled':
            observation = route.get('assembly_observation')
            status = observation.get('status') if type(observation) is dict else None
            require(status == ('OBSERVED' if bound else 'NOT_BOUND'),
                    f'a compiled heat worker reports {status} while the assembly observer is {"" if bound else "not "}bound')
        admitted = [key for key in BOUND_ROW if key in row]
        if bound:
            require(not row.get('faces') or len(admitted) == len(BOUND_ROW),
                    'a bound heat worker computed faces without its admission row keys')
        else:
            require(not admitted, f'a heat worker row carries {admitted} although no assembly observer is bound')


def check_pool(receipt, bound):
    """Heat pool report of a finished run B (TC D-IV1-2) in r6's records: computed in workers, strict, no fallback,
    no worker problem or event, no caller work."""
    reports = find_key(receipt, 'heat_first_pass')
    require(len(reports) == 1 and type(reports[0]) is dict, 'run B must record exactly one heat_first_pass report')
    report = reports[0]
    totals, calls = report.get('totals'), report.get('calls')
    workers = report.get('workers')    # r38 E-3: the width this launch set, as the run recorded it
    require(type(workers) is int and workers >= 2,
            f'the launch set the heat pool to {workers!r} workers: below two the heat ran in the caller. The science '
            f'is unaffected (the same faces, computed serially); this run cannot show the pool, so rerun on a freer host')
    require(type(totals) is dict and type(calls) is list and calls, 'pool report lacks totals or calls')
    assert isinstance(totals, dict) and isinstance(calls, list)          # narrowing only; require() raised otherwise
    fields = ('calls', 'faces', 'collected', 'in_caller', 'fallbacks', 'restarts')
    require(all(type(totals.get(name)) is int for name in fields), f'pool totals must hold integer {fields}')
    require(totals['fallbacks'] == 0 and totals['restarts'] == 0 and report.get('fallbacks') == [],
            'heat pool fell back or restarted')
    # R6-1: cand-r3 records a call that never starts workers (unmetered, failed meter, ledger below 2) only as a
    # worker problem with an event, never as a call (FIELD-MAP-r1.md 4.4); a started pass's problem counts there too.
    problems = report.get('worker_problems')
    require(type(problems) is int and problems == 0 and report.get('worker_events') == [],
            f'the heat pool records {problems} worker problems, events {report.get("worker_events")}')
    require(totals['faces'] == totals['collected'], 'pool collected fewer faces than it was given')
    # The caller computes a pooled face only after a fallback or a worker problem (pool r4 :1045, :1054), so with
    # neither allowed none may remain, whether or not every call was kept (only the last 16 are, pool r4 :187).
    require(totals['in_caller'] == 0, 'pool totals show faces computed in the caller')
    used, worker_faces, largest = [], [], None
    for call in calls:
        require(call.get('fallback') is None and call.get('second_fallback') is None and
                call.get('worker_traceback') is None and call.get('restarted') is False, 'a heat call fell back')
        require(call.get('strict') is True, 'a heat call ran without strict heat workers')
        require(call.get('configured') == workers,    # r38 E-3: one launch, one width
                f'a heat call ran under {call.get("configured")!r} workers, not the launch\'s {workers}: the pool was set twice')
        processes, count = call.get('processes'), call.get('workers')
        # r6 pools a call with fewer than two workers only with a fallback (pool r4 :1021) and never hands it a
        # small face set (kernel_r5.py:325-333), so r2's serial-by-design branch is gone. workers(budget, faces) may
        # size a call below the setting (pool r4 :245-289); each call must use all it started.
        require(type(count) is int and 2 <= count <= workers and type(processes) is list and len(processes) == count,
                'a heat call did not run every worker it started')
        faces = [row.get('faces') for row in processes]
        require(all(type(value) is int and value >= 0 for value in faces) and any(faces),
                'a heat call lacks per-worker face counts')
        # Faces go one at a time to whichever worker is ready; one still starting when a short call ends computes
        # nothing and is ended by the caller (pool r4 :634 records ended_by_caller as forced and not ended by
        # itself): only such a worker may exit non-zero.
        # S-6: a cap/integrity test of the pool's own workers, not of how an earlier step ended: it stays stopping.
        require(all(row.get('exit_code') == 0 or (row.get('faces') == 0 and row.get('ended_by_caller') is True)
                    for row in processes), 'a heat worker exited non-zero')
        require(call.get('in_caller') == 0 and sum(faces) == call.get('collected'),
                'the caller computed faces the workers should have')
        check_rows(processes, bound)
        # Refuter F2, tightened by the smoke and pre-review IV1-r3-1: check_rows judges compiled routes only. A worker
        # reports its route after each face it computes (pool r4 :1658-1676) and loads H3 only to certify a face, so
        # one whose faces were all boundary-power (Neumann) faces reports NOT_OBSERVED (kernel_r5 _face :201-205).
        # Any other route ('unavailable: ...', OBSERVATION_FAILED, none) ran outside the compiled H3 route or hid it.
        # NOT_OBSERVED workers together may hold no more faces than the call's Neumann faces (faces - to_reconstruct,
        # pool r4 :953-954, :1007-1009); every kept call has faces to reconstruct, so then at least one worker per
        # call reports 'compiled'. The fix chat's r6d cells (2 and 8 workers on 36 faces) show every worker compiled.
        reported = [row['candidate_heat_route'] if type(row.get('candidate_heat_route')) is dict else None
                    for row in processes if row.get('faces')]
        require(all(type(route) is dict and route.get('route') in ('compiled', 'NOT_OBSERVED') for route in reported),
                'a heat worker computed faces without reporting the compiled heat route')
        given, wanted = call.get('faces'), call.get('to_reconstruct')
        require(type(given) is int and type(wanted) is int and 0 < wanted <= given,
                'a heat call lacks its face and reconstruction counts')
        unobserved = sum(row['faces'] for row in processes
                         if row.get('faces') and row['candidate_heat_route'].get('route') == 'NOT_OBSERVED')
        require(unobserved <= given - wanted,
                f"heat workers that never loaded H3 computed {unobserved} faces, more than the call's "
                f'{given - wanted} boundary-power faces')
        used.append(count)
        worker_faces.append(faces)
        if largest is None or call['collected'] > largest['collected']:
            largest = call
    assert largest is not None                                          # calls is non-empty and each one ran here
    # TC 23:4x and the R6-1 backstop: every configured worker computed faces in the largest call, where all are
    # ready long before it ends. A run whose heat stayed in the caller has no kept call and stopped above.
    # K8: diagnostic (how the pool was used, not what it computed; a call sized below the setting is lawful): journaled.
    largest_all = largest['workers'] == workers and all(row['faces'] > 0 for row in largest['processes'])
    routes = {}
    for call in calls:
        for row in call['processes']:
            route = row.get('candidate_heat_route')
            observation = route.get('assembly_observation') if type(route) is dict else None
            key = (f'{route.get("route")}/{observation.get("status") if type(observation) is dict else None}'
                   if type(route) is dict else repr(route))
            routes[key] = routes.get(key, 0) + 1
    return {'workers': workers, 'calls_total': totals['calls'], 'calls_kept': len(calls), 'workers_per_call': used,
            'faces_per_worker': worker_faces, 'in_caller_total': totals['in_caller'], 'worker_problems': problems,
            'all_calls_kept': totals['calls'] == len(calls), 'faces': totals['faces'], 'assembly_observer_bound': bound,
            'route_counts': routes, 'largest_call_all_workers_computed': largest_all}


def check_receipt(path, status, *, pin, prior, seeded=False):
    """prior(ok, what): place 2, the status tests (decision 285); production_acceptance stays a refusal."""
    receipt, digest = read_json(path, pin=pin)
    prior(receipt.get('status') == status, f'{path} status {receipt.get("status")} is not {status}')
    prior(receipt.get('errors') == [] and receipt.get('final_reserved_bytes') == 0,
          f'{path} records errors or retained reservations')
    require(receipt.get('production_acceptance') is False, f'{path} production_acceptance is not False')
    if seeded:
        reused = receipt.get('reused_initial_cache')
        require(type(reused) is dict and reused.get('status') in SEED_REUSED and
                reused.get('counts_agree_with_bytes') is True, 'run B did not reuse run A measurements cleanly')
    return receipt, digest


CHECK3_READER_SHA = 'a1d71a3d4e5abf8adc2467280d2f831ffa0228e6e544d0592b5092d152e291a8'   # r17: reader r4 (K7 was r3, K3 r2)
CHECK3_CLOCK = 'time.monotonic_ns; same-host system monotonic clock'
CHECK3_PHASES = (
    'actual-composed-heat-forward', 'heat-low-predictor', 'heat-certified-polygon-reconstruction',
    'heat-worker-fallback', 'heat-conservative-finish', 'heat-finish-correction',
    'heat-finish-closed-guard', 'heat-finish-issue', 'heat-native-projection',
    'heat-projection-decode', 'heat-projection-exact', 'heat-result-packaging',
    'heat-checkpoint-save', 'heat-exterior-finish', 'endpoint-store-publish')
CHECK3_R3_PHASES = (*CHECK3_PHASES[:13], 'heat-checkpoint-r3-checks', *CHECK3_PHASES[13:])
CHECK3_SOURCE_NAMES = {
    'driver': 'atlas_tectonics/_private/integration/fresh_interval_driver.py',
    'pool': 'atlas_tectonics/_private/integration/heat/functionals_parallel.py',
    'joined': 'atlas_tectonics/_private/private_heat_original_joined_r8.py',
}


def check3_member(member, path):
    require(member == path, f'CHECK3 selected member differs: {path}')


def check3_config(config):
    part = shape(config['check3'], {'reader', 'recorder_member', 'guard_member', 'source_members',
                                   'heat_phases', 'clock'}, 'check3')
    pinned(part['reader'], 'CHECK3 reader')
    require(Path(part['reader']['path']).is_absolute() and part['reader']['sha256'] == CHECK3_READER_SHA,
            'CHECK3 reader is not the absolute accepted receiving source')
    check3_member(part['recorder_member'], 'atlas_tectonics/_private/integration/heat/check3_recording.py')
    check3_member(part['guard_member'], 'atlas_tectonics/_private/integration/heat/continuation_guard.py')
    shape(part['source_members'], set(CHECK3_SOURCE_NAMES), 'CHECK3 source members')
    for role, path in CHECK3_SOURCE_NAMES.items():
        check3_member(part['source_members'][role], path)
    require(type(part['heat_phases']) is list and tuple(part['heat_phases']) in (CHECK3_PHASES, CHECK3_R3_PHASES),
            'CHECK3 phase list is not the selected driver inventory')
    require(part['clock'] == CHECK3_CLOCK, 'CHECK3 selected same-host clock differs')
    return part


def check3_ordinary_file(path):
    require(Path(path).is_absolute(), 'CHECK3 requires absolute selected paths')
    path = Path(os.path.abspath(path))
    require(stat.S_ISREG(refuse_reparse(path).st_mode), f'CHECK3 file is not regular: {path}')
    for parent in path.parents:
        require(stat.S_ISDIR(refuse_reparse(parent).st_mode), f'CHECK3 ancestor is not ordinary: {parent}')
    return path


def profile_source_selection(config, profile):
    """Resolve the workspace and the native root for this profile."""
    require(type(profile.get('workspace')) is str and Path(profile['workspace']).is_absolute(),
            'CHECK3 requires the absolute selected workspace')
    workspace = Path(os.path.abspath(profile['workspace']))
    native = Path(os.path.abspath(workspace / profile['native_root']))
    require(same_path(native, config['package']['root']) and inside(native, workspace),
            'CHECK3 native root differs from selected installed package/workspace')
    return workspace, native


def check3_bindings(config, profile, *, source_selection=None):
    """Independent profile/runtime selection, never authority copied from a journal."""
    part = check3_config(config)
    if source_selection is None:
        source_selection = profile_source_selection(config, profile)
    _, native = source_selection

    def selected(member):
        path = check3_ordinary_file(native / member)
        require(inside(path, native), 'CHECK3 selected source escapes native root')
        return {'path': str(path), 'sha256': sha_file(path)}

    recorder = selected(part['recorder_member'])
    guard_source = selected(part['guard_member'])
    reached = [selected(part['source_members'][role]) for role in CHECK3_SOURCE_NAMES]
    require(len({row['path'] for row in reached}) == len(CHECK3_SOURCE_NAMES),
            'CHECK3 selected reached sources repeat a path')
    reader_path = check3_ordinary_file(part['reader']['path'])
    require(sha_file(reader_path) == part['reader']['sha256'], 'CHECK3 accepted reader source changed')
    return {'recorder': recorder, 'guard_source': guard_source,
            'sources': {row['path']: row['sha256'] for row in reached},
            'heat_phases': part['heat_phases'], 'clock': part['clock'],
            'reader': {'path': str(reader_path), 'sha256': part['reader']['sha256']}}


def check3_artifacts(receipt_path):
    path = Path(receipt_path)
    return {'guard': path.with_suffix('.guard.json'),
            'producer_journal': path.with_suffix('.check3-producer.jsonl'),
            'sample_journal': path.with_suffix('.check3-samples.jsonl')}


def guard_within_receipt(config, guard, receipt):
    """CHECK3: the in-run guard is no weaker than the limits its own receipt records, and its floor the gate's."""
    _, RG = machine_modules(config)
    limits, held = guard.get('limits'), receipt.get('guard_limits')
    require(type(limits) is dict and type(held) is dict and type(limits.get('rss_bytes')) is int
            and type(held.get('rss_bytes')) is int and 0 < limits['rss_bytes'] <= held['rss_bytes']
            and type(limits.get('free_floor_bytes')) is int and limits['free_floor_bytes'] >= RG.FLOOR_BYTES,
            'CHECK3 guard weakens the resource policy its receipt records')


def receive_check3(config, binding, profile_sha, receipt_path, receipt, captured, *, execution_identity):
    """Authenticate the actual final producer/guard records, then cross the accepted reader boundary."""
    identities = receipt.get('identities')
    require(type(identities) is dict and identities.get('producer_identity') == profile_sha
            and identities.get('runtime_identity') == execution_identity,
            'CHECK3 producer does not bind selected profile and execution identity')
    path = check3_ordinary_file(receipt_path)
    producer_pin = captured.get(str(Path(receipt_path)))
    require(is_sha(producer_pin), 'CHECK3 producer receipt changed after capture')
    producer_bytes = path.read_bytes()
    require(hashlib.sha256(producer_bytes).hexdigest() == producer_pin, 'CHECK3 producer receipt changed after capture')
    on_disk = json.loads(producer_bytes, object_pairs_hook=_unique)
    require(on_disk == receipt, 'CHECK3 producer in-memory receipt differs from captured bytes')
    artifacts = check3_artifacts(receipt_path)
    for role, artifact in artifacts.items():
        check3_ordinary_file(artifact)
        pin = captured.get(str(artifact))
        changed = f'CHECK3 required producer/guard artifact changed after capture: {artifact}'
        require(is_sha(pin), changed)
        if role == 'guard':
            guard_bytes = artifact.read_bytes()
            guard_sha = hashlib.sha256(guard_bytes).hexdigest()
            require(guard_sha == pin, changed)
        else:
            require(sha_file(artifact) == pin, changed)
    guard = json.loads(guard_bytes, object_pairs_hook=_unique)
    supervisor = receipt.get('supervisor')
    require(type(supervisor) is dict and type(supervisor.get('receipt')) is str
            and same_path(supervisor['receipt'], artifacts['guard'])
            and type(guard.get('guardian')) is dict
            and type(guard['guardian'].get('pid')) is int and guard['guardian']['pid'] > 0
            and supervisor.get('pid') == guard['guardian']['pid']
            and supervisor.get('limits') == guard.get('limits')
            and supervisor.get('ownership') == guard.get('ownership'),
            'CHECK3 final guard differs from authenticated producer supervisor binding')
    nonce, parent = guard.get('nonce'), guard.get('parent')
    require(guard.get('schema') == 'atlas.private.continuation-guard.r3'
            and type(nonce) is str and len(nonce) == 32 and all(c in '0123456789abcdef' for c in nonce)
            and type(parent) is dict and set(parent) == {'pid', 'created_ticks'}
            and all(type(parent[k]) is int and parent[k] > 0 for k in parent)
            and parent['pid'] != guard['guardian']['pid']
            and guard.get('sample_interval') == .25,
            'CHECK3 final guard identity/schema/cadence differs')
    guard_within_receipt(config, guard, receipt)
    producer_ref, sample_ref = receipt.get('check3_producer'), guard.get('check3_samples')
    for reference, target in ((producer_ref, artifacts['producer_journal']),
                              (sample_ref, artifacts['sample_journal'])):
        require(type(reference) is dict and set(reference) == {'path', 'sha256', 'records', 'complete', 'schema'}
                and type(reference.get('path')) is str and same_path(reference['path'], target)
                and reference.get('sha256') == captured[str(target)], 'CHECK3 journal is not the captured actual output')

    # Compile only the independently pinned accepted reader bytes. No journal authorises executable code.
    reader_path = Path(binding['reader']['path'])
    raw = reader_path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == CHECK3_READER_SHA, 'CHECK3 reader changed before loading')
    namespace = {'__file__': str(reader_path), '__name__': '_plan31_check3_receiving'}
    exec(compile(raw, str(reader_path), 'exec'), namespace)
    result = namespace['evaluate'](producer_ref, sample_ref, guard,
        expected_nonce=nonce, expected_parent=parent,
        expected_heat_phases=binding['heat_phases'], expected_sources=binding['sources'],
        expected_recorder=binding['recorder'], expected_clock=binding['clock'])
    for artifact in (path, *artifacts.values()):
        require(sha_file(artifact) == captured[str(artifact)], 'CHECK3 actual artifact changed during receiving')
    measured = result.get('measured')
    require(result.get('schema') == 'atlas.check3.sampled-result.r2' and result.get('status') == 'RECORDED'   # K7
            and type(measured) is dict and set(measured) == CHECK3_MEASURED
            and measured['heat_peak_below_reread_peak'] in (True, False, None)
            and result.get('sampled_only') is True and result.get('continuous_peak_guarantee') is False
            and result.get('scientific_acceptance') is False, 'CHECK3 reader result contract differs')
    return {'schema': 'atlas.iv1-chain-check3-receiving.r1', 'selection': binding,
            'producer': {'path': str(path), 'sha256': producer_pin},
            'guard': {'path': str(artifacts['guard']), 'sha256': guard_sha},
            'producer_journal': producer_ref, 'sample_journal': sample_ref,
            'expected_nonce': nonce, 'expected_parent': parent, 'result': result}



class Chain:
    def __init__(self, config, config_sha, config_path, *, home_admission=None, checked_profile=None):
        self.config, self.config_sha, self.config_path = config, config_sha, config_path
        self.home_admission = home_admission
        if checked_profile is None:
            profile, self.profile_sha = read_json(config['profile']['path'], config['profile']['sha256'])
            self.source_selection = None
        else:
            profile, self.source_selection = checked_profile
            self.profile_sha = config['profile']['sha256']
        self.profile = profile
        self.profile_path = config['profile']['path']
        workspace = Path(profile['workspace'])
        self.attempt = Path(profile['output_directory'])
        self.store = Path(profile['store_directory'])
        self.queries = workspace/profile['completed_query_directory']
        self.journal_dir = Path(config['journal_directory'])
        self.env = {}                                   # built after the pre-checks, inside the journaled try
        self.journal = {'schema': JOURNAL_SCHEMA, 'config_sha256': config_sha, 'profile_sha256': self.profile_sha,
                        'chain_sha256': sha_file(__file__), 'records_mapped_against': MAPPED, 'started_utc': utc(),
                        'steps': [], 'status': 'RUNNING', 'driver_identity': process_identity(os.getpid()),
                        'child_identities': []}                                 # R-1: from the start
        _child_hook[0] = self.note_child
        self.key_differs = False                        # S-1: the resume key differed (stop_reuse from resume_key)
        self.trees = {'attempt': self.attempt, 'store': self.store, 'queries': self.queries}
        self.launched, self.checkpoint, self.earlier, self.reusable = False, None, None, {}
        self.released = False
        self.overlap_stages = config['overlap']['stages'] if 'overlap' in config else []   # o4
        self.whole = None                               # o4: the pair whose producer was reused; its reader must be too
        self.run_log = None
        self.producer_profile_words = self.reader_profile_words = ()
        self.package_change = None                     # RP: set by resume_key when the rule applies
        self.mixed_restart = None
        self.admission_changes = set()
        self.reused_recorded = []                      # R-3: steps reused as recorded (place 3)
        self.pause_proved, self.brand_checked = False, False   # B-2, B-1
        self.torn = []                                 # 821: outputs of a reused step that failed their digest
        self.continuation = config['continuation']
        resume = config['resume_from']
        if resume is not None:
            earlier, digest = read_json(resume['path'], resume['sha256'])
            steps = earlier.get('steps') if type(earlier) is dict else None
            require(type(steps) is list and earlier.get('schema') in EARLIER_SCHEMAS and
                    all(type(s) is dict and type(s.get('step')) is str for s in steps) and
                    len({s['step'] for s in steps}) == len(steps), 'resume_from is not a chain journal')
            self.released = earlier.get('status') in ('RUNNING', 'INTERRUPTED')
            release = release_checks(config, earlier, digest, self.trees, profile, config_sha) if self.released else None
            self.earlier, self.resume_dir = earlier, Path(resume['path']).parent
            self.reusable = {s['step']: s for s in steps}
            self.journal['resume'] = {'from': {'path': resume['path'], 'sha256': digest}, 'reused': [],
                                      'rerun_from': None, 'reason': None}
            if release is not None:
                self.journal['resume']['release'] = release
        if self.continuation:
            old = self.earlier
            require(old.get('schema') == CONTINUE_FROM, f'continuation reads only an {CONTINUE_FROM} journal')
            require(old.get('status') == 'STOPPED' and old.get('stop') == CONTINUE_STOP,
                    f'continuation needs a journal stopped only by "{CONTINUE_STOP}"')
            require(tuple(s['step'] for s in old['steps']) == RETAINED and all(passed_in(s) for s in old['steps']),
                    f'continuation needs exactly steps {RETAINED} journaled as passed')
            require(type(old.get('storage')) is dict and
                    {str(self.store), str(self.attempt)} <= set(old['storage']),
                    'continuation: the earlier journal lists no storage for the store and attempt trees')

    def stop_reuse(self, reason):
        """This step and every later one rerun."""
        if self.continuation:                                   # K1: a retained step never reruns
            raise ChainStop('continuation refuses: '+reason)
        covers = next((s['checkpoint']['covers'] for s in (self.earlier or {}).get('steps', [])   # r6: also before
                       if type(s) is dict and type(s.get('checkpoint')) is dict and 'covers' in s['checkpoint']), None)
        if covers and covers[-1] not in self.journal['resume']['reused']:     # K5: all covered steps or none
            raise ChainStop(f'resume refuses: one continuation checkpoint covers {covers}; '+reason)
        if self.reusable:
            self.journal['resume']['reason'] = reason
        self.reusable = {}

    def resume_key(self):
        """R1's run-wide key: package and interpreter trees, profile, execution identity, audited environment, each
        equal at the earlier run's start (K43, decisions 273, 275: the end half is gone; nothing writes end values)."""
        pre, old = self.journal['pre_checks'], self.earlier.get('pre_checks')

        def kept(env):      # decision 298: the queue's values differ from ticket to ticket and no step reads them
            return {k: v for k, v in env.items() if not k.upper().startswith('RUNQ_')} if type(env) is dict else env
        pairs = {'profile': (self.profile_sha, self.earlier.get('profile_sha256')),
                 'environment': (kept(self.journal['environment']), kept(self.earlier.get('environment'))),
                 'package tree': (member(pre, 'package', 'tree_sha256'), member(old, 'package', 'tree_sha256')),
                 'interpreter tree': (member(pre, 'interpreter', 'tree_sha256'), member(old, 'interpreter', 'tree_sha256')),
                 'execution identity': (member(pre, 'execution_identity', 'execution_identity'),
                                        member(old, 'execution_identity', 'execution_identity'))}
        change = self.package_change_checks(pre, old)               # RP: None unless the rule applies
        if change is not None:
            for name in ('profile', 'package tree'):                # P-1, P-2 stand in for these two
                pairs.pop(name)
        differ = [name for name, (now, then) in pairs.items() if then is None or now != then]
        if 'post_check_failure' in self.earlier:
            differ.append('post_check_failure')
        if differ:
            self.key_differs = True                                     # S-1: no stopped store is taken
            self.stop_reuse(f'differs from the earlier journal or is not journaled there: {differ}')
        elif change is not None:
            self.brand(change)
            self.admission_changes = changed_admission_steps(change)

    def reopen_mixed_restart(self):
        record = member(self.earlier, 'resume', 'mixed')
        if record is None:
            return
        require(not self.key_differs and self.home_admission is not None and self.home_admission.owner.assigned(),
                'pending mixed history requires its matching diagnostic home and admitting owner')
        origin = record['origin']
        original, _ = read_json(origin['path'], origin['sha256'])
        damaged = self.earlier
        try:
            self.earlier = original
            change = self.package_change_checks(self.journal['pre_checks'], original['pre_checks'])
        finally:
            self.earlier = damaged
        require(change is not None and change['reviewed'], 'mixed history no longer binds its original reviewed change')
        self.brand(change)
        self.admission_changes = changed_admission_steps(change)
        self.mixed_restart = MixedRestart(self, Path(record['archive']), record['groups'], record['intervals'],
                                          origin, original, resuming=True)
        self.journal['resume']['mixed'] = copy.deepcopy(record)

    def package_change_checks(self, pre, old):
        """RP P-1, P-2 and the earlier proof for P-4 (integrity checks: any failure stops the chain), or None when the
        trees are equal or the record names no change from the earlier journal's tree (today's rule)."""
        now_tree, then_tree = member(pre, 'package', 'tree_sha256'), member(old, 'package', 'tree_sha256')
        if then_tree is None or now_tree == then_tree:
            return None
        part = self.config['issue_record']
        record, record_sha = read_json(part['path'], part['sha256'])
        change = record.get('package_change')
        if type(change) is not dict or change.get('earlier_tree_sha256') != then_tree:
            return None
        require(not self.continuation, 'package change: a continuation is refused')
        files, profile, readers = change.get('files'), change.get('earlier_profile'), record.get('readers')
        only = change.get('reader_files_only', False)                       # RFO
        require(type(only) is bool, 'package change: reader_files_only must be true or false')
        keeps = change.get('keeps_queries', False)                          # KQ (U-3)
        require(type(keeps) is bool, 'package change: keeps_queries must be true or false')
        reason = change.get('keeps_queries_reason')
        require(not keeps or type(reason) is str and bool(reason.strip()),
                'package change: keeps_queries true needs keeps_queries_reason, the fix reviewer\'s reason '
                '(review N-6)')
        keeps_m = change.get('keeps_measurements', False)                   # S-1 (F-6), as keeps_queries
        require(type(keeps_m) is bool, 'package change: keeps_measurements must be true or false')
        reason_m = change.get('keeps_measurements_reason')
        require(not keeps_m or type(reason_m) is str and bool(reason_m.strip()),
                'package change: keeps_measurements true needs keeps_measurements_reason, the fix reviewer\'s reason')

        def named(row):
            return (type(row) is dict and type(row.get('path')) is str and row['path'] and
                    all(row.get(k) is None or is_sha(row.get(k)) for k in ('old_sha256', 'new_sha256')) and
                    (row.get('old_sha256'), row.get('new_sha256')) != (None, None) and
                    (type(row.get('old_copy')) is str or row.get('old_sha256') is None and row.get('old_copy') is None) and
                    type(row.get('diff')) is dict and type(row['diff'].get('path')) is str and
                    is_sha(row['diff'].get('sha256')))
        require(type(files) is list and files and all(named(row) for row in files) and
                len({row['path'] for row in files}) == len(files) and type(profile) is dict and
                type(profile.get('path')) is str and is_sha(profile.get('sha256')) and
                type(readers) is list and readers, 'package change: the issue record\'s package_change is malformed '
                '(files with path, old/new hash, old_copy and diff; earlier_profile; readers)')
        root = self.config['package']['root']
        cached = _package_tree.get(root)                                    # 777: hashed once per run
        digest, members = cached if cached is not None and cached[0] == now_tree else tree_digest(root)[::3]
        require(digest == now_tree, 'package change P-1: the package tree differs from its pre-check')
        for row in files:
            require(members.get(row['path']) == row['new_sha256'], f'package change P-1: {row["path"]} is not at its new hash')
        earlier = dict(members)
        for row in files:
            if row['old_sha256'] is None:
                earlier.pop(row['path'])
            else:
                earlier[row['path']] = row['old_sha256']
        put_back = hashlib.sha256(json.dumps(earlier, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        require(put_back == then_tree, 'package change P-1: with the named files put back the tree is not the earlier '
                                       'journal\'s: a file differs that the record does not name, or an old hash is wrong')
        require(profile['sha256'] == self.earlier.get('profile_sha256') and sha_file(profile['path']) == profile['sha256'],
                'package change P-2: the earlier profile file is not the one the earlier journal recorded')
        earlier_profile, _ = read_json(profile['path'], profile['sha256'])
        require(type(earlier_profile) is dict and
                earlier_profile == self.profile,
                'package change P-2: the profiles differ')
        earlier_identity = member(old, 'execution_identity', 'execution_identity')    # K43: the start value only
        require(is_sha(earlier_identity), 'package change: the earlier journal holds no execution identity')
        return {'record_sha256': record_sha, 'reviewed': record.get('status') == REVIEWED,
                'files': files, 'earlier_tree_sha256': then_tree, 'earlier_profile': profile,
                'runtime_identity': earlier_identity, 'reader_files_only': only,
                'keeps_queries': keeps, 'keeps_queries_reason': reason if keeps else None,       # KQ
                'keeps_measurements': keeps_m, 'keeps_measurements_reason': reason_m if keeps_m else None}   # S-1

    def brand(self, change):
        """RP brand (decision 129: BR3 on every save from here, BR6 as one file in the run's home above its folders)."""
        self.package_change = change
        brand = {'brand': BRAND, 'reason': 'resume-across-package-change',
                 'previous_profile_sha256': change['earlier_profile']['sha256']}
        self.journal['not_scientifically_permissible'] = brand
        self.journal['resume']['package_change'] = {
            'record_sha256': change['record_sha256'], 'files': change['files'],
            'earlier_tree_sha256': change['earlier_tree_sha256'], 'earlier_profile_sha256': change['earlier_profile']['sha256'],
            'reader_files_only': change['reader_files_only'], 'keeps_queries': change['keeps_queries'],   # KQ
            'keeps_queries_reason': change['keeps_queries_reason'],
            'keeps_measurements': change['keeps_measurements'],                                          # S-1
            'keeps_measurements_reason': change['keeps_measurements_reason']}
        if 'execution_identity' in change:
            self.journal['resume']['package_change']['execution_identity'] = change['execution_identity']
        path = self.home()/BRAND_FILE          # r24 D-1 (098861a9 s2): a branded home stays branded, both reasons kept
        if os.path.lexists(path):
            raw = path.read_bytes() if path.is_file() else b''
            require(raw.startswith(BANNER.encode('utf-8')), f'brand: {path} is not a brand file')
            try:
                earlier = json.loads(raw[len(BANNER.encode('utf-8')):])['reason']
            except (ValueError, TypeError, KeyError):
                earlier = None
            require(type(earlier) is str, f'brand: {path} holds no reason after its banner')
            if earlier != brand['reason']:
                brand['also'] = earlier
        self.journal['resume']['package_change']['brand_file'] = str(self.brand_file(brand, keep=True))

    def brand_file(self, brand, keep):
        """The brand file in the run's home (F11:1266-1274, shared). keep: an existing file stays as it is (S-7);
        else an existing file must hold this brand's text."""
        home = self.home()
        require(len(home.parts) > 1, f'brand: the run has no home folder above its folders: {home}')
        text = BANNER + json.dumps(brand, indent=1, sort_keys=True) + '\n'
        path = home/BRAND_FILE
        if os.path.lexists(path):
            require(path.is_file() and (keep or path.read_bytes() == text.encode('utf-8')), f'brand: {path} differs')
        else:
            path.write_bytes(text.encode('utf-8'))
        return path

    def brand_recorded(self, reason='recorded-failed-step', **extra):
        """Decision 285: the first recorded item brands the run. A brand already there is kept and the reason added
        beside it; its file is never written a second time (S-7)."""
        brand = self.journal.get('not_scientifically_permissible')
        if brand is not None:
            if reason != brand['reason']:
                brand.setdefault('also', reason)
            return
        brand = {'brand': BRAND, 'reason': reason, **extra}                   # B-1: the change and what was taken
        self.journal['not_scientifically_permissible'] = brand
        self.journal.update(diagnostic_only=True, scientific_acceptance=False)
        brand['brand_file'] = str(self.brand_file(brand, keep=True))

    def pause_point(self, name):
        """B-2 (decision 811): before a launch, a pause request in the journal folder. A valid one ends the chain
        PAUSED here, at a step boundary; a malformed one is not obeyed, and the chain runs on and says so."""
        path = self.journal_dir/PAUSE_REQUEST
        if not os.path.lexists(path):
            return
        try:
            digest = sha_file(path)
            request = json.loads(path.read_bytes())
            valid = (type(request) is dict and request.get('schema') == PAUSE_SCHEMA and
                     all(type(request.get(key)) is str and request[key] for key in ('reason', 'utc')))
        except (OSError, ValueError):
            digest, valid = None, False
        if not valid:
            os.replace(path, self.journal_dir/'PAUSE-REQUEST.refused.json')
            self.journal.setdefault('pause_refused', []).append({'sha256': digest, 'before': name, 'reason': 'malformed'})
            self.save()
            return
        taken = self.journal_dir/'PAUSE-REQUEST.taken.json'
        os.replace(path, taken)
        pre = self.journal['pre_checks']
        self.journal['pause'] = {'request': {'path': str(taken), 'sha256': digest}, 'reason': request['reason'],
                                 'before': name, 'package_tree_sha256': member(pre, 'package', 'tree_sha256'),
                                 'interpreter_tree_sha256': member(pre, 'interpreter', 'tree_sha256')}
        raise Paused(f'paused by request before {name}')

    def pause_resume(self):
        """B-2: a PAUSED journal resumes unbranded only when this start check's package and interpreter tree digests
        equal its pause record's (ledger B2-01). A differing tree with a recorded package change is a resume across
        a fix (branded as today); without one it stops."""
        pause, pre = self.earlier.get('pause'), self.journal['pre_checks']
        if self.earlier.get('status') == 'STEP_LIMIT_REACHED':      # r32: stop_after is a pause by choice too
            old = self.earlier.get('pre_checks')
            pause = {'request': None, 'before': self.earlier.get('step_limit'),
                     'package_tree_sha256': member(old, 'package', 'tree_sha256'),
                     'interpreter_tree_sha256': member(old, 'interpreter', 'tree_sha256')}
        require(type(pause) is dict, 'B-2: a PAUSED journal without its pause record: a person decides')
        now = {'package_tree_sha256': member(pre, 'package', 'tree_sha256'),
               'interpreter_tree_sha256': member(pre, 'interpreter', 'tree_sha256')}
        equal = all(pause.get(key) == value for key, value in now.items())
        self.journal['resume']['pause'] = {'request_sha256': (pause.get('request') or {}).get('sha256'),
                                           'before': pause.get('before'), **now, 'equal': equal}
        self.save()
        require(equal or self.package_change is not None,
                'B-2: the package or interpreter tree differs from the pause record and no change is recorded: '
                'a person decides')
        self.pause_proved = equal and self.package_change is None and not self.key_differs

    def brand_resume(self):
        """B-1 (decisions 808, 811, 815; rulings 27, 27a): once, before the first launched step or at the end when
        every step was reused. What the resume took or left in place; branded unless nothing, a package change (today's
        brand) or a proved pause at a clean boundary."""
        if self.earlier is None or self.brand_checked:
            return
        self.brand_checked = True
        r = self.journal['resume']
        first = r.get('rerun_from') or ''                 # F-13: a saved result is taken only by the step that reads it
        reads = first.endswith('-producer') and 'interval' in first
        left = ((['query leftovers'] if reads and 'kept_query_leftovers' in self.journal else []) +
                (['measurements'] if (r.get('measurements') or {}).get('taken') else []) +      # S-1: step 1 only
                (['completed-heat'] if reads and not self.heat_of_passed_step()                  # item 4
                 and os.path.lexists(self.attempt.parent/'completed-heat') else []))
        taken = list(r['reused']) + left
        clean = self.pause_proved and not left and 'leftovers' not in r
        stop = self.stop_kind()
        missing = [held[0] for held in self.arm_kinds() if not self.kind_proved(held)] if stop == 'outside' else []
        outside = stop == 'outside' and not missing and self.package_change is None and not self.key_differs
        r['brand_rule'] = {'change': 'package' if self.package_change is not None else 'none', 'taken': taken,
                           'pause_proved_clean': clean, 'stop': stop, 'kinds_not_proved': missing}
        if self.package_change is None and taken and not clean and not outside:
            self.brand_recorded('resume-after-stop', change='none', taken=taken, stop=stop, kinds_not_proved=missing)
        elif outside and taken:                                   # 815, 818: as a pause
            pre = self.journal['pre_checks']
            r['outside_stop'] = {'status': self.earlier['status'],
                                 'kinds': {kind: OUTSIDE_STOP_PROVED[kind] for kind, _, _ in self.arm_kinds()},
                                 'package_tree_sha256': member(pre, 'package', 'tree_sha256'),
                                 'interpreter_tree_sha256': member(pre, 'interpreter', 'tree_sha256'),
                                 'digests_equal_to_earlier_start': True}
        self.save()

    def heat_of_passed_step(self):
        """Item 4 (2f05ebed; N-66): at a pause the completed-heat folder is a passed interval producer's saved result,
        not a leftover, key or no key: it stays in place and is not listed."""
        return self.stop_kind() == 'pause' and any(passed_in(step) and step['step'].endswith('-producer')
                                                   and 'interval' in step['step'] for step in self.earlier['steps'])

    def stop_kind(self):
        """B-1 (815, 818): how the earlier chain ended, by its journal. RUNNING or INTERRUPTED with no failed exit of a
        step: a stop from outside (a kill, a power cut, a caught interrupt). A failed exit: a failed step, also when
        the driver died after journaling it (F-4). A pause or stop_after: a pause."""
        status = self.earlier.get('status')
        failed = [s for s in self.earlier['steps'] if type(s.get('exit')) is int and s['exit'] != 0]
        if status in ('PAUSED', 'STEP_LIMIT_REACHED'):
            return 'pause'
        if failed:
            return 'failed-step'
        return 'outside' if status in ('RUNNING', 'INTERRUPTED') else 'other'

    def arm_kinds(self):
        """B-1 (818, N-17): [kind, unit, revision] for each kind the arm holds. Every arm holds step boundaries and
        before-seal; its list (ARM_UNITS in the package tree) names its saving units. No list, an unreadable one or a
        unit the driver does not know: an entry no table holds, so the resume is branded."""
        held = [['step-boundary', None, None], ['before-seal', None, None]]
        try:                                                     # Worker 4's form: one line, each 'unit revision'
            text = (Path(self.config['package']['root'])/ARM_UNITS).read_text(encoding='utf-8')
            lines = [line for line in text.splitlines() if line.startswith(UNITS_LINE)]
            require(len(lines) == 1, f'{len(lines)} {UNITS_LINE.strip()} lines')
            listed = ast.literal_eval(lines[0][len(UNITS_LINE):])
            require(type(listed) is tuple and all(type(item) is str for item in listed), 'not a tuple of strings')
            for item in listed:
                unit, revision = item.split(' ')
                held.append([UNIT_KIND.get(unit, f'unknown unit {unit}'), unit, revision])
        except (OSError, ValueError, SyntaxError, ChainStop) as error:
            held.append([f'no readable saving-units list ({type(error).__name__})', None, None])
        return held

    def kind_proved(self, held):
        """B-1 (818, 821): in the table, and for a unit at the revision its real kill passed on."""
        kind, unit, revision = held
        entry = OUTSIDE_STOP_PROVED.get(kind)
        return type(entry) is dict and (unit is None or (entry.get('revisions') or {}).get(unit) == revision)

    def home(self):
        return Path(os.path.commonpath([self.attempt, self.store, self.queries, self.journal_dir]))

    def carry_brand(self, branded_home):
        """S-5: a resume or continuation from a journal holding recorded items or a brand, or from a home that held the
        brand file before this run, is branded before its first step, whatever its key says."""
        if 'recorded' in self.earlier or 'not_scientifically_permissible' in self.earlier or branded_home:
            self.brand_recorded('carried-from-earlier-run')
            self.save()

    def prior(self, ok, step, what):
        """Decision 285: a test of how a step ended. Recorded when the configuration says so; else refused, as before."""
        if ok:
            return
        require(self.config['record_failed_steps'], what)
        self.journal.setdefault('recorded', []).append({'step': step, 'what': what, 'status': 'RECORDED'})
        self.journal.update(diagnostic_only=True, scientific_acceptance=False)
        self.brand_recorded()
        self.save()
        self.log_event('WARNING', 'diagnostic_recorded', step=step, detail=what)

    def recorded_step(self, name):
        return any(item['step'] == name for item in self.journal.get('recorded', []))

    def package_recorded(self, entry, record):
        """Items a step's own record lists as `recorded` (the package's places 4 and 5): copied into the step's entry
        and recorded in the journal; with the switch off they are refused."""
        if 'recorded' not in record:
            return
        items = record['recorded']
        require(type(items) is list and items and all(type(item) is str for item in items),
                f'{entry["step"]}: its record\'s recorded list is malformed')
        entry['recorded'] = items
        for item in items:
            self.prior(False, entry['step'], item)

    def added_words(self, finalise=False):
        """Words appended only to a launched command and journaled as added_argv: never compared by reuse."""
        words = ['--record-failed-prior'] if self.config['record_failed_steps'] else []
        change = self.package_change
        if finalise and change is not None and change['reader_files_only']:
            words += ['--reuse-previous-run', change['earlier_profile']['path'],
                      '--reuse-previous-run-sha256', change['earlier_profile']['sha256']]
        return words

    def note_child(self, identity):
        """R-1: a probe's identity, journaled before it is waited on (once the journal folder exists)."""
        self.journal['child_identities'].append(identity)
        if self.journal_dir.is_dir():
            self.save()

    def package_release(self):
        """R-1a (decisions 750, 753, 757): after a kill, the package tree's time test; under a recorded package change
        whose checks passed in full for this resume (package_change is set only then: P-1's earlier tree, new hashes
        and put-back tree, P-2's profile) those checks stand in its place."""
        release = self.journal['resume']['release']
        if self.package_change is not None:
            release['package'] = {'package_change_checks': 'passed', 'record_sha256': self.package_change['record_sha256']}
        else:
            release['newest_file_utc']['package'] = newest_before(self.config['package']['root'],
                                                                  self.earlier['started_utc'], 'package')
        self.save()

    def measurement_words(self, name):
        """S-1 (design 3942586a s7c): a resume whose first launch is step 1 names the stopped attempt's measurement
        folder, where settle moved it, to the producer. Not when the resume key differs, across a package change
        (F-6) unless its record says keeps_measurements, on a tree that is not diagnostic, or with capture."""
        if name != '1-root-producer' or self.earlier is None:
            return ()
        moved = self.journal['resume'].get('leftovers')
        source = None if moved is None or not moved['moved'] else Path(moved['aside'])/'attempt'/folder('run', 'root')
        if self.mixed_restart is not None:
            source = self.mixed_restart.aside/'attempt'/folder('run', 'root')
        change = self.package_change
        why = ('no stopped measurement store' if source is None or not (source/MEASUREMENT_STORE).is_file() else
               'the resume key differs' if self.key_differs else
               'package change' if change is not None and not change['keeps_measurements'] else
               'capture' if self.config['capture'] else
               'not a diagnostic tree' if not diagnostic_profile(self.profile) else
               'the tree does not take resumed measurements'                         # F-9
               if not self.config.get('takes_resumed_measurements', False) else None)
        self.journal['resume']['measurements'] = {'taken': why is None,
                                                  **({'from': str(source)} if why is None else {'reason': why})}
        return () if why else ('--resume-measurements', str(source))

    def seed_words(self, mode, seed):
        """D-3 (decision 726): step 5 across a package change other than reader files only keeps its seed and names
        the earlier profile, which P-2 has verified against the earlier journal. Journaled as added_argv."""
        change = self.package_change
        if mode != 'interval' or seed is None or change is None or change['reader_files_only']:
            return ()
        if self.mixed_restart is not None:
            root = next(step for step in self.journal['steps'] if step['step'] == '1-root-producer')
            if root.get('producer_journal_sha256') != self.mixed_restart.origin['sha256']:
                return ()
        profile = change['earlier_profile']
        return ('--reuse-previous-run', profile['path'], '--reuse-previous-run-sha256', profile['sha256'])

    def reuse(self, name, argv, outputs):
        """The earlier entry when every R1 condition holds for this step, else None (and nothing later is reused)."""
        mixed = self.mixed_restart
        deferred = mixed is not None and mixed.deferred(name)
        if not self.reusable and not deferred:
            return None
        if self.continuation and name not in self.reusable:      # K1: past the retained steps, launch from here
            self.reusable = {}
            return None
        old, why = (mixed.original[name] if deferred else self.reusable.get(name)), None
        recorded = old.get('outputs') if type(old) is dict else None
        bare = type(old) is dict and passed_in(old) and 'checkpoint' not in old and not self.continuation
        paired = name.endswith('-producer') and name[:-len('-producer')]+'-overlap' in self.reusable
        pair_half = (bare and paired and                                     # R-4: its reader did not pass
                     not passed_in(self.reusable.get(name[:-len('-producer')]+'-reader')))
        late = (self.released and bare and not paired and                    # R-2: killed before its checkpoint
                old is self.earlier['steps'][-1])
        passed = passed_in(old) and (type(old.get('checkpoint')) is dict or self.continuation or late or pair_half)
        ended = (self.config['record_failed_steps'] and type(old) is dict and type(old.get('exit')) is int and   # place 3
                 (self.package_change is None or self.package_change['reader_files_only']) and   # r25 F-4: a fix reruns it
                 type(old.get('end_utc')) is str and not self.released)
        affected = name.rsplit('-', 1)[-1] in self.admission_changes and (mixed is None or deferred)
        if deferred:
            reason = ('shared resource admission changed' if affected else
                      'command or required receipt pin changed' if not self.same_command(name, old.get('argv'), argv) else
                      'parent adoption pin changed' if not mixed.predecessor_matches(name) else None)
            if reason is not None:
                self.journal['resume']['mixed'].setdefault('reruns', {})[name] = reason
                return None
        if affected:
            why = 'a shared resource admission dependency changed'
        elif old is None:                                           # r21: e.g. steps 9-12 after an eight-step journal
            why = 'no entry in the earlier journal'
        elif not passed and not ended:
            why = 'not journaled as passed with a checkpoint'
        elif not self.same_command(name, old.get('argv'), argv):
            why = 'its command differs'
        elif type(recorded) is not dict or not {str(path) for path in outputs} <= set(recorded):
            why = 'not every expected output is journaled'
        elif deferred:
            mixed.restore(name, mixed.receipt_check(name, old, mixed.origin['sha256']))
        else:
            check = (mixed.receipt_check(name, old, self.journal['resume']['from']['sha256'])
                     if mixed is not None else None)
            torn = [path for path, digest in recorded.items() if not Path(path).is_file() or
                    not (check(path, path, digest) if check is not None else sha_file(path) == digest)]
            if torn:                                      # 821: this step and every later one run again
                why = 'an output differs from its journaled digest'
                self.torn = torn
                self.journal['resume']['torn_outputs'] = torn
        if why is not None:
            if deferred:
                raise ChainStop(f'{name}: restored outputs failed acceptance: {why}')
            if affected and self.mixed_restart is None and self.home_admission is not None and self.home_admission.owner.assigned():
                self.mixed_restart = MixedRestart.plan(self, name)
                if self.mixed_restart is not None:
                    self.journal['resume']['reason'] = f'{name}: {why}'
                    return None
            self.stop_reuse(f'{name}: {why}')
            return None
        earlier_dir = Path(mixed.origin['path']).parent if deferred else self.resume_dir
        for suffix in ('stdout', 'stderr') if 'log' not in old else ():    # the adopt acceptance reads its stdout log;
            # o4: an overlap step's log is its wrapper's, in the attempt tree
            shutil.copyfile(earlier_dir/f'{name}.{suffix}.log', self.journal_dir/f'{name}.{suffix}.log')
        entry = copy.deepcopy(old)
        entry['reused_from'] = mixed.origin['sha256'] if deferred else self.journal['resume']['from']['sha256']
        if mixed is not None:
            entry.setdefault('producer_journal_sha256', old.get('reused_from', entry['reused_from']))
        if not passed:
            self.reused_recorded.append(name)                     # R-3
        if deferred:
            entry['original_checkpoint'] = entry.pop('checkpoint')
        elif passed and not pair_half:                             # place 3: the last checkpoint stays a passed step's
            self.checkpoint = old.get('checkpoint')                # K1: None for an r4 journal
        pair = member(old, 'checkpoint', 'pair')                   # o4: a reused producer of a pair binds its reader
        self.whole = pair if type(pair) is list and pair[0] == name else None
        self.journal['resume']['reused'].append(name)
        if late:                                                   # R-2: nothing launched after it
            self.write_checkpoint(entry)
            self.journal['resume']['checkpoint_taken'] = name
        if pair_half:                                              # R-4: K-2 sets its reader's files aside
            self.journal['resume']['pair_producer_kept'] = name
        self.prior(old['exit'] == 0, name, f'{name} exited {old["exit"]}')
        return entry

    def same_command(self, name, then, now):
        """R1's command test; under RP (P-3) equal once the profile words are set aside, J1's being the earlier profile's.
        o4: an overlap reader's --overlap-spec value (this launcher's process and nonce) is set aside too."""
        then, now = spec_aside(then), spec_aside(now)
        if self.package_change is None or (self.mixed_restart is not None and not self.mixed_restart.deferred(name)
                                           and self.mixed_restart.resuming):
            return then == now
        profile = self.package_change['earlier_profile']
        earlier = profile_words(then, profile['path'], profile['sha256'])
        require(earlier is not None, f'package change P-3: {name}\'s journaled command does not hold the earlier profile')
        return earlier == profile_words(now, self.profile_path, self.profile_sha)

    def passed(self, entry, pair=None):
        """R2, after a step's acceptance: the three trees' file sizes (r16 D1); the checkpoint marks the step passed. o4: pair is
        an overlap producer's entry; the one checkpoint, taken after both ended, marks both."""
        restored = ('reused_from' in entry and self.mixed_restart is not None
                    and self.mixed_restart.deferred(entry['step']))
        if 'reused_from' in entry and not restored and not (self.continuation and entry['step'] == RETAINED[-1]):
            return
        if self.recorded_step(entry['step']):                       # a recorded step gets no checkpoint
            return
        if restored:
            entry['checkpoint'] = self.checkpoint
        else:
            self.write_checkpoint(entry)
        if pair is not None:
            self.checkpoint['pair'] = [pair['step'], entry['step']]
            pair['checkpoint'] = self.checkpoint
        if 'reused_from' in entry and not restored:                 # K5: the retained steps' one checkpoint
            self.checkpoint['covers'] = list(RETAINED)
            for step in self.journal['steps']:
                step['checkpoint'] = self.checkpoint
        self.save()

    def write_checkpoint(self, entry):
        """R2: the three trees' file sizes (r16 D1) as found, in the step's checkpoint file (r30: also R-2's)."""
        path = self.journal_dir/f'{entry["step"]}.checkpoint.json'
        entry['checkpoint'] = self.checkpoint = live_checkpoint(self.trees, path)

    def settle(self, final=False):
        """R1 before the first launch: every file of the last reused checkpoint unchanged; the rest are leftovers,
        journaled with sizes (r16 D1) and then renamed aside. final (nothing launched): there must be none."""
        if self.continuation:                                   # K1: checked once at the start instead
            return
        before = (dict.fromkeys(self.trees) if self.checkpoint is None else
                  read_json(self.checkpoint['path'], self.checkpoint['sha256'])[0])
        produced = [Path(path) for step in self.earlier['steps'] if passed_in(step)
                    for path in (step.get('outputs') or {})]
        reused = {os.path.normcase(os.path.abspath(path)) for step in self.journal['steps'] if 'reused_from' in step
                  for path in (step.get('outputs') or {})}
        units, keep = {}, {}
        last = next((step for step in reversed(self.journal['steps']) if 'reused_from' in step), None)
        bare = None                                 # r19 K-2: a reused producer with no checkpoint keeps its files
        if last is not None and 'checkpoint' not in last and last['step'].endswith('-producer'):
            reader = folder('reader', last['step'].split('-')[1])                         # r21: -0002 at interval 2
            bare = {reader, f'launch-{reader}', f'{reader}.tracking.json'}   # its reader's: aside
        for label, root in self.trees.items():
            kept = before.get(label)
            if not os.path.lexists(root):
                require(kept is None, f'{label} tree vanished since the last reused step')
                continue
            now = tree_inventory(root, hashed=False)[2]                     # r16 D1: presence and size
            if kept is None:
                found = {'': now}
            else:
                changed = sorted(name for name, was in kept.items()
                                 if name not in now or type(was) is int and now[name] != was)   # a str is an older driver's digest
                require(not changed, f'{label} files changed or vanished since the last reused step: {changed[:5]}')
                found = {unit: {name: size for name, size in now.items() if name == unit or name.startswith(unit+'/')}
                         for unit in leftover_units(root, kept)}
            if (label == 'queries' and found and not final and                               # KQ
                    (self.package_change is None or self.package_change['keeps_queries'])
                    and self.config.get('keep_query_leftovers') is True):
                self.journal['kept_query_leftovers'] = sum(len(files) for files in found.values())  # decision 267
                continue
            for unit, files in found.items():
                for name in files:
                    path = Path(root)/name
                    require(not path.name.startswith(OWNED), f'leftover {path} is an adoption or verdict file: a person decides')
                    require(os.path.normcase(os.path.abspath(path)) in reused             # r18: held below
                            or bool(self.torn)                       # 821: from a torn output on, all run again
                            or not any(same_path(path, out) for out in produced),
                            f'leftover {path} is an output of a step journaled as passed: a person decides')
            hold = {unit: files for unit, files in found.items()          # a reused (recorded) step's output: kept
                    if any(os.path.normcase(os.path.abspath(Path(root)/name)) in reused for name in files)
                    or bare is not None and not (label == 'attempt' and unit in bare)}           # r19 K-2
            found = {unit: files for unit, files in found.items() if unit not in hold}
            if hold:
                keep[label] = hold
            if found:
                units[label] = found
        heat = self.attempt.parent/'completed-heat'   # r24 (098861a9 s3): the step's home, RFI:1537; no tree
        if not final and os.path.lexists(heat) and (self.config.get('keep_query_leftovers') is not True     # as the queries
                and not self.heat_of_passed_step()                    # item 4: a passed step's, at a pause
                or self.package_change is not None):                  # r26 F-5: any package change
            require(heat.is_dir() and not any(inside(heat, root) for root in self.trees.values()),
                    f'{heat} is not a folder outside the trees')
            units['completed-heat'] = {'': tree_inventory(heat, hashed=False)[2]}
        if keep:
            self.journal['resume']['kept'] = keep
            self.save()
        if final:
            require(not units, f'files appeared after the last reused step: {sorted(units)}')
            return
        if not units:
            return
        number = 1
        while os.path.lexists(self.attempt.parent/f'resume-aside-{number}'):
            number += 1
        aside = self.attempt.parent/f'resume-aside-{number}'
        require(not any(inside(aside, root) for root in self.trees.values()), 'the aside folder lies inside a tree')
        manifest = self.journal_dir/'leftovers.json'
        with manifest.open('x', encoding='utf-8') as stream:
            json.dump({'aside': str(aside), 'units': units}, stream, indent=1, sort_keys=True)
        self.journal['resume']['leftovers'] = {'manifest': str(manifest), 'sha256': sha_file(manifest),
                                               'aside': str(aside), 'moved': False}
        self.save()                                                      # journaled before anything moves
        for label, found in units.items():
            for unit in found:
                target = aside/label/unit if unit else aside/label
                target.parent.mkdir(parents=True, exist_ok=True)
                os.rename(Path(self.trees[label])/unit if unit else self.trees.get(label, heat), target)
        self.journal['resume']['leftovers']['moved'] = True
        self.save()

    def settle_continuation(self):
        """K1 at the start, before any acceptance writes: the store and attempt trees list exactly the earlier journal's storage (names
        and sizes; outputs were re-hashed by reuse). Nothing moves. The three trees' files and bytes are journaled now (r16 D1c)."""
        for root in (self.store, self.attempt):
            files = sorted([p.relative_to(root).as_posix(), p.stat().st_size] for p in root.rglob('*') if p.is_file())
            require(self.earlier['storage'][str(root)] == {'files': files, 'bytes': sum(size for _, size in files)},
                    f"continuation: {root} differs from the earlier journal's storage listing")
        self.journal['resume']['continuation_trees'] = {
            label: dict(zip(('files', 'bytes'), tree_inventory(root, hashed=False)[:2], strict=True)) if os.path.lexists(root) else None
            for label, root in self.trees.items()}
        self.save()

    def retained_checks(self, *, checked_only=False):
        """F2/F4 on resume, once: the reused steps' retained receipts against this run's probe identity (F2, the
        interval continues the root's identity) and its current source proof and profile (F4, what each reader
        compares)."""
        reused = [step for step in self.journal['steps'] if 'reused_from' in step]
        if not reused:
            return
        identity = self.journal['pre_checks']['execution_identity']['execution_identity']
        mixed = self.mixed_restart
        producer, runtime = self.profile_sha, identity      # mixed: each step selects its actual producer below
        if mixed is None and self.package_change is not None:   # P-4: the earlier journal's identity and profile (R-2)
            runtime, producer = self.package_change['runtime_identity'], self.package_change['earlier_profile']['sha256']
        default = {'producer_identity': producer, 'runtime_identity': runtime}
        seen, roots = dict.fromkeys(default, 0), 0
        for step in reused:
            expected = default
            if mixed is not None:
                expected = mixed.expected_proof(step['step'], step, step['reused_from'])
            if step['step'] == '1-root-producer':
                expected = dict(expected, execution_identity=expected.get('execution_identity', identity))
                identity = expected['execution_identity']
            for path, digest in step['outputs'].items():
                if not path.endswith('.json'):
                    continue
                counts = None if mixed is None else mixed.checked_receipts.get((path, digest, tuple(expected.items())))
                if counts is None:
                    require(not checked_only, f'{path} has no retained receipt proof for its pinned producer')
                    receipt, _ = read_json(path, digest)
                    counts = retained_receipt_fields(path, receipt, expected)
                for key in seen:
                    seen[key] += counts.get(key, 0)
                roots += counts.get('execution_identity', 0)
        require(seen['runtime_identity'], 'F4: no retained receipt carries a runtime identity')
        require(roots or all(step['step'] != '1-root-producer' for step in reused),
                'F2: the retained root receipts name no execution identity')
        self.journal['retained_checks'] = {'identity': identity, 'root_identities': roots, 'proof_fields': seen}
        self.save()

    def preflight(self, name, argv):
        """F5/F6 before the first launch, for every producer still to run."""
        number = int(name.split('-')[0])
        modes = [mode for mode in ('root', 'interval', 'interval2')[:3 if self.config.get('intervals', 1) == 2 else 2]
                 if number <= NUMBER[mode]*4+1]
        record = {'first_launch': name}
        if modes:
            limits = store_limits(self.config, self.env)
            quota = self.profile.get('completed_query_limits', {}).get('max_store_bytes')
            require(type(quota) is int and quota > 0, 'profile completed_query_limits lacks max_store_bytes')
            need = limits['max_store_bytes'] + limits['max_staging_bytes'] + quota
            free = shutil.disk_usage(self.store.parent).free
            require(free >= need, f'disk headroom {free} B < {need} B that each producer demands')
            record['disk'] = {'free_bytes': free, 'needed_bytes': need}
        if any(MODE[mode] == 'interval' for mode in modes):          # r21: any interval producer still to run
            record['issue'] = self.check_provider_issue()
            record['heat_workers'] = pool_workers(self.config)    # r38 E-2: 'launch'; the width is the run's own
        record['producers'] = {}
        for mode in modes:
            launch = argv if name == f'{NUMBER[mode]*4+1}-{mode}-producer' and mode != 'interval2' else (  # D-8
                self.producer_argv(mode, None, PLACEHOLDER) if mode == 'interval2' else
                self.producer_argv(mode, None if mode == 'root' else (PLACEHOLDER, PLACEHOLDER)))
            dry = [word for word in launch if word != '--launch']
            done = run_child(dry, env=self.env, cwd=self.journal_dir, capture_output=True, text=True, timeout=600)
            lines = done.stdout.strip().splitlines()
            try:
                printed = json.loads(lines[-1]) if lines else {}
            except ValueError:
                printed = {}
            require(done.returncode == 0 and type(printed) is dict and printed.get('status') == DRY_STATUS,
                    f'{mode} producer refuses before launch: exit {done.returncode}: {done.stderr[-300:]}')
            record['producers'][mode] = {'argv': dry, 'placeholder_seed': PLACEHOLDER in dry}
        self.journal['preflight'] = record
        self.save()

    def check_provider_issue(self):
        return issue_checks(self.config)
    def producer_argv(self, mode, seed, parent=None):
        args, _ = self.booking(mode)
        extra = [] if seed is None else ['--seed-receipt-sha256', seed[0], '--seed-store-sha256', seed[1]]
        if parent is not None:                                    # r21: interval N >= 2, adopted(N-1) pin
            extra = extra+['--parent-adopted-sha256', parent]
        if self.config.get('open_proofs', False):                 # r21: proof-mode arm, producers only (D-9)
            extra = extra+['--open-proofs']
        return self.command('producer', mode)+['--launch']+args+extra

    def save(self, *, durable=False):
        replace = self.home_admission.module.durable_replace if durable else os.replace
        save_journal(self.journal_dir/'CHAIN-JOURNAL.json', self.journal, replace)

    def command(self, route, mode):
        spec = self.config['routes'][route]
        return [self.config['python'], '-B', self.config['entries'][spec['entry']]['path'], *spec['words'],
                '--profile', self.profile_path, '--profile-sha256', self.profile_sha, '--mode', MODE[mode]] + (
                [] if NUMBER[mode] <= 1 else ['--interval', str(NUMBER[mode])])     # r21: steps 9-12

    def booking(self, stage):
        value = self.config['bookings'][stage]
        return ['--booking-bytes', str(value['bytes']), '--booking-basis', value['basis']], value['bytes']

    def first_launch(self, name, argv):
        """Once, before the first launch, whether a step or a pair (o4): the retained checks, the leftovers, the dry run."""
        if self.launched:
            return
        if self.package_change is not None and self.package_change['reader_files_only'] and name not in FIRST_LAUNCH:
            require(not self.reused_recorded,                     # R-3 (N-13): before anything moves or launches
                    f'R-3: {self.reused_recorded} reused as recorded under reader files only: a person decides')
            self.package_change['reader_files_only'] = False      # an ordinary package change from here (D-1b, D-3)
            self.journal['resume']['package_change']['reader_files_only'] = False
            self.journal['resume']['reader_files_only_dropped'] = name
            self.save()
        if self.earlier is not None:
            self.journal['resume']['rerun_from'] = name
            self.retained_checks()                               # before anything moves
            if self.mixed_restart is None:
                self.settle()
            elif not self.mixed_restart.resuming:
                self.mixed_restart.park()
            if not self.attempt.exists():
                self.attempt.mkdir()                             # step 1 reruns: empty, as on a fresh run
        self.preflight(name, argv)
        self.launched = True

    def log_event(self, level, event, *, stamp=None, step=None, detail=None):
        if self.run_log:
            self.run_log.event(level, event, utc=stamp if stamp is not None else utc(), step=step, detail=detail)

    def log_reused(self, entry):
        self.log_event('INFO', 'step_reused', step=entry['step'],
                       detail={'original_start_utc': entry.get('start_utc'),
                               'original_end_utc': entry.get('end_utc'), 'step_exit': entry.get('exit')})

    def log_finished(self, entry, *, can_record, **streams):
        code = entry['exit']
        level = 'INFO' if code == 0 else 'WARNING' if can_record else 'ERROR'
        self.log_event(level, 'step_finished', stamp=entry['end_utc'], step=entry['step'],
                       detail={'step_exit': code, **streams})

    def run(self, name, argv, outputs, launch_peak=None, added=()):
        entry = self.reuse(name, argv, outputs)                  # K43: no profile hash or probe before each launch
        if entry is not None:                                    # R1: only the launch is skipped
            self.journal['steps'].append(entry)
            self.save()
            self.log_reused(entry)
            return entry
        require(self.whole is None, f'{name}: a pair is reused whole or launched whole: {self.whole} share one checkpoint')
        self.pause_point(name)                                               # B-2: at a step boundary
        self.first_launch(name, argv)
        added = tuple(added) + self.measurement_words(name)                 # S-1: after settle moved the leftovers
        self.brand_resume()                                                  # B-1: before the first launch
        if self.config['capture'] and name == '5-interval-producer':        # C-1: the record judged is this launch's
            require(not os.path.lexists(self.attempt/'run-interval'/CAPTURE_FAILURE),
                    'capture: a failure record exists before step 5')
        MM, RG = machine_modules(self.config)
        entry = {'step': name, 'argv': argv, 'free_ram_at_launch': MM.free_memory()}
        if added:
            entry['added_argv'] = list(added)                    # beside the command, never part of it
        if launch_peak is not None:
            entry['ram_wait_seconds'], entry['free_ram_at_launch'] = wait_for_ram(
                MM, RG.start_need(launch_peak), self.config['ram_wait_seconds'], self.config['ram_poll_seconds'])
            entry['start_gate_bytes'] = RG.start_need(launch_peak)
        entry['free_cores_at_launch'] = machine_at_launch(self.config)
        entry['start_utc'] = utc()
        self.journal['steps'].append(entry)
        self.save()
        self.log_event('INFO', 'step_started', stamp=entry['start_utc'], step=name)
        with open(self.journal_dir/f'{name}.stdout.log', 'wb') as out, open(self.journal_dir/f'{name}.stderr.log', 'wb') as err:
            with subprocess.Popen(argv+list(added), env=self.env, cwd=self.journal_dir, stdout=out, stderr=err) as child:
                try:
                    entry['identity'] = process_identity(child.pid)            # R-1: before it is waited on
                    self.save()
                    entry['exit'] = child.wait()
                except BaseException:
                    child.kill()
                    child.wait()
                    raise
        entry['end_utc'] = utc()
        entry['outputs'] = {str(path): sha_file(path) for path in outputs if Path(path).is_file()}
        self.save()
        self.log_finished(entry, can_record=self.config['record_failed_steps'],
                          stdout=f'{name}.stdout.log', stderr=f'{name}.stderr.log')
        self.prior(entry['exit'] == 0, name, f'{name} exited {entry["exit"]}')                   # place 1
        require(len(entry['outputs']) == len(outputs), f'{name} did not write every expected output')
        return entry

    def stage(self, mode, seed=None, parent=None):
        n = NUMBER[mode]
        receipt_path = self.attempt/folder('run', mode)/'run.json'
        store_names = [self.store/f'{kind}-interval-{n:04d}.json' for kind in ('runner-record', 'sealed-awaiting-reader')]
        _, peak = self.booking(mode)
        expected_outputs = [receipt_path, *store_names]
        if MODE[mode] == 'interval':
            expected_outputs.extend(check3_artifacts(receipt_path).values())
        name, argv = f'{n*4+1}-{mode}-producer', self.producer_argv(mode, seed, parent)
        if mode in self.overlap_stages:                                   # o4
            entry = self.reuse(name, argv, expected_outputs)              # a pair is reused whole or launched whole
            if entry is None:
                return self.overlap_stage(mode, seed, expected_outputs)
            self.journal['steps'].append(entry)
            self.save()
            self.log_reused(entry)
        else:
            entry = self.run(name, argv, expected_outputs, peak,
                             [*self.seed_words(mode, seed), *self.producer_profile_words])   # D-3
        receipt, producer_sha = self.producer_checks(mode, entry, seed)
        self.passed(entry)
        if self.config.get('stop_after') == name:                          # r20: the step limit
            raise StepLimit(name)
        return self.reader_steps(mode, receipt, producer_sha)

    def producer_checks(self, mode, entry, seed):
        """o4: stage()'s checks after the producer, moved unchanged but for the checkpoint (the caller's)."""
        run_dir = self.attempt/folder('run', mode)
        receipt_path = run_dir/'run.json'
        require(not (self.config['capture'] and MODE[mode] == 'interval'),    # CAP: before any acceptance (C-3: not reusable)
                'capture: step 5 passed under pins issued for another identity')
        step = entry['step']
        receipt, producer_sha = check_receipt(receipt_path, SEALED[MODE[mode]], pin=entry['outputs'][str(receipt_path)],
                                              prior=lambda ok, what: self.prior(ok, step, what), seeded=seed is not None)
        entry['status'] = receipt['status']
        check_heat_record(receipt, MODE[mode])
        if MODE[mode] == 'interval':
            entry['heat_pool'] = check_pool(receipt, parent_bound(self.config))
            checked_path = run_dir/'check3-received-r2.json'      # K1; K5: also a resume of a continuation journal
            if not self.continuation and str(checked_path) not in entry['outputs']:
                checked_path = run_dir/'check3-received.json'
            if 'reused_from' in entry and self.package_change is not None:      # P-6 (decision 300, ruling 7)
                pin = entry['outputs'].get(str(checked_path))
                require(is_sha(pin), 'package change P-6: the reused step 5 journals no CHECK3 receiving')
                checked, checked_sha = read_json(checked_path, pin)
            else:
                try:
                    checked = receive_check3(self.config, self.journal['pre_checks']['check3_selection'],
                                             self.profile_sha, receipt_path,
                                             receipt, entry['outputs'],
                                             execution_identity=self.journal['pre_checks']['execution_identity']['execution_identity'])
                except Exception as error:
                    entry['check3'] = {'status': 'INVALID_EVIDENCE', 'error': type(error).__name__+': '+str(error)}
                    self.save()
                    self.prior(False, step, 'interval CHECK3 INVALID_EVIDENCE: '+str(error))    # r15: rule 4; switch off: r14's stop
                    return receipt, producer_sha
                if 'reused_from' in entry and not self.continuation and checked_path.is_file():     # R1; r15: a step reused as ended has none
                    require(checked_path.read_text(encoding='utf-8') ==
                            json.dumps(checked, indent=1, sort_keys=True, allow_nan=False),
                            'interval CHECK3 receiving on the reused bytes differs from the journaled record')
                else:
                    with checked_path.open('x', encoding='utf-8') as stream:
                        json.dump(checked, stream, indent=1, sort_keys=True, allow_nan=False)
                checked_sha = sha_file(checked_path)
            entry['outputs'][str(checked_path)] = checked_sha
            entry['check3'] = checked
            self.save()
            measured = checked['result']['measured']
            self.journal['check3' if mode == 'interval' else 'check3_interval2'] = {   # K7; r21: interval 2's own key
                'status': 'RECORDED', **measured}
            if measured['heat_peak_below_reread_peak'] is not True:
                self.journal['diagnostic_only'] = True
                self.journal['scientific_acceptance'] = False
            self.save()
        else:
            # TC condition 4: r5 only yields this report (fresh_interval_driver.py:131). A build that records it needs
            # its reviewed check before run B, so a recorded one stops here instead of passing unchecked.
            require(not find_key(receipt, 'initial_parallel'),
                    'run A records an initial_parallel report: its condition-4 check must be reviewed for this build')
            entry['initial_parallel'] = 'NOT RECORDED (fresh_interval_driver.py:131 only yields it)'
        self.save()
        return receipt, producer_sha

    def reader_steps(self, mode, receipt, producer_sha, entry=None, gate_sha=None, pair=None):
        """o4: stage()'s reader, finalise and adopt steps, moved; an overlap reader (entry) has already run, and its
        producer's entry (pair) shares the reader's checkpoint."""
        n = NUMBER[mode]
        reader_dir = self.attempt/folder('reader', mode)            # r16 D2; r21: -0002 at interval 2
        if entry is None:
            args, peak = self.booking('reader-'+mode)
            words = ['--producer-receipt-sha256', producer_sha, '--launch']
            if self.whole is not None:                  # o4: a reused pair's reader, in its form (the spec set aside)
                words = ['--overlap-spec', '', '--launch']
                gate_sha = member(self.reusable.get(f'{n*4+1}-{mode}-overlap'), 'gate_sha256')
            entry = self.run(f'{n*4+2}-{mode}-reader', self.command('reader', mode)+words+args,
                             [reader_dir/'reopen.json', reader_dir/'reopen.guard.json',
                              reader_dir/'reopen.guard-control.json'], peak, [*self.added_words(), *self.reader_profile_words])
        reopen_path = reader_dir/'reopen.json'
        step = entry['step']
        reopen, reopen_sha = check_receipt(reopen_path, REOPENED[MODE[mode]], pin=entry['outputs'][str(reopen_path)],
                                           prior=lambda ok, what: self.prior(ok, step, what))
        self.package_recorded(entry, reopen)
        guard_sha = entry['outputs'][str(reader_dir/'reopen.guard.json')]
        control_sha = entry['outputs'][str(reader_dir/'reopen.guard-control.json')]
        entry['status'] = reopen['status']
        self.passed(entry, pair)
        if pair is not None and 'checkpoint' not in pair:       # r15: the reader was recorded, so the pair got no checkpoint
            self.passed(pair)                                   # the producer passed: it gets one
            pair['checkpoint']['pair'] = [pair['step'], step]   # a resume still reuses the two together
            self.save()
        verdict_path = self.store/f'reader-verdict-interval-{n:04d}.json'
        entry = self.run(f'{n*4+3}-{mode}-finalise', self.command('reader', mode)+
                         ['--producer-receipt-sha256', producer_sha,
                          '--reopen-receipt-sha256', reopen_sha,
                           '--guard-receipt-sha256', guard_sha,
                           '--guard-control-sha256', control_sha,
                          '--finalise']+([] if gate_sha is None else ['--overlap-gate-sha256', gate_sha]),   # o4
                         [reader_dir/'reopen-final.json', verdict_path], None, self.added_words(finalise=True))
        final, _ = read_json(reader_dir/'reopen-final.json')
        require(final.get('status') == READER_PASS[MODE[mode]] and final.get('errors') == [], f'{mode} finalise did not pass')
        self.package_recorded(entry, final)                                 # the final record's recorded list
        verdict_sha = (sha_file(verdict_path) if 'reused_from' in entry
                       else entry['outputs'][str(verdict_path)])
        require(final.get('verdict_sha256') == verdict_sha, 'verdict on disk differs from the finalise record')
        entry['status'] = final['status']
        entry['width_gate_passed'] = final.get('width_gate_passed')         # decides IV2 (reopen_fresh_restart.py:35-36)
        self.passed(entry)
        adopted_path = self.store/f'adopted-interval-{n:04d}.json'
        entry = self.run(f'{n*4+4}-{mode}-adopt', self.command('reader', mode)+
                         ['--verdict-sha256', verdict_sha, '--adopt'], [adopted_path])
        lines = (self.journal_dir/f'{n*4+4}-{mode}-adopt.stdout.log').read_text(encoding='utf-8').strip().splitlines()
        printed = json.loads(lines[-1], object_pairs_hook=_unique) if lines else {}
        require(printed.get('status') == ADOPTED and
                printed.get('sha256') == (sha_file(adopted_path) if 'reused_from' in entry
                                          else entry['outputs'][str(adopted_path)]) and
                Path(printed.get('adopted', '')) == adopted_path, f'{mode} adoption is not the recorded file')
        entry['status'] = ADOPTED
        self.save()
        self.passed(entry)
        return receipt, producer_sha

    def overlap_stage(self, mode, seed, expected_outputs):
        """o4 (chain_overlap_r4.py:953-1072): the producer and an admitted-ahead reader, each through its entry's own
        --launch wrapper (launch route r1 option B). Overlap launcher r1 s2 steps 1-7; the post-producer and reader
        checks are stage()'s own. r13: the first-launch work first; no profile hash or probe before the launch or the
        gate (K43; review W-2); each step journaled with its command; one checkpoint for the pair."""
        n = NUMBER[mode]
        producer_argv = self.producer_argv(mode, seed)
        self.pause_point(f'{n*4+1}-{mode}-producer')                          # B-2
        self.first_launch(f'{n*4+1}-{mode}-producer', producer_argv)
        self.brand_resume()                                                  # B-1
        OG, OR, OC, LP, shas = overlap_modules(self.config)
        settings = self.config['overlap']
        run, reader = tree_paths(self.attempt, 'run', mode), tree_paths(self.attempt, 'reader', mode)
        store_names = [self.store/f'{kind}-interval-{n:04d}.json' for kind in ('runner-record', 'sealed-awaiting-reader')]
        attempt = str(self.attempt.resolve())
        spec = {'schema': OR.SPEC_SCHEMA, 'gate_path': str(OR.gate_path(attempt, mode, n)), 'attempt': attempt,
                'stage': mode, 'interval': n, 'profile_sha256': self.profile_sha,
                'launcher': OG.process_identity(os.getpid()), 'launcher_nonce': secrets.token_hex(32),
                'timeout_seconds': settings['wait_seconds'][mode], 'wait_basis': settings['wait_basis']}
        OR.validate_spec(spec)
        record = {'step': f'{n*4+1}-{mode}-overlap', 'wait_spec': spec, 'gate_sources': shas,
                  'helpers': {name: value['sha256'] for name, value in settings['helpers'].items()}}
        self.journal['steps'].append(record)
        self.save()
        Path(spec['gate_path']).parent.mkdir(exist_ok=False)
        proved = exit_proved(OG, LP)
        tasks = []

        def start(name, argv, paths, step, added=()):             # D-3: added words beside the command
            task = OC.start(argv+list(added), self.env, paths, await_running=LP._await_running, track=LP._track,
                            confirm_exit=proved, emit=lambda line: None)
            tasks.append(task)
            record[name] = {'argv': argv, **({'added_argv': list(added)} if added else {}), 'tracking': task.tracking, 'running_seconds': round(time.monotonic()-task.started, 3)}
            self.save()
            self.log_event('INFO', 'step_started', stamp=record['start_utc'], step=step,
                           detail={'log': str(paths['log'])})
            return task

        def finished(name, task, paths, outputs, role):
            code, seconds = OC.wait(task, check_sources=lambda: None)
            entry = {'step': name, 'argv': record[role]['argv'], 'start_utc': record['start_utc'], 'exit': code,
                     **{key: record[role][key] for key in ('added_argv',) if key in record[role]},
                     'wall_seconds': round(seconds, 3), 'end_utc': utc(), 'log': str(paths['log']),
                     'outputs': {str(path): sha_file(path) for path in outputs if Path(path).is_file()}}
            self.journal['steps'].append(entry)
            self.save()
            self.log_finished(entry, can_record=role == 'reader' and self.config['record_failed_steps'],
                              log=entry['log'])
            if role == 'reader':                    # r15 (decision 322): place 1, as run() has it
                self.prior(code == 0, name, f'{name} exited {code}')
            else:                                   # a producer of a pair: the pair stops; a resume records it (place 3)
                require(code == 0, f'{name} exited {code}')
            require(len(entry['outputs']) == len(outputs), f'{name} did not write every expected output')
            require(proved(paths, task.tracking), f'{name}: guard exit and cleanup proof absent or failed')
            return entry

        try:
            require(not LP._matching_processes([attempt+os.sep]), 'a process already names this attempt')
            pair = settings['bookings'][mode]['bytes']
            MM, RG = machine_modules(self.config)
            record['ram_wait_seconds'], record['free_ram_at_launch'] = wait_for_ram(
                MM, RG.start_need(pair), self.config['ram_wait_seconds'], self.config['ram_poll_seconds'])
            record['start_gate_bytes'] = RG.start_need(pair)
            record['free_cores_at_launch'] = machine_at_launch(self.config)
            record['start_utc'] = utc()
            producer = start('producer', producer_argv, run, f'{n*4+1}-{mode}-producer',
                             [*self.seed_words(mode, seed), *self.producer_profile_words])
            args, _ = self.booking('reader-'+mode)
            began = time.monotonic()
            try:
                reader_task = start('reader', self.command('reader', mode)+
                                    ['--overlap-spec', OR.encode_spec(spec), '--launch']+args, reader,
                                    f'{n*4+2}-{mode}-reader', self.reader_profile_words)
            except OC.CohortRefused as refused:                              # launch-route r2 s3: no out, no guard
                notes = list(getattr(refused, '__notes__', ()))
                if not any('nothing was started' in note for note in notes):
                    raise
                require(not LP._matching_processes([str(reader['out'])+os.sep]), 'a process names the unstarted reader output')
                booked = self.config['bookings']['reader-'+mode]['bytes']
                with open(reader['log'], 'rb') as stream:                    # the entry's start-gate refusal text
                    stream.seek(max(0, stream.seek(0, 2)-4096))
                    reason = stream.read().decode('utf-8', 'replace')
                record['reader'] = {'status': 'NOT_STARTED', 'error': str(refused), 'notes': notes,
                                    'log': str(reader['log']), 'refusal_reason': reason,   # dec 78: reported, never silent
                                    'seconds': round(time.monotonic()-began, 3),
                                    'start_gate': {'booking_bytes': booked, 'gate_bytes': RG.start_need(booked),
                                                   'free_ram_after_refusal': MM.free_memory()}}
                record['counts_as_overlap'] = False                          # dec 78: never an overlap measurement
                self.journal['overlap_measurement'] = False
                self.save()
                self.log_event('WARNING', 'reader_not_started', step=f'{n*4+2}-{mode}-reader',
                               detail=record['reader'])
                reader_task = None
            produced = finished(f'{n*4+1}-{mode}-producer', producer, run, expected_outputs, 'producer')
            guard = LP._read(run['guard']) or {}
            require(guard.get('status') == 'STOPPED' and guard.get('workload_exit_confirmed') is True,
                    'producer guard receipt is not STOPPED with workload_exit_confirmed')
            receipt, producer_sha = self.producer_checks(mode, produced, seed)
            require(reader_task is None or not self.recorded_step(produced['step']),         # r15 (review W-3)
                    f'{produced["step"]} was recorded while its reader waits: no gate; a resume runs the reader after it')
            pins = dict(zip(('producer_receipt_sha256', 'guard_receipt_sha256', 'runner_sha256', 'sealed_sha256'),
                            (sha_file(path) for path in (run['receipt'], run['guard'], *store_names)), strict=True))
            require(pins['producer_receipt_sha256'] == producer_sha, 'producer receipt changed after its checks')
            if reader_task is None:                                          # launch-route r2 s3.3: sequential reader
                record['reader_route'] = 'SEQUENTIAL_AFTER_NOT_STARTED'
            else:
                require(reader_task.process.poll() is None, 'overlap reader exited before gate publication')
                expected = OR.expected_gate(spec, reader_task.tracking['parent'])
                gate = dict(expected, schema=OG.SCHEMA, **pins)
                OG.validate_gate(gate, expected)
                OG.atomic_publish(spec['gate_path'], gate)
                record['gate_sha256'] = gate_sha = OG.gate_sha256(gate)
                record['gate_utc'] = utc()
                self.save()
                entry = finished(f'{n*4+2}-{mode}-reader', reader_task, reader,
                                 [reader['receipt'], reader['guard'], reader['control']], 'reader')
                reopen, _ = read_json(reader['receipt'], entry['outputs'][str(reader['receipt'])])
                record.update({name: reopen.get(name) for name in ('admitted_ahead', 'gate_wait_seconds')})
            require(not LP._matching_processes([attempt+os.sep]), 'a process still names this attempt after the pair')
            self.save()
        except BaseException:
            cleanup = []
            for task in reversed(tasks):                                     # reader first, then producer
                try:
                    cleanup.append(OC.cancel_and_confirm(task, timeout_seconds=CANCEL_SECONDS))
                except BaseException as failure:  # noqa: BLE001 - recorded; no process is killed by guess
                    cleanup.append({'output': str(task.paths['out']), 'unconfirmed': repr(failure)})
            record['cleanup'] = cleanup
            self.save()
            raise
        if reader_task is None:                                              # its own start gate, same output path
            self.passed(produced)                                            # an ordinary reader: its producer's own checkpoint
            self.log_event('WARNING', 'reader_sequential_fallback', step=f'{n*4+2}-{mode}-reader')
            return self.reader_steps(mode, receipt, producer_sha)
        return self.reader_steps(mode, receipt, producer_sha, entry=entry, gate_sha=gate_sha, pair=produced)

    def execute(self, run_profile='off', profile_tool=None):
        require(not self.journal_dir.exists(), f'journal directory exists: {self.journal_dir}')
        self.journal_dir.mkdir(parents=True)
        try:
            try:
                if self.source_selection is None:
                    self.source_selection = profile_source_selection(self.config, self.profile)
                logging = selected_diagnostic(self.source_selection, 'run_logging')
                self.run_log = logging.open_run_log(self.journal_dir)
            except Exception:
                pass
            self.log_event('INFO', 'run_started', stamp=self.journal['started_utc'])
            return self.execute_admitted(run_profile, profile_tool)
        except BaseException as error:
            self.log_event('ERROR', 'run_stopped', detail={'reason': f'{type(error).__name__}: {error}'})
            raise
        finally:
            if self.run_log is not None:
                self.run_log.close()

    def execute_admitted(self, run_profile, profile_tool=None):
        release = (self.journal.get('resume') or {}).get('release')
        if release is not None and 'driver_record' in release:              # R-1 (V-3): the driver's own record
            path = self.journal_dir/'release-by-driver.json'
            with path.open('x', encoding='utf-8') as stream:
                json.dump(release.pop('driver_record'), stream, indent=1, sort_keys=True)
            release['record'] = {'path': str(path), 'sha256': sha_file(path)}
        try:
            self.journal['pre_checks'] = install_checks(
                self.config, 'pre', profile=self.profile, source_selection=self.source_selection)
            if run_profile != 'off':
                selection = self.source_selection
                if selection is None:
                    selection = profile_source_selection(self.config, self.profile)
                profiler = selected_diagnostic(selection, 'profiling')
                requested = profiler.profile_selection(run_profile)
                tool = ['--profile-tool', str(profiler.profile_tool(requested, profile_tool))] if 'tree' in requested else []
                self.producer_profile_words = [*profiler.profile_words(requested), *tool]
                self.reader_profile_words = [*profiler.profile_words(requested.intersection(('stacks', 'tree'))), *tool]
            else:
                require(profile_tool is None, '--profile-tool needs --run-profile tree')
            self.env = child_environment(self.config['environment'])
            self.journal['environment'] = {k: v for k, v in sorted(self.env.items()) if k.upper().startswith(AUDITED)}
            if self.earlier is None:
                for path in (self.attempt, self.store, self.queries):
                    require(not path.exists(), f'output exists before the run: {path}')
                self.attempt.mkdir()                                          # empty, just before step 1
            else:
                branded = os.path.lexists(self.home()/BRAND_FILE)             # S-5: the home as the resume found it
                self.resume_key()                                             # leftovers wait for the first launch
                self.reopen_mixed_restart()
                if self.released:
                    self.package_release()                                    # R-1a: after the package change checks
                self.carry_brand(branded)                                     # S-5: before the first step
                if self.earlier.get('status') in ('PAUSED', 'STEP_LIMIT_REACHED'):
                    self.pause_resume()                                       # B-2: before anything is reused
                if self.continuation:
                    self.settle_continuation()
                if self.mixed_restart is not None:
                    self.mixed_restart.park()
            require(self.config.get('intervals', 1) == 1 or self.package_change is None or not self.package_change['reader_files_only'],   # r27 (D-10; D-3 lifts D-7)
                    'intervals 2: no change of reader files only (decision 617, D-10): after a change of reader files only, step 11 '
                    'would get --reuse-previous-run, which the package takes at interval 1 only')
            self.save()
            root_receipt, root_sha = self.stage('root')
            stored = root_receipt.get('initial_measurement_store')
            require(type(stored) is dict and is_sha(stored.get('sha256')) and type(stored.get('filename')) is str,
                    'run A does not name its measurement store')
            seed = (root_sha, stored['sha256'])
            self.stage('interval', seed=seed)
            if self.config.get('intervals', 1) == 2:                         # r21: steps 9-12
                adopt = next(s for s in self.journal['steps'] if s['step'] == '8-interval-adopt')
                self.stage('interval2', parent=adopt['outputs'][str(self.store/'adopted-interval-0001.json')])
            if not self.launched:
                if self.mixed_restart is None:
                    self.settle(final=True)                                   # every step reused
                    self.retained_checks()
                    self.brand_resume()                                       # B-1
                else:
                    self.retained_checks(checked_only=True)
            self.journal['status'] = 'COMPLETED_RECORDED' if 'recorded' in self.journal else 'PASS'   # K7; decision 285
        except Paused as pause:                                             # B-2: ended by itself, no release needed
            self.journal.update(status='PAUSED', stop=str(pause))
        except StepLimit as limit:                                          # r20
            self.journal.update(status='STEP_LIMIT_REACHED', step_limit=str(limit))
        except ChainStop as stop:
            self.journal.update(status='STOPPED', stop=str(stop))
        except Exception as error:  # noqa: BLE001 - every failure is recorded and stops
            self.journal.update(status='STOPPED', stop=f'{type(error).__name__}: {error}',
                                stop_traceback=traceback.format_exc())
        except BaseException as error:  # noqa: BLE001 - interrupted: journaled; step processes may outlive the chain
            self.journal.update(status='INTERRUPTED',
                                stop=f'{type(error).__name__}: step processes may still run; kill them only by exact PID')
        if os.path.lexists(self.journal_dir/PAUSE_REQUEST):                   # B-2 (N-15): not taken by the end
            try:
                os.replace(self.journal_dir/PAUSE_REQUEST, self.journal_dir/'PAUSE-REQUEST.void.json')
                self.journal['pause_void'] = True
            except OSError as error:
                self.journal['pause_void'] = f'{type(error).__name__}: {error}'
        last = self.journal['steps'][-1] if self.journal['steps'] else {}
        admitted = self.home_admission is None or self.home_admission.shared is not None
        if (admitted and self.config['capture'] and self.journal['status'] == 'STOPPED' and last.get('step') == '5-interval-producer'
                and last.get('exit') not in (None, 0)):                     # CAP: final when judged (K43: C-2 withdrawn)
            captured, self.journal['capture'] = judge_capture(self.attempt/'run-interval'/CAPTURE_FAILURE,
                                                              self.config['issue_record'])
            if captured:
                self.journal['status'] = 'CAPTURED'
        try:                                                    # K43: no closing re-checks (decisions 273, 275)
            storage = {}
            if admitted:
                for root in (self.store, self.attempt):
                    if root.is_dir():
                        files = sorted((p.relative_to(root).as_posix(), p.stat().st_size)
                                       for p in root.rglob('*') if p.is_file())
                        storage[str(root)] = {'files': files, 'bytes': sum(size for _, size in files)}
                self.journal['storage'] = storage
        except OSError as error:
            self.journal['storage_error'] = f'{type(error).__name__}: {error}'
        self.journal['ended_utc'] = utc()
        self.save(durable=not admitted)
        status = self.journal['status']
        code = PAUSED_EXIT if status == 'PAUSED' else 0 if status in ('PASS', 'STEP_LIMIT_REACHED') else 1
        stopped = status in ('STOPPED', 'INTERRUPTED', 'CAPTURED')
        detail = {'status': status, 'chain_exit': code}
        for key in ('stop', 'step_limit'):
            if key in self.journal:
                detail[key] = self.journal[key]
        if last and 'exit' in last:
            detail['last_step_exit'] = last['exit']
        self.log_event('ERROR' if stopped else 'WARNING' if status == 'COMPLETED_RECORDED' else 'INFO',
                       'run_stopped' if stopped else 'run_finished', stamp=self.journal['ended_utc'],
                       step=last.get('step'), detail=detail)
        return code


OVERLAP_FIELDS = {'stages', 'wait_seconds', 'wait_basis', 'bookings', 'helpers'}   # o4 (overlap launcher r1 s2)
OVERLAP_HELPERS = ('overlap_cohort', 'launch_pieces')
CANCEL_SECONDS = 30                                       # overlap launcher r1 s2.7
GUARD_ENDED = ('STOPPED', 'PARENT_EXITED', 'HARD_STOPPED', 'GUARDIAN_FAILED')


def overlap_config(config):
    """o4: closed `overlap` key; the sequential route is untouched when it is absent. r13: not with a capture of the
    interval stage (its step 5 is expected to fail). r15: with record_failed_steps it is allowed (decision 322)."""
    overlap = shape(config['overlap'], OVERLAP_FIELDS, 'overlap')
    stages = overlap['stages']
    require(type(stages) is list and stages and len(set(stages)) == len(stages) and set(stages) <= {'root', 'interval'},
            'overlap stages must be distinct names from root, interval')
    require(not (config['capture'] and 'interval' in stages), 'capture refuses an interval overlap')
    shape(overlap['wait_seconds'], set(stages), 'overlap wait_seconds')
    shape(overlap['bookings'], set(stages), 'overlap bookings')
    for stage in stages:
        seconds = overlap['wait_seconds'][stage]
        require(type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0,
                f'overlap wait for {stage} must be a positive finite number')
        value = shape(overlap['bookings'][stage], {'bytes', 'basis'}, f'overlap booking {stage}')
        require(type(value['bytes']) is int and value['bytes'] > 0 and type(value['basis']) is str and value['basis'],
                f'overlap booking for {stage} is not a positive integer with a basis')
    require(type(overlap['wait_basis']) is str and overlap['wait_basis'].strip(), 'overlap wait_basis required')
    shape(overlap['helpers'], set(OVERLAP_HELPERS), 'overlap helpers')
    for name in OVERLAP_HELPERS:
        pinned(overlap['helpers'][name], f'overlap helper {name}')


def load_pinned(name, path, pin):
    """Execute exactly the hashed bytes as module `name` (the helpers import the gate by this plain name)."""
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == pin, f'{name} differs from its pin')
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def load_module(name, path):
    """Execute the file's bytes as module `name` without importing its package."""
    path = Path(path)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def shared_modules(native, names):
    """Import the shared package from the installed native root (a checkout: its shared/src), without tectonics."""
    native = Path(native)
    shared = native.parent.parent/'shared'/'src' if (native.name, native.parent.name) == ('src', 'tectonics') else native
    before = list(sys.path)
    sys.path.insert(0, str(shared))
    try:
        return tuple(importlib.import_module(name) for name in names)
    finally:
        sys.path[:] = before


def selected_diagnostic(source_selection, name):
    _, native = source_selection
    module, = shared_modules(native, ('atlas_shared.execution.' + name,))
    return module


def overlap_modules(config):
    """Load gate and wait-spec code from the arm's selected members, with its pinned helpers."""
    package = config['package']
    native = Path(package['root'])
    checked = _package_tree.get(package['root'])
    if checked is None:
        binding = config['profile']
        profile, _ = read_json(binding['path'], binding['sha256'])
        _, native = profile_source_selection(config, profile)
        digest, _, _, members = tree_digest(native)
        _package_tree[package['root']] = (digest, members)        # hashed once per run, as package_checks does
        require(digest == package['tree_sha256'], 'overlap sources need the selected package tree')
    else:
        require(checked[0] == package['tree_sha256'], 'overlap sources need the selected package tree')
        members = checked[1]
    private = native/'atlas_tectonics'/'_private'/'integration'/'geometry'
    shas = {name: members.get(relative(private/(name+'.py'), native))   # tree_digest keys are native-relative
            for name in ('reader_overlap_gate', 'overlap_reader')}
    require(all(is_sha(pin) for pin in shas.values()), 'overlap gate and reader must be selected sources')
    shared_modules(native, ('atlas_shared.errors',))
    OG = load_pinned('reader_overlap_gate', private/'reader_overlap_gate.py', shas['reader_overlap_gate'])
    geometry = 'atlas_tectonics._private.integration.geometry'
    stubs = {name: types.ModuleType(name) for name in
             ('atlas_tectonics', 'atlas_tectonics._private', 'atlas_tectonics._private.integration', geometry)}
    require(not set(stubs) & set(sys.modules), 'the chain driver must not have imported atlas_tectonics')
    stubs[geometry].reader_overlap_gate = OG   # overlap_reader's only Atlas import
    sys.modules.update(stubs)
    try:
        OR = load_pinned('overlap_reader', private/'overlap_reader.py', shas['overlap_reader'])
    finally:
        for name in stubs:
            del sys.modules[name]
    helpers = config['overlap']['helpers']
    OC = load_pinned('overlap_cohort', helpers['overlap_cohort']['path'], helpers['overlap_cohort']['sha256'])
    LP = load_pinned('launch_pieces', helpers['launch_pieces']['path'], helpers['launch_pieces']['sha256'])
    return OG, OR, OC, LP, shas


def tree_paths(attempt, kind, mode):
    """Launch route r1 s2.2: the entry's --launch wrapper creates `out`; it runs from the sibling `launch` folder."""
    out, stem = attempt/f'{kind}-{mode}', ('run' if kind == 'run' else 'reopen')
    launch = attempt/f'launch-{kind}-{mode}'
    return {'launch': launch, 'log': launch/'wrapper.log', 'out': out, 'receipt': out/f'{stem}.json',
            'guard': out/f'{stem}.guard.json', 'control': out/f'{stem}.guard-control.json',
            'abort': out/f'{stem}.guard-abort.json', 'cancel': out/f'{stem}.cancel',
            'tracking': attempt/f'{kind}-{mode}.tracking.json'}


def exit_proved(OG, LP):
    """Plan11 cancellation_proved (launch_fresh_interval.py:644-655): exact exits plus the guardian's cleanup proof."""
    def proved(p, tracking):
        guard = OG._retry_sharing(lambda: LP._read(p['guard']), 'guard read') or {}
        control = OG._retry_sharing(lambda: LP._read(p['control']), 'control read') or {}
        return (guard.get('schema') == LP.GUARD_SCHEMA and guard.get('status') in GUARD_ENDED and
                guard.get('workload_exit_confirmed') is True and guard.get('cleanup') == LP.CLEAN and
                'cleanup_error' not in guard and guard.get('parent') == tracking.get('parent') and
                guard.get('guardian', {}).get('pid') == tracking.get('guardian', {}).get('pid') and
                guard.get('nonce') == control.get('nonce') and control.get('parent') == guard.get('parent') and
                not any(OG.process_alive(identity) for identity in guard.get('launch_cohort', [])) and
                not LP._matching_processes([str(p['out'])+os.sep]))
    return proved


def shape(value, fields, name):
    require(type(value) is dict and set(value) == fields, f'{name} must hold exactly {sorted(fields)}')
    return value


def pinned(value, name):
    shape(value, {'path', 'sha256'}, name)
    require(type(value['path']) is str and is_sha(value['sha256']), f'{name} needs a path and a sha256')


def load_config(path, pin):
    """Closed configuration: every member and nested member named, typed and pinned before any step runs."""
    config, digest = read_json(path, pin)
    shape(config, FIELDS | ({'overlap', 'keep_query_leftovers', 'stop_after', 'intervals', 'open_proofs',
                             'takes_resumed_measurements'} & set(config)),
          'the configuration')                                       # o4, MSS, r20, r21: optional
    require(config['schema'] == CONFIG_SCHEMA, f'configuration schema is not {CONFIG_SCHEMA}')
    require(type(config['python']) is str and type(config['journal_directory']) is str,
            'python and journal_directory must be paths')
    for name in ('interpreter', 'package'):
        optional = ({'listing_sha256'} & set(config[name]) if name == 'interpreter' and type(config[name]) is dict
                    else set())                                      # r36 (IH): absent = hashed in full, as r33
        part = shape(config[name], {'root', 'tree_sha256'} | optional | ({'top_level'} if name == 'package' else set()),
                     name)
        require(type(part['root']) is str and is_sha(part['tree_sha256']) and
                is_sha(part.get('listing_sha256', part['tree_sha256'])),
                f'{name} needs a root and a tree sha256 (and a listing sha256 if it names one)')
    top = config['package']['top_level']
    require(type(top) is list and top and len(set(top)) == len(top) and
            all(type(n) is str and n and '/' not in n and '\\' not in n and not folded(n, ('.dist-info',)) for n in top),
            'package top_level must list distinct plain names (the one dist-info is implied)')
    if config['pth'] is not None:
        pinned(config['pth'], 'pth')
    delivery = shape(config['delivery'], {'materialiser', 'inventory_root', 'sha256'}, 'delivery')
    pinned(delivery['materialiser'], 'delivery materialiser')
    require(type(delivery['inventory_root']) is str and is_sha(delivery['sha256']),
            'delivery needs an inventory root and a sha256')
    entries, routes = config['entries'], shape(config['routes'], {'producer', 'reader'}, 'routes')
    require(type(entries) is dict and entries, 'entries must be a non-empty map')
    for name, entry in entries.items():
        pinned(entry, f'entry {name}')
    for name, route in routes.items():
        shape(route, {'entry', 'words'}, f'route {name}')
        words = route['words']
        require(route['entry'] in entries and type(words) is list and
                all(type(word) is str and word and not word.startswith('-') for word in words),
                f'route {name} needs a known entry and plain subcommand words')
    require(set(entries) == {route['entry'] for route in routes.values()}, 'every entry must serve a route')
    check = config['layout_check']
    if check is not None:
        shape(check, {'python', 'script', 'args'}, 'layout_check')
        pinned(check['script'], 'layout_check script')
        require(type(check['python']) is str and type(check['args']) is list and
                all(type(a) is str for a in check['args']) and '--out' not in check['args'],
                'layout_check needs a python and string args (the chain adds --out)')
    environment = config['environment']
    require(type(environment) is dict and all(type(k) is str and k.startswith('ATLAS_') and k == k.upper() and
                                              type(v) is str for k, v in environment.items()),
            'environment must map upper-case ATLAS_* names to strings')
    require(environment.get(STRICT) == '1', f'environment must declare {STRICT}=1: IV1 needs strict heat workers')
    pool = shape(config['heat_pool'], {'member', 'sha256'}, 'heat_pool')
    member = pool['member']
    require(type(member) is str and member and '\\' not in member and not member.startswith('/') and ':' not in member
            and '..' not in member.split('/') and is_sha(pool['sha256']),
            'heat_pool needs a package-relative member path and a sha256')
    pinned(config['profile'], 'profile')
    require(config.get('intervals', 1) in (1, 2) and type(config.get('intervals', 1)) is int,   # r21
            'intervals must be the integer 1 or 2')
    two = config.get('intervals', 1) == 2
    require(not two or not (config['capture'] or config['continuation'] or 'stop_after' in config or
                            'overlap' in config), 'intervals 2 refuses capture, continuation, stop_after and overlap')
    require(type(config.get('open_proofs', False)) is bool, 'open_proofs must be true or false')   # r21
    require(not config.get('open_proofs', False) or not (config['capture'] or config['resume_from'] is not None),
            'open_proofs refuses resume_from and capture: a proof run reuses nothing')
    stages = STAGES + (STAGES2 if two else ())
    bookings = shape(config['bookings'], set(stages), 'bookings')
    for stage in stages:
        value = shape(bookings[stage], {'bytes', 'basis'}, f'booking {stage}')
        require(type(value['bytes']) is int and value['bytes'] > 0 and type(value['basis']) is str and
                value['basis'] and not value['basis'].startswith('-'),
                f'booking for {stage} is not a positive integer with a basis')
    # r38: decision 1044's standard count (the binders hold it equal to q540's), compared with nothing; the launch's
    # own width is in the pool record (check_pool).
    require(type(config['heat_workers']) is int and config['heat_workers'] >= 2, 'heat_workers must be an integer >= 2')
    for name in ('ram_wait_seconds', 'ram_poll_seconds', 'cores_sample_seconds'):
        require(type(config[name]) in (int, float) and config[name] > 0, f'{name} must be a positive number')
    if config['resume_from'] is not None:
        pinned(config['resume_from'], 'resume_from')
        require(Path(config['resume_from']['path']).is_absolute(), 'resume_from needs an absolute journal path')
    require(type(config['continuation']) is bool, 'continuation must be true or false')
    require(not config['continuation'] or config['resume_from'] is not None, 'continuation needs resume_from')
    require(type(config['capture']) is bool, 'capture must be true or false')
    require(not (config['capture'] and config['continuation']), 'capture refuses a continuation')
    require(type(config['record_failed_steps']) is bool, 'record_failed_steps must be true or false')   # decision 285
    require(not (config['capture'] and config['record_failed_steps']), 'capture refuses record_failed_steps')   # R-5
    require(type(config.get('keep_query_leftovers', False)) is bool, 'keep_query_leftovers must be true or false')  # MSS
    require(type(config.get('takes_resumed_measurements', False)) is bool,                                       # F-9
            'takes_resumed_measurements must be true or false')
    if 'stop_after' in config:                                       # r20
        require(config['stop_after'] == '1-root-producer', "stop_after must be '1-root-producer'")
        require(config['resume_from'] is None and not config['capture'] and 'overlap' not in config,
                'stop_after needs a fresh sequential run: no resume_from, capture or overlap')
    if config['resume_release'] is not None:                              # K9
        pinned(config['resume_release'], 'resume_release')
        require(config['resume_from'] is not None and not config['continuation'],
                'resume_release needs resume_from and no continuation')
    issue = shape(config['issue_record'], {'path', 'sha256', 'grid_path'}, 'issue_record')
    require(type(issue['path']) is str and is_sha(issue['sha256']) and type(issue['grid_path']) is str and
            Path(issue['path']).is_absolute() and Path(issue['grid_path']).is_absolute(),
            'issue_record needs an absolute record path, its sha256 and the absolute grid path run B reads')
    check3_config(config)
    if 'overlap' in config:                                          # o4
        overlap_config(config)
    return config, digest


def load_home_owner(config):
    profile, _ = read_json(config['profile']['path'], config['profile']['sha256'])
    selection = profile_source_selection(config, profile)
    _, native = selection
    path = check3_ordinary_file(native/'atlas_tectonics/_private/integration/interval_admission.py')
    module = load_module('_r39_interval_admission', path)
    return module, profile, selection


def save_journal(path, journal, replace):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(json.dumps(journal, indent=1, sort_keys=True))
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(SAVE_TRIES):
        try:
            replace(temporary, path)
            return
        except PermissionError:
            if attempt == SAVE_TRIES-1:
                raise
            if attempt == 0:
                journal['save_retries'] = journal.get('save_retries', 0)+1
            time.sleep(SAVE_WAIT_SECONDS)


def intent_digest(intent):
    return hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def live_checkpoint(roots, path, *, replace=None):
    trees, members = {}, {}
    for label, root in roots.items():
        trees[label] = members[label] = None
        if os.path.lexists(root):
            count, size, members[label] = tree_inventory(root, hashed=False)
            trees[label] = {'files': count, 'bytes': size}
    raw = json.dumps(members, sort_keys=True, separators=(',', ':')).encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    if replace is not None and path.exists():
        require(sha_file(check3_ordinary_file(path)) == digest, 'live checkpoint conflicts with pending transition')
    else:
        target = path if replace is None else path.with_suffix('.tmp')
        with target.open('xb' if replace is None else 'wb') as stream:
            stream.write(raw)
            if replace is not None:
                stream.flush()
                os.fsync(stream.fileno())
        if replace is not None:
            replace(target, path)
    return {'path': str(path), 'sha256': digest, 'trees': trees}


def protected_trees(profile):
    return {key: str(Path(path).resolve()) for key, path in {
        'attempt': profile['output_directory'], 'store': profile['store_directory'],
        'queries': Path(profile['workspace'])/profile['completed_query_directory'],
    }.items()}


def changed_admission_steps(change):
    dependencies = {'atlas_shared/machine/resources_monitor.py': {'producer', 'reader', 'adopt'},
                    'atlas_shared/machine/resources_gate.py': {'producer', 'reader'}}
    paths = {row['path'] for row in change['files']}
    affected = set().union(*(dependencies[path] for path in paths & dependencies.keys()))
    if not affected:
        return affected
    require(change['reviewed'] and not change['reader_files_only'],
            'a shared resource admission edit requires a reviewed change covering its actual callers')
    unclassified = sorted(path for path in paths - dependencies.keys()
                          if re.fullmatch(r'[^/]+\.dist-info/RECORD', path) is None)
    require(not unclassified, f'no retained-step dependency proof for combined admission edit: {unclassified}')
    return affected


class MixedRestart:
    """Keep original outputs aside until a step's new predecessor pins are known."""
    def __init__(self, chain, aside, groups, intervals, origin, original, *, resuming=False):
        self.chain, self.aside, self.groups, self.intervals = chain, aside, groups, intervals
        self.origin, self.original = origin, {step['step']: step for step in original['steps']}
        self.original_identity = member(original, 'pre_checks', 'execution_identity', 'execution_identity')
        self.checked_receipts = {}
        self.resuming = resuming

    def expected_proof(self, name, old, from_pin):
        c = self.chain
        pre = c.journal['pre_checks']
        produced = old.get('producer_journal_sha256', old.get('reused_from', from_pin))
        root = c.root_producers.get(name)
        if root is not None:
            producer, identity = root['profile']['sha256'], root['identity']
        elif produced == self.origin['sha256']:
            change = c.package_change
            producer, identity = change['earlier_profile']['sha256'], self.original_identity
        else:
            producer, identity = c.profile_sha, pre['execution_identity']['execution_identity']
        expected = {'producer_identity': producer, 'runtime_identity': identity}
        if name == '1-root-producer':
            require(is_sha(identity), 'F2: retained root has no pinned producer execution identity')
            expected['execution_identity'] = identity
        return expected

    def receipt_check(self, name, old, from_pin):
        expected = self.expected_proof(name, old, from_pin)
        proof = tuple(expected.items())
        outputs = old['outputs']

        def check(live, present, pin, receipt=None):
            path = str(live)
            if not path.endswith('.json') or path not in outputs:
                return sha_file(present) == pin
            require(outputs[path] == pin, f'{path} is pinned by a different retained step output')
            key = (path, pin, proof)
            if receipt is None:
                if key in self.checked_receipts:
                    return sha_file(present) == pin
                raw = Path(present).read_bytes()
                if hashlib.sha256(raw).hexdigest() != pin:
                    return False
                receipt = json.loads(raw, object_pairs_hook=_unique)
            if key not in self.checked_receipts:
                self.checked_receipts[key] = retained_receipt_fields(path, receipt, expected)
            return True

        return check

    @classmethod
    def plan(cls, chain, first):
        old = chain.earlier['steps']
        number = int(first.split('-')[0])
        accepted = [step for step in old if passed_in(step) and type(step.get('checkpoint')) is dict]
        if not any(int(step['step'].split('-')[0]) > number for step in accepted):
            return None
        require(diagnostic_profile(chain.profile) and not chain.config['capture'] and not chain.continuation
                and not chain.config.get('open_proofs', False) and not chain.overlap_stages and not chain.released and
                all(not ({'covers', 'pair'} & step['checkpoint'].keys()) for step in accepted) and
                all(step.get('reused_from') is None for step in accepted),
                'mixed restart requires original sequential diagnostic checkpoint groups and a quiescent home')
        identities, unknown = recorded_identities(chain.earlier)
        require(not unknown and not any(process_alive(identity) for identity in identities),
                'earlier driver or child still owns the passed output groups')
        modes = ('root', 'interval', 'interval2')
        expected_steps = [f'{NUMBER[mode]*4+index}-{mode}-{phase}' for mode in modes
                          for index, phase in enumerate(('producer', 'reader', 'finalise', 'adopt'), 1)]
        require([step['step'] for step in old] == expected_steps[:len(old)] and len(accepted) == len(old)
                and len(old) % 4 == 0,
                'protected restart needs original runner, seal, verdict and adoption pins for every active generation')
        require(not os.path.lexists(chain.queries) or chain.package_change['keeps_queries'],
                'existing query tree lacks the reviewed retention binding')
        aside = next(path for index in range(1, 10000)
                     if not os.path.lexists(path := chain.attempt.parent/f'resume-aside-{index}'))
        groups, intervals = {}, []
        active_attempt = tree_inventory(chain.attempt, hashed=False)[2]
        previous_attempt = checkpoint_attempt(old[-1])
        unexpected = sorted(active_attempt.keys() - previous_attempt.keys())
        require(not unexpected, f'earlier attempt has unassigned outputs: {unexpected[:5]}')
        store_files = {'interval-catalog.json', 'interval-catalog.json.lock'}
        preceding = None
        for interval, mode in enumerate(modes[:len(old)//4]):
            steps = old[interval*4:interval*4+4]
            pins = cls.record_pins(chain.store, interval, steps)
            adopted = chain.store/f'adopted-interval-{interval:04d}.json'
            adoption, _ = read_json(check3_ordinary_file(adopted), pins[adopted.name])
            segment = adoption['entry']['filename']
            require(Path(segment).name == segment and is_sha(adoption['entry']['file_sha256']),
                    'protected interval has an invalid sealed file reference')
            store_files.update((*pins, segment))
            if interval >= (number-1)//4:
                archive = aside/f'protected-{interval:04d}'
                disposition = {'interval': interval, 'archive': str(archive), 'records': pins,
                               'before': adoption['catalog_digest'],
                               'after': None if preceding is None else preceding[0],
                               'parent_adopted_sha256': None if preceding is None else preceding[1],
                               'filename': segment, 'interval_sha256': adoption['entry']['file_sha256']}
                intervals.append(disposition)
                for step in steps:
                    name = step['step']
                    if int(name.split('-')[0]) >= number:
                        groups[name] = cls.attempt_moves(chain.attempt, aside/'attempt', mode, step,
                                                         active_attempt)
            preceding = adoption['catalog_digest'], pins[adopted.name]
        actual = set(tree_inventory(chain.store, hashed=False)[2])
        require(actual == store_files,
                f'active interval store ownership differs, extra {sorted(actual-store_files)[:5]}, '
                f'missing {sorted(store_files-actual)[:5]}')
        require(number % 4 == 1, 'the first affected protected group must start at its interval producer')
        return cls(chain, aside, groups, intervals, chain.journal['resume']['from'], chain.earlier)

    @staticmethod
    def record_pins(store, interval, steps):
        suffix = f'-interval-{interval:04d}.json'
        names = (('runner-record', 'sealed-awaiting-reader'), (), ('reader-verdict',), ('adopted',))
        return {stem+suffix: step['outputs'][str(store/(stem+suffix))]
                for step, owned in zip(steps, names, strict=True) for stem in owned}

    @staticmethod
    def attempt_moves(attempt, archive, mode, step, active):
        phase = step['step'].rsplit('-', 1)[-1]
        reader = folder('reader', mode)
        if phase in ('producer', 'reader'):
            key = folder('run', mode) if phase == 'producer' else reader
            names = (key, f'launch-{key}', f'{key}.tracking.json')
        elif phase == 'finalise':
            names = (reader+'/reopen-final.json',)
        else:
            names = ()
        checkpoint = checkpoint_attempt(step)
        result = []
        for relative_name in names:
            path = attempt/relative_name
            skip = 'reopen-final.json' if phase == 'reader' and relative_name == reader else None
            excluded = None if skip is None else relative_name+'/'+skip
            expected = {name: size for name, size in checkpoint.items()
                        if (name == relative_name or name.startswith(relative_name+'/')) and name != excluded}
            observed = {name: size for name, size in active.items()
                        if (name == relative_name or name.startswith(relative_name+'/')) and name != excluded}
            require(observed == expected, f'{step["step"]} has missing, changed or unassigned attempt files: {path}')
            if not expected:
                require(not os.path.lexists(path), f'{step["step"]} has an unassigned attempt destination: {path}')
                continue
            pins = {str(Path(name).relative_to(path)) if not same_path(name, path) else '': pin
                    for name, pin in step['outputs'].items() if inside(name, path)}
            saved = (archive.parent/'finalise' if phase == 'finalise' else archive)/relative_name
            directory = relative_name not in expected
            digest = (intent_digest({name[len(relative_name)+1:]: size for name, size in expected.items()})
                      if directory else sha_file(check3_ordinary_file(path)))
            result.append({'live': str(path), 'saved': str(saved), 'exclude': skip, 'pins': pins,
                           'directory': directory, 'digest': digest})
        recorded = {name for name in step['outputs'] if relative(name, attempt) is not None}
        claimed = {str(row['live'] if not name else Path(row['live'])/name)
                   for row in result for name in row['pins']}
        require(recorded == claimed, f'{step["step"]} attempt receipt is outside its original owner group')
        return result

    def deferred(self, name):
        return name in self.groups and (not self.resuming or not passed_in(self.chain.reusable.get(name)))

    def predecessor_matches(self, name):
        interval = (int(name.split('-')[0])-1)//4
        if interval == 0:
            return True
        disposition = next(row for row in self.intervals if row['interval'] == interval)
        parent = self.chain.store/f'adopted-interval-{interval-1:04d}.json'
        return parent.is_file() and sha_file(check3_ordinary_file(parent)) == disposition['parent_adopted_sha256']

    def transition(self, action, *, disposition=None, moves=(), step=None, check_receipt=None):
        c = self.chain
        journal = (c.journal_dir/'CHAIN-JOURNAL.json').resolve(strict=True)
        c.save()
        intent = {'action': action, 'store': str(c.home_admission.store), 'journal': str(journal),
                  'earlier': self.origin,
                  'config': {'path': str(Path(c.config_path).resolve()), 'sha256': c.config_sha},
                  'disposition': disposition, 'moves': list(moves), 'archive': str(self.aside), 'step': step}
        c.checkpoint = c.home_admission.transition(c, intent, check_receipt=check_receipt)

    def park(self):
        c = self.chain
        record = c.journal['resume'].setdefault('mixed', {'archive': str(self.aside), 'origin': self.origin,
                    'groups': self.groups, 'intervals': self.intervals, 'committed': []})
        if os.path.lexists(c.attempt.parent/'completed-heat'):
            record['completed_heat'] = 'retained for the existing owner to verify each pinned input and worker source'
        parked = {row['interval'] for row in record['committed'] if row['action'] == 'park'}
        for disposition in reversed(self.intervals):
            n = disposition['interval']
            if n in parked:
                continue
            stages = [name for name in self.groups if (int(name.split('-')[0])-1)//4 == n]
            moves = [move for name in reversed(stages) for move in self.groups[name]]
            self.transition('park', disposition=disposition, moves=moves)

    def restore(self, name, check_receipt):
        c = self.chain
        completed = next((row for row in reversed(c.journal['resume']['mixed']['committed'])
                          if row['step'] == name), None)
        if completed is not None:
            # A recovered step may have completed its owner transition just before writing its ordinary entry.
            old = self.original[name]
            require(all(check_receipt(path, check3_ordinary_file(path), pin) for path, pin in old['outputs'].items()),
                    f'{name}: completed mixed transition no longer has its pinned outputs')
            c.checkpoint = completed['checkpoint']
            return
        n = (int(name.split('-')[0])-1)//4
        disposition = next(row for row in self.intervals if row['interval'] == n)
        moves = list(self.groups[name])
        phase = name.rsplit('-', 1)[-1]
        if phase == 'adopt':
            self.transition('restore', disposition=disposition, step=name, check_receipt=check_receipt)
            return
        if phase in ('producer', 'finalise'):
            step = self.original[name]
            pins = {Path(path).name: pin for path, pin in step['outputs'].items() if Path(path).parent == c.store}
            if phase == 'producer':
                pins[disposition['filename']] = disposition['interval_sha256']
            for filename, pin in pins.items():
                moves.append({'live': str(c.store/filename), 'saved': str(Path(disposition['archive'])/filename),
                              'exclude': None, 'pins': {'': pin}, 'directory': False, 'digest': pin})
        self.transition('files', disposition=disposition, moves=moves, step=name, check_receipt=check_receipt)


def move_digest(path, directory, excluded):
    if not directory:
        return sha_file(check3_ordinary_file(path))
    sizes = tree_inventory(path, hashed=False)[2]
    if excluded is not None:
        sizes.pop(excluded, None)
    return intent_digest(sizes)


def checkpoint_attempt(step):
    ref = step['checkpoint']
    record, _ = read_json(ref['path'], ref['sha256'])
    attempt = record['attempt']
    require(type(attempt) is dict and all(type(size) is int and size >= 0 for size in attempt.values()),
            f'{step["step"]} lacks a producing attempt size inventory')
    return attempt


class ProtectedTransitionOwner:
    """Run the interval owner's checked operation inside r39's exclusive admission."""
    def __init__(self, config, profile):
        self.config, self.profile = config, profile
        self.trees = protected_trees(profile)
        self.engine = None
        self._assigned = None
        self._transition_config = None

    def assigned(self):
        if self._assigned is not None:
            return self._assigned
        issue, _ = read_json(self.config['issue_record']['path'], self.config['issue_record']['sha256'])
        assignment = issue.get('protected_home_assignment')
        if assignment is None:
            self._assigned = False
            return False
        require(issue.get('status') == REVIEWED and type(assignment) is dict and
                set(assignment) == {'trees', 'exclusive_handback'} and
                assignment['trees'] == self.trees and
                type(assignment['exclusive_handback']) is str and assignment['exclusive_handback'].strip(),
                'protected home has no reviewed assignment and exclusive handback for the selected clients')
        roots = tuple(self.trees.values())
        require(not any(inside(first, second) or inside(second, first)
                        for i, first in enumerate(roots) for second in roots[i+1:]),
                'protected home trees overlap')
        self._assigned = True
        return True

    def load_engine(self):
        if self.engine is None:
            workspace = Path(self.profile['workspace']).resolve(strict=True)
            path = check3_ordinary_file(workspace/self.profile['native_root']/'atlas_runtime.py')
            runtime = load_module('_r39_transition_runtime', path)
            profile = self.config['profile']
            self.engine = runtime._load_engine('reopen_fresh_restart', profile['path'], profile['sha256'])
        return self.engine

    def __call__(self, access, journal_path, journal, intent, begin, *, check_receipt=None):
        require(self.assigned(), 'protected output has no established admitting owner')
        require(not any(inside(root, access.control) or inside(access.control, root) for root in self.trees.values()),
                'protected home trees overlap their admission control directory')
        config_ref = intent['config']
        if self._transition_config is None or self._transition_config[0] != config_ref:
            original, _ = load_config(config_ref['path'], config_ref['sha256'])
            self._transition_config = (dict(config_ref), original)
        original = self._transition_config[1]
        require(original['profile'] == self.config['profile'] and original['issue_record'] == self.config['issue_record']
                and original['package'] == self.config['package'] and
                same_path(journal_path.parent, original['journal_directory']) and
                journal.get('config_sha256') == config_ref['sha256'],
                'protected transition differs from its original checked configuration')
        previous = intent['earlier']
        origin = member(journal, 'resume', 'mixed', 'origin')
        require(previous == (origin if origin is not None else journal['resume']['from']),
                'protected transition names a different producing journal')
        producing_journal, _ = read_json(previous['path'], previous['sha256'])
        identities, unknown = recorded_identities(producing_journal)
        require(not unknown and not any(process_alive(identity) for identity in identities),
                'protected transition still has an earlier driver or step process owner')
        engine = self.load_engine()
        from atlas_tectonics._private.integration import interval_admission
        from atlas_tectonics._private.codecs import interval_catalog
        from atlas_tectonics._private.codecs.content_cache import create_retained_scope
        from atlas_tectonics.integration.resources import WorkBudget

        planned = intent['disposition']
        archive = interval_catalog.safe_path(planned['archive'])
        aside = interval_catalog.safe_path(intent['archive'])
        home = Path(self.trees['attempt']).parent
        require(aside.parent == home and archive.parent == aside and
                not any(inside(aside, root) or inside(root, aside) for root in (*self.trees.values(), access.control)) and
                aside.name.startswith('resume-aside-'),
                'protected archive is outside its assigned aside')
        action = intent['action']
        if action == 'park':
            archive.mkdir(parents=True, exist_ok=True)
        moves = self.checked_moves(intent['moves'], action, aside, archive, interval_catalog, planned, check_receipt)
        scope = create_retained_scope(WorkBudget(engine.MONITOR.machine_memory()),
                                      process_epoch='r39-protected-'+str(os.getpid()))
        def agrees(actual):
            require(actual == (dict(planned, restoring=True) if action == 'restore' else planned),
                    'protected interval differs from its journaled disposition')
            begin()
        with interval_admission.inherit_exclusive(access):
            try:
                if action == 'park':
                    engine.park_retained_interval(access.store, archive, planned['interval'],
                        pins=planned['records'], parent_adopted_pin=planned['parent_adopted_sha256'],
                        scope=scope, assert_exclusive=access.require_exclusive, save_disposition=agrees)
                elif action == 'restore':
                    def check_adoption(path, pin, record):
                        require(check_receipt(path, path, pin, record),
                                'restored adoption differs from its pinned producer receipt')
                    engine.restore_retained_interval(access.store, planned, scope=scope,
                        assert_exclusive=access.require_exclusive, save_disposition=agrees,
                        check_adoption=check_adoption if check_receipt is not None else None)
                else:
                    require(action == 'files', 'unknown protected transition action')
                    from atlas_tectonics._private.codecs.interval_store_set import catalog_transient_charge
                    active_catalog = access.store/'interval-catalog.json'
                    active = None
                    if active_catalog.exists():
                        size = interval_catalog.file_token(active_catalog)[2]
                        with scope.run_budget.reserve(catalog_transient_charge(size), category='retained-catalog-predecessor'):
                            active = interval_catalog._read_catalog_image(active_catalog, expected_size=size)[1]
                    require(active == planned['after'], 'retained outputs have a different catalog predecessor')
                    if planned['interval']:
                        parent = access.store/f"adopted-interval-{planned['interval']-1:04d}.json"
                        require(sha_file(check3_ordinary_file(parent)) == planned['parent_adopted_sha256'],
                                'retained outputs have a different parent adoption record')
                    begin()
                for source, target in moves:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    interval_admission.durable_move(source, target)
            finally:
                scope.close()
            access.require_exclusive()
            paths = {label: Path(root) for label, root in self.trees.items()}
            checkpoint = journal_path.parent/f'protected-{intent_digest(intent)}.json'
            return live_checkpoint(paths, checkpoint, replace=interval_admission.durable_replace)

    def checked_moves(self, rows, action, aside, archive, catalog, disposition, check_receipt):
        result = []
        protected = dict(disposition['records'], **{disposition['filename']: disposition['interval_sha256']})
        for row in rows:
            live, saved = (catalog.safe_path(row[key]) for key in ('live', 'saved'))
            require((relative(live, self.trees['attempt']) is not None and relative(saved, aside) is not None) or
                    (action == 'files' and same_path(live.parent, self.trees['store']) and saved == archive/live.name
                     and protected.get(live.name) == row['digest'] and not row['directory']),
                    'protected output move is outside its owner paths')
            source, target = (live, saved) if action == 'park' else (saved, live)
            require(os.path.lexists(source) != os.path.lexists(target),
                    'protected output is missing or has a conflicting owner: '+str(live))
            present = source if os.path.lexists(source) else target
            pin = row['digest']
            matches = (check_receipt(live, check3_ordinary_file(present), pin)
                       if check_receipt is not None and not row['directory'] else
                       move_digest(present, row['directory'], row['exclude']) == pin)
            require(matches,
                    'protected output changed before transition: '+str(live))
            for name, pin in row['pins'].items():
                if not name and not row['directory'] and pin == row['digest']:
                    continue
                path = check3_ordinary_file(present/name if name else present)
                require(not name or relative(path, present) is not None,
                        'protected output escaped its move: '+str(live))
                matches = (sha_file(path) == pin if check_receipt is None else
                           check_receipt(live/name if name else live, path, pin))
                require(matches,
                        'protected output differs from its journal pin: '+str(live))
            if present == source:
                result.append((source, target))
        return result


class DriverHomeAdmission:
    """Own the driver's access mode while the caller retains the separate driver claim."""
    def __init__(self, module, store, owner=None):
        self.module = module
        self.store = module.canonical_store(store)
        self.shared = None
        self.owner = owner

    def enter_shared(self):
        scope = self.module.admitted((self.store,))
        scope.__enter__()
        self.shared = scope

    def leave_shared(self):
        if self.shared is not None:
            scope, self.shared = self.shared, None
            scope.__exit__(None, None, None)

    def transition(self, chain, intent, *, check_receipt=None):
        journal_path = (chain.journal_dir/'CHAIN-JOURNAL.json').resolve(strict=True)
        reference = {'journal': str(journal_path), 'intent_sha256': intent_digest(intent)}
        self.leave_shared()
        with self.module.admitted((self.store,), exclusive=True) as held:
            journal, _ = read_json(journal_path)
            require(journal == chain.journal, 'restart journal changed before protected transition')
            self.complete(held[self.store], journal_path, chain.journal, intent,
                          reference=reference, check_receipt=check_receipt)
        self.enter_shared()
        return chain.journal['protected_transition']['result']

    def recover(self, config):
        try:
            self.enter_shared()
            return None
        except self.module.RecoveryRequired:
            pass
        with self.module.admitted((self.store,), exclusive=True, recovery=True) as held:
            access = held[self.store]
            reference = access.pending()
            require(type(reference) is dict and set(reference) == {'journal', 'intent_sha256', 'store'}
                    and is_sha(reference['intent_sha256']), 'invalid pending driver transition reference')
            path = check3_ordinary_file(reference['journal'])
            require(path.name == 'CHAIN-JOURNAL.json', 'pending transition names a foreign journal')
            journal, before = read_json(path)
            pinned_resume = config['resume_from']
            if pinned_resume is not None and same_path(path, pinned_resume['path']):
                require(before == pinned_resume['sha256'], 'pending resume journal differs from its configured pin')
            saved = journal.get('protected_transition')
            require(journal.get('schema') == JOURNAL_SCHEMA and type(saved) is dict and
                    intent_digest(saved.get('intent')) == reference['intent_sha256'],
                    'pending transition does not bind its journal intent')
            self.complete(access, path, journal, saved['intent'])
            after = sha_file(path)
        self.enter_shared()
        return (path, before, after)

    def complete(self, access, journal_path, journal, intent, *, reference=None, check_receipt=None):
        access.require_exclusive()
        require(intent.get('store') == str(self.store) and intent.get('journal') == str(journal_path),
                'protected transition has a different store or journal')
        require(self.owner is not None, 'protected output has no established admitting owner')
        def save():
            save_journal(journal_path, journal, self.module.durable_replace)
        def begin():
            if reference is not None:
                journal['protected_transition'] = {'intent': intent, 'phase': 'pending'}
                save()
                access.publish_pending(reference)
        result = self.owner(access, journal_path, journal, intent, begin, check_receipt=check_receipt)
        require(access.pending() is not None, 'protected transition did not publish its recovery reference')
        journal['protected_transition'] = {'intent': intent, 'phase': 'complete', 'result': result}
        mixed = member(journal, 'resume', 'mixed')
        if mixed is not None:
            transition = {'intent_sha256': intent_digest(intent), 'action': intent['action'],
                          'interval': intent['disposition']['interval'], 'step': intent['step'], 'checkpoint': result}
            if not mixed['committed'] or mixed['committed'][-1] != transition:
                mixed['committed'].append(transition)
        save()
        access.clear_pending()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--config', required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--run-profile', default='off')
    parser.add_argument('--profile-tool', type=Path, help='with --run-profile tree: the sampling profiler executable')
    args = parser.parse_args(argv)
    try:
        config, digest = load_config(args.config, args.config_sha256)
        admission, profile, source_selection = load_home_owner(config)
        with admission.driver_claim(profile['store_directory']):
            home = DriverHomeAdmission(admission, profile['store_directory'],
                                       ProtectedTransitionOwner(config, profile))
            recovery = home.recover(config)
            try:
                if recovery is not None and config['resume_from'] is not None and same_path(recovery[0], config['resume_from']['path']):
                    config = dict(config, resume_from=dict(config['resume_from'], sha256=recovery[2]))
                chain = Chain(config, digest, args.config, home_admission=home,
                              checked_profile=(profile, source_selection))
                if recovery is not None:
                    chain.journal['recovered_transition'] = dict(zip(('path', 'prior_sha256', 'sha256'),
                                                                      (str(recovery[0]), *recovery[1:]), strict=True))
                code = chain.execute(args.run_profile, args.profile_tool)
            finally:
                home.leave_shared()
    except Exception as error:  # noqa: BLE001
        print(json.dumps({'status': 'REFUSED', 'error': f'{type(error).__name__}: {error}'}), flush=True)
        return 1
    print(('[NOT SCIENTIFICALLY PERMISSIBLE] ' if 'not_scientifically_permissible' in chain.journal else '') +   # BR1
          json.dumps({'status': chain.journal['status'], 'stop': chain.journal.get('stop'),
                      'journal': str(chain.journal_dir/'CHAIN-JOURNAL.json')}), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
