# r24 dynamic platform integration: WIP1

**Compile/elaboration only. Not native-qualified, not hardware switching, not board-ready.**

Base: validated r23 `475d05ab9164c3348a7721c382eb4b3ff6b96645`.
This checkpoint adds default-off CMU external leases and real control-owner
observations, UART actual STOP/state observation, hard backend-fault isolation,
and an optional R10 release interlock. It does not yet connect a physical backend
or create complete gate permission. All software qualification tables remain empty.

- `IonSoC.test.compile`: PASS.
- Enabled managed bank with real fixed MAC and CMU lease/owner outputs: 69 SV emitted.
- Default performance300-static platform: actual 248/248 SV byte-identical to the
  frozen r16 baseline, no normalization, identical inventory, unchanged sources.
- An initial overly broad `mill -i __.compile` additionally selected the historical
  LegacySoC target and failed on its missing difftest types. Its log is preserved;
  no simulator or legacy emulator was invoked, and no legacy source was changed.
  The focused active target and explicit emissions above succeeded.

## Required next work

Connect the production platform CMU leases to the existing epoch adapter and
actual per-domain backend ports. Add a same-epoch final-close command/commit using
existing command/observation mailboxes: CPU-private, both transport ends, actual
fabric owners, and fixed AXI/timer predicates remain separate. Held snapshots are
not full gate acknowledgments. Actual target lock/open/resumed edges must precede
CPU uncommit consumption, then the real fabric release. Accepted closes must drain
on cancellation even if they never qualified. Stale proof tags cannot satisfy a
new owner. Assertions do not substitute for structural admission closure.

Actual existing board input io.sources is hardwired 31'b0 and programmable input
is absent; this is not permission to mask an external IRQ in another configuration.
UART must actually have STOP=0 and stable-ON control plus all old MMIO/CMU receipts
consumed. A pre-gated UART causes qualification failure, not a forced policy change.

RX-clock watchdog/media state can change while the fixed MAC is parked. A minimum
candidate will explicitly fail closed if this safety qualification changes during
committed gate ownership, with a direct always-running-domain fault path. It must
not claim that a delayed fabric snapshot detects changes while fabric is stopped.
Emergency no-new-admission must also cover fixed debug/MAC when lock is lost with
no active epoch. Retain accepted owners; never invent an epoch ACK, successful
retirement or automatic recovery. Such fatal failures require coordinated cold
reset. Recoverable backend programming errors need independent fallback tests.

The FPGA worker owns the independent AON/CPU/fabric MMCM/BUFGCE/DRP implementation
in its separate worktree. This checkpoint contains none of that worker's changes.
CPU300/fabric250 static performance constraints are unchanged; boot remains 50 MHz.
The first real backend candidate encodes only 50/100 MHz, not the full eventual
5 MHz grid. No untested point is enabled, no remote write is made here, and the
user's requested dynamic local verification is not replaced by a static profile.
