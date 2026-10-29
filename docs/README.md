# Valence 文档导航

## 先跑通的功能基线

[命名启动入口与验收顺序](../simulator/gsim/BRINGUP.md)：先复位/ROM、UART 或 tohost、RAM，再中断基本链。
`make bringup-plan` 只列出真实入口、阻断项和证据范围；实际测试须显式选择配置。
历史 bit、当前源码的功能检查、物理时序签核分别记录，未运行项不能算通过。
最终可替换 CPU 的公共平台必须显式启用独立 CPU/fabric 时钟；新增异步传输组件并不表示两个 SoC 已接通该平台。

性能实验单列：[Orbital-A1 ready/raw73、measured74 与资格限制](timing-closure-candidate-20261014.md)。这些候选不由功能基线入口自动选择；历史记录保留原有范围。

## 公共 SoC 的显式配置

- [A1 访存容量规格](common-a1-cpu-spec.md)：限定的 LSU 2/4 所有者容量选项，保留完整 ISA 与共享平台；配置、组件验证和 CPU 性能证据分开记录。
- [JTAG RAM 下载外设选项](common-jtag-peripheral-option.md)：真实实例与接口可裁剪，剩余 ABI 地址不重排。

## Orbital-I1：独立参数化顺序核（dev2）

- [本次兼容合并与公共平台边界](dev2-integration-20261019.md)：保留两侧已有配置、时序资格范围和后续统一外设计划。

- [架构、参数与完整阶段记录](orbital-i1.md)：与 Orbital-A1 乱序核、legacy 历史核分开。
- [源码与构建边界](layout.md)、[GSIM 入口](../simulator/gsim/inorder/README.md)、[FPGA 整板入口](../fpga/inorder/README.md)。
- 当前显式测试配置：fpga8、RV64IMAFDC、M/S/U、PMP/Sv39、PLIC、I/D 各32KiB、
  两个 DDR 槽位；新实验开关默认关闭，未自动替换平台默认值。
