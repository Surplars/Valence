# Passive frontend performance diagnosis, 2026-10-07

## Scope and reproduction

Run `source scripts/cloud/env.sh`, then:

```
python3 simulator/gsim/frontend_perf.py --tag <unique-tag> \
  --profile staged-fetch-feedback \
  --firmware-dir build/gsim/performance-baseline-20261007/firmware
python3 simulator/gsim/analyze_frontend_perf.py \
  build/gsim/frontend-perf-<unique-tag> \
  build/gsim/performance-baseline-20261007
```

One board model is reused for one-iteration CoreMark, short DDR control and RV64GC context/ISA smoke. No CAD, full GSIM, long Linux or NEMU rebuild. Two issue, RV64GC/FPU, 100 MHz, UART460800, 2 GiB DDR, two-way data cache and requested instruction-prefetch configuration are preserved. The effective physical instruction cache is512B (8×64B,4sets,2ways). Its line prefetch is DISABLED in the production two-word fetch path: enabling it requires four-word fetch. The requested flag alone must not be described as active physical-line prefetch. The workload firmware's reporting constant remains 50 MHz; use raw guest ticks, not its printed rate. These are simulated guest-cycle measurements, not official CoreMark scores or routed/physical-board results.

Passive BoringUtils taps exist only in the GSIM test wrapper, enabled with its final `frontend-probes=1` argument. Other invocations default to disabled probes. The host observer samples at the existing post-step boundary. No production hardware ports or functional logic were changed for this measurement.

## Evidence and equivalence

Measured baseline: `build/gsim/frontend-perf-baseline-20261007-r2/`.

- `receipt.json`: configuration, source/firmware/artifact hashes, full workload logs, negative-oracle result.
- `frontend-analysis.json`: structured event matrix and exact-equivalence checks.
- `probe-source/`: exact source used for this measured run, prior to the subsequent test-wrapper opt-in cleanup. This preserves the measured input rather than presenting later source as already measured.
- All firmware BIN bytes match the archived uninstrumented baseline.
- All original guest output lines, CoreMark CRC/ticks and every existing performance counter match exactly for all three workloads. The known meaningless baseline CoreMark-named ROI in the unrelated DDR/GC controls is excluded; whole-run counters still match exactly.
- Existing independently checked GC context/anchor negative test still fails as expected.

The initial probe elaboration rejected indexing a child UInt before boring it; boring the UInt and indexing the local result fixed visibility. No failed elaboration was treated as measurement evidence.

## CoreMark result

Guest ticks 834653; inclusive retirement ROI 834654 cycles, 360528 retired instructions, IPC0.431949. Head empty313283 cycles; zero retirement617794 cycles.

| Observation | ROI cycles/events | Head-empty overlap |
|---|---:|---:|
| Physical instruction wait without reply | 277263 | 235291 |
| Translation phase | 42308 | 20900 |
| Physical send phase | 42308 | 6623 |
| Virtual reply phase | 42309 | 16130 |
| Reply with next request valid but blocked | 35040 | 14094 |
| Raw lane0 absent | 473974 | 290526 |
| Full reservoir, consuming and valid supply, unpaused/uncancelled | 46059 | 0 |
| Three reservoir entries, consuming and two valid supply lanes | 4912 | 0 |
| Allocation offered with ROB full | 150562 | 0 |
| Allocation offered without lane0 PRF capacity | 3567 | 0 |

The physical wait-without-reply overlaps 75.1% of empty-head cycles. This is an observed overlap, not proof that each of those cycles could be eliminated. Adapter physical wait phase, including replies, is319571 cycles;42308 physical requests give approximately7.55 wait-phase cycles per request, with ROI-boundary caveats.

All42308 translation requests are bare; all translation responses occur in the request cycle. Translation-service waiting is0, while the adapter still occupies its separate translation phase for42308 cycles. All35040 virtual request-blocked cycles coincide with an old reply and a waiting next request. Bare-stage bypass and reply/request turnover therefore have concrete opportunity counts, but their5.07% and4.20% cycle shares are not additive predicted speedups.

The reservoir is empty462341 cycles(55.4%). Raw lane0 supply is absent473974 cycles(56.8%). Supply/capture/rename counts, occupancy histograms and every event's empty-head/zero-commit cross-tab are in the structured matrix. ROB pressure is substantial when allocation is offered; PRF pressure is much smaller; dispatch and tag-exhaustion flags are0. Reservoir pre-consume credit rejection occurs, but does not coincide with an empty ROB in this workload.

Successor corrections6027, non-inclusive local backend redirects8443, queued instructions discarded13581. Corrections are not synonymous with branch mispredictions. Correction-to-first capture averages approximately11.0 cycles among6027 observed completions; first subsequent rename/retirement measurements are censored/superseded as reported. The next retirement can be older work and is not a correct-path-retirement latency.

## Interpretation limits and next measurement

The event matrix overlaps and must not be summed into a CPI stack. The adapter phase histogram is mutually exclusive and exhaustive for this run (idle388158, translate42308, send42308, wait319571, reply42309, unclassified0), but phases also overlap useful backend work.

