# Valence 板级 MMIO 与中断寄存器

2026-10-06 更新：OpenIon Valence VL100 / Orbital-A1，新可选2GiB配置只改变RAM窗口，
现有MMIO/IRQ号不变。新增Linux valence-cmu固定频率CCF、valence-dma通用DMAengine；
GMAC专属DMA仍独立。默认旧512MiB不变，新ROM/DT不能用于旧bit。
最新驱动、启动与容量合同见 [VL100 Debian BSP](vl100-debian-bsp.md)；
下方2026-10-04的板级状态列保留当时阶段，不能替代最新验证记录。

本文是 [SoC datasheet](soc-datasheet.md) 的寄存器附录，以 2026-10-04 工作树中的
`BoardSocTop` / `BoardSocConfig` 为准。地址均为物理字节地址，数据按小端解释。
复位值指硬件复位；ROM monitor 初始化后的值可能不同。通用 `MachinePlatform` 默认参数及
历史 4 KiB GSIM 平台不能代替本页的板级配置。

## 地址译码和访问规则

| 设备 | 地址范围（含首尾） | 窗口大小 | 有效访问 | 板级状态 |
| --- | --- | ---: | --- | --- |
| Machine timer | `0x02000000–0x0200ffff` | 64 KiB | 下表列出的 32/64 位读写 | 可达；每个核心周期加1，timebase跟随40/45/50/100 MHz profile |
| M-APLIC | `0x0c000000–0x0c003fff` | 16 KiB | 自然对齐 32 位 | 可达；31 个源，1 个 S 子域 |
| S-APLIC | `0x0c004000–0x0c007fff` | 16 KiB | 自然对齐 32 位 | 可达；须由 M 域逐源委托 |
| UART | `0x10000000–0x10000007` | 8 B | 8 位读写 | 可达；逐字节寄存器，16字节RX/TX FIFO |
| DMA control | `0x10001000–0x10001027` | 40 B | 自然对齐 64 位 | 新源码窗口随 RAM 配置；旧 bit 仍受勘误限制 |
| Network DMA（可选） | `0x10002000–0x100020ff` | 256 B | 下表列出的自然对齐 64 位 | `ethernetDma` 默认关闭；APLIC 6 |
| Ethernet（可选，互斥后端） | `0x10040000–0x1007ffff` | 256 KiB 路由窗口 | 旧 AXI MAC 32 位；native GMAC 按下表 | `ethernetControl` 默认关闭；native 单口4 KiB；APLIC 5 |
| CMU（可选） | `0x10080000–0x10080fff` | 4 KiB | 自然对齐 8/16/32/64 位 | `clockManagementHz>0`；默认关闭；APLIC 7 |
| M-IMSIC MSI page | `0x24000000–0x24000fff` | 4 KiB | 内部 MSI 端口的 32 位访问 | **未接 CPU load/store 地址路由** |
| S-IMSIC MSI page | `0x28000000–0x28000fff` | 4 KiB | 内部 MSI 端口的 32 位访问 | **未接 CPU load/store 地址路由** |

APLIC 在 `MappedMachineCore` 中，其余外设在 `MachinePlatform` 中；后者按配置使用
串行或并行 MMIO 路由，可选 CMU 在两种路径中均有独立窗口。IMSIC 的页地址仅用于
APLIC 向 IMSIC 的内部消息；不能将这两页当作 OS 可直接写入的软件 MSI doorbell。
IMSIC 状态通过下文的 M/S 间接 CSR 访问。

`CoreRegisterRouter` 将 64 位 beat 内的写数据和字节使能按地址低 3 位右移，交给
`RegisterPort` 时数据均从 bit 0 开始；读响应再移回原 byte lane。因此表中的 mask
是**寄存器端归一化后的掩码**：8/32/64 位分别为 `0x01/0x0f/0xff`。
CPU 使用 `lbu/sb`、`lwu/sw`、`ld/sd` 等对应宽度即可，不能使用 64 位访问代替两个 UART
或 APLIC 寄存器访问。APLIC 仅检查写掩码；UART、DMA、timer 同时检查读写掩码。

非法宽度/地址/掩码按各设备规则返回 `error`，经数据路径成为精确 load/store access fault；
不拆分访问、不自动重试。APLIC 窗口内的保留偏移例外：合法格式访问读零、写忽略。
MMIO 原子请求不送入寄存器端，而是继续下传并由仅允许 RAM 原子操作的边界拒绝。
软件应使用普通 volatile MMIO 及所需 `fence iorw,iorw`，不能把 MMIO 映射为普通可缓存 RAM。
权限仍受 CPU 特权、页表和 PMP 控制，外设译码本身不区分 M/S 身份。

## CMU V1：独立常开时钟管理单元（可选）

代码位于 `src/main/scala/ip/clock/`，固件定义为 `fpga/firmware/valence_cmu.h`。
`ClockManagementUnit` 不依赖 CPU；内部 RegisterPort 和原生 TL-UL 入口二选一。
CMU 本身位于常开域，BoardSocTop 通过完整请求/回复 CDC 访问它，IRQ 持续电平同步到
CPU 的 APLIC source7。构建设置 `clockManagementHz=50000000` 会新增 `alwaysOnClock`
输入；该输入须实际接固定50MHz来源，CMU不能自行生成它。默认0不增加端口或窗口。

