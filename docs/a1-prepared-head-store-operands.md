# A1 independent head-store operand row (experimental)

Status: bounded row, configuration and actual Common-A1 CPU validation passed on
2026-10-24. Stream work cycles fell **735 to 687**, while dependency stayed **1071**.
Frequency, area, board and DDR bandwidth remain unmeasured. Selected, FullCandidate
and existing named profiles remain unchanged. This experimental batch is not
connected to the public/runtime SoC selector.

## Why this candidate

A passive host-only observation of the existing checked-flow CPU model preserved
all 158 original metric fields, every original owner timestamp, and both complete
retirement/memory oracles. Evidence is in
`build/gsim/checked-store-preparation-analysis-20261024-r1/manifest.json`.
It observes 48 warm stores in each unchanged guest:

- Stream: store admission intervals are 11 cycles. Every store already has saved
  VA/data 33–42 cycles before head, but takes one cycle from becoming head to LSU
  start. The preceding cycle retires one ordinary ALU; normal preparation is
  occupied by a younger load, not empty.
- Dependency: intervals are 18 cycles. Store data first becomes ready when the
  store reaches head, with no saved complete-store row before start. This candidate
  must fall back immediately to normal preparation, not wait for an optional row.

The possible stream opportunity is at most 48 local one-cycle windows. That is
not a measured end-to-end saving. Dependency has no observed saved-row opportunity.
Neither another proof cache nor late-commit overwriting of normal preparation is
implemented.

## Explicit stage and ownership contract

`PreparedHeadStoreOperands` stores only a full ROB token, numerical VA, data and
size. Capacity is one preparation row, minimum latency one cycle, pre-head refresh
II=1, no empty flow. At current ROB16/tag64 geometry this is 198 payload bits plus
one valid bit, **199 bits**, parameterized rather than fixed to that geometry.
It contains no PA, read/write permission, epoch certificate, request credit or
accepted memory owner.

The existing registered `head + 1` selects an already-address-known, already-
prepared ordinary virtual store. No PRF port, AGU, TLB query or walk is added.
Capture uses early registered owner/head facts, never accepted commit, ready or
issue fire. A live current-head row holds its complete payload. Only actual LSU
start for that full token consumes it. A consumed head row cannot refill on that
same edge; subsequent preparation resumes from the existing registered rows.
Flush/recovery/context and dead/reused tokens invalidate disposable preparation.
The row is deliberately absent from memoryBusy, ownersIdle and fence/park drain.
Otherwise an older system operation could wait forever for a younger intent.

The normal memory preparation stage, load query and two-level read-proof boundary
keep their original inputs. A complete `PreparedStoreIssue` bundle joins the
normal and saved-store sources only at the existing LSU issue boundary:

- token, PC, VA, data, size and operation class;
- forward and prechecked metadata, serial/parallel class, destination sideband;
- canonical epoch/start, pending clear, order-check and protected owner bookkeeping.

The prepared source is always an ordinary virtual, serial store. Its payload
starts from zero and cannot inherit the normal younger load's forwarding,
prechecked proof, destination or parallel credit. PC is read from the exact actual
head, not retained in another 64-bit register. Real DTA translation, PMP/range,
MMIO treatment, faults, reply and precise retirement remain mandatory. There is
no posted acknowledgement or early architectural retirement.

The selector still excludes the **actual issued index**, including a saved-row
store. Normal-stage consumption is separately identified. Turning off planner
issued on a row start would incorrectly recapture the just-issued head store.
Final system/IRQ/recovery/exception and LSU credit checks authorize valid only;
they do not select a new wide capture payload. A missing row takes the old path.

## Scope and cost

Default-off flag: `preparedHeadStoreOperands`.
Explicit candidate: `full-r1-m3-checked-flow-store-row`, exactly the preceding
`full-r1-m3-checked-flow` configuration plus that one flag. Its distinct memory
policy rejects mismatched profile/flag combinations. Construction excludes the
historical resident/posted/tagged/pending-proof/fast-retirement modes. The helper
itself supports alternate ROB/tag geometry, while the integrated candidate keeps
A1's two-wide, ROB16/PRF48/LSU4/cache-MSHR2 resource contract.

This costs more than the 199 stored bits: an additional logical saved-row read,
head/full-token/class matching, valid/hold/cleanup control and a final complete
LSU-payload mux are new. The selected payload includes PC and optional metadata,
so its current **type width is 715 bits**: 707-bit MemoryOperation plus parallel
and a 7-bit destination sideband. The 707 includes a 240-bit canonical-forward
sidecar and 33-bit store-epoch field. Many store-side fields are constants; 715 is
not a measured physical mux width or resource count. Constant folding has not
been quantified by a lowered-resource or physical report. It avoids
late-commit control of a 202-bit capture mux, but does not remove muxing or routing
cost and does not prove the 300 MHz target.

## Focused verification scope

- One tiny actual-row model covers both ROB16/tag64 and ROB8/tag9. Independent
  finite shelf oracle checks initial capture, 64 continuous refreshes, head hold,
  consume gap, dead/reused owner replacement, flush priority, wraps and random
  transitions. Seven exact hardware-assertion negative cases plus one sampled-
  payload negative check full-token/head/liveness/flush rejection and the oracle.
- Pure configuration/shape checks prove default-off, one-flag delta, distinct
  profile identity, incompatible-mode rejection and parameterized owner widths.
- One actual Common-A1 candidate CPU runs the same two short guests and unchanged
  service law. Preserve all 233 retirements, 48 successful M3 forwards, 49 actual
  store requests/replies/completions, and precise data/memory oracle. Observe row
  starts against their full token and saved operands, and fallback when absent.
