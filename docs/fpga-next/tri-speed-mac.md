# FPGA-next tri-speed MAC qualification record

Status: implementation and simulation in progress. This is an opt-in source candidate. The existing `ManagedGmac`, `native_rgmii`, clock generation and old project remain the default. No Vivado synthesis/place/route, timing closure, bitstream or board claim is made here.

## Media architecture

- The TX engine and symbol generator use one continuously running 125 MHz reference. The forwarded 125/25/2.5 MHz signal is an ODDR **data** waveform; it never clocks internal logic and no fabric clock mux is used. Logical codec proof is separate from the unqualified physical adapter below.
- TX byte-enable periods are1,10 and100 reference cycles. A rate change inserts at least12 new-rate idle byte times before accepting a wire byte. Preamble, body, FCS and the 12-byte IFG advance only on that enable. At 10/100 each byte is two successive rising-edge nibbles; each nibble is duplicated on the falling data edge. RX_CTL/TX_CTL remains DDR encoded at every rate.
- The initial `native_rgmii_trispeed.sv` experiment uses a nominal 2 ns TX-clock delay cascade. It must not be selected: repository history records failed setup/hold results for earlier calibrated output-delay candidates. The new, also unqualified `native_rgmii_trispeed_quarter.sv` preserves the shipping common-125/250 MHz clock architecture. All six pad ODDRs use 250 MHz; data changes only on positive edges and TXC only on negative edges, retaining a fixed 2 ns source skew at every rate. PHY policy verifies TXDLY=0 and RXDLY=1. No physical success is inferred from the existing 1G ancestor.
- Recovered RXC must go through IBUF→BUFG directly. The legacy fixed-125 MHz RX MMCM is incompatible with 25/2.5 MHz input. IDDRE1 produces rising/falling pairs on the recovered clock; the low-speed decoder assembles one byte every two recovered cycles. Missing byte-enable cycles cannot terminate a frame. Odd-nibble tails produce an errored byte, then an explicit idle.
- The physical RX decoder packs four bytes per token into a64-word dual-clock ingress FIFO. Its destination and the RX frame engine/complete-bank reader run continuously at125 MHz, so a stopped recovered clock cannot strand a partly streamed DMA frame. Existing framed CDC FIFOs retain data/keep/last/bad atomically. The CPU domain stays fixed; there is no CPU/network dynamic frequency coupling.

## Ownership and rate changes

The PHY manager is the only configuration writer in managed mode. It verifies the exact RTL8211F identity `001c:c916`, preserves unrelated RGMII delay bits, verifies write readbacks, advertises 10/100/1000 full duplex only, and disables EEE advertisement. Half duplex, pause negotiation and LPI are unsupported. Every page sequence restores and verifies page zero before releasing MDIO ownership. Software CSR requests are serialized between sequences; only default-page reads of registers 0–15 at PHY1 are accepted. Writes and unsafe vendor/page accesses return noAck explicitly.

Polling reads BMSR twice to handle latched-low link, checks AN complete/remote fault and partner capabilities, and compares two resolved PHY status samples. Two matching complete polls are needed to raise link; failures lower it and record diagnostics. No-ACK/readback failures invalidate initialization and trigger a bounded retry. The MDIO wire clock is 1.25 MHz, allowing a conservative 400 ns read half-cycle with pad synchronization.

A media transition closes new TX/RX admission, cancels only incomplete physical frames, and preserves complete RX-bank/framed-CDC/adapter ownership. A1 ms recovered-clock watchdog also closes the link when RXC stops even if MDIO still reports link. The physical-ingress-only FIFO epoch reset asserts to BOTH endpoints, including while RXC is absent; each endpoint releases on its own clock. It contains no completed packet/DMA owner. The fixed125 MHz frame engine, complete banks and framed output FIFOs use cold reset only.

After partial-parser abort and the fixed ingress pipeline flush, down-link drain waits for real retained-packet/adapter retirement but does not await a dead raw-clock rate ACK. Outstanding raw configuration mailboxes stay owned and can complete after RXC returns. Reopening an up-link requires both actual rate-consumption ACKs and a new returned physical-ingress epoch acknowledgment. The raw packer additionally waits for a real physical idle after capture is enabled, so an embedded SFD in an old frame cannot start a new epoch. A blocked DMA consumer can still retain complete packet ownership; no timeout fabricates its completion. FIFO overflow poisons an escaped prefix or counts a wholly skipped frame, and never joins it to the next SOP. A DMA completion still means transfer to/from the existing MAC stream, not proof of delivery on the wire; TX link-abort diagnostics distinguish that case.

## Additive CSR extension V1

