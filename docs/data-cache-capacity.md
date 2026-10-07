# Bounded coherent D-cache capacity experiment

## Scope

Opt-in comparison of 32 versus 64 total 64-byte lines, two ways: 2 versus 4 KiB.
Both use selected `staged-fetch-turnover`, two LSU slots, issue width two,
ROB16 / PRF48 / predictor32 / store-buffer2, 32 I-cache lines (2 KiB), RV64GC/FPU,
100 MHz CPU, UART 460800 and 2 GiB DDR. Load-issue bypass stays disabled.
No defaults, signoff guards, RX_STOP behavior, FPU, DDR range or clock changes.

This is **not only a data-SRAM resize**. `MachinePlatform` couples
`CoherentLineHome.trackedLines` to private-cache capacity. The home owner directory
therefore doubles from 32 to 64 entries, with two ways and 16→32 sets. Its tags
remain 58 bits. The private cache has eight byte-masked 64-bit banks, each
32→64 entries, 54→53-bit tags and 16→32 LRU bits. Data RAM is 16384→32768 bits.
The response queue stays two entries, only one miss is active, and acquire,
line-transfer and probe engines retain their existing four-entry credits.
The cacheable address window is unchanged.

## Activation and defaults

Every appended argument defaults to 32 D-cache lines. Existing positional calls
remain valid. The production managed export accepts:

```sh
mill -i IonSoC.test.runMain ooo.ManagedBoardSocMain \
  build/managed-dcache64-fresh 100000000 staged-fetch-turnover 460800 \
  rv64gc 50000000 50000000 250000000 2147483648 32 64
```

The last two arguments are instruction-cache lines and data-cache lines.
`BoardSocGsimMain` appends data-cache lines **after** its backend-probes argument.
`EthernetSocTop` and `EthernetTimingMain` also pass the optional data capacity.
The generic `BoardSocMain` interface and existing default capacities are unchanged.
This is an opt-in experiment, not a recommendation to replace the default.

A capacity change needs fresh full RTL implementation and timing/resource
signoff. It is not a ROM ECO. No previous timing receipt, netboot WNS or routed
signoff applies to the resized data cache/home directory.

## Independent short verification

`DataCacheCapacitySpec` checks emitted SRAM/tag/LRU/home geometry for managed
32/64-line boards, the omitted D-cache default, Ethernet wrapper forwarding,
unsupported geometry rejection and the explicit 2 GiB DDR bound.

The parameterized coherent-cache driver derives conflict stride independently:
`64 * totalLines / ways`. It checks same-set residency, actual dirty LRU victim
writeback/reload, masked writes, probes/invalidation, hit-under-miss, response and
probe/bypass backpressure, flush, denied last-beat refill and successful retry.
An independent architectural memory map is preserved. Corrupt refill data must
fail the driver.

The real cache + home + Ethernet DMA fixture runs both geometries with three
backpressure seeds. Three same-set lines force a dirty victim out. It verifies
backing-memory writeback, the remaining upper-way owner hit, eight actual memory
read beats when the victim is reloaded, DMA TX reading/probing the remaining
owner, and a subsequent eight-beat CPU reload after invalidation. Existing dirty
TX, dirty RX and partial-tail oracles remain. Corrupt TX expectations must fail.
This short fixture is not a full physical/asynchronous GMAC DMA proof.

## Matched workload and counters

CoreMark reuses the exact RV64IMC BIN with SHA-256
`05b9a01d74a03389433ef942fef7056827331be18a91e0795f6456cee51fdac5`.
Its selected 2 KiB anchor is 486605 guest ticks, 360528 ROI retired instructions
and ordered-PC digest
`142a5aafefa1eabaa2b76f5d7c42baa1cb31de1c6fd95384652ea4e936aa84fa`.
No cross-binary performance comparison is used.

