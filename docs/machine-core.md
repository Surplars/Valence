# 系统指令、CSR 与陷阱合同

当前状态（2026-09-30）：`OooParams(machineSystem=true)` 启用六条 Zicsr、ECALL、EBREAK、
MRET/SRET、FENCE/FENCE.I、WFI hint、M/S/U 陷阱与中断路径。MachinePlatform 启用 16 项 PMP；
可选 I/D 分页已接通，当前 BoardSocTop 选择 Sv39。`time` 可读，`cycle/instret` 等计数 CSR 未实现；
VS/H、完整特权 CSR 和 RVA23 合规仍未完成。原整数裸核配置的异常停止行为不代表板级机器核。

板级可用 CSR、复位/下载 ABI 和已知限制以 [OS/软件移植合同](os-software-porting.md) 为入口，
MMIO 见 [寄存器手册](soc-registers.md)。下文包含按里程碑保留的历史验收记录；
历史“本轮”数字不能作为当前板级配置的性能或功能总表。

依据 Zicsr 2.0 和特权规范机器级 CSR/陷阱语义，独立于旧 CSRFile：
https://docs.riscv.org/reference/isa/v20240411/unpriv/zicsr.html
https://docs.riscv.org/reference/isa/v20250508/priv/machine.html

## 执行与副作用合同

系统指令使用一个独立单项事务槽，借用 lane0 的发射预算和完成端口；只允许 ROB 队首且源就绪、
提交允许、无恢复并且访存已排空时发起。CSR 副作用不能投机，握手后保持 token 所有权直到退休，
外部恢复不能撤销该指令；年轻分支的恢复可以保留它。CSR 请求与响应都必须在背压下保持稳定。
年轻访存不能越过未执行的系统指令，已经发起的普通 RAM 读必须先排空；这是保守顺序基线。
普通整数/M 流仍可乱序执行。每实例最多一条系统指令在途；本地请求后下一拍完成，外部 IMSIC
访问另等待其响应。尚未优化 CSR 流吞吐，不把它当成最终多发射 CSR 实现。

CSRRS/CSRRC 的写抑制依赖编码中的 rs1/zimm 是否为零，不能用寄存器的数值是否为零判断。
CSRRW[I] rd=x0 不产生读副作用。IMSIC 当前无读副作用，但仍保留读/写意图的处理边界。
非法 CSR、只读地址写入、权限不足均无副作用，产生 cause=2、tval=原指令的精确异常。

同步异常不退休，不更新目的寄存器；先撤销故障项及其所有年轻项，再从 mtvec.BASE 取指。
保存 mepc/mcause/mtval，MPIE←MIE，MIE←0，MPP←原权限，进入 M。
MRET 在 M 模式执行：跳到 mepc，MIE←MPIE，MPIE←1，权限←MPP，MPP←U；取消所有年轻旧路径指令。
当前可记录 M/S/U 权限标签、检查 CSR 最低权限及 ECALL cause，支持有限的 S/U 裸地址空间程序，但还未实现完整 S/U 执行环境。

本地 CSR：mstatus 的 MIE/MPIE/MPP（SXL/UXL 固定 RV64）、mtvec（Direct/Vectored 模式，同步陷阱使用 BASE、M外部中断使用BASE+44，M定时中断使用BASE+28）、mscratch、
mepc（C 开启时 IALIGN16，否则 IALIGN32）、mcause、mtval，及只读 ID（均0）。`misa` 返回固定 RV64 MXL、I/M/S/U，
并按实例参数声明 A 与 C；不把未实现的扩展写入位图。
当前 mie/mip 已包含 MEI、MTI、SEI、SSI、STI；其中 SSIP 可写，STIP 的写权限取决于 STCE。
`time` CSR（0xC01）已接通；`cycle/instret` 等不存在的 CSR 访问产生非法指令。
AIA 已接 M/S 文件的间接 CSR；完整 AIA/VS 仍待实现，不能据此声明标准 AIA 操作系统无需适配。
外部 IMSIC 的 CSR 请求必须由上述队首授权产生，不能从组合译码直接驱动。

## 时序边界

CSR 文件读/改/写、权限检查及响应寄存；陷阱向量/返回地址进入现有 ROB 回滚和前端重定向。
CSR 完成、MRET 重定向和年轻分支仲裁不能相互构成 ready/valid 组合环。状态存储、发射选择及
旁路开销待 Vivado 测量；原裸核配置应保持 IPC 基线。全部行为验证只使用 GSIM。

