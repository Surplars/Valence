# DDR write collection / AXI send overlap

2026-10-11 source candidate, based on published dev `c46359c`. Default OFF.
This is a structural burst-path change, not a new CPU/DDR performance preset.

## Reason and scope

The existing bridge collects every TL A write beat before offering either AXI
AW or W. With a 64-byte line, collection and transmission each occupy eight
beats, even when the downstream channels could prepare/send earlier. Increasing
write credits alone does not remove that per-owner serialization.

The new `writeCollectionFlow` lane/bridge/DDR option uses the same bounded payload
RAM and one write/read port. Separate registered capture count and consumer
cursor allow AW and previously captured W beats while later A beats arrive.
No W credit is borrowed from a current-edge input. A producer gap stops new W
offers after existing credits drain. A stalled W retains its address/data/strobe.
The full payload capacity is unchanged; no ring overwrite or early slot reuse.

Targets: at most one accepted A and one W beat per cycle, simultaneously; first
eligible W after a registered capture boundary; arbitrary independent AW/W
backpressure; existing transaction/AXI-ID/TL-source credits and completion rules.
Single-lane read capture/playback and aggregate R error behavior are unchanged.

Only explicit ordinary-RAM windows may enable this option. MMIO/legacy scalar
boundaries reject it. Rejected or oversize writes drain every A beat without
issuing AW/W. B and final TL D still precede source/slot reuse. Existing matching
AW and W owner queues, cross-source reply policy and interval RAW/WAR/WAW
exclusion stay in place. Reset tests assume coordinated subordinate reset/drain;
this does not make a reset in a live external AXI transaction non-destructive.

## Selection and compatibility

`--ddr-write-collection-flow` is accepted by FPGA-next Scala native/GSIM exports
and Python export/board preflight. It does not change two-issue RV64GC, cache,
ROB/PRF/LSU, DDR/shared/write slots, address aperture or clock frequency. Every
default and frozen recommended preset retains OFF.

At this first checkpoint the complete FPGA config gained one Boolean field
(36 rather than 35 fields). The following independent
[line-transfer dispatch batch](line-transfer-dispatch-flow.md) brings the current
arity to 37; historical audited experiments explicitly require both options OFF.
Historical evidence is not relabeled as a runtime pass on the modified source.

## Focused gate

Host-only selector/default checks:

```sh
python3 -B simulator/gsim/test_ddr_write_collection_cli.py
GSIM_CXX=clang++-19 python3 -B simulator/gsim/ddr_write_collection.py --tag fresh-tag --preflight-only
```

