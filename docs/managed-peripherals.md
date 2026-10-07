# CMU 管理的 UART 与原生 GMAC（2026-10-04）

2026-10-06：r4已上板TFTP/Linux/小ping，长帧活性失败；当前Home修复短回归通过。
新增Linux valence-cmu CCF固定频率provider、GMAC TX/RX clock consumer、
UART critical；没有动态调频/GMAC runtime-PM。Debian/2GiB/自动驱动见
[VL100 BSP](vl100-debian-bsp.md)。下文无driver/未上板文字为10-04历史阶段。

本批在 WSL 主工程 `/home/openion/Valence` 完成可选生产 `BoardSocTop` 接入：
CMU 管理真实 UART 和 GMAC TX/RX 引擎，原 packet DMA 四条流接 native GMAC。
默认开关仍关闭、旧端口和已上板整数 100 MHz / 460800 bit 不变。
**不是 RGMII/RTL8211F 上板、Linux 网络驱动、完整 SoC 时序或新 bit 验收。**

## 配置与连接

`BoardSocTop(..., managedPeripherals=true)` 必须同时设置 `ethernetControl=true`、
`ethernetDma=true`、`clockManagementHz>0`、`peripheralClockHz>0`，不能再添加额外
`managedClockResources`。native 与旧 AXI Ethernet 后端互斥，不混用寄存器 ABI。
单一 `ManagedPeripheralBank` 拥有 CMU；不能再外接第二个 CMU 或重复门控。

| 资源号 | 时钟资源 | 本候选频率 | 可申请停钟 |
| --- | --- | ---: | --- |
| 0 | AON/CMU | 50 MHz | 否 |
| 1 | CPU/控制寄存器/packet DMA | 100 MHz | 否 |
| 2 | TIME | 随 CPU | 否 |
| 3 | UART 引擎 | 50 MHz | 是 |
| 4 | DDR_UI | 配置声明默认 250 MHz | 否 |
| 5 | GMAC TX 引擎 | 125 MHz | 是 |
| 6 | GMAC RX 引擎 | 千兆标称 125 MHz | 是 |

GATEABLE=`0x68`，STOP/WAKE/FAULT 用这些资源位。DDR_UI 标称值必须与实际 MIG 匹配；
独立外设 OOC 没有实例化 MIG，不证明 UI 实际频率。
常开 AON、原始 UART 时钟、125 MHz TX 和 PHY RX 原始时钟必须持续运行；只关闭
三个专用 SYNC BUFGCE 后的引擎钟，不关闭输入采样、PHY、MIG 或 Clock Wizard。
目前只支持 1G 全双工，不以 125 MHz 模型宣称自动适配 10/100M 协商。

顶层连接 CPU `clock`、`io_alwaysOnClock`、`io_peripheralClock`，以及新增
`io_nativeGmac_rawTxClock/rawRxClock`、8-bit GMII RX/TX、MDIO/MDC/link 输入输出。
RGMII DDR 数据转换、IOBUF/PHY reset、实际 pin XDC、时钟偏移和 driver/DT 仍须另接。
没有直接修改旧 Vivado 工程。可选导出入口（不是综合/bit 命令）：

```sh
mill -i IonSoC.test.runMain ooo.ManagedBoardSocMain <fresh-output>
# 可选参数：CPU-Hz profile baud ISA AON-Hz UART-Hz DDR-UI-Hz
# 默认：100000000 staged-fetch-feedback 460800 rv64imac 50000000 50000000 250000000
```

双发射固定为 2；F/D 开关独立，但本次没有新的带 FPU 整 CPU 10 ns 结论。

## 排空、唤醒与吞吐合同

- UART：CPU 常开 `ClockRegisterAdmission` 停止新 MMIO，并唤醒关闭的目标钟；
  完整请求/回复 `RegisterClockDomainBridge` 容量一项，必须等源端回复被消费。
  ACK 同时检查 TX/RX FIFO、收发状态、MMIO 回复、IRQ 和 break；未读 RX/未服务 IRQ
  不会被静默丢弃来完成停钟。DLL/格式/SCR 等保留，不做局部热复位。