All existing offsets and the V1 identity remain compatible. Check CAP before accessing additions:

- CAP bit10: tri-speed media; bit11: hardware-managed PHY ownership; bit12: detailed drop diagnostics.
- 0x98 MEDIA_STATUS: version63:56=1; initialized0; PHY link1; requested speed3:2; applied speed5:4; pending6; timeout7; PHY fault11:8; MAC ready12; TX drained13; RX drained14; recovered-clock-present15. Speed 0/1/2 means 10/100/1000; 3 is rejected.
- 0xA0: noAck low32, verification failures high32.
- 0xA8: PHY link changes low32, completed polls high32.
- 0xB0..0xE8, eight 64-bit counters: RX bank-full, admission-closed, preamble, bad-FCS verdict, length/LT, address filter, PHY/error/odd-tail, link-abort drops. Drop reasons are exclusive; the legacy bad-FCS observation counter remains independently meaningful.
- 0xF0: TX link-aborted frames; 0xF8: RX FIFO stalled cycles; 0x100: TX FIFO stalled cycles; 0x108: odd RX nibble tails.
- 0x110: unsupported link modes low32, media transition timeouts high32.
- 0x120: physical-ingress overflow/discarded-frame count; 0x128: wholly skipped ingress frames whose prefix never reached the parser. The legacy RX drop total includes these wholly skipped frames; poisoned prefixes are already counted by the parser, preventing double counting.
- 0x118: full-width write1 requests PHY reinitialization; read returns0. It does not erase any DMA or packet-buffer owner.

The14 diagnostic frame/stall counters clear with the existing CLEAR_STATS action; coincident deltas win over clear. PHY lifetime counters are modulo32 pairs. Counter CDC snapshots must be consumed more frequently than 2^32 source increments; the highest-rate cycle counters make that bound 34.36 seconds at125 MHz, so permanently disabling the CPU/statistics consumer beyond that is unsupported.

Firmware and Linux inspect managed-PHY CAP. Managed mode skips the legacy PHY reset/forced-1G/page-delay writer. Linux does not attach a second phylib writer; it polls qualified media status every100 ms, retains IRQ/NAPI for packet processing, reports all three full-duplex rates, and routes ethtool autonegotiation restart to0x118. Without the CAP bit, the original PHY path remains in use.

## Evidence so far

Baseline packet/adapter/DMA suite: 255 frame cases,96 adapter cases,54 DMA cases; independent mismatch injections rejected. Historical first tri-speed frame/codec run, before the stopped-RXC redesign:212 cases;75 TX frames,90 RX frames,35 classified drops;2,658,442 core cycles;363,497 forwarded-clock half-period checks;83,866 duplicate-nibble checks;8,991 stalled RX beats. Its independent TX oracle mismatch injection fails as required. The larger frozen suite must rerun after the RX ownership redesign and added all-six-direction rate/TX-abort checks. This is single-clock GSIM logic evidence, not CDC or primitive timing proof.

Firmware MMIO oracle: all three managed rates start without any MDIO command; a verified delay fault blocks startup; existing30 ordering cases,22 posted-RX cases and4,162 alignment/store cases remain passing. Pure Linux media-status decoder:24,576 combinations, including unknown version, unresolved/pending/timeout/fault and mismatched rates.

## Frozen focused logic milestone (2026-10-08)

`python3 simulator/gsim/tri_speed_gmac.py --tag rx-fixed-r1` passed with unchanged before/after source and harness hashes. Receipt: `build/gsim/tri-speed-gmac-rx-fixed-r1/receipt.json`; production SystemVerilog: the sibling `rtl/` directory. The seven independent models and deliberate oracle corruption checks passed:

- Frames/codecs:239 cases,87 complete TX and90 RX frames,15 TX aborts,415,273 half-period checks,87,466 duplicate nibble checks,61,932 cycles holding a rate request until TX frame/IFG drain; all six directed rate changes checked without disabling clock monitors.
- Physical-ingress logic:102 cases,96 retained frames, two forced physical FIFO overruns, one entirely skipped frame, three completed banks retained through input halt/epoch reset; embedded mid-frame SFD rejected. This is logical input-progress stalling, not independent-clock proof.
- PHY policy:488 register transactions,33 complete polls,14 up/13 down transitions; injected no-ACK, readback mismatch, half duplex and reserved speed.
- Media transition:180 randomized trials,146 TX/RX rate images; down-drain completes despite an outstanding dead-clock rate ACK, while reopening requires a returned ingress epoch.
- MDIO owner:400 policy and80 software requests across80 locked page sequences,53 explicitly denied unsafe software requests.
- Actual Clause22 serializer:96 transactions,9 no-ACK reads,8 reset positions, divider40 at100 MHz (1.25 MHz MDC).
- Native64 CSR:66 accesses,14 diagnostic carry tests above32 bits,15 upper-lane reads, stalled response stability and write/offset denials.

