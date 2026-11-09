# Netboot checksum aligned-halfword candidate

Only netboot.c's sum16 changes: on an even source pointer, use a GCC-supported may_alias uint16_t load while at least2bytes remain, convert to network byte order, and preserve uint32_t accumulation. Odd pointers and the final odd byte retain the original byte path. The candidate explicitly requires little-endian targets. It neither disables UDP checksums nor changes CRC, image stores, DMA, or packet ownership.

## Reproduce the native regression

With an existing GCC and ASan/UBSan development environment:

    python3 scripts/test_netboot_sum16.py --dry-run
    python3 scripts/test_netboot_sum16.py --out build/netboot-sum16-native

The test runner first checks that its frozen candidate function exactly equals the production function. The original and candidate snippets plus oracle are byte-identical to the tested experiment. The runner is a separate portable packaging change; it uses no private workspace paths. Its positive test covers458,976direct and196,704chained cases across8alignments,0..2048lengths,4patterns and7initial sums. The deliberate negative mutation must fail at the exact length2 anchor. Strict aliasing, ASan and UBSan are enabled; LSan is disabled. Sanitizer granularity complements, rather than replaces, the alignment/range proof.

## Real CPU experiment already completed

Matched16KiB TFTP/window4, same GSIM CPU/DMA/memory model and real MAC RX+CDC endpoint, same host/frames/service law, retained CRCmode3,100MHzCPU:

- Interior ACK4→ACK16:34.765264→38.208213Mb/s (+9.9034%)
- Full firstDATA→retiredEOFACK:34.031469→37.320844Mb/s (+9.6657%)
- RXchecksum inclusive interval:98,230→65,008cycles (−33.8206%)
- StreamCRC:149,360cycles in both; store74,410→74,424cycles
- Both runs passed all17DATA,19totalRX completions, byte/CRC/ownership ledgers and actualCPU16KiB readback plus sentinel

The emitted RV64 fast path contains lhu, with alignment/length guards and byte fallback/tail. sum16 text grows112→160bytes; table/BSS stay2048/5376bytes. These are one deterministic matched pair and inclusive retired software intervals, not physical timing, whole-system throughput or an installed-board result. The user's running ROM/CRC identity remains unverified. ACK capture is a declared bounded test boundary; actual TXDMA/PHY and final2s dally/RAMCRC/autoboot are outside this RX experiment.

The CPU reproduction inputs require the separately retained qualified saved model and bounded RX harness; this small repository patch is not a self-contained fresh CPU build. Source-only harness evidence is packaged separately, explicitly bound to those inputs. No saved CPU/model artifacts or unrelated CPU candidate source is included here.

## Baseline and scope

Local base ea77475d5a39c63dd01856d52167bb007833f387 has the exact tested original netboot.c SHA256 f3470104a6bef117c5516528d32c58ffb268d8547e946802bac746d70bc3334e. The base does not descend from the blocked8248596CPU batch. This candidate changes one production function plus native regression/docs only; it does not merge any hardware candidate or move main.
