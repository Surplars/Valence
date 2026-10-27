# A1 combined checked-data flow experiment

Status: bounded component and actual-CPU comparisons PASS on 2026-10-24. This is not the
unimplemented two-proof/lookahead-cache proposal and adds none of its 399-bit
payload storage. There is no timing, area, 300 MHz, board, Linux or DDR-bandwidth
qualification. Public Selected/FullCandidate/FullR1M3 and runtime/SoC selectors
remain unchanged.

## Explicit policy

`combinedCheckedDataFlow` defaults false in OooParams and FpgaNextConfig. The
explicit `full-r1-m3-checked-flow` rebuild profile changes only:

- `precheckedDataRequestFlow`: false to true;
- `combinedCheckedDataFlow`: false to true.

`translationHitFlow` stays true. All two-wide resources, ROB16/PRF48/LSU4,
DTLB16, translated8/checked2/response-owner8, cache/Home credits, M3 forwarding,
actual store replies and retirement behavior remain unchanged. The legacy board
factory rejects the new policy rather than silently ignoring it.

The combined policy requires registered ingress and checked authorization,
ordinary ordered canonical-store ownership and same-edge canonical events. It
rejects M2 registered translation, posted/tagged returns, pending/frontier/frozen
proof topologies, physical-ingress bypass, translated-response empty flow and
queued-head selection. The two original separate flow experiments remain legal;
an implicit simultaneous combination without the new policy remains rejected.

## Why this experiment precedes proof lookahead

The validated original M3 trace has 48 warm stores and two raw head loads per
guest with DTA upstream-to-physical latency 2. Prechecked loads take 3 cycles:
stream has seven final validation loads; dependency has 48 leading loop loads
plus those seven. One cold store takes 24 cycles in each guest.

The old legal flag swap would disable demand-hit flow while enabling prechecked
flow, adding a cycle to existing warm stores/raw loads. That is not this
experiment. Coexistence targets the redundant translated FIFO stage for a PA
already captured at registered ingress, without taking away the raw-hit path.
It does not accelerate the two-stage production of read certificates or make a
ready head wait for an optional certificate.

## Module contract

Both sources share the existing checked register, not a new arbitration queue:

- Raw demand hit: ingress register, same-cycle TLB result/PMP, checked register.
- Prechecked load: ingress register already carries PA, full PMP/epoch/shape/
  range authorization, checked register; only the empty translated FIFO is
  bypassed.

Target minimum upstream-to-physical latency is 2 for either eligible source,
versus 3 for the old prechecked route. There is at most one incoming/result
transfer per cycle. Query/transfer II=1 is a component target, not a claim that
these serial CPU guests achieve one memory operation per cycle.

`active` excludes precheckedLoad; a prechecked offer therefore cannot also be a
demand-hit offer. Waiting translation or older translated work prevents the
shortcut. Acceptance/translation-response credit remains FIFO-space based.
If checked blocks, the accepted result spills to translated exactly once.
Both queues retain their registered availability and full-release bubble; no
external physical-ready chain is added to ingress acceptance.

Complete PMP read permission, current authorization epoch/change/flush,
privilege/mode, ordinary RAM interval, alignment/mask and precise fault handling
remain. The final physical stale gate and accepted-owner context-drain contract
remain. A legal same-epoch PA remains a trusted upstream certificate input, not
a new unauthenticated mapping or a repeated demand translation.

All new hardware assertions are candidate-only and appended after the unchanged
legacy DTA logic. They check mutually exclusive offers, exact immediate incoming
transfer to either direct checked or translated storage, delayed miss ownership,
blocked prechecked spill and raw-store-only canonical event attribution. They
intentionally permit an older translated head entering checked while a younger
incoming enters translated in the same cycle. A raw miss may instead be held in
waiting/savedRequest without an immediate result.

## Physical-path cost

There is no new TLB-CAM dependency for the registered-PA source. The existing raw
hit path already has a TLB-result-to-PMP/checked cone, and this candidate retains
it. Adding another offer to common head/valid selection, enabling its shape
predicate and widening canonical-source exclusion can increase mux/control
fanout. Cycle latency unchanged on the raw path does not prove unchanged Fmax.
No store is acknowledged or retired early, and no new request/response credit,
TLB port, LSU slot or proof-cache row is added.

## Validation plan and evidence boundary

One coordinated compile/configuration batch precedes two small actual-DTA plus
real 16-entry Sv39 DTLB A/B models, and one actual CommonA1 candidate CPU model
for the two unchanged M3 VM guests. The control CPU is reused only after the
strict disabled-source FIR/artifact-hash gate. No broad GSIM, frontend matrix,
new SoC/DDR model, Verilator or Vivado run is part of this batch.

