# OS 与软件移植合同

状态：2026-10-04。下表保留 Board40/UltraRAM 历史基线；新 ISA 配置见下节。
本文描述 `BoardSocTop` 的软件可见行为，以仓库 RTL 和
`fpga/firmware` 为准。模块参数可支持的功能、历史 GSIM 配置和这版 FPGA 板级配置
不是同一个承诺。平台总览见 [SoC datasheet](soc-datasheet.md)，MMIO 位定义和访问宽度见
[寄存器手册](soc-registers.md)，板级生成见 [FPGA bring-up](fpga-bringup.md)。

本版适合裸机、监控程序和小型 RTOS 移植；不能把“GSIM 中有 Linux/OpenSBI 流程”解释成
这版 1 MiB RAM 板级 bitstream 已具备 Linux 启动条件。当前 ROM 不提供 SBI 服务、DTB、
ELF 装载器、磁盘或网络启动，也没有把 Zynq PS 的 ARM CPU、DDR 或外设接入此 RISC-V 地址空间。

DDR50 现已有匹配 ROM M-mode ABI 的 OpenSBI/Linux/BusyBox/fastfetch 下载镜像；
不需要 F/D，用户态静态 RV64IMAC/lp64。GSIM 内核启动后按用户要求停止，尚未完成
用户态或板级验证；具体入口、保留内存和限制见 [Linux 启动记录](linux-bringup.md)。
下面固定参数表属于历史 Board40，不是新的 DDR50 容量/波特率。

## 完整 F/GC 候选的软件选择

BoardSoc RTL 新增最后一个可选 `isaProfile`：默认 `rv64imac`；
`rv64imafc` 仅 F；`rv64gc` 为 IMAFDC+Zicsr+Zifencei。
misa/设备树与完整已选择配置一致，详见 datasheet；裁剪组不能宣告完整 F/D。
旧整数版 bit 与软浮点镜像不变，不得先改 DT 宣告 F/D 再运行旧 bit。

Linux 构建器新增 `--isa rv64gc --cpu-hz 100000000 --uart-baud 460800`，
使用新的 `--out` 目录。它生成匹配的 DT，并启用 `CONFIG_FPU`；默认仍关闭。
BusyBox/CoreMark 用户态仍可使用原 lp64 软浮点二进制；需要实际 FP 程序才能
验收 Linux 的上下文调度与信号保存恢复，单纯开启 CONFIG_FPU 不算通过。
本轮尚未构建/验收新的 Linux FP 镜像或生成 F/D bit。
裸机完整 GC 可用 `-march=rv64gc -mabi=lp64d`，仅 F 用 lp64f；这并不扩大
当前 ABI 的 ROM 下载范围或改变 MMIO/入口/DTB 布局。

## 固定板级参数与存储布局

| 项目 | 当前 BoardSocTop |
| --- | --- |
| Hart / XLEN / 字节序 | 单 hart，RV64，小端；`mhartid=0` |
| 时钟与时间源 | CPU 40 MHz；每个 CPU 时钟递增一次 `mtime/time`，timebase=40,000,000 Hz |
| 复位入口 | M 模式，PC=`0x80000000` |
| ROM | `0x80000000..0x8001ffff`，128 KiB，BRAM Native Dual Port ROM |
| RAM | `0x80200000..0x802fffff`，1 MiB，UltraRAM；底层 RAM 读返回流水为 3 拍 |
| ROM 与 RAM 间的空洞 | `0x80020000..0x801fffff`，不是额外 RAM；不得放代码、页表或堆 |
| 下载器保留区 | `0x802fc000..0x802fffff`，16 KiB，ROM 监控程序全局变量、测试区与栈 |
| 示例程序区域 | `0x80200000..0x802f7fff`，992 KiB，代码/常量/已初始化数据/BSS |
| 示例程序栈 | `0x802f8000..0x802fbfff`，16 KiB，初始 SP=`0x802fc000` |
| UART | `0x10000000`，仅 8-bit 寄存器访问；新版 ROM divisor=1 对应 1.5 Mbaud；旧 bitstream 为 host 115200、divisor=22 |

