# 同步机器核启动平台合同

MachinePlatform 组合 MappedMachineCore、SynchronousFetch、双32位 bank 的同步 InstructionRom
及4KiB SynchronousDataRam。ROM 位于0x80000000，默认8KiB；RAM 位于0x80010000；APLIC 位于
0x0c000000。APLIC/IMSIC 参数保持原单M域单hart配置，中断输入属于核心时钟域。

板级目标是把片上 ROM 限定为 BootROM：初始化存储/内存控制器，从 eMMC 等块设备
读取下一阶段镜像到可执行 RAM（通常是外部 DDR），然后跳转。eMMC 不是 CPU 的
直接取指存储器。本仿真平台的 RAM 仍是片上 `SyncReadMem` 模型，用于验证
ROM→RAM 取指与一致性；eMMC 控制器、DDR 控制器和板级加载链尚未接入。

复用已验证的同步存储模块：ROM/RAM 目标一拍返回、下游允许时每拍一项请求，前端最多一项在途
并用两个指令包缓冲。同步取指填充/重定向可以产生气泡，不声明裸核每拍双发射能始终维持。
程序初始化RAM，禁止依赖上电内存值。ROM初始化使用两个bank文件；GSIM用同一平台的可选编程口
装载相同固件镜像，装载期间核心、前端和存储器协议状态保持复位。编程口默认不导出。

输入中断在不同取指/退休时刻到达，测试须按实际提交顺序核对指令、GPR、内存和同步/异步陷阱。
ROM中已请求的旧路径响应不能被误用为陷阱向量/返回指令。无外部理想指令供给或软件模拟RAM响应。
ROM与RAM均仍为Chisel SyncReadMem；现已接入 [UART控制台IP](uart.md)；新增 [DMA 与双主设备仲裁](dma.md)；没有板级时钟、引脚、DDR或Vivado时序验证。

## 构建与验证入口

- `make machine-boot`：编译独立汇编入口和 RV64I/Zicsr C 固件，输出 ELF、二进制以及两个 ROM bank 的 hex 文件。
- `make gsim-machine-platform-test`：在 ROB8/PRF36 和 ROB32/PRF64 两种配置下执行固件；每种配置三组退休背压种子。
- `make machine-platform-rtl`：导出默认配置的生产 RTL，初始化文件使用上述两个 bank；没有仿真编程口。
- `make test`：包含本平台的全量 Scala/GSIM 验收。无需 Verilator。

固件先清零4KiB RAM，再运行编译后的 C 数组写入和求和（结果376），经 CPU 数据口配置 APLIC、
启用 IMSIC/M 外部中断，并等待 source3。处理程序领取中断、关闭 APLIC 投递、增加 RAM 计数，
经 MRET 返回后读回计数及 C 结果。另有非法宽度 LB/LD/SB 三个 MMIO 访问，检查精确异常与返回。
入口与处理程序是此定向测试专用，不是通用 ABI 中断上下文保存实现。

测试逐条独立解释提交指令，并核对 GPR、访存结果、CSR 和陷阱；新平台路径没有启用 NEMU 的
设备模型，原整数/机器核已有的 NEMU 回归继续保留。负向测试篡改 MMIO 读的预期值，必须被核对器拒绝。
周期计数不含 ROM 装载和复位，包含 RAM 清零、C 工作负载、配置及陷阱开销，不作为纯计算 IPC 基准。

生产 ROM 的初始化 hex 路径记录在导出的 RTL 中；移动产物时需要保留或更新路径。还没有 Vivado 综合、
布局布线和上板验证，因此块 RAM 推断、资源占用和最高频率均未验证。当前只是单 M 域启动平台，
尚非 RVA23 完整 SoC。

原RAM/外部中断固件的定向 GSIM 验证结果（UART接入后仍作为对照执行）：

| 配置 | 三次启动总提交 | 同步异常 / 外部中断 | seed0 / seed17 / seed8191 周期 |
| --- | ---: | ---: | --- |
| ROB8 / PRF36 | 5,373 | 9 / 3 | 3,564 / 4,141 / 4,115 |
| ROB32 / PRF64 | 5,376 | 9 / 3 | 3,606 / 4,205 / 4,217 |

两种配置每次启动均读回结果376及计数1；不同微架构时序导致等待循环提交数不同。
默认配置在此短启动程序上并不比小配置更快，不能据此推导通用工作负载性能。

