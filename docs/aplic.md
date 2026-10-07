# APLIC M/S 域 MSI IP 合同

当前板级口径（2026-09-30）：BoardSocTop 已通过 MachinePlatform / MappedMachineCore
接入 M 根域和 S 子域，分别位于 `0x0c000000` / `0x0c004000`，每域16 KiB、31个源。
UART=source3，DMA=source4，其余外部源在板级绑0。DMA在当前板级有地址参数限制。
精确寄存器表、源号/身份号区别与中断链见 [MMIO 寄存器表](soc-registers.md)，
整体配置见 [SoC datasheet](soc-datasheet.md)。IMSIC的M/S页仅接内部MSI端口，
没有CPU直接读写路由；软件使用间接CSR。下文历史测试覆盖各自明确的IP/平台配置。

依据 RISC-V AIA 1.0（修订 20250312）第 4 章：
https://docs.riscv.org/reference/aia/_attachments/riscv-interrupts.pdf 。
当前实现单 hart、M 根域加一个 S 子域、MSI-only、小端 APLIC；支持 sourcecfg 的
D 位委托到子域 0，不包含多 hart APLIC 路由、多级子域或直接投递 IDC。
域有 1..1023 个连续源，默认 31 个；输入 bit0 对应源1，端口属于本时钟域，跨域同步由平台完成。

控制区默认 0x0c000000，大小16KiB，可参数化；采用通用 RegisterPort，不依赖 CPU/全局配置。
仅接受对齐32位访问和完整四字节写掩码；其他访问返回错误且无副作用。保留区读零写忽略。
domaincfg.DM=1、BE=0；IE 可写。sourcecfg 支持 Inactive/Detached/Edge1/Edge0/Level1/Level0；
保留模式和叶域 D=1 写入转换为 Inactive。Inactive 清 pending/enable/target，激活后 target 从0开始。
支持 setip/in_clrip/setie/clrie、全部 num 别名、setipnum_le/be、target 和 genmsi。
Hart/Guest Index 固定0；EIID 位宽与 IMSIC 身份容量匹配。mmsiaddrcfg[h] 固定暴露参数给定的
本域的MSI目的页地址（M域为IMSIC M页，S域实际为IMSIC S页；L=1、Hart 位宽0）。
M 根域的 smsiaddrcfg[h] 暴露 IMSIC S 页地址；
独立叶域读零写忽略。

`MappedMachineCore` 将 M 根域映射到 0x0c000000，S 子域映射到 0x0c004000。
根域仅在 sourcecfg.D=1 且子域编号为 0 时委托，子域源输入及有效掩码由根域给出；
两个域的 MSI 经保序双主仲裁送入同一 IMSIC 的 M/S 文件。UART 固定接 source3，
是否进入 S 域由固件配置。`make gsim-aia-supervisor-uart-test` 检查委托、S 文件投递、
UART RX、TOPEI 领取与撤销；`make gsim-machine-aia-s-uart-test` 在整机上从 M 态配置后
进入 S 态，检查 UART RX 导致的 S 外部中断陷阱、TOPEI 身份和接收字节。
此范围不包含 Linux 设备树/驱动验收，也没有 FPGA 时序结论。

网关在校正后的低到高转换置 pending；Level 在输入失效时清 pending，软件只能在有效电平时置位。
MSI 转发后清 pending；电平持续有效不会自动反复发送。软件 setipnum 可重触发仍有效的电平。
同周期转发/软件清除与新边沿竞争，新事件保留；Inactive 与无效 Level 电平最终优先。
sourcecfg 写入若新校正输入有效，本实现置 pending。所有状态复位0，domaincfg 常量位除外。

