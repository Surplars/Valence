# 模块化 SoC / AIA IP 合同

当前应用 SoC 选择 AIA 1.0：设备中断线 → APLIC → MSI → 每 hart IMSIC → CPU 精确中断入口。
PLIC 是后续可替换的兼容控制器，不是 APLIC 的别名，也不把旧 PLIC 的存在当成已验证支持。
RVA23S64 与继承的 U64 必选能力仍为目标，guest 文件只是 H/AIA 的组成部分，不代表 H 已实现。

依据：https://docs.riscv.org/reference/aia/v1.0/IMSIC.html 。IMSIC IP 已实现；MachineCore 已接通 M/S 文件 CSR 与精确陷阱处理。
M/S 外部中断及 M 根域到 S 子域的 UART source3 委托已接通；PLIC 适配、VS 中断和
Linux AIA 设备树/驱动验收仍待完成。整数基准配置仍保留异常停止模式。

## 依赖和复用边界

- `soc.ip.dma`：四项在途内存拷贝IP，独立RegisterPort控制/内存端口和完成中断；详见 [DMA合同](dma.md)。
- `soc.ip.bus`：不依赖任何 CPU 的寄存器事务端口。地址为字节地址；数据和 byteEnable 右对齐到访问地址，
  不采用 AXI/TL beat 内偏移格式。平台适配器负责转换、事务 ID、错误编码及跨时钟域；不伪称原生 AXI/TL。
- `soc.ip.axi`：独立的 64 位数据 AXI4 通道类型；新核的有序数据口桥位于 `soc.core.ooo`，
  不把旧 AXI3 风格定义作为新平台协议。当前桥仅独立验证，见 [AXI4 内存桥](axi4-memory-bridge.md)。
- `soc.ip.interrupt`：独立 IMSIC 状态、优先级、MSI 和 CSR 原子事务，不导入 `soc.core` 或全局配置。
- CPU：只在 CSR 获得不可撤销提交授权后发起 IMSIC 请求；保存 iselect，检查 M/S/VS 权限与 VGEIN，
  接收各文件的外部中断电平，再由 mie/mip/delegation/status 等决定精确陷阱。CSR 响应错误需转换成
  illegal/virtual instruction，不得把未经授权的请求交给 IP 后再回滚。
- 平台：实例化 CPU、控制器、ROM/RAM、互连和外设；负责地址分配、参数和 irq 路由。AIA/PLIC 替换发生在
  平台组装层；PLIC 走 MEIP/SEIP，AIA 另有 CSR 侧带。可替换不意味着软件寄存器接口相同。
- FPGA 封装：后续将稳定 RTL 接口打包为 Vivado IP；不把 IP-XACT、BD 自动化或综合报告当成目前已有功能。

新 IP 在 `src/main/scala/ip` 添加；既有内存/总线/外设按独立验证后逐项迁移，不批量移动旧逻辑。
各 IP 要有局部参数、协议合同、独立 GSIM 验收及 RTL 导出入口。

## 新核的互联边界

旧 `IonSoC` 使用 TileLink `TLXbar` 连接顺序核、调试模块和设备。新 `MachinePlatform`
默认仍由乱序核的 `DataPort` 经 MMIO/原子/DMA 边界直连同步 RAM；
本地外设使用独立 `RegisterPort`。可选 `tileLinkMemory` 配置现将普通 RAM 路径接为
`DataPort`→`OrderedTileLinkBridge`→TileLink A/D→`TileLinkDataRamAdapter`→同步 RAM，
见[TileLink 内存桥](tilelink-memory-bridge.md)。LSU 内部和 MMIO/原子侧不直接暴露 TileLink。
`splitTileLinkMemory` 可选配置再加入[双 RAM 路由](tilelink-router.md)，
按地址分流两个 2 KiB RAM manager，并按 source 校验和仲裁乱序 D。
可选 `tileLinkFetch` 配置将取指作为第二个 TL-UL 主端口，
用[双主双窗口互联](tilelink-fetch.md)分别仲裁 ROM 与 RAM；
CPU/DMA 仍先经过同一个原子共享边界。
OrderedAxi4Bridge 是数据口到外部 AXI4 的独立验证模块；另有复用该模块的
TileLinkAxi4Bridge 作为独立 TL-UL→AXI4 边界。两者均尚未接入生产平台。

