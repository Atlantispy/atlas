"""Intended assertion predicates reviewed against the frozen test bodies.

Method/subtest and check arguments identify a semantic assertion. Only a failure
at the exact retained status or needle assertion counts, never a generic assert.
Direct field assertions name their exact adapter source line.
"""


def check(case, status, needle=None, subtest=None):
    return {"case": case, "status": status, "needle": needle, "subtest": subtest,
            "retained_line": 79 if status is not None else 85}


def line(case, number, subtest=None):
    return {"case": case, "adapter_line": number, "subtest": subtest}


PREDICATES = {
    "events never explain": [check("01", "VOID-ENVIRONMENT", "external operator_cancel", "acknowledged")],
    "unproved stop excusable": [check("07_08", "VOID-SUSPECT", "capture provenance")],
    "requested explains": [check("01", "VOID-SUSPECT", "does not establish an external cause", "requested")],
    "no producer pin": [check("02", "FAIL", "differs from the selected pin", "producer")],
    "no nonce check": [check("02", "FAIL", "guard nonce differs", "nonce")],
    "no process check": [check("02", "FAIL", "process differs", "pid")],
    "no sealed refs": [check("05b", "FAIL", "names another sealed arm", "sealed refs")],
    "observer event unchecked": [check("05b", "FAIL", "missing", "requested-only event")],
    "observer process unchecked": [check("05b", "FAIL", "targeted another process or step", "event for another process")],
    "environment over suspect": [check("05d", "VOID-SUSPECT")],
    "repeat passes": [check("11", "REVIEW", "diagnostic repeat rep-1")],
    "second repeat admitted": [check("10", "FAIL", "second diagnostic repeat", "second repeat record")],
    "ordinal unchecked": [check("10", "FAIL", "only one diagnostic repeat", "ordinal 2")],
    "same attempt allowed": [check("10", "FAIL", "must be a new attempt", "same attempt")],
    "profile keys unchecked": [check("10", "FAIL", "changes source/input/profile/budget keys", "changed budget")],
    "approvers subset": [check("10", "FAIL", "exactly one from each pinned approver", "two approvals")],
    "rejection counts": [check("10", "FAIL", "is not an approval", "rejection")],
    "owner optional": [check("10", "FAIL", "including OWNER", "pins without OWNER")],
    "retained bytes unchecked": [check("02", "FAIL", "retained file bytes differ", "retained file changed after reference")],
    "binding unchecked": [check("02", "FAIL", "bound to another", "attempt")],
    "pre-start traces ignored": [check("12", "FAIL", "claims pre-start", "pre-start refuted by capture")],
    "event step ignored": [check("01b", "VOID-SUSPECT", subtest="observer step")],
    "host restart explains": [check("01", "VOID-SUSPECT", "no independent host/execution binding", "host_restart acknowledged")],
    # Wording is deliberately diagnostic, never counted as a behaviour kill.
    "automatic not refused": [{"case": "01", "status": "VOID-SUSPECT",
                               "needle": "does not establish an external cause",
                               "subtest": "automatic launcher action", "retained_line": 85}],
    "first trigger ignored": [check("13", "VOID-SUSPECT", "first trigger 'free_memory_floor'", "free floor first")],
    "cleanup ignored": [check("13", "VOID-SUSPECT", "cleanup is not complete", "cancel not exited")],
    "observer path unchecked": [check("15", "FAIL", "not an ordinary file with the pinned observer bytes", "path None")],
    "termination unbound": [check("15", "FAIL", "does not bind this observer", "termination interval")],
    "observer void breaks": [line("05c", 643)],
    "observer void pops proofs": [line("05", 607)],
    "chain only without void": [check("14", "FAIL", "after: interval width gate is not the gate of the recorded", "cross-stage chain")],
    "pre-start outcome lost": [{"case": "12", "status": "VOID-SUSPECT",
                              "needle": "is a pre-start claim: no workload outcome",
                              "subtest": None, "retained_line": 85}],
    "claimant gate needs peer": [check("16", "FAIL", "after arm interval width gate",
                                      "reference interval unresolved, candidate gate false")],
    "claimed gate ignored": [check("16", "FAIL", "after arm interval width gate",
                                  "reference interval unresolved, candidate gate false")],
    "peer branch breaks": [check("16", "FAIL", "after arm interval width gate",
                                 "reference root unresolved, candidate gate false")],
    "unreached arm counted": [check("16", "VOID-SUSPECT", subtest="stale reference interval files after its own root stop")],
}
