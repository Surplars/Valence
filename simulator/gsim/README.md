# 新乱序核的 GSIM 仿真入口

此目录运行独立于旧顺序核的 Chisel 模型。唯一受支持的仿真后端是 GSIM；Verilator 及旧 emu 入口已退役。
默认裸核测试可运行固定 32 位编码的整数、条件分支、调用/返回及 load/store 程序，包含编译的 C 栈/数组程序，并按提交顺序与 NEMU 比较。可选 RV64C 平台已运行混合 16/32 位固件和 CoreMark 工作负载；其覆盖范围及性能口径见 [RV64C 与 CoreMark](../../docs/rv64c-coremark.md)。
**LSU 默认四槽，普通 RAM load 可并行；显式普通 RAM 可提前 load，store 与其他地址读取只在队首执行，GSIM RAM 写已接四项不可撤销缓冲。独立 MachineCore 配置已支持基础 M/S CSR、同步陷阱委托、MRET/SRET 和 M/S IMSIC 文件桥接；已接 M/S 外部中断、SSI 和 Sstc 定时中断；MachinePlatform 另有默认关闭的共享读缓存，尚未完成完整 RV64I/RVA23 或生产 SoC。**

## 目录

`harness/` 存放 C++ 驱动与独立模型，`payloads/` 存放当前指令子集的汇编测试与链接脚本，
`config/` 存放工具链/参考版本锁和 NEMU 配置；`run.py` 与 `reference.py` 为统一入口。
旧仿真资产集中于 `../../legacy/simulator`，完整结构见 [目录说明](../../docs/layout.md)。

## 使用

`make coremark-setup` 获取固定版本的官方源码；`make gsim-coremark` 编译并运行
RV64IMAC+Zba/Zbb/Zbs 的 2 KiB CoreMark 工作负载，输出 guest 周期和整体 IPC。
仿真缺少实测硬件频率，结果不是可发布的 CoreMark 分数。
报告还按零提交周期的 ROB 队首状态互斥分类，并用固定 ELF 的符号与反汇编注释
热点 PC；分类口径与 A/B 数据见[RV64C 与 CoreMark](../../docs/rv64c-coremark.md)。
较早的 MULW 三拍及已就绪 load 旁路/重叠回放版本单次迭代为 305,375 周期、IPC 1.0570；
`make gsim-coremark-cache`、`make gsim-coremark-delay12` 和
`make gsim-coremark-cache-delay12` 用同一二进制比较 128 行缓存与人工 12 拍 RAM 延迟，
四组结果见[共享读缓存](../../docs/shared-read-cache.md)。
`python3 simulator/gsim/run.py coremark-tune --issue-width 4`
使用同一裸机镜像生成独立的宽度配置报告；还可调整 `--rob`、`--physical`、
`--memory-entries`、`--store-buffer-entries`。报告写入
`build/gsim/coremark-n4-c4-r32-p64-m4-s4-x4.json` 等带参数的文件。
针对 2 路 load 延迟，可用
`python3 simulator/gsim/run.py coremark-tune --flow-tilelink-response`
对比最老 TileLink 数据响应直通配置；直通桥的背压/乱序检查为
`make gsim-tilelink-bridge-flow-test`，RAM、DMA 和原子平台检查为
`make gsim-tilelink-platform-flow-test`。周期对照与 FPGA 时序边界见
[RV64C 与 CoreMark](../../docs/rv64c-coremark.md)。
独立乘法单元与整核 NEMU 验证入口分别为 `make gsim-pipelined-mul-test` 和
`make gsim-core-test`。外部写入下的读序合同与验证见
[已就绪 load 旁路](../../docs/load-ready-replay.md)。
`make gsim-backend-recovery4-test` 用独立 ROB 记分板验证每周期回滚 4 项的配置，
覆盖寄存器映射恢复、释放与过期完成过滤。
`make gsim-atomic-memory8-test` 验证 8 KiB 原子边界的上半区和末端，
`make gsim-atomic8-platform-test` 验证同一范围经过 CPU、原子边界及 TileLink RAM 的行为；
默认 4 KiB 对照仍用 `make gsim-atomic-test`。结果与限制见[原子访存](../../docs/atomic-memory.md)。

8 槽平台对照：`make gsim-machine-platform-memory8-test` 运行同步 RAM、DMA 和原子固件
各三个种子，结果见 `build/gsim/platform-memory8.json`；
`make machine-platform-memory8-rtl` 导出独立的 8 槽平台 RTL 和 `filelist.f`，
供后续 Vivado 资源及时序对比。默认平台仍为 4 槽。
`make gsim-machine-platform-latency-test` 用默认关闭的 40 拍有序 RAM 响应模型和
排空写入后的独立读取固件，对比 4/8 槽；三个种子均通过独立模型，
8 槽还覆盖 DMA 与原子固件各三个种子，
结果见 `build/gsim/platform-latency.json`，限制见[机器平台](../../docs/machine-platform.md)。
`make gsim-delayed-ram-test` 独立检查该返回队列满载背压、读写顺序和错误响应。
`make gsim-tilelink-bridge-test` 独立验证新核 TileLink A/D 桥的 8 笔并发读、
通用串行写、单 RAM 有序多笔写及混合读写、同 bank 写流水化、乱序 D 重排、读错误、背压与负向数据注入；
`make tilelink-bridge-rtl` 导出独立通用 RTL。
`make gsim-tilelink-platform-test` 验证可选同步机器平台的 RAM、DMA 与原子启动；
`make tilelink-machine-platform-rtl` 导出该可选配置。默认平台仍直连 RAM，
合同见[TileLink 内存桥](../../docs/tilelink-memory-bridge.md)。
`make gsim-tilelink-router-test` 独立验证双窗口请求路由、source 归属、
跨窗口乱序 D 和未映射错误；`make gsim-tilelink-split-platform-test`
使用跨两个 RAM bank 的启动镜像验收片上接线，详见[TileLink 路由](../../docs/tilelink-router.md)。
`make gsim-tilelink-arbiter-test` 独立验证双主 A 仲裁、source 命名空间、
乱序 D 返回、背压和负向注入；`make tilelink-arbiter-rtl` 导出该 IP，
边界见[双主 TileLink 仲裁](../../docs/tilelink-arbiter.md)。
`make gsim-tilelink-fetch-test gsim-tilelink-crossbar-test` 验证取指包转换、
只读 ROM beat 复用/复位、RAM 不复用、denied/corrupt 的逐 word 错误位及双窗口并发；
crossbar 测试还覆盖 64 字节 A/D burst 不交错与未映射 burst 的完整错误响应，
见 [burst 与一致性边界](../../docs/tilelink-burst-coherence.md)。
`make gsim-tilelink-burst-ram-test` 验证单 RAM manager 的 64 字节
Get/PutFullData、完整错误响应及单拍访问回退；现有 CPU/DMA 固件仍发单拍请求。
`make gsim-tilelink-line-fill-test` 验证 4 槽缓存行 Get 请求端的乱序 D、
背压、错误与槽位复用，并验证连接单 RAM manager 后的整行数据和越界错误；
`make tilelink-line-fill-rtl` 导出独立缓存行请求端 RTL。
`make gsim-tilelink-line-write-test` 验证 64 字节写主端的 8-beat A 锁定、乱序 D 确认，
以及可复用读写组合 IP 经单 RAM manager 的整行写后读回与并发仲裁；
`make tilelink-line-write-rtl tilelink-line-transfer-rtl` 导出独立写端和组合 IP RTL。
`make gsim-tilelink-line-acquire-test gsim-tilelink-line-probe-test` 分别验证
TL-C 的 AcquireBlock/AcquirePerm→GrantData/Grant→GrantAck 与
ProbeBlock→ProbeAck/ProbeAckData 64 字节事务端点，包括乱序、多拍背压和非法交错断言；
`make tilelink-line-acquire-rtl tilelink-line-probe-rtl` 导出独立 RTL。
`make gsim-tilelink-coherent-platform-test` 验证可选单 CPU 写回缓存的 UART、
CPU 脏行与 DMA 读写探测及原子固件；`make gsim-tilelink-coherent-fencei-test`
用 RAM 自修改代码验证脏行写回、`FENCE.I` 失效与后续取指；
`make gsim-instruction-cache-test` 验证压缩指令前端的多项取指缓存和显式失效。
`make gsim-instruction-line-cache-test` 验证物理侧两路整行 I-cache 的 TL 突发填充、
同组替换、失效和 PMP 精确回退。
`make gsim-tilelink-coherent-evict-test`
以 16 行容量覆盖 ReleaseData 脏逐出；`make gsim-coremark-coherent
gsim-coremark-coherent-delay12` 与对应直连 CoreMark 命令比较 IPC，
`make coherent-platform-rtl` 导出组合平台 RTL。该模式仍限单 CPU、单笔 home 事务。
home 的无探测 Acquire 当拍启动整行读取已通过单/双 hart 定向检查；
固定 CoreMark 结果与未验证的 FPGA 时序见[性能记录](../../docs/performance-status.md)。
`make gsim-tilelink-two-hart-coherent-test` 单独验证两个私有 L1 的 T 权限迁移、
脏数据探测、无缓存访问和同时请求；这不是双 hart CPU 启动测试。
单 hart ROB 队首完成当拍退休由 `make gsim-backend-test gsim-core-test`
覆盖令牌/异常/恢复及 NEMU 差分；固定 CoreMark 镜像的对照与频率限制见
[性能记录](../../docs/performance-status.md)。
写回 L1 连续读命中与两项响应背压由 `make gsim-tilelink-two-hart-coherent-test`
中的独立缓存代理用例覆盖；整机 UART/DMA/原子与脏逐出分别用上述两个
一致性平台目标检查。单 hart CoreMark 周期对照见同一性能记录。
LSU start 当拍发请求与零延迟响应、背压和恢复由
`make gsim-integer-test gsim-core-test` 的独立模型/NEMU 检查，
机器级访存由 `make gsim-tilelink-coherent-platform-test` 检查；
CoreMark 与 FPGA 时序边界见[性能记录](../../docs/performance-status.md)。
`make gsim-vm-data-coherent-platform-test gsim-vm-instruction-coherent-platform-test`
验证写回 L1 与 Sv39 数据/指令译址共存，包含脏 PTE 探测、虚拟 AMO、
PBMT=NC 别名和精确异常。热虚拟访存用例的 IPC 与限制见
[虚拟内存合同](../../docs/virtual-memory.md)。
`make gsim-tilelink-dual-platform-test gsim-tilelink-dual-split-platform-test`
运行可选双主平台的 RAM、DMA、原子固件、精确取指访问异常及
FENCE.I 后从 RAM 执行指令，
详见[TileLink 取指路径](../../docs/tilelink-fetch.md)。
`make gsim-tilelink-dual-latency-test` 用同一双主路径和 40 拍 RAM 响应延迟比较
4/8 槽 LSU，结果见 `build/gsim/tilelink-dual-latency.json`。
`make tilelink-fetch-rtl tilelink-rom-adapter-rtl tilelink-crossbar-rtl` 导出三块独立 RTL。
`make gsim-axi-bridge-test` 验证新有序 AXI4 内存桥的 8 笔读取、独立 AW/W 背压、
4 笔写在途、混合请求顺序及读值/写错误负向注入；
`make axi-bridge-rtl axi-bridge32-rtl` 导出两种地址宽度的独立 RTL。
桥尚未接入生产平台，合同见[AXI4 内存桥](../../docs/axi4-memory-bridge.md)。
make gsim-tilelink-axi4-bridge-test 验证独立 TL-UL→AXI4 组合桥的
64/32 位地址版本各 105 笔混合事务、8 笔读和 4 笔写在途、错误和背压；
另有 256 笔写的 1/4 槽完成时间对照，报告在 build/gsim/tilelink-axi4-write-stream.json；
make tilelink-axi4-bridge-rtl 和 make tilelink-axi4-bridge32-rtl 导出 RTL。
合同见[TileLink→AXI4 内存边界](../../docs/tilelink-axi4-bridge.md)。
项目只实现 AXI4 外部边界；Zynq-7000 PS HP 是 AXI3，使用时需由 Vivado IP 转换。
旧 SoC 的 TileLink 总线和新平台默认的直连数据口没有被 AXI4 桥替换，
拓扑选择见[模块化 SoC](../../docs/modular-soc.md)。

