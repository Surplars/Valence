# R1: static circular instruction-reservoir payload

2026-10-24. **Focused component, whole-frontend and actual-CPU checks passed with no R1 cycle or
traffic loss in the measured cases. Physical timing/area remain unqualified.**
The default remains the original compacting reservoir. R1 is independent of M2 data translation;
neither the original `full-candidate` profile nor its existing evidence is silently redefined.

## Targeted dependency and its cost

In the actual two-wide B2+A2+P1 configuration, `RenameRob` admission drives `IntegerCore.accepted`,
then `RegisteredFetchPacket.consume`, `PopCount`, remaining occupancy and the write selection of
four 226-bit instruction slots. Partial consumption moves surviving payload; new payload is placed
at `remaining + lane`. These are source-level dependencies, **not a measured critical path**.

The existing raw capture credit already depends only on registered occupancy, not consumption.
Raw cursor progress, split correction capture, prediction/hint logic and cancellation priorities
are retained. Ordinary branch redirection flushes the reservoir and changes its registered cursor;
it is not synonymous with system `invalidateFetch`. A2 demand owners and held physical requests
are not changed or withdrawn by this experiment.

R1 replaces movement of live payload with static storage and small head/tail controls:

| Contract | Legacy and R1 |
|---|---|
| Capacity | Four complete instruction owners |
| Capture / consume width | Two, contiguous prefixes |
| Minimum latency / target II | One cycle / one cycle |
| Capture credit | Four minus **old** occupancy, no consumed-credit borrowing |
| Bypass / additional stage | None / none |
| Payload | Instruction, access/page faults, exact fault address, PC and raw successor, 226 bits |
| Cancellation | Old outputs remain observable before the edge; discard old and same-edge captured owners |

The four payload slots remain 904 bits. R1 adds a two-bit head and two-bit tail; its three-bit
occupancy replaces, rather than duplicates, the original occupancy. Two parity banks each have
two static rows. Successive captures always use different banks, with at most one write per bank.
Registered tail selects each write row and lane; current `consume` never selects payload writes.
Cancellation changes logical ownership only. Speculative same-edge payload writes may occur but
cannot become valid after the pointer/count reset.

**This trades write-side control for read-side selection.** The original compacted head outputs
are direct registers. R1 adds two-row bank reads and a lane exchange mux for its two full payload
outputs. Accepted-prefix validation additionally reads only the third queued PC, not a third or
fourth full payload. Head fanout and read-mux depth may hurt the decode path; no Fmax, LUT/FF,
power or synthesis-runtime improvement is claimed before physical evidence.

## Ownership argument and steady-state throughput

With head `h`, tail `t` and count `n`, the invariant is `t = h + n (mod 4)`. A capture prefix `a`
satisfies `a <= 4 - n`; a consumed prefix `d` satisfies `d <= n`. Captures therefore write only
old free slots, not surviving owners, even when capture and consume coincide. Normal state is
`h' = h+d`, `t' = t+a`, `n' = n-d+a`; cancellation resets all three controls to zero.

The event sequence is exactly old queue minus its consumed prefix followed by new captures,
unless cancellation discards both. At occupancy two, capture two plus consume two preserves
occupancy two indefinitely. Both implementations therefore permit continuous two-instruction
cycles without adding a bubble. Full-queue/partial-consume behavior deliberately preserves the
old credit law, rather than quietly improving traffic by borrowing same-cycle capacity.

RVC alignment, cross-packet assembly, precise fault `tval`, raw successor prediction and
instruction acceptance remain in their existing production modules. A circular slot is only an
instruction-owner transport; it does not decode instructions, infer addresses or reconstruct PCs.

## Scope and comparison plan

Production scope is the new `CircularFetchInstructionStorage`, the optional storage branch in
`RegisteredFetchPacket`, the `IntegerCore` connection and an explicit default-off
`circularFetchPayload` configuration field. Two-wide/non-phase specialization is enforced at
construction. Shared configuration/profile and emitter changes are coordinated with M2, not
concurrently edited by independent implementations. No BPU, A2 credit, ITLB, I-cache, PMP or
physical-request context change belongs to R1.

The focused runner is `simulator/gsim/r1_fetch.py --gsim <pinned> --tag <fresh>
--baseline <P1-leaf-receipt>`. It builds only:

1. One small storage fixture, with an independent event deque and full 226-bit owner checks,
   partial prefixes, all pointer residues/wrap, old-credit stalls, simultaneous events,
   cancellation/dead-write/refill and continuous two-wide witnesses. Slot/read and next-PC
   observation negatives require their exact diagnostic and injection marker.
