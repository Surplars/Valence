# Independent line-read ingress and whole-line return

Later follow-up: [snapshot/response handoff and full-way Home admission](memory-schedule-overlap.md).
Same two-issue/two-MSHR geometry; Sv39/Bare COPY incl. flush improves a further2.9340%/9.1163%.
Sv39 simultaneous R/W remains zero; default OFF and no new physical qualification.

Latest follow-up (2026-10-12): [internal Home-to-cache whole Grant and bounded
dual-origin prefetch](internal-line-grant-prefetch.md). This extends the earlier
memory-to-Home transport without widening public TL. Matched f1ef886 Sv39 COPY
incl. flush gains17.1343% with the same two MSHRs; four-arm results, preserved
regression and remaining bottlenecks are documented. Both options stay default OFF.

2026-10-11, `dev` at `c46359c3f35758465ca6e94d3fa5609747a1be30` plus
source-hashed local changes. Third coherent bandwidth batch, following
[write capture/send overlap](ddr-write-collection-flow.md) and
[line dispatch flow](line-transfer-dispatch-flow.md). Opt-in, default OFF;
the recommended FPGA/board profile is unchanged. No new STA or bit is claimed.

## Removed serialization

The old data-home transfer arbiter places an address-only Get behind an
eight-beat Put on TL A, although AXI AR and W are independent. Completed reads
then take another eight TL D beats to copy into a private line-fill buffer;
those beats also contend with write acknowledgements.

The new `LineReadMemoryPort` carries a tagged 64-byte request and a 512-bit
complete result. It connects the coherent data home to the **existing shared**
DDR owner scheduler, not to a second independent bridge. Writes and ordinary
scalar/other TL traffic keep the primary TL port. This interface is a local
memory transport, not a widened standard TileLink channel.

Related structural changes are qualified together:

- Independent read eligibility: a blocked primary write cannot prevent an
  eligible disjoint read from using a free shared slot.
- A primary write continuation and a new read owner can be accepted on the
  same edge. At most one new owner is allocated per cycle. A fair turn selects
  between eligible new owners without interleaving primary TL A messages.
- Independent primary D and whole-line response schedulers. A held read result
  does not lock the primary write-ack channel; unrelated results can progress.
- Each existing lane's payload storage is split into eight beat-interleaved
  banks. Its total `maxBurstBeats * 72` bits are unchanged: one 64-bit R beat is
  captured per cycle, and a completed line can leave as one 512-bit result.
  The 16-beat primary read/write path still supports both bank rows.
- The data home's duplicate private reader/payload RAM is not instantiated in
  this mode. InstructionLineCache's separate TL fill engine deliberately remains.

Target transport throughput is one accepted R and one accepted W beat per cycle,
with one whole-line result per cycle when complete owners are available. Request
and response backpressure remain explicit; this is not a zero-cycle DDR path.
Banked payload placement and wide result muxes still require physical evaluation.

## Preserved contracts and configuration

The paired geometry is unchanged: four DMA line owners, four shared AXI slots,
two write credits, max burst 16 beats, 64-bit AXI data, four-bit physical AXI IDs.
Both OFF and ON sides enable write-collection and dispatch flow. There is no
hidden second read pool, enlarged payload storage, shortened subordinate delay,
or early write acknowledgement.

Full physical address intervals, including the carry above 4 GiB, are checked
across **both** ingress classes. RAW/WAR/WAW wait for actual logical response
retirement. Tag/source namespaces are distinct, but all owners consume the same
capacity. Each AXI ID, interval and caller tag stays live until the relevant
accepted final primary D or whole-line response. RLAST alone does not free it.
AW and W retain matching owner FIFOs; B may reorder across IDs. All R beats are
captured before a result is offered, and a last-beat error zeros the whole line.
The coherent home still performs directory/probe/atomic/drain admission; the new
port is **not** a coherence or permission bypass.

`FpgaNextConfig.lineReadChannel` / `--line-read-channel` selects this path through
native and official GSIM assemblies. It requires a bounded mixed coherent home
and shared unordered ordinary-RAM DDR bridge. It is independently selectable
from the two earlier flags. At this third-batch checkpoint the FPGA configuration had 38 fields; historical
explicit configuration auditors keep all three experiments OFF.

The official GSIM assembly also now correctly forwards the previous batch's
`lineTransferDispatchFlow`. Its emitter had accepted the flag without passing it
to BoardSocGsim/BoardSocTop. The earlier DMA fixture did pass it and its measured
component evidence is unchanged. New native/official-GSIM elaboration checks
verify the actual data-home-to-manager bulk connection and absence of the
duplicate data-home reader. Elaboration is not executing-board qualification.

## Completed short acceptance

Receipt: `build/gsim/line-read-channel-local-20261011-r3/receipt.json`.
Status: `PASS_DUAL_INGRESS_AND_COHERENT_DMA`.
SHA256: `3239e0552a26dd4e24debc1dd06b10a69eeea62cdfb6a4919a9a5e48606f7606`.
All 503 frozen input hashes matched at that checkpoint. Three fresh models were
built: independent two-ingress boundary, real coherent-DMA OFF and ON. ASan/UBSan
were enabled. Each DMA model was reused for the necessary short protocol checks,
not for a full regression or Linux run.

The independent boundary oracle checks host-authored bytes, accepted commands,
AXI IDs and full caller tags, never DUT internal owner/payload state. It proves:

- Read admission during gapped write capture and held AW/W; a blocked write
  quota/head does not block an eligible read.
- Retained four-slot/two-write capacity, blocked fifth owner, retained tag reuse,
  distinct source namespaces and a held packet response with unrelated write
  acknowledgement progress.
- RAW/WAR retention, high physical addresses and rejected-window zero results,
  late R errors, 16-beat bank rows and all 256 partial-write masks.
- 192 mixed-ingress stress commands with reordered R/B and stable stalled
  address/data/results.

All 11 negative controls failed at their intended independent checks: five
boundary mutations (tag, bytes, RID, BID, early RLAST), and drop-write,
corrupt-write and early-ack on each DMA side. The real DMA/cache/atomic/home/AXI
checks additionally cover clean/dirty probes, late errors/restart, AMO/LRSC,
held responses, same-line opposite directions, tag reuse, fairness and drain.

