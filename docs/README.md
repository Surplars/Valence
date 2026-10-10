# Valence 文档导航

最新 `dev` 源码交付及限制见 [2026-10-08 交付记录](dev-delivery-20261008.md)。
本轮 Vivado 物理验证仍待完成，当前候选没有新的物理时序签核。

独立 [FPGA-next 配置与证据](../fpga/next/README.md) 提供 Selected v2 构建入口、逐模块升级和未完成的物理验收边界。

本目录同时保存当前软件合同、模块设计和阶段验收记录。网络入口局部核对：2026-10-04；
下方早期 Board40 配置表保留历史口径，当前 DDR/100 MHz 状态查 datasheet 与对应验收。
当前开发对象是 `core/ooo` 乱序核；GSIM 是唯一受支持的硬件仿真后端。
日期化数据和“初始 / 实现前 / 本轮”章节保留当时的配置与结论，不自动代表当前板级状态。

2026-10-08 dot 交接已接入 WSL `fix/dot-handoff-20261008`，保留 `main`；当前 32+32KiB、
LVT PRF、MSHR2/并行写回/预取/posted TX4 候选及短验证结果查
[接续与性能记录](performance-status.md)。该候选没有新板级时序签核或 bit，勿复用旧版签核。

2026-10-07 已完成当前/历史源码的物理分离，目录与构建入口见 [layout](layout.md)，
build 历史证据归档、恢复方法与提交检查见 [工程整理清单](repository-maintenance.md)。
下面的 Board40 表仅描述早期实验；最新 r6 为 RV64GC、双发射、100 MHz、460800 baud、完整 2 GiB DDR，
已生成静态时序通过的 bit，但工程裕量不足且该 bit 的板级复测待完成。

## 软件适配入口

建议按“选配置 → 查地址与寄存器 → 配置启动与 OS”阅读：

| 文档 | 用途 |
| --- | --- |
| [VL100 Debian BSP](vl100-debian-bsp.md) | OpenIon/Orbital-A1身份、完整2GiB、自动驱动、CMU/DMA测速及新bit前提 |
| [SoC datasheet](soc-datasheet.md) | 配置、CPU 能力、内存图、时钟和已验证边界 |
| [MMIO 寄存器手册](soc-registers.md) | UART、定时器、DMA、APLIC/IMSIC 的访问合同和中断路由 |
| [受管 UART / GMAC](managed-peripherals.md) | 可选生产连接、CMU叶子钟、排空/唤醒、模块时序与上板边界 |
| [OS 与软件移植指南](os-software-porting.md) | 启动 ABI、链接布局、设备树、权限、缓存与 OS 适配限制 |
| [机器平台](machine-platform.md) | 通用 `MachinePlatform` 组装及早期验收记录 |
| [OpenSBI 启动验证](opensbi-bringup.md) | GSIM 的真实 OpenSBI 初始化、S 态交接和串口探针 |
| [Linux 启动实验](linux-bringup.md) | 64 MiB GSIM 平台、用户态 `/init` 与交互运行记录 |

先确认目标配置，不能跨列复用链接脚本、设备树或固件地址：

| 配置 | ROM | RAM | 结论范围 |
| --- | --- | --- | --- |
| 通用 `MachinePlatform` 默认 | 8 KiB @ `0x80000000` | 4 KiB @ `0x80010000` | 定向模块与固件回归 |
| OpenSBI GSIM | 8 KiB @ `0x80000000` | 1 MiB @ `0x80010000` | OpenSBI + S 态探针 |
| Linux GSIM | 8 KiB @ `0x80000000` | 64 MiB @ `0x80010000` | Linux 启动及最小用户态 |
| ZU15EG `BoardSocTop` | 128 KiB @ `0x80000000` | 1 MiB @ `0x80200000` | UART 下载/执行已通过 GSIM；40 MHz 是目标配置 |

Linux GSIM 的 `0x80200000` 是内核装载地址；在板级它是 RAM 基址。
GSIM 的 OpenSBI/Linux 成功不能证明上表的早期 1 MiB 板级平台能启动 Linux。
该阶段仅有 RAM 单模块综合和整板 RTL 展开等证据；后续 DDR、Linux、RV64GC 与 100 MHz
实现/上板结果须分别查 [datasheet](soc-datasheet.md)、[Debian BSP](vl100-debian-bsp.md) 和
[时序记录](fpga-timing-windows.md)，不要以这张早期表覆盖后续状态。

## FPGA 与启动固件

