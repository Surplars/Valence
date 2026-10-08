# 当前性能与证据边界

## 2026-10-08：dot 增量交接的本地接续

本次交接接续于隔离的开发工作区，
基线 `6c8977f684830137fae088d4679f9d84e5ce4a11`。交接的累计补丁已核对 209 个文件，
逐文件哈希零差异；原始包保存在 `build/handoff-20261008/archive`，Windows 原包未删除。
交接包原状态是部分验证，不是发布版；旧 SATP 失败和平台任务失败记录不作为本轮测试结果。
不要在当前工作分支再次应用原累计补丁，也不要覆盖原 `main`。

显式候选为双发射 / LSU2 / RV64GC / CPU100MHz / UART460800 / DDR2GiB，
32KiB I-cache + 32KiB D-cache、MSHR2、DDR4槽 / 写槽2、两项写回信用，
启用 compact tags、identity request flow、banked ROB、共享 store 读口、LVT PRF、下一行数据预取。
受管 GMAC 导出另显式选择 frame2048 / MAC RX4 / posted RX4 / memory credits4 / posted TX4。
构造器默认配置与实验开关没有改变；不能省略参数后把默认导出叫作该候选。

本轮已通过：15 项 Scala suite；PRF 48/64/128 容量；预取开/关的权限上下文与
真实 MPRV 后继 load 精确异常、晚 ReleaseAck、DMA probe、flush/reset；
GMAC posted TX 0/1/4 槽、实际字节/FCS、32KiB 目录与 dirty-cache 一致性；
BootROM 可移植验证、Linux 网络软件 23 项、ROM profile/MIF 审计 4 项。
预取最终回执 `build/gsim/data-prefetch-handoff-20261008-r2/receipt.json`；
PRF 回执 `build/gsim/prf-handoff-20261008-r1/receipt.json`；
网络回执 `build/gsim/network-tx-handoff-20261008-r1/receipt.json`。

预取模块的 64KiB 流读由 75026 降至 71113 拍（吞吐约 +5.5%），chase 未改善；
这是 cache/home 模块的相同输入对照，不是整 CPU、Linux 或上板增益。
同一完整 CPU 模型的 RV64GC/Sv39/32 FPR 状态机制、单迭代 CoreMark CRC 和
64KiB steady memory 已通过。CoreMark 444600 ticks，**单迭代不是有效分数**；
新编译的 guest 未与归档 guest 做字节相同对照，不能据此宣称整 CPU 提速比例。

| 当前 CPU 定时区域 | 周期 | ROI IPC |
| --- | ---: | ---: |
| READ 64KiB × 3 | 279735 | 0.197884 |
| WRITE kernel | 344154 | 0.160780 |
| WRITE flush tail | 17860 | 0.000560 |
| COPY kernel | 641916 | 0.124527 |
| COPY flush tail | 9215 | 0.001085 |
| dependent chase 3072 hops | 231189 | 0.016649 |

这些是固定独立 AXI 主机（读延迟32拍、beat间隔1拍、WLAST 后32拍 B响应、背压）的
真实 CPU GSIM 周期，保留 flush 尾部和后备内存逐字校验；不是 MIG 物理带宽。
当前结论仍不能保证双发射 IPC≥1。完整候选短批回执位于
`build/gsim/incremental-handoff-20261008-r1/receipt.json`，以该文件的最终 status 为准；
BootROM backing-only 损坏检测、外部应用返回锁以及两次诊断往返全部通过；
后者实际执行内置短 CoreMark 和 512B DMA，独立核对64次读取/写入，恢复栈、gp、CSR和返回状态。
完整候选回执最终为 `PASS_SELECTED_BOARD_FUNCTIONAL`（6 项短集成执行，含错误 ISA anchor、
后备内存损坏和 cache 掩盖检测等独立负对照）。

新入口 `simulator/gsim/incremental_acceptance.py` 冻结源码，只生成/编译一个模型，复用对象做短验证；
`--resume` 核对所有检查点。仅审阅后的 CoreMark harness-only 修正可以显式刷新，
旧失败回执保留，硬件模型不重建。两个原预取失败是无效 fixture 调度，修正未改 RTL 或弱化 oracle。
CoreMark 的小 guest 全驻留32KiB后，测试返回 stub 真实执行 `fence.i`，再要求 DDR 写回，
不通过修改 cache 元数据伪造流量。

新受管 RTL 已导出至 `build/fpga/incremental-20261008-r1/rtl`，候选组装器为
`fpga/zu15eg/stage_incremental.py`。当前只准备下一轮物理输入，不启动整板布局布线。
本轮物理时序/资源尚未测量；
旧板级正裕量不属于该候选。Linux 新 driver 的内核模块编译、新固件、真实板卡网络和
Linux 浮点调度仍未验收；未生成 bit、未自动 commit/push。

以下为各自冻结输入的历史记录，不替代这次增量候选验收。

最新受管外设组合：UART50/AON50、CPU控制侧100、GMAC TX/RX125MHz，真实引擎/DMA流
已接可选BoardSoc/CMU。必要短GSIM、独立边沿CDC-only xsim通过，组合OOC只综合/布线一次：
内部setup/hold=+3.018/+0.031ns，3964 LUT/4503 FF/2 RAMB18/3 BUFGCE；13组skew最小+7.107ns。
CDC 5条Critical仍保留，零I/O预算整体hold=-0.555ns，不是整板/RGMII/PHY或新bit资格。
不推导CPU/FPU Fmax或IPC增益；详见 [受管外设验收](managed-peripherals.md)。
下方CMU独立银行及其他各批次数据为历史证据。

2026-10-04 独立CMU批次：`src/main/scala/ip/clock/` 提供常开CSR、原生TL-UL、CPU寄存器CDC，
以及SYNC BUFGCE与本地排空ACK后端。可选BoardSoc窗口`0x10080000`/APLIC7，默认关闭；
CPU/TIME/UART/DDR/GMAC保护，无动态调频/热复位/掉电。四项Scala、四小模型GSIM共1323事务
和四独立负例通过；真实BUFGCE模型的CDC-only xsim三组时钟、脉宽/停钟保持/唤醒/失钟超时
及独立负例通过。回执 `build/gsim/clock-management-20261004-r2/receipt.json` 与
`build/fpga/clock-management-20261004-r1/functional-r3/receipt.json`，综合哈希审计
`build/fpga/clock-management-20261004-r1/audit-final.json`。固件header交叉编译通过。
未重综合CPU/整板，无新IPC/Fmax/功耗结论或新bit；只增可选平台入口，执行流水与DMA未改。
现有外设真正可关钟仍需真实排空/隔离/唤醒接入；详见
[当前时钟资源边界](../fpga/zu15eg/clock-domain-plan.md)。

以下CDC/帧/FP各批次数据为各自冻结输入的历史证据，不自动代替当前CMU或整板签核。

2026-10-04 自研网络下一批 CDC/时钟管理基础：原生38-bit帧 FIFO、52-bit 配置原子快照、
累计事件 delta、常开域排空/停钟/隔离/唤醒/超时策略独立通过。最终
`build/fpga/self-gmac-cdc-20261004-r1/functional-r4/receipt.json` 为
`PASS_NATIVE_GMAC_CDC_CLOCK_POLICY_SHORT`，3项Scala、4组三时钟、20480双向拍、
640配置拷贝、计数回绕/暂停时钟/背压/协调复位、四独立负例通过。
快生产者/慢消费者发现提前归还 RAM 信用，已改为目的端输出捕获后释放；失败记录保留。
这是用户授权的 CDC-only xsim，不模拟 CPU/MAC/PHY，不重复 GSIM/CPU综合。
尚未接生产 SoC、真实门控/软件MMIO/唤醒源和网口排空器，不能宣称外设已可软件停钟。
CPU/原DMA/默认配置/旧bit均未改，无新IPC/Fmax结论。详细合同见
[时钟域与停钟边界](../fpga/zu15eg/clock-domain-plan.md)。

本批小型 OOC 一次布线及同 DCP 约束复核完成：最终
`build/fpga/self-gmac-cdc-20261004-r1/audit-final.json` 为
`PASS_SCOPED_CDC_RETENTION_MODULE_OOC`。control/TX/RX 10/8/8ns，内部
setup +6.268ns、hold +0.042ns；236 LUT/671 FF，其中48 LUTRAM，无BRAM/DSP。
TX/RX 38位 RAM 数据 max-delay8ns 最小裕量 +7.323/+7.354ns，10组bus-skew
最小裕量 +7.472ns；227个CDC端点均有明确max-delay，Critical=0。
4组Gray/212条held或RAM数据Warning保持可见、未waive；真实clock source/I/O预算、
门控/PMU/MMIO/完整网口/整板未验收。这仅是含两条16-bit测试累计器的 wrapper 面积。
必要 RTL/报告/DCP 已逐文件SHA-256归档至上述目录 `native-results/`，未重综合CPU。

2026-10-04 自研千兆第二批：GMII TX/RX 整帧缓冲及原生 DMA 适配器，
`build/gsim/self-gmac-frames-20261004-r3/receipt.json` 为
`passed_single_clock_frames_dma_only`：246帧例、96适配例、54真实DMA联合例；
三个独立负例通过，四项访存信用、尾掩码、坏FCS不写内存/随后好帧、故障排空/重启覆盖。
主 CPU 和原 DMA 实现未改变；不重复 CPU/NEMU/完整GSIM/长Linux。
每方向仅单帧 RAM，RX 缓冲持有期间开始的新帧会完整丢弃，未宣称持续千兆线速。
首次 RX 多写端口导致2KiB缓冲展开为34413 LUT/16766 FF/0BRAM，已停止该批。
统一单写端口后同一独立 oracle 全部再次通过；最终模块布线审计
`build/fpga/self-gmac-frames-20261004-r1/audit-final.json` 为
`PASS_GMAC_MODULE_INTERNAL_OOC`。TX 复用字节一致的已通过 route；只重跑 RX 与适配器，
不重复 CPU/整板。下面资源均为 post-route，不包括 CSR/MDIO/原 DMA/CDC/PHY。

| 模块 | 目标周期 | 内部 setup / hold 裕量 | LUT / FF | RAMB18 |
| --- | ---: | ---: | ---: | ---: |
| GmiiFrameTx | 8 ns（125 MHz） | +5.144 / +0.045 ns | 268 / 178 | 1 |
| GmiiFrameRx | 8 ns（125 MHz） | +4.747 / +0.052 ns | 245 / 271 | 1 |
| EthernetDmaFrameAdapter | 10 ns（100 MHz） | +8.077 / +0.046 ns | 52 / 43 | 0 |

三模块合计 565 LUT / 492 FF / 2 RAMB18 / 0 DSP。RX 同阶段综合资源从
34413 LUT / 16766 FF / 0 BRAM 改善为 255 LUT / 271 FF / 1 RAMB18，route 后为表中值。
全部内部 setup/hold 通过，但这是零 I/O delay 的模块比较：三者边界 hold 分别
-0.049/-0.089/-0.032 ns，未设置真正 PHY/CDC 接口预算，不能签核整板。
必要 RTL/报告/DCP 逐文件 SHA-256 核对后归档到该审计目录的 `native-results/`；
最初 RAM 推断失败的 RTL/综合报告/DCP 保存在 `rejected-ram-inference/`。
RGMII、独立时钟配置/事件/帧CDC、新CSR/APLIC、PHY、driver/DT、整板与bit仍未验收。
详细新帧/完成事件合同见 [DMA](dma.md)；旧 TEMAC 联合综合不能替代本批资源数据。

2026-10-04 自研 GMAC 公共模块：用户选 1G RTL8211F 优先，10G/SFP1 延后。
新增 native TL-UL CSR / 8、64-bit 并行 CRC / MDIO Clause22 三项独立 IP，
`build/gsim/self-gmac-20261004-r3/receipt.json` 状态 `passed_foundation_only`；
CRC 20195 向量、MDIO 96 事务、TL 3045 请求及三个独立负例通过，完整 SV 导出和
软件 header 交叉编译通过。r3 同时通过 TL→MDIO 联动和位序负例：4 次完整帧、
23 次寄存器请求、462 拍 busy START 背压，覆盖 noAck/IRQ/W1C/复位取消。
不重复 CPU/NEMU/长 Linux、xsim 或 Vivado；没有新的 CPU IPC/Fmax/资源数据。
这份第一批记录本身没有帧引擎或 DMA 联调证据；后续进展见上面的第二批。
不能沿用下面旧 TEMAC 联合综合作为新自研网口的面积/时序证明。
代码与必要产物均在 WSL 主工程；旧 bit 和默认开关未改。
接口/接线与后续批次见 [DMA](dma.md) 和
[Ethernet 接入台账](../fpga/zu15eg/ethernet-integration.md)。

