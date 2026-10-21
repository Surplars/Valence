# Preserve singleton masks in grouped one-hot operands

This stage repairs only `I1ExecuteDatapath.operand`'s final singleton group:
explicit `Mux(mask, payload, 0)` replaces singleton `Mux1H`; two-/three-element
groups and the final masked-OR reduction are unchanged. The bug affects arities
1 mod3, because Chisel's singleton Mux1H elides its selector. No mask relaxation,
new owner, queue, ready-path restructuring, clock target or timing exception.

The r5 real-core stop trace exposed the existing four-source recovery problem:
ECALL at0x80000028 correctly redirected fetch to0x80000100, but the architectural
restart register contained0x8000012c, the target OR stale sequential PC. The r5
optional stop path used an explicit Mux; this stage fixes the shared helper for
the default core as well. R5 default-byte equivalence was NOT proof of correctness.

## Complete callsite audit (r5 source line numbers)

- FiveStageCore.scala:517/518 rs1/rs2:5 sources.
- :520/522 assertion references:6; :527/530 ALU operands:6.
- :744 retirementRedirectPc:4, the concrete affected production caller.
- :746 combined redirectPc:6.
- I1CoherentLineCache.scala:513 parallel-way byte select:20 (4+8x2), eight bytes.
- :517 nonparallel-way byte select:5, eight bytes.
- I1ExecuteDatapath.scala:41 overrideOperand calls operand with generic N.
  Concrete callers Core:534/536 use5; FiveStageMain:149/150 tests use6.
- Existing FiveStageBackendControlMain:28/29 and FiveStageMain:148 tests use6,
  so they cannot detect singleton-tail leakage.

All sizes are elaboration-static. Other direct grouped Mux1H sites were checked:
FiveStageAddressTranslation:455 uses exact eight-row groups and two/four banks;
BankedOneHotRead:16 uses exact eight-row groups and explicitly handles a single
outer bank. Neither has the same ungated singleton-tail construction.

## Version and qualification boundary

Frozen performance source366a643 remains unchanged for diagnostic timing data.
This repair is a NEW functional source revision and needs its own final physical
and board signoff. Do not relabel earlier routed/diagnostic results as applying
to this revision. Runtime CMU backend and full drain ACK remain disconnected;
architectural stop is not cache/fabric/DDR clock-gating permission.

## Focused proof

`python simulator/gsim/i1_operand_singleton.py --tag FRESH_TAG` checks the real
helper against an independent C++ masked-OR oracle for64-bit arities1..10 and20,
including all-zero/poisoned tails, every selected/suppressed bit, exhaustive masks
through10 and randomized multi-hot masks. Override authority and disabled-register
cases are checked independently. A test-only exact legacy helper is required to
fail nine explicit witnesses while nonaffected arities remain passing.

`python simulator/gsim/i1_external_quiesce.py --default-core --tag FRESH_TAG`
checks the real default core with the stop option disabled: ECALL/MRET, pending
machine IRQ during iterative DIV drain, and delegated supervisor ECALL followed
by machine IRQ before any supervisor handler retirement, then MRET/SRET. The
interrupt must save the exact supervisor handler PC, not target OR stale nextPC.

The original enabled stop sweep is rerun separately without changing its oracle:
`python simulator/gsim/i1_external_quiesce.py --tag ANOTHER_FRESH_TAG`.
These remain short single-clock architectural traces, not full cached/CDC/board
functional qualification. Use the prepared environment and Clang19; no simulator
substitution or weakened production assertion.
