# B2: independent branch resolution from existing execution holders

## Status and baseline

This opt-in change follows `4e8e7ca` and is distinct from the frontend request
pipeline experiment. The pre-B2 completion topology is `dual-owner`; its full
CPU `compiled_sum` latency-one result is 1,462 cycles, versus the original
fixed-lane baseline's 1,458. B2 must compare each unchanged guest and service law
against that dual-owner checkpoint. No 300 MHz, board qualification or CPU
speedup follows from structural inspection or decoded-input measurements.

The B2-only isolated tree compiled successfully. The decoded real-A1 backend
matrix and the unchanged full-CPU 12-throughput/6-memory matrix have passed their
independent oracles. The matched 11-program recovery continuation also passed
336 retirements, with the old witness explicitly reported as zero/not required.
The passive trace reproduced every original B2 IPC field. A separate single
legal external-error scenario also exercised integrated mailbox discard. No
standalone mailbox result is counted as CPU evidence.

## Explicit topology and boundaries

`branchResolutionTopology` has exactly two values:

- `writeback-coupled`, the unchanged default, resolves on accepted physical ALU WB.
- `execution-mailbox`, requiring the bounded dual-owner registered A1 contract.

The latter replaces the old `branchRedirectValid`/`branchRedirect` registers with
one `BranchResolutionMailbox`; it does not cascade another redirect register.
The two execution operand/data holders and two PRF/ROB write ports are unchanged.
Each physical holder gains one resolved-once bit. Only its actual mailbox capture
sets that bit. Completion, cancellation or accepted replacement clear it, with
replacement taking priority even when the old owner captures on that edge.

| Boundary | Capacity | Minimum latency | Initiation interval | Backpressure |
| --- | --- | --- | --- | --- |
| Existing physical execution holder | 1 per lane | 1 | 1 | Original two-WB selection |
| Resolution mailbox | 1 redirect total | 1 | 1 with turnover | Accepted redirect or explicit discarded owner |
| Architectural completion | 2 per cycle | Unchanged | 2 aggregate | Existing oldest dual-owner selector |

The mailbox reads stable old-holder operands and full owner independently of WB.
Fetch faults, page faults, illegal control encodings and misaligned targets never
offer a redirect. They retain the original completion/precise-trap path.

## No late-kill feedback into redirect valid

Mailbox `out.valid` depends only on its registered occupied bit. Integration ties
`flush` and `cancelHeld` low. The old full token is guarded before its index is
used. Output ready is the OR of two mutually exclusive terminal authorizations:

1. Ordinary local recovery accepted this exact full token noninclusively.
2. The accepted recovery killed this old owner. An independent witness requires
   an older boundary, or an inclusive trap at the exact same full token.

A trap sharing the old branch's token is a discard, not publication of that
branch target. Neither terminal event gates output valid. Their feedback through
ready may authorize a different capture, but that path ends at the mailbox and
resolved-bit register inputs. It does not feed source offer, age winner, current
WB selection, ALU data promise or PRF address selection. A lowered-graph check is
still required; reasoning about an impossible self-kill is not a loop waiver.

## WB/retirement progress and two simultaneous branches

A registered resolved holder can still complete while the mailbox is occupied.
Without this exception the branch's own pending redirect could block its WB.
Unresolved control holders retain the old occupied-mailbox WB block. Ordinary
ALUs remain independent, and there is no new branch-compare-to-WB-ready path.

If an empty mailbox sees two mispredicted branches and both write back, it
captures the older resolution. The younger WB has no architectural future.
Assertions independently require it to be younger than the captured token and
to be killed when the older mailbox record is actually published/discarded,
with no retirement while that obligation is pending. This is narrower than
claiming that every speculatively completed branch must have its own redirect.

The existing global branch-retirement hold lasts while the mailbox is occupied.
It must not form a wait cycle with older protected memory/system ownership:
redirect admission is independent of their retirement, then the hold releases.
Tests must observe that sequence, not require retirement during the hold, which
is intentionally prohibited.

## Bounded verification plan

