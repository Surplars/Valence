# R11 opt-in controller cleanup integration

This isolated candidate connects two real ClockRateControl instances to the r10 runtime epoch boundary through a new AON adapter. It is not enabled in the production platform. The default constructor remains unchanged; no production qualification entry, backend-present setting, clock gate or DRP implementation is added.

The optional controller delegates the initial epoch-drain watchdog to r10. Counting starts at accepted boundary requests, not while a second controller waits for the shared owner. Actual r10 drainDeadline/timeoutSelected directs cancellation cleanup; this is not an externally injected cancel used to pretend that a controller timeout was exercised. The deadline wins over matching proof and four full ACKs on the same edge. Matching held is only an additional prerequisite, never a replacement for the independent four drain ACKs.

A timeout keeps the old clock enabled and quiesce asserted. Matching terminal consumption is followed by actual fabric retirement; neither mailbox enqueue nor AON result acceptance completes the controller. Adapter retirement is itself a held consumption handshake: backend locked/open proof must be present before the controller consumes it and the adapter permits another requester. A missing clock proof after real fabric retirement therefore retains the shared rate owner rather than manufacturing completion. Cleanup fault is sticky and never aborts an accepted memory/interrupt owner.

## Explicit limits

- The r10 watchdog stops after the first qualified epoch observation. Later full-system ACK waiting and revoked proof do not restart it. A full-qualification phase watchdog/cancel path remains required.
- Arbitration waiting is unbounded; permanently unresponsive owners require restored progress or coordinated cold reset.
- A boundary cleanup fault remains global/sticky until coordinated reset. A later acquired lease is conservatively marked failed; faulted full qualification cannot authorize gate closure.
- The real fixture sets complete drainAcks to zero. No physical clock transition occurs. Startup lock/open inputs and the allowed 100 MHz point are explicit test-only models, not production qualification.
- The component's modeled normal path checks bookkeeping/quiesce continuity only. It is not real switching, generated MMCM, physical CDC, DDR or board evidence.
- IRQ stop-domain capture, actual IRQ trap/claim/mret and AMO/LR/SC combination coverage, real gate close/open witnesses, complete peripheral admission, DRP and physical signoff remain separate prerequisites.
- Hardware-default 50 MHz and BootROM-direct-Linux compatibility remain goals unchanged by this default-off work. U-Boot is optional; performance constraints remain CPU300/fabric250.

## Validation status

Final source-bound component tests pass 355 cycles plus two independent negative oracles. They cover deadline/full-ACK priority, queued-controller waiting beyond its disabled local watchdog, wrong terminal token/epoch, terminal versus fabric retirement, missing lock/open proof retaining the shared owner, sticky fault, reset, and a clearly modeled normal bookkeeping branch. All three existing ClockRateControlSpec tests pass. Final compilation/fresh emissions pass and the default-off export is byte-identical across all 248 performance-profile SV files. The real-I1 final native suite is still in progress. A read-only review found an intermediate retirement failure predicate too broad and final owner receipt insufficiently backpressured; both were tightened before these final tests.

Intermediate component runs initially timed out because the TB checked combinational ready in the same delta as driving valid and missed the resulting handshake. Only TB sampling was corrected, not DUT assertions. Raw failed receipts and exact TB versions remain in the cloud output directories. The first real-I1 native run was intentionally interrupted for the retirement safety fix after real timeout/cleanup-fault checkpoints; it is not a full PASS and its logs remain preserved.