The optional `build_ddr_bench.py --locality` firmware adapts existing DDR kernels
at 1/2/4/8 KiB. Each size measures cold read, three warmed read/write/copy repeats,
separate write/copy flushes and cold/warmed pointer traversal. Copy has two
buffers, so its true data footprint is twice the per-buffer size. “Warmed” means
one preceding complete sweep, not guaranteed residency when capacity is exceeded.
Source/destination are poisoned before write/copy; firmware checks independent
expected values and the host checks final AXI backing memory. UART reporting is
after timed work/flush, and counter ROIs use actual start/stop `rdtime` retirement
PCs from the final ELF. These windows include both retirement cycles and can
differ from guest timer ticks; they are not exact per-request ownership windows.

Existing 2 KiB model objects are hash-verified and reused, with a small harness
relink; one new 4 KiB board model is built. A normalized emitted-FIR comparison
removes source annotations and assertion diagnostic line numbers only. Unchanged
core/fabric/queue modules are compared, and disabled added observer outputs are
reviewed separately. No old owner ledger is generalized to a new cache geometry.

Counters are passive scalar observations checked against emitted FIR definitions.
Hits/misses count accepted ordinary cacheable requests. Empty/replacement and
read/write miss classes partition misses. Dirty-eviction events exclude flush and
probe writebacks; C-channel dirty writeback beats/lines include flush, and probe
beats are separate. Miss/bypass/probe blocked and refill/eviction state cycles
can overlap retirement stalls and other events. Do not add them into a CPI stack.

Short DDR and RV64GC context/negative controls reuse each board model. CPU guest
ticks/IPC are reported, never GSIM host speed. Synthetic AXI latency, one-iteration
CoreMark, short FPU smoke and bounded locality are not FPGA throughput, routed
Fmax, BRAM inference, power or Linux qualification.

## Evidence status

The emitted geometry/default tests and parameterized cache/DMA checks pass.
Matched CoreMark is complete: 486605→482513 guest ticks, **0.8409% fewer ticks**.
The ROI has 360528 retirees and the exact same ordered-PC digest/CRCs on both.
IPC is 0.740903→0.747187 (ROI cycles 486606→482514). D-cache ROI counters:

| Counter | 2 KiB | 4 KiB |
| --- | ---: | ---: |
| Accepted hits | 69711 | 69774 |
| Accepted misses | 63 | 5 |
| Read misses | 44 | 0 |
| Write misses | 19 | 5 |
| Dirty eviction/writeback lines | 48 | 1 |
| Miss-blocked cycles | 2644 | 206 |
| Refill-state cycles | 3409 | 287 |
| Eviction-state cycles | 2073 | 38 |

The counters overlap. Timing can change speculative traffic and which physical
requests cross the ROI boundaries even when the architectural PC stream matches.
The small overall gain means D-cache capacity is not the main remaining CoreMark
bottleneck. The preferred profile remains D-cache32/LSU2 regardless of locality results.
D-cache64 is optional only, and D-cache64+MLP4 has not been tested. Locality
results and their independent backing-memory checks pass.

A supplemental full-directory fixture fills all 32/64 lines with exactly eight
backing reads per line and zero evictions/writes, then checks dirty DMA probing of
the highest directory slot 31/63, invalidation/reload, dirty replacement and
reacquisition. Both capacities pass all three seeds and reject a bad byte oracle.
An initial test-wrapper-only UBSan failure (renaming C++ main removes its implicit
return special case) was fixed with an explicit return; the original fixture was
not changed.

The first positive locality run completed all 32 regions and eight continuous
completion totals in 5930650 guest cycles. Its optional full-sweep negative hit
the old 120-second helper watchdog. The completed positive results and models are
preserved; a bounded first-cold-ROI negative replaces that unnecessarily repeated
full sweep. Continuation permits only that exact failure, verifies all baseline
artifacts, keeps the final BIN unchanged and checks exact phase order. Its new
positive guard is 10 million guest cycles / 8192 UART bytes (900 seconds unchanged);
the short negative is 2 million cycles / 2048 bytes / 120 seconds. No completed positive
workload or hardware build is repeated. The final receipt records the original
failure and the authorized pre-locality firmware/source epoch explicitly.


