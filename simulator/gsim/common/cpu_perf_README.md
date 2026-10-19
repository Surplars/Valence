# Common CPU native synthetic observation, 2026-10-19

## Repaired candidate: same ROM guest passes on both CPUs

The later reset-arbitration candidate at
`c7c54336f730fe24a719cdda4ff8f84856ababa0` passes both CPU profiles with the
**identical 360-byte guest, generated testbench SHA and synthetic DDR service
law**. A1 also passes the independent wrong-pattern negative control. I1's entire
four-window record is bit-for-bit identical to the frozen reference below.
The old A1 failure remains valid historical evidence; it was not overwritten or
hidden by a startup delay. Full bound results are in
[`cpu_perf_repaired_20261019.json`](cpu_perf_repaired_20261019.json).

| Window | I1 CPU / fabric cycles | A1 CPU / fabric cycles | Both retired |
|---|---:|---:|---:|
| 256 dependent loads | 9279 / 7734 | 2035 / 5088 | 768 |
| 32 groups of 8 independent loads | 5819 / 4850 | 833 / 2082 | 608 |
| 4 KiB cold copy | 16875 / 14065 | 6652 / 16630 | 1280 |
| FENCE.I drain + resumed instruction | 8159 / 6801 | 1805 / 4512 | 1 |

Actual FENCE.I retirement completes after I1 7619 CPU / 6351 fabric cycles and
A1 1795 / 4487. Resumed instruction overhead is separately I1 540 / 450 and A1
10 / 25. Both profiles complete 192 reads and 64 real B responses and check all
512 source/destination words. A1 reaches two outstanding reads during copy and
two writes during drain; I1 reaches one each. Neither phase overlaps reads and
writes or saturates all four bridge read slots. Both clocks remain unchanged
(I1 3334 ps, A1 10000 ps, fabric 4000 ps); CPU-cycle figures are not equal-MHz
comparisons. No board MB/s is claimed.

**Important measurement boundary:** the guest executes from ROM at 0x80000000.
I1's configured cacheable region begins at DDR 0x80200000, so its ROM instruction
requests use the uncached/scalar path. Thus the low warm-load figures, I1
0.2207/0.3520 useful guest bytes per CPU cycle, include uncached ROM instruction
delivery, branch/loop instructions, dependencies and checksum accumulation.
They are not isolated L1 throughput. The cacheability and transport code is
source evidence for an instruction-delivery explanation; there are no stage
stall counters in this run to quantify its share or establish a unique
bottleneck. A follow-on DDR-resident execution of the same code after FENCE.I
can improve the measurement without changing hardware for this ROM result.

`cpu_perf_candidate.py` validates the candidate's new source/class/emission
chain and preserved profile configuration directly. The prior boot receipt is
only a reference for configuration/tool identities, never a candidate PASS.
`cpu_perf_lower.py` performs the one shared existing-tool sv2v conversion with
`--exclude=SeverityTask`; all 586 `$error` and 586 `$fatal` tasks survive exactly.
A1 positive/negative wall times are 105.74/99.17 s; I1 positive is 118.34 s.
All commands stay above 5.12 GB free with a 4 GiB hard floor. The historical
reference and its gzip-restorable failed executables below remain unchanged.

## Historical frozen reference

## Outcome

Frozen DUT: `df9821cd8be30898bf289a06350dd49d5ad65b66`.

- **I1: PASS** for this finite guest and external-memory oracle, including the
  wrong-expected-pattern negative control.
- **A1: BLOCKED** before the first measured window by a retained production
  assertion. The identical guest exposes an uninitialized three-input router
  reply arbiter; a read-only replay confirms an upstream/downstream handshake
  mismatch on its first DDR response. No A1 performance comparison is valid.
- No Scala, DUT RTL, capacities, clocks, assertions, production ROM or release ZIP
  changed. No full-ROM, GSIM, Vivado, Verilator, installation or board run occurred.

This is digital functional and **synthetic-service performance observation**,
not routed timing, measured DDR bandwidth, or FPGA/board qualification. These
finite instruction-loop costs include instruction delivery and branch overhead;
they are not isolated L1 load latency or a saturated/steady-state bandwidth test.

## Workload and exact windows

