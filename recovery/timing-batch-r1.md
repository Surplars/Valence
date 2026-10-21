This candidate follows routed diagnostic baseline b75abd894d5dda25a83f7601ad2d7a1dd0760260.

Status: source changes only; functional simulation and new physical results pending.

- IMSIC: compute each selected bank's CSR write/set/clear from that bank's old state. Keep the queued old read response, priority/claim rules, concurrent MSI precedence, and response credits unchanged. This removes TOPEI priority selection from unrelated threshold write enable/data.
- GMAC: use exact aligned page equality, and qualify MDIO credit from the complete legal MDIO-start condition. General CSR legality remains on response/side effects, outside upstream ready. Invalid MDIO requests must still be accepted and denied without command credit.
- Neither change introduces pipeline stages or changes request/response latency.

The baseline's CPU300/fabric250 clocks and all active path budgets remain fixed. Native generated-DUT scoreboards will check architectural state, responses, backpressure, and concurrent events before production export. The original vendor debug-hub contract is being recovered separately; no arbitrary asynchronous exception is authorized.

Preserve the r11 routed checkpoint (SHA256 99c8880cf540305e6bd3f500214b7d5d964fb585db2d9d0b73d22c21db77d456). Its WNS -7.411 ns/TNS -68247.391 ns are failing diagnostic results, not acceptance criteria already met by this candidate. No bitstream or board validation is included.