全量 `make test` 已通过：27项Scala检查及全部GSIM/NEMU回归，原整数44条IPC记录完全不变。
验收日志：`build/gsim/machine-platform-final.log`；生产RTL清单：`build/ip/machine-platform/filelist.f`。

UART接入后默认生产固件输出 `OK\n` 并等候RX字符 `Z`，由source3中断处理程序将字符保存到RAM偏移16。
GSIM另外构建 `machine-boot-ram.bin` 保留上述原固件性能基线，两种映像共用同一平台硬件。
平台新增uartRx/uartTx引脚；外部sources位2应置0以避免与UART的source3共用输入相互影响。

`make gsim-privilege-uart-platform-test` 使用独立测试镜像验证整机特权级路径：M态配置委托和UART，
配置并锁定单指令禁执行条目、高编号TOR条目，再配置ROM、RAM和UART条目；
MPRV以U权限访问APLIC得到M态访存异常。MRET进入S态，SRET进入U态；U态两次ECALL、
越权读`sstatus`、APLIC读写及禁执行字取指分别进入S态处理程序，最后SRET返回S态。
串行线应完整输出`SU!\n`，RAM记录6次S态异常、MPRV检查及结果42。
GSIM在三个提交背压种子下逐条核对PC、寄存器、CSR、陷阱原因与目标，并独立解码串行TX；
串行预期值负向注入必须被拒绝。`make gsim-pmp-fetch-platform-test` 用同一镜像验证
双主TileLink取指不会读取禁执行字；详细范围见[PMP合同](pmp.md)。仍不提供Sv39分页
或通用S/U运行环境；默认生产ROM仍使用原UART演示镜像。

## DMA 接入

平台增加0x10001000起40字节DMA控制窗口，CPU与DMA通过8项有序标签的轮询仲裁共享原同步RAM。
DMA 地址是物理地址，进入共享数据口时 `virtualized=false`；原子仲裁器的合法 RAM 范围
跟随平台 `ramBytes` 参数，避免 8 KiB 配置上半区被错误拒绝。
2026-09-24 严格 RTL 导出曾检出 DMA 请求的该字段未赋值；明确接线后
`make machine-platform-rtl` 通过，`make gsim-machine-platform-test` 的两组配置、
DMA/原子/启动固件及负向注入通过。随后 `make gsim-atomic8-platform-test` 在同一
8 KiB 机器平台验证上半区 AMO.D、LR/SC、末尾高半字 AMO.W，以及越界 AMO 的
精确 store access fault；详见[原子访存](atomic-memory.md)。
DMA为独立RegisterPort IP，完成/错误接APLIC source4；外部sources位3也应置0。
`gsim-machine-platform-test` 另构建 `machine-boot-dma.bin`：CPU写入128个64位数，经FENCE启动1KiB DMA；
CPU同时在不相交区域做64次store/load，处理source4中断、清DMA状态、领取IMSIC并MRET，最后FENCE后逐项检查目标。
这份固件为专用测试，处理程序仅保存其已知使用约束下的寄存器，不能当作通用中断入口。
参考模型由独立提交解释器维护源数据并计算期望拷贝，不采用DUT输出生成预期数据。
平台参考不精确模拟DMA每拍状态，而是要求目标读取发生在中断后；最终写响应前禁止完成的时序由独立DMA测试覆盖。
可编程仿真配置额外导出活动计数观测信号，用于证明DMA活跃期间CPU确实获得RAM访问；生产接口不导出这些信号。
默认生产ROM仍为UART演示，DMA固件独立构建。仲裁未增加RAM物理端口；整机性能须另测，不能把DMA带宽当成CPU IPC。

## 机器定时器

平台增加同步输入timerTick和0x02000000起64KiB的寄存器路由窗口，mtimecmp位于0x02004000、mtime位于0x0200bff8。
只有这两个寄存器及其32位高半有效，其他地址报错。时基须由板级固定频率逻辑产生，独立于commitEnable；
引脚不接受未经同步的异步时钟。当前尚无time CSR、软件可发现的板级timebase频率或RTC/CDC验收。
GSIM新增 `machine-boot-timer.bin`：CPU清零RAM、运行C负载、配置mtime/mtimecmp，连续接收两次MTI并重装比较值，
最后读回中断计数2和C结果376。测试时基每四个核心周期一个tick，启动阶段固定，不读取DUT内部计数生成期望值。
mtime动态读的握手快照由独立timer测试逐拍覆盖；平台固件仅在tick开始前读取mtime，避免用退休时值冒充请求时快照。
已有UART、RAM、DMA固件继续作为性能/功能对照；生产RTL默认仍使用UART演示镜像。


