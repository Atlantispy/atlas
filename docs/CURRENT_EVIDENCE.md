# Current evidence register

26 September 2026. WORKING NON-CANON. Roadmap Phase A2.

Old receipts remain useful history, but documentation must not present one as
evidence about the current checkout after the bytes it bound have changed. The
[register](../tectonics/evidence/current-evidence.json) is the explicit list of
classified evidence; `tools/check_current_evidence.py` is its read-only checker.

## Run it

From the repository root, standard library only (Python 3.10 or later):

```text
python -B tools/check_current_evidence.py
python -B -m unittest discover -s tests -p test_current_evidence.py -v
```

The checker never imports Atlas, runs a campaign, edits a receipt, repins a
digest or writes a file. It exits 0 on a pass and 1 on any failure. Each failure
names the record, the receipt field, the bound file and both digests. `--register`
selects another repository-relative register; paths inside a register are always
repository-relative.

## What each status means

| Status | Meaning | Checked |
| --- | --- | --- |
| `current` | Relied upon for a claim about this checkout. | The receipt must keep its registered bytes. Every repository file it binds must still have the recorded SHA-256. Every digest-bearing receipt field must be either a checked binding or an explicit `not_checked` entry (`runtime`, `artefact` or `historical`) with a reason. |
| `historical` | Retained for its recorded source snapshot; not a current claim or new validation. | Only that the file still exists with its registered bytes. Code moving on never fails it. |
| `superseded` | Replaced for current claims by the named `superseded_by` record. | As historical. The successor must exist, must not be invalid and must not form a cycle. No current record may bind it. |
| `invalid` | Known to be wrong for its own sources; kept only as a trail. | As historical. No current record may bind it, and it cannot be a successor. |

A pass means only that the declared bytes match. It is **not** runtime,
native-execution, platform or scientific verification. Recorded timings and PASS
results remain observations of the original run. Nothing is re-executed.

## Coverage today

- **Current I01 design controls:** [four bounded controls](../tectonics/evidence/i01-controls-r1.json)
  bind their tool, declared case policy and physical-contract document. The four
  controls pass, but do not establish 2D fault generation, physical rupture,
  global evolution or regional water/flexure coupling. Runtime versions are
  observations, not sealed library binaries. No native package is imported.
- **Current:** the Step 7 r2 predeclared matrix and the
  [B1 matched boundary diagnostics](../tectonics/evidence/boundary-kinematics-r1.json).
  B1 checks its tool and two portable input bindings, not a native simulation or
  transitive runtime seal; its source/runtime limitations remain explicit.
  The [Windows installation receipt](../tectonics/evidence/environment-install.json)
  also remains current against its package-version JSON record. Its local smoke
  script, wheel archives and runtime are not repository bindings. It records one
  successful installation, not continuing PyPI availability, current Atlas behaviour
  or a fresh byte audit of installed libraries. Requirement-file consistency is
  checked separately by the environment checker.
- **Historical:** S2, S3, S4 and S5 r1; Step 7 r2; bundle r1 and r2;
  motion-frame r2; and the
  [line-ending correction trail](../tectonics/evidence/line-ending-digest-correction-r1.json).
- **Superseded:** S7 r1, by S7 r2. Its regional outputs must not be quoted as current.
- **Invalid:** none.

Evidence files that are not listed, including the W01-W12 receipts, are
unclassified. The register makes no claim about them.

Integration review found that A3 changed the native `reuse.py` source after Step 7
r2 and bundle r2 ran. Their adapter hashes still match, but this cannot make
their native integration results current. Motion-frame r2 binds its correction
and assessment files, but its embedded project/session integration and generation
observations use changed or unbound dependencies. The whole receipt is therefore
historical; this does not undo the implemented motion correction. None of the
original receipts, source hashes, measurements or runtime identities was rewritten.

Known dependency drift requires historical classification even when all declared
file bindings still match. An unchecked dependency is not evidence of compatibility.
No physical campaign was rerun merely to obtain a current label.

Receipts may contain identities that cannot be checked locally; the register must
name each one if such a receipt is classified current. Each current record's
`limits` are printed on every run. For
example, `native_execution_id` is an atlas_tectonics loaded-code and runtime
identity, not a file hash. The checker never compares it with a file. So changes
under `tectonics/src/atlas_tectonics` or to the scientific runtime are not
detected here. Generated worlds, job files and output identities live outside the
repository and are listed as artefacts.

## Integration checks

Claude supplied the checker and 19 focused tests. Review corrected the three
whole-record classifications above and tightened strict JSON parsing: exponent
overflow such as `1e999` is now refused instead of silently becoming infinity.
The focused suite recorded 18 passes and one Windows file-symlink-privilege skip
in 0.526 s; the directory-junction refusal passed. That initial checker reported one current
declaration, nine historical records and one superseded record. No simulation ran.
The added fixed-record classification assertion passed separately in 0.033 s.
Public-path scanning and required static source checks also passed; the latter
recorded 30 passes and its existing Windows privilege skip in 0.122 s.

## When it fails

- **A bound source changed.** Produce a successor receipt from the changed code
  and register it, or reclassify the old record as historical and update the
  documents that cite it. Never edit a recorded digest.
- **A registered file changed.** Review the change. An authorised correction needs
  an explicit trail, like the line-ending correction, before its `sha256` is
  updated in the register.
- **Only CRLF line endings differ.** This is still a failure; the message says so.
  `tectonics/.gitattributes` stores these files with LF. Restore the repository
  bytes of the named file after review, as recorded in the correction trail.
- **An unclassified digest field.** Add a checked binding or a `not_checked` entry
  with its reason. Do not drop the field.

## Writing rules

`pointer` is a JSON Pointer into the receipt. A whole segment `*` matches any key
or list index. `{key}` does the same and passes the matched key into the `file`
template; a rule may have at most one. For example, `/source_sha256/{key}` with
file `{key}` checks every path-to-digest entry. Paths use `/` and must stay inside
the repository. Traversal, drive letters, backslashes, streams, device names,
symlinks and reparse points (including junctions) are refused. A binding can
never target an `_id` field. A rule that matches nothing, or a field claimed by
two rules, is a failure.
