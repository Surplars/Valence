# Atomic backend reconstruction: bounded integrated acceptance

This is new qualification of reconstructed source, not recovery of a lost commit or reuse of its historical PASS.

## Pinned scope and reproduction

- Baseline: `223453bae0185dcc59b9ea5414ddb266e1f5af93`.
- Candidate: `e3e1ff348db09c663bbb25bffc59974da7256ccf`.
- Repaired GSIM executable SHA-256: `f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116`.
- The runner creates exact git archives, checks an explicit 12-file production-difference allowlist, and applies the same test-only observer to both arms. It hashes Scala sources, build inputs, original oracle files, driver, observer and executable.
- The real decoded backend/translation fixture requires board/core configuration arities **95/178**, three proof rows, two early-load credits and four LSU entries. Its actual core parameters must equal `ThreeProofRowNativeProfile.config.coreParams`; emitted parameter JSON must match between arms. This is not an executing-board test.

From a checkout containing both pinned commits and these test files:

```sh
source scripts/cloud/env.sh
python3 simulator/gsim/recovered_atomic_backend.py \
  --output /absolute/path/to/new-results \
  --gsim /absolute/path/to/verified/gsim
```

The output directory must be new. The command compiles/emits both bounded backend fixtures, generates GSIM models, builds with ASan/UBSan, runs positives and retirement negative controls, and writes `receipt.json` plus logs. It does not invoke Verilator, Vivado, Linux or full regression.

## Observer and oracle

`RecoveredAtomicBackendGsim.scala` passively samples the real request FIFO's enqueue/dequeue boundary. A four-entry shifting ledger independently checks non-flow/non-pipe capacity, ready/valid timing, occupancy and the complete native request plus posted/canonical/frozen `Valid` bundles, including invalid metadata payloads. Full return handles, token indexes/tags, epochs, permission bits, addresses, data, size and masks are retained. The observer neither gates traffic nor flushes accepted ownership.

The original decoded-instruction, byte-memory, full-token, physical-response and retirement oracle is unchanged. The original lifecycle driver's sole textual adaptation renames its `main` for reuse. Additional scenarios hold physical request/response service and inspect exact drain obligations.

## Observed result

Status: `PASS_PINNED_RECONSTRUCTION_BACKEND_TRANSPORT_AB`. Both arms produced identical actual-core JSON and all metrics below.

| Lifecycle scenario | Cycles | Retired | Accepted instructions | Physical requests/replies | Early starts/credit returns |
| --- | ---: | ---: | ---: | ---: | ---: |
| Two bound stores, same-epoch frozen PTE, two credits | 835 | 123 | 123 | 8/8 | 3/3 |
| Oldest-store late fault | 774 | 118 | 123 | 7/7 | 3/3 |
| Selective kill, bound store survives | 914 | 121 | 123 | 7/7 | 2/2 |
| Full kill, physical-response credit drain | 668 | 119 | 123 | 5/5 | 2/2 |

Additional real FIFO observations (counts are events/cycles, not unique owners):

| Scenario | Enqueued/dequeued | Stalled cycles | Queued-cancel cycles | Resident-cancel cycles | Canonical/frozen/posted valid enqueues |
| --- | ---: | ---: | ---: | ---: | ---: |
| Held physical response | 8/8 | 0 | 0 | 0 | 3/2/0 |
| Full kill with held response | 5/5 | 0 | 0 | 1 | 1/0/0 |

Both retirement negative controls failed with the expected `fault/killed/duplicate retirement` oracle diagnostic. These inject an invalid retirement into the host observer; they demonstrate oracle sensitivity, **not injected RTL faults**.

## Evidence provenance and limits

The first run compiled/generated the baseline model and all 18 model objects, then failed compiling the new host because its metrics function used a const object with non-const generated getters. That failed receipt/logs were retained. The successful second run freshly compiled the corrected host and **reused the source-identical baseline model/objects**, recording their hashes and linking the failed receipt hash. The candidate model was newly generated in the second run. Do not describe this as two freshly generated models in the successful run.

Successful receipt SHA-256: `191bfaefc3ef7f9df753588efcad563b60b1e13f9f08e75bb792ddc9cf5c2036`. Receipts/generated models remain local run artifacts; this document does not claim they are shipped with the repository. The runner's optional `--reuse-run` accepts a terminal failed run only after checking pinned commits, executable identity, source inventories and unchanged observer.

Coverage not supplied by this A/B run (the later directed test below is separate evidence):

- **Zero real FIFO stall and zero queued-cancel cycles**: this integrated run does not qualify cancellation of an owner while still queued or held at that FIFO boundary.
- **Zero posted-valid enqueues**: virtual-only traffic has no posted-cache authority. Posted-cache merge/ACK behavior is untested here.
- Resident cancellation and real physical-response/credit draining were observed; they do not substitute for the missing queued-cancel case.
- No cache/Home integration, executing board, Linux, timing, synthesis, PPA or full-regression claim.
- The original `atomic_request_proof_backend.py` guards and original independent oracle remain unchanged.

## Subsequent directed queued-cancellation test

A separate test-only external ready/valid interposer, pinned to `d69f4cd2d1e3160853ae22904b795ea9a4c704de`, subsequently exercised the missing real FIFO stall/queued-cancel case. At cycle 530 it observed two queued entries, matching queued/cancelled handle masks of 3, 61 stalled cycles, one queued-cancel cycle, and zero pre-release physical requests/replies or returned credits. Exact resident LSU tokens and the full FIFO metadata ledger were retained. After twelve additional held cycles and release, exactly two requests/replies and two credits drained; final totals were 599 cycles and 74 stalled cycles.

The retained-handle negative control corrupts a host observation, not RTL. The initial run's one-cycle-too-early registered-counter observation failure was preserved; the successful retry freshly compiled the corrected host and hash-linked the unchanged interposer model/objects. This directed candidate result is not an additional A/B run and does not qualify posted-cache merge/ACK or stalled valid store-proof traffic. See [queued-cancel reproduction, provenance and limits](queued-cancel-integration.md).
