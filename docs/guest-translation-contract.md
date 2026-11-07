# OoO nested translation bring-up, 2026-11-06

## Scope and status

`GuestTranslationService` is a new independent OoO-package translation owner, not a port of I1 control logic. It implements VS Bare/Sv39 and G Bare/Sv39x4 with a read-only Svade walk. It does not advertise full H-extension support, an integrated OoO CPU result, Linux guest boot, timing closure, or a high-performance nested TLB. The production host `SvTranslationService` and dirty main checkout are unchanged.

Reference inspected: Valence I1 `94c4fac446afef73ddfcbe8784b2518f669718c8`, `I1HypervisorTranslation.scala`, for integration context only. Architectural rules were checked against the official RISC-V H 1.0 and translation specifications:

- https://docs.riscv.org/reference/isa/v20260120/priv/hypervisor.html, sections 14.1.3.1, 14.1.5, 14.1.5.1, 14.1.5.2 and 14.1.5.3.
- https://docs.riscv.org/reference/isa/v20240411/_attachments/riscv-privileged.pdf, H 1.0 and Sv39 sections, for the prior official snapshot.

## Architectural invariants

- A request captures the original VA, `vsatp`, `hgatp`, virtualized state, effective privilege, actual access type, size, VS SUM/MXR, HS MXR, HLVX flag and epoch. Later input changes cannot reinterpret it.
- A VS-stage page-table pointer is a GPA. Each implicit VS PTE load passes G-stage translation before physical memory. A final GPA also passes G-stage when VS is Bare.
- Sv39x4 uses an unsigned 41-bit GPA, an 11-bit root index and 16-KiB-aligned root. Lower indices remain 9 bits. Out-of-range GPAs fault before any truncated memory address can escape.
- All G-stage leaf accesses require U=1. The G bit is ignored at G-stage. VS global propagation remains distinct.
- Implicit G permission uses load semantics independently of the original instruction/load/store/AMO. Exception classification remains the original access, owned by the caller. Missing A/D produces a fault, never a PTE write.
- VS MXR affects VS only. HS MXR affects both stages. HLVX uses X during both translations, but the actual access remains a load and final physical permission must include both R and X.
- PMP runs on supervisor physical addresses: G PTE reads, translated VS PTE reads, and the final access. A physical denial or downstream read error is an access fault, not a guest-page fault. PMP state must stay stable until idle, as under existing CSR/fence drain rules.
- The response retains original VA and the full unshifted faulting GPA. `implicitPte` identifies a guest-page fault on an implicit VS PTE load. The trap owner shifts GPA right by two when writing `htval`/`mtval2`; no early width truncation is permitted.
- Unsupported modes and reserved PTE fields fault. This base profile deliberately does not implement Svnapot/Svpbmt, Sv48/Sv57, A/D writes or big-endian tables.

## Owner and service contract

Capacity one, at most one offered/accepted PTE transaction, no TLB or page-walk cache inside the service. Requests and completions use Decoupled channels. Initiation interval is the complete variable-latency walk plus completion retirement. A hitless 3-level VS / 3-level G walk requires at most 15 physical PTE reads. Bare/Bare needs no PTE access. Final physical data traffic is issued only by the caller after a successful response.

Cancellation produces one tombstone response carrying the captured epoch. It cannot revoke an already presented physical read; that offer stays stable until ready and its response is drained. No further read is launched afterward. Completion payload stays stable under backpressure. Cancellation after completion has been offered cannot rewrite that offer; the caller must reject stale epochs. Epoch reuse is allowed only after all owners for the prior epoch are retired/drained, not merely after an eight-bit counter wraps.

The caller handles misalignment/split-page accesses before requesting translation. The module accepts aligned scalar accesses of at most eight bytes. Instruction packets must preserve per-parcel fault addresses and any per-word PMP checks beyond the requested scalar beat. The caller must check final PMA and HLVX R+X PMA.

There is no internal translation cache to invalidate. SFENCE.VMA/HFENCE.VVMA/HFENCE.GVMA may conservatively drain this service and globally invalidate any downstream `SvPteDataBridge` nonleaf cache. In-flight walks must never resume across the new fence epoch.

## Real OoO integration points and hazards

The actual translation-service instances are in `core/ooo/platform/MachinePlatform.scala` (two I/D `SvTranslationService`s with `SvPteDataBridge`, physical-memory arbitration, drain/flush logic). A standalone module is not proof that those instances use it.

