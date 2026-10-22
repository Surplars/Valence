# Runtime qualification audit after r17

Source reviewed: a49a1f254343a17752072d5931125eba2f0fccfb. Read-only source/receipt review, not an additional simulation or physical result. The subsequent historical-monitor correction changes no production RTL.

## Four request-scoped classes are not yet production ACKs

ClockRateControl.scala:54-67 describes private-owner, transport, fabric and AXI drain classes, consumed as a conjunction. There is no production bit-to-owner assignment. CommonMachinePlatform.scala:242-253 correctly keeps endpoints absent, drainAcks zero, gate/lock/resumed false and programming refused. ClockRateManagement.scala:33 still instantiates the default controller, not the separately verified externalDrainLease composition.

- Private: CommonI1CpuTile.scala:131-198 accounts for architectural stop, cache flush/quiescence and native adapters; release observes actual local edges. Real I1/cache/Home scoped evidence exists. A1 remains unsupported. This is not a physical gate witness.
- CPU transport: CommonCpuClockBoundary.scala:45-124 covers actual coherent/scalar/MSI/maintenance channels, source offers and local storage, with epoch-tagged observation in CommonRuntimeEpochBoundary.scala:129-142,217-240. Periodic time snapshots are intentionally retained, not permanently empty. Fixed-DDR, timer and managed-control qualifications are not included merely because CPU transport is empty.
- Fabric: CommonMachineFabric.scala:18-63,328-387,463-506 and CommonFabricScalarArbiter.scala:32-80 account accepted scalar/MMIO, AMO/reservation, coherence through E/ReleaseAck/probe data, ROM/RAM/fetch, DMA and MSI owners. Network and debug sequencing now join actual retirement. Retained software descriptors are not accepted memory owners; packet runtimeOwnersIdle deliberately does not include control-MMIO responses.
- AXI: CommonMachineFabric.scala:425-449 has real AR-to-last-R and AW-to-B ledgers/channel checks. Axi4ClockDomainBoundary.scala exposes both-domain FIFO empty observations, but CommonMachinePlatform.scala:138-145 does not consume them in runtime qualification. R17 uses a real bridge with a modeled RAM endpoint, not DDR UI CDC/MIG. Earlier independent-channel conservation does not prove combined runtime drain.

## Smallest remaining real composition

Use the actual ManagedPeripheralBank/TriSpeedManagedGmac control paths with clocks running, not another packet-only MAC assembly. Platform sourceClock is fabricClock (CommonMachinePlatform.scala:228-241). TriSpeedManagedGmac.scala:383-390 intentionally reports only packet RX-stop and TX payload/wire tail for runtime admission. This does not prove all management transport safe.

Classify and test each owner as either drain-before-stop or safely retained across stop:

- raw RX decoder/packer, pending EOF, physical FIFO and unpack handoff;
- configuration dirty/sent snapshots and their receipt mailboxes;
- TX/RX statistics, diagnostics and raw diagnostics snapshots/consumption;
- media-rate/PHY polling/page transactions;
- MDIO active operation, policy arbitration, held/denied reply;
- MAC register frontend and CSR replies; UART bridge/reply/ingress/wake.

Do not require continuously arriving raw diagnostics to become permanently empty. CdcCounterBank (ManagedPeripheralSupport.scala:101-141) retains modulo-32 totals and snapshots, with fewer than 2^32 increments per field between consumed snapshots. That contract needs real composition tests. Raw traffic may be explicitly dropped before admission and counted; accepted packets cannot be silently discarded.

Next bounded candidate should prove old config/MDIO responses, runtime versus software stop independence, retained counters under raw traffic, real MAC/DMA CSR final state, second packet after release, and terminal backpressure. Any new observational/park hooks remain default-off. No four-bit ACK or backend connection is justified by this one slice.

## Separate hard prerequisites

- FixedTimebaseBoundary.scala:18-41 has complete MMIO CDC and continuously offered coherent snapshots. Accepted scalar MMIO ownership exists, but no runtime boundary qualification output is exported; snapshot retention requires explicit evidence.
- External sources enter fabric directly; Aplic.scala:127-144 samples only fabric edges. Already sampled MSI pending is preserved, but a pulse wholly during stopped fabric can be lost. Require a per-source held-level contract or fixed/source/AON capture with consumption acknowledgment, not a synchronizer in the stopped domain.
- FpgaClockResources.scala:30-46 ManagedClockBuffer has no real closed/open feedback. CE command, model inversion or logical epoch release is not gate feedback.
- PHY/MDIO/watchdog control runs on source/fabric clock and uses elaboration-time cpuHz constants (TriSpeedManagedGmac.scala:85-94,269,272-296; MdioClause22.scala:23-25). Live fabric DFS requires fixed control placement or qualified rate-aware timing.
- CMU response receipt is not CPU retirement. R17 does not exercise MAC CSR, DMA status reads or a second post-release packet. Existing full-system, stopped-clock and physical qualification remain absent.

Preserve hardware-default-50 goal, independent CPU300/fabric250 performance targets, empty runtime whitelist and absent gate/DRP backend. This audit grants no timing or board signoff.
