# Protected FP retirement consumer

This test-only increment composes the unchanged production `ProtectedSystemOwner`,
`FloatingPointState(dualFs = true)` and `HypervisorState(floatingPoint = true)`.
It closes the architectural-state-consumer gap in the earlier owner-only component
probes. It does not enable H+FP in an actual CPU or modify production hardware.
Both `MachineSystemUnit` and `IntegerBackend` H+FP admission guards, public defaults,
the two-issue baseline and all ISA/firmware advertisements remain unchanged.

## Contract and claims

The protected owner captures only a real FP `issue.fire`, with exactly that
instruction and full ROB token. A caller acceptance input admits the real retained
FP completion once per issued owner. Successful completion retains the owner.
The owner's raw `retired` and retained token drive the real FP state's retirement
input directly, without an invented active gate. `headAuthorized` is constant
true, matching `FloatingPointSystem`; flush is false, IRQ/trap inputs are inactive,
and resets occur only at cold idle. Real FP mutation drives real VS-FS state.
Status/CSR setup and V changes are serialized at idle.

Three events are deliberately separate:

1. Valid full-token match against the protected owner's retained token.
2. `FloatingPointState.retireAccepted`, which additionally needs completed FP
   state, head authorization and the exact pending command token.
3. Architectural effects selected by the pending command: an FPR write,
   accumulated fflags and host/guest Dirty mutation.

An idle inactive-token match is not an accepted FP retirement. Conversely,
`retireAccepted` itself has no owner-active condition. A matching completed FP
command can be accepted even if an invalid caller has lost external ownership.
This fixture never constructs that invalid lifecycle. A completed exception can
also drain without architectural mutation, but faulted/inactive drain is excluded
from this first successful-only batch. No claim that *all* inactive matches are
rejected by the FP consumer is made.

FPR observations use the real state's passive architectural view, including
committed-value forwarding. Acceptance updates that view at the retirement edge;
the committed memory's physical write occurs one edge later. Flags accrue only
for `writesFlags`; `frm` remains unchanged by retirement. FPR-only or flags-only
retirement dirties host FS and, for a captured guest command, VS FS. A no-write
command can retire successfully with no FPR, fcsr or FS mutation. Existing status
setup/CSR mutations are counted separately from retirement effects.

The stimuli supply explicit successful result envelopes. Their operation words
and decoded command fields are independently audited, but numerical values and
flags are synthetic. No arithmetic engine, actual ROB, MSU, CPU, LSU or counter
consumer is instantiated. This proves transport and component retirement wiring,
not F/D arithmetic or actual CPU retirement/trap behavior.

## Frozen successful schedules

Baseline and staggered contain 67 and 87 recorded nonreset cycles. Both have
four transactions: host FADD.D writing f0 and flags, guest FADD.S writing boxed
f5 and flags, guest FCVT.W.D selecting flags only, and guest FCLASS.D selecting
neither architectural FP write class. Dynamic rounding uses retained frm=3;
initial flags=1 and synthetic producer flags=2/4/8/16 distinguish OR accumulation
from replacement and ignored flags. FCVT's flags-only retirement starts with
host and VS FS Clean. The final no-write command starts with both already Dirty:
it checks mutation_valid=0 and unchanged architecture, not an independently
observable Clean-to-not-Dirty transition.

The execute holds are 1/3 cycles and completed holds 2/5. Every transaction sees
a stale upper-tag result, invalid and wrong-tag/index grants, and a held
completion whose caller acceptance occurs exactly once. Commit lanes alternate.
The last two commands reuse ROB index 3 and tag low bits while differing in bit63.
The flags-only retirement edge offers the no-write command, but real issue.ready
stays false; on the next edge its genuine acceptance coincides with the retained
old inactive-token pulse. No phantom refill, duplicate retirement or mutation is
permitted. Cold and successful-retained inactive tokens probe each commit lane.

Each schedule expects 13 raw owner match pulses: 4 active successful releases and
9 inactive matches. Real FP retirement accepts 4 commands, with 3 architectural
mutation events, 2 FPR writes, 3 fflags-update events, 3 host Dirty events and
2 guest Dirty events. These count selected accepted writes/events, not necessarily
numeric value changes. The initial idle fcsr setup mutation is excluded from
retirement metrics.

