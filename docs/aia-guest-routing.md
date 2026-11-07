# APLIC guest interrupt routing

## Scope and baseline

This change is based on `a6448d9165f9c3c95456fab5895dd66d818c66aa`
(`dev/verified-a1-source-20261106`). Its APLIC, IMSIC, CommonInterruptFabric and
I1 AIA adapter sources are identical to the corresponding files in the I1 H/V
reference commit `94c4fac446afef73ddfcbe8784b2518f669718c8`.

The change completes **the single-hart M/S APLIC-to-guest-IMSIC routing path**.
A separate component fixture connects that path to frozen H interrupt state,
without adding that state to the OoO processor.
It does not claim complete AIA hart-CSRs or hypervisor support. In particular,
The baseline A1 lacks architectural V state, H/VS CSR banks, VGEIN authorization,
precise guest traps and two-stage translation. Separate core integration must
qualify those paths before claiming that guest interrupt files serve a real guest. The I1 reference explicitly excludes `withH && withAia`
and uses GEILEN=0, so it cannot stand in for that qualification.

No original checkout, main branch, FPGA run or local Vivado process was changed.
No physical timing, resource, Linux guest or board claim accompanies this patch.

## Architectural behavior

- `AplicParams.guestFiles` defaults to zero, accepts 0 through 63, and is enabled
  only for the existing supervisor child domain. The MSI page aperture is
  power-of-two padded and aligned, matching `ImsicParams`.
- `CommonInterruptFabric` passes `ImsicParams.guestFiles` to the supervisor
  domain. The machine domain keeps GuestIndex read-only zero.
- For an active supervisor source, `target[17:12]` selects GuestIndex and
  `target[10:0]` holds the implemented EIID bits. Hart Index is fixed at zero.
  GuestIndex zero targets S. Nonzero index g targets
  `supervisorBase + (g << 12)`. Unsupported WLRL GuestIndex values retain the
  previous valid field; EIID is updated independently. Reserved bits read zero.
- The outgoing queue captures GuestIndex alongside EIID. Retargeting or revoking
  a source cannot change an already queued MSI. The existing two queue entries,
  four outstanding response credits, registered response ownership and
  backpressure behavior are unchanged. No pipeline stage was added.
- `genmsi` always targets the domain's own M or S file, never a guest. It ignores
  writes while Busy and does not depend on domain IE. The common fabric pauses
  new ordinary forwarding while either domain has a pending generated MSI, and
  waits for **both domains'** older queues and real responses to drain before
  enqueueing it. MMIO writes still complete normally and source pending state
  continues to update. Simultaneous M/S generated MSIs may enter together after
  the old traffic drains. No ordinary MSI pipeline stage is added.
- An undelegated child source is unimplemented: sourcecfg, target, pending and
  enable read zero, writes have no retained effect, and delegation later starts
  inactive. Bitmap readback is masked immediately on revocation, before the
  following edge clears stored state. This prevents a first-cycle read leak.
- Machine MSI address configuration registers are read-only zero in the S child.
  Root `smsiaddrcfgh` reports guest-page stride and has no bit-31 lock; that bit
  is reserved. Root `mmsiaddrcfgh.L` locks both configuration pairs.

Queued MSIs may arrive after revocation. Software must use the AIA `genmsi`
synchronization procedure before reassigning the old guest interrupt file.
Hardware does not silently drop an accepted owner to make revocation look instant.

The IMSIC adds a live, read-only `topIdentities` packed output. File f occupies
bits `11*f+10:11*f`, with file zero in the low field. Each identity equals that
file's current TOPEI identity, filtered by EIP/EIE/threshold but not eidelivery.
This lets the hart rank guest external interrupts without a CSR transaction or
claim side effect. A Vec output was rejected because the restored GSIM emits
an invalid array-return getter; the packed output is functionally checked.

The IMSIC's existing file mapping is unchanged: file 0=M, file 1=S, file 2=guest1,
and so on. Its guest interrupt output bits can feed hgeip bits GEILEN:1 after
shifting the guest subvector left by one. CPU-side privilege checks and VGEIN
selection belong at the irrevocable CSR commit boundary, not in the shared APLIC.

## Focused verification

Run the normal toolchain entry point:

```sh
python3 simulator/gsim/aia_guest_acceptance.py \
  --output build/aia-guest/fresh-run --gsim "$GSIM" --cxx "$GSIM_CXX"
```

The runner also supports an offline native Scala compilation using installed
hash-pinned jars through `--runtime-manifest` and `--scala-cache`. This path was
used in the cloud because Mill's classgraph-worker dependency was not cached and
Maven DNS was unavailable. It compiles the exact production IP files and test
wrappers from source, with the Chisel compiler plugin, without cached CPU classes.
It does not download tools or dependencies.

The finite run contains:

1. Five Scala configuration/elaboration tests, including 63-guest IMSIC topology
   and APLIC guest configurations 0, 1, 2 and 63.
2. New real APLIC-pair plus IMSIC GSIM fixture: two independent guest files,
   EIID 5/6/65, M and S destinations, target masking and WLRL behavior, threshold,
   delivery versus TOPEI, claims under response backpressure, queued retarget,
   revocation/redelegation, first-cycle bitmap revocation, preservation of queued
   MSIs through revocation, genmsi ordering/Busy, big-endian MSI writes, padding
   pages, invalid identity, selector and access width/alignment/mask errors.
