# Writer ownership contract

This is a concise public contract for `ab_heat_r13.py`. Original document and
export identities are recorded in `../SOURCE-MAP.json`. Current outcome and
acceptance status are in `../README.md`.

The observer registers a concrete arena before native acquisition, decoding,
copying or encoding. The callback transfer slot is an ordinary dictionary.
The arena retains call/result arguments until callback finalisation and admits
owner slots before acquisition: `2 * cells + faces + 1`, or 1,305 acquisitions
for 236 cells and 832 faces. This does not require 1,305 simultaneous wrappers.

`copy_owner` returns a separately funded JSON encode/decode copy, including
nested mutable values. Native payloads cannot escape that private synchronous
window. A deliberate alias requires `arena.retain()` before publication.
Failures retain the exact primary exception, callback roots, acquired owners,
failure graph and admitted observer funding; reporting failures do not replace
the primary exception or clear CONTROL frames.

The arena keeps an independent traceback reference. Supported optimised frames
have admitted positive local-reference snapshots. Module/exec frames and
dynamic-local overflow use the explicit incomplete-snapshot fallback. If
snapshot admission/insertion fails, the original traceback remains a concrete
root and `preserve_failure_frames_until_release` is true. The caller must not
destructively clear those owner-held frames. Arbitrary graph or native-object
mutation is outside the contract.

After callback finalisation and after every alias and consumer has finished,
the caller may invoke `release_retained_owner(id, aliases_released=True)`.
This is an explicit caller assertion. Without that knowledge, ownership stays
funded. Release drops retained graph/copy references and reclaims unreachable
traceback cycles while still funded, then drops native wrappers and the lease.
A finalisation failure retains a recoverable owner. Weak references and
negative reachability scans never authorise release.

The writer emits all five arrays, metadata, native cell/face rows, physical
support and exact grid-pool sidecars. Graph volumes, transported enthalpy and
component masses are copied under native ownership and bound to their source,
graph and parent identities. These readers do not issue or solve a model.

Native WorkBudget reservations are logical accounting, not a Python heap or
process RSS bound. The historical 24 MiB projection is not the selected
launcher's admission basis. The selected entry is `launch_plan05_r13.py`;
inherited standalone supervision is disabled. Attempt/output creation is
exclusive, continuations require separately bound authority and prior process
and log finality, and no automatic retry follows a failure.
