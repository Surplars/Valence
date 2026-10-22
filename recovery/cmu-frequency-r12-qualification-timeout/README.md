# R12 opt-in full-qualification timeout

This isolated stage extends the r11 controller/epoch adapter, not the production platform. A matching first `held` observation begins a separate full-qualification watchdog. Losing `held`, receiving partial ACKs or waiting for complete system qualification does not restart it. At first-held edge C, the counter starts at zero; expiry at C+N takes priority over complete ACK qualification. Initial r10 abort has still higher priority and does not emit a redundant local cancel. Arbitration waiting before an accepted prepare starts neither local qualification phase nor an invented controller timeout.

Local expiry keeps the old clock enabled and quiesce asserted, retains the token/epoch, and offers cancel until the real r10 boundary accepts it. Terminal consumption is forbidden before that handshake. A local qualification cancellation requires `canceled=true,timedOut=false`; an r10 initial-drain timeout requires both flags true. Wrong tags or reason flags cannot complete a newer or different transaction. Actual terminal consumption, real fabric retirement and the controller's backpressured retired receipt remain separate. Loss of lock/open proof and a late sticky cleanup fault cannot be hidden by terminal or boundary retirement.

The two controllers share the existing serial adapter owner. No full drain ACK, gate-closed/open witness, program response or DRP configuration is manufactured. Production backend-present and runtime whitelist remain unchanged. A1 support is not added. The optional constructor remains off by default.

## Ownership and liveness

- R10 owns initial epoch-drain timeout and endpoint cleanup timeout; it stops the initial watchdog after genuine qualified epoch observation.
- The selected controller owns this new post-held full-system qualification timeout.
- A local timeout sends a normal requester cancel into r10, so r10 does not claim its initial-drain timeout fired.
- Matching cancel backpressure, permanent accepted memory/interrupt owners, missing terminal or retirement, and missing safe clock proof can block indefinitely. This is safe retained ownership, not promised bounded recovery or immediate revival. Progress or coordinated common cold reset is required.
- The defensive component test injects simultaneous initial-abort/local-expiry. Real r10's qualifiedOnce prevents that collision after genuine held; component evidence must not be mislabeled as an integrated occurrence.
- Reset coverage means coordinated boundary/controller common reset, never unilateral endpoint reset or arbitrary live epoch reuse.

## Validation

Component validation passes 723 cycles and two independent negative oracles using real controller/adapter with an explicitly modeled boundary. It checks exact 32-edge deadline, revoked proof, partial ACKs, full-ACK/deadline priority, 40-cycle cancel backpressure, terminal-before-cancel rejection, wrong reason flags, matching retirement, defensive initial-abort priority, pending-cancel common reset, queued ownership, and late-fault/clock-proof retirement regressions. Modeled complete ACK/gate/program signals test only controller protocol; they are not physical qualification.

Two added component runs failed because the new reset test began its timing assumption before the adapter's real captured-epoch edge. Exact failing TB versions, FAIL receipts and logs are preserved. The correction waits for that capture before first held; no production logic or assertion was weakened. The original r11 tests remain in the same suite.

Fresh compilation and all three ClockRateControlSpec tests pass. All 248 default-off performance300-static SV files are byte-identical to the r11 baseline. The real-module run passes both original r11 ratios, both new qualification ratios and all three independent wrong-data, previous-store and IMSIC-pending negative controls. All current source, RTL, tool and guest inventories pass the runner’s before/after drift checks; source entries were also independently rehashed. The real fixture keeps all full-system drain ACKs zero, allowing actual held and actual controller qualification expiry but never clock closure/programming. Its allowed 55 MHz point and startup lock/open inputs are explicit test-only models, not production signoff.

IRQ capture while fabric clocks stop, actual IRQ trap/claim/mret and AMO/LR/SC combinations, complete peripheral admission, true clock-gate witnesses, official generated DRP configuration and physical closure remain prerequisites. This stage does not change the hardware-default 50 MHz goal, optional U-Boot/direct BootROM-to-Linux chain, or CPU300/fabric250 performance constraints. No actual clock-rate switch or board qualification is claimed.

Publication remains blocked pending explicit approval for the prior r10 metadata receipt. Local commits and tests must not be described as pushed until remote ref/tree verification succeeds.

## Real three-clock observations

CPU/fabric/AON half-periods 5/7/11 and 11/5/7 ns use phases 0/2/3 ns. Both qualification runs first observe actual matching I1/fabric held, never provide full ACKs, and see cancel.valid at exactly 64 AON edges after first held and cancel.fire at edge 65. Both controllers complete one canceled epoch each only after real terminal/fabric/CPU-resume handshakes. Actual r10 initial timedOut remains false, and no cleanupFault is manufactured. Terminal backpressure retains the fabric admission barrier and queued requester. After resumed operation, three MSI IDs arrive once each with three replies and pending bitmap 0x3800; independent RAM/store/previous-value ledgers pass 11 loops for the first ratio and 10 for the reverse.

The original r11 paths also remain passing at both ratios: three initial 4096-edge timeouts, retained real dirty ReleaseAck through the cleanup watchdog, actual cleanupFault, and six MSI requests/replies. Those original timeout tests are separate from the two new post-held local timeout outcomes.
