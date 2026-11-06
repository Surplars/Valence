# DMA Probe / older Acquire overlap candidate

This is a default-off experiment. It permits DMA-only capture while an older CPU Acquire is live, then parks same-set maintenance and allows different-set maintenance to progress. It does not reopen fresh scalar/A admission during maintenance. Queued CPU fills retain ownership; Probe ownership clears on the exact response handshake. Dirty writeback failure remains fatal.

All six reviewed Scala files remain byte-identical to their tested source snapshot. A separately qualified current-source entry is described below; it does not inherit the retained CPU runtime qualification or change defaults. The [descriptive manifest](data/dma-probe-acquire-overlap-candidate.json) is **not executable configuration**: no runner consumes it and it does not select a hardware profile.

## Selection and limits

`dmaProbeAcquireOverlap` is default false in `CommonMachineFabric`, `CoherentLineHomeModule.build`, `MixedCoherentLineHome`, and the focused `CommonMachineFabricFlatGsim` wrapper. The flag passes through that chain. Both factory and implementation require read overlap, two coherent clients, two DMA tags, two Acquires, two writebacks, Home1024×4/256 sets, mixed read/write, independent line reads and whole-line Grant.

These guards constrain Home geometry, not the entire W16 CPU/system profile. The focused emitter obtains `CommonFabricHomeCompletion.config`, which calls `CommonFabricDmaSchedule.config("dual")`, a copy of live `FpgaNextConfig.Selected`. It selects DMA line transfers/two tags, write collection flow, independent line reads and threshold rewrite, without single-read-wait. Other inherited settings can change when Selected changes. The reviewed DDR limits are four outstanding requests and two outstanding writes; the manifest is an evidence summary, not a complete resolved configuration lock.

The emitter fixes maintenance completion flow and read overlap ON, and accepts Probe overlap `off|on`. Thus the paired OFF baseline already has read overlap ON. Completion-flow OFF has a pure elaboration check only, not the measured runtime/performance qualification described here.

## Source and class entry points

Existing sources are under `src/test/scala/platform`:

- `CommonFabricDmaAcquireSpec` and `CommonFabricDmaProbeAcquireSpec`: five tests total, pure Scala/elaboration, not hardware execution. The latter covers retained/new assertions, nine invalid parameter profiles and completion-flow OFF elaboration.
- `CommonFabricDmaProbeAcquireGsimMain`: fabric-only CHIRRTL emitter; arguments are a fresh output directory and `off|on`. An existing output directory is rejected.

Standard Mill entry points, **not rerun or validated in this environment**:

```sh
mill -i IonSoC.test.testOnly platform.CommonFabricDmaAcquireSpec platform.CommonFabricDmaProbeAcquireSpec
mill -i IonSoC.test.runMain platform.CommonFabricDmaProbeAcquireGsimMain build/gsim/probe-acquire-off off
mill -i IonSoC.test.runMain platform.CommonFabricDmaProbeAcquireGsimMain build/gsim/probe-acquire-on on
```

Validate the installed CLI before use and choose unused output directories. These commands do not reproduce full-CPU acceptance. CHIRRTL emission alone is not firtool validation, a GSIM model build or a behavioral test.

The actual archived source run used pinned Scala 2.13.17, Chisel/plugin 7.3.0 and ScalaTest 3.2.19 directly because Mill was unavailable. Its compile class was `scala.tools.nsc.Main`; tests used `org.scalatest.tools.Runner -R <fresh-classes> -o -s platform.CommonFabricDmaAcquireSpec -s platform.CommonFabricDmaProbeAcquireSpec`; emissions launched `platform.CommonFabricDmaProbeAcquireGsimMain` from those fresh classes. The full exact argv/classpath, source/tool hashes, class-load logs and exit receipts are in the external source evidence bundle's BUILD_PLAN and commands records. Do not copy machine-specific classpaths into this repository or rerun a frozen bundle in place.

There is currently **no portable repository-owned runner for the full archived CPU composition**. The similarly named `CommonA1DmaProbeMain` is a different fixture and does not enable this flag. The legacy FPGA-next/full-board GSIM wrappers still do not expose this candidate. Do not bypass their scheduling guards to claim reproduction. The separate current common-platform entry below is the supported explicit source experiment.

