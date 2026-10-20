# Retained Windows ownership boundary

`owned_windows_job.py` is the retained process-ownership dependency of the r13
launcher. Importing it starts no process or Windows API operation. Its original
design-note and source identities are recorded in `../SOURCE-MAP.json`.

An explicit executable is created suspended with no visible window and a
restricted inherited stdin/stdout/stderr handle list. A non-inheritable,
unnamed Job Object has kill-on-close enabled and no breakaway flags. The
retained suspended child is assigned and membership/accounting checked before
its primary thread resumes. Assignment failure terminates only the retained
suspended child handle; there is no resumed fallback or PID-based termination.

Finality requires both a signalled retained root handle and a successful Job
Object accounting query reporting no active processes. Query failure remains
an error. Timeout/cancellation terminates through the owned Job handle and
attempts bounded cleanup. Kill-on-close is containment, not proof that logs are
final. Missing finality prevents a successful result and later dispatch.

The original implementation cites Microsoft's API documentation for
[process creation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw),
[job assignment](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject),
[restricted handle inheritance](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[job accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)
and [job termination](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject).
These are retained design references, not a claim of fresh API or OS validation.

This source snapshot preserves that helper and its relative lookup path. It
does not supply the original runtime, queue, launch selections or containment
receipts, and does not authorise a new process or scientific run.
