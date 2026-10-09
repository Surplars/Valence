# Integrated coherent memory-copy DMA fixture

This is a source-bound GSIM fixture, not a CPU instruction benchmark, board run,
physical DDR model, or timing/resource result. It uses the real MemoryCopyDma,
DmaRegisterDataAdapter, AtomicDataMemory, DataRequestBuffer,
NonBlockingCoherentLineCache, MixedCoherentLineHome, OrderedTileLinkBridge,
line-transfer arbiter, and TileLinkAxi4Bridge. It does not synthesize a fake cache
or coherence responder.

## Fixed topology and independent model

- Selected aperture: base `0x80200000`, 2 GiB; valid high line `0x1001fffc0`.
- Cache: 512 lines / 32 KiB, two ways, two read MSHRs, two response credits,
  two writeback credits, compact banked tags. Prefetch is disabled: no executing
  CPU/PMP predictor context is represented by this request-port test.
- DDR bridge: four total slots, two write slots, at most sixteen AXI beats;
  a full 64-byte DMA line is eight 64-bit beats.
- Independent host model: separate byte arrays for the first 1 MiB and final
  4 KiB, with a rejected gap between them. High addresses cannot alias low memory.
  Four read and two write credits; 32-cycle first read latency; 40-cycle B delay
  plus the same ID-dependent 3/17-cycle offset for all compared modes. AR, AW,
  and W stalls repeat with periods 7, 11, and 5. R and B can select newer owners.
- CPU expected bytes and DMA source snapshots come from a separate architectural
  byte oracle. Every completed copy and final coherent cache/home drain are
  checked against that oracle. The AXI model checks address range/alignment,
  4 KiB burst boundaries, live IDs, beat counts, WLAST, and response ownership.

## Measurement definitions

Cycles run at an assumed 100 MHz. Decimal MB/s and binary MiB/s are both printed.
Descriptor programming happens before the measured interval. DMA rows start at
the START control offer and end at observed IRQ; final destination B and its
completion tail are recorded separately. CPU and bus counters use that same
interval, excluding subsequent status reads, clear, verification, and flush.

The CPU driver permits one outstanding request in performance rows, offers the
next request on a 32-cycle grid, and periodically stalls response ready. Reads
consume one 8-byte word, stores update four selected bytes, and copy pairs read
8 bytes then write those 8 bytes to a separate region. These are synthetic
CPU DataPort patterns, not LSU instruction streams or a software memcpy loop.
Each read/store address is used twice before advancing one cache line. Copy
pairs advance one line per pair. Cache-line DDR traffic is reported separately
from useful CPU bytes.

CPU latency percentiles measure accepted request to returned response; the worst
VALID-to-READY offer wait is a separate counter. Continuous-load rows count useful
CPU bytes completed while DMA is active. Their CPU work count differs when DMA
finishes earlier, so they are supplemented by:

- CPU-only references with exactly 256 completed requests.
- Combined rows with a fixed DMA payload and exactly 256 CPU requests (128 copy
  pairs), recording CPU finish, DMA finish, and time until both finish.
- Balanced-work combined rows where useful CPU bytes equal the DMA payload:
  read requests = payload/8, masked-store requests = payload/4, and copy
  requests = payload/4 (half reads and half writes). Each remains bounded.

The first combined endpoint means CPU DataPort completion plus DMA's final B/IRQ;
dirty CPU stores may still be cache-owned there. A second full_makespan_cycles
endpoint includes completion-control cycles, the final coherent cache/home flush,
and all AXI responses drained. Flush tail and extra AXI bytes are recorded
separately. Use this second endpoint for fully completed memory-work comparisons.

## Correctness gates

The directed suite covers clean/dirty source and destination, partial CPU masks,
CPU read/write/copy contention, two simultaneous real cache/home refills before
DMA, LR-to-DMA-to-SC invalidation, AMO read/write-gap exclusion, busy descriptor
and control rejection, delayed final B, denied final R/B plus restart, scalar
prefix/tail fallback, differing source/destination line offsets, 4 KiB crossings,
exact high-aperture copies above 4 GiB, overflow/MMIO/overlap rejection, and a
visible unaccepted line request while the home is held in drain. FENCE completion
must not wait for that unaccepted offer; releasing drain lets the copy finish.

Three host-side negative controls corrupt a write byte, drop a write, or invoke
the completion checker before final B. They validate independent checker
sensitivity, not RTL fault mutation coverage. Separate isolated RTL mutations
must be reported independently. The existing fatal behavior for failed dirty
probe writeback is unchanged; clean direct DMA R/B error tests do not cover it.
No packet-DMA fast path or STOP ABI is introduced or inferred by this fixture.

## Reproduction

Reuse the already installed, verified GSIM/cloud cache. Do not install tools.
From the candidate checkout:

```sh
export VALENCE_CLOUD_ENV=/absolute/path/to/existing/verified/cloud-env
export VALENCE_GSIM_SOURCE=/absolute/path/to/existing/verified/gsim-src
source scripts/cloud/env.sh
python3 simulator/gsim/prepare_dma_coherent_baseline.py \
  --revision 8e78b5b3252311d19d728d815cf32ad3ec5cedb2 \
  --output build/new-exact-baseline
(cd build/new-exact-baseline && python3 simulator/gsim/dma_coherent_line.py --tag baseline)
python3 simulator/gsim/dma_coherent_line.py --tag candidate --line
python3 simulator/gsim/dma_coherent_line.py --tag candidate-disabled
python3 simulator/gsim/dma_coherent_line.py --tag yield4 --line --line-yield-cycles 4
python3 simulator/gsim/dma_coherent_line.py --tag yield16 --line --line-yield-cycles 16
```

The public baseline is `8e78b5b3252311d19d728d815cf32ad3ec5cedb2`, whose exact
source tree is `c82f46861725be23b8c4f68630e341b72281c05c`. The helper verifies
that tree before extracting it. Historical local measurements used `e8520ab`,
which has the same tree; fresh public replays must not rely on that local commit.
Use a previously provisioned tool cache, or follow the repository setup process
separately; these commands do not install tools.

Use fresh tags for changed RTL. `--reuse` requires identical source hashes.
`--rebuild-driver` checks DUT/wrapper hashes and generated FIR/C++/header hashes
before recompiling only the independent C++ driver. Both retain ASan/UBSan.
Runtime binary options `--one-line` and `--protocol-only` support focused isolated
RTL mutation checks. `--smoke` runs the short 512-byte case. The runner writes
source hashes, per-case metrics, negative-control results, and artifact hashes
to `receipt.json`.
