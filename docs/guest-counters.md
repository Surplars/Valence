# Opt-in RV64 guest basic counters

The experimental H assembly has a separate, default-off `basicCounters` option.
It supplies the missing cycle/instruction-retirement counters for guest software;
it does not enable H, A or F/D in any existing production configuration.

Set `basicCounters = true` on `HypervisorMachineCore` or
`CommonHypervisorCpuTile`. The shared platform selector is
`experimentalHypervisorCounters = true` and requires
`experimentalHypervisor = true`. The underlying `OooParams` selector also
requires both `hypervisorExperiment` and `machineSystem`. Defaults and `misa` advertisements are unchanged,
including clear `misa.H`. Firmware/device-tree ISA declarations are not modified.

## Implemented architectural state

The enabled single-hart RV64 profile provides:

- M-only writable `mcycle` (0xB00), `minstret` (0xB02) and
  `mcountinhibit` (0x320). Only CY/IR inhibit bits 0/2 are writable.
- Read-only `cycle` (0xC00) and `instret` (0xC02), aliasing the same physical
  64-bit counters. They are not per-guest counters and have no virtual offsets.
- CY/IR bits in `mcounteren` and `scounteren`, alongside the existing TM bit,
  and the already implemented `hcounteren.CY/IR` access controls.

Counters and inhibit reset to zero. With CY clear, `mcycle` counts every core-clock
edge after reset release, including admission, memory and retirement holds. The
shared platform holds CPU reset during initial admission, so pre-release edges do
not count. It is not the
platform `time` clock and does not imply a measured CPU frequency. `minstret`
counts actual successful ROB retirements while IR is clear, including compressed instructions,
zero-destination instructions and every valid retirement lane. Instructions
causing synchronous exceptions do not count. Arithmetic wraps modulo 2^64.

The disabled profile retains absent counter/inhibit CSRs and TM-only M/S enable
bits. Existing H counter-enable WARL behavior is preserved. RV64 high-half CSRs
and HPM counters are absent. `time`, `htimedelta`, timer comparisons and Sstc
permissions retain their existing implementations.

## Precise publication and access

A legal counter/inhibit write captures its computed value and full ROB token
during the existing serialized MSU execute step. It changes architectural state
only when that exact owner retires. Explicit `mcycle`/`minstret` writes override
the corresponding increment on that edge, including the writing instruction's
own retirement. An inhibit write uses the old inhibit bits for its retirement
edge and the new bits afterward. CSR read/RMW operands are sampled once and stay
stable through completion and commit stalls.

No new issue barrier or speculative rollback mechanism is added. The bank has
one pending SYSTEM write owner; ordinary counting can accept all existing commit
lanes each cycle. A counter CSR owner retires alone under the existing SYSTEM
contract. This describes the functional contract, not measured timing or IPC.

Counter alias reads use the corresponding CY/IR permission bit:

- M always has read access.
- HS requires M enable; host U additionally requires S enable.
- VS requires M and H enable; VU additionally requires S enable.
- Missing M permission gives illegal instruction (cause 2). With M permission,
  missing H permission or missing S permission in VU gives virtual instruction
  (cause 22). Host U denial remains illegal instruction.
- Encoded writes to read-only aliases remain illegal, including a nonzero source
  register holding the value zero. Direct M-only or absent CSR access below M
  remains illegal. No `vscounteren` bank is invented.

## Focused validation entry

`make gsim-guest-counters-test` uses the pinned, repaired GSIM toolchain and
independent C++ oracles. It compiles the full production `IonSoC` module and the
explicit `IonSoC.guestCounters` test module containing `GuestCountersGsim.scala`,
`GuestCountersConfigSpec.scala` and `GuestAtomicsConfigSpec.scala`. This avoids
compiling hundreds of unrelated test fixtures in constrained environments; the
normal `IonSoC.test` source set is unchanged, and no counter scenario or negative
control is omitted. The small counter-bank and actual MSU fixtures check edge
counting, write ownership, sampled read stability, inhibit/overflow, CSR access
and disabled-profile behavior. A separate real H tile/common-fabric fixture
executes finite guest programs with real ROM/RAM and actual ROB retirements.
Component stimulation is distinct from evidence of actual core execution.

The actual-core oracle derives expected state from independent clock edges and
decoded retirement history. Passive sampling/owner observations do not drive
control or supply expected counter values. Legal stalls exercise delayed
publication and held completion; named negative controls must fail at their
specific oracle checks, not through sanitizer crashes. Python entry tests mock
orchestration only and are not hardware evidence.

The pinned specifications are [machine counter/enables/inhibit rules](https://docs.riscv.org/reference/isa/v20250508/priv/machine.html),
[Zicntr](https://docs.riscv.org/reference/isa/v20250508/unpriv/counters.html) and
[H counter-access rules](https://docs.riscv.org/reference/isa/v20250508/priv/hypervisor.html).

## Qualification limits

Focused qualification uses one clock and shared physical counters. It does not provide
guest-specific accounting, HPM events, independent-clock counter transport,
multicore synchronization, firmware discovery, OS boot, complete architecture
compliance or FPGA timing/resource qualification. All actual-core test interrupts
are disabled; synchronous traps originate in VS/VU and are delegated to HS.
No M-origin guest-fault or IRQ/fault-overlap experiment is added.
