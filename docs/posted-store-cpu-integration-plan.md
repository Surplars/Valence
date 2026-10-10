# Posted CPU proof integration, source checkpoint 1

Delivery note (2026-10-10): this document preserves the initial checkpoint and
its follow-ups. Current frozen-component results, combined-source limits and
remaining checks are in [the integration review](posted-store-delivery-review.md).

Status: **SOURCE ONLY, NOT COMPILED OR SIMULATED**. The default remains OFF.
Base contract commit: 7a1b517fc363c7b194bc6ab1734653d444c3c05c.
Published owner baseline: dev 2886a3b0c8e8ab701ae7caa8c8cf5c7a50534a54,
source tree ccab58e99eccd48ef0ef0644fd9a1330691ae5e1.
This candidate inherits no lost historical CPU PASS or performance evidence.

The MachinePlatform cache constructor and port use the frozen optional API in
posted-store-cache-integration-plan.md. They require the cache author's actual
implementation patch before compilation. There are no production proof tieoffs.

## Authority and immutable transport

`OooParams.postedStoreMerge` defaults to false and requires integer machine/PMP,
VM, buffered stores and the existing naturally aligned successful RAM aperture.
`postedProofConfig` specifies only full ROB tag/index width, epoch32 and
production generation64. MachinePlatform separately supplies enabled owner
configuration from actual cache set/way/MSHR/response/WB capacities and validates
its actual cache aperture. `None` removes all added ports, counters and queues.

The ordinary path captures authority with the actual accepted backend LSU start
while the full token is still the current ROB head. PMP, physical RAM range,
natural alignment, integer origin and non-atomic store shape must all hold.
The original address, aligned data, size and byte mask are constructed from the
same LSU operation and asserted against the actual DataRequest. The fast direct
head StoreBuffer path captures the same facts at its actual acceptance. Neither
path grants authority to virtual, FP, load, atomic, uncached or MMIO traffic.
Physical successful RAM stores retain the existing early local ACK contract;
virtual stores retain recoverable checked translation faults and receive no
proof. In particular identity translation's `fault=false` creates no authority.

MemoryOperation retains the proof in each LSU slot. Parallel arbitration selects
request and proof with its existing locked owner. A proof Queue shares every
actual non-flow request FIFO acceptance/dequeue, with capacity and lockstep
assertions. StoreBuffer records proof with its actual ordinary/fast acceptance
and sets `legacyPostedAccepted` there. Its existing entries retain the proof until
their real ordered external responses. Flow-through copies are asserted to share
that same real acceptance. The adapter captures proof in ingress, saved miss,
translated and checked storage. The checked capture asserts unchanged payload,
full original authority, epoch and actual final PMP permission, then alone sets
`finalChecked`. All request-side response buffers and MMIO routing stages have
combinational request paths, so their enclosing assemblies wire the sidecar.
DataRequest and DataResponseBuffer are unchanged.

## Accepted responsibility and boundaries

An optional backend counter spans accepted LSU/direct proof starts to the real
StoreBuffer external response, including ordinary local early ACK and the
registered request FIFO. Its union with cache busy has no acceptance/ACK handoff
gap. The first posted start waits for all previously accepted CPU memory and
prefetch work. While that union is busy, only additional eligible head physical
stores can launch. Every already accepted LSU/FIFO/SB request remains able to
drain. Backend forwarding cannot start a new load across this boundary, and the
StoreBuffer disables new local forwarding/direct reads while its own posted
entries or external posted owners remain. This deliberately conservative first
integration policy has not been performance-qualified.

The common adapter checked-to-physical gate precedes both APLIC domains and all
external MMIO. A nonposted head waits only for older cache busy. It does not count
itself, younger FIFO stores or raw valid against its own drain predicate.
Existing memoryBusy-based FENCE/FENCE.I/system/PMP/SATP/trap/FP/atomic boundaries
now include accepted posted responsibility. Recovery seals cache runs but does
not clear proof counters or cancel committed writes. The independent fixture
must verify these statements with real instruction execution and held returns.

