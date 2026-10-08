# Independent AW/W dispatch at unchanged DDR capacity

## Scope and contract

This candidate changes `TileLinkAxi4OutstandingBridge` only. The selected geometry stays four total AXI/TL owners, at most two live writes, 16 buffered beats per owner, 64-bit data, and four physical AXI ID bits. The existing one-read/one-write-port payload memories, registered AR/AW skid queues, source lifetime, whole-D-message arbitration, overlap checks, upstream ordering and coherence boundaries remain.

The previous mixed-write dispatcher used one FIFO head until both its AW enqueue and its final W handshake completed. That prevented the next write's address from entering the address pipeline while older write data was pending, despite independent AXI channels.

The candidate uses matching address-token and data-token FIFOs. Both receive the same first-A accepted write in the same order. The address head advances on AW enqueue; the data head advances only on accepted WLAST. Both skip locally denied complete writes. No AXI W interleaving or AW/W pairing relaxation is allowed. Each queue is bounded by the live write-credit limit. At the selected 4/2 geometry, the two 2-entry, 2-bit token payloads contain the same eight token bits as the former single 4-entry FIFO. Small additional ownership/control state is explicit; this is not a claim of mapped LUT/FF savings.

Per-slot pending bits prevent a locally denied younger write from retiring its TL source/AXI slot while either token still sits behind older stalled traffic. The gate is applied to unordered selection, external D.valid, and lane D.ready. Raw lane D.valid remains available to skip tokens. Clears are registered, so valid writes retain their completion latency; a denied head gains one registered ownership-cleanup cycle, and a queued denial waits until both of its dispatch tokens reach their respective heads. This also fixes a pre-existing unordered denied-tail lifecycle bug reproduced by the independent directed oracle.

AW burst/lock/cache/prot/qos are assigned their constructor constants after owner selection, keeping fixed metadata static even when no owner is offered.

## Timing and resource limits

- No datapath widening, slot-count increase, payload duplication, or transparent pipeline bypass.
- External AW stability remains protected by the existing registered queue.
- AW/W ready paths terminate at independent token/slot control. D qualification uses bounded registered ownership bits.
- The new pending qualification adds logic to D eligibility; actual 100 MHz slack must be checked in implementation. No routed timing, power, LUT/FF/BRAM, MIG throughput, CDC, or board claim follows from these simulations.
- AXI4 W remains ordered and non-interleaved. Same-address RAW/WAR/WAW waits until full TL retirement.
- CPU/DMA maintenance admission remains unchanged. The homes' broad acquire/release drain guards can still limit actual end-to-end overlap.

## Independent verification

`write_pipeline.py` elaborates the preserved baseline and candidate independently, runs the same frozen traffic/oracle, records source hashes, and compares fixed transactions and memory service laws. It measures 128 sustained transactions at 1/2/8/16 beats, zero or 12-cycle AW preparation, independent channel stalls, and mixed reads/writes. A latency measured from each accepted address is a synthetic service law, not a MIG estimate.

Existing independent mixed/unordered and AW/W-channel checks cover out-of-order R/B, repeated/overlapping addresses, source recycling, partial strobes, aggregate late errors, channel independence, held payloads, resets, and rejected windows. Directed additions cover two AWs before any W, skewed AW/W-head reset, denied tail behind blocked older W, unrelated read bypass, and source/slot reuse without reset. Wrong expected data/pairing and malformed RID/BID/RLAST are required failing controls.

`bus_fabric_throughput.py` uses the actual nested arbiter, registered A/D boundaries, two-master/two-bank crossbar, and DDR bridge. Three independent disjoint backing streams represent instruction, home-line, and ordered direct-DMA traffic, 128 requests each. It checks exact transaction and byte ledgers, AXI IDs, response ownership, whole-message D, masked memory, errors, per-master/channel backpressure, fairness/latency and idle duplicate detection. This deliberately excludes the CPU/cache/home admission logic; it must not be reported as simultaneous coherent CPU/DMA execution.

Commands from each isolated checkout (installed toolchain only):

