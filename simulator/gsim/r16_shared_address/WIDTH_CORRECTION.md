# Full-width snapshot supplement

Status: PASS_FULL_WIDTH_SUPPLEMENT_AND_BIT64_NEGATIVE. This replaces only the earlier complete-public-output comparison claim; it does not change the original source, hardware models, host logic or shared-row state oracle.

The original bounded trace serialized 244 scalar outputs with uint64_t casts. Thirty-two PMP regionLow/regionEnd leaves are UInt65, so those traces compared only their low 64 bits. The original claim to compare every output bit was too broad. All original records remain unchanged; this note is the explicit correction.

The corrected serializer derives each output’s declared width from the actual emitted FIR and writes separate low/high 64-bit words before any narrowing. There are still 244 output fields, now 276 serialized words per cycle. The same original validity masks are retained. Fresh OFF/ON execution of the same frozen models and byte-identical host.cpp passes all 1,930 cycles; all full-width traces are identical. All original directed counters remain unchanged.

A serializer-only negative flips exactly bit64 of io_pmpState_regionEnd_0. The independent trace comparator exits 1. An additional checker verifies that every original data/control field and low word is identical, with only that high word XOR1 across the 1,930 cycles. No DUT state, input, source or hardware model is mutated by this negative. This proves the previously omitted bit is now observed.

The original real-source wrong-lane model is relinked against the corrected serializer and unchanged host. It still fails specifically in the independent row payload oracle with exit 1, not an assertion/sanitizer/trace-only mismatch.

The original source/class/model binding remains in r16-shared-address-gsim-r2 and r16-shared-address-lanes-negative-r1. receipt.json binds every reused object, new executable, source/header and actual command/exit/raw log. No Scala/FIR/GSIM regeneration or production edit was needed. The original bounded scope exclusions remain in force; mapped area, timing and CPU throughput are not measured.