产品线选择 TileLink 作为共享内存/设备互联，项目实现的外部总线只考虑 AXI4。
7 系列 MIG 可配置 AXI4 从端口。Zynq-7000 PS HP 原生是 AXI3；若用 PS DDR，
由 Vivado 集成层放置 AXI4→AXI3 协议转换 IP，本项目不实现 AXI3 端口。
本地寄存器 IP 可继续使用 `RegisterPort`，由平台适配；不要求每个 IP 暴露完整 TL-C。
64 字节 burst 与 TL-C 为产品线目标；新平台已实现 burst 安全的双主互联传输、
单 RAM manager 和可选单 CPU 写回缓存。独立 home 已验证两个私有 L1 的独占权限迁移，
但尚未形成双 hart SoC，也没有完整共享权限协议；边界见
[TileLink burst 与一致性推进](tilelink-burst-coherence.md)。
旧 `TLXbar` 的 B/E 通道仍被固定处理，旧无缓存桥只保留一笔事务，
不能不经审计就作为新核多笔访存或一致性互联。新数据口要求全局请求顺序响应，
新桥已用 source ID 匹配并重排独立模型的乱序 D 响应；双窗口路由也有独立模型验证。
默认平台仍没有 TileLink；可选数据路径为单主，取指路径接入后为双主。
双主 RAM、DMA、原子固件已做 GSIM 加独立 C++ 体系结构模型验证，
但取指延迟仍有性能代价；这组同步平台固件未运行 NEMU。
独立 [TileLink→AXI4 边界](tilelink-axi4-bridge.md)已通过 GSIM，
尚未接入整机；MMIO 原生 TL 适配及 FPGA 时序仍待实现或测量。