## Retained W16 runtime evidence scope

The source phase emitted 85 fabric modules, with only Home changed between matched OFF/ON; storage, ports and instances were preserved. The real-cache fixture uses 18 exact bodies. CPU measurements use retained W16, 277 module bodies, with only Home replaced and 276 bodies unchanged. This is not a fresh elaboration of all current CPU sources.

Separate frozen phases establish directed protocol behavior; actual retained CPU/DMA measurements under matched service laws; real overlap-time FENCE.I waiting, private flush/shared drain; and precise failed-load trap/MRET/retry. Real FENCE can wait at the head during an older CPU request but cannot launch cache flush while that request still owes a response. Flush overlapping independent DMA ownership is a distinct witness.

The SMC/concurrent-DMA follow-on has two matched native PASS runs and an independent frozen review PASS. Actual old instruction-cache tag/data for the same physical address remain resident until real invalidation, followed by new fetch/install and retirement of the modified instruction word. OFF → ON total cycles are 3776 → 3759, DMA 1861 → 1844, and instruction wait remains 313. This is one hart, one same-line 8-byte patch, with active optional instruction prefetch disabled. Code writeback occurs within the DMA job but has no Home DMA-line owner at its exact accepted beat; do not claim that stronger simultaneous witness.

The terminal EBREAK is not the zero-debt instant: an already accepted demand fetch continues draining afterward. Zero debt applies at the final quiet/GPR-inspection endpoint. Read the separately frozen errata with the original report. The manifest binds the producer freeze, RESULT, errata freeze and independent final review by SHA256.

The historical IRQ/MMU feasibility assessment remains read-only. A later separate frozen retained-W16 IRQ phase now has two matched native PASS cases, six producer offline checker negatives and nine independent oracle negatives per side. A real M-mode timerTick/mtimecmp sequence reaches a precise IRQ, handler and MRET continuation with DMA ownership spanning that interval. Final timer level remains1 with MTIE0: masked pending, not cleared/rearmed. All31 fills are direct, so this adds no queued-fill IRQ coverage. These are retained-model results, not current-source runtime qualification. The manifest records the final phase and review hashes.

MMU tests remain uncovered and are not drop-in: page tables, translation, PMP, SFENCE and architectural checking require a separately scoped task. Existing interfaces and hardware presence do not establish coverage. The original assessment is `recovery-1106-probe-acquire-irq-vm-assessment/REPORT.md`; the later IRQ phase is `recovery-1106-probe-acquire-irq-final/REPORT.md`.

Measured improvements are workload-specific. Preserve counterexamples: mixed instruction wait +60/+66 cycles, delayed mixed accepted-fetch max/p99 +2/+3, and a FENCE case +25 total/+83 DMA cycles. Finite accepted-request completion is not universal starvation freedom. The CPU trace's inactive coherent client0 must not be presented as full two-client CPU coverage; two-client protocol coverage comes from the component fixture.

The existing logical map reports +81 fabric LUT, -141 MUXF and unchanged FF/CARRY/RAM. Directory/client local D depth each increases by one; flattened paths crossing RAM/CARRY are unknown. None of this establishes physical Fmax, routed timing, DDR throughput, MIG or board acceptance.

## Current static A1 entry: source/elaboration qualification only

The real `platform.CommonMachinePlatformMain` now accepts an optional `--experimental-fabric-dma=read-baseline|probe-acquire` selector. Absence retains the old configuration path and all overlap defaults false. It is limited to generic static production A1, memory-copy DMA present, with no separate CPU experiment/spec, runtime or SoC-file selector. Existing unsupported profile/legacy/internal-RAM guards are unchanged.

The selection resolves the fabric once for `CommonMachinePlatform`, which passes the three flags through the real `CommonMachineFabric` into Home. CPU-private configuration is resolved independently. Existing CPU identity files include shared-fabric configuration, so their digest is a combined identity: explicit experiments update that shared fabric and flags and recompute the digest. A changed combined digest is not evidence that the CPU changed. The absent-selection identity construction remains unchanged.

Actual tested production-main arguments, after a fresh bound compilation:

```text
<fresh-output> a1 --programmable --emit-chirrtl-only --compile-receipt=<bound-receipt.json> --experimental-fabric-dma=read-baseline
<separate-fresh-output> a1 --programmable --emit-chirrtl-only --compile-receipt=<same-bound-receipt.json> --experimental-fabric-dma=probe-acquire
```

The explicit experiment requires a complete source/classpath-bound compile receipt, not a legacy exit-only receipt. Programmable CHIRRTL export requires no guest/COE/MIG input and executes no guest. The actual run used the pinned direct Scala compiler and fresh classes, not a newly asserted Mill run.

One fresh compile of 347 main sources and nine selected test/helper sources passed. Three focused suites passed nine tests. Both real production-main emits passed, with 571 non-external modules (including the public top) and three BUFGCE extmodules each. Only MixedCoherentLineHome's location-normalized body differs; all module ports, storage declarations and instances match, including Home's 57 storage declarations. CPU-private effective fields are identical. This pair has ROB16/PRF48/two LSU owners, two-wide issue and 32KiB two-way instruction/data caches; it is not relabeled retained W16.

Eight malformed/unsupported real CLI invocations are rejected before emission. The emitted metadata records the actual resolved fabric, its derived settings, selection and source-only scope. Evidence is separately retained in `recovery-1106-probe-acquire-current-entry`; historical before-source aliases preserve old bytes rather than rewriting older pins.

This source-entry phase establishes real common-platform constructor/configuration and CHIRRTL qualification only. In that phase, no firtool lowering, combinational-loop verification, native current-CPU execution, SV board-shell port check, vendor-IP proof, map, physical timing or board test was run. `soc_top_common_ddr.sv` integration is not signed off by checking CHIRRTL ports. Historical default emitted-byte equivalence is not established: no valid task-entry default emit was available, and a third post-change None emit would not prove it. Default preservation is source-reviewed and pure-resolver-tested.

## Current matching CPU/cache/fabric: synchronous runtime qualification

A separate current-runtime phase now passes eight native runs: four matched OFF/ON conditions using the same guest and external service law. The 266-module model contains 181 CPU-closure modules, 84 fabric-closure modules and one explicit shared-clock top. Its 265 child bodies match the current production-entry FIR byte for byte. This is current generic two-LSU A1 evidence, not inherited retained-W16 qualification.

The full production RawModule and its independent clock/CDC/FIFO/reset/BUFGCE path did not run: GSIM does not support that complete clock construction. The matching component model uses direct synchronous connections instead. Its cycles cannot be converted to production 100:250 MHz board time, and it provides no full-platform or board signoff.

Independent architectural/next-PC, all 32 GPR, full-memory/guards, protocol-owner, dirty-data and FENCE.I private/shared drain checks pass. The eight runs close 640 A/Grant/E/install generations and 128 DMA lifetimes. ON has 22 early dirty Probes with an older Acquire live, versus 0 OFF. Ten saved-trace corruptions are rejected by the producer checker; these are diagnostic sensitivity checks, not DUT fault injections. Independent review confirms the runtime results and rejects 20 independently constructed offline negatives. At each terminal trap edge, two accepted debts remain: one fetch and one scalar reservation-clear request. Zero debt is established only during the later 36 quiet samples and 32-GPR inspection, not at the trap edge.

Matched OFF → ON outcomes (DMA cycles / whole-run cycles):

- Data-conflict normal: 1407 → 1174 / 6912 → 6679.
- Data-conflict delayed: 2753 → 2135 / 10623 → 10005.
- Instruction-conflict delayed: 1313 → 1274 / 9745 → 9773. Instruction wait rises 28 cycles despite shorter DMA time. All 107 accepted fetches finish; maximum 49 and p99 48 remain unchanged.
- Poll normal: 679 → 679 / 2968 → 2968.

Whole-run cost is not a CPU-work-only interval. The regression is retained explicitly; this is not a universal speedup or fairness guarantee. This current phase adds no IRQ, MMU, self-modifying-code or fault-recovery qualification. Retained-W16 results for those separately tested cases remain in their own lineage. Producer and independent final evidence references are recorded in the descriptive manifest; defaults remain false.

## Production clock boundary: component runtime qualification

