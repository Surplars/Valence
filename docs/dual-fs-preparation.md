# Dual-FS state-component preparation

This is preparation for future guest F/D integration, not an enabled guest F/D
profile. Both `MachineSystemUnit` and `IntegerBackend` still reject H+FP. Existing
H/A/counter defaults, numerical/resource configurations, `misa.H` and firmware
advertisements are unchanged. No FP memory or guest-fault transport is added.

## Production contract

`FloatingPointState(p, dualFs = true)` adds an optional guest context and mutation
event. The default is false, preserving the ordinary host state interface. There
is one host FS owner and one shared physical bank of 32 FPRs plus fcsr. The guest
context supplies architectural V and the existing VS FS from `HypervisorState`.

With V=0, host FS alone authorizes FP. With V=1, both host and VS FS must be nonzero.
A denied FP command completes with illegal instruction, cause 2, without offering
a producer request. FP CSR denial is exposed through the state component's
`csrIllegal` interface; this component has no CSR trap envelope. It does not prove
an actual guest MSU CSR trap, because H+FP remains unavailable.

Accepted issue captures the guest owner until retirement. A successful,
full-token retirement modifying an FPR or fflags dirties host FS and emits that
captured owner. A legal accepted fflags/frm/fcsr write uses the accepting cycle's
context and existing write-intent semantics, including same-value writes.
`HypervisorState` consumes guest mutation events to dirty its separate VS FS.
Host mutations do not dirty VS FS. Read-only CSR operations, rejected commands,
unretired completions, wrong retirement tokens and faulting results do not mutate
architectural FP data or Dirty state under this implementation's precise policy.
Numerical NV/DZ/OF/UF/NX remain accrued flags, not synchronous traps.

The shared production `FloatingPointStatus` helper supplies joint authorization,
host/guest status-write targeting and derived FS/SD bits. Actual MSU CSR legality
and host status routing use it, as do the genuine state components. Guest sstatus
targets VS FS; host mstatus/sstatus and direct HS vsstatus accesses target their
respective owners. The surrounding MSU still owns instruction privilege and CSR
legality. Component status writes are preauthorized writes, not a replacement
for those checks.

The actual `FloatingPointSystem` does not enable dual-FS ports, and the actual H
MSU does not enable HypervisorState's FP option. The combined optional interfaces
are exercised only by the dedicated component fixture in this phase. No test-only
constructor bypass was added.

The caller must not replace a VS context image while an FP owner is pending.
Capturing V identifies host versus guest ownership; it does not identify a guest
VM or validate a future CPU context-drain protocol. Status writes and mutation
events must be serialized. If they coincide at the component boundary, Dirty
wins. Setting FS=Initial changes metadata and does not initialize register data.
Explicit software initialization/save/restore is still required for isolation.

## Focused validation entry

`make gsim-dual-fs-preparation-test` uses the strict pinned repaired GSIM binding,
ASan/UBSan and two freshly generated state models:

- `DualFsPreparationGsim` connects genuine FP and Hypervisor state using the
  production helper/event contract. It selects the existing FPGA state-storage
  topology to exercise delayed committed-array writes and forwarding. No
  arithmetic unit, CPU or guest memory is instantiated. HypervisorState retains
  its ordinary interrupt logic, but external/nominated interrupt inputs remain
  inactive and no interrupt scenario is exercised.
- The unchanged `FloatingPointStateGsim` and host driver provide compatibility
  coverage for the ordinary baseline state-storage topology.

The new independent C++ oracle covers the host-FS × VS-FS matrix in host and guest
contexts, FCSR aliases, independent status/SD targets, denied accesses without a
producer offer, held completions, successful/faulted/full-token retirement and
explicit transport of three distinct 32-FPR/fcsr images. Its synthetic producer
results are component inputs, not evidence of executed floating-point arithmetic.
Live V perturbation stresses captured component ownership; it is not claimed to
be a legal CPU context switch. Named negative controls must fail at their specific
independent oracle, never merely through a sanitizer failure.

The focused `IonSoC.dualFsPreparation` module compiles all production dependencies
and only the two state fixtures plus the new configuration spec and the existing
guest counter/atomic specs. Ordinary `IonSoC.test` remains unchanged. Configuration
checks retain actual H+FP rejection and default/ISA/optional-interface boundaries.
Python entry tests mock orchestration and do not establish hardware behavior.

## Remaining work and limits

Usable guest F/D still requires actual MSU joint-state wiring, combined integer/H/FP
memory ownership, accepted effective guest translation context, owner-aligned
guest-fault response buffering and complete FP-result metadata transport. It also
requires actual guest programs proving precise VS/VU-to-HS traps and explicit
host/guest software context save/restore. None is supplied by this component work.

No guest execution, guest memory translation, automatic per-guest FPR banking,
OS scheduling/boot, complete ISA compliance, PPA, board, multicore or independent
clock claim follows. No M-origin guest-fault or IRQ/fault-overlap experiment is
included. Existing unique evidence must be preserved when arranging build space.

Normative references: [H v20250508 §14.2.11](https://docs.riscv.org/reference/isa/v20250508/priv/hypervisor.html),
[machine FS/SD](https://docs.riscv.org/reference/isa/v20250508/priv/machine.html),
[F](https://docs.riscv.org/reference/isa/v20250508/unpriv/f-st-ext.html) and
[D](https://docs.riscv.org/reference/isa/v20250508/unpriv/d-st-ext.html).
The ISA allows conservative Dirty tracking; the precise policy above is this
implementation's selected stronger contract, not the only ISA-permitted policy.

Follow-on: `guarded-fp-bridge.md` adds the default-off architectural context/event
ports to the genuine FloatingPointSystem and qualifies a limited real arithmetic
subsystem. The earlier state-only evidence above remains unchanged; actual core
H+FP guards and software/context-isolation release gates remain.

Follow-on: [guarded FP memory/fault recovery](guarded-fp-fault-recovery.md) joins
the real FP system and already implemented owner/selector to nested translation
and H-state trap consumption. Drained traps are external caller stimulus, not
automatic MSU/ROB admission. This historical stage and its evidence are retained.