板级资源号：0 AON、1 CPU、2 TIME、3 UART、4 DDR_UI、5 GMAC_TX、6 GMAC_RX；
默认/旧后端这些域全部受保护。新增 `managedPeripherals=true` 配置真实 UART/原生 GMAC
接入时，仅3/5/6可停钟，GATEABLE=`0x68`；CPU/TIME/DDR不变。DDR/GMAC是否存在随构建配置变化，TIME父域为CPU。
额外 `managedClockResources` 从7开始；只有真实门控、排空确认、隔离和持久唤醒均已
接入的叶子域才可设置 `canGate=true`。无额外资源且未启用 managedPeripherals 时 GATEABLE=0。
native配置禁止叠加额外资源；MMIO自动唤醒、首输入延迟与 watchdog 合同见
[受管外设接入](managed-peripherals.md)。

| 偏移 | 名称 | 访问 | 字段 / 复位 |
| --- | --- | --- | --- |
| `0x00` | ID_VERSION | RO | `0x56434d5500010001` |
| `0x08` | CAPABILITIES | RO | [63:32] 常开域标称Hz，[31:16] 资源数；bit0门控策略、1唤醒、2故障；无DFS/热复位能力 |
| `0x10` | PRESENT_MASK | RO | 已存在资源的位图 |
| `0x18` | GATEABLE_MASK | RO | 已声明可安全门控资源的位图 |
| `0x20` | STOP_REQUEST | RW | 停钟请求位图，复位0；须串行化软件RMW |
| `0x28` | CLOCK_ENABLE_MASK | RO | 逻辑开钟命令，复位PRESENT；不是物理门控完成或测频结果 |
| `0x30` | STOPPED_MASK | RO | 已完成排空并发出关钟命令，复位0；不含BUFG传播延迟 |
| `0x38` | QUIESCE_MASK | RO | 正在排空或已停止的域，复位0 |
| `0x40` | ISOLATE_MASK | RO | 停止/唤醒过程保持隔离的域，复位0 |
| `0x48` | ADMISSION_MASK | RO | 可接受新工作，复位PRESENT |
| `0x50` | WAKE_PENDING | W1C | 持久唤醒原因，复位0；同拍新事件优先于清除 |
| `0x58` | WAKE_ENABLE | RW | 外部持久唤醒使能，复位GATEABLE |
| `0x60` | WAKE_SET | W1S | 软件唤醒，读0；不受WAKE_ENABLE屏蔽 |
| `0x68` | FAULT_PENDING | W1C | 排空/唤醒超时，复位0；新超时优先于清除 |
| `0x70` | IRQ_ENABLE | RW | 对应域唤醒或故障的IRQ使能，复位0 |
| `0x78` | IRQ_STATUS | RO | WAKE_PENDING OR FAULT_PENDING，与IRQ_ENABLE相与后产生IRQ |

每个资源描述符位于 `0x100 + resource*0x40`：`+0x00`资源号，`+0x08`标称Hz，
`+0x10`flags（bit0存在、bit1可停钟），`+0x18`状态（bit0CE、1STOPPED、2QUIESCE、
3ISOLATE、4ADMISSION、5FAULT、6WAKE_PENDING），`+0x20`父域号（无父为全1），
`+0x28`最多8字节小端ASCII标签。其余偏移保留并返回error；无频率写入/热复位接口。
频率均为生成配置，不是测量，GMAC_RX=125MHz代表千兆标称，不代表协商后PHY实测频率。

自然对齐的1/2/4/8字节操作不拆分；读mask须与宽度一致，写允许合法子集及零mask。
未知偏移、RO写、未对齐或置1到任何非GATEABLE位均原子拒绝，无部分副作用。
例如同时请求受保护CPU与可停外设会整体失败；不能把PRESENT直接写入STOP_REQUEST。
四项有序回复，原生入口每周期最多一项；BoardSoc的完整跨域代理容量为一项。
原生TL只支持Get/PutFull/PutPartial，拒绝原子、burst、TL-C和非法param/corrupt；
所有请求须符合单拍TL-UL advertised size≤8B合同，不能用非法多拍探测设备。

停钟：先关闭新工作准入、等待真实端点的稳定排空ACK，再请求关闭专用时钟缓冲并隔离。
ACK必须覆盖总线、回复、FIFO输出、帧尾、配置和统计等，不可只用DMA active或FIFO空指针。
唤醒清除对应STOP并先开钟，收到目标域ACK返回低才解除隔离；软件需等待ISOLATE清除。
排空超时保持开钟并阻止held STOP立即重试，需先清STOP重新武装；清FAULT不是重新武装。
唤醒超时保持开钟命令和隔离，缺失源时钟不会被伪装为恢复成功。
外部wake须持久或可靠锁存；持续高电平会持续置WAKE_PENDING，先撤销来源再W1C。
共同冷复位清队列和状态；停钟不复位保留寄存器，不是电源管理或动态调频。