## 独立组装与验证入口

`MachineCore` 组装启用系统指令的 `IntegerCore` 和独立 `Imsic`，仍暴露指令供给、数据存储器、
MSI 寄存器事务和提交/陷阱观察接口。IMSIC 可继续独立导出；核心侧 `MachineCsrPort` 不依赖
IMSIC 内部实现。`externalPending` 输出各文件中断电平，M/S 文件已连接 CPU 异步陷阱入口；VS 暂未接入。
`FpgaPlatformTop` 是旧整数基准入口；当前上板入口为 `BoardSocTop`，使用上述机器核、
128 KiB ROM 和 1 MiB RAM。它不提供预置 SBI/DTB，见 [板级软件合同](os-software-porting.md)。

- `make gsim-machine-test`：ROB8/PRF36、ROB32/PRF64 两组机器核。
- `make machine-core-rtl`：单独导出默认机器核组装到 `build/ip/machine-core`。
- `make test`：同时验收新机器核、独立 IP 和既有整数基准配置。

初始同步陷阱里程碑定向验收两组各 10 个程序、7,893 条退休指令、34 次同步陷阱、36 次 MRET、1,310 次 CSR 操作。
覆盖六种 CSR 编码、rs1/zimm/rd=x0、别名、非零寄存器值为零仍触发写、只读/未知 CSR、非法 SYSTEM、
384 组随机 64-bit 操作数、MIE/MPIE/MPP 栈、嵌套处理程序、U/S 权限标签拒绝 M CSR/MRET、
不同 ECALL cause、load 对齐/访问错误、提交背压、错误路径 CSR/store 与 IMSIC claim。

每个事件先与独立 C++ 解释器核对。三组标准 CSR/陷阱程序及嵌套陷阱程序另与锁定 NEMU 比较
全部 GPR、PC、mstatus/mode、mepc/mcause/mtval/mtvec/mscratch；测试开始前统一复位状态，
执行过程中不重同步或跳过错误。AIA 桥接、低权限裸地址空间与指定访存错误用独立模型，
不宣称它们已经过 NEMU 对照（参考配置未启用 AIA，且 PMP/地址空间策略不同）。
日志：`build/gsim/machine-focused.log`。

初始同步陷阱里程碑 `make test` 通过：Scala 22 项、两组机器核及错误注入、三组独立 IMSIC 和完整 GSIM/NEMU
回归均通过，日志 `build/gsim/machine-final.log`。原整数配置的 44 条 IPC 测量记录与
`build/gsim/ipc-before-machine.json` 完全一致；这是关闭系统指令功能的基线回归，
不代表启用 MachineCore 的性能已经测量。机器核 CSR 结果篡改和原整数核 NEMU 篡改均被测试拒绝。

`make machine-core-rtl` 已通过，独立顶层和依赖在 `build/ip/machine-core/filelist.f`；
导出日志 `build/gsim/machine-export.log`。Vivado 综合、布线、Fmax 与资源使用尚未验证。

## 异步 M 外部中断实现合同（本轮）

仅接 IMSIC M 文件的电平请求，增加 mie.MEIE 和只读来源 mip.MEIP，其余位读零、写忽略。
M 模式使用 MIE 与 MEIE 门控；较低权限标签不受 MIE 门控。已完成的队首同步异常优先。
中断在精确指令边界进入，mcause=最高位|11、mtval=0；mepc 是未退休队首 PC，空 ROB 使用前端下一 PC。
Direct 使用 BASE，Vectored 中断使用 BASE+44。中断本身不 claim IMSIC，由处理程序访问 mtopei。

请求有效时停止发起新系统事务；已获授权的 CSR 先完成并退休，然后禁止新访存发起。已有不可撤销访存允许完成并退休，已发起读及
store buffer 排空后接收。中断与退休不在同周期；使用现有逐项回滚取消队首及年轻项，不新增
全宽 RAT 恢复端口。空 ROB 可以直接进入，不依赖指令供给；此时 trap token 为无所有权观察值。
中断每次仅接收一项，进入后清 MIE；背压/恢复期间不接收，延迟受已有访存响应和回滚长度影响。
这是保守的精确中断基线，尚无固定最坏响应周期或 FPGA 频率数据。后续阶段已接 S 外部/软件/定时中断、APLIC 与机器定时器；VS 中断及完整 AIA CSR（例如 mtopi）仍待补。

