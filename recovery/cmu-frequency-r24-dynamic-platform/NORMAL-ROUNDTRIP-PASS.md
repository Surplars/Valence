# r24 first whole-platform dynamic protocol loop: PASS

Dynamic protocol simulation, NOT hardware frequency qualification.

The fresh r6 run completed the actual ROM software MMIO sequence:
CPU 50 -> 100 -> 50 MHz, then fabric 50 -> 100 -> 50 MHz.
The actual full-size I1/CommonMachinePlatform, managed owners, CMU, epoch boundary,
fixed-125 MAC control park and production backend SV participated. MMCM and BUFGCE
were explicitly behavioral stand-ins, not vendor UNISIM primitives.

At 5.115135 ms simulated time, the ordinary success oracle proved four program
accepts, four matching results, four genuine epoch retirements, four MMIO writes,
31 requests/31 replies and 75 instruction retirements. The final fabric change
programmed at 5.109050 ms and completed at 5.112390 ms. Its checker observed 88
managed-clock edges after program before software completion. Both rates ended
at 50 MHz, runtime was idle, real PHY configured/media ready, and no MDIO noAck.
The checker also verified actual managed 10/20 ns periods, no closed-gate edges,
real gate/open/resume evidence and exact epoch/owner/terminal/retirement ordering.

Normal native execution took 786.191 seconds, exit 0, no timeout/cancellation,
child reaped. The same executable's mandatory first-retire preflight passed.
All 516 emitted production assertion sites were enabled. Frozen source/RTL/guest,
tool and VVP binary comparisons remained true through completion. Exact receipt,
logs and test inputs are in roundtrip-normal-r6; normal-verification.json summarizes
the terminal receipt and actual success line without replacing the ordinary oracle.

The extra passive traces confirm that the long drain tail was the existing MDIO
poll owner: CPU held, other fabric/control/fixed owners idle, MAC park requested,
MDIO/PHY not yet parked, operation progressing through the twelve-command poll.
No PHY internal analog implementation was modeled or added. Existing register-level
pin responses merely let the production MDIO policy complete and restore its page.

The previous r5 5 ms observation-cap FAIL remains intact. Only the TB cap increased
to 6 ms and the sole normal host cap to 1200 s. No DUT, MDIO, guest or protocol
limit, clock timing, cache geometry or owner capacity was reduced. Only the fixture
PHY policy waits are 256/512 cycles; real MDIO source remains 125 MHz.

Limits: this normal ROM/MMIO loop injects no packet or DDR payload and no fault or
arbitrary backpressure. Earlier component and r23 owner tests remain separately
scoped. Test-only 50/100 points exercise the controller; production points stay
empty. No vendor primitive, routed timing, board, complete frequency-grid, whole-
platform fault-matrix, or new MAC hardware admission is claimed. Fresh post-hook
production/default-off emissions remain a following source-closure check.