## 原子内存接入

MachinePlatform现默认开启CPU的atomicMemory配置，以AtomicDataMemory/AtomicMemory替换普通共享仲裁边界。
原子请求穿过寄存器路由到RAM侧，LSU提前拒绝非RAM地址；普通流仍使用原有序端口。
CPU原子只在ROB队首、LSU/写缓冲排空后执行，年轻访存等到它退休；trap入口清除保留。
新增`machine-boot-atomic`固件同时验证原子、DMA、精确陷阱与MRET，纳入`gsim-machine-platform-test`。
生产RTL默认仍使用原UART启动镜像，但硬件已包含原子执行端；详情见[原子访存合同](atomic-memory.md)。


## 可选共享读缓存

`sharedReadCache`默认false；开启后在AtomicDataMemory与RAM之间插入CachedDataMemory/SharedReadCache。
所有CPU/DMA写都通过缓存，缓存范围内的匹配8字节扇区在写接单时失效；无旁路写一致性承诺。
缓存版五种启动固件已建立独立回归。
当前缓存已支持流水命中、多笔未命中及写读重叠，但整机负载尚未全面受益，
生产默认配置不变；[实测与限制](shared-read-cache.md)。

## 8 槽 LSU 平台对照

`make gsim-machine-platform-memory8-test` 使用 ROB32/PRF64、8 槽 LSU 和原同步 ROM/RAM，
执行 RAM、DMA、原子三类固件各三个种子。9 次启动及独立提交/内存模型检查通过；
与默认 4 槽的相同固件、种子相比，9 条周期记录逐项相同：种子 0 的 RAM/DMA/原子
分别为 3606/5440/6494 周期。报告为 `build/gsim/platform-memory8.json`，
日志为 `build/gsim/platform-memory8-focused.log`。
这只说明当前一拍、最多两项在途的同步 RAM 平台与上述固件没有利用额外 LSU 槽；
不能外推到长延迟 DDR。8 槽仍是可验证的高吞吐裸核配置，生产平台保持 4 槽，
资源与时序待 Vivado 验证。
`make machine-platform-memory8-rtl` 将同一 8 槽平台导出到
`build/ip/machine-platform-memory8/`，其中 `filelist.f` 可用于后续 FPGA 综合；
生成的 `ParallelLoadStoreUnit.sv` 包含 8 个 LSU 实例。该导出不提供资源或频率结论。

## 长延迟有序内存对照

`ramResponseDelay` 默认 0，生产平台保持原同步 RAM。非零时，RAM 内部响应进入
8 项按序返回队列，RAM 的两项内部信用可提前复用；每拍至多接收和返回各一项，
队列满时向 RAM 施加背压。`make gsim-machine-platform-latency-test` 用额外 40 拍
响应延迟比较 ROB32/PRF64 的 4/8 槽平台。专用固件先排空初始化写，再重复
16 轮、每轮 16 次独立读取，最后仍验证结果 376；三种调度种子的独立提交/内存
模型检查均通过，每种配置提交数同为 6925。
8 槽延迟配置还运行了 DMA 与原子固件，各三个种子通过；对应日志位于
`build/gsim/machine-platform-latency8/`。

| 种子 | 4 槽周期 | 8 槽周期 | 少用周期 |
| --- | ---: | ---: | ---: |
| 0 | 9209 | 7794 | 1415 |
| 17 | 9324 | 7921 | 1403 |
| 8191 | 9305 | 7888 | 1417 |

记录见 `build/gsim/platform-latency.json` 和 `build/gsim/platform-latency-focused.log`。
独立 `make gsim-delayed-ram-test` 在 2 项返回队列配置下交错读、写和错误响应，
验证背压时顺序与数据保持；96 次请求中峰值 4 项在途、203 次请求停顿、
19 次响应停顿，日志为 `build/gsim/delayed-ram-focused.log`。
这只验证有序、流水化响应与额外 LSU 槽的组合；它没有 AXI ID、DDR 控制器、
乱序响应或板上时序。现有 LSU 按请求顺序匹配响应，后续 AXI 适配器必须保持
该顺序，或在边界按 ID 重排序。40 拍模型不是生产默认配置。