2026-10-04 最新 `staged-fetch-feedback` + 自研网络 DMA 候选（尚未推广）：
两条取指反馈链结构改变保持 13 项真实 CPU 同二进制 NEMU A/B 周期不变；
50 项控制/访存、11 项恢复及实际 board RV64GC/权限撤销烟测通过。
记录 `build/gsim/fetch-feedback-20261004-r5/receipt.json`，没有实测 IPC 增益。
网络部分的最终短验收 `build/gsim/ethernet-dma-20261004-r7/receipt.json` 通过，
含 154 收发例、真实 cache/home 脏 TX 探测及 RX 失效、TL 单/多拍部分写、
实际整机生产 RTL 导出和软件 helper 交叉编译。CDC-only 双时钟 xsim 通过。
联合综合/CPU OOC 路由已完成，严格审计 `build/fpga/ethernet-dma-20261004-r2/audit-final.json`
为 `PASS_CPU_INTERNAL_OOC`：10 ns 内部 setup **+0.290 ns**、hold +0.024 ns，
CPU 141737 LUT / 41259 FF / 41 DSP。与同 production 端口的旧 -1.512 ns 相比，
setup 改善 1.802 ns、LUT +660、FF +68；同短集合周期不变，但没有整板/板测频率×IPC结论。
实际 MAC/ROM/CPU/DMA 联合综合为零功能黑盒，200903 LUT / 85740 FF / 43 RAMB36 / 41 DSP；
DMA 本体 1805 LUT / 729 FF / 2 RAMB36。最新最差内部链为 ROB head→store owner/
PRF→地址/范围→storeSafeRange，22级、9.691 ns（布线7.558 ns）；旧取指反馈不再是最差链。
接口 hold=-0.049 ns，网口 CDC 仍有 Critical；整板、DMA 路由/PHY和 Linux 驱动未签核。
原生必要输出及已验收输入逐文件 SHA-256 核对并归档到该目录 `native-results/`，
不能用本次 CPU-only 通过替代旧整数整板 bit 的资格。
默认 ISA/profile、旧工程/bit 不变；单描述符、2 KiB 帧缓冲、标量 coherent 访存
是 bring-up 基线，不宣称千兆线速、完整 TL-C、Linux 驱动或整板 100 MHz。
详细接口与验证边界见 [DMA](dma.md)、[TileLink→AXI](tilelink-axi4-bridge.md)
和 [Ethernet 接入台账](../fpga/zu15eg/ethernet-integration.md)。

2026-10-04 后续 `staged-ethernet` 批量候选：组合 PMP 分段比较、紧凑访存源 ID
选择与分块进位地址加法，必要短 GSIM/NEMU 的 13 项同二进制 A/B 周期全部相同。
功能通过不等于时序优化成功：实际全 F/D 双发射 production CPU OOC 布线
10 ns WNS=**-1.512 ns**，内部 hold=+0.024 ns；最差 PC→packet PMP→
fetchPacket supplyPc/CE 链 34 级、11.407 ns（布线 8.817 ns），尚未达标。
本批 production 导出裁剪了旧裸核未裁剪的调试端口，不能作纯资源 A/B；
141077 LUT/41191 FF/41 DSP。新的真实 Ethernet/ROM/CPU 集成综合已完成，
但整板/CDC/PHY/DMA/授权仍未签核；**不替换旧 profile/bit，不宣称频率×IPC 正收益**。
记录与后续断链方向见 [Ethernet 候选验收](../fpga/zu15eg/ethernet-integration.md)，
严格结果 `build/fpga/axi-ethernet-20261004-r1/audit-final-r1.json`。

2026-10-04 前端组合候选 `staged-gmac-ready`：四字节 packet PMP 改为 word-span
并行候选，路径验证由晚到的 64-bit mux/compare 改为提前比较后选 1-bit，
successor hint 从 8 配置为 32 项。三个开关均 opt-in，默认整数/FP 配置不变，未增加流水周期。
必要短 GSIM 同二进制 A/B：原 12 项 ALU/依赖/分支/访存用例周期完全相同；
新增 17 个分支站点的 hint 冲突专项从 1685 到 1161 cycles，同频 1.4513x。
13 项几何平均为 1.0291x，**这是人工专项集合，不是 CoreMark/Linux 的 2.9% 实测收益**。
原始数据在 `build/gsim/gmac-ready-20261004-r1/receipt.json`；同源实际 CPU 布线已经结束，
候选 **未达到 100 MHz**，不能将这些周期与旧 CPU/整板频率直接拼接成新性能。
多时钟域实现/边界见
[板级时钟域记录](../fpga/zu15eg/clock-domain-plan.md)。

本轮包含完整 F/D、issue=2 的 MachineCore OOC 比较（不是整板签核）：

| 指标 | 本轮前 CPU 基线 | `staged-gmac-ready` 候选 |
| --- | ---: | ---: |
| 10 ns 内部 setup WNS | +0.090 ns | **-0.841 ns** |
| 内部 hold | +0.023 ns | +0.019 ns |
| LUT | 138743 | 143164（+4421） |
| FF | 38532 | 42446（+3914） |
| DSP | 41 | 41 |

新全局最差路径为 `head_reg[0]_rep`→访存 owner 选择→PRF 操作数→
`stagedMemoryAddress_reg[61]`，17 级逻辑、数据延迟 10.822 ns，其中布线 8.813 ns
（81.435%）；TNS=-2212.058 ns，6569 个 setup 失败终点，不能只修一个最差 bit 后宣称通过。
其中操作数控制分支存在 fanout=336，另一路 fanout=64 的单段布线达 2.723 ns。
已执行 post-route 优化，没有通过；不重复盲跑。只读打开两份已布线 DCP 的补充对比表明，
原 `pc_reg`→`fetchPacket/supplyPc_reg/CE` 反馈链也未改善：32→28 级逻辑，但
9.806→10.360 ns、WNS +0.090→-0.465 ns；本次最差路径逻辑 2.809 ns、布线 7.551 ns。
访存 head→地址路径为 9.852→10.822 ns、WNS +0.129→-0.841 ns，20→17 级。
两者最差起止 bit 不同，比较的是相同路径族的最差值，不是单一门级修改的因果 A/B。
补充报告在 `build/fpga/gmac-ready-20261004/native-r1/frontend-review-r1/`，无重新布线。
下一批应成组处理访存 owner 局部译码、操作数选择/地址准备边界、取指 PMP/反馈链，
以及 hint 表面积/布局成本。新增寄存器与拥塞相关，但尚无隔离
A/B 布线实验，不能把整个回退单独归因于 hint 扩容。
零边界 I/O delay 的全部 hold=-0.040 ns，接口预算尚未签核。
原始最终记录：`build/fpga/gmac-ready-20261004/audit-final-r1.json`；完整原生输出
（179 文件、163883114 字节）归档到 WSL `native-r1/` 并逐文件 SHA-256 校验一致。
归档副本重新严格审计：`build/fpga/gmac-ready-20261004/audit-final-archived-r2.json`，
状态 `FAIL_INTERNAL_CPU_TIMING`；保留旧 bit 与默认 profile，不发布新 100 MHz 候选。

> 阅读口径（2026-10-01）：下面保留按日期记录的 GSIM/微结构实验结果。
> 已上板 DDR50/115200 版为双发射、128 KiB ROM、512 MiB CPU-visible PL DDR；
> 用户已验证下载及 DDR 测试/测速。旧 Board40 为 1 MiB UltraRAM。
> 用户随后反馈双发射／两路相联 2 KiB L1 板测全部 PASS，8 MiB COPY 达 17.214 MiB/s。
> 四发射和后续回放重构仍是候选；BootROM 修复版只改 ROM INIT，不含回放重构。
> 旧 4-issue/64 MiB Linux、理想供指 IPC、独立模块时序和新 GSIM 周期，
> 不能与板级频率拼接成实测性能或正式 CoreMark 分数。
> 独立 RAM 资源及旧紧凑 OOC 45 MHz 报告的适用边界见 [FPGA 时序状态](fpga-timing-windows.md)。

2026-09-27：写回数据 L1 在单条整行 Acquire/fill 等待期间可受理其他直接映射
索引上的两个读命中；响应队列仍保证先返回较老的缺失，再返回两个命中。
同索引、写入、探测、逐出及 flush 仍需等待；这不是多 MSHR。
双客户端一致性定向测试覆盖背靠背命中和返回顺序，FENCE.I 后 RAM 执行用例通过。
此改动尚无同配置 CoreMark 周期对照，不宣称 IPC 增益。

4-issue、压缩指令前端现用 16 字节物理取指接口，一次 I-cache 命中填充两个
8 字节前端包；2-issue 仍为 8 字节。4-issue 默认使用 128 组前端包缓存，
2-issue 默认 64 组。此前只扩大缓存容量时，1.5 KiB 纯 32 位 RAM 热循环
IPC 从 1.894 提高到 3.503，热段达到 3.968；当时物理接口仍为 8 字节，
代码超出前端缓存就无法持续四发射。
现在 3 KiB 长循环超出 2 KiB 前端包缓存但容纳于 64 行物理 I-cache，
首轮之后退休 22,330 条/5632 拍，稳态 IPC **3.965**，RAM Get 为 1。
这验证了 L1 命中时的持续供给，并不代表冷缺失或 DDR 带宽。
4-issue 整行 I-cache 已接入一条需求行加两条顺序预取行并发填充，
预取 Get 发出后继续寻找下一行；RAM manager 可在当前 burst 返回期间
预接收一笔后续整行 Get。在同一 3 KiB 代码、16 行（1 KiB）物理
I-cache 的循环缺失场景，稳态从 22,330 条/22,678 拍（IPC 0.985）
改善到 22,330 条/18,197 拍（IPC **1.227**）；整段 Get 从 1474 增至
1522。独立 GSIM 验证了三笔 Get 并行在途及缓存失效后的重取。
第三条预取使稳态退至 1.218 IPC，故保留两条。64 位 D 通道仍逐 beat
串行返回，冷流尚不能持续四发射，也没有 FPGA Fmax 数据。
固定 4-issue CoreMark 在 128 组、8 字节物理接口和后继包预取下为
142,491 拍、IPC 2.2652659；宽接口和 ROM 两笔 8 字节适配后为
142,914 拍、IPC 2.2585611，增加 423 拍约 0.30%，退休数同为
322,780、CRC 错误均为 0。ROM 仍是双 bank 同步 8 字节读取，
不具备原生 16 字节带宽。以上均为 GSIM 周期，没有 FPGA Fmax 数据。

2026-09-27：单 hart TL-C home 在无需探测、读队列有空位时，于接收 AcquireBlock
当拍提交整行读取请求；队列满时仍使用原有等待态。固定 CoreMark 镜像从 239,058
降到 239,014 周期，322,780 条退休、44 次 L1 缺失、CRC 错误 0，正好每次缺失
少一拍。单 hart 脏逐出/DMA/原子和双 hart TL-C 定向 GSIM 通过；未运行 Linux，
也没有 Vivado 时序数据。这是缩短首个缺失的控制空拍，不解决单笔缺失和整行写回
串行化的主要限制。

存储层仍有明确的产品化缺口：当前 64 MiB `SynchronousDataRam` 是 GSIM
功能模型，不是 xczu15eg 上可直接实现的片上 RAM；独立 TL→AXI4 桥只发单拍
事务且尚未接入机器平台/DDR。片上 `InstructionRom` 是双 bank 同步启动 ROM；
从 RAM 执行代码现可经过 16 行默认、参数化容量的整行 I-cache。机器核的
`FENCE.I` 已在带脏写回 L1 的定向 GSIM 中验证写回、失效和 RAM 代码重取，
但未覆盖多 hart 广播同步。见
[FPGA 存储基线](fpga-bringup.md)、[TL→AXI4 边界](tilelink-axi4-bridge.md)与
[TL-C 边界](tilelink-burst-coherence.md)。