Integration must also modify the native owners, not wire fault flags to a live CSR snapshot:

1. `VirtualDataRequest.context`, accepted request storage and `TranslationResponseOwner` in `DataTranslationAdapter` need guest context and fault GPA/implicit/epoch metadata.
2. `FetchTransactionCommand`/`FetchTransactionResult` and the registered/pipelined fetch translation owners need the equivalent guest information and parcel-precise faults.
3. LSU/ROB completions and retirement must carry guest-page cause 20/21/23, original VA, raw GPA, GVA and implicit access information to the H trap state. The original instruction class must survive nested implicit reads and HLVX.
4. Guest VS Bare must not use host-only identity paths. Disable or guest-qualify `fetchIdentityTranslation`, `identityDataRequestFlow`, physical/prechecked loads, certified ingress, load peek and posted/frozen store permission proofs. A context epoch must include both translation stages and virtualization state.
5. Every physical PTE response must remain tied to the accepted I/D walker owner across cancellation, memory backpressure and CSR transitions. The PTE cache may retain supervisor physical nonleaf data only with correct PMP gating and fence invalidation.
6. Default host behavior remains on its existing optimized path. The experimental H profile may use this slow, uncached path until end-to-end ownership and fault tests pass.

## Reproduction

Run from the restored cloud workspace:

```
python recovery-1106-gstage-translation/run_focused.py --mutations
```

This uses hash-pinned Scala 2.13.17 / Chisel 7.3.0 and the existing pinned GSIM toolchain. It does not invoke Verilator, legacy simulation, whole-core rebuild, long Linux runs, synthesis, placement or routing. Command receipts, source hashes, test outputs and mutation outputs are under `build/`.

The independent C++ driver tests architectural results and actual physical PTE addresses. It provides randomized request/response stalls, held-offer and held-response checks, live-input perturbation after acceptance, and precise cancellation/draining. Directed tables separate implicit PTE mappings from final data mappings; permissions are exhaustively tested independently of DUT encodings.

## Measured component result

The final nominal GSIM run passed 7,789 accepted translation requests, 52,148
physical PTE reads and 491,241 simulated cycles, including randomized memory and
completion stalls. These cycle totals are test workload totals, not an IPC or
throughput comparison. ASan and UBSan were enabled.

Seven separately compiled source mutants were rejected: truncated Sv39x4 root
index, ignored G U bit, original access type used for implicit translation,
wrong implicit GPA, skipped final PMP, omitted HLVX execute PMP and revoked
cancelled read offer. The cancellation mutant deadlocks and is caught by the
bounded completion oracle.

The optional repository-native entry point is
`python3 simulator/gsim/guest_translation.py` after merging these new files. Its
syntax was checked; the complete restored-cloud `run_focused.py --mutations`
flow above is the executed qualification evidence.

## Single-owner native data adapter

`GuestDataTranslationAdapter` connects the exact shared DataPort wire format
(`NativeMemoryPort`) to a `GuestTranslationPort` and a physical data port. The
native alias and shared port have identical fields. It adds no posted-store,
identity, prechecked-load or TLB shortcut. It snapshots the entire native payload
and translation context on virtual request acceptance; address/access/size come
from that request, not from caller-provided placeholders in the context bundle.
LR uses read permission, SC uses write permission, and other AMOs use read/write.

The adapter clears all virtual permission proof fields before any physical
request. It preserves the accepted write/atomic/data/mask/uncached/return-handle
payload. A physical operation is acknowledged only by its actual completion.
Translation faults and PMA denials return one ordered fault placeholder and issue
no physical data request. Raw GPA, guest-address and implicit-PTE metadata travel
with exactly the same response owner and remain stable under backpressure.

`physicalCheck` exposes the translated address, size, access and HLVX flag for
final PMA checking. `pmaDenied` is captured at this separate authorization stage;
it must be wired to the platform's actual PMA policy. `forceExecute` requires R
and X for HLVX. Physical PTE reads independently require a PTW-safe PMA path,
including restrictions on side-effecting device memory.