凭据与物理后端限制见 [时钟资源规划](../fpga/zu15eg/clock-domain-plan.md)。当前无CMU
Linux clock/reset driver、DT节点、整板门控验收或新bit；旧固件不得盲目探测该可选窗口。

## 自研 GMAC 控制器（独立 IP，未接板级）

2026-10-04 千兆优先的自研后端：`TileLinkGmacControl` 默认一个 `Rgmii1G` 端口，
使用 `0x10040000 + port*0x1000`，独立IP最多四端口。可选生产 `managedPeripherals=true`
已接单口原生 CSR/APLIC5、GMII帧引擎、packet DMA四条流和CMU；默认仍关闭。
尚无 RGMII/PHY 上板、Linux 网络驱动或新bit，详见 [本批接入合同](managed-peripherals.md)。
与旧 AXI Ethernet 的 256 KiB 窗口重叠，后续配置必须二选一；不是同一寄存器 ABI。
软件定义：`fpga/firmware/valence_gmac.h`。未上板，不能仅改 DT 就启用。

TL-UL 64-bit beat：Get/PutFull/PutPartial，size=0..3，自然对齐；Get/Full mask
须与宽度和地址 lane 完全匹配，Partial 为其子集（允许零 mask）。数据保持原生 TL lane，
**不是 RegisterPort 右对齐数据**。Get 回整个对齐的 64-bit 寄存器快照；所请求 lane 有效。
四项有序非 flow 回复，下一拍可见、背压保持。不支持 burst、原子或 TL-C；
超出 advertised 8-byte 的非法多拍请求不属于本 manager 合同。
未知地址、RO 写、保留字段置 1、param!=0、corrupt 等返回 denied，原子拒绝且无副作用；
带数据回复同时 corrupt=1。TX/RX busy 时非零 mask 的 CONTROL/MAC_ADDR 写亦拒绝。

下列偏移以各端口 4 KiB 基址为起点；未列偏移保留。计数为 64-bit 自然回绕。

| 偏移 | 名称 | 访问 | 字段 / 复位 |
| --- | --- | --- | --- |
| `0x00` | ID_VERSION | RO | `0x56474d4100010001` |
| `0x08` | CAPABILITY | RO | [63:32] maxFrameBytes，[23:16] mediaBits，bit0 RGMII/bit1 XGMII 设计合同；bit8 表示可选 RX_STOP 屏障 |
| `0x10` | CONTROL | RW | bit0 TX enable、1 RX enable、2 promiscuous、3 broadcast；复位8 |
| `0x18` | MAC_ADDRESS | RW | 低48位；线上第一 octet 为[47:40]，复位0 |
| `0x20` | MAX_FRAME_BYTES | RO | 默认2048，不计 preamble/SFD/FCS |
| `0x28` | STATUS | RO | bit0 linkUp、1 txBusy、2 rxBusy；来自控制域输入 |
| `0x30` | IRQ_PENDING | W1C | bit0 TX done、1 RX done、2 drop、3 bad FCS、4 underflow、5 link change、6 MDIO done；复位0 |
| `0x38` | IRQ_ENABLE | RW | bit[6:0]；复位0，IRQ 为 enabled pending 的 OR |
| `0x40` | TX_FRAMES | RO | TX done 次数；复位0 |
| `0x48` | RX_FRAMES | RO | RX done 次数；复位0 |
| `0x50` | RX_DROPS | RO | RX drop 次数；复位0 |
| `0x58` | RX_BAD_FCS | RO | RX bad FCS 次数；复位0 |
| `0x60` | TX_BYTES | RO | TX done 同拍的 txBytes 增量总和；复位0 |
| `0x68` | RX_BYTES | RO | RX done 同拍的 rxBytes 增量总和；复位0 |
| `0x70` | CLEAR_STATS | WO/read0 | 写 bit0 清六项计数；同拍事件先清后加，不丢该次事件 |
| `0x78` | MDIO_COMMAND | WO/read0 | [15:0] data、16 write、17 START、[22:18] PHY、[27:23] register |
| `0x80` | MDIO_STATUS | RO | bit0 busy、1 done；复位0，START 清 done，完成置 done |
| `0x88` | MDIO_RESULT | RO | [15:0] data、16 noAck；复位0，保留最近一次完成结果 |
| `0x90` | RX_STOP（仅 CAP bit8=1） | RW | 仅完整64位写0/1，忙时可写；读bit0 requested、bit1 drained；复位0 |

2026-10-07 RX_STOP 扩展默认只在 `ManagedGmac` 开启；没有 CAP bit8 时该地址仍为
未知地址并拒绝访问。写1先关闭新帧准入，已接受的完整帧、CDC FIFO／预取／输出以及
适配器 data/status 尾部必须经实际握手排空后才读到drained=1。保持 DMA scratch RX 消费者
运行直到此屏障，再用 DMA RX_STOP／BUSY 检查排空 DDR。写0解除准入限制；STATUS busy
包含尚未完成的命令跨域，初始化须等其清零。停收后丢弃的新物理流量不阻塞安全 CONTROL=0；
旧 CONTROL 忙时拒绝语义不变。此扩展不取消事务、不清FIFO、不强制复位或停钟。

