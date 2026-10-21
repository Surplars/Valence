# Routed r2 reset/DCI diagnosis (read-only)

Checkpoint SHA256: `69aec185f64dea8931db5fde7d8bab51e9dc544ac8832d318cb13b414ba55da5`; production source dd814d96. This evidence is for the historical routed r2, not newly qualified runtime-rate hardware. Native query exited0. No synthesis/optimization/placement/routing, constraint edit, waiver, netlist mutation or bitstream was performed. The unchanged DCP hash was read after queries.

## Definite board integration blocker: no DCIRESET

Fresh DCIRST-1 report reproduces44 warnings: c0_ddr4_dm_dbi_n[0:3] and c0_ddr4_dq[0:31] use POD12_DCI; c0_ddr4_dqs_t[0:3] and c0_ddr4_dqs_c[0:3] use DIFF_POD12_DCI. The entire design contains zero DCIRESET cells. Full individual messages, package pins and actual connected leaf cell/pins are in diagnosis.json and dcirst-full.rpt/reset-cones.txt. Other SSTL12_DCI ports are enumerated in reset-cones.txt too; the44 warnings are the reported subset, not the total DCI port count.

Minimal hardware remedy: integrate the official UltraScale+ DCIRESET primitive with a real post-configuration reset sequence and honor LOCKED before allowing DCI-dependent DDR activity. Use an available fixed reference/control clock and avoid a dependency cycle in which DCI readiness waits for DDR calibration while DDR waits for DCI. Reconcile with the original vendor MIG example design/reset contract before implementation. Do not change IO standards, waive DCIRST or assume CPU frequency affects it. This task has not modified RTL or selected an unverified reset pulse duration.