A separate component test executes the exact 107 production `CommonCpuClockBoundary` dependency definitions extracted from the same frozen current-entry FIR, without vendor modules. The installed official Yosys native simulator runs CPU 100 MHz / fabric 250 MHz clocks at fabric phase offsets 0/1/3 ns. Each of the 26 lanes delivers 128 tokens, then 32 after a drained common reset, per phase: 12,480 delivered tokens across the three phases. Capacity 17, full backpressure, held payloads, wraparound and empty indications pass.

All 52 original assertion instances execute natively and pass independent pre-edge checks. Every assertion has at least 92 enabled samples per phase; active predicate/enable/trigger values contain no unknowns. Only verification cells receive the independently structure-checked official lowering. The 3,075 functional cells, 26 RAMs and 423 asynchronous-reset flip-flop cells remain unchanged. Five negatives have distinct meanings: two copied-monitor cases trigger native assertion failures, one copied DUT with a wrong fabric clock is rejected by the oracle, and two observer perturbations are rejected. They are not collectively described as hardware fault injection.

A separate blocked common-cold-reset case accepts 17 old tokens on each lane, then aborts all 442 when both test endpoints reset together. Reset asserts at 697 ns and releases at 797 ns. A 240 ns empty window contains no old valid/replay; the new epoch delivers 32 per lane, or 832 tokens. The 442 aborted tokens are not completions, and this component result does not establish rollback of external writes already accepted by DDR.

The original three-phase review and the later cold-reset review are separate frozen evidence. Historical per-run model hashes were not recorded or reconstructed; the final freeze binds the retained model and actual traces, with command/mtime evidence supporting model reuse. This does not qualify the integrated A1+fabric+CDC production platform or its end-to-end 100:250 throughput. One-sided reset, stopped clocks, metastability/MTBF, physical STA, BUFGCE/vendor clocks and board behavior remain untested. The earlier matching synchronous runtime retains its own cycle/model scope; this boundary result does not convert those cycle counts into board time or power measurements. Defaults remain false.

## Exact production CDC + fabric: synthetic-endpoint combination

A separate matched OFF/ON test combines 107 production CDC definitions, 84 fabric definitions and two startup definitions, with an explicit wiring wrapper and synthetic CPU protocol endpoints. Actual independent 100 MHz CPU-side / 250 MHz fabric clocks run at one 1 ns phase offset. This is not real A1 execution or a CPU FENCE.I test.

Independent replay verifies the matched DDR service, Acquire/Grant/E, dirty Probe, Release, MMIO, fetch and private-ready/shared-drain owners. ON advances the final DDR B response and fabric drained-epoch publication by 224 ns; CPU reception of that epoch advances by 230 ns. Second Acquire acceptance and Grant timing are unchanged. These are synthetic transaction/maintenance timings, not application throughput or IPC.

A drained common reset preserves committed DDR data and supports the subsequent sequence. This does not establish rollback of external accepted writes or an in-flight-reset protocol. Eleven saved-observation corruptions are rejected; they are checker-sensitivity negatives, not hardware fault injections. Assertion coverage is partial: 189/297 OFF and 190/301 ON sites are reached, not every retained site. Real A1 workload qualification and board/physical qualification are separate gates; the narrow real-CPU result below does not promote the synthetic combination into an application-throughput result.

## Real A1 + CDC + fabric: narrow strict short-guest result

The original native strict-assertion attempt remains FAILED at 415 ns: six idle PMP predicates were unknown while enabled. Its later assertion-diagnostic trace is historical evidence, not a retroactive strict pass. A separate owner-lifetime repair changes only verification behavior in three Scala files. All 752 predicates and trigger clocks remain unchanged; only six enables now require the real owner lifetime. Independent structural/owner proofs and 20 directed cases retain valid-owner predicates and rejection of active illegal/unknown cases. No zero-initialization or generic unknown-value filter is used.

After that repair, the real A1+CDC+fabric short guest passes the 10 µs native strict run at 100:250 MHz, phase 1 ns. It retires 344 instructions with x7=18, timer observations 90/91 and x12=102. FENCE private status at 6285 ns, returned epoch at 6385 ns and retirement at 6415 ns match the earlier diagnostic. Of 752 assertion sites, 273 are reached with 184,664 enabled known-true samples; 479 remain unreached. Independent comparison finds all 752 original predicate waves unchanged and all 612 public ports equal across 6,120,612 comparisons.

