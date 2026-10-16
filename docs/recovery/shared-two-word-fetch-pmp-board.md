# Experimental shared two-word fetch PMP board wiring

This is a newly reconstructed, default-off candidate, not a restoration of lost
source bytes. It extends the separately checked component through ordinary
constructor arguments only. `OooParams` remains a 178-field product and
`FpgaNextConfig` a 95-field product. No frozen export, CLI profile, manifest or
physical recipe is changed.

## Constructor graph

`FpgaNextSocTop.sharedTwoWordFetchPmp` → `FpgaNextConfig.managedBoard` →
`BoardSocTop.sharedTwoWordFetchPmp` → `MachinePlatform.sharedTwoWordFetchPmp` →
`SynchronousFetch` and `InstructionTranslationAdapter`.

The separate standalone `FpgaIntegerCore` wrapper forwards the same default-off
argument to its `SynchronousFetch`. It is not an intermediate board constructor.

Native MAC, raw clock handoff, BSCAN chain 2 and RAM-loader choices remain those
of the explicit `ThreeProofRowNativeProfile` constructor used for this experiment.
The cache `splitCacheableBounds` candidate remains disabled. This experiment does
not inherit the older profile's qualification merely by using its configuration.

## Reproduction

Source `scripts/cloud/env.sh`, then invoke:

```
mill -i IonSoC.test.runMain ooo.SharedTwoWordFetchPmpBoardMain FRESH_DIRECTORY default
mill -i IonSoC.test.runMain ooo.SharedTwoWordFetchPmpBoardMain FRESH_DIRECTORY off
mill -i IonSoC.test.runMain ooo.SharedTwoWordFetchPmpBoardMain FRESH_DIRECTORY on
```

Use a different fresh directory for each invocation. The independent exporter
writes complete CHIRRTL and an `experiment.json` with actual constructor audits,
full core/profile values and field order, and raw/hardware CHIRRTL hashes. It
rejects any unexpected helper count (zero for default/off, two for on), changed
core values, cache range enabling, or missing native MAC/BSCAN/loader instances.

`simulator/gsim/shared_two_word_fetch_pmp_board_audit.py ROOT` compares archived
`before/default/off/on` exports and verifies the `after-source-sha256.json`
snapshot against the current source. `before-source-sha256.json` preserves the
prepatch source hashes. The comparison strips only source-location annotations;
all hardware IR remains in the comparison. Raw hashes are also retained.

## Limits

This is a constructor and complete-CHIRRTL check. It is not enabled-caller
behavioral qualification, CPU execution, board testing, synthesis, timing, or
physical qualification. No Verilog or physical recipe is emitted. The separate
component proof retains the baseline's 56-bit physical maximum-NAPOT contract;
an unbounded byte oracle would differ above that domain for all-ones raw54 NAPOT.
