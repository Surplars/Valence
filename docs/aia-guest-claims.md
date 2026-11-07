# Guest IMSIC claims on the actual shared platform

This focused test exercises the real OoO core, its guest CSR routing, the real
APLIC/IMSIC and CommonMachineFabric. It changes no RTL or production defaults.
Experimental H remains opt-in and `misa.H` remains clear.

## Gap and scope

The earlier actual-retirement AIA programs use one pending identity, ID 5.
Component tests already cover many identities, thresholds and guest files, and
the ordinary non-H MachineCore already tests CSRRS with a nonzero source
register containing zero. Those tests do not establish the same behavior
through guest shadow CSRs and guest-file selection in the actual platform.

This program uses four real source edges: guest file 1 receives IDs 3, 5 and 65;
guest file 3 receives ID 5. The CPU configures every APLIC register and initializes
the used guest EIP, EIE, delivery and threshold registers. It does not rely on
architecturally unspecified IMSIC reset contents. ID 65 uses RV64 selectors
0x82/0xc2, bit 1, called eip2/eie2 by the specification.

The retired MRET into HS is the arming boundary. The test then holds retirement
admission until all four real MSI replies complete. No observational CSR can
start across that boundary. The pending-event oracle is independently planned;
each actual MSI tuple must match an expected event, with no duplicate or missing
event. No claim/MSI concurrency or APLIC source-arbitration policy is qualified.

HS selects guest 1, guest 3, then guest 1 and reads direct guest-file CSRs. It
enters VS through retired status/SEPC writes and SRET. VS accesses the shadow
siselect, sireg and stopei CSRs and checks:

- Encoded x0 CSRRS/CSRRC and zero-immediate CSRRSI/CSRRCI are read-only.
- CSRRS with a nonzero source register containing zero claims ID 3.
- CSRRC with a nonzero source register containing zero claims ID 5.
- CSRRWI with immediate zero claims ID 65.
- Thresholds 3/4, 5/6 and 65/66 distinguish equality from strict admission.
  A threshold masks delivery/TOPEI without clearing EIP.
- TOPEI contains `(ID << 16) | ID`; ID 65 therefore returns 0x410041.

Claims of IDs 3 and 5 run temporarily with threshold zero, so another pending
identity is eligible immediately afterward. The subsequent EIP and TOPEI reads
detect unintended extra destructive claims rather than hiding them behind the
threshold. The reported claim count counts retired claim instructions; there
is no probe of internal IMSIC CSR transaction counts.

One ordinary VS ECALL enters HS. Guest file 3 must still contain its own ID 5,
which HS claims through direct vstopei. Returning selection to guest file 1
must show it is empty. Architectural retirement checks distinguish a CSR's
encoded source-register number from the value in that register.

All interrupt enables remain zero: MIE/HIE, HGEIE, HVIP and guest SIE. Delivery
is enabled in the populated files. Masking only global IE would not suffice to
prevent a higher-privilege interrupt from preempting VS. This program allows
only its intended ECALL, no external-interrupt traps or guest-memory faults.

## Standard entry

With the repository's pinned, repaired GSIM setup:

```
make gsim-aia-guest-claims-test
```

The entry generates the unchanged HypervisorPlatformGsim fixture and compiles
the driver with ASan/UBSan. It runs open and stalled service schedules, then
two deliberately wrong independent expectation controls. A negative control
must exit 1 with its particular claim or file-isolation diagnostic; a generic
failure or sanitizer error is rejected. No recovery directory, precompiled
model or private evidence artifact is required by this entry.

The normal toolchain prerequisites still apply. See
[the platform entry](hypervisor-platform-entry.md) and
[strict bundle binding](gsim-reset-graph-bundle.md). This target does not fetch
or install missing GSIM tools, relax binding, or claim arbitrary toolchain
rebuild portability.

Entry-only unit tests use mocked compilation/simulation:

```
python3 -m unittest discover -s simulator/gsim -p test_aia_guest_claims_entry.py
```

## Limits

The CPU uses Bare addresses. This is guest CSR/claim integration evidence, not
two-stage translation, IRQ/fault overlap, cancellation, independent-clock CDC,
guest OS, full H/AIA compliance or performance evidence. The CPU's enable stays
high after startup. A final success snapshot can retain instruction-fetch
owners, which are reported rather than relabeled as complete quiescence.
The stopped IRQ/fault cancellation work and the separate M-origin guest-fault
review are unrelated and are not retried by this test.

Architectural references:

- [AIA v1.0 IMSIC](https://docs.riscv.org/reference/aia/v1.0/IMSIC.html)
- [Zicsr](https://docs.riscv.org/reference/isa/v20250508/unpriv/zicsr.html)
- [Hypervisor extension](https://docs.riscv.org/reference/isa/v20250508/priv/hypervisor.html)
