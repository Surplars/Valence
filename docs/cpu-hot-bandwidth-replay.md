# Frozen-model CPU hot-bandwidth replay

Completed 2026-10-09. This is a six-case, physical-address, integer M-mode GSIM
replay at a **nominal 100 MHz conversion**. It is not a physical-board measurement,
routed-frequency result, or qualification of the current hardware source tree.

## Result

Each case warms both bounded buffers by cache line, runs the **same assembly
kernel once untimed**, and then runs four timed passes. The cache-data read/write
miss counts are zero during every kernel and drain window. A copy's useful payload
counts each copied byte once; its logical read-plus-write traffic is twice that.

| Case | Kernel cycles | Drain | Flush | Complete cycles | Kernel payload MiB/s | Complete payload MiB/s |
|---|---:|---:|---:|---:|---:|---:|
| Read, 4 KiB | 6,195 | 3 | 584 | 6,782 | 252.220 | 230.389 |
| Write, 4 KiB | 9,801 | 3 | 2,722 | 12,526 | 159.423 | 124.741 |
| Copy, 4 KiB | 15,636 | 3 | 2,671 | 18,310 | 99.9296 | 85.3359 |
| Read, 8 KiB | 12,339 | 3 | 584 | 12,926 | 253.262 | 241.761 |
| Write, 8 KiB | 19,529 | 3 | 4,860 | 24,392 | 160.018 | 128.116 |
| Copy, 8 KiB | 31,252 | 3 | 4,808 | 36,063 | 99.9936 | 86.6539 |

Timed payload is 16 KiB or 32 KiB. The largest simultaneous warmup/timed-copy data
footprint is 16 KiB, within the selected 32 KiB two-way D-cache. Completion includes
the explicit drain and flush markers, before the separately checked architectural
signature. Shared-fabric AXI read bursts are not the D-cache-miss oracle; instruction
fetch traffic can occur while the data accesses remain all hits.

## Attribution from actual full-token lifetimes

### Read supply

- Every timed load in read and copy has **six cycles from accepted CPU start to
  result**, with no tail distribution: FIFO enqueue on the start edge, physical
  acceptance three cycles later, physical reply one later, LSU reply one later,
  and registered result one later.
- For the 8 KiB read, 4,096 loads use both LSU owners. Start gaps are 1 cycle
  2,044 times and 5 cycles 2,044 times; the seven remaining gaps are loop/marker
  overhead. Mean start gap is 3.00635 cycles.
- Same-cycle full-slot completion/replacement is directly witnessed 4,084 times
  (2,036 in the 4 KiB read). The result edge is reusable, so there is no additional
  mandatory seventh residency cycle.
- Two owners with six-cycle residency give an owner-supply bound of
  `2 * 8 / 6` bytes/cycle, or **254.313 MiB/s** at 100 MHz. Measured read throughput
  approaches that bound: 252.220 and 253.262 MiB/s. This is a bound for this
  microarchitecture and workload, not a universal 100 MHz CPU limit.
- Physical service is one cycle, physical pending peak is one, FIFO backpressure
  is zero, and there are no timed data misses. The measured bottleneck is upstream
  load ownership/supply; a faster DDR response would not remove this all-hit bound.

### Store supply

- Timed stores have start→local LSU acknowledgement = 1 cycle, start→result = 2,
  FIFO→physical acceptance = 3, and FIFO→physical reply = 4.
- LSU live peak and StoreBuffer allocated peak are both one. The source-receipt-
  proved StoreBuffer depth is **two**, and full cycles are **zero**. Increasing
  StoreBuffer depth alone is not supported as the remedy for this kernel.
- At 8 KiB, CPU start gaps are `4:3577, 5:7, 10:508, 21:3`. This is approximately
  four cycles per store within an eight-store group, plus preparation/control
  overhead between groups; mean gap is 4.75849 cycles.
- The full-token head categories separately count 4,096 preparation/selection
  cycles, 4,096 launch cycles, and 4,096 local-response acceptance cycles. Combined
  with exact-head store issue in the model-source backend, the evidence points to
  serialized store preparation/issue/retirement and loop overhead. It does not
  establish a complete single-cause counterfactual or a measured optimization gain.
- No timed dirty writeback occurs. The explicit flush adds 2,722/4,860 cycles,
  which is why complete throughput is lower than the kernel-only figure.

### Copy

- The load leg retains the same six-cycle owner residency and the store leg the
  same two-cycle local completion. All 8,192 physical requests of the 8 KiB copy
  receive one-cycle hit service.
- The 8 KiB copy's mutually exclusive head categories include 6,068
  `queued_memory_no_available_slot`, 5,646 `queued_memory_serial_exclusion`,
  4,096 preparation/selection, and 4,096 launch cycles. These are head-state
  attribution categories, not additive independently removable penalties.