“RAM 读 3 拍”只是存储器接口延迟，不是 CPU load 固定 3 拍：缓存、TileLink、
仲裁、翻译和 CPU 调度会增加周期。40 MHz 是板级时钟配置，不能代替这版设计的最终实现时序报告。

ROM 监控程序先初始化自己的数据/BSS，再进入命令终端。RAM 内容不是软件初始值合同；
应用必须初始化栈、`gp` 和 BSS，并处理自己的 `.data`。不要使用历史小配置中的
`0x80010000` 作为 RAM 基址，它在本版属于 ROM。

ROM manager 当前仅定义 Get 读取，非法写只有协议断言、没有完整的 denied 写响应合同；
不能靠写 ROM 探测来期待规范 access fault。应以页表/PMP 设置只读/可执行权限，
避免直接写 ROM；详见 [datasheet 的 ERR-B40-002](soc-datasheet.md)。

## DDR45 / DDR50 FIFO-UART 软件配置

2026-10-01 两个候选的 CPU/mtime 时基分别为 **45,000,000 Hz** 和 **50,000,000 Hz**，
UART 下载速率分别为 **1,500,000** 和 **115,200 baud**。DDR 窗口是
`0x80200000..0xA01FFFFF`（512 MiB），ROM 监控区是末尾 16 KiB
`0xA01FC000..0xA01FFFFF`；不能沿用上表的 UltraRAM 容量或栈地址。
ROM 仅打印版本/下载状态；旧 r/a/t/e 自检菜单已移至 RAM 应用。

UART 仍位于 `0x10000000`，reg-shift=0、reg-io-width=1、APLIC source3。
现在具备 16 字节 RX/TX FIFO、RX 超时中断、可编程帧格式和错误状态。
16550 驱动必须提供**波特率参考时钟**而不是 CPU 时钟：

| 配置 | UART clock-frequency | 初始 divisor | 初始波特率 | timebase-frequency |
| --- | ---: | ---: | ---: | ---: |
| DDR45 FIFO | 24,000,000 | 1 | 1,500,000 | 45,000,000 |
| DDR50 FIFO | 1,843,200 | 1 | 115,200 | 50,000,000 |

所有 divisor 遵循 `baud=reference/(16*max(divisor,1))`；旧镜像的 divisor=22
不能在新硬件上继续解释为 115200。OpenSBI/OS 若重配 UART，需修改对应板级配置或 DTB，
否则 ROM 下载成功后应用日志也可能乱码/消失。外部 modem 引脚、硬件流控未实现，
OUT2 不门控 SoC IRQ；详见 [UART 合同](uart.md)。
匹配的 DDR 测试程序和 bit 路径见 [时序发布记录](fpga-timing-windows.md)。

## ISA、ABI 与发现方式

当前机器核的 `misa` 返回 `0x8000000000141105`：MXL=RV64，I/M/A/C/S/U 置位。
该值固定，写 `misa` 不改变扩展；它不是完整合规认证，也没有描述所有多字母扩展。

| 能力 | 当前实现 / 软件边界 |
| --- | --- |
| RV64 整数、M | 普通整数、分支、自然对齐的 8/16/32/64-bit load/store、乘除路径 |
| A | RAM 范围内 LR/SC.W/D 与 AMO.W/D；单 hart；不要对 ROM/MMIO 执行原子指令 |
| C | 板级默认整数压缩路径；对齐单位 2 字节；实验 F+D 配置新增四种压缩双精度访存，默认板级不启用 |
| Zicsr、Zifencei | 六类 CSR 操作及 `FENCE.I`；具体 CSR 只支持下表列出的集合 |
| Zba/Zbb/Zbs、Zicond | 译码与执行路径已实现，见 [B 扩展](rv64b.md)、[架构目标](rva23.md)；`misa.B` 当前未置位 |
| M/S/U | 有返回、委托、中断和分页开发路径；没有完整特权规范合规声明 |
| F/D | 已接入可选完整基础指令功能候选，默认关闭且 misa/DT 不声明；Linux 浮点上下文和新完整 F/D FPGA 时序待验收，详见 [阶段记录](ooo-core-plan.md) |
| V/H | 未实现；不能使用向量或虚拟化内核路径 |
| Zicntr / Zihpm | 不能声明支持：只有 `time`，没有 `cycle/instret` 或 HPM CSR |
| WFI | 作为可立即继续执行的 hint；不保证睡眠、省电或阻塞到下次中断 |
| 非对齐访问 | load/store 不做硬件拆分，产生地址非对齐异常；软件应自然对齐 |

