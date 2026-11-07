# Experimental RV64 H and AIA core integration

## Scope and source authority

This clean integration is based on verified commit a6448d9165f9c3c95456fab5895dd66d818c66aa and keeps the earlier experimental source/evidence tree intact. It is not a modification of the generated W16 snapshot. The in-order reference commit `94c4fac446afef73ddfcbe8784b2518f669718c8` explicitly excludes H+AIA and uses GEILEN=0, so it is not evidence that this integration already existed.

The AIA patch applies directly to the clean commit. H changes were three-way ported using the pre-existing dirty source as the merge base; only three constructor conflicts required resolution. Those resolutions preserve the clean APIs and remove the unrelated dirty compact-immediate-storage option. The original experimental tree and original checkout are not edited. Clean qualification has its own manifests and results.

`OooParams.hypervisorExperiment` defaults to false. It adds optional precise fault fields only when selected. The explicit H constructors must agree with that flag. No change advertises `misa.H`. `MachinePlatform` defaults and production profiles are unchanged. The new `HypervisorMachineCore` is a conservative, maintainable experimental assembly, rather than a free-standing CSR model.

## Implemented path

- ROB-head-authorized H/VS CSR banks, privilege/V transitions, MRET/SRET, delegated traps, raw guest interrupt selection and guest IMSIC CSR authorization.
- Live IMSIC identities feed AIA TOPI nomination. Global enables apply to actual trap selection, not TOPI reads. Cross-target priority is M before HS before VS.
- Minimal allowed AIA priority implementation: physical iprio and hviprio arrays are read-only zero; HVICTL implements VTI, six-bit IID, DPR, IPRIOM and all eight priority bits. MVIP software aliases do not latch a hardware SEIP assertion during CSR RMW.
- Guest fault metadata travels with the original fetch/LSU completion, ROB token and head exception. It contains a raw, unshifted GPA, the guest-page-fault flag, GVA provenance and implicit-VS-PTE provenance. HTVAL/MTVAL2 perform the right shift by two exactly once at trap entry. Implicit VS-PTE faults report transformed instruction 0x3000.
- HLV/HLVX/HSV execute through an exclusive, drained ROB-head LSU. HSV captures the actual second integer operand. HSTATUS.SPVP selects effective guest privilege; HLVX asks both translation and final physical permission for execute, while retaining load exception class and requiring physical read permission too.
- HFENCE.VVMA and HFENCE.GVMA conservatively drain all owners. No TLB is present, so address/ASID/VMID operands may be ignored as a stronger fence. HS TVM constrains only HFENCE.GVMA. Valid H instructions attempted in VS/VU raise virtual instruction exceptions.
- Actual fetch and data requests traverse owner-captured Sv39 VS translation and Sv39x4 G translation, including guest Bare requests. The service supports Svade, ASIDLEN=VMIDLEN=0 and base PTEs. It does not advertise Svnapot, Svpbmt, Sv48 or Sv57.

## Ownership and physical integration contract

One scalar instruction/fetch owner and one data owner are supported, with separate nested walkers. Requests and responses retain their context, epoch, virtual address and fault metadata while stalled. A changed fetch PC/context cancels and drains an old owner before any new instruction is supplied. Data cancellation remains owned by the existing LSU until its actual response drains; a live CSR epoch is not used to reinterpret a saved response.

The surrounding integration must:

1. Qualify fetch physical checks as executable and side-effect-free PMA.
2. Qualify data by final SPA, size, access and `forceExecute`, not by the original guest VA. `dataPmaUncached` is captured before the physical offer so a translated MMIO destination cannot accidentally inherit a cacheable VA classification.
3. Connect both physical PTE read ports only to a side-effect-free physical memory endpoint that rejects non-memory PMA. Walkers check PMP on actual SPA PTE accesses, but PMP is not a substitute for PMA.
4. Drain the complete fetch owner on PMP, SATP/HGATP, return and fence boundaries. The experimental assembly connects these drain handshakes.

Host-only prechecked, identity, posted/canonical store proofs, FP memory and buffered/tagged memory optimizations are explicitly rejected in this experimental configuration rather than silently reused across guest context. The baseline floating-point path is not part of this configuration; F/D remain disabled.

## Evidence boundaries

`system-build` uses the actual MachineSystemUnit and IMSIC. It checks CSR/trap semantics but is not an instruction-execution proof. `core-build` executes a real Bare OoO program through ROB retirement and actual guest IMSIC delivery. `translated-build` executes a real OoO program through the actual two-stage fetch/data paths, H memory instructions and precise guest faults. The source files and commands used for each generated model are pinned separately.