Two cold reset steps precede the recorded schedule. Every raw pre observation is
sampled from GSIM's step outputs; post architectural state is sampled on the next
step and linked to its pre state. One final neutral observation supplies the last
post state. These setup/final observation steps are not advertised as scheduled
transaction cycles. Raw input and all32 architectural FPR observations remain
available; no expected architectural state is learned from DUT observations.

The seven checker controls are inactive_retire_accepted, full_token,
premature_fpr, fflags_loss, guest_dirty, duplicate_retire and refill_credit.
Each mutates a local observation only after writing the complete unmodified raw
trace, then must fail at its exact named cycle/phase diagnostic. The raw trace
must still pass independent replay. This is checker sensitivity, not RTL mutant
coverage.

## Focused reproduction

Use the pinned repaired `cloud-tools-20261030-r2` GSIM/compiler bundle and verified
Scala dependency cache. `setup(False)` rejects an unqualified tool binding and
disables tool fetching. The supervisor additionally uses offline Scala resolution,
fresh workspace-local Mill output/HOME/XDG/native/JVM temporary paths and complete
production plus HardFloat source compilation. Old compiled classes and model
outputs are not reused or mutated.

```sh
export COURSIER_MODE=offline
python3 -m unittest discover -s simulator/gsim -p test_protected_fp_retirement_entry.py -v
mill -i IonSoC.protectedFpRetirement.compile
mill -i IonSoC.protectedFpRetirement.testOnly \
  ooo.ProtectedFpRetirementConfigSpec ooo.DualFsPreparationConfigSpec
GSIM_CXX=clang++-19 make gsim-protected-fp-retirement-test \
  PROTECTED_FP_RETIREMENT_ARGS="--output /absolute/fresh/workspace-output/model"
```

The entry creates one fresh GSIM model, then reuses only that newly built sanitized
executable for baseline, staggered and named negative checker controls. Native
execution has a 512-cycle bound, 1 MiB per-trace bound and 120-second timeout.
Every negative must exit exactly 1 at its named diagnostic with a raw target
trace. Crashes, timeouts, sanitizer failures, missing or truncated evidence,
unknown fields and partial coverage are failures, not successful negatives.
An independent Python replay reconstructs expected state from the frozen inputs,
not the DUT outputs or native summary. Mock-only host tests do not count as
hardware validation. Retain source/tool identities, raw traces, logs, independent
review and resource receipts with any reported result.

## Resource and release boundaries

One heavy phase runs at a time. Admission floors remain 336 MiB free workspace,
128 MiB free `/tmp` and 3.5 GiB MemAvailable. The supervised batch retains a
192 MiB aggregate new-output budget, 16 MiB `/tmp` spill limit and 32 MiB packaging
reserve, with hard reserves of 128 MiB workspace, 96 MiB `/tmp` and 1 GiB available
RAM. The actual sampled process-tree RSS cap is frozen in the run receipt and
never exceeds 3.5 GiB or launch MemAvailable minus 1 GiB. The batch wall cap is
1,200 seconds. These are abort limits, not guaranteed fit. Preserve failed and
partial outputs; never reclaim unique prior evidence to make a test pass.

Actual `FloatingPointSystem` still lacks architectural V/VS-FS/mutation plumbing
and instantiates single-FS state. The H MSU still lacks the FP state integration.
Before any future H+FP enablement, context replacement must serialize the complete
FP-owner lifetime, and actual trap drain, guest instruction retirement and
host/two-guest FPR/fcsr software isolation need separate qualification.
IRQ/fault interleaving, cancellation, M-origin guest-fault review, live-owner
reset, independent clocks, Yosys, Verilator, full OS, PPA and board work are
excluded. Existing pinned RISC-V v20250508 H 1.0, Machine 1.13, F 2.2 and D 2.2
references apply; no new ISA interpretation is introduced.

Follow-on: `guarded-fp-bridge.md` adds the default-off production FP-system bridge
and limited genuine arithmetic qualification. This document records the earlier
synthetic retirement-consumer stage, whose retained evidence remains unchanged.
