# Optional local translated-response empty flow

`translatedResponseEmptyFlow` / `--translated-response-empty-flow` is independent
and **default OFF**. Performance is workload-dependent: independent warm READ
replay is 12.7397% slower with the option ON, while the earlier WRITE20 and COPY21
pairs improve. These mixed results do not support unconditional or default
enablement.

This local review candidate applies the qualified delta to published dev
`2886a3b0c8e8ab701ae7caa8c8cf5c7a50534a54`, tree
`ccab58e99eccd48ef0ef0644fd9a1330691ae5e1`. It preserves all fifteen published
standalone posted-owner source, test and documentation files exactly. That owner
remains uninstantiated in this candidate. Preparation does not update dev or main.
Existing final54/D32/D4 documents retain their original source identities.

The combined production `src/main` tree is `b178f3eacb834356e999f5bd5ee38daf5bf2b69f`. Removing only the two
uninstantiated posted-owner/proof source additions gives the exact qualified
response-flow production tree `996e8819be894bc7272191331f78db8fd46e3fe4` from
experiment `c3f3af4857e02f83bac50bb54b78ba92d128b081`. Every pre-existing production
file is byte-identical. This is a source projection, not a claim that historical
receipts were run against the new combined source inventory.

## Profile and boundary contract

The measured profile is two-issue selected, DTLB16, LSU4, virtual-load precheck,
physical-load ingress flow, older-load retirement, previous fetch packet, DMA4,
prepared stores, checked store prefetch and store-prefetch MRU insertion.
**Prechecked request flow remains OFF.** Only the response Boolean differs
across the measured OFF/ON sides. A read-only ON preflight is:

```sh
python3 -B simulator/gsim/fpga_next_board.py --tag response-flow-review --variant selected --preflight-only --lsu-entries 4 --data-translation-entries 16 --virtual-ram-load-precheck --physical-load-ingress-flow --load-order-older-retire --fetch-previous-packet --dma-line-transfers --dma-line-entries 4 --prepared-store-lookahead --store-next-line-prefetch --store-prefetch-mru-insertion --translated-response-empty-flow
```

Native `fpga/next/export.py` accepts the same profile flags, uses selected by
default and requires `--output`; without `--emit` it only performs preflight.
Scala entry points include `FpgaNextConfig.fromOptions`, `FpgaNextMain`,
`FpgaNextBoardGsimMain`, and explicit `BoardSocGsim`/`BoardSocTop` parameters.
No preset enables the option. It requires registered translation heads, which
in turn require registered request/fabric and response boundaries. Illegal
unregistered combinations fail Scala construction/elaboration. Both Python
preflights now also reject the existing invalid prechecked-flow-without-virtual-
precheck combination; valid profile output is unchanged. Other hardware-legal
combinations, including reference/storage topology, D4/D32, or response flow
with prechecked request flow, are **unqualified by this evidence**.

The buffer retains two dedicated register slots, capacity two and II=1. Incoming
ready uses pre-edge occupancy credit: a full queue cannot borrow a simultaneous
dequeue's credit. Requests remain transparent with no new ownership. OFF connects
the original registered queue directly. ON always prioritizes an old registered
head. At empty, an actual response can reach a ready consumer on the same edge
without entering storage; a blocked consumer instead causes exactly one capture,
held until consumption. `idle` describes stored occupancy, not incoming or
outstanding work. Complete data/access-error/page-fault payloads travel together.
Permission, request, translation, store-ACK and cache implementations do not change;
the bypass neither creates early store ACKs nor bypasses authorization. Component
payload coverage alone is not CPU atomic/MMIO/interleaving coverage.

## Completed measurements and verification

### Confirmed warm READ regression

Independent same-guest case 0 replay is **16531 → 18637 guest ticks**, a 2106-tick
increase: **+12.7397% time / −11.3001% throughput**. Both rows are S-Bare, 8 KiB
warmed READ, two pages, count 1024, eight passes, 65536 payload bytes, zero flush
tail and checksum `6863348401280905216`. Time change is `ON/OFF-1`; throughput
change is `OFF/ON-1`.