CAPABILITY 表示端口目标接口，**不是 MAC/PCS 已完成或链路可用的声明**；`Xgmii10G`
目前仅可配置接口宽度，用户指定未来 SFP1，实际 10G RTL 不在本批。
TX/RX 字节增量不含 preamble/SFD/FCS；这些事件当前由测试输入，尚无真实帧生产者。
W1C 同拍事件优先，清 pending 不清 MDIO done/result；新 START 不清 IRQ_PENDING。

MDIO START 须完整 64-bit、mask=0xff；部分 START 拒绝，START=0 无动作。
合法 START 在 MDIO busy 时 A 背压，但非法格式仍可接受并 denied。已接受命令的 TL
AccessAck 是启动回复，不等于串行完成；轮询 done/IRQ 后读 RESULT。
MDIO Clause22 带 32 个 preamble 1；读 TA0 非零置 noAck，不自动超时重试或扫描 PHY。
IOBUF 与 PHY reset/strap/页寄存器/链路查询由未来板级与驱动适配负责。
最终验收 `build/gsim/self-gmac-20261004-r3/receipt.json` 为 `passed_foundation_only`：
TL 3045 请求、4 次完整 CSR→MDIO 帧/23 请求/462 拍 busy 背压及独立负例通过。
详情见 [自研 GMAC/DMA 合同](dma.md)。

## UART：`0x10000000`

寄存器按字节偏移，size=0、mask=0x01、reg-shift=0。升级版有 16 字节 RX/TX FIFO，
16x 多数接收采样与可编程格式；硬件复位 FIFO 禁用，BootROM 写 FCR=0x07 使能并清空。
只暴露 RX/TX，没有板外 modem 引脚或自动流控。

| 偏移 | 条件 / 名称 | 读 | 写 | 复位 / 副作用 |
| --- | --- | --- | --- | --- |
| 0x0 | DLAB=0：RBR / THR | 队头字节，空时0 | 发送字节，FIFO满时背压 | 空；RBR消耗字节，THR写清THRE pending |
| 0x0 | DLAB=1：DLL | divisor低8位 | 修改低8位 | 1；TX非空或RX接收中时背压 |
| 0x1 | DLAB=0：IER | bit0 RX/timeout，bit1 THRE，bit2线路错误，bit3 modem | 保存低4位 | 0；打开THRE且TX FIFO空时置pending |
| 0x1 | DLAB=1：DLM | divisor高8位 | 修改高8位 | 0；忙时与DLL相同 |
| 0x2 | IIR / FCR | 原因低4位；FIFO启用时高2位11 | bit0 FIFO enable，bit1/2清RX/TX，bit7:6触发1/4/8/14 | IIR=1；模式改变清两个FIFO；清TX不截断移位器 |
| 0x3 | LCR | 全8位 | 字长[1:0]，stop[2]，parity[5:3]，break[6]，DLAB[7] | 3，即8N1 |
| 0x4 | MCR | 低5位 | DTR/RTS/OUT1/OUT2/loopback | 0；只有loopback有内部接线；OUT2不门控IRQ |
| 0x5 | LSR | 下表 | 忽略 | 0x60；读清OE和当前队头PE/FE/BI |
| 0x6 | MSR | modem高4位与delta低4位 | 忽略 | 外部恒0；内部loopback有效，读清delta |
| 0x7 | SCR | scratch | 保存低8位 | 0 |

| LSR bit | 名称 | 含义 |
| ---: | --- | --- |
| 0 | DR | RX队列非空 |
| 1 | OE | RX满时丢弃新字节，保留已排队字节 |
| 2 | PE | 队头字节校验错误 |
| 3 | FE | 队头停止位多数采样为低 |
| 4 | BI | 队头为break字符；持续低只发布一次，等回高重启 |
| 5 | THRE | TX FIFO空，不等同于FIFO尚有容量 |
| 6 | TEMT | TX FIFO和移位器均空 |
| 7 | FIFO error | FIFO内存在尚未确认的PE/FE/BI字节 |

IIR优先级：线路错误6 > RX阈值4 > RX超时12 > THRE2 > modem0；无中断1。
FIFO启用时实际为0xc6/0xc4/0xcc/0xc2/0xc0/0xc1。
读IIR只确认当前THRE；RX由RBR/FCR，线路错误由LSR/FCR，modem由MSR读确认。
RX FIFO未空且四字符时间无新接收/RBR读取产生超时。IER bit0同时控制阈值和超时中断。

LCR支持5/6/7/8位，无/奇/偶/mark/space parity，1/2 stop（5位时1.5 stop）。
RX检查第一stop，配置修改前软件应等待TEMT并确保RX空闲。
内部loopback把TX接RX、外部TX保持高；modem映射 CTS←RTS、DSR←DTR、RI←OUT1、DCD←OUT2，
MSR delta包括CTS/DSR/DCD变化与RI下降沿；板外无这些引脚。

波特率统一为 referenceClockHz/(16*max(divisor,1))，参考频率通过核心时钟内的
相位累加时钟使能实现，不是另一个时钟域：

