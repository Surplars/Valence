# ZU15EG PL DDR4 MIG integration contract

Status: 2026-10-01. The latest FIFO-UART profiles are DDR45 / 1.5 Mbaud and
DDR50 / 115200; see the current release/CDC record at the end.
The following early-DDR50 paragraph is historical. The independent DDR50 candidate wires the CPU's
coherent memory backend through a 64-bit TL/AXI burst bridge to `ddr4_0`.
Focused GSIM CPU/AXI tests pass. The retained, REGION-repaired, post-route
optimized checkpoint meets 50 MHz with WNS +0.001 ns / WHS +0.008 ns.
This is only 1 ps setup margin, not headroom for overclocking or a guarantee
for another implementation run. DDR PHY calibration/on-board operation is
not yet verified. A DDR50 bitstream with the prompt-free Bootrom V0.1 was
generated on 2026-09-30 at 22:13 (Asia/Shanghai); see the release record below.
It has not been programmed by this workflow. The last on-board validation
still refers to the earlier 1 MiB UltraRAM version.

## DDR50 candidate and software contract

- Project: `D:/TOOLS/projects/vivadoProjects/ZU15EG/board-ddr50/ValenceDDR50.xpr`.
- RTL: `E:/VM/Share/Valence-rtl/board-ddr50`; assets: original project `src/board-ddr50`.
- Top: `soc_top_ddr`, with the existing board clock/reset/UART/LED port names and
  `c0_ddr4_*` physical DDR signals. `board_ddr.xdc` reuses the original GPIO
  and clock package pins, with the MIG-generated DIFF_SSTL12 clock standard.
  `pl_ddr4_pins.xdc` assigns all 71 DDR signals plus the oscillator N pin;
  it excludes the vendor ILA constraints.
- MIG: `LY-075`, x32, one rank, DDR tCK=1000 ps (2000 MT/s), input=200 MHz,
  AXI data=64, address=31 and ID=4. The candidate explicitly sets AXI width=64,
  because changing the part in the GUI restored the original IP's default 256.
- Clocking: the oscillator goes only to MIG; MIG `ui_clk`=250 MHz drives
  `clk_wiz_ddr` with No Buffer input to generate the CPU's 50 MHz clock.
  `axi_clock_converter_ddr` uses asynchronous conversion, 64-bit data,
  32-bit addresses and 4-bit IDs. The 512 MiB offset fits MIG's 31-bit address.
- CPU RAM: **0x80200000..0xA01FFFFF, 512 MiB**, backed by the first 512 MiB
  of the physical 2 GiB DDR channel. The AXI bridge subtracts 0x80200000.
  The DDR profile instantiates no large on-chip RAM. ROM/MMIO remain unchanged.
- I-cache, write-back L1, coherence home, DMA/atomic serialization, and the
  page-table path remain above the TL/AXI boundary. The AXI endpoint is ordinary
  Get/Put memory; LR/SC and AMO are resolved by the existing single-hart logic.
- Reset is asserted asynchronously and released synchronously in each clock
  domain. Both domains reset on either board reset button. CPU/AXI remain
  held until calibration and the CPU clock lock succeed; LED indicates release.
- DDR ROM monitor globals, receive buffer and stack reserve **0xA01FC000..0xA01FFFFF**
  (the final 16 KiB of the 512 MiB aperture). Download limit is **0x1FFFC000 =
  536854528 bytes**, with load base 0x80200000. Use host `--memory ddr`.
  The default UltraRAM firmware/host profile retains its 1008 KiB limit.
  The DDR sample reserves a further 16 KiB for its own stack below the monitor.
  This requires the new ROM COE in the FPGA bitstream, not only a Python update.
- For the historical DDR50 / 1.5 Mbaud profile, software must set `mtime`/DTB
  timebase to **50,000,000 Hz** and UART to **1,500,000 baud**.
  The new DDR45/DDR50 FIFO profiles have different clock/baud contracts; see below. Previously built 40 MHz OpenSBI/RTOS images have not been
  rebuilt or revalidated for this candidate.

Build with `make fpga-board-ddr-rtl`; verify with
`GSIM_CXX=clang++-19 make gsim-board-ddr-test`. Candidate creation is handled
by `prepare_ddr_project.tcl`; it generates IP products and checks RTL ports
using freshly generated vendor .veo declarations, without full CPU/IP
synthesis, implementation, timing closure or PHY simulation.