2026-09-27：4-issue RAM 压缩指令循环在首轮填充后的稳态达到 3.966 IPC；
32 行 I-cache 将 12 拍 RAM 延迟模型下的稳态 IPC 从直连 0.305 提高到 3.966，
零附加延迟时两者同为 3.966。此段为扩大 4-issue 物理取指接口前的压缩指令
对照；当前纯 32 位指令的 L1 命中长循环数据见上文。该定向循环不代表 CoreMark/Linux 综合性能，
也没有 Vivado Fmax 数据；口径和命令见 [TileLink 取指路径](tilelink-fetch.md)。

2026-09-27：单 hart 一致性 home 改用与直接映射 L1 同索引的 128 个带标签
owner 槽位，使 64 MiB Linux RAM 可接入可选 8 KiB 写回 L1。
4 issue + L1 已启动到 `/init`，但同镜像对照为直连 128,892,266 拍、
L1 175,413,979 拍，后者多 36.1%；启动退休条数不同，不是稳态 IPC 对照。
带冲突逐出的单 hart UART/DMA/原子与双客户端 TL-C 定向 GSIM 均通过。
当前不默认启用 L1，后续优先量化缺失、探测及串行等待，再优化非阻塞能力。
详见 [Linux 启动](linux-bringup.md)。

2026-09-27：可选写回 L1 的脏 ProbeAckData/ReleaseData 已接成 64 字节
TileLink PutFullData burst。双客户端同一脏行迁移定向 GSIM 两个方向均从
50 降到 39 周期，且记录 48 个实际 burst A beat；同一 CoreMark 保持
239,058 拍、IPC 1.3502163。双 bank 的启动、DMA 和原子固件通过。
这是脏行迁移路径的收益，不代表 Linux 或 FPGA 性能；详见
[burst 与一致性边界](tilelink-burst-coherence.md)。

2026-09-27：可选写回 L1 的字节写使能优化使同一 CoreMark 从 239,685 拍、
IPC 1.3466842 改为 239,058 拍、IPC 1.3502163，退休数同为 322,780、CRC 错误 0。
收益约 0.26%；仅运行 CoreMark、双 bank 一致性平台和双客户端迁移的定向 GSIM，
未运行 Linux 或完整回归。详见 [burst 与一致性边界](tilelink-burst-coherence.md)。
同一轮直连 CoreMark 为 253,576 拍、IPC 1.2729123，优化后写回 L1
为 239,058 拍、IPC 1.3502163；这是配置差异，不能归因于本轮单项优化。

2026-09-23：当前可称为已验证部分指令与系统功能的双发射乱序原型，尚不能认定为高性能CPU。
双发射是吞吐上限的一个条件；实际程序性能还取决于依赖、访存、分支和工作频率。
GSIM运行速度是验证工具的速度，不能当作硬件频率或CPU性能。

2026-09-24 更新：固定 RV64IMAC+Zba/Zbb/Zbs CoreMark 单次仿真从 410,891 降至
305,375 总周期，IPC 从 0.7856 升至 1.0570，CRC 错误为 0。已按零提交周期的
ROB 队首状态和热点 PC 下钻，再以同一二进制验证 StoreBuffer 当拍应答、MULW 快路径
和[已就绪 load 旁路及重叠回放](load-ready-replay.md)的收益；
详见 [RV64C 与 CoreMark](rv64c-coremark.md)。这仍不是 FPGA 时序或正式 CoreMark 分数。
进一步采样表明队首访存处于 LSU 完成态的 36,570 个零提交周期中，完成端口
仲裁阻塞为 0；这是固定交接拍，当前没有证据支持优先扩大完成仲裁带宽。
在 MULW 优化前，可选共享读缓存的 128 行、扇区失效版本为 377,421 周期，
当时仍慢于直连 RAM；详情见[共享读缓存](shared-read-cache.md)，所以默认保持直连。
当前 RTL 的同二进制复测及有序下游响应直通优化后：零附加 RAM 延迟下，128 行
缓存 323,175 周期，仍慢于直连的 305,375 周期；附加 12 拍响应延迟下，缓存
564,805 周期，快于直连的 600,412 周期。优化前两档缓存分别为 342,992 和
587,296 周期。该翻转仅说明缓存收益依赖内存延迟模型，尚无 DDR 或 FPGA 测量。
最新裸核 IPC 报告有 52 条记录，其中两种配置下共 8 条为新增的
已就绪 load/外部写入回放用例。早期 44 条基准的历史数据包含多轮其他优化，
不用于单独归因本次 load 调度改动。
双主 TileLink 平台种子 0 的 RAM/DMA/原子固件当前分别为
3,085/4,839/6,039 周期，CPU 与 DMA 同时有进展；启动周期不等同纯计算 IPC。

## 最新可复现数据

来源：`make gsim-core-test` 生成的 `build/gsim/ipc.json`；
`make gsim-ipc` 只重测默认配置，会把同一文件改为 26 条。以下为默认 ROB32/PRF64，
从首次供指到最后退休（含首尾拍），不含复位及退休后的内存排空；完整报告另列排空周期。
理想双路供指、四项LSU、现有分支预测与写缓冲；不含cache/MMU/CSR执行，内存延迟为测试参数。
52条结果包括默认与小配置，以及四项新增的已就绪 load/外部写入回放用例；
不能把不同配置或不同供指方式混成同一成绩。

| 测试 | 内存响应延迟 | 退休指令数 | 周期 | IPC |
| --- | ---: | ---: | ---: | ---: |
| 独立整数ALU流 | 1 | 4096 | 2050 | 1.998049 |
| 整数ALU依赖链 | 1 | 4096 | 4098 | 0.999512 |
| taken分支循环 | 1 | 1026 | 522 | 1.965517 |
| C数组求和 | 1 | 1310 | 1311 | 0.999237 |
| C数组求和 | 12 | 1310 | 1379 | 0.949964 |
| 独立load流 | 1 | 257 | 262 | 0.980916 |
| 独立load流 | 12 | 257 | 903 | 0.284607 |
| store/load依赖链 | 12 | 769 | 1539 | 0.499675 |
| 独立乘法流 | 1 | 130 | 137 | 0.948905 |
| 乘法依赖链 | 1 | 130 | 899 | 0.144605 |

12拍store/load依赖链另需9拍退休后内存排空，不能把上述IPC视为全部写入已完成的端到端吞吐。
乘法依赖链受六拍乘法器及唤醒时机限制；独立吞吐和相关链延迟必须分别看。
C数组4拍结果为1278拍、IPC 1.025039，比1拍略好，说明调度/转发相位影响小基准；不据此声称更慢内存普遍更快。

真实同步ROM+RAM模型中，同一C程序无提交背压为1310条/1333拍，IPC **0.982746**；
来源`build/gsim/platform-ipc.json`与`build/gsim/platform/test.log`，入口`make gsim-platform-test`。
这里“真实同步”指使用Chisel同步存储模块，仍是GSIM仿真，不是上板实测。
人为随机提交背压下IPC 0.780226/0.788682仅用于停顿验证，不作为软件性能成绩。

## 可以得出的判断

独立ALU流已经接近双发射上限，说明基本整数吞吐通路工作正常；相关链约IPC 1也符合串行依赖。
长延迟独立load明显下降，说明访存隐藏能力仍有不足。小C程序约0.95～1.03，
只能代表这个短程序及当前存储模型，不能外推到应用处理器、Linux或商业CPU的综合表现。
原子内存IP现已接入机器平台CPU通路，以保守串行排序建立正确性；这是功能推进，原子专用负载单列于[合同](atomic-memory.md)。

已有可选共享读缓存的微基准对照，但尚无代表性的大程序集合和DDR成绩，也没有Vivado布局布线后的Fmax、资源或上板数据。
目标器件已确定为 XCZU15EG，仍需明确封装、速度等级与板级约束。
在这些证据缺失时，不能用 IPC 承诺 MHz、每秒性能或对标商业高性能核。

最新总线工作已把独立的 TileLink→AXI4 桥做到最多8笔读、4笔写在途，并通过
[独立桥验证](tilelink-axi4-bridge.md)。256笔连续写的桥微基准从单写槽1379拍降至四写槽378拍；
这条路径尚未接入机器平台，因此既不是CPU IPC提升，也不是DDR实测带宽。
在12拍内存的当前裸核测试中，可选8槽LSU把独立load流从903拍降至459拍、C数组程序从1379拍
降至1295拍；默认仍为4槽，资源和Fmax代价尚未测量。平台40拍响应延迟的三组种子也显示
8槽比4槽少1403～1417拍，具体数据见`build/gsim/platform-latency.json`。
同一比较现已扩展到双主TileLink ROM/RAM平台：40拍响应延迟下，4槽三个种子为
9413/9530/9513拍，8槽为7965/8075/8080拍，减少约15%；详见
`build/gsim/tilelink-dual-latency.json`。单RAM桥允许有序读写混合在途后，
当时正常延迟的双主平台种子0 DMA固件5766→5559拍、原子固件6848→6694拍；
40拍延迟固件则没有周期变化。两种优化都还没有Vivado资源和Fmax数据。
新增的64字节 TileLink burst 互联与单 RAM manager 已通过独立 GSIM，
默认 CPU/DMA 固件仍发送单拍请求；双主平台正常延迟与40拍延迟的完成周期
均与加入 burst 前逐项相同。可选单 CPU 写回 L1 已接入整行 burst、TL-C
Acquire/GrantAck、脏行 ProbeAckData 与 ReleaseData；同一 CoreMark 在 0 拍模型为
302,809 周期、IPC 1.0660（直连 305,375/1.0570），12 拍模型为
303,337/1.0641（直连 600,412/0.5376）。单 CPU 逐行 home 现有 DMA 读写探测，
但多 hart 目录、多在途缺失及 Vivado 时序尚未完成，见
[burst 与一致性边界](tilelink-burst-coherence.md)。

## 下一步验收顺序

1. 已完成机器平台原子通路、队首授权、旧写排空、精确异常及强排序基线；下一步依据停顿数据优化访存与原子执行成本。
2. 保留既有裸核基准，加入真实混合程序及原子/DMA竞争负载，分别记录吞吐、延迟与停顿来源。
3. 以已接通的双主TileLink→同步RAM路径作为当前SoC仿真主线，测量CPU取指/访存与DMA竞争、
   长延迟load及C负载；比较4/8槽LSU和缓存开关的整机完成时间，并记录仲裁、排空及响应等待。
   AXI4桥留作日后外部内存边界验证，不作为当前GSIM整机性能推进的前置条件。
4. 有Vivado后测资源/BRAM/DSP映射及布局布线时序，再在固定器件/时钟/内存条件下比较程序完成时间。

目前不引入SMT；先把单线程双发射核的完整性、访存与时序证据做好。

第一阶段历史验证：31项Scala及完整GSIM/NEMU通过，44条IPC测量字段与修改前快照逐项一致，24次平台启动周期/结果不变。
日志`build/gsim/atomic-final.log`；比较快照`build/gsim/ipc-before-atomic.json`。本轮增加功能基础，没有宣称CPU IPC提升。


2026-09-23 CPU原子接入最终验证：32项Scala、完整GSIM/NEMU通过；原44条IPC全部测量字段与24次平台启动记录逐项不变。
无背压原子压力程序362条指令/72次AMO，下游1拍与12拍分别为1372与4468周期，作为强排序基线，不外推到普通应用。
日志`build/gsim/atomic-core-final.log`，快照`build/gsim/ipc-before-atomic-core.json`。机器平台RTL已导出，仍无Vivado频率/资源结果。


可选共享缓存首版：默认核在12拍内存下重复读取由903降到786周期，下游读由256次降到1次；
无重用流式读反而由903升至4101周期。首版为单项阻塞事务，默认关闭，不能当作总体CPU性能提升。
开关缓存下的原子/DMA与启动验证、所有代价见[共享读缓存](shared-read-cache.md)；原44项IPC继续作为无缓存基线。

