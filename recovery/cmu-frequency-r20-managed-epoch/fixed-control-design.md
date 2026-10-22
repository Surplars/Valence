# Next fixed-control design, read-only proposal

No implementation, throughput experiment or physical qualification is claimed by this document. The r20 control park still runs on fabric/sourceClock. Its correctness while clocks run does not fix frequency-dependent timing.

## Actual timing and owner boundary

ManagedPeripheralBank passes sourceClock and busHz to TriSpeedManagedGmac, not a separate fixed control clock. PHY policy, MdioClause22 plus ManagedMdioArbiter, EthernetMediaTransition, RX-clock watchdog monitor, CSR/frontend, configuration launch, statistics consumption and lifecycle wake/drain all live on sourceClock. Production configured timing includes MDC 1.25 MHz, PHY startup 50 ms/poll 100 ms, media timeout 500 ms and RX-clock absence timeout 1 ms. Changing frequency metadata alone is not a solution.

The source domain also contains EthernetDmaFrameAdapter and the CPU-facing ends of the frame FIFOs. Merely rebinding sourceClock to AON without complete transports would make direct fabric stream and CSR connections unsafe.

## Candidate A: whole MAC source domain on existing continuous raw125

Move CSR/frontend, adapter, PHY/MDIO, media/watchdog, configuration, statistics and lifecycle together. Preserve their existing same-clock atomic busy/configuration and event-versus-clear rules. Add at the external island boundary:

- One complete RegisterPort request/reply CDC.
- Four complete data/keep/last stream CDCs, TX data/control and RX data/status (37 bits per stream).
- Persistent IRQ synchronization.
- Epoch-tagged stop/park commands, true/false held observations and consumed release/terminal receipts.

Four depth16 stream stores represent 2368 payload bits, not a mapped area estimate. FIFO output/prefetch owners, reset state and pointers are additional. Whole-island CDC count alone does not establish that this approach costs more than splitting several internal control protocols.

The existing continuous raw TX125 is an architectural candidate, not managed txClock, forwarded PHY TXC or recovered RXC. TriSpeedManagedGmac requires continuous125 and distinguishes its raw leaf from packet-engine gated leaves. soc_top_common_ddr.sv supplies rawTxClock through the independent Ethernet clock block. native_gmac_divided_clock.sv uses a divide-by-four raw leaf with CE=1; cold reset/PLL lock, not CPU/fabric runtime commands, govern its availability. Reuse requires checking the actual raw/parallel-buffer topology, especially balancedRawClock, without adding a cascaded clock buffer. No new MMCM or DRP is proposed. Fixed-clock loss still requires the existing coordinated cold-reset contract.

### Why AON50 is not a safe line-rate assumption

CdcDataChannels.scala readEnable requires !pending; pending is assigned readEnable, and the following pending cycle captures output and advances readGray. Consequently consecutive read starts are impossible. Ideal sustained dequeue is at most one word per two destination edges.

For the existing 32-bit MAC stream path, 50 MHz therefore gives at most 25 Mword/s or 100 MB/s, below the 31.25 Mword/s ceiling required for 1 Gb/s. The existing RX frame FIFO already ends in the source domain, so migrating the whole MAC to AON50 meets this obstruction even before adding outer transport FIFOs. At125 the corresponding capacity bound is 62.5 Mword/s. That removes this one ceiling but is NOT measured line-rate evidence: two FIFO layers, status/control tails, short frames, burst occupancy, backpressure and simultaneous RX/TX still require independent accounting and throughput tests.

## New transport owners change stop order

The current network sequencer closes TX after dmaTxIdle. With outer FIFOs, that alone is unsafe: DMA can finish a stream handshake while an old first control word or payload remains queued.

1. Pause new DMA packet launches while completing accepted producers.
2. Drain all accepted TX data/control through BOTH outer FIFO destination outputs/prefetch into the MAC.
3. Only then close MAC TX admission.
4. Wait actual adapter/frame-FIFO/transmitter/encoder tails.

Source-side empty alone is insufficient: read credit is released when data reaches the destination output register, before its consumer accepts it. RX qualification must join both outer data/status FIFO owners with real DMA memory/reply owners. Data/status can arrive in either relative order; payload/keep/last must remain inseparable.

## Candidate B: split fixed control island

Keep fabric CSR and adapter local; move PHY/MDIO, media FSM and watchdog to a fixed clock. This avoids full packet CDCs but requires complete software-MDIO command/reply transport, lossless restart requests, coherent link/speed/fault/counter snapshots, epoch-tagged media close/drain/reopen transactions, ingress/raw-drain status and a wake path independent of fabric edges.

Moving CSR alone while retaining a fabric adapter is not a shortcut: synchronized busy can be stale as a frame starts. Configuration acceptance requires a real reservation/admission handshake, not two-flop busy sampling. Whole-MAC migration preserves that rule locally; split-control must redesign and verify it.

A standalone fixed PHY+MDIO island is a small independently testable timing phase, but must explicitly leave media timeout, RX watchdog, wake and full DFS unresolved. If whole-MAC fixed125 is selected, testing its complete transport island directly may avoid a throwaway intermediate split-PHY refactor.

## Verification and compatibility prerequisites

- Preserve every accepted request/reply and irrevocable offered payload through park, cancellation and reset.
- Never equate reply enqueue or destinationIdle with source consumption.
- Start qualification only after real matching fabric held/all-obligations-idle.
- Cross coherent epoch-tagged true AND false status; stale idle cannot grant a new epoch.
- Early cancel requires no successful park, but does require actual release/terminal receipts.
- Do not re-drain unrelated new traffic after resume; do not treat initially high released as a sent command's acknowledgement.
- The r20 same-clock registered-low receipt must be replaced by a real cross-domain consumption handshake, not reused as fixed-cycle delay.
- Only common cold reset can clear the new owner-retaining bridges; physical ingress epoch reset must not reset them.
- Keep a default-off elaboration branch with unchanged existing ports, constructors and parameter path; compare emitted OFF RTL to immutable references.
- Explicitly bind the fixed source's actual configured frequency. No software rate recalculation or live divider rewrite is proposed.
- Keep real gate feedback/DRP and platform integration separate from standalone transport validation.

ManagedUart also retains a fabric-clock admission timeout/raw-wake merge even though its baud engine is fixed raw50. Fixing GMAC alone does not qualify every peripheral. External short IRQ capture during stopped fabric clocks remains another independent requirement.

## Source anchors

- src/main/scala/ip/clock/ManagedPeripheralBank.scala: busHz/source construction and bank clock wiring.
- src/main/scala/ip/ethernet/TriSpeedManagedGmac.scala: source-domain owners, continuous raw leaf, packet gated leaves, controlPark.
- src/main/scala/ip/ethernet/Rtl8211fPhyManager.scala and EthernetMediaTransition.scala: fixed-time assumptions and policy ownership.
- src/main/scala/ip/bus/CdcDataChannels.scala: readEnable/pending/output ownership law.
- src/main/scala/ip/ethernet/EthernetDmaFrameAdapter.scala and ip/dma/EthernetPacketDma.scala: four stream ownership and completion rules.
- src/main/scala/platform/CommonNetworkRuntimeSequencer.scala: current TX stop order.
- fpga/common/soc_top_common_ddr.sv and fpga/zu15eg/native_gmac_divided_clock.sv: existing fixed raw125 source/reset contract.
