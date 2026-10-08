# Capability-gated Linux media diagnostics

The new driver exposes raw hardware values through `ethtool -S INTERFACE`. It does not clear counters, alter packet ownership or issue MDIO operations when reading statistics.

## Compatibility and interpretation

The six existing MAC counters are always available on the supported V1 identity: TX/RX frames, RX drops, bad FCS, and TX/RX bytes. Only CAP bits 10, 11 and 12 together, with managed-media extension version 1, enable the additional 21 fields. Old hardware is never probed at reserved diagnostic offsets. As before, an unknown managed-PHY extension version prevents driver attachment rather than programming an unknown PHY ownership interface.

Probe itself is fail-closed: bit 11 without extension bit 10 is rejected before any media-status read. Bits 10+11 authorize one 32-bit read of the version lane at 0x9c. Bit 12 separately enables the detailed statistics. The host oracle checks the actual probe callback's access pattern for all tested CAP/version combinations, not just the reported statistic count.

The 27-field new set contains:

- Six original MAC counters.
- Eight exclusive parser drop reasons: bank full, admission closed, preamble, FCS verdict, length, destination address, PHY/error and link abort.
- TX link-aborted frames, RX/TX FIFO-stall cycles, odd RX nibble tails, physical-ingress overflows and wholly skipped ingress frames.
- Six independent 32-bit lifetime counters: PHY no-ACK, verification failure, link changes, completed polls, unsupported modes and media-transition timeout.
- `media_status_v1`, the actual 64-bit versioned status word. This is a gauge, not an accumulating counter; its bit definitions remain in the MAC qualification record.

Values are not invented or extended into software lifetime counters. MAC counters are modulo 64 bits and clear with cold reset or explicit `CLEAR_STATS`; the PHY/transition counters are modulo 32 bits and clear with cold reset only. Reading statistics does not clear them. A consumer calculating deltas must handle wrap and reset/explicit clear; there is no hardware reset-generation counter from which to reconstruct lost history. Different registers are sampled at different times, so the entire report is not an atomic cross-counter snapshot.

## 32-bit sampling safety

All 64-bit fields use ordered high-low-high 32-bit CSR reads and retry when the high half changes. This prevents a carry, wrap or reset between bus operations from returning a torn value. Independent packed 32-bit PHY fields use exactly one read of their actual lane. The fastest ordinary upper-half carry is once per 2^32 / 125 MHz, about 34.36 seconds; normal counter progression cannot continuously defeat the short retry loop.

This sampling helper supports a 32-bit MMIO read path. The overall driver remains the existing RV64 driver: DMA/MDIO launch commands still require the original atomic full-width writes, and this change does not claim a complete 32-bit kernel port.

## Using the counters to narrow packet loss

Read statistics before and after a controlled transfer, alongside the existing `napi_status` sysfs snapshot and an independent packet capture:

- Bank-full or ingress-overflow growth points to capacity/ingress loss before DMA ownership.
- Admission or link-abort growth indicates closed-media/transition loss.
- FCS/PHY/preamble/odd-nibble growth points to wire framing or media capture; board timing must still be checked independently.
- MAC accepted frames advancing without matching DMA/software progress requires inspection beyond the parser. Zero posted-RX drops alone does not exclude earlier MAC/ingress loss.
- The old `mac_rx_bad_fcs` observation and the exclusive `rx_drop_fcs` verdict have different meanings. Do not sum both as separate dropped packets. Ingress-overflow counts also overlap poisoned-prefix parser drops; only wholly skipped ingress frames are added separately to the legacy total.

The driver feature passed 1,188 value/carry/reset cases, 32,768 capability/version cases and 32,768 actual probe-access cases, plus the existing 24,576 media-policy cases. The deliberate counter-oracle mismatch was rejected. The final Linux module compiled for RISC-V with `W=1` and no warnings. The matching firmware guard rejects unsupported managed-PHY CAP combinations without probing reserved status or issuing PHY commands; its existing 30 MMIO, 22 posted-RX and 4,162 store/alignment cases still pass.

Reproduce the host statistics checks with `python3 fpga/firmware/linux_net/test_media_stats.py FRESH_OUTPUT`. The combined source-bound proof is `build/trispeed-linux-stats/receipt.json`, with host checks under `host-r3/` and the isolated module under `module/`. These checks do not establish board throughput, solve a TFTP-stack loss, or qualify the new physical tri-speed path.
