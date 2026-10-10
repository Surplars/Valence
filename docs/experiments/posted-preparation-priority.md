# Posted preparation priority (default OFF)

This experiment changes only the candidate pool for the existing registered
memory payload preparation stage. It starts from the opt-in frontier/LRU source
checkpoint `7c5191ed205f9716bc137c09c4ad993afc7755de` (the published development
checkpoint is `e2f506c9a67a742d3bcd63751625e82840fb53e3`). No performance, native
combinational acyclicity, mapped timing, or hardware correctness qualification is
inherited from that checkpoint.

## Selection contract

Let O be the original memory-candidate mask before issued-owner exclusion, and P
be the existing safe prepared-store mask. The existing fallback is O when O is
nonempty, otherwise P. That fallback remains unchanged unless all these conditions
hold:

- The new option is enabled, registered accepted posted ownership is busy, and
  the current data context is physical (`!virtualized`).
- O is explicitly nonempty, and **every bit in O** describes an ordinary decoded
  load: memory, not store/atomic/system/mulDiv/control-flow/fetch-fault/fetch-page-
  fault, with `IntegerOp.add`.
- `blockPostedStart`, `interruptDrain`, `contextMemoryEpoch`, `fpMemoryEpoch`, and
  `ledger.io.recovering` are all false.

In that window the planner receives O | P, retaining the original circular
oldest-first selection and issued-owner exclusion. An older ready load still
wins over a younger prepared store. A ready head store remains in O, makes the
all-load test false, and retains its original priority. This does not select P
alone, latch a preferred store, or add a rank, port, queue, buffer, or PMP path.
The empty-O behavior remains the pre-existing prepared-store lookahead.

P is unchanged: pending and memory-live, nonhead, current token index, ordinary
decoded store, prepared address and data, known aligned physical RAM range.
P does not imply PMP permission. Final head, full-token, PMP, alignment, alias,
accepted-owner, fault, ACK and recovery checks still authorize actual requests.
The change has no dependency on the planner result, `postedLaunchAllowed`, LSU
start/fire/ready, seal, or a same-edge authorized kill.

## Intentional timing effect and unchanged authority

The actual launch and seal equations, payload capture, posted owner drain, and
all downstream memory state machines are byte-identical to the base. Their input
selection can occur on a different cycle. In particular, an older safe prepared
store can precede a younger ordinary decoded load whose address later proves to
be MMIO, misaligned, or PMP-faulting. That load may therefore be selected later,
and the unchanged selection-driven seal equation may act later. Decode-only
qualification does not claim all original loads are RAM or permitted.

This timing effect is part of the experiment, not a proof that seal timing is
unchanged. It requires explicit focused coverage for MMIO/faulting loads, drain,
recovery, wrap/reuse, and posted accepted-owner behavior. No cycle savings can be
predicted from the observed one-cycle preparation gap alone.

## Explicit entry points

- `OooParams.postedPreparationPriority`, appended with default `false`.
- `FpgaNextConfig.postedPreparationPriority`, appended with default `false` and
  propagated into `coreParams` and `managedBoard`.
- `BoardSocConfig.boardParams`, `BoardSocTop`, `BoardSocGsim`, and
  `CanonicalOverlapBoardGsim` accept the same default-false parameter. Their
  shared FPGA-next/canonical board builders forward it unchanged.
- Native `fpga/next/export.py` / `ooo.FpgaNextMain`, GSIM
  `simulator/gsim/fpga_next_board.py` / `ooo.FpgaNextBoardGsimMain`, and the full
  constructor reporter `ooo.FpgaNextProfileMain` accept
  `--posted-preparation-priority`.

The option requires `preparedStoreLookahead`, `postedStoreMerge`,
`registeredMemoryAddress`, and `parallelMemoryPreparation`. Existing posted
prerequisites still apply. The CLI checks both explicit parent flags before
creating output. All FPGA-next profiles already provide the reviewed registered
preparation path; direct core/Board construction additionally checks it.

Example host-only preflight:

```sh
python3 -B fpga/next/export.py --output /tmp/fresh-priority-export \
  --prepared-store-lookahead --posted-store-merge --posted-preparation-priority
python3 -B simulator/gsim/fpga_next_board.py --tag priority-preflight \
  --preflight-only --variant selected --prepared-store-lookahead \
  --posted-store-merge --posted-preparation-priority
```

The profile name gains `-posted-preparation-priority` only when selected. Complete
Scala configuration reports include the new false field on control profiles;
native preflight preserves the historical omitted-option profile bytes. The
recommended performance preset, its options, frozen JSON, and hashes are
unchanged and never enable this option. Existing historical full-constructor
checks account for the new field explicitly as false without changing the old
field expectations. Source/parameter similarity alone does not authorize reuse
of a previously generated control model: newly generated profile/code bytes must
establish that correspondence.

## Verification scope and measured result

The default-OFF candidate has closed five original matched CPU pairs on tested
production aa37b6a00666ee9be4284ea1793cd376c0775344. It improves only the narrow
Bare COPY preparation window measured here. The recommended performance v3 is
unchanged. The complete integrated src/main tree is byte-identical to the tested
source tree 52da00911b5ee66cca85b24c46ffc02a8ed9607d.