2026-09-23 缓存首版最终验证：33项Scala、完整GSIM/NEMU与60次平台启动通过；
44项IPC测量字段与`build/gsim/ipc-before-cache.json`逐项一致，默认平台30次启动周期不变。
日志`build/gsim/cache-final.log`；缓存版RTL导出通过，尚无Vivado资源/时序结果。

2026-09-23 阶段的共享缓存命中流水化定向结果：命中启动间隔1拍，孤立命中延迟3拍；12拍重复读取由首版786降至277周期（无缓存903）。
流式读取仍需3846周期，未命中并行尚未实现，默认继续关闭。数据口径和背压检查见[共享读缓存](shared-read-cache.md)。

命中流水化最终验收：`make test cached-platform-rtl`通过，33项Scala、完整GSIM/NEMU及60次启动通过。
44项IPC测量、30次无缓存启动和所有无缓存CPU对照均未变化；对照快照`build/gsim/ipc-before-cache-pipeline.json`，
日志`build/gsim/cache-pipeline-final.log`。缓存版RTL已重新导出，仍无Vivado资源/时序结果。

多笔未命中缓存最终结果：12拍流式读取由缓存上一版3846降至1094周期，无缓存为903；
12拍重复读取仍仅访问下游一次、276周期。同步平台DMA缓存版6426周期，无缓存5440，默认继续关闭缓存。
`make test cached-platform-rtl`通过；44项IPC、30次无缓存启动与24条无缓存CPU对照逐项不变，
日志`build/gsim/cache-mshr-final.log`，快照`build/gsim/ipc-before-cache-mshr.json`。暂无Vivado资源/时序结果。

平台DMA写路径诊断：缓存版种子0在DMA活跃期间原有独占等待576拍、串行等待328拍，
而RAM请求背压及缓存下游4笔容量占满均为0；瓶颈主要在缓存写入独占规则。
写响应完成后释放独占状态，DMA固件6426→6004周期，仍慢于无缓存5440；默认关闭策略不变。
事件口径及逐次数据见[共享读缓存](shared-read-cache.md)和`build/gsim/cache-stalls.json`。

允许缓存填充与不同物理 SRAM 字的读查询同拍执行后，默认整核 1/12 拍流式读分别
518→327、1094→1031 周期；默认平台缓存版 DMA 6004→5910 周期，仍高于无缓存 5440。
聚焦缓存 IP、整核 NEMU 和平台 GSIM 检查通过，48 条整核对照无周期退步；
缓存继续默认关闭。详细事件与限制见[共享读缓存](shared-read-cache.md)。

缓存范围内的写后读现可重叠，默认平台缓存版 DMA 5910→5714 周期，活跃期间写独占阻塞
384→276 拍；无缓存仍为 5440 周期。48 条整核对照测量不变、60 条平台启动无周期退步，
且原子/NEMU 与独立写后读检查通过。默认开关保持关闭；见[共享读缓存](shared-read-cache.md)。

缓存范围内的连续写已可并行下发。默认平台缓存版 DMA 5714→5452 周期，接近无缓存的 5440；
旧写独占阻塞 276→0 拍，剩余等待主要是写前旧读未完成。独立读回、四种整核原子/NEMU
及 60 条平台启动定向检查通过，无周期退步。其他固件仍有缓存代价，默认继续关闭；
见[共享读缓存](shared-read-cache.md)。

8 槽 LSU 配置已完成独立整核 GSIM/NEMU 验证，默认仍为 4 槽。相同 ROB32/PRF64、
相同程序与 12 拍有序 RAM，256 次独立 load 从 903 降至 459 周期，峰值在途数 4→8；
C 数组从 1379 降至 1295 周期，IPC 0.949964→1.011583。26 条同配置 IPC 对照中
4 条改善、22 条不变，提交数和物理读写数均未变化。数据见 `build/gsim/ipc-memory8.json`，
完整差分日志见 `build/gsim/core-memory8/test.log`。8 槽增加硬件规模与选择网络，
Vivado 面积、布线和 Fmax 未测，不能仅凭周期数决定在目标 FPGA 上默认启用。

8 槽接入同步机器平台后的历史对照中，RAM、DMA、原子固件各 3 个种子的 9 条启动周期与 4 槽逐项相同；
当时种子 0 为 3606/5440/6494 周期。平台同步 RAM 仅容纳两项在途且响应很短，
这些固件没有体现裸核 12 拍内存的收益。定向检查与报告见[机器平台](machine-platform.md)；
下一步应先建立真实长延迟、可并行的外部内存边界及其 FPGA 时序证据。

为分离访存延迟与写后转发，新增默认关闭的 40 拍有序响应模型和专用固件：
初始化写排空后反复发出独立读取。三个种子中 4 槽 9209/9324/9305 周期，
8 槽 7794/7921/7888 周期，分别减少 1415/1403/1417 周期，提交数相同且
独立模型检查通过。数据见 `build/gsim/platform-latency.json`。结果证明当前平台
在足够长且可并行的有序内存延迟下能利用 8 槽，但不代表真实 DDR/AXI 性能；
仍需总线适配、资源和 Fmax 测量。

双 hart TL-C home 定向优化：在脏 ProbeAckData 写回 RAM 后直接用 home 缓冲行发 GrantData，
同一 GSIM 用例的两个方向脏行迁移均从 62 降到 50 周期（约 19.4%）；
此数值是缓存行转移延迟，不是 CPU IPC。原单核一致性 L1、12 拍 RAM CoreMark
固定镜像仍为 303,337 周期、322,780 条退休、IPC 1.064097，CRC 错误为 0，
未宣称单核 CoreMark 加速。多 hart SoC 集成、共享 B 权限与 FPGA Fmax 尚未完成。

单 hart 优先的 ROB 退休优化：允许已通过令牌、恢复边界与异常检查的队首完成结果
在同拍退休，省去完成结果写入 ROB 后再等一拍的交接。相同固定镜像、单核写回 L1、
12 拍 RAM 的 GSIM CoreMark 从 303,337 降至 290,642 周期（减少 4.18%），
退休指令仍为 322,780，IPC 1.064097→1.110576，校验错误为 0。
这不是可报告的 CoreMark 分数；现有固定镜像用于同二进制比较。
独立 ROB 模型、整核 NEMU 差分及单核一致性平台固件验证通过。
新完成到退休的组合路径可能影响 FPGA Fmax，尚未取得 Vivado 时序数据，
因此周期收益还不能等同于实机每秒性能收益。

随后对单 hart 写回 L1 的读命中做连续受理：同步 SRAM 保持一拍读延迟，
两项响应缓冲承担背压；有空间时可每拍受理一笔读命中，写命中、缺失和绕行
仍等待此前读响应完成。独立 GSIM 验证同一已缓存行的 32 笔连续读在不超过
34 拍内完成，并验证响应停止时最多保留两笔、恢复后数据不丢失。
同一固定 CoreMark 镜像从 290,642 降至 282,604 周期（减少 2.77%），
322,780 条退休指令与校验结果不变，IPC 1.110576→1.142164。
与最初 303,337 周期相比合计减少 20,733 周期（6.84%）。
单核一致性平台 UART/DMA/原子与脏逐出、虚拟内存数据回归通过；
响应队列的寄存器开销及新组合路径的 FPGA Fmax 尚未测量。

单 hart LSU 请求交接再减少一拍：已授权的对齐访存在 start 当拍即可向内存请求，
背压时锁存后保持稳定，并支持当拍零延迟响应。固定写回 L1、12 拍 RAM 的
同一 CoreMark 镜像从 282,604 降至 257,062 周期（减少 9.04%），
退休 322,780 条、校验错误 0，IPC 1.142164→1.255650。
相较最初 303,337 周期，累计减少 46,275 周期（15.26%）。
CoreMark 的 8 槽 LSU 对照与 4 槽周期及停顿计数完全相同，故默认保留 4 槽；
独立整数模型、整核 NEMU、单核一致性 UART/DMA/原子及虚拟内存数据回归通过。
start 到内存 request 的新组合路径仍需 Vivado Fmax 与资源测量。

4-issue 裸核固定 CoreMark 镜像的队首 RAM store 路径已拆出独立入队口：
在地址已知、对齐、PMP 许可且保证写成功的 RAM 范围内，可与不重叠的年轻 load
同拍发射；空闲内存端口仍能在 store 入队当拍发送写请求。相同 GSIM 配置下，
原 143,772 周期、IPC 2.245083 降至 142,124 周期、IPC 2.271115，
退休指令均为 322,780，CoreMark 校验错误均为 0。差分检查和缓冲区双入口
背压/重叠测试通过。链表指针追逐的约 6,120 个队首停顿仍存在；此结果是仿真
周期收益，FPGA Fmax 与资源尚未测量。

XCZU15EG 确定后，下一阶段优先建立目标器件的综合/布线时序与资源基线，
并让现有 TileLink 缓存及 AXI4 外存边界在接近 DDR 延迟和背压的模型下完成系统级性能验证。
上述阶段桥仍是独立 IP；2026-10-01 的 DDR50 板级配置已接入 TileLink→AXI4/MIG，
但仍不能把桥的微基准带宽当作 CPU 外存性能。
在真实内存路径和目标器件时序证据取得前，继续追逐约百分之一的裸核周期收益
不足以判断 FPGA 上每秒性能是否增加。

## 2026-10-01：DDR50 同容量两路 L1 / 前端组合逻辑候选

用户实测旧 DDR50/115200 bit：8 MiB read 47.316 MiB/s、write(+flush)
28.114 MiB/s、copy payload 3.130 MiB/s。这是 CPU 可见带宽，不是 DDR 峰值。
旧 bit、MIG、时钟、UART 和 MMIO 均未改动；下面是新源码候选的证据。

同一 5638 字节 ddr_bench.bin、50 MHz、115200、相同独立 AXI 回压模型。
两份 bin SHA256 均为
`46D728EF19758A8273DC488B4F5399F8951E3E9934FE507087B5F27926773110`。
数据 L1 都是 32×64 B / 2 KiB；只改成 16 sets×2 ways，同步匹配单 hart
home 所有权目录。没有扩大容量、改变测试地址或修改测速程序。

| 4 KiB timed region | 单路 cycles | 两路 cycles | 结论 |
| --- | ---: | ---: | --- |
| READ | 4587 | 4583 | 基本不变 |
| WRITE(+flush) | 7212 | 7214 | 基本不变 |
| COPY(payload,+flush) | 59280 | 11419 | 周期 -80.74%，约 5.19× |
| CHASE，64 hops | 3662 | 3661 | 基本不变 |

copy 的合成模型速率 3.294→17.104 MiB/s；不是新板上带宽。
write 输出结束到 copy 输出结束的观察区间，miss 976→292、
dirty eviction 434→81、miss-blocked cycles 41856→10841。
这些事件计数包含准备、校验和 UART，不冒充 timed copy 的精确事件数。
同索引反复替换是此工作负载的主要低吞吐原因；两路并非对所有负载都更快，
独立 manager 的混合访问总 miss 58/59 就展示了相联度取舍。

两路仍只有一个 outstanding line miss，命中 SRAM 一拍、两项有序响应缓冲，
hit-under-miss 保留；没有预取、MSHR/AXI 位宽/并发度扩容。
前端用 5-bit packet-relative offset；IntegerCore 预计算顺序 PC，
晚到指令长度/rename acceptance 只选择 PC，不再启动 XLEN 加法。
没有新增流水拍，单路对照的四项 timed cycles 与原始基线完全相同。
新整机 post-route、Fmax、CoreMark IPC 和上板 DDR A/B 未测。
模块时序/资源代价见 [时序台账](fpga-timing-windows.md)。

## 2026-10-01：紧凑双/四发射同镜像对照

默认和已上板配置仍是双发射乱序：rename/issue/commit=2。
四发射候选取三项宽度=4，但 ROB=16、PRF=48、LSU=2、store buffer=2、
前端 packet cache=16 sets、I-line cache=8×64 B、D-L1=32×64 B/2-way
均不扩容。四路取指带宽变为 16 B；原平台还自动启用两条顺序预取，
不是只改变 ALU 数量的孤立试验。

