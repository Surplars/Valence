Status: unvalidated source candidate; native directed fixtures being prepared. No new synthesis or implementation has started.

Baseline: f6f04c4 production RTL, routed DCP a5567bf8c99bfa09098bc4653d1c9bf7e795be1233f16501237839ec27a95cd1; CPU300/fabric250. Preserve all baseline reports and constraints. No added pipeline cycles.

- PacketDMA: its aligned, nonoverflowing 256-byte window admits exact upper-bit equality plus byte offset in all modes. RX_STOP acceptance depends only on that command's own basic legality and data=1. Remove unrelated descriptor validation from RX launch/reset control. Descriptor range/overlap logic, credits, owner counters and response timing stay unchanged.
- CPU: normal store reservation-clear currently inherits general translator READY, whose read-ahead branch contains a late address/permission proof. readHandoff already requires !write && !atomic, so accepted ordinary store is exactly VALID && write && !atomic && !readAhead && normalSlot. Export that factored event from the data translator and consume it at the original clear aggregation. READY, accepted request edges, all other clear causes, owner/drain/barrier and response paths stay unchanged.

The CPU measured path is addrPacket_address[19] → prepared translation grants/fastEligible → request.ready → clearReservation → scalar FIFO4 source_valid → writeBinary[1]/D, -2.231ns,14levels,5.295ns(1.370logic+3.925route). The fabric measured path is FIFO2 valid → scalar selection/address → full-width packetDMA offset/legality → RX control → rxIssued CE, -2.422ns,19levels,6.114ns(1.579logic+4.535route).

Bounded500-path sampling supports those priorities: CPU addrPacket address source264paths/-547.483ns; fabric FIFO2 valid source448paths/-1011.311ns, including packetDMA225targets. These are sampled subtotals, not full-design TNS coverage. Exact collection and limitations are in timing-batch-root-review.json.

The inactive FIFO8 Gray crossing is a separate reachability/model classification; changing its report would not count as an active-logic speedup. Preserve active CDC budgets and the 21 unresolved reset CDC Critical entries. No arbitrary false paths, clock reduction, bitstream or board download.
