WIP: source compiled and production-lowering RTL emitted. Behavioral tests pending; no production integration or board qualification.

ClockRateControl.scala: AON rate transaction, separate rate evidence flags, source-reply receipt before quiesce, four owner/transport/fabric/AXI drain ACK contracts, closed-gate check, exact-Hz/token backend, lock/resume checks, timeout and50MHzfallback/fatal isolation. No DRP constants or production ACK ties. Default qualification table empty.

ClockRateManagement.scala: optional CPU/fabric CMU banks0x10080800/0x10080880, aligned64-bit MMIO, ordered replies, requested/target/actual frequencies, state/errors/W1C, completion and qualification metadata. A real RegisterClockDomainBridge plus separate CdcMailbox returns source.response.fire receipt to AON. Outer CPU owners must still participate in real drain; this is not CPU-retirement proof. Production CMU v1 decoder/platform remain unchanged.

Per-bank offsets00requestHz,08actualHz,10status,18errorsW1C,20target,28boot,30qualificationIndex,38pointHz,40flags,48timeout,50completed,58state,60max,68min,70step,78version/count. Status flags0busy,1actualValid,2clockEnable,3quiesce,4isolate,5locked,6gateClosed,7gateOpen,8lastSuccess,9fatal,10backendPresent.

ClockRateControlSpec.scala: config/elaboration suite and native fixture emitter with explicitly synthetic evidence flags. Tests have not run; compilation/emission passed after fixing private-helper visibility. Native behavior testbench is next. Real backend/DRP images, gates, real quiesce endpoints, AXI CDC, fixedtimebase, CMU dispatcher and timing/CDC integration remain unconnected.

Automatic approval rejected this stage's commit/push before execution. Files and hash receipt remain local; no new commit or remote publication occurred. Preserve them if moving environments. No synthesis, implementation or bitstream.