短 CoreMark：同一 18140 B BIN，SHA256
`AE05E5BE6D30BB8EC111E4734D41407AC31E9DE200DD25AC7FEF3EE92739E821`；
RV64IM/Zicsr/Zifencei、GCC 13.2.0 -O2、DDR50/115200、独立 AXI
memory/latency/backpressure，ASan/UBSan。只跑 1 iteration，不足 10 秒
提示保持可见；list/matrix/state=0xe714/0x1fd7/0x8e3a 全通过。
仅 timed ticks 比较，不把含 UART 的整段周期当 IPC，不发布 CoreMark 分数。

| 候选 | timed cycles | 应用全程 AXI read bursts |
| --- | --- | --- |
| 双发射、无指令预取 | 639000 | 6746 |
| 四发射、原自动指令预取 | 697141 | 14318 |
| 四发射、关闭指令预取 | 587055 | 7481 |

同频四路关闭预取比双路快 **8.85%**，cycle -8.13%；
比原四路预取版快 18.75%，cycle -15.79%。
当前小指令缓存下自动预取反而增加流量/等待；这是此 workload 的实测，
不能据此删除面向大指令缓存/顺序流的通用预取支持。
`MachinePlatform` 默认策略保留，板级可以显式选择预取开关。

性能判断用同工作量完成时间而非标称宽度：
`speedup = (f4/f2) × (639000/587055)`。
若双路 f2=50 MHz，四路至少需要 **45.935 MHz** 才能打平本次短回归。
四路整机 Fmax 尚未测得，不能据此宣布系统已经正优化或替换默认板级配置。
冷启动/单 iteration 结果不等同于长时间暖缓存 CoreMark 或 Linux IPC。

4 KiB DDR benchmark 的原四路预取版也通过 backing-memory/速率检查：
READ/WRITE+flush/COPY+flush/CHASE=4746/7352/11375/3817 cycles，
对应双路两路缓存=4583/7214/11419/3661；不呈现普遍的四发射提速。
四路关闭预取版复用相同已验证 GSIM 模型、只换原 DDR benchmark driver，
READ/WRITE+flush/COPY+flush/CHASE=4548/7137/11228/3636 cycles，全通过。
对应同频速度仅约 +0.77%/+1.08%/+1.70%/+0.69%，不是翻倍；
AXI backing source/destination/ring、burst/backpressure 及带宽单位独立检查通过。
这是人工 AXI 模型，不是新 FPGA 带宽。复现命令为
`python3 simulator/gsim/ddr_bench_app.py --cache-ways 2 --issue-width 4 --no-instruction-prefetch`。

本轮另修正物理 InstructionLineCache：16 B 包在同一 64 B 行内允许
0..48 的全部 8 B 偏移，offset 56 跨行仍 precise fallback。
完整 128-bit、高/低半包、连续命中/背压、PMP、错误 fill、失效通过；
恢复旧对齐条件的独立负向模型被回归正确抓住。
这项修正 **没有** 改变上述四路 CoreMark 周期，因为当前板级宽前端
自身始终发 16 B 对齐包；不把它虚报成 CoreMark 收益。

默认双路 97 个 SV 文件在预取开关/取指修正之后仍逐一 SHA256 相同。
配置检查 15 项通过；没有全量 GSIM、COM4 或四路整机布局布线。
四路参数/预取开关为显式评估入口，不表示四路 OS/中断/压力测试全部验收。

资源及频率结果见 [时序台账](fpga-timing-windows.md)：四路关闭预取 SoC
178574 LUT（全芯片 52.3%），双路 118861 LUT；存储/DSP 数相同。
双路两路 L1 的新独立 bit 已完成 50 MHz 签核，CPU WNS +0.163 ns，
上述生成时尚未烧录；后续用户板测见下一节，四路仍未执行整机实现/签核。

## 2026-10-01：双发射基线板测、回放重构与 BootROM 修复

用户提供的新版双发射／2-way L1 DDR benchmark 输出全部 PASS。
配置为 CPU 50 MHz、UART 115200、D-L1 2 KiB/64 B 行；板上 bit 的文件哈希未读回核验。
8 MiB 工作集的前后对照：

| 指标 | 原单路 L1 | 用户反馈新版 2-way L1 |
| --- | ---: | ---: |
| READ MiB/s | 47.316 | 47.131 |
| WRITE+flush MiB/s | 28.114 | 28.110 |
| COPY payload MiB/s | 3.130 | 17.214 |
| COPY ticks | 127793599 | 23235686 |
| CHASE ticks/hop | 55.713 | 55.714 |

复制带宽约 5.50 倍，耗时 2555.871→464.713 ms；64 KiB/1 MiB 分别为
17.212/17.213 MiB/s。热 1 KiB 缓存读仍为 245.251 MiB/s，单独读写和指针追踪
基本不变。符合相联度改善冲突的预期，不是 MIG 峰值或全程序 IPC 提升；
PASS 也不代表完整电气/温度/长时间稳定性资格验证。

以双发射为本轮基线，容量不变、不增加生产流水拍。新 `LoadReplaySelector`
完整比较 61-bit PA 与字节掩码，按环形 ROB 顺序挑选最老的重叠 younger load。
核心候选采用独热 PC/token 读取，避免旧 tournament index 再读 queue 的串行结构。
16892832 组独立选择器向量及负向检查通过；NEMU 对照实际执行核心通过
282 programs、18000 random instructions/3 seeds、同地址/部分重叠回放、回滚和精确异常。
15 项参数检查通过。没有跑全量 GSIM。

同一 18140 B CoreMark 单轮镜像仍为 639000 timed cycles、read bursts=6746；
原 5638 B DDR smoke 四项仍为 4583/7214/11419/3661 ticks。
两项只是人工 AXI/GSIM 回归，未观察到周期回退，不是新上板性能或有效 CoreMark 分数。
新版真实 BootROM 的 UART 下载/CRC重试/保留区/fence.i/执行返回测试通过
18319290 cycles、936 UART bytes、ROM 3061 B、sample 552 B。

已完成一轮候选 SoC 综合和三个小模块布局；未执行新回放候选的整机布线。
SoC LUT 118861→118181（-680），FF 62602→62606，RAMB36/DSP 保持 37/19。
实际 SoC 回放→PC 综合估计 15.183→15.053 ns，层数 57→53；
整机最差综合路径仍为 20.919 ns。不能与旧 post-route 19.449 ns 混比，
不能据此承诺更高频率。完整小模块结果与取舍见 [时序台账](fpga-timing-windows.md)。

上一版 `release-2way` 错误选用了旧工程 ROM DCP：只比较 candidate 与 bit 的 INIT
无法证明固件新鲜。已修正为明确期望 BIN/MIF/ROM DCP，全部 32768 MIF 字及
4176 INIT/INITP 独立核对；用旧候选作负测试被门禁拒绝。
最新 Bootrom V0.1 只接收/引导，无测试菜单或 `>`；固件 SHA256
`987FA3687E82620B8A708E03B93791D8F3A2AE181BFFAAF3FE533174A744E1F2`。
通过 INIT-only ECO 生成 `ddr-opt-20261001/bootrom-fix/release` 独立 bit，
未修改原布线和旧 bit；保留已测双发射／2-way CPU，不包含回放候选。
代理未访问 COM4 或烧录板卡，需用户验证新版启动 banner/下载。

## 2026-10-01：可选 registered-replay 双发射候选

`registered-replay` 同时启用既有 registered load replay 和 registered ROB retirement，
保留提前恢复阻断、地址/owner 寄存边界；不修改默认 `early-issue` 或板上 bit。
ROB16/PRF48/LSU2/SB2、双发射和 2 KiB/2-way L1 容量不变。
它把回放授权延迟一拍，必须连同退休逻辑验证，不能只给比较器插寄存器。

同一 18140 B CoreMark 单轮 BIN：639000→642274 timed ticks，
耗时增加 **0.512%**（不是有效 CoreMark 分数）。相同工作量的收益条件为
`speedup = (f_new/f_old) × (639000/642274)`；频率至少增加 0.512% 才能打平本例。
GSIM 主机运行时间不纳入这个比较。
相同 DDR 4 KiB smoke READ/WRITE/COPY/CHASE=4594/7216/11469/3661 ticks；
旧默认为 4583/7214/11419/3661，全部内容/AXI backing-memory/背压检查通过。

执行核心 NEMU：282 程序、185224 decoder cases、18000 随机指令/3 seeds、
19 陷阱、负向 mismatch、部分字节重叠回放/回滚/精确退休均 PASS；
板级 CoreMark/DDR 定向 PASS，参数测试 16 项 PASS。没有全量 GSIM。
核心随机测试为通用配置；板级两个短应用才使用精确的紧凑板级容量。

Vivado 仅完成候选 SoC OOC 综合，无整板布线或新 bit：
LUT118181→119567（+1386/+1.17%）、FF62606→62731（+125），RAMB36=37/DSP=19。
原 beat→PC 直接组合路径已不存在；两个定向段为 3.508/13.324 ns，
上一版组合估计 15.053 ns。整体最差综合路径仍 20.919 ns，没有证明整体提频。
因此暂不提升为默认，也不把 replay 单链的改善当作整个 CPU 的 Fmax。
证据在 `ddr-opt-20261001/replay-stage`，细节见 [时序台账](fpga-timing-windows.md)。

## 2026-10-01：默认双发射物理响应 owner 优化

这轮不增加 replay/retirement 流水拍，保持 `early-issue` 和全部板级容量。
同时取消系统仲裁及AtomicMemory普通响应的空owner直通，仅改变已有队列metadata
可见性，不增加缓存响应数据寄存器。>=1拍下游没有新增响应延迟；零拍下游须保持
valid直到ready，普通响应有预期等待，不能说对所有配置都无代价。

同一18140B CoreMark BIN（SHA256 ae05e5be6d30bb8ec111e4734d41407ac31e9de200dd25ac7fef3ee92739e821）
仍639000 timed ticks；同一DDR 4KiB READ/WRITE/COPY/CHASE仍4583/7214/11419/3661。
VM与同源码未切分基线均1810 commits，firstTrapCycles=1723、retired=675。
仅这些工作量的周期成本不变，不宣称所有软件IPC相同或单轮测试是有效CoreMark分数。
原子1/12拍模型事务轨迹不变，LR/SC/AMO、DMA竞争、零拍背压与负向oracle均PASS；
板级应用保留ASan/UBSan，参数检查19项PASS，无全量GSIM/长Linux重跑。

SoC综合最长20.919→19.318ns（-7.65%）、20ns WNS -1.023→+0.482ns，
LUT118181→118171、FF62606/RAMB36=37/DSP=19不变。
只改第一处owner时20.880ns，确有另一处旁路，不能隐去该中间结果。
对已测相同工作量，`speedup=(f_new/f_old)×(ticks_old/ticks_new)` 的周期比为1，
若真实布线能提高频率才有净性能收益；综合延迟改善本身不等于已实现的频率提升。
新版尚未route/bit或上板，真实DDR带宽及Linux运行收益均未测。
最终配置460800连续8N1的BootROM下载数字检查PASS（8481736 cycles）；无物理串口
可靠性结论，当前发布115200 bit/Linux DTB不变。
证据和剩余临界链见 [时序台账](fpga-timing-windows.md) 及
`ddr-opt-20261001/response-owner-cut/results.json`。

## 2026-10-01：批量 staged-fabric 候选的周期成本

按用户要求，一次组合 checked-PMP 请求级、Home 请求/CPU归属缓冲和并行 MMIO，
并启用已验证的 registered replay/ROB retirement。仍双发射、ROB16/PRF48/LSU2/SB2，
默认 `early-issue` 和已发布 bit 不变。两个新请求级各增加一拍，但 MMIO 串联 owner
级数减少，不能把所有访问的净延迟统称增加两拍。

合并必要短测通过：21项 Scala 参数/结构检查，11081项独立 fabric 事务（8项owner、
2项请求缓冲、连续230拍收单、974项原子旁路），共享仲裁两模式各12596项及负向
oracle；VM和板级两个应用均保留ASan/UBSan。CoreMark与DDR复用一次生成/编译的模型，
不做全量GSIM、长Linux、整板route或新bit。

