# Banked indirect target storage experiment

## Source and contract

`IndirectTargetPredictor(p, bankedStorage = false)` retains the existing register-vector
implementation by default. The true branch maintains 16 logical full-64-bit-PC/full-64-bit-target
rows using one tag/target memory pair per retirement lane and a valid bit plus writer owner per row.
It accepts two ordered writes and two asynchronous lookups per cycle (II=1, no backpressure).
The youngest committed lane wins a same-index update. Both reads select the same writer's
tag/target pair; an unselected stale bank cannot hit. Reset clears logical validity, not payload.
Miss targets remain unspecified and are not compared. There is no added pipeline or bypass.

The opt-in is deliberately restricted to 16 entries, two rename/lookups, two commits, compressed
instructions and registered prediction training. Commit offered at cycle c is first query-visible
at c+2 in the existing old-Q GSIM observation convention. Other geometries/training modes remain
available through the unchanged register path but are not qualified for the banked path.

The banked implementation comes from the W14 source candidate, not a generated FIR/RTL graft.
Historical W13/W14 CPU measurements used ROB32/PRF64 and do not qualify today's production A1
ROB16/PRF48/LSU2. The historical W13 LLVM gain and W14 mapped resource improvement are motivation,
not new runtime, timing or area results for this source integration.

## Reproduce focused acceptance

Use the repository's pinned repaired GSIM setup and Clang19+:

```sh
GSIM_CXX=clang++-19 make gsim-banked-indirect-storage-test
```

The dedicated fixture runs the same independent logical table oracle against `reg` and `banked`:
40004 randomized ticks, 123 ISA/full64/latency/collision directed ticks, and 81 writer-bank directed
ticks. The banked extension now asserts reset for only one step with pending and newly offered
commits live, then checks that neither resurrects. It covers all16 rows under each writer, same-index
youngest priority, same-parity distinct rows, fixed dual queries during writer switches, full64
tag aliases/targets and six continuous updates. Four observation-only negative controls must exit1
at their expected diagnostics: branch, valid/hit, target bit63, and stale unselected-bank false hit.

Pure elaboration checks: `mill -i IonSoC.test.testOnly ooo.BankedIndirectStorageSpec`. They compare
omitted vs explicit-false predictor emission, verify unchanged port types, and reject unqualified
banked geometry/training and a core opt-in with no indirect table. Existing `PredictionTrainingGsimMain`
and its host are not modified.

## Usable core source entry, not production selection

`IntegerCore` and `IntegerCoreGsim` have a trailing default-false `bankedIndirectStorage` argument.
The existing positional CLI is preserved. Three explicit trailing flags select RVC, registered
training and storage; the banked flag does not silently select its prerequisites. Example CHIRRTL:

```sh
mill -i IonSoC.test.runMain ooo.IntegerCoreGsimMain build/gsim/core-banked-source \
  32 64 64 4 plain plain plain plain plain 16 plain 1 \
  compressed registered-prediction-training banked-indirect-storage
```

Omit only `banked-indirect-storage` for the matched register16 source export. Omit all three flags
and use the original arguments for existing behavior. There are no new `OooParams`, `FpgaNextConfig`
or `CommonA1CpuSpec` fields, production CPU/fabric selector changes, board packaging changes or
default changes. This experimental source entry does not mean the existing fullCPU host now supports
RVC or that a CPU has been executed. Current production selector integration, CPU runtime/IPC,
combined mapping, routed timing and board behavior remain pending.
