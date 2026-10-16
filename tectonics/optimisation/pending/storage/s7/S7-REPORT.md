# S7: source-identity guard cost per stage (existing cProfile files, read-only)

Share = guard cumtime / profile total own time. De-nesting: only entries from callers outside the guard are counted; the cross-family union is an edge-propagation estimate. cProfile inflates Python code (`verify` 55-110 ms/call here, 27-32 ms unprofiled on 5 Oct).

|Stage|Profile|Guard (file)|Calls|Cum s|Share|ms/call|
|---|---|---|---|---|---|---|
|Admission|initial-metrics|reuse.py (composed-r1)|3,876|329.3|31.3%|85|
|Pressure admission|small5 admission|reuse.py (composed-r2)|54|2.96|2.6%|55|
|Pressure stage|small5 pressure-stage|reuse.py (composed-r2)|45|2.94|1.1%|65|
|Heat advance|heat-w4-p1|issuer r13|4|6.49|8.0%|1,623|
|Heat advance|heat-w4-p3|issuer r13|4|7.04|10.5%|1,760|
|Heat tail|heat-tail-w4|issuer r13|10|12.63|6.4%|1,263|
|||reuse.py (g13l1)|106|9.14|4.6%|86|
|||union, de-nested||19.57|9.9%||
|Heat workers (6 summed)|worker-*.prof|private_heat_* verify_sources|4,282|5.58|1.06%|1.3|
|Interfaces/deep surface (6)|all six|none, no reuse.py code runs|0|0|0%||

Heat profiles include worker waiting (p1 41%, p3 34%, tail 22%); against non-waiting time the shares are 13.8%, 16.3%, 12.6%. Context capture is separate: 7 contexts cost 3.2 s (pressure admission) and 3.3 s (heat tail).

## Findings
1. **Admission pays most.** One function, `cached_initial_component` (integration_dual_geometry.py:688), issues all 3,876 verifies: 4 per component (identity, pre-put verify, put's publication check, final verify) x 969 components. Cost follows call count at flat ms/call, not mesh size. 3,876 x 27-32 ms is about 105-124 s, 25-30% of the 415 s unprofiled stage wall (admission-timing-rc1), so the share is credible.
2. **composed-r2 is cheaper per call** (55-65 against 85-110 ms): source handles removed the file re-read (44% of r1's `verify_boundary`); 96% is now the `_verify_callable_inventory` walk. Pressure stages are 1-3%, dominated by exact-rational arithmetic.
3. **Heat issuer r13 is a different guard.** Only about 28% of its 1.3-1.8 s/call is source identity (ExecutionContext.verify, `_verify_implementation`); about 72% is snapshot, mesh and origin hashing, which grows with mesh size and survives any source-guard policy. In the tail, 64 of 106 reuse verifies come through the `regional_evolution3d._verify` owner chain.
4. Workers make no ExecutionContext calls, only 1.3 ms module hash checks (1.1%).
5. q02 profiles are the two small5 files. No q03 profile exists yet under T/hs.

Files: so/s7/scan_guard.py, guard-scan.txt.