中断电平属于核心时钟域；独立 IntegerCore 接入其他控制器时，集成方负责跨时钟域同步。
当前组合路径包含 IMSIC 待处理归约、使能判断、ROB 恢复仲裁和退休门控；未增加中断状态镜像，
CSR 退休后下一边界重新判断使能。系统指令退休的同周期不再退休年轻指令，避免跨过使能更新边界。
更宽提交不需要新增中断端口；恢复宽度由 `recoveryWidth` 配置，当前 BoardSocTop 为 4，
早期默认配置为 1，响应恢复开销仍随 ROB 占用及访存排空变化。

新增独立模型测试涵盖 Direct/Vectored、MEIE/MIE 分别屏蔽、MEIP 写忽略、U 权限下 MIE=0 的抢占、
MRET 后多个待处理 ID 逐次重入、停止供指且空 ROB 的 MSI、延迟 load、已提交 store buffer 排空、
分支错误路径，以及已完成同步异常与中断同时待处理的优先级。处理程序读取 mcause/mtval/mepc/mstatus，
claim 后保持 mepc 原值返回；同步异常处理程序才跳过故障指令。MSI 注入由独立测试调度，
store 的总线副作用与架构提交分别记账，陷阱时核对两者一致。新增中断测试不使用未启用 AIA 的 NEMU
作参考；原标准 CSR/同步陷阱的 NEMU 检查保留。

本轮定向验收两组配置各 31 个程序、10,815 条退休、37 次同步异常、39 次外部中断、81 次 MRET、
1,805 次 CSR 操作通过；三种随机种子各验证空 ROB、load 排空、store 排空及异常优先级。
`build/gsim/irq-focused.log` 包含两组结果及 CSR/中断原因负向注入。更新后的 RTL 导出通过，
日志 `build/gsim/irq-export.log`，仍未运行 Vivado。

最终 `make test` 全量通过：Scala 22 项、两组机器核、三组 IMSIC、所有原 GSIM/NEMU 检查及
负向注入通过，日志 `build/gsim/irq-final.log`。原整数配置 44 条 IPC 测量与
`build/gsim/ipc-before-irq.json` 完全一致；启用机器核配置的 IPC 尚未测量，不能据此推断其频率或吞吐。

新增 `WiredMachineCore` 在组合层连接 APLIC → IMSIC → CPU。APLIC 控制口仍独立暴露，
新增 MappedMachineCore 已接 CPU 数据总线地址映射；分别见 [APLIC 合同](aplic.md) 与 [映射合同](core-mmio.md)。

## FENCE 扩展验收

FENCE在ROB队首等待LSU与不可撤销写缓冲完全排空，使用现有系统事务授权边界。
按完整 IORW 屏障保守实现所有 pred/succ/fm，忽略保留 rd/rs1 字段。后续机器核还接入
FENCE.I：在队首排空后刷新取指并从后继 PC 重取；双主 TileLink RAM 执行测试见[取指路径](tilelink-fetch.md)。
两组机器核定向回归现各34个程序、10,962条提交、40次同步异常及39次外部中断、84次MRET。
新增三种背压下的80拍写响应测试，检查年轻load不能越过FENCE，另有基础FENCE的NEMU差分。
完整合同及与DMA的配合见 [DMA](dma.md)。

## 机器定时中断

新增timerInterrupt输入、mie.MTIE与只读mip.MTIP（位7）。MEIP/MTIP读值独立于mie和mstatus屏蔽。
同拍可用的MEI优先于MTI；同步异常仍优先于两者。中断原因分别为11/7，向量偏移分别44/28。
定时器和IMSIC各自提供核心时钟域的电平；timerInterrupt不通过APLIC或IMSIC领取，软件通过写mtimecmp消除。
新增18个核心定向程序覆盖MTIE/MIE屏蔽、mip写忽略、U态抢占、Direct/Vectored、空ROB、访存排空及异常/外部中断优先级。
接口和平台时基要求见 [机器定时器](machine-timer.md)。

## S 态同步异常与返回

