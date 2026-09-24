#!/usr/bin/env python3
"""Run only the remake's bounded mathematical tests and emit a fresh JSON record.

No installer, persistent cache, old checkpoint binding, simulation runner or
historical source import. JSON goes to stdout; test detail goes to stderr.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent

# Stage 8 is a focused composition of existing gates, not all tectonics physics.
# Keep exact selections reviewable; no implicit all-tests fallback on bad names.
W01_GATES = {
    'original_representation_and_thermal_limits': (
        'test_foundations.RotationTests.test_inverse_restores_batch',
        'test_foundations.RotationTests.test_composition_order_is_not_commutative',
        'test_foundations.RotationTests.test_distances_orthogonality_and_orientation',
        'test_w01_coordinates.SphericalTests.test_round_trip_grid',
        'test_w01_coordinates.SphericalTests.test_poles_exact_xy_and_near_pole_not_snapped',
        'test_w01_coordinates.SphericalTests.test_seam_continuity',
        'test_w01_coordinates.LocalFrameTests.test_finite_rotation_then_frame_invariants',
        'test_w01_coordinates.ConventionTests.test_length_and_angle_units',
        'test_w01_coordinates.ConventionTests.test_legacy_axial_rule_preserves_cross_product',
        'test_w01_coordinates.TimeTests.test_axes_round_trip_and_strided_input',
        'test_w01_coordinates.TimeTests.test_explicit_epoch_bridge',
        'test_w01_geometry.SphericalGeometryTests.test_octant_independent_area_perimeter',
        'test_w01_geometry.SphericalGeometryTests.test_dateline_crossing_not_world_spanning',
        'test_w01_boundaries.SharedPlanarTests.test_rectangle_shared_once',
        'test_w01_boundaries.SharedPlanarTests.test_reversal_swaps_regions_plates_and_direction',
        'test_w01_boundaries.SharedPlanarTests.test_shared_trace_correct_and_reversed',
        'test_w01_boundaries.SharedSphericalTests.test_spherical_reversal',
        'test_w01_spherical_atlas.AtlasQueries.test_every_seam_reports_true_owners',
        'test_foundations.ThermalTests.test_initial_and_surface_conditions',
        'test_foundations.ThermalTests.test_equal_temperature_limit',
    ),
    'initial_inventory_and_unknown_meaning': (
        'test_w01_initial_sampling.RegionalInitialSampling.test_mixed_cells_and_refinement_conserve_reference_inventory',
        'test_w01_initial_sampling.RegionalInitialSampling.test_unknown_porosity_and_temperature_remain_explicit',
        'test_w01_initial_sampling.RegionalInitialSampling.test_used_unknown_density_refuses_only_mass_not_volume',
        'test_w01_initial_sampling.RegionalInitialSampling.test_temperature_validity_checks_interior_not_mean',
    ),
    'supported_workflow_geometry_history_recovery': (
        'test_w01_workflow', 'test_w01_workflow_geometry',
    ),
    'combined_stage8': ('test_w01_acceptance',),
    'shared_execution_invalidation': ('test_execution_reuse.IdentityTests',),
    'acceptance_status_contract': ('test_w01_acceptance_profile',),
}


W04_GATES = {
    'physical_reference_loads': ('test_w04_column_loads',),
    'uniform_periodic_discrete_support': ('test_foundations.FlexureTests',),
    'uniform_finite_continuum_support': ('test_w04_finite_region',),
    'fixed_variable_rigidity_continuum_support': ('test_w04_variable_flexure',),
    'combined_stationary_workflow': ('test_w04_acceptance',),
    'verified_load_reuse': ('test_w04_load_reuse',),
    'source_geometry_ownership_and_validity_guards': (
        'test_w04_workflow.W04WorkflowTests.test_surface_requires_correct_cells_complete_water_and_explicit_shapes',
        'test_w04_workflow.W04WorkflowTests.test_policy_ownership_periodic_scope_and_old_water_bath_stiffness_refuse',
        'test_w04_workflow.W04WorkflowTests.test_finite_capacity_and_linear_validity_limits_refuse',
        'test_w04_workflow.W04WorkflowTests.test_changed_source_datum_and_loaded_callable_refuse',
        'test_w04_regional_workflow.W04RegionalWorkflowTests.test_unknown_surroundings_gate_displacement_and_derivative_validity',
        'test_w04_variable_workflow.W04VariableWorkflowTests.test_source_profile_shape_frame_and_uncertainty_refuse',
    ),
    'acceptance_status_contract': ('test_w04_acceptance_profile',),
}


W05_GATES = {
    'independent_reference_controls': ('test_w05_reference', 'test_w05_support_reference'),
    'characteristic_kinematics_and_accounts': (
        'test_w05_extension.W05ExtensionTests.test_characteristic_means_and_signed_multicohort_accounts',
        'test_w05_extension.W05ExtensionTests.test_continuation_references_initial_family_and_complete_export',
        'test_w05_extension.W05ExtensionTests.test_stationary_footwall_zero_motion_and_immutable_views',
        'test_w05_extension.W05ExtensionTests.test_tiny_front_cell_integrals_against_quadrature',
        'test_w05_extension.W05ExtensionTests.test_invalid_definition_clock_and_underflow_guards',
        'test_w05_extension.W05ExtensionTests.test_foreign_closed_cancel_and_budget_guards_release',
        'test_w05_extension.W05ExtensionTests.test_separate_existing_ale_uniform_dilation',
    ),
    'single_owner_load_support_and_envelopes': ('test_w05_support',),
    'combined_frozen_case': ('test_w05_acceptance',),
    'atomic_recovery_and_verified_reuse': ('test_w05_workflow',),
    'acceptance_status_contract': ('test_w05_acceptance_profile',),
}


W06_GATES = {
    'combined_three_route_recovery_and_reuse': ('test_w06_workflow',),
    'shared_execution_invalidation': ('test_execution_reuse.IdentityTests',),
    'acceptance_status_contract': ('test_w06_acceptance_profile',),
}


def w06_acceptance_record(passed):
    """Workflow acceptance; unchanged component evidence is retained separately."""
    return {
        'status': 'PASS_SUPPORTED_W06_WORKFLOW' if passed else 'FAIL_OR_INCOMPLETE',
        'supported_workflow_accepted': bool(passed),
        'routes': ['constant_ocean', 'history_ocean', 'inherited_margin'],
        'scope': 'Source-bound prescribed planar W06 outputs, finite accounts, single-owner local support and atomic exact recovery.',
        'numerical_methods': {
            'ocean_motion': 'Exact affine birth strips and first-exit histories; full age distributions.',
            'thermal': 'Retained constant-property finite-plate and inherited-profile conduction.',
            'recovery': 'Lossless ArrayStore payloads; cheap geometry/account reconstruction without completed thermal solves.',
        },
        'component_evidence': 'Retain unchanged W06 Steps 2-4 source-bound component evidence; this profile exercises the new workflow joins, not another grid/partition sweep.',
        'resource_scope': 'Explicit bounded work admission, not an operating-system RSS limit.',
        'regional_coupling': 'Three separately bound physical routes; no implicit spatial join or shared-reservoir transfer between them.',
        'whole_terrain_accepted': False, 'field_validated': False, 'production_ready': False,
        'empirical_challenge': 'PENDING_INDEPENDENT_AGE_DEPTH_HEAT_FLOW_DATA',
        'other_stage_acceptance': 'UNCHANGED_NOT_DECIDED_BY_W06',
        'R4_4_status': 'HELD_INCOMPLETE',
    }


def w05_acceptance_record(passed):
    """Numerical acceptance of the stated mechanism, not empirical terrain proof."""
    return {
        'status': 'PASS_SUPPORTED_DRY_LISTRIC_1D_W05' if passed else 'FAIL_OR_INCOMPLETE',
        'supported_workflow_accepted': bool(passed),
        'scope': 'Prescribed dry isothermal constant-density listric extension on a fixed planar 1D grid with continuous uniform elastic support.',
        'numerical_methods': {
            'motion': 'Exact characteristic cell integrals of the declared exponential initial family and constant cohort fractions.',
            'support': 'Cell-load Green convolution on a continuing uniform plate, with true mean outputs and explicit exterior uncertainty.',
            'independent_reference': 'Separate adaptive quadrature, full crop centres/faces, and equivalently averaged extrema.',
        },
        'assumptions': [
            'Fault geometry and constant horizontal velocity are prescribed, not solved from stress.',
            'Only hanging-wall material moves; the unflexed footwall stays fixed.',
            'Dry restoring coefficient is mantle density times gravity; support is total change from the initial reference.',
            'Rigidity and densities are fixed; no feedback from supported geometry into transported inventory.',
            'Finite region and output crop are distinct; omitted loads and continuous displacement/slope/strain envelopes are bounded.',
            'Quadrature uncertainties are numerical estimates, not rigorous continuum-error certificates.',
        ],
        'whole_terrain_accepted': False,
        'field_validated': False,
        'production_ready': False,
        'empirical_challenge': 'PENDING_SEPARATE_ANALOGUE_AND_SUPPORT_DATA',
        'other_stage_acceptance': 'UNCHANGED_NOT_DECIDED_BY_W05',
        'R4_4_status': 'HELD_INCOMPLETE',
    }


def w01_acceptance_record(technical_passed):
    """Passing representation/engineering must not close missing science gates."""
    return {
        'technical_status': 'PASS_SUPPORTED_WORKFLOW' if technical_passed else 'FAIL_OR_INCOMPLETE',
        'whole_W01_status': 'INCOMPLETE',
        'whole_W01_complete': False,
        'S3C_scientific_status': 'REOPENED',
        'R4_4_status': 'HELD_INCOMPLETE',
        'described_initialisation_status': 'PASS_SUPPORTED_WORKFLOW' if technical_passed else 'FAIL_OR_INCOMPLETE',
        'future_formation_work': 'R5-R9 include unimplemented process/spherical-generation capabilities; not failed tests of the described-state route.',
        'remaining_scientific_gates': [
            'Generated plate realism remains unaccepted: bounded scale-matched shape comparisons are available, not full morphology/dynamics validation.',
            'PB2002 source checking already covered all 5819 motion rows; consistency of prescribed Euler motion is not independent validation of generated dynamics.',
            'R4.4 mature convection evidence remains incomplete and held; no long campaign is implied or required for the supported described-state route.',
        ],
        'unsupported_not_passed': [
            'Unrestricted spherical material dynamics and unresolved interface/event laws.',
            'Evolved temperature, heat, compaction or relative pore-fluid motion in the S7 workflow.',
            'Whole-world scale/cost, geological realism and production readiness.',
        ],
    }


def w04_acceptance_record(technical_passed):
    """Accept the specified supported workflow, not untested terrain or stages."""
    return {
        'status': 'PASS_SUPPORTED_STATIONARY_PLANAR_1D_W04' if technical_passed else 'FAIL_OR_INCOMPLETE',
        'supported_workflow_accepted': bool(technical_passed),
        'scope': 'Source-bound stationary planar 1D W01-W03 load-to-support projection, total from one fixed reference.',
        'numerical_methods': {
            'uniform_periodic': 'Centred finite-difference biharmonic operator on periodic cells; discrete, not continuous spectral k^4.',
            'uniform_finite': 'Continuous uniform-rigidity equation with exact cell-constant load integration and explicit continuing or physical ends.',
            'variable_rigidity': 'Conservative continuum weak form with source-aligned Hermite finite elements and declared mesh-change estimates.',
        },
        'assumptions': [
            'Positive rigidity D is fixed in time, either uniform or prescribed spatially; restoring coefficient K is positive and constant.',
            'Thermal support has one owner; closed water placement, background replacement and any additional pressure remain explicit.',
            'Continuing-plate exterior loads/materials are explicit: variable-D support requires exact declared exterior loads and refuses nonzero omitted-load uncertainty.',
            'Uniform finite support retains its declared exterior uncertainty bounds; mesh-change estimates are not rigorous continuum-error bounds.',
            'Periodic discrete and finite/variable continuum methods need not agree at finite resolution.',
        ],
        'whole_terrain_accepted': False,
        'field_validated': False,
        'production_ready': False,
        'other_stage_acceptance': 'UNCHANGED_NOT_DECIDED_BY_W04',
        'R4_4_status': 'HELD_INCOMPLETE',
        'unsupported_not_passed': [
            'Moving, spherical or general 2D support; time-varying rigidity or restoring density.',
            'Yielding, viscoelasticity or feedback into material, thermal or shoreline evolution.',
            'Whole-terrain realism, field calibration, whole-world scale and other-stage acceptance.',
        ],
    }


def _acceptance_suite(gates, label):
    sys.path.insert(0, str(ROOT / 'tests'))
    suite = unittest.TestSuite()
    selected = {}
    seen = set()
    def leaves(group):
        for item in group:
            if isinstance(item, unittest.TestSuite):
                yield from leaves(item)
            else:
                yield item
    for gate, names in gates.items():
        group = unittest.defaultTestLoader.loadTestsFromNames(names)
        tests = list(leaves(group))
        ids = [t.id() for t in tests]
        if not ids or seen.intersection(ids) or len(ids) != len(set(ids)):
            raise ValueError('empty or duplicated ' + label + ' acceptance selection')
        seen.update(ids)
        selected[gate] = ids
        suite.addTests(tests)
    return suite, selected


def w01_suite():
    return _acceptance_suite(W01_GATES, 'W01')


def w04_suite():
    return _acceptance_suite(W04_GATES, 'W04')


def w05_suite():
    return _acceptance_suite(W05_GATES, 'W05')


def w06_suite():
    return _acceptance_suite(W06_GATES, 'W06')


def _checks_passed(result, source_unchanged):
    return (result.wasSuccessful() and result.testsRun > 0 and not result.skipped
            and source_unchanged)


def source_inventory(root: Path) -> dict[str, str]:
    """Hashes are observations of local source bytes, not approval or signatures."""
    # -B prevents writes, not reads. Refuse pre-existing local bytecode rather
    # than authenticate source while executing a different timestamp cache.
    for folder in ('src', 'tests'):
        if next((root / folder).rglob('*.pyc'), None) is not None:
            raise ValueError('local bytecode exists; use a clean source-only checkout')
    paths = [root / 'verify.py', root / 'pyproject.toml']
    paths += sorted((root / 'cases').glob('*.json'))
    if not (root / 'cases/foundations.json').is_file():
        raise ValueError('foundation case is missing')
    paths += sorted((root / 'src').rglob('*.py'))
    paths += sorted((root / 'tests').rglob('*.py'))
    paths += sorted((root / 'tools').glob('*.py'))
    if not (root / 'src/atlas_tectonics/__init__.py').is_file():
        raise ValueError('tectonics source package is missing')
    if not list((root / 'tests').glob('test_*.py')):
        raise ValueError('no mathematical tests found')
    result = {}
    for path in paths:
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError('verification input must not be a symbolic link')
        if not path.is_file():
            raise ValueError('verification input missing: ' + path.name)
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> int:
    if sys.argv[1:] == ['--w10']:
        sys.path.insert(0,str(ROOT/'tools'))
        from check_w10 import main as w10_main
        return w10_main([])
    if sys.argv[1:] not in ([], ['--core'], ['--native'], ['--acceptance'], ['--w01'], ['--w04'], ['--w05'], ['--w06']):
        print('Usage: python -I -B tectonics/verify.py [--core | --native | --acceptance | --w01 | --w04 | --w05 | --w06 | --w10]', file=sys.stderr)
        return 2
    w01 = sys.argv[1:] == ['--w01']
    w04 = sys.argv[1:] == ['--w04']
    w05 = sys.argv[1:] == ['--w05']
    w06 = sys.argv[1:] == ['--w06']
    acceptance = sys.argv[1:] == ['--acceptance']
    if acceptance:
        import importlib.util
        if importlib.util.find_spec('psutil') is None:
            raise ImportError('Resource acceptance needs the explicit psutil acceptance extra; no automatic installation')
    core_only = sys.argv[1:] == ['--core']
    native = not (core_only or w06)
    if not core_only:
        import importlib.util
        if any(importlib.util.find_spec(p) is None for p in ('scipy', 'numba', 'blosc2', 'threadpoolctl', 'shapely')):
            raise ImportError('Full verification needs scipy, numba and the storage extra; --core explicitly tests reference foundations only')
    if native:
        import importlib.util
        if importlib.util.find_spec('numba') is None:
            raise ImportError('Default transport verification requires numba==0.65.1')
    sys.dont_write_bytecode = True
    before = source_inventory(ROOT)
    sys.path.insert(0, str(ROOT / 'src'))
    import numpy as np
    import atlas_tectonics
    from atlas_tectonics import reuse
    if Path(atlas_tectonics.__file__).resolve() != ROOT / 'src/atlas_tectonics/__init__.py':
        raise ValueError('imported tectonics package is not this checkout')
    selection = None
    if w01:
        suite, selection = w01_suite()
    elif w04:
        suite, selection = w04_suite()
    elif w05:
        suite, selection = w05_suite()
    elif w06:
        suite, selection = w06_suite()
    else:
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_foundations.py' if core_only else 'test_*.py')
    if native and not (w01 or w04 or w05 or w06):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='check_native_transport.py'))
    started = time.perf_counter()
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    elapsed = time.perf_counter()-started
    resource_record = None
    if acceptance and result.wasSuccessful() and not result.skipped:
        import subprocess
        # A separate process keeps telemetry out of unit-test timings. All child
        # profiles have their own finite watchdog and immutable source inputs.
        proc = subprocess.run([sys.executable, '-I', '-B',
            str(ROOT / 'tests/check_combined_acceptance.py')],
            capture_output=True, text=True, timeout=300)
        if proc.returncode:
            print(proc.stderr, file=sys.stderr)
            resource_record = {'status': 'FAIL_RESOURCE_ACCEPTANCE', 'returncode': proc.returncode}
        else:
            resource_record = json.loads(proc.stdout)
    after = source_inventory(ROOT)
    unchanged = before == after
    passed = (_checks_passed(result, unchanged)
              and (not acceptance or (resource_record is not None and
                   resource_record.get('status') == 'PASS_BOUNDED_CURRENT_PLATFORM')))
    print(json.dumps({
        'schema': 'atlas.tectonics.foundation-verification.v26' if w06 else 'atlas.tectonics.foundation-verification.v25' if w05 else 'atlas.tectonics.foundation-verification.v24' if w04 else 'atlas.tectonics.foundation-verification.v23',
        'profile': 'w06-supported-workflow' if w06 else 'w05-supported-acceptance' if w05 else 'w04-supported-acceptance' if w04 else 'w01-supported-acceptance' if w01 else 'combined-resource-acceptance' if acceptance else 'core' if core_only else ('full-native-transport' if native else 'full-memory-storage'),
        'status': ('PASS_SUPPORTED_W06_WORKFLOW' if w06 else 'PASS_SUPPORTED_DRY_LISTRIC_1D_W05' if w05 else 'PASS_SUPPORTED_STATIONARY_PLANAR_1D_W04' if w04 else 'PASS_MATHEMATICAL_TESTS_ONLY') if passed else 'FAIL_OR_INCOMPLETE',
        'test_elapsed_seconds': elapsed,
        'w01_acceptance': w01_acceptance_record(passed) if w01 else None,
        'w04_acceptance': w04_acceptance_record(passed) if w04 else None,
        'w05_acceptance': w05_acceptance_record(passed) if w05 else None,
        'w06_acceptance': w06_acceptance_record(passed) if w06 else None,
        'w05_case_metrics': getattr(sys.modules.get('test_w05_acceptance'), 'CASE_METRICS', None) if w05 else None,
        'selected_tests_by_gate': selection,
        'tests_run': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors),
        'failure_details': [{'test': t.id(), 'traceback': detail} for t, detail in result.failures],
        'error_details': [{'test': t.id(), 'traceback': detail} for t, detail in result.errors],
        'skip_details': [{'test': t.id(), 'reason': reason} for t, reason in result.skipped],
        'skips': len(result.skipped), 'source_unchanged_during_tests': unchanged,
        'source_sha256_before': before, 'source_sha256_after': after,
        'execution_runtime': ({'threadpoolctl': __import__('threadpoolctl').__version__,
                               'process_start_method': 'spawn'} if native else None),
        'w02_runtime': (__import__('atlas_tectonics.remapping', fromlist=['w02_native_build_info']).w02_native_build_info() if native else None),
        'material_runtime': (__import__('atlas_tectonics.materials', fromlist=['material_native_build_info']).material_native_build_info() if native else None),
        'regional_runtime': (__import__('atlas_tectonics.regional', fromlist=['regional_native_build_info']).regional_native_build_info() if native else None),
        'native_runtime': (__import__('atlas_tectonics.transport', fromlist=['native_build_info']).native_build_info() if native else None),
        'R4_status': 'IN_PROGRESS',
        'R4_complete': False,
        'convection_r4_4_scope': 'published-case definitions, independent endpoint diagnostics, immutable trajectory runner, per-run and refinement gates, combined recovery tests; passing tests does not establish mature published convection or complete R4.4 acceptance',
        'thermochemical_r4_2_scope': 'retained constant-property rectangular heat/binary composition evolution and local same-source restart; explicit R4.3 mode adds nonlinear mechanics, not full convection benchmark acceptance',
        'stokes_r4_1_scope': 'retained constant-viscosity closed free-slip 2D steady mechanics; variable-stress assembly is the separate R4.3 component, not an unmodified vector Laplacian',
        'variable_stokes_r4_3_scope': 'closed 2D rectangular symmetric-stress variable-viscosity mechanics, updated-law Picard yielding and explicit two-stage Tosi thermochemical coupling; no evolving damage or full R4.4 convection benchmark acceptance',
        'physical_closure_r3_scope': 'local Tosi/BF2023 constitutive laws, explicit material-point memory and 1D fixed-length operator; R3 alone does not establish coupled localisation or R4 completion',
        'spherical_atlas_scope': 'closed static conforming patch geometry; no spherical material evolution',
        'earth_material_scope': 'W01 4B sourced reference data and declared mixtures; no hot/high-pressure laws or W03 evolution',
        'geological_description_scope': 'W01 stage 4 plus R2 pre-partition state and bounded stage-5 point/prism/shell-sector initial sampling; no W03 evolution',
        'precursor_r2_scaling_scope': 'conservative spherical candidate index and bounded independent sampling batches; auto indexed points, measured serial cell default',
        'precursor_r2_scope': 'plate-independent immutable state; conservative initial material volumes; no physical plate-formation/rheology/global-mesh acceptance',
        'planetary_generation_scope': 'W01 3C unweighted nearest-site initial geometry; not validated plate history',
        'geometry_runtime': __import__('atlas_tectonics.geometry', fromlist=['geometry_runtime']).geometry_runtime(),
        'runtime': {'python': platform.python_version(), 'numpy': np.__version__,
                    'interpreter_launcher_is_symlink': Path(sys.executable).is_symlink(),
                    'interpreter_target_sha256': reuse._loaded_binary(reuse._interpreter_binary()),
                    'platform': platform.system(), 'machine': platform.machine(),
                    'thread_environment': {k: os.environ.get(k) for k in
                        ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}},
        'resource_acceptance': resource_record,
        'plate_reference_r1_scope': 'parser/metric/policy checks; complete external PB2002 verification requires explicit reference command',
        'scope': 'synthetic analytical, numerical and resource checks; platform scope is explicit',
        'physical_validation': False, 'production_ready': False,
        'historical_checkpoint_compatibility': False,
        'note': 'Local evidence record, not a cryptographic signature or performance benchmark.'
    }, indent=2, allow_nan=False))
    return 0 if passed else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ImportError, OSError, ValueError) as exc:
        print(json.dumps({'status':'BLOCKED','error':str(exc),
              'action':'Use the declared existing development dependencies; no auto-install occurs.'}), file=sys.stderr)
        raise SystemExit(2)