| 候选 | CPU/timebase Hz | UART参考 Hz | divisor | 主机baud |
| --- | ---: | ---: | ---: | ---: |
| DDR45 FIFO | 45000000 | 24000000 | 1 | 1500000 |
| DDR50 FIFO | 50000000 | 1843200 | 1 | 115200 |

设备树/8250驱动的 clock-frequency 用UART参考频率，timebase-frequency 用CPU频率。
旧bit仍按其旧配置，不能靠GUI改时钟或只改波特率混用。IRQ仍为APLIC source3、高电平模式6。
未提供完整ns16550a合规认证，驱动探测/MMIO访问宽度和无硬件流控需另行验收。
详情见 [UART合同](uart.md)。

## Machine timer：`0x02000000` 窗口

| 绝对地址 | 寄存器 / 别名 | 宽度 | 权限 | 硬件复位 |
| --- | --- | --- | --- | --- |
| `0x02004000` | mtimecmp；32 位访问时为低半 | 64 或 32 位 | RW | `0xffffffffffffffff` |
| `0x02004004` | mtimecmp 高半 | 32 位 | RW | `0xffffffff` |
| `0x0200bff8` | mtime；32 位访问时为低半 | 64 或 32 位 | RW | `0x0000000000000000` |
| `0x0200bffc` | mtime 高半 | 32 位 | RW | `0x00000000` |

64 位访问要求 size=3、mask=`0xff` 且访问低地址；32 位访问要求 size=2、mask=`0x0f`。
这是同一对 64 位寄存器的半字别名，窗口中其他地址（包括 `0x02000000`）均返回 error；
没有 CLINT/ACLINT MSIP 阵列、多个 hart 的 compare，也没有 MMIO stimecmp。
修改其中一半保留另一半。读在请求握手时采样；写在握手时生效，mtime 写优先于同拍 tick。

`BoardSocTop` 将 timerTick 固定为 1，所以 Board40 的 timebase 为 **40,000,000 Hz**（DDR45/DDR50 分别为45000000/50000000 Hz），与退休、WFI 或
访存等待无关；64 位加法自然回绕。`mtime>=mtimecmp` 为无符号比较，比较结果先寄存一拍再产生
MTIP（`mip[7]`），不经过 APLIC。使能为 `mie.MTIE[7]` 和适用的全局中断使能。
RV64 软件可用一次 `sd` 更新比较值；采用分半更新时需自行避免中间值触发不期望的中断。

| CSR | 地址 | 当前实现 |
| --- | --- | --- |
| time | `0xc01` | RO，读取同一 mtime；M 总可读，S 需 mcounteren.TM，U 还需 scounteren.TM |
| stimecmp | `0x14d` | 64 位 RW，复位全 1；M 可访问，S 需 menvcfg.STCE 与 mcounteren.TM，U 不可访问 |
| menvcfg.STCE | `0x30a[63]` | 复位 0；为 1 时 STIP 由 time>=stimecmp 比较后寄存产生 |
| mcounteren.TM / scounteren.TM | `0x306[1]` / `0x106[1]` | 均复位 0 |

STCE=0 时 M 软件可写 `mip.STIP[5]`；STCE=1 时它来自硬件比较、软件写无效。
STI 的目标/使能另受 `mideleg[5]`、`mie/sie[5]` 控制。参见 [机器定时器](machine-timer.md)
和 [Sstc](sstc.md)；不要把 time CSR 的存在扩展为完整性能计数器支持声明。

## DMA：`0x10001000`

**2026-10-04 新源码：** `MachinePlatform` 显式传递 RAM 基址/容量；Board40 为
`0x80200000–0x802fffff`，DDR 为 `0x80200000–0xa01fffff`。旧 bit 仍是
`0x80010000–0x80010fff`，不能用于板级成功复制；新 bit 上板验收前不默认启用 OS DMA 驱动。
历史 4 KiB 测试记录不能替代板级验收，见 [DMA 合同](dma.md)。

全部寄存器只接受自然对齐 64 位访问（size=3，mask=`0xff`）；所有状态复位 0。

| 偏移 | 名称 | 访问 | 字段 / 副作用 |
| --- | --- | --- | --- |
| `0x00` | SOURCE | RW，busy 时拒绝写 | 64 位源物理地址 |
| `0x08` | DESTINATION | RW，busy 时拒绝写 | 64 位目标物理地址 |
| `0x10` | LENGTH | RW，busy 时拒绝写 | 64 位字节数 |
| `0x18` | CONTROL | RW，busy 时拒绝写 | 写 bit0 START、bit1 CLEAR、bit2 IRQ_ENABLE；读仅返回 bit2 |
| `0x20` | STATUS | RO | bit0 BUSY、bit1 DONE、bit2 ERROR；其他位为 0，写返回 error |

每次合法 CONTROL 写都会用 bit2 更新中断使能；bit1 清 DONE/ERROR，bit0 启动。
两位同置时 START 的结果优先于 CLEAR。合法描述符要求非零长度、源/目标/长度均 8 字节对齐，
两个完整区间落入 DMA 参数定义的 RAM，无 64 位溢出，且源目标不重叠；源=目标同样非法。
非法描述符使 BUSY=0、DONE=1、ERROR=1，没有内存请求。写 SOURCE/DESTINATION/LENGTH 本身
不清上次完成状态；再次 START 会重置状态和计数。busy 时包括 CLEAR 在内的所有配置写均返回 error。

