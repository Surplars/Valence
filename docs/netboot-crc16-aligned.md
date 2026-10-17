# Mode3 CRC aligned-halfword input

This follow-on to the aligned sum16 candidate changes only mode3 CRC input loading. Even pointers with at least two remaining bytes use a GCC `may_alias` halfword load. Odd pointers and the final byte retain their original byte paths. The recurrence and2KiB table are unchanged. Little-endian compilation is explicitly required for mode3. Other CRC modes preprocess identically.

Run the portable native regression from the repository root:

```
python3 scripts/test_netboot_crc16.py --out build/netboot-crc16-native
```

`--cc` selects an existing GCC-compatible compiler; no installation is performed. `--dry-run` prints inputs and scope without compiling. The script verifies exact production/candidate function identity and reconstructs the original function against SHA256 `dd2c907c9857744e74a6685b41298d2bc996121331c003c87aab78f1208f9900`. It checks unchanged modes0/1/2, strict-aliasing ASan/UBSan execution,328,640direct and525,792chained cases, all8alignments, lengths0..2048 plus boundary lengths up to16KiB,4patterns,5initial CRCs, independent bitwise results and known vectorCBF43926. A deliberate length2 result mutation must fail at its exact anchor. LSan is disabled; ASan/UBSan remain active. Poison granularity does not replace source bounds review.

## Qualified CPU experiment

The frozen16KiB/window4 RX experiment retained the same saved GSIM CPU/DMA/memory model, real MAC RX/CDC endpoint, host binary, legal packets with nonzero UDP checksums and service law. Sum16, store and protocol code remained unchanged. Full throughput improved37.320844→39.076069Mb/s (+4.7031%); interior ACK4→ACK16 improved38.208213→40.045136Mb/s (+4.8077%). StreamCRC inclusive interval fell149,360→133,181cycles (10.8322%). Interior cost is19.977458CPU cycles/image byte. Actual CPU readback checked all16KiB plus sentinel; descriptor/write-response counts matched.

RV64 emitted guarded `lhu`; text grew72bytes while data/BSS remained2,048/5,376bytes. Source-identical store time changed slightly with layout, so attribution is a matched software experiment rather than a unique hardware-stall decomposition. Inclusive call counters must not be blindly added.

This is one deterministic pair, not board qualification or installed-ROM identity. ACK capture is a bounded test callback. Post-transfer readback, final2s dally/RAMCRC/autoboot and production TXDMA/PHY latency are outside the transfer interval. The CPU benchmark depends on preserved qualified model objects and endpoint artifacts described in the separate bounded RX source package; this native test does not rebuild or independently reproduce that CPU model. No generated models or binaries are committed here.
