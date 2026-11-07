# Guarded guest FP multiplication qualification

This separate, explicitly selected and default-off profile adds FMUL.S/D to the
actual translated `HypervisorMachineCore`. Both earlier exact recipes remain
frozen: [moves-memory](guarded-guest-fp-core.md) and
[add/sub](guarded-guest-fp-arithmetic.md). Unselected H+FP and mixed selectors
remain rejected. Public defaults and ISA/firmware advertisements do not change.

## Exact admission and actual execution

`guardedGuestFpMultiplyQualification` retains two-wide rename/completion/retirement,
ROB16, PRF48, memory capacity two, 64-bit tags, C, machine-system operation, H,
PMP16, Sv39 and FPGA FP resources. It adds only multiply to the previous add/sub,
moves/sign/class and memory subset. Divide, square root, fused operations,
compare/minmax and conversions remain disabled. Exact equality excludes unrelated
pipeline/memory experiments. The old add/sub selector still rejects multiply.

Two production files add the exact selector and top-level choice. Existing
`guardedGuestFpEnabled` wiring preserves constructor guards and real dual-FS/H
connections; arithmetic, ROB/MSU, owner, retirement, trap and translation
algorithms are unchanged. The fixture reuses passive probes and instantiates a
fresh actual core, never a replacement control machine. Only cold reset,
enable/commitEnable and physical memory/PTE transport are driven. Architectural
state, FP commands/results, starts, completions, retirement and traps are never
injected. IRQ/MSI remain inactive and there is one clock.

## Independent numerical and software contract

The [generator](../simulator/gsim/guarded_guest_fp_multiply_program.py) freezes
encoded software, operands and PTEs in the
[recipe](../simulator/gsim/config/guarded_guest_fp_multiply.json), without expected
numeric values. M bootstrap enters HS then VS. Genuine translated FLD/FSD feeds
and stores numerical data. Real HS handlers read trap CSRs and execute SRET
following reserved rounding and joint-FS denials.

C++ exact significand-product/exponent arithmetic and Python exact Fraction
arithmetic independently derive multiplication values/flags from encoded inputs
and pre-instruction state. Cases cover all five rounding modes, static/dynamic
rounding and static override, positive/negative halfway, signed overflow,
sNaN and zero-times-infinity invalid, canonical NaNs, infinities, signed zeros,
S boxing/malformed boxing, exact subnormals and true inexact underflow. Tininess
is detected after rounding to target precision with an unbounded exponent.
A delivered minimum-normal result can still set UF|NX when that precision-only
result remains tiny. The program contrasts this with a closer product whose
precision-only rounding reaches minimum normal and therefore sets NX without UF. A genuine finite multiplication dependency and real software
fflags read/clears distinguish new flags from stale accrued flags. Sticky chains
retain an old flag absent from the next operation's newly generated flags.
Decoded coverage rejects omission of the necessary flag-changing clears.

All32 FPR/fcsr, dual FS and protected owner observations remain retirement-owned.
Two matched external transport schedules exercise held retirement and delayed
real trap admission. Same-edge accepted completion and retirement is legal with
exact tokens and once-only acceptance. Faulting operations never retire. Both
complete linked raw pre/post traces are preserved before named Python replay
checker controls, including removal of UF and premature tininess. These are
checker-sensitivity controls, not native or RTL mutants. Timeout, sanitizer,
crash, truncation and incomplete coverage always fail.

The earlier eager host/A/B/A/host all32 save/restore proof is separate and not
repeated here. One physical FP bank does not imply general guest isolation.
Physical-response bytes and nested data-PTE sequences are independently checked;
exact canceled speculative fetch-walk prefixes are not qualified. Scalar fetch
does not establish two-lane throughput or hardware performance.

## Reproduction and bounded evidence

```sh
mill -i IonSoC.guardedGuestFpMultiply.compile
mill -i IonSoC.guardedGuestFpMultiply.testOnly \
  ooo.GuardedGuestFpMultiplyConfigSpec ooo.GuardedGuestFpArithmeticConfigSpec \
  ooo.GuardedGuestFpCoreConfigSpec ooo.DualFsPreparationConfigSpec
make gsim-guarded-guest-fp-multiply-test
```

Compile all production and HardFloat plus focused sources fresh with the strict
repaired cloud-tools binding, `setup(False)` and verified offline dependency
cache. One fresh ASan/fatal-UBSan GSIM model serves both schedules. Source-only
numeric crosschecks and host mocks are not hardware evidence. Actual counts and
results belong to source-bound execution receipts, not this contract alone.

Independent prebuild review binds all source, encoded inputs, service laws,
oracles, controls, tools and resource limits. Native bounds are 180000 cycles,
22 MiB per trace and 120 seconds, based on the compact program and nested traffic
relative to the prior matched actual-core run. Aggregate new outputs, including
failed attempts, preparation and publication, are capped at 512 MiB with a
64-MiB packaging/review reserve. Admission floors are 768 MiB workspace,
128 MiB /tmp and 3.5 GiB RAM. Hard reserves are 128 MiB workspace, 96 MiB /tmp
and 1 GiB RAM; /tmp spill is at most 16 MiB. Process-tree RSS is at most
min(3.5 GiB, launch available RAM minus 1 GiB). One heavy phase runs at a time
under one persistent 1200-second batch clock. Retries never reset the clock or
relax caps, and all prior and failed artifacts remain preserved.

## Not qualified

No full F/D compliance, FMA/conversions/divide/square-root, general H+FP release,
arbitrary profiles, VU, general OS/isolation, IRQ/fault overlap, in-flight fault
cancellation, M-origin guest-fault review, live reset, independent clocks, PPA,
board, synthesis, Yosys or Verilator claim follows. Pinned RISC-V v20250508
F 2.2, D 2.2, H 1.0 and Machine 1.13 references continue to apply.