2. One reservoir fixture containing both old compaction and R1 storage, with cycle-by-cycle
   visible-output comparison. The unchanged independent ISA/deque host also checks prediction,
   faults and recovery; the old RTL is not the sole oracle.
3. The actual A2 two-owner supply chain with R1 enabled. Its unchanged byte oracle, service law,
   nine cold cases and six warm/warmup rows must preserve all 570 P1 metric fields. Four existing
   observation negatives remain. Original/single-owner frontend models are not rebuilt here.

Actual-tile R1-only, M2-only and necessary combined CPU comparisons are separately coordinated;
this runner does not silently build three redundant CPU regressions. Feature fields must be
recorded, and geometry, guests, service law and functional oracle remain fixed.

## Frozen-input results

The unified incremental compile and the two `CircularFetchStorageSpec` tests passed. No R1
production/fixture/host/runner repair was needed after its initial freeze. The three-model
component/frontend receipt is `build/gsim/r1-fetch-20261024-r1/receipt.json`, SHA256
`2680a0fba3ed1b2222c78917aab463f4f583df78223af0d33dd287ff570c2d18`.

- Storage: 740 cycles, 760 captures = 701 consumed + 57 discarded + 2 reset-discarded owners;
  all 226 payload bits observed in both polarities. Two 64-cycle runs supplied/consumed two
  instructions every cycle, totaling 128 continuous two-wide witness cycles.
- Cancellation: 17 dead captures, 20 immediate refills, and all four cancelled-write tail
  residues were observed. Old outputs were checked on the cancellation cycle; invalid payload
  was not incorrectly required to clear to zero.
- Legacy/circular paired reservoir: 32,223 cycles, including 1,541 partial joins, 441 flushes
  with traffic, 1,273 path mismatches and 126 boundary jumps, under the unchanged independent host.
- Actual two-owner frontend: all **570 output fields** over nine cold cases and six warm/warmup
  rows equal the P1 receipt (`fbe442a7...e28b`). This includes work/drain cycles, request/response
  counts, bus extent/hash, fault counts and instruction hashes; exact fault addresses remain
  checked by the byte oracle, not a separate metric field. ROM32 stays 517 cycles, RAM32 299;
  retained-cache Bare/Sv39 stay 142/170 cycles with zero TL traffic.
- Seven exact-diagnostic observation negatives passed: two storage, one reservoir, four frontend.
  They test oracle sensitivity, not RTL mutation coverage.

The separate actual production `CommonA1CpuTile` four-control run passed all 16 case executions
and two combined-model observation negatives. CPU receipt:
`build/gsim/m2-r1-common-vm-20261024-r1/receipt.json`, SHA256
`76d3b7cb6e77dbaf5c14098452abf837d2b9bce28a1c647294d829f58c2cb558`.
For both fixed M2 settings, enabling R1 preserves all **100 CPU output fields** exactly:

| Guest | baseline = R1 work cycles | M2 = M2+R1 work cycles |
|---|---:|---:|
| Independent ALU, RAM | 1027 | 1027 |
| Branches, RAM | 375 | 375 |
| Sv39 ordinary-store stream/readback | 1024 | 1074 |
| Sv39 dependent store/readback | 1173 | 1223 |

R1 is the only configuration/core-parameter difference within either equality pair. The +50
work-cycle (+49 ROI-cycle) VM cost belongs to the independent M2 translation stage, not R1.
The CPU exercised partial consumes (branch 1; VM 109/205) and accepted-successor validation,
unlike the supply-only fixture whose `expectedNext` is inactive. Actual
`acceptedPrefixValidation=false` is retained throughout; the future true specialization is
not qualified here. Full RV64GC resources, ROB16/PRF48/LSU4/DTLB16 and 32KiB L1I/L1D were retained;
the VM workloads cover one supervisor data page/cache line with preset A/D, not broad VM/ISA
or memory-bandwidth qualification. Rebuilt tools retain pinned revisions, not binary identity
with the earlier P1 environment; the two retained P1 CPU control cases also matched exactly.

`full-r1` is the recommended explicit experiment for the next development comparison, not a
change to `Selected`/`FullCandidate` defaults or a timing sign-off. The added read muxes and head
fanout still require physical evaluation before claiming a net implementation gain. No new
synthesis, STA, CDC, board, Linux or full-regression result is claimed.
