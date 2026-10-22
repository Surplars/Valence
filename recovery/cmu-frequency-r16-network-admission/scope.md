# R16: opt-in network packet admission composition

This stage keeps every clock running. It does not connect a rate backend, open a runtime frequency whitelist, provide a full-system clock-gating ACK, or qualify FPGA timing/board operation. The default production configuration remains disabled. Hardware-default 50 MHz remains a subsequent clock-backend requirement; the independent performance target stays CPU 300 / fabric 250 MHz.

## Ordering and ownership

An offered epoch first pauses new packet-DMA TX launches and asks the existing RX admission-stop mailbox to close new frame admission. Already offered memory requests remain valid, old admitted RX frames can obtain posted buffers, and their payload/status/memory responses complete. Old TX prefetch must finish its control/data transaction before MAC TX admission closes. The production sequencer requires both real DMA owner counters and existing MAC RX/TX drain proofs before forwarding prepare through the r15 debug sequencer to the actual I1/fabric path.

The fabric retains matching network-epoch proof in both initial drain and final owner qualification. Pending descriptors and a pristine armed RX buffer can remain parked without deleting software ownership. Runtime pause is not a destructive software STOP. MMIO requests/replies remain the existing scalar/native fabric ledger's responsibility.

Only the retained terminal-consumed-at-AON receipt opens runtime admission. Existing RX-stop settled proves the release reached its destination. Both debug and network retirement permits must precede the actual fabric terminal consumption and final AON owner release. Timeout/cancel remains the prior real AON protocol: cancellation cannot discard an old network owner or bypass prepare/drain. A permanently stalled memory/frame consumer can therefore block cancellation indefinitely; this is a safety-preserving liveness limitation.

## Deliberate limits

A PHY cannot be backpressured. Newly arriving frames after admission closes are discarded by the real receiver with its existing admission-drop reason, not described as lossless delivery. Already admitted packet owners must finish. A frame already being received at the boundary is governed by the existing receiver's ownership handshake. Physical ingress capture is not disabled; background ingress, configuration and statistics are not substituted with this packet-payload proof. No physical clock may be stopped based on this stage alone.

The native component fixture uses actual GMII parser, frame CDC FIFOs, managed stream adapter, packet DMA, GMII transmitter, RX-stop mailbox and the production network sequencer across independent clocks. Its ordered RegisterPort memory responder and downstream prepare/terminal receipts are explicitly test models. It does not prove packet operation through Home/DDR, the actual AON timeout/cancel implementation, RGMII PHY calibration, statistics-tail retirement or a complete I1/network system. The opt-in full platform is separately elaborated with real Home/DMI/I1 wiring; elaboration is not dynamic proof of those combinations. Prior r15 real Home/DMI results cannot be relabeled as r16 packet integration coverage.

Default RTL equivalence and native/source-bound results are recorded separately after validation. No blocked remote receipt is uploaded by this stage.

## Validated result

Final native-r2 passed 16 positive cases (four independent fabric/RX/TX clock ratios across four scenarios) and three intended oracle-negative failures. Enabled production assertions remained active. Exact packet payload/FCS, six-word RX status tails, accepted/replied memory ledgers, pending/completed descriptor FIFO ownership, paused-empty posted-TX enable/disable, terminal backpressure, stale epochs and common-reset discard/restart were checked. Reset explicitly discarded four accepted unreplied reads rather than pretending they completed. Final receipt SHA-256: f3c5f22209ce190c4d9d2a2deeca78b58680e22b2857548dc1a80f66baefa91e.

The integration owner independently rehashed 319 sources, 24 inputs, seven tools, the compiled simulator and all case logs. Full opt-in platform emission passed with 258 SV files; packet fixture emission passed with 22. Six focused Scala tests passed (three DMA and three rate-control tests).

The strict default byte comparison was NOT a 248/248 pass: 246 modules are byte-identical. Two modules differ solely in one explicit compiler temporary-identifier bijection and listed assertion-source line-number strings. The original FAIL receipt remains preserved. verify_default.py accepts only those exact substitutions/counts, rejects identifier collision, and then requires literal equality; logic, width, constant and handshake mutations in both modules are rejected. This is narrowly reviewed structural/text comparison evidence, not formal equivalence or timing equivalence. No RTL input is rewritten by this comparison.

Read-only review identified and fixed two issues before compilation: queue launch permission must not alter physical engineIdle or empty-queue MMIO legality; and a prepare offer must remain asserted while downstream is backpressured. Optional launchAllowed and retained prepareOffered implement those fixes. Live drain proof still qualifies held independently.

All results are local only while the earlier exact-receipt upload remains blocked. There was no remote publication attempt.