| 同源码、同镜像、同合成AXI模型 | 双owner切分基线 | staged-fabric | 周期增加 |
| --- | ---: | ---: | ---: |
| CoreMark单轮 timed ticks | 639000 | 677729 | 6.06% |
| VM到第一次异常，均675 retired | 1723 | 1997 | 15.90% |
| DDR 4KiB READ | 4583 | 4757 | 3.80% |
| DDR 4KiB WRITE+flush | 7214 | 7272 | 0.80% |
| DDR 4KiB COPY+flush | 11419 | 11860 | 3.86% |
| DDR 4KiB CHASE | 3661 | 3748 | 2.38% |

CoreMark仍为18140B、SHA256 ae05e5be6d30bb8ec111e4734d41407ac31e9de200dd25ac7fef3ee92739e821；
CRC e714/1fd7/8e3a通过，唯一预期报错是单轮运行不足10秒，故不是合法分数。
DDR写回/复制/指针环独立AXI backing核对通过，不是上板测速。
VM仍5次walk、7次PTE RAM读、263次physical request、8次ProbeAckData、16次ReleaseData。
其3000拍观察窗的commits=1536不能与旧1810当同等工作量；到首异常的675条退休才是
等工作量对照，页错误和CSRs/结果均通过。

净收益必须计算 `speedup=(f_new/f_old)*(ticks_old/ticks_new)`。
相对50MHz基线，CoreMark须超过53.03MHz才抵消流水代价；上述VM工作量须超过57.95MHz。
综合估计改善不等于已经达到这些真实布线频率，也不保证所有应用同样受益。
短测：`build/gsim/staged-fabric-20261001`；归档及联合综合：
`E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-fabric`，综合结论见时序台账。

## 2026-10-01：staged-control 控制候选

整批加入分支预完成、稳定前端异常payload和并行rename信用，无新增正常取指流水拍。
仍双发射/原容量，默认和发布bit不变。合并必要短测一轮PASS、一次联合综合；没有
全量GSIM、长Linux、整板route或bit。独立取指/容量/NEMU负向判据及ASan/UBSan保留。

相同18140B CoreMark BIN/SHA不变，单轮timed ticks从677729降为677047（-0.101%）；
合成DDR4KiB read/write/copy/chase仍4757/7272/11860/3748，VM首异常1997拍/675retired
也不变。这一批没有观测到新增周期损失，但原fabric相对639000基线的访存流水代价
仍存在：CoreMark相对50MHz旧板基线须超过52.98MHz才抵消，不能宣称已经取回全部IPC。

受影响裸核NEMU配置ROB32/PRF64/LSU8，282程序、185224编码向量、18000随机整数3seed
通过，退休380429、dual commits164818、19异常/438重定向/2总线错误；它不是板级
ROB16/PRF48/LSU2的理想供指IPC或四路CPU验收。板级短应用使用实际紧凑配置及独立AXI模型。

SoC综合最长15.047→14.831ns（-1.44%），20ns WNS +4.849→+5.065ns，
LUT119401→118723、FF62716→62457。查询证实三处控制依赖从有路径变为无路径，
但新的访存发射→DTLB ready→LSU零拍response ready→APLIC链限制整机。真实Fmax
未重新布局布线测量；不能用局部链改善或倒数计算直接承诺板上速度。
证据 `ddr-opt-20261001/staged-control/results.json`，后续联合切分方向见时序台账。
## 2026-10-01：staged-data 联合访存信用候选

仍两发射/原容量，继承staged-control；一次启用LSU请求寄存、前移既有返回信用，
同时寄存size并重构末端越界译码。请求队列新增一拍；返回空队列仍直通，不叠加
第二个响应FIFO。本地StoreBuffer零拍ACK合同不变。没有全量GSIM/长Linux/板级实现。

| 同BIN、同合成模型、同工作量 | staged-control | staged-data | 周期增加 |
| --- | ---: | ---: | ---: |
| CoreMark单轮 timed ticks | 677047 | 707697 | 4.53% |
| VM到首异常，均675 retired | 1997 | 2261 | 13.22% |
| DDR 4KiB READ | 4757 | 5030 | 5.74% |
| DDR 4KiB WRITE+flush | 7272 | 7642 | 5.09% |
| DDR 4KiB COPY+flush | 11860 | 12567 | 5.96% |
| DDR 4KiB CHASE | 3748 | 3786 | 1.01% |

CoreMark仍18140B/SHA ae05e5be6d30bb8ec111e4734d41407ac31e9de200dd25ac7fef3ee92739e821，
CRC e714/1fd7/8e3a通过；单轮不足10秒不是可报告CoreMark分数。
DDR独立AXI backing、复制及指针环核对通过，不是上板吞吐。
VM保持walk5/PTE7/physical263/probe8/release16；3000拍窗commits=1271不是等工作量IPC。
同675 retired的首异常周期才可与前版比较。

收支仍按 `speedup=(f_new/f_old)*(ticks_old/ticks_new)`：相对上一control候选需
至少4.53%真实提频才抵消CoreMark代价；VM需13.22%。相对旧50MHz/639000ticks
基线，CoreMark需超过55.38MHz；相同VM工作量相对50MHz/1723拍需超过65.61MHz。
不能用未布线OOC延迟倒数承诺这些频率，也不能说所有应用同样受益。

全部必要短测组通过，保留ASan/UBSan及独立负向oracle。26项Scala、23669项信用事务
（满2/2、连续1000收单、1037空队列直通、5240fault payload、3次reset/drain）、
1274016×12数学range、NEMU282程序/380429retired/18000随机整数3seed，burst/ROM/VM/
同镜像CoreMark/DDR。CoreMark和DDR仅生成/编译一次板级模型。
新harness排空/覆盖激励及空FIFO size动态移位曾失败；局部修复，复跑受影响项后验收，
没有关闭sanitizer或修改生成C++。last-subset JSON仍partial-pass，合并归档逐项列出全部
passed组，不宣称一次不间断全绿。资源/时序与边界查询见 [时序台账](fpga-timing-windows.md)。
证据 `E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-data/results.json`。

## 2026-10-01：staged-execute 双链联合候选

两条相关链一次合并：ranked操作数脱离晚到预约/完成授权，退休RAS link由PC+2/4
等价生成。无新增执行/预测周期，真实完成、恢复、异常和store准备授权均不放宽。
保持双发射、原ROB/PRF/LSU/SB容量、默认配置与原bit；早算被拒绝候选可能增加
逻辑切换，动态功耗未测。

同18140B/同SHA CoreMark仍707697ticks；DDR4KiB read/write/copy/chase仍
5030/7642/12567/3786，VM首异常仍2261拍/675retired；本批短测没有观察到周期损失。
NEMU282程序及M/B/Zicond、独立RAS20000拍和故意完成payload/负向oracle、
22项Scala和紧凑VM/板级应用一轮合并全部通过，ASan/UBSan开启。
不是正式CoreMark分数、上板DDR带宽、宽核或完整Linux验收。

一次SoC综合13.091→12.382ns（-5.42%），LUT119658→119473、FF62473→61454。
原ALU数据→RAS、LSU信用→ALU右操作数依赖均由checkpoint查询证明消失；
10ns仍WNS=-2.400ns，前端PC局部11.647→11.879ns回退也记录。未route/bit，
不能以延迟倒数报告实际提频/吞吐收益。相对旧50MHz/639000ticks基线，CoreMark
仍需超过55.38MHz才抵消以前访存流水成本；VM等工作量仍需超过65.61MHz。
详情与后续2–3条组合方向见 [时序台账](fpga-timing-windows.md)。
证据E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-execute/results.json。

## 2026-10-02：staged-rename 三链联合候选

继承staged-execute，整批加入提前fresh目的候选、逐PRF寄存器wake/reserve并行更新、
稳定AUIPC/预测payload。没有新增状态/流水拍，授权及allocation-clear优先级不变。
保持双发射/ROB16/PRF48/LSU2/SB2，默认early-issue和现板bit不变；提前计算无效
payload可能增加切换，动态功耗未测。新目的候选与moveAlias不能同时启用。

| 同BIN/同必要短测工作量 | staged-execute | staged-rename |
| --- | ---: | ---: |
| CoreMark单轮 timed ticks | 707697 | 707697 |
| VM首异常（均675 retired） | 2261 | 2261 |
| DDR 4KiB READ | 5030 | 5030 |
| DDR 4KiB WRITE+flush | 7642 | 7642 |
| DDR 4KiB COPY+flush | 12567 | 12567 |
| DDR 4KiB CHASE | 3786 | 3786 |

相同18140B CoreMark/SHA ae05e5be6d30bb8ec111e4734d41407ac31e9de200dd25ac7fef3ee92739e821，
CRC e714/1fd7/8e3a通过；不足10秒不是正式CoreMark分数。独立AXI backing验证的
DDR不是上板带宽。VM仍walk5/PTE7/physical263/probe8/release16；3000拍窗口1271
commits不是等工作量IPC。裸核NEMU282程序/380429commits等计数也与前批一致。

7组必要短测最终PASS，但初次在共享prediction wrapper容量合同处停止，修复测试
wrapper后只续跑未完成的4组。保留独立oracle、sanitizer及负向检查；不是一次不间断
全绿，也不是完整Linux/四发射CPU验收。板级CoreMark和DDR只生成/编译一个模型。

一次联合综合LUT119473→117161（-1.94%），FF61454→61452；ready路径
12.382→11.703ns，前端PC11.879→11.501ns。全局却12.382→12.409ns、
10ns WNS -2.400→-2.513ns，瓶颈转向分支完成/同拍退休/RAS.CE，RAS.D与
owner.CE的局部回退已记录。因此这是资源及局部链改善，尚不是已验证的提频收益。
没有place/route/bit或实际频率测量，不能用OOC倒数带入frequency×IPC宣称净提升。

按 `speedup=(f_new/f_old)*(ticks_old/ticks_new)`，本批相对前批没有观察到新增周期
成本；过去访存流水成本仍存在。相对旧50MHz/639000ticks基线，CoreMark仍需真实
频率超过55.38MHz，VM等675退休工作量相对50MHz/1723拍仍需超过65.61MHz。
剩余关联链和全部边界结果见 [时序台账](fpga-timing-windows.md)。
证据E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-rename/results.json；目录沿用
10月1日tag，综合完成日期为10月2日。

## 2026-10-02：staged-retire 局部有效、整机回退的实验候选

同一批启用分段分支比较、分离同拍退休fault、并行有序RAS控制，继承staged-rename。
保持双发射/原容量，没有新增执行或预测流水拍；完整异常/实际授权保留，快速退休
fault合同断言进入GSIM生成模型。默认early-issue和已发布bit不变。

同18140B/SHA CoreMark仍707697ticks；VM首异常2261拍/675retired，工作量仍
walk5/PTE7/physical263/probe8/release16；DDR4KiB四项仍5030/7642/12567/3786。
NEMU282程序/380429commits计数亦不变。短测没有观察到新增周期损失，但不是
正式CoreMark分数、上板DDR带宽或全体应用无性能变化的证明。

8组必要短测最终通过，24项Scala、262144分支向量（6种条件分支均双向）、独立
RAS/ledger/预测packet/NEMU/VM/板级应用与负向判据、ASan/UBSan保留。初始Seq
编译错误修复及激励/指令类型相关性的覆盖补查均留档；覆盖补查复用小型已有模型，
没有重跑板级程序。CoreMark/DDR仅生成/编译一次板级模型，未跑全量GSIM或长Linux。

旧branch alignment→commit.valid依赖确实切断，RAS.D/CE/count.D分别
12.180→10.795、12.409→11.054、12.110→10.447ns。但整机最差
12.409→12.883ns（+3.82%），10ns WNS -2.513→-2.901ns；LUT+156/FF-4。
其它终点局部回退见 [时序台账](fpga-timing-windows.md)。因此该组合不推广，不宣称
净频率×IPC收益。当前瓶颈转为ready/分支→重定向捕获资格→动态pending更新，下一批
成组重构该控制链并与原carry比较方案对照；三项联合结果不能当单项独立归因。

没有布局布线频率测量，不能用OOC倒数计算正向吞吐；相对旧50MHz/639000ticks
基线，CoreMark真实频率仍须超过55.38MHz抵消此前访存流水成本，VM等675退休
工作量相对50MHz/1723拍仍需超过65.61MHz。现板频率/CDC结构没有变化。
证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-retire/results.json。
## 2026-10-02：staged-redirect，向100MHz目标推进但未达标