- 被屏蔽的 UART 自动唤醒或目标源缺失时，**尚未转发**的请求 1024 CPU 周期后返回
  稳定 error，失败写无副作用；已有下游事务不支持单边丢钟自动恢复，仍须共同冷复位。
- UART 原始输入先两拍同步，再保留完整 waveform 64 原始周期，增加约 1.28 μs
  固定延迟；引擎内原同步/RX 采样延迟另计。波特率仍 460800，FIFO/格式合同未改变。
- GMAC：CPU adapter 不接受新 TX 描述符，但已开始的六字控制头、数据和帧尾继续排空。
  RX data 与六字 status 尾均必须被 DMA 消费；FIFO 双端输出/预读、配置 ACK、最后一份
  统计快照也纳入 ACK，不能只查 DMA busy 或 FIFO 空指针。
- 两个 52-bit 配置 mailbox 同拍接受同一快照，各自安全帧边界应用；未完成时 CSR busy。
  配置与 TX 描述符自动唤醒相应引擎；初次配置会置 WAKE_PENDING，申请 STOP 前先服务
  唤醒来源并 W1C。持续来源或 pending 会保持开钟，不能仅反复写 STOP。
- GMII RX 原始 DV/ER/8-bit 数据完整延迟 128 原始周期（125 MHz 下 1.024 μs），
  保留首帧波形直到唤醒；RAW 永远运行。首输入保证依赖固定时钟比例、有效 WAKE_ENABLE
  和持续原始时钟，不是无限缓冲、缺钟恢复或 DFS 保证。软件屏蔽 RX wake 时可主动丢帧。
- 帧 FIFO 16 个完整 38-bit beat，每本地周期最多一拍；GMII 每 media 周期一字节。
  延迟线不降低连续输入吞吐，但原 TX/RX 各单个 2 KiB 帧缓冲仍不是持续满线速架构；
  RX 缓冲被持有时会丢新整帧，仍须驱动及时 ARM/消费。
- 统计使用原子 `CdcCounterBank`，TX 三字段、RX 四字段，握手稳定 delta 在 CPU 汇入六个
  64-bit CSR 计数器。源事件不背压，不把脉冲直接两拍同步；每字段两次已消费快照之间
  增量须小于 2^32。清统计与同拍增量按原 CSR 新事件优先规则处理。
- 生产 CMU 排空 watchdog 为 65536 AON 周期（50 MHz 下约 1.31 ms）；GSIM fixture
  缩短为 4096 周期。排空超时保持钟开并报错。CLOCK_ENABLE/STOPPED 是策略命令，
  实际门控/解除隔离有同步传播延迟，软件须等 ISOLATE 清除后使用。

MMIO 不变：UART `0x10000000`/APLIC3，packet DMA `0x10002000`/APLIC6，
native GMAC `0x10040000`/APLIC5，CMU `0x10080000`/APLIC7。
native GMAC 单口 4 KiB，其余被路由的旧 Ethernet 大窗口地址由 native 前端返回 error；
不是 AXI Ethernet 32-bit 寄存器映射。TX reject 在 native IRQ bit4（旧标签 underflow）。

## 功能与时序证据

`build/gsim/managed-peripherals-20261004-r4/receipt.json`：3 项 Scala 配置/elaboration
（含真实生产 SoC 与 packet DMA 接线）、UART 首字节 24 组、TX 8/RX 10 帧、10 个
status 尾、坏 FCS、停钟/唤醒/屏蔽唤醒 error、211 MMIO、553 背压周期；两个严格错配
负例通过。原 UART 格式回归 40 cases、真实 packet DMA 回归 54 cases 同批通过。
引擎使用 GSIM，所有时钟 alias 且物理 gate 省略；固定版 GSIM 派生 async reset 别名
生成缺陷由 **仅测试 FIR 中按周期采样复位** 绕开，实际 RTL/固定工具源未修改。
这不是独立边沿或异步复位证明。

