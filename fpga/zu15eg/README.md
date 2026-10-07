# ZU15EG 板级配置（VL100 100 MHz 与历史 Board40/DDR50 基线）

现用 Vivado 工程：`D:\TOOLS\projects\vivadoProjects\ZU15EG\ZU15EG.xpr`。
历史 Board40 RTL 在 `E:\VM\Share\Valence-rtl\board-40m`。
历史板级 top、ROM 初始化镜像、下载工具在工程的 `src\board40` 目录。
源代码维护在 WSL `/home/openion/Valence`；不是已删除的 Windows Valence 目录。

当前发布为 OpenIon Valence VL100 / Orbital-A1：RV64GC（F/D 开）、双发射、
CPU 100 MHz、UART 460800、完整 2 GiB DDR、原生 GMAC、CMU 和通用 DMA。
2026-10-06 r5 完成新 RTL 整板综合、布线及最终物理优化，已生成 bit。
整板 setup +0.003 ns / hold +0.003 ns / pulse +0.081 ns，MAC TX/RX setup
分别 +0.066/+0.161 ns；裕量薄，静态签核不代表真实板卡稳定性已验证。
发布目录 `E:\VM\Share\Valence-rtl\native-rv64gc-ddr2g-20261006-r5`，
方便烧录的副本和配套 Debian 固件在
`E:\VM\Share\Valence-rtl\firmware-debian13-vl100-2g-20261006-r1`。
详细内存、驱动、下载命令和板测步骤见 [VL100 Debian BSP](../../docs/vl100-debian-bsp.md)。
本页以下为历史配置，不要沿用其旧菜单、40/50 MHz 或 1.5 Mbaud 参数。

## DDR50 独立候选

DDR 版使用 `soc_top_ddr`，CPU 50 MHz、MIG 64-bit AXI，CPU 可见 DDR 为
`0x80200000..0xA01FFFFF` 共 512 MiB。工程在原 ZU15EG 目录的
`board-ddr50/ValenceDDR50.xpr`，RTL 在共享目录 `board-ddr50`，
资产在 `src/board-ddr50`。DDR 参数、时钟/复位、下载限制与验证范围见
[PL DDR4 集成说明](pl-ddr4-integration.md)。历史 DDR50 已生成 bit，但用户反馈下载头被拒绝；最新 FIFO UART DDR45/DDR50 候选见
[时序台账](../../docs/fpga-timing-windows.md)。下表仍描述原 UltraRAM 基线，不是最新 DDR 配置。

## 硬件

| 项目 | 配置 |
| --- | --- |
| FPGA | xczu15eg-ffvb1156-2-i |
| SoC 时钟 | clk_wiz_0，200 MHz 差分输入，40 MHz 输出 |
| ROM | 128 KiB，0x80000000–0x8001FFFF，blk_mem_gen_0 |
| ROM 接口 | Native Dual Port ROM，32768 × 32 位，两读端口，15 位字地址 |
| ROM 时序 | ENA/ENB，同一时钟，关闭 primitive/core 输出寄存器，1 周期读 |
| RAM | 1 MiB，0x80200000–0x802FFFFF，XPM_MEMORY_SDPRAM UltraRAM |
| RAM 时序 | 64 位数据，8 位字节写使能，3 周期读 |
| 串口 | 新版 RTL/ROM：主机 1,500,000、8N1、无流控；divisor=1 启用板级分数分频；旧 bitstream 仍为 115200 |

RAM 迁移是必要的：旧地址 0x80010000 与新的 128 KiB ROM 重叠。
TileLink/缓存/原子访问/地址译码均使用新的 RAM 基址，旧测试配置保留原默认值。
SoC 只需 `clock/reset/uartRx/uartTx` 四个端口；板级 top 保留原 XDC 引脚名字。
ROM 由 COE 初始化，不再用启动时的 case 表逐字写入。RAM 不带程序初值，由串口下载写入。

RAM 顶部 16 KiB 留给监控程序的全局变量、测试区和栈。
可下载文件上限是 **1008 KiB**；示例链接脚本另留 16 KiB 应用栈，代码/数据/BSS 上限 992 KiB。
这不是内存保护：运行在 M-mode 的测试程序应主动遵守该布局。

## 第一次上板

本次改动包含硬件和 bootrom，必须完整生成一次新 bitstream 并下载。
打开 ZU15EG.xpr，确认 top 为 `soc_top` 后正常运行综合、实现、Generate Bitstream。
不要运行旧的 `use_walker_queue_rtl.tcl` 或旧的 `refresh_board_monitor.py`，它们属于旧配置。
工程/IP 的旧配置备份在 `src\board40\previous-config-20260929`，旧板级 top 未删除。

串口菜单为 `r:RAM a:ALU t:TMR e:ECHO d:LOAD g:RUN`。
后续只更改 RAM 测试程序时，不需要重新综合或生成 bitstream。

