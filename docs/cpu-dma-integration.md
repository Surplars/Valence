# CPU ingress and coherent DMA integration

This source checkpoint composes two independently qualified, default-off
experiments. It does not select new release defaults or establish physical
FPGA timing, mapped resources, MAC/CDC behavior, or board bandwidth.

## Source lineage

- CPU standalone: `2835556917ac5c175619e94647bbd830544d81f7`, tree
  `3b34bf27bafcad58874700a2c9b726fb46221cac`.
- DMA overlap standalone: `d39d80fe6aeff2306dfa826c1c6adfc4c4a75210`, tree
  `4b2ae178e30d8ba3fd08a435c3f436bc451338b2`.
- Published DMA phase-one parent: `02e8ea249b900dafe8de9b52cdf55bf4a6dcefcb`,
  tree `096dff7e95fa6ca1d1a4bad95cfd2e9e3fa3019d`. The local same-tree parent is
  `bf52a3461e32d8c49eefd71c318a4462440c54ad`; this integration starts from the
  full DMA overlap history, including its prototype, rather than just its last
  documentation/qualification commit.

Shared configuration and exporters retain both flag families. The CPU adapter
and CPU parameter implementation are byte-identical to the standalone CPU
freeze. DMA-only production implementations are byte-identical to its freeze.
The integration adds configuration checks and independently bounded runtime
fixtures, not another production optimization.

## Explicit experiment matrix

The paired CPU models use the same selected geometry, DMA line support,
four line owners, and zero pacing. Only `physicalLoadIngressFlow` differs:

| Profile | Physical ingress | Line DMA | Owners | Yield | Virtual precheck / checked flow |
| --- | --- | --- | --- | --- | --- |
| Inherited selected default | off | off | 1 | 0 | off / off |
| Combined reference | off | on | 4 | 0 | off / off |
| Combined candidate | on | on | 4 | 0 | off / off |

Both models retain two LSU owners, 32 KiB two-way instruction/data caches,
two data read MSHRs, two response entries, two writeback entries, the 2 GiB RAM
aperture, four DDR slots and two DDR write slots. The 100 MHz clock value only
converts measured simulation cycles; it is not an implementation timing result.
`--prechecked-data-flow` remains a separate experiment that also requires
`--virtual-ram-load-precheck`.

`MemoryCopyDma` is always instantiated in the executed-board wrapper and can
be controlled by real guest MMIO instructions. The wrapper does not instantiate
Ethernet packet DMA, native MAC, or clock-domain crossings. Its concurrent copy
fixture must therefore be described as executed CPU plus coherent memory-copy
DMA, never as executed CPU plus Ethernet packet traffic.

## Required integrated checks

1. Focused Scala checks retain baseline dimensions/defaults and reject illegal
   CPU precheck or DMA owner/yield combinations.
2. Fresh selected OFF/ON board models and the RV64GC smoke/negative control.
3. Source-built identical hot read/write/copy guests with exact full-token,
   checked-payload, speculative-guard and independent data/backing oracles.
   DMA is configured but idle in this measurement; it isolates CPU ingress cost.
4. A real guest starts memory-copy DMA after dirtying source and destination,
   continues independent CPU memory work during DMA activity, then reload-checks
   the coherent result. Passive ownership/AXI observations and a separate host
   byte oracle must establish actual overlap and data visibility.
5. Portable NEMU hot replay checks each retired guest PC, all 32 GPRs after each
   complete retirement edge, and full final RAM. DMA is configured but idle in
   this independent architectural comparison.
6. Representative cold/over-capacity streams, dependent pointer chase, Sv39,
   fetch PMP, MMIO and atomic cases replay against the same source/config pair.
7. Precise data-PMP/MPRV fixture against the exact same model pair, plus negative
   controls. Native selected exports retain real managed peripherals and are
   separate from the executed single-clock simulation scope.

Results and source/configuration hashes belong in fresh integration receipts.
An earlier standalone receipt is not automatically an integrated pass.

## Standalone evidence and replay boundaries

The immutable CPU evidence archive is `cpu-bandwidth-evidence-20261009.tar.gz`,
SHA-256 `4297893fc8ecf3a2de4315e022d1d11d84ea65b4968d14e0476481ffe60d4aa8`.
Its index SHA-256 is
`29a96d9e77e3e27465446959daeea0d08160fc615cc0607d7d034ad7945261c8`.
The archive preserves source recipes, guest artifacts, independent reviews,
receipts and logs; it excludes tool/reference binaries and compiled model
objects. Original absolute paths record historical provenance and do not make
those receipts portable executable tests.