Final observed fetch/scalar/exercised transport debts are zero, but the terminal JAL remains active; global CPU quiescence is not claimed. Four independent saved-observation mutations are rejected, not injected into the DUT. This guest has no DMA/dirty-Probe, MMU, FPU, IRQ or fault-recovery workload. The repaired owners are idle in this guest; their active behavior is covered only by the separate directed controls. The result is neither a concurrent-DMA throughput measurement nor broad full-platform, vendor-clock, physical or board qualification. Prior failures and diagnostics remain frozen separately; all configuration defaults remain unchanged.

## Real A1 + CDC + fabric: dirty-source DMA and FENCE.I

A separate matched OFF/ON pair passes native strict execution and independent review with real two-LSU A1: 181 production CPU, 107 CDC, 84 fabric and two startup definitions, plus an explicit wrapper. Each run covers 20 µs with independently edged 100 MHz CPU / 250 MHz fabric clocks at phase 1 ns. OFF substitutes the exact earlier production OFF Home body into the repaired current ON composition; it is not a fresh OFF production-main emission. Only Home differs between the pair; the assertion-lifetime repair is unchanged.

The same 65-word guest dirties a 64-byte source line, programs DMA, issues a different-set Acquire, executes real FENCE.I with destination DDR B ownership deliberately retained, then checks DMA status and all eight destination words. No synthetic CPU endpoint or internal CPU state injection drives it. The matched test service loads a 2,200-cycle final-B delay counter, yielding 2,201 fabric cycles from accepted last W to B. This is imposed validation backpressure, not production DDR latency.

OFF → ON final destination B is 12575 → 12355 ns, fabric drained epoch 12603 → 12383 ns, CPU epoch reception 12645 → 12425 ns, FENCE.I retirement 12705 → 12485 ns and guest pass marker 14225 → 14005 ns. Each advances 220 ns, or 22 CPU cycles, under this fixed service law. ON destination AW at 3511 ns overlaps the other fabric Acquire owner (3343–3683 ns); OFF AW at 3727 ns follows its E. Dirty Probe and other Acquire/Grant/E timings are unchanged. CPU/fabric private status remains 8875/8895 ns with the destination B owner still live. This is a bounded workload result, not general throughput/IPC or the earlier synthetic endpoint's 224 ns result.

Independent replay checks the same 62 nonterminal retirements and exact final 128 written bytes, including the dirty source and copied destination. Each side has eight dirty Probe beats, four AR/32 R and two AW/16 W/two B. At 20 µs, accepted protocol/DDR debts and all 26 accounted CDC lanes are empty; only 11 lanes carry traffic. Clean cache lines and the terminal spin remain, so global CPU quiescence is not claimed. Assertion coverage is partial: OFF reaches 421/748 sites with 404,504 enabled known-true samples; ON reaches 422/752 with 404,459. Sixteen independent saved-observation negatives on OFF are rejected; they are checker-sensitivity tests, not DUT fault injection.

Original copied common-base metadata incorrectly described the pair's configs as identical. Preserved effective-config bindings clarify that CPU-private configuration is identical, while the intended fabric Probe flag, selector and derived combined identity differ. Original records remain unchanged; the clarification changes no model or stimulus.

This one current-A1 workload at one phase remains separate from retained W16, synchronous A1, synthetic-endpoint and narrow short-guest evidence. It adds no current multiclock MMU, FPU, IRQ, error-recovery or reset-while-DDR-owner coverage, and no physical CDC, metastability/MTBF, RDC, vendor-clock, MIG or board-timing qualification. Defaults remain false. Final producer, independent-review and source/native binding references are recorded in the descriptive manifest.

## Real A1 + CDC + fabric: DMA read-error clear/restart

A matched strict OFF/ON pair now covers one recoverable DMA source-read error with actual CPU execution at independent 100:250 MHz, phase 1 ns. Each run is 7 µs, reusing the same production definitions and assertion-lifetime repair. The 86-word guest dirties 64 bytes, programs DMA and issues another real CPU load. The external service returns one SLVERR on beat 3 of the second accepted source read, after successful dirty Probe writeback; it completes all eight beats. The failed line response contains zero data, and the failed descriptor issues no destination write.