2026-09-23 Sstc M/S 路径：平台 `mtime` 送入机器核，增加 `time`、`stimecmp`、
`menvcfg.STCE`、`mcounteren/scounteren.TM`、STIE/STIP 与委托。比较结果寄存一拍；
STCE=0 时 M 仍可写 `mip.STIP`。两组机器核各新增 9 段定向程序，
`make gsim-machine-test gsim-timer-test gsim-machine-platform-test` 通过；日志为
`build/gsim/sstc-focused.log`、`build/gsim/sstc-timer-focused.log`、
`build/gsim/sstc-platform-focused.log`。专用 `make gsim-sstc-platform-test` 又以
两组机器平台以同步 `mtime` 驱动 S 态固件：两个调度种子均在第 5 次 tick 收到一次 STI，
处理程序核对 `time` CSR、更新 `stimecmp` 并从 SRET 返回，无重复中断；
日志为 `build/gsim/sstc-platform-boot.log`；完整平台回归也运行此镜像。
同一模型还通过原 RAM 启动镜像，
见 `build/gsim/sstc-platform/ram-baseline.log`；
功能与时序边界见 [Sstc 合同](../../docs/sstc.md)。

2026-09-23 SSIP 闭环：`mideleg[1]`、`mie/sie[1]` 和软件可写的 `mip/sip[1]`
接入原有精确中断路径；GSIM 机器核两组配置各新增 7 段定向程序，覆盖 SIE 屏蔽、
委托/未委托、S/U 接收、Direct/Vectored、CSR 清除及 SRET/MRET。仅运行聚焦的
`make gsim-machine-test`，记录于 `build/gsim/supervisor-ssip-focused.log`；
其他完整回归和 FPGA 综合/时序没有因本次变更重跑。设计合同见
[机器核合同](../../docs/machine-core.md)。

2026-09-23 S 文件外部中断闭环：M/S IMSIC 文件均接入机器核。`mideleg[9]`、
`mie/sie/sip` 的 SEI 位及 `siselect/sireg/stopei` 已支持；GSIM 两组机器核各新增
12 段定向程序、15 次中断，覆盖委托/未委托、SIE 屏蔽、M/S 同时待处理优先级、
M/S/U 权限下的入口和返回、Direct/Vectored、S 文件领取与背压。
当时平台 APLIC 仍仅 M 域；现已接入 S 子域及 UART 委托，见下文定向入口。
`make test` 的 33 项 Scala 与完整 GSIM/NEMU、负向注入通过；`make machine-core-rtl wired-machine-rtl`
导出通过，原裸核 44 项 IPC 测量逐项相同。日志：`build/gsim/supervisor-imsic-final.log`、
`build/gsim/supervisor-imsic-export.log`；功能边界见 [机器核合同](../../docs/machine-core.md)。

2026-09-23 有限 S 态同步陷阱里程碑：`make test` 与 `make machine-core-rtl` 通过。
两组机器核各新增三段程序，覆盖 MRET/SRET、U 态 ECALL 与非法 S CSR/SRET 委托、
`medeleg` WARL 读回及 SIE/SPIE 往返；每组 9 次委托陷阱、12 次合法 SRET。
S 态程序使用独立 C++ 模型，既有 M 态和裸核 NEMU 差分保留；33 项 Scala、完整 GSIM
与负向注入通过。原裸核 44 项 IPC 测量逐项不变，模型哈希因重新生成而变化。
日志：`build/gsim/supervisor-final.log`、`build/gsim/supervisor-export.log`。
详细能力边界见 [机器核合同](../../docs/machine-core.md)。

最新验收已包含可选共享读缓存、CPU原子访存、DMA共享边界、机器定时器及MTIP：Scala 33 项及 GSIM 全量通过；原整数裸核每组配置 278 个程序、380,406 条提交，
访存与寄存器均经过独立模型/NEMU 检查。新增确定性 IPC 基准和可编译 C 程序，
接口、限制、测量结果见 [裸核 IPC](../../docs/bare-core-ipc.md)，日志为 `build/gsim/load-overlap-final.log`；包含同步 ROM/RAM 执行平台、顺序预取与投机 store 地址消歧检查。
机器核两组配置保留原34个程序，另各增18个定时中断程序，CSR/中断负向注入通过；当前44条IPC相对定时器接入前逐项不变；启用系统指令的配置尚未测量IPC。详见 [机器核合同](../../docs/machine-core.md)。

2026-09-23 缓存命中流水化验收：`make test cached-platform-rtl`通过，日志`build/gsim/cache-pipeline-final.log`。
33项Scala、完整GSIM/NEMU、19项故障注入及60次平台启动通过；44项IPC、30次默认平台启动和无缓存CPU对照逐项不变。
命中每拍一项，12拍重用读由首版786降至277周期，未命中仍阻塞，缓存默认关闭；RTL已更新导出。

2026-09-23 可选共享读缓存最终验收：`make test`通过，日志`build/gsim/cache-final.log`；
四种原子/缓存整核配置各88个程序及60次平台启动通过，原44项IPC和默认平台30次启动周期逐项不变。
缓存默认关闭：长延迟重复读取有收益，流式读明显退化，详见[共享读缓存](../../docs/shared-read-cache.md)。

2026-09-18 公共 ISA 拆分后 `make test` 全部通过：Scala 14 项、完整 GSIM 回归及 NEMU 故障注入。
译码/提交覆盖与双宽吞吐保持原结果，记录见 [ISA 复用验收](../../docs/isa-reuse.md)。

2026-09-18 GSIM-only 入口验证：活动 Scala 配置/展开检查 13 项全部通过（此次 Mill 命令耗时 13 秒），
GSIM smoke 通过。两项均在 PATH 前置禁用 Verilator 的拦截脚本下运行；活动目录不含 ChiselSim 调用。
旧仿真 Make 目标已撤下，历史测试/驱动原样归档，尚未迁移的覆盖率不作通过声明。
日志为 `build/gsim/gsim-only-scala.log` 和 `build/gsim/gsim-only-smoke.log`。

