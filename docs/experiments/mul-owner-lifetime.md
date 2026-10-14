# Bounded multiplier slot identity (default OFF)

PipelinedMultiply(p, boundedSlotIdentity = true) removes only internal arithmetic tag transport and its two row-write/preview equality predicates. Full64 result-reservation, completion, preview and owner tokens remain. Capacity8, acceptance II1, arithmetic latency, output holding and cancellation behavior are unchanged. No board profile enables the constructor option in this package.

## Exact lifetime contract

Number accepting edge E0. Direct operands write MULW at E1 and full MUL at E5. Registered operands write at E2/E6. The API's first observable completion latency counts2/6 or3/7 cycles respectively; these are the same schedules, not an added cycle. valid stages always advance. Only accepted starts increment tail, one per edge; cancel/pop never rewind it. Thus a row cannot be allocated again before E8. The latest possible write E6 is strictly earlier. MULW never writes at the later full-width site because it requires !word. Reset clears tail, live, arithmeticFire and every valid together.

The constructor requires capacity > lastArithmeticWriteOffset. That bound depends on the current fixed, nonstalling pipeline. Do not introduce independently gated clocks, stalls, tail rewinds, extra delayed writes or smaller capacity without a new proof. This does not justify narrowing any asynchronous ROB/LSU token.

## Focused test

Run from repository root with the pinned GSIM installation and Clang19+:

    GSIM_CXX=clang++-19 python3 simulator/gsim/mul_owner_lifetime.py --tag component-r1

This independent arithmetic/scheduling oracle checks both operand-stage settings and both constructor settings. Each case runs3000 accepted operations for each active-reset offset1/2/4/6/8, all five multiply classes, high-bit full owners, preview validity/data/token, retained owners, full capacity, blocked completion, cancel before/at/after result write, and dense E8 canceled-row reuse. It does not import DUT expected arithmetic. The runner also checks an observation-mismatch negative; this is not a source-mutant claim.

For the separately qualified source negative, apply simulator/gsim/fixtures/mul_owner_lifetime/wrong-slot.patch only to an isolated copy, then run the bounded registered fixture. The source mutant shifts every saved arithmetic slot by one and must fail `pipeline response validity/latency` (an earlier preview/arithmetic oracle failure is also evidence of corruption, but not the original qualified diagnostic). Do not apply it to the production working tree. The archived qualification ran the actual mutated Scala source, not just a corrupted expected observation.

## Current evidence and limits

Component evidence: reference/bounded logs byte-identical for both operand modes; five reset placements each; registered per reset201 exact-E8 reuses, cancellation452/66/806 before/at/after write; direct200 exact-E8 reuses. True wrong-slot source mutation is rejected. Registered native tag-transport declarations384 bits→0, direct320→0; all eight full64 row tokens remain. These are native structural counts, not mapped FF/LUT savings. Whole CPU, board, routed timing and physical resource changes are unverified. New public fixture uses a distinct name so existing pipelined-mul tests remain unchanged.

A later board candidate can opt in at IntegerBackend's PipelinedMultiply instance with a separately reviewed R16/PRF48/tag64/two-wide/registered-operands predicate. This package leaves that integration OFF.