The CPU observes status 6, clears to 0, restarts and observes 1 then 2. The same DMA tag is reused only as a new drained descriptor generation. All eight destination loads and guest comparisons pass. Ordinary `fence iorw,iorw` retires at 4325 ns, and both modes reach the pass marker at 5615 ns. This instruction orders CPU memory after observed DMA success; it does not trigger FENCE.I, a shared maintenance epoch or instruction-cache visibility testing. Neither mode traps. All 82 useful retirements and final 128 written bytes match; all measured OFF/ON timing differences are zero, so this check makes no speedup claim.

All 26 CDC lanes are accounted for, with nine active. Each mode has five AR/40 R, two AW/16 W/two B, and a 1385 ns post-pass interval with zero accepted debt or native owner activity. Native assertion coverage is partial: 420/748 sites and 129281 enabled known-true samples OFF; 421/752 and 129321 ON. Ten reached saved-observation corruptions are rejected separately from the actual legal RRESP error injection. Final B follows accepted WLAST by one fabric cycle under this idealized service, not measured DDR timing.

This is single-line descriptor error/restart coverage, not multi-entry error drain, CPU trap/MRET recovery, dirty-writeback failure recovery, IRQ/MMU/FPU, reset-abort, sustained throughput or board qualification. Legal external R/B responses are asserted ready by this bridge's reserved-owner contract; READY is not forced to manufacture stalls. The service still allows only one read and one write/B owner. Defaults remain false. Final producer and independent-review references are in the descriptive manifest.

## Real A1 + CDC + fabric: dual-owner DDR service and four cold loads

A separate matched native strict OFF/ON pair executes real two-LSU A1 for 9 µs each at independent 100:250 MHz, phase 1 ns, with the same 122-word/488-byte ROM guest and test-only dual-owner DDR service. The existing CPU/cache/CDC/fabric bodies, assertion-lifetime repair and 1,138 Scala source files remain unchanged. The guest dirties 128 bytes at `0x80201000`, starts DMA to `0x80202000`, retires four cold 64-bit loads at 128-byte strides, checks their sum and DMA status 2, executes ordinary FENCE, then checks all 16 destination words individually. This adds no FENCE.I or shared-maintenance claim.

OFF → ON guest pass time is 7915 → 7285 ns. From the first source-store retirement at 1225 ns, elapsed work is 669 → 606 CPU cycles: 63 fewer cycles, or 9.42%. From DMA-start retirement at 3365 ns it is 455 → 392 cycles. The first cold request through fourth cold retirement is 168 → 105 cycles; individual cold-load retirements are 3845/4375/4735/5085 → 3845/4115/4265/4455 ns. Both retire the same 116 useful instructions with no repeated busy polling; terminal-spin retirements are excluded.

DMA fabric-start acceptance is 3295 ns in both modes. Final destination B is 4803 → 4099 ns, reducing the 128-byte copy interval from 1508 to 804 ns (377 → 201 fabric cycles, 704 ns less). The bounded payload rate is 84.88 → 159.20 MB/s, counting 128 copied bytes, not 256 read-plus-write bytes. Status-2 capture is 5195 → 4563 ns and ordinary FENCE retirement is 5415 → 4785 ns. These measured intervals are specific to this guest and matched service, not sustained DDR bandwidth or general application speedup.

Independent architectural, byte-memory, protocol-owner and CDC replay verifies the same 256 distinct source/destination backed bytes and ten AR/80 R/four AW/32 W/four B on each side. Four cold loads consume 32 architectural bytes but require 256 line-fill bytes; no data-prefetch prediction or allocation occurs. Actual peak accepted ownership is two reads and one AW-through-B on both sides, despite the service's capacity for two of each. Cold-demand external-read overlap with DMA/writeback ownership is 76 → 89 fabric cycles. ON shortens cold Acquire admission waits, then its third cold AR waits 44 ns (11 fabric edges) for the service's two-read capacity. This is an imposed test-service limit, not measured physical DDR capacity. All 26 CDC lanes are accounted for, nine active, with zero non-fetch accepted debt and observed DDR/DMA/shared owner activity throughout 1085/1715 ns post-pass guards. Clean cache lines and the terminal spin remain; global CPU quiescence is not claimed.

