# Guarded guest fused multiply-add qualification

This separate, exact, default-off profile enables FMADD/FMSUB/FNMSUB/FNMADD.S/D
in the actual instruction-fetched `HypervisorMachineCore`. The earlier
[moves-memory](guarded-guest-fp-core.md), [add/sub](guarded-guest-fp-arithmetic.md)
and [multiply](guarded-guest-fp-multiply.md) recipes remain frozen. Generic H+FP,
unselected recipes, mixed selectors and unrelated geometry remain rejected.
No public defaults or ISA/firmware advertisements change.

## Admission and shared product path

`guardedGuestFpFmaQualification` selects the previous fixed two-wide ROB16,
PRF48, memory2, tag64, C, machine-system, H, PMP16, Sv39 and FPGA-resource
recipe with only `fusedMultiplyAdd = true` added to its FP configuration.
Conversions, compare/minmax, divide and square root remain disabled. Two
production files add the selector/profile and top-level choice. No arithmetic,
owner, retirement, trap or translation algorithm changes.

Enabling fused operations selects the existing `FloatingPointRawMultiplyFused`
producer for both multiply and fused operations. Earlier multiply-only hardware
evidence therefore does not qualify FMUL in this profile. A compact mixed
FMUL/FMA dependency and preservation slice is required here. The existing
producer contracts are multiply latency/II 3/4 and FMA 4/5, not a claim of measured
guest throughput. Scalar instruction fetch does not establish two-lane throughput.

## Independent software and numerical evidence

The input-only [generator](../simulator/gsim/guarded_guest_fp_fma_program.py)
freezes actual encoded instructions, operands and page-table bytes in the
[recipe](../simulator/gsim/config/guarded_guest_fp_fma.json). M bootstrap enters
HS then VS. Actual translated loads/stores supply operands and save results.
Real ROB/MSU faults enter HS handlers that read trap CSRs and resume with SRET.
Only cold reset, enable/commitEnable and external physical memory/PTE transport
are driven. All32 FPRs, fcsr, dual FS and protected owner state are passive probes.
Architectural state, operands, results, starts, completions, retirement and traps
are never injected. There is one clock and IRQ/MSI remain inactive.

Independent C++ exact integer dyadic and Python exact Fraction models derive
numerical values and flags from instructions and pre-instruction operands.
FMA rounds once, including cancellation residuals that differ from unfused
multiply/add and direct S results that differ from D-then-S double rounding.
Third-operand capture, rs3-only dependencies, destination aliasing rs3 and
malformed S boxing specifically in rs3 are separate coverage obligations.
All four sign variants in both widths, legal rounding modes across each width,
static/dynamic rounding, static override, reserved modes, signed zero, canonical
NaNs, signaling NaNs and zero-times-infinity even with a quiet-NaN addend are
checked. Coverage does not imply every rounding mode for every opcode.

Finite overflow and inexact underflow use precision-only rounding with an
unbounded exponent for after-rounding tininess, separate from final subnormal
grid rounding. Real decoded fflags clears make new flags and no-new-flag cases
observable; sticky chains preserve flags from older instructions. Joint-FS
permission denials and retirement ownership remain part of this profile.

Two matched external service schedules use baseline request hold0/response1
and staggered hold2/response2+cycle%5, with five-cycle commitEnable holds after
accepted FP or exceptional system completion, once per tag. Same-edge accepted
completion and retirement is legal with exact tokens. Faulting instructions do
not retire; exceptional completion releases the protected owner only after
memory drain, and FP busy remains until the real trap. Complete linked raw
pre/post traces for both schedules must be saved before named Python replay
checker controls. These controls are not native or RTL mutants. Crashes,
sanitizer reports, timeouts, truncation and incomplete coverage are failures.

One physical FP bank does not establish general guest isolation. Earlier eager
all32 context-save/restore evidence is separate and is not mechanically replayed.
Actual translated fetch response bytes and retired instructions are checked,
but exact canceled speculative fetch-walk prefixes are not qualified.

## Reproduction and resource limits

```sh
mill -i IonSoC.guardedGuestFpFma.compile
mill -i IonSoC.guardedGuestFpFma.testOnly \
  ooo.GuardedGuestFpFmaConfigSpec ooo.GuardedGuestFpMultiplyConfigSpec \
  ooo.GuardedGuestFpArithmeticConfigSpec ooo.GuardedGuestFpCoreConfigSpec \
  ooo.DualFsPreparationConfigSpec
make gsim-guarded-guest-fp-fma-test
```

Before heavy execution, independent review freezes sources, inputs, independent
models, controls, tool/cache bindings and program-specific bounds. Compile all
365 production and 18 HardFloat sources plus focused Scala sources fresh, using
the strict repaired cloud tools, `setup(False)` and unchanged 527-file offline
cache. Use unique workspace-local Mill/HOME/XDG/native/JVM temporary paths and
one fresh ASan/fatal-UBSan model. Source-only numerical tests and host mocks are
not hardware evidence; earlier models/classes are not qualification inputs.

The unchanged native abort caps are 180000 cycles, 22 MiB per raw trace and
120 seconds. The final source-bound plan must justify the compact program within
these bounds before building. Aggregate new output is capped at 512 MiB,
including preparation and failed artifacts, with 64 MiB reserved for review
and packaging. Admission floors: workspace768 MiB, /tmp128 MiB, RAM3.5 GiB.
Hard reserves: workspace128 MiB, /tmp96 MiB, RAM1 GiB. /tmp spill is limited to
16 MiB. Process-tree RSS is bounded by min(3.5 GiB, launch RAM minus1 GiB).
Only one heavy phase runs at a time. One immutable first-launch clock caps all
execution, retries, final review and packaging at1200 seconds; it is never reset.
Failure does not authorize enlarged limits. Previous and failed artifacts stay
intact. Hardware results and exact counts belong to source-bound receipts, not
this document alone.

The preceding ee5b041 multiplication hardware qualification and prepublication
review passed, but independent postpublication all-file byte/mode verification
did not finish within that batch's original time cap. That limitation remains;
this new functional batch does not resume or replace the expired review.
Publication of this FMA increment requires separate authorization after the
qualified outcome is reported.

## Not qualified

No full F/D compliance, conversion/divide/sqrt, general H+FP release, arbitrary
profiles, VU, general OS/isolation, IRQ/fault overlap, in-flight cancellation,
M-origin guest-fault review, live reset, independent clocks, PPA, board,
synthesis, Yosys or Verilator claim follows. Pinned RISC-V v20250508 F2.2,
D2.2, H1.0 and Machine1.13 references continue to apply.