The fresh hot replay path in [cpu-bandwidth-flow-results.md](cpu-bandwidth-flow-results.md)
builds its tracked guest sources and models. Historical standalone NEMU,
representative, held-context extension, and native comparison runners remain
archive-dependent unless separately promoted with an explicit portable entry
point. Their source scripts are preserved in the evidence archive. Reproducing
the fresh hot replay alone does not reproduce those additional historical gates.

## Integrated measured checkpoints

The fresh hot A/B with shared DMA depth4/yield0 configured but idle reproduces
all twelve standalone `HOT_RESULT` records exactly, including completion/flush
cost and speculative traffic. For 8 KiB buffers, read takes 12,339 → 10,313 kernel
cycles (253.262 → 303.016 MiB/s at the fixed 100 MHz conversion), copy takes
31,252 → 28,689, and write remains 19,529. ON reads include four extra canceled
guard loads (32 physical bytes), retained in raw traffic and elapsed time.

The portable data-PMP/MPRV gate passes both sides with six checker negatives:
1,992 / 1,989 cycles, the same 108 retired instructions and PC trace, and zero
forbidden physical requests. The first portable runner attempt failed before
hardware execution because resolving the `clang++` symlink changed its driver
name to `clang`; the failed receipt is retained. The fix preserves the invocation
name while separately hashing the resolved binary and has a symlink regression.

The [executed CPU/copy-DMA fixture](../simulator/gsim/fixtures/cpu_dma_execute/README.md)
passes both sides and eight checker negatives. Each side completes two dirty
4 KiB generations, a real cold AXI read error with full owner drain, and successful
restart. Both observe four resident DMA slots and independently check 1,024
dirty-source plus 1,024 dirty-destination accepted C beats. ON exercises 4,292
physical ingress passes. This is a functional integration result: OFF/ON total
cycles are 56,098 / 56,021, but polling, retired instructions and speculative
physical loads differ (4,161 / 4,293 checked physical loads). Those differences
remain counted, so this fixture is not presented as a fixed-work throughput A/B.

Three full native exports pass: inherited selected default, combined candidate,
and the separately gated virtual-prechecked + physical + DMA candidate. Ten fixed
selected storage groups remain identical. As a literal per-module-definition
proxy, adapter register declarations remain 184 bits; MemoryCopyDma changes
288 → 2,464, MixedCoherentLineHome 3,566 → 4,345, AtomicMemory 338 → 344,
TileLinkLineFillEngine 2,336 → 2,343, and TileLinkLineWriteEngine 2,966 → 2,977.
The line-write queue payload helper gains two total array bits. These are neither
hierarchy-weighted instance totals nor mapped FPGA resources. The checked export
also adds the full virtual-precheck option, so its delta is not attributed only
to the FIFO bypass. No timing or 100 MHz physical implementation is established.

The integrated representative replay passes ten positives and ten explicit
negatives (plus the four inline backing-oracle corruptions). Every recorded metric
map matches the standalone proof exactly. The 64 KiB three-pass read is
279,718 → 268,971 cycles; copy is 641,791 → 627,214; write stays 344,151 with an
unchanged 17,754-cycle flush tail. Dependent 3,072-hop chase is
231,188 → 227,973; independent-line traversal is 114,346 → 112,706. Sv39
warm/cold/chase remains 4,422 / 512 / 2,311, with identical signature, retired-PC
trace, page-fault provenance and one permitted UART LSR read. The Sv39 case still
has zero outstanding-cancellation cycles, so no new cancellation witness is claimed.
Fetch-PMP revoke/restore and RV64GC atomic smoke also pass. DMA is idle in this
representative suite; concurrent traffic is covered by the separate copy fixture.

The fresh integrated NEMU replay also passes all twelve cases and six PC/GPR/RAM
corruption negatives. It checks 123,444 retired guest PCs and all 32 GPRs after
81,294 full retirement edges (including 42,150 dual-retire edges), for 2,602,560
GPR value comparisons including the independently specified ROM prefix. Each case
compares all 4,194,368 final RAM bytes. There are zero reference resynchronizations
and zero speculative requests stepped into NEMU. Every hot result exactly matches
the non-NEMU replay. This covers integer physical M-mode guests with DMA configured
but idle; it does not claim concurrent-DMA NEMU or CSR/FP/VM ISA compliance.

These checkpoints qualify an explicit source/configuration integration candidate.
Release defaults remain unchanged; mapped resources, routed timing and real-board
promotion are outstanding gates.