The initial translated test passed 216 retired instructions, four guest faults, 965 actual PTE reads, seven physical data operations and 2,271 independent checks under ASan/UBSan. This is evidence for its explicit scenarios, not full ISA certification, OS boot, W16 performance, synthesis timing, or a claim that all default production profiles support H.

The final C-enabled assembly additionally owns a two-byte parcel assembler. It freezes one context across both halves, emits one completion for a compressed instruction, and preserves instruction EPC separately from a second-parcel fault address. Drain acknowledgments include the complete assembler owner. The real-core case executes C.LI and faults the second parcel of a 32-bit instruction beginning at VA 0x40003ffe: EPC remains 0x40003ffe, tval is 0x40004000, and the raw failing GPA is 0x30001000.

The final clean-build run passed:

- Actual MSU/IMSIC: 288 commands, 1,618 edges, 652 checks, including the final VS odd-selector regression.
- Bare actual OoO/IMSIC: 76 retirements, three precise traps, 628 checks.
- Same-DUT physical APLIC source → IMSIC → actual OoO retirement: guest1/guest3 route to VS (98 retirements each), and non-selected guest2 routes to HS (111 retirements) before a retired VGEIN change and CSR claim. Across the three programs: three actual MSIs, 307 retirements, nine traps and 3,420 checks. Real MSI request and response valid/payload stability are checked under backpressure. A wrong-destination negative oracle is rejected. This initial suite is Bare fetch. The subsequent same-DUT AIA plus nested-translation suite is documented separately below.
- C plus actual nested translation and the 12-case MPRV/MPV/MPP access matrix: 474 retirements, four precise guest faults, 1,849 actual PTE reads, 964 physical parcel reads, 43 data operations and 5,202 checks over 22,453 cycles.
- The same clean generated core with a separate HFENCE coherence program: 590 retirements, four precise guest faults, 1,879 actual PTE reads, 1,198 parcels, 49 data operations and 6,034 checks over 25,348 cycles. The program changes actual G and VS PTEs, fences, observes changed translations, and restores them.
- In the preserved original experiment, three real-source mutations were rejected against source-identical H-state, ROB and LSU logic: incorrect HTVAL shifting, dropping the raw GPA in the ROB, and misclassifying a guest data fault as an ordinary access fault.
- Independently authored CSR oracle, replayed on the final clean MSU during clean integration validation: 24 scenarios; H-memory/HFENCE permission review: 120 checks.
- An independent real-OoO 24-case matrix reproduced and then verified the MPRV+MPV static-fault GVA correction for LD/SD, MPP U/S/M, MPV and MPRV combinations. Static faults issue no data/PTE request.
- The four frozen G-stage/data/fetch/assembler fixtures compile against the clean core classes. Their original source-matched component runtime/mutation receipts remain separate from these actual-core runs.
- Default-OFF elaboration: no guest-fault field or HypervisorState instance and no advertised H bit.

The clean integration also fixes a final AIA exception-classification issue. Under
valid VGEIN, RV64 odd EIP/EIE selectors raise virtual instruction exceptions from
VS, as required by IMSIC sections 2.1.8.3/4. A directed oracle reproduced cause 2
on the previous model before the fix. The final test distinguishes four odd
selector boundaries (read/write), M-mode illegal-instruction controls, seven
RAZ/WI slots, out-of-window reserved selectors that remain illegal, and invalid
VGEIN even for an otherwise RAZ/WI selector. See the official
[IMSIC specification](https://docs.riscv.org/reference/aia/v1.0/IMSIC.html).

The cloud replay scripts executed the pinned toolchain directly. The repository-standard `simulator/gsim/hypervisor_core.py` runner was syntax-checked, not executed through Mill in this cloud environment. Generated models and source manifests identify the actual executed path. OS boot, ISA-wide external compliance, production-profile integration and PPA are still separate qualification gates.

## Subsequent same-DUT AIA and G-stage qualification

The unchanged production core is now also exercised with real APLIC sources and
IMSIC delivery while VS instruction and data accesses traverse both translation
stages. Three programs cover selected guest1/guest3 VS delivery and non-selected
guest2 HS delivery with a retired VGEIN change and claim. All 538 instructions
retire against the independent interpreter, all three traps preserve the exact
halfword-aligned EPC, and handler writes are observed by translated accesses
after SRET. Actual G-table and translated VS-table reads are counted separately
for both walkers, with new reads required after return. Complete MSI request and
response fields are checked under actual backpressure. See
`aia-translated-core-chain.md` for the final evidence, precise overlap claim,
reproduction and remaining platform/ISA limits. No production RTL or default
configuration changed for this qualification.


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