- Useful-copy throughput is about 100 MiB/s, while logical read+write bandwidth
  is about 200 MiB/s. The shared-port traffic and serial store ordering mean the
  read-only owner bound cannot be applied directly to useful-copy bytes.

## Correctness and sensitivity

The observer does not inject testbench memory requests. It observes the CPU's
actual instruction retirement, complete generation-tag/index tokens, queue
ownership, and accepted DataPort transactions.

All cases check exact timed architectural LD/SD counts; per-address physical
read/write order; write data, masks and class; read reply data against independently
initialized backing memory; unchanged source backing; final destination backing;
and the four-word architectural signature. Accepted physical counts equal the
architectural counts in every case. The end marker requires all data-path owners
to be drained. Stage conservation and full-token ordering are checked every cycle.

The frozen ledger explicitly handles the existing identity-path translated-queue
bypass. It does not infer missing owners from queue-count differences. The actual
two-entry StoreBuffer geometry is verified against the historical BoardSocTop
source hash from the selected model's input receipt.

The six cases perform 52 negative oracle checks in total: read address/mask/count,
write address/data/mask/count, read reply data, both backing buffers, and signature
as applicable. These mutate host-side evidence or expected memory temporarily;
they demonstrate oracle sensitivity, **not DUT fault injection**. The frozen probe
ABI covers address/data and the ordinary request class/mask fields used by these
precheck-disabled, physical M-mode cases. It does not certify every newer
precheck/prefetch authorization field or unexercised VM/fault/reset behavior.

## Model and recovery provenance

Selected checkpoint:
`../Valence-fpga-next/build/gsim/fpga-next-board-selected-address-r1`

- Model receipt git head: `54bcc7508a0f0dd05fd6004d96f4f6649fb4da0b`
- Comparison baseline: `e8520ab23fb31cd03566787056d5e937e1aca7c3`
- Model receipt SHA-256:
  `308e65ba6c5edc51b5f540b53bc0534dd37e4f1a3eee56655b3eb4bc7516b7f2`
- Model header SHA-256:
  `cbf4fafdd0807a6562e007754d52a03dd4f93134a763a7cbc14f260438471aaf`
- Reused model object SHA-256:
  `e8e2343b44e8a938407bef466565f4827c5e78ffb3d464ab9cf1e8550bc4bd5e`

The checkpoint's recorded source inputs differ from e8520ab in 12 files:
BoardSocTop, CoherentCacheConcurrency, FpgaNextConfig, FpgaNextSocTop,
MachinePlatform, NonBlockingCoherentLineCache, BoardSocGsimMain,
CoherentCacheHomeGsim, DataPrefetchConfigSpec, FpgaNextBoardGsimMain,
FpgaNextConfigSpec, and FpgaNextMain. The baseline additionally contains
BscanRamTransport, JtagRamLoader, JtagBootGsimMain, JtagDmaLaneGsim, and
JtagRamLoaderSpec. Exact paths and both hashes remain in the receipt and
`summary.json`; source equivalence is not asserted.

The interrupted `build/gsim/cpu-hot-bandwidth-r2/receipt.json` remains **unchanged**,
including its historical `RUNNING` status and three completed 4 KiB cases. Recovery
hashes every original file before and after, validates all recorded command logs,
reparses historical results, and verifies source/model/artifact hashes. It writes
only a fresh sibling output directory.

- Original receipt SHA-256:
  `1683ac2920fe98a3f78633a1d6ea661f4225670b14fa849961a4a633c5a36209`
- Final recovery receipt:
  `build/gsim/cpu-hot-bandwidth-r2-recovery-r1/receipt.json`
- Final recovery receipt SHA-256:
  `4f6332ffcbfdf2d51806acbb5930e5f636534cff6d6363fe5fd0c2cd3b629590`
- Machine-readable summaries in the same directory: `summary.json`, `summary.csv`
- Recovery qualification test output: `qualification-tests.log`, 12 tests passed

Recovery reused all three historical passes and the already-built 8 KiB read
executable. Only the two missing write/copy guest/observer pairs were compiled.
**No hardware model was generated or compiled.**

The 8 KiB read executable had a recorded successful historical compile command,
but the interrupted original runner had not yet written its artifact digest.
Recovery records its **first hash at recovery** explicitly, checks unchanged
source inputs, ELF symbols and extracted guest bytes, runs the independent
oracles, and verifies all prebuilt bytes remain unchanged. This is not a claim
that a pre-interruption binary hash existed. The two newly built cases have
ordinary completed-run artifact hashes and a separately bound child receipt.

## Verify or replay the historical archive