There are6899 instruction TileLink Gets versus42308 physical instruction requests. The first pass does not expose InstructionLineCache hit/miss/refill classification or InstructionRom's live cache versus registered-window presence. Do not infer a precise cache miss rate or assign the remaining physical latency to a single component solely from these counts. The next candidate probe revision adds already-public TileLink Get size/address (candidate-only, no baseline rebuild), which can separate64B line fills from fallback word reads and identify requested code lines. TL source and cache-state internals remain unobserved. Minimal read-only visibility for those internals, or additional interface transaction tracing, can distinguish downstream miss cost from fixed hit-path latency without changing production behavior.

No result here qualifies numerical FPU throughput, DMA contention, independently clocked Ethernet/CMU, DDR PHY, routed timing or Linux.

## Optional fetch-turnover candidate

`build/gsim/frontend-perf-turnover-20261007/` contains the optional `staged-fetch-turnover` run and source snapshot. All three workload oracles and the GC negative control passed; firmware BINs are identical. This candidate remains separate from cache-capacity changes.

- CoreMark ticks834653→790688:5.267% fewer cycles; retired instructions stay360528; CRC text unchanged; IPC0.431949→0.455967.
- Translation phase42308→0; reply-with-next-request-blocked35040→0.
- Head-empty cycles313283→278528.
- Physical wait-without-reply grows277263→297779; physical requests42308→44240. The faster frontend also raises instruction line traffic: candidate7411 Gets are all size6 (64-byte lines). Baseline6899 Gets were not size-classified in the first probe revision. These tradeoffs limit additive speedup claims.
- Short DDR read5706→5684, write8142→8120, copy13772→13745 ticks; pointer chase3998→4014 ticks is a0.40% regression. GC smoke32326→32177 cycles with all32 FPR context signatures.

The candidate Get histogram touches90 distinct64-byte lines (5760 bytes), concentrated in the state benchmark code. An unordered line histogram does not predict the hit rate of a larger cache.

## Capacity experiment instrumentation

The next isolated experiment uses `staged-fetch-feedback` for both8 and32 instruction-cache lines. The fetch-turnover switches remain off, the two-way organization/64-byte lines remain fixed, and only capacity changes. `--instruction-cache-lines 8|32` passes the capacity through the test board; production default stays8.

A fresh8-line run can use `--coremark-only`: its purpose is exact same-BIN output/counter equivalence and new passive cache attribution. Unchanged DDR/GC coverage then references the previously verified8-line baseline; those controls are not represented as rerun. The32-line candidate runs CoreMark and the necessary short DDR/GC controls once, using one model per geometry.

Additional passive probes provide accepted hit/miss/fallback classes; cache state; demand refill request/completion/error/install; TL source; and request-to-response latency by accepted class. A transaction observer independently enforces exclusive request classes and one active cache response owner, including old-response/new-request turnover. ROI-boundary orphan replies and unfinished requests are reported explicitly. Latency bin64 means64 or more cycles; sums and maxima retain the full count.

State mapping:0 idle,1 fallback-active,2 send-fill,3 wait-fill,4 wait-prefetch,5 hit-reply,6 line-reply,7 retry-fallback. The state×physical-wait counters form an additive partition of the measured physical-wait event; other event rows still overlap.

The runner verifies emitted FIR geometry rather than trusting CLI metadata: two512-bit memories with the expected set depth, valid-array dimensions and tag width must match. It records compiler/toolchain configuration and hashes each executable and shared model object. A host-only independent ASan/UBSan test (`frontend_observer_test.py`) checks41-cycle miss,1-cycle hit, simultaneous turnover, censored boundary reply, invalid class partition and duplicate ownership rejection.

### Fresh8-line direct attribution

`build/gsim/frontend-perf-capacity8-20261007/` passes exact original CoreMark guest output and every original performance counter, with all BIN bytes identical. Emitted FIR confirms512B/4sets/2ways; source guards and executable/object hashes pass. The original DDR/GC baseline controls were not rerun.

Within the CoreMark ROI:

- 42308 accepted instruction-cache requests =35409 hits +6899 misses +0 fallback.
- Every hit responds in exactly1 cycle.
- 6899 misses accumulate284162 request-to-response cycles: mean41.19, maximum74.6034 misses take41 cycles and841 take42 cycles; remaining misses are longer.
- All6899 instruction Gets have size6 and source0;55192 D beats equal8 per line. Refill error0, install6899, prefetch-wait0.
- Every277263 physical-wait-without-reply cycle is accounted for by the cache:6899 send-fill +270364 wait-fill. No idle/hit-reply/fallback/prefetch state contributes. This also equals miss latency sum minus miss count.
- 235291 of these cycles overlap empty ROB head:2125 send-fill +233166 wait-fill.
- No ROI-boundary orphan response or unfinished cache request remains.

The earlier refill-dominance hypothesis is therefore directly verified. This is an exact classification of physical-wait cycles, while their effect on total execution time still depends on overlapping backend work.

## Capacity-only result and next backend attribution

