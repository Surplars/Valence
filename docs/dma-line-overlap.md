# Bounded coherent DMA line overlap

The selected experimental profile is four line owners with zero pacing:
`--dma-line-transfers --dma-line-entries 4`. It reaches 178.975 MiB/s for a
128 KiB isolated copy in the delayed-DDR model at 100 MHz, versus 49.228 MiB/s
with one owner on exactly the same source and workload. The selected default
configuration remains scalar until physical timing and board qualification.
The machine-readable choice is `fpga/next/dma-overlap-candidate.json`.

This extends the single-owner candidate documented in
[dma-line-transfers.md](dma-line-transfers.md). That document and
`dma-line-candidate.json` retain the phase-one measurements/profile. The
four-owner profile supersedes phase one's yield16 choice for the next
integration candidate. Yield4 remains an explicit alternative; it is not a
universal improvement under contention.

## Why overlap

The original line engine used only one of four existing DDR slots. With delayed
AXI, a line read retained ownership for about 53 cycles and its following write
for 68 cycles, plus three turn cycles. Bypassing AtomicMemory in a diagnostic
fixture changed no cycle count, so removing atomic protection would not help.
Reducing the AXI delay raised single-owner throughput to 124.558 MiB/s but still
left read and write service serialized. The measured ablations are described
in [dma-pipeline-study.md](dma-pipeline-study.md).

The new scheduler holds two or four bounded payload/offset slots. It can read a
later source line while an earlier destination write awaits its real response.
The default depth is one; supported depths are 1, 2 and 4. DDR shared/write
credits remain four/two, and the 64-bit TileLink/AXI links, cache geometry, MSHRs
and packet DMA ABI are unchanged.

## Ownership and ordering

Each occupied DMA slot retains its descriptor offset, 512-bit payload, and
read-wait/write-ready/write-wait phase. A write address comes from that slot's
saved offset, including when replies arrive out of order. A tag is unique among
accepted requests until its matching response handshake. Stalled requests and
responses retain their complete payload, tag, direction and error. No timeout
or local abort withdraws offered work or frees an accepted owner.

All line traffic still passes through AtomicMemory. Line admission requires an
idle atomic FSM and drained ordinary owners. Live tagged line owners and an
irrevocable held offer exclude an AMO from starting; accepted line writes clear
matching LR reservations. Ordinary demand arriving during a live line set stops
additional line admission, except for at most one previously held offer. Initial
simultaneous arbitration may also grant one preferred line. The accepted set then drains and
ordinary traffic gets a turn. A pending cache Acquire similarly stops new home
admission. This bounds admission under downstream progress; arbitrary external
backpressure cannot have a finite cycle guarantee.

The coherent home serializes admission and probes. After dispatch it retains
each line's address/type owner while the existing line-transfer engines run in
parallel. A later same-address operation waits in a registered hazard state
until the earlier response actually retires, including response backpressure.
This address comparison is outside the request-ready path. New CPU ownership
and conflicting maintenance remain excluded until the live line set drains.
Read/write response tags are outside refill/release tag ranges, with explicitly
wide dispatch addition so boundary carries cannot alias another owner class.
The existing engines hold complete replies; the home adds a direction lock
when its response is stalled.

Descriptor qualification and partial-transfer rules remain the phase-one ABI:
positive length and both addresses must be 8-byte aligned, nonoverlapping and
fully within RAM. Zero length, overlap, wrapping, MMIO and invalid ranges fail
without traffic. Differing source/destination offsets modulo 64 remain scalar.
Aligned interiors use full lines; scalar prefixes/tails drain before switching
ownership modes. A line never crosses 4 KiB; a descriptor may cross pages. This is
not memmove and does not make a whole copy atomic against conflicting software.

Direct R/B errors stop new work, drain all accepted/held owners and report
failure. Earlier successful writes are not rolled back. The inherited dirty
probe/release writeback error policy remains assertion/fail-stop. Completion
waits for every actual write response and every owner; reset still requires
coordinated interconnect reset. MemoryCopyDma has no STOP/generation ABI.

## Paired results

Each MiB/s figure counts copied destination bytes once. All modes use the same
100 MHz clock, C++ byte oracle, DDR delay policy and exact source inventory.
The delayed profile uses R delay 32, B delay 40 plus ID-dependent 3/17-cycle skew,
and periodic AR/AW/W stalls. Allocation can change the resulting ID mix; these
are simulation comparisons, not promised board ratios.