Native independent-clock simulation, primitive timing, synthesis/routed timing and board qualification remain NOT RUN. Capability-gated firmware policy tests passed separately. The managed-PHY Linux module compiled without warnings using the existing RISC-V toolchain and prepared Linux 7.3.0-rc5+ output copied into an isolated build directory; receipt: `build/trispeed-linux/receipt.json`. This establishes compile compatibility, not driver runtime.

The opt-in two-bank TX extension is described in [tx-buffer-bandwidth.md](tx-buffer-bandwidth.md). Fresh post-hook default-off regression also passed: 255 legacy frame cases and 3,045 native CSR requests, including integrated MDIO, with independent negative tests. Receipt: `build/gsim/legacy-mac-post-hooks-r1/receipt.json`.

## Required physical qualification

1. Integrate the new profile into a separate complete-board top. Do not select the legacy fixed-frequency RX MMCM or the generic TX delay-cascade experiment. Use continuous TX125 and phase-related PAD250 from `native_gmac_quarter_clock`, its common word-reset release, REF500 and direct recovered RX BUFG. Preserve the external pin map.
2. Validate the new quarter-clock serializer in native simulation, then check its actual mapped clock/reset phase and ODDR pin connections. The prepared `trispeed_quarter_constraints.tcl` refuses a different topology; it is syntax-checked only, not Vivado-qualified. Check RX IDELAYCTRL grouping/calibration and both PHY delay readbacks before traffic.
3. Export and inspect the real complete netlist and every actual CDC first-stage/payload endpoint. Bound Gray buses with max-delay and bus-skew; bound held-data mailboxes and FIFO RAM payload capture. Do not introduce global asynchronous clock groups or broad false paths that hide these crossings. Related raw/managed clock paths, ODDR data paths and reset recovery/removal remain timed.
4. Analyze separate 1000/100/10 scenarios with 8/40/400 ns recovered RX periods, actual mode-specific forwarded TX waveforms, board skew, PHY setup/hold and calibrated input-delay variation. Generated TX clocks use PAD250 source edges {2 4 6}, {2 12 22} and {2 102 202}. Preserve the existing +/-1.250 ns output budgets on both TXC edges. Only after mapped-topology proof may the physically nonexistent falling data-launch edge be excluded at the pad; no internal or CDC path exemption follows. Do not assume a low-rate multicycle exception from byte enable alone.
5. Inspect both-edge I/O setup/hold, pad clock insertion, clock startup/rate transitions and reset release in the routed checkpoint. Check timing and CDC reports for unconstrained or accidentally cut paths; retain complete reports and netlist hashes.
6. Exercise each negotiated rate with an independently configured partner, cable loss/reconnect, PHY restart, minimum and maximum frames, saturation, no posted RX credits, recovery after credits return and independent packet captures/FCS. Physical link qualification remains incomplete until these tests pass.

## Primary references

- AMD, [PG051 UltraScale RGMII transmitter](https://docs.amd.com/r/en-US/pg051-tri-mode-eth-mac/RGMII): the 125 MHz transmitter reference and 1/10/100 byte enables, lower-rate forwarded clock patterns and dedicated clock-output delay.
- AMD, [UG571 UltraScale SelectIO](https://docs.amd.com/r/en-US/ug571-ultrascale-selectio): DDR and I/O delay primitive contracts and implementation requirements.
- AMD, [UG572 UltraScale clocking](https://docs.amd.com/r/en-US/ug572-ultrascale-clocking): dedicated global clock/reset requirements.
- Realtek, [RTL8211F product specification](https://www.realtek.com/Product/Index?cate_id=786&id=3975):10/100/1000 RGMII PHY capability.
- Linux, [Realtek PHY driver](https://github.com/torvalds/linux/blob/master/drivers/net/phy/realtek/realtek_main.c): device identity and RGMII delay/status definitions.
- U-Boot, [Realtek PHY driver](https://github.com/u-boot/u-boot/blob/master/drivers/net/phy/realtek.c): RTL8211F page0xD08 delay control, page0xA43 status and default-page restoration.
- Alex Forencich, [RGMII PHY interface](https://github.com/alexforencich/verilog-ethernet/blob/master/rtl/rgmii_phy_if.v): independent primary implementation confirming low-rate nibble repetition and DDR-control treatment. No source was copied into this implementation.