The completed 32-line capacity-only run is
`build/gsim/frontend-perf-capacity32-20261007/`. With the identical RV64IM BIN,
CoreMark ticks fall from 834653 to 586310 (29.754% fewer cycles; 42.357% more
same-clock throughput). ROI retirement count is 360528 and IPC is 0.614909.
Misses fall from 6899 to 284; physical wait without reply falls from 277263 to
11830 cycles, only 2.02% of the new ROI. This supports stopping the capacity
sweep at 32 lines for this workload; 64 lines were not measured.

Short DDR controls preserve small regressions: read 5706→5686, write 8142→8146
(+0.049%), copy 13772→13776 (+0.029%), pointer chase unchanged. GC smoke is
unchanged. These are narrow synthetic-latency GSIM controls, not memory-controller
bandwidth or physical DDR results.

Remaining backend counters are observations rather than a causal diagnosis.
Head-not-done and head-memory overlap. In the staged LSU path, request acceptance
can mean FIFO enqueue, not memory-service acceptance. The selected LSU request
owner and the StoreBuffer FIFO dequeue owner can differ, so StoreBuffer cause 0
or causes 1–7 must not be attributed to the ROB head without a full token match.

The next useful study is owner-qualified tracing across request FIFO, store
buffer, translation, cache and return, plus actual LSU-slot occupancy versus
serial exclusion. A mutually exclusive zero-commit classification should
prioritize retirement progress, recovery, empty head, done-awaiting-retirement,
queued readiness, issued nonmemory, issued-memory phase and unknown, and verify
that the partition sums. Ordinary data adapter/router/cache-hit paths already
pipeline; a generic data-turnover change, extra load bypass or issue widening is
not justified by these counters. No such backend change is enabled here.

## Combined turnover + 32-line result

`build/gsim/frontend-perf-combined32-20261007/` combines the opt-in
`staged-fetch-turnover` profile and 32-line I-cache. The original RV64IM BIN is
unchanged. CoreMark ticks are 532363: 36.217% below original 834653 and 9.201%
below capacity-only 586310; same-clock throughput is 56.783% above original.
Inclusive ROI is 532364 cycles, with 360528 retirees and IPC 0.677221.
CRCs and retirement count match the original. The new ordered PC trace contains
360528 entries, but there is no original-BIN baseline ordered trace; count
matching must not be represented as ordered-trace equivalence.

There are 284 instruction misses and 11652 physical-wait-without-reply cycles
(2.19% of ROI). Short DDR read/write/copy/chase ticks are
5684/8112/13744/4012 versus original 5706/8142/13772/3998. Pointer chase therefore
regresses 0.350%. GC smoke is 32177 versus 32326 cycles. All bounded workload
oracles and the GC negative control pass; full qualification remains unrun.

The new zero-commit partition is independently sum-checked. ROI counts are
recovery 15466, empty 31077, done-awaiting-retirement 23321, profile operand-wait
0, structural 84175 and executing 166575. Executing subdivides into nonmemory
27403, downstream-after-LSU-enqueue 137557 and completion 1615. These bins name
observable pipeline states. In particular, downstream-after-enqueue is not a
measurement of physical memory service and must not be interpreted as such.

## Separate matched RV64IMC/lp64 software pair

`build/gsim/frontend-rvc-pair-20261007/receipt.json` passes using the same
compressed firmware BIN on baseline8 and combined32 existing board models.
No hardware model was rebuilt. This is a separate experiment: do not compare
these cycles as if the original RV64IM BIN were unchanged.

- Baseline8 611411 ticks → combined32 486605 ticks: 20.413% fewer cycles.
- IPC 0.589665 → 0.740903; both inclusive ROIs retire 360528 instructions.
- The full ordered retired-PC streams are byte-equal, SHA256
  `142a5aafefa1eabaa2b76f5d7c42baa1cb31de1c6fd95384652ea4e936aa84fa`.
  This verifies ordered PC equivalence for this pair, not complete architectural
  register/memory-state equivalence or ISA compliance.
- Independent objdump mapping finds 178610 compressed retirees out of 360528
  (49.54%); cache misses 2743→170, physical fetch wait 110504→6975 cycles.
- The firmware uses `-march=rv64imc_zicsr_zifencei -mabi=lp64` (soft-float), with
  matching CRCs. The unchanged default builder reproduces the original RV64IM
  BIN byte-for-byte; proof and firmware hashes are in
  `build/gsim/coremark-rvc-20261007/build-receipt.json`.

Reproduce the compressed build and matched pair only after producing the two
corresponding original board model directories:

```sh
python3 fpga/firmware/build_coremark.py --iterations 1 --clock-hz 50000000 \
  --memory ddr --march rv64imc_zicsr_zifencei \
  --out build/gsim/coremark-rvc-20261007/rv64imc
python3 simulator/gsim/coremark_rvc_pair.py \
  --baseline build/gsim/frontend-perf-capacity8-20261007 \
  --candidate build/gsim/frontend-perf-combined32-20261007 \
  --firmware build/gsim/coremark-rvc-20261007/rv64imc \
  --out build/gsim/frontend-rvc-pair-NEW_TAG
```