The same 360-byte ROM guest runs on both profiles. All 32768 ROM words are
programmed as in the passing boot fixture, outside every measured window. There
is no UART wait or inserted workaround delay. Host preload initializes only
external synthetic DDR, never CPU registers, internal cache state, or DUT RAM.

1. Warm all 64 lines of a 4 KiB pointer array outside the windows, then perform
   **256 total dependent loads**, one pointer-chasing load per iteration.
2. Perform **256 total independent loads**, 32 groups of eight distinct destination
   registers, with checksum accumulation and a separate guest-side expected sum.
3. Copy a cold 4 KiB source into a cold 4 KiB destination: 64 iterations of eight
   loads and eight stores, **512 loads and 512 stores**. Both addresses differ
   from the warm array. Store retirement is not external-memory completion.
4. Measure the subsequent FENCE.I and resumed instruction separately. Record the
   actual FENCE.I retirement point, when all 64 real B responses have completed.
   Only after final maintenance/home-idle checks does the host verify all 512
   source words and all 512 destination words against its independent formula.

Both unique begin/end marker PCs must retire in order; the marker NOPs are
excluded from retired-instruction counts. Lane 0 is processed before lane 1, so
same-cycle paired markers are handled correctly. CPU cycles are differences in
CPU rising-edge numbers. Fabric cycles count fabric rising edges strictly
between the marker timestamps; a boundary coinciding with a fabric edge or the
1 ps occupancy sample is rejected. Fabric ownership is sampled 1 ps after each
rising edge, after handshakes. Read ownership is AR→accepted RLAST, and write
ownership is AW→accepted B. CPU and fabric cycle units are never mixed.

The inherited `overlap` field means read-owner plus AW/W/B-queue activity; it may
include W accepted before AW. It is **not** generally a strict AW-owner-overlap
metric. All measured I1 windows have zero overlap, and strict read/write owner
overlap is independently zero here because each window has either max_reads=0
or max_writes=0. This limited result makes no concurrency-saturation claim.

## I1 measured result

CPU period remains 3334 ps; A1 remains 10000 ps. Fabric is 4000 ps, UART/AON
20000 ps, independent Ethernet raw clocks 8000 ps, phase offset 731 ps. Clock
rate is not treated as achieved performance, and the profiles are not compared
as though they ran at equal clocks.

| Window | CPU cycles | Retired | Fabric cycles | LD / SD | AR / AW / R / W / B |
|---|---:|---:|---:|---:|---:|
| dependent | 9279 | 768 | 7734 | 256 / 0 | 0 / 0 / 0 / 0 / 0 |
| 8-load groups | 5819 | 608 | 4850 | 256 / 0 | 0 / 0 / 0 / 0 / 0 |
| cold 4 KiB copy | 16875 | 1280 | 14065 | 512 / 512 | 128 / 0 / 1024 / 0 / 0 |
| drain + resume | 8159 | 1 | 6801 | 0 / 0 | 0 / 64 / 0 / 512 / 64 |

- The warm windows generate no DDR traffic. Their observed loop costs are
  36.2461 and 22.7305 CPU cycles per load, respectively.
- Cold copy transfers 8192 accepted R bytes, including source and destination
  write-allocation reads. Max outstanding reads is 1. Its 72 AR-stall edges are
  explicitly counted; R stall is zero. No write has completed in this window.
- Drain transfers 4096 accepted W bytes and receives 64 accepted B responses.
  Max outstanding writes is 1, with 18 AW and 159 W stall edges. B stall is zero.
- FENCE.I itself retires **7619 CPU / 6351 fabric cycles** after drain_begin.
  The additional **540 CPU / 450 fabric cycles** before drain_end are resumed
  instruction-fetch/retirement overhead. The end marker has home_drained=0 due
  to renewed front-end traffic; the final completion check subsequently observes
  maintenance=0 and home_drained=1 before any successful data verdict.
- Including prewarm, total traffic is 192 AR, 1536 accepted R beats, 64 AW,
  512 accepted W beats and 64 accepted B responses. All 192 reads completed.
- The negative control reuses the exact I1 VVP, changes only expected destination
  word 31 by one bit, and fails `COMMON_PERF_FINAL_PATTERN_ORACLE index=31` after
  real completion. It returns HDL exit 1, not a host/HDL timeout.

## Synthetic DDR service law

