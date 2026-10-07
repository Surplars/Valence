# OpenIon Valence VL100 SoC Datasheet

## 2026-10-06 当前候选补充（优先于下方历史口径）

厂商 OpenIon，CPU Orbital-A1。r4 RV64GC/双发射/100MHz/UART460800 bit为512MiB，
TFTP/Linux/小包ping已上板，长帧仍卡死。本轮Home读保持修复已短验证，未出新bit。
新增显式可选完整2GiB，地址0x80200000–0x1001fffff，TL先完整物理地址翻译再给MIG偏移；
容量改为BigInt，旧默认512MiB不变。监控区0xffff8000–0xffffbfff，DT no-map。
新配置未签核100MHz；不能只改DT或把新ROM装到旧bit。

Debian13 LP64D minbase及 valence-soc/aia/cmu/dma/gmac五驱动已构建并配置自动初始化。
通用DMA/APLIC4与packet DMA/APLIC6分开；CCF CMU固定频率，UART critical，无DFS。
驱动运行与带宽待新bit板测，完整接口与命令见 [VL100 BSP](vl100-debian-bsp.md)。
以下Board40/2026-10-05“无网口驱动/bit”等文字保留历史状态，不代表当前候选。

版本：0.7 / 2026-10-05。对象：`BoardSocTop`，XCZU15EG PL 中的单 hart RISC-V SoC。
本文是当前源码的软件接口说明，不是 FPGA 速度等级保证或 RISC-V 完整一致性认证。
地址均为 **CPU 物理字节地址**，范围两端包含在内；KiB/MiB 按 1024 进制。

软件移植先读本文，再查 [MMIO 寄存器手册](soc-registers.md) 和
[OS/裸机适配指南](os-software-porting.md)。板级操作见 [FPGA 启动](fpga-bringup.md)。

## 最新 ISA 配置边界（2026-10-05）

