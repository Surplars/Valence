# r21 standalone fixed-source MAC boundary

This is a default-unselected, reusable real MAC composition and transport stage.
It does not replace CommonMachinePlatform/ManagedPeripheralBank, allocate a
runtime epoch, manufacture CPU/DMA/Home ownership, or connect a clock controller.
CPU/fabric independent 5 MHz-grid and hardware-default-50 goals remain unchanged;
CPU300/fabric250 implementation constraints are not relaxed.

## Actual source boundary

FixedSourceManagedGmac keeps CSR/frontend, EthernetDmaFrameAdapter, PHY manager,
MDIO/arbiter, media transition, watchdog, configuration, statistics and lifecycle
together on the MAC's existing continuous raw125 leaf. Its actual source metadata
is 125,000,000 Hz. raw125 remains an independently available input, not fabric,
managed TX/RX, forwarded TXC or recovered RXC. No MMCM, DRP, software divider
recalculation or new reset epoch is introduced.

TriSpeedManagedGmac gains only a default-false exportContinuousClock parameter and
optional output. With balancing disabled the existing leaf is rawTxClock; with
balancing enabled the one existing CE=1 ContinuousClockBuffer remains parallel
to the two existing managed clock buffers. The wrapper uses its output directly
for MAC source and outer fixed endpoints; it never feeds a buffered leaf back
into rawTxClock. Both production topology variants emit successfully. This is
an emitted-RTL connectivity check, not implementation, routing or clock timing.
The existing rawClockHandoff + balancedRawClock prohibition remains unchanged.

The boundary reuses one RegisterClockDomainBridge, four unmodified
CdcDataFifo(37,16) instances and three unmodified CdcMailbox instances. Complete
AXIS data/keep/last words cross together, independently for TX data/control and
RX data/status. A registered persistent IRQ level crosses to fabric. No short
external-IRQ capture guarantee is added. Physical media outputs remain fixed/raw
clock-domain signals, not fabric-synchronized software observations.

## Owner and command contract

- Commands carry caller epoch, strictly increasing 16-bit serial until common
  cold reset, and complete RX-stop/TX-stop/park votes. This is an ordered transport,
  not the existing whole-system epoch/terminal state machine.
- Begin RX stop may be sent before CPU prepare. Before offering TX stop, the
  caller must close and complete real upstream TX producers and leave no
  unaccepted TX stream offer. The fixture drives this witness itself; it is
  not actual DMA idle evidence.
- TX command launch additionally waits both outer FIFO sourceIdle predicates.
  Hence every old accepted RAM word has already reached a fixed output before
  the command crosses. Applying TX stop separately waits BOTH fixed destination
  predicates, including synchronous-read/prefetch/output owners. Neither endpoint
  empty alone nor a fixed wait count proves this cross-lane ordering.
- Park requires both stop votes, the caller's actual matching fabric-held/control
  producer proof, no old unaccepted CSR offer, and RegisterClockDomainBridge
  sourceIdle. sourceIdle requires final fabric response consumption; fixed
  destinationIdle after enqueue is insufficient. Fixed park application then
  waits actual MAC admission drain, TX consumers and destination CSR ownership.
- Applied stop/park votes latch until actual fixed consumption of a command
  clearing them. New post-release data may cross faster than the independent
  release command; a falling live-idle predicate must never withdraw an OLD vote.
- Each consumed-command receipt is generated on actual fixed command consumption
  and echoes the entire command. Its fabric consumption frees the outstanding
  command owner. It does NOT mean park succeeded, MAC release finished, AON
  consumed a terminal, or the epoch retired.
- A separate coherent mailbox continually reports true AND false observations
  with full epoch/serial. Callers must consume stale observations but only use
  matching ones. RX fixed drain includes both outer source stores, not fabric
  destinations; the wrapper exports fabricRxConsumersIdle for the necessary join
  with real DMA memory/reply owners. fabricCsrIdle and fabricTxStorageIdle are
  likewise fabric-local outputs. No combinational cross-domain idle join exists.
- Release commands require no new data drain. Actual MAC admission/control
  release is reported in matching observations. Complete AON terminal consumption,
  cancellation/retirement and observation-tail retirement remain the existing
  integration work, not a fabricated ACK inside this wrapper.

