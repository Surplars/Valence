# Coherent line-DMA qualification, 2026-10-09

## Selected next profile

Select `fpga-next-selected-v2-dma-lines-yield16` for the next shared-work candidate. It enables line DMA with a 16-cycle quiet interval after each completed line read or write. `FpgaNextConfig.Selected` remains the published scalar reference; zero-yield line mode remains the explicit maximum isolated-throughput option. The selected next profile is also recorded in `fpga/next/dma-line-candidate.json`.

Production full-SoC RTL exports passed for both line profiles. Functional gates include real cache/home/atomic/AXI plus real packet-DMA STOP coexistence. Mapped area, routed setup/hold, Fmax and a new board run remain unverified. This is a concrete next candidate, not a physical release.

## Isolated DMA payload, 100 MHz delayed-DDR model

Each destination byte is counted once; reads and writes are not added as copy payload.

| Payload | Scalar MiB/s | Line yield0 MiB/s | Selected yield16 MiB/s |
|---|---:|---:|---:|
| 512 B | 11.290 | 48.926 | 39.730 |
| 4096 B | 11.301 | 49.203 | 39.401 |
| 131072 B | 11.303 | 49.228 | 39.361 |

For 128 KiB, scalar issues 16,384 AR and 16,384 AW; line mode issues 2,048 of each, with exactly the same 131,072 accepted R bytes and 131,072 W bytes. DMA line ownership peaks at one; this gain does not come from extra DDR credits. Completion is observed only after actual final B: tail is four cycles scalar and five cycles line mode.

## Balanced CPU-port + DMA work, fully completed

Useful CPU bytes equal DMA payload. The endpoint includes both fixed work streams, completion-control handling, CPU dirty-cache flush and all DDR replies. Total AXI R/W bytes match for every pair. These are synthetic CPU DataPort request patterns through a real cache, not executed LSU instructions or a contiguous software memcpy.

| DMA / CPU pattern | Scalar full cycles | Selected full cycles | Speedup | CPU p95 old→new | p99 old→new | max old→new |
|---|---:|---:|---:|---:|---:|---:|
| 4096 B / read | 58209 | 39704 | 1.466× | 194→167 | 203→202 | 285→204 |
| 131072 B / read | 1675533 | 1059980 | 1.581× | 106→91 | 109→97 | 122→103 |
| 4096 B / masked write | 97494 | 94492 | 1.032× | 126→161 | 194→201 | 285→204 |
| 131072 B / masked write | 2339162 | 2120999 | 1.103× | 91→83 | 92→84 | 122→103 |
| 4096 B / copy | 123014 | 125127 | 0.983× | 122→199 | 125→212 | 206→213 |
| 131072 B / copy | 3582559 | 3282116 | 1.092× | 123→113 | 124→134 | 126→144 |

At 100 MHz, one cycle is 0.01 μs. The remaining dirty 4 KiB copy cost is about 1.7% more total time and p99 125→212 cycles (1.25→2.12 μs). It is unchanged by yields 0/4/16; it is a measured tradeoff, not an automatic rejection. Large mixed workloads improve while small copy stays slightly slower. Yield16 reduces isolated DMA from 49.23 to 39.36 MiB/s but is the best tested mixed read/write setting. All CPU-only reference rows are identical.

The CPU workload has a 1024-line ring. Read repeats one 8-byte word twice per 64-byte line; masked stores update four bytes twice; copy reads/writes one 8-byte word perline pair to disjoint regions that deliberately conflict in cache sets. The performance driver has one outstanding CPU request and a 32-cycle offer grid. Two simultaneous real refill owners are checked separately in protocol tests. There is no claim of a formal starvation bound for arbitrary external backpressure; all bounded fairness/contention cases completed and report observed maxima.

## Verification and source closure

- Exact old-source baseline: `e8520ab23fb31cd03566787056d5e937e1aca7c3`, tree `c82f46861725be23b8c4f68630e341b72281c05c`.
- Four final modes (disabled, line0, line4, line16): each 17 DMA rows, 3 CPU-only rows, 12 combined rows, directed ownership/error/boundary tests and 3 host checker-sensitivity negatives.
- New-source disabled mode reproduces every old-source timing/byte/protocol metric exactly. Zero-yield after adding pacing exactly reproduces the earlier line candidate.
- Selected full 2 GiB RAM aperture and compact banked tags; valid physical accesses above 4 GiB; high boundary, overflow, MMIO and overlap rejection.
- Dirty/clean source+destination, partial CPU masks, two real refills, LR→DMA→SC, AMO read/write gap, busy control rejection, held line during home drain, final-B delay, direct R/B error and restart.
- Three actual RTL mutations rejected by independent host invariants: missing reservation invalidation, early completion, missing probe. A fourth atomic-admission mutation is caught by the preserved DUT ownership assertion. These are distinct from host checker mutations.
- Real packet DMA remains scalar. At line0 and line16, four STOP/drain/restart scenarios and three negative controls pass with ASan/UBSan. Accepted late read/RX B and unaccepted held request are separate cases. Ownership epochs are software bookkeeping, not invented hardware generation tags.
- Fifteen focused Scala tests and existing default-off AtomicMemory randomized/zero-latency/latency12 checks pass.
- Full production `FpgaNextSocTop` exports pass for bulk0 and shared16; no implementation or bit generation was run.

All positive final receipts, source inventories, FIR/generated-model hashes, raw logs, negative controls, comparison CSV/JSON and RTL-export receipts are preserved in the external `Valence-dma-qualified-20261009.tar.gz` evidence package. The source-only tree intentionally omits these generated `build/` outputs and raw logs. Earlier fixture/setup expectation failures are retained separately and are not labelled successful original launcher runs.

## State budget and remaining gates

Matched CHIRRTL: line0 adds 1,034 scalar state bits, of which 1,024 are two 64-byte payload registers and 10 are control/state bits. Yield4/16 adds 3/5 further counter bits. Existing vector/bundle register types and memory declarations/port counts match; no RAM/port/credit/cache-capacity expansion is requested. These are IR declarations, not mapped LUT/FF/BRAM counts. Existing dirty probe/release writeback denial remains fail-stop; direct DMA error tests do not establish graceful recovery for that separate failure.

The user-confirmed 9fceb61 board baseline is memory DMA 131,072 B / 515,418 ticks at 100 MHz ≈ 24.252 MiB/s. The same-model speedup is not a promise of that factor on the board. Native PPA/CDC/board validation remains a separate gate.

## Continuing toward sustained bandwidth

This freeze is the first qualified batching step, not the bandwidth endpoint. Further work belongs in a separate clone: split read/write line ownership latency, measure low-latency/component ablations and required outstanding credits, then evaluate multiple safely owned lines rather than removing coherence or atomic exclusion. The 64-bit 100 MHz one-way interface ceiling is 762.94 MiB/s. Scalar CPU copy has at least one read and one write on its shared request port; burst DMA has different control/data overhead. Those ceilings are not attained performance predictions.
