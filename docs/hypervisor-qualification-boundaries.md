# H/M, fence and translation-coherence qualification boundaries

This is a clean, opt-in RV64 H/AIA implementation candidate, not a declaration of complete H support. The tested assembly is `HypervisorMachineCore`, with two-issue maintenance sources and a conservative parcel/translation path. Existing production `MachinePlatform`, BoardSoC and generated W16 configurations are not switched to it. `misa.H` remains clear.

## Implemented and exercised

- VS/VU and HS/M state transitions, MRET/SRET, CSR shadowing, delegated exceptions, guest IMSIC selection and AIA nomination have actual-MSU and real-retirement tests. The specific CSR permission matrix and H instruction permissions were independently checked.
- M-mode ordinary load/store effective context is exercised for all 12 MPP U/S/M × MPV × MPRV combinations. Applicable MPRV+MPV accesses traverse both stages, including U versus S leaf permissions. Other combinations retain host physical semantics.
- Static misaligned LD/SD faults preserve GVA provenance for all 24 MPP/MPV/MPRV/access combinations. The independent test checks both the original ROB metadata and the resulting `mstatus.GVA`, with no data or PTE request.
- HLV.D, HSV.D and HLVX.HU traverse the real ROB-head path and two-stage service. The separate adapter/walker tests cover the remaining size, permission, access and cancellation combinations. This is not an ISA-wide guest-instruction compliance claim.
- C/32-bit fetch assembly freezes one owner and context across both parcels. The full core checks a second-parcel guest fault at a page boundary, preserving the first parcel's EPC and the second parcel's tval/raw GPA.
- The real-core guest faults currently exercised are VS-origin load, store, fetch and implicit VS-PTE faults delivered to HS. They verify cause, EPC, tval, raw GPA, HTVAL and HTINST through actual completion/ROB/headtrap ownership.

## Actual AIA-to-retirement integration

The same DUT now includes CommonInterruptFabric, IMSIC and the actual two-issue
OoO core. Three finite programs validate guest1 and guest3 VS delivery and
non-selected guest2 HS SGEI delivery, followed by a retired VGEIN switch, claim,
post-claim reads, precise trap/return and both MSI channel stalls. Interrupts
come from real APLIC source pins, not an injected guest-interrupt Boolean.
Those initial tests use Bare instruction supply. The subsequent
`aia-translated-core-chain.md` qualification now exercises the same production
core, nested IF/data translation and real APLIC/IMSIC in one DUT. Its three
finite programs check IRQ entry, claim, SRET and translated memory state before
and after the interrupt. This closes the combined-scenario gap, not guest
operating-system or complete-platform qualification.

## M-origin trap review still outstanding

The additional independent M-mode explicit/implicit guest-page-fault regression was not completed because its execution was blocked. No alternate route or retry was used. Do not claim that this extra review passed. In particular, the existing positive MPRV access matrix and static-GVA matrix do not substitute for a new end-to-end matrix of M-origin guest faults, MTVAL2 and MTINST. The implemented CSR/trap path is present, and the already completed module and VS-to-HS tests remain separate evidence.

## HFENCE and TLB behavior

The new H path deliberately has no TLB or PTE cache. Every guest access, including VS Bare, goes through its captured roots and an actual walk when required. Thus no V/VMID/ASID cache entry exists to invalidate. ASIDLEN and VMIDLEN are both zero; selective address/identifier operands are conservatively ignored by fences, which drain all owners.

The real-core fence program writes a G leaf PTE, executes HFENCE.GVMA, observes the new SPA and restores it. It also writes a VS leaf PTE, executes HFENCE.VVMA, observes the alternate GPA/SPA and restores it. These tests verify publication and visibility in the uncached path. They do not prove a tagged TLB implementation, remote-hart shootdown, instruction-cache coherence or concurrent DMA coherence.

The old host `SvTranslationService`/TLB path is not extended with V/VMID keys by this patch and must not be substituted into the H assembly. Future reuse requires complete owner keys, permission context, both roots, fence invalidation and stale-proof cancellation tests. Existing host-only identity/prechecked/posted/canonical-store paths are explicitly rejected rather than reused for H.

## Platform and ISA gates

- Physical PMA classification must use SPA and the actual access. HLVX requires read plus execute. Instruction and PTE endpoints must be side-effect-free; the earlier core-only fixture supplies RAM only. The additive shared-platform fixture separately checks ROM/RAM/MMIO attributes and denied physical PTE accesses. The core captures final data cacheability before offering a physical request.
- Sv39/Sv39x4/Bare and Svade are the supported translation modes. NAPOT/PBMT, Sv48/Sv57 and hardware A/D updates are not advertised.
- This assembly enables C and integer execution but leaves F/D and atomic-memory profile options disabled. It does not claim a stock RV64GC operating-system boot or complete guest FP/atomic integration.
- The official AIA/privileged specification version, remaining AIA interpretation notes and excluded profiles are recorded in the AIA conformance scope document. Component priority tests are not a substitute for complete architecture certification.
- No OS boot, ISA-wide external compliance, production-profile PPA or W16 integration has been qualified. Those are explicit gates before advertising H or replacing a production profile.


## Actual shared-platform extension

The next additive candidate connects an explicit `CommonHypervisorCpuTile` to
`CommonMachineFabric`, including actual ROM/RAM, Home, CPU-configured APLIC MMIO,
real MSI request/reply traffic and epoch-matched FENCE.I completion.
`CommonMachinePlatform(experimentalHypervisor = true)` selects it; the default
remains false and the original A1/I1 implementations remain unchanged.
See [hypervisor-platform-integration.md](hypervisor-platform-integration.md) for
the four finite IRQ/cold-reset cases, three VS-origin PMA exception cases, complete
selector elaborations, source identities and hard remaining qualification gates.
No dynamic H-enabled CDC/DDR/DMA, runtime parking, board or OS qualification is
claimed, and the restricted independent M-origin fault review remains unverified.
