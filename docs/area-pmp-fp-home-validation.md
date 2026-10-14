# PMP, FP conversion and home lookup resource candidate

Baseline: commit `32a54afb0a2ca86cf953f275c63fe907811cb3ba`. Seven production leaves change: PhysicalMemoryProtection, InstructionRom, InstructionTranslationAdapter, FloatingPointExecute, new FloatingPointToIntegerShared, MixedCoherentLineHome and CoherentLineHome. Existing release documents and named entries are preserved. Their historical source pins do not qualify this new candidate.

The exact board configuration remains 177 core fields, 94 profile fields and the same ordered 73 options: two issue lanes, ROB16, PRF48, LSU4, full F/D and 64-bit ownership. No MSHR, credit, memory-port, PMP-entry or throughput-capability reduction is introduced.

- Four aligned frontend PMP word checkers share overlap/coverage comparisons for complete decoded four-byte regions. Generic/default behavior remains unchanged; 65-bit bounds and all physical address bits remain.
- Each S/D miscellaneous FP converter shares its 64-bit conversion with explicit 32-bit saturation/flags correction. Independent exact-rational vectors cover rounding, overflow, NaNs and flags; owner64 tests cover held/flush/high-tag identity.
- The existing home functional lookup port shares its selected-address match. Release/Acquire independent query ports remain. The factory enables it only for the tested overlap/internal-grant geometry. The constructor remains default OFF.

## Results

Fresh full production/test classes and one new 38-object CPU model passed COPY Bare/Sv39, NEMU hot/compressed, PMP short/word and held-causal positives, plus eight same-object negative controls. All positive stdout and event TSV bytes match the qualified service baseline. COPY inclusive cycles remain 179571 and 191618.

An additional same-model FP guest retired all 20 S/D W/WU boundary anchors and passed flags, 32-FPR, Sv39, FS/fcsr context and ECALL checks in 6151 cycles, byte-identical to the prior R6 model. Its deliberately wrong expected literal was reached and rejected. This is an oracle negative control, not a DUT source mutant.

Home exact-overlap paired component passed 64392 cycles with 71 output assertions and 52 matched retained state members. A legal dirty eviction and independent miss reached Release/Acquire coexistence for 52 cycles. The earlier overlap=false fixture had 53 observed members; those counts must not be mixed. Two wrong-selected-address source mutants were reached/rejected in that earlier fixture. Tag RAM contents are not claimed exhaustively compared by the retained-member observer.

The actual native board export has the same top-level/MAC/JTAG bytes and all actual configuration audits as R6. Four frontend instances use the new PMP checker; both FP32 converters are removed in favor of shared64 wrappers; the board home has the shared match enabled. Generated RTL structure is not measured LUT savings. Synthesis, placement, routing and board qualification remain unmeasured for this candidate.

CPU qualification SHA256: `54469bc38a7b20b9cd1e27e894b9d2595a08a873c82269414f4a0988da491c62`.
Count-correction addendum: `677564e32a322ff0b0b816a54bdd240631f874130542542016ab7129076fbd81`.
Native supplement: `02313aa24f1da201f89ab16bdbddecceb66d570c35bb90758ba4164f6e741996`.
Stronger held rollback/reuse coverage remains incomplete. Prior R6 system-reserve witness was not rerun for this batch.

## Focused reproduction

Use the repository's pinned Scala/Chisel/GSIM tools. Keep fresh output directories and exact existing service/guest snapshots; do not substitute an arbitrary current host service for the qualified one. The existing R6 CPU emitter can be used with unchanged exact73 arguments, but its historical Python source-qualification entries intentionally reject this new source. New model and class hashes must be recorded.

PMP and FP board guest commands are in `pmp-word-granularity.md` and `fp-word-boundary-test.md`. FP component runner instructions accompany its fixtures.

Home:

1. `mill -i IonSoC.test.runMain ooo.HomeLookupFactoryConfigMain` checks exact enable plus four excluded configurations.
2. `mill -i IonSoC.test.runMain ooo.HomeSharedLookupGsimMain OUT 0 4 1 1 1 4 2` emits the actual paired overlap fixture.
3. Run pinned GSIM on `OUT/HomeSharedLookupGsim.fir` into OUT.
4. `python3 simulator/gsim/home_shared_lookup.py --model OUT --output RUN --cxx clang++-19` binds retained observers from that actual FIR/header and runs the original byte-level protocol oracle plus the directed coexistence case.

For source-negative reproduction in an isolated source copy, replace only the `wayHit(tagLookupAddress, _, lookupTags)` argument with live upstream or DMA request address. The paired reference must remain untouched and must reject on output mismatch. Historical reached-negative evidence used the earlier overlap=false fixture; do not label a newly unexecuted variant as passed.

No generated RTL, model objects, toolchain or large raw logs belong in this source change.
