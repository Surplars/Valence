# r24 WIP4: frozen 900-second native normal attempt, still unqualified

The full software-driven dynamic normal loop is still running at this checkpoint.
This is NOT a passing dynamic-switch checkpoint, vendor primitive verification,
STA qualification, or board evidence. Production rate tables remain empty.

The previous normal r3 attempt exhausted its real 300-second host budget after
2 ms of simulated time and 38 real PHY MDIO transactions, before guest boot or
any frequency request. Its original timeout, process-group kill/wait receipt,
logs, TB and runner are retained without rewriting that result.

Root approved a 900-second host-only budget for the first actual normal loop
and necessary narrow reruns. The fresh r4 run uses the same DUT, guest, TB,
MDIO125 source, PHY policy waits256/512, protocol timeouts, strict unknown checks,
and 516 retained production assertion sites. The runner now records its exact
budget and snapshots the test/guest/backend/PHY inputs before running.

The archived r4-start receipt is an immutable RUNNING snapshot, not a final
receipt. It binds the exact source, RTL, tool, guest and simulator inputs.
At checkpoint time the local live run had reached1.5ms,29 real PHY transactions,
with both managed clocks actually booted50 and guest legitimately held until
PHY readiness. No frequency programming or normal completion has occurred yet.

The diagnostic MAC structural review applies only to the previous frozen
production emission. No admission hash/table or qualification was changed.
Fresh production emission/source closure and post-factory-hook actual default
RTL comparison remain pending. Component scope reproduction wording was fixed;
original component receipts and logs were not changed.