After the whole batch compiles, run the paired serial and four-shared/two-write
real bridges once:

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/ddr_write_collection.py --tag fresh-tag
```

The same-source OFF/ON gate keeps the AXI service law and traffic identical.
It additionally runs four-owner DMA through the real atomic/cache/mixed-home/
TL/AXI path at 4 KiB and 128 KiB under unchanged delayed and minimum-delay service
laws. This is DMA/coherence component integration, not executing CPU evidence.
External handshakes, authored bytes, masks, AXI IDs and live TL sources drive the
oracle; no DUT pointers or payload RAM are used. It covers 1/2/8/16-beat writes,
producer gaps, separate AW/W holds, all 256 single-beat strobes including zero,
mixed R/W, late R/B errors, source/slot reuse, dependencies and coordinated reset.
Independent byte/credit checker mutations and malformed R/B/last responses must
fail at their intended checks. Every model is generated fresh with ASan/UBSan;
failed receipts remain in their unique output directory.

The initial `local-20261011-r1` gate passed the serial OFF positive checks but
stopped because its negative checker expected the multi-slot R-ID assertion
text on the serial lane. The actual illegal ID was rejected by the serial
engine's existing ID/RLAST assertion. The failure receipt is retained; it is not
counted as a completed acceptance. The corrected gate selects the expected
serial or multi-slot assertion explicitly and regenerates fresh models.

The second `local-20261011-r2` gate retained a too-strong timing check requiring
same-edge A/W handshakes even with three-cycle producer gaps. Registered credits
normally send W on the edge following A, so a phase overlap does not imply that
edge coincidence. The corrected check requires W before last A in sparse cases
and simultaneous accepted A/W in continuous cases. The byte, mask, owner,
accepted-credit and no-early-ack oracles were not weakened. Its partial results
and failed receipt are retained separately.

Report request-channel accepted-beat duty, acceptance while offered and accepted
R/W beat duty separately. Mixed traffic is independent read/write traffic, not
a CPU COPY payload metric. Cycle-derived 100 MHz component rates do not qualify
real MIG bandwidth, cache coherence, executing CPU IPC or a board image. The
unchanged historic CPU host's AW/pending-R fence is not removed to manufacture
a bandwidth result. Physical-board speedups and whole-SoC 10 ns timing remain
UNVERIFIED. Independent bridge OOC results are recorded separately below.

## Completed short acceptance: local-20261011-r3

The receipt at `build/gsim/ddr-write-collection-local-20261011-r3/receipt.json`
records `PASS_COMPONENT_AND_COHERENT_DMA`, based on dev
`c46359c3f35758465ca6e94d3fa5609747a1be30` plus the source-hashed local patch.
All 30 negative controls were rejected at their intended checks. The separate
host CLI gate passed three tests; the unified affected Scala configuration /
elaboration gate passed 30 tests. No full regression or executing CPU benchmark
was run in this batch.

The matched shared bridge has four slots, two write credits, 64-bit data and a
maximum 16-beat burst. Each row below retains identical accepted traffic and
external AXI service. Duty means accepted beats divided by measured cycles,
not VALID alone, not acceptance conditional on an offer, and not wall time.

| Shared bridge workload | OFF cycles | ON cycles | Accepted W duty OFF -> ON | Throughput gain |
| --- | ---: | ---: | ---: | ---: |
| 128 independent 8-beat writes, minimum service delay | 1,416 | 1,031 | 72.316% -> 99.321% | 37.342% |
| Same writes, 12-cycle preparation delay | 2,120 | 1,672 | 48.302% -> 61.244% | 26.794% |
| 64 reads + 64 writes, 8 beats, 12-cycle preparation delay | 1,296 | 985 | 39.506% -> 51.980% | 31.574% |

The mixed row also has the same R duty as W duty. Its A accepted-beat duty rises
from 44.444% to 58.477%. The first row's 128 writes all overlap AW and first W
with TL collection. Minimum-delay single-beat traffic stays at 513 cycles on
both sides; the optimization is not a blanket gain on every request size.
Address-request duty is separate from A data-beat duty: the first row accepts
128 AW addresses on each side, so AW duty rises from 9.040% to 12.415%. The mixed
row accepts 64 AR and 64 AW addresses on each side; each address channel rises
from 4.938% to 6.497%. The same burst carries multiple useful data beats per
address, so a low address-channel duty alone does not imply wasted bandwidth.

The second pair copies actual data using four line owners through the existing
DMA / atomic endpoint / cache / mixed coherent home / TL / AXI path. Payload
rates below assume 100 MHz for the component; they are not measured on the FPGA.

| Coherent DMA copy | External service | OFF -> ON cycles | Payload MiB/s OFF -> ON | Throughput gain |
| --- | --- | ---: | ---: | ---: |
| 4 KiB | Existing delayed profile 0 | 2,152 -> 2,112 | 181.517 -> 184.955 | 1.894% |
| 128 KiB | Existing delayed profile 0 | 69,842 -> 64,609 | 178.975 -> 193.471 | 8.099% |
| 128 KiB | Existing minimum-delay profile 1 | 28,708 -> 26,912 | 435.419 -> 464.477 | 6.674% |

For the 128 KiB delayed copy, accepted A duty rises from 26.391% to 28.529%,
and R and W duty each rise from 23.459% to 25.359%. This is a real component
integration improvement, but it is far from saturating the interface. It must
not be multiplied by prior CPU/cache gains or labeled as a CPU COPY speedup.

## Remaining measured limits and next structural work

In the delayed 128 KiB DMA copy, the ON write bridge-slot residence still averages
58.011 cycles, versus 65.496 OFF. WLAST-to-B averages 43.014 cycles on both sides;
the external service latency was not shortened. The read slot still averages
49.033 cycles ON, and RLAST-to-last-D is 8.008 cycles. Mean bridge occupancy is
3.393 of four slots. These observations support investigating owner residence
and return/admission scheduling rather than only changing a bus-width or credit
number. They do not prove that all blocked home offers are an arbitration bug.

Next batch should profile the real CPU refill/writeback supply alongside home
admission and return arbitration, then consider structurally decoupling response
storage and active AXI ownership where the ordering/error contract permits it.
Read capture cannot simply forward early data: this bridge currently aggregates
late AXI errors over the complete TL response. Preserve that behavior, interval
RAW/WAR/WAW exclusion, bounded response storage, and source/ID ownership. Keep
the CPU host service law unchanged and compare both independent traffic and an
executing CPU before recommending a new default preset.

## Native bridge OOC experiment

The exact accepted shared OFF/ON FIRs are exported with firtool 1.135.0 to
`build/gsim/ddr-write-collection-local-20261011-r3/native/{off,on}.sv`.
`fpga/next/measure_ddr_write_collection.tcl` measures both on
`xczu15eg-ffvb1156-2-i`, using a 10 ns clock and identical synchronous input /
output assumptions (max 2 ns, min 0.25 ns). Only the externally managed reset
port is excluded. These assumptions are not actual board boundary constraints.

The first OOC attempt stopped after OFF synthesis because `remove_from_collection`
is not a Vivado Tcl command. It produced no timing verdict. The corrected script
uses `get_ports -filter` and saves a synthesis checkpoint before subsequent
steps; the failed log is retained separately. This was a validation-script fix,
not another RTL change or a new GSIM source candidate.

The second attempt completed both routes in Vivado 2025.1. Reports, exact RTL,
scripts and synthesis/routed checkpoints were copied back to
`build/gsim/ddr-write-collection-local-20261011-r3/ooc/r2` with every copied file
verified by SHA256. The first attempt's files are retained under `ooc/r1`.

| Routed bridge metric | OFF | ON | Change |
| --- | ---: | ---: | ---: |
| Setup WNS at 10 ns | +3.282 ns | +3.242 ns | -0.040 ns |
| Hold WHS | +0.025 ns | +0.046 ns | +0.021 ns |
| CLB LUTs | 1,415 | 1,470 | +55 |
| CLB registers | 797 | 837 | +40 |
| LUT as memory | 228 | 228 | Unchanged |
| BRAM tiles / DSPs | 0 / 0 | 0 / 0 | Unchanged |

Both have zero setup/hold failing endpoints, zero unclocked registers and zero
unconstrained internal endpoints. The one false-pathed reset input is reported
explicitly. DRC has no errors; the OOC no-routable-load warning remains. The
ON worst setup path is physical-address-to-A-ready interval qualification, not
the new payload cursor. These results qualify this standalone bridge only;
they do not qualify actual SoC clocks, reset, boundary paths, MIG, CDC or a bit.

User refinement after this experiment: prioritize useful bandwidth and request
supply; do not insert frequent STA runs between further optimization edits.
The following line-transfer dispatch batch has its own source-hashed short
acceptance, with no further STA. This bridge OOC does not qualify that later
home/line-engine change or the complete current SoC.