This section is archive-dependent. It needs the historical model receipt/object,
all six original/recovered guest and observer artifacts, logs, recorded Git
source revisions, and the matching frozen source snapshot. The archive is
identified by the receipt hashes above. Strict verification from a later edited
source tree may intentionally reject it; never rewrite an old source digest to
make it pass. The recovery unit tests also require that historical archive and
are not source-only tests.

For a new self-contained test, use the fresh source-only path in
`cpu-bandwidth-flow-results.md` instead. For an explicitly retained archive,
replace the example cache/model paths with verified locations and load its
matching source snapshot's existing toolchain:

```sh
export VALENCE_CLOUD_ENV=/path/to/verified/cloud-env
source scripts/cloud/env.sh
```

Verify the finished result without compiling or executing the model:

```sh
python3 simulator/gsim/cpu_hot_bandwidth_verify.py \
  --receipt build/gsim/cpu-hot-bandwidth-r2-recovery-r1/receipt.json
python3 simulator/gsim/test_cpu_hot_bandwidth_recover.py
```

The actual recovery command was:

```sh
GSIM_CXX=clang++-19 python3 simulator/gsim/cpu_hot_bandwidth_recover.py \
  --prior build/gsim/cpu-hot-bandwidth-r2 \
  --out build/gsim/cpu-hot-bandwidth-r2-recovery-r1
```

It refuses an existing output directory. To intentionally repeat recovery use a
new output name; the old original receipt is deliberately not advanced. For a
new six-case lightweight replay of that old model, also choose a fresh output directory:

```sh
GSIM_CXX=clang++-19 python3 simulator/gsim/cpu_hot_bandwidth.py \
  --model-root /path/to/verified/frozen-selected-models \
  --baseline 8e78b5b \
  --repetitions 4 --out build/gsim/cpu-hot-bandwidth-fresh-r1
```

Both historical routes require the existing toolchain and frozen model artifact.
The public baseline defaults to `8e78b5b` and pins source tree
`c82f46861725be23b8c4f68630e341b72281c05c`; an original local archive may explicitly
select same-tree `e8520ab` when that private historical revision is available. Neither
installs tools or invokes Verilator, Vivado, board access, Linux, or a full suite.

## Candidate observer extension review

The future physical-load ingress shortcut must use a new observer/model receipt;
the frozen hot harness and old probe ABI remain unchanged. Static review of the
separate `cpu_flow_bandwidth.h/.cpp` confirms that routing the accepted bus token
directly to checked, while still appending the StoreBuffer response owner, is the
right ownership change. It needs explicit raw-event and authorization coverage:

1. Independently predict the route from enabled configuration, accepted virtual
   input, empty pre-edge ingress/translated queues, no waiting translation,
   available checked capacity, ordinary aligned cached RAM read, and no precheck.
   Do not infer it merely from a missing incoming event or the DUT bypass bit.
2. Compare the prediction with raw physical-ingress-pass, virtual-enqueue and
   checked-enqueue events. Assert accepted virtual requests partition exactly
   into virtual queue enqueue or ingress pass; checked enqueue must have exactly
   one owner route. Keep the checked register and non-pipe capacity semantics.
3. Conservation becomes:
   `virtual accepted = incoming dequeues + ingress passes + reset drops + pending ingress`,
   `checked enqueues = translated pops + identity passes + ingress passes`, and
   `checked enqueues = checked pops + reset drops + pending checked`.
   Keep all existing StoreBuffer, physical, return and full-token conservation.
4. Full request metadata is **53 bits**: the old 19-bit class/mask field,
   precheckedLoad, 32-bit translationEpoch, and prefetchNextAllowed. With the old
   layout preserved, use prechecked bit 19, epoch bits 20..51, and hint bit 52.
   DataRequest has no separate VA field; upstream VA/token/size certificate
   matching belongs to the dedicated preparation proof.
5. Preserve original and stage request fingerprints separately. The checked
   boundary may overwrite only the captured next-line hint; the physical boundary
   deliberately clears precheckedLoad and translationEpoch. Check those exact
   transformations. Do not globally discard the authorization fields. Next-line
   permission itself needs the independent adapter/PMP proof.
6. The bounded M-mode fixture should assert precheck/epoch inactivity rather than
   silently assuming it. Add negative route/event/metadata/full-token mutations
   for the new observer paths, spill under checked backpressure, retained owner
   order, simultaneous pop/push, and reset/cancel behavior in the dedicated proof.
7. Reject unknown third arguments in the new C++ runner. Its initial version
   silently treats a misspelled mutation switch as a normal successful replay.

These are static review findings, not a claim that the new candidate was run or
that its timing is qualified by this frozen-model result.
