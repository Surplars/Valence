# Valence PL DDR 板级时钟域与后续策略

## 最新：真实 UART / 原生 GMAC 受管域接入

可选 `managedPeripherals=true` 已接生产BoardSoc：CPU控制侧100MHz、AON/UART50MHz、
GMAC TX/RX125MHz，专用BUFGCE管理三个叶子钟，GATEABLE=0x68；CPU/TIME/DDR保护。
真实packet DMA流/完整回复/状态尾/配置/统计排空、MMIO自动唤醒和RAW首输入保留已接。
短GSIM及仅CDC的真实门控xsim通过；组合外设OOC内部setup/hold=+3.018/+0.031ns，
3964 LUT/4503 FF/2 RAMB18。默认和旧bit不变；5条CDC Critical不隐藏，零I/O预算边界
hold=-0.555ns，不是整板签核。完整合同、证据、复现与PHY待办见
[受管外设接入](../../docs/managed-peripherals.md)。以下各批次为当时冻结输入的历史记录。

## 先前批次：独立 CMU V1 与物理门控模型短验收

`src/main/scala/ip/clock/` 分开管理策略、总线边界和FPGA物理实现：

- `ClockManagementUnit`：独立常开域CSR/资源清单、保护掩码、停钟/唤醒/超时策略；
  1..16资源，四项有序回复，无CPU实现依赖。
- `TileLinkClockManagement`：原生64-bit TL-UL四项有序入口，不支持burst/原子/TL-C。
- `ClockManagementBoundary`：CPU→常开域的完整RegisterPort请求/回复CDC与IRQ同步。
  BoardSocTop通过可选 `clockManagementHz` 接入窗口`0x10080000`和APLIC7；默认关闭。
- `ManagedClockBuffer`：在**不被关闭的原始时钟**上同步CE，再驱动BUFGCE的SYNC模式；
  不是逻辑AND，不复位MMCM/MIG，不修改频率。原始源时钟必须持续运行。
- `FpgaClockResources`：不含CPU的独立CMU+门控+本地排空ACK资源银行；常开资源0直接用
  alwaysOnClock。与BoardSoc内CMU为两种使用方式，不要对同一时钟叠加两个CMU所有者。
  使用BoardSoc额外控制端口时，外层接ManagedClockBuffer和PeripheralQuiesceAck。

BoardSoc资源号0..6分别是AON、CPU、TIME、UART、DDR_UI、GMAC_TX、GMAC_RX，全部保护。
显式启用CMU需外层提供匹配频率的固定alwaysOnClock，不能将受管时钟反馈作为常开源。
DDR UI频率由 `ddrUiClockHz` 声明，默认250MHz，须按实际MIG配置填写；GMAC频率为千兆
标称，非测量。额外叶子域从7起，需要可靠端点idle/ACK、隔离代理、持久wake和专用
门控连接后才可设置canGate；保护掩码不允许关闭CPU/TIME或误关DDR。
父域编号必须先于子域；V1禁止停有已存在子域的父资源。

目前**不是**完整板级PMU。既有UART还需常开RX唤醒与FIFO/回复排空；native GMAC还需
停止描述符/帧并排空所有数据、状态、配置和事件；DMA须覆盖coherent home与缓存事务。
隔离期间访问须在常开侧唤醒或返回错误，不能送到停钟slave后永久等待；Bank不替调用方
生成这些代理。缺失源时钟的唤醒保持隔离并报错，CLOCK_ENABLE只是命令，不是物理测频。
MachineTimer仍随CPU周期递增，故CPU不允许停钟/DFS；固定timebase尚未迁移。
无DRP/动态频率、局部热复位、自刷新、掉电；共同冷复位仍须同时覆盖CPU/master/桥两端。

最终局部功能回执：`build/gsim/clock-management-20261004-r2/receipt.json`，
`PASS_CMU_SCOPED_GSIM`：4项Scala（含默认及完整可选BoardSoc纯elaboration）、
Register/TL/串行Router/并行Router各326/339/329/329事务，共1323事务，四个严格负例，
保护写原子拒绝、子字/掩码、四信用背压、资源清单、W1C并发事件、软/硬唤醒、超时与恢复通过。
Header交叉编译通过；没有CPU执行、全GSIM、长Linux或全板仿真。

实际BUFGCE原语模型的CDC-only xsim回执归档于
`build/fpga/clock-management-20261004-r1/functional-r3/receipt.json`，
`PASS_MANAGED_CLOCK_GATE_CDC_SHORT`：三组原始周期8/13/20ns与常开20ns，
逐边沿/完整高脉宽匹配、真实关钟后无边沿、保留/唤醒/取消/排空超时、停钟中共同冷复位，
以及原始时钟消失时唤醒超时/恢复通过；独立错误注入拒绝。
缺glbl的初始失败和测试台周期变量竞争失败保留：最终oracle对照原始时钟真实边沿，
没有放宽停钟、脉宽或隔离判据。输入RTL相同，无需重复CPU或修改门控RTL。
综合审计 `build/fpga/clock-management-20261004-r1/audit-final.json` 核对哈希和边界。

