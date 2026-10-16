# Targeted real-FIFO queued-cancellation acceptance

This separate test closes the queue-stall/queued-cancellation gap recorded in [the earlier bounded A/B acceptance](atomic-backend-reconstruction.md), for the scenario below. It does not change that earlier test or its evidence.

## Source and stimulus

- Pinned candidate: `d69f4cd2d1e3160853ae22904b795ea9a4c704de` (same reconstructed production tree as the earlier candidate).
- Repaired GSIM SHA-256: `f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116`.
- The exact 95/178 board/core parameter fixture, four LSU entries and two early-load credits are retained.
- `QueuedCancelBackendGsim` extends the existing passive full-entry FIFO observer. A **test-only ready/valid interposer** holds the existing external backend-memory request boundary and its metadata valids. Responses are never gated. The hold starts after warm-up has drained, so it does not withdraw an already offered downstream request.
- A real decoded delayed branch naturally allows two early loads to enter the FIFO, then cancels them. No internal owner, queue pointer, cancel signal, credit or production state is forced.

## Observed result

Status: `PASS_REAL_FIFO_QUEUED_CANCEL_PHYSICAL_DRAIN`.

At the held cancellation witness (cycle 530):

- FIFO occupancy **2**, queued return-handle mask **3**, matching cancelled-handle mask **3**.
- **61** real FIFO stalled cycles and **1** queued-cancellation cycle observed.
- Both cancelled owners retain their exact resident LSU tokens.
- **Zero** new physical requests, physical replies or returned early-load credits while held.

After twelve further held cycles and normal release:

- Exactly **2** physical requests, **2** actual replies and **2** returned credits.
- FIFO empty; enqueue/dequeue accounting equal; killed loads do not retire.
- Total **599 cycles**, **74 stalled cycles**, **1 queued-cancellation cycle**.
- The independent shifting ledger checks the complete native request and posted/canonical/frozen `Valid` payloads throughout the stall, cancellation and drain. These queued loads have no valid posted/canonical/frozen store authority; preserving their full invalid sidecars does not claim stalled valid-store-proof coverage.

The retained-handle negative control toggles one bit in the **host's observed handle mask** and fails with `independent retained queued-handle oracle mismatch`. It proves oracle sensitivity, not an injected RTL fault. The original decoded-instruction, byte-memory, token and physical-response oracle is unchanged.

## Reproduce

```sh
source scripts/cloud/env.sh
python3 simulator/gsim/queued_cancel_backend.py \
  --output /absolute/path/to/new-results \
  --gsim /absolute/path/to/verified/gsim
```

The runner creates a fresh archive of the pinned commit, adds the separate test-only wrapper, hashes source/build/oracle inputs and tools, then emits and runs only this scenario plus its negative control with ASan/UBSan. It does not depend on the working checkout's HEAD matching the pin. The output directory must be new.

## Evidence provenance and remaining limits

The first run generated the new interposer model and all 18 model objects. Its host checked registered cancellation counters one cycle too early: at cycle 529 there were already two queued entries and 60 stalled cycles, but the registered cancelled-handle mask was still zero. That failed receipt and trace were preserved.

The corrected host keeps the boundary held and waits boundedly for the registered cancellation witness. The successful second run freshly compiled this host and reused the **source-identical interposer model/objects**, linking the failed receipt hash and recording reused artifact hashes. It did not reuse the earlier non-interposer model. Successful receipt SHA-256: `6bfaf7d7a2f30a4a68bb3373ef5376fe82cf66213afdc0bd7a59de46a5807e5c`. Receipts/models are local run artifacts, not shipped repository evidence.

This is one directed candidate scenario, not another baseline/candidate comparison or full regression. Posted-cache merge/ACK, stalled valid-store-proof traffic, cache/Home integration, board execution, Linux, synthesis and timing remain unqualified here. No production RTL or earlier acceptance fixture was edited.
