# Real coherent-home qualification

The new posted-store owner and actual private cache now pass a bounded component gate through the real MixedCoherentLineHome, AtomicDataMemory DMA boundary and original TL/AXI path. The gate uses authored requests and an independent byte-addressed AXI environment. Full SRAM bytes are checked through real CPU loads, home-generated B/C probes and complete backing bytes after cache-plus-home flush. No synthetic coherence responder is used in this gate. The authority sidecar remains a fixture-supplied successful physical committed-store premise. Executing CPU authority and a combined whole-board run remain separate requirements.

## Exact scope and provenance

Production src/main bytes are identical to bc518ec83fc51bbef9e5376f9cee0e1e10200848. The initial real-home wrapper copied a two-bit private-cache source field and failed MixedHome's three-bit minimum constructor guard. Session 98208 exited 1 before any native model. This failed receipt is retained. The corrected wrapper uses three transport bits while retaining only Acquire sources 0/1 and WB sources 2/3, with no extra resource credits.

The OFF/gen64 and ON/gen64 models passed on 7960d020f36f768124db5431bedcedbbaa6e8eec, tree a7bb18498f2c18b87982f36dcb6b7879a605a777. Session 58084 exited 0 after 13 steps in 100.480 seconds, producing 34,495,418 bytes. Receipt SHA-256 is 4b8707edd4a1794a846645e7de39d246ca104304ac1f28f3e1b1877e424c2945.

A separate ON/gen2 model passed on 08af97c1c257526741fcc62dffd7aefc3b5cc922, tree 839e9823c5e916929c030f961ba884966cfe632a. Session 50320 exited 0 after eight steps in 57.104 seconds, producing 23,357,269 bytes. Receipt SHA-256 is 838132477a72444073504570ccdcc413bccee70deb0e87230769a3530c4033bf. The prior gen64 models were retained. ASan/UBSan and the 200 MiB / 700 MiB resource guards passed in both complete runs. No lost historical result was inherited.

All three models use 16 private lines, 16 directory lines, two MSHRs, two response slots and two WBs. Legal production geometries and default OFF pruning were checked in the earlier private-cache gate; this real-home gate does not extend its runtime results to other geometries. The first stage constructs both real-home ON/OFF configurations before native generation.

## Runtime coverage

Seven positive native scenarios pass. OFF checks legacy stores/loads and complete flush. ON/gen64 checks five same-line stores sharing one actual Acquire while the original two response tickets are repeatedly reused; a real DMA write changing the base before actual A; a real home-generated dirty probe after install while the original CPU ACK is held, followed by DMA overwrite and a later load proving no resurrection; and separate clean/dirty victim C-last to Acquire overlap while a real home-produced ReleaseAck is held. The queue holding that Ack captures real messages and does not invent a source or completion. Every claimed event is observed with a nonzero count.

The ON/gen2 positive takes 736 cycles. Four full owners exhaust generation space, followed by two actual legacy fallbacks. After the first fallback's CPU ACK, aggregate cache busy stays high while the independent real C/source ledger still awaits ReleaseAck. A real DMA B/C probe completes during that tail. A younger held proof cannot prevent the old cache/home flush from finishing; afterward the next fallback progresses without generation wrap. Complete AXI backing bytes agree.

There is one real-home RTL negative: contextEpoch changes from 0 to 1 after fallback CPU ACK while the actual home ReleaseAck is held. It exits -6 with exactly `cache fallback context changed before real coherence drain`. The six synthetic-manager RTL negatives in the earlier cache gate are not counted here. Pre-A DMA does not imply a pre-A probe when the real directory has no owner. The synthetic younger-refill/oldest-install and after-E probe schedules have not yet been claimed as real-home reachable.

## Independent observer rejection controls

A separate offline gate at 689cbbae5bb744ee001a21d065bafe82fe99fde0 verifies the original model, hardware input and artifact hashes, then replays all six original gen64/OFF traces through the independent byte/full-owner/WB observer. Five mutations of copied observation records are each rejected with their exact expected diagnosis: wrong dirty C byte, wrong full generation, wrong owner slot, missing WB-completion association and prematurely asserted WB-completion association. The actual TL handshakes are retained for the two association mutations. Original RTL inputs and all source model/trace files remain byte-identical. These are offline observer controls, not five new RTL stimulus negatives. The offline receipt SHA-256 is 6b7dbe4259fe0907160ee1bcd8d4111606f204aca128041124634efac0223265.

The ten scalar/AXI host tests and existing owner-contract 22 tests / 10 detected host mutants also pass, in their own host scope. They do not substitute for the three actual native models.

## Fresh resource accounting

In this instrumented 16-line configuration, complete declared registers increase by 12,737 bits, from 15,780 to 28,517 across the wrapper. The increment lies entirely in the private-cache/owner subtree. Memory stays 12,406 bits and physical memory-port count stays 38. The declaration delta is:

| Category | Added bits |
| --- | ---: |
| Overlay payload and byte-valid masks | 1,152 |
| Full ROB tokens for 16 members | 1,088 |
| Repeated full line context for 16 members | 3,616 |
| Original response ticket per member | 16 |
| Owner line context and reservation | 594 |
| Cache copies of line context and reservation | 594 |
| Original response-slot full member copies | 590 |
| WB exact ticket and context copies | 858 |
| Fallback full token/ticket copies | 207 |
| Widened original acquire tags | 134 |
| Lifecycle, cohort and generation control | 229 |
| Assertion-only held payload and epoch state | 3,659 |
| Total | 12,737 |

Exact leaf mapping to generated native headers finds 3,410 retained named cache/engine register bits OFF versus 12,655 ON, a 9,245-bit delta. The ON native model omits 3,619 declared cache-register bits. This model has observation and assertion cones, so the number is neither an uninstrumented production measurement nor mapped FPGA PPA. The separate 512-line default-OFF comparison against the published cache has identical declared state/memory/port shape and a disclosed +8-byte native top layout difference.

Current production capacity is two line owners and sixteen global store tokens; there is no eight-token per-owner limit. The documented eight-store tail is an example. Owner/MSHR retention lasts until its actual accepted tokens and exact attached WB responsibility drain. Token-context compaction or earlier owner release is future work that must preserve provenance and pass new measurements. No CPU throughput improvement, synthesis-area improvement or old +4,960-bit figure is claimed.