- 最新整板为 [batch44](../fpga/inorder/README.md#batch44300mhz整板约束sta通过bit已生成用户确认jtag小程序运行)：CPU300 WNS 0.000ns、hold +0.007ns，属于冻结 dev2 的 no-MAC 配置；合并后的源码不自动继承该物理时序结论。
- 以下保留 batch40 及更早历史记录。batch40：切除注册式取指器不可能发生的IT同拍回接依赖；分离对齐器载荷
  捕获与晚到VALID，展平缓存命中回复，PMP分组优先级、EX短进位选择一起优化。
  49项短检查、13项性能门、17项参数测试通过；六组吞吐和CoreMark逐字段不变，
  6999寄存器/89内存声明完全相同。CPU hold保护从50ps加严到80ps，
  多时钟域、32+32KiB和槽位不变。dev2-r4整板路由及一次后路由优化完成：
  CPU300 setup 0.000ns（MET）/hold +0.010ns，setup/hold/脉宽失败端点均为0。
  这是贴线STA通过，并非充足setup裕量或上板验证。DDR250 +0.358/+0.010ns，
  AON/UART50 +0.619/+0.040ns。整板93788 LUT、55189寄存器、BRAM62.5、DSP31。
  原9项CDC Critical端点完全不变，结构/功能释放审计通过但仍非完整CDC签核。
  2026-10-17 20:14已按用户要求从该路由DCP生成bit，未重做实现；
  USER2/65位修复已包含，MAC未接，UART460800，上板运行及JTAG下载仍待实测。
  bit路径、哈希与清理归档见[本轮交付](orbital-i1.md#batch40-bit-delivery-and-cleanup)。
- 上一批 batch39：DT按真实TLB源并行授权、按物理证明页并行判定缓存窗口；
  probe独立所有者捕获、victim逐way前递；BTB按bank局部选择下一PC。
  37项受影响短检查、13项性能门、17项参数测试通过；六组Bare/Sv39与短O3
  CoreMark逐字段等同batch38。寄存器与内存声明逐条不变，无新增槽位或流水级。
  dev2-r3已完成真实整板路由及一次后路由优化：300MHz WNS −0.017ns、
  TNS −0.418ns/70端点，hold +0.003ns；相比batch38的−0.316ns明显改善，仍未达标。
  已专项回读：D元数据WE +0.021ns、probe捕获 +0.402ns、victim捕获 +0.280ns、
  PC自反馈 +0.006ns；最坏链仍为I-cache victim标签→PC准入CE。
  整板93624 LUT、55121寄存器、
  BRAM62.5、DSP31；DDR UI250、AON/UART50的setup/hold均为正。
  9项原有复位CDC Critical端点不变，三级同步结构和7条功能释放时序已审计；
  另2条仅同步器复位分支保留原例外，不算CDC全签核。未生成bit、未提交。
- 上一批 batch38：Home 目录集中单写口、DT 下一地址准备与回复准入解耦；
  29 项受影响短检查、17 项参数测试通过。六组 Bare/Sv39 流量与 batch37 逐字段一致，
  O3 CoreMark ROI 保持646056拍，CRC/退休轨迹一致，不是正式持续时间评分。
  目录六读口叶模块实际映射为700 LUT（576 LUTRAM）、0 FF；不是整板资源统计。
- batch38 已集中进入真实整板实现：同综合口径总 LUT 156094→93883，
  FF 74921→54457；Home 74067→11379 LUT，目录各582 LUT/0 FF。
  完整 MIG/AXI CDC IP 已计入；BRAM62.5、DSP31保持不变。
- 以下为batch38及更早的未通过历史记录，不是当前batch40结果。旧r11路由
  WNS −0.007ns不是新版时序结果；
  batch37 整板综合 WNS −3.089ns 属于修复前。batch38 已完成恢复路由：
  CPU300 setup −0.316ns /hold +0.010ns，仍未达标；未生成 bit。
  最终整板92982 LUT、55150寄存器、BRAM62.5、DSP31；MIG/AXI CDC计入，MAC未接。
  DDR UI250、AON/UART50的setup/hold均为正；9项原有复位CDC Critical仍待审计。
  Explore在末尾时钟优化崩溃，最终数据来自同一物理优化DCP的时序驱动-no_psir恢复，
  不是Explore完成结果，时钟/RTL/约束未变。详见架构记录最新章节。
  USER2 板上65位扫描与66位拒绝已做实际双 TAP 验证。
- 历史小报告、验收收据及源码快照保存在 WSL 独立归档：
  `/home/openion/Valence-inorder-evidence/pre-dev2-20261017-r1`。
  本批另存`/home/openion/Valence-inorder-evidence/batch39-board-routed-20261017-r1`；
  机器可读结果为dev2-r3/physical-review.json，原始收据及整板清单未覆盖。
  最新batch40归档为`/home/openion/Valence-inorder-evidence/batch40-board-routed-20261017-r1`，
  机器可读结果为dev2-r4/physical-review.json，最终路由在dev2-r4/postroute-r1/。
  完整 `build/`、`out/` 和 Vivado 工程/缓存不进源码提交。

## Orbital-A1 / VL100 及通用平台

[下一完整 timing/CDC 板版](fpga-next/timing-cdc-combined-v1.md) 已通过实际构造、native 导出与同负载 CPU 对照；物理 CDC/STA、vendor 与上板门仍未完成。独立默认关闭选项、旧板版回退和原始失败证据保留。

Read-prefetch demand adoption 的独立默认关闭源码备份、Bare/Sv39 实测收益与额外读流量、原始失败门和 native 限制见 [实验记录](experiments/read-prefetch-demand-adoption.md)；下一统一板版须组合资格通过后显式启用。

当前推荐入口与 Sv39 COPY canonical-store-overlap 资格记录见 [v3 配置、回退与证据](../simulator/gsim/canonical_virtual_store/README.md)。

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

- [DDR 写收集/发送重叠](ddr-write-collection-flow.md)：2026-10-11 默认关闭的结构候选、请求/传输占比和短验证边界。
- [行传输调度去气泡](line-transfer-dispatch-flow.md)：第二组默认关闭的带宽结构优化、真实 DMA 路径增益和历史 checkpoint；后续解耦已由第三组完成，本组不跑 STA。
- [独立行读入口与整行返回](line-read-channel.md)：第三组共享容量不变的重构，最低延迟 DMA 128KiB 达 99.817% AXI R/W 有效传输占比；实际延迟下的写信用限制及待完成 CPU/物理资格。
- [高延迟容量与 MMU](line-read-channel.md#latency-and-mmu-follow-up)：第四批 DMA8/DDR8/写4 的固定延迟 COPY 221.7→442.2MiB/s；同容量 DTLB 成功写权限复用与异常/刷新证明、服务上限和 ID 延迟模型偏差；真实 CPU 接续见下一项。
- [真实 CPU / Sv39 吞吐与阻塞](line-read-channel.md#actual-cpu-sv39-throughput-follow-up)：第五批同容量、同工作量的 S-mode READ/WRITE/COPY，默认关闭的翻译命中直送、被回退的预取组合、虚拟 store/并行准入瓶颈及60个短 CPU 正例；本轮不跑综合或 STA。
- [授权 store 交接与独立准入](line-read-channel.md#authorized-store-handoff-and-independent-demand-admission)：第六批保持双MSHR／双响应槽，消除全局store-miss和整set独占；实际Sv39 COPY双owner重叠30.971%，但COPY仅+1.695%、Bare回归，继续定位读／写预取争用，候选默认关闭、不改preset、不跑综合。

- [Proof frontier 与 store-PF LRU 显式实验](experiments/frontier-lru-opt-in.md)：推荐 v3 不变；完整 CLI/参数映射、已完成组件资格及待闭合 CPU/回归边界。

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

- [Posted/PF v2 integration](posted-prefetch-integration.md): recommended posted/coexistence/head-offer preset, completed scoped qualification and explicit remaining coverage limits; generic defaults stay OFF.

- [Exact raw-PMP change publication: qualified CPU candidate and explicit ON entry](fpga-next/pmp-change-publication-v1.md)