## Locality results and conclusion

The same final BIN (`ddr_bench.bin`, 4765 bytes) ran on both models. Positive runs
completed in 5930650 / 5863701 total guest cycles, including UART, initialization
and verification; these whole-run totals are **not** kernel speed claims.

| Data per buffer | Warm read, 3 sweeps: 2K→4K ticks | Warm chase: 2K→4K ticks | Complete write+flush: 2K→4K ticks | Complete copy+flush: 2K→4K ticks |
| --- | ---: | ---: | ---: | ---: |
| 1 KiB | 1422→1422 | 436→436 | 2624→2658 | 4414→4398 |
| 2 KiB | 3101→2766 | 1012→868 | 4995→4859 | 19694→8192 |
| 4 KiB | 15986→5792 | 12167→1876 | 23722→9450 | 40275→38833 |
| 8 KiB | 31778→31778 | 24262→24263 | 46943→47081 | 80085→80163 |

Copy includes two buffers, so the 2 KiB row has a 4 KiB data footprint. Stack and
bookkeeping can cause boundary-set conflicts even when the named data fits.
Complete write/copy intervals run continuously from kernel start through flush
completion, including bookkeeping between the separately reported sub-windows.
They are not sums of disjoint timers. At 4 KiB, warm-read misses fall 193→5 and
warm-chase misses 192→2; complete write cost drops 60.16%. The 2 KiB-per-buffer
copy complete cost drops 58.40%. At 8 KiB, both caches still miss on repeated
sweeps; complete write/copy regress slightly (0.294% / 0.097%). At 1 KiB, complete
write regresses 1.296% because the larger cache adds flush overhead. Larger flush
costs are retained in the comparison, not omitted from the apparent kernel gain.

The unchanged short DDR BIN also passes both models: read 5684→5593,
write+flush 8112→5665, copy+flush 13744→13725 and chase 4012→3926 ticks.
RV64GC context/ISA controls and their deliberate corruption negatives pass on
both models. None of the printed firmware-derived MiB/s figures are FPGA rates.

Conclusion: D-cache capacity is a real bottleneck for a repeatedly reused data
footprint near 4 KiB, but it is a small remaining factor for this CoreMark workload.
**Keep the preferred D-cache32 / LSU2 configuration; retain D-cache64 as an opt-in
experiment. Do not stack it with the unselected MLP4 profile.** No larger cache,
new workload, synthesis, physical implementation or board test was run.


## Final evidence and replay lineage

- Final accepted receipt: `build/gsim/data-cache-final-20261007/receipt.json`
  (`PASS_MATCHED_DCACHE_CAPACITY`).
- Cache/real-DMA checks: `build/gsim/data-cache-checks-20261007-r2/receipt.json`.
- Full-directory boundary: `build/gsim/data-cache-directory-boundary-20261007-r2/receipt.json`.
- Initial board collection: `build/gsim/data-cache-board-20261007/receipt.json`.
  Its source-epoch flag and full-sweep-negative timeout are preserved, not relabeled
  as a pass. `data_cache_continue.py` admits only that exact failure and the two
  documented pre-locality source refinements, then reuses completed positive
  artifacts and performs the bounded continuation. The final receipt records this
  lineage, frozen firmware, all actual driver/header inputs and normalized FIR
  comparison. No failing functional result is waived.

The final source contains the archival initial collector and the verified bounded
continuation separately. The initial collector's full-sweep negative is known to
exceed its old helper watchdog; use the documented continuation for these saved
artifacts rather than repeating completed workloads or increasing timeouts.

The preferred managed export pins both cache arguments explicitly:

```sh
mill -i IonSoC.test.runMain ooo.ManagedBoardSocMain \
  build/managed-preferred-fresh 100000000 staged-fetch-turnover 460800 \
  rv64gc 50000000 50000000 250000000 2147483648 32 32
```

This is configuration guidance only; no production export/implementation is
claimed by these GSIM measurements. D-cache64 remains optional and requires its
own fresh physical signoff before any board use.
