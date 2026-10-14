# Independent width-supplement review

Reviewed 2026-10-14. **PASS for the corrected full-declared-width comparison in this bounded component run.** No hardware build or production edit was performed by this review. Earlier artifacts and reviews remain unchanged.

## Correction to the earlier claim

The original snapshot serialized 244 output fields, but narrowed 32 declared `UInt<65>` PMP region-bound fields to `uint64_t`. Its trace therefore omitted bit 64 of those fields. The earlier review's complete-output/full-width implication was too broad. The original shared-row oracle, narrow-output comparisons and execution witnesses are unaffected; full-width output comparison is established only by this supplement.

## Independent checks

- Parsed the actual top-module outputs in both original FIR models, separately from the supplement generator. Both have the same 244 named outputs and declared widths, matching the corrected contract and generated accessor signatures.
- Exactly 32 outputs exceed 64 bits: `io_pmpState_regionLow_0..15` and `io_pmpState_regionEnd_0..15`. Each is 65 bits, has an `unsigned _BitInt(128)` accessor, and emits two words. The total is 276 words.
- The high-word expression shifts the wide unsigned accessor by 64 **before** conversion to `uint64_t`; there is no shift by 64 on a 64-bit value. The serializer-negative XOR is also constructed in unsigned 128-bit precision. With its macro set to zero, it is an identity and does not modify DUT state.
- Field order and every original validity/head-valid gate are unchanged. All 32 wide fields are unmasked. The positive high words are zero throughout this workload; no padding bits above the declared width appear. The serializer conservatively emits the complete high word rather than masking its single declared bit.
- Independently verified 1,930 sequential cycles, exactly 276 snapshot words per cycle, and byte-identical complete OFF/ON traces. Selecting each field's low word reproduces the original 244-word trace exactly, with unchanged event-summary lines.
- Independently checked every receipt-bound object, output, binary, log, host, snapshot, contract and original-qualification hash. The host is unchanged, and saved original hardware objects are reused.

## Negative controls

The serializer-only negative changes exclusively `io_pmpState_regionEnd_0` bit 64, represented by word index 168. Independently confirmed that every summary line and every other snapshot word is unchanged, with exactly XOR 1 in that word in all 1,930 cycles. The comparator exits 1 for a full-width trace difference. This is serializer/comparator sensitivity evidence, not a hardware mutation or a positive DUT bit-64-equals-one PMP case.

The original real shared-byte-lane source mutation was rerun with this serializer and the unchanged host. It exits 1 with exactly `FAIL independent row payload mismatch`; its saved log does not show a DUT assertion or sanitizer failure. Thus the width correction preserves the earlier independent row-oracle negative.

## Evidence identity and conclusion

- Supplement receipt SHA-256: `94cc75d90b380b02d1e39178b2a34d35cd4ab2b66e2899b886a94300ac42a1e2`.
- Corrected snapshot SHA-256: `e0ac0b873be62f0ea715fe04904114258cf0d7ba193319c7e33379da247eabce`.
- Width contract SHA-256: `3c21a3fc527ac03015f0cce483eed342715284018782c941c6c4822da6613553`.
- OFF/ON trace SHA-256: `4624bed05032ed2c748adcaa22d81a49a83fa28775e1f2bbe3e5501fe5adc2d8`.
- Unchanged host SHA-256: `ba2b970d3c31f7b8402dc877e2e9c94c9491a57d4d4943682d133cf8367e8fb6`.

No blocking width/shift/gating defect remains for these artifacts. This correction does not expand the original workload's architectural, translation, frozen-proof, CPU or physical-performance coverage.