用户目标为先稳定100 MHz、再150 MHz，并为固定外设域准备。本批一次重构早期
redirect资格/静态pending槽位清除并恢复native carry比较；保留退休fault/RAS切割，
双发射及容量不变。多时钟域桥/复位/IRQ/mtime合同已记录，但尚未实现第三域或动态调频。

9组必要短测一次通过，独立捕获/分支/packet/NEMU等oracle及sanitizer保留；26项Scala、
66384捕获向量，含被杀最老winner不退选年轻分支的3771案例。CoreMark707697ticks、
VM2261拍/675退休和DDR四项5030/7642/12567/3786均不变；未观察到新增周期成本。
板级两项共用一个模型，未跑全量GSIM/Linux。不是正式CoreMark分数或实板带宽。

一次联合综合data delay12.883→12.249ns（-4.92%；比staged-rename12.409改善1.29%），
pending12.883→11.598、redirect12.075→10.219ns。LUT117317→117814（+497），
FF61448→61449，RAMB36/DSP仍37/19；owner.CE9.364→9.900ns的回退亦留档。
10ns WNS=-2.266ns、约150MHz=-5.599ns，都未达标。报告是未布线OOC估算，clock
仍在综合后施加，不能以倒数报告板频或宣布频率×IPC净收益。默认early-issue与发布bit不变。

剩余首要链为LSU完成/仲裁→访存地址准备（12.249ns），以及head→前端lockedMask
（12.244ns）。下一批成组处理这两个边界并使用真正综合前10ns约束；若新增流水需
比较同镜像周期。此前访存流水盈亏点仍需实际频率：CoreMark>55.38MHz、VM等工作量
>65.61MHz。100/150MHz整板setup/hold/CDC与实板压力运行证据仍缺，不缩小目标。
全部局部结果及验证范围见 [时序台账](fpga-timing-windows.md)；证据位于
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-redirect/results.json。

## 2026-10-02：staged-preparation 局部收益与面积/全局回退

一次成批优化双候选访存payload预计算和对齐压缩取指PMP，保持2issue与容量、无新增
流水拍。8组必要短测通过，29项Scala、独立selector/PMP/held-mask及原packet/NEMU/VM
oracles保留；同BIN CoreMark707697ticks，VM2261拍/675退休，DDR四项5030/7642/12567/3786
均不变。只复用一个板模型，未跑全量GSIM/Linux或生成bit。

首次真正综合前加载10ns约束，一次综合512秒（synth_design412秒）。访存地址
12.249→7.484ns，through晚到issued-owner路径6.710ns且0CARRY8；取指mask12.244→11.171ns。
但PRF11.636→12.291ns、redirect10.219→11.032ns及RAS回退。全局最差12.291ns，
WNS10ns=-2.309ns、约150MHz=-5.642ns，仍不达目标；TNS10ns改善到-26443.410ns不能
代替WNS签核。LUT+9331（7.92%）到127145，FF61443；映射约束与结构同时变化，未做
独立归因，不推广候选或声称频率×IPC净收益。发布50MHz bit不变。

下一批围绕late grant/kill→ALU/PRF payload及trap/recovery/invalidate→fetch request/PMP
控制耦合继续改造，保留精确异常、held mask和原架构oracle。多时钟域准备合同仍在，
第三域/DFS未实现；100/150MHz整板与实板稳定运行仍待验收。
详见 [时序台账](fpga-timing-windows.md)，证据
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-preparation/results.json。

## 2026-10-02：staged-payload，取指掩码切断，CPU仍需收敛

成批完成环形one-hot issue payload、早期completion owner及raw fetch presence，保持
双发射容量、授权/精确异常/locked fetch协议，不加流水拍。7组必要短测通过，32项
Scala、独立selector/取指oracle及原NEMU/VM/板级应用均通过；26条完整IPC记录与上版
相同，CoreMark707697ticks、VM2261/675和DDR四项5030/7642/12567/3786不变。额外取指
payload隔离witness只复用模型重编译C++。不跑全量GSIM/Linux，不生成bit。

两版均综合前加载10ns约束，一次综合581秒。PRF12.291→10.503ns，fetch mask11.171→
5.318ns，redirect11.032→9.369ns；结构查询证明invalidate不再经过PMP address但仍
控制instruction-valid。全部追踪family改善或不变。新最差ROM回复仲裁到LSU data
仍11.818ns，原DataResponseBuffer flow=true并非实际payload寄存边界。

全局12.291→11.818ns（-3.85%），10ns WNS=-1.836ns，约150MHz=-5.169ns，仍不达标；
LUT+2.02%到129714、FF61439、RAMB36/DSP37/19。保持下一实验基线但不切换默认或发布
bit，不以未布线OOC宣称实际频率×IPC收益。新检查脚本端口名错误已修，只复查DCP，
首次失败证据保留。下一批集中registered回复、memory/MMIO payload和PRF操作数链。
动态调频/第三域尚未实施；静态100MHz须匹配UART/BootROM/timebase及整板与实板验收。
详见 [时序台账](fpga-timing-windows.md)，证据
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-payload/results.json。

## 2026-10-02：staged-return，回复切断成功，尚不能证明净性能收益

同批完成translated CPU回复寄存边界、两层MMIO memory payload直通、并行one-hot物理
操作数读取。双发射ROB16/PRF48/LSU2/SB2不变，ALU不增加拍；回复最少增加1拍。
37项Scala及全部受影响短测通过。Vec setter/Record clone仅修测试wrapper；VM UBSan
触发的无效owner移位修于DUT，固定8种移位和零默认值，不关闭sanitizer、不改oracle。
保留失败记录；恢复时只重跑fabric/VM/board，raw JSON仍partial-pass，不伪称一次全过。

同BIN CoreMark707697→731130ticks（+3.31%），VM固定首个里程碑2261→2525拍、均675退休
（+11.68%）。DDR四项5030/7642/12567/3786→5295/7714/12987/3847（+5.27/+0.94/+3.34/
1.61%）。26项裸核IPC完整记录相同，但裸核不经过新增SoC回复级。仍只用一个板模型；
单轮CoreMark和模拟AXI不是正式分数或实板带宽。

一次综合542秒、synth_design442秒，两版综合前均10ns。查询证明回复data/error/pageFault/
valid的67输入到67输出组合路径为0，LSU data11.818→8.995ns（slack+0.987ns）；新回复
存储输入8.153ns/信用状态8.609ns。PRF10.503→10.516ns，换成pending→issue→ALU写回
成为最差，不能说one-hot已解决PRF。其独立模块10064LUT；整批LUT+6451/+4.97%到136165，
FF+9到61448，RAMB36/DSP37/19不变。不能把单模块资源数当成整批净增加的独立归因。

全局转为ROM回复仲裁→fallback下一请求地址/译码→ready→fetchAdapter.state.CE，11.425ns；
10ns WNS -1.836→-1.529ns、TNS -7456.943ns，约150MHz WNS -4.862ns，仍不满足目标。
RAS CE虽然data9.965ns，slack仍-0.069ns：必须看setup/时钟裕量，不能只看data<10ns。
面积和部分终点回退、周期成本已留档，不推广默认或发布bit；实际频率×IPC未验证。
相对即时前版，要抵消周期代价，CoreMark实际频率需提升>3.31%，该VM工作量需>11.68%。

下一批联合处理取指回复→下一请求的反馈/地址payload、前端decode→rename allocation控制、
pending/issue→PRF写回与操作数选择面积。仍每批2–3条相关链、必要短GSIM后一次综合；
不因小幅OOC改善生成bit。动态clk先准备固定外设/timebase与启动选频，运行态DFS后置；
100/150MHz完整整板和实板验收仍待完成。证据与详细比较见 [时序台账](fpga-timing-windows.md)
及E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-return/results.json。

## 2026-10-02：staged-fetch-address，周期不变、面积回收，尚未100MHz

成批提前fallback地址计算、精确静态TL prefix译码，并恢复binary PRF操作数路径；保持
真实寄存回复，双发射容量/授权/精确异常不变，无新增流水拍。十组受影响短测汇总通过，
23项Scala，原协议/NEMU/VM oracles与反例、ASan/UBSan保留。4word预取仅修驱动的完整
packet/已接受ROM握手契约，失败日志与raw failed/partial JSON留档；不是一次全跑通过。
实际板级2word不启用4word-only预取。一个板模型，不跑全量GSIM/Linux。

同BIN CoreMark731130ticks、VM2525拍/675退休、DDR5295/7714/12987/3847，以及26条完整
IPC配置/cycles/retired记录均与staged-return相同。无本批新增周期损失，但相对
staged-payload继承的回复成本仍CoreMark+3.31%、VM+11.68%；不能把即时比较当作零总代价。

一次综合前10ns联合综合576秒，DCP查询150秒。最差11.425→10.890ns（-4.68%），
10ns WNS-1.529→-0.994，约150MHz-4.862→-4.327，仍未达标。限定D.valid→next A.address
10.338ns/0CARRY8；全局改成多层D-ready/ROM请求信用反馈。LUT136165→129570（-4.84%），
FF61448→61439，RAMB36/DSP37/19。RAS CE回退9.965→10.315ns（slack-0.419），以及
150MHz失败端点增加都完整记录。OOC改善不是物理时钟/实板频率×IPC证明，不切默认/bit。

下一批共同处理ROM请求信用/返回ready、PC相邻取指命中及prediction→rename/PC资格，
PRF10.503ns与RAS回退继续跟踪。第三域/DFS和100/150MHz整板稳定运行仍未验收。
详见 [时序台账](fpga-timing-windows.md)；证据
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-fetch-address/results.json。

### 2026-10-02 staged-fetch-control：短验证通过，OOC改善仍未达标

双发射/ROB16/PRF48/LSU2/SB2不变。一次三条相关链：两项ROM回复弹性信用、TL回复
source/owner与valid并行查询、PC-relative预测资格不等待完整target加法。实际target、
JALR/RAS/间接预测与precise exception/ownership合同保持；空队列ROM回复不新增拍数。

最终一次完整九组短测通过：27项Scala、50360独立full64预测向量、原路由/ROM边界
检查、独立ROM满空/复位/排序/背压模型、packet/NEMU/VM以及一个板模型上的两份同BIN。
初次两次结构检查仅为Chisel队列层级名假设失败，原始日志/failed JSON完整留档。
26条完整IPC记录、VM2525拍/675退休、CoreMark731130ticks、DDR5295/7714/12987/3847
均与上一候选相同；继承的回复拍数成本不消失。ASan/UBSan及8个反例仍启用。

118SV只做一次综合前10ns的SoC分区综合，580秒（synth_design479秒）；随后仅用DCP
46份报告查询147秒。最差10.890→10.590ns，WNS-0.994→-0.608ns；TNS-6773.861→
-1400.467，失败端点25817→12079。LUT129570→129718（+148/+0.114%），FF+1至61440；
RAMB36/DSP仍37/19。ROM外部D.ready→A.ready路径1→0、四层TL late-valid→source路径4→0
已证明；既有CPU回复真实寄存切断仍保留。三项一起变化不作独立面积/时序归因。

取指adapter数据9.938ns但CE slack仍-0.042；全局移到预测器更新10.590ns。PRF10.503、
RAS CE10.315仍超标，issueQ10.355→10.359小幅回退；前端/ROB/ready改善但未全过。
约150MHz WNS-3.941ns、失败59936，仍未达标。不声称实板频率×IPC正收益，不切默认/
clock/reset/IP/bit；100/150MHz与第三外设域、timebase/选频仍未验收。导出参数仍为
50MHz/115200，不能拿10ns重约束代替真实100MHz硬件、软件timebase及整板验收。
证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-fetch-control/results.json与short-tests.json；
61份短测日志、46份DCP报告、53份源码快照及相同固件。完整路径审计纠正此前基于网名
的顺序PC推测：实际串行项为异常/恢复候选仲裁、选中token再次授权和重定向token匹配，
之后才传播到completion/退休与predictor/RAS。PRF bit-manip写回链继续跟踪。

### 2026-10-02 staged-recovery-control：相关恢复链候选合同

