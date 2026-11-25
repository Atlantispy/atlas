# Scratch landing tools

Use `tools/atlas.py` to capture or compare a diagnostic arm and prepare a landing in scratch. Give each round a private settings file. References to issued inputs, tools, patches and evidence contain `path` and `sha256`. Relative paths are resolved from the settings file. Use an ordinary scratch output directory with a short path on Windows.

These commands use existing Atlas producers and readers. Submit resource-heavy jobs through the project's queue. The scratch results go to the publication owner. The public `tools/develop.py capture` command continues to create development bindings for the public profiles.

## Capture and compare

```powershell
python -I -B tools/atlas.py land capture-compare --settings .atlas-dev/rounds/strict.json
python -I -B tools/atlas.py land capture-compare --settings .atlas-dev/rounds/historical.json
```

Set `output` and `comparison` in each settings file. The comparison contains a `kind`, an ordered `reference` and `candidate`, and the bound `comparator`. Two comparison contracts are supported.

- `end-capture` compares the stored live IDs, partition, ordered supports and full decoded graph. Supply the pinned extraction helper and parity implementation. For a saved arm, supply the receipt, operands, profile and selected package, config and profile digests. For a fresh arm, supply the issued capture home, config and entries, their interpreters and resource guards, and the permitted operand destination. The command stops at capture, operand reconstruction and comparison. It can resume from the selected root or an already completed capture.
- `decoded-exports` compares materialised restart and record exports with the selected decoder and comparer in a fresh process. Supply each export index and the restart fingerprints where required by the comparison contract. An arm with a missing export can bind a child producer or a legacy binding with the selected decoder and mesh reader. Its home and interpreter are part of the binding. The legacy route writes the mesh using the same scratch store and traversal when creating a complete export. Supply a decoded export to use the standalone mesh extension.

For a pair-specific historical disposition, select its separately approved report with `historical_approval` and leave the rest of the comparison settings and output directory identical. This setting is for `decoded-exports`. An `end-capture` round specifying it returns exit 2 before capture or comparison. The decoded command reuses the existing strict report. The historical approval must cover the same exports and exact differences. For the retained dev43/dev44 replay, strict comparison returned exit 1 with nine unexplained rows. Applying the approved disposition to that result returned exit 0 with all nine explained. A disposable control added an unrelated motion ID difference. The command explained the original nine and returned exit 1 with the motion ID difference unresolved.

The command writes a JSON result containing the selected comparator, both arm bindings, the strict result and any disposition. The result preserves the producer's failure details and the first differing field where one is available.

| Exit | Meaning |
| --- | --- |
| 0 | The selected comparison completed and passed. |
| 1 | The comparison completed with unresolved differences or unmatched records. |
| 2 | A selected input or stage was missing, invalid or incomplete. |

The dev43/dev44 replay reused existing exports. A separate fresh diagnostic run used the retained r6 source, an empty capture destination and the saved r6 arm. It produced the root and sealed interval, reconstructed the operands and returned exit 0 with no strict differences in live IDs, partition, ordered supports or the full decoded graph. The command took 991.781 s and the queue measured 2.11 GiB peak process-tree RSS. These checks cover the diagnostic capture and comparison. IV1 chain, scientific and Release acceptance require their own checks.

## Prepare a landing

```powershell
python -I -B tools/atlas.py land prepare --settings .atlas-dev/rounds/prepare.json
```

Set `base_commit`, `output` and `preparation`. Select an independent composition, a cumulative correction, or an already issued candidate. The first two use a pinned receiving file roster and unit reports with the reviewed patch and per-file preimage and postimage fingerprints. Independent changes with overlapping paths need an explicitly reviewed composition. A cumulative correction binds to its exact predecessor. The issued-candidate route uses the bound diff, declaration, seal and RECORD.

Preparation saves the composition before asking for a receiving issuer. A later invocation with the same composition binding reuses that result and can supply the issuer or the next phase's reviewed inputs. The legacy issuer checks the staged member bytes against the reviewed composition as it reads them. It supports changes to existing members of one exact native parent. Member additions, removals or relocations need an issuer that supports the receiving layout. Templates carry expected fields and replacements. Reviewed issuance additionally needs a passing comparison and an accepted verdict for the exact candidate and issue draft. The command writes the preparation result, kit and available evidence paths. If a prepared artifact is missing on resume, the command returns exit 2.

The scratch rehearsal prepared the published Unit 4 candidate twice with the same composition result, returning exit 0 both times. The independent fixture retained its composed tree across two invocations and returned exit 2 while awaiting an issuer. A conflicting receiving preimage returned exit 2, named the affected file and preserved the earlier composition.

## Optional finite-stock reference case

```powershell
$snapshot = 'tectonics/optimisation/working-snapshot-20261113'
$tempRoot = (Get-Item -LiteralPath ([System.IO.Path]::GetTempPath()) -ErrorAction Stop).FullName
$stagingPath = Join-Path $tempRoot "atlas-e4-$([guid]::NewGuid())"
$packageParent = (New-Item -Path $stagingPath -ItemType Directory -ErrorAction Stop).FullName
try {
    Copy-Item -LiteralPath "$snapshot/atlas_tectonics", 'shared/src/atlas_shared' -Destination $packageParent -Recurse -ErrorAction Stop
    python -I -B tools/e4_collar_finite_adoption.py $packageParent
    if ($LASTEXITCODE -ne 0) { throw "Collar adoption check failed with exit $LASTEXITCODE." }
} finally {
    $staged = Get-Item -LiteralPath $packageParent -ErrorAction Stop
    if ($staged.FullName -ne $packageParent -or $staged.Parent.FullName -ne (Split-Path -Parent $stagingPath) -or
        ($staged.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw "The temporary package folder changed: $packageParent"
    }
    Remove-Item -LiteralPath $staged.FullName -Recurse -Force -ErrorAction Stop
}
```

Run from the repository root with the pinned Atlas interpreter. The commands stage both packages from the same checkout in the adjacent layout used by snapshot CI. You can also point `$packageParent` at an existing staged pair from that checkout.

To reproduce the historical refusal, set `$historicalPackageParent` to the parent of the retained build-3 `atlas_tectonics` package and run it in a fresh process.

```powershell
python -I -B tools/e4_collar_finite_adoption.py $historicalPackageParent
```

The fixture supplies one physical cell and one source stock. It exercises the real finite-stock preparation, spatial solve and collar adoption. In the original paired run, the then-published snapshot adopted the issued proposal in 1.595 s and returned exit 0. The retained build-3 arm reproduced the original collar identity refusal in 2.216 s and returned exit 1. The recorded times include interpreter startup and fixture setup. The fixture covers this adoption path. Full geometry issuance, packed throughput, checkpoint recovery and multiple intervals require their own checks.
