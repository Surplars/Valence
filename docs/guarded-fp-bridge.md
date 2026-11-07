# Guarded architectural FP bridge

`FloatingPointSystem(p, dualFs = true)` now forwards the existing architectural
`guestContext` and `mutation` contract to its real `FloatingPointState`. The
constructor default remains false, preserving the ordinary interface and state.
Architectural V comes only from `guestContext.virtualized`; the existing
`io.virtualized` still means memory translation-active context. The two controls
must not be conflated. No queue, stage, issue credit or arithmetic behavior changes.

Both actual `MachineSystemUnit` and `IntegerBackend` H+FP rejection guards remain.
There is no dead MSU plumbing added to imply full-core integration. This is a real
subsystem feature, not enabled guest F/D in a CPU. The one physical 32-FPR/fcsr bank
still requires software initialization and context save/restore. The entire FP
owner lifetime, through retirement, must drain before replacing a guest context.

## Focused contract and evidence

`GuardedFpBridgeGsim` composes the genuine system, `HypervisorState` and
`ProtectedSystemOwner`. Owner capture uses real `start.fire`; completion acceptance
uses real `complete.fire` and the existing system once-sent behavior. The raw
owner token and `retired` feed the real state's retirement input without an added
owner-active qualifier. Passive observations expose all 32 architectural FPRs,
exact-token accepted retirement, fcsr, FS and mutation. No numerical result or FPR
state is injected. Cold reset only, status/CSR/architectural V setup only at idle,
and no same-cycle refill remain explicit contracts.

The experimental resource-bounded profile includes S/D add, sign/class/moves and
compare/minmax, with the existing FPGA shared-rounder/committed-memory topology.
Multiply, divide, square-root, fused multiply-add, conversions and memory are
absent. It is deliberately not full F/D and is not advertised as such.

Real FMV operations seed operands from an abstract x1 value supplied through the
real SystemRequest operand (no integer CPU or register file is instantiated).
Real FADD exercises exact D addition and S/D
halfway rounding with NX. Dynamic RUP and explicit RNE are independently compared.
FEQ on a signaling NaN supplies NV and a flags-only retirement. Clean-start FCLASS
and FP-to-integer moves check no FP-state mutation. Arithmetic values and flags
come from independently encoded instructions and an input-derived IEEE oracle,
not from observed producer results. All numerical operations are successful;
accrued IEEE flags are not synchronous exceptions.

The frozen schedules contain 264/360 recorded nonreset cycles, respectively,
with completion-ready holds of 1/4 cycles and retirement holds of 2/5 cycles.
Each expects 16 starts/completions/accepted retirements, 49 raw owner match pulses
(16 active, 33 inactive), 11 FPR writes, 5 flags-update events and 12 retirement
mutations (12 host Dirty events, 4 guest Dirty events). Two CSR writes are counted
separately. Final fcsr is 113 (frm=3, NV|NX), with both FS banks Clean after the
no-write tail. Matched baseline/staggered schedules differ only in completion
backpressure and retirement delay. They distinguish host V=0/translation-active=1 from guest
V=1/translation-active=0, test full upper-tag retirement identity, retained and
inactive tokens, held completion, once-only acceptance and dependent no-refill
behavior. Legal idle CSR writes test accepting-context mutation ownership. This
arithmetic-only model does not establish actual translated memory behavior.

The independent native ledger writes complete unmodified raw observations before
checker-negative mutations; the separate Python replay reconstructs expected
state from raw inputs. Named negatives prove checker sensitivity, not RTL mutant
coverage. Missing/truncated traces, schema drift, sanitizer failure, crashes and
timeouts never count as successful negatives. Existing dual-FS component tests
cover FS-Off permission behavior; this successful-only bridge batch does not
claim newly tested denied-command or CSR trap draining.

## Reproduction and scope

Use the pinned repaired `cloud-tools-20261030-r2` binding and verified offline
527-file dependency cache. Freshly compile all production and HardFloat sources;
never reuse old classes or models. The focused module retains default and both
actual-core guard checks, including the experimental subset.

```sh
python3 -m unittest discover -s simulator/gsim -p test_guarded_fp_bridge_entry.py -v
mill -i IonSoC.guardedFpBridge.compile
mill -i IonSoC.guardedFpBridge.testOnly \
  ooo.GuardedFpBridgeConfigSpec ooo.DualFsPreparationConfigSpec
make gsim-guarded-fp-bridge-test
```

One new sanitized GSIM model is reused for short matched schedules and negatives.
The supervised batch freezes a 512 MiB aggregate new-output limit including failed
attempts, a 64 MiB packaging reserve, a 16 MiB `/tmp` spill limit and 1,200 seconds.
Heavy-phase admission requires 768 MiB workspace, 128 MiB `/tmp` and 3.5 GiB RAM;
hard reserves are 128 MiB workspace, 96 MiB `/tmp` and 1 GiB RAM. Process-tree RSS
must remain below min(3.5 GiB, launch available RAM minus 1 GiB). These are reviewed
abort limits, not a pre-existing measurement that the arithmetic model fits.
Preserve all prior evidence and failed attempts. No parallel heavy phases.

No actual ROB/MSU/CPU guest execution, full numerical compliance, trap/IRQ/fault
interleaving, cancellation, M-origin guest-fault review, context-isolation proof,
live-owner reset, independent clocks, full OS, PPA or board claim follows. Core
H+FP admission and complete-owner context/trap/software isolation remain future
release gates. Pinned RISC-V v20250508 H 1.0, Machine 1.13, F 2.2 and D 2.2 references
from the preparation documents still apply.
