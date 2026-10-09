# Four-owner passive observer host proof

Run from the repository root:

```sh
python3 simulator/gsim/tests/mlp4_owner/run_host_tests.py
```

This builds only small, ordinary C++ host fixtures with ASan, UBSan and standard-library assertions. It does not invoke Mill, GSIM, firmware, NEMU, or an RTL model. Generated binaries, logs and `host-test-receipt.json` remain under `build/mlp4-ledger-preparation`.

## Contract

- `BACKEND_OWNER_COUNT` is explicitly 2 or 4 and defaults to 2. Four-owner builds require the new count probe to report 4. New two-owner models must report 2; old two-owner models without the added getters remain supported.
- Slot 0/1 tags and the historical 16-bit `backendSlotIndices`/`backendSlotState` retain their exact meanings. Slots 2/3 use separate 64-bit tags and `backendSlotIndicesHi`/`backendSlotStateHi` with the same two-slot layout. In each pair: live bits 0/1, phase bits 2–5, parallel bits 6/7, cancellation bits 8/9; indices occupy bytes 0/1. `backendReturnSlot` carries 0–3 without truncation.
- Every ownership comparison uses the separate ROB index **and complete 64-bit allocation generation**, never address or aggregate counts alone. Fixtures intentionally reuse one ROB index and generation low bits while varying high generation bits.
- Both the backend request FIFO and LSU response-owner queue are parameterized by `memoryEntries` in the production source, hence 2/4 entries. `BACKEND_REQUEST_CAPACITY` defaults to the same owner count and rejects disagreement. These are distinct from the two-entry adapter ingress, checked queue, and relocated response buffer. The test traces assert those capacities separately.
- Four-owner slot shadows start empty. Accepted starts independently establish physical slot identity, old full-token completion identifies same-cycle replacement, and request/response/completion handshakes govern lifetimes. Cancellation is remembered until the accepted read drains and its final result is discarded. Hidden pre-request and result-ready owners are rejected, even when request/response counts are unchanged.
- Request and response queues retain their ordered, non-flow request and local-ack flow semantics. Data-path ledgers retain full request fingerprints and persistent buffered-write lineage after local acknowledgment. Both base and selected identity-shortcut ledger variants support upper-owner returns/cancellation.
- Stalled FIFO-enqueue owner/payload and LSU response payload remain stable across observations; existing held FIFO/ingress/translated/checked fingerprints and accepted physical request/return payloads remain checked.

## Independent cases

`four_owner_test.cpp` constructs explicit observations from its own named transaction stages and fixed request/reply fixtures. It never reads a ledger's queue contents to produce a succeeding sample. It covers four simultaneously live/request owners, four physical owners, same-cycle full-slot completion/replacement, simultaneous FIFO dequeue/enqueue, local result/fault completion, forwarded result cancellation, fast-load release, cancellation before request acceptance and before/after physical issue, reset, and ordered drain.

The 54 corruption cases include lost slot 2/3 owners, swapped slot placement, high-bit stale generations, duplicate tokens, hidden fifth starts and physical owners, premature release/completion, double returns, swapped physical lineage, and corrupted stalled/returned payloads. The existing two-owner backend test and all 39 existing data-path corruption cases run unchanged.

`probe_reader_test.cpp` compiles against a plain C++ mock probe object, not a generated model. It verifies exact tag widths/pair packing, owner-count mismatch rejection, hidden upper-state rejection for two-owner models, return slot 3, and complete free-slot histogram columns. Separate expected compile failures reject a four-owner build against legacy probes, unsupported owner count 3, and an incorrectly fixed two-entry backend FIFO.

## Limits and source review

This is host-observer preparation, not functional hardware, performance, timing, synthesis, or board evidence. Four-owner observation must run continuously from reset/start; beginning in the middle of live ownership is intentionally rejected. Legacy two-owner slot semantics/report format remain unchanged, while four-owner mode enables the additional strict slot-lifetime shadow.

A start which produces neither an observed request nor a forwarded result may be request-arbitration stalled or an immediate alignment/access fault. The observer permits only request/result-ready initial phases in that case, retaining the exact new full token; it does not claim an independent fault-decode proof. Subsequent phases require the corresponding observed handshake.

The physical request port does not expose separate raw valid/ready probes. Held checked-head fingerprints and accepted physical payloads are verified; an unaccepted physical-port-only transient is outside this probe contract. Translation and downstream authorization rules are unchanged. `performance_observer.h` and `data_path_sample.h` require no owner-width edits: their fixed-size arrays count commit lanes or named ports/stages, not LSU owners.

The reader packing was checked against `BoardSocGsimMain.scala::slotPairState`; owner start/release rules were checked against `ParallelLoadStoreUnit.scala` and `LoadStoreUnit.scala`; request capacity against `IntegerBackend.scala`. The runner hashes all observer headers and host sources before/after execution, captures compiler/commands/log hashes, and verifies that `harness/board_hot_nemu` is unchanged from baseline `66c06d7`.