The adapter oracle must measure raw/prechecked/mixed sustained supply, latency,
checked-full spill, older FIFO/walk ownership, full release, held payloads,
ordered fault/data responses and exact canonical-store events. Context/epoch,
PMP, MMIO/PBMT/atomic, malformed certificate shape and independent negative
controls remain explicit. An enabled malformed shape is rejected; the disabled
historical path retains its original policy. Legal LSU-generated requests cannot
have those forged shapes.

The real CPU must retain 48 actual M3 forwards and 49 actual store requests,
replies and completions per guest, unchanged raw/store 2-cycle adapter latency,
original retirement/memory/final-register oracle and service law. Measure
prechecked 3-to-2 behavior and report work/ROI, traffic and setup/tail separately;
component latency does not substitute for end-to-end improvement.

Historical `prechecked-queue-flow-proof.md` records a separate 2026-10-09 flow
qualification, and `line-read-channel.md` records separate demand-hit flow.
Their old build receipts are absent from this restored workspace, and neither
qualifies the new composition. The following results use newly executed
evidence, with the old CPU control reused only through its explicit identity gate.

## Executed results

The coordinated compile and eight focused Scala configuration/elaboration tests
passed. Two actual-DTA models each completed 783 accepted/returned requests
across eight functional cases. Their matched sustained-supply measurements are:

| 128-request scenario | Control / candidate cycles, including drain/settle | First physical latency | Acceptance / physical span |
| --- | --- | --- | --- |
| Raw TLB hits | 136 / 136 | 2 / 2 | 128 / 128 in both |
| Prechecked PA | 137 / 136 | 3 / 2 | 128 / 128 in both |
| Alternating, prechecked first | 137 / 136 | 3 / 2 | 128 / 128 in both |
| Congested raw | 277 / 277 | 96 / 96 | 256 / 169 in both |
| Congested alternating | 277 / 277 | 96 / 96 | 256 / 169 in both |

Thus continuous acceptance and physical-transfer II remain one in the
uncongested component tests, not an improvement from II=2. The benefit is one
cycle of latency; under the tested congestion total cycles do not improve.
Both full-FIFO release cases retain the one-cycle no-borrow gap. Actual mixed
old-FIFO-pop/new-spill, delayed walk, held payload/reply and full queue witnesses
occurred. Candidate prechecked-spill count is nonzero. Ordered data/fault
results and canonical attribution match the independent oracle.

Nine component negative controls passed their exact marker/diagnostic/exit
gates: four sampled-observation mutations per model, plus a candidate hardware
assertion for deliberately changing authorization before accepted work drains.
These are not nine RTL mutants, and do not authorize arbitrary in-flight
PMP/context changes.

### Explicit malformed-sideband policy difference

The component `shape_hardening` case directly offers 15 naturally aligned
subword/word certified requests and two intentionally invalid certified inputs:

- size 3 (eight bytes), PA `ram + 1`, shifted lane mask `0xfe`;
- size 3, aligned PA `ram + 24`, incomplete lane mask `0x7f`.

Control produces 17 physical requests and zero faults. Candidate produces 15
physical requests and two local access faults. This difference comes from the
**existing** `precheckedShapeFault` guard enabled by
`precheckedDataRequestFlow`, not a newly invented architectural alignment rule.
All other functional-case ordered result fingerprints/counts agree.

These are malformed CPU-to-DTA certified descriptors, not legitimate
misaligned RISC-V instructions whose trap semantics changed. The unchanged LSU
computes misalignment from the original VA and completes with
`LoadAddrMisaligned` before issuing any request; it also requires certified PA
and VA page offsets to agree and constructs the byte mask from size/offset.
The candidate does not modify those LSU exception, tval or request equations.
This component case is therefore hardening of impossible legal ingress, not
proof that the old standalone adapter independently traps misaligned accesses.

### Actual CPU comparison

One new `full-r1-m3-checked-flow` CommonA1 model ran the two unchanged M3 VM
guests, independent retirement/memory/final-register oracle and identical
external service. No alias guest, new SoC or broad matrix was rerun.

| Guest | Retired | Work cycles, control to candidate | ROI cycles, control to candidate | Work-cycle reduction |
| --- | --- | --- | --- | --- |
| Store stream | 233 | 736 to 735 | 568 to 567 | 1 (0.136%) |
| Dependency | 233 | 1120 to 1071 | 952 to 903 | 49 (4.375%) |