The unified seven-suite Scala configuration/elaboration gate passed 35 tests;
logs and XML are in `build/gsim/line-read-channel-scala-local-20261011-r3/`.
Seven focused host CLI/default checks passed across the three flags.
`git diff --check` passed. The broader host CLI discovery was **not** all green:
23/24 passed, with an unrelated historical IntegerBackend text-equality anchor
already differing at remote HEAD. IntegerBackend was not changed or that check
weakened in this batch.

### Retained failures and corrected checks

Failed records are preserved, not overwritten:

- Scala r1 incorrectly forbade every TileLinkLineFillEngine in the whole SoC,
  including the unchanged instruction-cache reader. r2 scoped the data home but
  searched for individual request-field connections rather than the actual
  `connect manager.io.lineRead, coherentHome.io.lineRead` bulk connection.
  r3 checks the correct connection and data-home module and passes all 35 tests.
- GSIM r1 passed boundary and paired transport measurements but its old mixed
  held-response test demanded two downstream read retirements while the result
  was deliberately held. That assumed the removed private fill RAM. The new
  check witnesses independently accepted backing RLASTs and a retained packet
  offer, while preserving write-ack progress, stable payload/tag/error, no
  downstream retirement, and eventual independent byte/drain checks.
- GSIM r2 exposed a harness compile error: GSIM provides setters, not getters,
  for R input fields. r3 observes accepted RLAST through the existing independent
  host AXI transaction ledger before its owner is erased. No DUT timing, error,
  ownership or coherence check was relaxed to obtain the passing result.

## Matched results

Rates below are component-cycle measurements converted at an **assumed**
100 MHz, not physical board results. Accepted AXI bytes and AR/AW/B counts match
between every pair. OFF means only the new line-read channel is OFF; both prior
bandwidth changes are ON.

| DMA COPY payload | Unchanged service profile | OFF cycles | ON cycles | MiB/s OFF → ON | Throughput gain |
| --- | --- | ---: | ---: | ---: | ---: |
| 4 KiB | delayed 0 | 2,052 | 1,912 | 190.363 → 204.302 | 7.322% |
| 4 KiB | minimum-delay 1 | 815 | 542 | 479.294 → 720.710 | 50.369% |
| 128 KiB | delayed 0 | 62,812 | 58,291 | 199.007 → 214.441 | 7.756% |
| 128 KiB | minimum-delay 1 | 25,367 | 16,414 | 492.766 → 761.545 | 54.545% |

| 128 KiB accepted AXI beat duty, each R/W channel | OFF | ON |
| --- | ---: | ---: |
| Delayed 0 | 26.084% | 28.107% |
| Minimum-delay 1 | 64.588% | 99.817% |

At 64 bits and 100 MHz the one-way AXI ceiling is 800 MB/s = 762.939 MiB/s.
COPY can approach this payload rate because AXI R and W operate independently;
its logical read-plus-write rate counts both directions, not twice the payload
on either one channel. The old shared TL A/D COPY transport also has a 64/9-byte
per-cycle limit. The new port removes that transport ceiling: minimum-delay steady
streaming is within 0.183% of the 64-bit AXI one-way ceiling, including setup/tail.
This is not the physical DDR/MIG utilization and is not a CPU IPC/CoreMark gain.

Physical TL events and packet events are recorded separately. No fictitious TL
A or D beats are added to make the new interface resemble the old one.

## Remaining measured limits

For the 128 KiB delayed case:

- Mean read home→transport admission: 7.985 → 1.000 cycles.
- RLAST→accepted complete transport result: 8.006 → 1.000 cycles.
- B→primary D: 3.280 → 1.000 cycles.
- Read-channel blocked offers: zero in this workload. WLAST→B remains 43.014
  cycles; the external service law was unchanged.
- Mean live write slots: 1.962/2. Mean write slot lifetime: 55.848 cycles.
  Applying Little's-law occupancy to this observed residence gives roughly
  218.6 MiB/s for two credits, close to the measured 214.4 MiB/s. This is an
  explanation of this run, not an immutable theoretical roof under other laws.
- Mean live DMA owners: 3.926/4. Primary TL A still has 19,867 blocked cycles,
  now mainly reflecting write-credit/owner pressure rather than read/write
  A-channel merging. Request supply and credit depth must be evaluated together.

More micro-bubble removal cannot hide a 43-cycle B latency with only two write
credits. A future explicit capacity sweep should retain these service laws and
report separate 4/2 baseline vs larger-credit results, payload/storage costs and
tag/source/interval qualification; never attribute larger buffers to this
same-capacity structural gain. A long-latency saturated stream needs enough
independent owners throughout DMA, home and DDR, not only a larger AXI queue.

Other unresolved serialization remains outside this gate: the mixed home's
global CPU scalar/Acquire versus active DMA-line exclusion, instruction-cache
TL ingress, CPU request supply and cache/LSU/frontier limitations. Removing the
home exclusion requires new nonconflicting-owner directory/probe/fence proofs,
not deletion of an `anyDmaLine` guard. Keep source-order, MMIO, atomic and fences.
The historical CPU host AW/pending-read fence is not bypassed here.

## Reproduction and handoff

```sh
mill -i IonSoC.test.testOnly \
  ooo.LineReadChannelConfigSpec ooo.LineTransferDispatchConfigSpec \
  ooo.DdrWriteCollectionConfigSpec ooo.FpgaNextConfigSpec \
  ooo.DistinctWayReleaseConfigSpec ooo.MemoryStateReuseConfigSpec \
  ooo.CanonicalVirtualStoreBoardConfigSpec
python3 -B simulator/gsim/test_ddr_write_collection_cli.py
python3 -B simulator/gsim/test_line_transfer_dispatch_cli.py
python3 -B simulator/gsim/test_line_read_channel_cli.py
GSIM_CXX=clang++-19 python3 -B simulator/gsim/line_read_channel.py --tag UNIQUE_TAG
```

Use fresh acceptance tags. Native/official GSIM exporters accept the combined
`--ddr-write-collection-flow --line-transfer-dispatch-flow --line-read-channel`
flags. For the four-owner coherent DMA path also select
`--dma-line-transfers --dma-line-entries=4`. No default promotion was made.
Executing-CPU/NEMU performance and necessary CPU/cache integration checks,
combined physical timing/resources, native DDR CDC/MIG and board measurements
remain required before promoting a new board release. No commit or push made.