当前 ROM 与示例使用保守、已验证的编译目标：

```sh
-march=rv64im_zicsr_zifencei -mabi=lp64 -mcmodel=medany -mno-relax
-msmall-data-limit=0 -ffreestanding -fno-builtin -nostdlib -nostartfiles
```

这些选项没有要求硬件缺少 A/C，只是让首个软件基线更容易排错。采用 A/C/B 等指令的
库和运行时，应选择相应的工具链选项并做针对性验证。不要直接使用 `rv64gc/lp64d`：
其中 F/D 在现有上板配置关闭；实验功能候选并不允许直接改现有 Linux 到硬浮点 ABI。
需先验收上下文保存/恢复、匹配 misa/DT 及新 bit，再选择 lp64f/lp64d。
时间测量使用 `rdtime`，不能把 `rdcycle` 当作可用的便利指令。

## 当前 CSR 清单

地址为十六进制。M/S 表示最低访问权限；更低权限访问、未知 CSR 和真正只读地址的写入会
产生非法指令异常（cause=2）。WARL 字段会按实现掩码读回，写不存在的状态位不会创建功能。
S/U 的 `time` 访问另外受 TM 位控制。

| CSR 地址 | 名称 | 权限 / 当前合同 |
| --- | --- | --- |
| `100` | sstatus | S；SIE/SPIE/SPP、SUM/MXR，UXL 固定 RV64 |
| `104` / `144` | sie / sip | S；仅显示已由 `mideleg` 委托的 SEI/STI/SSI；sip 只允许改 SSIP |
| `105` | stvec | S；Direct=0、Vectored=1，其他模式写成 Direct |
| `106` | scounteren | S；只实现 TM[1]，控制 U 态读 time |
| `140` / `141` / `142` / `143` | sscratch / sepc / scause / stval | S；64 位；sepc[0] 固定零 |
| `14d` | stimecmp | M 总可访问；S 还要求 STCE=1 且 mcounteren.TM=1；复位全 1 |
| `150` / `151` / `15c` | siselect / sireg / stopei | S；S IMSIC 文件的间接选择、访问及领取；selector 12 位 |
| `180` | satp | S；本板 Bare=0 或 Sv39=8；不支持的 MODE 写入保持旧值；Bare 写入整体清零 |
| `300` | mstatus | M；SIE/MIE/SPIE/MPIE/SPP/MPP/MPRV/SUM/MXR；SXL/UXL 固定 RV64 |
| `301` | misa | M；固定值见前文，写入忽略 |
| `302` | medeleg | M；可写掩码 `0xb3ff`，同步 cause 0–9、12、13、15；M 态异常不委托 |
| `303` | mideleg | M；仅位 1、5、9（SSI/STI/SEI） |
| `304` | mie | M；仅 SSIE[1]、STIE[5]、MTIE[7]、SEIE[9]、MEIE[11] |
| `305` | mtvec | M；Direct=0、Vectored=1，其他模式写成 Direct |
| `306` | mcounteren | M；仅 TM[1] |
| `30a` | menvcfg | M；仅 STCE[63]，未实现 PBMTE 等其他字段 |
| `340` / `341` / `342` / `343` | mscratch / mepc / mcause / mtval | M；64 位；mepc[0] 固定零 |
| `344` | mip | M；MEIP/MTIP/SEIP 为外部状态；SSIP 可写；STCE=0 时 STIP 可写 |
| `350` / `351` / `35c` | miselect / mireg / mtopei | M；M IMSIC 文件间接访问；selector 12 位 |
| `3a0` / `3a2` | pmpcfg0 / pmpcfg2 | M；分别含 PMP0–7、PMP8–15；RV64 奇数配置 CSR 不存在 |
| `3b0..3bf` | pmpaddr0..15 | M；有效低 54 位，对应 56-bit 物理地址空间 |
| `c01` | time | 只读；M 总可读，S 需 mcounteren.TM，U 还需 scounteren.TM |
| `f11..f14` | mvendorid / marchid / mimpid / mhartid | M，只读，当前均为 0 |