M 模式可写 `medeleg`（支持同步异常 cause 0–9、12、13、15；机器态 ECALL 位 11 恒为零）。
仅非 M 权限、非中断且 cause 小于 64 的异常按 `medeleg` 对应位进入 S；其余仍按原 M 陷阱路径处理。
委托陷阱保存 `sepc/scause/stval`，`SPIE←SIE`、`SIE←0`、`SPP←原权限`，从 `stvec.BASE` 取指。
`SRET` 在 S 或 M 权限执行，跳至 `sepc`，权限←`SPP`，`SIE←SPIE`、`SPIE←1`、`SPP←U`。
`sstatus` 实现 SIE/SPIE/SPP、固定 RV64 UXL，VM 配置另接 SUM/MXR；`stvec` 支持
Direct/Vectored WARL 编码，同步异常均使用 BASE；另有 `sscratch`，`sepc` 按实例 IALIGN 对齐
（当前板 C 开启，低 1 位清零）。U 态访问 S CSR 产生非法指令异常。

这些 CSR 仍使用单项、ROB 队首不可撤销系统事务，本地访问下一拍完成；同时最多一个事务在途。
异常回滚沿用逐项清空，不新增并行恢复端口。`medeleg` 到目标向量的动态选择会增加陷阱入口组合路径；
此早期里程碑未测量 S 态连续 CSR 的 FPGA 吞吐。后续已加入 `satp`、Sv39 与 SUM/MXR，
见 [虚拟内存合同](virtual-memory.md)；TSR/TVM/TW 和完整特权控制仍未实现。
当前板级 OS 支持范围见 [软件移植合同](os-software-porting.md)，不能以单项 CSR 测试推导通用 OS 上板可用。

GSIM 两组机器核配置各运行三种调度种子，覆盖 MRET→SRET→U 态 ECALL→S 态处理→SRET，
以及 U 态非法读取 `sstatus`、非法 SRET 被委托到 S；`medeleg` 全位写入后的 WARL 掩码也经读回检查。
处理程序核对 `scause/stval/sepc/sstatus`（含 SIE/SPIE 保存与恢复）并修改 `sepc`。
两种 `stvec` 模式和所有提交、陷阱、重定向均与独立 C++ 模型核对。此 S 态程序尚未与 NEMU 差分；
既有 M 态程序仍保持 NEMU 检查。

2026-09-23 验收：两组配置各三段 S 态程序，合计每组 9 次委托陷阱、12 次合法 SRET；
`make test` 的 33 项 Scala、完整 GSIM/NEMU 及负向故障注入通过，日志为
`build/gsim/supervisor-final.log`；`make machine-core-rtl` 导出通过，日志为
`build/gsim/supervisor-export.log`。原裸核 44 项 IPC 测量与改动前逐项相同；重新生成的模型哈希不同。

## S 外部中断开发合同

本阶段接 IMSIC S 文件的 SEIP。M 通过 `mideleg[9]` 控制 S 外部中断目标；
`mie[9]` 与 `sie[9]` 是同一个使能位，`mip[9]` 读取 S 文件电平；
`sie[9]` 和 `sip[9]` 仅在委托后可见。
中断被委托时，M 态不接受它；S 态需 `sstatus.SIE`，U 态无需 SIE。
未委托时按机器级全局使能规则进入 M。机器外部和机器定时中断优先于 S 外部中断。
进入 S 时 `scause=中断位|9`、`stval=0`，保存 `sepc` 与 SIE/SPIE/SPP；Vectored `stvec` 使用 BASE+36。
处理程序通过 `siselect/sireg/stopei` 访问并领取 S 文件，不能访问 M 文件。

CPU 仍只有一个 ROB 队首系统事务槽和一条 IMSIC CSR 请求/响应端口；本地 CSR 请求下一拍完成，
IMSIC 访问等待原有背压响应。中断需要已发起读和写缓冲排空；精确回滚沿用逐项恢复，
不能因 S 中断引入额外的年轻指令提交或新组合 ready/valid 环。两个 IMSIC 文件的 pending 归约、
中断优先级和陷阱向量选择进入组合路径，FPGA 频率/面积尚未测量；这仍是保守吞吐基线。
VS 文件和完整 AIA 优先级 CSR 留待后续。

