# Bounded real managed-control matrix complete

Remaining matrix r3 finished PASS_REMAINING_MATRIX with all child outcomes reaped. Together with exact-source normal qualification managed-accelerated-normal-r5, the four real combined TX positives are complete:

- Unrelated normal: 229.083s/300; timer 42/42; CSR 6/6.
- Unrelated early cancellation: 72.713s/180; timer 17/17; CSR 2/2.
- Reversed normal: 180.182s/300; timer 80/80; CSR 6/6.
- Reversed early cancellation: 78.170s/180; timer 12/12; CSR 2/2.

Every positive passes two 72-byte packets with independent FCS 449789ae, DMA 16/16, AXI R66/66 and B3/3, actual fixed-clock/AON/debug/network/fabric ownership and one joined retirement. Normal cases additionally retain two admission-drop statistics and configuration through park, keep park under AON backpressure, and retire the old epoch without re-draining fresh CSR/timer owners. Both early cancels observe one raw-held edge, zero qualifying held-plus-idle samples and zero runtime park edges; cancellation correctly requires no successful park qualification. Every actual park is still subject to prior matching held-plus-idle history.

Four independent observation negatives also pass expected ordinary-oracle rejection, all on unrelated/normal:

- TX payload: 72.359s/180; byte 2f changed to 2e, rejected by NETWORK_ORACLE_PAYLOAD.
- CSR drain: 74.999s/180; observed drained 0 changed to 1, rejected by MANAGED_CONTROL_ORACLE_CSR_DRAIN.
- Retained statistics: 234.968s/300; actual CSR count 2 changed to 3, rejected by MANAGED_CONTROL_ORACLE_STATISTICS.
- Park retention: 237.186s/300; observed park request 1 changed to 0 while actual AON result remains unconsumed, rejected by MANAGED_CONTROL_ORACLE_PARK_RETENTION.

No negative directly fails merely because selected. Each has the exact observation-injection marker, expected ordinary rejection, nonzero exit, no positive PASS and confirmed reaping. Immutable per-case receipts were independently rehashed and committed as work completed; the final whole-run receipt and aggregate verification are now present.

Source 332, unchanged production 315, original emitted RTL 257, all 11 tool/configuration files and guest/log/assertion/binary artifacts are bound and rehashed. Exact current normal remains independently compared against preserved original same-clock r6. Default performance RTL is independently rechecked 248/248 byte-identical. CPU 300/fabric 250 goals and production-disabled controls are unchanged.

Scope stays test-only preboot source scheduling with actual empty/park/reset/low-phase boundaries, 51 genuine MDIO initialization transactions and permanent runtime source/fabric identity. This does not implement a production fixed-clock control island, full-system drain ACK, gate/DRP/backend, runtime frequency whitelist, physical PHY/MIG/board/routed timing, RX payload, timeout, late-cancel-after-park or simultaneous eight-clock PHY initialization coverage.

All prior FAIL/TIMEOUT receipts and checker errata remain unchanged. The original r5 interrupted child's reaping remains unknown; later process observations do not prove it. This task performed no upload or main-branch modification. The parent reported an upload authorization blocker, tracked separately.