继承staged-fetch-control固定双发射，三条链一起处理：原始外部/局部候选并行存活与
恢复资格检查；逐槽杀除与completion保留边界预计算；trap/local重定向token提前匹配。
不缩短64位tag、不改变年龄/同龄优先级或陈旧local阻挡external的既有选择语义，也不
新增流水周期。两项开关默认false，early-issue/时钟/IP/发布bit保持不变。
独立oracle采用原始串行“外部准入→年龄选择→选中token再次检查”算法，不复制新硬件
布尔化简；同时检查所有槽的kill/survive、恢复期间更严格边界及trap覆盖完整token匹配。
短测入口为GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-recovery-control-stage-test。
功能/时序/面积/周期结果须以本候选实际报告为准；此合同不是100MHz验收。

实测必要范围通过：30项Scala、810304独立恢复/token向量、8/64tag ledger、packet/
NEMU/VM及一个板模型上的同BIN CoreMark/DDR。26完整IPC、VM2525/675、CoreMark731130、
DDR5295/7714/12987/3847完全保持，无本批新增周期成本；既有回复寄存成本仍保留。
补充system的固定32/direct-IRQ原断言及反例通过；新旧注册IMSIC封装都在同一零延迟
eligibility断言失败，日志/FIR留档，生产一拍IRQ时间合同仍未验收。

120SV一次综合868秒（synth_design768秒），49份checkpoint-only报告151秒。恢复
准入/token匹配through-path7.914ns、kill5.954ns；predictor10.590→10.172、ROB
10.289→9.938、ready10.165→9.922均改善。但全局10.590→10.931ns、WNS-0.608→
-0.949，PRF/pending/redirect回退；不能把局部改善或失败数减少当作目标达成。
10ns TNS-2339.994、失败4945；约150MHz WNS-4.282。RAS CE-0.001、fetch CE-0.042
仍未过。LUT-1687/-1.30%至128031、FF-14至61426，RAMB36/DSP37/19保持。

因此不推广默认/发布bit，保留staged-fetch-control为较好全局参考；本候选控制链
收益只作为下一批联合改造的候选基础。下一批一起缩短ready/双发射操作数、bit-manip
与主ALU结果选择、completion/PRF写回链。未布线、导出参数仍50MHz/115200，不宣称
物理Fmax或实板频率×IPC收益；100/150MHz、第三域、选频/DFS及注册IRQ门槛仍未验收。
完整16族及回退证据见 [时序台账](fpga-timing-windows.md) 和
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-recovery-control/results.json。

### 2026-10-02 staged-execute-select：无新增周期成本，联合时序测量中

双发射基线同批改造并行前二名rank、base/B互斥结果选择及完整completion payload
优先选择。吞吐/容量/执行周期和完整tag/精确异常/原grant优先级不变；默认、IP、板级
clock/reset/bit不改。33项Scala及七组行为必要范围通过；1087008独立算术输入、原
16/32循环选择扫描、全部32来源掩码/完整字段、原NEMU/system/VM/同BIN板模型验证
通过，8反例和ASan/UBSan保持。两次前置展开/驱动编译失败留档，raw运行是partial-pass，
不冒充一次全跑通过；direct-IRQ system不是生产注册IRQ时间签核。

26条完整IPC、VM2525/675、CoreMark731130和DDR5295/7714/12987/3847完全保持，没有
本批测到新增周期。121SV唯一一次pre-mapping10ns综合于08:31:43启动，当前仍运行；
时序/面积尚无结论，不能提前宣称优于fetch-control或达100MHz。待同DCP查询完整终点
族后决定，不跑全量GSIM/Linux或route/bit。证据
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-execute-select/results.json与short-tests.json。

### 2026-10-02 staged-frontend-select：前端三链合并短测，无额外周期

保持双发射，在上批候选之上联合处理fetch tag动态读后比较、控制流预测decode、
同包AUIPC/JALR资格链。全64位tag/目标、后端合法性/异常、缓存数据优先级和
杀除/背压合同不变；新开关默认false，没有新增流水拍。

一次36Scala和九组必要短测通过；独立编码/完整64位算术/选定set扫描共277728
向量，10负注入均拒绝。26条IPC的全部23字段与上批一致，同BIN CoreMark731130、
DDR5295/7714/12987/3847以及VM2525/675完全保持。没有本批额外IPC损失证据，
但频率×IPC收益必须等实际SYN/route/板测，不能先由结构化改造推断。

证据已保存到E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-frontend-select。
78份原始日志/FIR/固件逐字节核对；196份当前源码及独立oracle冻结。上批单次
staged-execute-select综合仍运行，使用其旧72源码/121SV快照，不是新工作树。
新候选未导出/综合，不并行启动第二次SYN。没有完整GSIM/Linux/route/bit，
没有修改时钟IP；CoreMark一迭代/合成DDR不当作板级性能。注册IMSIC时间合同及
实际100/150MHz仍未验收，可调时钟不提高CPU逻辑Fmax。

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

### 2026-10-02 本轮综合完成：更接近10ns，尚不晋级默认

staged-frontend-select已一次导出124SV并完成单次有界RuntimeOptimized综合：
总430.5秒，synth_design308秒，预映射10ns。未重复功能短测，原36Scala/九组、
277728独立向量/10反例及26条23字段IPC一致结论保留；新硬件未增流水拍。
只复用DCP完成57份报告，首次查询因lookup综合网表计数错误停止，补7份后完整，
不是一次无错误查询；源码/测试oracle/DUT未因报告问题改变。

全局CPD10.295、WNS-0.313、TNS-68.758、失败2062；此前最佳10.590/-0.608。
剩余主链是fetch到RAT/ROB10.295、issue/ALU/completion到PRF10.181；前端PC/
队列10.005/10.008也微超标。LUT130936/FF63205比最佳+1218/+1765，RAMB36/
DSP37/19不变。策略由Default同时改成RuntimeOptimized，不能隔离RTL-only收益；
未route/上板、实际导出仍50MHz/115200，不能宣称100MHz或板级频率×IPC收益。

已净清理约1.37GiB旧可再生输出，失败.Xil可由ZIP恢复；日志、FIR、固件、源码、
用户改动和DCP/bit/时序报告保留。详单cleanup-20261002.json。优化程度、全部16族、
查询修复和状态边界见本轮[时序台账](fpga-timing-windows.md)。默认/发布bit不变；
实际100/150MHz、注册IRQ、第三域与DFS仍未验收。

### 2026-10-02 三组敏感链合并验收：不能视为整体正优化

staged-sensitive-paths在staged-frontend-select上启用独立预测源资格、固定Zba
并行加法、两项物理取指请求缓冲；容量/二发射/默认不变，execute不加拍，
物理取指请求增加1拍。39Scala/十组必要短测通过，26条bare-core的全部23字段
IPC一致，但bare-core不经过新增平台队列，不能推成板级无周期损失。

同BIN模型：VM首trap2525→2530（675退休，+0.20%）；CoreMark单次731130→761601
（+4.17%，同频吞吐约-4.00%）；DDR四项+0.05%至+0.53%。CoreMark短运行警告
保留，既定3CRC及退出通过；不是有效CoreMark分数、实板吞吐或MIG峰值带宽。

一次127SV导出/一次484.5秒综合（synth_design376秒），使用与直接基线相同
RuntimeOptimized预映射10ns。59份DCP报告一次查齐：CPD10.291/WNS-0.309/
TNS-5.783、失败244（原2062）；PRF9.934、取指状态6.562、队列9.538转正，
仍RAT10.291/PC10.014超标，PRF仅48ps。LUT+814、FF-1，BRAM/DSP不变。
逻辑35级但估算连线占78.8%，实际瓶颈迁移到取指/合法性译码/rename到RAT。

周期归一估算收益约-3.96%，且尚非route/板级证据，因此不晋级默认或发布bit。
实际配置保持50MHz/115200；新快照、原日志、反例、BIN哈希和路径全表见
[时序台账](fpga-timing-windows.md)与staged-sensitive-paths/results.json。
优先处理残留RAT/PC依赖，同时回收请求队列的周期成本；注册IRQ/CDC/RDC、
实际100/150MHz及第三域/DFS仍未验收。

### 2026-10-02 staged-decode-align：周期回收成立，100MHz仍未签核

三组合并：固定半字/lane1并行对齐+类并行合法性、空请求队列flow直通但不借满队列
credit、MIN/MAX直接operand资格。继续二发射，四个选项默认关闭，无新流水级。
42Scala/12个必要范围/14反例通过；首夹具getter编译错后只续跑未完成9范围，
两份原JSON的failed/partial-pass状态保留，由汇总记录接受结果。

26条bare-core IPC全23字段不变。相同BIN单模型：CoreMark761601→731130
（周期-4.00%，同频模型吞吐+4.17%）；DDR四项恢复5295/7714/12987/3847；
VM首trap2530→2525/675退休。这是收回上一版队列成本，周期与更早frontend-select
相同；短CoreMark警告未删除，不是有效分数/实板带宽/Linux验收。

一次129SV/425.4秒RuntimeOptimized预映射10ns综合，复用DCP查齐61报告；
首次旧tag计数查询错误，修复报告并只补7项，未重综合/改硬件。
CPD10.178、WNS-0.196、失败106（原244），但TNS-12.991比-5.783更差。
PC9.795转正；残留译码/B合法性→rename第二destination→free/RAT10.178。
PRF9.941仅41ps，scoreboard9.921仅61ps，均比上一版余量更薄。
LUT+580/FF+2，BRAM/DSP不变。全16族及回退见[时序台账](fpga-timing-windows.md)。

按OOC CPD与同BIN周期归一相对直接基线投影约+5.32%，相对更早frontend候选仅
+1.15%；投影不是实际frequency×IPC证明。候选不晋级默认/发布bit，保持50MHz/
115200；未route/上板/全量GSIM/长Linux，实际100/150MHz、注册IRQ、CDC/RDC、
第三域/DFS仍未验收。下一批集中B合法性/物理destination准入及PRF/scoreboard薄余量。

## 2026-10-02：重命名/W结果汇合修正候选

staged-word-destination（两发射，ROB16/PRF48）完成48项Scala检查、8类受影响短测和一次修正批综合；本次OOC 10ns setup仍未满足。 未route或上板，不能据此宣称实板100MHz稳定。

decode-align → rank-legality → word-destination的OOC全局CPD：10.178 → 10.253 → 9.915ns；最后WNS -0.115ns，失败端点80。首批局部改善但全局回退未隐瞒，修正批单独保留。

26 IPC×23字段、同BIN CoreMark731130ticks、DDR5295/7714/12987/3847、VM2525/675不变；本轮没有新增流水级/周期损失。在同配置下组合重构周期不变，并不证明提高真实CPU时钟后frequency×IPC会等比例提升：DDR/CDC与CPU比例变化可能改变访存周期。1次CoreMark仅CRC/exit回归，不是正式分数。

细节、19家族时序及资源增减见docs/fpga-timing-windows.md；证据：E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-word-destination/。默认/发布保持50MHz、115200，未改MMCM/MIG/ROM内容、未生成bit、未跑全量GSIM/长Linux；注册IMSIC temporal、真实DDR/CPU频率变化下IPC、整板setup/hold/CDC/RDC、第三域/DFS及实板高频仍未验收。

## 2026-10-02：请求capture/目录批次，10ns OOC首次过线

staged-request-capture保持二发射，合并独立RAM capture、并行目录tag比较和精确前缀
RAM范围判断；没有新增可见流水周期。51 Scala及6类必要短范围通过，5反例拒绝；
同BIN CoreMark731130、DDR5295/7714/12987/3847及VM2525/675完全不变。
未重跑未改bare-core NEMU/26IPC，旧证据不得称本批新结果。

一次700.7s综合、复用DCP189.1s/71报告：10ns WNS-0.115→+0.234、setup失败80→0、
CPD9.748；RAM WE9.915→1.011。LUT-31/FF+1；原CPU家族时序不变。
周期保持而OOC裕量改善成立，但实板frequency×IPC仍未测；1迭代CoreMark不是有效分数。

ROM反馈仍仅234ps，指针466ps，不能把“综合过线”称为边缘风险全部解决。
未route/bit/默认晋级，仍为50MHz/115200稳定发布。150MHz仍WNS-3.099；
整板CDC/RDC/实际高频、第三域/启动选频/DFS均未验收/实现。
详情：[时序台账](fpga-timing-windows.md)；证据staged-request-capture/results.json。