- Reuse the prior checked-flow control only after its source/tool/artifact binding
  and strict fresh disabled-control FIR gate pass. Source-locator differences are
  not permission to ignore structural changes. Preserve failures and any explicitly
  reviewed correction rather than rewriting receipts.

Report actual work/ROI cycles for both guests alongside local stage timing and
traffic. Local preparation II=1 is not a second store issue port or extra memory
credit, and reduced CPU-internal cycles are not external DDR bandwidth evidence.


## Actual results

A single unified compile and six configuration tests passed. The tiny row model
passed 4,108 cycles: 2,530 captures, 1,672 pre-head refreshes, 819 live-head holds,
235 consumes, 387 dead replacements, 151 flushes, 15 index wraps and two tag wraps.
Both token shapes and the 64-cycle continuous-refresh interval were exercised.
All seven isolated invalid consumes reached their exact hardware assertion and
returned SIGABRT (-6). The independently corrupted sampled payload was rejected
with its exact oracle diagnostic and exit 1. Real generated-header syntax checking
preceded C++ model compilation. This is row lifecycle evidence, not CPU throughput.

| Same original guest | Control work | Candidate work | Control ROI | Candidate ROI | Actual row starts / fallback |
| --- | ---: | ---: | ---: | ---: | --- |
| vm_store_stream | 735 | **687** | 567 | **519** | 48 / 1 initial cold store |
| vm_dependency | 1071 | **1071** | 903 | **903** | 0 / all 49 stores |

Stream saves 48 work cycles (6.53% fewer cycles), with 48 captures and 48 row
starts. Its 47 measured warm-store admission intervals all improve from 11 to
10 cycles; dependency's remain 18 cycles. Initial cold-store admission stays at
cycle 123, while the last stream store advances from cycle 688 to 640. These are
actual fixed-guest intervals, not a general maximum issue-II claim. The dependency guest performs zero row captures or choices and keeps every
original CPU metric equal, including all owner timestamps. It does not wait for
unavailable saved data. Normal load starts are 57 and 105 respectively, including
the unchanged 48 M3 forwarded loads in each guest.

Each guest retains 233 architectural retirements, 48 successful M3 forwards, and
49 actual store requests, replies and completions. All original retirement/data,
service, final-GPR and architectural load-readback oracles pass. Relative DTA stage timing remains identical:
one cold store at 24 cycles, 48 warm stores at two cycles, two raw loads at two
cycles, and 7/55 prechecked real loads at two cycles. The store row removes the
head-only preparation bubble, not translation, permission, memory service or
precise store completion latency. Every original stage metric is equal; stream's
original CPU-field differences are only work/ROI cycle counts and derived IPC.
External instruction/data traffic is unchanged, including one data acquire/grant.
This is improved CPU work per cycle in the stream guest, not increased DDR bandwidth.

The actual CPU observer independently tracks the registered row and joins each
accepted issue to its selected full owner. It never assumes every LSU start comes
from the normal staged-memory register. Two CPU sampled-output negatives, prepared
store data and retirement data, returned exit 1 with exact markers/diagnostics;
ASan/UBSan did not report an error. One DUT object and one host object were freshly
built for the candidate. No additional model or broad regression was run.

These two CPU guests exercise ordinary virtual integer stores/loads with real
MPRV/Sv39 translation and fixed service. They are not a new whole-SoC, MMIO/AMO,
trap/interrupt stress, or physical timing qualification. Those paths were not
relaxed; the candidate stays default-off and retains serial actual-head effects.

### Strict control gate and retained rejected attempt

The first CPU attempt correctly refused historical-control reuse: after removing
only FIR source-location annotations, one auto-generated assertion diagnostic still
changed from `IntegerBackend.scala:3454` to `IntegerBackend.scala:3472`. The r1 FAIL
receipt and exact diff remain intact. Independent review confirmed the same
PopCount dispatcher-bound assertion. Only that complete diagnostic string, exactly
once on each side, was explicitly approved for mapping. Every remaining normalized
FIR byte then matched. This is **not raw-FIR byte identity** or general numerical-
string normalization.

The r2 runner reused only the already emitted disabled-control FIR/config/logs,
with source/tool/hash checks, then built the candidate fresh. Production, Scala,
host and historical baseline model remained unchanged. The only r1-to-r2 input
change was the private CPU runner's explicit control-reuse/mapping logic.
Final common mapped FIR SHA-256:
`f4fca0349d5b9089fb9c932e9ed4af4c91fa68b7977150ae2832da0e7d112543`.

Reproducible evidence:

- Row component: `build/gsim/prepared-head-store-component-20261024-r1/receipt.json`,
  SHA-256 `91038975cde2c72ff5c6c0ab6cbe24dea9e44e1bef68e594d718272b28a00fe5`.
- Rejected CPU control gate: `build/gsim/prepared-head-store-cpu-20261024-r1/receipt.json`,
  SHA-256 `7046a44d6ba6bdc2a20b7d303bc742b9e8fd4397593f6b882759cb9016b62e37`.
- Final CPU: `build/gsim/prepared-head-store-cpu-20261024-r2/receipt.json`,
  SHA-256 `8822545165993f9a8a604b2577126a3d562b0e25441902d672e4ce92dbba3390`.

No synthesis, placement/routing or new STA was performed. The 199-bit preparation
state and 715-bit typed join are explicit cost boundaries, not a 300 MHz guarantee.
