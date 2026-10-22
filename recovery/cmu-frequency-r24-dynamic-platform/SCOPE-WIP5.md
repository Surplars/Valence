# r24 WIP5: executable ROM initialization repaired; full loop still running

This checkpoint is NOT a complete dynamic-frequency pass or physical qualification.
The first full normal attempt r4 reached genuine PHY readiness/51 MDIO transactions,
but then retired no instructions. Independent inspection proved its compiled
executable omitted both ROM initializers: ENABLE_INITIAL_MEM_ was missing.
Raw RTL path presence was insufficient to prove executable ROM loading.

The original r4 RUNNING receipt, logs and exact test inputs are preserved beside
a separate cancellation/diagnosis record. The tool session ended130 on cancellation;
the runner did not finalize a child-reap receipt. No natural timeout, normal checker
failure, or proven runner reap is claimed for that interrupted attempt.
A separate12us observation-only trace confirmed released reset, real clock progress,
open gates and ready CDC links, then X instruction/control state from unloaded ROM.

The corrected runner explicitly enables only the ROM initializer, not randomization.
It checks exactly two frozen ROM loads in preprocessed RTL and the VVP executable.
The TB validates actual memory first words after time-zero initialization, checks
valid instruction/control for X, and bounds first retirement to1000 AON cycles after
boot. Every full run now automatically executes a same-binary early-first-retire
smoke before waiting for the real PHY. This early fixture boot is diagnostic only.

Standalone corrected smoke passed at3.02us: first PC0x80000000, instruction0x10081437,
CPU26cycles, both CDC links ready. The final r5 runner's automatic smoke also passed
before entering its ordinary full normal900s run; the start receipt remains RUNNING.
Real MDIO125, PHY policy waits256/512 and all DUT/protocol timeouts are unchanged.

A persistent output STOP file is now checked while each child runs; finally kills
and waits any live owned process. A separate lifecycle-only test canceled an actual
compile child: runner1, child-9, canceled=true, reaped=true, timeout=false, finalFAIL
receipt retained. This is a runner-lifecycle check, not DUT negative qualification.

Production rate tables remain empty. No vendor primitive, STA, board, new MAC
admission, or current-source default-off comparison result is claimed here.