选择协议本身不构成性能结论。对同一工作负载应比较请求在途数、总线宽度与突发、
仲裁等待、BRAM/LUT 占用及布线后 Fmax；目前没有新核 TileLink 与 AXI 整机的对照数据。
外部接口依据：[Zynq-7000 PS–PL AXI3](https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/PS-PL-AXI-Interfaces)、
[7 系列 MIG AXI4](https://docs.amd.com/r/en-US/ug586_7Series_MIS/AXI4-Slave-Interface-Block)。

## IMSIC 微架构合同

每 hart 一个 IMSIC：一个 M 文件、一个 S 文件及 0..63 个 guest 文件；每文件支持
63..2047 个身份，数量必须为 64 的倍数减一，0 永不有效。默认 127 个身份、0 guest。
M 页和 S/guest 区域以独立参数指定，均 4 KiB 对齐；S/guest 预留区域按页数向上取 2 的幂，
基地址按该区域大小对齐。保留页与保留 word 均读零、写忽略。

每文件 pending/enable 按 64-bit 分组，最低非零 pending & enabled 身份优先；阈值过滤严格小于，
threshold=0 不过滤。delivery 只控制 irq，不影响 topei 的值/claim。复位所有状态为零。
64-bit CSR 访问支持 eidelivery(0x70)、eithreshold(0x72)、偶数 eip/eie selector；
0x71/0x73..0x7f 和有效分组中未实现位 RAZ/WI；奇数 eip/eie selector 报错。
WLRL threshold 合法值 0..最大身份；非法写保留原值。WARL delivery 只保留 bit0，不支持 PLIC bypass。

CSR 端口每拍最多一个事务，operation=0读、1写、2置位、3清位；CPU 负责将 rs1/zimm=0 的
CSRRS/CSRRC 抑制写转换为 operation=0。topei 的任意写都 claim 当前最高优先级身份，忽略写数据，
返回同一事务清除前的值。CSR 副作用在请求握手时发生，响应背压不能重复执行。
MSI 端口每拍最多一个事务，仅自然对齐 32-bit 普通读写；错误大小/对齐/strobe 或地址域外报错且无副作用。
支持 seteipnum_le/be，完整 32-bit 身份检查，不截断高位后误命中低身份。两口可同拍访问同一文件；
定义 CSR 先、MSI 后，同身份 claim/clear 与新 MSI 相遇时保留新 pending。连续相同 MSI 合并为 pending bit，
不是事件计数器。

每口独立两项注册响应 FIFO，空队列请求至响应可见为一拍；下游持续接收时可每拍接一项。
ready 只看本地响应 FIFO 剩余容量，禁止 ready→ready 组合环。满时恢复接收允许一个周期间隔；
队列中响应在背压下保持稳定。两口各最多两项未消费响应，没有内部请求重排。
irq/topei 由已注册状态组合产生，状态更新下一拍可见。分组优先编码与文件复制是可扩展基线；
最大参数面积、路径及目标 XCZU15EG 的可达频率尚待 Vivado 实测。

## 使用与集成

```scala
import soc.ip.interrupt._
val imsic = Module(new Imsic(ImsicParams(
    identities = 127,
    guestFiles = 0,
    machineBase = BigInt("24000000", 16),
    supervisorBase = BigInt("28000000", 16)
)))
```

`io.mmio` 接平台寄存器总线适配器。`csrRequest.file` 为 0=M、1=S、2=guest1，依此类推；
`selector` 是 CPU 保存的 iselect 值，`topei=true` 选择直接 top/claim 操作，此时忽略 selector。
`csrResponse.error` 表示该文件/间接选择器访问不合法，异常类别由 CPU 按当前权限确定。
`interrupts` 的 bit0/bit1 对应 MEIP/SEIP，其余 bit 对应 guest 外部中断线；CPU 不得把这些线直接
当成跳转命令。默认地址仅是可配置 IP 参数，尚未接入现有 FpgaPlatformTop 的地址图。

- `make gsim-imsic-test`：63 身份/1 guest、127 身份/2 guest、2047 身份/0 guest 三组独立验证及负向注入。
- `make imsic-rtl`：默认 127 身份、M/S 两文件，输出 `build/ip/imsic/Imsic.sv` 及依赖 filelist。
- `make test`：活动 Scala 检查与完整 GSIM，包括 IMSIC。环境需按 GSIM README 设置 firtool。

独立 C++ 模型按每个身份逐项记录 pending/enable、线性查找优先级；不读取 DUT 定义或复制硬件分组网络。
检查所有实现身份、大小端、保留地址/selector、非法字段、零身份、高位身份拒绝、文件隔离、原子 claim、
双口并发、响应背压、复位与连续吞吐。IMSIC 此阶段不使用 NEMU 中断差分；原 CPU 的 NEMU 差分独立保留。
最大 63 guest 拓扑有 Scala 展开检查，功能仿真仅覆盖上述三组；没有全参数组合验收声明。

## 独立 IMSIC 初始验收

`make test` 全部通过：Scala 21 项、完整 GSIM、原 CPU 的 NEMU 差分与负向注入。
IMSIC 自身使用独立状态模型，三组结果如下（每组包含 20,000 拍随机双口竞争）：

| 身份数 / 文件数 | CSR 接收 | MMIO 接收 | 同拍双口接收 | 错误响应 |
| --- | ---: | ---: | ---: | ---: |
| 63 / 3 | 10,184 | 9,937 | 1,919 | 6,127 |
| 127 / 4 | 11,320 | 14,831 | 1,913 | 6,536 |
| 2047 / 2 | 9,459 | 15,687 | 1,891 | 5,870 |

三组都通过连续 256 拍双口每拍接单、一拍响应、随机背压、带未消费响应复位、原子 claim/MSI、
pending 写入/清除与 MSI 同拍的检查；故意篡改参考响应由验收拒绝。ASan/UBSan 保持开启。
原 CPU 两组配置各 278 个程序、380,406 条提交，44 条 IPC 记录与此次前完全一致。
日志：`build/gsim/imsic-focused.log`、`build/gsim/imsic-final.log`。

CPU 侧已增加系统/CSR 队首执行授权、有限 M/S CSR、同步陷阱委托和 MRET/SRET，并连接 IMSIC
M/S 文件 CSR 通路，以及提交边界的 M/S 外部中断选择。APLIC M 根域和 S 子域 MSI 网关已实现；
MappedMachineCore 已接 CPU 数据口到两个 APLIC 窗口；后续完善多 hart SoC、VS CSR 与虚拟化。
APLIC 的线中断 gateway/MSI 发送及组合验收见 [APLIC 合同](aplic.md)；PLIC 兼容适配仍待实现。

默认 IMSIC 的 `make imsic-rtl` 已通过，最终导出禁用验证层绑定，顶层及所有实际依赖由
`build/ip/imsic/filelist.f` 列出；日志 `build/gsim/imsic-export-final.log`。
这是独立 SystemVerilog IP 导出，尚未生成 Vivado IP-XACT 包或执行综合/时序分析。

## 机器核接入进展

`MachineCore` 已连接 IMSIC 的 M/S 文件 CSR 通路，支持通过软件读/改/写 mireg/sireg 与原子 mtopei/stopei claim。
队首事务槽保护不可撤销请求直到退休，错误路径不能产生外部 CSR 副作用。同步陷阱和 MRET/SRET 已接通，
M/S 文件电平已接入精确异步陷阱；WiredMachineCore 已增加 APLIC M 域，S 软件/定时与 VS 路径仍待补齐。
具体限制、NEMU 覆盖范围及命令见 [机器核合同](machine-core.md)。原整数基准仍保留异常停止配置。

新增 [MappedMachineCore 数据口映射](core-mmio.md)，程序可直接配置 APLIC；独立控制器接口保持不变。

UART已拆为CPU无关 `soc.ip.uart.UartConsole`，通过RegisterPort接入MachinePlatform，串行中断进入APLIC source3。当前是固定8N1、非FIFO的16550寄存器子集；旧仿真UART保留。见 [UART复用审计与合同](uart.md)。
