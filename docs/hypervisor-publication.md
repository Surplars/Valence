# Experimental H/AIA source publication

This branch assembles the previously validated H/AIA candidate on base
`a6448d9165f9c3c95456fab5895dd66d818c66aa`. It is a separate experimental
branch, not a merge into the current production branch. Unrelated working-tree
changes are not included.

## Contents and defaults

- The 86-file H/AIA platform candidate: two-stage guest translation, precise
  guest trap metadata, HS memory instructions, guest interrupt routing and
  the conservative shared-fabric platform integration.
- The standard repository GSIM entry and strict fixed reset-graph toolchain
  binding. The previously reported toolchain-binding blocker was repaired
  before this publication; the actual standard entry has passed.
- Test-only HS-width, HS-pattern/backpressure, VS-boundary and consecutive
  trap-metadata additions.

`hypervisorExperiment` and `experimentalHypervisor` remain false by default.
`misa.H` remains clear. Existing production selections are not switched to the
experimental H platform. Unsupported combinations remain rejected.

## Validation and reproduction

The standard fresh-build target is:

```
make gsim-hypervisor-platform-test
```

Use the pinned repaired toolchain described in
[the platform entry guide](hypervisor-platform-entry.md) and
[the strict bundle profile](gsim-reset-graph-bundle.md). The explicit bundle
profile validates the byte-identical qualified bundle and fixed Java launcher;
it does not accept arbitrary toolchain rebuilds or hosts. Missing or mismatched
proofs fail closed. The target compiles the active Scala sources, emits a GSIM
model, and runs the interrupt/reset and VS-origin PMA checks with ASan/UBSan.

The four supplemental runners are preserved evidence-reproduction tools, not
fresh-clone regression targets. HS-width/pattern tests require the preserved
platform recovery artifacts, including its native model object. VS-boundary
and trap-sequence tests require the preserved entry-binding recovery tree,
receipts and emitted models. Their documents specify the inputs and hashes:

- [HS widths](hypervisor-hs-widths.md): two SPVP contexts, 79 operations each,
  13 independently assembled instruction forms and a wrong-data control.
- [HS patterns](hypervisor-hs-patterns.md): 36 cases, 2,844 H-memory operations,
  data/byte-mask checking, backpressure and a wrong-data control.
- [VS boundaries](hypervisor-vs-boundaries.md): five cases across three service
  schedules, 12 traps/returns, 84 retired handler CSR reads and four negative
  controls.
- [Consecutive traps](hypervisor-trap-sequence.md): five different faults in
  one DUT per schedule, three schedules, 15 traps/returns, 105 retired handler
  CSR reads and three stale-metadata negative controls. There are no resets
  between faults or manual trap-metadata clears.

The supplemental driver and runner bytes are unchanged from their sealed
tested versions. Their prior hardware runs are retained evidence, not new
executions performed by this publication. Offline VS-boundary and consecutive
trap trace/provenance checks were repeated during publication preparation.

The source manifest records all 108 assembled paths, the patch identities and
the five sealed archive identities. Raw recovery archives, native executables,
objects, generated models and caches are not committed.

## Unfinished and unverified

This is finite, single-clock GSIM qualification. It is not full H compliance,
guest OS support, independent-clock CDC qualification, external DDR or DMA
drain verification, FPGA/PPA results, or general quiescence proof. Service
stalls are not independent clocks. No Yosys or retired simulator was used.

The proposed IRQ/fault-overlap cancellation test remains unimplemented and
unexecuted. Its incomplete runner draft is excluded entirely. The separate
M-origin guest-fault review remains unperformed. No result is claimed for
either item.

The build and test results for this publication are recorded in
`hypervisor-publication-validation.json`. They do not imply full regression
coverage or merge readiness.
