# A1 fetch S1 independent review

Date: 2026-10-24. Baseline: commit `aaa2af4`.
Scope: the actual registered-heads translation-adapter decomposition described
in [the S1 proposal](a1-fetch-stage1-implementation-proposal.md). No production
source was modified by this reviewer. This document initially records source
review, not a hardware-test or timing PASS.

## Source identity and mechanical comparison

The following working-tree source hashes identify the reviewed implementation:

| Source under `src/main/scala/core/ooo` | SHA-256 |
|---|---|
| `interfaces/FetchTransaction.scala` | `d1f5fc62c242cb50d50d1d53a0b077e2cbdafce179cd51ac6ec401fbeab1f8ae` |
| `mmu/RegisteredInstructionTranslationEngine.scala` (corrected r2) | `0de8202319a5e4b0ffad33c5f61b9706f8e308a696008c8736514e1779465f25` |
| `mmu/InstructionTranslationAdapter.scala` | `24cdce000ba7664fdeffd91e3ed2c79da32d76ff33984ba2cc9436f990f26155` |

**Correction retained in the review record:** the first combined compile (r1)
failed because a global string replacement had also changed two child-module
`checker.io.privilege` connections into nonexistent `checker.io.command.bits.privilege`
ports. The initial review's global normalization made the same mistake and its
reported equality was insufficient evidence. That unconditional initial
mechanical-equivalence claim is withdrawn. The failed compile log remains in
`build/a1-s1-20261024-r1/scala-compile.log`; no passing compile had been claimed
by this review.

After the owner restored the two original checker ports, comparison was rerun
with a **top-level-only** mapping: an `io` reference preceded by a member-access
dot or identifier cannot be rewritten. Exactly two original top-level privilege
references are mapped, not the two child ports. The mapped old registered FSM
body and corrected new body are identical after removing indentation and blank
lines. All ten `checker.io` connection/use lines were additionally compared
without mapping and manually reviewed: both checker variants retain original
PMP state, saved privilege, address/base, word size, execute access and denied
result connections. No child `io.command` or `io.result` replacement remains.
The two nonregistered adapter branches remain byte-identical. The frozen
comparison adapter matches the baseline after only the class-name change.

The original `A1FetchSupplyGsim.scala`, supply runner, `driver.cpp`, `oracle.h`,
and `oracle_test.cpp` were hash-checked against the checkpoint and were unchanged.
This prevents a new service law or easier oracle from being mistaken for a
cycle-preserving implementation. It does not substitute for running the model.

## Acceptance, response and turnover

The new boundary stores `occupied`, `activeToken` and `nextToken`. The engine
captures its own token on the original command-acceptance edge. The returned
token is that engine register, not a token attached retrospectively from the
boundary's current state.

For a legal engine transaction, `occupied` is equivalent to engine state not
being `idle`, and a valid engine result carries `activeToken`. Then:

- In idle, boundary credit is available and engine command readiness is the
  original idle readiness.
- In reply, the old result is presented to the caller only if its identity
  matches. Real caller acceptance releases credit; `result.valid` alone does not.
- With turnover enabled, old reply acceptance permits the new command on the
  same edge. With turnover disabled, engine readiness still prevents it.
- In all translating/sending/waiting phases, no second command is accepted.
- On a simultaneous old-result release and new-command acceptance, allocation
  wins the boundary state update. The pre-edge result remains the old token/data;
  the command uses `nextToken`. Neither the old clear nor the new token overwrites
  the other transaction's visible payload.

An independent Boolean truth-table check covered all 64 combinations of the eight
FSM states, turnover enable, request valid and response ready under the legal
owner invariant. Request-ready, both acceptance events, response-valid and
release matched the original equations. This is an algebraic check, not RTL
simulation. The production wrapper also asserts equal boundary/engine idle state.

No combinational cycle was found: result-valid derives from the old registered
reply state, identity derives from old token registers, and result-ready derives
from caller readiness. Credit may feed command-valid/ready but does not feed any
of those old-owner inputs. The actual SynchronousFetch response sink remains
always ready and drains old accepted transactions after redirect.

The boundary does **not** contain an immutable context snapshot: command VA,
mask, SATP and privilege are passed through until the engine's real acceptance.
When turnover is disabled, old-result release may expose a command for one
cycle while engine-ready is still false. Stability in that window depends on
the caller retaining the entire offered context. In the actual integration,
SynchronousFetch's pending/locked ownership and the existing context-drain
barrier provide that precondition. A generic standalone user of the boundary
cannot assume arbitrary live-CSR changes under stall are supported. Tests must
include legal release-with-engine-stalled then next-cycle acceptance, and the
old/new adapter comparison must cover turnover disabled. Adding a new early
context-capture edge would change the original sampling semantics and is outside
S1; future multiple-owner work needs a genuinely immutable context contract.

