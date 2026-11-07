# Standard H/AIA platform GSIM entry

After integrating the H/AIA platform sources, run from the repository root:

```
GSIM_CXX=clang++-19 make gsim-hypervisor-platform-test
```

The target invokes `simulator/gsim/hypervisor_platform.py`. It uses `run.setup(False)`
(no automatic fetch), `IonSoC.test.runMain ooo.HypervisorPlatformGsimMain`, and the
pinned, repaired GSIM toolchain. Mill registers the four named H/AIA Scala fixtures using explicit `Task.Sources`
inputs alongside its normal test sources, without copying the fixtures. Archived
baseline files in the same directory remain outside the active source set. This also makes the AIA
retiring/translated-core fixtures discoverable; registration does not run them.

The focused entry checks the existing final platform interrupt/reset driver,
the three VS-origin PMA exception scenarios, and the driver's `--wrong-memory`
negative control. It requires both expected exit status and pass/failure markers.
ASan/UBSan remain enabled. Artifacts go to `build/gsim/hypervisor-platform`.
The PMA driver reuses the generated model without re-elaboration, but recompiles
its translation units because the common runner does not retain object files.

Prerequisites: Mill and the repository Scala/Chisel/HardFloat dependencies;
Clang 19 or newer; a qualified repaired GSIM epoch from `make gsim-setup` or
`VALENCE_GSIM_INIT_RECEIPT`, or the explicitly qualified reset-graph bundle
selected with `VALENCE_GSIM_RESET_GRAPH_BUNDLE`. See
[the strict bundle profile](gsim-reset-graph-bundle.md) for its fixed identities,
fail-closed selection and limits. The platform entry does not install or fetch missing GSIM tools; explicit
bundle verification is read-only. Mill still requires its normal Scala/JVM dependencies; use a complete
cache or the official configured Maven repository.
Use the repository GSIM README for toolchain preparation.

This is finite single-clock platform coverage, not dynamic CDC, external DDR,
DMA-drain, architectural H completeness, or the separate M-origin guest-fault
review. The recovery-only `platform_acceptance.py` and
`platform_final_acceptance.py` remain unchanged as historical provenance tools.

Entry-point unit tests (no hardware build or simulation):

```
python3 -m unittest discover -s simulator/gsim -p test_hypervisor_platform_entry.py
```
