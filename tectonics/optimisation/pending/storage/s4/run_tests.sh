#!/bin/bash
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
export PYTHONHASHSEED=0 SO_PKG=$T/so/s4/pkg SO_HELPERS=$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/composed-r2/helpers
cd $T/so/s4 && $T/.r44-env/Scripts/python.exe -B -m unittest -v test_s4_retry 2>&1 | tail -20