MMIO 两项注册响应 FIFO：空时响应一拍，下游持续接收时 II=1。
MSI 使用两项有序发送 FIFO、最多4项已发未响应事务，正常持续输出目标 II=1；满时允许恢复气泡。
仲裁选择最低源号，genmsi 优先；MSI 进入发送 FIFO 即为不可撤销转发点，清 pending 并保存目标。
后续修改屏蔽、target 或撤销电平不能撤回已排队的消息。新边沿可在旧消息背压期间再次置 pending。
对外 request 在背压下稳定；响应必须按序，写可见顺序必须与请求顺序一致。
genmsi 独立于 IE，Busy 期间写忽略，发送握手后清 Busy；其 FIFO 顺序保证不越过先前 MSI。
错误响应置独立 sticky msiError 输出，不自动重试（避免重复），由集成方处理；正常 IMSIC 写不应报错。
重置须同时复位互连/接收端，不能遗留旧响应。最多每拍转发一个源，无多计数事件队列。

时序重点为 pending/enable 归约与源选择，仲裁到 MSI 输出之间有 FIFO 寄存器；MMIO ready 只看
响应信用。最大规模面积、FPGA Fmax、跨域行为尚未实测；不把模块 II 当成 CPU IPC 或板级性能。

## 入口与组合范围

- `make gsim-aplic-test`：31/63 路独立 IP，软件状态模型、MSI 消息计数/顺序及协议检查。
- `make gsim-wired-machine-test`：默认机器核与 APLIC/IMSIC 的中断线组合测试。
- `make aplic-rtl` / `make wired-machine-rtl`：独立 APLIC 与 WiredMachineCore RTL 导出。
- `make test`：Scala 参数/展开及全部 GSIM 验收。

`WiredMachineCore` 将独立 APLIC 的 MSI 端口接到原 MachineCore 的 IMSIC，保留 APLIC 控制总线、
指令和数据接口。该独立组合的配置由测试台从外部控制口写入；新增 MappedMachineCore 已接 CPU 数据总线，
BoardSocTop 已通过 MachinePlatform 集成 MappedMachineCore；旧 FpgaPlatformTop 并非当前板级入口。
CPU访问布局现记录于 [寄存器表](soc-registers.md)，但设备树及Linux中断驱动仍需针对上述限制适配和验证。
输入仍须由平台确保时钟域和脉宽。单源与1023源的 Scala 展开检查不等于最大参数功能/频率验收。

独立测试覆盖4000轮随机配置/软件置位/输入变化，以及32位访问限制、保留字段、叶域委托拒绝、
失效源状态清零、正负边沿与电平、持续电平不重发、软件重触发、失效电平清 pending、排队身份不变、
新边沿保留、genmsi 的 Busy/IE/发送顺序、4项下游信用、错误响应和带队列复位。
模型按源逐项维护状态；对发送端使用期望 MSI 计数和顺序，不复制硬件优先编码或 FIFO 实现。
组合测试的 IRQ 期望由独立的输入注入计划产生，不使用 DUT 中断输出修正参考状态。
原标准 CSR/同步陷阱仍经过 NEMU；APLIC/AIA 部分使用独立模型，未宣称 NEMU AIA 差分覆盖。

## 定向验收

31/63路分别通过20,615/20,877个控制事务；两组各4000轮随机操作，MMIO连续256拍每拍收单，
MSI分别连续31/63拍每拍发送一项。身份错误注入被检测。独立及组合定向日志为
`build/gsim/aplic-focused.log`、`build/gsim/aplic-validation.log`。
默认 WiredMachineCore 通过31程序、10,815次退休、37次同步异常、39次外部中断、81次MRET。
独立及组合 RTL 导出成功，文件清单位于 `build/ip/aplic/filelist.f` 和
`build/ip/wired-machine/filelist.f`，尚无 Vivado 综合或时序结果。

最终 `make test` 全部通过：25项 Scala 检查、31/63路 APLIC、WiredMachineCore、原机器核、
三组 IMSIC 和完整 GSIM/NEMU/负向注入。日志 `build/gsim/aplic-final.log`。
原整数配置44条IPC记录与 `build/gsim/ipc-before-aplic.json` 完全一致；未测 WiredMachineCore IPC。

CPU 直接配置 APLIC 的新组合与验证见 [数据口映射合同](core-mmio.md)。