传输以 64 位读写进行，4 项数据缓冲、4 项有序请求归属；成功完成须等到最后一笔写响应。
总线错误置 ERROR，停止新增工作并排空已经接受/锁定的事务后置 DONE，已经完成的写不回滚。
没有进度寄存器、取消操作、scatter/gather、字节尾部、重叠 memmove、外设握手或 IOMMU。
IRQ=`IRQ_ENABLE && DONE`，成功和错误完成都可触发，接 APLIC source 4；用 CONTROL.CLEAR 清除。
集成和历史测试见 [DMA 合同](dma.md)。

## 网络 DMA（可选）：`0x10002000`

所有寄存器要求 size=3、mask=0xff。未列出的保留地址、错误宽度、RO 写返回 error。
TX/RX 分别一个简单描述符，活跃时禁止修改对应地址/长度/CMD；可修改 IRQ_ENABLE、读状态。
状态未确认时禁止只 START 覆盖，CMD=3 可先确认再启动。无 SG 或 AXI DMA ABI 兼容。

| 偏移 | 名称 | 访问 | 语义 / 复位值 |
| --- | --- | --- | --- |
| `0x00` | ID_VERSION | RO | `0x56444d4100010001` |
| `0x08` | IRQ_ENABLE | RW | bit0 TX、bit1 RX；复位0 |
| `0x10` | TX_ADDRESS | RW | 64-bit 物理地址，须8字节对齐；0 |
| `0x18` | TX_LENGTH | RW | 字节数1..2048；0 |
| `0x20` | TX_CMD | WO / 读0 | bit0 START，bit1 ACK（清完成/错误） |
| `0x28` | TX_STATUS | RO | bit0 BUSY、bit1 DONE、bit2 ERROR；0 |
| `0x30` | RX_ADDRESS | RW | 64-bit 物理地址，须8字节对齐；0 |
| `0x38` | RX_CAPACITY | RW | 缓冲区字节容量1..2048；0 |
| `0x40` | RX_CMD | WO / 读0 | bit0 ARM，bit1 ACK |
| `0x48` | RX_STATUS | RO | bit0 BUSY、bit1 DONE、bit2 ERROR；0 |
| `0x50` | RX_LENGTH | RO | 本次实际接收字节数，启动清零 |
| `0x58..0x80`，步长8 | RX_STATUS_WORD0..5 | RO | 原始 PG138 六字状态放低32位；启动清零 |
| `0x88` | MAX_FRAME_BYTES | RO | 默认2048 |

IRQ 为 `(TX_DONE && IRQ_ENABLE[0]) || (RX_DONE && IRQ_ENABLE[1])`，接 APLIC source 6；
应先 ACK 对应 DMA 完成再确认 IMSIC/APLIC。未 ARM 时背压收包，不能假设 MAC 无限缓存。
缓冲区所有权、错误/尾字节、CDC 和软件 helper 见 [网络 DMA 合同](dma.md)。

## APLIC：M `0x0c000000`，S `0x0c004000`

两域各 16 KiB，均为 MSI-only、小端、单 hart，31 个源。下表偏移相对各自 base；
除固定字段外所有状态复位 0。要求 size=2、地址低两位=0；写 mask=`0x0f`。
合法格式的保留寄存器读零、写忽略；下表中只写接口读零。

| 偏移 | 名称 | 访问 | 实现字段与语义 |
| --- | --- | --- | --- |
| `0x0000` | domaincfg | RW | 固定读值 `0x80000004` 加 IE[8]；仅 IE[8] 可写，DM=1、BE=0 |
| `4×s`，s=1..31（`0x004–0x07c`） | sourcecfg[s] | RW | M 域支持 D[10] 委托到 child 0；否则低 3 位 source mode，见下文 |
| `0x1bc0` | mmsiaddrcfg | RO / 写忽略 | M 域读 `0x00024000`；S 域实际读 `0x00028000`（本域 MSI 目的页的 PPN） |
| `0x1bc4` | mmsiaddrcfgh | RO / 写忽略 | 两域均读 `0x80000000`：L=1，无可配置 hart 索引 |
| `0x1bc8` | smsiaddrcfg | RO / 写忽略 | M 域 `0x00028000`；S 叶域读 0 |
| `0x1bcc` | smsiaddrcfgh | RO / 写忽略 | M 域 `0x80000000`；S 叶域读 0 |
| `0x1c00` | setip[0] | RW1S | 读 pending；写 1 置对应源 pending，受源模式约束 |
| `0x1cdc` | setipnum | WO | 按完整 32 位值指定源号置 pending |
| `0x1d00` | in_clrip[0] | R / W1C | **读校正后的输入电平，写 1 清 pending** |
| `0x1ddc` | clripnum | WO | 按源号清 pending |
| `0x1e00` | setie[0] | RW1S | 读 enable；写 1 置对应源 enable |
| `0x1edc` | setienum | WO | 按源号置 enable |
| `0x1f00` | clrie[0] | WO/W1C | 写 1 清 enable；读 0 |
| `0x1fdc` | clrienum | WO | 按源号清 enable |
| `0x2000` | setipnum_le | WO | 按小端源号置 pending |
| `0x2004` | setipnum_be | WO | 先字节交换 32 位写数据，再按源号置 pending |
| `0x3000` | genmsi | RW | EIID[6:0]，只读 Busy[12]；空闲写发起一条 MSI，不受 domaincfg.IE 约束；忙时写忽略 |
| `0x3000+4×s`，s=1..31（`0x3004–0x307c`） | target[s] | RW | 仅保存 EIID[6:0]；Hart/Guest 索引写入被忽略，固定为 0 |