## Latency and MMU follow-up

2026-10-11 fourth batch, same `dev` HEAD plus local changes. Explicit capacity
experiments and data-TLB permission reuse are implemented through the official
native and GSIM assemblies. All original presets remain unchanged; none of
these results qualify a board frequency, Linux speedup or new bit.

### End-to-end capacity, not a same-capacity scheduler claim

The old delayed stream already occupies almost all four DMA payload owners and
both write credits. Add support for eight tagged DMA owners, eight shared DDR
slots and four write slots. Do not just enlarge a single queue. Four ablations
use the same real DMA/atomic/cache/home/bridge and the same external service
capacity **8 reads / 4 writes**, regardless of DUT geometry:

| Configuration | DMA owners | Shared DDR slots | Write credits |
| --- | ---: | ---: | ---: |
| baseline | 4 | 4 | 2 |
| owners-only | 8 | 4 | 2 |
| ddr-only | 4 | 8 | 4 |
| combined | 8 | 8 | 4 |

The older external service was 4/2; its capacity is deliberately widened for
ALL four ablations, otherwise it would artificially cap the larger DUT.
Baseline results reproduce the prior 4/2 receipt exactly. Read delay, B delay,
ready-stall phases and ID-skew rules are unchanged within this comparison.

| 128 KiB COPY | ID-skew delayed model, MiB/s | Constant-delay model, MiB/s |
| --- | ---: | ---: |
| baseline | 214.441 | 221.714 |
| owners-only | 172.611 | 221.541 |
| ddr-only | 205.985 | 241.896 |
| combined | 332.403 | 442.243 |

ID-skew keeps B eligible at WLAST+40 plus 3/17 cycles according to the selected
AXI ID. The scheduler chooses IDs differently at larger capacities: observed
mean WLAST→B is 43.014 cycles at baseline and 56.877 at combined. Consequently
the 19.5% owners-only regression is NOT proof that congestion alone caused that
loss; it includes a changed service-delay distribution under the same law.

The supplementary constant-delay comparison removes this confound: every read
is eligible at AR+32, every B at WLAST+40, independent of the chosen ID. The
same ready stalls and 8/4 external capacity remain. Actual observed means are
32 and 40 cycles in the combined run. Baseline→combined is 56,379→28,265
cycles: **+99.466% payload throughput**, R/W accepted duty **29.060%→57.966%**.
Small 4 KiB results are 214.747→396.574 MiB/s, including ramp and tail.
The fixed-service checks use hash-verified identical generated RTL, not
re-elaboration; only the independent host drivers are rebuilt.

Minimum-delay primary results remain near the wire ceiling: combined 128 KiB
is 761.174 MiB/s, a 0.049% regression versus 761.545 at baseline. Combined
4 KiB is 710.227 versus 720.710; record this short-transfer overhead too.

### Distance to the ceiling and remaining pressure

- Ideal 64-bit / 100 MHz one-way ceiling: **762.939 MiB/s**. Constant-delay
  combined reaches 57.966%; the gap is 320.696 MiB/s, or about 1.725× to ideal.
- This delayed external model holds WREADY low one cycle in five. Its own
  sustained COPY service ceiling is therefore at most **610.352 MiB/s**.
  The measured 442.243 reaches 72.457% of that ceiling; 168.109 MiB/s remains,
  about 1.38×. Removing DUT bubbles cannot remove this external 20% stall.
- Fixed-delay combined mean live DMA owners: 7.731/8; writes: 3.769/4.
  Mean write bridge residence: 52.018 cycles. Four-credit Little's-law estimate
  is 469.343 MiB/s, close to 442.243. More credits and/or shorter residence
  still matter; eight owners and four writes are not enough to hide every
  long response interval at the wire rate.
- Write home→first TL A averages 8.784 cycles in the constant-delay run, versus
  28.580 in the ID-skew run. The four-source line writer retains payloads until
  response acceptance. Its bounded retention and the home's shared maintenance
  admission still deserve structural review. Increasing DDR credit limits
  beyond four writes alone cannot enlarge this writer.
- For full CPU throughput also inspect LSU supply, cache/MSHR/writeback owners,
  page walks and the home's CPU/Acquire-versus-DMA exclusion. The DMA ceiling
  is not the CPU scalar COPY ceiling: a shared one-request-per-cycle port
  needs both load and store requests. Do not claim these DMA gains as CPU IPC.

Explicit storage cost versus baseline: four additional DMA 512-bit payload
registers (2,048 data bits) and four additional 16-beat, 72-bit bridge payload
lanes (4,608 bits), plus tags/offsets/ownership metadata. TLB capacity is NOT
increased by reuse. Native BRAM/LUTRAM mapping, LUT/FF totals and critical
paths remain unmeasured; no new synthesis/STA is run in this batch.

### Successful-write data TLB reuse

Previously successful read and write translations for the same page occupy
separate TLB entries. Optional `dataTlbWriteReadReuse` reuses a successful
Svade WRITE/RW result for data READ/WRITE/RW in the identical root, ASID, mode,
effective privilege, SUM and MXR context. The walker already rejects W=1,R=0
and requires A/D for a successful write. No raw PTE flags are guessed or added
to the TLB; a read or MXR executable read never grants writes, and data success
never grants execute. A successful write walk upgrades a matching page entry
instead of consuming a duplicate; failed walks never replace it. SFENCE/drain,
PA reconstruction, PBMT and final physical PMP checks remain in force.

Native and official GSIM board assembly enable this policy on the **D-service
only**. Entry count and all CPU/cache geometry are unchanged in each pair.
The fixture uses the real data translation adapter and walker/service, with an
independent PTE/PA/permission/ordered-response oracle and 12-cycle PTE replies,
16-cycle physical replies and deterministic backpressure.

| Same-capacity read/write mixed working set | Cycles OFF→ON | Walks OFF→ON | PTE reads OFF→ON | Useful MiB/s OFF→ON |
| --- | ---: | ---: | ---: | ---: |
| 8-entry TLB, 8 pages, 128 operations | 6,103→1,027 | 128→16 | 384→48 | 16.001→95.089 |
| 16-entry TLB, 16 pages, 256 operations | 12,183→2,033 | 256→32 | 768→96 | 16.032→96.071 |