| Owners / yield | 512 B cycles / MiB/s | 4 KiB cycles / MiB/s | 128 KiB cycles / MiB/s |
| --- | ---: | ---: | ---: |
| 1 / 0 | 998 / 48.926 | 7,939 / 49.203 | 253,923 / 49.228 |
| 2 / 0 | 554 / 88.137 | 4,404 / 88.698 | 140,804 / 88.776 |
| 4 / 0 | 365 / 133.776 | 2,152 / 181.517 | 69,842 / 178.975 |
| 4 / 4 | 392 / 124.562 | 2,567 / 152.172 | 79,862 / 156.520 |
| 4 / 16 | 480 / 101.725 | 3,552 / 109.973 | 112,672 / 110.941 |

For 128 KiB, every mode issues exactly 2,048 AR, 2,048 AW and 2,048 B transactions,
with 131,072 read bytes and 131,072 write bytes. Four-owner completion follows
the final B by four cycles. The four-owner delayed run uses all four bridge
slots and both write slots; average occupancies are 3.366 bridge slots and 3.909
line owners. The one-owner reference averages 0.903 bridge slots. This is actual
overlap, with no extra DDR credits or reduced payload.

With minimum AXI delay, 128 KiB improves from 100,355 cycles / 124.558 MiB/s at depth 1
to 49,166 / 254.241 at depth 2 and 28,708 / 435.419 at depth 4. A configured zero-delay
host response still arrives on the next simulation cycle. The ideal 512-bit
oracle is only an ablation; it bypasses 64-bit serialization and coherence.

### Fixed CPU and DMA work

CPU results below are synthetic cache DataPort requests, not an executing LSU
or CPU memcpy loop. The test offers one request at a time on a 32-cycle grid,
visits a 1,024-line ring, accesses each line twice, and creates deliberate cache
set conflicts. Read uses 8 useful bytes, masked write 4, and copy counts the
8-byte written result once per read/write pair (four useful bytes per request
on average). The balanced cases perform equal
useful CPU and DMA byte counts. Endpoint timing includes both kernels,
completion control, dirty CPU flush and all final DDR responses. Full AXI byte
counts match exactly across all five modes; CPU-only rows are identical.

| Workload | 1/0 full cycles | 4/0 full cycles | 4/0 speedup | 4/4 full cycles |
| --- | ---: | ---: | ---: | ---: |
| dirty 4 KiB + CPU read | 42,999 | 40,279 | 1.0675 | 39,991 |
| dirty 4 KiB + CPU write | 97,527 | 95,086 | 1.0257 | 94,777 |
| dirty 4 KiB + CPU copy | 125,127 | 124,522 | 1.0049 | 124,522 |
| cold 128 KiB + CPU read | 1,113,196 | 1,097,708 | 1.0141 | 1,112,812 |
| cold 128 KiB + CPU write | 2,129,612 | 2,168,354 | 0.9821 | 2,183,369 |
| cold 128 KiB + CPU copy | 3,282,116 | 3,239,094 | 1.0133 | 3,239,094 |

The cold 128 KiB CPU-write case takes 1.819% longer at depth 4/yield0. Its aggregate
useful rate is 11.529 MiB/s versus 11.739 at depth 1. This measured tradeoff is
accepted for the selected performance candidate; isolated throughput alone is
not the selection criterion. Yield4/16 produce identical balanced-work rows in
this workload, but yield16 loses more isolated throughput.

CPU response latency in cycles is listed as p95/p99/maximum. One cycle is 10 ns
in this model. Request-offer blocked maxima for the three 4 KiB rows are 1/10/10
cycles and for 128 KiB are 0/0/0, identical for profiles 1/0 and 4/0. The paced
4/4 cold-write case instead reaches 10 offer-blocked cycles. These offer times
do not replace the following acceptance-to-response latency measurements.

| Workload | 1/0 p95/p99/max | 4/0 p95/p99/max | 4/4 p95/p99/max |
| --- | ---: | ---: | ---: |
| dirty 4 KiB + read | 225/307/308 | 181/201/303 | 182/200/204 |
| dirty 4 KiB + write | 177/288/315 | 159/195/303 | 166/195/204 |
| dirty 4 KiB + copy | 199/212/213 | 200/212/225 | 200/212/225 |
| cold 128 KiB + read | 128/139/146 | 106/155/199 | 97/189/200 |
| cold 128 KiB + write | 83/85/145 | 82/154/199 | 82/175/200 |
| cold 128 KiB + copy | 113/134/144 | 82/179/223 | 82/179/223 |

Directed continuous-DMA admission tests observe Atomic/Acquire service within
61/59 cycles at depth 2 and 77/75 at depth 4 under the tested DDR response policy,
with at most one prior irrevocable admission. No starvation was observed.
Yield4 reduces the small dirty read/write maximum to 2.04 us from 3.03 us, but
increases the cold write full-work cost to 2.524%. It is an explicit tradeoff.

