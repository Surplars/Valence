# Same-DUT AIA interrupts during two-stage guest execution

## What this adds

This finite qualification closes the previously separate AIA/Bare and nested
translation test paths. The DUT instantiates the existing, frozen
`HypervisorMachineCore` plus the production `CommonInterruptFabric`. The core
contains the actual C/32-bit instruction assembler, separate nested fetch and
data translation services, OoO execution/ROB, H/VS system state and IMSIC.
There is no synthetic guest interrupt input or substitute translated address.
No production RTL is changed by this addendum.

The underlying clean candidate is based on commit
`a6448d9165f9c3c95456fab5895dd66d818c66aa`. Its sealed source/evidence archive is
unchanged (SHA256
`27b1eab5f3c18d6df5c092e0787273f2f80f778099028d3039dd3bec01f0ccc0`).
The runner validates and freezes the completed 369-source compilation, 1,556
prepared classes and all external dependencies, then compiles the new wrapper.
This is documented reuse of the qualified core, not another claimed full-source
compilation.

## Physical memory and interrupt path

Guest code VA 0x40000000 translates through VS page tables to GPA 0x20000000,
then through G-stage tables to SPA 0x80200000. Guest data follows VA 0x40001000,
GPA 0x20001000 and SPA 0x80201000. The VS page-table GPAs beginning at 0x10000000
are themselves translated to physical table pages beginning at 0x80300000.
The memory responder accepts physical addresses only; it does not alias a VA or
GPA onto an expected response. Both PTE ports separately count actual G-table
and translated VS-table reads. New fetch and data walks after SRET are required.

A real rising APLIC source is delegated to the S domain and converted into an
MSI for an IMSIC guest file. The core executes the configuration, handler CSR
reads, claim and return instructions. APLIC registers are initialized through
external test MMIO while the CPU is disabled; this is not CPU load/store access
to the APLIC register window.

Three programs are checked:

1. Guest1 receives a VS external interrupt. The physical source rises while a
   guest data-PTE response is pending.
2. Guest3 receives a VS external interrupt. The source rises while a fetch-PTE
   response is pending, proving the path is not hardwired to guest1.
3. Guest2 is pending while VGEIN selects guest1. hgeie routes SGEI to HS. The
   handler reads the empty selected file, changes VGEIN through retired code,
   claims guest2, checks TOPEI/hgeip clear, and returns to translated VS code.

Source-edge overlap is the claimed condition. The source, MSI-acceptance and
trap cycles are recorded separately. MSI backpressure can outlive the triggering
PTE response; the test does not claim that the same PTE is held until the trap.

## Architectural and ownership checks

An independent instruction interpreter checks every retirement's PC,
instruction, destination value and next PC. The initial C instruction leaves
following PCs with bit1 set, so the precise interrupt EPC and SRET exercise
halfword alignment. All IRQ fault-metadata fields must be zero. This is not a
claim of stale-GPA clearance following an earlier guest-page fault.

The program stores and reloads data before the interrupt. The handler writes a
second location, through guest translation for VS or physical HS access for the
HS route. After SRET, the guest loads that value and performs another translated
store/load. Exactly three physical stores and the final values are checked.
Both translation stages must perform actual reads on both PTE ports, including
new walks after return. At success, disabling the CPU must drain outstanding
physical fetch/PTE/data responses without further retirement or traps.

Real MSI requests and responses are independently stalled. The test checks all
request fields (address, data, write, size and byte enable), response data/error,
and valid stability on every held cycle. Both directions require nonzero actual
stall coverage. The production adapters' owner/held-offer assertions remain in
the generated model; responder-capacity checks are not presented as a separate
proof of CPU ownership.

## Final results

The final source-frozen run uses the runner's defaults and ASan/UBSan:

- guest1 to VS: 172 retirements, one trap, 17,124 checks; 912/228 G/VS fetch-PTE
  reads and 108/27 G/VS data-PTE reads. Post-return fetch/data PTE reads: 270/45.
- guest3 to VS: 172 retirements, one trap, 16,948 checks; 902/225 fetch-PTE and
  108/27 data-PTE reads. Post-return reads: 300/60.
- non-selected guest2 to HS: 194 retirements, one trap, 14,262 checks; 615/153
  fetch-PTE and 84/21 data-PTE reads. Post-return reads: 300/60.

Total: 538 retirements, three actual source MSIs, three precise traps, 27 physical
data operations and 48,334 checks. Actual held request/response cycles are 12/8,
6/5 and 9/8. The deliberately wrong MSI-destination oracle fails with the
expected diagnostic. Cycle counts are finite test execution positions, not
performance measurements.

The first positive run was already successful. The final batch corrected the
runner's default log markers and strengthened the explicit evidence checks; it
did not change the production implementation. Both source snapshots and receipts
are retained, with the final run authoritative.

## Reproduction and limits

Run `simulator/gsim/aia_translated_core_acceptance.py` with `--core-root` pointing
to the validated clean tree, a new `--output` directory and the pinned `--gsim`
and `--cxx` paths. The final defaults match the included harness. The optional
`--generate-only`/`--resume` flow separates generation from native linking while
revalidating all frozen artifacts. The actual executed commands are recorded.

This addendum supersedes only the earlier absence of a same-DUT AIA-plus-G-stage
scenario. It does not enable misa.H or change default production/W16 profiles.
It does not qualify guest OS boot, FP/atomic guest integration, CPU MMIO routing,
board integration, physical timing or a complete architectural compliance suite.
The blocked independent M-origin guest-page-fault review remains unperformed;
no retry or substitute review of that operation was attempted here.
