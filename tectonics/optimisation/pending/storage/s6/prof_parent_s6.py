"""S6 (H5) read-only pstats query over a W4 parent advance profile. Writes nothing."""
import os, pstats, sys
st = pstats.Stats(sys.argv[1])
S = st.stats
def short(k):
    return '%s:%d(%s)' % (os.path.basename(k[0]), k[1], k[2])
want = {('functionals_kernel_r5', 'reconstruct'), ('functionals_kernel_r5', '_prepare'),
        ('functionals_kernel_r5', '_face'), ('functionals_kernel_r5', '_prepared_bytes'),
        ('functionals_parallel_r1', 'reconstruct_faces'), ('functionals_parallel_r1', 'workers'),
        ('refinement_kernel_r1', 'intersect'), ('interval_assembly_kernel_r5', 'assess'),
        ('stage_lifetime_r3', 'compact_assessment'), ('decimal_sparse_core_r2', 'solve_rounded'),
        ('low_solver_kernel_r5', 'solve'), ('finish_kernel_r10', 'finish'),
        ('geometry_inventory_r3', 'prepare'), ('forward_kernel_r13', '_run'),
        ('forward_kernel_r13', '_next_rungs'), ('forward_kernel_r13', '_settle'),
        ('forward_kernel_r13', 'advance'), ('polygon_moment_inventory_r4', 'second_moment'),
        ('support_basis_resources_r1', 'support'), ('support_basis_resources_r2', 'basis'),
        ('functional_bounds_kernel_r2', 'functional_bounds'), ('stage_lifetime_r3', 'compact'),
        ('owned_value_r4', 'transfer')}
for k, (cc, nc, tt, ct, callers) in sorted(S.items(), key=lambda kv: -kv[1][3]):
    base = os.path.basename(k[0]).replace('private_heat_', '').replace('.py', '')
    if (base, k[2]) in want or ('rounded_system' in k[2]):
        print('%9.2f cum %8.2f self %8d calls  %s' % (ct, tt, nc, short(k)))
        for ck, v in sorted(callers.items(), key=lambda kv: -kv[1][3])[:4]:
            print('            <- %8.2f cum %6d calls  %s' % (v[3], v[1], short(ck)))