- Focused Scala config/elaboration checks, including default-off and unsupported
  topology rejection; one coordinated compile after the structural batch.
- The original 13 decoded real-A1 programs remain unchanged, including exact FP,
  CSR, recovery, contention, held promises and their independent ISA/byte-memory
  oracle. B2 results are a separate receipt, not replacements for their history.
- A small separate branch program set uses fixed external reply/commit schedules
  to test resolution before WB, pending-owner WB, older protected-memory/system
  progress, two physical branch ages and a faulted branch encoding. Raw full-token
  source/capture/retire observations support a separate procedural observer.
- Both architectural retirement mutation and actual-capture observer mutation
  must reach exact independent rejection diagnostics with sanitizers clean.
- The unchanged full CPU/NEMU throughput, memory and recovery programs compare
  total hardware cycles. The same `compiled_sum` passive trace identifies whether
  the known branch-WB/predictor-training delay was actually removed.

The decoded runner is `simulator/gsim/a1_branch_resolution_backend.py` with a fresh
`--tag` and `--build-run`. It builds both branch topologies with dual-owner WB,
keeps original-13 and directed-case logs separate, and binds source/model/host
hashes. Full CPU/NEMU receipts are produced by the coordinated validation task.
Uncovered events remain explicitly uncovered; no broad GSIM, long Linux,
Verilator or Vivado run is part of this stage.

## Integrated results available so far, 2026-10-24

The immutable first B2 attempt and its exact limitations remain recorded. Two
host-only qualifications were necessary; neither changed the RTL or relaxed an
architectural expectation:

1. The fault-injection fixture deliberately retains decoded `controlFlow` while
   masking rename sources/destination. Real `IntegerCore` constructs a zero-class
   `faultRequest`, so these two inputs exceed its current producer contract.
   The old WB-coupled mode produced an unjustified early redirect and was correctly
   rejected by the strict oracle. That is recorded as an unsupported stronger input
   contract, **not a proven production frontend bug**. B2 passes access/page faults
   with causes 1/12 and the exact fault PC, without capturing either branch.
2. The legacy recovery harness stops a latency/padding search on an old physical
   simultaneous-resolution witness. Early mailbox resolution removes that event
   from the observed run, so the original B2 attempt ran all 384 contention inputs
   before failing that coverage gate. This is not the matched original 11-program
   result. The explicit `BRANCH_RESOLUTION_MAILBOX` host mode fixes the exact old
   eight latency-one/padding-0..7 inputs, retains forwarding and the two recovery
   tail programs, prints the old witness as not required/actually observed, and
   preserves every ISA/NEMU/memory/other coverage check. Default mode is unchanged.

Decoded backend receipt:
`../Valence-b2-4e8e7ca/build/gsim/a1-branch-resolution-b2-20261024-r2/receipt.json`.
The original 13 programs and the four nonfault directed programs each have exactly
identical baseline/candidate hardware cycles. Candidate runs all 19 programs,
including the two defensive fault cases. Both retirement-data negatives and the
independent mailbox-capture mutation are rejected at their exact diagnostics.

Actual integration events in the six directed cases:

- Resolution capture before that owner's WB: 1; its WB while mailbox occupied: 1.
- Younger uncaptured branch WB: 2; independently observed subsequent discard: 2.
- Simultaneous unresolved offers with physical lane 1 older: 2.
- Mailbox occupied while the protected system owner remains live: 4 cycles.
- Strict redirect-before-WB, mailbox turnover/stall/drop, older-lane-0 offers,
  resolved-owner replacement, same-edge kill/enqueue, and protected-memory overlap:
  **0, unexercised**, not silently covered by the standalone mailbox tests.

Full CPU/NEMU throughput retains the continuous ALU and dependency-chain cycle
counts. Eleven throughput cases and all six memory cases are unchanged.
`compiled_sum` latency one improves from 1,462 to **1,461 cycles**, only one cycle;
it remains **three cycles slower than the original 1,458-cycle fixed-lane baseline**.
Latency twelve remains 1,848. This is a narrow scheduling change, not evidence of
general CPU speedup, routed timing, full RV64GC qualification or the 300 MHz target.