Both cases traverse eight rounds, read then write two 8-byte words per page.
The 16-page VA span is 64 KiB, not 2 KiB of contiguous DMA data. Read-only
controls are unchanged: 523 cycles at 8 entries and 1,027 at 16 entries.
The near-6× gain is a deliberately capacity-sensitive MMU path result, NOT
a Linux or executing-CPU benchmark. In particular the fixture's PTE endpoint
does not include the production non-leaf `SvPteDataBridge` cache; production
page-walk memory traffic and real programs still require separate measurement.

Fault/context controls cover read-only and MXR-only write denial, missing D,
failed-walk retention, ASID/root/SUM/MXR/effective privilege separation, flushed
remap, final PMP denial even with a warm TLB, AMO RW, stable physical/response
backpressure and ordered fault placeholders. Existing independent read-only
capacity/replacement/context/peek checks pass on each of the four fresh models.

### Evidence, configuration and handoff

- Primary receipt: `build/gsim/latency-bandwidth-local-20261011-r5/receipt.json`,
  `PASS_LATENCY_CAPACITY_AND_SV39_REUSE`; SHA-256
  `5a3d9aec207890a9d60bd45b43fc15edf57bda6f6c98b916dddd4efb1c623c0c`.
  Nine fresh models, 509 frozen input hashes and 25 intended negative controls.
- Constant-delay receipt: `build/gsim/dma-fixed-latency-local-20261011-r2/receipt.json`,
  `PASS_FIXED_AXI_LATENCY_ABLATIONS`; SHA-256
  `99808bc6d95c8194e96c680c6a5bdb9aae3cdd4a0ff6b528b53cab3129355f5f`.
  All primary inputs and reused FIR/header/C++ hashes verified; 511 inputs and
  12 intended negative controls. ASan/UBSan enabled throughout.
- Unified affected Scala regression: 42 tests passed; logs and XML under
  `build/gsim/latency-bandwidth-scala-local-20261011-r2/`. XML SHA-256
  `4dcb9149334f0019b3036a641587b188501ef79fb69566a6c7e3c301c50a56c7`.
  Nine focused host CLI checks passed; recommended performance preset unchanged.
- The configuration now has 41 fields (three new fields after the historical
  38-field checkpoint); backend parameters remain 142. Default capacities are
  still DDR 4/2, one DMA line owner, MMU policy OFF.

Preserved attempts: primary r1/r2 failed compiler selection before generating
models (`GSIM_CXX`, not `CXX`, must name clang++-19). r3 hit a protocol driver's
old full-pool assumption; holding every read result can legitimately block an
unallocated write. r4 then hit a fairness precondition requiring eight offers
before any reply with only four DDR slots. The final driver uses a bounded
mixed-direction witness with a spare shared slot and min(DMA,DDR) initial
pressure; independent full-pool/source reuse proofs remain in the boundary
gate. Supplementary fixed-law r1 failed incorrect host event indices; r2 uses
the correct R_FIRST/W_LAST and eligibility checks. Do not reinterpret any of
these failed-driver runs as hardware qualification or discard their logs.

```sh
# Optional official export/GSIM selectors (other baseline options unchanged):
--dma-line-transfers --dma-line-entries=8 \
--ddr-outstanding=8 --ddr-write-credits=4 \
--ddr-write-collection-flow --line-transfer-dispatch-flow --line-read-channel \
--dtlb-write-read-reuse

GSIM_CXX=clang++-19 python3 -B simulator/gsim/latency_bandwidth.py --tag UNIQUE_TAG
GSIM_CXX=clang++-19 python3 -B simulator/gsim/dma_fixed_latency.py --tag UNIQUE_TAG \
  --receipt build/gsim/latency-bandwidth-PRIMARY_TAG/receipt.json
```

Next priorities: writer retention/independent read-write issue under long
latency, and an executing-CPU Bare/Sv39 same-work comparison with actual
production cache/PTE bridge. Do not remove coherency/atomic/MMIO/fence guards
to increase offered traffic. Continue bandwidth-first; batch changes and short
proofs before any eventual combined physical qualification. No default
promotion, full CPU/NEMU acceptance, Linux boot, new bit, commit or push here.

## Actual CPU Sv39 throughput follow-up

2026-10-11 fifth batch, same `dev` HEAD plus source-hashed local changes.
The requested executing-CPU measurement is now complete: the real
`FpgaNextBoardGsim` CPU boots one identical guest image, enters **S-mode** with
`mret`, and runs READ/WRITE/COPY under both Bare and Sv39. The final S-mode ECALL
must produce cause 9. Requests are generated by instructions, not injected at
DataPort. Production I/D caches, translation adapter/service, non-leaf PTE
cache, coherent home and DDR bridge are present. No Linux or NEMU acceptance,
MIG/CDC measurement, synthesis, STA, bit, commit or push is included.

### Fixed geometry, work and service law

- Two issue/rename/commit lanes, two LSU entries, ROB16, PRF48, DTLB8, ITLB8,
  four non-leaf PTE-cache entries, 32+32KiB two-way caches, 64-byte lines,
  two read MSHRs, two writeback entries and DDR shared4/write2. The single DMA
  line owner is idle. No owner, cache, TLB, ROB or PRF capacity is enlarged.
- Sv39 uses three-level page tables: 4KiB ordinary A/D-set data leaves,
  identity-mapped code/control, and two distinct data VAs mapped to the same
  physical buffers used by Bare. The source/destination buffers are disjoint.
  COPY therefore does **not** reproduce the previous adapter test's alternating
  read/write permission churn on the same page; its near-6x result is not a CPU
  claim for this workload.
- Every model sees the same independent sparse AXI endpoint: first R eligible
  at AR+32, beat gap 1, B eligible at WLAST+32, independent IDs, eight host read
  and eight host write slots. AR/AW/W READY have fixed modulo-7/11/5 stalls.
  This is the CPU fixture's law, not the earlier DMA R32/B40 comparison.
