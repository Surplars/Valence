# r24 WIP3: combined backend and native fixture

Native end-to-end switching is NOT yet qualified at this checkpoint.

The eight frozen FPGA backend commits are merged, including pre-synthesis
CPU300/fabric250 constraints and separate actual boot50 evidence contracts.
The shared source replay of behavioral backend and 81 Python checks passed.
No vendor primitive, STA or board result exists; production rate tables are empty.

Actual FixedClockSafetyGuard component: 16 positives and 4 ordinary observation
negative controls passed. Exact source/RTL/tool/log bindings are archived.
Full actual CommonMachinePlatform fixture with only a test table and shortened
PHY startup/poll policy waits256/512 emitted272 SV. Real MDIO remains125MHz.
A protected bank-construction hook allows this test without duplicating platform
wiring; the default hook constructs the identical bank configuration. Default
RTL comparison after this hook remains pending (WIP2 prior actual248/248 passed).

Guest writes real aligned64-bit MMIO at CPU0x10080800 and fabric0x10080880,
sequentially100 then50MHz. It waits actual completed counters, errors0 and
actualHz. Normal native case r3 is in progress; all clocks run during legitimate
cold bootEnable hold until genuine PHY readiness. No fake drain ACK/terminal
or preboot source acceleration is used. MMCM primitives are explicit behavior
models driven by actual DRP registers, not vendor primitives.

Initial r1/r2 attempts failed strict unknown-state checking before boot because
initially-high TB reset did not reliably generate asynchronous assertion into
yet-clockless managed domains. They are preserved, not accepted negatives.
An explicit0->1 common reset pulse removed those startup unknowns in r3; no
assertion is waived. At0.5ms modeled time the first9 real PHY transactions had
completed. The currently approved host bound is300s; any larger bound requires
explicit approval and changes no DUT/guest/protocol timing.
