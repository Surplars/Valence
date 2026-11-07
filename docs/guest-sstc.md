# Experimental RV64 guest Sstc

The opt-in H assembly implements a guest timer compare path alongside the existing
host [Sstc baseline](sstc.md). It does not turn on H in a production profile or
advertise `misa.H`. This is RV64 functionality; RV32 high-half CSRs are not added.

## State, pending level and time

`vstimecmp` (0x24d) is a 64-bit compare register, reset to all ones. With V=1,
`stimecmp` (0x14d) addresses this guest bank; with V=0 it addresses the existing
host bank. HS/M can directly address 0x24d subject to the permissions below.
Guest writes cannot update the host compare bank.

`henvcfg.STCE` (0x60a bit 63) resets to zero. It reads zero and is non-writable
while `menvcfg.STCE` is zero. This implementation explicitly clears stored H STCE
when M STCE is disabled, so software must enable it again after re-enabling M
STCE. Other HENVCFG fields remain read-only zero.

Guest time is `(time + htimedelta) mod 2^64`. An unsigned comparison against
`vstimecmp` is registered for one cycle before its hardware contribution reaches
VSTIP. Both M and H STCE must be set for that contribution. Counter enables,
current V/privilege, delegation and interrupt enables do not gate the comparison.
They control access or delivery separately. The same-clock time input is required;
no independent RTC or clock crossing is introduced.

`hip.VSTIP` is the logical OR of hardware expiry and writable `hvip.VSTIP`
software injection. Disabling either STCE restores injection-only behavior.
Clearing injection cannot clear an expired hardware timer; moving the comparison
into the future cannot clear a still-injected interrupt. Timer bits of HIP/VSIP
remain read-only. The existing guest interrupt selector and trap path are reused.

## CSR access contract

- M can access both compare CSRs regardless of STCE or TM gates.
- Below M, either M STCE=0 or `mcounteren.TM`=0 makes a compare access illegal
  (cause 2). This has priority over virtual-instruction classification.
- HS can access direct `vstimecmp` with the M gates enabled regardless of H STCE
  and `hcounteren.TM`.
- VS accesses the 0x14d shadow only with both M gates plus H STCE and
  `hcounteren.TM`; missing H permission causes a virtual instruction (cause 22).
- Direct 0x24d access in VS/VU is virtual when HS-qualified, otherwise illegal.
  VU access to the 0x14d shadow is likewise never legal.
- AIA `hvictl.VTI` retains its write-only virtual trap for VS `stimecmp` access.
  Encoded read-only CSR forms remain reads; a nonzero source-register number is
  a write even when that register holds zero.

This follows the pinned [Sstc 1.0 specification](https://docs.riscv.org/reference/isa/v20250508/priv/sstc.html)
and [H virtual-instruction rules](https://docs.riscv.org/reference/isa/v20250508/priv/hypervisor.html).

## Focused validation entry

Run `make gsim-guest-sstc-test` using the repository's validated pinned GSIM setup.
The entry freshly elaborates/generates/compiles two fixtures with ASan/UBSan:

1. `HypervisorSystemGsim` exercises the actual system unit and IMSIC. The independent
   CSR matrix covers privilege, direct/shadow addresses, hierarchical gates and
   encoded read/write forms. It checks denied-write state, host/guest isolation,
   time offsets and wrap, one-cycle pending transitions, injection, delegation and
   delivery gates. Ordinary ECALL results drive the fixture trap interface for
   mode recovery. This component test does not claim real ROB retirement.
2. `GuestSstcCoreGsim` instantiates the actual `HypervisorMachineCore`, including its
   real fetch and owner-drain logic. A same-clock controlled time change expires a
   guest timer. A VS handler checks its cause/EPC/time/compare, rearms and returns
   with SRET. An independent interpreter checks every retirement, and an owned
   RAM store/load checks continued execution. Open/stalled schedules log full
   traces, physical traffic and finite terminal ownership counts.

The core case uses Bare addresses and one clean timer interrupt per schedule.
There is no guest memory fault injection, external IRQ or IRQ/fault-overlap test.
Periodic commit-disable cycles do not claim blocked-ready-retirement throughput.
Finite terminal snapshots do not establish general quiescence. Post-guest host
bank isolation is directly checked by the system-unit matrix, not inferred from
the core interpreter's expected host state.

Named `--wrong-compare` and `--wrong-timer` controls deliberately reject correct
results with independent wrong expectations. The entry requires exit 1 and the
exact final diagnostic; sanitizer failures are not accepted controls. Python
entry tests mock hardware calls, and `GuestSstcConfigSpec` is a pure configuration
check. Neither substitutes for the real GSIM executions.

This does not qualify guest OS boot, translated timer handling, multicore,
independent clocks, FPGA PPA or complete H/AIA compliance. All existing exclusions
and the default-off experimental configuration remain in force.
