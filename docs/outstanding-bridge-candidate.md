# Four-slot read-overlap bridge candidate

## Contract and limits

The default `TileLinkAxi4Bridge(maxOutstanding = 1)` still selects the unchanged serial burst engine. Values 2/4/8, bounded by AXI ID and TL source widths, select a bank of independent existing burst engines. Four is the proposed external-DDR setting; no CPU, coherence, cache, FENCE, frequency, UART, or memory-window configuration changes are included.

One slot owns one TL source and one AXI ID until the complete TL response drains. A repeated source is backpressured. Ring allocation and head-only D arbitration preserve acceptance-order completion and prevent D burst interleaving. Later IDs can receive all their R beats while the oldest waits. Each lane buffers its entire read and aggregates errors before returning D, so a final-beat AXI error denies/corrupts the complete TL burst, with zeroed data. This also preserves the old out-of-window response behavior.

Writes are exclusive fences. A first write A beat is accepted only after all prior TL responses have drained; subsequent A beats are locked to its slot; later reads/writes wait for its final D acknowledgment. Thus overlapping-address read/write hazards do not depend on unspecified cross-ID AXI ordering. This is concurrent reads plus serialized writes, not fully parallel read/write and not a claim of maximum system throughput.

AR/AW use registered two-entry queues after arbitration. Address payloads cannot change under backpressure. AXI permits W before AW; the harness chooses to hold WREADY until it has observed AW. The existing burst engine verifies RLAST, beat lengths, masks, alignment, 4-KiB crossing, and unsupported TL messages. The wrapper routes response IDs and asserts against an ID without a live channel owner. Reset clears allocation, queues, and all lane FSMs. Reset must flush the downstream AXI domain as in the existing design; accepting stale pre-reset responses is not supported or newly implied.

Finite accepted work cannot starve: ring D head eventually drains when its complete R burst is supplied and DREADY returns. Later completed reads cannot replace that head, but cannot block its R channel because buffers are per slot. An indefinitely withheld oldest memory response or DREADY still stalls progress by protocol design.

## Downstream source-level ID audit

- `MachinePlatform.scala`: existing external DDR port/manager has AXI ID width 4.
- `fpga/zu15eg/soc_top_ddr.sv` and `soc_top_gmac_ddr.sv`: CPU ARID/AWID go through the clock converter into MIG; RID/BID return through the converter. No ID tying or truncation is present.
- `prepare_ddr_project.tcl`, `build_board_clock_rom.tcl`: converter `CONFIG.ID_WIDTH 4`.
- `prepare_ddr_project.tcl`, `build_native_board.tcl`: MIG `CONFIG.C0.DDR4_AxiIDWidth 4`.

This proves the checked-in connection contract, not the properties of a previously generated IP checkpoint. No Vivado or board run is included.

## Independent focused verification

`python3 simulator/gsim/outstanding_bridge.py` runs identical serial and four-slot hardware test models against one independent C++ oracle and latency model. Checks include varied 1/2/4/8/16-beat transfers, repeated addresses, partial writes, all-beat error propagation, rejected-window traffic, source ownership, reordered read IDs, AR/AW/W/D stalls and stability, exact AXI/TL transaction counts, reset with live reads and a partially transmitted write, and clean post-reset operation. Negative runs inject bad RLAST, unknown RID, and corrupt the expected data independently.

The matched benchmark reports read-only and one-write-per-four-transaction mixed traffic at a fixed 32-cycle synthetic read latency. It measures bridge capacity, not CPU IPC, MIG latency, DDR bandwidth, or routed 100 MHz timing. Physical timing/resource/power signoff and end-to-end frontend credit limits remain unverified.
