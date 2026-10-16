# 2026-10-16 native timing repair source candidate

Publication base: dev611b3fb531fe9446bb36aad161d56c30e4082966. This source-only reconstruction preserves the complete src/main and src/test trees of CPU50cb0c5d4b17318904d6cf818ad23829821d5d93 and the network hardware adapter of7dc9cea2dfc45d1921664efa2dc7c2fc894572ee. It does not promote the later cache-aperture experiment. Library defaults remain OFF; the explicit repair-on profile selects the qualified batch.

## Exact selected hardware

Native entry: ooo.CombinedTimingRepairR1NativeMain, fresh-output-directory, repair-on. Top FpgaNextSocTop,179 core fields,96 profile fields,76 ports. Selected features: home pre-arbiter boundary, projected request head, factored preparation pool, full proof-bank control decoupling, registered preparation descriptor, aligned backend PMP specialization, and checked next-line classification. Raw preparation and narrow rename-clear experiments remain OFF. Existing shared fetch PMP, cache overlap, GMAC and JTAG configuration is preserved.

Build the Scala test module with the repository's pinned Mill setup; invoke `IonSoC.test.runMain ooo.CombinedTimingRepairR1NativeMain <fresh-directory> repair-on`. The emitter writes CHIRRTL and actual constructor/profile audits. Four expected JSON inputs are source fixtures required by the audit; they are not execution receipts.

The matched lowering used firtool1.135.0, binary SHA256 c2e1ac4d88be9579313c8a33ea3c8643db7d1840c78a4593dc05395171e25051, with --disable-all-randomization --default-layer-specialization=disable --strip-debug-info --lowering-options=disallowLocalVariables --split-verilog. Include the three resource SV files in addition to the split-file listing; the matched CPU export contained290 SV files. Generated RTL and tool binaries are not committed here.

The network source adapter is fpga/zu15eg/combined_network_candidate/export_board.py, BOTH mode: --enable-pad-domain-reset --enable-rx-capture-sibling --serializer-profile t1-selected. Apply the existing fpga/next/export.py bscan_board_wrapper transformation and check_wrapper_ports against the actual FpgaNextSocTop export. The resulting physical wrapper has76 named CPU ports and physical top soc_top_fpga_next_ddr; the matched wrapper SHA256 is467ff67094af5eac3947d735dd424d77d67b8b5ee8ffd62e4e3f9433eac71a09. T1 and selected half are both1. Six board SV files accompany the290 CPU files.

Use the versioned combined-network constraints/diagnostic source, not the legacy fixed-topology sealing entry. Source-bound runtime compatibility files are captured separately; their observed use and remaining external dependencies are stated in their README. They are not permission to start implementation.

## External implementation dependencies

Vivado2025.1 build6140274; xczu15eg-ffvb1156-2-i. Reuse the exact verified BMG, DDR4, clock wizard and AXI clock-converter IP dependency set; no vendor binaries included. The actual local dependency-contract SHA256 is fbc338c1089041260d9ae9e8f6e0a3382e8a722f69156ae9540ed9084809ab8b.

ROM is the verified67280-byte image SHA256 ee7c2e5fb86d50dad55df532aeb7ccb1d0b91cb37b0b7042d03b446eee362d79; padded131072-byte word image SHA2560d03f41230ed458e133d9503acba36edb34689f5aaa6cafd41ea2f81ec5879fd. Do not use the older unverified434de/a020 expectation. Firmware source tree is unchanged from3554932. Full32768-word and leaf-clock checking passed on the matched local design.

## Validation and current reported physical state

The frozen50cb batch passed six focused board cases and five negative controls. Relative to the saved full-C1 reference, Sv39 write cycles increased11.984% and copy cycles8.579%; those costs are not hidden by timing improvement. No full Linux regression or on-board boot is claimed.

First routed result was WNS−0.096ns/TNS−5.717ns with123 CPU setup failures; hold/recovery/removal were positive. The parent subsequently reported a single authorized post-route phys_opt run14:18:14–14:33:50, final DCP SHA25623a4edd50f0c4852f89ffb549f5ba9d2c51dc2019f546479b1dbe538ce102743, final14:35 summary WNS+0.006ns/TNS0/WHS+0.010ns/THS0, zero setup/hold failures and256283 fully routed nets. These final values are **local reported, pending artifact review** at preparation of this source candidate. Bit generation is separately authorized locally; no bitstream is included or claimed generated here.

## Publication boundary

No generated RTL, bitstream, DCP, compiled model, log, execution receipt, or old rejected evidence payload is included. Historical output receipts remain outside this commit. This is a local review candidate; remote publication is handled separately.