位图中 bit s 对应 source s，bit0 恒 0，只有一个 32 位组；超出 1..31 的 num 操作无效果。
例如 UART 的 source3 对应 sourcecfg 偏移 `0x00c`、target 偏移 `0x300c`、位图 bit3；
输入线则是 sources bit2。DMA source4 对应偏移 `0x010` / `0x3010`、位图 bit4、输入 bit3。
sourcecfg 模式：0 Inactive、1 Detached、4 上升沿、5 下降沿、6 高电平、7 低电平；
2/3 写为 Inactive。M 域 `D=1 && child[9:0]=0` 才委托；其他 D=1 写为 Inactive，
S 叶域 D=1 也写为 Inactive。Inactive 清本域 pending/enable/target。
已委托源在 M 域不投递，S 域仅对 M 域已委托的源有效；M 域 IE 不充当 S 域的全局使能。

最低源号先发送；genmsi 优先。EIID=0 可以写入 target/genmsi，但 IMSIC 不置 pending。
MSI 进入发送 FIFO 时清 APLIC pending 并固定目标，之后屏蔽/修改 target/撤销输入不能撤回消息。
高/低电平模式在无效电平清 pending，软件只可在有效电平置位；**持续有效电平在一次投递后不会
自动重发**，需服务外设使电平撤销，或在仍有效时通过 setipnum 重触发。
同拍新边沿可保留，配置模式时若新校正输入有效也会置 pending。没有逐事件计数队列。

发送端最多 4 项未响应 MSI；genmsi.Busy 在请求发送握手后清除，不能据此断言 CPU 已处理中断。
MSI 总线错误置 sticky `msiError` 输出、无自动重试；没有软件可读/清的错误状态寄存器，
`BoardSocTop` 也未导出此调试输出。见 [APLIC 合同](aplic.md)。

## IMSIC：内部 MSI 页与软件 CSR

板级实例包含 M file 0、S file 1，各支持 EIID 1..127，EIID 0 保留；guestFiles=0。
下表为 IP 的内部 MSI 端口，**不是当前板级 CPU 可写 MMIO**。

| 内部页内偏移 | 名称 | 行为 |
| --- | --- | --- |
| `0x000` | seteipnum_le | 合法 32 位写的 EIID 1..127 置对应 file pending；其他身份忽略 |
| `0x004` | seteipnum_be | 先字节交换 32 位值，再按同样规则置 pending |
| 其余对齐偏移 | 保留 | 读 0、写忽略 |

页内所有读返回 0；size=2、自然对齐，写 mask=`0x0f`，否则 error。M/S APLIC 分别发送到
`0x24000000` / `0x28000000` 的 LE 偏移。没有从 CPU 普通数据总线到这些页的连接；
CPU 软件若需要测试 pending，可使用间接 CSR 或 APLIC.genmsi。

| 软件 CSR | M 地址 | S 地址 | 行为 / 复位 |
| --- | --- | --- | --- |
| xiselect | `miselect=0x350` | `siselect=0x150` | 12 位 selector，复位 0；仅保存低 12 位 |
| xireg | `mireg=0x351` | `sireg=0x151` | RV64 间接读/写/置位/清位；目标见下表 |
| xtopei | `mtopei=0x35c` | `stopei=0x15c` | 读值在 [26:16] 与 [10:0] 均为 topEIID；无候选时 0 |

M 软件可访问 M/S CSR；S 软件仅可访问 S CSR；U 不可访问。读取 TOPEI 本身不 claim；
有写效应的 CSR 操作清除当前最高优先级身份 pending，写入的数值不决定清除哪个身份。
例如 `csrrw rd, stopei, x0` 会返回并领取当前身份，`csrrs rd, stopei, x0` 为只读。
无候选时写无效果；同拍新 MSI 在 claim 之后合入，不会被 claim 丢弃。

| selector | 寄存器 | 位定义 | 复位 / 写行为 |
| --- | --- | --- | --- |
| `0x70` | eidelivery | bit0 投递使能 | 0；只保存 bit0 |
| `0x72` | eithreshold | 11 位门限 | 0；仅接受 0..127 的更新值，超范围保持原值 |
| `0x80` | eip0 | EIID 0..63 pending | 0；bit0 恒 0 |
| `0x82` | eip1 | EIID 64..127 pending | 0 |
| `0xc0` | eie0 | EIID 0..63 enable | 0；bit0 恒 0 |
| `0xc2` | eie1 | EIID 64..127 enable | 0 |