上述零值 ID 不构成可区分硬件版本的发现接口；软件应带固定板级配置。没有
`mconfigptr`、`mstatush`、`mcycle/minstret`、`cycle/instret`、
`mcountinhibit`、PMP 增强控制、H/VS CSR、`mtopi/stopi`、FPU/向量状态 CSR。
不要以“通常的 RISC-V 启动代码会写它”为理由无条件访问。

复位时权限为 M，`satp=0`，中断使能、委托、PMP 配置、TM 与 STCE 为零；
`mstatus=0x0000000a00000000`，`stimecmp=~0ULL`。
`mtvec/stvec` 为零，需在启用中断或预期异常前设置。
应用被 ROM `g` 命令启动时，已执行一段 ROM 代码，不能假设所有 CSR 仍为硬件复位值。

## 陷阱、时间与中断移植

`mtvec/stvec` 的基址按 4 字节对齐；Direct 模式所有陷阱跳基址，Vectored 模式只有
中断使用 `BASE+4*cause`，同步异常仍跳基址。异常记录故障 PC 到 EPC，
记录原因到 cause；非法指令 tval 为指令，load/store 故障 tval 为有效地址。
不要在中断处理函数里无条件给 EPC 加 4；当前板还启用了压缩指令。

中断可用原因及固定仲裁优先级为 MEI(11)、MTI(7)、SEI(9)、SSI(1)、STI(5)；
已完成的同步异常优先。精确中断需要旧访存排空，不能推导固定最坏响应周期。
未委托的中断进入 M；已委托的 S 中断在 M 态保持待处理，S 态受 SIE 屏蔽，U 态不受 SIE 屏蔽。

机器定时器只提供 `mtime/mtimecmp`，不等于完整 CLINT/MSIP。
当前 `time` 每 tick 为 25 ns；RTOS tick 为 1 kHz 时比较值间隔应为 40,000，
不能沿用某些 GSIM/Linux 配置的 10 MHz 时基。
M 态可用 MTIP；S 态可由 M 设置 TM、STCE、委托与使能后直接使用 Sstc。
Sstc 比较结果寄存一拍，写比较值后应允许待处理中断稍后撤销，见 [Sstc](sstc.md)。

UART/复制 DMA 的有线源分别接 APLIC source 3/4；UART 下载监控程序使用轮询。
新增 opt-in Ethernet 控制为 source 5，网络 DMA 为 source 6，不改变原分配。
网络 DMA MMIO=`0x10002000–0x100020ff`，自然对齐 64-bit；MAC 控制
MMIO=`0x10040000–0x1007ffff`，原生 32-bit AXI-Lite。两项均默认关闭，
不能把这些窗口添加到旧 bit 的静态板配置后就认为硬件存在。
裸机/RTOS helper 在 `fpga/firmware/ethernet_dma.h`，提交前/完成后 fence，
活跃缓冲区归 DMA 所有；缓存探测、尾字节、错误和冷复位合同见 [DMA](dma.md)。
自研 ABI 无 SG/ring，不兼容标准 Xilinx AXI DMA 寄存器；通用 xilinx_axienet
驱动不能直接使用。尚未交付 Linux 专用网卡驱动、网卡 DT 节点或 PHY 上板验收。
MappedMachineCore 有 M 根域和 S 子域，但当前 AIA 是定制集成，并非标准 AIA 平台的完整软件合同。
`0x24000000/0x28000000` 是内部 MSI 通道使用的 IMSIC 地址，未映射到 CPU MMIO 路由；
不能把这些地址直接写进一个声称可用的标准 AIA 设备树。完整寄存器细节和缺口见
[寄存器手册](soc-registers.md)。

