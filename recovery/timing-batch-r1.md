This candidate follows routed diagnostic baseline b75abd894d5dda25a83f7601ad2d7a1dd0760260.

Status: actual generated-DUT native xsim and affected configuration checks passed. CPU300/fabric250 diagnostic route completed, still failing setup. Exact hashes, comparison and limitations are in timing-batch-routed.json; directed tests are in timing-batch-validation.json.

- IMSIC: compute each selected bank's CSR write/set/clear from that bank's old state. Keep the queued old read response, priority/claim rules, concurrent MSI precedence, and response credits unchanged. This removes TOPEI priority selection from unrelated threshold write enable/data.
- GMAC: use exact aligned page equality, and qualify MDIO credit from the complete legal MDIO-start condition. General CSR legality remains on response/side effects, outside upstream ready. Invalid MDIO requests must still be accepted and denied without command credit.
- Neither change introduces pipeline stages or changes request/response latency.

The baseline's CPU300/fabric250 clocks and all active path budgets remain fixed. Native generated-DUT scoreboards check architectural state, responses, backpressure, and concurrent events before production export. The original revision4 vendor debug-hub timing contract was recovered exactly from the hashed original export; its helper validates IP SHA, USER1, clock periods, and endpoint cardinalities. No CDC waivers are restored. Full baseline STA recalculation remains separate from measured RTL improvement.

Preserve the r11 routed checkpoint (SHA256 99c8880cf540305e6bd3f500214b7d5d964fb585db2d9d0b73d22c21db77d456). Its WNS -7.411 ns/TNS -68247.391 ns are failing diagnostic results, not acceptance criteria already met by this candidate. No bitstream or board validation is included.

With the exact vendor contract restored, the unchanged r11 baseline is WNS -3.125 / TNS -67188.742 ns. Candidate f6f04c4 has WNS -2.524 / TNS -38582.219 ns (42.6% lower magnitude TNS), WHS +0.002 / THS 0. CPU TNS improves 51.0%, fabric 37.5%; target rates remain unchanged. LUT -214, FF -33; BRAM/DSP unchanged. All 182107 nets routed with zero routing errors. No bus-skew violation. All 21 remaining CDC Critical targets are reset PRE/CLR; none is a data target. Reset/IO/board signoff remains open.

Exact old IMSIC pending-to-threshold CE path no longer exists although both pins remain, with no effective exception. Exact old fabric ready path remains at -2.070 ns versus -3.125 ns. Routed MIG matches all 73 direct connections, pins and IO standards. Its fresh read-only re-open has zero Critical Warnings; stale linked-XDEF restoration warnings did not reproduce after full placement/routing. See timing-batch-root-review.json.

New routed checkpoint SHA256: a5567bf8c99bfa09098bc4653d1c9bf7e795be1233f16501237839ec27a95cd1. Preserve it as the next batch's rollback. Fixed-layout setup estimates are about180MHz CPU /156MHz fabric; these are not verified Fmax or board results.
