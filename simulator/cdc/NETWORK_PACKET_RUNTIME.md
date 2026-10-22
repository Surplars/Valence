# Native real network packet/runtime admission fixture

`CommonNetworkPacketRuntimeFixture` composes the production
`CommonNetworkRuntimeSequencer`, `EthernetPacketDma`, `EthernetTxDescriptorQueue`,
`GmiiFrameRx`, `EthernetRxAdmissionStop`, two `EthernetFrameClockBridge` instances,
`EthernetDmaFrameAdapter(true)`, and `GmiiFrameTx`.

The fabric, RX, and TX clocks are independent. The TX-local idle predicate is
registered before its production `CdcLevel` crossing. RX admission uses the
existing mailbox barrier and actual RX-owned payload, source/destination FIFO,
and adapter/status ownership. No frame-owner surrogate replaces these modules.

## Deliberately bounded scope

The memory endpoint is an explicit ordered `RegisterPort` model with accepted
request/response bookkeeping and independently checked payload writes. It is
**not** CommonMachineFabric, I1, Home, external DDR, or a cache-coherence proof.
The prepare consumer, AON-terminal-consumed indication, and final-retirement
receipt are explicit test endpoints. They test production network-sequencer
ordering, not actual AON delivery, CPU resume/cancellation, or full-system ACK.

There is no RGMII encoder/PHY, full managed-MAC register plane, media transition,
software MAC stop vote, interrupt, fault-injection, physical CDC, clock gate,
DRP, board, or unilateral-reset qualification. Coordinated cold reset is tested
as explicit abandonment of all affected owners, not lossless packet delivery.

## Independent checks

Four clock ratios and phases each run four cases:

1. An actual CRC-valid RX frame spans admission closure. Its sixth PG138 status
   word is held after five accepted status words and the actual last data beat.
   Accepted memory writes remain owned while their ordered replies are delayed.
   Exact per-byte data, addresses, masks, single-write identity, six status words,
   completion lengths, and request/reply ledgers are checked. Closed frames are
   counted by reason, including drain while a closed physical frame is still
   arriving. A resumed valid frame and a corrupted-FCS frame distinguish accepted
   payload from admission and CRC drops.
2. A TX memory request already exposed under backpressure remains stable when
   pause arrives. Four accepted prefetch reads retain owners until replies return.
   The actual sixth control word and final data beat are separately held. DMA idle
   cannot replace real wire/FCS/IFG drain. A legacy TX started while paused remains
   parked and resumes without reprogramming. Every wire byte, preamble/SFD, length,
   and FCS is independently checked.
3. Posted TX pending/completed descriptors and posted RX pending/empty-armed
   descriptors survive pause. No fresh TX read or RX memory write occurs during
   the held pause. After release, three RX and two TX descriptors complete in FIFO
   order with original addresses and lengths. Completion POPs release each owner
   exactly once. Empty TX queue enable/disable MMIO works while paused.
4. Coordinated reset interrupts an active epoch with four accepted, unreplied TX
   reads. The discarded ledger is printed explicitly. Fresh post-reset DMA work
   and epoch retirement pass with no old packet escaping.

Each case uses the production network sequencer. Downstream prepare and modeled
terminal-consumption are backpressured separately. Admission remains closed
until the terminal receipt; retirement waits for the actual RX stop-release
mailbox to settle. A new prepare cannot overtake an owned terminal, and duplicate
or stale epochs are rejected after retirement.

Three negative controls corrupt only an independent oracle: one expected TX byte,
one expected RX write byte, or the expected retained-status ownership. Each must
fail at its intended checker, without modifying production RTL.

## Running

Source `scripts/cloud/env.sh` in every shell. Coordinate the sole Mill slot with
the integration owner. Emit fresh native RTL with
`IonSoC.test.runMain platform.CommonNetworkPacketRuntimeNativeMain OUT` using the
central emission wrapper, which must produce a `PASS_EMIT_ONLY` receipt binding
all production Scala plus the fixture to the emitted RTL inventory.

Then run:

```
python3 simulator/cdc/test_network_packet_runtime.py RTL_DIR FRESH_OUTPUT_DIR \
  --emission-receipt EMISSION_RECEIPT.json \
  --iverilog /path/to/existing/iverilog --vvp /path/to/existing/vvp
```

The runner invokes no Mill, installation, RTL rewrite, Verilator, or Vivado.
Production assertions are enabled and checked after preprocessing. It preserves
source/RTL/tool hashes, input snapshots, resource/disk-floor measurements, all
commands, per-case ledgers, and failed as well as successful receipts.

The first r16 execution passed 16 positive runs and 3 intended negative failures
in `out/cmu-frequency-r16/native-r1/receipt.json`. Per clock ratio, the RX case
recorded 2 accepted frames, 4 admission-closed drops, 1 bad-FCS drop, 12 status
words, and 17 exact writes; posted ownership recorded 3 RX frames/25 writes and
2 TX frames. These are scoped native component/composition results only.