关闭占用 COM 口的串口终端，在 Windows PowerShell 运行（COM5 换成实际端口）：

```powershell
cd D:\TOOLS\projects\vivadoProjects\ZU15EG\src\board40
python -m pip install pyserial
python uart_load.py COM5 sample_app.bin --baud 1500000 --run --console
```

工具自动发送下载命令、分块传输、校验并启动。示例输出 `RAM APP OK` 后回到菜单。
新波特率必须同时更新板级 RTL、bootrom COE 和 bitstream；当前已烧录的旧 bitstream 仍应使用
`--baud 115200`。OpenSBI/RTOS 镜像若仍把 UART 配成 divisor=22，启动后主机也要切回 115200，
或先将软件 UART 配置改为 1.5 Mbaud。
以上 divisor=22 只针对旧单字节 UART bit；新 FIFO UART 的参考时钟见 [UART 合同](../../docs/uart.md)，
不能继续沿用其旧分频解释。`--baud` 仅指定下载时的主机速率，不修改应用自己的 UART 配置。
`--console` 在交互式终端中双向转发 UART：显示板端输出，也立即发送键盘输入；无需再另开串口终端。
Ctrl-C 仅关闭主机终端，不会复位 CPU；若标准输入被重定向，则保持仅接收模式。
程序应链接到 0x80200000，下载平坦 `.bin` 而不是 ELF。程序死循环可按板上复位键恢复。
详细协议、应用启动代码和限制见源码 `fpga/firmware/README.md`；Windows 部署副本为 `FIRMWARE.md`。

## 源码构建

在 WSL 仓库根目录：

```sh
make fpga-board-firmware
make fpga-board-rtl FPGA_BOARD_OUT=/mnt/e/VM/Share/Valence-rtl/board-40m
make gsim-board-boot-test
```

第一条只编译固件和 RAM 示例。第二条导出硬件，不会运行 Vivado。
默认固件输出在 `build/fpga/firmware`。复制最新 COE/top/工具到工程 `src/board40` 后，
在 Vivado Tcl Console 执行：

```tcl
source D:/TOOLS/projects/vivadoProjects/ZU15EG/src/board40/configure_project.tcl
```

该脚本只配置文件引用、时钟/ROM IP 并生成 IP 输出文件，不启动整机综合或 bitstream。
50 MHz 候选需使用 `make fpga-board-rtl FPGA_BOARD_CLOCK_HZ=50000000` 重新生成固件/RTL，
并确认时钟 IP 当前输出为 50.000 MHz；脚本不带第四个参数时会保留现有时钟 IP 配置，
显式传入第四个 Tcl 参数 `50.000` 才会改动它。不要将 50 MHz 固件与 40 MHz 时钟混用。
它强制刷新 IP 输出，避免修改了同名 COE 后仍使用旧初始化内容。
固件代码改动才需要更新 ROM；普通 RAM 应用改动只需重新下载 `.bin`。

## 验证范围

只运行相关定向 GSIM，不跑全量测试。GSIM 使用相同 RAM 地址、容量、3 周期延迟，
但存储器采用通用模型；板级启动测试使用与新版 ROM 相同的 divisor=1 分数分频，不是 FPGA 时序签核。
另外运行 Vivado 独立 RAM 综合和整板 RTL elaboration，不运行耗时的整机实现。

2026-09-29 独立 RAM 综合：32/112 个 URAM（28.57%），2018 LUT，108 FF。
25 ns 约束下的综合估算内部 WNS=+21.397 ns；这是未布局布线、未约束模块外部 I/O 的结果，
**不能当作整颗 CPU 40 MHz 已通过的结论**。仍需本次完整板级实现后的 timing summary。
Vivado 对大深度 URAM 给出流水级数建议，若未来提高频率，应结合实际布线报告重新评估。

本次通过的功能检查（2026-09-29）：

- GSIM boot/download：2,006,849 周期，ROM 菜单、RAM 程序执行、CRC/越界拒绝、重传、
  同地址不同代码重复下载及 fence.i 可见性全部通过；ASan/UBSan 无报错。
- GSIM RAM：1/3 周期模型共 192 次请求、14 次预期边界错误，包含背压。
- GSIM ROM：128 KiB 末端 1/2/4/8 字节访问，120 次请求、60 次预期错误、720 次响应阻塞。
- 取指相关定向 GSIM/NEMU 回归、8 项 Python 下载协议测试通过。
- Vivado RAM 单模块综合和整板 RTL elaboration 通过；未运行整机实现或生成新 bitstream。

日志位于共享 RTL 目录的 `reports`，包括 `gsim_board_boot.log`、`gsim_board_rom.log`、
`ram_synth_utilization.rpt`、`ram_synth_timing.rpt` 及 Vivado 配置/检查日志。