| Case | OFF kernel + flush | ON kernel + flush | Primary result |
| --- | ---: | ---: | --- |
| Bare COPY19 | 384,957 + 5,562 | 380,840 + 5,572 | GAIN |
| Sv39 COPY21 | 345,578 + 5,565 | 345,578 + 5,565 | EQUAL |
| Warm READ0 | 16,458 + 0 | 16,458 + 0 | EQUAL |
| Warm READ6 | 24,589 + 0 | 24,589 + 0 | EQUAL |
| WRITE18 | 112,761 + 10,643 | 112,761 + 10,643 | EQUAL |

Bare19 gains approximately 1.081% kernel throughput and 1.063% total throughput.
ROI AR/R/AW/W/B remain 4,099/32,792/2,049/16,392/2,049. ROI-empty cycles decrease
188,110 to 183,883, while read-owner-cycle sum is exactly 159,869 on both sides.
Its occupancy average can rise because the ROI is shorter; this does not show
faster DDR service. ON total 386,412 still exceeds original recommended-v3 total
370,853 by about 4.19% cycles. This does not justify promoting the frontier/LRU
profile or changing the recommended preset.

Each new pair retains original byte/row, precise fault/trap/CSR, cache/owner,
AXI conservation/drain, parser and real-trap-negative checks. Warm0, warm6 and
WRITE18 use the separately frozen functional-pair closure; a speedup or nonzero
translation witness is not required for their functional pass. The earlier
published parent's frontier/LRU five-case results are separate identities and
are not inherited as qualification of this priority candidate.

Sv39's original pair status remains `NO_CASE21_GAIN_AND_STRUCTURE`: it is
functionally qualified with equal primary ROI/tail performance. Its physical
context guard excludes the new choice during Sv39 operation. Physical boot and
passive owner-observation diagnostics can differ; equal primary counts do not
claim complete cross-side JSON or trace identity. Its seven exact proof mutations
per side passed. Unreconstructed cross-interval joins remain UNKNOWN.

### Focused behavior and native cost

The actual raw-decoder/backend/cache fixture passed 26 programs per side and
three exact data/token/timing poisons per side, using one immutable r4 host and
the fixed r3 validator. Independent checks cover instruction decoding, backing
bytes, full-token ownership, actual PMP, precise exceptions, retirement, real
translation, recovery/token reuse and posted owner/writeback drain.

Focused main store start changes 266→265. The final-drain boundary regresses
291→293 and retains one registered store stage before original-load selection
resumes. Both architectural results pass; no all-case timing nonregression is
claimed. Fresh full CPU models, actual constructor/profile/ABI checks and RV64GC
positive plus real-negative gates passed on both sides.

Negative controls are counted separately: the five CPU cases execute ten actual
trap-negative runs (one per side per case); Sv39 case21 additionally checks 14
actual-original-parser proof mutations, with no new DUT execution for those
mutations; the focused fixture executes six exact poisons. The two model/GC
`--inject-mismatch` controls fail at the exact `firmware independent anchor/context
failure` check. These are different contracts and are not combined into one CPU
gate count.

Native reachable scalar and array register deltas are zero, with equal ports and
RAM geometry. IntegerBackend emitted SV grows by 26,224 bytes from additional
combinational logic. Mapped area, PPA/STA and physical-board behavior remain
unmeasured. No formal-equivalence or hardware-clock improvement is claimed.

### Preserved failures and integration checks

The initial focused r1 OFF matrix passed 22/26. Its remaining host failures are
retained: virtual-store logic incorrectly demanded a frontier-bank insertion,
context bookkeeping omitted real internal CSR cancellation, and recovery/token
reuse drove external recovery illegally under the registered-branch profile.
Final r4 changes only independent host stimuli/oracle and numeric JSON rendering,
including a real raw BEQ recovery and actual virtual translation lineage.
Production, wrapper, profiles and compiled models did not change. Earlier host
revisions and failure logs remain in the focused archive; the old full54 suite
belongs to older source and is not reused.

In the independent integration checkout, the priority CLI suite passed 3 tests,
recommended-v3 suite 9, LRU CLI 10 host cases and existing selector policy 5 host
tests. Tracked snapshot hashes/AST and wrapper bytes also passed. These are
source/host checks; no new integration hardware execution is claimed.

The historical `test_selection.py:79` native metadata assertion fails identically
on the published-equivalent baseline and this candidate: it compares fresh
command output paths and nested prepared-store metadata after removing only
top-level fields. That assertion is unchanged. Exact snapshots also preserve
two harmless whitespace findings in the original CPU contract and native fixture.
No full-repository test pass is claimed.

### Source and evidence reuse

The dedicated Scala wrapper is tracked under src/test. Independent C++/raw
reference, strict validators, exact control contracts and warm/WRITE closure
sources are retained with original paths and hashes under
`simulator/gsim/posted_preparation_priority`. Only the src/test wrapper is compiled;
historical snapshot Scala files stay outside Mill source roots.

The CLI invariant check uses the actual published parent tree rather than an
unpublished local recovery commit. This changes only test baseline addressing;
its comparison bytes remain equal. Ordinary checkout byte/AST verification uses
`python -B simulator/gsim/posted_preparation_priority/verify_sources.py`.

See `posted-preparation-priority-evidence.json` for exact terminal pair identities,
original statuses and the bounded checks. The tracked evidence index contains
confirmed Library IDs, versions, sizes and SHA256 values. Full raw/model artifacts
are external. Historical replay requires the original absolute paths and pinned
tool/source/model bindings; a relocated fresh run requires a new binding and
new receipts. Neither copying a snapshot nor running its source checker creates
runtime qualification.
