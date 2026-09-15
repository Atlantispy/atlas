"""Real rule/SQL preparation with synthetic, non-canon sites and fault injection."""
from __future__ import annotations

import contextlib
import io
import multiprocessing
import pickle
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

import build_stage6d_population as population
import generation_runtime as runtime


def sites(count=12, varied=False):
    hausen = sorted(population.human_rules.EXPECTED_HAUS_IDS) if varied else ["BUCHHAIN"]
    result = []
    for index in range(count):
        haus = hausen[index % len(hausen)]
        result.append({
            "settlement_id": f"S{index:04d}", "owner_haus_id": haus,
            "economic_network_id": haus, "barony_id": index // 3,
            "county_uid": "C1", "duchy_uid": "D1",
            "functional_tier": "FT3_LOCAL_CENTRE",
            "realised_settlement_form": "GENERAL_SETTLEMENT",
            "effective_vertical_domain": "SURFACE",
            "ordinary_permanent_human_allowed": 1,
            "analysis_anchor_x_km": index + 0.25,
            "analysis_anchor_y_km": 12.5,
            "stage6c_analysis_status": (
                "DEFERRED_SPECIALIST_3D" if varied and index % 7 == 0 else "COMPLETE"
            ),
            "stage6c_review_status": "WORKING_PROPOSAL",
            "stage6c_input_fingerprint": "synthetic",
        })
    return result


def resolved_plans(count=12, varied=False):
    rows = sites(count, varied)
    plans, _ = population._make_site_plans_serial(rows)
    for plan in plans:
        plan.working_total = plan.structural_total
    population._resolve_splits(plans)
    return rows, plans


