# R36 fixed-MAC TX admission setup cut

## Measured family

`fabric_target250-setup30.rpt` reports -2.533 ns from
fixedMacSequence.serial[1] to crossing.txData storage WE: 25 levels,
6.132 ns data (logic 2.218, route 3.914), skew -0.087 ns.

The actual chain runs through serial/observation fault validation, network pause
and held qualification, fabric producer-drain aggregation, atomic PARK command
READY and VALID, then speculative TX admission closure. This is separate from
the line-writer READY path addressed by the A-beat queue.

## Exact local change

FixedMacBoundary's closingTx uses only the accepted current.txStop, matching the
existing accepted-command CSR closure approach. It no longer ORs in an unaccepted
command.valid && command.bits.txStop. Nothing in serial validation, immediate
fault handling, producer closure, FIFO-empty proof or command acceptance changes.

The existing txFence requires txProducersClosed AND both source TX VALIDs absent
AND fabricTxStorageIdle before accepting a stop command. Therefore an accepted
stop cannot coincide with either TX beat acceptance. From the next fabric edge,
current.txStop closes both inputs. Prior to acceptance, the caller contract and
existing assertion already require completed producers and no offered TX beat.
A PARK that is cancelled before acceptance cannot manufacture a held stop.
During release, current.txStop stays asserted until the release is accepted,
exactly as before. Both data/control streams use the same accepted state.

This is not retiming a live fault or sampled drain flag. It removes redundant
speculative gating under the existing producer contract. No new registers,
packet latency, capacity, byte format, burst timing or stream throughput changes.
The direct boundary and adapter assertions retain illegal-producer detection.

## Verification

Fresh CommonFixedMacAdapterMain emission and existing native asynchronous adapter
matrix cover three fabric/fixed-clock ratios, stop/drain/release receipts, packet
stream bytes, unsent PARK cancellation, retained CSR response ownership, stale
observations/serials, terminal/final snapshot backpressure and fail-closed faults.
Results are recorded with source/RTL hashes after the shared compile. This
component fixture models MAC endpoints and producer-closed witnesses; it is not
full CPU/DMA/Home integration, hardware timing or board qualification.

Executed 2026-10-23: shared compile PASS; fresh RTL emission 8.20 seconds;
complete adapter matrix PASS in 8.92 seconds including emission. Ten cases:
fabric50/fabric250/fabric71, four deliberate oracle failures, three fail-closed
fault cases. Source, RTL and tool hashes remained unchanged.
Receipts: `build/r37-fixed-mac-tx-cut/emission.json` and
`build/r37-fixed-mac-tx-cut/matrix/receipt.json`.
No physical or board result is implied.
