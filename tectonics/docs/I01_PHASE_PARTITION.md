# I01 composition-aware phase partition

WORKING NON-CANON. A bounded fixed-pressure/temperature prerequisite for a shared
melt law, not its thermal closure or a replacement for the accepted Katz control.

## Why this is needed

Extracting liquid also removes its particular ingredients. Reusing the original
rock composition afterwards can recreate liquid without a reaction or heat
account. Separately, Katz thermal-path accounts are not transferable absolute
phase enthalpies. Setting `L=T*entropy_of_fusion` in `h=cp*(T-Tref)+F*L` adds the
unrepresented term `F*entropy_of_fusion*dT`. Changing W08's melting temperature to
match each snapshot does not solve either problem.

The new calculation keeps individual solid/liquid component inventories. It
implements a candidate fixed-state equilibrium relationship, then debits exactly
the extracted liquid components. Existing kernels and evidence stay unchanged.

## Method and independent derivation

For supplied positive partition coefficients `K_i=c_s_i/c_l_i`, let `b_i` be
bulk component mass fractions and `f` liquid mass fraction. Component accounting
requires `b_i=(1-f)c_s_i+f*c_l_i`. Hence

```text
c_l_i = b_i / (f+(1-f)K_i)
c_s_i = K_i*c_l_i
R(f) = sum_i b_i*(1-K_i)/(f+(1-f)K_i)
R'(f) = -sum_i b_i*(1-K_i)^2/(f+(1-f)K_i)^2.
```

The derivative proves monotonicity. At a mixed root, both phase compositions
have equal sums; their bulk-weighted sum is one, so each sums to one.
`R(0)<=0` gives solid; `R(1)>=0` gives liquid. If all occupied components have
`K=1`, phase amount is indeterminate and refused. Zero mass has no defined phase
fraction. No composition is claimed for an absent phase.

Bracketed Newton steps use the analytic derivative; midpoint fallback guarantees
bracket contraction. Stopping bounds the root correction using the minimum
derivative magnitude across the bracket, not just a small residual. A 16-epsilon
summation allowance refuses ill-conditioned mixed fractions; this is a numerical
guard, not an interval-arithmetic proof. Composition closure is checked before return. No clipping
rescues invalid outputs. Inputs are immutable or copied, with at most 64
components/96 iterations and cancellation/deadline checks. No workers, disk cache
or growing iteration history are needed. Reuse a prepared partition only at its
declared P/T and coefficients; a changed physical state needs a new preparation.

Removing equilibrium liquid at unchanged P/T leaves the same coexisting phase
compositions but changes the bulk composition. Re-equilibration should recover
the remaining phase masses, not reset the original fraction. The analytical
binary has `K=(0.5,2)`, bulk `(0.4,0.6)` and `f=0.2`. Extracting half the liquid
from 10,000 kg leaves 9,000 kg with 1,000 kg liquid (`f=1/9`). Reusing `f=0.2`
would instead imply 1,800 kg.

## Remaining energy-bearing connection

This accepts sourced `K` at P/T, not a calibrated mantle model or a phase diagram
inferred from desired melt amounts. The fixture is analytical. No MagmaticPayload
or cooling result is produced. The shared provider still must supply compatible
`F,c_s,c_l,h_s,h_l`, a common energy datum, composition evolution and pressure-work
convention. Only then can extraction transfer `dm_i=dm*c_l_i`, `dH=dm*h_l` into
existing W08 emplacement without its incompatible common-Tm source inversion.
Temperature evolution, reaction kinetics, permeability, compaction and physical
extraction amount remain named closures. Prescribed splitting is not crust supply.

I01 selects and checks that common law; I05 implements its moving thermal/material
state; I06 connects ocean birth. This closes a composition prerequisite, not the
full melt/delivery connection.

## Research/software checked

- [Keller & Katz (2016), section 2.1.1, equations 4-7](https://eprints.gla.ac.uk/195948/1/195948.pdf):
  component/phase constraints. Derivative and bracket were independently derived;
  no published mantle calibration is adopted.
- [R_DMC equilibrium source](https://github.com/richard-katz/R_DMC/blob/master/src/R_DMC_Equilibrium.m):
  inspected, not copied or executed. With P/T and K already supplied, Atlas avoids
  nested solidus/liquidus solves and output clipping. No timing comparison with
  R_DMC is claimed.
- [ASPECT melt transport](https://aspect-documentation.readthedocs.io/en/latest/user/methods/melt-transport.html)
  distinguishes phase transport and reaction; not run or vendored.
- [pyMelt Katz source](https://pymelt.readthedocs.io/en/latest/_modules/pyMelt/lithologies/katz.html):
  fixed-lithology scope checked, not a substitute for phase-component inventories.

## Focused checks

Run from repository root:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_phase_partition.py -v
python -B tectonics/tools/check_i01_phase_partition.py --output NEW_PATH.json
```

The exclusive-create receipt binds the tool, tests, case and method, recording
actual runtime. Independent binary roots, phase/component identities, depletion,
permutation/scale invariance, endpoint/empty/ambiguous states and refusals are tested.
Three interleaved batches compare 200 Newton and bisection solves with identical
inputs/tolerance, recording raw times, median saving, iterations and mass parity.
This is a kernel comparison, not a world speedup or a calibrated mantle campaign.
