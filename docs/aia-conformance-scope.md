# AIA audit scope, 2026-11-06

This inventory describes the isolated AIA component tree based on
`a6448d9165f9c3c95456fab5895dd66d818c66aa`. The clean combined candidate separately qualifies H/VS/MSU, G-stage and a real
APLIC-to-OoO Bare chain, as described in `hypervisor-core-integration.md`. Passing
a component test by itself does not qualify the CPU integration or permit
advertising complete H+AIA support.

## Implemented and checked component profile

- RV64 IMSIC: M, S and up to 63 guest files; 63..2047 identities in 64-bit banks;
  reserved/even/odd selectors, zero identity, EIP/EIE, delivery, strict threshold,
  claim and MSI races, endian MMIO, padded pages, access errors and decoupled
  response ownership. The caller owns privilege, VGEIN and actual CSR write
  suppression. A CSRRS with nonzero source-register number containing zero is
  still a real write, while encoded rs1=x0 is read-only.
- APLIC: one M root and S child, one hart, optional guest target files, fixed
  MSI addresses, delegation and revocation, all six supported source modes,
  queued ownership, and globally ordered genmsi synchronization. Normal MSI
  source arbitration remains lowest source number; the standard does not
  mandate that source-priority policy in MSI mode.
- `HypervisorGuestInterrupts`: independent committed hgeie/hvip/VGEIN state and
  HS/VS candidate generation, with selected guest VSEIP independent of hgeie.
- `AiaHartControl`: independent M/HS TOPI nomination and hvictl/vstopi controls.
  The selected guest TOPEI must be live. Candidate inputs must already include
  enables/delegation but exclude global IE and current-privilege masking.

## Permitted simplifications, not missing mandatory functionality

- Physical iprio and hviprio bytes may be read-only zero; physical TOPI may then
  report priority 1. TOPI still must reflect pending/enabled candidates when
  global interrupts are disabled.
- mvien and hvien may be read-only zero. Their existence does not remove the
  required mvip aliases or hvictl behavior.
- IMSIC eidelivery maps unsupported values through bit0. Invalid threshold
  values retain the previous legal value. Both choices are documented legal
  WARL/WLRL behavior; supported threshold values are 0..N, not 0..N+1.
- Optional PLIC/APLIC bypass, heterogeneous file capacities, direct-delivery
  IDC, multiple harts, deeper APLIC hierarchies and RV32 are not implemented.
  Their absence is not a conformance failure for this declared RV64 profile.

## Hart integration and evidence boundary

The component-only baseline lacked the hart functions listed below. This clean
combined candidate implements the CSR, nomination and owner paths and has
actual-MSU plus real-OoO tests described in `hypervisor-core-integration.md`.
The list remains a review checklist, not a claim that standalone component
receipts qualify the complete CPU or platform:

- mtopi/stopi, M/S even iprio selectors 0x30..0x3e, correct odd-selector faults,
  mvien/mvip including software SEIP and the correct CSR read/modify/write alias.
- vsiselect/vsireg/vstopei/vstopi, hvien/hvictl/hviprio, H/VS state banks, and
  VTI-dependent virtual-instruction exceptions. vsiselect needs at least 9 bits.
- M-target before HS-target before VS-target arbitration, independently of
  interrupt identity; precise trap entry/return and complete vector offsets.
  Six-bit hvictl IID requires widening the old four-bit cause path.
- Valid nonzero VGEIN-to-file selection. VGEIN 0 must not alias guest CSR access
  to M or S. IMSIC's generic error bit alone does not qualify illegal-versus-
  virtual-instruction exception selection.
- Two-stage translation, guest page-fault reporting, guest operating-system
  execution, device-assignment/IOMMU protection, CDC and physical timing.

## Exact hvictl encoding edge

AIA v1.0's normative priority rules give hvictl=`0x40000100` (VTI=1, IID=0,
DPR=0, IPRIOM=1, IPRIO=0) a valid injected IID 0 candidate with reported
priority 0, encoding vstopi as 0. A nearby explanatory note says absence while
VTI=1 can be indicated only by IID 9. The standalone module follows the explicit
field encoding/priority rules; it does not silently prohibit legal IID 0 or
invent a nonzero priority. The core integration must retain this exact directed
case and document the resolution before claiming unqualified full-AIA support.

## Official sources

- https://docs.riscv.org/reference/aia/v1.0/AdvPLIC.html
- https://docs.riscv.org/reference/aia/v1.0/IMSIC.html
- https://docs.riscv.org/reference/aia/v1.0/MSLevel.html
- https://docs.riscv.org/reference/aia/v1.0/VSLevel.html
- https://docs.riscv.org/reference/aia/v1.0/CSRs.html

The online chapter numbering differs from the revised 20250312 PDF. Mutable
GitHub `main` copies were cross-checked against official v1.0 text; they are not
used alone as a stable compliance reference.