Validated results: Scala checks and the original UltraRAM boot regression pass.
After the loader expansion, DDR GSIM passes in 6,421,378 cycles, covering
1135 read bursts, 592 write bursts and 1482 stalls. This includes acceptance
of >1 MiB and maximum-size image headers followed by clean frame aborts;
it does not stream a full 512 MiB image in GSIM. Host protocol tests complete
a >1 MiB transfer including CRC retry, and check exact upper bounds without
allocating 512 MiB. The default UltraRAM regression passes in 952,063 cycles.
All 10 firmware host tests pass. Vivado checks freshly generated vendor port declarations
and all 71 DDR pin assignments; this is not physical MIG implementation validation.

The focused test covers calibration hold, serial CRC/retry/bounds, RAM execution,
rewritten-code fence.i, byte/half/word stores, high/middle/end-of-aperture accesses,
LR/SC and AMO. Its independent sparse AXI model adds response latency and
backpressure. The original UltraRAM boot regression and Scala checks also pass.
This does not replace MIG electrical/pin validation or real on-board memory tests.

## 2026-09-30 full implementation and timing result

One full synthesis/place/route attempt was followed by a checkpoint ECO and
post-route physical optimization; no CPU pipeline stage or architectural
latency was added. Do not confuse synthesis/place estimates with routed timing:

| Stage | Setup WNS (ns) | Hold WHS (ns) | Status |
| --- | ---: | ---: | --- |
| Synthesis, estimated wires | +0.433 | -0.464 | Not signoff |
| Post-place estimate | +0.506 | — | Not signoff |
| REGION-repaired, fully routed | -0.597 | +0.005 | 50 MHz fails; TNS -1403.147 ns |
| Post-route Explore, retained | **+0.001** | **+0.008** | Setup/hold TNS=0; 0 failing endpoints |

The initial route failed because eight AXI Clock Converter AWREGION/ARREGION
inputs were not driven. The top source now explicitly drives both fields to
zero. The same eight pins were connected to GROUND in the retained checkpoint,
then incrementally routed and audited. All 161,529 routable nets are routed;
route errors=0. The original `impl_1` status still records that failed run;
the repaired result is a separate checkpoint, not a fabricated successful
project-run status. Fresh synthesis of the corrected source may place differently.

Final artifacts under
`D:/TOOLS/projects/vivadoProjects/ZU15EG/src/board-ddr50/timing50-repair/`:

- `optimized_routed.dcp`: retained result for subsequent bitstream generation;
  **no bitstream has been generated or programmed for this profile**.
- `optimized_timing.rpt`, `cpu_paths.rpt`, `mig_ui_paths.rpt`.
- `optimized_route_status.rpt`, `utilization.rpt`, `drc.rpt`.
- `cdc.rpt`, `clock_interaction.rpt`, `bus_skew.rpt`,
  `check_timing.rpt`, `region_tieoff_audit.txt`.

The CPU domain is 50 MHz; MIG UI is 250 MHz with WNS +0.307 ns.
The pre-optimization routed critical path was loadBeat -> load replay /
recovery -> frontend/rename -> backend queue enable. After optimization, the
worst path is backend `queue_2_renamed_token_tag_reg[29]` to predictor
`counters_16_reg[1]` (19.848 ns data delay, 56 logic levels). The next paths
include data translation/PMP -> LSU with only +0.005 ns slack. Future margin
work should target these control boundaries, not blindly pipeline MIG.

Resources: 132,002 LUTs (38.68% of 341,280), 78,124 FFs, 62 RAMB36 + 1 RAMB18,
22 DSPs, 0 URAMs. Routing reported local congestion level 6 before convergence.
Post-route optimization preserves CPU cycle semantics; DDR versus UltraRAM
throughput still needs an actual workload measurement.

Checks: no missing clocks or unconstrained internal endpoints; 14/14 bus-skew
constraints pass (minimum slack +3.934 ns). All crossings analyzed by
`report_cdc` are Safe; this is not a full external asynchronous-I/O proof.
No DRC errors/critical warnings, but DSP pipelining advice, three generated
debug-hub LUT-equation warnings and one unused-load warning remain.
Input-delay warnings remain for button_n, sys_rst_n, uart_rxd; output-delay
warnings remain for c0_ddr4_reset_n, led, uart_txd. These asynchronous/control
interfaces have no board-level synchronous I/O timing contract here; the
internal STA result does not substitute for their electrical/board validation.

