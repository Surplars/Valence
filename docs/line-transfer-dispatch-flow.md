# Line-transfer dispatch flow: bandwidth checkpoint

2026-10-11, dev `c46359c3f35758465ca6e94d3fa5609747a1be30` plus local source-hashed
patch. Independent opt-in candidate, default OFF. This is the second coherent
bandwidth batch, after [DDR write collection/send overlap](ddr-write-collection-flow.md).
The next [independent line-read ingress/whole-line return batch](line-read-channel.md)
is now implemented and separately qualified. The measurements and source hashes
below remain this second batch's historical checkpoint, not current-source proof.
No physical timing run was made for this second batch, following the user's
instruction to prioritize useful bandwidth and avoid frequent STA.

## Three related structural changes

1. The line reader can offer a newly accepted Get directly when its dispatch
   queue is empty. If A stalls, the accepted owner, address and caller tag spill
   into the existing queue/registers; the following offer stays stable. Request
   admission still depends on registered occupancy, not downstream A READY.
2. The line writer loads the registered active payload directly from a newly
   accepted request when its dispatch queue is empty. It can also capture a late
   successor on the current burst's last accepted A beat. The 512-bit input does
   not bypass the active payload registers onto the fabric.
3. The mixed coherent home qualifies an accepted multi-owner DMA line against
   live same-line owners and committed directory ownership. An unowned,
   nonconflicting line skips the otherwise redundant hazard state. A conflict or
   committed cache owner retains the original hazard/probe/drain path. This does
   not add lookup logic to upstream request READY or remove the register cut
   between accepted home metadata and transport.

Owner count, payload capacity, shared AXI slots, write credits, response storage,
source namespace and physical address width are unchanged. Source/slot reuse
still waits for accepted final responses. Last-beat errors, response backpressure,
dirty probes, AMO/LRSC, drain and same-line ordering remain part of acceptance.
Neither reader mode supports a zero-cycle D response to a new request.

`lineTransferDispatchFlow` selects the production home and both line engines;
`--line-transfer-dispatch-flow` forwards through the native and GSIM FPGA-next
entry points. It requires the existing coherent TileLink mixed-home assembly.
It is independent of `--ddr-write-collection-flow`. No default or frozen recommended
profile is promoted. At this checkpoint the FPGA configuration had 37 fields;
the third batch adds field 38. Historical auditors keep all three experiments OFF.

## Completed short acceptance

Receipt: `build/gsim/line-transfer-dispatch-local-20261011-r1/receipt.json`.
Status: `PASS_LINE_ENGINES_AND_COHERENT_DMA`.
Receipt SHA256: `59512326a6179b97d9c1775cab740e2775503acbd1bed9f633f53323e6665ab7`.

The paired run builds six fresh models: reader, writer and real coherent-DMA
integration, each OFF and ON. Both DMA sides enable the first batch's DDR write
collection flow, retaining four line owners, four shared AXI slots, two write
credits and identical traffic/service laws. ASan/UBSan are enabled. The oracle
uses externally accepted transactions and independently authored bytes, not DUT
owner pointers or payload RAM. All ten checker-mutation controls were rejected
at their intended checks. The reused DMA models additionally passed short
dirty/probe/error/AMO/LRSC/order/drain protocol checks.

The unified affected Scala configuration/elaboration gate passed 32 tests; the
host CLI/default checks passed five tests across the two new options. The Scala
logs and XML report are archived in this batch's `scala-acceptance/` directory.
The archived XML SHA256 is
`2b355abfff7fe1d21c595154edc50178af9642479a3f141bb1b362616fee490a`.
At this checkpoint's documentation/archival, all 501 frozen input hashes matched
its hardware/verification sources; the original acceptance receipt is unchanged.
Subsequent third-batch sources have a separate 503-input receipt.
Generated models, full event logs and receipts remain under WSL `build/`, not
in version control. There was no full GSIM regression, Linux simulation,
executing-CPU benchmark, SoC synthesis, bit generation or new STA in this batch.

Reproduction, using a fresh tag for every acceptance:

```sh
python3 -B simulator/gsim/test_ddr_write_collection_cli.py
python3 -B simulator/gsim/test_line_transfer_dispatch_cli.py
mill -i IonSoC.test.testOnly \
  ooo.LineTransferDispatchConfigSpec ooo.DdrWriteCollectionConfigSpec \
  ooo.FpgaNextConfigSpec ooo.DistinctWayReleaseConfigSpec \
  ooo.MemoryStateReuseConfigSpec ooo.CanonicalVirtualStoreBoardConfigSpec
GSIM_CXX=clang++-19 python3 -B simulator/gsim/line_transfer_dispatch.py --tag UNIQUE_TAG
```

## Matched bandwidth results

Payload rates assume 100 MHz and are derived from measured component cycles;
they are not board measurements or MIG peak rates. OFF below means only dispatch
flow OFF; DDR write collection flow is ON on both sides. Accepted AXI read/write
bytes and AR/AW/B transaction counts match between each pair.

| Coherent DMA payload | External service | OFF cycles | ON cycles | Payload MiB/s OFF -> ON | Gain |
| --- | --- | ---: | ---: | ---: | ---: |
| 4 KiB | Existing delayed profile 0 | 2,112 | 2,052 | 184.955 -> 190.363 | 2.924% |
| 4 KiB | Existing minimum-delay profile 1 | 872 | 815 | 447.964 -> 479.294 | 6.994% |
| 128 KiB | Existing delayed profile 0 | 64,609 | 62,812 | 193.471 -> 199.007 | 2.861% |
| 128 KiB | Existing minimum-delay profile 1 | 26,912 | 25,367 | 464.477 -> 492.766 | 6.091% |

| 128 KiB duty: accepted beats / measured cycles | Delayed OFF -> ON | Minimum-delay OFF -> ON |
| --- | ---: | ---: |
| TL A accepted-beat duty | 28.529% -> 29.345% | 68.490% -> 72.661% |
| AXI R accepted-beat duty | 25.359% -> 26.084% | 60.880% -> 64.588% |
| AXI W accepted-beat duty | 25.359% -> 26.084% | 60.880% -> 64.588% |

A mixes Get addresses and Put data beats; it is not an address-only request duty.
COPY payload counts each copied byte once, while logical read-plus-write traffic
counts it twice. Neither is actual DDR bus utilization. Do not multiply these
DMA gains by prior executing-CPU/cache gains or call them IPC improvements.

Independent engine markers establish the removed bubbles:

| Directed case | OFF | ON |
| --- | ---: | ---: |
| Accepted read request -> first A offer | 1 cycle | 0 cycles, with stable spill if stalled |
| Accepted write request -> first A offer | 2 cycles | 1 cycle, registered payload retained |
| Late successor accepted on previous burst's last A | 1 bubble | 0 bubbles |

## Remaining measured bottlenecks and next batch

In the 128 KiB delayed integration, mean read home-to-first-A falls from 8.986
to 7.985 cycles and write home-to-first-A from 4.048 to 2.048. WLAST-to-B remains
43.014 cycles: the external service latency was not changed. RLAST-to-last-D is
still about 8 cycles. Mean shared bridge occupancy rises from 3.393 to 3.506 of
four slots. Read/write bridge-slot residence increases slightly with the new
arbitration pattern (49.033 -> 49.279 and 58.011 -> 58.260 cycles), despite higher
end-to-end throughput. This candidate has not removed all waiting.

The existing line-transfer arbiter merges reads and writes into one TL A channel.
A write holds that channel for eight accepted beats, so a Get can wait even when
the eventual AXI AR and W channels are independent. This is a concrete structural
target, not evidence that every observed stall is caused by this arbiter.

Next controlled design to evaluate: separate read-only line ingress from write /
scalar ingress into one shared AXI owner scheduler. Preserve the four shared
slots and two write credits, route replies by the originating owner, and retain
full interval RAW/WAR/WAW exclusion, same-source ownership, per-channel burst
locks and late-error aggregation. Establish independent two-ingress credit,
stall, overlap, error, source-reuse and byte oracles before comparing a real
coherent-DMA pair. This split is NOT implemented or qualified in this checkpoint.

Do not bypass the coherent home, instantiate independent uncoupled bridges to
inflate credits, remove the historic CPU host AW/pending-read fence, or forward
early R data while discarding the existing complete-response error contract.
Increasing credits alone is not a substitute for improving request supply.
An executing-CPU comparison and combined physical timing/resource qualification
remain necessary before changing the recommended FPGA/board configuration.
The proposed split has since been implemented in the separately source-hashed
third batch; see [its contracts, result, failures and remaining limits](line-read-channel.md).