Both executions passed the original independent 32768-word per-case and final
buffer checks, fault/trap sequence 13/15/1/9, accepted timing markers, per-case
poison, three offline oracle poisons, the actual trap-injection negative and all
eighteen owner categories quiet for two consecutive snapshots. Qualified model,
source, tool, full-guest and kernel identities were revalidated. The only model
parameter change was the response-flow option; prepared stores, store prefetch
and MRU stayed enabled on both sides.

Within the timed READ interval, PF candidates/allocations/useful events and
PF busy/miss-owner/release-owner cycles were zero on both sides. AXI read
requests changed 1→2 and accepted read beats 8→16; writes remained zero. These
are passive observations. A later source-bound scheduling diagnostic reproduced
both original results and traced the timing change; no selective-flow RTL fix
was applied. The lower whole-boot ON count does not erase the slower timed READ.

The earlier LSU completion wins completion port 0 while the pointer-increment
instruction waits in execution port 0. There are 4093 such accepted-LSU/held-pointer
overlaps with flow ON, versus zero OFF; 4085 of 8192 retired pointer increments
change from one to two dispatch-to-execute cycles. The dependent next load becomes
ready later, and the steady four-load period changes from eight to nine cycles.
All 8192 retired loads are cache hits. One extra accepted but cancelled speculative
load beyond the tested 8 KiB region misses and retains response ordering until its
reply. It is tracked separately from the retired loads.

The diagnostic partitions the 2106 additional guest ticks into disjoint observed
interval differences: 2040 steady within-pass intervals, one 49-tick interval,
14 across pass boundaries, one before the first load and two after the last load.
The port-overlap count and response latencies are not additive estimates of
removable clocks. External AR addresses were not recorded in this diagnostic,
so it does not prove the exact identity of the extra external read burst.
Read-only arbitration alternatives are documented separately; no timing closure,
priority change or measured remedy is claimed.

The original-ROM run independently observes row 0 at **16582 → 18693 ticks**
for the same case tuple and unchanged kernel. Its startup and prestate differ
from the standalone replay, so these are separate comparisons with their own
OFF baselines. The first six matching rows of the now-completed original-ROM pair show
workload dependence:

| Original-ROM row | S-Bare workload | OFF ticks | ON ticks |
|---|---|---:|---:|
| 0 | 8 KiB warmed READ | 16582 | 18693 |
| 1 | 8 KiB warmed WRITE | 41256 | 41256 |
| 2 | 8 KiB warmed COPY | 57541 | 49294 |
| 3 | 128 KiB stream READ | 172194 | 172193 |
| 4 | 128 KiB stream WRITE | 215809 | 211731 |
| 5 | 128 KiB stream COPY | 383555 | 376455 |

The complete ON run passed at **95,279,477 cycles**. All 54 rows, the original
return menu, the subsequent `h` response, 64 CSR/PMP fields, final DDR bytes and
one empty snapshot of all eighteen owner categories passed. This final drain is
**not** a two-cycle quiet guarantee. One cold seed followed by 96 complete-state
resumptions preserves the original ROM execution; all 97 attempts exited zero.
Three intended faults and 54 supervisor returns produced 57 checked trap returns.
Every row has independent checks of 32768 data words and 2048 PTE words; all 163
oracle poisons were rejected.

[The complete 54-row comparison](translated-response-empty-flow-full54.csv)
keeps every kernel and flush delta. Kernel time improved in 46 rows, was identical
in one and increased in seven. The regressions above 1% are S-Bare warmed READ
(16582→18693, +12.7307%) and S-Bare four-page READ (2125→2253, +6.0235%). Each Sv39
mode has seventeen faster rows and one slightly slower warmed READ row. For
example, original-ROM Sv39-4K 128 KiB COPY changes 497145→464164 ticks while flush
changes 5567→5584. Sv39-2M 128 KiB COPY changes 493923→460856 with flush
5565→5573. No unweighted average is presented across different payloads.

These are matching original-ROM rows with their own sequential prestate. They
must not be exchanged with the standalone case-0/20/21 baselines. CSV rates use
the fixed 100 MHz simulation convention; they are not routed FPGA or Linux
throughput measurements. The older OFF full54 and new ON full54 retain separate
source/model/checkpoint identities.

