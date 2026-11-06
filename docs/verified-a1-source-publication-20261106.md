# Verified A1 source publication, 2026-11-06

This development branch publishes the reviewed default-off banked indirect predictor,
accepted bus/Home overlap source, PMP assertion-owner lifetime repair, and focused
reproduction tools. It does not promote an experimental mode to a production default.

## Base and scope

The parent is the already-public development commit
`a9986aac35c5263a854278ee1dc7330cd8cdd813` from
`dev/a1-inorder-opt-20261103`. Its OoO/Common A1 source matches the qualified source
baseline before this overlay. Using this public development base preserves required
interfaces without merging unrelated local query-work commits or changing `main`.
Unchanged files and older experiments belong to that existing public baseline; this
publication does not freshly qualify all of them.

The change adds or updates 51 reviewed source/test/tool/document files, plus this
publication note. The new in-progress board-export experiment, generated FIR/SV,
class files, binaries, waveforms and recovery archives are excluded.

`singleReadWait` remains a tested, default-off, unselected experimental control,
not an accepted CPU performance improvement. Both supported named fabric modes
force it off. Legacy board guards and strict production identity admission remain.

## Verification on this assembled source tree

- Fresh direct Scala 2.13.17/Chisel 7.3.0 compilation: all 351 main sources and
  53 selected test/helper sources, producing 1733 new classes. No prior project
  classes were reused; pinned external dependencies, including HardFloat, were reused.
- Nine focused pure Scala/elaboration suites passed all 32 tests: banked predictor,
  PMP lifetime, legacy DMA scheduling guards, fabric selection/read/Probe overlap,
  scheduling/completion and platform-boundary contracts.
- Separately emitted production A1 `read-baseline` and `probe-acquire` CHIRRTL.
  Each has 574 definitions. Against its previously qualified arm, every module body
  is identical after removing source-location annotations only. Identities match
  exactly. Across OFF/ON, only `MixedCoherentLineHome` changes; all 181 CPU-closure
  definitions are byte-identical.
- All 25 maintained export-tool tests passed with these fresh production inputs,
  including receipt, identity, port, layer and repaired-hash wiring controls.
- The reviewed 51-file overlay passed scope, dependency, whitespace and privacy
  checks. No production source was altered to accommodate publication.

The Mill wrapper was not run because this environment lacked its launcher. The
actual compile, tests and emissions used pinned direct stages. The earlier banked
component and PMP four-state results remain bound to their documented source
lineages; those hardware executions were not repeated for publication. There is
no new CPU runtime/IPC, full-board, MIG, physical CDC or timing qualification.

## Reproduction and evidence boundaries

Create a fresh compile receipt in your checkout using the documented
`fpga/common/scala_compile_receipt.py` workflow. Qualification-time receipts bind
an exact Git HEAD, absolute source root, source set and runtime classpath. They
are not portable to this new commit or another checkout merely because source
bytes match. Do not reuse or edit an old receipt to claim a fresh build.

Start with [the source status](a1-optimization-source-status.md),
[banked predictor commands](banked-indirect-storage.md),
[production export tooling](../simulator/qualification/a1_cdc_fabric/README.md),
and [PMP lifetime checks](../simulator/qualification/pmp_lifetime/README.md).
The `recovery-*` names in historical reports and the descriptive evidence JSON
refer to separately retained evidence, not files shipped by this source commit.
They are not runtime dependencies. This branch does not by itself reproduce the
complete archived CPU composition, guest, DDR service and assertion-adapter run.
Historical W14 ROB32/PRF64 results must not be relabeled as current A1 ROB16/PRF48/LSU2
performance.
