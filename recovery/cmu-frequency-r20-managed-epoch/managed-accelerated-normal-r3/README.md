# Accelerated normal/unrelated qualification

The exact r3 native run passed in 229.610606 seconds under its separately approved 300-second wall-only budget. The child exited zero and its runner reaped it. Production, DUT and guest timing are unchanged. This is only one normal case and one clock ratio. Cancellation, reversed ratio and four combined negatives are still pending.

The actual source completed 51 initialization MDIO transactions while the empty preboot CPU/fabric/UI/timer/debug domains were paused. Real park/empty/reset/page-zero/config/MDIO boundaries and low-phase clock handovers were checked. After permanent same-fabric rejoin, the real release receipt preceded ROM, CSR and guest work. This fixture scheduling optimization is not a production fixed-clock domain, gate, DRP or fullACK proof.

The independent compare_managed_epoch.py script compares 17 complete marker classes and five stable-field marker classes against original same-clock r6. It also checks production sources, guest binary/hex/symbols, clock vector, ordered CSR results, two 72-byte/FCS packets, retained configuration/statistics, and exactly-once retirement. Its lost-packet, corrupt-statistics and broken-timer-conservation selftests are expected rejections.

Timer traffic is phase-dependent: r6 had 58/58 final MMIO and 53/52 post-resume ownership; r3 has 42/42 and 37/36. AXI stall counts differ but remain nonzero. The two runs independently conserve all owners. Both have packet DMA 16/16, AXI R66/66 and B3/3, CSR6/6, two retained drops and one retirement at each actual epoch join. Comparison does not force timing-dependent traffic equality.

All 331 frozen source files, 257 emitted RTL files, 11 tool/configuration files, guest/log/assertion/binary artifacts and the baseline/emission receipts were independently rehashed. Both preserved 248-module default RTL inventories were independently rehashed byte-identical. Generated binary/RTL files remain under out, not in this commit. Phase observations record read time with at most one-second polling after observer startup, not simulator-emission timestamps; early lines may predate observer startup.

This result does not overwrite any failed or interrupted run. The old r5 child outcome remains unknown. Remote upload remains blocked; this checkpoint is local only.
