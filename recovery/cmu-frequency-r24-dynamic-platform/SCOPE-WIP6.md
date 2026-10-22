# r24 WIP6: preserve real partial-loop failure; correct observation budget

This checkpoint is NOT a complete dynamic-frequency pass. No vendor primitive,
STA, board, new production rate admission, or current-source default-off result
is claimed. All production software rate tables remain empty.

The corrected executable passed its automatic first-retire preflight, then ran
the full real PHY startup and software loop with 516 production assertions enabled.
The r5 terminal receipt is ordinary FAIL at the testbench's absolute 5 ms cap,
not a host timeout: 839.715324 wall seconds, exit 1, timeout false, reaped true.
CPU 50 -> 100 -> 50 completed two exact epochs/programs/results/retirements.
Fabric 50 -> 100 completed; its real request to return to 50 was still draining.
Three completed transitions do not constitute the four-transition success oracle.

Real PHY boot occurred at 2.622820 ms after 51 complete MDIO commands. CPU request,
held, and completion times were 2.625990/3.241570/3.245370 ms and
3.247330/3.863850/3.867790 ms. Fabric times were
3.872710/4.486250/4.489770 ms; its final request was at 4.491810 ms.
The archived original receipt, logs and exact test inputs are preserved.
A separate archive verification checks 1246 frozen inputs plus tools and binary;
the two subsequently changed test files are checked against their exact archived
copies rather than falsely calling the current edited copies identical.

Static inspection corrects an earlier tentative latency attribution: the dominant
~0.615 ms wait is a residual complete PHY poll, not a Home/cache directory scan.
The PHY must restore/check the default page before parking. Twelve MDIO commands,
each 128 * 50 transfer cycles plus two command/reply cycles at fixed 125 MHz,
take 614.592 us. Full-size 32 KiB I/D invalid scans each contain 512 rows and run
concurrently; their scan term is 10.24 us at the slowest managed frequency, 50 MHz.
Home drain is a true outstanding-owner/idle predicate, not a directory walk.
No cache, directory, FIFO, or owner capacity has been reduced.

Only the TB absolute observation cap changes from 5 to 6 ms. Passive 100 us drain
traces expose real CPU/fabric holds, owner idle, fixed MAC control park, and PHY
operation progress. The sole normal case may use the approved 1200 s host cap:
the measured 5 ms / 839.715 s rate predicts 1007.658 s for the full 6 ms observation
window, leaving about 19% scheduling margin. All DUT, MDIO, guest and protocol
timeouts remain unchanged, as do real fixed-125 MDIO timing and fixture-only PHY
policy waits 256/512. The next fresh normal run has NOT started at this checkpoint.

The runner now records frozen input/tool/binary comparisons even for an ordinary
failed run; it retains the existing persistent STOP-file and finally kill/wait
lifecycle and always runs same-binary first-retire preflight before the normal run.

Normal-only observation planning uses a 5.6 ms engineering envelope: startup
<=2.7 ms, four transition slots of 0.7 ms, and <=0.1 ms final guest/ledger margin.
Each transition slot includes the source-derived full residual poll 614.592 us,
a conservative serial addition of the concurrent cache scan term 10.24 us, and
75.168 us allowance for CDC, core, backend and guest progress. The allowance is
an engineering margin, NOT a mechanically proven complete cycle bound or a bound
for arbitrary backpressure/fault/timeout combinations. Normal behavioral DRP has
fixed two-cycle response latency, nine transactions (three words, each read/write/
verify), then 20 reference-cycle lock latency plus actual synchronization/stability.
No normal RX, JTAG, packet DMA or DDR traffic is injected by this ROM-only fixture.