本批未做新的布局布线/整板时序或bit；数字仿真不是亚稳态/实际门控I/O时序签核。
接板后须检查桥的held payload max-delay/skew、全部单比特同步路径、BUFGCE CE时序、
同步复位释放、实际时钟源/外设预算；不得用全局clock_groups或宽泛false_path掩盖问题。
原整数100MHz Linux bit、默认开关与CPU流水/DMA实现不变，只新增可选平台入口。
软件ABI见 [CMU寄存器](../../docs/soc-registers.md#cmu-v1独立常开时钟管理单元可选)。

## 先前批次：原生网口 CDC 与外设停钟基础独立验收，未接整板

本节先前批次时，生产 SoC **没有统一的运行时 CRG/PMU**。新增CMU见上节；不能把构建参数或外设 enable 位
说成时钟门控；外设运行时关闭、局部复位和电源关闭也是不同能力。

| 当前对象 | 已有时钟/配置能力 | 运行时停钟状态与后续要求 |
| --- | --- | --- |
| UART | 板级常驻；`peripheralClockHz>0` 可选固定独立域与寄存器/IRQ CDC | 未门控；需要 TX/RX/FIFO/回复排空及常开 RX 唤醒采样器 |
| MachineTimer / rdtime | 当前留 CPU 域 | 不应随 CPU 停钟或 DFS 丢失计时；固定时间基准与64位一致读仍待实现 |
| memcpy DMA | CPU 域，板级常驻 | 未门控；要排空请求、回复、coherent home/缓存事务，不能只看 active 位 |
| packet DMA / GMAC | 构建选项默认关闭；新 native 帧 CDC 独立通过 | 仍未接生产网口；停止新描述符和帧，排空全部数据/状态/配置/事件后才可停钟 |
| DDR MIG / UI / PHY | 已有独立时钟和 AXI 跨域 | 本批不关闭；自刷新/恢复是另一个协议，不能把通用停钟 FSM 直接套上去 |
| CRG/PMU/唤醒 | 本批新增独立 retention clock policy | 应留常开域；软件 MMIO、实际门控资源、唤醒源和整板连接仍待接入 |

本批三项可复用结构：

- `CdcDataFifo` / `EthernetFrameClockBridge`：完整32-bit帧 + keep/last/bad 跨域，
  双时钟同步读、目的端寄存器保持。RAM 指针为空不代表目的端输出/预读为空，停钟必须
  检查双方及全部待完成工作。首次快生产者/慢消费者检查发现提前归还信用使槽位覆盖，
  已改为**目的端输出捕获后才推进读指针**，未放宽 oracle；失败 RTL 和日志保留。
- `CdcMailbox` / `EthernetConfigClockBridge`：52-bit 配置原子快照，目的端消费后才 ACK，
  TX/RX 两分支须一起接受同一快照。应用必须在各自安全帧边界执行，两个域都 ACK 后才
  能对软件宣称配置生效。`CdcAccumulator` 将源端累计事件/字节快照转为背压稳定的 delta，
  不把脉冲直接过两拍同步；32-bit 默认要求两次已消费快照间增量小于2^32。
- `PeripheralClockControl` + `PeripheralQuiesceAck`：控制器在常开域；停止源端接单，
  目的端看到 quiesce 后停止接单并排空，ACK持续稳定后才请求关钟/隔离；唤醒先开钟，
  观察 ACK 返回低（证明本地时钟真实推进）再放开访问。命令均寄存器输出，无 FSM
  多位组合译码直接送门控。排空超时保持钟开、置故障、阻止 held STOP 重试直到 STOP 清除。

这只是**时钟保留（retention）基础**，不复位保留寄存器，不是掉电、独立热复位、DFS/DRP。
STOP/wake/clearFault 必须已在常开域，短异步 wake 须在常开侧可靠锁存。endpoint idle
必须覆盖真实总线/回复/包尾/配置/统计和所有 CDC 缓冲；测试 wrapper 不是完整网口排空器。
软件访问停钟域须由常开代理唤醒或显式返回错误，不能发出后永久等无时钟的 slave。
本批没有新增软件可用 MMIO 或改变原地址表，不能宣称 Linux clock/reset driver 已可用。

最终短证据：`build/fpga/self-gmac-cdc-20261004-r1/functional-r4/receipt.json`，
`PASS_NATIVE_GMAC_CDC_CLOCK_POLICY_SHORT`。3项Scala检查、4组独立时钟与相位、
双向20480拍/640配置拷贝、计数回绕、暂停输入时钟、输出保持与背压、共同冷复位、
停钟/唤醒/超时/取消及四种独立错误注入通过；来源和必要输出均 SHA-256 核对并归档到 WSL。
按用户授权只用 CDC-only xsim，没有 CPU/MAC/PHY xsim、全GSIM或长Linux。
数字通过不能证明亚稳态不存在或 BUFGCE/板级时序已签核。

本批只综合/布线一次小型 `SelfGmacCdcTop`（无 CPU/MAC/PHY），随后两次报告复核只打开
同一 post-route DCP：第一次约束端点选择器未适配 RAM 原语展开，失败保留；修正
CLK/WCLK 名称查询后覆盖双方38位 RAM 数据，没有重新综合或布局布线。
最终 `build/fpga/self-gmac-cdc-20261004-r1/audit-final.json` 为
`PASS_SCOPED_CDC_RETENTION_MODULE_OOC`，必要输入/报告/DCP 在 `native-results/`：

| 度量 | 本批独立 CDC/retention wrapper |
| --- | ---: |
| control / TX / RX 约束 | 10 / 8 / 8 ns |
| 内部 setup / hold 裕量 | +6.268 / +0.042 ns |
| post-route LUT / FF | 236 / 671 |
| 其中 LUTRAM / BRAM tile / DSP | 48 / 0 / 0 |
| TX / RX RAM 38位最小 max-delay 裕量（8ns预算） | +7.323 / +7.354 ns |
| 10组 Gray/held/RAM skew 最小裕量 | +7.472 ns |
| CDC Critical | 0 |

CDC-6 仍有4组 Gray 同步总线 Warning；CDC-15 仍有212条 Warning：136位原子 held
payload、76位受指针/捕获所有权保护的 LUTRAM payload。所有227个 CDC端点均有明确
max-delay，10组 skew 均满足；不隐藏/waive Warning，不由“Critical=0”推导整个系统安全。
该 wrapper 只实例化两条**16-bit 测试累计器**，不代表实际 GMAC 全部32/64位统计资源。
OOC 没有真实 HD.CLK_SRC、I/O delay 预算或物理门控原语，模块时序不等于整板 signoff。
OOC DRC 的225条无 routable load 端口网告警保留，不声称零 Warning；未来接消费者后检查。
旧 `StreamClockDomainFifo`、现有板级 CDC/时钟资源/默认配置本批未修改；新原生 CDC
不能自动覆盖旧接口资格。没有新的 CPU IPC/Fmax/整板/bit 结论。

FPGA 后端须使用专用无毛刺时钟资源，不能 `clk & enable`；单寄存器 CE 则仅减少数据翻转，
不等于关闭时钟树。见 [AMD BUFGCE](https://docs.amd.com/r/en-US/ug572-ultrascale-clocking/BUFGCE-Clock-Buffers)。
Gray 指针、held payload 和 RAM 数据须精确 max-delay/bus-skew 约束；不使用宽泛异步组
或 false-path 掩盖数据路径。见 [AMD CDC 约束](https://docs.amd.com/r/2024.2-English/ug903-vivado-using-constraints/About-Bus-Skew-Constraints)。

以下为前批网络物理集成和旧候选的历史记录；新原生 CDC 已独立验证，但生产三域网口尚未接入。

2026-10-04 自研MAC前批边界：公共TL/MDIO/CRC及GMII帧/真实DMA单时钟短验收已通过；
用户要求千兆优先，10G仅记录未来SFP1。新RX/TX帧引擎各自属于PHY RX与固定125MHz TX域，
原生帧适配器拟留CPU100MHz域，用两条完整data/keep/last/bad帧CDC连接。
配置须可靠快照到MAC域；完成/丢弃脉冲和计数须保持/握手，不能逐bit两拍同步。
**这套物理拓扑尚未接入**：单时钟 `SelfGmacDmaGsim` 不是三域顶层，
旧TEMAC四FIFO或旧CDC独立xsim报告不能替代新原生帧/事件边界验收。
当前无新网口bit或动态时钟；资料和本批RAM推断修正见 [Ethernet台账](ethernet-integration.md)。

最新新增 AXI Ethernet 控制候选及实际 IP 生成/授权记录见
[Ethernet 集成记录](ethernet-integration.md)。以下“GMAC 尚未接入”是前一批历史状态；
新控制集成仍未发布 GMAC bit，也没有完成网络 DMA 或 PHY 管脚签核。

## 2026-10-04：可选固定外设域已接入源码，GMAC 尚未接入

以下旧 50 MHz 章节是历史合同。既有整数双发射 100 MHz bit 不变；本轮
`staged-gmac-ready` 是新候选，不以旧 bit 或 FPU CPU OOC 报告替代本轮整板验收。
当前功能短测已通过，CPU 新候选布线时序未通过；Clock Wizard、MIG 和 GUI 工程未修改。
实际全 F/D 二发射 MachineCore 的 10 ns OOC WNS=-0.841 ns、内部 hold=+0.019 ns，
关键链为 ROB head→访存 owner/PRF 操作数→stagedMemoryAddress，数据延迟 10.822 ns，
其中布线 8.813 ns（81.435%）。这是 CPU OOC，不是整板或新增第三域 bit 签核。
旧同口径 CPU OOC WNS=+0.090 ns 仍保留，新 profile 不推广；既有整数 100 MHz bit 不变。
最终验收记录为 `build/fpga/gmac-ready-20261004/audit-final-r1.json`，状态
`FAIL_INTERNAL_CPU_TIMING`。本批只做一次联合综合/布局布线；后续约束复核仅打开已布线 DCP。
原取指反馈路径族的只读对比同样回退：9.806→10.360 ns、WNS +0.090→-0.465 ns，
不能因其不再排名第一而称之为已优化达标。报告/检查点归档于
`build/fpga/gmac-ready-20261004/native-r1/`，跨域短 RTL 证据也已放回 WSL。
归档全部文件 SHA-256 与原生输出一致，再审计记录为
`build/fpga/gmac-ready-20261004/audit-final-archived-r2.json`；没有删除原始报告。

- CPU/FPU/ROB/PRF/L1/TileLink 仍同域，issue=2；定时器留在 CPU 域，timebase 不变。
- `BoardSocTop(..., peripheralClockHz=50000000)` 增加 `io_peripheralClock`，
  UART 真正在该域运行，经 `RegisterClockDomainBridge` 访问，IRQ 经 `CdcLevel` 返回。
  `peripheralClockHz=0` 默认保持原端口与单域 UART。实际顶层必须提供稳定时钟并协调复位；
  此源码选项没有自动生成、重配 Clock Wizard，也没有发布第三域 bit。
- 控制桥容量 1 个有序事务：完整 address/write/size/data/byteEnable 和 data/error 跨域。
  接受请求后到响应被消费前不接下一请求；控制采用两级 toggle 同步，数据寄存器保持。
  最短跨域可见延迟包括两级同步和一次本域捕获；背压下延迟无固定上限，不用于高速包数据。
- `StreamClockDomainFifo(depth=16)` 独立数据边界：64-bit data + keep/last/user，
  Gray 指针、两级同步、每本域每拍至多一 beat，容量 16 beat（128 字节 payload）。
  当前小容量采用异步读存储，综合可用 LUTRAM；大容量网络包缓冲应另做 BRAM/XPM 方案。
  这不是完整 GMAC、DMA、MTU 缓冲、包级溢出丢弃或以太网 CRC 处理。
- 只支持共同复位：必须同步复位 CPU/master 与外设，两端异步断言、各域三拍释放。
  共同复位可取消在途事务/部分包；不支持独立热复位、自动事务重放、运行中 DFS/DRP。
- IRQ 同步器只处理持续电平。脉冲/计数事件须另用握手、toggle 或计数协议。

用户确认 PHY 为 **RTL8211F**。先按 RGMII MAC 独立 125 MHz 域规划，但 MAC IP、
板级 RGMII/MDIO 管脚、PHY strap、TX/RX 时钟延迟仍需核对后才能接入。
RXC 是 PHY 提供的接收时钟，不能简单当成固定 TX/AXIS 时钟的同域信号。
参考 [Realtek RTL8211F](https://www.realtek.com/Product/Index?cate_id=786&id=3975)、
[AMD RGMII 时钟合同](https://docs.amd.com/r/en-US/pg051-tri-mode-eth-mac/RGMII)。
网络 DMA 后续须明确 CPU 缓存一致性/uncached 缓冲、描述符所有权及内存屏障，不能由控制 CDC 推导 DMA 已完成。

验证记录（只运行必要短测）：

- `build/gsim/gmac-ready-20261004-r1/receipt.json`：独立 PMP byte-range oracle，
  2/4 路 compressed reservoir、wrap/fault/stale hint/reset；真实二发射 CPU 的逐提交 NEMU，
  50 项控制/访存烟测和 11 项执行槽恢复检查，正/负对照均通过。
- `build/gsim/rv64gc-board-20261004-gmac-ready-r2/receipt.json`：生产板级模型
  31960 cycles，完整 FPR/FCSR/FS/SD context、Sv39 非同址映射及精确 S ECALL。
  这是机制烟测，不是 Linux 浮点调度或新增 bit 验收。
- 用户明确批准 **仅新增 CDC 模块使用 xsim**：`fpga/zu15eg/cdc_tb.sv`、
  `run_cdc_xsim.py`。4 组独立时钟（14/22、22/6、8/18、10/8 ns），
  1200 次完整请求/回复、16384 beats、满空/背压/packet sideband、在途共同复位通过；
  注入损坏的数据被独立 scoreboard 拒绝。CPU 仿真仍仅 GSIM。
  最新完整逐拍 IRQ oracle 的证据已归档至 `build/fpga/gmac-ready-20261004/cdc-xsim-r3/receipt.json`。
- `cdc_constraints.tcl` 对 bundled-data、toggle 和完整 Gray 总线做 scoped max-delay/bus-skew；
  不使用 blanket clock groups。综合可能合并 Gray MSB 和 binary MSB，因此从首级同步器
  D 端追踪真实驱动，不能只用 `*Gray_reg*` 名称匹配。需检查 post-route 约束/CDC 报告，
  不把逻辑 xsim 通过等同于物理 CDC/整板已签核。

CDC 原生独立 100/125 MHz 布线复核已完成：78 LUT / 476 FF，内部 hold +0.044 ns；
请求、回复、read/write Gray 的实际 bus skew 为 0.476 / 0.572 / 0.420 / 0.399 ns，
都小于 8 ns。必须使用寄存器 C 引脚或 cell 作为合法 startpoint；Q 起点会触发路径
segmentation，原 r1/r2 的 NA skew 报告不作为验收。完整纠正后的报告为 native batch
`cdc-review-r3`，复用原 route DCP 只重算约束/报告，没有重复综合或布线。
`report_cdc` 保留 205 条 CE 控制数据通路、2 条 Gray 多位同步提示及 5 条外部 reset/IRQ
提示，未添加全局 waiver；这是显式协议审查对象，不宣称工具零警告。
零边界 I/O delay 的全部 hold 仍为 -0.135 ns，不是整板 I/O 预算或第三域 bit 签核。
相关规则参考 [AMD 合法 bus skew 起点](https://docs.amd.com/r/2023.1-English/ug903-vivado-using-constraints/Syntax-of-the-set_bus_skew-Command) 和
[路径 segmentation 风险](https://docs.amd.com/r/2023.1-English/ug903-vivado-using-constraints/Path-Segmentation)。

复现 CPU 短测：

```sh
GSIM_CXX=clang++-19 make gsim-gmac-ready-test GSIM_GMAC_READY_TAG=fresh-tag
GSIM_CXX=clang++-19 python3 simulator/gsim/rv64gc_board.py --tag fresh-tag --profile staged-gmac-ready
```

原生 Windows CDC-only 短测的命令参数为：
`python fpga/zu15eg/run_cdc_xsim.py <cdc-rtl> <fresh-native-output>`。
板级 RTL 可选导出最后参数为外设实际频率，例如：
`mill -i IonSoC.test.runMain ooo.BoardSocMain <fresh-output> 100000000 ddr staged-gmac-ready 460800 2 2 1 rv64gc 50000000`。
该导出需要板级 wrapper 接 `io_peripheralClock`，**不能直接覆盖旧单域 bit 工程**。

---

当前已经有两个内部频率域，不需要为了“多时钟域”再拆一次CPU：

| 域/接口 | 当前配置 | 跨域处理 |
| --- | --- | --- |
| CPU/SoC、L1、TileLink、MMIO、UART、timer | 50 MHz clk_soc | 内部同域，UART RX另有两级输入同步 |
| MIG AXI UI | 250 MHz ui_clk | axi_clock_converter_ddr，AXI4/64data/32addr/4ID、ACLK_ASYNC=1 |
| 板级差分参考输入 | 200 MHz | 仅由MIG接收；CPU clock wizard输入是MIG ui_clk |

这是代码/IP配置核对，不是本轮新跑的整板CDC/route验收。CPU时钟由UI经过MMCM派生，
不是两个独立晶振；AXI桥仍明确配置为异步转换模式，不能因此直接撤掉CDC桥或IP约束。
定义见soc_top_ddr.sv与prepare_ddr_project.tcl。既有release/audit流程检查reset链及CDC，
后续改时钟或重新集成IP时须再跑完整检查。

## 既有双域基线（以下不是新增外设域实现）

- 保持CPU/ROB/PRF/发射/执行/L1同域，靠明确的数据与信用流水边界处理13.091ns
  等内部长组合路径。把CPU流水级拆到异步域不会自动缩短单域的组合路径，还需要
  跨域队列、退休/恢复/异常一致性协议与额外延迟证明；当前没有这项收益证据。
- 保持DDR独立高频域和既有AXI转换器。桥的异步转换依赖内部FIFO重新同步读写域；
  必须保留IP生成的XDC，不能用宽泛false-path绕过尚未分析的跨域错误。
- UART/定时器目前无需单独时钟，用CPU域内时钟使能即可。未来CPU时钟变化时必须
  同步核对UART分频、mtime/timebase、BootROM、应用和DTB；不要把50MHz软件常量当成
  不随硬件变化的板卡事实。
- 只有确认独立高频互连/缓存能改善CPU可见带宽，或确有固定频率外设需求时，才考虑
  第三个域；同时预算FIFO容量/延迟、请求回复顺序、原子/flush排空、reset/calibration
  联动和CDC/RDC检查。先做带宽/周期收支，不仅凭MIG峰值提速推导CPU收益。

两域reset均为异步断言、各域三拍同步释放；board reset、MIG ui_reset、校准未完成或
clock wizard失锁均抑制CPU运行。不要直接跨域采样多位总线，或为本轮时序优化添加
false-path、多周期例外。优化不更改现有板级时钟、IP配置或已发布bit。

AMD官方依据：[AXI时钟转换](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Clock-Conversion)、
[异步CDC约束](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Asynchronous-Clock-Domain-Crossing-Constraints)。

## 2026-10-02：用户目标与多时钟域准备合同

当前目标是双发射CPU稳定运行100 MHz（10 ns），达标后继续150 MHz（约6.667 ns）。
不是把可选时钟IP输出设为100 MHz就算完成：需要相同实际RTL/ROM的整板setup/hold、
CDC/RDC、DDR接口约束签核，并有实板启动、DDR正确性、程序与中断压力运行证据。
目前只有50 MHz既有板级证据；staged-retire的10 ns OOC WNS=-2.901 ns，随后
staged-redirect改善到-2.266 ns，仍不满足100 MHz；约150 MHz重约束WNS=-5.599 ns。
阶段成果不得代替整个目标。继续按2–3条相关CPU链成批改造、一次必要短GSIM、一次联合
综合推进；接近目标后再安排有意义的整板布局布线，不为每个小改动生成bit。

准备的结构为CPU/L1/核心互连一个域、固定50 MHz外设域、既有250 MHz DDR UI域。
CPU发射/ROB/PRF/退休不拆异步域。新增外设边界使用现有RegisterPort事务抽象：

- CPU侧完成地址译码、大小/原子合法性检查，再向外设域发送完整RegisterRequest。
  保持UART地址0x10000000及现有MMIO布局，不把全系统TileLink直接接入慢域。
- 首版桥最多一个在途事务，读写均严格有序，每次请求fire恰好执行一次副作用、产生
  一个RegisterResponse；响应未消费前不接受下一请求。空闲可接受一个请求，背压时
  valid和payload保持，目标是正确可复用，不声称线速或固定跨域延迟。
- 请求/响应分别用经验证的双时钟FIFO或完整握手传递。普通Chisel Queue、直接跨接
  ready/valid和逐位双拍同步均不构成多位事务CDC。桥用相互独立的源/目的时钟及复位。
- 首版采用两端协调复位：只有两域均已同步释放且桥ready，CPU侧才允许发起事务。
  系统复位允许丢弃在途事务，但不能只复位目的端后让CPU继续等待丢失的响应。
  后续若支持热复位，另需停止接单、排空或显式错误回复/代际协议，不能默默丢包。
- UART irq是保持到软件服务的电平，在CPU侧用规范同步链；未来短脉冲事件采用
  握手/计数或toggle协议，不能直接借用电平同步器。APLIC/IMSIC逻辑先保持CPU域。
- MachineTimer先留CPU域：它同时驱动64位timeValue/rdtime、比较器和timerInterrupt。
  真正迁移需证明64位读值一致、单调性、比较器更新及Sstc中断行为；不能逐位同步计数器。
  静态提频先同步更新软件timebase；运行时调频前必须换成不随CPU频率变化的时间基准。
- DMA寄存器可移外设域，数据主端仍是另一独立协议边界；控制桥不是DMA数据通路CDC。

外设域桥先做独立短验证：不等频率/非整数比例、不同相位、请求/回复背压、满空边界、
只执行一次副作用、顺序、协调复位和IRQ；之后再用UART作为首个真实从设备接入。
整板须report_cdc和report_clock_interaction，并检查IP生成的约束，不能添加宽泛
false-path来掩盖未经验证的桥。上述是明确的待实施/验收合同，不是已存在第三时钟域。

### 可调CPU时钟的后续门槛

已发布clk_wiz_ddr为50 MHz且USE_DYN_RECONFIG=false。先做固定外设域，再考虑启动
选频（CPU保持复位，选频/锁定后启动）；仅开放已验证的离散档位。运行中无损调频
不是本批CPU组合链优化的一部分，也不是100 MHz稳定运行的必要前提。

若实现DRP调频，控制状态机必须在固定域运行，CPU独立时钟资源不得使固定外设域失锁。
当前soc_top_ddr把CPU MMCM失锁纳入CPU和AXI桥复位原因，直接启用DRP会破坏运行态。
无损方案需暂停/排空CPU访存及AXI事务、规范停钟、重配/等待锁定、安全恢复，同时重新
设计lock/reset处理及超时回退。不得暂停有在途AXI操作的CPU后复位DDR跨域桥。
DDR PHY/UI频率及校准保持不变，先只考虑DFS，不改板级供电电压。

本批不改顶层时钟端口、Clocking Wizard/MIG配置、reset链或发布bit；第三域桥和实板
100/150 MHz均未验收。MMIO桥准备与CPU关键路径改造分开记录，不能用其局部测试证明
CPU提频或完整Linux运行。

2026-10-02 staged-preparation更新：访存地址OOC终点7.484ns，取指mask11.171ns，
全局PRF12.291ns；真正综合前10ns约束WNS=-2.309ns，约150MHz=-5.642ns，仍未达标。
本批没有新增周期成本，但有面积和若干终点回退，未推广。上述固定外设域、timebase、
启动选频/无损DFS门槛继续有效；没有因为一个访存终点达10ns而改时钟IP、复位或发布bit。

### 2026-10-02：选频准备不替代CPU时序收敛

可调时钟的主要近期收益是同一bit的离散频率试验，不是提高逻辑自身Fmax。
优先启动/复位状态下选频，运行中无损DFS仍是后续独立功能。仅开放已验证档位；
100/150MHz目前都是待验收目标。控制器和调频参考时钟必须位于不被重配置的固定域，
固定外设不能与CPU共用一个会在重配置时失锁的MMCM输出集合。

静态100MHz板级验收并不以第三时钟域实施为前提：若仍采用CPU域UART/timer，必须
同步更新UART时钟参数、BootROM/程序/DTB timebase后再生成和验证真实bit。若要一个
bit在启动时任选不同CPU频率且UART/timebase不变，先完成固定外设域和一致时间基准。
两种方案的证据不得混用；当前仅50MHz发布bit有实板证据。本批保持原板级IP和复位。

staged-payload最新OOC：fetch mask5.318ns、PRF10.503ns，全局LSU回复数据11.818ns，
10ns WNS=-1.836ns、约150MHz=-5.169ns。原translated response FIFO flow=true仍可直通，
下一批优先真正的回复寄存边界和PRF operand链。100/150MHz和第三域/选频均未验收；
本批没有更改时钟、reset或bit。

### 可调时钟取舍：先启动选频，不直接运行态DRP

可调时钟不会提高CPU逻辑Fmax。一个bit开放多档位时，每档仍需真实时钟约束与板级
验收；最高未验收档不能作为回退/正常运行档。启动选频的用途是减少实板频率对比时
反复生成bit，运行时DFS才是独立的功耗/性能管理功能。当前只完成规划，没有启用DRP。

无损DFS的排空不能仅依赖WFI或DataResponseBuffer.idle：后者只覆盖已排队回复。
还须证明ROB/LSU/store buffer、缓存miss/writeback、页表遍历、TileLink/AXI及跨域桥
无在途事务，并停止新请求、保留待处理中断和精确恢复状态。调频状态机及超时回退
由不被重配的固定域驱动；DDR PHY/UI和固定外设时钟不跟着改。UART分频及OS的
timebase必须稳定，64位time值不能逐位跨域同步。先做离散启动档，再独立验证运行态
停止/排空/安全停钟/重配/锁定/恢复；不以直接修改MMCM参数替代这个协议。

时钟IP能力依据：[AMD Clocking Wizard动态重配置](https://docs.amd.com/r/en-US/pg065-clk-wiz/Dynamic-Reconfiguration-through-AXI4-Lite)。

staged-return最新单次OOC：回复寄存切断已证明，LSU data8.995ns/slack+0.987ns；全局
取指回复到下一请求ready反馈11.425ns，10ns WNS-1.529ns，约150MHz-4.862ns。LUT136165，
同BIN CoreMark周期+3.31%、VM等工作量+11.68%，不能只看局部提速。第三域、DRP和
100/150MHz稳定运行仍未验收，本批不改IP/clock/reset/发布bit。

staged-fetch-address更新：一次真实综合前10ns的OOC最差10.890ns、WNS-0.994ns，约150MHz
-4.327ns；LUT129570、FF61439，同镜像周期与staged-return不变。旧地址carry反馈缩短后，
剩余首要链为ROM/TL D-ready→request信用反馈；frontend/RAT10.867ns、PRF10.503ns、RAS
CE10.315ns也未完全达标。未布线报告不是100/150MHz稳定运行的证据，不修改Clocking
Wizard/MIG、复位或发布bit。继续先CPU结构收敛；固定外设域/timebase、启动选频与运行
态DFS门槛仍按上述合同，不能直接启用DRP绕过现有失锁会复位CPU/AXI桥的问题。

staged-fetch-control本批九组必要短测通过，ROM新增两项独立回复信用、raw TL回复元数据
和PC-relative预测资格一起改造。26条完整IPC、VM2525/675、同BIN CoreMark731130与
DDR5295/7714/12987/3847均未变；118SV单次pre-mapping10ns综合与46份DCP查询完成，
全局10.590ns/WNS-0.608ns，约150MHz-3.941ns；LUT129718/FF61440。ROM信用反馈与TL
late-valid lookup切断已证明，但退休→predictor、PRF、RAS及前端setup仍未全过。
这些是未布线且UART/timebase参数仍50MHz的候选，不是实际100MHz板级验收。外设固定
域/timebase/启动选频合同没有被“动态调频”建议替换；运行态DFS与第三域仍未实现，
100/150MHz仍未验收，本批不改顶层clock/reset/IP/已发布bit。

staged-recovery-control已经完成三条相关恢复控制链改造及必要短功能范围检查；120SV
单次真实10ns综合868秒、49份DCP查询151秒已完成。30项Scala、810304独立恢复/匹配向量、
ledger8/64tag、NEMU/packet/VM/同BIN板模型均通过，26完整IPC及CoreMark/DDR周期不变。
补充system使用原固定32/direct-IRQ oracle；新旧注册IMSIC封装触发同一零延迟断言，
失败证据保留，生产一拍IRQ的独立时间合同未验收。第三固定外设域、64位time一致性、
启动选频和无损DFS仍按上述门槛，均未实现；本批不修改clock/reset/IP/bit。100/150MHz
目标保持，但不能把局部控制链改善当作达标：全局10.590→10.931ns、WNS-0.608→
-0.949，约150MHz-4.282ns，PRF/pending/redirect回退。LUT-1687至128031、FF61426，
RAS/ROB/ready/predictor改善；仍不推广默认或生成bit。下一批联合优化ready/双发射
操作数、bit-manip/ALU结果选择和completion/PRF写回。导出UART/timebase仍50MHz，
未布线报告不代替实际100MHz整板setup/hold/CDC/RDC及实板运行；动态调频不提高Fmax。

staged-execute-select完成三条相邻执行/写回选择链及必要短测：33Scala、独立rank/
算术/完整payload和原NEMU/system/VM/同BIN板模型通过，IPC及周期未变。121SV单次
真实pre-mapping10ns综合08:31:43启动，结果待测。当前导出仍50MHz/115200，不改
实际MMCM/MIG/reset/bit，不把约束目标冒充实际100MHz配置；100/150MHz整板及实板、
生产注册IRQ时间合同、第三固定外设域/一致timebase/启动选频/DFS仍未验收或实施。

### 多时钟短验证工具门槛（2026-10-02静态审计）

当前GSIM固定于93b8cd23edd3228807c4f2a08c19c3936a463cb2，实际vendor HEAD一致且工作树
无改动。源码clockOptimize.cpp把支持的门控转换为寄存器条件更新；cppEmitter.cpp的
genStep统一调用resetAll和全部subStep后增加全局cycles。当前短测是同步周期级功能
证据，这些代码本身不能证明独立输入时钟的边沿、相位和不等频率已被模拟。

接入固定外设域前，必须先用最小双时钟寄存器探针证明验证引擎能分别推进两个域，
再验收非整数频率比、相位、背压、恰好一次副作用及协调复位。不得把同一step推进
全部寄存器的测试冒充真正双时钟CDC验收，也不得修改vendor或生成DUT绕过这个门槛。
该静态审计不是探针通过，也不是断言所有GSIM版本都不支持多时钟；没有新增桥、测试
或第三域。整板CDC/RDC及IP约束仍需独立检查，数字仿真不能证明亚稳态不存在。
审计证据保存在staged-execute-select/clock-validation-audit.json；CPU100MHz优化继续
等待同一次综合报告，不以这个准备工作替代CPU时序及实板目标。

2026-10-02最小探针已实际运行，命令为GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8
python3 simulator/gsim/clock_probe.py --output independent-clock-probe-20261002-v2。
两个Clock输入与两个16位计数器各自使用withClockAndReset，oracle只按各自0→1边沿
计数。七种案例均不符合：保持低电平16step预期0/0，实际16/16；仅A有32个上升沿
预期32/0，实际64/64；5:3频率比/相位差预期50/30，实际300/300。保持高电平、
仅B、同时边沿和5:7频率比也失败。输出在enable关闭后稳定采样，初始零值、禁止
更新及有使能时进展sanity通过；另测运行后AsyncReset断言，预期0/0而仍32/32。

首轮复用模型在第二案例复位sanity失败，原driver/FIR/日志均保留；后续每个边沿
案例使用新模型，单独验证运行后复位，并未放宽时钟或复位oracle。观察命令exit0
仅表示能力调查结束；无observe的原合同验收明确exit1，结果clock-or-reset-not-supported，
不是CDC通过。GSIM vendor及CPU均未改。该结论限定当前固定版和探针，不宣称所有
模拟器/版本不支持，也不把它当作实板CPU故障或已解决CDC。原始独立双时钟wrapper
不得进入GSIM验收；若后续需要专用多时钟仿真，须先获用户批准工作流例外，不能擅自
启用替代后端。外设桥、固定timebase及100/150MHz目标仍未完成。证据和源码归档于
staged-execute-select/clock-probe；已冻结CPU综合输入保持不变。

### staged-frontend-select：CPU前端优化结果与调频门槛分开

三条前端选择链合并必要短测通过：36Scala、九组、277728独立向量、10负注入；
26完整IPC、VM和同BIN CoreMark/DDR周期未变。当前源码冻结196文件，上一份
staged-execute-select综合仍使用原72源码/121SV快照；新候选没有另起综合。
时序/面积未测，不以功能短测替代100/150MHz整板证据。

近期仍建议固定CPU频率收敛后，再实现保持复位的离散启动选频；运行态无损DFS
另做停止/全事务排空/安全停钟/重配置/锁定恢复合同。UART、timebase及控制器应位于
不会随CPU重配而失锁的固定域；当前第三域尚未实现。没有更改MMCM/MIG/reset/bit，
也没有启用动态重配置。固定版GSIM独立边沿探针失败，专用多时钟仿真的工作流例外
仍待用户明确批准；CPU优化与这个门槛独立推进，不能声称CDC桥已经通过验收。

### 2026-10-02 10:41 停止异常综合（覆盖上文“仍运行”的历史状态）

用户要求“看看为何卡死，过于异常就停住”。已确认staged-execute-select本次
08:31开始的命令行综合在Timing Optimization异常耗时超过两小时：
主日志08:35:35后未写，内部文件08:41:10后未写；3秒采样主线程CPU增加3.109秒，
读/写字节均不变。系统仍有约11GiB物理内存可用，未见内存耗尽或等待磁盘证据。

现场保留520619929字节的timing文本（6490668条c记录），这不是LUT使用量，也不能
仅凭文件大证明因果。怀疑新组合图触发时序优化算法异常耗时，尚未区分RTL触发、
工具缺陷或定位唯一模块；无栈采样，日志未报latch/组合环/多驱动/fatal错误。

已按用户授权停止PID49884及专属辅助进程，10:41:53确认全部退出；GUI PID37688
及原bit未动，未删文件、未另起综合。CLI exit1由人工停止造成，不记作工具自身报错。
无soc_blackbox/soc_candidate DCP，因此不能继续checkpoint查询或宣称新时序/面积。
两批功能短测结论保持，但staged-frontend-select仍未导出/SYN。

诊断、日志/journal/timing哈希及停止证据见
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-execute-select/synthesis-hang-diagnosis.json；
两个候选results.json已更正。建议先做rank/ALU/completion局部定位，未经确认不重跑
整颗SoC。官方debug_log、RuntimeOptimized/no_timing_driven可用于后续经批准的诊断，
但减少/关闭时序驱动的结果不等价于原10ns候选签核。
[AMD2025.1综合设置](https://docs.amd.com/r/2025.1-English/ug901-vivado-synthesis/Using-Synthesis-Settings)。

### 2026-10-02 当前时序状态更新，时钟域方案仍独立待验收

本轮用户授权清理/定位/重开一次综合后，staged-frontend-select单次
RuntimeOptimized预映射10ns综合正常结束（总430.5秒）。同DCP的57报告齐全：
CPD10.295ns、WNS-0.313ns，仍未达10ns；报告查询曾因综合网表lookup计数出错，
仅修复并补齐报告，未改DUT。全局最佳参考更新为本轮“RTL+策略”的度量结果，
不将它视为Default策略下的纯RTL收益或物理100MHz证明。

实际导出仍50MHz/115200双发射；CPU/UART/timebase同域、MIG UI另域的现状不变。
无MMCM/MIG/reset/bit更改，无第三域、启动选频或运行DFS；独立多时钟探针及
专用仿真例外仍未通过/获批，注册IRQ/整板setup/hold/CDC/RDC/上板门槛仍保留。
清理只涉及旧可再生输出，失败现场ZIP可恢复，原DCP/bit/日志/报告保留；
完整更新见docs/fpga-timing-windows.md与staged-frontend-select/results.json。

### 2026-10-02 敏感链批次完成，未引入新时钟域

staged-sensitive-paths三组优化、39Scala/十组必要短测和一次同策略综合完成；
实际导出仍50MHz/115200，CPU/UART/timebase同域、MIG UI另域不变。
取指请求新增两项注册队列/+1请求拍，是同域握手隔离，不是CDC桥或第三域。

59份DCP报告：CPD10.291ns/WNS-0.309ns，仍未达10ns；PRF转正仅48ps，
RAT和PC仍负。全局hold+0.006仅为无物理时钟网络的OOC估算，不是整板hold证明。
未修改MMCM/MIG/reset约束、无DFS/启动选频/route/bit、默认及旧GUI未改。
同BIN CoreMark模型+4.17%周期，不能把薄时序改善当成实板frequency×IPC收益。

独立域探针/专用仿真例外、注册IMSIC时间合同、实际100/150MHz timebase/
UART/固件、整板setup/hold/CDC/RDC及板测仍未验收。详细路径和代价见
docs/fpga-timing-windows.md与staged-sensitive-paths/results.json。

### 2026-10-02 decode-align批次完成：仍不改变时钟域

实际RTL保持50MHz/115200，CPU/UART/timebase同域、MIG UI另域。空物理取指请求
队列flow-through只改变同域请求延迟：满队列仍occupancy-only ready、无pipe信用借用，
不是CDC桥、第三域或运行DFS。未改MMCM/MIG/reset/实际约束/旧GUI/发布bit。

42Scala/12必要短测和唯一425.4秒综合完成，61个DCP报告（一次计数错误后仅补7项）。
10ns WNS-0.196，CPD10.178，PC转正但free/RAT仍负；PRF41ps/scoreboard61ps过薄。
20ns WNS+9.804和OOC hold+0.006都不是整板物理签核。CoreMark周期恢复早期
731130不是实板高频收益证据，候选不宣称100MHz或150MHz。

注册IMSIC temporal、第三域探针/仿真例外、timebase/UART/固件高频适配、
整板setup/hold/CDC/RDC及板测仍未验收。详情见docs/fpga-timing-windows.md及
staged-decode-align/results.json；这一轮没有全GSIM/长Linux/route/bit。

## 2026-10-02：组合重构的10ns观察范围

staged-word-destination（两发射，ROB16/PRF48）完成48项Scala检查、8类受影响短测和一次修正批综合；本次OOC 10ns setup仍未满足。 未route或上板，不能据此宣称实板100MHz稳定。

本轮优化raw rd→rename/RAT与Zba/W→PRF，不新增任何时钟域、寄存器切片、复位链或DFS。报告10ns是OOC综合/查询目标，RTL实际固件/timebase/UART仍按50MHz生成；不能直接用100MHz时钟上板而沿用这些参数。

最终WNS -0.115，setup失败80，WHS +0.006，hold失败0。所有AXI/OOC外部端口边界仍需整板约束/真实MIG与CDC检查；HD.CLK_SRC未定义的估计skew不等于已验证MMCM布线。

默认/发布保持50MHz、115200，未改MMCM/MIG/ROM内容、未生成bit、未跑全量GSIM/长Linux；注册IMSIC temporal、真实DDR/CPU频率变化下IPC、整板setup/hold/CDC/RDC、第三域/DFS及实板高频仍未验收。 详情见docs/fpga-timing-windows.md及E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-word-destination/results.json。

## 2026-10-02：request-capture收尾，动态时钟仍未实现

本批10ns SoC OOC WNS+0.234、setup失败0，native取指RAM WE9.915→1.011ns；
CPU旧家族不变，相同BIN/VM周期不变。ROM回环仍仅234ps，6.667ns WNS-3.099；
这不是整板100MHz/CDC/RDC/实板验收，没有改变任何时钟IP、reset或发布bit。

再次核对已发布clk_wiz_ddr.xci：USE_DYN_RECONFIG=false、
CLKOUT1_REQUESTED_OUT_FREQ=50.000；soc_top_ddr仅连接clk_in1/clk_out1/reset/locked，
没有DRP端口/运行态控制器。UART、MachineTimer仍跟CPU同域；MIG UI250MHz及异步
AXI converter是既有第二域，不是第三固定外设域。当前MMCM失锁会断言CPU与UI侧
AXI bridge复位，不能把直接开放DRP称为无损DFS。

第三固定外设域、一致timebase、离散启动选频和运行态排空/停钟/DRP/锁定/恢复
均是待实现合同。建议先固定UART/timebase并验证CDC/RDC，再做复位状态下选频；
运行态DFS另需完整ROB/LSU/cache/PTW/TL/AXI drain与独立固定时钟FSM。
上述规划不影响本批源码/短测/OOC签收，但不能回答为“动态时钟已做好”。