def _deep_size(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    total = sys.getsizeof(value)
    if isinstance(value, dict):
        return total + sum(_deep_size(key, seen) + _deep_size(item, seen) for key, item in value.items())
    if isinstance(value, (tuple, list, set, frozenset)):
        return total + sum(_deep_size(item, seen) for item in value)
    if hasattr(value, "__dict__"):
        return total + _deep_size(vars(value), seen)
    return total


def measure_batch_payloads():
    """Audit synthetic full-schema rows, every Haus and actual prepared SQL.

    Conservative envelope: both decoded object graphs in parent and child plus
    four simultaneous serialised/pipe copies. Interpreter memory is separate.
    This is measured fixture coverage, not a bound on arbitrarily large strings.
    """
    evidence = []
    with contextlib.closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(population.schema.SIDECAR_DDL)
        columns = [row[1] for row in connection.execute("PRAGMA table_info(stage6d_source_site)")]
    for haus in sorted(population.human_rules.EXPECTED_HAUS_IDS):
        rows = sites(population.POPULATION_BATCH_SIZE)
        for row in rows:
            row["owner_haus_id"] = row["economic_network_id"] = haus
            if haus in {"LAUBRAUNEN", "VERFUEHRSCHLUND"}:
                row["realised_settlement_form"] = "EMBEDDED_NATIVE_ENCLAVE"
            for column in columns:
                row.setdefault(column, None)
        plans, _ = population._make_site_plans_serial(rows)
        if not plans:
            continue
        for plan in plans:
            plan.working_total = plan.structural_total
        population._resolve_splits(plans)
        task = ("TEST", tuple(plans))
        result = population._prepare_population_statements(task)
        input_pickle, output_pickle = len(pickle.dumps(task)), len(pickle.dumps(result))
        input_objects, output_objects = _deep_size(task), _deep_size(result)
        evidence.append({
            "haus_id": haus, "sites": len(plans),
            "input_pickle_bytes": input_pickle, "output_pickle_bytes": output_pickle,
            "input_object_bytes": input_objects, "output_object_bytes": output_objects,
            "conservative_batch_bytes": 2 * (input_objects + output_objects) + 4 * (input_pickle + output_pickle) + 2048,
        })
    return evidence


class TrackedWriter:
    def __init__(self, connection=None):
        self.connection = connection
        self.thread = threading.get_ident()
        self.statements = []

    def execute(self, sql, parameters):
        if threading.get_ident() != self.thread:
            raise AssertionError("SQLite escaped the coordinator thread")
        self.statements.append((sql, tuple(parameters)))
        if self.connection is not None:
            return self.connection.execute(sql, parameters)


def database_for(rows, *, profiles=True):
    connection = sqlite3.connect(":memory:")
    connection.executescript(population.schema.SIDECAR_DDL)
    connection.execute("INSERT INTO stage6d_run VALUES (?,?,?,?,?,?,?,?,?)", (
        "TEST", "synthetic", population.schema.SCHEMA_VERSION,
        population.schema.METHOD_VERSION, "a" * 64, "{}", "{}",
        population.schema.CANON_STATUS, "RUNNING",
    ))
    for row in rows:
        columns = tuple(row)
        connection.execute(
            f"INSERT INTO stage6d_source_site ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(row[column] for column in columns),
        )
    if profiles:
        population._insert_profiles(connection)
    connection.commit()
    return connection


class PopulationParallelTests(unittest.TestCase):
    def test_private_batch_estimate_includes_objects_and_ipc_copies(self):
        evidence = measure_batch_payloads()
        self.assertEqual(len(evidence), 18)  # Mobile/shared-only Hausen have no site rows.
        self.assertLess(max(row["conservative_batch_bytes"] for row in evidence),
                        population.POPULATION_BATCH_ESTIMATED_BYTES)

    def test_all_haus_rules_and_exception_order_equal_serial_reference(self):
        rows = sites(80, varied=True)
        reference = population._make_site_plans_serial(rows)
        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 3):
            parallel = population._make_site_plans(rows, workers=4, memory_budget_mb=64)
        self.assertEqual(reference, parallel)
        original_by_id = {row["settlement_id"]: row for row in rows}
        self.assertTrue(parallel[1], "fixture must exercise real exception results")
        for plan in parallel[0]:
            self.assertIsNot(plan.site, original_by_id[plan.settlement_id])

    def test_actual_rule_calls_overlap_and_results_stay_ordered(self):
        rows = sites(3)
        barrier = threading.Barrier(3)
        original = population.rules.structural_human_population_band
        threads = set()
        lock = threading.Lock()

        def overlapping(site):
            with lock:
                threads.add(threading.get_ident())
            barrier.wait(timeout=5)
            return original(site)

        stats = runtime.RuntimeStats()
        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1), mock.patch.object(
            population.rules, "structural_human_population_band", side_effect=overlapping,
        ):
            plans, exceptions = population._make_site_plans(
                rows, workers=3, memory_budget_mb=48, runtime_stats=stats,
            )
        self.assertFalse(exceptions)
        self.assertEqual([plan.settlement_id for plan in plans], [row["settlement_id"] for row in rows])
        self.assertEqual(len(threads), 3)
        self.assertNotIn(threading.get_ident(), threads)
        self.assertEqual(stats.counts["population_site_preparation.peak_active_workers"], 3)

    def test_memory_admission_caps_both_preparation_phases(self):
        rows, plans = resolved_plans()
        stats = runtime.RuntimeStats()
        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1):
            population._make_site_plans(rows, workers=8, memory_budget_mb=16, runtime_stats=stats)
            population._insert_site_populations(
                TrackedWriter(), "TEST", plans, workers=8, memory_budget_mb=16, runtime_stats=stats,
                preparation_backend="thread",
            )
        for phase in ("population_site_preparation", "population_row_preparation"):
            self.assertEqual(stats.counts[f"{phase}.worker_limit"], 1)
            self.assertEqual(stats.counts[f"{phase}.peak_active_workers"], 1)
            self.assertEqual(stats.counts[f"{phase}.peak_inflight"], 1)

    def test_parallel_statements_and_real_sqlite_rows_are_exact_and_ordered(self):
        rows, plans = resolved_plans(40, varied=True)
        with contextlib.closing(database_for(rows)) as serial_db, contextlib.closing(database_for(rows)) as parallel_db:
            serial, parallel = TrackedWriter(serial_db), TrackedWriter(parallel_db)
            expected = population._insert_site_populations_serial(serial, "TEST", plans)
            with mock.patch.object(population, "POPULATION_BATCH_SIZE", 2):
                actual = population._insert_site_populations(parallel, "TEST", plans, workers=4,
                                                             preparation_backend="process")
            self.assertEqual(expected, actual)
            self.assertEqual(serial.statements, parallel.statements)
            for table in ("stage6d_population_pool", "stage6d_pool_anchor", "stage6d_population_attribution",
                          "stage6d_population_assignment", "stage6d_population_estimate"):
                self.assertEqual(
                    serial_db.execute(f"SELECT * FROM {table} ORDER BY 1,2,3").fetchall(),
                    parallel_db.execute(f"SELECT * FROM {table} ORDER BY 1,2,3").fetchall(),
                )
            self.assertEqual(parallel_db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_actual_sql_preparation_overlaps_but_writer_remains_coordinator(self):
        _, plans = resolved_plans(2)
        barrier = threading.Barrier(2)
        original = population._prepare_population_statements
        seen = set()
        lock = threading.Lock()

        def prepare(task):
            with lock:
                seen.add(threading.get_ident())
            barrier.wait(timeout=5)
            return original(task)

        writer = TrackedWriter()
        stats = runtime.RuntimeStats()
        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1), mock.patch.object(
            population, "_prepare_population_statements", side_effect=prepare,
        ):
            population._insert_site_populations(writer, "TEST", plans, workers=2, runtime_stats=stats,
                                                preparation_backend="thread")
        self.assertEqual(len(seen), 2)
        self.assertNotIn(threading.get_ident(), seen)
        self.assertEqual(stats.counts["population_row_preparation.peak_active_workers"], 2)
        self.assertGreater(len(writer.statements), 10)

    def test_worker_failure_joins_peers_and_publishes_no_sql(self):
        _, plans = resolved_plans(2)
        barrier = threading.Barrier(2)
        peer_finished = threading.Event()
        original = population._prepare_population_statements

        def prepare(task):
            barrier.wait(timeout=5)
            if task[1][0].settlement_id == "S0000":
                raise RuntimeError("injected worker failure")
            result = original(task)
            peer_finished.set()
            return result

        writer = TrackedWriter()
        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1), mock.patch.object(
            population, "_prepare_population_statements", side_effect=prepare,
        ), self.assertRaisesRegex(RuntimeError, "injected worker failure"):
            population._insert_site_populations(writer, "TEST", plans, workers=2, preparation_backend="thread")
        self.assertTrue(peer_finished.is_set())
        self.assertEqual(writer.statements, [])

    def test_writer_failure_closes_scheduler_and_joins_admitted_peer(self):
        _, plans = resolved_plans(2)
        both_started = threading.Barrier(2)
        release_peer, peer_finished = threading.Event(), threading.Event()
        original = population._prepare_population_statements

        def prepare(task):
            both_started.wait(timeout=5)
            if task[1][0].settlement_id == "S0001":
                if not release_peer.wait(timeout=5):
                    raise AssertionError("coordinator never reached ordered write")
                result = original(task)
                peer_finished.set()
                return result
            return original(task)

        class FailingWriter(TrackedWriter):
            def execute(self, sql, parameters):
                release_peer.set()
                raise RuntimeError("injected coordinator write failure")

        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1), mock.patch.object(
            population, "_prepare_population_statements", side_effect=prepare,
        ), self.assertRaisesRegex(RuntimeError, "injected coordinator write failure"):
            population._insert_site_populations(FailingWriter(), "TEST", plans, workers=2,
                                                preparation_backend="thread")
        self.assertTrue(peer_finished.is_set())

    def test_mid_preparation_cancel_joins_workers_before_any_write(self):
        _, plans = resolved_plans(2)
        both_started = threading.Barrier(2)
        cancelled = threading.Event()
        finished = []
        original = population._prepare_population_statements

        def prepare(task):
            both_started.wait(timeout=5)
            result = original(task)
            cancelled.set()
            finished.append(task[1][0].settlement_id)
            return result

        writer = TrackedWriter()
        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1), mock.patch.object(
            population, "_prepare_population_statements", side_effect=prepare,
        ), self.assertRaises(runtime.GenerationCancelled):
            population._insert_site_populations(writer, "TEST", plans, workers=2, cancel_event=cancelled,
                                                preparation_backend="thread")
        self.assertEqual(sorted(finished), ["S0000", "S0001"])
        self.assertEqual(writer.statements, [])

    def test_invalid_controls_and_precancelled_build_fail_before_source_access(self):
        with mock.patch.object(population.schema, "_assert_checkpointed_source", side_effect=AssertionError("source opened")):
            for workers, budget in ((0, 256), (True, 256), (1, 15), (1, True)):
                with self.assertRaises(ValueError):
                    population.build(Path("absent-source"), Path("absent-output"), workers=workers, memory_budget_mb=budget)
            cancel = threading.Event()
            cancel.set()
            with self.assertRaises(runtime.GenerationCancelled):
                population.build(Path("absent-source"), Path("absent-output"), cancel_event=cancel)

    def test_cancelled_real_preparation_rolls_back_candidate_and_retains_release(self):
        # Cover every Haus so the unchanged realm guard passes. Planning is
        # intentionally serial in a build; process preparation is tested below.
        rows = sites(2) + sites(20, varied=True)
        for index, row in enumerate(rows):
            row["settlement_id"] = f"S{index:04d}"
        cancelled = threading.Event()
        original = population.rules.structural_human_population_band
        calls = []

        def prepare(site):
            result = original(site)
            calls.append(site["settlement_id"])
            cancelled.set()
            return result

        def seed_sidecar(source, candidate, **kwargs):
            with contextlib.closing(database_for(rows, profiles=False)) as fixture:
                with contextlib.closing(sqlite3.connect(candidate)) as destination:
                    fixture.backup(destination)
            return {"run_id": "TEST"}

        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]) as temporary:
            root = Path(temporary)
            source, output = root / "source.sqlite", root / "population.sqlite"
            source.write_bytes(b"synthetic source delegated to fixture adapter")
            output.write_bytes(b"prior validated population release")
            with mock.patch.object(population.schema, "create_sidecar", side_effect=seed_sidecar), mock.patch.object(
                population, "POPULATION_BATCH_SIZE", 1,
            ), mock.patch.object(population.rules, "structural_human_population_band", side_effect=prepare):
                with self.assertRaises(runtime.GenerationCancelled):
                    population._build_complete_database(
                        source, output, expected_active_sites=len(rows), workers=2,
                        memory_budget_mb=32, cancel_event=cancelled,
                    )
            self.assertEqual(output.read_bytes(), b"prior validated population release")
            self.assertEqual(sorted(calls), ["S0000"])
            self.assertEqual(list(root.glob(".population.sqlite.building.*")), [])

    def test_real_process_worker_failure_joins_children_and_writes_nothing(self):
        _, plans = resolved_plans(3)
        plans[0].split = None  # Actual worker rule invariant, not a parent mock.
        existing = {child.pid for child in multiprocessing.active_children()}
        writer = TrackedWriter()
        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1), self.assertRaisesRegex(
            AssertionError, "resolved site total has no human split",
        ):
            population._insert_site_populations(writer, "TEST", plans, workers=3, memory_budget_mb=256,
                                                preparation_backend="process")
        self.assertEqual(writer.statements, [])
        self.assertFalse({child.pid for child in multiprocessing.active_children()} - existing)

    def test_real_process_cancellation_joins_children_before_return(self):
        _, plans = resolved_plans(4)
        existing = {child.pid for child in multiprocessing.active_children()}

        class CancelWhenSpawned:
            def is_set(self):
                return bool({child.pid for child in multiprocessing.active_children()} - existing)

        writer = TrackedWriter()
        with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1), self.assertRaises(runtime.GenerationCancelled):
            population._insert_site_populations(
                writer, "TEST", plans, workers=3, memory_budget_mb=256, cancel_event=CancelWhenSpawned(),
                preparation_backend="process",
            )
        self.assertEqual(writer.statements, [])
        self.assertFalse({child.pid for child in multiprocessing.active_children()} - existing)

    def test_process_reservation_caps_workers_and_thin_budget_uses_serial(self):
        _, plans = resolved_plans(4)
        for budget, expected_limit in ((256, 3), (64, 1), (16, 1)):
            stats = runtime.RuntimeStats()
            with mock.patch.object(population, "POPULATION_BATCH_SIZE", 1):
                population._insert_site_populations(
                    TrackedWriter(), "TEST", plans, workers=8, memory_budget_mb=budget, runtime_stats=stats,
                    preparation_backend="process",
                )
            self.assertEqual(stats.counts["population_row_preparation.worker_limit"], expected_limit)

    def test_auto_small_workset_uses_exact_serial_without_process_startup(self):
        _, plans = resolved_plans(4)
        reference, actual = TrackedWriter(), TrackedWriter()
        expected = population._insert_site_populations_serial(reference, "TEST", plans)
        stats = runtime.RuntimeStats()
        result = population._insert_site_populations(actual, "TEST", plans, workers=8, runtime_stats=stats)
        self.assertEqual(expected, result)
        self.assertEqual(reference.statements, actual.statements)
        self.assertEqual(stats.counts["population_row_preparation.requested_workers"], 8)
        self.assertEqual(stats.counts["population_row_preparation.worker_limit"], 1)
        self.assertEqual(stats.counts["population_row_preparation.process_worker_limit"], 0)

    def test_auto_threshold_boundary_enables_actual_process_path(self):
        _, plans = resolved_plans(4)
        for count, limit in ((3, 1), (4, 2)):
            stats = runtime.RuntimeStats()
            with mock.patch.object(population, "POPULATION_PROCESS_MIN_SITES", 4), mock.patch.object(
                population, "POPULATION_BATCH_SIZE", 1,
            ):
                population._insert_site_populations(
                    TrackedWriter(), "TEST", plans[:count], workers=2, runtime_stats=stats,
                )
            self.assertEqual(stats.counts["population_row_preparation.worker_limit"], limit)
            self.assertEqual(stats.counts["population_row_preparation.process_worker_limit"], 0 if count == 3 else 2)

    def test_cli_forwards_parallel_controls(self):
        with mock.patch.object(population, "build", return_value={"status": "PASS"}) as build, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(population.main([
                "--source", "source.sqlite", "--output", "output.sqlite",
                "--workers", "4", "--memory-budget-mb", "96", "--no-reuse",
            ]), 0)
        self.assertEqual(build.call_args.kwargs["workers"], 4)
        self.assertEqual(build.call_args.kwargs["memory_budget_mb"], 96)
        self.assertFalse(build.call_args.kwargs["reuse"])


if __name__ == "__main__":
    unittest.main()
