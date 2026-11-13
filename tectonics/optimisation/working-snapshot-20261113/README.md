# Working snapshot, 13 November 2026

Status: **WORKING NON-CANON**. This folder is a working snapshot of the optimisation package, published so the
later work is visible on the review branch. It is not the reviewed folded package. The work made after the fold
has not yet been reviewed, and nothing here claims scientific acceptance.

## Contents

- `atlas_tectonics/`: the public package and `_private`, copied byte for byte from the working arm, with the
  source-list files `_application_sources.json` and `_application_sources.sha256`.
- Left out: the compiled compression library and compiled Python files.
- `.gitattributes` keeps git from rewriting line endings in this folder.

## The one difference from the working arm

`atlas_tectonics/_private/run_fresh_interval.py` line 1238: a machine-specific path to the real-input
qualification folder is replaced by `Path(os.environ['ATLAS_REAL_INPUT_QUALIFICATION'])`. Because of that edit,
this file's row in `_application_sources.json` does not match its bytes here. Every other file is identical to
the arm.