`endEpisode` requires CPU aggregate idle, adapter idle, no new proof acceptance
and no held proof. It excludes `episodeActive`, which preserves cohort identity
but is not outstanding responsibility. Cache busy still covers retained WB and
ReleaseAck according to the frozen cache contract.

## Context lifetime

The adapter shares its existing full effective VM/PMP comparison and snapshots
with load precheck, avoiding a duplicated wide snapshot bank. The comparison
covers SATP, SUM, MXR, effective data privilege (including MPRV's effect), and all
implemented PMP cfg/address CSRs. A separate posted epoch changes only with a
real context change at aggregate idle; that transition blocks new backend
captures on the same edge, including reset-context initialization. Branch
recovery and load `precheckFlush` may advance the load epoch but never mutate
accepted store proofs or the posted epoch. Architectural context changes with
accepted posted/adapter responsibility assert as an integration violation.

Future H support must extend the captured context and boundary to two-stage
translation, virtualization state, VMID/guest context and the applicable fence
operations. Epoch32 alone does not establish H compatibility; H is not added.

## Qualification still required

- Merge real cache integration; compile once after a global heavy-slot grant.
- OFF elaboration/default profile census and strict invalid-combination checks.
- Independent real-instruction CPU fixture: raw store intent and full token at
  every boundary, ROB index reuse under retained owner, actual PMP/fault cases,
  ordinary load/APLIC waits, fences/context/recovery and held request/returns.
- Separate real cache/coherence-home tests; a synthetic fixture cache obligation
  is a CPU environment premise, never a cache/home correctness claim.
- Fresh same-guest A/B and synthesis/resource comparison only after correctness.

Primary board profile remains selected D-TLB16, LSU4, physical-load ingress,
older-prefix load retirement, previous fetch packet, virtual-load-precheck,
prepared-store-lookahead, checked store prefetch and MRU insertion. The new
`--posted-store-merge` flag is routed explicitly through both board GSIM and RTL
export entrypoints. `--prechecked-data-flow` is rejected with this first candidate;
translated-response empty flow was absent in that initial baseline. The later
delivery preserves its separate default-OFF selector; enabling both options is
unqualified.

## Source follow-up 1: GSIM scalar wrapper routing

Static end-to-end review found that the initial source checkpoint accepted the
CLI selector and built the selected profile but omitted its final two GSIM
wrapper hops. A separate source commit passes the switch from
FpgaNextBoardGsimMain to BoardSocGsim to BoardSocTop, preserving default false,
and adds a lightweight route guard. The initial checkpoint is retained unchanged.
No hardware compilation or behavioral PASS is implied by this host check.

## Source follow-up 2: actual emitted-board qualification

The CLI and PostedStoreCpuConfigSpec now call the same FpgaNextBoardGsim builder.
The pending Scala test elaborates that real board in ON and OFF configurations,
then checks the presence/absence of the real PostedStoreMerge module and
CPU/cache/StoreBuffer proof ports and storage. It checks full token/generation/
epoch widths and the unchanged selected cache geometry. This test has not run.
The board runner also checks its actual emitted FIRRTL before GSIM generation,
records the census, and includes the verifier in its source fingerprint. Host
selector checks remain supplementary and are not emitted-hardware evidence.

The separate CPU lineage fixture uses real instructions and the actual Sv39
walker but only a stated downstream cache-retention environment. Its detailed
scope and unexecuted coverage gates are in posted-store-cpu-lineage-fixture.md.
It cannot replace the real cache/home tests or a real CPU+cache combined run.

## Source follow-up 3: current four-owner fixture profile

The first unexecuted lineage/census checkpoint inherited two LSU owners and left
physical ingress, older-prefix retirement and previous-packet history disabled.
The next fixture checkpoint explicitly selects the current four-owner measured
profile and asserts those actual OooParams values. The old checkpoint is retained
as source history and is not current CPU behavioral evidence. Production defaults
remain unchanged; both ON/OFF tests use the same explicit current profile.
