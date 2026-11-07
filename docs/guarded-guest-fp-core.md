# Guarded guest FP core qualification

This explicitly selected, default-off profile joins the actual `MachineCore`,
MSU, ROB, protected owner, dual-FS FP system, instruction assembler and nested
fetch/data translation path inside `HypervisorMachineCore`. It is a restricted
qualification route, not general guest F/D availability. Other H+FP combinations
remain rejected by both constructor guards. Production defaults, selected board
profiles and ISA/firmware advertisements do not change.

## Exact admission and wiring

`guardedGuestFpQualification` selects one fixed shape: two-wide rename,
completion and retirement, ROB16, PRF48, memory capacity two, 64-bit tags,
C, machine-system operation, H, Sv39 and PMP16. The FP subset is F/D
moves/sign/class plus memory, with numerical arithmetic groups disabled and
FPGA committed-state storage. Untested geometry, resources, host-only memory
proofs, atomics, counters and posted/tagged memory are not admitted through this
selector. The canonical parameter recipe and configuration rejection tests are
the source of truth for every frozen field.

The MSU enables the real dual-FS state and H floating-point contract. Architectural
V and VS FS feed FP state directly; actual retirement/CSR mutation updates the
captured owner. Effective memory translation context retains its existing
separate path. No owner, ROB, selector, LSU, translator or trap-admission
algorithm is replaced. In particular, MSU trap readiness must not wait for FP
architectural busy: an exceptionally completed FP instruction retains busy until
its genuine trap flush.

## Software and observation boundary

The fixture fetches the encoded input program through the real instruction
translation/assembly path. The only drivers are cold reset, enable/commitEnable
and physical instruction, data and PTE transport. IRQ/MSI are inactive and there
is one clock. No SystemRequest, status, FPR/fcsr, result, retirement token or trap
is injected. Passive probes observe all 32 FPRs, fcsr, host/VS FS, protected owner,
accepted starts/completions, retirement, real traps and memory/translation drain.

The frozen program, PTE/byte image and external service laws live in
[`guarded_guest_fp_core.json`](../simulator/gsim/config/guarded_guest_fp_core.json).
The narrow software contract includes M boot and HS/VS entry, nonidentity guest
FLD/FSD and move readback, both host-Off and VS-Off instruction denial, both
fcsr-CSR denials, misaligned FLD and explicit G-stage denial. Real ROB-generated
VS-to-HS traps execute a handler that reads scause, sepc, stval, hstatus, htval and
htinst, then resumes using real SRET. Faulting operations must not retire or
mutate FP state, and younger poison stores must not escape. This is not an
in-flight younger-load cancellation experiment.

Software performs eager host/A/B/A/host all32-FPR/fcsr save/restore using distinct
images and saved-memory regions. There remains one physical bank, and FS=Initial
is metadata rather than initialization. Correctness for the exact software and
images does not establish general-purpose software isolation or complete F/D
ISA compliance.

Two matched transport schedules and genuine commitEnable holds exercise held
retirement and delayed automatic trap admission. Native C++ and separate Python
oracles derive instruction, state, translation and byte expectations from the
frozen inputs. Data-request and nested data-PTE sequences are checked against
independent walks, including absence of a final physical access on G denial.
Fetch uses genuine translation with physical-response byte and retired-program
checks; canceled speculative fetch-walk prefixes are not separately qualified.
Linked raw pre/post observations cover every edge; complete state interning and
sparse-zero probe encoding are lossless, not event filtering. They are retained before named
Python replay checker-sensitivity controls. These thirteen named, in-memory
corruptions reuse preserved pristine traces and are not native-oracle or RTL
mutation coverage.
Crashes, sanitizer findings, timeout and incomplete evidence are failures.

## Reproduction and resource contract

```sh
mill -i IonSoC.guardedGuestFpCore.compile
mill -i IonSoC.guardedGuestFpCore.testOnly \
  ooo.GuardedGuestFpCoreConfigSpec ooo.DualFsPreparationConfigSpec
make gsim-guarded-guest-fp-core-test
```

Compile every production and HardFloat source and the focused test sources
fresh. Use the strict repaired cloud-tools binding, verified offline dependency
cache and one new ASan/fatal-UBSan GSIM model. Host orchestration tests are
mock-only, not hardware evidence. Actual counts, cycles and outcomes belong to
the source-bound run receipt; a listed test contract is not a passing result.

The native bounds are 240,000 cycles, 24 MiB of raw evidence per schedule and
120 seconds. They account for the encoded software, repeated nested walks and
bounded external stalls. The independent prebuild review binds source, encoded
input, schedules, these limits, negative controls and tools before heavy execution.
The supervisor preserves old and failed artifacts and caps aggregate new outputs
at 512 MiB including a 64 MiB packaging/review reserve. Admission floors are
768 MiB workspace, 128 MiB /tmp and 3.5 GiB available RAM. Hard reserves are
128 MiB workspace, 96 MiB /tmp and 1 GiB RAM, with at most 16 MiB /tmp spill.
Process-tree RSS is capped at min(3.5 GiB, launch available RAM minus 1 GiB).
Only one heavy phase runs at a time within the 1,200-second batch budget. Limits
are abort criteria, not measured fit or hardware performance.

## Not qualified

This increment does not establish full numerical F/D behavior, VU behavior,
IRQ/fault overlap, in-flight fault cancellation, M-origin guest faults, live reset,
independent clocks, a stock OS, PPA, synthesis, board operation, Yosys or Verilator
coverage. Generic H+FP admission remains closed after the restricted tests pass.
Prior component evidence in [guarded fault recovery](guarded-fp-fault-recovery.md)
remains a distinct external-trap-consumer result, not retroactive CPU evidence.

Follow-on: [guarded guest FP add/sub qualification](guarded-guest-fp-arithmetic.md)
uses a separate exact default-off selector. It does not change this moves-memory
recipe or turn the historical result into numerical coverage.
