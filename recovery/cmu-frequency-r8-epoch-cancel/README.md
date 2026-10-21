# R8 cancellation after actual drain (opt-in)

`runtimeCancellation=true` requires `runtimeMaintenance=true`; both remain off in production. A1 remains unsupported. No CMU register/timeout integration, production rate whitelist, DRP, clock gate or FPGA constraints are enabled here.

## Owner and cancellation contract

The fabric owns an accepted external prepare epoch separately from the currently draining maintenance epoch, which may still be an older ordinary FENCE.I. A matching cancel request can be accepted before runtime status, during real drain or while held. It is sticky and does not cancel any accepted memory/probe/reply/GrantAck owner. Invalid, stale, duplicate or post-release cancel offers are unaccepted and have no side effects.

A cancellation finishes the existing real drain and consumes its matching completion before scheduling the same CPU resume message used by normal release. Matching simultaneous cancel wins over normal resume; a wrong cancel cannot block a valid resume. Home admission stays blocked through CPU resume delivery, not just fabric enqueue.

The CPU retains the epoch after consuming resume. Two actual CPU-domain rising edges with the aggregate quiesce request low cover the core's registered release bubble; a held maintenanceResumed(epoch) response is then returned to fabric. These are destination-domain edges, not a fixed AON waiting period. They prove local release processing, not PLL lock, correct frequency, physical gate-open or system-wide barrier release. An independently asserted external stop delays this response. New prepare stays blocked through response/terminal ownership.

On matching CPU response, fabric releases Home and offers runtimeComplete(epoch,canceled). Terminal bits remain held under backpressure and the external owner remains allocated until that result is consumed. Epoch tokens must not be reused before retirement; equality alone cannot defeat arbitrary ancient replay after finite-width wrap. Common cold reset remains the only reset cancellation contract.

## Recovery versus safety limitation

A timeout decision must eventually issue a matching cancel, not an early normal resume. The old clocks must continue while cleanup runs. A delayed owner that eventually responds permits safe recovery. A permanently stalled accepted owner, or a CPU clock that never supplies release edges, prevents successful cancellation. The endpoint preserves ownership and does not fabricate quiescence or a terminal success. Repair of the responder or a supported common cold reset covering every owner is then required. Finite stalled-owner tests establish safety, not unbounded liveness.

The production ClockRateControl is unchanged. In particular its DrainTimeout/resuming timeout path is not yet connected to this protocol. A future AON bridge must latch the timeout-versus-qualified-ACK decision, suppress any late ACK from starting gate closure/programming after cancellation wins, and await the matching terminal result. A terminal protocol event is not a replacement for gate/lock/edge confirmation.

## Current real combined test

The full I1/private-cache/Home fixture uses transparent backpressure on actual ReleaseAck and fabric completion channels, never manufactured responses. Six prepare epochs yield exactly five accepted cancellations, one normal resume and six terminal results. It checks early cancellation, held ReleaseAck, queued drain completion, held cancellation, simultaneous matching cancel/resume, invalid cancellation alongside normal resume, wrong/stale/duplicate cancellation, terminal backpressure and data preservation after recovery. An external stop held for 18 CPU cycles prevents false resume proof; subsequent real CPU release edges are required. Independent retirement/load/store oracles and a deliberately wrong data oracle remain active.

Observed native result: 36 stores, 36 loads, 48 dirty release beats, six terminal results; wrong data oracle rejected. See native-receipt.json and logs for exact source/RTL/tool hashes. This fixture is single-clock and internal-RAM; it does not establish independent-clock CDC, physical timing, board acceptance, full interrupt/AMO integration or actual CMU timeout counting.

Run with `python3 simulator/gsim/common/i1_runtime_epoch_native.py --out <fresh-directory> --iverilog <existing-tool> --vvp <existing-tool>` after sourcing scripts/cloud/env.sh. The explicit cancel inputs represent timeout decisions at different owner phases; they are not a fake ClockRateControl backend.

The normal-resume and cancel inputs are a single controller's mutually resolving choices, not two independently persistent requesters: when matching cancel wins a simultaneous offer, the losing unaccepted resume must be withdrawn after observing cancel.fire. A new resume offered after release started is a duplicate and remains an assertion failure. An eventual AON bridge must own and serialize that decision.

Fresh default-off production performance export remains 248/248 SystemVerilog files byte-identical to r7 (and r6). No default production ready chain or generated clock frequency changes are introduced. The CPU/fabric timing target remains 300/250 MHz; no physical qualification is inferred from this equality.

## Final fabric and compatibility results

The real fabric's cancellation mode passes under ASan/UBSan: 7 prepares, 5 cancels, 2 normal resumes, 7 resume deliveries, 7 CPU release acknowledgements and 7 terminal results, with 42 AXI writes matched by 42 real B responses. Tests include equal numeric ordinary/runtime epoch 50 distinguished by ownership type, an older ordinary FENCE during external cancellation, late stale CPU acknowledgement while a newer epoch owns release, delayed matching acknowledgement, same-edge completion/cancel, and an ordinary FENCE while terminal output is backpressured. Wrong/stale/duplicate cancels cause no acceptance or result. Early/wrong/duplicate normal resume offers trigger their exact DUT assertions; wrong-data oracle is rejected.

Legacy runtime-maintenance-only mode still passes (1322 cycles, 27 writes/27 B), and default fabric mode remains 1247 cycles, 27 writes/27 B. All three modes use the same final source snapshot and independent wrong-data negatives. The strengthened combined CPU test also asserts the exact increment/store/load/branch/jump retirement sequence and exact dirty-release ledger, rejecting skipped or duplicate architectural side effects rather than merely printing counts.

Reproduce fabric modes using `simulator/gsim/common/fabric_machine.py --cloud-tools` with `--runtime-cancellation`, `--runtime-maintenance`, or neither, each with a fresh `--out` directory. Scalar test ports are direct wires around the real fabric; no simulator backend or generated-model logic is patched.