```sh
source ../Valence/scripts/cloud/env.sh
# Preserved baseline
python3 simulator/gsim/write_pipeline.py --tag cloud-r1 --baseline-control --selected-only
python3 simulator/gsim/bus_fabric_throughput.py --tag cloud-r1
# Candidate
python3 simulator/gsim/write_pipeline.py --tag cloud-r1 --baseline ../Valence-throughput-baseline/build/gsim/write-pipeline-cloud-r1
python3 simulator/gsim/bus_fabric_throughput.py --tag cloud-r1 --baseline ../Valence-throughput-baseline/build/gsim/bus-fabric-throughput-cloud-r1
```

## Verified results (2026-10-08)

All receipts below are PASS. Only the production `TileLinkAxi4OutstandingBridge.scala` differs between each matched baseline/candidate pair. Synthetic service latency and accepted transaction definitions are identical; handshake timing is allowed to improve.

| Workload | Baseline cycles | Candidate cycles | Reduction |
| --- | ---: | ---: | ---: |
| 128 × 8-beat writes, preparation 12 | 2700 | 2120 | 21.48% |
| Same writes, independent channel stalls | 3775 | 3459 | 8.37% |
| 128 mixed 8-beat transactions | 1368 | 1296 | 5.26% |
| Same mixed workload with stalls | 2012 | 1931 | 4.03% |
| Real fabric, 384 three-master requests, steady | 4506 | 4303 | 4.51% |
| Real fabric, 384 requests, stalls + 12 errors | 5440 | 5098 | 6.29% |

For the first row, useful W throughput rises from 0.379259 to 0.483019 beats/cycle (+27.4%). The zero-preparation controls at 1/2/8/16 beats do not regress (all finish two cycles earlier, a startup/drain difference rather than a material sustained-bandwidth claim). At preparation 12, the 1/2/16-beat cases reduce cycles by 32.28% / 30.11% / 15.54%.

The real fabric reports three concurrently active AXI master domains, four live AXI IDs and two live writes. AW owners pending W rise from one to two; 58 steady / 57 stressed later AWs lead unfinished older W. Steady useful bytes/cycle rise 3.508211 → 3.673716; stressed 2.798529 → 2.986269. Exact R/W/D counts and bytes are unchanged. All three masters finish 128 requests; candidate stressed maximum response latency is 113 / 146 / 79 cycles for fetch/home/DMA. Home's maximum increases one cycle (145 → 146), so this is not a claim that every individual transaction becomes faster. Successful progress and per-master backpressure are checked independently.

Bridge parameter coverage: total/write/ordered = 4/2/unordered, 4/2/ordered, 4/1/unordered, 8/4/unordered. Each tests independent AW/W timing, W-before-AW, inverse B IDs, errors, held D and reset. The selected geometry additionally passes all sustained benchmarks, denied-tail/read-bypass/no-reset-reuse and skewed-head resets. Wrong expected W/data, bad RID/BID/RLAST, and an emitted-RTL mutation forcing all new retirement guards open are detected. The original baseline fails the denied-tail ownership test; the corrected candidate passes. Removing the fix reproduces `write data FIFO lost its live owner`.

CHIRRTL audit verifies four unchanged 16 × 72-bit payload memories, each one read and one write port: 4608 payload bits total. Token payload remains eight bits (one 4 × 2-bit queue becomes two 2 × 2-bit queues). Control-state/logic additions are not hidden by these counts. Actual mapped area and 100 MHz timing remain unverified.

Evidence under the candidate's `build/gsim`:
- `write-pipeline-cloud-r1/receipt.json`, `comparison.json`, `structure.json`
- `bus-fabric-throughput-cloud-r1/receipt.json`, `comparison.json`
- `write-pipeline-mutation-cloud-r1/receipt.json`

The baseline receipts live under the same test-directory names in the preserved baseline checkout. Reproduce the guard mutation and storage audit with:

```sh
python3 simulator/gsim/write_pipeline_mutation.py --tag cloud-r1 --input build/gsim/write-pipeline-cloud-r1/s4-w2-u1/TileLinkAxi4Bridge.fir
python3 simulator/gsim/write_pipeline_structure.py ../Valence-throughput-baseline/build/gsim/write-pipeline-cloud-r1/s4-w2-u1/TileLinkAxi4Bridge.fir build/gsim/write-pipeline-cloud-r1/s4-w2-u1/TileLinkAxi4Bridge.fir build/gsim/write-pipeline-cloud-r1/structure.json
```

No repository commit/push, full GSIM, Linux simulation, Vivado run, bitstream or hardware access was performed by this batch.
