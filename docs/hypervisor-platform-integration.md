# Explicit H tile on the shared machine platform

## Selection and unchanged defaults

This candidate adds `experimentalHypervisor = false` at the end of the `CommonMachinePlatform` constructor. With it explicitly set to true on an A1 profile, the selected CPU becomes `CommonHypervisorCpuTile`, with the already-qualified conservative `HypervisorMachineCore` and three guest IMSIC files. With it false, the existing A1/I1 implementations and zero-guest interrupt fabric remain selected. The older synchronous `MachinePlatform`, production FPGA/W16 profiles, firmware images, and advertised `misa.H` are unchanged.

The new tile is deliberately cacheless and uses the finite, single-owner nested translation services. It must not become the default throughput configuration. Enabling this constructor is an experimental integration choice, not an H-conformance or board-support declaration. The current firmware/device-tree ABI still describes the normal zero-guest production profile; experimental firmware must explicitly configure its H/AIA state.

Runtime-maintenance, cancellation, interrupt-hold, rate-control and other production A1 experimental combinations are rejected. External maintenance commands are not accepted by this tile, matching the existing non-runtime A1 behavior. Architectural FENCE.I is supported through the real fabric drain protocol.

## Actual platform connections

- Scalar lane 0 transports physical data through `CommonNativeOwnerAdapter`, including ordered trap reservation-clear transactions.
- Scalar lane 1 retains independent instruction-parcel, instruction-PTE and data-PTE owners. A registered offer queue and response-owner FIFO preserve each accepted request until its actual response arrives.
- Both lanes request coherence lookup. Neither claims a private-cache bypass authorization.
- The existing `CommonMachineFabric` owns MMIO routing, atomic exclusion, Home, ROM/RAM or DDR, timer and APLIC. Its `experimentalGuestFiles` parameter defaults to zero and is set to three only for the experimental platform branch.
- Real APLIC MSI requests and real IMSIC replies use the existing bidirectional tile boundary. No synthetic interrupt or memory response replaces those paths.
- Inactive coherent and instruction-TileLink ports reject unexpected responses or probes.

PMA checks use the translated physical address and complete byte extent. ROM is executable/read-only; RAM is executable/read/write. MMIO is uncached and cannot satisfy HLVX execute permission. Instruction and PTE requests may reach only side-effect-free ROM/RAM. An invalid/alignment-failing PTE request receives a local access-error response without reaching a device. Fetch parcels are extracted from the physical native beat at the saved address offset, including offsets 0, 2, 4 and 6.

## Fences and reset ownership

The H core has optional platform fence ports, absent in its default standalone shape. FENCE.I stops fetch and waits for the assembler, both translation services, data adapter, read slots, queues, native owner adapters and any reservation-clear response. The tile then submits exactly one epoch to the shared fabric. Retirement waits for the matching actual Home/fabric drain response. There is no fake drain acknowledgement.

Only initial admission hold and shared cold reset are supported. Once enabled, dropping tile enable is rejected rather than treating it as quiescence. Accepted response owners remain live under commit backpressure. A cold reset must cover tile, fabric and their transport together; CPU-only warm reset is unsupported. The existing CommonMachinePlatform startup-only reset extension is preserved.

## Focused qualification

The native test instantiates the actual new tile plus the actual CommonMachineFabric with hardware ROM, 64 KiB RAM, Home, timer, UART and APLIC/IMSIC. It uses one clock, no DMA, and no external DDR. Its test-only gates preserve exposed valid offers until handshake and only introduce lawful backpressure. Image programming occurs before CPU admission. Afterward the CPU, not the test driver, executes all five APLIC configuration stores.

Four actual instruction-execution cases pass under ASan/UBSan:

1. Two-stage translated VS code, guest 1 MSI to VS, claim and SRET.
2. The same with guest 3.
3. Non-selected guest 2 through HGEIE to HS SGEI, retired VGEIN switch, claim and SRET back to translated VS.
4. A shared cold reset while a physical read owner is in flight, followed by complete image reload and successful repetition of case 1.

Each completed case executes three FENCE.I operations, checks both scalar request/reply owners and held payloads, real MSI request/reply backpressure, all four fetch halfword offsets, precise trap PC/cause, claim clearing and pre-handler/post-handler/post-return RAM values. There are 966 counted post-start/post-restart retirements and 444,822 independent checks across the four completed cases. The interrupted prefix in the cold-reset case is not included in those retirement totals. An intentionally wrong independent store expectation is rejected. Three separately rebuilt real-source mutants are also rejected: removing PTE PMA filtering, bypassing fabric FENCE.I completion, and ignoring the saved instruction halfword offset. Each fails the intended independent check with exit 1, not a crash or sanitizer finding.

Three additional **VS-origin** physical-attribute cases pass (320 retirements, 28,919 checks):

- Store to a G-stage mapping of read-only physical ROM: store access fault 7.
- Instruction mapping to physical APLIC MMIO: instruction access fault 1, with no MMIO request.
- VS page-table entry physically mapped to APLIC MMIO: original instruction access fault 1, with no device request.

These cases check precise EPC/stval, retained guest-address provenance, zero guest-page-fault metadata, HS hstatus/htval, and that the faulting instruction never retires. They do not perform the separately restricted M-origin guest-page-fault review.

Both actual `CommonMachinePlatform` selections are elaborated separately: default uses the existing A1 tile with no H state/walkers; explicit H uses the new tile and nested services. I1+H and runtime-debug+H combinations are rejected. This is structural qualification of those complete platform branches, not dynamic CDC/DDR qualification.

Run the reproducible scripts under `simulator/gsim/platform_acceptance.py` and `platform_final_acceptance.py`, using the pinned qualified clean core and tools recorded in receipts. `HypervisorPlatformShapes` provides the separate full-platform selector elaboration check. The complete main-source set is also compiled from a fresh copied source tree.

## Hard remaining boundaries before H advertisement

- No H-enabled dynamic multi-clock CommonMachinePlatform/CDC, external DDR, concurrent DMA drain, runtime park/resume, warm reset or board execution has been qualified here.
- The restricted independent M-origin explicit/implicit guest-page-fault review remains blocked/unverified. It was not retried or replaced by these VS-origin tests.
- No guest OS boot, architectural conformance suite, multi-hart interrupt/VM consistency, nested hypervisor software stack, firmware/DT integration or broad reset/security matrix is claimed.
- The tile has no TLB or private cache, so HFENCE uses conservative local drain and subsequent real page walks. Production TLB/cache owner-context, VMID/ASID and high-throughput proof integration remains separate work.
- The chosen base Sv39/Sv39x4/Bare, ASIDLEN/VMIDLEN zero, Svade and RV64 integer/compressed scope remains unchanged. Optional paging extensions and FP/vector virtualization are not added.
- Ordered reservation-clear transport is tested; this platform program does not execute LR/SC or AMO, and does not qualify atomic reservation invalidation semantics.
- Synthesis, routed timing, bandwidth/IPC and FPGA resource effects remain unmeasured. Finite GSIM cycle counts are test observations, not performance claims.

Accordingly, `misa.H` remains clear, normal platform defaults remain unchanged, and this is an opt-in source candidate rather than a complete production virtualization claim.
