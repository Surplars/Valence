# Experimental held-ALU operand forwarding

`heldAluIssueForwarding` is default OFF. The explicit `--held-alu-issue-forwarding` option lets lane 0 advertise its stable old ordinary-ALU result while another producer occupies completion port 0. A dependent ALU can capture that value in its registered operand stage. The promise grants no completion, PRF write, retirement, memory permission or store authority.

The supported topology requires registered issue/execute and load forwarding, two-wide rename/completion/commit, parallel issue/ranks/recovery, ROB16, PRF48 and 64-bit tags. Move aliasing, load-completion bypass and multiply-word preview are excluded. Lane 1 retains its previous promise equation.

## Configuration and source identity

The sole publication parent is `bb85d08bda18121b1b848fbbbd004af50f2cc504`, tree `d1447e5e10179c9cc287c600d9aa36a2239128e2`. The 174-field core product appends held forwarding after `postedYoungerLoadSealDeferral`; the 91-field platform product appends it after `triSpeedRawClockHandoff` and `postedYoungerLoadSealDeferral`. Historical A172/A88 and exact64 entries use complete named, typed false projections, preserving field order and all original values.

The tested full CPU used A's ordered 68 options plus held forwarding. All four A options remained true; younger-load seal deferral and physical raw MAC handoff were false. Simultaneous young+B execution and physical MAC combinations are **unmeasured**. Expressible parameters and constructor checks do not qualify these combinations.

The compiled execution snapshot is preserved by SHA256 `8025373a74451e95f3192d35f3a067f41bf048086f8be051a451a30f53a3ab06`. Publication adds portable fixtures/documentation and a source-only identity/closure bridge; all four production leaves remain byte-identical to that tested snapshot.

The retained Young source entries accept current 174/91 products through an explicit named Boolean-false `heldAluIssueForwarding` projection to their published 173/90 shape. All four complete typed OFF/ON and MAC constructor documents match the independent Young baseline. Three stale entry arity guards were reproduced and repaired; 12 focused Scala checks, 12 Python bridge checks and two actual board constructions pass. This repair does not rerun Young CPU emission or inherit joint-on execution qualification.

## Observed results and limits

- One compile, 25 focused Scala tests, actual CPU/native full-product audits and one 36-unit sanitized ON model build passed. Retained A objects supplied OFF.
- COPY Bare 198642 and Sv39 191618 inclusive cycles match A. Original 105-field architecture/owner/service checks and three original negative controls passed. NEMU hot/compressed plus three controls and PMP short/word passed; all seven logs match A. No speedup is claimed.
- Eleven ordinary directed inputs passed OFF/ON, including precise faults, Sv39/PMP, M and system paths. They never stalled an occupied ALU stage, so these passes alone do not exercise the new promise.
- One causal input changes two register-source fields and one independently seeded RAM value. At cycle 779 the first load completes and dummy/P0 capture. At 780 the second load holds P0 token14:49 in lane0 while C1 token15:50 captures its value in lane1. At 781 P0 drains and C1 completes. Real M/load/store descendants use the registered result afterward. OFF has no held capture; both variants take 1558 cycles and retire 49 instructions.
- Five reached observation-corruption controls reject value, full owner, consume/refill, precise-trap and stale-response errors. Mixed-priority and killed-held-owner controls remain `NOT_REACHED` in the full CPU.

C1 acceptance or descendant grants while the same P0 remains stalled, held cancellation/reuse, and M/system-caused held captures remain **NOT_REACHED**. Full integration qualification remains false. The earlier isolated backend gate separately passed 72 cases per variant, five controls, II=1 dependent ALUs and two ALUs/cycle; its stronger held-chain/rollback witnesses do not become full-CPU coverage.

Of 286 native SystemVerilog leaves, 285 match A byte for byte; the only change removes lane0 `deq.ready` from the wake expression. Stage capacity, dequeue arbitration and enqueue/payload-enable dependence remain. State, ports and memory declarations are unchanged. No new STA, placed/routed timing, mapped area or board claim is made.

Portable regeneration, binding and bounded replay instructions are in `simulator/gsim/held_alu_forwarding/`. [Relative evidence](evidence/held-alu-forwarding-r1.json) separates reached and missing coverage. Model binaries and environment inventories are excluded.
