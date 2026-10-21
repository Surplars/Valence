Status: CPU and packetDMA directed native fixtures PASS; production source 38ab4f1. Routed diagnostic complete; setup FAIL, hold PASS. No board signoff.

Baseline: f6f04c4 production RTL, routed DCP a5567bf8c99bfa09098bc4653d1c9bf7e795be1233f16501237839ec27a95cd1; CPU300/fabric250. Preserve all baseline reports and constraints. No added pipeline cycles.

- PacketDMA: its aligned, nonoverflowing 256-byte window admits exact upper-bit equality plus byte offset in all modes. RX_STOP acceptance depends only on that command's own basic legality and data=1. Remove unrelated descriptor validation from RX launch/reset control. Descriptor range/overlap logic, credits, owner counters and response timing stay unchanged.
- CPU: normal store reservation-clear currently inherits general translator READY, whose read-ahead branch contains a late address/permission proof. readHandoff already requires !write && !atomic, so accepted ordinary store is exactly VALID && write && !atomic && !readAhead && normalSlot. Export that factored event from the data translator and consume it at the original clear aggregation. READY, accepted request edges, all other clear causes, owner/drain/barrier and response paths stay unchanged.

The CPU measured path is addrPacket_address[19] → prepared translation grants/fastEligible → request.ready → clearReservation → scalar FIFO4 source_valid → writeBinary[1]/D, -2.231ns,14levels,5.295ns(1.370logic+3.925route). The fabric measured path is FIFO2 valid → scalar selection/address → full-width packetDMA offset/legality → RX control → rxIssued CE, -2.422ns,19levels,6.114ns(1.579logic+4.535route).

Bounded500-path sampling supports those priorities: CPU addrPacket address source264paths/-547.483ns; fabric FIFO2 valid source448paths/-1011.311ns, including packetDMA225targets. These are sampled subtotals, not full-design TNS coverage. Exact collection and limitations are in timing-batch-root-review.json.

The inactive FIFO8 Gray crossing is a separate reachability/model classification; changing its report would not count as an active-logic speedup. Preserve active CDC budgets and the 21 unresolved reset CDC Critical entries. No arbitrary false paths, clock reduction, bitstream or board download.

Historical f6 and candidate using identical production lowering/TB/seed both PASS:4061cycles,743requests=743responses,193stores,196reads,354atomics,3faults,7store-readAhead blocked cycles,1read handoff,656blocked reply cycles,740native requests,18invalidations. Both negative oracles rejected. Default-lowering PMP X reproduced on historical source; production lowering and true cacheable RAM 0x80200000 fix fixture issues without changing production behavior or weakening fault/drain assertions. See validation-store-clear-admission-batch.json. DMA PASS1234cycles,355requests=responses,12memory completions; negative oracle rejected.

Routed result (2026-10-21 07:49:30 UTC, exit0), CPU300/fabric250, compared with 013396e8:

| Domain | Prior WNS/TNS ns | Current WNS/TNS ns | TNS reduction |
|---|---:|---:|---:|
| Global | -2.524 / -38582.219 | -2.219 / -28742.234 | 25.5% |
| CPU | -2.231 / -12507.094 | -1.333 / -6036.505 | 51.7% |
| Fabric | -2.422 / -26029.627 | -2.175 / -22663.119 | 12.9% |

WHS +0.007ns, THS0, no hold failures. All181617routable nets routed, routing errors0. LUT116442(-925),FF75982(-82),BRAM91.5,DSP31,URAM0,IO93. All237frozen inputs unchanged;100shared implementation/constraint script hashes match the prior batch. Routed DCP69aec185f64dea8931db5fde7d8bab51e9dc544ac8832d318cb13b414ba55da5 remains local; no vendor products uploaded. Full native result and hashes: timing-batch-r2-routed.json.

Exact old CPU addrPacket.address19/C to FIFO4writeBinary1/D: both pins exist, no timed path, no valid timing exceptions. DMA FIFO2valid/C to rxIssued6/CE remains a real path but improves -2.422 to -1.552ns;19levels include3CARRY8 versus7before, no exception. MIG73direct/electrical ports match reference on fresh routed open, zero Critical Warnings in that read-only query; routed DCP hash unchanged. See timing-batch-r2-root-review.json.

Remaining worst CPU: address18 replica to D-cache pendingBypass/D,-1.333ns,12levels,4.485ns(1.372logic+3.113route). Remaining fabric: coherent-crossing destinationRelease2/C to home.transfer.reader.sendQueue RAM WE,-2.175ns,16levels,5.754ns(1.247logic+4.507route). Full500-endpoint bounded samples suggest physicalRequests queue address decode/home flow control as the next fabric priority; CPU nextPc/CSR control and pendingBypass are candidates. Sampled slack subtotals are not full-design TNS. No next physical run started.

Ordinary same-domain full-cycle setup estimates, fixed routed clock/skew assumption: CPU214.3MHz,fabric161.9MHz. These are not verified Fmax or an approved clock change; cross-domain/reset/IO and new-rate implementation remain unqualified.

No-clock0/internal-unconstrained0;21reset CDC Critical(10CDC10+11CDC11),0data Critical;DRC86warnings(44DCIRST1),0Error/0Critical. Board signoff is not complete. Raw worst inter-domain Gray paths remain in STA and are not used to infer CPU Fmax. No bitstream/download.

Bus-skew clarification: both this batch and the prior routed report contain86summary entries:84numeric rows with no violations(minimum current slack1.560ns,prior1.663ns), plus2NA rows. Earlier shorthand "no violations" described numeric rows and did not qualify the NA rows. These are crossing_1/empty_fifo_4 and crossing_2/empty_fifo_4, exact RAMD32 DP/CLK to output_0_reg/D, each an observable1-bit payload. They fail inactive proof with observable_nonzero_payload, so are not inactive waivers. Both have explicit3.333ns max-delay/skew scope entries. Exact routed max-delay applicability is being checked separately before classifying why single-bit skew is NA; no NA PASS or relaxed budget is claimed.