## PMP 与进入 S/U 模式

本板启用 16 项 PMP，最小粒度 4 字节，支持 OFF/TOR/NA4/NAPOT。
最小编号的重叠项获胜，而且要覆盖访问的所有字节。未锁定项允许 M 态绕过其权限位；
S/U 态无匹配项则拒绝。锁定位只能通过硬件复位清除，TOR 的锁定还可能锁住前一项地址。
保留位读零，W=1/R=0 写后清 W；详见 [PMP](pmp.md)。

ROM 默认在 M 模式运行并关闭未锁定 PMP 项；直接执行 MRET 到 S 不会自动赋予 S 对 RAM 的访问权。
操作系统启动阶段需要为 S/U 程序、页表和必要设备设置 PMP 区域，并安装 M/S 陷阱入口、
配置返回目标和委托。MPRV 只影响 M 态数据访问的有效权限，不影响 M 态取指。
当前未实现 TSR/TVM/TW 等完整特权控制；不要把该开发核心用作已验证的安全隔离边界。

## Sv39 页表与缓存维护

本板 I/D 译址都接通，`satp` 含 MODE、16-bit ASID 和 44-bit 根 PPN，只接受 Bare 或 Sv39。
独立可参数化模块的 Sv48/Sv57 不代表这版板级配置支持这些模式。
支持标准层级叶子的地址重建，4 KiB 基页、2 MiB/1 GiB 超页仍必须映射到实际存在的物理资源；
超页不会凭空扩大 1 MiB RAM。每侧有 8 项 TLB、独立 miss walker 和 4 项非叶 PTE 缓存。

PTE 的 V/R/W/X/U、规范虚拟地址、超页对齐、SUM/MXR 均参与检查。
A=0 或写访问 D=0 会产生 page fault，硬件不回写 A/D 位：软件应预置或在缺页处理程序中设置。
PTE 读取使用 S 态 PMP 权限；页表内存错误/PMP 拒绝是原访问类型的 access fault，
格式/权限/A/D 等页表错误是 page fault。

写 `satp` 会使年轻取指重取，但不会自动清空 TLB/PTE 缓存。
使用 `sfence.vma x0,x0` 完成页表变更边界；当前所有 rs1/rs2 编码均采用保守的全局失效，
不提供定 VA/定 ASID 的性能收益。修改可执行代码还需要 `fence.i`，
它和 `sfence.vma` 解决的是不同状态。详细流程见 [虚拟内存](virtual-memory.md)。

页表 walker 识别部分 Svnapot 64 KiB 与 Svpbmt 编码，数据 NC/IO 可旁路 L1；
但 PBMTE 控制、完整 PMA/PBMT 访问顺序及软件发现没有完整实现。
OS 初版应使用普通 Sv39 PTE（PBMT=0、N=0），不要宣称已完成这些扩展的通用移植。

板级 D-cache 为 32×64 B=2 KiB、直接映射、写回；可执行 RAM 的两路 I-cache 为
8×64 B=512 B，前端另有 16 组×2 路×8 B=256 B 的取指包缓存。缓存未向软件开放
逐行 clean/invalidate 操作或标准 CMO 指令。所有普通 RAM 写后执行以下序列再跳转到新代码：

```asm
fence rw, rw
fence.i
```

在本实现中 FENCE.I 等待写回 D-cache 刷新完成，并使取指状态失效，然后从后继 PC 重取。
UART 下载器已使用此路径；GSIM 已覆盖重复下载并在同一 RAM 地址执行改变后的指令。
普通 FENCE 按全 IORW 排空保守实现；`volatile` 只限制编译器访问，驱动仍应按协议设置
`fence iorw,iorw` 等顺序边界。