3. Existing randomized APLIC regression: 20,615 transactions and 4,000 random
   operations; 31 consecutive stream transfers.
4. Extended IMSIC regression: explicit delivery WARL and threshold WLRL values
   with write/set/clear, same/different-identity claim collisions, cross-bank
   pending writes, held responses, and per-cycle live identity checks. The
   oracle uses 128-bit IRQ storage so guest63/file64 cannot disappear or invoke
   an undefined host shift.
5. Existing delegated S-domain UART regression, covering target GuestIndex zero.
6. A complete APLIC -> IMSIC -> `HypervisorGuestInterrupts(2)` component fixture.
   It drives a real level-sensitive source wire and checks hgeip bit mapping,
   VGEIN selection independently of hgeie, SGEIP and VSEIP, hideleg, hie and
   HS/VS global masking, VU/VS/HS/M privilege states, uncommitted-update
   suppression, enabled/threshold/delivery masking, and TOPEI claims under
   response backpressure. It also switches VGEIN while an MSI is queued and
   proves APLIC revocation does not erase an interrupt already stored in IMSIC.
7. Cross-domain genmsi ordering in both directions, simultaneous M/S generated
   MSIs, delayed real responses, ignored Busy writes, preserved revoked queues,
   and a new physical source edge while ordinary forwarding is paused.
8. With `--boundaries`, runtime checks for IMSIC identities 2047, guestFiles 63 and
   guestFiles 62 padding, exact 64-bit address-space ends and adjacent windows;
   real APLIC-to-IMSIC routing for guest counts 0/1/3/63; and APLIC source counts
   1/255 with EIID 2047, the highest physical wire, bitmap and target registers,
   the final 16-KiB control window and final 56-bit MSI page.
9. Wrong-destination, wrong-hgeip, wrong-order and wrong-response oracle negative
   controls must fail at their expected mismatches. ASan and UBSan are enabled.

The first-cycle revocation test was first run against the pre-mask RTL and failed
with `first-cycle revoked source bitmap leak`. The corrected RTL passes that same
stimulus. This is a reproduced defect, not only a source inspection claim.

The original cross-domain genmsi probe produced guest1/EIID11, M/genmsi13,
guest2/EIID12 after both guest messages had already been forwarded and their
sources revoked. This reproduced the global-ordering defect before the fix;
the fixed tests require both older messages before the generated one.

These tests do not qualify all AIA hart CSRs,
CPU virtualization, G-stage faults, IOMMU/device assignment, or guest OS boot.
Run with `--boundaries` for the extended parameter matrix. The separate
`--max-sources` option attempts the 1023-source model. It elaborated successfully,
but GSIM generation was killed by SIGKILL twice, including a lower-memory-option
attempt with peak RSS 3,535,144 KiB. No 1023-source runtime result is claimed.
This resource blocker is preserved in the evidence rather than converted to PASS. The runtime is the previously restored GSIM toolchain, not a claim of pristine
upstream GSIM qualification. Source, dependency, tool, command and artifact hashes
are recorded in each output directory's `receipt.json`.

## Component-chain integration boundary

`AiaGuestRoutingGsim` composes production APLIC, IMSIC, register arbitration,
CommonInterruptFabric and the independent `HypervisorGuestInterrupts` module.
The latter is the peer-validated frozen source with SHA256
`37031aeaa3eb1b18d8ee55dfa026ae6c521e8df834716164604025bc1a6a3213`.
For two guests, IMSIC output bits 3:2 connect to the module's guestExternal bits
1:0. They appear at architectural hgeip bits 2:1, leaving hgeip[0] zero.

The testbench passes explicit IMSIC file indices. It does not exercise a CPU's
VGEIN-to-CSR-file decoder or CSR privilege authorization. `setVgein` is an
explicit committed field-update interface, not an implemented hstatus bank.
The fixture exposes local HS and VS candidates, which can both be asserted;
CPU trap arbitration and precise trap entry remain outside this component.
The interrupt-state module uses the H 1.0 fixed local priority order, not full
AIA programmable priorities or mtopi/stopi/vstopi arbitration.

When integrating with another worker's tree, retain the identical frozen
`HypervisorGuestInterrupts.scala` source rather than introducing a duplicate
class. If its source changes, rerun the chain against the new source. The final
receipt pins the exact tested production sources and harnesses.

## Specification references

- [AIA 1.0 APLIC](https://docs.riscv.org/reference/aia/v1.0/AdvPLIC.html):
  §§3.1.5.2–.5, .9, .15–.16, and 3.1.9.
- [AIA 1.0 IMSIC](https://docs.riscv.org/reference/aia/v1.0/IMSIC.html):
  guest-file layout, CSR banks, delivery and TOPEI.
- [AIA 1.0 VS level](https://docs.riscv.org/reference/aia/v1.0/VSLevel.html):
  §5.1.1. A guest-visible virtual APLIC is emulated by the hypervisor; real source
  interrupts can be forwarded directly to a guest IMSIC file by the real APLIC.
