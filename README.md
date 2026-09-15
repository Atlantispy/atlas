# Atlas

**Atlas is a vibe-coded world generator. Its code is written with OpenAI's ChatGPT/Codex under human direction.** The project owner provides the worldbuilding requirements, decisions and feedback; AI assistants perform the coding and much of the technical testing. AI-generated explanations and passing tests are not substitutes for independent scientific validation.

Atlas is being developed for the fictional world of the Diadem. It is experimental, not production-ready or independently validated scientific software. Mountain and wider terrain realism remain unaccepted.

## Current code — 15 September 2026

This repository contains the approved public source snapshot, including embedded Diadem worldbuilding inputs and source references. It is a point-in-time export, not automatic synchronisation with the original local workspace.

This is a public source export of the current local development stack, including generator upgrades through R31 and the latest native-terrain R5 storage implementation. It is not the obsolete 1 September backup, a complete installed runtime or a generated Diadem world.

- [Generator upgrade R31](engineering/work/generator_upgrade_r31/): the latest scientific and integration successor, with earlier `generator_upgrade_r*` modules retained alongside it.
- [Runtime R12](engineering/work/generator_runtime_r12/): execution and reproducibility infrastructure.
- [Native terrain R5](engineering/work/native_terrain_r5/): the latest bounded native terrain storage successor. Its R1–R4 numerical and execution predecessors are retained alongside it; do not copy only the R5 directory.
- `engineering/work/terrain_model_*`, `diadem_tectonics_*`, `geology_r1/` and `topography_r1/`: supporting model components and predecessors.
- `shared_generator/engine/`: the retained shared generator source, contracts and tests.
- [Current state and limitations](docs/CURRENT_STATE.md): what the latest work establishes, what is missing, and where to start.

Private coordination records, personal usage tools, source-owner records, installed libraries, large inputs, saved checkpoints and generated world data are not published here. Local user-directory names and a private project identifier are replaced in public copies; therefore this export must not be described as byte-identical to historical execution bindings. The original local source is unchanged.

## Working with Atlas

Start by reading the current-state page and the module relevant to your change. Inspect dependencies before running anything. The original environment is Windows with Python and pinned numerical/geospatial packages. Native compressed history currently uses a pinned Windows Zstandard library; copying source into Linux does not establish runtime or checkpoint compatibility.

This initial public export is for code review and further development. No cloud execution, complete dependency installation, full-world run or physical acceptance is claimed. Do not disable source/hash checks, change acceptance tolerances or silently rebind old checkpoints to make a test pass. Runtime portability should be a separately labelled change with focused evidence.

Proposed improvements and pull requests are welcome. Identify AI assistance and provide focused, reproducible evidence. Maintainer review is required before accepting a change; code approval, scientific validation and fictional-world canon are separate decisions. This setup does not enable automatic merging or background simulation.

No project-wide licence has been selected by the owner in this setup. Existing third-party notices retain their own terms; public visibility is not a new project-wide licence grant.