Serial wrap, unilateral reset, raw125 loss recovery and separate fabric-only
reset are unsupported. Common cold reset clears all transport owners together;
physical ingress/media epoch reset never resets these added bridges.

## Verification scopes

The standalone boundary test exercises actual CDC primitives with explicitly
modeled MAC-local control predicates. It checks all four independent payload,
keep and last streams, held-output stability, TX destination owners after source
RAM credit returns, exact receipt ownership/backpressure, applied-vote retention,
persistent IRQ with paused fabric, and coordinated common reset with fixed clock
paused. Reset explicitly discards 17 accepted outstanding words in each channel;
64 new-generation words/channel then reject any stale data. It does not promise
lossless delivery across reset, nor emulate a physical clock-gate primitive.

The separate real MAC test uses the complete production MAC with hardwareClocks
false and independent continuous fixed125, fabric, and recovered-RX digital
clocks. Only PHY policy startup/poll waits are shortened to 256/512 cycles. The
MDIO divider, all operations/page restoration, media timeout and RX watchdog use
125 MHz metadata. The external PHY is the existing independent pin-level register
responder, not a physical RTL8211F. Producer-closed witnesses come from the fixture,
not CPU, DMA, Home, DDR, AON or a final platform integration.

Each positive real-MAC case checks 51 real initialization MDIO transactions,
seven fabric and MAC CSR accept/reply pairs, 32 TX payload words and 12 TX control
words, 32 RX payload words and 12 RX status words, exactly three consumed command
receipts, retained MAC address/statistics, and two complete TX/RX frames. Each TX
wire frame has 7 preamble bytes + SFD + 64 payload bytes + 4 independently checked
FCS bytes, 76 bytes total. One complete raw frame arriving while admission is
closed is intentionally dropped and counted; already admitted outer transport
words are never silently dropped.

Native matrices use fabric 50 MHz, 250 MHz, and an unrelated approximately
71.428571 MHz test clock, with fixed source exactly 125 MHz and RXC 125 MHz.
The unrelated ratio is digital CDC stress, not a newly authorized 5 MHz-grid
runtime rate. No whitelist is populated. Four observation-side ordinary-oracle
negatives accompany each matrix, without a direct-fatal fault-injection shortcut.

## Measured transport bandwidth, not Ethernet line-rate

The four FIFO channels run concurrently; each measured window spans 1,920 actual
accepted output words after warmup. At fabric50 the TX channels each deliver
200 MB/s and RX channels each deliver 100 MB/s; at fabric250 they deliver
250 MB/s TX and 500 MB/s RX; at the unrelated ratio they deliver 250 MB/s TX and
about 142.857143 MB/s RX. These are continuous FIFO-only payload-byte rates.

The RX outer FIFO still ends at fabric. Its unmodified synchronous-read II=2
therefore caps fabric50 RX at 100 MB/s, below the 125 MB/s 1 Gb/s byte rate. Moving
MAC source to fixed125 fixes its internal timebase but does NOT remove this new
low-fabric transport ceiling. A separately verified pipelined FIFO/adapter stage
or explicit rate/backpressure/drop policy is still required; HeldResponseCdcDataFifo
is not silently substituted. Two real short frames are not sustained line-rate,
full-duplex congestion, legal-IFG stress, maximum-size or all speed-mode evidence.

## Preserved intermediate failures

The first default-export invocation omitted its required compile receipt. It
failed before emitting RTL; no equivalence failure or PASS is inferred from it.
A subsequent compile-bound export performs the actual 248-module comparison.

The first expanded real-MAC matrix passed fabric50 but hit a configuration CSR
error at fabric250. Its fixture had issued the next configuration write without
waiting for the preceding fixed-domain configuration image to be consumed. The
corrected fixture waits the actual configDrained predicate before its next write;
no DUT, bus response, timeout or error oracle is relaxed. Original source,
receipt and failure log are preserved in initial-failures/real-matrix-r1.

A read-only pre-native review also found that combinational idle-qualified votes
could be withdrawn if post-release data outran the release mailbox. The tested
implementation latches applied votes; a modeled local-idle revocation check
exercises retention. No native PASS is attributed to the pre-review draft.