- Each operation warms its own kernel once, then measures two repetitions over
  4KiB or 64KiB per buffer. 64KiB exceeds the 32KiB L1. Initial backing bytes,
  executable, retired ROI PC hash, instruction/load/store counts and useful
  bytes match across policies and Bare/Sv39. Policies can alter their own
  warmup cache microstate; identical initial RAM and retired work do not imply
  identical cache contents at the ROI marker. READ includes a scalar checksum
  dependency; these are specific scalar-kernel rates, not peak CPU bandwidth.
- ROI and post-ROI fence/dirty-clean tails are separate. COPY reports useful
  payload, not the sum of read/write traffic or the number of AXI bytes.
  Rates use GSIM cycles at an **assumed 100MHz**, not board frequency signoff.

### Same-capacity translated-hit staging change

The new `translationHitFlow` / `--translation-hit-flow` is default OFF and
requires registered checked requests, registered translation heads and the
stable virtual-load-precheck epoch. It is incompatible with the separate
`precheckedDataRequestFlow` experiment. It does not change the 142 core
parameters or cache/DDR dimensions; the FPGA configuration now has 42 fields.
Official native and GSIM entry points forward the flag. The recommended
performance preset is unchanged.

A successful same-cycle demand DTLB hit can avoid an **empty translated FIFO**
and enter the existing checked register directly. Final physical PMP, epoch,
shape and canonical-store exact-token/VA/PA checks still apply. An older FIFO
head always wins. Delayed walk replies, page/access faults, atomic, uncached,
PBMT and changing/flush contexts retain the old path. If checked cannot accept,
the hit spills to the original FIFO; response READY remains FIFO-space-based,
not dependent on external physical READY. No physical-port bypass, new owner,
premature acknowledgement or added storage is introduced.

The added TLB-hit-to-PMP/checked selection is a combinational path. Functional
qualification below does **not** establish that this opt-in path meets 10ns.

### Matched actual CPU results

`baseline` has the prior three DDR policies and DTLB reuse OFF. `batch` enables
write collection, line dispatch, line-read channel and DTLB reuse. `accepted`
adds only translated-hit flow to `batch`; prefetch candidate lifetime stays
1 and distinct-way release stays OFF. These are separately frozen revisions,
not reuse of changed generated models. The comparison rehashes all saved
artifacts and verifies full core/storage/derived geometry, toolchain, guest
executable and retired work, as well as the exact policy deltas.

| Sv39, 64KiB per buffer, 2 repetitions | Baseline MiB/s | Prior batch MiB/s | Accepted MiB/s | Accepted vs baseline | New hit-flow vs batch |
| --- | ---: | ---: | ---: | ---: | ---: |
| READ | 63.480 | 71.849 | 71.849 | +13.184% | unchanged |
| WRITE | 69.900 | 77.467 | 84.927 | +21.498% | +9.629% |
| COPY payload | 32.279 | 35.804 | 37.716 | +16.842% | +5.340% |

Sv39 cycles baseline/prior batch/accepted are READ
196911/173975/173975, WRITE 178828/161359/147186 and COPY
387244/349122/331425. Bare 64KiB final READ/WRITE/COPY are
79.253/162.249/43.004MiB/s; hit-flow leaves all three prior-batch Bare results
unchanged. The earlier DDR batch's 4KiB Bare COPY is four cycles worse than
baseline (7682 to 7686, -0.052%); retain this small regression too.

The 4KiB cache-resident control isolates staging from DDR and page walks:

| Warm Sv39 operation | Baseline → accepted cycles | MiB/s | Hit-flow accepts |
| --- | ---: | ---: | ---: |
| READ | 3606 → 3606 | 216.653 → 216.653 | 0 |
| WRITE | 9485 → 8461 | 82.367 → 92.335 (+12.103%) | 1024 |
| COPY payload | 13335 → 12311 | 58.586 → 63.460 (+8.318%) | 1024 |

All three warm ROIs have zero data walks and zero AXI traffic/cache misses.
Removing exactly 1024 cycles on 1024 demand-hit stores directly witnesses the
avoidable translation FIFO stage. Loads already use their registered physical
precheck path, so this change does not improve pure READ.

### Rejected policies and the remaining real bottleneck

Two existing policies were evaluated without enlarging any geometry. `flow`
retains prefetch candidates for 16 cycles instead of 1 in addition to hit-flow;
`scheduled` adds the existing qualified distinct-way release to `flow`.

| Sv39 64KiB | Prior batch | Retained-PF `flow` | +distinct-way `scheduled` | Final accepted |
| --- | ---: | ---: | ---: | ---: |
| READ MiB/s | 71.849 | 115.493 | 115.493 | 71.849 |
| WRITE MiB/s | 77.467 | 84.927 | 84.927 | 84.927 |
| COPY MiB/s | 35.804 | 29.146 | 29.146 | 37.716 |

Retained candidates produce 1512 useful read prefetches, but COPY regresses
18.597% versus the prior batch, and Bare COPY regresses from 43.004 to
36.600MiB/s. Distinct-way release changes **none** of the measured cycles in
these twelve cases. Neither combination is selected as a general improvement;
the final candidate restores prefetch lifetime 1 and distinct-way OFF. The
rejected fixtures and receipts remain available; the existing policies are not
deleted or promoted. A READ-only gain does not justify a COPY regression.

Actual final counters make the next priorities concrete:

- READ: cache/physical blocked offers 110848/173975 cycles (63.715%), but
  only one cache miss owner and one outstanding host AXI read are observed.
  Two LSU entries are used, yet the second MSHR is not overlapped in the ROI.
  At candidate lifetime 1 there are 2014 read-prefetch candidates and zero
  allocations. Retry timing and cache demand/refill/eviction admission, not
  more cache capacity, require the next structural investigation.
- WRITE: warm cache stores still consume about eight cycles each, despite zero
  walks, misses or DDR traffic. The stream has LSU peak 1 and physical owner
  peak 1. `IntegerBackend.postedEligible` excludes virtualized stores and the
  virtual store retains ordinary serial head ownership. The hit shortcut
  removes one real bubble but does not create a pipelined authorized-store
  handoff. Next design work must preserve exact VA/PA/epoch/PMP proof and
  precise-fault/retirement semantics before releasing further owners.
