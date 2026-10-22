# R11 opt-in controller cleanup integration

This isolated candidate connects two real ClockRateControl instances to the r10 runtime epoch boundary through a new AON adapter. It is not enabled in the production platform. The default constructor remains unchanged; no production qualification entry, backend-present setting, clock gate or DRP implementation is added.

The optional controller delegates the initial epoch-drain watchdog to r10. Counting starts at accepted boundary requests, not while a second controller waits for the shared owner. Actual r10 drainDeadline/timeoutSelected directs cancellation cleanup; this is not an externally injected cancel used to pretend that a controller timeout was exercised. The deadline wins over matching proof and four full ACKs on the same edge. Matching held is only an additional prerequisite, never a replacement for the independent four drain ACKs.

A timeout keeps the old clock enabled and quiesce asserted. Matching terminal consumption is followed by actual fabric retirement; neither mailbox enqueue nor AON result acceptance completes the controller. Adapter retirement is itself a held consumption handshake: backend locked/open proof must be present before the controller consumes it and the adapter permits another requester. A missing clock proof after real fabric retirement therefore retains the shared rate owner rather than manufacturing completion. Cleanup fault is sticky and never aborts an accepted memory/interrupt owner.

## Explicit limits

- The r10 watchdog stops after the first qualified epoch observation. Later full-system ACK waiting and revoked proof do not restart it. A full-qualification phase watchdog/cancel path remains required.
- Arbitration waiting is unbounded; permanently unresponsive owners require restored progress or coordinated cold reset.
- A boundary cleanup fault remains global/sticky until coordinated reset. A later acquired lease is conservatively marked failed; faulted full qualification cannot authorize gate closure.
- Controller submit and responseCommitted are explicit test stimulus. This fixture does not qualify the complete software/MMIO response-consumption path.
- The real fixture sets complete drainAcks to zero. No physical clock transition occurs. Startup lock/open inputs and the allowed 100 MHz point are explicit test-only models, not production qualification.
- The component's modeled normal path checks bookkeeping/quiesce continuity only. It is not real switching, generated MMCM, physical CDC, DDR or board evidence.
- IRQ stop-domain capture, actual IRQ trap/claim/mret and AMO/LR/SC combination coverage, real gate close/open witnesses, complete peripheral admission, DRP and physical signoff remain separate prerequisites.
- Hardware-default 50 MHz and BootROM-direct-Linux compatibility remain goals unchanged by this default-off work. U-Boot is optional; performance constraints remain CPU300/fabric250.

## Validation status

Final source-bound component tests pass 457 cycles plus two independent negative oracles. They cover deadline/full-ACK priority, queued-controller waiting beyond its disabled local watchdog, wrong terminal token/epoch, terminal versus fabric retirement, missing lock/open proof retaining the shared owner, sticky fault, reset, and a clearly modeled normal bookkeeping branch. All three existing ClockRateControlSpec tests pass. Final compilation/fresh emissions pass and the default-off export is byte-identical across all 248 performance-profile SV files. The final real-I1 native suite passes both unrelated/reversed clock ratios and all three independent negative oracles. A read-only review found an intermediate retirement failure predicate too broad and final owner receipt insufficiently backpressured; both were tightened before these final tests.

Intermediate component runs initially timed out because the TB checked combinational ready in the same delta as driving valid and missed the resulting handshake. Only TB sampling was corrected, not DUT assertions. Raw failed receipts and exact TB versions remain in the cloud output directories. The first real-I1 native run was intentionally interrupted for the retirement safety fix after real timeout/cleanup-fault checkpoints; it is not a full PASS and its logs remain preserved.

The subsequent real-I1 r2/r3 failures were a test admission-timing mistake: the TB asserted two additional IRQ sources after AON request acceptance but before the actual fabric prepare handshake. Diagnostic r3 records fabricPrepares=2 at that request, then accepted=6/replied=3/blocked=1 at the third timeout: two owners were legally admitted before the barrier, not lost. The correction waits for actual fabricPrepares=3 before raising those sources. The original expected accepted=4/replied=3 assertion and production RTL remain unchanged. Both FAIL receipts, logs and exact hash-matched old TB bytes are retained here.

An additional review and executable counterexample found the intermediate adapter masked cleanupFault with boundary busy. Actual r10 can clear busy and set its sticky fault on the same retirement edge. The old component reproduction reports success=1/Fatal=0; the one-line correction propagates fault throughout the retained adapter lease. Final component cases cover ordinary normal retirement, exact simultaneous retirement/fault, and the same fault with lock/open backpressure. The failed old receipt/log and exact old adapter source are retained; intermediate commit 6074063 is not the final qualified candidate.

## Final real-module result

The v3 source-bound real I1/Home/private-cache/APLIC/IMSIC test passes CPU/fabric/AON half-periods 5/7/11 and 11/5/7 ns, with phases 0/2/3 ns. Each positive reaches three actual 4096-AON-cycle timeouts, holds a real dirty ReleaseAck through the 16384-cycle cleanup watchdog, retains the queued second controller, requires actual CPU resume edges, and completes three terminal/fabric/controller retirement handshakes. Controller completion counts are exactly 2 and 1, and every outcome is failed/canceled rather than a claimed rate change.

Each ratio delivers six accepted MSI requests and six replies, IDs11/12/13 exactly twice each, with pending bitmap0x3800. The first ratio checks22 store/load/previous-store loops and the reverse20. After the fixed stimulus boundary, blocked MSI remains exactly four accepted/three replied until its real response is released. Wrong-data, wrong-previous-store and wrong-IRQ runs fail at their independent monitors. All current source, emitted RTL, guest and tool inventories were rechecked before archiving.

The current production default remains byte-identical across248 SV files. These are digital protocol and architectural guest checks, not a full Linux, actual runtime frequency-switch, physical timing or board signoff. Upload of this stage remains pending separate authorization resolution; local commit availability must not be described as remote publication.