### Passive trace: exactly one WB-coupling cycle recovered

The supplemental receipt is `build/a1-b2-trace-r1/receipt.json` in the development
checkout, with `analysis.json` and `trace.log` alongside it. It reuses the exact
10 generated model object files from the accepted B2 model. Only the trace host
was compiled; there was no new RTL elaboration or simulation-model generation.
The host starts from the original `4e8e7ca` architectural/NEMU harness and changes
only passive printing and selection of the existing compiled-sum latency-one case.
All original measured IPC fields match the non-trace 1,461-cycle run exactly.

Zero-based cycle evidence:

- Cycle 38: physical ALU1 owns branch tag 36 with no WB credit, but mailbox capture
  mask 2 accepts its resolution. Cycle 39 sees the registered resolved bit and
  publishes that redirect. Pre-B2 dual-owner published it at cycle 40.
- Cycle 43: load tag 24 again forwards from the store path. The old dual-owner
  schedule issued the same load without forwarding. From retirement ordinal 24
  through the final instruction, B2 is exactly one cycle ahead of dual-owner.
- The sum-loop direction counter first becomes taken at cycle 1,261, still one
  later than original fixed-lane cycle 1,260. The extra warmup redirect moves
  from pre-B2 1,264 to B2 1,263; it does not disappear. The eventual delta versus
  original fixed-lane remains +3 cycles, not zero.

The evidence establishes a specific decoupling benefit and the remaining
retirement/training phase difference. It does not justify changing global WB
priority or claiming the entire earlier regression has been removed.

### Separate functional supplement: older load fault discards the mailbox

A single additional host-only case reused the accepted execution-mailbox model.
It is an adversarial functional schedule, **not matched performance traffic**:
the already accepted older load response is released with a legal access-fault
error after observing the younger independent branch's rename. No internal owner
is forced, no phase search is performed, and the original 19 cases are not rerun.

The first fixed run passed:

- Cycle 5: external older load request accepted.
- Cycle 6: younger branch renamed; cycle 7: that load's error response handshakes.
- Cycle 8: mailbox captures the branch; cycle 9: the older load traps precisely
  and the mailbox is discarded, not published.
- Capture 1, drop 1, publish 0. Only the two older prefix instructions retire;
  neither the faulting load nor any younger instruction retires. There is one
  accepted request and one error response, with zero stores and no byte-memory
  change. All 32 committed GPRs and the exact cause-5/tval result match the
  independently executed architectural program.
- 15 execution/drain cycles plus 32 inspection cycles, with ASan/UBSan enabled.
  These numbers describe the functional scenario only and are not a speedup.

The prior 19-case host remains archived at SHA-256
`988dede603afb1ab2c941bd764f5b82bef70a875731c2f9e226f6344cad3102f`.
The new host and this one-case receipt are separate provenance; the earlier
19-case receipt is not rewritten to pretend it used the later host revision.
Mailbox turnover/stall, reversed unresolved physical ages and same-edge
kill/replacement remain unexercised in the integrated tests unless separately
stated. No default profile was enabled and no physical timing was measured.

Supplement artifacts are at
`../a1-branch-drop-host/receipt.json` and `../a1-branch-drop-host/test.log`,
with command `run --branch-fault-drop-only` in that model build. Receipt SHA-256:
`4e22dec6d72db52be25699deacc85d9ab2f910eee4c4306847ee48c5af639651`.
The final supplemental host is
`a784aaee575763b9eea8853d5ff913b4b86f95fe275f4fd6f51304f5e6e8600e`.
The old model's sole later source-manifest difference was the separately validated
lazy profile-registry repair; its original exact profile source is archived, and
all generated model/header/FIR/parameter bytes remained unchanged. The repair
leaf independently re-emitted all three B2 FIRs byte-identically.

All B2 dynamic CPU/backend measurements use the original two LSU entries. The
four-LSU-entry `combined-branch` profile has configuration/tile elaboration
coverage, not these dynamic measurements; combining it with the frontend or
memory experiment still requires a separately identified comparison.