Each actual owner is associated using the selected LSU request slot and full
ROB token, then follows ordered ingress, checked, physical and response events.
All seven stream prechecked loads and all 55 dependency prechecked loads move
from three to two upstream-to-physical cycles. The 48 warm ordinary stores and
two raw loads per guest remain two cycles; the single cold store remains 24.
Checked-to-physical is still one registered cycle for every request.

Those sample counts must not be summed into seven or 55 end-to-end saved
cycles: the measured savings are **one and 49**. Overlapping final validation
loads yield only one cycle at the tail; the dependency guest additionally
contains 48 leading loads in its dependency sequence. This is consistent with
the measured totals, not a claim that every local latency reduction lies on
the critical execution schedule.

Both guests retain 48 actual M3 forwards, 49 actual store requests, replies and
completions, and 233 retired instructions. Physical data request/reply totals
remain 58 (stream) and 106 (dependency), including 9 and 57 loads respectively.
Bootstrap stays 168 cycles; drain stays seven; all original CPU metric fields
except work/ROI cycles and their derived IPC values are unchanged. Instruction
TileLink requests/beats remain 136; external data-cache line traffic is also
unchanged. This batch avoids a redundant internal FIFO stage, **not additional
DDR bandwidth or more external traffic**. The CPU fixed-service test has no
injected backpressure; the component matrix supplies the congestion coverage.
Two CPU sampled-observation negative controls also passed exact rejection gates.

### Control identity, failures and receipts

The disabled candidate's newly emitted original M3 wrapper FIR is byte-for-byte
identical to the retained control, even before source-locator normalization:
`fa1662ccc52e493bd9fa1db54b6f5ba2b7ebb2541a7516c79c13893ef1225434`.
The historical model, source inputs, host and pinned tools are hash-bound and
unchanged. The old control was not silently relabeled as a new source model.

Preserved failed attempts are part of the evidence:

1. The first unified compile rejected a test-wrapper reference to
   `OooParams.translationHitFlow`, which exists only on FpgaNextConfig. The
   wrapper-only check was corrected; production was unchanged. Logs and frozen
   inputs remain under `build/checked-flow-20261024-r1/`.
2. Component r1 was rejected by the existing canonical-origin input assertion:
   its host incorrectly attached a store origin to a certified load. Read,
   atomic and explicitly uncached constructors were corrected together. No
   production assertion was relaxed; original inputs/logs/FAIL receipt remain.
   The unchanged baseline FIR/header/generated source/model object were reused;
   only the host was recompiled. Legal origin-free prechecked loads still have
   an independent zero-canonical-event check.
3. CPU r1 rejected only the compiler command-string identity before any DUT
   emission: `clang++-19` versus the historical absolute command
   `/workspace/shared/valence-a1-toolchain-r2/sysroot/usr/bin/clang++-19`.
   Resolved executable hash/version and every other tool field already matched.
   Restoring that exact GSIM_CXX environment command allowed r2 to pass; the
   strict gate, runner and source were not changed.

Authoritative bounded receipts:

- Components: `build/gsim/checked-data-flow-20261024-r2/receipt.json`, SHA-256
  `5b18de36b78b790397c09a95bc556f63f5a7a77025b39edeed4b1e8039fc5393`.
- Component host-only repair/model reuse:
  `build/checked-flow-20261024-r2/component-repair-receipt.json`, SHA-256
  `24b6a688c6fa489ea7cf70f42f7d89dc706a3df653fc5710b95265fbbb8769b1`.
- CPU: `build/gsim/checked-flow-cpu-20261024-r2/receipt.json`, SHA-256
  `d8af8798c93ca437131233af06655c54008aa137f793c05c28ebe9b520485bb8`.
- Per-owner CPU observations:
  `build/checked-flow-20261024-r2/cpu-observed-analysis.json`.
- Failed component r1 receipt SHA-256:
  `c0378326010eeed06506ea8e4cd04a628ea6c14df9807e425eb3cd180c663370`.
- Failed CPU r1 receipt SHA-256:
  `2d6bbff5e18e7aa909ed00578ba395ea18869dd46ff58c745261e0ae72095d7a`.

The final component host is
`a65006fed227846e19d35a763f24a0fd07803ec7ac31dc83fb487f52d760c579`.
Both C++ model paths used Clang 19.1.7 with ASan/UBSan and the pinned GSIM
93b8cd2 executable. Actual command lines, generated artifacts and source/tool
identities are in the receipts; no generated source was edited.

The measured dependent-workload improvement makes this a useful **explicit CPU
experiment**. Selected, FullCandidate, FullR1M3 and all existing runtime/public
SoC selectors remain unchanged. Promotion and physical qualification are separate
work: extra shared control/mux fanout is unmeasured, there is no area/Fmax result,
and no 300 MHz guarantee follows from these cycle counts.
