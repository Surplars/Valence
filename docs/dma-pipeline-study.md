# DMA pipeline bottleneck study

These historical checkpoint numbers are simulated at 100 MHz, with unchanged phase-1 production RTL. The study source is commit `d6be099a87149a0b71206ad3af680b3c04b25ef1`; later overlap changes are documented in [dma-line-overlap.md](dma-line-overlap.md). The 36 cases cover 512 B, 4 KiB and 128 KiB through full atomic/home/TL/AXI, diagnostic atomic bypass, and independent ideal 512-bit line slaves with/without AtomicMemory. The real path also passes the existing directed ownership/error/AMO/LRSC protocol suite and three host checker-sensitivity negatives. All production source hashes match the clean phase-1 freeze. This is a component study, not new board or timing qualification.

## Findings

- 128 KiB delayed AXI: 253,923 cycles, 49.227522 MiB/s. Diagnostic atomic bypass is exactly cycle-identical at every size and latency setting. Removing atomic protection has no isolated-throughput benefit.
- Minimum configured AXI latency: 100,355 cycles, 124.557820 MiB/s. Configured zero and one cycle are identical because the host slave drives a response on the next cycle; this is not a combinational-memory test.
- Delayed path average accepted-read lifetime is 53.1191 cycles; accepted-write lifetime is 67.8652. Read-to-write and write-to-next-read turnaround are exactly 1 and 2 cycles. Total is about 124 cycles per copied 64 B.
- Read stages: home to first TL A 2; TL A to AXI AR 2.1191; AR to first R 32; R span 7; final R to final TL D 8; final D to home response 2; home-to-DMA response 0.
- Write stages: home to first TL A 3; eight TL A beats span 7; first TL A to AW 9.0684; AW to first W 1.0342; W span 8.7627; WLAST to B 43; B to final TL D 1; final D to home response 2; home-to-DMA response 0.
- Line/home occupancy peaks at 1; bridge occupancy also peaks at 1 despite 4 shared slots and 2 write slots. The bridge is occupied by this single transaction 90.32% of cycles, averaging only 0.903 occupied slots out of 4. Its R/W occupancy is 0.396/0.507 slots.
- Existing minimum-latency path still spends 22 read + 24 write + 3 turnaround cycles per copied line. Store-and-forward R playback (8 cycles) and complete TL-A collection before AXI W remain visible after external latency is removed.
- The independent 512-bit ideal-line slave yields 1220.35 MiB/s at one-cycle replies, 321.21 at 8, and 91.10 at 32. These bypass all 64-bit serialization and coherence; they only bound DMA control/supply overhead and are not attainable RAM bandwidth claims.

## Capacity estimates and ceilings

One-way 64-bit 100 MHz is 762.94 MiB/s. Scalar shared-request copy has a 381.47 MiB/s ideal request ceiling; line-burst copy instead needs 1 Get + 8 Put A beats and 8 read + 1 write-ACK D beats, giving a 678.17 MiB/s ideal A/D ceiling.

Using isolated observed bridge-slot residence (49.1191 read, 62.8652 write), four shared slots imply a 218.01 MiB/s average occupancy estimate, while two write slots imply 194.18 MiB/s. These are latency-capacity estimates, not achieved results or strict universal bounds: mixed contention and AXI-ID skew may lengthen residence. At minimum delay the analogous estimates are 659.84/642.48 MiB/s. Merely exposing all four slots under the current delayed model cannot justify a near-678 MiB/s claim.

## Next bounded prototype

Start with two tagged operation owners and two DMA payload buffers; allow read-next/write-previous overlap through the existing transfer/AXI slots. Preserve AMO exclusion and LR invalidation. Serialize coherence admission/probes and retain global exclusion of refill/ordinary maintenance while owners are live for the first prototype. Check same-line hazards after registered admission, not in READY. Stop admissions for waiting ordinary/refill work and drain every accepted/held owner before yielding. A depth-four comparison can follow from the measured depth-two result. No production RTL has changed at this study checkpoint.

## Reproduction and evidence

For this historical study, check out the checkpoint source above in an isolated worktree, or restore its source from the evidence archive, then run `simulator/gsim/dma_pipeline.py --tag <fresh-tag>` using the existing verified cloud tool environment. Do not substitute the later overlap RTL when claiming an unchanged phase-one source comparison. Receipt: build/gsim/dma-pipeline-study2/receipt.json; raw handshake events and occupancy integrals are in test.log/events.json; protocol and negative logs are sibling files. Every occupancy sum is independently recomputed from handshake timestamps. Initial study1 compilation failed because the host driver attempted getters for input-only ports; the fixture was corrected to observe the host-driven values before sampling. Its failed receipt/log remains archived and is not a successful run.