The new service has registered, uncontended accepted intervals of 11 fabric edges from AR to first R, four between R beats and two from final W to B. It is not the earlier single-owner service law. Both modes use the same capacity; this comparison measures Home overlap selection, not a capacity increase from one owner to two. Its separate endpoint qualification has 19 native positive cases, nine native invalid-endpoint rejections and 136 saved-observation rejections; those do not become actual-CPU fault/reset/hold coverage. Original native assertion wiring is preserved: 748/752 DUT sites plus 13 additive service checks per mode. This guest reaches 431/748 and 438/752 DUT sites, with 170225/169477 enabled known-true samples, not every site. Fourteen reached saved-observation corruptions per mode (28 total) are independently rejected; these are checker-sensitivity controls, not DUT fault injections.

Native host execution took 471.549/488.339 seconds (959.889 seconds total), separate from the simulated 9 µs per mode and the hardware-time intervals above. ROM instruction supply does not test DDR fetch fairness; finite accepted completion does not establish universal starvation freedom. Current maintenance/error, retained-W16 IRQ/SMC and other historical results keep their separate scope. Physical CDC/RDC/metastability, vendor clocks, MIG, routed timing, board behavior and broader ISA/MMU/FPU/IRQ coverage remain unqualified. Hardware timing is still unknown and defaults remain false. Final producer, independent-review, paired-metric and service evidence hashes are recorded in the descriptive manifest.

## Probe-window extension: rejected after component/resource screening

A separate recovery-only `dmaProbeWindowAcquire` overlay permits a different-set, unowned fresh Acquire during retained DMA-read ProbeSend/ProbeWait/WriteSend. It remains default false and is not in production RTL, configuration or CLI. Short component checks and independent review pass while preserving owner lifetimes, backpressure, arbitration and error policy. The finite matrix is not exhaustive; simultaneous new-window Release admission is not separately exercised.

Four matched component-service pairs deliver Acquire responses 22–58 Home cycles earlier, but DMA completion is unchanged and all-owner terminal/drain completion improves by only 6–7 Home cycles. These are component measurements, not CPU-cycle savings, and cannot be converted by a clock ratio. One actual logical map increases Home-own LUTs 10817→11563 (+746, 6.90%) and MUXF 2929→3720 (+791, 27.01%); FF/CARRY/RAM are unchanged, including Home children. Local mapped depth rises 11→12 for A.ready and 18→20 for maintenance D. These are graph-cell depths, not ns or Fmax. Earlier Acquires can still compete for downstream capacity and alter DMA service phase; these fixtures establish no global DMA non-regression.

The extension is rejected: the added logic and deeper local paths are disproportionate to the bounded terminal benefit, with no measured actual CPU gain. No CPU/system simulation or default promotion follows. The already validated actual-CPU dual-owner result remains 669→606 CPU cycles (63 saved, 9.42%) and DMA 1508→804 ns on the unchanged production Home. This rejected extension neither changes that baseline nor adds CPU, cache, CDC, DDR or physical-timing coverage. Component, review, resource and decision evidence hashes are recorded separately in the descriptive manifest.

## Before any default promotion

- Keep generic defaults false and retain the exact OFF fallback. A future qualified-profile default needs an explicit separate decision.
- Preserve the frozen SMC/concurrent-DMA scope and errata; distinguish its executed cases, diagnostic checker mutations and untested fault/privilege/MMU/IRQ combinations.
- Pin the full deployment profile, tools, sources and emitted composition. Constructor guards and live Selected inheritance are insufficient.
- Any current-source CPU integration starts a new qualification lineage. Re-establish affected protocol/cache/CPU architecture, memory, maintenance/recovery and SMC checks on that actual model with matched OFF/ON service laws. Historic results remain valid for their original pinned model, not the changed integration.
- Review end-to-end regressions and a defined traffic/service progress contract; do not infer universal fairness from finite tests.
- Obtain explicit authorization for any needed combined physical qualification, default edit or publication. No such action is implied by this document.
- Keep generated models/traces and machine-specific paths out of commits; preserve frozen evidence and unrelated dirty source changes.