**当前板级 DMA 应禁用。** `MachinePlatform` 实例化 DMA 时没有传递新 RAM 范围，
其描述符检查仍使用旧 `0x80010000/4 KiB`；合法的新板 RAM 地址会被拒绝，
旧范围又已经落入 ROM。不要运行旧 DMA 示例，也不要把它作为当前板级缓存一致性的验收证据。
修复该地址合同并完成针对性测试后，才可移植 DMA 驱动；内存屏障无法修正地址配置错误。
这不影响当前轮询 UART 下载器，其写 RAM 操作由 CPU 完成。

## 应用装载、链接与调试

ROM 的 `d` 命令进入下载模式，PC 工具发送长度/入口/CRC32，再按 256 字节分块、
逐块 ACK 传输。镜像完成后再次读 RAM 校验 CRC；只有验证通过的镜像允许 `g` 执行。
协议、错误码和超时见 [固件说明](../fpga/firmware/README.md)。

下载器只接收从 `0x80200000` 开始的 flat binary，最大 1008 KiB。
它不解析 ELF、不定位多个段、不清应用 BSS，也不提供重定位。链接脚本必须让代码、常量和
初始化数据位于实际 RAM 装载地址，应用启动代码负责其余初始化。
示例把下方 992 KiB 用作镜像/BSS，并额外保留 16 KiB 应用栈；它不是一个 1008 KiB 栈外镜像上限。

```sh
make fpga-board-firmware
riscv64-unknown-elf-objcopy -O binary app.elf app.bin
```

```powershell
python -m pip install pyserial
python uart_load.py COM5 app.bin --run --console
```

复用 [sample_app.ld](../fpga/firmware/sample_app.ld) 与
[sample_start.S](../fpga/firmware/sample_start.S) 最容易保持正确布局。
下载入口必须 4 字节对齐且在镜像内；硬件支持 2 字节 IALIGN 并不改变当前下载协议的入口规则。

ROM 调用镜像时处于 M/Bare、关闭中断、关闭未锁定 PMP 项，`a0=a1=0`，
并提供应用栈顶；应用应建立自己的 `gp`、栈与 BSS。
这里 `a1` 不是 DTB 指针，`a0` 为零也不表示已实现 Linux 启动 ABI。
通过保存的 `ra` 正常返回可恢复监控终端。
保护 ROM 的 trap handler 和保留 RAM 时，同步异常可回到监控终端；应用重写 mtvec、锁定 PMP、
切换权限或无限循环后可能必须按硬件 reset。下载器是可信程序调试工具，不是安全启动机制。

改变 RAM 程序只需重新编译和串口下载；改变 ROM 监控程序、硬件内存映射或 RTL，
仍需更新对应 COE/IP/bitstream 流程。关掉主机串口程序不会停止 CPU。

## 移植检查顺序与证据边界

1. 先从 ROM 终端验证 UART、RAM、ALU、timer；再下载能返回的最小 M 态应用。
2. 建立 trap 输出，使用 time CSR 计时，确认无硬浮点或未实现 CSR。
3. 为 RTOS 配置真实 40 MHz timebase 和比较器，再接入中断；保留轮询控制台便于定位问题。
4. 需要 S 态时先做 PMP 与 MRET/SRET，再做普通 Sv39 页表及缺页处理；最后接入 SBI/OS 框架。
5. Linux/OpenSBI 需要单独解决 RAM 容量、SBI/DTB、启动 ABI、AIA 集成和缺失 CSR/ISA 的适配，
   使用 [Linux 文档](linux-bringup.md) 与 [OpenSBI 文档](opensbi-bringup.md) 中匹配的 GSIM 配置。

已完成的板级逻辑 GSIM 验证覆盖 ROM 启动、保留区 RAM 自检、错误头/越界、
CRC 失败重试/重复 ACK、下载 C 示例、RAM 执行返回以及同地址代码更新。
它验证真实 CPU 和串口时序逻辑，不等于 XPM/BMG 实现后的物理时序、板级串口或
Linux/RTOS 上板验收。本次文档整理没有新增功能测试，也没有重跑全量回归。