### Earlier independent WRITE20 and COPY21 pairs

The completed same-guest WRITE20/COPY21 pairs below retain their original
baselines and results. They do not substitute for the warm READ regression or
for the matching full-ROM rows above.

| Half-open ROI | OFF cycles | ON cycles | Cycle reduction | Cycle-derived throughput increase |
|---|---:|---:|---:|---:|
| WRITE20 | 207483 | 207128 | 0.171098355% | 0.171391603% |
| COPY21 | 497148 | 464186 | 6.630218768% | 7.101032776% |

Reduction is `(OFF-ON)/OFF`; throughput change is `OFF/ON-1`. WRITE flush tail
changes 10681→10684 cycles and COPY 5574→5587. Three COPY read beats move across
the ROI/flush boundary; whole-boot AXI and prefetch totals remain equal. Local
response-clock savings are not a count of removable program clocks.

For the WRITE20/COPY21 pairs, both models were freshly generated, compiled and
executed separately using the same guest/kernel bytes. All four CPU replays retain
independent full-buffer byte checks, per-case row oracle, three faults, S-mode
return, poison controls,
actual trap negative and eighteen-owner quiet-two drain. They used the original
high-level oracle audited for same-edge behavior, not the old non-flow token ledger.

- Component: six finite cases and 656 responses per mode, seven exact-reason
  negative controls per mode under ASan/UBSan. Covers all data/error/page-fault
  tuples, held faults, exactly-once capture, old-head priority, full-pop non-pipe
  credit, simultaneous pop/capture, capacity, request transparency and drain.
  Isolated latency is one→zero clocks; both 96-response streams span 95 clocks.
- Configuration: original 21 focused Scala/configuration checks and two CLI
  checks passed on c3f3. Delivery passes five light host tests for defaults, native
  command forwarding and prerequisite rejection, including 16 invalid-option
  subcases. Fresh host-ledger controls at the tracked path pass 44 positive
  validations and 19 negatives under ASan/UBSan. Relocation does not claim a
  new Scala or component execution; those Scala sources/drivers are unchanged.
- Fresh full-board RV64GC: OFF 33370 / ON 33316 cycles, 32 FPR context, precise
  supervisor ECALL, compressed retirement, DDR and corrupted-anchor negative.
  These are smoke counts, not workload performance.
- Fresh ON timer: 186064 cycles, two traps/two mret, 121 IRQ-pending/PF-live
  overlap cycles, all 8192 final words, eighteen-owner drain and three negatives.
- Fresh ON NEMU: three original physical M/Bare integer read/write/copy4096
  guests, 20685 retired PC comparisons, 461632 GPR comparisons, 12583104 final-RAM
  bytes, unchanged PC sequences, zero resynchronizations and four negatives.
  GPRs are checked after each complete retire edge, not between dual-retire lanes.
- Fresh ON CPU+coherent-copy-DMA: 53301 cycles, four descriptors, three successes,
  one injected read error, restart, 1024 dirty-source and 1024 dirty-destination
  checked beats, zero terminal owners and four negatives. This is a separate
  CPU+DMA run, not concurrent NEMU/DMA validation.
- Full original 54-case ROM menu ON: **PASS** on the newly bound c3f3 ON model,
  independently audited at 95,279,477 cycles, with all three original modes,
  normal/fault restoration, menu return and `h`, data/PTE oracles and final drain.
  The original firmware was freshly built into the r1 output directory and copied
  byte-exactly into r2. A separate provenance correction records the actual build
  command; the earlier frozen preparation description is preserved, not rewritten.
  The prior 9483 D16 OFF full54 remains a separate baseline. The complete terminal
  archive is `libfile_36a0294a57cc8191ab8548445eda30f8`; its exact SHA and the
  preparation dependency are recorded in the companion evidence JSON.

