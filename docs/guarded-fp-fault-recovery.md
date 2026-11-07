# Guarded FP memory and fault recovery

Historical component result: the subsequent [guarded guest FP core
qualification](guarded-guest-fp-core.md) introduces a separate, explicit narrow
constructor exception and real software-driven test. The component evidence
and external-trap limitations documented here remain unchanged.


This test-only system contract composes genuine `FloatingPointSystem(dualFs = true)`,
`ProtectedSystemOwner`, `MemoryDomainSelector`, `HypervisorState(floatingPoint = true)`,
`GuestDataTranslationAdapter` and `GuestTranslationService`. Production hardware,
public defaults, ISA/firmware advertisements and both actual-core H+FP rejection
guards remain unchanged. This is not guest F/D enabled in a CPU.

The small FPGA committed-state profile keeps F/D moves and memory, with numerical
arithmetic groups disabled. Real encoded commands enter the FP system. Physical
memory and PTE responders supply only genuine memory data; no FP result or FPR
state is injected. The one physical all32-FPR/fcsr bank still requires software
initialization and context save/restore before any isolation claim.

## Narrow lifecycle contract

The [frozen recipe](../simulator/gsim/config/guarded_fp_fault_recovery.json)
defines the exact encoded commands, PTE and byte image, external service laws and
checker controls. The two matched external-service schedules execute eleven instructions: host
FMV.D.X seeds f0, nested nonidentity guest FLD fills f1, guest FSD writes a distinct
translated location, and four fault/recovery pairs exercise each joint-FS denial,
a misaligned FLD and an explicit G-stage-denied FLD with VS Bare. Each fault is
followed by real FMV.X.D readback of f1 without repairing or reseeding FP state.
There are seven successful commands and four exceptional completions. A chosen
nonzero fcsr must survive unchanged. Store bytes and neighboring bytes are checked.

All successful commands retain their full owner through exact-token retirement.
For a fault, completion backpressure retains the complete envelope and owner.
Exactly one accepted exceptional completion releases the protected owner and FP
memory epoch. At that point all real memory queues, adapter and translator must
already be drained. Architectural FP busy remains true, new-start credit remains
false, and the real once-sent bridge suppresses duplicate completion while the
caller delays its trap. Owner inactivity is not permission to replace context.
No fault token is committed. The later drained trap flushes real FP state without
architectural mutation; only later idle cycles may restore guest context.

The synchronous VS-to-HS trap is **external caller stimulus**. Its PC, cause,
tval and guest provenance must independently match the accepted command and
exceptional completion. It enters the actual FP trap/flush and H-state trap
consumer, with hedeleg clear, interrupts inactive and privilege fixed to S
(VS before trap, HS after). H-state V/SPV/GVA/HTVAL observations are consumer
checks. This fixture has no real ROB or MSU trap admission, HS scause/sepc/stval
handler execution or software isolation. It does not synthesize a replacement
trap-admission state machine.

Architectural V remains distinct from effective memory translation context. The
production translation helper controls translated handling. Status, CSR, guest
context and PMP setup require the complete FP lifecycle to be idle. Passive
observations cover all32 FPRs, fcsr, both FS banks, complete full owner, bridge
handshakes, memory occupancy, drain and selector domain before and after edges.

## Reproduction and evidence

Use the pinned repaired `cloud-tools-20261030-r2` binding, `setup(False)` and the
verified offline dependency cache. Compile all production and HardFloat sources
fresh along with the focused fixtures; reuse no earlier classes or model. Both
actual-core constructor guard tests remain in the existing default checks and
new subset checks.

```sh
python3 -m unittest discover -s simulator/gsim -p test_guarded_fp_fault_recovery_entry.py -v
mill -i IonSoC.guardedFpFaultRecovery.compile
mill -i IonSoC.guardedFpFaultRecovery.testOnly \
  ooo.GuardedFpFaultRecoveryConfigSpec ooo.DualFsPreparationConfigSpec
make gsim-guarded-fp-fault-recovery-test
```

One fresh ASan/fatal-UBSan GSIM model serves both short schedules. Independent
C++ and Python ledgers derive expected architectural state, faults, translations
and byte effects from input instructions/PTEs/memory. Raw pre/post observations
are linked across actual samples. Complete unmodified traces are saved before
named local checker mutations. Exact diagnostics and exit 1 qualify those
checker-sensitivity controls, not RTL mutant coverage. Crashes, sanitizer
reports, timeout, missing or truncated traces and incomplete coverage always fail.
Host orchestration tests are mock-only and are not hardware validation.

The native bounds are 2,048 cycles, 4 MiB per trace and 120 seconds. The supervised
batch retains all earlier and failed artifacts and limits aggregate new outputs
to 512 MiB including a 64 MiB packaging/review reserve. Workspace/RAM admission
floors are 768 MiB/3.5 GiB and /tmp admission is 128 MiB. Hard reserves are 128 MiB
workspace, 96 MiB /tmp and 1 GiB available RAM, with at most 16 MiB /tmp spill.
Actual process-tree RSS must stay below min(3.5 GiB, launch available RAM minus
1 GiB). One heavy phase runs at a time with a 1,200-second total batch cap.
These are abort limits, not predicted fit or performance evidence.

## Remaining release boundary

The next actual-core gate needs a separately authorized default-off combined
MSU/ROB profile and real software-driven owner, context and precise trap
qualification. This increment does not remove that gate or add dead MSU wiring.
No automatic CPU trap admission, numerical F/D compliance, eager host/two-guest
all32 context isolation, IRQ/fault overlap, in-flight cancellation, M-origin
guest-fault review, live reset, independent clocks, full OS, PPA, board,
synthesis, Yosys or Verilator claim follows. Pinned RISC-V v20250508 H 1.0,
Machine 1.13, F 2.2 and D 2.2 references from the preparation documents apply.
