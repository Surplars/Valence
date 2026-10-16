# Default-off disjoint victim/store SRAM overlap

## Result and scope

Fresh GSIM component execution, 2026-10-16, based on `1a40353e` plus the working-tree candidate.
The unmasked 64-store stream accepted 512 payload bytes in **67 OFF versus 65 ON cycles**
(3.08% higher accepted-store duty); the last actual CPU response arrived after **68 versus 66 cycles**.
The total fixture ROI, including fixed 20-cycle settling and drain checks, was **90 versus 88 cycles**.
OFF rejected a resident store on the queued dirty-victim read and its following capture cycle;
ON accepted one resident store on each of those exact cycles. Both retain one refill-write conflict.
The direct-demand dirty-victim case accepts its disjoint store one cycle earlier, but its overall
fixture ROI (including settling) remains 63 cycles. The all-hit control remains 64 acceptance / 65 response-drain cycles.

This is a synthetic-manager **private-cache component** result, not executing-CPU, real-home,
DDR, board bandwidth, PPA or routed-timing qualification. No board default is changed. Enabling
it in a board configuration still needs explicit option plumbing and system qualification.

## Native cache specification and traffic

`DisjointEvictionStoreGsim` derives controls from `ThreeProofRowNativeProfile.config.cache`:
512 lines, two ways, 256 sets, 32 KiB; two read MSHRs, two response rows, two writeback rows;
64-byte lines; native RAM base `0x80200000`, aperture 2 GiB; compact banked tags; actual
whole-line grant mode; original posted owner, tagged-response configuration, registered probe
lookup, local read selection and shared store-write payload. Board/core case-class arities stay
95/178. The host byte image covers the 64 KiB touched subset of the full native aperture.

The existing synthetic eight-beat manager is unchanged: first D eligibility is 24 cycles after
actual A acceptance, then one beat per cycle when ready; the wrapper collects those eight
independent memory words into the actual whole-line grant input. Alternating noninteger
store-buffer return handles 4/5 preserve acceptance-ordered external byte checking without
changing the tagged cache implementation. This is not integer-return bypass or LSU lineage coverage.

The primary unmasked stream has no imposed C/E/CPU holds on either side. Its request sequence,
service law and accepted CPU/TL traffic volumes are identical. The masked/backpressure case uses
an accepted-store-ordinal hold schedule; it is correctness coverage, **not cycle-identical external
stall-service performance evidence** (OFF/ON held-C counts differ 12/10).

## Change and resource contract

`NonBlockingCoherentLineCache.disjointEvictionStoreOverlap` defaults to false and requires
`independentDemandAdmission && memoryScheduleOverlap`. It changes only resident-store readiness:

- A queued dirty-victim read may coexist with a store only when the full SRAM indexes differ.
- The next eCapture cycle may coexist with a resident store. Capture consumes the previous
  edge's read result; a store creates no read-result owner.

There are still eight 64-bit banks, each with separate synchronous read and masked write ports.
The original read/write collision assertion remains. Full-way and physical-line reservations,
victim writeback identity, response credits, refill priority, probes, bypasses and flush barriers
remain required. The victim is invalidated before capture, so a store cannot mistake its old
physical way for a live resident hit. No state, queue depth, MSHR, response row, SRAM port or
per-slot duplicate datapath is added. The 9-bit queued-read index comparison is control logic.

Static OFF selects the original independent-store predicate and adds only a constant-false
term to the eviction-phase predicate; the local Boolean check covers 4,096 input combinations.
That check is not an RTL-equivalence proof or a physical-area measurement.

## Fresh acceptance

Eight scenarios per side passed, with ASan/UBSan and the original independent byte/protocol oracle:

1. Direct demand victim capture and disjoint resident store
2. Same set, other physical way store during capture
3. Full-duty 64-store stream across queued victim read/capture
4. Partial mask during victim read, zero mask during capture, full masks, all banks, held C
5. Warm ordinary-hit latency/throughput control
6. Exact victim-address store excluded until safe writeback/reacquisition
7. Two full response rows reject another store
8. Probe offered during active victim capture excludes the store

Positive ON overlap and zero OFF resident-hit overlap are required, not merely counted.
Refill installation blocks every offered store on its write-port cycle. Independent expected bytes
come from authored CPU intentions and initial backing memory, never from a candidate/reference
DUT. CPU readback, dirty ProbeAckData/ReleaseData and full backing image after flush all pass.
Two transport corruption controls independently flip CPU-result and dirty-C data; both are rejected
by the expected oracle diagnostic. They do not simulate a hardware mutation.

Artifacts: `build/gsim/disjoint-eviction-store-r1/{off,on}/qualified-r2/` contains raw traces,
results and source/FIR/executable hashes; `paired-r2/receipt.json` binds both sides and negative controls.
The earlier exploratory fixture attempts remain available, including one rejected witness counter
that incorrectly counted a store miss's own direct eviction as resident-store overlap. It was fixed
by requiring `hit`; no DUT change was made after the OFF/ON emitters.

## Area and remaining limits

A native-geometry Yosys Xilinx UltraScale prescreen was attempted with verification layers disabled.
OFF reached ABC after extracting 39,380 gates / 46,744 wires, but hit its 90-second Yosys limit.
ON mapping was therefore not started. **No completed area delta is available.** Generated SRAM
geometry is unchanged by construction; mapped BRAM/LUT/FF counts and physical timing remain
unverified. No Vivado, bit generation, local tools, full Linux or full regression was run.

Reproduction (only with a granted serial compiler window): source `scripts/cloud/env.sh`, then
run `python3 simulator/gsim/disjoint_eviction_store_build.py --run-grant --gsim <repaired-gsim>
--output <fresh-directory>`. This compiles/elaborates the two static variants, uses the repaired GSIM,
runs the eight short cases and paired negative controls. Do not reuse a pre-existing output directory.
