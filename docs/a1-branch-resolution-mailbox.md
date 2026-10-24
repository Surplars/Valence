# Independent branch-resolution mailbox

This module follows the first dual-owner checkpoint `aaa2af4`. It is **not
connected to IntegerBackend**. Existing A1 execution, clocks, completion order,
and the measured `compiled_sum` 1,458/1,462-cycle comparison are unchanged.

## Contract

`core/ooo/frontend/BranchResolutionMailbox.scala` owns one registered
`FrontendRedirect` payload, including its full ROB token, PC and target.

- Two physical execution sources, at most one selected capture each cycle.
- Capacity one, minimum latency one, no empty bypass. With continuous supply and
  output readiness, the old owner leaves and a distinct new owner enters every
  edge: sustained initiation interval one.
- Source candidates use registered presence, owner and resolved-once metadata.
  The oldest circular ROB position wins, with a deterministic low-lane tie.
  Only then does current per-source kill authorize capture. Killing the older
  winner does not select a younger branch as a fallback.
- `canCapture = !occupied || out.ready` is an early capacity hint, not acceptance.
  Kill and flush do not create same-cycle capacity. A full mailbox cancelled while
  output-ready is low becomes available on the following cycle. If output-ready
  was already high, cancellation may coexist with a different accepted input.
- Ordinary backpressure keeps output valid and the entire payload stable.
  Explicit `cancelHeld` or `flush` may withdraw the old owner and is a separately
  documented exception. Flush also blocks any new capture that cycle.
- A currently held full token cannot be recaptured, including on its drain edge.
  A new generation using the same ROB index is not mistaken for that old owner.
- The two physical sources must own distinct full tokens. Simultaneously offering
  the same token is an **illegal source-ownership state**, with a specific hardware
  assertion and a separate negative test, not an arbitrarily supported alias.
- A source's `sourceResolved` state changes to true only on its actual `capture`.
  It clears only on a new physical holder owner or cancellation. It is registered
  source metadata, never combinational feedback from the same capture. This source
  lifecycle prevents repeated resolution after the mailbox payload has drained.
  The module does not contain an unbounded historical-token deduplication table.
- Mailbox capture is not ROB completion, PRF writeback, retirement or permission to
  alter architectural state. Future integration must preserve those authorizers.

## Executable independent oracle

`simulator/gsim/harness/branch_resolution_mailbox.cpp` models a separate held-owner
queue and two physical sources. Its scheduler walks ROB positions from the head;
it does not use the RTL's pairwise age-comparison expression. The software's own
expected capture, not the observed DUT capture, changes source resolved state.
An independent set rejects a second capture within the same full-token lifetime.

Directed cases cover wrapped age, older-killed/no-younger-fallback, output stalls,
turnover, repeated single-source offers through and after mailbox drain, flush,
kill without borrowed credit, same-index/new-generation reuse, and 32 consecutive
accepted owners at II one. A bounded 6,000-cycle deterministic phase varies legal
source lifetimes, ready and cancellation. Arbitrary index layouts stress the
selector; they are not a proof of backend ROB live-window eligibility.

The runner has two distinct negative controls:

1. Mutate sampled capture after a marker, requiring the independent oracle to
   reject it, not a sanitizer error.
2. Offer one full token from both physical sources, requiring the specific DUT
   ownership assertion after its marker. A host-generated failure alone does not
   satisfy this negative test.

Entry point: `python3 simulator/gsim/branch_resolution_mailbox.py --tag <fresh>
--build-run`, after the coordinated Scala compilation. No tool installation,
Verilator, full regression, NEMU rerun or CPU throughput claim is involved.
The receipt records source/artifact hashes and explicitly sets
`backend_connected=false`.

### Standalone result, 2026-10-24

The focused Scala elaboration test and one GSIM model passed. Receipt:
`build/gsim/a1-branch-mailbox-s1-20261024-r2/receipt.json`.

- 6,061 checked cycles; 2,813 captures and 1,540 simultaneous old-output/new-input
  turnovers, including the exact 32-cycle continuous-supply window.
- 886 held-output stall cycles, 525 killed-oldest winner cases, 64 cancellations
  without borrowed credit, and 2,797 same-index/new-generation captures.
- The deliberate observed-capture mutation reached its marker and was rejected
  by the independent oracle with exit one.
- The illegal duplicate-source case reached its marker and the exact hardware
  ownership assertion, terminating with SIGABRT. This is the expected ownership
  rejection, not an arbitrary host failure or sanitizer fault.
- ASan/UBSan remained enabled; all eight recorded input hashes still matched on
  independent receipt review. No NEMU or connected-CPU run was needed for this
  unconnected module.

These are mailbox capacity, latency, ownership and backpressure results only.
CPU throughput, integrated recovery timing and routed timing remain unverified.

## Future integration boundary, not this change

The current backend generates `newResolutions` only when the physical ALU holder
gets completion credit. Extracting and connecting this mailbox could let a held
branch resolve without waiting for a writeback port, while preserving the existing
registered redirect cycle. It also requires capture-once metadata in the execution
holder and careful redirect-before-completion handling. Test mailbox-full behavior,
older exceptions/replays, two branch ages, recovery cancellation, and retirement
hold before connection. Do not simply substitute `occupied` for `deq.fire`.

In particular, `cancelHeld` must not be wired indiscriminately to the backend's
combined dynamic `killed(mailbox.token.index)` expression. If that mask depends on
this mailbox's own outgoing redirect, the resulting `out.valid → redirect
arbitration → killed → out.valid` path is a structural combinational loop even if
the branch cannot logically kill itself. Distinguish an external older trap or
recovery cancellation from the suffix kill caused by this resolution. Keep the
final common recovery authorization separate and verify the elaborated/lowered
dependency graph, not merely a Boolean argument about self-survival.

The mailbox must replace the existing `branchRedirect` valid/payload registers
when integrated, not precede them as an unintended second redirect stage. Preserve
the precise operand-capture-to-registered-redirect latency and compare it explicitly
under output stalls and external recovery. The present standalone cancellation
input is independently driven by the oracle and establishes no integrated
absence-of-loop guarantee.

That future connected stage needs its own continuously supplied whole-path
baseline/candidate comparison, including the exact earlier `compiled_sum` case,
dependency chains, congestion and recovery. A successful independent mailbox test
does not establish any IPC, Fmax, or 300 MHz improvement.