依赖：现有 Mill/Java 环境、Python 3、Git、Make、GMP 开发库、Flex、Bison、Clang 19 或更新版本。
程序差分另需 GCC/G++、zlib 开发库、`riscv64-unknown-elf-gcc/objcopy` 及本仓库固定 NEMU 提交和锁定资源文件。
工具链版本固定在 `config/toolchain.json`，首次下载需要网络：

```bash
make gsim-setup
make gsim-test
```

`make test` / `make regress` 先运行活动 Scala 配置/展开检查，再运行完整 GSIM 回归。
`mill -i IonSoC.test` 不再发现已归档的旧 ChiselSim 测试；这不表示这些旧用例已迁移到 GSIM。

分别运行：

```bash
make gsim-smoke
make gsim-cache-test # 独立共享读缓存
make gsim-cache-core-test # 相同CPU开关缓存的NEMU/原子/DMA及性能对照
make gsim-cache-platform-test # 四种平台配置与五种启动固件
make gsim-atomic-core-test # CPU+原子边界，指令/排序/异常/DMA及NEMU子集
make gsim-atomic-test # 独立LR/SC与AMO共享内存IP
make gsim-timer-test # mtime/mtimecmp 逐拍模型、访问宽度、背压和回绕
make gsim-dma-test # 独立 DMA：多项在途、背压、错误排空及完成时序
make gsim-shared-data-test # CPU/DMA 内存仲裁：保序、公平性与背压
make gsim-machine-test # M/S CSR、同步异常委托、外部/软件/定时中断与 IMSIC 文件桥接
make gsim-sstc-platform-test # 平台 mtime→stimecmp→S 态处理程序的固件闭环
make gsim-router-test # CPU 数据口 / 寄存器接口与响应保序
make gsim-mapped-machine-test # 程序直接配置 APLIC 并处理中断
make gsim-aplic-test # 独立 M 域 APLIC
make gsim-aia-supervisor-uart-test # M 根域委托 UART 到 S APLIC/IMSIC
make gsim-machine-aia-s-uart-test # 整机 S 态 UART 外部中断与 TOPEI
make gsim-wired-machine-test # 中断线 → APLIC → IMSIC → CPU
make gsim-imsic-test # 独立 AIA IMSIC IP，不是整核中断验收
make gsim-backend-test
make gsim-integer-test
make gsim-predictor-test # 计数器饱和、索引冲突、同周期双更新
make gsim-core-test
make gsim-ipc           # 只跑默认配置 IPC，输出 build/gsim/ipc.json 与 ipc.csv
make gsim-core-memory8-test # 8 槽 LSU 整核差分及 IPC，输出 ipc-memory8.json 与 ipc-memory8.csv
make gsim-machine-platform-memory8-test # 8 槽同步平台 RAM/DMA/原子启动对照
```

`GSIM_CXX` 可指定 Clang 路径，`GSIM_BUILD_JOBS` 控制 GSIM 构建并发，默认 4。
构建工具链源码位于被忽略的 `simulator/build/gsim-src`。脚本要求源码提交与锁文件一致，
且没有已跟踪文件的修改；不下载上游示例 CPU 和其子模块，不修改系统安装。

生成的 CHIRRTL、C++、测试二进制和日志位于被忽略的 `build/gsim/<case>`。
每次执行都会重新生成模型，不依赖旧的生成结果。`toolchain-used.json` 记录实际编译器及 GSIM 提交。
生成、编译或运行失败时返回非零状态，并打印对应日志末尾。

## 已实现的硬件边界

- `src/main/scala/core/ooo/OooParams.scala`：后端参数和边界约束。
- `BackendTypes.scala`：重命名请求、物理映射、完成、提交、恢复及异常接口。
- `RenameRob.scala`：投机/已提交映射、物理寄存器身份分配、ROB、提交和反向回滚。
- `IntegerAlu.scala`：64 位加减、逻辑、移位、有符号/无符号比较及加减/移位 W 变体。
- `StoreBuffer.scala`：显式保证写成功 RAM 的不可撤销队首 store 缓冲，四项 FIFO、逐字节转发、按序排空。
- `LoadStoreUnit.scala`：单在途 valid/ready 数据口、掩码/扩展、对齐与访问错误；仅执行 ROB 头部许可的访问。
- `BranchUnit.scala`：六种条件分支、JAL/JALR、链接地址及 IALIGN=32 的目标对齐检查。
- `IntegerBackend.scala`：PRF 数据/就绪表、按 ROB 索引的保留槽、最老就绪选择、整数执行与提交连接。
- `IntegerDecode.scala`：独立整数机器指令译码，严格检查 opcode/funct 字段。
- `BranchPredictor.scala`：64 项两位饱和条件分支预测，双查询、按退休顺序双更新，同索引更新顺序折叠。
- `IntegerCore.scala`：条件分支方向预测、双路供指、预测跳转处截断 packet、执行校正、精确异常停止接口。
  JAL 和相邻 AUIPC→JALR 提前计算目标，普通间接跳转及返回仍顺序预测，无 BTB/RAS。

新核译码共享 `soc.isa` 的 opcode/funct 定义，异常结果共享 MCause 常量；
旧流水线控制表已移至 `core/pipeline/decode`，不参与新核译码。
GSIM C++ 独立指令表与 NEMU 不由 Scala 常量生成。复用范围见 [公共 ISA 说明](../../docs/isa-reuse.md)。

默认配置为双宽、32 项 ROB、64 个整数物理寄存器身份、64 位分配标识。
重命名、提交、完成端口分别由 `renameWidth`、`commitWidth`、`completionWidth` 配置，互不绑定。
`RenameRob` 单独维护寄存器身份和生命周期；`IntegerBackend` 加入数据与执行，已接四槽 LSU；LSU 完成优先占用完成端口 0，其余端口仍可执行整数指令。
LSU 启动与 ALU 共用 `completionWidth` 条/周期的发射预算（默认 2），禁止独立的第三条发射。
`OooParams` 的 speculativeRamBase/speculativeRamBytes 显式声明无副作用 RAM，默认不开放；
GSIM 平台开放 0x80010000 起 4 KiB。取消读取保持请求稳定、排空响应且不能写回。
LSU 完成旧结果时可锁存下一笔独立访存；默认四槽允许普通 RAM load 并行。
外部仍是一个请求/响应端口、无事务 ID，必须严格按请求握手顺序返回响应；
请求选择在背压下锁定，响应 owner FIFO 路由到原槽，取消事务排空后才释放槽。
store 与区间外读取串行化；`memory_entries`/`max_outstanding` 分别报告槽容量和外部峰值在途数。
1/2 槽目前只有展开检查；4 槽为默认 GSIM 行为配置，8 槽已通过独立整核/NEMU
程序和 26 条 IPC 基准。运行 `make gsim-core-memory8-test`，报告单独写入
`build/gsim/ipc-memory8.json`，不会覆盖默认 4 槽报告；资源/Fmax 尚待 Vivado。
旧非投机访存的保护独立保留至退休，新 RAM load 的启动或错误不能提前解除它。
ROB 索引投机 SQ 保存非队首 store 的准备位、地址和数据，准备使用整数发射槽且不报告架构完成。
分配/退休/恢复清除准备项，外部写仍只在队首获准；队首未准备的 store 保留直接执行路径。
最老 pending load 可越过已准备、对齐且普通 RAM 范围内的不相交较老 store；未知地址、
重叠或非 RAM store 仍阻塞。当前没有对未知地址的推测与重放，也未实现紧凑独立 SQ。
成功 store 完成时可向完整覆盖的下一笔 RAM load 转发数据，避免一次外部读请求；
部分覆盖、不同 beat、失败 store 和非普通 RAM 不转发。该完成窗口转发保留；另有下述不可撤销 store buffer。
GSIM 裸核显式启用 `bufferedRamStores`，普通 `OooParams` 默认关闭。启用要求上述 RAM 区域的对齐写
永不返回错误；区域外写仍等待真实响应并支持精确错误。队首 store 入缓冲后即可完成并退休，
缓冲写按序发出，真实响应后释放项；分支恢复和年轻异常不能清除缓冲。
缓冲内逐字节选择最新 store，全覆盖的 load 可直接得到数据；部分覆盖或不同地址先等排空。
MMIO 也等待排空。未实现 cache、权限检查或热复位时排空协议，不可默认用于任意 SoC RAM。
`storeBufferEntries` 可配 1/2/4/8；本轮行为测试为 4 项，其余容量只做展开检查。
独立验证入口为 `make gsim-store-buffer-test`，包含写成功契约错误注入。
IPC 报告 `forwarded_loads` 计数有转发启动的周期（两条路径 OR），可能包含后来取消的读取；
`loads` 仍计外部读请求，二者均不等于退休 load 数。
ROB 暂存完成数据供提交验证；整数 PRF 写入和就绪置位服从 `completionAccepted`，非法操作不写 PRF。