## Storage, ports and remaining ceiling

Complete CHIRRTL declaration counts, including vectors/bundles and instantiated
modules, add 719 register bits at depth 2 or 1,941 at depth 4 relative to depth 1.
Yield4 adds three further bits. Memory declarations add two bits because the
two-entry write-dispatch queue's tag widens from two to three bits. There are
no additional memory ports; the home's eight existing tag-memory ports remain.
These are elaborated declarations, not mapped LUT/FF/BRAM or routed timing.

At 100 MHz, a 64-bit one-way wire carries 762.94 MiB/s. Copy requires both reads and
writes; that wire rate is not an attainable copy target by itself. The scalar
shared request path has a 381.47 MiB/s ideal copy bound. Eight-beat line requests
use one Get plus eight Put beats and eight read replies plus one write reply,
giving a 678.17 MiB/s ideal TileLink bound before latency/credits/coherence.
Observed isolated bridge residence estimated about 218 MiB/s from four shared
slots and 194 MiB/s from two write slots. These are occupancy estimates from a
specific latency distribution, not universal limits. The measured delayed
four-owner run already averages 1.921 of two write slots occupied. Further work
should measure write response residence and admission conflicts before adding
more payload buffers; removing atomic protection gave zero benefit.

## Evidence and replay

The external `Valence-dma-overlap-qualified-20261009` evidence package retains
source-bound receipts, raw logs, generated RTL/FIR, comparison data, failures
and source mutations. They are intentionally absent from the source-only Git
tree. `build/dma-overlap-final-qualification.json` is its entry point. Every
performance mode has 42 isolated/diagnostic cases, 12 combined cases and three
CPU-only cases, plus protocol and host-checker negative suites.

The protocol suite checks reordered read/write tags, held offers/replies,
mixed-direction replies under backpressure, dirty/clean probes, real LR/SC and
AMO exclusion, errors while another offer is held, scalar tails, page/aperture
boundaries, busy descriptor rejection and the cache/home drain path used by
FENCE.I (the fixture does not execute that instruction). Manual line clients
pass through the real Atomic/home boundary and test same-address ordering while
the older response is held. The always-on per-tag checker binds read data to
independent admission snapshots. Its same-address B counter is an exact own-B
check for cold isolated writes; a dirty probe writeback can also increment that
counter. Dirty correctness therefore additionally uses the full byte oracle
and final empty-DDR/owner checks, not a claimed per-operation dirty-B identity.

Packet coexistence runs the real scalar EthernetPacketDma alongside depth 4 copy
DMA at yields 0/4. Four STOP/drain/restart cases include a held unaccepted TX
request, delayed accepted TX read, held TX stream, 66-cycle RX B hold, 13-byte
masked RX, dirty probes and rejected premature reuse. Final DDR queues are
empty and 100 quiet cycles reject late owners. These tests do not execute a CPU
or include MAC/PHY/CDC. Software epochs are not hardware generation tags.

Three source mutations target retained destination offsets, reply tags and
same-line hazards; a fourth targets the tag carry assertion. They are distinct
from the host data-drop/corruption/early-check sensitivity negatives. Fresh
full-SoC exports cover the two selected/optional profiles and mean RTL export
only. Native timing, mapped resources, CDC and a new board run remain pending.

With the already provisioned tools, from the repository root:

```sh
source "$VALENCE_CLOUD_ENV"
export VALENCE_GSIM_SOURCE=/path/to/verified/gsim-src
mill -i IonSoC.test.testOnly ooo.DmaOverlapSpec ooo.DmaLineSpec ooo.FpgaNextConfigSpec
python3 -B simulator/gsim/dma_overlap.py --tag fresh-d4-y0 --entries 4
python3 -B simulator/gsim/dma_packet_stop.py --tag fresh-d4-y0 --line-entries 4
python3 -B simulator/gsim/dma_overlap_source_mutations.py --output build/fresh-overlap-mutants
python3 -B fpga/next/export.py --output build/fpga-next/fresh-overlap4 --emit \
  --dma-line-transfers --dma-line-entries 4
```

`VALENCE_CLOUD_ENV` should identify a verified checkout's `scripts/cloud/env.sh`;
no simulator/tool installation is implied. Use new output names to preserve
evidence. The focused receipts hash all production Scala inputs and the exact
fixture/model/driver. Fresh comparisons must keep clock, payload, DDR policy
and full completion endpoint equal. The historical 9fceb61 board DMA result of
24.252 MiB/s remains a separate user-supplied baseline, not this candidate's result.
