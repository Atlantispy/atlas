# Pressure runtime integration

WORKING NON-CANON. This is the executable receiving route for the selected
[pressure implementation](../README.md), using the existing fresh-profile
runner and pressure worker. It adds an explicit source/profile binding;
existing profiles and defaults are preserved. No run or scientific hold is
released by constructing or opening the binding.

## Construct and open

Run [bind_runtime.py](bind_runtime.py) from this directory in the repository.
Its `plan` and `apply` commands require the explicit local arguments shown by
`--help`: repository, compatible Atlas workspace, predecessor composition and
runtime roots, fresh target/runtime roots, a private evidence directory, and
the SHA-256 of [selection.json](selection.json). There are no inferred runtime
roots, executable placeholder paths or optional source pins. `apply` also
requires the exact plan SHA emitted by `plan` and rederives every output byte.
Existing target roots and previous evidence files are refused.

The input selection pins this binder, [build_profile.py](build_profile.py),
[profile_guards.py](profile_guards.py), [bootstrap_template.py](bootstrap_template.py)
and [runtime_entry.py](runtime_entry.py), plus both source maps and all five
predecessor metadata identities. The builder uses the retained Plan11
composition, inventory, path, input-finality and canonical-encoding guards
without changing their function bodies. The bootstrap renderer retains the
original interpreter, environment, source-loader and finality contracts;
only explicit workspace/root/interpreter and fixed inventory constants are
supplied to the generated executable. These guards are supplied here; no
private builder source is imported.

The complete successor contains 240 native files and 398 helpers. It retains
14 external code and 105 external data references, 21 profile helper bindings,
query limits and runtime policy. The three pressure replacements and midpoint
module have their exact selected bytes. The two geometry/quadrature members
already selected by Plans19–20 are carried forward. Public sanitisation of
older members is bound explicitly to each row's pinned private-original
bytes; DLL placeholders are never executed. Compatible private dependencies
are required and fail closed if absent or changed. This is not a public replay
of historical runs.

The output `runtime-binding.json` pins the fresh profile, whole composition,
generated bootstrap and this public entry. Existing consumers read the new
`fresh-profile.json` through their unchanged `FreshProfile` interface.
`runtime_entry.selected_sources(binding_path, binding_sha256)` opens the
original outer `HelperFinder`, actual `FreshSources.selected`, and actual
`configure_pressure_workers`; it supplies no replacement Atlas loader or
stub. The inherited generated bootstrap remains the existing fresh-launcher
entry for a separately authorised run. Opening the binding requires the
selected Atlas Python with `-B -s -P`, hash seed 0, bytecode writes disabled and
the existing single-thread environment contract.

## Connected caller and worker

The existing `fresh_interval_driver.advance_first_interval` pressure caller
reaches differential-pressure forcing and the selected pressure-wall result
dispatcher. Worker startup serialises this exact fresh profile, reconstructs
the same checked `FreshSources` boundary, then enters the existing native
worker. `PW.batch_worker` issues midpoint custody only around its synchronous
computation on a fresh root ledger; `wall_set` calls spatial-pressure
integration, which calls the selected coupling and midpoint module. Ordinary
parent fallback retains its original ownership and refusal behaviour.

The owner qualifies construction and opening from these actual public files,
including complete source imports before any worker dispatch, and reuses the
accepted numerical evidence for unchanged source bytes. The bounded worker
proof is separate from a process-transport, full-stage or interval campaign.
Historical receipts do not authenticate the new profile. The
[receiving-check record](RECEIVING-CHECKS.json) records construction from these
public files, 299 strict imports, 21 profile helpers and the actual same-process
worker entry: two fast midpoint evaluations, exact serial agreement, explicit
and insufficient-budget declines, exact serial fallback and zero retained
worker charges. The earlier fixture coverage failure is retained. Spawned
transport, parent adoption, full-stage/IV performance and scientific acceptance
remain outside this check; held programme-wide/default work remains separate.

The guard successor addresses the receiving review's F1/F2 findings: emission
uses the validated contract bytes and exclusive PLAN creation; entry checks and
restores the complete import-finder list, retaining body and finality failures.
Five constructor controls and six finder/exit controls pass, including an injected
old defect. The repaired public constructor and entry also pass the actual
299-source/21-helper loader check. The receiving record retains the original
numerical and worker proof identities explicitly; those unchanged calculations
were not rerun or relabelled for the guard successor. Each runtime remains bound
to its declared predecessor; preserving heat publication does not combine the
two runtime generations.

OpenAI Codex prepared this integration under the project owner's direction.
