# B1 selected-cache initial correctness results

The unchanged r1 model passed three initial cases and the expected install-observation mutation negative. This is component protocol and byte-correctness evidence, not CPU progress, throughput, or physical timing qualification.

| Case | Cycles | Accepted / ACK / drained stores | Target logical / AR / R bytes | Dirty flush |
|---|---:|---:|---|---|
| Eight full SDs | 597 | 8 / 8 / 8 | 0 / 0 / 0 | 1 AW, 8 W, 1 B |
| 63-byte explicit seal | 635 | 14 / 14 / 14 | 64 / 64 / 64 | 1 AW, 8 W, 1 B |
| 63-byte timeout | 863 | 14 / 14 / 14 | 64 / 64 / 64 | 1 AW, 8 W, 1 B |

Each case had one decision, acquire, grant, E, install and owner release. Eight ordinary 64-bit upstream reads checked actual cache SRAM contents after installation; final dirty writeback and independent backing bytes matched the accepted store intents, including the untouched partial-line byte. Target-read accounting continued through readback, flush and final drain. All exposed owner/resource masks and independent obligations drained. Selected prefetch options are enabled, but these requests set prefetchNextAllowed=0; this does not claim active prefetch coverage.

The negative changes one observed install byte only in the host oracle. It reached the exact named byte-mismatch failure with exit 1 and no sanitizer diagnostic. This qualifies oracle sensitivity, not DUT error handling.

The first attempt failed because the host expected nToT=2; the exact bound TileLink definition is nToT=1. The old source, release, receipt and trace remain preserved under failed-oracle-parameter-r1 and runs. PROTOCOL_CONSTANT_AUDIT.json records the complete opcode/permission/size audit. The reviewer approved the sole semantic correction and the same executable was used for runs-r2. Both corrected runs were sanitizer-clean; positive wall time 0.821 s and negative 0.107 s. Peak task allocation was 15,835,136 bytes, below 48 MiB; sampled minimum free space was 2,268,454,912 bytes.

Pending coverage: dirty victim replacement, probes and permission-to-install transient interactions, active prefetch, default-off lowered equivalence, and separate compact-member integration. No production selection follows from this initial result. Independent final receipt audit is requested separately.