- [Ethernet 接入台账](../fpga/zu15eg/ethernet-integration.md)：自研千兆优先、TL/CRC/MDIO 公共 IP、PHY 管脚/复位证据、SFP1 延后；保留旧 AXI Ethernet 许可/综合记录。
- [时钟域与 GMAC 准备](../fpga/zu15eg/clock-domain-plan.md)：独立CMU、可选MMIO/APLIC7、保护资源清单、实际BUFGCE模型短验证及UART/GMAC排空边界；不是整板门控签核或已发布网口bit。
- [ZU15EG 40 MHz 配置](../fpga/zu15eg/README.md)：当前板级地址、ROM/RAM、Vivado 配置与验证范围。
- [BootROM 与 UART 下载](../fpga/firmware/README.md)：监控程序、下载协议、平坦二进制布局和应用限制。
- [Windows Vivado 时序检查](fpga-timing-windows.md)：当前 SoC 的导出入口、约束和各配置时序记录。
- [FPGA 启动与历史实验](fpga-bringup.md)：当前 Board40 入口及早期 `FpgaPlatformTop` 的取指、同步存储和预取记录。

## 验证与性能

- [CPU 读带宽候选源码交付](cpu-fetch-prefix-source-delivery.md)：显式 LSU4/history/prefix 选择、默认 OFF、冻结证明与本次源码整合边界。
- [GSIM 验证说明](../simulator/gsim/README.md)：依赖、Make 入口、独立参考模型和回归范围。
- [当前性能与证据边界](performance-status.md)：各工作负载和配置的周期结果及不能外推的指标。
- [裸核接口与 IPC](bare-core-ipc.md)：理想供指/内存的裸核基线与历次功能验收。
- [RV64C 与 CoreMark](rv64c-coremark.md)：压缩指令与 CoreMark 测量口径。

## 架构与模块合同

- [目录与依赖边界](layout.md)：源码、工具、生成产物和文档维护规则。
- [OoO Core 设计与验收规划](ooo-core-plan.md)：架构目标、不变量和阶段实施记录。
- [模块化 SoC / AIA IP](modular-soc.md)：CPU/IP/平台依赖、AIA 组合及互联边界。
- [公共 ISA 与复用边界](isa-reuse.md)、[RVA23 目标与差距](rva23.md)：共享编码与合规边界。
- [RV64M](rv64m.md)、[RV64B](rv64b.md)：乘除、位操作执行与验证合同。
- [机器核 CSR 与陷阱](machine-core.md)、[PMP](pmp.md)、[虚拟内存](virtual-memory.md)：特权、物理保护和可选 I/D 译址。
- [APLIC](aplic.md)、[CPU MMIO 路由](core-mmio.md)：线中断、MSI 与设备访问的硬件接口。
- [UART](uart.md)、[机器定时器](machine-timer.md)、[Sstc](sstc.md)：串口、时间源和定时中断。
- [DMA 与 FENCE](dma.md)、[原子访存](atomic-memory.md)：共享内存访问及不可撤销副作用。

互联与缓存：

- [TileLink 内存桥](tilelink-memory-bridge.md)、[双 RAM 路由](tilelink-router.md)、[双主仲裁](tilelink-arbiter.md)：并发事务、source 归属与响应重排。
- [TileLink 取指](tilelink-fetch.md)、[burst 与一致性](tilelink-burst-coherence.md)：ROM/RAM 共享访问、整行事务与一致性范围。
- [AXI4 内存桥](axi4-memory-bridge.md)、[TileLink→AXI4](tilelink-axi4-bridge.md)：外部内存合同与阶段记录；当前 PL DDR 接入查 datasheet/板级验收。
- [共享读缓存](shared-read-cache.md)：可选读缓存实现、配置对照与历史优化记录。
- [写缓冲排空](store-drain.md)、[load/store 重叠](load-overlap.md)、[load 旁路与回放](load-ready-replay.md)：访存微架构与定向性能记录。

## 历史资料与维护规则

- [历史资料索引](../legacy/README.md)：旧 SoC、退役 ChiselSim、旧固件和故障记录；旧仿真命令不能作为活动入口。
- 本次以导航分类组织文档，不移动或删除现有研究日志。已有路径继续有效。
- 软件适配优先查前三份软件合同，再核对目标顶层参数和对应验证记录；模块文档中的早期阶段边界不能覆盖后来的实现。
- 更新软件可见接口时同步修改 datasheet、寄存器或 OS 指南，并保留变更前后配置、日期与证据。
- 仿真通过、RTL 展开、独立模块综合、整机实现和上板验证分别陈述；不得互相替代。

- [Optional translated-response empty flow](translated-response-empty-flow.md): default-OFF local response bypass, measured CPU pairs, strict observer controls and remaining qualification limits.

- [Posted-store integration review](posted-store-delivery-review.md): source-only composition, exact frozen component qualification and pending actual CPU/cache/home gate.

- [Posted-store WRITE/COPY performance tradeoff](posted-store-seal-performance.md)
- [Posted-store same-source native storage cost](posted-store-native-cost.md)
