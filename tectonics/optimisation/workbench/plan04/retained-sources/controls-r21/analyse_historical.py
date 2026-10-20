"""Reinterpret retained complete evidence; never execute a test or queue job."""
import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from support import digest, read_json, require, verify_pins, write_new
from report import interpret


def main():
    selection = read_json(ROOT / "SELECTION-r20-r2.json")
    verify_pins(selection["pins"])
    full = read_json(ROOT / "evidence-r2/mutation-controls/result.json")
    row = full["results"]["observer path unchecked"]
    verify_pins(row["evidence"])
    folder = ROOT / "evidence-r2/mutation-controls/m26"
    summary = read_json(folder / "summary.json")
    events = [json.loads(line) for line in (folder / "summary.events.jsonl").read_text().splitlines()]
    new_map = read_json(ROOT / "diagnostic-predicate-r2.json")
    revised = interpret(row["process"], summary, events, (folder / "run/stderr.txt").read_text(),
                        summary["expected"], new_map["predicates"])
    require(revised["admitted"] and revised["intended_kill"], "Diagnostic predicate did not match")
    require(all(check["actual_status"] == "FAIL" for match in revised["matched"]
                for check in match["checks"]), "Unexpected semantic detection")
    epoch = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
    overlap = []
    start_other = datetime.datetime.fromisoformat("2026-10-20T06:58:57+00:00")
    for label, item in full["results"].items():
        process = item["process"]
        start = epoch + datetime.timedelta(microseconds=process["ownership"]["creation_filetime"] / 10)
        end = start + datetime.timedelta(seconds=process["elapsed_seconds"])
        if end > start_other:
            overlap.append({"label": label, "start_utc": start.isoformat(), "end_utc": end.isoformat()})
    result = {
        "status": "HISTORICAL_SCOPE_ONLY",
        "original_result_sha256": digest(ROOT / "evidence-r2/mutation-controls/result.json"),
        "predicate_map_sha256": digest(ROOT / "diagnostic-predicate-r2.json"),
        "analysis_source_sha256": digest(Path(__file__)),
        "observer_path_supplement": {"category": "diagnostic", "report": revised,
                                     "behaviour_certified": False},
        "original_categories_unchanged": full["categories"],
        "mixed_failure_error": full["results"]["peer branch breaks"]["report"],
        "unproved_stop_survivor": full["results"]["unproved stop excusable"]["report"],
        "queue_overlap": {"other": "Plan6 q26", "reported_start_utc": start_other.isoformat(),
                          "affected_mutants": overlap, "isolated_timing_claim": False},
        "readiness": False, "scientific_capture": False,
    }
    write_new(ROOT / "HISTORICAL-ANALYSIS.json", result)
    print(json.dumps({"diagnostic_supplement": revised["intended_kill"],
                      "historical_behaviour": "31/34", "overlap_count": len(overlap)}))


if __name__ == "__main__":
    main()