Scripts are kept beside the board sources: `run_ddr50_timing.tcl` for an
initial full run (does not reset existing runs), `repair_ddr50_route.tcl`
for this specific eight-pin checkpoint ECO plus post-route Explore, and
`signoff_ddr50.tcl` for bus-skew/clock/REGION checks. The ECO follows
[AMD's netlist connection flow](https://docs.amd.com/r/2021.1-English/ug835-vivado-tcl-commands/connect_net)
and [post-route physical optimization](https://docs.amd.com/r/2023.2-English/ug904-vivado-implementation/phys_opt_design).
Keep the ROM-monitor 16 KiB reservation and rebuild 50 MHz software before
attempting OpenSBI/Linux on the real DDR board.

## DDR serial downloads

```powershell
python .\uart_load.py COM4 .\image.bin --memory ddr --baud 1500000 --run --console
```

The file is still a contiguous flat binary based at 0x80200000; this change
does not add ELF loading, arbitrary segment addresses, or automatic Linux/DTB
handoff. Rebuild OpenSBI and the OS for the DDR memory map and 50 MHz timer.
Keep the monitor region reserved (including in a future Linux DTB); apps
are responsible for their stack/BSS and must not overwrite the monitor if
return-to-monitor is required. The current handoff is M-mode, a0=a1=0.

The final RAM CRC budget scales as max(30 s, image_bytes / 16384), and can
be overridden with `--verify-timeout SECONDS`. Per-block acknowledgement,
retry, image CRC and RAM readback are unchanged. At 1.5 Mbaud, UART 8N1 has
a theoretical ceiling of 150 kB/s before framing/ACK/firmware costs; large
Linux images still take minutes. A block device is not required for an
initramfs experiment, but DDR alone does not establish Linux boot support.

## Physical interface and IP choice

The `XCZU15EG_CORE+V1.0` schematic has two separate DDR4 groups. PS DDR4 is
connected to PS Bank 504. The requested PL DDR4 uses two Micron
`MT40A512M16LY-062E` x16 devices (U8/U11) on FPGA Banks 64/65, forming one
x32, one-rank, nominal 2 GiB channel. Address/command/clock are shared;
`DQ[31:0]`, `DQS[3:0]`, and `DM[3:0]` are split across the two devices.
The board-level pin mapping must come from the schematic/vendor XDC and pass
Vivado MIG pin validation; do not substitute the PS DDR pins.

Generate Vivado **DDR4 SDRAM (MIG), Controller + PHY**, Components, x32 from
two x16 devices, one rank, AXI4 Slave interface, no ECC for the first test.
Do not choose PHY Only: it provides no DRAM command scheduler, refresh, or
protocol/timing checking. If the exact Micron suffix is absent, use Vivado's
supported equivalent only after comparing the device datasheet/timing values.
Micron lists the installed `MT40A512M16LY-062E` as a 3200 MT/s, CL22 speed
grade and the selectable `MT40A512M16LY-075` as 2666 MT/s, CL19. Both are
8 Gb x16, 1.2 V, 96-ball LY parts. The -075 profile is a reasonable initial
bring-up candidate **only at a MIG-selected DDR4 rate within that profile**;
do not request 3200 MT/s with it. Verify the actual -062E revision's supported
CL/CWL and all timing/refresh parameters against its datasheet, then validate
MIG calibration and memory traffic on the board. A matching custom-parts
profile is preferable for exact part support; faster-part substitution alone
is not a guarantee of calibrated operation.
Keep the generated `.xci`, pin constraints, and example design with the
ZU15EG project. Select the system/reference clock and memory data rate only
after checking the actual oscillator routing and MIG pin planner; the SoC's
40/50 MHz CPU clock is not the DDR4 memory clock.

## Initial `ddr4_0` audit before DDR50 integration (historical)

The initial XCI was MIG v2.2, Complete Memory Controller, `-075` part,
x32, no ECC, AXI4 slave, DDR `tCK=1000 ps` (2000 MT/s), 256-bit AXI data,
31-bit AXI address and 4-bit AXI ID. The 2 GiB address space is consistent
with two 8 Gb x16 chips. The AXI narrow-burst option is disabled.

The initial audit identified two board-level issues; the DDR50 candidate now
corrects the input frequency and adds the extracted physical pin map:

1. `C0.DDR4_InputClockPeriod=14000 ps` means the MIG expects a 71.4 MHz
   differential input, whereas the board's `PL_CLK0_P/N` oscillator and
   `clk_wiz_0` input are 200 MHz. Reconfigure MIG for an input period of
   5000 ps if Vivado validates it at the selected DDR data rate; otherwise
   choose another validated DDR rate/M,D combination. Both IPs share the
   *same physical input pair*. Follow PG150's shared-clock/No Buffer wrapper
   guidance rather than assigning two independent input buffers to one pair.
2. Neither the project `board.xdc` nor generated `ddr4_0/par/ddr4_0.xdc`
   currently contains `PACKAGE_PIN` assignments for the PL DDR interface.
   Obtain or derive the exact board pin map, apply it through MIG I/O planning,
   and pass MIG pin validation. Generic IOSTANDARD constraints are not a pin
   map.

The initial 256-bit MIG port could not directly accept the 64-bit SoC port.
DDR50 selects a 64-bit MIG AXI port, with MIG's internal upsizer, and retains
an external AXI clock converter. It does not need an external width converter.

## Vendor 10_DDR4_TEST audit

The vendor's `ddr4_test.srcs/constrs_1/new/pin.xdc` maps 66 DDR4
signals. All 66 entries match the `PL DDR4` sheet of the supplied
`XCZU15EG-F V1.0` pin-definition workbook. A clean copy is kept in
`pl_ddr4_pins.xdc`; a machine comparison found 66/66 exact matches
against the vendor XDC. It excludes the vendor's ILA/debug constraints,
the reset F16 already mapped in `board.xdc`, and the shared PL_CLK0
AL8/AL7 clock pair. Five differential negative DDR pins from the workbook
and the oscillator negative mate are now assigned explicitly. DDR4 uses RAS_n/A16 on AP11 and WE_n/A14
on AJ9, so the vendor XDC matches the schematic and AMD's DDR4
pin definitions. Do not swap `adr[14]` and `adr[16]` based on
the RAS/WE name order. MIG owns the
DDR I/O standards. Do not add this XDC until the board top exposes
the named `c0_ddr4_*` ports.

The vendor XCI is **not** a drop-in replacement for `ddr4_0`:
it uses the native application interface (`AxiSelection=false`),
`MT40A512M16HA-083E`, `tCK=833 ps` (~2400 MT/s), and a
4997 ps (~200 MHz) input clock. The installed devices are `LY-062E`,
while the Valence XCI is AXI4 with `LY-075` at 2000 MT/s.
Keep Valence's AXI interface, but reconfigure its invalid-for-this-board
14000 ps input period to a Vivado-accepted ~5000 ps combination and
verify the selected memory part/timings by MIG validation and on-board
calibration. The 200 MHz PL_CLK0 pair is already used by `clk_wiz_0`:
follow PG150's shared-clock/no-buffer guidance before connecting MIG
and the clock wizard to the same physical oscillator.

## Integration boundary

- The MIG AXI port runs on `ui_clk`, with `ui_clk_sync_rst`; the 40/50 MHz
  CPU AXI master needs an AXI clock converter unless both are deliberately
  clocked from `ui_clk`. Hold DDR traffic until the MIG calibration succeeds.
- `TileLinkAxi4BurstBridge` currently exports a 64-bit AXI4 master with
  at most 16 beats per burst. If the generated MIG AXI data width differs,
  insert SmartConnect or an AXI width converter; do not wire unequal widths
  directly. Preserve AXI address, ID, WSTRB, response, and reset semantics.
- DDR50 uses this bridge as the CPU main-memory path after coherence/atomics.
  The default Board40 profile remains on-chip 1 MiB RAM. The DDR profile's
  decode/cache/atomic/page-table ranges are 512 MiB. The DDR ROM loader now
  reserves only the final 16 KiB; small applications retain their load addresses.
  Real DDR correctness and calibration remain board gates. The retained
  optimized checkpoint meets 50 MHz static timing with only 1 ps setup margin.

Bring-up gates: (1) MIG example design calibrates on board; (2) AXI memory
walk and random read/write/byte-mask tests pass across a useful address range;
(3) CPU data/fetch/page-table/atomic traffic uses DDR under GSIM and board
tests; (4) only then place OpenSBI, DTB and a Linux Image/initramfs in DDR.

References: AMD PG150 DDR4 SDRAM/AXI4 interface and the supplied core-board
schematic pages 5, 8, 16-17. The page-8 PS DDR wiring is a different channel.

## 2026-09-30 Bootrom V0.1 firmware-only update (historical intermediate)

The exported `src/board-ddr50/bootrom.coe` and `bootrom.bin` now contain
Valence Bootrom V0.1 (3069 ROM bytes, previously 3589). It prints
`Valence Bootrom V0.1`, `download mode (UART)`, and on launch
`boot from UART (DDR) @ 0x0000000080200000` (or the selected entry).
RAM/ALU/timer/echo tests and their menu were removed; diagnostics belong in
downloaded programs. VLD1, d/g commands, readiness prompt, CRC/range protection,
memory reservations and M-mode handoff remain compatible. No auto-run occurs
on reset or on download without an explicit g / host --run.

Focused verification after this change:
- 10 host protocol tests pass.
- UltraRAM boot GSIM: 906327 cycles, 804 UART bytes, ROM 3069 bytes.
- DDR boot GSIM: 6349373 cycles, 964 UART bytes, 1098 read bursts,
  554 write bursts and 1395 stalls.
- Both check the exact version/status output, retired commands ignored,
  download retry/CRC/bounds, unverified jump rejection, program execution/return
  and rewritten-code fence.i. DDR additionally covers the large-image header
  bounds and clean abort path. This is not an on-board DDR calibration result.

No Vivado run or bitstream generation was performed for this firmware change.
The retained `timing50-repair/optimized_routed.dcp` and its +0.001 ns timing
result still correspond to the earlier ROM contents. Do not generate a bit
directly from that checkpoint expecting the V0.1 banner. Refresh the ROM IP
initialization/output products and dependent synthesis/implementation before
creating the updated bitstream, then check timing again. The exported COE path
is unchanged; changing the COE file alone does not update an existing DCP/bit.

## 2026-09-30 prompt-free Bootrom V0.1 DDR50 bitstream

Release directory:
`D:/TOOLS/projects/vivadoProjects/ZU15EG/src/board-ddr50/bootrom-v01-noprompt/release`.

- `valence_ddr50_bootrom_v01.bit`: 28,700,913 bytes, generated at 22:13 Asia/Shanghai.
- `valence_ddr50_bootrom_v01.ltx`: matching debug probes.
- `bootrom_updated_routed.dcp`: fully routed checkpoint with the new ROM contents.
- `timing_summary.rpt`, `timing_paths.rpt`, `bus_skew.rpt`, `check_timing.rpt`,
  `route_status.rpt`, `bitstream_drc.rpt`, `rom_init_audit.txt`: release checks.

The ROM is now 3061 bytes. No `>` prompt is emitted. Reset prints only
`Valence Bootrom V0.1` and `download mode (UART)`. A verified download
ends with `ready to boot\r\n`; use the updated `src/board-ddr50/uart_load.py`,
which recognizes this complete line and remains compatible with legacy prompts.
An old host script that waits only for `> ` will time out on this bitstream.

The ROM IP was synthesized in isolation using the same configuration and
Vivado version. Its full primitive set, non-memory properties, pin/net graph
and top-level ports matched the old ROM IP. All 32768 generated MIF words
matched the new binary including zero padding. The routed ROM's old INIT
values matched the old IP, then 82 INIT properties were updated across the
existing 29 BRAMs. All 4176 INIT/INITP properties were read back against the
new IP. CPU logic, placement, routing, clock constraints and project XDC
results were preserved. This was not a new full CPU implementation run.

Fresh checks on the updated design: WNS **+0.001 ns**, WHS **+0.008 ns**,
WPWS **+0.081 ns**; setup/hold/pulse-width total negative slack and failing
endpoints all zero. CPU clock period 20 ns (50 MHz); all 161529 routable nets
fully routed, routing errors zero; all 14 bus-skew checks pass. No unclocked
or unconstrained internal endpoints. Bitstream DRC has zero errors/critical
warnings and 63 existing ordinary warnings (DSP pipelining, debug LUT terms,
unused loads). Asynchronous/control I/O delay omissions remain as previously
documented; this is not on-board electrical validation. The 1 ps setup margin
is narrow and does not imply overclocking headroom.

Validation: 12 host protocol tests pass, including status-line completion and
legacy prompt compatibility. Focused DDR GSIM passes in **6339996 cycles**
(936 UART bytes; 1098 read bursts, 554 write bursts, 1378 stalls). It checks
download CRC/retry/bounds, no unverified jump, program execution/return,
rewritten-code fence.i and old test commands ignored. No full GSIM suite run.

The update flow is recorded in `build_bootrom_ip.tcl` (one-off isolated IP
build used for this release) and `update_bootrom_bit.tcl` (guarded INIT-only ECO
and timing/DRC-gated bit generation). The original
`timing50-repair/optimized_routed.dcp` is unchanged and still has the old ROM.
The main candidate project's previous run status/output products were not
silently relabelled: select the release bit above explicitly. A future project
rebuild must regenerate the ROM IP output products from the updated COE.

UART remains **1500000 baud, 8N1**, no flow control. Example after programming:

```powershell
python uart_load.py COM4 sample_app.bin --memory ddr --baud 1500000 --run --console
```

MIG calibration and actual DDR operation still require board testing. The CPU
is held in reset until DDR calibration and clock lock; no banner before this
gate does not alone prove the ROM or UART is faulty. No programming or flash
write was performed by this workflow.

## SoC 分区迭代：复用综合好的 CPU 与 DDR/IP

优化 CPU 时使用独立批处理，输出放在一个新的候选根目录，
不打开/覆盖旧 GUI 工程、不修改输入 DCP、不自动烧录：

1. `synth_soc_partition.tcl RTL_DIR ROM_DCP OUT_DIR PERIOD_NS`：
   仅综合 BoardSocTop，保存 `soc_blackbox.dcp` 以便工具兼容问题可恢复而无需重综合。
   导出实际 BMG ROM 的结构网表，用 `update_design -from_file` 接入
   （本机 Vivado 2025.1 的 `read_checkpoint -cell` 报 Project 1-9）。
   输出 `soc_candidate.dcp` / `soc_candidate.edf`，真实 native 端口来自同目录 .veo。
   用 OOC clock 筛选，保存候选前仅在该独立 SoC 内执行
   [AMD reset_timing](https://docs.amd.com/r/2020.2-English/ug835-vivado-tcl-commands/reset_timing)
   清除临时约束；不能对已布线整机执行这个动作。
2. `assemble_soc_candidate.tcl SOC_DCP IP_SOURCE_DIR TOP_SV BOARD_XDC DDR_PIN_XDC OUT_DIR`：
   在新内存工程中只综合顶层连接，SoC 用已有 DCP，
   MIG/Clock Wizard/AXI CDC 从原来的 .xci 读取已有综合结果与约束。
   必须通过 .xci 加载，而非只添加 IP DCP，否则会缺 MIG 子 IP / 时钟 / CDC XDC。
   MIG 校准 ELF 初始化仍由 IP 流程加载。
   按正常 [AMD 调试核流程](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/implement_debug_core)，
   自动 dbg_hub 在 opt_design 前可以暂为黑盒，opt_design 后必须无黑盒。
   核对真实 CPU 20 ns 后整机 opt/place/route/phys_opt，
   输出 assembled / placed / routed DCP 和整机报告。
3. `release_soc_partition.tcl SOC_DCP ROUTED_DCP OUT_DIR CPU_HZ UART_BAUD EXPECTED_ROM_DCP EXPECTED_ROM_BIN`：
   独立读回候选与实现中的全部 4176 个 ROM INIT/INITP 值；
   setup/hold/pulse width、失败端点、14 项 bus skew、完整布线、
   bitstream DRC、内部时序覆盖、真实 MMCM CPU50MHz / MIG UI250MHz、
   8 个 REGION 接零和 UART 两级 ASYNC_REG 全通过后才输出
   `valence_ddr50_early_issue.bit`。CPU_HZ 默认 50000000；其他频率须提供真实
   MMCM 派生时钟，输出名随整数 MHz 改变，不会以参数伪造时钟。

每个 OUT_DIR 必须属于同一份未改变的 RTL：综合脚本可复用该目录内已经存在的
soc_blackbox.dcp，新 RTL 版本一定换新目录，不能在旧目录中覆盖源文件再“恢复”。

2026-10-01 实测不能直接对旧 routed DCP 黑盒化/替换 u_soc：
物理优化跨层移动了逻辑，替换接口多出 1694 个内部端口（并有已裁剪的 AXI bus）。
因此撤下该候选 ECO 脚本，改为上面的新顶层拼接；没有猜测这些内部端口的接线，
也没有把失败的旧边界修改写回输入 DCP。
这复用的是不变的综合分区和 IP，**整机布局布线仍须重做**。
原 200 MHz 输入、CPU 50 MHz、MIG UI 250 MHz、DDR 管脚与 IP CDC 约束均保留。

## 2026-10-01：独立 DDR45 对照（尚未发布 bit）

主 GUI `ZU15EG.xpr` 的 `clk_wiz_0`（200 MHz 输入）不控制本流程的 DDR CPU 时钟。
DDR 使用 MIG UI 250 MHz 输入的 `clk_wiz_ddr`；改变 CPU 频率时还须按相同
CPU_HZ 导出 UART 和重编 BootROM / 定时软件。本轮没有修改原工程或覆盖旧 bit。

`E:/VM/Share/Valence-rtl/ddr45-compare-20261001` 已包含 45 MHz RTL、
`firmware/ddr_test.bin`（6064 bytes）和 `eco/routed.dcp` / 完整报告。
97 个 SV 与 DDR50 对照仅 UART 的分频常量不同；ROM 和 DDR 测试程序 CPU_HZ
均为 45000000。原 CPU/DDRsynth 分区复用，MIG 时钟/型号/引脚不变。

CPU setup WNS +2.489 ns，但整机仍有三级复位同步 PRE 的 recovery/removal
违例：全局 WNS -2.011 ns、WHS -0.114 ns，各 3 个失败端点。
因此**没有 DDR45 release bit**，不能把 `eco/routed.dcp` 直接当作已签核产物。
后续需审查异步置位、同步释放复位入口及其约束，而不是放宽 CPU 数据时序。
详细路径、保留布局检查和必要 GSIM 证据见
[Windows 时序记录](../../docs/fpga-timing-windows.md#2026-10-0145-mhz-降频对照与-uart-连续接收)。

连续 8N1 定向 GSIM 在 45/50 MHz 均通过，仍不能替代实体 UART 下载验证。
本节是 FIFO 升级前的历史记录；当前 FIFO/超时/中断升级与复位链修正见下节。

## 2026-10-01：FIFO UART 小分区迭代与复位合同

两版均保留 early-issue CPU、512 MiB DDR 窗口、MIG 型号/引脚/250 MHz UI、
128 KiB ROM，UART 具有 16 字节 RX/TX FIFO、16x 中心三点多数采样、
可编程 5–8 数据位/校验/停止位、RX 超时/错误中断；不是完整 16550 芯片认证。
BootROM 的 FCR 变为 7，默认 divisor=1；VLD1 下载协议与 MMIO/IRQ 地址不变。

| 配置 | CPU/mtime Hz | UART baud | UART reference Hz |
| --- | ---: | ---: | ---: |
| DDR45 FIFO | 45000000 | 1500000 | 24000000 |
| DDR50 FIFO | 50000000 | 115200 | 1843200 |

应用/DTB 的 UART clock-frequency 是上表 reference，不是 CPU_HZ。
旧软件 divisor=22 不能按旧 bit 的 115200 解释。主机 `--baud` 不修改应用初始化。

使用新目录生成，避免复用不匹配的固件/分区缓存：

```sh
make fpga-board-ddr-rtl FPGA_DDR_CLOCK_HZ=45000000 FPGA_DDR_UART_BAUD=1500000 FPGA_DDR_OUT=build/fpga/ddr45-fifo-new FPGA_DDR_FIRMWARE_OUT=build/fpga/ddr45-fifo-new/firmware
make fpga-board-ddr-rtl FPGA_DDR_CLOCK_HZ=50000000 FPGA_DDR_UART_BAUD=115200 FPGA_DDR_OUT=build/fpga/ddr50-fifo-new FPGA_DDR_FIRMWARE_OUT=build/fpga/ddr50-fifo-new/firmware
```

本轮 97 个 SoC SV 与已签核 early-issue 基线比较：96 个相同，
仅 UartConsole 改动。没有重综合 CPU、没有增加 CPU 流水级。
只有以下**明确审计过的旧基线/边界**可以使用局部 ECO；CPU 或其他 RTL 改动后，
应回到 synth_soc_partition + assemble_soc_candidate 流程，不能套用该 ECO。

1. `build_uart_partitions.tcl RTL_DIR COE OUT_DIR CPU_HZ`：
   独立生成 Clock Wizard 和 ROM IP、综合 native UART 与严格 215 端口物理 wrapper。
   仅支持 45/50 MHz；每版必须独立 OUT_DIR，不能改变源码后复用旧缓存。
2. `replace_uart_candidate.tcl OLD_SOC_DCP OLD_ROM_DCP ROUTED_DCP PARTITION_DIR OUT_DIR CPU_HZ`：
   核对新旧 ROM 原语/端口/非 INIT 参数/连线；按实际 Clock Wizard 参数修改 MMCM，
   更新 ROM、严格替换 UART。context-pruned size[2] 只在验证 CoreRegisterRouter
   零扩展 RTL 后恢复 GND。逐项检查 UART 外 274284 个原有 LOC/BEL 不变。
3. `repair_uart_hold.tcl INPUT_ROUTED_DCP OUT_DIR`：
   验证每条负 hold 路径的驱动/负载只属于 UART，解开该网络后用 Default
   `route_design -preserve` 修复短路径。不能组合 Explore 与 preserve；
   Quick routing 不做足够的 hold 优化。保持所有原有 LOC/BEL，不增加功能延迟。
4. `repair_reset_gate.tcl INPUT_ROUTED_DCP OUT_DIR`：
   CPU 的原组合 reset_request 改为直接来自 UI 复位链末级；
   clock unlock 与 board/UI reset/calibration 一起在 UI 链入口限定。
   独立核对旧 64 项真值表、新 LUT2 的 4 项真值表、所有输入驱动和 PRE 负载；
   只暂时解除审计过的复位网络/六个 FF 的 DONT_TOUCH，跨层 locked 连接使用
   `connect_net -hier`。同步链 ASYNC_REG 和原有布局必须恢复/核对。
   消除组合跨域复位路径，不通过 CDC waiver 隐藏问题。
5. `release_soc_partition.tcl SOC_DCP ROUTED_DCP OUT_DIR CPU_HZ UART_BAUD EXPECTED_ROM_DCP EXPECTED_ROM_BIN`：
   核对真实 CPU/MMCM 与 UI 时钟、全部 4176 ROM INIT、两条三阶段复位链、
   直连 CPU PRE、UART 同步链、setup/hold/PWS、14 bus skew、完整布线与 DRC；
   CDC 已分析路径 unsafe/unknown/缺 ASYNC_REG 和 Critical 必须全部为 0，
   才生成 `valence_ddr45_uart1500000_fifo.bit` 或
   `valence_ddr50_uart115200_fifo.bit`。

`board_ddr.xdc` 只对经过完整结构审计的六个同步器 PRE 入口添加异步复位例外。
UI/CPU 链 Q→D、真实同步 CPU 数据、AXI CDC 与原 IP 约束仍保留。
这是异步置位/同步释放合同，不是放宽 CPU 数据周期。
参考 [AMD 异步复位同步器](https://docs.amd.com/r/2025.1-English/ug906-vivado-design-analysis/Asynchronous-Reset-Synchronizer)；
普通串口/按钮等没有同步 I/O delay，仍需独立物理验收。

本轮必要 GSIM 的两组连续 8N1 下载/CRC/DDR 执行与独立 UART
FIFO/帧格式检查通过，详见 [UART](../../docs/uart.md) 与
[最终时序/bit 台账](../../docs/fpga-timing-windows.md)。
脚本可复用已验证分区，不修改旧工程，不自动烧录。

## 2026-10-01 双发射 2-way BootROM 回退修复

`ddr-opt-20261001/release-2way` 的 CPU/L1 已获用户 DDR 板测反馈，但该构建
从原工程缓存 DCP 引入旧 ROM。原发布只核对 candidate==bit，漏掉了固件新鲜度。
`release_soc_partition.tcl` 现在必须显式指定期望 ROM DCP 与 BIN：
`audit_bootrom.py` 对照全部32768 MIF字、padding、V0.1身份及DCP时间；
再在Vivado比较期望IP、SoC候选、routed设计全部4176 INIT/INITP。
使用旧candidate的真实负测试被拒绝，没有生成bit。Vivado调用Python使用`-I`，
避免其PYTHONHOME/PYTHONPATH污染外部解释器。只证明构建来源/一致性，不是安全启动。

恢复原ROM参考可用`extract_rom_checkpoint.tcl SOC_DCP OUTPUT_ROM_DCP`。
`update_bootrom_bit.tcl OLD_ROM_DCP NEW_ROM_DCP ROUTED_DCP OUTPUT_DIR prepare-only SOC_DCP`
严格验证IP拓扑/非INIT参数/端口，先检查所有旧值，再修改路由与逻辑候选的INIT；
最后必须用正常release重新检查时序、reset/CDC、DRC、bus-skew和固件来源。
本轮只改83个INIT属性，原布局/布线不变，不跑整机实现。

最新3061B BIN SHA256 `987FA3687E82620B8A708E03B93791D8F3A2AE181BFFAAF3FE533174A744E1F2`。
新bit在`E:/VM/Share/Valence-rtl/ddr-opt-20261001/bootrom-fix/release`，
WNS +0.163ns/WHS +0.011ns/WPWS +0.081ns，14 bus-skew/CDC/DRC/route全签核。
该bit保持原双发射2-way CPU，不包含后续回放重构。旧bit未覆盖，代理未烧录。
重启应仅输出`Valence Bootrom V0.1`、`download mode (UART)`，无菜单或`>`。

## 时钟域策略

CPU/SoC 50MHz与MIG UI 250MHz已通过异步AXI转换器连接，并非尚未引入多时钟域。
CPU时钟由UI经MMCM派生；两域复位异步断言、各自同步释放。当前不拆CPU流水为异步域，
内部时序继续通过明确的流水/信用边界优化。详见 [时钟域计划](clock-domain-plan.md)。
