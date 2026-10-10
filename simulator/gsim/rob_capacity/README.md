# ROB capacity experiment, revision 1

This is an isolated capacity experiment based on source `09f23d153577b792a5868ac5dd88bdcb7eead1cc`
(tree `a314ece03d7953b695ac8ca0e45c10337a7f1a1a`). It does not change the published recommendation.
The existing generic profiles and `fpga/next/performance.py` remain unchanged when new options are omitted.
`performance.py` still rejects capacity overrides. Use the generic official exporter explicitly.

## Profiles and legality

New official native and GSIM options are `--rob-entries 16|32|64` and `--physical-regs 48|64`.
Scala emitters use the corresponding `--name=value` form. Each option is optional and overrides only its named
dimension. All six combinations are supported, including legal but register-starved controls. The experiment
retains rename/commit/completion widths 2, LSU 4, 64-bit generation tags and the existing storage topology.
The existing default OooParams32/64 and historical Board/FPGA16/48 defaults remain distinct and unchanged.
LSU8 is a separate possible experiment; current official selectors continue rejecting it.

- `default`: exact existing recommended options, implicit ROB16/PRF 48/LSU 4; compatibility bridge
- `rob16-prf48`: explicit capacity control with the same hardware dimensions
- `rob16-prf64`: same-PRF control for later separating ROB and PRF effects
- `rob32-prf64`: window sensitivity profile, prepared without requiring an initial model build
- `rob64-prf64`: first treatment, a joint ROB/PRF capacity change relative to default

All retain DTLB 16, canonical virtual-store overlap, posted merging/coexistence/head offer, checked store
prefetch with MRU insertion, prefetch lifetime 1, and the complete frozen profile. Prechecked request flow and
translated response flow remain off. No dual-prefetch or storage/RAM layout changes are included.
ROB 64 is sufficient to *represent* the original next-line COPY load (minimum 41 entries); PRF 64 has 32 fresh
destinations above the 32 mappings (minimum 25 needed). Store issue ordering and same-line cache no-join can
still prevent admission. This is not evidence of demand overlap or throughput improvement.

## Exact profile and emitted geometry gates

`expected-inputs.json` binds the independent current full profile and every new expected JSON file.
The full report advances to `posted-board-full-profile-v2`, adding the two optional selector fields explicitly.
No field is omitted during comparisons. The complete 136-field core, cache, DDR, storage, protection and
derived geometry remain bound. The native export's existing 66-field performance preset and command stay exact.

After toolchain activation, these commands require the coordinator's Java slot:

```
mill -i IonSoC.test.testOnly ooo.BackendCapacityConfigSpec ooo.FpgaNextConfigSpec
mill -i IonSoC.test.runMain ooo.RobCapacityActualParamsMain FRESH_DIR board rob64-prf64
mill -i IonSoC.test.runMain ooo.RobCapacityActualParamsMain FRESH_DIR native rob64-prf64
python -B simulator/gsim/rob_capacity/check_profile.py rob64-prf64 FRESH_DIR --fir FRESH_DIR/BoardSocGsim.fir
```

Use `default` similarly for the exact OFF compatibility bridge. Normalize source-location annotations only,
then compare unchanged production module graphs with the frozen baseline before reusing any baseline model.
The actual-constructor audit checks six core, three cache, two DDR and cache TileLink parameter records.
`backend_capacity_geometry.py` independently checks actual ROB entry count, head/tail/count widths, free/ready
PRF arrays, full index-plus64-bit tag tokens, two 96-bit parity banks, two 64-bit PRF banks and owner-ready arrays.
The posted-owner census independently checks the expanded index width. A generated C++ header audit is also
required before runtime; constructor labels alone do not establish host ABI compatibility.

## Host impact and acceptance

The separate CPU preparation namespace owns passive instrumentation and independently modeled host oracles.
It must use the exact frozen production blobs from this experiment plus a test-only instrumentation commit.
ROB indices widen 4→5→6 bits, occupancy 5→6→7 bits, complete tokens 68→69→70 bits. Tag/generation remains 64 bits.
Both PRF 48 and64 use 6-bit indices; range checks still change. Packed tokens cannot be narrowed to uint64.
Audit canonical token bounds, ROI head modulo/masks, per-ROB observer arrays and scalar getters, PRF bounds,
one-hot masks, captured-token checks and actual generated dimensions. Never use `1ULL << 64`.

Before gain claims, directed qualification must cover load/store ownership, simultaneous completion and slot
reuse, wrap beyond every ROB index, physical destination reuse, recovery/kill, precise fault and stale/wrong
full-token controls. The original guest, kernel, instruction stream and stimulus stay byte-identical.
The guest is 6104 bytes, SHA256 `3af27dccda6acd677bb01fdad4d240ffee2f9af1c1fb4181a71c43ff2087a810`;
the kernel is 1472 bytes, SHA256 `f5a152ca2779ee567a9f864bc29d524bd91a935dab0323f21353ae9c9af0fec5`.

First runtime is the unchanged case 21 COPY with64/64/4 against the established16/48/4 control.
Observe actual rename occupancy/free PRF/rename stalls, admitted load count, cache-line diversity and full
token causal lineage. Only if the result warrants it, build16/64 to separate PRF from ROB effects, or32/64
to test the threshold. Consider LSU8 only if real owner occupancy justifies a separate qualification.
No exponential capacity matrix, full Linux run, local Vivado, push, synthesis, board or mapped timing claim.

Current baseline timing references: case 21 Sv39 COPY 431622 plus 5580 drain cycles; Bare case 19 COPY 365235
plus 5618 drain; warm case 0 COPY 16530. The 64 PTW walks cost 3209 cycles (about 0.74% of case 21);
these do not explain the COPY throughput. Old receipts are context, never new-capacity qualification.
