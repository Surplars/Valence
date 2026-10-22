# R10 three-clock runtime epoch boundary

This isolated candidate adds an AON transaction owner around the r8/r9 real drain endpoints. It is not instantiated by any production profile. CPU and fabric clocks remain running; no gate, DRP, rate table entry or backend-present signal is enabled. Legacy ClockRateControl's DrainTimeout path is deliberately unchanged and disconnected from this candidate. A real counter in the new AON boundary makes and retains timeout/cancel decisions; injected cancels alone are not its timing evidence.

Two AON-native request lanes represent future CPU/fabric rate requesters but share one serialized tile/Home epoch owner. Their 32-bit opaque request tokens are not frequencies or qualifications. Resume and cancel echo both that token and the allocated maintenance epoch; stale decisions cannot match a newer epoch merely because a requester reused its token. Internal maintenance epochs are not reused before common cold reset in this first prototype; exhaustion prevents further acceptance, rather than silently wrapping ambiguous tags. This is an explicit bounded prototype limitation, not a production runtime manager.

Prepare, cancel, resume and observations cross unrelated clocks through held message channels. Matching CPU and fabric observations include actual local held state, local link/transport emptiness, synchronized remote emptiness, and real fabric owner/Home/MSI idle. An observation is not instantaneous and can be revoked by newer actual traffic. It is not physical gate-close permission or complete peripheral admission proof. Timeout has priority over a simultaneous qualified observation and becomes a sticky cancel decision; a late observation cannot restart a closing/programming path.

Terminal handling distinguishes mailbox capture from endpoint consumption. The fabric's runtimeComplete is copied without ready; its actual handshake is delayed until the selected AON consumer accepts that terminal and the acknowledgement returns. A separate fabric-retirement receipt keeps the AON owner allocated until fabric has actually released the external epoch. Thus terminal backpressure continues to close MSI admission, and a new request cannot overlap the old fabric owner merely because a CDC queue accepted a result.

The drain watchdog covers admission through the first qualified observation. If a later false snapshot revokes that observation, held deasserts; the initial watchdog is not restarted. The caller must await fresh proof or explicitly cancel. This is a separate liveness limitation, not a latched permission to close a gate.

A cleanup watchdog reports a stuck cleanup but never clears ownership, fabric isolation, or manufactures terminal success. Old clocks must continue. Permanent missing responses or a CPU clock that never resumes require repaired progress or a supported common cold reset covering every transaction owner. Warm or unilateral endpoint reset is not supported.

## Required later work before real clock switching

- Explicit legacy ClockRateControl abort/cleanup integration, with the same winning decision and end-consumption ownership.
- Real gate primitive close/open and managed-clock edge witnesses. Clock enable or its inverse is not gate confirmation.
- Fixed/AON/source-domain capture or a source-held-until-acknowledged contract for every IRQ source. A synchronizer solely in a stopped fabric cannot capture arbitrary short pulses.
- Real IRQ trap/claim/mret and AMO/LR/SC combination tests across the maintenance boundary, plus all network/JTAG/new peripheral admission owners and fixed DDR/timebase contracts.
- Generated official MMCM configuration, physical CDC constraints and independent native/Vivado/board qualification. The 300/250 MHz performance constraints and hardware-default 50 MHz goal remain unchanged; BootROM-to-Linux still does not depend on U-Boot.

## Verified component and compatibility scope

Scala compilation and fresh native RTL emission passed. The independent endpoint-model component suite passes 34 positive cases across four clock ratios and two deliberately wrong ledger/receipt controls. It includes 255 allocated epochs and refusal to wrap in each ratio, reset recovery, 152 AON edges of terminal consumer backpressure beyond the 128-edge cleanup watchdog without a false endpoint fault, and actual end-consumption/retirement ordering.

The proof/deadline collision is actually witnessed at AON age 64 in the fabric-fast and AON-fast phase configurations; cancellation wins and the eventual terminal reports canceled plus timedOut. The other two source/mailbox cadences skip that exact age and are not falsely counted as same-edge witnesses. False proof after initial qualification revokes held, rejects matching normal resume for 216 AON edges without a fake completion, and finishes only after explicit matching cancel.

These 34 cases use independent CPU/fabric endpoint models, not a substitute for the real I1/Home test. Their receipt preserves source, original RTL, emission and executable hashes and checks drift. A fresh default-off production performance export remains 248/248 SV files byte-identical to r9.

## Verified real I1 three-clock scope

The fresh real full-I1/Home/private-cache/APLIC/IMSIC suite passes both CPU/fabric/AON half-period sets 5/7/11 and 11/5/7 ns with phases 0/2/3 ns. Each positive completes six terminals (two normal, one explicit cancellation, three actual 4096-AON-cycle timeouts), plus one coordinated-reset-aborted owner. Independent wrong-load-data, wrong-previous-store and wrong-IMSIC-pending controls all fail at their intended monitors.

Real ReleaseAck, MSI response and fabric-completion stalls exercise actual AON timeout decisions. A queued CPU completion cannot count as CPU held; paused CPU edges prevent resumed acknowledgement. Terminal backpressure retains fabric ownership and MSI admission, and stale epoch decisions cannot match reused request tokens. Native simulation is digital protocol evidence, not analog CDC or physical gate qualification. The guest checks IMSIC pending with global interrupts disabled; it does not validate IRQ trap delivery or AMO/LR/SC sequences.

The first native run remains archived as diagnostic-r1-fail-receipt.json and diagnostic-r1-fail.log. It failed the unchanged boot-enable assertion at a testbench simultaneous reset/enable transition, after earlier epochs passed. Only TB reset sequencing changed; original emitted RTL stayed identical. The exact old TB bytes were reconstructed and verified against the original receipt hash, retained as diagnostic-r1-tb.source.sv. The final passing receipt is i1-receipt.json; the failed result is not replaced.

## Reproduction

Source scripts/cloud/env.sh. Compile with mill --no-server IonSoC.test.compile. Emit platform.CommonRuntimeEpochBoundaryMain with output directory, drain cycles 64 and cleanup cycles 128; emit platform.CommonI1RuntimeCdcNativeMain to a separate directory. Emission receipts must bind current sources and exact generated RTL; both runners require those receipts. Exact native commands, clock parameters, executable hashes and source inventories are retained in component-receipt.json and i1-receipt.json. Generated vendor IP and simulator executables are not published here.