其余 `0x70..0xff` 范围内 selector 读零/写忽略，但 `0x80..0xff` 中的奇数 selector 返回错误；
范围外 selector 也返回错误，CPU 对失败的间接 CSR 操作产生非法指令异常。
top 是 pending & enable 中最小的非零 EIID；threshold=0 不限，非零时只允许 EIID<threshold。
`eidelivery` 仅门控中断线，不屏蔽 TOPEI 的候选计算。M/S pending 输出分别连 MEIP[11] 与 SEIP[9]。

## 板级中断连接与软件初始化

| 信号 | 路径 | 软件控制 / 限制 |
| --- | --- | --- |
| UART IRQ | APLIC source 3 → 选定域 IMSIC → MEIP 或 SEIP | IER、sourcecfg/target/enable、domaincfg.IE、IMSIC eie/eidelivery、CPU 中断使能 |
| DMA IRQ | APLIC source 4 → 同上 | DONE && IRQ_ENABLE；旧 bit 地址限制如上 |
| MAC IRQ（可选） | APLIC source 5 → 同上 | MAC 持续电平经过同步器 |
| Network DMA IRQ（可选） | APLIC source 6 → 同上 | TX/RX DONE 与各自 IRQ_ENABLE 的 OR |
| CMU IRQ（可选） | APLIC source 7 → 同上 | 各可停钟域的WAKE/FAULT持续电平，经CPU域同步 |
| Machine timer | 直接 MTIP，cause 7 | mtimecmp、mie.MTIE；不经 APLIC/IMSIC |
| Supervisor timer | time/stimecmp → STIP，cause 5 | STCE、mideleg[5]、mie/sie.STIE |
| Supervisor software IRQ | CSR 中的 SSIP，cause 1 | mip/sip 对应位及委托；没有 MSIP MMIO |
| 其他外部有线输入 | BoardSocTop 未分配源绑0 | 无 GPIO/通用外部 IRQ 引脚；APLIC 仍允许软件置 pending/genmsi |

`MachinePlatform` 将外部 sources bit2/bit3 分别与 UART/DMA IRQ 做 OR；在 `BoardSocTop`
默认可选功能关闭时固定源仅有 UART=3、DMA=4；启用时另有MAC=5、packet DMA=6、CMU=7。
APLIC source 号和 IMSIC EIID
是两个不同编号空间：EIID 由 target 配置，不必等于源号。

驱动初始化顺序可为：先屏蔽设备 IRQ；配置目标域 sourcecfg、target、enable 与 domaincfg.IE；
配置该 IMSIC file 的 eie/eidelivery（需要时 threshold）；设置 CPU 中断委托、mie/sie 和全局使能；
最后打开设备 IRQ。S 域使用还须由 M 固件将对应 sourcecfg 写为 `0x400` 并配置 S 域源。
中断处理程序服务外设并领取 TOPEI；电平模式的重触发限制见 APLIC 小节。
当前支持的中断优先级依次为 MEI、MTI、SEI、SSI、STI；PLIC claim/complete 接口、APLIC IDC、
多 hart 目标、guest interrupt files 和直接 CPU MSI 页写入均不能假定存在。

## 实现依据与验证边界

地址、连线、寄存器副作用以以下源文件为依据；本页是静态实现审计，不增加硬件验证声明。

- [BoardSocTop.scala](../src/main/scala/core/ooo/BoardSocTop.scala)：40 MHz、板级 RAM、tick 和外部源绑值。
- [MachinePlatform.scala](../src/main/scala/core/ooo/MachinePlatform.scala)：timer/UART/DMA 窗口与 IRQ 合并，DMA 默认参数实例化。
- [MappedMachineCore.scala](../src/main/scala/core/ooo/MappedMachineCore.scala)、[MachineCore.scala](../src/main/scala/core/ooo/MachineCore.scala)：M/S APLIC、内部 MSI 与 CSR 连接。
- [CoreRegisterRouter.scala](../src/main/scala/core/ooo/CoreRegisterRouter.scala)、[RegisterPort.scala](../src/main/scala/ip/bus/RegisterPort.scala)：宽度、数据 lane 与错误传递。
- [UartConsole.scala](../src/main/scala/ip/uart/UartConsole.scala)、[MachineTimer.scala](../src/main/scala/ip/timer/MachineTimer.scala)、[MemoryCopyDma.scala](../src/main/scala/ip/dma/MemoryCopyDma.scala)：外设寄存器定义。
- [Aplic.scala](../src/main/scala/ip/interrupt/Aplic.scala)、[Imsic.scala](../src/main/scala/ip/interrupt/Imsic.scala)、[MachineSystemUnit.scala](../src/main/scala/core/ooo/MachineSystemUnit.scala)：AIA 与 CSR 状态。

各模块文档保留原 GSIM 验收记录；这些记录不等于 Linux/OpenSBI 驱动兼容、物理板启动或
40 MHz 布线后时序签核。当前板级流程见 [ZU15EG 入口](../fpga/zu15eg/README.md)。
