# Ethernet 接入台账（2026-10-04）

最新可选 `managedPeripherals=true`：native GMAC CSR/APLIC5、GMII帧引擎、原packet DMA
四条流与独立TX/RX CDC已接生产BoardSoc；CMU管理UART/TX/RX叶子钟。短功能/门控CDC通过，
组合外设OOC内部时序达标，仍无RGMII/RTL8211F上板/driver/bit签核；5条CDC Critical和
边界hold违例不隐藏。完整接线/配置/排空/计数/证据见
[受管外设接入](../../docs/managed-peripherals.md)。以下章节保留原批次记录。

## 自研 GMAC：千兆优先，10G/SFP1 延后

用户确认不依赖缺失硬件许可的 TEMAC，改为自研 MAC；先跑通板载 PL RTL8211F 千兆，
未来 10G 先用 **SFP1**，光模块尚未选定。新代码位于 WSL 主工程
`src/main/scala/ip/ethernet/`，没有导入第三方 MAC，也未改旧 Vivado 工程或 bit。
原 `EthernetSocTop` 仍是下文的 AXI Ethernet 候选，不是假称已经替换。

第一批完成 native TL-UL CSR、并行 8/64-bit CRC32、MDIO Clause22 公共模块与软件 header，
初始短验收 `build/gsim/self-gmac-20261004-r2/receipt.json` 为 `passed_foundation_only`。
最终 r3 全部通过，补 TL→MDIO 4 帧/23请求/462拍 busy 背压、noAck/IRQ/复位及独立位序负例，
`build/gsim/self-gmac-20261004-r3/receipt.json` 状态仍为 `passed_foundation_only`。
完整 SV 导出已做；不重复 CPU 验证/综合。后续帧与单时钟 DMA 联动已通过，见下节；
仍无新的 CPU 时序、RGMII/持续线速或整板 bit 证据。
寄存器/帧/复位合同见 [DMA](../../docs/dma.md)、
[MMIO](../../docs/soc-registers.md#自研-gmac-控制器独立-ip未接板级)。

### 已核对的 PL 千兆接线

已视觉检查用户提供的载板原理图第4/7/8页和核心板第6页；厂家
`12_UDP_TEST/.../pin.xdc` 的全部 RGMII 数据/时钟管脚与原理图一致。
此前未在厂家 XDC 找到的 MDIO/MDC/PHY reset 现已跨 J5 追到 Bank66，
保存为 `self-gmac-board.json`；**本批不直接修改板级 XDC**。

| 信号 | 载板 J5 / 核心网 | FPGA ball | 说明 |
| --- | --- | --- | --- |
| PHY2_MDIO | 87 / B66_L5_P | Y12 | 1.8V，双向 IOBUF，载板已有1.5K上拉 |
| PHY2_MDC | 85 / B66_L6_N | Y9 | 1.8V，输出；最高2.5 MHz |
| PHY2_RST | 83 / B66_L22_N | Y11 | **输出1复位、0释放**；经过 Q10 反相，不是直接 PHYRSTB |
| PHY2_RXCK | 93 / B66_L12_P | AA7 | RGMII RX 输入，真实125 MHz接收域，不接CPU时钟 |

载板 U3 为 RTL8211F-CG、RJ2；图中 PHY 地址为 `001`（1），RXDLY/TXDLY 均上拉。
这是原理图的初始 strap，需上板读取 ID/页寄存器确认，不假定实际延迟已经配对正确。
必须明确只加一次 RGMII TX/RX 延迟，并把最小/最大 I/O 延迟约束写进候选，不能只看
CPU WNS。复位源是上拉的 MOS gate，保持/释放时序应由独立寄存输出和域内同步器管理。
原理图 PHY 本地 25 MHz 晶振 Y2 标 NC，参考由 AD9523 OUT11 / `PLL_PHY2_CLK` 提供；
载板第8页自动配置表标25 MHz。上板应先测/确认它有效，再排查 MDIO/协商。
不能把无 PHY 参考时钟误判为 MAC CRC 错误。

### 10G 后续：仅保留 SFP1 接线证据

载板第2/14页、核心板第7页视觉核对：SFP1 使用 GTH Bank129 channel0；
TX P/N=K29/K30，RX P/N=L31/L32，REFCLK0 P/N=L27/L28。
载板第8页 Y5 为独立 SiT9120 156.25 MHz，经 AC 耦合接 `129_CLK0`，不是表中
标 NC 的 AD9523 SFP 输出。厂家 IBERT 的 SFP TX_DISABLE[0] 为 A12，但未来启用前
仍须核对全部辅助信号、模块能力/功耗和 GTH 站点。当前没有选模块或使能光口。
设计矩阵可选择 `Xgmii10G` 64-bit / 156.25 MHz **接口合同**，不等于实现 MAC、
64b/66b PCS、10.3125 Gb/s PMA 或上板验证；本批不接这条通路。

### 第二批：自研千兆帧与 DMA，单时钟验收通过

`GmiiFrameTx` / `GmiiFrameRx` / `EthernetDmaFrameAdapter` 为原项目实现，
每方向2KiB同步帧RAM、32-bit原生帧。TX 整帧收齐后连续发出 preamble/SFD、
至少60字节帧体、FCS、12-byte IFG；RX 校验全帧后才交 DMA，错误/溢出完整丢弃。
RX保留padding、不剥VLAN；无pause/10/100/多播表。单缓冲会丢弃缓冲持有期间的新帧，
不是持续线速。完整字段/完成事件和限制见 [DMA](../../docs/dma.md)。

`build/gsim/self-gmac-frames-20261004-r3/receipt.json` 最终通过：帧246例、
适配96例、真实DMA联合54例/四项信用；三独立负例通过，完整 SV 导出。
不运行CPU/NEMU/全量GSIM/长Linux/xsim。联合模型仅一个时钟与外部字节内存，
不因此宣称真正 PHY、跨域、CPU cache或DDR验收。原DMA和生产默认配置未变。

第一次 RX 双写端口使2KiB同步帧 RAM 展开为34413 LUT/16766FF/0BRAM；
已停止自己的该次原生模块布线（不是用户GUI），保留 TX 已通过 route 和 RX synth。
改成单一写端口后必要短检查全部复验通过；新 CAD 只重跑 RX 和尚未跑过的适配器，
TX 全部 RTL 依赖逐文件字节一致才复用 route。原生目录
`E:\VM\Share\Valence-rtl\self-gmac-frames-20261004-r{1,2}`；
轻量入口 `fpga/vivado-self-gmac-frames.tcl`，TX/RX 8ns、适配器10ns，
最终结果由 `fpga/audit-self-gmac-frames.py` 检查：
`build/fpga/self-gmac-frames-20261004-r1/audit-final.json` 为
`PASS_GMAC_MODULE_INTERNAL_OOC`。逐文件哈希核对的必要 RTL/报告/DCP 已归档到该目录
`native-results/`；原 RX 失败的 RTL/综合报告/DCP 保存在 `rejected-ram-inference/`。

| 模块 | 周期 | 内部 setup / hold 裕量 | post-route LUT / FF | RAMB18 |
| --- | ---: | ---: | ---: | ---: |
| TX | 8 ns | +5.144 / +0.045 ns | 268 / 178 | 1 |
| RX | 8 ns | +4.747 / +0.052 ns | 245 / 271 | 1 |
| adapter | 10 ns | +8.077 / +0.046 ns | 52 / 43 | 0 |

RX 同阶段综合已降至255 LUT / 271 FF / 1 RAMB18；以上 route 值合计565 LUT /
492 FF / 2 RAMB18 / 0 DSP，仅统计这三个模块，不含 CSR/MDIO/原 DMA/CDC/PHY。
此处零 I/O delay 只是模块比较，边界 hold 为 -0.049/-0.089/-0.032 ns，
不是 RGMII/CDC/整板资格，也没有新的 CPU 时序、IPC 或 bit 结论。

### 下一批物理集成与联合验收边界

2026-10-04 CDC 批次已独立通过：`EthernetFrameClockBridge` 完整帧位域、
`EthernetConfigClockBridge` 原子配置、`CdcAccumulator` 可靠累计事件与常开 retention
clock policy，短三时钟/暂停/背压/回绕/排空/唤醒/超时/共同复位及四独立负例通过。
证据 `build/fpga/self-gmac-cdc-20261004-r1/functional-r4/receipt.json`。
该 wrapper 仅 CDC/控制策略，不实例化帧引擎、DMA、PHY 或 CPU；不得算作完整三域网口联调。
52-bit 配置的 TX/RX 接受共同准入，但两个实际帧边界 ACK 仍需生产管理器确认。
累计 delta 要接64-bit统计，不可把多事件 delta 缩成一次旧 CSR pulse；清计数也须有明确 epoch。
generic 停钟策略不是 GMAC 排空证明：packet DMA 与全部 frame/config/event CDC 须明确合并 idle。
实现与软件/门控边界见 [时钟域台账](clock-domain-plan.md)。

同批小型 CDC OOC 布线和同 DCP 约束复核已完成，最终
`build/fpga/self-gmac-cdc-20261004-r1/audit-final.json` 为
`PASS_SCOPED_CDC_RETENTION_MODULE_OOC`：内部 setup +6.268ns、hold +0.042ns，
全部227个CDC端点明确max-delay、10组skew最小 +7.472ns，Critical=0。
236 LUT/671FF/48 LUTRAM只属于含16-bit测试累计器的CDC/retention wrapper。
真实门控原语、HD.CLK_SRC、I/O预算及完整网口仍未接入，Warning未隐藏；不生成新bit。

已完成上述数字帧/DMA 单时钟边界，接下来成组实现 RGMII DDR I/O、原生帧 CDC、
配置快照/事件CDC及可选SoC后端路由，再统一短功能检查。数字帧验证用 GSIM，
独立时钟 CDC 仅用此前授权的短 xsim；通过后一起综合，不为本批基础 CSR 再跑整板。
TL 控制在 CPU 域或显式管理域；TX 为125 MHz，RX由PHY提供。事件和配置快照都需
安全 CDC，不只两拍同步多位字段。新后端 IRQ、互斥 MMIO、PHY初始化与驱动/DT须明确落实。
单时钟适配器拟留CPU域，两条原生32-bit帧流带keep/last/bad跨域，
不必沿用旧TEMAC四路流CDC；但新拓扑未实现，旧FIFO/CDC证据不能自动借用。
原64-bit / 100 MHz 标量DMA理论入口仅800 MB/s，还需扣除一致性/请求开销；
不承诺1G实测线速，更不承诺10G。CPU内部 +0.290 ns 是下文旧候选证据，不替代新完整网口签核。

## 原 AXI Ethernet 候选（历史记录，保留）

本轮是独立候选，不修改 ZU15EG GUI 工程、Clock Wizard、DDR IP、已有整数 100 MHz bit。
新增控制接入已写入 WSL 原工程；不等于已完成网卡、Linux 驱动或上板时序签核。

## 配置与边界

- Vivado 2025.1、`xczu15eg-ffvb1156-2-i`，AXI Ethernet v7.2 Rev.23。
- RTL8211F 使用 RGMII、1 Gb/s 模式；不是 2.5 Gb/s。
- AXI-Lite、四路 32-bit AXIS、GTX 使用固定 125 MHz；RGMII 接收时钟由 PHY 输入，不能直接接 CPU。
- UltraScale+ 延迟参考时钟为 **333.333 MHz（3 ns）**，匹配该次 IP 实际
  `REFCLK_FREQUENCY=333.333`；初次 300 MHz 假设产生告警，已在最终综合修正。
  CPU 目标 100 MHz，issue=2，但本批 CPU 布线未达标。
- TX/RX 内部缓冲各 4 KiB，不启用 AVB、1588 和 checksum offload。
- `EthernetSocTop` 有 CPU/以太网/参考时钟、DDR AXI、四路 packet AXIS、RGMII 与拆分的 MDIO i/o/t。
  它是集成综合边界，不是最终板级顶层：MIG、时钟 IP、MDIO IOBUF 和完整板级 XDC 仍在边界外。
- DMA 必须接全 TX data/control 与 RX data/status 四路，并明确描述符、缓存维护和中断合同。
  基线不含报文 DMA；后续新增的自研 `packetDma=true` 候选已接通四路及 coherent 内存入口，
  默认仍关闭。尚无 Linux 网络驱动/设备树网卡节点或真实板级收发验收。

## 可选 MMIO 与 CDC

`BoardSocTop(..., peripheralClockHz=125000000, ethernetControl=true)` 才增加接口；默认关闭，
旧配置端口、默认整数 ISA 与实验性 F/D 开关均不变。

| 资源 | 分配 | 合同 |
| --- | --- | --- |
| Ethernet 控制窗口 | `0x10040000`–`0x1007ffff`，256 KiB | native IP 的 18-bit AXI-Lite 本地地址 |
| 中断 | APLIC source 5 | `interrupt OR mac_irq` 持续电平同步到 CPU；UART=3、现有 DMA=4 |
| 定时器 | CPU 域 | 100 MHz timebase 不因外设域改变 |
| UART | 125 MHz 外设域 | 460800 baud，控制/IRQ 跨域；不是动态调频 |

控制路径为 CPU DataPort → 原并行 MMIO 路由 → RegisterPort →
`RegisterClockDomainBridge` → `RegisterAxiLite` → native MAC。
桥容量 1 个有序事务；共同复位可取消在途访问，两端各三拍释放，不支持独立热复位。
Ethernet IRQ 同步器复位使用 CPU 域释放后的 `sourceReset`。
所有 MAC 复位额外保持至少 32 us，覆盖低速 MAC 的复位保持要求。

AXI-Lite 适配器 AW/W 独立握手，不等待 READY 才发 VALID；读响应与写响应独立等待，
反压时请求/响应保持。支持同一个 32-bit word 内的 byte/half/word，自动转换
RegisterPort 的右对齐数据和 AXI 字节通道；64-bit、跨 word、越界请求本地报错，不发 AXI。
必须用共同复位同步取消适配器和 slave 的事务；不提供丢响应超时或热复位重放。

## 本轮 CPU 三项优化

### 后续取指反馈候选（2026-10-04，未推广）

`staged-fetch-feedback` 继承 `staged-ethernet`，只增加
`capturedFetchPermission` 和 `splitFetchCursor`，仍默认关闭、issue=2。
PMP 四字节执行检查从 architectural PC/rename 反馈链提前到 raw supply 入队边沿，
与指令一起捕获；虚拟取指仍由原物理翻译适配器授权。
PMP/SATP/xRET 的 ROB-head 屏障和 trap/恢复重定向必须清除所有旧上下文条目。
正常游标与纠错游标分为两个寄存 bank，纠错 bank 无条件捕获，寄存选择器下一拍生效；
不新增流水拍、不借用 decode acceptance 驱动正常游标 CE。

独立权限撤销固件发现本候选的 PMP-only 精确异常地址问题：当原取指没有报错时，
不能使用对齐器的备用 second-half 地址。现改为该 raw 指令的真实 PC；
原第二半字访问/页故障仍保存原来的 fault address。此项属于候选修复，不放松 oracle。
固件 trap entry 必须四字节对齐；混合 16/32-bit GNU 汇编代码在 `.option norvc`
下的两字节填充未生效，改用局部 RVC 对齐作用域，并在 ELF 符号层再次检查。
失败诊断记录保留，不能把早期未完成的整批 receipt 当作通过证据。

本候选短验收 `build/gsim/fetch-feedback-20261004-r5/receipt.json` 已通过：
13 项真实 CPU 同二进制 NEMU A/B 周期不变、50 项控制/访存与 11 项恢复检查，
以及实际 board RV64GC/权限撤销固件。权限固件 trap cause=[9,1,9]、mepc/mtval
与真实 raw PC 匹配，并检查 compressed retirement；没有提前声称 100 MHz 达标。

`staged-ethernet` 继承 `staged-gmac-ready`，仅打开三项组合结构选项：
`balancedPacketPmp`、`compactMemoryOperandSelect`、`parallelMemoryAddressSum`。
目标为缩短 PMP 大位宽比较串行链、先选择访存源 ID 再读 PRF、使用分块进位地址加法。
不增加流水拍；原 owner/rank、精确异常、恢复 token 和顺序提交策略不变。

短 GSIM `build/gsim/ethernet-stage-20261004-r2/receipt.json`：
算术 10900 向量；PMP 16 定向、6000 随机、30840 边界；AXI-Lite 240 事务
（AW-first/W-first、读写反压、错误与复位）；所有独立负对照能拒绝注入错误。
双发射真实 CPU 同二进制 A/B 共 13 项、8804 提交，周期全部相同；
50 项控制/访存 NEMU 烟测与 11 项恢复检查通过。因此本批短集没有 IPC 损失或收益，
频率与资源改善须另看本轮布线，不能借用旧 +0.090 ns 报告。

IRQ 释放修正发生在上述裸核测试之后，仅影响新 Ethernet 开启分支；
配置/复位合同测试和后续 production RV64GC 机制烟测使用修正后的源码。
裸核不覆盖压缩取指、整板缓存、MAC 报文、独立输入时钟或 Linux 浮点调度。
独立时钟 CDC 模块沿用上一轮短 xsim 的证据；新完整集成没有跑整板仿真。

## 原生工程与授权

生成工程：`E:\VM\Share\Valence-rtl\axi-ethernet-20261004-r1\ip-project-licensed\ethernet_ip.xpr`。
生成脚本 `generate_ethernet_ip.tcl`；真实 IP 综合检查 `synth_ethernet_ip.tcl`。
本轮 CPU/SoC 联合综合入口 `vivado_ethernet_batch.tcl`，只综合 CPU 一次，导入真实
CPU 分区、原生初始化 ROM 与 Ethernet IP；要求没有残余功能黑盒，然后仅对 CPU OOC 布线。
这是集成综合加 CPU OOC 比较，不是包含 MIG/PHY 管脚的整板 100 MHz 签核。

用户提供的许可证只传给候选进程的 `XILINXD_LICENSE_FILE`，不安装或修改全局环境。
2026-10-04 11:48，MAC 子 IP 与 Ethernet 顶层真实综合完成；
`post_synth_ip_status.rpt` 仍显示 TEMAC 与 AXI Ethernet 为 `Design_Linking`。
**这不证明可生成含 MAC 的 bit**；后续上板仍需有效 Hardware Evaluation/Full 授权，
不使用黑盒替身、删许可属性或绕过检查。

用户随后要求继续优化并生成完整 bit。2026-10-04 15:52，本轮在独立 Vivado
查询工程重新导入真实 XCI，使用同一用户提供许可证，未综合或修改原 IP。
`USED_LICENSE_KEYS` 的 implementation / synthesis 仍为
`tri_mode_eth_mac@2015.04 design_linking`；`report_ip_status` 的顶层 AXI Ethernet
和 TEMAC 子 IP 均仍为 `Design_Linking`。该许可证仅列 Vivado/HLS 产品，
没有 TEMAC 硬件授权。因此本轮整板实现/bit 尚未启动，不能把 CPU OOC 通过当作
含 MAC 整板可发布；需要用户提供有效 TEMAC Full/Hardware Evaluation 授权，
或明确批准先交付不含 MAC 的 CPU/FPU/DDR 板级候选。不会静默移除网口或更换 MAC。
新记录保存至 `build/fpga/ethernet-bit-preflight-20261004-r1/`，
查询脚本为 `check_ethernet_license.tcl`；旧综合/布线验收和旧 bit 保持不变。

厂家 `12_UDP_TEST/.../pin.xdc` 的 RGMII 管脚已找到；MDIO/MDC/PHY-reset
没有在该 XDC 中找到，尚未猜填。TX/RX 的 RGMII 延迟、PHY strap 和复位也需逐项确认。

## 最终结果（不推广）

严格记录：`build/fpga/axi-ethernet-20261004-r1/audit-final-r1.json`，状态
`FAIL_CPU_INTERNAL_TIMING`。本次 CPU 仅综合/布局/布线一次；脚本链接层次错误由
已有 checkpoint 恢复，没有重新综合 CPU。随后只修外设并重新综合外围：
MAC/UART IRQ 各在源域寄存，MAC reset 使用 `ResetHold` 的单一寄存输出，参考时钟改为 3 ns。
导入缓存 CPU 前，所有 103 个递归依赖 RTL 模块逐文件 SHA-256 完全一致。

| 对象/指标 | 结果 | 限制 |
| --- | --- | --- |
| 全 F/D、双发射 production CPU OOC 10 ns setup | **WNS -1.512 ns；TNS -10921.530 ns；22715 失败终点** | 未达标，不发布 100 MHz |
| 同一 CPU 内部 hold | +0.024 ns | 全/边界 hold -0.046 ns，仍不是整板 I/O 签核 |
| CPU 布线资源 | 141077 LUT、41191 FF、41 DSP | 与旧裸核 OOC 的端口裁剪不同，不作纯资源收益 A/B |
| 真实 MAC/ROM/CPU 集成综合 | 零未解析功能黑盒，完成 | 仅综合，无 MIG/PHY 管脚整体布线 |
| 新完整集成综合资源 | 197884 LUT、84698 FF、41 RAMB36、41 DSP | 包含 ROM、缓存、APLIC/IMSIC 和 MAC；不是板级最终值 |
| 其中真实 Ethernet 子系统 | 3940 LUT、5836 FF、4 RAMB36 | 仍有 Design_Linking 许可限制 |

当前最差链为 `core/pc_reg[4]` → packet PMP →
`core/fetchPacket/supplyPc_reg[57]/CE`，34 级，数据延迟 **11.407 ns**，
逻辑 2.590 ns、布线 8.817 ns（77.294%）。新的分段组合逻辑并未达到目标；
不能因短测试周期不变而称为频率×IPC 的正优化，也不能只放宽约束宣称 100 MHz。
下一批应优先切开 PC/PMP/packet-ready 的反馈使能链，明确新增前端准备拍的恢复/IPC 成本，
并同时处理高 fanout 和 32 项 hint 表的布局成本。暂不再盲跑相同候选。

复位验证：`build/gsim/ethernet-reset-20261004-r3/test.log` 同步计数/IRQ
1280 检查、20 reset epochs，负对照通过；实际 `soc-rtl-r2/ResetHold.sv` 的短 xsim
5 epochs、4000 本域边沿的异步断言/保持/精确释放通过。不把固定版 GSIM 混合异步复位
模型的时步问题作为 RTL 通过证据。

最终 CDC 报告：83 个 CDC-3、4 个 CDC-9；两条源域 IRQ 的 CDC-10 已消除。
仍有 **1 条 CDC-10 Critical**：`soc/ResetHold/held_reg` → 厂家 MAC 内部隐藏复位同步器，
报告显示厂商 false-path；必须继续检查 MAC 复位拓扑/释放合同，不因其在 IP 内部而豁免。
498 条 CDC-15、1 条 CDC-17 为保持/握手结构，另有 1 条 CDC-26；这些告警没有整体 waive，
新集成尚未布线，因此不能宣称所有 CDC 最大延迟、bus skew 或 PHY I/O 时序通过。
RGMII 原生 IP 已创建 8 ns RX 输入时钟；本次额外同周期命名产生 override 告警，
后续脚本移除冗余定义并改为校验 native 真实 RX 时钟，不重跑 CPU。

默认 profile、默认 F/D 关闭和原 bit 不变。`EthernetSocTop` 默认 ISA 也使用
`BoardSocConfig.isaProfile`；本轮验收显式选择 `rv64gc`，不是默认启用 F/D。
固件、时钟 IP、MDIO IOBUF/管脚、DMA 上板/性能、Linux driver/DT、TEMAC 上板授权仍需后续完成。

## 是否必须 DMA / 现有 DMA 能否复用

MAC 原始 AXI-Stream 不强制连接 DMA：硬件包发生器/检查器，或补上 CPU 可访问的
包 FIFO 与完整收发控制，也可以收发。当前 AXI-Lite 只配置 MAC，内部 4 KiB FIFO
不是已映射的 CPU 报文窗口；目前尚未实现这种 PIO 通路。
四路 TX data/control、RX data/status 的握手、包尾和状态必须同时处理。

若复用 Linux AXI Ethernet 驱动，采用标准 AXI DMA 的 TX/RX + SG/描述符通路；
还需 DDR 仲裁、跨域、DMA 映射/缓存可见性、IRQ 和设备树，不是只加一个 IP 即可。
[AMD 驱动说明](https://xilinx-wiki.atlassian.net/wiki/spaces/A/pages/18842485/Linux)
明确驱动假设硬件连接 DMA。

2026-10-04 本批开发前核对：`MachinePlatform` 为 `new MemoryCopyDma()`；
默认描述符范围 `0x80010000`–`0x80010fff`，与板级 `0x80200000` RAM/DDR 不匹配。
现有 IP 是 RegisterPort 内存到内存拷贝，没有 AXI-Stream、包尾、字节尾部或 SG。
它不能直接用于网卡；旧 bit 的软件仍应禁用板级复制。用户随后要求完善自研 DMA，
新源码已修正复制窗口，并新增可选 `EthernetPacketDma`，不是标准 AXI DMA/SG。
新通路为 CPU/coherent home ↔ 64-bit DMA ↔ 四个 CDC FIFO ↔ 实际 MAC 的四路 AXIS；
APLIC 6、MMIO `0x10002000–0x100020ff`，每方向 2 KiB staging RAM / 一个描述符。
组合短验证及联合综合记录以新 receipt 为准；旧基线结果保留，不冒充新功能上板证据。
详细编程/错误/复位合同见 [DMA](../../docs/dma.md) 与 [MMIO](../../docs/soc-registers.md)。

## 自研 DMA / TileLink 最新短验收

`build/gsim/ethernet-dma-20261004-r7/receipt.json` 已通过：154 组收发/错误/IRQ，
三种子真实 CPU cache/coherent home 的脏 TX 探测和 RX 失效、复制 DMA 48 组，
RAM 256 mask / 2048 beat、AXI 部分写 521 笔及旧单拍 512 笔，独立负例均拒绝错误。
实际 `EthernetSocTop` 已经 firtool 完整生产 RTL 导出；软件 helper 交叉编译通过。
生产导出暴露的冷复位 async/sync 混接已修复：CPU 保留同步复位合同，
以本域同步释放后的 guard 电平驱动，CDC FIFO 两端共同冷复位。

新候选冻结为 `build/fpga/ethernet-dma-20261004-r2/`，Windows 临时 CAD 目录
`E:\VM\Share\Valence-rtl\ethernet-dma-20261004-r2`；CPU 从同一 production SoC
递归提取 104 个字节一致的依赖模块。只进行一次 CPU 综合/布线和外围联合综合，
真实 ROM/MAC 保留；不生成 bit、不修改旧默认。新 CAD/CDC 结果须看本批审计，
上述旧 -1.512 ns 报告不能自动沿用为新候选结果。

本批真实联合综合已完成，零未解析功能黑盒；资源为 200903 LUT / 85740 FF /
43 RAMB36 / 41 DSP。其中 `EthernetPacketDma` 为 1805 LUT / 729 FF / 2 RAMB36 / 0 DSP；
仲裁、CDC 及平台改动不包含在 DMA 模块自身数值中，不能把整机差值都归于 DMA。
四个 FIFO 的八组 Gray 指针均命中 scoped 8 ns max-delay/bus-skew（每组5 bit），
但这是已应用约束，不是布线后通过。CDC-only xsim 4 组时钟比、1200 事务、16384 beat
及独立负例通过；记录 `native-results/cdc-xsim-r1/receipt.json`（归档完成后可读）。

新联合 CDC 报告仍未签核：CDC-1=47、CDC-10=7、CDC-13=72 个 Critical，
主要涉及 guard 冷复位进入释放同步器、分布式异步 FIFO 数据到 BRAM/寄存器；
另有 CDC-6=8、CDC-15=740、CDC-17=1、CDC-26=39。Gray 指针正确及数字短仿真
不能替代这些数据保持/物理延迟/复位拓扑的签核。没有 waive，不能称为可上板网口版；
后续应成组完善 FIFO 本域输出边界、冷复位源域结构和物理约束，保留独立 CDC oracle。

本批 CPU 最终审计 `build/fpga/ethernet-dma-20261004-r2/audit-final.json` 为
`PASS_CPU_INTERNAL_OOC`：全 F/D、issue=2、10 ns 内部 setup +0.290 ns / hold +0.024 ns，
CPU 141737 LUT / 41259 FF / 41 DSP；同 production 端口旧基线为 -1.512 ns / +0.024 ns、
141077 LUT / 41191 FF / 41 DSP。setup +1.802 ns、LUT +660 / FF +68，无额外流水拍，
但人工短集合周期不变不能证明 CoreMark/Linux 性能已经提高。
最新最差为 head→earlyStorePayloads owner/PRF→storeAddress/range→storeSafeRange，
22级、9.691 ns，逻辑2.133 ns / 布线7.558 ns；head fanout406、PRF局部网 fanout64
有2.103 ns单段布线，后续裕量优化仍应针对局部控制/布局而非只看级数。
全部/接口 hold=-0.049 ns；CPU内部通过不是整板、DMA路由、PHY或新GC bit通过。
必要原生输出、输入及审计工具保存到该批 WSL `native-results/`，逐文件 SHA-256 已匹配；
没有更换旧 profile/默认F/D或生成新bit，也没有重复CPU综合/布局布线。

参考：[PG138 时钟接口](https://docs.amd.com/r/en-US/pg138-axi-ethernet/Ethernet-System-Interface)、
[PG138 授权](https://docs.amd.com/r/en-US/pg138-axi-ethernet/Licensing-and-Ordering)、
[RTL8211F](https://www.realtek.com/Product/Index?cate_id=786&id=3975)。