- COPY: `candidateLoadBlockedByStore` is observed on 225421/331425 cycles
  (68.016%). Physical/cache blocked offers are only 2076 cycles (0.626%);
  waiting for a data walk is 3200 cycles (0.966%, 64 walks, 64 physical PTE reads,
  128 non-leaf PTE hits). Unknown-store blocking is zero. The surviving
  canonical/older-store ownership barrier and serial request supply are the
  major next targets; simply declaring MMU misses the bottleneck is incorrect.
  Physical owner peak and cache miss owner peak remain 1 despite available
  DDR4 and MSHR2 capacities. During `flow`, two cache owners overlap for only
  1824 COPY cycles, while total latency worsens.
- Accepted AXI duty for final Sv39 COPY is R 9.906% / W 4.943%; physical CPU
  accepts are 32768/331425 cycles (9.887%). This is far below saturation.
  The one-request-per-cycle scalar port's COPY payload ceiling is at most
  4B/cycle = 381.470MiB/s at 100MHz, not the independent-R/W DMA ceiling of
  762.939MiB/s. Final COPY is only about 9.9% of that scalar-port ceiling;
  the checksum/instruction/ordering kernel imposes further restrictions.

Counters are independently overlapping predicates, not disjoint causal
partitions; never add store-blocked, head-memory, walk and cache counts to
obtain total delay. The code conditions and measured signatures identify the
next ownership/admission redesign; they do not prove every reason a second
MSHR was refused. Keep single-SRAM write-port safety, set/way reservations,
response tickets, probes, fences, MMIO and atomics when restructuring it.

### Short gates, evidence and reproduction

- Five fresh executing-CPU models, twelve positive cases and three intentional
  negative controls each: **60 positive cases / 15 negative controls**. The
  independent host ledger looks up host-initialized bytes at observed physical
  request addresses and checks data/mask/ordered responses/faults; checksum and
  post-clean backing bytes are separately checked. This is not a per-instruction
  architectural VA-to-PA/PC oracle or a replacement for NEMU.
  Mutating expected read data, final copied bytes or ECALL cause fails at its
  respective independent check. ASan/UBSan enabled; no NEMU library is available
  locally, and no full ISA, speculative recovery or FPU claim follows.
- New adapter boundary gate reuses the independent DTLB read/write reuse and
  peek oracle on one fresh hit-flow model. Context/ASID/root/SUM/MXR, SFENCE,
  read-only/dirty-bit/AMO permission, final warm-TLB PMP denial, held replies,
  ordered fault placeholders and capacity remain qualified. Two PA/permission
  mutations fail as intended. The earlier gate r1 failed a host `defines`
  argument type before model compilation, not hardware behavior; r2 passes.
- Unified affected Scala gate: **44 tests / 10 suites passed**. XML:
  `build/gsim/cpu-sv39-bandwidth-local-20261011-r4/scala-test-report.xml`,
  SHA256 `d01b42274bda2629e1d75addc9ff9a3d34b3faa187ac59556660acb50e21691f`.
  Eleven affected CLI/default checks and `git diff --check` pass. Broader CLI
  discovery is **27/28**, not all green: the historical IntegerBackend text
  equality anchor still differs at remote HEAD; that file was not changed and
  the check was not weakened.

All paths below are under `build/gsim/`; receipts bind frozen sources and all
saved generated objects, executables and case logs.

| Evidence | Status | SHA256 |
| --- | --- | --- |
| `cpu-sv39-bandwidth-local-20261011-r1/receipt.json` (baseline/batch) | PASS_ACTUAL_S_MODE_CPU_SV39_BANDWIDTH | `372ac3ff037414385179bc0b27ac7644a1987108820e08d5301b74551fa83093` |
| `cpu-sv39-bandwidth-local-20261011-r2/receipt.json` (flow) | PASS_ACTUAL_S_MODE_CPU_SV39_BANDWIDTH | `e52d36c7f26d2f6af618bf9be2af69369390e7d454f3d718170856e533676c65` |
| `cpu-sv39-bandwidth-local-20261011-r3/receipt.json` (scheduled) | PASS_ACTUAL_S_MODE_CPU_SV39_BANDWIDTH | `2a5c590fffeb2e022749ac5ed7b2df243bb2e33f16c9f64f90005d615e0d6b11` |
| `cpu-sv39-bandwidth-local-20261011-r4/receipt.json` (accepted) | PASS_ACTUAL_S_MODE_CPU_SV39_BANDWIDTH | `1756b623ceb8cd2a13106a9961932caedaed90893873da90492c2ba08bc042bf` |
| `cpu-sv39-bandwidth-local-20261011-r4/comparison.json` | PASS_FROZEN_CPU_SV39_COMPARISON | `36d0b0976a2015c01f6f5ee72215f1635a1fd7ae3f688cf90ad6009d4da73f6c` |
| `translation-hit-flow-local-20261011-r2/receipt.json` | PASS_TRANSLATION_HIT_FLOW_BOUNDARIES | `7fcad718f9d4ab99c8cd34a6aadbb374643158294b0eccbf5329d74790935367` |

```sh
# Two fresh real CPU models, same guest/work/capacity/service law:
GSIM_CXX=clang++-19 python3 -B simulator/gsim/cpu_sv39_bandwidth.py \
  --tag UNIQUE_TAG --profiles baseline accepted
# One necessary independent adapter permission/backpressure model:
GSIM_CXX=clang++-19 python3 -B simulator/gsim/translation_hit_flow.py --tag UNIQUE_TAG
# Read-only audit of this run's five frozen profiles (does not rebuild models):
python3 -B simulator/gsim/cpu_sv39_compare.py \
  --receipt build/gsim/cpu-sv39-bandwidth-local-20261011-r1/receipt.json \
  --receipt build/gsim/cpu-sv39-bandwidth-local-20261011-r2/receipt.json \
  --receipt build/gsim/cpu-sv39-bandwidth-local-20261011-r3/receipt.json \
  --receipt build/gsim/cpu-sv39-bandwidth-local-20261011-r4/receipt.json
mill -i IonSoC.test.testOnly \
  ooo.TranslationHitFlowConfigSpec ooo.LatencyBandwidthConfigSpec \
  ooo.DataTranslationCapacitySpec ooo.LineReadChannelConfigSpec \
  ooo.LineTransferDispatchConfigSpec ooo.DdrWriteCollectionConfigSpec \
  ooo.FpgaNextConfigSpec ooo.DistinctWayReleaseConfigSpec \
  ooo.MemoryStateReuseConfigSpec ooo.CanonicalVirtualStoreBoardConfigSpec
PYTHONPATH=simulator/gsim python3 -B -m unittest \
  test_ddr_write_collection_cli test_line_transfer_dispatch_cli \
  test_line_read_channel_cli test_latency_bandwidth_cli test_translation_hit_flow_cli
```