## Remaining integration and qualification

No full-system ACK, real gate feedback, DRP/backend, runtime whitelist, physical
CDC/RDC/STA, board behavior or full AON-terminal retirement is supplied. Actual
upstream CPU/DMA proofs, early/late cancellation under the real platform, stopped
fabric transient IRQ capture and UART's remaining fabric-dependent control tail
are still separate obligations. The wrapper is not selected by production and is
not a board-ready replacement for ManagedPeripheralBank.

Final evidence and exact local commit/bundle hashes are recorded separately after
all native cases and independent rehash finish. Remote upload remains blocked;
no GitHub write, git push, alternate destination or encoding bypass was attempted.

## Final scoped result

Both final matrices PASS: three positives and four ordinary observation-corruption
negatives each. Real-MAC positive wall times are 46.581, 54.214 and 45.565 seconds
for fabric50, fabric250 and the unrelated ratio. Native boundary positives take
0.345, 0.305 and 0.305 seconds. All exits are observed through wait4; no matrix case
timed out or was interrupted. The bounded runner's interrupted-process cleanup
is not separately qualified by this stage.

The final boundary matrix strengthens the earlier version with complete 52-bit
observation backpressure stability, exact accepted-command echo, a same-serial
true-to-false snapshot, early release before TX stop can apply with old destination
outputs retained, and an explicit old-vote guard through actual fixed consumption
of a release that admits new data. These are modeled-MAC boundary tests, not real
platform cancellation/terminal proofs. The real-MAC test uses successful park
then release and waits release before its second packet; it does not establish
integrated early cancellation or post-release owner retirement.

The initial boundary-r1 varied keep and counted full-width word capacity. Its
100 MB/s report therefore meant a 25 Mword/s full-width-equivalent bound, not
that stimulus's keep-counted byte rate. It is retained unchanged in
initial-boundary-r1. The final boundary-r2 measurement instead uses all-valid
keep in the 1,920-word window and independently counts 7,680 valid bytes; the
100 MB/s fabric50 RX figure is now measured valid FIFO payload throughput.
Variable keep/last remains checked on tail and new-reset-generation words.

Independent verification rehashes 958 source inputs and seven native tool-chain
files for each matrix, emitted RTL, compiled VVP and all case logs. It checks both
production clock topologies, four FIFO and three mailbox instances, the real
MDC half-period divider of 50 fixed cycles, and the complete default-OFF inventory.
Actual default production emission remains 248/248 SystemVerilog files byte
identical, without normalization. Native preprocessing separately confirms 21
real-MAC and four standalone-boundary inline fatal assertion sites are enabled.
The first static topology checker assumed unsuffixed CdcDataFifo; the final check
recognizes the actual legal specialized CdcDataFifo_3 module names and still
requires exactly four instances.

- Real matrix receipt SHA256: 9d396e891c11eb2321fe75086011286266a538de424fb6900521f2a5e305412c
- Boundary matrix receipt SHA256: 513d5f49057d193cf60a92b6849854c0a19a850679b968440bbebd6dd3d6f46b
- Final aggregate: aggregate-verification-r1.json
- Exact current sources and original base: source-binding.json

Reproduce emission from the repository root with the archived emission.py
helper and a fresh name, for example `python3 recovery/cmu-frequency-r21-fixed-mac/emission.py fresh-test test`.
It invokes the actual `ip.FixedSourceManagedGmacMain` and binds all production,
test, resource and build sources before and after emission. Modes are test,
production, balanced and boundary. Source scripts/cloud/env.sh first. Existing
Icarus/VVP executables are required; no simulator installation or fallback runs.

Run test_fixed_source_mac.py or test_fixed_mac_boundary.py with fresh output,
the corresponding RTL directory, --emission-receipt, --iverilog and --vvp.
Omitting --single runs the full named three-ratio/four-negative matrix. The
independent verifier is simulator/cdc/verify_fixed_mac.py; its documented
--out-root, --real, --boundary and fresh --output arguments rehash the retained
workspace evidence without rerunning or editing it. No generated RTL, simulator
binary or waveform is committed.
