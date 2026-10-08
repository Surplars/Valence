# AXI lane payload reuse candidate

## Scope and invariants

The supplied 2026-10-08 short-accepted handoff is the functional baseline,
Git tree `8ae3db0badcfef91192cf159df871eb89cfb9d33` on commit
`6c8977f684830137fae088d4679f9d84e5ce4a11`. This candidate changes only the
burst engine's private payload storage and the outstanding wrapper's AW
selection. It does not increase LSU entries, AXI credits, issue width, cache
capacity, or change ordering and error semantics.

Each burst engine holds exactly one complete TileLink transaction, which is
either a read or a write. Independent AXI IDs still have independent engines
and independent payload memories. A read and a write on different IDs can
continue concurrently; no shared global data port has been introduced.

The previous lane used separate `readData` and `writeData` register arrays plus
write strobes. The candidate has one `maxBurstBeats x 72` asynchronous-read
memory: 64 payload bits and 8 write-strobe bits. There is one explicit capture
port and one explicit read port. TL writes capture their strobes; AXI reads
put zero into the unused strobe field. Metadata resets continue to prevent
uninitialized/stale payload from becoming architecturally visible.

- Idle/collect-write accepts TL A into the private payload; denied writes drain
  every A beat without writing it or issuing AXI.
- Read-data captures all R beats, aggregates errors, and only then offers D.
- Write-address offers buffered W independently of AW readiness.
- Read-reply offers buffered D; write-reply contains no data.
- Payload capture is asserted mutually exclusive with both output offers.

One beat cursor serves capture and playback. The final R capture uses the
old cursor for its write and resets the register to zero for the following D
beat. This avoids adding a state-controlled read-address mux ahead of the
asynchronous memory. Denied oversized reads still count their complete TL
response length using the full size-domain cursor, not the truncated buffer
address.

The wrapper already has one selected write owner, either the write FIFO head
or the exclusive-write slot. A one-hot owner decode therefore replaces the
redundant AW round-robin arbiter. AW remains buffered by the same two-entry
registered skid queue. Write FIFO progression still observes AW **enqueue**
and final W acceptance independently, never the external AW handshake in
place of enqueue.

## Structural target, not a physical result

Logical payload capacity changes from 136 to 72 bits per beat. At four lanes
and sixteen beats this removes 4,096 duplicated logical storage bits. The
second beat counter and one AW arbitration state/selection network also
disappear. This is not a measured LUT/FF/BRAM reduction: mapping, duplication,
read-port fanout, placement and routing require Vivado on the intended device.

The required CPU100 MHz timing margin remains a hard constraint. In particular,
check async memory-to-W/D selection and AW skid-queue input paths. No claim of
improved routed timing, bandwidth, IPC or board performance follows from source
or CHIRRTL structure alone.

## Focused acceptance

The cloud `cloud-r2` baseline/candidate comparison passed all four eight-beat
models under ASan/UBSan. Exactly 986 / 1608 / 1771 / 1771 cycles match in the
respective configurations (6,136 cycles per version). All eight independent
read/write oracle mutations are rejected on each version. The frozen source
comparison permits only the two bridge files and confirms the expected
single-reader/single-writer memory structure. Evidence is copied into
`build/gsim/axi-payload-reuse-cloud-r2/{baseline,candidate}`.

The selected four-slot/sixteen-beat/two-write-credit/unordered-D shape also
passed the existing independent mixed-memory and AW/W channel oracles on both
versions, with identical full protocol and benchmark-cycle logs. Read/mixed
stress retained four outstanding transactions and two write owners; all five
additional data/ID/RLAST negative controls are rejected on each version. This
extends the bounded scope to the selected burst capacity.

Ten matching baseline/candidate SystemVerilog inputs are exported under
`build/fpga/axi-payload-reuse-cloud-r2`, with SHA-256 manifests and a conservative
10ns component-comparison Tcl script. These have **not** been synthesized or
routed. These bounded proofs do not qualify every generic burst capacity or
the complete production SoC.

`simulator/gsim/axi_buffer_reuse.py` exercises the same deterministic independent
oracle on the frozen baseline and candidate:

- Single lane; four lanes with exclusive writes/unordered D; four lanes with
  two write credits and both ordered/unordered D.
- Repeated read-to-write and write-to-read reuse of every physical AXI slot.
- Partial writes, AW-before-W, W-before-AW, held W/AW/D and late R errors.
- Oversized Get/Put denial, inverse-ID B completion, mixed live transactions,
  reset during ownership and clean recovery.
- Separate read-data/write-data oracle mutations must fail.
- Exactly matching driven input and meaningful output cycle traces; only the
  two bridge RTL source files may differ in the A/B source snapshots.
- CHIRRTL must contain one payload memory, one writer and one reader per lane.

Run baseline with `--expect-layout split`, then candidate with
`--expect-layout shared --baseline <baseline-output-directory>` and unique
tags. The script neither swaps source files nor runs synthesis, full GSIM or
long Linux workloads. Final passing receipts, when available, establish only
this bounded bridge functional/structural scope. The original CPU/board/ROM
handoff proofs do not automatically qualify modified RTL.