输入分配采用连续前缀，`dispatchReady` 表示下游能接受该周期整个获准前缀，
`renamed.valid` 是已接受事件而非可独立反压的候选。未来调度队列必须与这个握手契约一致。
同周期提交释放的寄存器和 ROB 槽位到下一周期才参与分配，不构造提交到重命名的快速组合路径。
分支恢复保留边界指令，异常恢复可以包含边界；恢复期间每周期撤销一项，允许新的更老恢复边界。

分配标识不静默回绕：耗尽后阻止新分配，已有指令仍可完成和提交。
默认 64 位；8 位测试配置专门验证耗尽。重新复位前，外部执行/访存生产者必须一起复位或排空，
不能跨复位重放旧完成消息。后续若引入可复用世代标识，必须单独证明标识重用安全性。

## 整数执行接口与性能边界

`IntegerRequest` 输入已译码操作：`operation` 对应 `IntegerOp`，`word` 选择 W 运算，
`usePc`/`useImmediate` 分别选择 PC/寄存器和已扩展立即数/寄存器操作数。
`rename.instruction` 目前是提交和异常元数据，模块不检查它与操作控制字段是否匹配。
ALU 语义依据固定版本的 [RV32I 整数运算](https://docs.riscv.org/reference/isa/v20250508/unpriv/rv32.html)
和 [RV64I 扩展与 W 运算](https://docs.riscv.org/reference/isa/v20250508/unpriv/rv64.html)。
此后端接口自身不译码；`IntegerCore` 通过 `IntegerDecode` 接收机器指令。
`controlFlow` 选择六种条件分支或 JAL/JALR；分支操作使用真实寄存器值比较并计算目标。
分支恢复由执行端生成；后端仍支持外部恢复请求。尚无自动异常入口。
无效 operation 和不支持的 W 组合报告异常原因 2，并由 ROB 保持精确异常边界。

| 结构 | 周期级目标与约束 |
| --- | --- |
| 整数 ALU | 每实例每周期一条；默认两个实例，执行宽度暂取 `completionWidth` |
| 调度选择 | 每周期选择至多两条最老就绪操作；每路用平衡树比较年龄，后路排除前路已选项 |
| PRF | 默认 64 × 64 位；执行数据读端口为 `2 × completionWidth`、写端口为 `completionWidth`，另有提交值检查读口 |
| 就绪状态 | 每保留槽读取两个源的就绪状态；分配清零，获准且无异常的写回置位，下一周期可选中依赖者 |
| 保留槽 | 容量等于 ROB，避免额外调度队列容量冲突；取走后直到 ROB 释放仍保留该索引的容量归属 |
| 默认双宽吞吐 | 独立流填满后每周期两条分配/执行/提交；单依赖链填满后每周期一条 |
| 恢复 | 接受恢复当周期取消所有被杀保留项并过滤写回；保留路径继续执行，映射仍逐项回滚 |

独立流目标要求足够的物理寄存器；36 个物理寄存器配置故意验证资源不足时的反压，
不要求持续双宽。所有架构寄存器在本测试接口复位为零，这是 bring-up 契约，不是 RISC-V 通用复位规定。
选择树、PRF 读 Mux、ALU、写回授权尚处于同一组合路径；多路选择之间也有排除依赖。
寄存器阵列的复位、就绪读端口、宽选择网络和每周期一项回滚均需要综合与工作负载评估。
目前仅验收周期级行为，频率、面积、功耗及四/六宽实际吞吐均未验证。

## 最小取指与机器指令范围

`IntegerCore` 默认从 `0x80000000` 开始，供指端每周期提供 `fetchPc + 4*lane` 对应的有效前缀。
`accepted` 表示已分配事件；PC 按接受前缀推进，若该前缀包含预测跳转则改取其目标，执行重定向优先。
预测跳转后的 packet lane 不分配；预测分支未被接受时不能提前跳转。
未接受的指令需要按新 PC 重新提供，
因此部分接受和供指停顿不会跳过指令。目标是每周期最多 `renameWidth` 条，供指充足时不额外插泡。
当前是组合供指契约，尚未实现 ICache、异步取指响应、访问异常、跨行/跨页或压缩指令拼接。
译码到重命名的组合路径尚未做综合时序验收。

当前支持 49 种 RV64I 运算/控制流/访存编码：LUI/AUIPC；ADDI/SLTI/SLTIU/XORI/ORI/ANDI/SLLI/SRLI/SRAI；
ADD/SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND；ADDIW/SLLIW/SRLIW/SRAIW；ADDW/SUBW/SLLW/SRLW/SRAW。
另有 BEQ/BNE/BLT/BGE/BLTU/BGEU/JAL/JALR；LB/LH/LW/LD/LBU/LHU/LWU/SB/SH/SW/SD。
移位立即数、funct7 和 W 变体分别检查；未支持及保留编码报告原因 2。
这只是当前子集的拒绝策略，不意味着所有被拒绝编码在完整 RISC-V 中都非法。
报告异常前允许较老指令提交，之后停止供指和提交；尚无 trap CSR 更新、处理程序入口或返回，需复位开始新程序。

`integer-program.S` 通过独立的 RISC-V 汇编器生成 410 条指令的直线程序。
`branch-program.S` 覆盖循环、正负向跳转、六种条件分支、调用/返回、JALR 源/目的相同与奇数函数地址，
以及较年轻分支先重定向、较老分支随后撤销它的场景。
另有三个种子、各 6,000 条直线随机机器指令，以及三个包含有界循环、随机整数运算、分支和错误路径非法字的程序。
新增 `bare-start.S` / `bare-memory.c` 以 RV64I、`-O2` 编译，检查函数调用、栈访问和 64 项数组求和。
另有所有访存宽度/字节通道、三个种子的随机访存与依赖、错误路径 store、反压、同周期响应和异常用例。
这是受限执行环境，不代表支持普通裸机平台或完整编译器输出。

## 分支恢复与性能契约

当前条件分支使用 64 项两位饱和预测表，复位弱不跳转，按退休顺序训练。
JAL 与相邻 AUIPC→JALR 在接受时预测对齐目标；后者覆盖同包及跨包相邻指令，保留各自执行和提交。
普通寄存器间接跳转及返回仍预测 PC+4；尚无 BTB/RAS。
分支携带实际使用的预测下一 PC，每个执行槽有组合分支比较/目标计算；预测正确的分支与 ALU 一样可双宽完成，
实际下一 PC 等于预测值时不触发恢复，JAL 到 PC+4 仍正确写链接寄存器。
不同于预测值的对齐目标才请求重定向，最老的有效请求获胜。外部请求先经 ROB 的无副作用探测检查，
失效请求不能遮蔽内部重定向；年龄比较使用 ROB 索引位宽，分配标识仍用于身份验证。

选择逻辑不依赖自己生成的恢复结果，避免组合环。执行后用 ROB 的完成授权统一拦截错误路径的
完成、PRF 写入和就绪唤醒。同周期两个跳转只保留最老者；恢复中的更老边界可继续缩小保留集合。
若外部恢复保留了一个尚未完成的边界分支，该分支在自己的重定向获准前保持待执行，不能悄悄丢掉目标。
提交记录的 `nextPc` 来自获准的实际执行结果；有序提交时逐条与独立模型和 NEMU 比较。

恢复当周期与后续回滚周期暂停分配和提交，每周期撤销至多一个年轻 ROB 项，恢复后接受目标路径指令。
这是可测量的基线，不是最终低延迟恢复方案；已有基础 bimodal 方向预测，尚无 BTB/RAS 或重命名检查点。
分支目标/比较、重定向仲裁及完成授权仍在组合路径上，频率/面积需另行综合评估。
JALR 先清除目标 bit 0；跳转到非 4 字节对齐地址报告原因 0、tval 为目标地址，且不写链接寄存器。
不跳转条件分支不对未使用的目标产生对齐异常；这些事件仍只停机报告，不进入 trap 处理程序。

## NEMU 提交差分与参考审查

`core.cpp` 直接使用 NEMU 的 `difftest_init_v2/regcpy/memcpy/exec` API；尚未连接香山完整 `emu` 的探针传输框架。
每条提交先用独立指令表/软件求值检查 PC、指令、目标寄存器及写回值，再将 DUT 提交记录应用到架构影子，
调用 NEMU 执行一条并比较 PC 和全部 32 个整数寄存器。双提交依次检查，中间状态也必须匹配。
硬件已提交 PRF 值另每周期轮询一个寄存器，程序结束继续检查至少 32 周期。
不使用旧核心作期望值，不在运行中使用 skip 或 mismatch 后同步参考状态。

参考源码固定为 OpenXiangShan/NEMU `c00b6dd17fd6f9d196750af0babba167d271d1fe`。
`reference.py` 从 Git 对象导出到 `build/gsim/nemu-src` 后独立构建，不修改 NEMU 工作树、配置或 `.git` 文件。
构建显式禁用上游 Makefile 的自动 Git 提交。两个本地 checkpoint 资源按 `config/reference-lock.json` 校验哈希；
仅布局头文件参与编译，不执行 checkpoint 生成/恢复，不自动下载依赖。
独立 defconfig 设置 16 MiB RAM、M-mode 初始状态、无浮点/向量/虚拟化寄存器，显式启用 B 和 Zicond 并检查解析后的配置。
NEMU 本身仍支持此 DUT 尚未实现的指令，差分覆盖上述 49 种 RV64I 运算、控制流、访存、Zicond 两条指令、RV64M 13 条指令及 B（Zba/Zbb/Zbs）40 条指令。

已核对固定源码中的 `isa-def.h`、`isa_difftest_regcpy`、`difftest_memcpy/exec/init_v2` 和整数运算语义。
当前寄存器 ABI 是 32 个 GPR、18 个 CSR/模式字段和 PC，共 408 字节；加载时核对导出的大小，
配置变化导致 ABI 不符必须失败。CSR/模式字段用于初始化，尚不参与本子集的架构正确性声明。
`reference-used.json` 记录源码提交、资源、输入/解析后配置及共享库哈希和编译器版本。

NEMU 的内存拷贝不会清空译码缓存。每次装载新测试程序后，在参考端专用地址 `0x80ffff00`
执行一次 FENCE.I，再初始化程序 PC/寄存器，避免沿用前一个程序的译码。这只发生在测试启动前。
测试还主动篡改第一条提交后的影子寄存器，必须得到 NEMU mismatch 和非零退出，证明比较器不会静默放行。
非法指令和目标未对齐停止事件由独立模型按 DUT 的 IALIGN=32 检查，不推进 NEMU 到 trap；
参考模型可支持 C 扩展，不能用其较宽松的目标对齐规则作为当前 DUT 的异常期望。
每条 load/store 提交还比较独立字节内存与 NEMU RAM；外部 RAM 写流还按序与退休 store 的地址、宽度和有效数据字节匹配，允许写延后排出。
程序结束及异常停止时须排空缓冲，并检查无多余/遗漏 store，DUT RAM 与独立模型一致。
访存未对齐与访问错误按独立模型检查异常 PC/cause/tval，不执行 NEMU trap，错误写响应必须无副作用。
异常 CSR、MMIO 和中断差分仍待后续接入。

## 独立验证

`smoke.cpp` 验证寄存器复位、周期采样、64 位加法和同步内存的全部 16 种字节写掩码。
GSIM 的 `step()` 更新周期状态并计算本周期输出；驱动设置输入、调用 `step()`、检查本周期事件，
软件模型随后应用这些事件，在下一次 `step()` 检查新状态。测试不依赖内部 C++ 成员名。

`backend.cpp` 使用软件事务队列重建投机映射，以集合检查物理寄存器所有权。
它允许硬件选择任何空闲物理寄存器，不复制硬件的优先编码器实现，也不调用旧核产生期望值。
每组运行定向用例及三个固定随机种子、共 18,000 周期随机输入：

| 配置 | 目的 |
| --- | --- |
| ROB 8 / 物理寄存器 36 / 标识 64 位 | 寄存器不足、ROB 回绕、资源反压 |
| ROB 32 / 物理寄存器 64 / 标识 64 位 | 默认容量下的并发分配、完成、提交、恢复 |
| ROB 8 / 物理寄存器 36 / 标识 8 位 | 标识耗尽时禁止重用；不代表 18,000 周期始终有新分配 |

覆盖同包 RAW/WAW、x0、双提交、乱序完成、有序异常、错误路径完成、重复完成、
失效恢复请求、恢复中更老重定向、资源耗尽、映射及寄存器数量守恒。

`integer.cpp` 不使用物理映射计算期望值：重放架构写入求值，用生产者标识记录依赖，
比较实际执行结果和有序提交结果，并轮询检查已提交寄存器值。
覆盖 64/32 位算术边界与移位量截断、PC/立即数选择、同包 RAW/WAW、x0、年轻独立操作越过依赖链、
ROB 满/回绕、PRF 耗尽、提交反压、冲刷已执行/待执行操作、恢复中更老边界、失效恢复及精确异常。
两组配置（ROB 8 / PRF 36 和 ROB 32 / PRF 64）各运行三个种子、18,000 随机周期。
定向吞吐测试在 100 周期流中逐周期断言后 96 周期：默认配置持续双宽，依赖链持续单宽。
非法操作的异常恢复也必须排空依赖者，不允许测试以超时为正常完成。
另有五组恢复仲裁定向用例：失效外部请求、较老外部恢复、较年轻外部恢复、同边界保留重试及同边界包含清空。

`core.cpp` 对每组配置检查 136,072 个译码输入（穷举 opcode/funct3/funct7 组合加随机字段），
并测试供指/提交停顿、部分接受、x0、同周期提交覆盖同一寄存器、精确异常停止及机器指令流双宽吞吐。
分支程序按动态架构 PC 求值；循环不会靠线性数组位置推断提交顺序，错误路径上的非法字也不能触发架构异常。
GSIM 模型和驱动开启 ASan/UBSan；NEMU 使用锁定配置独立构建，未开启这些 sanitizer。

生成模型及测试驱动都启用 AddressSanitizer 和 UndefinedBehaviorSanitizer。
为兼容受限执行环境关闭 LeakSanitizer，不关闭地址或未定义行为检查。

2026-09-18 分支/跳转/恢复回归记录：Scala 编译及四项参数/展开测试通过。
锁定的 GSIM 提交配合 Clang 21.1.8，最终 `make gsim-test` 全部通过：
smoke、三组账本、两组整数执行、两组程序差分及故障注入检查。
两组整数测试共覆盖 36,000 随机周期；默认配置通过连续 96 周期双宽吞吐断言，
两组配置均通过连续 96 周期依赖链单宽吞吐断言，ASan/UBSan 未报告错误。
程序差分的两组配置各通过 136,072 个译码输入和 23 个程序测试，
各比较 28,618 条提交（含 18,000 条随机整数机器指令），并检查 9 个异常停止事件，含 3 个跳转目标未对齐事件。
每组检查 2,037 次重定向，其中 2 次由更老分支纠正较年轻分支已经改变的取指路径。
这两个程序级事件发生在此前回滚结束之后；恢复进行中收窄边界另由账本定向测试覆盖。
默认配置的独立整数流、不跳转分支流各连续 251 周期保持两条接受/两条提交；
小容量配置发生 3,044 次部分接受并正确续取。
固定的 64 周期提交暂停确保默认 ROB 也达到反压状态，之后再随机化供指/提交停顿。
主动篡改寄存器的负向测试以预期 NEMU mismatch 和退出码 1 结束。
以下为切换到 GSIM-only **之前**的历史记录，不再是当前回归要求：
仓库全量 ScalaTest 使用本机 firtool 1.135.0、Verilator 5.032，183 项中 182 项通过：
唯一失败是旧 `FrontendQueueSpec` 期待满队列同周期出入，而旧实现明确禁止该行为。
此前出现过 Verilator internal fault 的 Sv39 取指测试本次全量运行通过。
这些旧实现和测试均未修改，不用它们的结果作为新后端的期望值。
旧工程 `make verilator` 的 timer payload 通过（UART `S!!P`、退出值 0）；
受限环境中将 `CCACHE_DIR` 指向项目生成目录，并用 `CHISEL_FIRTOOL_PATH` 指向本机已有 firtool。
本批全量 Scala 和旧整机日志分别为 `build/gsim/scala-tests-branch.log`、
`build/gsim/legacy-verilator-branch.log`；
GSIM 全量日志为 `build/gsim/gsim-tests-branch-final.log`，负向检查日志为 `build/gsim/core/negative-test.log`。

另有 ScalaTest 参数/展开测试：

```bash
mill -i IonSoC.test.testOnly ooo.OooParamsSpec
```

四/六宽接口目前仅通过展开检查，不表示已验证或实现四/六发射 CPU。
这些模块级验证不等同于 ISA 差分、形式证明、综合时序检查或整核正确性。

预测器另有 10,000 周期独立 GSIM 测试，覆盖饱和、无效训练、PC 别名和双更新同索引顺序。
整核驱动独立维护预测计数器，在退休训练前计算本周期预测，检查取指 PC、packet 截断与供指/提交背压。
报告 `predicted_taken` 为接受的预测跳转事件（包含错误路径），`branch_mispredictions` 为条件分支
执行校正事件（也可能属于之后被清除的路径），不能直接用两者计算退休分支准确率。

## 当前 GSIM 兼容性处理

在锁定版本上实际遇到两个限制，已通过保持硬件语义的封装处理，上游源码未修改：

1. bulk-connect 后动态写入组合向量导致 `splitArray` 断言。重命名组合阶段改用逐元素 Mux 连接。
2. 顶层向量端口生成了标量 C++ accessor。测试顶层 `RenameRobGsim` 将两个 lane 展开成显式命名端口；
   生产模块仍保留 Vec 接口。

## 下一阶段

以已测 IPC 为基线，推进 LQ/SQ、地址生成与提交解耦、store-to-load forwarding 和分支预测，
再接缓存/平台与精确 trap 状态；当前基线与瓶颈见 [裸核 IPC](../../docs/bare-core-ipc.md)。
ISA 设计参考固定到 RISC-V 文档版本 `20250508`；当前仅声明上述经过测试的整数/控制流/访存子集。
[规范版本入口](https://docs.riscv.org/reference/isa/v20250508/unpriv/colophon.html)。

参考模型的整数子集构建与 ABI 已审查；完整平台的扩展、计时器、异常及中断配置仍需审查。
NEMU 子模块工作树链接仍指向旧的 `/home/openion/IonSoC` 路径，本次未修改其元数据或源文件。

## FPGA 同步取指验证

新增 `make gsim-fpga-fetch-test`：独立检查 Chisel SyncReadMem 双 bank ROM 的读延迟、奇地址 word 排列、
响应背压与范围边界；随机改变 PC 检查旧响应和请求背压稳定性；小 ROB 核直接连接同步 ROM，
运行循环、JAL/AUIPC-JALR、错误路径非法字及 ROM 上、下边界越界取指程序；正常提交前缀
经独立软件模型和 NEMU 比较，越界取指须在 ROB 队首报告 cause 1 和出错 PC。
该入口纳入全量回归，但与理想供指 `ipc.json` 分开，不能用后者代表 FPGA 前端性能。
导出与限制见 [FPGA 基线](../../docs/fpga-bringup.md)。

同步前端现已增加两组 packet 缓存、顺序预取和响应到供指旁路；独立检查连续 128 周期双供指、
停顿时有界预取及部分消费。240 条不写寄存器的 ADDI 吞吐用例经 NEMU 校验，不能代表一般程序 IPC。


## 同步 ROM / RAM 执行平台

`make gsim-platform-test` 已纳入完整验收：验证 Chisel 同步字节写 RAM 的连续吞吐、随机背压、
错误响应及最终内容，并连接 ROB32/PRF64 双发射核运行 C 栈/数组程序。
三次 C 运行与两个精确访问错误用例合计 3,934 条正常提交；C 执行由独立模型和 NEMU 检查，
负向寄存器注入必须被 NEMU 拒绝。ISA 软件求值器在 `harness/isa_model.h` 共享，不依赖 DUT 编码表。

无提交背压时 1,310 条指令 / 1,529 周期，IPC 0.856769130；跨 packet 供指后两个随机背压种子分别为 1,923 / 1,879 周期（原为 1,885 / 1,880）；
无背压周期不变，不能声称普遍提速。
`build/gsim/platform-ipc.json` 记录独立平台口径、工具版本及镜像哈希，不覆盖理想供指 `ipc.json`。
`make fpga-platform-rtl FPGA_IMAGE=build/gsim/bare-program.bin` 导出集成 ROM/RAM 顶层；
命令、测量限制和 Vivado 移交见 [FPGA 执行平台](../../docs/fpga-bringup.md)。

同步前端现支持跨 packet 双路拼接，独立验证缓存及当拍响应两种来源、后继未到时的单路供指和停用状态。
完整限制及前后测量见 FPGA 执行平台说明。


## RVA23 目标与 Zicond

应用 SoC 已以 RVA23S64（含 RVA23U64 必选能力）为目标，完整差距见 [架构目标](../../docs/rva23.md)。
当前只新增 Zicond 1.0.0 的 `czero.eqz` / `czero.nez`，不是完整 RVA23 实现。
两源参与现有重命名和就绪选择，共享双 ALU 与 issue 预算，拒绝 W 变体及相邻保留编码。
参考侧仅修改本仓库独立 defconfig 开启 `CONFIG_RV_ZICOND`，固定 NEMU 源码及 GPR/PC ABI 不变。
独立软件 mask/match 和语义表不从硬件生成；编译的 C 负载仍使用原 RV64I 参数，避免混淆基准。

Zicond 最终验收：Scala 19 项与完整 GSIM/NEMU 通过；每组裸核 79 个程序、66,238 条提交。
新增 5 个程序检查别名、x0、高位条件、随机依赖及默认配置的双宽吞吐；现有 IPC 基准不变。
日志：`build/gsim/zicond-final.log`。


## RV64M 多周期执行

`make gsim-muldiv-test` 独立检查单槽乘除单元，并已纳入 `make test`。
3,900 笔算术完成、39 次取消、15,611 个结果保持周期通过独立主机算术模型；
涵盖乘积高半、除零、溢出、W 符号扩展、输入变化与旧 token 取消后重发。

裸核通过全部 13 条 M 指令的译码、算术及 NEMU 比较，包含 832 组边界操作数、1,000 条随机 M、
源/目的别名、x0、分支撤销、较老 M 跨恢复保留和 LSU 完成仲裁。
新增 `rv64m_*` IPC 项（每配置四项），原有基准输入与 C 编译选项保持不变。
详细延迟、启动间隔和微基准见 [RV64M 合同](../../docs/rv64m.md)。
当前仍无完整 RV64I、B、CSR/MMU、浮点或向量，不能声明 RVA23 合规。

RV64M 最终验收：`make test` 的 Scala 19 项及完整 GSIM/NEMU（含负向注入）通过；
每组裸核 111 个程序、97,138 条提交。原有 28 条 IPC 测量不变，新增 8 条 M 测量。
日志：`build/gsim/muldiv-final.log`。


### 流水乘法

活动核将乘法与除法分开，`make gsim-pipelined-mul-test` 已纳入默认验收。
原 `gsim-muldiv-test` 保留串行算术模块回归；活动除法采用该模块的 divisionOnly 特化，不保留闲置乘法通路。
新乘法器延迟 6 拍、每拍最多接收一笔，八项预留结果容量，支持逐 token 取消与结果背压。
独立单元验证连续 256 拍吞吐、全部五种乘法边界、随机运算、满容量、长背压和多槽取消。
核级补充同时取消多笔乘法及较老乘法跨恢复保留，并检查乘除并发。

同一独立乘法微基准：ROB32/PRF64 从 899 降至 137 周期（IPC 0.948905109），
ROB8/PRF36 为 292 周期；依赖乘法链和除法周期不变，其余原有 IPC 记录不变。
这不构成 FPGA 频率/资源或通用程序加速声明。详情见 [RV64M](../../docs/rv64m.md)。

流水乘法最终验收：Scala 19 项、完整 GSIM/NEMU 和负向注入通过，两组裸核各 113 个程序、97,170 条提交。
日志：`build/gsim/pipelined-mul-final.log`。

## RV64 B 位操作验收

Zba/Zbb/Zbs 的 40 条 RV64 编码已接入，当前共支持 104 种编码（49 RV64I + 2 Zicond + 13 M + 40 B）。
`make test` 通过：Scala 19 项、完整 GSIM/NEMU 和负向注入；两组裸核各 278 个程序、380,406 条提交，
185,224 个译码输入，19 次精确停止。新增 7,680 组 B 操作数、3,000 条混合随机 B、40 个恢复/竞争程序，
并检查非法内部控制码和非法 W 组合。参考配置启用 CONFIG_RVB，固定 NEMU 版本和寄存器 ABI 不变。

默认双发射配置的独立 RORI/CLZ 基准为 2,049 条 / 1,027 周期（IPC 1.995131），
依赖链为 2,049 条 / 2,051 周期（IPC 0.999025）；原 36 条 IPC 记录完全不变。
同步 C 程序仍为 1,310 条 / 1,529 周期（IPC 0.856769），没有 FPGA 时序/面积实测结论。
合同、实现路径与详细验证见 [RV64B](../../docs/rv64b.md)，全量日志 `build/gsim/rv64b-final.log`。

## 模块化 AIA 中断 IP

独立 `soc.ip.interrupt.Imsic` 的合同、接线和状态见 [模块化 SoC](../../docs/modular-soc.md)。
`make gsim-imsic-test` 使用独立逐身份 C++ 状态模型验证三组配置、双口背压及原子操作，
包含故意破坏响应期望的负向测试。`make imsic-rtl` 可单独导出默认 IP，输出在 `build/ip/imsic`。
该独立 IP 验收本身不代表完整 AIA 实现；后续机器核/APLIC 组合进展见下文，PLIC 兼容适配和 NEMU AIA 差分尚待实现。

IMSIC 加入后的全量验收通过：Scala 21 项、三组 IMSIC、完整 GSIM/NEMU 及负向注入；
原 CPU 44 条 IPC 记录完全不变。日志 `build/gsim/imsic-final.log`，详细覆盖和统计见模块化 SoC 合同。

## 机器核 CSR / 同步异常 / 外部中断

`make gsim-machine-test` 验收独立 `MachineCore`（ROB8/PRF36、ROB32/PRF64）。支持六种 CSR 编码、
ECALL/EBREAK/MRET、最小 M CSR 集与 IMSIC M 文件 CSR 访问，处理程序可以保存/修改 mepc 后返回。
两组定向测试各 31 个程序、10,815 条退休、37 次同步异常、39 次外部中断、81 次 MRET、1,805 次 CSR 操作。
覆盖 MIE/MEIE 屏蔽、Direct/Vectored、空 ROB、U 标签抢占、load/store 排空、同步异常优先和重入。
定向日志 `build/gsim/irq-focused.log`；CSR 数据与中断原因负向注入均通过。
标准机器级程序与独立模型/NEMU 核对，AIA/低权限裸地址空间/指定访存故障使用独立模型；
执行过程中不重同步 NEMU。覆盖范围和限制见 [机器核合同](../../docs/machine-core.md)。

`make machine-core-rtl` 单独导出 `build/ip/machine-core`；已通过 RTL 导出，尚无 Vivado 综合/时序结果。
`FpgaPlatformTop` 和原整数 IPC 流仍使用原异常停止配置。新机器核已接 M/S 外部中断、SSI 和 STI，WiredMachineCore 已加 APLIC，MappedMachineCore 已接 APLIC 数据地址映射，尚未接 VS 中断、完整 SoC、
完整 S/U 环境、Sv39/MMU、计数器或完整 CSR 集，不是 RVA23 合规完成声明。MachinePlatform单独启用PMP，见[PMP合同](../../docs/pmp.md)。

## APLIC 与中断线组合

新增独立单 M 域、单 hart MSI-only APLIC，默认31路源，31/63路独立 GSIM 验收。
`WiredMachineCore` 用现有机器核/IMSIC 连接新 IP，中断线组合跑相同31个机器核程序。
寄存器端口支持一拍响应、持续 II=1；MSI 有序队列最多4项已发送未响应事务。
WiredMachineCore 保留独立控制口；MappedMachineCore 已将 M 根域及 S 子域映射到 CPU 数据总线。
sourcecfg.D 委托到单个 S 子域、UART source3 和 S IMSIC 文件已在独立与整机 GSIM 中验证；
多 hart APLIC 路由、VS 域、IDC 和 PLIC 兼容仍待实现。
命令、精确状态语义、模型覆盖和限制见 [APLIC 合同](../../docs/aplic.md)。

APLIC 加入后的完整验收通过：Scala25项、全部GSIM/NEMU及负向注入，原整数配置44条IPC记录不变。日志 `build/gsim/aplic-final.log`。

## 程序配置 APLIC

`MappedMachineCore` 用8项有序标签路由器连接 CPU 数据口与 APLIC，保留外部普通存储器接口。
独立路由定向检查15,234项事务、最大8项在途和连续282拍收单通过；两种核心配置各3个程序，
验证 SW 配置、LW/LWU 读回、访问错误、错误路径写取消及中断处理返回。
命令、覆盖和性能边界见 [数据口映射合同](../../docs/core-mmio.md)。

数据口映射加入后的完整验收通过：Scala26项、全部GSIM/NEMU及负向注入，原整数配置44条IPC记录不变。日志 `build/gsim/mapped-final.log`。


### 同步机器核启动平台

`make gsim-machine-platform-test` 执行 ROM 中编译的汇编/C 固件，覆盖 RAM 清零、数组求和、
CPU 配置 APLIC、IMSIC 领取中断、RAM 计数更新及 MRET，使用真实同步 Chisel ROM/RAM。
两种 ROB/PRF 配置各3次启动，分别5,373/5,376条提交，每组9次同步异常、3次外部中断；
结果376、计数1，MMIO 负向注入通过。新设备路径采用独立提交模型，原 NEMU 回归保留。
`make machine-platform-rtl` 导出带同一固件 ROM 初始化文件的生产 RTL。
本轮 `make test` 全部通过，27项Scala检查、全量GSIM/NEMU及负向注入通过，44条原整数IPC记录完全不变。
详细周期、构建入口与未验证的 FPGA 时序边界见 [平台合同](../../docs/machine-platform.md)。


### 串行UART与性能回归

`make gsim-uart-test` 检查独立 `UartConsole`：8N1、可编程分频、真实TX/RX、非FIFO寄存器子集，
1,090次事务、384拍连续读、43个串行TX字符及错误注入通过。不是完整16550，旧仿真UART未改动。
`make gsim-machine-platform-test` 每种核心配置执行UART和原RAM两套启动固件：TX输出 `OK\n`，
RX输入 `Z` 触发APLIC source3/IMSIC/M中断，处理程序保存0x5a到RAM并返回。
UART路径ROB8/32分别提交5,938/6,029条指令，每组9次同步异常、3次外部中断，设备及串行负向注入通过。

`make gsim-privilege-uart-platform-test` 运行独立的M→S→U→S整机镜像：U态ECALL和越权CSR读
及被PMP禁止的APLIC读写、单指令取指委托至S态，S态串行输出`SU!\n`，并检查RAM异常计数、
MPRV访问、锁定条目、提交/陷阱模型及串行负向注入。
`make gsim-pmp-fetch-platform-test` 在双主TileLink整机运行同一镜像，检查PMP锁定后
无Get读取禁执行字，边界允许字改用32位Get；正常双字路径仍使用64位Get。
`make gsim-pmp-test` 用独立区间模型检查PMP优先级、整段覆盖、TOR/NA4/NAPOT和边界地址，
含6000组随机用例及负向故障注入。仍无Sv39分页或通用S/U软件环境。

本轮 `make test` 通过28项Scala及全量GSIM/NEMU验收，日志 `build/gsim/uart-final.log`。
与 `build/gsim/ipc-before-uart.json` 对照，44条整数裸核IPC测量逐项一致；原RAM固件六组启动周期完全不变。
生产RTL含uartRx/uartTx引脚，已导出但未经Vivado验证。见 [UART审计、能力与测试边界](../../docs/uart.md)。


### 写缓冲并行排空

StoreBuffer把单项等待写响应改为独立发送指针和已发送计数，默认4项可连续4拍发出并保持4项在途。
槽位仍在响应后释放，未响应数据继续参与字节转发；MMIO/未完整覆盖load和中断继续等待排空。
`make gsim-store-buffer-test` 现在覆盖1/2/4/8项容量，每种3个随机种子及零/非零响应延迟。
全量 `make test` 通过28项Scala及全部GSIM/NEMU。12周期RAM下默认C程序IPC 0.463717→0.825977，
store/load链0.233952→0.428412，退休后写排空46→8周期；44条测量无周期退步。
同步片上RAM平台和启动周期不变，未验证Vivado频率与面积。详见 [优化合同与全部对照](../../docs/store-drain.md)。
日志 `build/gsim/store-pipeline-final.log`，基线 `build/gsim/ipc-before-store-pipeline.json`。


### 无字节冲突的RAM读提前请求

当所有旧写已发出，但响应尚未全部返回时，不相交普通RAM load可提前请求；完整覆盖转发保留，
部分覆盖仍等待，MMIO排空不变。复用原5项响应所有者队列，读/写各自最多4项，纯load并发仍为4。
独立RAM模型在响应消费时才实际写入，覆盖1/2/4/8项缓冲、同beat不相交字节、背压与零延迟，
增加读值负向注入；整核验证C程序确实存在读/写响应重叠。

全量 `make test` 通过28项Scala及全部GSIM/NEMU。默认C程序在12周期RAM下1,586→1,575周期，
IPC 0.825977→0.831746；小配置2,032→2,024周期。44条测量2条改善、42条周期不变，无周期退步；
同步平台和UART/原RAM启动记录不变。日志 `build/gsim/load-overlap-final.log`。
合同与限制见 [读写重叠](../../docs/load-overlap.md)，未验证FPGA频率与面积。

## FENCE 与 DMA

机器核支持队首完整排空式FENCE；独立慢响应测试检查写响应完成前禁止年轻读取，并覆盖FENCE.TSO、
忽略 rd/rs1。机器核的 FENCE.I 在同一排空边界刷新前端并重取；
独立前端测试覆盖背压旧请求及旧响应丢弃，双主单 RAM/双 RAM 平台测试覆盖写 RAM 后执行。
基础 FENCE 另进入已有 NEMU 机器核差分程序。
`dma.cpp` 用独立RAM模型覆盖48组拷贝/错误/重启/轮询用例，读写地址序列及整体内存结果均核对；
`shared_data.cpp` 验证双主设备请求/响应归属、公平性、8项信用、背压及每拍一项服务能力，两者均有负向数据注入。
机器平台另运行source4 DMA完成中断固件，两种ROB配置、三种退休背压种子；详见 [DMA合同](../../docs/dma.md)。
全流程仍只使用GSIM，平台设备参考采用独立软件模型，未宣称NEMU支持该自定义DMA设备。

2026-09-22 DMA验收：29项Scala、全部GSIM/NEMU和负向注入通过；独立DMA48组用例、6,612项请求，
仲裁12,607项请求，完整平台6次DMA启动均通过。1KiB DMA忙292–294拍，同期CPU仍获准35–36项RAM请求。
原44条裸核IPC及12组RAM/UART启动周期不变；模型源码哈希更新。日志 `build/gsim/dma-final.log`，
详细口径和限制见 [DMA验收](../../docs/dma.md)。

## 机器定时器与MTIP

独立MachineTimer使用同步tick和RegisterPort，支持64位与32位高/低半访问，比较后寄存输出中断。
机器核新增MTIE/MTIP与原因7，MEI优先于MTI；向量偏移由原因生成。
`gsim-machine-test`增加18个定向程序；`gsim-machine-platform-test`增加两种配置、三种背压下的两次定时中断启动固件。
平台时间由主机按固定四拍脉冲提供，独立软件模型检查比较值/中断；既有NEMU回归保持原覆盖，不宣称NEMU支持新定时设备。
合同和限制见 [机器定时器](../../docs/machine-timer.md)。独立RTL入口为 `make timer-rtl`。

2026-09-22 定时器验收：30项Scala及全部GSIM/NEMU/负向注入通过。独立IP13,587项访问，
两组机器核各新增18个定时相关程序，平台六次定时启动均完成两次MTI、计数2及C结果376。
44条裸核IPC和18组UART/RAM/DMA启动周期逐项不变，仅模型源码哈希更新。
定时器与平台RTL导出通过；日志 `build/gsim/timer-final.log`、`build/gsim/timer-rtl-export.log`。


## 原子共享内存IP（第一阶段）

`make gsim-atomic-test`验证独立AtomicMemory：W/D LR/SC、九种AMO、CPU/DMA竞争、保留失效、
响应错误、零/长延迟和随机背压；独立软件内存与下游序列模型，加结果篡改负向检查。
普通流连续501拍每拍一笔，12拍响应模式达到8笔在途；无背压1拍内存的AMO为6拍、12拍内存为28拍（包含请求/响应握手）。
以上是第一阶段IP级结果，当时MachinePlatform尚未接入；当前CPU接入状态与验证范围见下节，仍不宣称完整A合规。
接口和完整测试边界见 [原子内存合同](../../docs/atomic-memory.md)，性能口径见 [当前性能](../../docs/performance-status.md)。
独立RTL入口：`make atomic-rtl`；全量验收自动包含该IP测试。


2026-09-22 原子IP阶段验收：`make test`通过31项Scala、完整GSIM/NEMU与16项负向注入。
两组整数核各278个程序、380,406条提交；44条IPC测量字段与修改前逐项一致，24次UART/RAM/DMA/定时启动记录也保持一致。
独立原子RTL导出通过；日志`build/gsim/atomic-final.log`、`build/gsim/atomic-rtl-export.log`。


## 原子CPU接入（第二阶段）

机器平台默认启用22种W/D原子编码：LR/SC、九种AMO，所有aq/rl均采用队首授权、旧写排空和年轻访存阻挡。
裸核默认不启用，必须显式配置atomicMemory并连接AtomicDataMemory；DataPort原子rs2右对齐，返回为完整架构结果。
`make gsim-atomic-core-test`在两种配置各检查80程序、3072译码组合、52精确异常，覆盖DMA干扰与错误注入；
无外部干扰的AMO/LR/SC序列用现有NEMU差分，其余用独立模型。负向篡改必须检出。
`make gsim-machine-platform-test`增加六次原子/DMA/陷阱返回启动，保留原UART、RAM、DMA与定时器启动。
详见[原子合同及实测](../../docs/atomic-memory.md)。这仍不是多hart缓存一致性、完整A或RVA23合规声明。


2026-09-23 第二阶段最终验收：`make test`通过32项Scala、完整GSIM/NEMU与17项负向注入。
两种配置新增各80个原子集成程序，六次原子平台启动；原44条IPC测量字段及24次既有启动记录逐项不变。
生产机器平台RTL已重新导出，filelist包含AtomicMemory与AtomicDataMemory；Vivado仍未运行。
日志`build/gsim/atomic-core-final.log`、`build/gsim/atomic-core-rtl.log`。


## 可选共享读缓存

新增独立SharedReadCache及DataPort适配器：1KiB直接映射、64字节行/8字节有效扇区、写穿透与匹配行失效。
位于原子/DMA共享边界下游，MachinePlatform通过sharedReadCache显式开启，默认关闭。
独立GSIM检查命中/替换/错误/背压；缓存开关各两种CPU配置，每种88程序、3712提交，原子与DMA故障模型保持覆盖。
全量验收包括缓存平台及原平台各两种配置、五种固件、三种背压，共60次启动。
报告`build/gsim/cache-core.json`及`cache-platform.json`与原44项裸核IPC分开保存。
命中流水化后，12拍重复读取无缓存/首版/当前分别903/786/277周期，下游读256→1；
流式读取仍需3846周期（无缓存903），故不默认开启。独立512项热缓存请求514拍完成，并覆盖三项响应占用全满背压。
多笔未命中已实现，最新性能/平台代价见[合同与全部对照](../../docs/shared-read-cache.md)。
可选RTL入口`make cached-platform-rtl`，默认生产入口保持`make machine-platform-rtl`。

2026-09-23 多笔未命中缓存定向：8项有序返回槽、最多4笔下游请求；独立128项长延迟流式读峰值4笔在途，
同地址64次仅读下游1次。四种CPU配置各88程序、60次平台启动通过，结果见[共享读缓存](../../docs/shared-read-cache.md)。
缓存仍默认关闭；完整验收日志和RTL导出记录见该文档末尾。

2026-09-24 命中返回由3拍缩至2拍，缓存范围内的写只使匹配8字节扇区失效；
独立 `make gsim-cache-test` 包含每拍一项的热命中流、错误和背压检查。
在 MULW 快路径接入前，同一 CoreMark 二进制下，128 行缓存为377,421周期、直连RAM为346,307周期，
因此继续默认关闭。详情见[共享读缓存](../../docs/shared-read-cache.md)。

多笔未命中最终验收：`make test cached-platform-rtl`通过，日志`build/gsim/cache-mshr-final.log`；
33项Scala、完整GSIM/NEMU、14组缓存连续请求检查、19项故障注入及60次平台启动通过。
原44项IPC、30次默认平台启动和24条无缓存CPU对照逐项不变。

2026-09-23 缓存写路径归因与改进：`make test cached-platform-rtl`通过，
日志`build/gsim/cache-write-release-final.log`，逐次启动诊断`build/gsim/cache-stalls.json`。
33项Scala、完整GSIM/NEMU、60次平台启动及19项故障注入通过；
44项IPC、30次无缓存启动与48条整核对照逐项不变。
DMA缓存版6004周期，较上一版6426减少422周期，但仍慢于无缓存5440；默认关闭。
# 参数化页表遍历模块

`make gsim-sv-walker-test` 验证独立 `SvPageTableWalker` 的 Sv39/Sv48/Sv57
页表读取、超页、权限、异常与背压。SoC 可选翻译服务已有 TLB 和 TileLink
页表读取；机器核已有 `satp`、`SUM/MXR` 和全局 `SFENCE.VMA` 失效控制。
可选 I/D 两侧均已接入译址：GSIM 固件验证 MPRV=S 数据访存，以及 S-mode
虚拟地址取指、数据读取和跨页页故障；这仍不表示完整 S/U 软件或 RVA23 已合规。接口与性能边界见
[`docs/virtual-memory.md`](../../docs/virtual-memory.md)。

`make gsim-soc-translation-test` 检查 SoC 可选双路 TLB/页表遍历服务通过
TileLink RAM 读取真实 PTE，含 CPU 发起的失效、两路并发、非叶 PTE 缓存、
命中、失效、超页和 NAPOT。
此入口测试服务侧请求；`make gsim-vm-data-platform-test` 另用 MPRV=S 固件
验证 CPU 数据侧有效页 load/store、精确页故障和故障时不发出物理数据请求。
`make gsim-vm-instruction-platform-test` 验证 S-mode 映射页取指、页末指令执行及
下一页精确 instruction page fault。

## OpenSBI 启动

`make gsim-opensbi-setup` 拉取并核对上游 OpenSBI v1.9 固定提交；
`make gsim-opensbi-test` 使用 `riscv64-linux-gnu-` 工具链与 `dtc` 构建 `generic` 平台
`fw_jump`，通过 GSIM 真正执行固件，解码 UART，并由 S 态测试程序验证 SBI BASE ECALL。
`make gsim-opensbi-console` 把相同平台的 UART TX 实时输出到终端，键盘字节经串行 RX 注入；
交接后的 S 态探针回显输入，Ctrl+D/Ctrl+C 退出。
当前通过记录及内存布局见 [OpenSBI 启动验证](../../docs/opensbi-bringup.md)。

## Linux 启动

`make gsim-linux-setup` 从 `~/board/linux` 当前 Git 提交生成只读快照并构建独立
RV64 内核；`make gsim-linux-test` 通过 OpenSBI 在 64 MiB GSIM RAM 模型中启动它，
检查 Linux 串口日志和用户态 `/init` 标记。配置、内存布局与阶段性验证范围见
[Linux 启动实验](../../docs/linux-bringup.md)。
`make gsim-linux-profile ISSUE_WIDTH=4 LINUX_CACHE_MODE=coherent LINUX_PROFILE_CYCLES=10000000`
只采样指定周期数并输出 L1 读/写缺失、逐出和填充事件，不等待完整启动；
`LINUX_CACHE_LINES=256` 可做 16 KiB 容量对照。短窗口不能代表稳态 IPC。