网口状态补充：已按用户选择开始原生 TileLink 自研 GMAC，**千兆 RTL8211F 优先**，
10G 只记录未来 SFP1。公共 CSR/CRC/MDIO 及后续 GMII 帧/真实 DMA 联合短验证已通过，
但后者只用一个测试时钟；独立模块布线的 TX/RX 125 MHz、适配器100 MHz
内部 setup/hold 通过，不等于板级资格。最新可选生产 SoC 已接 native CSR/帧CDC/packet DMA，
并由CMU管理UART/TX/RX真实引擎；RGMII/PHY/driver仍未上板验收。
不是旧 AXI Ethernet ABI，也没有新网络驱动、DT 节点或 bit。
默认整数/FP/网络配置不变。新 CSR 拟用 `0x10040000`，每口 4 KiB，必须与旧 AXI
Ethernet 后端互斥；见 [受管外设接入](managed-peripherals.md)、[寄存器候选](soc-registers.md#自研-gmac-控制器独立-ip未接板级)、
[DMA 合同](dma.md) 和 [接线台账](../fpga/zu15eg/ethernet-integration.md)。

时钟管理补充：新增独立可配置CMU V1及同步BUFGCE后端。可选板级窗口
`0x10080000–0x10080fff`、APLIC7、固定常开时钟输入；默认关闭，既有bit不变。
支持资源/标称频率描述、保护掩码、排空/停钟/隔离/唤醒/超时和IRQ；只有明确接好真实
排空/隔离/持久唤醒/门控的资源可以宣称可停钟。默认现有域仍受保护；新增受管native配置
仅UART/GMAC TX/RX三叶子域可停钟，GATEABLE=0x68。CPU/TIME/DDR不关；无动态调频、独立热复位、掉电或测频。
四种局部GSIM与实际BUFGCE模型的CDC短验证通过，不是整板门控或Fmax签核。
见 [CMU寄存器](soc-registers.md#cmu-v1独立常开时钟管理单元可选) 与
[完整时钟边界](../fpga/zu15eg/clock-domain-plan.md)。

原整数版 100 MHz / UART 460800 bit 已由用户启动 Linux 并运行 CoreMark CRC；
本轮没有替换它。原 WSL 主工程已增加完整基础 F/D 功能候选，默认仍纯整数。
显式构建选择如下，不能仅修改设备树而不修改 RTL：

| BoardSoc ISA 参数 | 软件 ISA 字符串 | misa | 浮点能力 |
| --- | --- | --- | --- |
| `rv64imac`（默认） | `rv64imac_zicsr_zifencei` | `0x8000000000141105` | 无 F/D 模块 |
| `rv64imafc` | `rv64imafc_zicsr_zifencei` | `0x8000000000141125` | 完整 F，无 D 运算模块 |
| `rv64gc` | `rv64imafdc_zicsr_zifencei` | `0x800000000014112d` | 完整基础 F+D |

`OooParams.floatingPoint` 可进一步裁剪运算组；这种实验子集不得设置
`advertiseFloatingPoint=true`。D 要求 F，整数双发射与浮点配置独立。
完整 FP 端口仍是 ROB-head 串行、FLEN64/32 FPR，不声称 FP 双发射或并行重命名。
数值使用固定 Berkeley HardFloat，独立参考使用固定 SoftFloat。

当前完整功能与三类 NaN 输出适配优化的短验收为
`build/gsim/floating-point-full-20261004-nan-cut-r1/receipt.json`；真实 CPU
1,212 个用例、61,865 次提交、77,748 周期，实际读取 misa；实验裁剪/FS/FCSR/
精确异常与整数开关回归通过。13 个优化后 FP 模块的 10 ns 内部 setup/hold
均通过，完整 FP 系统 WNS +1.603 ns，23,114 LUT/6,127 FF/22 DSP；优化前为
+1.454 ns、23,272 LUT，相同 FF/DSP，没有增加浮点数值级或 II。
这是独立模块统计，不是整板新增资源或 F/D bit 签核。
新板级短固件已通过 31,960 模型周期，覆盖缓存/AXI/原子操作及 S-mode 全 FPR/
FCSR 保存恢复、真实 Sv39 非同址上下文 VA 0x40220000→PA 0x80220000，并有严格负例。
凭据 `build/gsim/rv64gc-board-20261004-sv39-context-r1/receipt.json`。模块对照已完成，
真实 RV64GC CPU 内部 10 ns route 已通过：WNS +0.090 ns、TNS 0、hold +0.023 ns，
含 FPU 共 138743 LUT/38532 FF/41 DSP，不含外围 cache/fabric/MIG/Clock Wizard。
最终审计 `build/fpga/fpu-rv64gc-20261004/audit-final.json` 锁定全部功能/RTL/报告。
所有零预算 FPU 模块边界 hold 仍 -0.080 ns，Core 边界 hold -0.046 ns；Linux FP
上下文、时钟/复位/接口边界和 F/D 上板没有据此自动通过。V 未实现。

以上为2026-10-04对应输入的历史模块/功能凭据。后续整数与总线优化改变了其部分输入，
不能将旧凭据原样称为当前源码的整体验收。2026-10-05补跑两个受影响短模型，凭据为
`build/gsim/rv64gc-native-20261005-r1/receipt.json`：当前真实CPU浮点参考比较与当前
`staged-fetch-feedback`板级配置的FPR/FCSR、Sv39上下文均通过。后者不模拟受管外设多时钟域，
Linux浮点调度仍未验证。第一次完整RV64GC整板route已完成，CPU100 WNS -0.685 ns，
RX setup -0.090 ns、TX setup/hold -0.037/-0.003 ns，不能宣称F/D整板满足10 ns。
当前又合并存储依赖、FPU输入/完成/读口、TL owner/source和取指纠正进位等十余处长链重构；
`build/gsim/rv64gc-path-batch-20261005-path-b3/receipt.json`受影响短验证通过。
13项整数短IPC周期不变，FPU加减/乘法延迟增加一拍、FP访存完成增加一拍，
板级Sv39/32FPR上下文短固件增加54周期（0.17%）；不等于Linux或浮点应用性能通过。
新完整候选显式开启`rv64gc`并按100 MHz综合及自由布局布线，厂商IP私有副本复用、
CPU综合网表不复用；最终新时序待报告，不产生新bit。MMIO及全局默认开关未改。详见
[Native GMAC整板记录](native-gmac-board.md#开启浮点的整板重新实现)。

## 历史已测配置与候选边界（2026-10-01）

用户已验证的 DDR50/115200 bit 为双发射乱序、128 KiB ROM、
512 MiB CPU-visible PL DDR。用户随后验证了两路相联 2 KiB 数据 L1 的新版 bit：
DDR benchmark 全部 PASS，8 MiB COPY payload=17.214 MiB/s，读/写约47.131/28.110 MiB/s。
下文 Board40/1 MiB UltraRAM 与早期 DDR50 均为保留的历史规格。
最新双发射／两路相联 2 KiB L1 候选已完成 50 MHz 静态签核并生成独立 bit，
其生成时尚未上板；上述为之后的用户实板反馈。CPU WNS +0.163 ns/hold +0.011 ns，
ROM/MMIO/DDR aperture/UART reference/timebase 不变。
随后 BootROM 通过 INIT-only ECO 修复为无测试菜单的 V0.1，独立输出到
`ddr-opt-20261001/bootrom-fix/release`；此版不含后续回放关键链重构。
回放候选仍为双发射、同容量、不增加生产流水级；尚未整机布线签核或上板。

板级默认 rename/issue/commit=2。可选紧凑四发射保持 ROB16/PRF48、
LSU2/store-buffer2、I/D cache 容量相同；关闭指令预取的 GSIM 同镜像
短 CoreMark 同频 +8.85%，SoC 综合 178574 LUT（芯片 52.3%，不含 MIG 等外部 IP）。
四路尚无整机 Fmax/bit/OS/中断/压力验收，不能当作板级发布规格。
详细命令、资源、频率盈亏点与产物见 [性能记录](performance-status.md)、
[时序台账](fpga-timing-windows.md)。

## DDR50 Linux 镜像状态（2026-10-01）

新增 OpenSBI v1.9 + Linux `7.3.0-rc5+`、BusyBox 1.37.0 和实际 fastfetch 2.69.0
的单一 UART 下载镜像，保持双发射/512 MiB DDR/50 MHz/115200；用户态为
静态 `rv64imac/lp64` 软浮点，无须先增加 F/D。M-mode 入口 `0x80200000`，
Linux S-mode 入口 `0x80400000`，DTB `0x80300000`，监控区末尾 16 KiB 保留。
已编译并检查镜像边界/ELF；GSIM 进入 Linux 并开始 rootfs 解压后按用户要求停止，
**未完成用户态启动，未板测**。根文件系统为 RAM-only；SBI hvc0 轮询，
不声称标准 Linux AIA、UART 外部 IRQ、SD/网络或持久存储已适配。
镜像/命令/准确资格状态见 [Linux 启动记录](linux-bringup.md)。
后续候选目标为 UART 460800，尚未实现；当前稳定规格仍是 115200。

## 当前 UART FIFO 候选（2026-10-01）

DDR45／1.5 Mbaud 和 DDR50／115200 使用同一升级 UART：16 字节 RX/TX FIFO、
16x 多数采样、超时中断、错误字节关联、5–8位／校验位／stop和内部loopback。
UART参考频率分别24000000／1843200 Hz，CPU/timebase分别45000000／50000000 Hz；
软件不得用CPU频率代替UART clock-frequency。BootROM设DLL=1、FCR=0x07。
MMIO基址与APLIC source3不变。功能回归通过，最终时序／bit签核状态见
[Windows时序记录](fpga-timing-windows.md)；实体板下载与DDR仍需用户测试。
下文Board40规格及DDR50早期记录不代表新候选的发布状态。

## DDR50 历史候选 (2026-09-30)

An independent `soc_top_ddr` / `BoardSocTop(externalDdr=true)` profile now
uses a 512 MiB AXI DDR window at `0x80200000..0xA01FFFFF`, a 50 MHz CPU
and 1.5 Mbaud UART. The existing UltraRAM bitstream is the board-validated
baseline. DDR electrical calibration remains unverified. The retained repaired/
post-route optimized checkpoint meets 50 MHz (WNS +0.001 ns, WHS +0.008 ns),
but only has 1 ps setup margin; no DDR bitstream/on-board test was performed.
The original candidate impl_1 still records the first failed route; use the
separate optimized_routed.dcp documented below. DDR firmware reserves
`0xA01FC000..0xA01FFFFF`; host
`--memory ddr` allows 512 MiB minus 16 KiB per download. The new ROM COE
must be included in the bitstream; the default URAM limit stays 1008 KiB.
Details and build commands:
[PL DDR4 integration](../fpga/zu15eg/pl-ddr4-integration.md).

## 1. 适用配置

| 项目 | Board40 配置 |
| --- | --- |
| FPGA | `xczu15eg-ffvb1156-2-i`；使用 PL，未接入 Zynq PS/DDR |
| CPU | 单 hart，`mhartid=0`，RV64，小端，M/S/U 特权态 |
| 乱序配置 | 双发射/双提交，ROB 16，物理整数寄存器 48，LSU 槽 2，store buffer 2 |
| 时钟 | 200 MHz 差分板载输入，经 `clk_wiz_0` 输出 40 MHz（25 ns 目标周期） |
| 时间基准 | `mtime` / `time` 每个 SoC 时钟加一，40,000,000 tick/s |
| 启动 ROM | 128 KiB BMG Native 双端口 ROM，32 位 × 32768，原生读延迟 1 周期 |
| 主 RAM | 1 MiB XPM UltraRAM，64 位 + 8 个字节写使能，原生读延迟 3 周期 |
| 缓存 | 前端包缓存 256 B；物理整行 I-cache 512 B；写回数据 L1 2 KiB；缓存行 64 B |
| 地址转换 | 指令/数据 Sv39，或 Bare；板级配置不启用 Sv48/Sv57 |
| 保护 | 16 项 PMP；具体模式、锁定与权限规则见适配指南 |
| 板外接口 | UART RX/TX；时钟与两路低有效复位按钮；LED 显示复位释放 |

发射宽度不是程序 IPC 保证；原生 RAM/ROM 读延迟也不是 CPU load/取指总延迟。
TileLink、缓存命中/缺失、译址、流水线和背压都会影响软件观察到的延迟。
LED/按钮/时钟 IP **没有 CPU MMIO 控制接口**，不能当作 GPIO 设备使用。

### 不要混用不同 profile

| Profile | 用途 | 内存区别 |
| --- | --- | --- |
| `BoardSocTop` / `BoardSocMain` | 当前板级软硬件合同 | ROM 128 KiB，RAM 1 MiB，RAM 基址 `0x80200000` |
| `CurrentSocTimingTop` / `CompactSocTimingTop` | 旧 4/2 发射 OOC 时序实验 | ROM 8 KiB、RAM 16 KiB，RAM 基址 `0x80010000` |
| 默认 `MachinePlatform` | 小容量功能测试 | ROM 默认 8 KiB、RAM 默认 4 KiB，RAM 基址 `0x80010000` |
| Linux GSIM 配置 | Linux/OpenSBI 功能仿真 | 使用更大的仿真 RAM，不能直接等同于本板片上 RAM |

ROM 扩到 128 KiB 后覆盖旧 RAM 基址，因此 Board40 把 RAM 移到 `0x80200000`。
旧程序/设备树/链接脚本中的 `0x80010000` 不能原样用于 Board40。

## 2. CPU 可见物理地址总表

| 起始地址 | 结束地址 | 大小 | 功能 | 软件使用状态 |
| --- | --- | ---: | --- | --- |
| `0x02000000` | `0x0200FFFF` | 64 KiB 译码窗口 | 单 hart 机器定时器 | 仅下面列出的 mtimecmp/mtime 偏移有效；不是完整 CLINT |
| `0x0C000000` | `0x0C003FFF` | 16 KiB | M-domain APLIC | 32 位寄存器；受限 MSI 模式实现 |
| `0x0C004000` | `0x0C007FFF` | 16 KiB | S-domain APLIC | 32 位寄存器；由 M-domain 委托源 |
| `0x10000000` | `0x10000007` | 8 B | UART | 8 位访问，`reg-shift=0`；当前 bootrom 使用轮询 |
| `0x10001000` | `0x10001027` | 40 B | MemoryCopy DMA 控制器 | 新源码随 RAM 配置；旧 bit 受 ERR-B40-001 限制 |
| `0x10002000` | `0x100020ff` | 256 B | 自研网络 DMA（可选） | 默认关闭，64-bit MMIO，APLIC 6；详见 DMA 合同 |
| `0x10040000` | `0x1007ffff` | 256 KiB | AXI Ethernet（可选） | 默认关闭，MAC AXI-Lite，APLIC 5 |
| `0x80000000` | `0x8001FFFF` | 128 KiB | Boot ROM | 可取指/读取，不可写；BMG COE 初始化 |
| `0x80020000` | `0x801FFFFF` | 1920 KiB | ROM 后至 RAM 前的空洞 | 不是 RAM；ROM manager 拒绝越界访问 |
| `0x80200000` | `0x802FFFFF` | 1 MiB | 主 RAM | 可读/写/执行；受当前 PMP/页表权限约束 |

表外未定义地址不得作为可用 RAM/外设探测。窗口大小不代表其中每个偏移都有寄存器；
无效地址、宽度、掩码或不支持的操作可返回访问错误，不能依赖返回零。
这是 PL RISC-V 的映射，**不是 Zynq UltraScale+ PS 的地址表**。

### 不可作为 CPU MMIO 发布的内部地址

| 内部地址 | 用途 | 限制 |
| --- | --- | --- |
| `0x24000000` 所在页 | M IMSIC MSI 投递 | 只有内部 MSI `RegisterPort` 路由可达 |
| `0x28000000` 所在页 | S IMSIC MSI 投递 | 只有内部 MSI `RegisterPort` 路由可达 |

CPU load/store 路径当前没有连接这两个 IMSIC 页。CPU 使用 AIA CSR 管理中断文件，
APLIC 通过内部路径发送 MSI。不能仅依据地址常量就在设备树声明 CPU 可写的标准 IMSIC 门铃。

## 3. 软件最常用的寄存器

以下是驱动起点，不替代 [完整寄存器表](soc-registers.md) 的复位值、掩码与副作用说明。

| 地址/偏移 | 名称 | 推荐访问宽度 | 用途/注意事项 |
| --- | --- | --- | --- |
| `0x02004000` | `mtimecmp` | 64 位 | MTIP 比较值；32 位拆分写法须防止中间值误触发 |
| `0x0200BFF8` | `mtime` | 64 位 | 时间计数；也可通过 `rdtime` 读取 |
| UART `+0x0` | RBR / THR / DLL | 8 位 | DLAB=0 时读 RX、写 TX；DLAB=1 时分频低字节 |
| UART `+0x1` | IER / DLM | 8 位 | DLAB=0 时中断使能；DLAB=1 时分频高字节 |
| UART `+0x2` | IIR / FCR | 8 位 | 读中断原因，FIFO使能/清除/触发阈值；IIR报告FIFO与超时 |
| UART `+0x3` | LCR | 8 位 | 字长/parity/stop/break可编程；bit7控制DLAB |
| UART `+0x5` | LSR | 8 位 | bit0 RX 数据可读，bit5 TX 可写，bit6 TX 完全空闲 |
| DMA `+0x00/+0x08/+0x10` | SRC / DST / LEN | 64 位 | 描述符；Board40 不应提交，见勘误 |
| DMA `+0x18/+0x20` | CONTROL / STATUS | 64 位 | 启动/中断及状态语义见寄存器手册，不是 AXI DMA 寄存器布局 |

当前升级UART包含16字节收发FIFO、字长/校验/stop和内部loopback；BootROM开启FIFO。
DDR45候选使用1500000，DDR50候选使用115200；二者都是8N1、无流控。
旧bit按旧配置，升级必须同时更新RTL、ROM COE与bit。
这不是完整ns16550a芯片级合规认证：板外modem/自动流控未接，OUT2不门控IRQ。
TX/RX须检查LSR并按IIR/FCR语义使用，UART参考频率与CPU/timebase分开配置。

MMIO 使用规定宽度和自然对齐的 volatile 访问，并根据访问顺序要求使用 I/O/内存屏障；
不要对 MMIO 执行 LR/SC/AMO，也不要把设备窗口映射成可缓存普通 RAM。
ROM/RAM 支持自然对齐的 1/2/4/8 字节普通读取；RAM 支持对应写入。
软件不得写 ROM：当前 ROM manager 只定义 Get 读请求，不能承诺非法写会得到干净的
store access fault，见 ERR-B40-002。页表/PMP 应将 ROM 设置为只读/可执行，禁止用于写入探测。

## 4. 中断分配与软件前提

| 信号 | 源/异常编号 | 路由 |
| --- | --- | --- |
| UART IRQ | APLIC source ID 3 | UART → M APLIC；可由 M 委托至 S APLIC |
| DMA IRQ | APLIC source ID 4 | 复制 DMA → M APLIC；旧 bit 仍受勘误限制 |
| MAC IRQ（可选） | APLIC source ID 5 | MAC 源域寄存电平，经 CDC 同步 |
| 网络 DMA IRQ（可选） | APLIC source ID 6 | TX/RX 完成中断，独立使能/确认 |
| 机器外部中断 | cause 11 / MEIP | M IMSIC → M-mode |
| 监督外部中断 | cause 9 / SEIP | S IMSIC → S-mode |
| 机器定时中断 | cause 7 / MTIP | mtime/mtimecmp，不经过 APLIC |
| 监督定时中断 | cause 5 / STIP | stimecmp/Sstc 路径及权限控制，不经过 APLIC |

APLIC source ID 与 IMSIC EIID 不是同一个固定编号：软件必须配置 sourcecfg、target、enable、
domain IE，以及对应 IMSIC EIE/EIDELIVERY/阈值和 CPU CSR 中断使能。
BoardSocTop 将其他外部源输入绑为零；没有额外可接线的 PL IRQ 引脚。
不要按 PLIC 的 enable/claim/complete 地址布局编写驱动。
定时器没有 `msip` 寄存器，`0x02000000` 不能当作软件 IPI 寄存器使用。

## 5. ISA、MMU 与 OS 发现

默认整数构建 `misa` 为 `0x8000000000141105`，声明 RV64 I/M/A/C/S/U；
显式 F/GC 构建见本文首节。任何 misa 取值都不是完整一致性认证。
译码还有部分 Z 扩展，推荐首先沿用已验证的固件编译选项：

```text
-march=rv64im_zicsr_zifencei -mabi=lp64
```

现有已上板构建继续使用软浮点库，F/D 默认关闭。2026-10-03 主工程新增
可选完整基础 RV64 F/D 功能候选，配置和验收见 [OoO 阶段记录](ooo-core-plan.md)；
默认 misa/设备树不声明 F/D；显式完整 F/GC 构建才声明匹配能力。Linux 浮点
上下文和带 F/D 的新整板时序尚未验收。V 未实现。
不要根据器件型号选 AArch64 编译器，
也不要将 RVA23 规划文档当作当前 CPU 已支持的 profile。

| 软件功能 | 当前合同 |
| --- | --- |
| `time` CSR `0xC01` | 可用；Board40 timebase=40 MHz；低特权访问受计数器权限控制 |
| `cycle/instret/mcycle/minstret` | 未实现；直接读取会非法指令陷阱，不能用于当前移植的通用性能计数 |
| `satp` | Bare/Sv39；写 satp 后软件仍须正确执行 SFENCE.VMA |
| PTE A/D | 当前由软件管理；缺少所需 A/D 位会 page fault |
| `FENCE.I` | 当前平台串口下载后执行的路径包含数据可见性处理和取指失效；仅单 hart 合同 |
| SBI/DTB | ROM monitor 不提供 SBI 服务，也不传设备树地址；需单独移植启动层 |
| Linux | 已有 GSIM 启动记录，但 Board40 的 1 MiB RAM、外设连接与启动协议不能直接套用它 |

详细 CSR 清单、陷阱、PMP、页表约束见 [OS/裸机适配指南](os-software-porting.md)。
不发布“拿来就能启动 Linux”的设备树；内存节点、定时器、中断控制器驱动和启动 ABI
必须与上面的实际连接一致，特别是内部 IMSIC 地址与暂不可用 DMA。

## 6. Boot ROM 与 RAM 程序布局

启动顺序：复位 → ROM monitor → UART 下载到 RAM → CRC 校验 → 屏障/取指同步 → 跳转。
BootROM V0.1 只负责下载和引导：打印 `Valence Bootrom V0.1`、`download mode (UART)`，
校验通过后显示 `ready to boot`，执行时显示 `boot from UART (RAM/DDR)` 和入口地址。
保留 `d` 下载、`g` 执行；移除 ROM 内 RAM/ALU/定时器/回显测试，由下载程序负责。
仅支持 UART 镜像来源，不代表已支持 Flash/SD 启动；复位后不会自动运行 RAM 残留内容。
复位不会清空整块 RAM；应用必须初始化自己的 BSS、栈和全局指针，不能依赖 RAM 上电内容。

| 区域 | 起止地址 | 大小 | 所有者 |
| --- | --- | ---: | --- |
| 应用代码/数据/BSS（示例链接脚本） | `0x80200000–0x802F7FFF` | 992 KiB | 应用 |
| 应用栈（示例链接脚本） | `0x802F8000–0x802FBFFF` | 16 KiB | 应用，向低地址增长 |
| ROM monitor 工作区 | `0x802FC000–0x802FFFFF` | 16 KiB | bootloader 全局变量、接收缓冲和栈 |

下载器接受的文件最大 1008 KiB，但这一上限包含示例应用栈所在的地址范围；
不能把 1008 KiB 都用于代码/BSS 后仍按示例栈布局运行。
启动地址默认 `0x80200000`，入口必须在镜像内、4 字节对齐；加载平坦 `.bin`，不解析 ELF。
以 M-mode、Bare、关闭中断进入，`a0=a1=0`；这不是 Linux 的 hartid/DTB 交接协议。
应用按约定返回后可回到 monitor；死循环、破坏 monitor RAM/mtvec/PMP 等情况需按键复位。
该预留区是软件约定，不是对 M-mode 程序的硬件隔离。

串口协议使用 256 B 分块、CRC32、逐块确认与重试，整镜像及 RAM 读回校验成功才允许运行。
详见 [ROM 下载器协议与链接脚本](../fpga/firmware/README.md)。
本次首次部署仍需生成新的 bitstream；后续仅修改 RAM 程序，只需编译和串口下载。

## 7. 勘误与尚未提供的能力

### ERR-B40-001：旧 bit 的 DMA 地址检查仍使用旧平台范围

旧部署的 `MachinePlatform` 创建 `new MemoryCopyDma()`，没有传 Board40 的 RAM 基址/容量。
DMA 自身仍只接受 `0x80010000–0x80010FFF`，该区域在 Board40 中已落入 ROM。
真正的板级 RAM 地址 `0x80200000` 会被描述符检查拒绝；旧范围也不能作为可写 RAM 使用。
**旧 bit 软件必须禁用 RAM DMA，使用 CPU memcpy。** 2026-10-04 新源码已显式传递
正确 RAM 基址/容量；新 bit 板级复制验收之前不把此勘误视为已部署解除。
新增可选 `EthernetPacketDma` 是独立 ABI，收发/缓存/跨域合同见 [DMA](dma.md)。

### ERR-B40-002：ROM 非法写缺少完整总线拒绝合同

`TileLinkInstructionRomAdapter` 通过 assertion 要求输入为合法 Get，响应类型固定为
AccessAckData；它没有为 Put 写请求实现明确的 denied/AccessAck 返回路径。
ROM 本身没有写端口，但“内容不会被修改”不等于“CPU 一定获得规范写访问异常”。
驱动/OS 不应执行 ROM 写探测，也不能用 ROM 地址作 DMA 目标；此问题仍需 RTL 修复和负向测试。

尚无板级 DDR/PS AXI、SD/SPI 闪存、以太网、USB、通用 GPIO、调试模块/JTAG RISC-V 调试接口
的软件合同；不要将 FPGA 芯片自带的资源视为已接入本 RISC-V SoC。
也不承诺多 hart 启动、IPI、跨 hart 缓存同步、浮点/向量、完整 AIA 或标准外设驱动即插即用。

## 8. 验证状态与接口依据

| 证据 | 范围 | 不能外推的结论 |
| --- | --- | --- |
| Board boot GSIM：2,006,849 周期通过 | 菜单、RAM 程序、CRC/范围拒绝、重传、同地址重下载/FENCE.I | 通用存储模型、缩短 UART 分频；不是 FPGA 时序签核 |
| ROM/RAM 定向 GSIM、主机协议测试 | 访问边界、背压、1/3 周期 RAM 模型、8 项 host 测试 | 不是所有设备或完整 ISA 一致性认证 |
| Vivado RAM 独立综合 | 32/112 个 URAM，2018 LUT，108 FF | 不是整机面积；未布局时序不能代表板级 Fmax |
| 两个 IP 构建、整板 RTL elaboration | IP 输出、端口和工程连接 | 未进行新 Board40 的完整布局布线/板上回归 |

此前小内存紧凑 profile 的 45 MHz 内部时序报告不适用于新 Board40。
当前 40 MHz 是配置目标，最终应以此版板级 post-route 报告和上板测试确认。
历史优化记录保留在 [FPGA 时序台账](fpga-timing-windows.md)，不与软件地址合同混用。

维护本文时优先核对以下源码，而非复制旧测试的硬编码地址：

- [BoardSocConfig/BoardSocTop](../src/main/scala/core/ooo/BoardSocTop.scala)：板级参数、时钟 tick、顶层连接。
- [MachinePlatform](../src/main/scala/core/ooo/MachinePlatform.scala)：外设实例、译码窗口、RAM 路由与中断源。
- [MappedMachineCore](../src/main/scala/core/ooo/MappedMachineCore.scala) / [MachineCore](../src/main/scala/core/ooo/MachineCore.scala)：APLIC 与内部 MSI 连接。
- [MachineSystemUnit](../src/main/scala/core/ooo/MachineSystemUnit.scala)：CSR、特权态、Sstc 与中断。
- [板级工程配置](../fpga/zu15eg/README.md) / [固件链接脚本](../fpga/firmware/bootrom.ld)：IP、时钟和软件预留 RAM。

### 2026-10-01 缓存候选与已发布版本的区别

地址/设备合同不因相联度改变。新 BoardSoc 源码候选使用
16 sets×2 ways×64 B（仍为 2 KiB），home 目录匹配；
已上板 DDR50/115200 bit 仍是 32 sets×1 way×64 B，未被替换。
无新增流水拍，ROM 协议、UART 与软件物理地址不变。
新候选通过必要 GSIM/模块 OOC，但整机布线/板上性能尚未验收；
源码默认值变更不代表实体板已更新。见 [性能记录](performance-status.md)。