The original `cpu_boot_tb.sv` host service logic is reused verbatim. There are
16 host read owners, 16 AW entries, 128 W-beat entries and 16 B entries; native
IDs are preserved, with no singleton restriction. DUT capacity remains four DDR
slots and two write slots.

- AR ready: fabric edge modulo 5 is neither 1 nor 2.
- AW ready: fabric edge modulo 7 is neither 2 nor 3.
- W ready: fabric edge modulo 4 is not 1.
- Read eligibility: AR edge + 3 + (zero-based AR ticket × 7) modulo 13. Select
  the newest eligible ticket; hold each selected burst through accepted RLAST.
  An eligible/ready 64-bit R beat can transfer on each fabric edge.
- Write backing bytes update only after AW and all W beats are paired, applying
  WSTRB. This update is explicitly **not** counted as completed DDR service.
  B becomes eligible at pairing edge + 23 + (current accepted AW count × 3)
  modulo 31; **only a B handshake** releases its owner/completes the write.
- Original payload stability, owner reuse, bounds, burst geometry and WLAST
  assertions remain active. A1 original SV and severity-preserving sv2v output
  are hash-bound to the passing emission/boot receipts; assertions are retained.

## A1 failure and bounded diagnosis

Evidence: `common-perf-a1-r2/positive.log` and the 34-line
`common-perf-a1-diag-r1/diagnostic.log`, under the integration `evidence` directory.

Data-master router 0 serves the Home/ordinary bridge; router 1 serves separate
instruction fetch. Router bank 0 is ROM and bank 1 is DDR. The first DDR request
is aligned address 0x80210000, source 8, size 6, accepted at 131970731 ps.

| Upcoming fabric edge, ps | Observation |
|---:|---|
| 132026731 | occupied=0x0100; bank1 D valid=1/ready=X; host D valid=1/ready=1; replies chosen=1, lastGrant=XX |
| 132030731 through 132054731 | Seven genuine downstream D handshakes; host had already counted an extra first beat |
| 132058731 | occupied=0 while bank1 still presents source 8; retained “TileLink bank response has no matching source” assertion fires |

The router instantiates an unreset `RRArbiter(TLBundleD, 3)` in
`src/main/scala/ip/tilelink/TwoBankTileLinkRouter.scala`. The trace establishes
that its unknown initial grant state causes the first ready mismatch and early
owner release. No fixture admission contract requires an earlier UART/ROM data
access. The early DDR load is legal. This result is a frozen-baseline defect
report; fixing RTL requires a separate candidate, not an extra delay or a disabled
assertion in this test.

## Reproduction and evidence handling

`cpu_perf_native.py --prepare-only` builds the shared guest using tool identities
from the original passing guest receipt. Per-profile runs accept the original
passing `--boot-receipt`, frozen `--source-root`, and common `--guest-dir`.
Every command is time-bounded with a continuously monitored 4 GiB disk floor.
The initial I1/A1 positive bound is 600 seconds each. Use `--negative-pattern`
on I1 to repeat only this same finite guest with the independently wrong oracle.

`cpu_perf_diagnose.py --failed-run PATH OUTPUT` reproduces the failed A1 run with
read-only `cpu_perf_trace.sv` taps, unchanged traffic and a 132.1 us simulation
bound / 90-second wall bound. The recorded diagnostic used the equivalent
captured `executed-diagnostic-script.py`; the checked-in CLI is generalized and
syntax-checked, not separately simulated.

Original integration evidence remains untouched. New evidence directories:

- `common-perf-guest-r2`: common image, symbols, build/tool/source hashes
- `common-perf-i1-r2`: passing positive and independent negative, exact VVP
- `common-perf-a1-r2`: failed unchanged-DUT run, compressed VVP
- `common-perf-a1-diag-r1`: bounded replay, trace, exact diagnostic VVP
- `common-perf-{i1,a1}-r1`: fixture-only Icarus plusarg startup errors, preserved
  separately; no guest ran in these attempts

Failed VVP files are reversibly gzipped, with compressed and restored SHA-256
in each archive receipt. This keeps total new evidence plus sparse worktree
below the 100 MiB budget. Recorded positive I1 wall time is 129.91 s; its negative
is 127.05 s. A1 failure is 14.58 s; diagnostic is 15.17 s. All commands stayed
above 5.39 GB free. See `cpu_perf_baseline_20261019.json` for bound receipts and
machine-readable counters. No long stream or broad bandwidth matrix was run.