## Permission, faults and exact original priorities

Mechanical comparison and manual review retained these nontrivial cases:

- Request-ready still controls the existing ready-only `firstPhysical` capture
  and optional data clear. New context/token capture requires actual fire.
- SATP mode/root/ASID, SUM, MXR and privilege sample at the original request edge.
  PMP remains a live input until the original first `sendFirst` permission
  capture, including a blocked physical offer. It is not snapshotted early.
- Translation request/response may both fire in one cycle. The original later
  response assignment still clears `issued` with final priority.
- With identity translation enabled, a zero mask goes directly to reply after
  command capture. A nonidentity zero mask still takes its original translation
  path. No zero-mask transaction is silently dropped or releases credit early.
- Generic cross-page behavior, second-page faults, second-only physical sends,
  and placing a returned second physical word into result word 1 are unchanged.
- Captured permission masks and errors remain fixed during physical request
  backpressure. Physical replies, page/access fault aggregation and the reply
  holding registers retain their original assignment order.
- New-command initialization wins over old-reply release. No cancel or guessed
  stream epoch was added. A redirected old accepted owner still completes/drains;
  the existing caller decides whether its bytes are stale.

One assertion-coverage difference was reported and corrected: the engine's
credit-gated command-valid would hide an invalid unaligned public offer while
busy. The wrapper now retains the original public-offer alignment assertion,
even when that offer is not accepted. This does not alter valid-trace behavior.

## Timing and token-width costs are not zero

S1 claims zero **added cycles**, not PPA equivalence. The new full-token equality
gates `response.valid` and `result.ready`, and consequently release, credit and
request-ready on turnover. Its operands are registered and it can compute in
parallel with FSM reply decoding, but it is still a new combinational control
cone. Counter and two-sided token storage also add logical state; whether
synthesis merges redundant state is not established by source review.

Registering the comparison is not automatically latency-free: an identity
zero-mask request can produce its reply in the first cycle after acceptance.
That legal path has no general spare cycle for a new match register. The current
review does not bypass or weaken token qualification to hide its cost.

The default 64-bit token is not justified merely because the ROB uses 64-bit
tags. A future reduction requires an explicit contract: one internal owner,
real terminal acceptance before reuse, no outstanding duplicate/late internal
result, and reset only with the relevant external obligations drained. Wrap
tests must accompany any reduction. Neither 64 bits nor a shorter token replaces
PTW/physical-response ownership or provides permanent identity against arbitrary
delayed duplicates. No routed 300 MHz, resource, or fmax claim is made here.

## Independent validation boundaries

The new boundary fixture uses a host-controlled engine and an accepted-owner
history, checking context, generations, payload, faults, withheld credit and
turnover. Wrong-generation and duplicate-result negatives must specifically
observe the **hardware route assertion**. Merely seeing nonzero exit is not
sufficient: a driver that complains that hardware failed to reject the input
also returns nonzero. This runner requirement was reported to the owner.

Held-data and turnover-context observation mutations must be rejected by the
independent payload/history oracle, with a diagnostic showing the intended
mutation was reached. The proposed long completion delay includes 17 cycles;
an initial 1-through-7-only generator was flagged as insufficient for that claim.
The corrected test generator includes 1/2/7/17, mandatory release-with-engine-
blocked coverage, and a two-bit boundary configuration with 256 accepted/drained
transactions and 64 expected wraps. Its four negative modes require the intended
injection marker and exact hardware/oracle rejection, not merely nonzero exit.

The paired test runner now uses the actual Selected streaming configuration with
turnover enabled, generic two-word cross-page streaming with turnover disabled,
and isolated four-word requests with identity/turnover disabled. Thus the
no-turnover stream explicitly presents a new held offer during old-result
release; the isolated case alone would not cover that window. These are reviewed
test designs; execution status comes only from the subsequent receipts.

The old/new adapter pair is a cycle-equivalence witness, not the sole permission
or ISA oracle. The unchanged nine supply scenarios still need exact per-scenario
fields, hashes, latency histograms and drain results, including work cycles
580/332/644/688/1034/433/59/25/22. They are supply measurements, not core IPC.
The scheduled short checks and their final receipts determine test status;
this source review does not independently run extra regressions.