`cancel` only kills ordinary reads. Accepted writes and atomics are irrevocable
committed owners and drain normally. Read cancellation before physical offer
returns a tombstone without issuing a data operation. An already presented read
stays offered, drains its actual response and then returns a tombstone. The
caller must serialize side-effecting MMIO and honor `cancelled`/`responseEpoch`.
`translationCancel` must drive the matching service's cancel input; do not also
wire global cancellation directly to that service, which would cancel committed
write/atomic owners. The adapter delays translator cancellation until its held
request has been accepted so cancellation cannot deadlock request READY.

Capacity is one and all stages are registered; there is no same-cycle turnover.
This is a conservative experimental correctness boundary, not a performance
optimization or a claim about the production OoO datapath.

Reproduce the real adapter plus nested translator component with:

```
python recovery-1106-gstage-translation/run_adapter.py --mutations
```

The nominal sanitizer-enabled GSIM run covers 163 accepted native requests,
156 real physical operations and 1,416 physical PTE reads. Cases cover all 64
return handles, live context/payload changes after acceptance, writes, eleven
atomic function encodings, five cancellation points for reads/writes/atomics,
VS/guest/access faults, PMA denial, real downstream errors, HLVX PMA checking and
VS-Bare guest translation. This is actual adapter/translator integration only;
CPU/ROB/retirement integration is a separate required acceptance gate.

Independent review found no confirmed defect in the scoped walker/adapter and
added 25 frozen-model sanitizer-enabled walker transactions (150 PTE reads):
host/guest Sv39 with G Bare, high canonical VAs, physical-width rejection,
implicit execute-only G mapping with HS MXR, HLVX U/SUM and cancellation at every
one of the 15 accepted PTE owners. Review artifacts are in the sibling
`review-hypervisor-core/` directory.

Two integration details are mandatory. A guest-page fault is returned as
`error=true`, `pageFault=false` plus `guestFault.guestPageFault=true`; LSU fault
classification must prioritize this sideband rather than misclassifying it as
an ordinary access fault. Also, the adapter preserves the accepted `uncached`
bit. A mapping to device memory must still be classified using the translated
SPA and actual PMA policy downstream, with caching prohibited and any
side-effecting read non-speculatively authorized. The virtual-address-time bit
is not proof that the translated physical region is normal RAM.

The adapter qualification also rejected five separately compiled source
mutants: wrong raw fault GPA, leaked prechecked proof, cancellation of committed
write/atomic owners, skipped final PMA and acknowledgement before actual
physical completion. See `adapter-build/result.json` and the individual negative
logs; all five were rejected by the independent behavioral oracle.

## Scalar guest fetch adapter

`GuestFetchTranslationAdapter(parcelBytes=4)` implements a single-owner aligned
instruction parcel; `parcelBytes=2` is also tested for future compressed
instruction assembly. Its `GuestScalarFetchPort` has one VA request and one exact
parcel response, with error/page-fault sidebands. It is intentionally not a
replacement for the multiword production `InstructionPort`.

All requests, including VS Bare, pass the captured `GuestTranslationRequest`
context. The adapter overrides access to execute, size to the parcel size, and
forceExecute to false. Final `physicalCheck` requires execute PMA and a
side-effect-free instruction source. `physical.response.bits` is the exact
requested parcel, not a physical 64-bit data-port beat: an integration using a
data-memory reader must select the right lanes before returning it.

The response includes the original parcel `responseAddress`, captured
`responseEpoch`, `cancelled`, and stable `GuestFaultMetadata`. The caller must
assemble instructions/packets, associate the correct architectural instruction
PC, and use the first faulting parcel VA for tval. A 32-bit instruction spanning
a page in a compressed configuration is two independently translated 16-bit
parcels. Merely supporting the 16-bit adapter is not validation of a compressed
frontend or spanning-instruction assembly.

All fetch owners may be cancelled. Held translation and physical offers remain
stable until acceptance, and accepted children drain before one tombstone
completion. The paired service receives only the adapter's `translationCancel`.
A held completion never changes on a later cancellation, so the frontend must
also reject stale epochs and addresses. Drain this owner and downstream PTE
caches when switching translation contexts or completing fences.

The current experimental CPU integration uses the 32-bit adapter with its
non-compressed combinational instruction-supply boundary. Supplying only lane 0
while this conservative frontend waits is a correctness bring-up mechanism; it
is not a demonstration of normal two-wide fetch throughput or end-to-end
performance. The backend configuration remains independently two-wide.

Reproduction:

```
python recovery-1106-gstage-translation/run_fetch.py --mutations
```

The nominal real adapter plus nested-service GSIM runs passed for both parcel
sizes: each 148 requests, 138 actual physical fetches, 1,272 PTE reads, 12,426
cycles with ASan/UBSan. Tests include execute-only VS/G pages, read-only execute
denials, VS U/SUM rules, implicit guest faults, final X PMA, bus errors, 128
captured epochs, context changes while active, five cancellation points, the last
parcel of a page followed by a precise next-page guest fault, and the high Sv39x4
root quadrant. No whole-core, compressed frontend or performance claim follows
from these component counts.

Five separately compiled fetch-source mutants were rejected: using R instead of
X translation permission, wrong guest fault GPA, responding before the physical
fetch returned, forgetting cancellation and bypassing executable PMA. An
independent frozen-model review added ten boundary cases per parcel size; both
configurations passed 158 total requests / 140 actual fetches / 1,312 PTE reads.
No confirmed defect was found within the declared contract. These extra cases
cover X PMP, MXR not granting fetch permission, HS/VS MXR effects on implicit
reads, VU permissions, non-virtualized hgatp bypass and parcel/width boundaries.
The architectural instruction EPC and the faulting parcel tval must remain
separate when the caller later implements compressed instruction assembly.

## C / 32-bit instruction assembly

`GuestInstructionAssembler` owns one complete instruction above the tested
2-byte fetch adapter. `GuestInstructionRequest` captures `pc`, a 64-bit owner
identifier and the full translation context. The response retains that owner,
epoch, architectural instruction PC and a separate faulting parcel address.
No existing adapter or core/state source was changed for this module.

A first parcel with low two bits different from 11 completes one raw compressed
instruction, zero-extended to 32 bits. A supported 32-bit prefix requests a
second parcel at PC+2, independently translating it. Assembly is little-endian:
first parcel is bits 15:0, second is bits 31:16. The module does not decompress C
or decode opcodes. Prefixes denoting an instruction longer than 32 bits complete
with `unsupportedLength=true` after the first parcel and must be rejected as
illegal by the caller; no tail is fetched for this unsupported encoding.

A second-parcel translation, guest-page, PMP, PMA or physical bus fault leaves
response.pc at the original instruction start and sets response.faultAddress to
PC+2. Raw GPA and implicit-PTE provenance come from that exact second parcel.
The caller uses pc for EPC and faultAddress for tval. Instructions crossing a
word or page need no assumption that their physical parcels are contiguous.
A C instruction at the end of a page must never touch the next page.

Both parcels share one captured context and epoch. The complete assembler owner
must be included in fetch-quiescent, CSR/PMP-change and fence-drain barriers; a
completed first parcel is not a drained instruction. Cancellation retains any
held parcel offer, passes cancel only after acceptance to avoid blocking child
READY, drains the child, and returns one tombstone. A held final response cannot
be changed by late cancellation, so caller epoch/owner rejection is mandatory.
The instruction response and all its fault fields remain stable under stalls.

Full-chain component reproduction:

```
python recovery-1106-gstage-translation/run_assembly.py --mutations
python recovery-1106-gstage-translation/run_assembly_host.py
```

The real assembler + 2-byte fetch adapter + nested translator GSIM passed 279
instructions, 420 parcels, 410 physical fetches and 3,742 physical PTE reads in
36,191 cycles with ASan/UBSan. It checks C and 32-bit instructions at both word
alignments, noncontiguous physical pages, C at page end without a tail fetch,
second-parcel VS/G/implicit-PTE faults, PMP/PMA/bus faults, nine cancellation
positions including both held parcel offers, live-context perturbation, owner
and epoch capture, and complete-response backpressure. Four additional host and
guest Bare provenance instructions passed with six physical parcel reads.
Compressed decompression, real CPU packet acceptance, precise ROB retirement and
full guest execution remain separate end-to-end integration tests.

Seven separately compiled assembler-source mutants were rejected: reversed
halfword order, second parcel at PC+4, tval incorrectly fixed at the first
parcel, EPC overwritten by the second parcel, discarded implicit GPA, tail
fetch for a compressed instruction, and forgotten cancellation. Independent
source review found no confirmed state-machine or provenance defect within the
stated contract and recommended strengthening guest/host provenance assertions;
those assertions and the additional host/guest tests above are now included.