Next batch: qualified virtual-store ownership handoff and independent demand/
prefetch admission under real refill/eviction latency, with the same fixed CPU
Bare/Sv39 workload. Do not compensate for serialized admission by increasing
issue width, LSU/DTLB/cache/MSHR or DDR capacity. Continue short necessary
validation only; combined physical qualification remains deferred.

## Authorized store handoff and independent demand admission

2026-10-11 sixth batch. `independentDemandAdmission` / official native and GSIM
`--independent-demand-admission` is an opt-in scheduling policy, **default OFF**.
It requires canonical virtual-store overlap and virtual RAM load precheck;
`FpgaNextConfig` now has 43 fields and `CoherentCacheConcurrency` 13. The
recommended performance preset is unchanged. It does not expand any queue,
cache, MSHR, TLB, ROB, PRF, DDR pool or issue width.

### Ownership and admission contract

The store keeps its real LSU slot, accepted-request response owner, completion
and precise ROB retirement/fault responsibility. No early store acknowledgement,
new store buffer or authority for an unissued older store is introduced. The
existing registered certificate still requires the exact token (index AND tag),
original VA, PA, byte lanes, epoch, final permission and live protected head.
Only a prechecked ordinary disjoint RAM load can use that certificate.

- The LSU selector can assign an empty slot while an authorized store retains
  a blocked completion, rather than insist on replacing that completing slot.
  Reservation selection uses registered owner state, not completion READY or
  same-cycle cancellation. Wrong-token, unprechecked, atomic and forwarded
  operations do not receive the exception. `cpuAuthorizedHandoff` counts
  authorized empty-slot starts, not just arbitration stalls actually saved.
- Normal cached store misses no longer create a global admission barrier.
  Bypass/MMIO/uncached/atomic and maintenance still drain the existing owners.
  Ordered response tickets, late denied grants, E/C/probe and fence obligations
  remain unchanged.
- Demand reservations protect the **complete physical line and full set+way**.
  Same-set independent lines can use distinct existing ways; a hit in the other
  resident way need not wait for the entire set. Invalid-first/LRU selection is
  evaluated only among unreserved ways. An outstanding writeback for the same
  physical line also excludes admission. No same-line miss coalescing is added.
- An independent resident store hit may use the SRAM write port beside a live
  miss. Refills/installations, eviction capture and probe ownership retain their
  port exclusions; accepted reads retain their snapshot and FIFO response owner.
  Autonomous prefetch allocation remains separately qualified. These changes
  do not promise arbitrary independent reads can overtake the ordered data port.

The policy is forwarded from cache configuration through MachinePlatform /
MappedMachineCore / MachineCore / IntegerCore / IntegerBackend to the LSU's
constructor flag `canonicalHandoff`. `OooParams` stays at 142 fields. Equality
of the core parameter object alone is therefore **not** equality of all core
scheduling policy; profile/cache equality plus this explicit forwarding and
the executing-core observation are part of the evidence.

### Short boundary proof

`independent-demand-admission-local-20261011-r4/receipt.json` passes
`PASS_INDEPENDENT_DEMAND_AND_AUTHORIZED_HANDOFF`; SHA256
`5ea4d7b43b799e9df1118b277bacb1e0f18a736f6bf172c0e59259a7d01a58a8`.
The compact cache fixture has **32 lines / 2 ways / MSHR2 / response8 / WB1**.
The eight response slots retain the pre-existing seven-held-response snapshot
test; this fixture is not evidence of production response2 capacity. Production
CPU A/B uses response2 / WB2 and 32KiB I/D caches.

The independent ordered byte ledger checks held store+read misses in the same
set/different ways with two simultaneous TL acquires; same-line denial; resident
opposite-way read hits; partial store hits beside a miss; denied-store retry with
no backing-memory side effect. Existing II1 hit, seven held byte-version replies,
probe/writeback snapshots, clean/dirty replacement, high-address aperture,
response backpressure, coordinated reset and drain cases remain in the driver.
The LSU gate deliberately holds completion READY low and checks exact-token
empty-slot handoff, rejecting wrong-token and unprechecked offers; existing
cancel, tag-reuse, request ownership, faults and completions remain checked.
Both independent data/payload mutations fail at their respective oracle checks.
ASan/UBSan remain enabled.

Failed development attempts remain saved: r1 sampled the allocation register on
the acceptance edge (fixed by observing the next edge); r2 exposed the old
test's global-store-miss barrier rule, replaced only for the new opt-in contract
and strengthened with a same-physical-line owner check; r3 exposed a pinned
GSIM POD initializer that supplied a uint32_t pointer distance as memset bytes.
The r3 sanitizer stack points to a newly constructed model's first reset edge,
not a live accepted request. The C++ fixture now initializes the complete POD
model before its unchanged real reset sequence. No generated/vendor code,
sanitizer suppression, capacity increase or read-result oracle weakening is used.

### Executing CPU A/B

The same-source `accepted` (OFF) / `admission` (ON) measurement retains the fifth
batch's guest, 4KiB/64KiB work, two measured repetitions, warmup and fixed
R32/B32 AXI service and READY stalls. Production geometry stays two issue,
LSU2 / ROB16 / PRF48 / DTLB8 / ITLB8 / PTE cache4 / 32+32KiB / MSHR2 /
response2 / WB2 / shared DDR4 / write2 / idle DMA1. Independent host-initialized
physical-address and allowed-store-byte checks, ordered replies, final backing
memory, checksum and retired PC/count/hash checks apply to both fresh models.
The host ledger is not a per-instruction VA-to-PA ISA oracle or a substitute for
NEMU. No Linux, board performance, FPU, MIG/CDC, synthesis or STA claim follows.

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/independent_demand_admission.py \
  --tag UNIQUE_TAG
GSIM_CXX=clang++-19 python3 -B simulator/gsim/cpu_sv39_bandwidth.py \
  --tag UNIQUE_TAG --profiles accepted admission