AMD2025.2 UG974 says DCI IO is unavailable during recalibration until LOCKED. [Official primitive reference](https://docs.amd.com/r/2025.2-English/ug974-vivado-ultrascale-libraries/DCIRESET). DRC cites [AR000038677](https://adaptivesupport.amd.com/s/article/000038677); its full web body was unavailable (CSS/loading), so no unobserved article details are asserted.

## Reset CDC: structural findings, not a blanket pass

Fresh report reproduces10 CDC-10 and11 CDC-11 Critical. Every one terminates at PRE/CLR of a reset-release bank. Each of the21 queried path instances has three actual FDPE/FDCE ASYNC_REG=1 cells, same local clock, stage1.D=stage0.Q and stage2.D=stage1.Q, and first D tied to inactive level. Exact source/destination clocks, launch/endpoint pins, assertion startpoints, reset nets and each chain pin net are recorded. all_fanin reports sequential startpoints as /C; these are tool reset-path conventions, not evidence that a clock wire is an ordinary reset payload.

11 CDC-11: ui_reset_pipe[2] fans into six AON release banks (CMU and UART) and five PHY-RX release banks (diagnostics/rawRx/watchdog/rxRate). These are separately synchronized copies of a common asynchronous reset, not eleven unsynchronized data paths. No missing release stage was found. A waiver or full reset signoff still requires shared-owner/reconvergence and release ordering evidence.

10 CDC-10: PHY reset2 paths; UI reset1; RX reset1; GMAC physicalIngress2; network phase reset1; BSCAN3. They have real combinational reset causes:

- PHY: board/UI reset, CPU/MMCM and Ethernet lock, replicated IDELAYCTRL RDY reduction.
- UI: board/UI reset, calibration-complete and combined clock lock.
- RX: common reset OR !IDELAY ready.
- GMAC physicalIngress: common reset OR media.ingressResetSource (two local release banks).
- Network phase: board/UI reset OR !PLL lock. The bank has3cells although report_cdc depth=2: source RTL intentionally taps phase_reset[1] for divider CLR and phase_reset[2] for lock indication. Do not call this missing stage solely from the reported depth.
- BSCAN: common debug POR OR TAP RESET; source/update also OR hard_reset. raw/update release on positive TCK; source releases on negative TCK. All3 FDCE banks exist. Preserve async assertion for stopped TCK and the existing edge/UPDATE contract.

Qualification still required: glitch/minimum pulse behavior of combined async causes, lock/calibration loss, RXC/TCK stopped and restarted, common reset deassertion/reconvergence, divider CLR startup and the FIFO contract when ingressResetSource resets one side. Combinational async assertion followed by local synchronous release is not automatically a functional bug; this snapshot does not prove these protocol/timing properties either. Prioritize definite DCIRESET integration plus focused reset-sequence tests; repair actual protocol failures if exposed, rather than replacing every reset chain or waiving by count. Source anchors: fpga/common/soc_top_common_ddr.sv:26-89; fpga/zu15eg/native_gmac_divided_clock.sv:35-56; src/main/scala/ip/bus/ClockDomainCrossing.scala:6-18; src/main/resources/inorder/ValenceI1BscanDebugPort.sv:37-61.

## Complete path index

| Rule | Source clock ¡ú destination clock | Source pin ¡ú reset endpoint |
|---|---|---|
| CDC-10 | mmcm_clkout0 ¡ú clk_out2_clk_wiz_common | `u_ddr/inst/div_clk_rst_r1_reg/C` ¡ú `phy_reset_pipe_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú clk_out2_clk_wiz_common | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/cmu/bridge/destinationResetSync/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú clk_out2_clk_wiz_common | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/uart/agent/release_0/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú clk_out2_clk_wiz_common | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/uart/bridge/destinationResetSync/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú clk_out2_clk_wiz_common | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/uart/gatedClock_gate/release_0/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú clk_out2_clk_wiz_common | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/uart/ingress/release_0/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú clk_out2_clk_wiz_common | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/uart/rawRelease/release_0_reg[0]/PRE` |
| CDC-10 | ref_source ¡ú clk_out2_clk_wiz_common | `network_clock/phase_reset_reg[2]/C` ¡ú `phy_reset_pipe_reg[0]/PRE` |
| CDC-10 | ref_source ¡ú mmcm_clkout0 | `network_clock/phase_reset_reg[2]/C` ¡ú `ui_reset_pipe_reg[0]/PRE` |
| CDC-10 | mmcm_clkout0 ¡ú phy_rx | `ui_reset_pipe_reg[2]/C` ¡ú `rx_reset_pipe_reg[0]/PRE` |
| CDC-10 | mmcm_clkout0 ¡ú phy_rx | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/gmac/physicalIngress/crossing/fifo/sourceRelease/release_0_reg[0]/PRE` |
| CDC-10 | mmcm_clkout0 ¡ú phy_rx | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/gmac/physicalIngress/sourceRelease/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú phy_rx | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/gmac/rawDiagnostics/mailbox/sourceRelease/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú phy_rx | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/gmac/rawDiagnostics/sourceRelease/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú phy_rx | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/gmac/rawRxRelease/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú phy_rx | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/gmac/rxClockWatchdog/sourceRelease/release_0_reg[0]/PRE` |
| CDC-11 | mmcm_clkout0 ¡ú phy_rx | `ui_reset_pipe_reg[2]/C` ¡ú `u_soc/peripherals/gmac/rxRate/destinationRelease/release_0_reg[0]/PRE` |
| CDC-10 | mmcm_clkout0 ¡ú ref_source | `u_ddr/inst/div_clk_rst_r1_reg/C` ¡ú `network_clock/phase_reset_reg[0]/PRE` |
| CDC-10 | mmcm_clkout0 ¡ú valence_bscan_tck | `ui_reset_pipe_reg[2]/C` ¡ú `u_debug/enabled.transport/raw_release_reg[0]/CLR` |
| CDC-10 | mmcm_clkout0 ¡ú valence_bscan_tck | `ui_reset_pipe_reg[2]/C` ¡ú `u_debug/enabled.transport/source_release_reg[0]/CLR` |
| CDC-10 | mmcm_clkout0 ¡ú valence_bscan_tck | `ui_reset_pipe_reg[2]/C` ¡ú `u_debug/enabled.transport/update_release_reg[0]/CLR` |

Raw query script is retained; first attempt failed only because report_cdc does not accept -force in2025.2; corrected read-only replay completed. Raw logs stay under out/reset-signoff-r2. Native process21650 is finished. No user files cleaned. Protect task-3 evidence.

Portable text reports normalize line endings/trailing whitespace only; original byte hashes and raw local output remain recorded.