`build/fpga/managed-peripherals-20261004-r1/native-results/functional-r5/receipt.json`：
CDC-only xsim 用生产 delay/proxy/bridge/counter/policy/ACK/BUFGCE 与 surrogate sink，
无 CPU、UART/MAC 引擎或 PHY xsim。独立 100/50/125 MHz、不同相位，两条 raw 源
390/1332 字节、真正停钟后首波形、完整脉宽/无边沿、回复/统计背压、共同异步冷复位和
两类错误注入通过。初始测试台 stale STOP、共享静态 task 及动态事件 elaboration 卡住
均保留失败证据；最终使用 automatic task 和显式时钟等待，没有放宽 oracle。

组合 `ManagedPeripheralBank` 只综合一次、place/route 一次；初始约束端点失败后复用
synth DCP，最终仅打开 route DCP 复核边界预算。器件 `xczu15eg-ffvb1156-2-i`：

| 指标 | 最终组合 OOC |
| --- | ---: |
| CPU 控制侧/AON/UART/TX/RX 周期 | 10/20/20/8/8 ns |
| 内部 setup / hold 最差裕量 | +3.018 / +0.031 ns |
| 内部最差链 | RX typeLength → 排空 ACK，4.889 ns 数据延迟 |
| LUT / FF | 3964 / 4503 |
| RAMB18 / BUFGCE / DSP | 2 / 3 / 0 |
| 13 组 held/Gray/RAM skew 最小裕量 | +7.107 ns（8 ns 预算） |

所有内部 endpoint 有最大延迟约束，握手 payload、Gray、RAM 和单比特同步均 scoped
max-delay；不用全局 clock groups、宽泛 false-path 或 waiver。原始→受管 ingress 为
同一 primary clock 的相关路径，仍正常计时，不当异步数据屏蔽。

**不能宣称整板/所有时序通过：**零 I/O 预算复核的整体 hold=-0.555 ns（CPU/MMIO
与 GMII RX 输入边界），非内部寄存器数据链；需要真实相邻模块/RGMII/PHY 的预算。
OOC 缺真实 HD.CLK_SRC，3 个输出 clock 与 commonReset 不属于数据 I/O 预算。
DRC 保留 213 个无 routable load 端口网，不是零 warning。全部必要 RTL、报告、DCP、
失败日志与 SHA-256 在 WSL `build/fpga/managed-peripherals-20261004-r1/`。

CDC 报告未隐藏：4 组 CDC-6、650 条 CDC-15 Warning，5 条 Critical：

- CDC-1 一条：TX 配置 52-bit 原子 mailbox 被综合裁剪为单个 enable held/captured bit。
  有 request/ACK 两拍同步、保持所有权和 8 ns settle 约束，不是自由变化异步电平。
- CDC-11 四条：AON quiesce 分别到 UART/RX 的持续 RAW 采样器和其同 primary 的受管
  ACK 域。两处同步可在 gate 停止时有意保留不同状态；没有将它们组合重汇聚作数据。
  同样生产拓扑的 CDC surrogate 检查了延迟/保留/排空/唤醒。仍保留为整板物理复核项，
  不能以功能仿真或协议解释代替亚稳态与板级时序签核。

总验收 `audit-final.json` 状态为 `PASS_FUNCTIONAL_AND_INTERNAL_OOC_NOT_BOARD_SIGNOFF`。
没有 CPU IPC/Fmax、功耗、FPU 整板、动态调频、Linux 网口或 bit 新结论。
短验证复现：

```sh
GSIM_CXX=/usr/lib/llvm-19/bin/clang++ python3 simulator/gsim/managed_peripherals.py --tag UNIQUE_TAG
mill -i IonSoC.test.runMain ip.ManagedPeripheralCdcRtlMain <fresh-cdc-rtl>
```

原生 Windows：`python fpga/zu15eg/run_managed_peripheral_cdc.py <cdc-rtl> <fresh-output>`。
组合 OOC 脚本 `fpga/vivado-managed-peripherals.tcl`；报告复核用
`fpga/review-managed-peripherals.tcl`，不要为查询报告重跑整 CPU。