The original NEMU/DMA hosts failed the obsolete assumption that actual response
input fire equals internal queue enqueue. Both failures remain preserved. A
separate strict observer continuation passed 44 positive host validations and
19 mutated-observation controls, retaining original observer.cpp files,
authorization oracle, architectural checks, guests and all runtime negatives.
Actual ON empty bypass counts were read 2698 / write 2693 / copy 5253 / DMA 8728. Those
runs saw zero held captures and zero registered-head transfers; component and
host controls cover held/queued/full-credit cases, not invented CPU coverage.

## Preserved observer and reproducible controls

The exact corrected header, complete validate/advance controls and patch are
tracked in [translated_response_flow_ledger](../simulator/gsim/harness/translated_response_flow_ledger/README.md).
Its provenance binds original execution receipts. The old shared header stays
unchanged. Empty bypass is established from pre-edge shadow occupancy and both
actual input/output fires, not from absent queue taps. Independent port/queue/
pass conservation is mandatory. Posted stores retain their separate early ACK
and later physical-response obligations. Foreign FP/system epochs still fail.

```sh
python3 -B simulator/gsim/test_translated_response_flow_cli.py
python3 -B simulator/gsim/test_return_flow_ledger.py --cxx clang++ --output build/return-flow-ledger-review
```

The second command needs an installed C++20 compiler with ASan/UBSan; `GSIM_CXX`
is also supported. It runs only host controls, requires a fresh output directory,
hashes source/compiler inputs and preserves failed receipts. It does not run a
DUT. Original CPU execution was in the archived continuation namespace, not this
new tracked path. The preserved controls cover complete advance transitions for
held capture/pop, old pop/new capture, full-two pop without borrowed credit, all
payload flag tuples and early posted ACK followed by later physical response.

The component runner `simulator/gsim/translated_response_flow.py` accepts explicit
`--output`, `--tool-receipt`, `--baseline-fir` and optional `--freeze-only` inputs.
A full invocation runs focused Scala and serial OFF/ON components. Retrieve the
qualified baseline FIR/tool identities from the original archives, use a fresh
output and do not share checkpoints across differing model ABIs.

## Native cost and remaining limits

Fresh c3f3 OFF/ON native exports passed. That OFF module inventory is
byte-identical to the previously qualified 9483 native model. Reachable scalar/array declaration counts are:

| Scope | Scalar bits, both modes | Array bits, both modes |
|---|---:|---:|
| BoardSocTop | 85417 | 705223 |
| IntegerBackend | 29623 | 15585 |
| ParallelLoadStoreUnit | 2572 | 8 |
| StoreBuffer | 445 | 5 |

All ten RAM/storage capacity/port contracts are unchanged. These are literal
native declarations, not mapped FPGA area. ON has 266 module definitions versus
265 OFF; counts follow reachable instances, without double-counting definitions.
Six existing SV modules differ and one is added. Two stricter SV bridge checks
failed and remain preserved. An independent token-by-token review accounts for
all changes: constant-zero FP request fields, response specialization, unused
idle/count pruning, intended enqueue gate, valid OR and old-head-priority muxes.
This bounded review is not formal equivalence; two-state mux/AND reasoning does
not establish arbitrary X/Z equivalence.

The forward path lengthens through adapter/router, bypass, integer/FP ownership,
StoreBuffer and LSU result/exception logic. Ready remains registered-occupancy-
only. The selected LVT profile forces `fastHeadLoadRetire=false`; no same-cycle
retirement claim is made. No STA, synthesis, routed Fmax, mapped PPA or board
result exists. A reduced achievable clock could offset the COPY cycle benefit.
No new controlled Sv39 late-cancel/ROB-reuse proof, arbitrary IRQ/fault-phase,
packet-DMA or broader ISA compliance claim is made. Timer restores only the
tested live t0..t4/sp context.

[The durable evidence index](translated-response-empty-flow-evidence.json)
records exact archive hashes, Library IDs, source identities and original result
receipts, including the warm READ loss, its measured scheduling mechanism and
the independently completed new full-ROM run. Historical partial snapshots and
failed attempts remain preserved with their original scopes. The original
physical posted-store cache/CPU reconstruction remains a separate pending effort;
its published standalone component is preserved but never instantiated here.
Defaults remain unchanged. The measured tradeoffs do not justify unconditional
enablement, and the independent prechecked-request-flow option remains OFF.
