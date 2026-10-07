# 参数化页表遍历合同

状态核对：2026-10-01。当前 DDR 板级为 Sv39、512 MiB DDR aperture；片上配置仍支持 1 MiB UltraRAM。
Sv48/Sv57 是其他参数配置的能力。
板级软件使用方法见 [OS/软件移植合同](os-software-porting.md)，以下历史性能数据不代表当前大 RAM 配置。

`SvPageTableWalker(maxLevels)` 是独立的 RV64 地址转换 miss 引擎。`maxLevels=3/4/5`
分别允许最高 Sv39/Sv48/Sv57；运行时 `mode=8/9/10` 选择实际层数，`mode=0`
走 Bare。硬件使用相同的 9 位 VPN 层级、8 字节 PTE 和 44 位 PPN，不为 Sv48
复制另一套控制器。依据 [RISC-V 特权规范 1.13 的地址转换过程](https://docs.riscv.org/reference/isa/priv/supervisor.html)。

每个实例最多处理一个 miss，每层最多一笔 8 字节 PTE 读取，完成响应保持到消费。
内存请求遵循 Decoupled 背压；PTE 物理地址在握手前接受 S-mode PMP 检查，
下游须检查 PMA 和总线错误。返回的页表读错误或 PMP 拒绝是原访问类型的
access fault；PTE 格式、规范地址、权限、超页对齐及 Svade A/D 位错误是 page fault。
支持 Svpbmt 编码 0/1/2 和 Svnapot 标准化的 64 KiB 编码；保留编码报 page fault。
输出保留叶层级、Global 和 PBMT，以供后续 TLB、PMA 与缓存策略使用。

`MachinePlatform(translationService=true)` 可配置 `translationLevels=3/4/5`；通用 RAM 参数检查
允许 4 KiB 至 64 MiB 的二次幂容量，但不表示 FPGA 能容纳任意上限配置。
当前 BoardSocTop 明确选择 `translationLevels=3`，按配置接 PL DDR 或 1 MiB UltraRAM。它包含两个独立的 8 项全并行查找 TLB、页表遍历器
和可配置 4/8/16 项非叶 PTE 缓存，两端现可分别接 CPU I/D 侧；未接入的端口仍可供
独立服务测试。两个 PTE 读取端按轮转仲裁，
再与 CPU/DMA 数据通路仲裁，
共用原有有序 TileLink RAM 主端。TLB 命中可在请求当拍返回，未命中各自最多
一笔遍历在途；超页和 64 KiB Svnapot 命中重建物理页内偏移。
缓存键含 MODE、根 PPN、ASID、虚页、访问类型、有效特权及 SUM/MXR，
避免用一次读取授权后续写入。页表缓存按 PTE 物理地址索引，仅保存格式合法的
非叶项；遍历器每次复用前仍执行 PMP 检查。`flush` 同时清空 TLB 和页表缓存，
调用者须先排空在途请求；页表修改后应按 `SFENCE.VMA` 的顺序要求触发失效。
可选 RAM 编程口仅在平台 hold 时写入，用于同步存储镜像装载。

MachinePlatform 的可选 VM 控制现从机器核提供 `satp`、`SUM/MXR`、取指/数据
有效特权，以及全局 `SFENCE.VMA`。`satp` 实现 Bare 和配置上限内的 Sv39/Sv48/Sv57，
不支持的 MODE 写入保持原值；写 `satp` 不隐式冲刷 TLB。
ROB 队首的 `SFENCE.VMA` 等待旧数据请求及前端取指排空，再等两路页表服务空闲，
统一失效 TLB 和非叶 PTE 缓存。PMP 权限更新也走此失效边界。
当前实现对 rs1/rs2 采用允许的保守全局失效，不做定址或定 ASID 失效。

可选 `coreDataTranslation=true` 已把 LSU 请求接到 DTLB：虚拟地址先翻译，再按
物理地址进行 PMP 检查及 APLIC/MMIO、TileLink RAM 路由。翻译产生的 page fault
与 PTE 读取/物理访问产生的 access fault 分别进入 LSU 的精确异常路径；故障请求
不发出物理数据访问。译址队列和响应归属队列各有 8 项，TLB 命中可当拍入队，
单路 miss 会阻塞新的译址，但已译址的请求仍可继续向物理端发出并等待响应。
StoreBuffer 不按未翻译的地址提前确认写入，原子访问的物理 RAM 范围在译址后检查。

可选 `staged-fabric` 在 `DataTranslationAdapter` 的 PMP/原子范围检查之后增加 2 项
非直通 checked-request FIFO，捕获完整物理请求、fault 和 pageFault 决策，隔离后续
MMIO/L1/仲裁的 ready 反馈。正常请求增加一拍，可连续每拍出入；故障占位也经过同一
FIFO 和原有 8 项响应 owner，绝不发出物理访问，不能被后面的正常响应越过。
适配器 `idle` 包括新增 FIFO；LSU/StoreBuffer 仍等待实际回复，PMP 更新、FENCE 和
SFENCE 的既有排空边界不以“请求已进缓冲”当作访问已完成。默认配置不增加此级。

可选 `coreInstructionTranslation=true` 把前端双指令包接到 I-TLB。包中两个 32 位指令
同页时只译址一次；跨 4 KiB 页时分别译址、分别做物理 PMP 检查，并在物理页不连续时
分别取指。取指 page fault 与 access fault 各有独立侧带位，随包进入 ROB 的精确异常路径。
`SFENCE.VMA` 排空等待前端和译址适配器空闲。

可选 `coherentLineCache=true` 现在可与 `translationService=true`、
`coreDataTranslation=true` 同时启用。CPU 数据请求先译成物理地址再查 L1，
因此不同虚拟地址映射同一物理行时共用缓存标签。页表遍历请求经 home 的
非 CPU 通道进入，在读取 CPU 持有的脏 PTE 行前先 Probe 并写回。
Svpbmt 的 NC/IO 数据请求绕过 L1；若目标物理行已驻留，先 Release，
再向物理总线发出请求。这里的 IO 仅表示缓存旁路，尚未实现完整 PMA/PBMT
访问顺序和副作用约束。

**这还不是整核虚拟内存合规声明。** 核级固件已验证 M-mode 取指加 MPRV=S
数据访问，以及切入 S-mode 后从虚拟地址取指和读取虚拟数据页、跨页取指包中的
单字成功与次页页故障。带 L1 的 MPRV=S 用例还验证了脏 PTE 探测、虚拟地址 AMO、
PBMT=NC 物理别名和 128 次热 load/store 回环。
完整 S/U 软件执行及译址后的 PMA/PBMT 策略仍待扩展验证。
虚拟访存目前在 ROB 队首执行，以避免未翻译地址的错误别名/写入确认；这是一条
保守的性能基线，不能据此宣称高性能虚拟内存或 FPGA 频率。

性能边界：每路 TLB 命中吞吐目标为每拍一笔；每路最多一个 miss，两路可并发。
当前 walker 在 PMP 检查后增加一项非直通寄存队列，每次 PTE 读取增加一拍，TLB 命中路径不变。
下列 15–16/27/10/12 拍是该队列和板级三拍 UltraRAM 接入之前的历史服务测量：
实际 miss 延迟由 3/4/5 次 PTE 读取的内存延迟及仲裁决定。GSIM 平台中
一笔 Sv39 和一笔 Sv48 miss 并发完成约 15–16 拍（受核取指阶段影响），
串行完成合计 27 拍，
共读取 7 条 PTE；同页命中请求当拍返回。同一区域另一页的 Sv39 miss
复用两条非叶 PTE，仅访问一次页表 RAM，用 10 拍完成；失效后重新访问三次，
同深度遍历用 12 拍完成。
此数据仅证明服务并发与页表缓存能力，不是 CPU IPC 或 FPGA Fmax。
TLB/PTE 缓存、仲裁和 RAM 的面积/布线/频率随配置改变；此前小 RAM 的服务周期不能预测
当前 1 MiB UltraRAM 板级性能。Vivado 结果只适用于报告对应的 RTL 和约束。

验证：`make gsim-sv-walker-test` 以独立 C++ 页表映像检查 Sv39/Sv48/Sv57
的各级叶子、超页地址拼接、规范地址、64 KiB NAPOT、PBMT、Svade、
SUM/MXR、Global、PMP/内存错误及请求和完成背压。当前独立用例 42 项通过；
`maxLevels=3/4/5` 均已单独 elaboration。
`make gsim-soc-translation-test` 用真实 MachinePlatform、双主 TileLink 与
同步 RAM 运行 PMP、`satp`、`SUM/MXR`、`SFENCE.VMA` 固件，然后检查
CPU 发起的失效、并发 Sv39/Sv48、Sv57、TLB 命中和失效、
非叶 PTE 复用与失效、非规范地址、2 MiB 超页与 64 KiB NAPOT 的跨 4 KiB 命中。
`make gsim-vm-data-platform-test` 在真实机器平台运行 M-mode 固件，用 MPRV=S
分别访问有效和缺页的 Sv39 地址，检查 load/store/load 回环、精确 load page fault 的
`mcause/mtval`、PTE RAM 读取次数以及缺页时没有物理数据请求。
`make gsim-vm-data-coherent-platform-test` 在相同固件与页表上启用写回 L1，
检查脏 PTE 的 ProbeAckData、PBMT 别名的 ReleaseData、虚拟地址 AMO 以及
热循环的结果。同一 128 次循环在第一次精确异常前提交 675 条指令：
直连 2225 拍、IPC 0.3034；带 L1 2167 拍、IPC 0.3115。
这个数字包含启动、页表遍历与冷缺失，不能代表稳态峰值吞吐。
`make gsim-vm-instruction-platform-test` 切入 S-mode 虚拟地址，从映射页取指并
读取映射数据页，执行页末指令，检查跨页双指令包的下一页缺页产生精确
instruction page fault，
同时观察 I-TLB 命中与 TileLink PTE 读取。
`make gsim-vm-instruction-coherent-platform-test` 用相同取指用例检查两者同时启用。