独立 GSIM 模型在 ROB8/PRF36 和 ROB32/PRF64 各运行 12 段程序、15 次外部中断：
委托的 SEI 在 SIE=0 时等待、打开后进入 S；未委托的 SEI 进入 M；M 与 S 文件同时待处理时先处理 MEI；
已委托 SEI 在 M 态即使 MIE=1 也不触发，SIE=0 的 S 态也继续等待，返回 U 态后进入 S。
Direct/Vectored 向量、`sie/sip` 读回、`mtopei/stopei` 领取、提交背压和 SRET/MRET 返回均与独立模型核对。
该 S 中断程序尚未与 NEMU 差分，原有 M 态及裸核 NEMU 对照继续保留。
此 S IMSIC 里程碑之后，MappedMachineCore 已加入 APLIC M 根域与 S 子域及设备委托。
IMSIC doorbell 仍是内部 MSI 通道，未映射到 CPU MMIO；当前软件集成缺口见
[寄存器手册](soc-registers.md)。独立 WiredMachineCore 与板级 MappedMachineCore 的组合边界不同。

2026-09-23 全量验收：`make test` 通过 33 项 Scala、完整 GSIM/NEMU 与故障注入；
日志 `build/gsim/supervisor-imsic-final.log`。`make machine-core-rtl wired-machine-rtl` 导出通过，
日志 `build/gsim/supervisor-imsic-export.log`。原裸核 44 项 IPC 测量逐项相同，模型重新生成后哈希变化。

### S 软件中断（SSIP）

语义依据 [RISC-V 特权架构的 supervisor interrupt 章节](https://docs.riscv.org/reference/isa/priv/supervisor.html)，
而非旧核实现。
`mideleg[1]` 控制 SSI 进入 S 还是 M。`mie[1]` 和 `sie[1]` 共用 SSIE；
`mip[1]` 是软件可写的待处理位，委托后 `sip[1]` 可读写同一位。
MEIP、SEIP、MTIP 仍只读；STIP 的写入规则见下文。已委托 SSI 在 M 态不打断执行；
S 态须打开 `sstatus.SIE`，U 态不受 SIE 屏蔽；未委托 SSI 按 M 全局使能规则处理。
M 外部、M 定时、S 外部中断保持在 SSI 前面。`scause/mcause` 写入中断位与原因码 1；
Vectored 入口为 BASE+4。清除 SSIP 后，SRET/MRET 沿用现有精确返回路径。

本地 CSR 保持一个 ROB 队首系统事务槽，完成延迟与端口数不变；中断仅增加一位
pending/enable/委托状态及组合优先选择。访存排空和恢复路径未变。FPGA Fmax、面积及
真实软件 IPC 尚未测量，本次功能变更不构成性能提升结论。
旧顺序核只有可参考的 SSIP 位定义与别名掩码；其 `mip` 写路径不完整，
因此实现依据规范重新建立，未复用旧控制逻辑。
`make gsim-machine-test` 在 ROB8/PRF36 和 ROB32/PRF64 各通过 7 段新增程序、
7 次 SSI，包括 U 态绕过 SIE 屏蔽，以及原有机器核程序和 NEMU 对照；日志为
`build/gsim/supervisor-ssip-focused.log`。本次按最小必要验证执行，未重跑全量测试或 IPC 基准。

### S 定时中断（Sstc）

独立 [Sstc 合同](sstc.md)记录时间源、STCE/TM 权限、`stimecmp`、STIP 产生和
一拍比较寄存、软件回退及频率风险。两组机器核各新增 9 段程序，覆盖 S/U 计数器权限组合、
Direct/Vectored S 定时中断与 STCE=0 时的 M 软件 STIP。专项目标
`make gsim-machine-test` 通过，日志为 `build/gsim/sstc-focused.log`；定时器 IP 的
`make gsim-timer-test` 逐拍核对 `timeValue`，日志为 `build/gsim/sstc-timer-focused.log`。
`make gsim-machine-platform-test` 的原有启动固件在两组平台配置下通过，日志为
`build/gsim/sstc-platform-focused.log`。另以 `make gsim-sstc-platform-test`
在两组机器平台运行专用 S 态固件，两个种子都核对 `mtime` 到 `time` CSR、一次 STI、
更新 `stimecmp` 后无重复中断及 SRET 返回；日志 `build/gsim/sstc-platform-boot.log`。
