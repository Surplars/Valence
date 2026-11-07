# Guarded guest FP add/sub qualification

This separate, explicitly selected and default-off profile adds FADD/FSUB.S/D
numerical execution to the genuine translated `HypervisorMachineCore`. It does
not widen the earlier [moves-memory profile](guarded-guest-fp-core.md). That
profile still rejects an unselected arithmetic change. Both constructors reject
generic H+FP, the two selectors are mutually exclusive, and public defaults and
ISA advertisements remain unchanged.

## Exact admission and execution

`guardedGuestFpArithmeticQualification` admits only the earlier fixed geometry:
two-wide rename/completion/retirement, ROB16, PRF48, memory capacity two, 64-bit
tags, C, machine-system operation, H, PMP16 and Sv39. Its FPGA FP resources retain
moves/sign/class and memory, adding only add/sub. Multiplication, division,
square root, fused operations, compare/minmax and conversions remain disabled.
Exact parameter equality excludes unrelated pipeline and memory experiments.

The existing protected owner, dual-FS state, arithmetic units, ROB/MSU completion,
retirement and trap mechanisms are reused without algorithm changes. The
production top selects this exact profile. A source-reused fixture keeps the same
passive probes and instantiates a newly compiled model, not a replacement CPU.
Only cold reset, enable/commitEnable and physical memory/PTE transport are driven.
Architectural V/status, FPR/fcsr, commands, results, retirement tokens and traps
have no external test driver. IRQ/MSI are inactive and there is one clock.

## Numerical and software contract

The [input generator](../simulator/gsim/guarded_guest_fp_arithmetic_program.py)
freezes instructions, operands and PTEs into the
[recipe](../simulator/gsim/config/guarded_guest_fp_arithmetic.json). It does not
supply expected numerical values. Actual M bootstrap enters HS and then VS;
guest loads and stores use the real nested translation path. Actual HS handlers
read trap CSRs and execute SRET after reserved-rounding and joint-FS denials.

Independent C++ integer and Python rational IEEE-754 models derive add/sub results
and flags from the encoded instructions and pre-instruction operands. Ten real
software fflags clears make targeted new NV/NX and no-new-flag behavior visible
rather than masked by earlier sticky bits. Decoded coverage rejects omission of
any of those clears. The focused
cases distinguish the five legal rounding modes, dynamic frm and static override,
S NaN boxing, canonical quiet NaNs, signaling-NaN/invalid NV, signed zero, exact
subnormal results, halfway NX and signed overflow OF|NX. Exact subnormal add/sub
results do not establish underflow-flag coverage. IEEE accrued flags are data,
not synchronous traps. Sticky fflags, CSR read/clear and all32-FPR/fcsr/dual-FS
state transitions must match actual retirement or permitted CSR mutation.

Two matched external transport schedules and real commitEnable holds test owner
retention, completion/retirement ordering and delayed trap admission. Same-edge
accepted completion and retirement are valid; wrong tokens, duplicate acceptance
and fault retirement are not. Complete pristine pre/post traces are retained
before named Python replay checker controls. Those controls are checker
sensitivity evidence, not native-oracle or RTL mutations. Timeout, crash,
sanitizer failure and incomplete evidence always fail.

The earlier all32 host/A/B/A/host context-save run remains separate evidence;
this numerical program does not repeat it or establish general guest isolation.
Physical response bytes and exact nested data-PTE sequences are checked against
independent input walks. Canceled speculative fetch-walk prefixes remain outside
the qualified scope. Scalar fetch does not prove two-lane throughput.

## Reproduction and resource contract

```sh
mill -i IonSoC.guardedGuestFpArithmetic.compile
mill -i IonSoC.guardedGuestFpArithmetic.testOnly \
  ooo.GuardedGuestFpArithmeticConfigSpec ooo.GuardedGuestFpCoreConfigSpec \
  ooo.DualFsPreparationConfigSpec
make gsim-guarded-guest-fp-arithmetic-test
```

All production and HardFloat sources and the focused Scala sources compile
fresh, with strict repaired cloud-tools binding and the verified offline cache.
One fresh ASan/fatal-UBSan GSIM model serves both schedules. Host orchestration
unit tests are mock-only. Actual counts, cycles and outcomes belong to a
source-bound run receipt; this contract alone is not a passing result.

Before heavy execution, independent review must bind the complete source,
encoded inputs, service laws, oracles, negative controls, tools and resource
limits. Native bounds are 180000 cycles, 22 MiB per raw trace and 120 seconds.
The aggregate new-output cap is 512 MiB including failures and a 64-MiB packaging
reserve. Admission floors are 768 MiB workspace, 128 MiB /tmp and 3.5 GiB RAM;
hard reserves are 128 MiB workspace, 96 MiB /tmp and 1 GiB RAM. /tmp spill is
limited to 16 MiB. Process-tree RSS is at most min(3.5 GiB, launch available RAM
minus 1 GiB). One heavy phase runs at a time under one shared 1200-second batch
clock; retries do not reset it. Limits are abort criteria, not predicted fit or
hardware-performance results. All prior and failed artifacts are preserved.

## Not qualified

No full F/D compliance, general H+FP release, arbitrary profiles, VU, full guest
OS/isolation, IRQ/fault overlap, in-flight fault cancellation, M-origin guest
fault review, live reset, independent clocks, PPA, board, synthesis, Yosys or
Verilator claim follows. Pinned RISC-V v20250508 F 2.2, D 2.2, H 1.0 and Machine
1.13 references continue to apply.