python3 -B simulator/gsim/cpu_memory_admission_compare.py \
  --receipt build/gsim/cpu-sv39-bandwidth-UNIQUE_TAG/receipt.json
```

The same-source r5 run passes 24 positive cases and six negative controls.
`cpu_memory_admission_compare.py` rehashes the artifacts and permits only
`independentDemandAdmission=false->true`; full profile sections, capacity,
retired work and guest are checked. OFF reproduces all twelve prior accepted
cycle counts exactly. Forty-eight Scala checks and thirteen relevant CLI
checks pass, with copied XML/logs bound into the CPU receipt.

Admission alone is **not a completed Sv39 bandwidth solution**:

| 64KiB / two measured passes | OFF cycles | ON cycles | OFF / ON MiB/s | ON two-MSHR cycles |
| --- | ---: | ---: | ---: | ---: |
| Bare COPY | 290672 | 284800 | 43.004 / 43.890 | 26342 (9.249%) |
| Sv39 COPY | 331425 | 331412 | 37.716 / 37.717 | 0 |

All warm-cache cases and stream READ/WRITE cycle counts are unchanged. Sv39
COPY physical owner peak rises 1->2, with 16351 authorized empty-slot starts;
cache-offer blocked cycles fall 2076->0, but store-blocked cycles only change
225421->225382. Both AXI read peak and cache miss owner peak remain 1. The
13-cycle gain is only 0.003923%; neither physical peak2 nor observed handoffs
prove sustained miss concurrency. Request R/W/retired-work counters still
match. Bare COPY accepts 2014 independent misses and overlaps two cache owners,
but gains only 2.062%; there is still substantial serialization before service.

A necessary follow-up ablation combines this new admission policy with the
existing single-candidate prefetch retention policy (16 retry cycles instead of
1, no more candidates or MSHRs). Only a test profile/runner label is added;
production hardware sources and guest remain identical. The fresh r6 model
passes twelve positive cases and three negative controls. The extended audit
rehashes both receipts, requires identical production sources/toolchain/guest,
permits only those two fixture/runner source changes and the retention policy
delta, and verifies full configuration and retired-work equality.

| Sv39 64KiB / two passes | OFF MiB/s | Admission + retention MiB/s | Delta |
| --- | ---: | ---: | ---: |
| READ | 71.849 | 115.493 | +60.743% |
| WRITE | 84.927 | 85.095 | +0.198% |
| COPY (payload, not R+W) | 37.716 | 38.355 | +1.695% |

**The existing second MSHR now really participates in executing Sv39 COPY:**
100935 / 325901 cycles (30.971%) have two cache owners, with 1982 independently
admitted misses and AXI read peak2. Physical CPU request peak is2, but request
duty is still only10.055%, AXI R10.074% / W5.027%. Thirty-one percent two-owner
occupancy is not thirty-one percent throughput gain or a saturated bus.

The combined policy is **not a recommended global configuration**. Bare COPY
regresses 43.004->36.600MiB/s (-14.892%); all4KiB cases remain unchanged. In
Sv39 COPY, read misses change2048->34 but write misses34->2048. The shared
single-prefetch-owner schedule favors the source stream and loses destination
prefetching. Store-blocked observations drop225421->91977 (overlapping predicates,
not an additive causal partition), yet overall cycles only drop331425->325901.
This establishes a real admission fix while exposing a read/store scheduling
tradeoff, not a complete bandwidth solution. The prior retention-only profile
had Sv39 COPY29.146MiB/s; its blocked global-store-miss boundary cannot be
replaced by merely giving the old scheduler more retry time.

Next structural batch should rebalance **qualified read/store prefetch owner
admission and head-store response/retirement handoff**, while preserving full
VA/PA/token/epoch/permission lineage, late errors, accepted FIFO response
responsibility and existing capacities. Do not solve the tradeoff by increasing
cache/MSHR/TLB/LSU/DDR size or early-acknowledging an uncompleted virtual store.
Keep the admission-only candidate separately available; the retention
combination remains an experimental ablation, default and preset unchanged.

| Evidence under `build/gsim/` | SHA256 |
| --- | --- |
| `cpu-sv39-bandwidth-local-20261011-r5/receipt.json` (fresh OFF/ON) | `92a866917dbf612e48e7ba23041478322d97ec436566523c8b6dd80d3042e422` |
| `cpu-sv39-bandwidth-local-20261011-r5/comparison.json` | `846681175b62f5c8a583ee4c4392aa58372854cb26c9ed464ac438fd14aa6173` |
| `cpu-sv39-bandwidth-local-20261011-r6/receipt.json` (retention ablation) | `832828137d27e194d92a6f88844b07daf4621d190724beb0bcc3d3ffb1a5db96` |
| `cpu-sv39-bandwidth-local-20261011-r6/comparison.json` (combined audit) | `7fb0e46f152483939071663bf01c5cd0b9e84a9f6d1bc50ac1572535052a54a1` |
| `cpu-sv39-bandwidth-local-20261011-r5/scala-test-report.xml` (48 tests) | `5f3943fad7a8ba835d8ba0202fa47ec0d4a0ad2b309ee149e906ba51ed920b3e` |
| `cpu-sv39-bandwidth-local-20261011-r5/cli-tests.log` (13 tests) | `affd5e62800b199b683c0edf6ff0f298fff8c00cab500a9622726a355cd301df` |

```sh
# One additional necessary model, not another baseline rebuild:
GSIM_CXX=clang++-19 python3 -B simulator/gsim/cpu_sv39_bandwidth.py \
  --tag RETENTION_TAG --profiles admission-retained
python3 -B simulator/gsim/cpu_memory_admission_compare.py \
  --receipt build/gsim/cpu-sv39-bandwidth-PRIMARY_TAG/receipt.json \
  --retained-receipt build/gsim/cpu-sv39-bandwidth-RETENTION_TAG/receipt.json
```

For a fresh all-current-source run, use `--profiles accepted admission
admission-retained`. The special cross-revision audit above documents this
turn's test-label addition and requires exactly those two test-only source
changes; it is not a generic waiver for changed production inputs.

Component MSHR occupancy2 must not be reported as sustained CPU MSHR2 usage;
actual two-owner cycles, accepted physical-request and R/W beat duty remain
required. No new physical qualification is run for these scheduling trials.
