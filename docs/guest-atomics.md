# Opt-in RV64 guest atomics

The experimental H core can explicitly enable the existing RV64 A execution and
physical atomic engine. This supplies guest LR/SC and AMO.W/D instructions used
by locks and other synchronization routines. It does not enable H or atomics in
the default experimental assembly, promote a production profile, or advertise
`misa.H`. Only an A-enabled configuration sets `misa.A`.

## Configuration and ownership

- `HypervisorMachineCore(atomicMemory = true, ramBase = ..., ramBytes = ...)`
  requires a nonempty, valid RAM window containing whole 64-byte reservation
  granules. Its external memory endpoint must implement the existing atomic
  request/response contract; the core does not emulate atomics or own a reservation.
- `CommonHypervisorCpuTile(atomicMemory = true, ...)` uses the tile's actual RAM
  range, shared with `CommonMachineFabric` and its existing `AtomicDataMemory`.
- `CommonMachinePlatform(experimentalHypervisor = true,
  experimentalHypervisorAtomics = true, ...)` selects that tile. Atomics without
  the H selector are rejected. Both selectors default to false. The new selector
  is not dynamic multi-clock platform qualification.

The RAM window also permits the backend's existing ordinary bare-host RAM-load
speculation. Translation-active guest loads remain excluded from that shortcut.
No new cache, TLB, speculative ownership scheme or atomic memory unit is added.

## Translation, protection and ordering

The guest data adapter captures the atomic operation with its address/context.
LR requests read permission, SC requests write permission, and AMO requests both
at the applicable VS/G translation stages and final PMP check. Even SC without a
valid reservation must undergo translation and protection checks before reaching
the physical reservation owner.

`GuestPhysicalAccess.atomic` distinguishes atomic capability from ordinary PMA
read/write permission. The core checks the entire translated SPA byte interval
against its configured RAM window before offering a physical request. The tile
also rejects atomic ROM and MMIO accesses. An ordinarily readable ROM or writable
register is not automatically an atomic-capable endpoint. Fetch drives this
qualifier false; HLV/HSV remain ordinary accesses.

The existing backend admits an atomic at the ROB head after older data owners
drain and prevents younger memory from passing it. This conservative ordering
supports the four aq/rl encodings without a weaker concurrent atomic path. It is
not a throughput improvement or a complete formal RVWMO proof.

One physical reservation belongs to the actual fabric atomic unit. LR establishes
an exact SPA/size reservation, SC consumes it, and ordinary writes invalidate the
matching 64-byte granule. A new LR replaces an earlier reservation. Same-SPA
virtual aliases use this implementation's physical matching policy; the ISA
allows an alias SC to succeed or fail. Distinct physical locations do not become
equivalent merely because virtual addresses match. Existing trap reservation-clear
transport is unchanged. Software remains responsible for its context-switch and
page-remapping reservation policy; no new root-write or xRET clearing is added.

The architecture follows the pinned [A 2.1](https://docs.riscv.org/reference/isa/v20250508/unpriv/a-st-ext.html),
[machine](https://docs.riscv.org/reference/isa/v20250508/priv/machine.html) and
[H](https://docs.riscv.org/reference/isa/v20250508/priv/hypervisor.html) specifications.
AMO.W ignores the upper half of rs2 and sign-extends the old 32-bit result. LR
faults use load exception classes; SC/AMO faults use store/AMO classes.

## Focused GSIM entry

`make gsim-guest-atomics-test` uses the strict pinned GSIM toolchain and a fresh
`GuestAtomicsPlatformGsim` model. It contains the real H tile, common fabric,
hardware ROM/RAM and physical atomic engine, on one clock. The harness programs
memory only before CPU admission. Request/response gates add legal backpressure
without replacing hardware replies or atomic operations.

The directed programs check independent precomputed retirement results and
physical data transactions. Clean programs cover W/D AMO arithmetic, LR/SC
reservation behavior and translated memory. Separate guest-origin exception
programs check VS/G write protection, atomic ROM/MMIO rejection and alignment.
All interrupt sources and enables are disabled in these atomic programs. A
separate ordinary ECALL scenario exercises the existing trap-clear policy.
The new cases do not add a directed final-SPA PMP denial; the inherited PMP
path is retained, and that additional atomic-specific negative is deferred.

The entry requires every named case under both schedules and a complete marker.
`--wrong-atomic` deliberately changes an independent expected atomic result; exit
1 and the exact final diagnostic are required. A sanitizer failure is not accepted
as a successful negative control. Python entry tests mock hardware calls and
Scala configuration tests only elaborate constructors. Neither replaces GSIM.

## Qualification boundaries

This increment does not qualify guest OS boot, F/D or vector virtualization,
multi-hart atomics, DMA interference, independent clocks, production CDC/DDR,
runtime parking, a full compliance suite, general progress under unbounded
interference, or FPGA timing/resources. Finite execution/stall counts are evidence
of the tested schedules, not bandwidth or PPA measurements. The separate blocked
M-origin guest-fault review and IRQ/fault-overlap work are not part of this entry.

The original default-off H/AIA and host functionality remain separate baselines.
The source/evidence package records actual execution counts and any remaining
directed-test limitations; this document describes the supported interface and
test contract, not an OS-readiness declaration.
