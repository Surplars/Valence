# 模块化 SoC / AIA IP 合同

本文描述模块边界并保留独立 IP 的初始验收数据。当前软件可见的配置、地址与限制见
[SoC datasheet](soc-datasheet.md)、[寄存器手册](soc-registers.md) 和
[OS 移植指南](os-software-porting.md)；板级集成见 [ZU15EG](../fpga/zu15eg/README.md)。
不要把独立 IP 的默认参数或测试能力自动当作板级 CPU 可访问接口。

## 整 SoC 重构和验收

当前任务是重构并完成真实 XCZU15EG 整板时序闭合，随后生成 bit；不以少数模块通过或
关闭 F/D、降低频率代替完成。交付候选保留双发射、完整 F/D 配置、CPU 100 MHz、UART
460800 baud、PL DDR4、原生 GMAC 和 CMU。ISA 与外设仍独立可配置，默认实验开关不改。
本节记录当前工作；下文的独立 IP 初始验收是历史证据，不自动升级为该候选的验收。

2026-10-06 07:40（+08）已启动本批全新整板综合、布局布线，候选为
`E:\VM\Share\Valence-rtl\native-rv64gc-soc-return-control-20261006-r3`。
CPU 使用已完成短验收的 r3 返回/控制/PMP/FPU 批次，GMAC 使用新生产 ODDR250
边界；未复用旧 CPU DCP。真实 TX 引脚私有探针已转正，生产短验证和接口综合
通过，但整板仍待最终签核，尚未生成 bit。三发射在双发射合格 bit 之后独立评估。

上一批整体布局后 WNS 从 -0.088 ns 回退至 -1.206 ns，setup 失败端点从 6 增至 18803。
本批因此优先重建明确的流水与握手边界，而非继续增加不相干的时序开关。
旧实现已获批准停止，保留日志、RTL 和 placed 检查点；未完成最终签核，不能发布 bit。
其布线中间估计只能记录为中间值，不能换算为已验证的整板 Fmax。

| 分区 | 职责和必须保留的合同 | 当前重构或审计状态 |
| --- | --- | --- |
| 取指和预测 | 双发射连续供给、混合 16/32 位、精确纠错、PMP 与指令故障元数据 | 高位游标邻接值按八位片并行计算；正常与纠错候选仍先计算再选择，周期不变，物理收益待测 |
| 整数后端 | 分配所有权、同包依赖、提交顺序、回滚、过期完成拒绝 | 保留已测双发射配置；只用必要的短 NEMU 和 IPC 检查，不能把独立 ALU IPC 当成应用 IPC |
| 浮点状态和计算 | FLEN 64、NaN boxing、舍入/标志、精确退休；F 与 D 独立选择 | 计算与体系结构状态保留，访存抽为独立 `FloatingPointMemoryPipeline` |
| 浮点访存 | 一笔 ROB 队首不可撤销操作；权限在实际 LSU 接收时检查 | AGU 保存完整参数，LSU 请求不旁路，响应和完成分别寄存；接受后的操作及回复必须排空后才能 trap |
| MMU 和 CPU 数据口 | 请求顺序响应；排队请求不继承新 SATP、SUM、MXR 或权限 | 注册输入保存 `DataRequest` 和接受时的 `VmCsrState`，idle 包含该队列；物理 PMP 保留原授权边界 |
| L1 和共享互连 | 缓存权限、源 ID 生命周期、burst 错误、回压和响应所有权 | 审计既有寄存边界，复用必须有未变源码和独立证据；不得把单纯原样重跑当作结构改进 |
| DDR 和 AXI CDC | AXI 五通道、burst、复位及跨域所有权 | DDR UI 域与 CPU 域继续隔离；整板须检查 Gray、payload、reset 和 bus skew 覆盖 |
| UART 和 GMAC | 独立外设域、MMIO/DMA/irq 跨域、RGMII 引脚与相位 | 保留已验证边界，整板重新查 setup、hold、pulse、IO min/max、divider release、CDC 和 DRC |
| CMU 和板级封装 | 时钟、复位、排空、隔离及唤醒职责清晰 | CPU 动态变频仍不得由资源清单或控制寄存器的存在推定已完成硬件验收 |

浮点访存仅是自然对齐的 4/8 字节操作，合法访问的 PMP 末字节可精确使用位或代替
65 位加法。只对检查器地址做自然对齐；LSU 仍保存原始地址，非对齐异常优先级和 tval
不变。权限、PMP 和虚拟化状态不在 AGU 准备时提前缓存。新增响应边界和 LSU 请求
寄存会增加浮点访存延迟，实际周期和 IPC 必须与保存的基线对照，尚未宣称性能提升。

必要短验收入口为 `python3 simulator/gsim/soc_pipeline_refactor.py --tag <新标签>`。
它检查游标算术、独立 PMP 字节区间参考、浮点访存边界、排队 VM 上下文、两组取指，
再跑短整数 NEMU/IPC/恢复检查和真实 RV64GC CPU/当前板级模型。每个独立检查有故意
注入错误的负对照，并冻结源码散列。新检查尚未通过前不能复用为综合准入证据。

本轮 `soc-restructure-20261005-r1` 已完成统一编译及上述受影响短验收：
`build/gsim/soc-pipeline-refactor-soc-restructure-20261005-r1/receipt.json` 的状态为
`PASS_SOC_PIPELINE_REFACTOR_AFFECTED_SHORT`。游标独立参考 10445 向量、PMP 16 定向/
6000 随机/30840 边界检查、浮点访存 320 次完成和 29 次同周期总线回复、VM 上下文
192 次检查及两组取指均通过，包括故意损坏参考结果的负对照。短整数回归覆盖 13 个
性能程序、50 个控制/访存程序和 11 个恢复程序；真实 F/D CPU 比对 1212 组 SoftFloat
向量，板级模型检查 32 个浮点上下文寄存器及 Sv39 地址映射。不是全量 ISA 认证、
Linux 浮点调度或物理多时钟板级仿真。

与上一批同口径比较，13 个短整数性能程序周期完全相同；F/D CPU 从 77748 到 77762
周期（+14），板级短程序从 32014 到 32231 周期（约 +0.68%）。浮点请求/回复新增两拍，
已启用的 VM 数据输入边界新增一拍；不能将裸整数核周期不变推广成所有应用 IPC 不变。

2026-10-06 又复用这两版已冻结的真实 RV64GC/cache/AXI 板级模型，没有重新生成模型，
用同一 18140 字节 CoreMark 二进制做单迭代 CRC/tick 对照。
`build/gsim/soc-refactor-coremark-soc-restructure-20261005-r1/receipt.json` 为
`PASS_SAME_BINARY_BOARD_COREMARK_COMPARE`：794923 → 818225 ticks（+2.931%），
同频吞吐比约 0.9715。两版参考 CRC 均通过；代码/模型/固件散列重新核对匹配。
这不是正式 CoreMark 分数、真实 MIG 延迟或 FPGA 实测，不能推广为 Linux 性能。
新频率至少比该旧模型的实际可用频率高 2.931% 才能抵消这一工作负载的代价；
目前两者均不能据未签核的中间时序换算为已验证 Fmax，所以整轮正优化尚待最终判断。

整板 post-synth：214819 LUT / 99337 FF / 44 DSP，相比上一批 214384 LUT / 98634 FF，
LUT 约 +0.203%、FF 约 +0.713%。约占目标器件 LUT 的 63%，是综合值，不是 routed 值。
增加的边界并未造成明显面积膨胀，但剩余 LUT 比例不能保证三发射布线/频率达标。

三处实际生产模块使用 `staged-fetch-feedback`、双发射和 RV64GC 参数完成 10 ns OOC
布线，入口为 `ooo.SocPipelineTimingMain`；报告归档在
`build/fpga/soc-restructure-20261005-r1/module-timing/`。

| 模块 | 内部 setup 余量 | 内部数据路径 | 内部 hold 余量 | LUT / FF |
| --- | ---: | ---: | ---: | ---: |
| FloatingPointMemoryPipeline | +5.587 ns | 4.393 ns，13 级逻辑 | +0.042 ns | 2891 / 1267 |
| DataTranslationAdapter | +4.122 ns | 5.858 ns，21 级逻辑 | +0.045 ns | 2838 / 833 |
| RegisteredFetchPacket | +2.149 ns | 7.746 ns，13 级逻辑 | +0.051 ns | 11753 / 6258 |

OOC 输入/输出 delay=0 是一致的模块比较约定，不是板级接口预算。其全路径 hold 的
-0.080/-0.080/-0.050 ns 来自该零延迟输入边界，不能冒充内部 hold 失败，也不能被
忽略来签核整板；OOC 时钟没有整板实际时钟树的 skew。数据路径数值也不是直接的 Fmax。
仍须检查实际连线后的反馈、时钟和拥塞，模块通过不代表整板通过。

完整候选单独固定在 `E:\VM\Share\Valence-rtl\native-rv64gc-soc-20261005-r1`，
WSL 导出和证据在 `build/fpga/soc-restructure-20261005-r1/`。ROM COE 与上一批完全一致，
可复用 BMG 初始化；新 CPU RTL 不复用旧综合检查点。打包工具新增 `--refactor` 门禁，
必须使用本轮真实 CPU/边界证明；旧批次仅能复用哈希未变的独立 TileLink/IP/bus 依赖，
不得复用旧 CPU 或取指通过结论。16 项打包门禁单元测试通过，不是硬件验收。
2026-10-06 01:09 完成整板布线，最终未通过，未生成 bit。归档
`build/fpga/soc-restructure-20261005-r1/routed-r1/completion.json` 状态为
`RV64GC100_ROUTED_TIMING_NOT_MET`。CPU 时钟域 WNS -1.218 ns、20794 个 setup
失败端点；整板 hold -0.018 ns、2 个失败端点。RGMII TX setup -0.045 ns、hold
-0.018 ns，RX setup +0.142 ns、hold +0.617 ns。所有 266817 个网络布通，DRC
无 error/critical，27 项 bus-skew 均通过；这些不能代替 setup/hold 签核。
最终资源 214168 LUT / 100130 FF / 44 DSP；真实 routed ROM 的 4176 项 INIT/INITP
与 BMG 初始化参考完全相同。实际主机结束时间与性能模型频率仍是不同概念。

只读 routed 长路径报告已归档在同目录 `path-review-r1/`。最差为 line writer
调度队列读指针到 TL 请求边界，11.019 ns，其中路由 10.025 ns；取指反馈
最差 -1.214 ns。store 准备输入来自 owner-ready，最差 -1.217 ns，而已准备 store
输出到依赖检查的定向路径 +1.183 ns；不能把后者误认为仍违例。FP Misc 转换
最差 -1.090 ns、25 级逻辑，另有提交授权到 FPR 写使能 -1.204 ns。

下一批源码已接入寄存化取指 cache window、完整 store 操作数到 AGU 的边界、
HardFloat raw 输入到转换舍入的边界、具有已提交值转发的 FPR 物理写入边界，
以及 line writer 的活动 owner/完整 line/逐 beat payload 寄存。FP 架构提交和原始
FMV 语义不变；Misc producer 新增一拍，store 准备新增一拍，writer 首次发送新增
一拍且接受 beat 目标 II=1。整板物理收益尚未验证。

`build/gsim/soc-window-batch-soc-window-20261006-r2/receipt.json` 已通过必要短验收，
状态 `PASS_SOC_WINDOW_BATCH_AFFECTED_SHORT`。3/5 行取指 window 各 18768 项独立检查，
包含 255 个连续供给周期；FP 状态 7875 周期，FD/F/裁剪三配置各 27840 数值向量，
writer 四在途、乱序 ACK、错误、复用、连续 32 beat II=1 和最后 ACK 相邻启动通过。
正向及故意损坏独立参考的负对照均通过；13 项整数性能、50 项控制/访存、11 项恢复
使用 NEMU。真实 F/D CPU 77762 周期不变，当前板级上下文 32231 → 32244（+13）。
首轮因纯整数性能测试夹具关闭压缩指令但未关闭新 window 而拒绝 elaboration，失败
记录保留；修正夹具后重新 elaboration，隔离模型只有 FIR 散列完全相同才允许复用，
真实 CPU 和板级模型均重新生成。25 项打包门禁单元测试通过，属于工具验收。

性能不是全面正收益：11 项整数周期不变，memory/ALU 混合低延迟 421 → 391，
延迟 12 的竞争场景 865 → 1015（+17.34%）。同一 18140 字节 CoreMark 单迭代
CRC/tick 对照为 818225 → 844297（+3.186%），同频吞吐比约 0.9691，证据在
`build/gsim/soc-refactor-coremark-soc-window-20261006-r2/receipt.json`。这不是有效
CoreMark 分数或真实 MIG/FPGA 测量；需结合合格频率判断频率乘 IPC，不能把切链
直接称为应用性能提升。统一入口 `simulator/gsim/soc_window_batch.py` 只跑必要短检查，
短功能 PASS 不能代替新整板时序，也不能用旧 r1 DCP 为改变后的源码签核。

旧 routed DCP 的 25 组 TX clock/data DRIVE 只读时序复核，没有任何组合使五个 lane
同时满足 setup/hold，连逐 lane 选择也无可行解。报告在 `routed-r1/tx-drive-review-r1/`。
新物理候选解除三个 TX BUFGCE_DIV 的固定 ordinal LOC，保留实际 pad 时钟区域、
clock root、pad/forward delay group、+2 ns 相位、完整 CLR 时序和 1.250 ns PHY 预算，
由整板 placer 选合法站点；该 r2 布局仍未满足全部要求，不是放宽接口要求。整板入口
也不再读取未被 native wrapper 实例化的旧 clk_wiz_eth IP。当前 RTL 已统一导出，
真实新 CPU、改变后的 writer、其余未改变的 IP、ROM 和 PHY 短边界均经过打包门禁。
2026-10-06 02:21:03（+08）启动一次完整新综合/布局/布线，候选为
`E:\VM\Share\Valence-rtl\native-rv64gc-soc-window-20261006-r2`，未复用旧 CPU DCP，
本次实现于 04:05:26 正常退出，约 104 分钟，未生成 bit。冻结输入另存
`build/fpga/soc-window-20261006-r2/staged-inputs.json`；工具的 25 项打包和 7 项
审计单元测试通过，但它们不是时序验收。最终证据为
`build/fpga/soc-window-20261006-r2/routed-r2/completion.json`，状态
`RV64GC100_ROUTED_TIMING_NOT_MET`。CPU setup WNS −0.374 ns / TNS −799.636 ns /
5514 个失败端点，hold −0.030 ns / 3 个失败；整板 setup −0.374 ns、hold −0.054 ns，
分别 5518/7 个失败端点，pulse +0.081 ns。271226 条网络全部布通，27 组 bus-skew
均通过（最小 +3.803 ns），没有 DRC error/critical 或未约束端点。TX setup/hold
−0.092/−0.054 ns，RX +0.161/+0.616 ns，DIV CLR +0.467/+0.723 ns。

最终资源为 217299 LUT / 104590 FF / 44 DSP / 64 RAMB36 / 3 RAMB18 / 0 URAM，
相对 r1 routed 增加 3131 LUT 和 4460 FF；FPU 占 25171 LUT / 8181 FF / 22 DSP。
CPU WNS 从 r1 的 −1.218 ns 改善到 −0.374 ns，失败端点 20794 → 5514，仍不合格。
归档时冻结 candidate/source 没有漂移；后续 r3 主源码修改不属于 r2 的资格证明。

只读实际路径复核归档在 `routed-r2/path-review-r2/`：line writer +2.496 ns，
Store dependency +2.172 ns，Store prepared owner +5.151 ns，prepared payload +1.246 ns，
registered fetch window +0.264 ns。仍失败的链包括系统指令派发、FPU 除法启动、
Store 分类到操作数捕获、桥返回到 AMO/MMU，以及仲裁返回到 CPU response buffer；
多数实际路径约 8.4–9.3 ns 花在路由，并非只剩一个 PMP 模块。

新 r2 DCP 的 25 组 DRIVE 只读扫描也无可行组合，最好的共用配置 clock=6/data=8
仍有 −0.084 ns 余量。逐 lane 选择亦不能全部满足 setup/hold。结果在
`routed-r2/tx-drive-review-r2/`，只改内存对象做时序查询，没有写回 DCP、约束或 bit；
不能把扫描中的某一个正 setup 路径当作 TX 已通过。

2026-10-06 开始 r3 同一结构批次：MachineSystemUnit 完整命令捕获（系统派发 +1 周期），
F/D DivSqrt IEEE→recoded 捕获（除法/开方再 +1 周期），Store 在分配时保存精确类别，
PMP 共享候选 word 比较/平衡最低编号优先级/分片常数加法，以及 TL 返回 source/head
载荷不再由晚到 valid 选择。后三者不增加周期、容量或发射宽度不变；保留完整 F/D、
精确异常、PMP 优先级和 XLEN 溢出语义，没有修改 HardFloat 上游实现。
整批统一编译已通过，必要短验证入口为 `simulator/gsim/soc_return_control_batch.py`，
包含独立 byte-range PMP oracle（2/4 宽、全低位边界）、SoftFloat fd/f/pruned、
TL 乱序/背压/无效载荷扰动、真实 CPU NEMU/恢复、F/D 上下文和同二进制 CoreMark
周期对照。必要短验收已完成，记录为
`build/gsim/soc-return-control-soc-return-control-20261006-r3-resume/receipt.json`，状态
`PASS_SOC_RETURN_CONTROL_AFFECTED_SHORT`，SHA256
`1a804a0ac346cbfd554ed25f58f584cb80667dede82c6a4d61a538f0c870c2af`。
算术 10900 向量，PMP 三个模型各有 30840 个一般边界和 36960 个四字节 execute
检查；均通过独立负例。TL generic/mixed-flow 分别 105/106 次访问，在途容量 8，
后者覆盖 4 个写在途、20 次 head flow、乱序 D、部分字节和无效 D payload 扰动。
fd/f/pruned 各 27840 个 SoftFloat 向量及 illegal/flags/flush/full-token 正负例通过。
50 项控制/访存、11 项恢复及真实 F/D CPU、32 FPR/FCSR/Sv39 板级短检查通过。

最初 r3 验收停在桥负例状态包装：预期 std::runtime_error 已报错，但驱动返回
SIGABRT（−6），脚本当时只接受 1。原失败 receipt、negative.log 和 executed_runner.py
保留；只修正包装状态和严格续跑入口，不改变 DUT/oracle。算术/PMP 已通过模型仅在
全部硬件、参考源码、旧 artifacts 不变且新导出 FIR 字节相同时复用，并重跑正负例；
桥及其余新 CPU/board 从当前源码重新生成。不得把这个包装修正称为发现并修复硬件问题。

13 项整数周期与 r2 全部相同，独立 ALU 1024/515（IPC 1.98835）。同一 18140 字节
CoreMark 镜像仍为 844297 ticks（0% 新增），完整 F/D 密集 CPU 短程序从 77762 →
85117 cycles（+9.458%），61865 次提交相同；板级上下文 32244 → 32326 cycles。
这些是确定的周期代价，不是全面性能正收益；CoreMark 单迭代亦不是有效分数。
新 managed RV64GC RTL 已统一导出 236 个 SV，仍为 issue2/CPU100/UART460800，
尚无本批 routed 时序或 bit，不能用 r2 DCP 为它签核。导出身份清单在
`build/fpga/soc-return-control-20261006-r3/export/receipt.json` 与四份 RTL SHA256 分片。

纯 Scala 检查随后发现两处前批未更新的配置合同：staged-fetch-feedback 的
registeredFetchWindow 已启用，ParallelFetchTagLookup 的合法 offset 已扩至 4，
旧测试却仍期望关闭/拒绝。只修正这两份 Spec，扩展正例并保留非法 offset 5/−1，
默认开关和 ISA 独立性检查保留。全部 `mill -i IonSoC.test` 通过；再次导出的
236 个 SV 与此前短功能验收的导出逐字节相同。所有 DUT、功能参考模型和实际
native CPU proof 输入散列不变，补充证据在
`build/fpga/soc-return-control-20261006-r3/scala-contract-update/receipt.json`，原失败
与原 Spec 也保留。原硬件短验收 receipt 仍是历史原件，其包含旧纯 Spec 的全文件
映射不能当作当前完全未变，打包必须同时验证这份严格补充记录。

TX 进一步做了两批仅固定真实引脚的 OOC 探针，预算始终 1.250 ns。共同钟源、
反相 forwarded clock 加单级 data ODELAY，在 600/800/1000/1100 ps 都未通过 hold；
1100 ps 的最差 setup/hold 为 +0.829/−0.687 ns。互补的单级 clock ODELAY 方案亦未
满足 setup（1100 ps 最差 −0.732/+0.850 ns），两种等价边沿 bias 的全部十条余量一致，
未用 source latency 替代物理传播或修改预算。前者证据已存
`build/fpga/soc-return-control-20261006-r3/tx-single-data-probe/`；后者为同级
`tx-single-clock-probe/`。两批均已终止，无继续运行的 Vivado 整板任务。
两者均不是板级 CDC/STA/bit 资格；生产 wrapper 尚未改为这两个失败的方案。

随后仅在私有 TX 探针中尝试 OSERDESE3 转发时钟：实际共同 PLL500 与 DIV125，
数据仍用 ODDR125，转发时钟串行输出固定字样。短 xsim 检查 3072 字节、四种
控制编码、三轮复位和两次冷启动重锁定，通过数据/控制/相位错误注入负例。
功能模型固定 100 ps CLK→OQ 延迟与物理 STA 分开处理，PHY 预算仍为 1.250 ns。
原语及端口定义见 [AMD UG974](https://docs.amd.com/r/2023.1-English/ug974-vivado-ultrascale-libraries/OSERDESE3)。

真实引脚探针未通过：直接 CLK500 分支最差 setup/hold 为 −1.946/+0.973 ns；
根据实际插入延迟增加同级专用缓冲并配平末级时钟树后，仍为 −0.569/−0.164 ns。
因此拒绝该混合架构，未合入生产 native_rgmii、未启动本批整板实现、未生成 bit。
所有初始工具/相位失败、短检查和两次完成的物理报告保存在
`build/fpga/soc-return-control-20261006-r3/tx-serdes-probe/`；DCP 路径与散列在
`completion.json`。功能相位正确不能替代真实 pad 时序通过。

继续比较了两个只含 TX 引脚的候选，PHY setup/hold 预算都保持 1.250 ns。
DATA4 SDR 使用重复位、CLK250 数据与 CLK500 转发时钟；3072 字节、四种控制编码、
三轮复位/两次重锁定、引脚变化边沿和四个负例通过，实际 10 组重复位共网。
真实布线的最差 setup/hold 为 −1.385/+0.410 ns，仍拒绝接入；证据在
`build/fpga/soc-return-control-20261006-r3/tx-sdr-probe/`。最初的属性解析失败也保留：
Vivado 的反相属性为 `1'b0`，严格解析接受它和 `0`，没有移除架构检查。

DATA8 候选随后使六个 serializer 共用同一真实 CLK500/CLKDIV125/RST 网，
每个半字重复四次，TXC 固定字样 3c。独立检查只允许 raw+2/raw+6 改变数据，
TXC 在 raw+0/raw+4 捕获；3072 字节及数据/控制/相位/重复位/非活动正边沿五个
负例通过。重复位与时钟身份在综合后和布线后都检查；pad-only 的 hold-start
选择下一真实变化边沿，setup 保持原生 2 ns，寄存器和功能复位路径不豁免。
该语法的 launch-edge 方向见
[AMD UG903](https://docs.amd.com/r/2025.1-English/ug903-vivado-using-constraints/set_multicycle_path-Syntax)。
真实布线最差 setup/hold 仍为 −0.254/−0.334 ns，未合入生产顶层；证据在同级
`tx-common-serial-probe/`。两种候选的 OOC 未绑定符号输入和 UI 代理钟不构成
整板 MAC 输入或时钟位置签核；本批 CPU 主源码、固件和功能验收不受这些私有探针影响。

另一种 DATA8 编码跨字携带前一高半字，使数据只在 raw+0/raw+4 变化、TXC f0
在 raw+2/raw+6 捕获。独立 3072 字节检查及六个负例通过，新增负例破坏跨字 carry。
综合和布线后逐项确认五个 carry 的 D 直接接当前高半字 Q，两级同为无条件负边沿
CLKDIV125 FF、复位与 serializer 相同。真实引脚的全部十条 setup/hold 余量却与
前一共 CLK500 编码完全相同，最差仍为 −0.254/−0.334 ns，因此未接入整板。
证据保存在同级 `tx-overlap-serial-probe/`；不继续尝试等价字样或相位旋转，
后续定位范围转为真实 IO 传播、共同钟路径悲观量与物理延迟结构。本批没有新 bit。

r3 打包入口新增严格 return/control 门禁，限定只有前述两份纯 Spec 能以归档原文和
补充散列替换；其余功能输入、实际 native CPU artifacts、236 个 RTL 的两次导出和
固件身份必须一致。旧 writer 只按未变 IP/bus、独立 wrapper/oracle 和执行 artifacts
闭包复用，不引入旧 CPU 证明。相关 50 个打包/audit 单元测试与当前实际输入检查通过，
记录在同级 `intake-gate/receipt.json`。原 bare-core 整数性能日志仍可追溯，但原记录未
封存该 executable，不能临时补造追溯散列或将它当作新 CPU 身份证明；实际 RV64GC
CPU 由已有 native receipt 单独证明。这些门禁不是硬件或板级时序验收。

### ODDR250 生产边界与整板候选

专用 ODDRE1 模式使五个数据/控制 lane 与 TXC 共用同一真实 CLK250。
数据 D1/D2 接同一已选择半字，只在正边沿变化；TXC 输入为同一相位计数器的
相位和反相，只在负边沿变化。实际字节时钟仍为 125 MHz、每拍一字节，TXC
周期 8 ns，相对数据变化为 2 ns。不是把 MAC 降频，也不使用完整 CLK500 DATA8
serializer 模式。原语映射依据见
[AMD ODDRE1](https://docs.amd.com/r/2025.1-English/ug974-vivado-ultrascale-libraries/ODDRE1)。

五个真实管脚的 routed setup/hold 全部为正，PHY 预算仍为 1.250 ns：

| 管脚 | setup 余量 ns | hold 余量 ns |
| --- | ---: | ---: |
| TX_CTL | +0.091 | +0.194 |
| TXD0 | +0.176 | +0.136 |
| TXD1 | +0.129 | +0.169 |
| TXD2 | +0.064 | +0.224 |
| TXD3 | +0.137 | +0.167 |

综合后和布线后都核对六个实际 ODDR 的共同 CLK/RST、五组 D1/D2 共网以及计数器
反相反馈。只排除五个数据/控制 OQ 到 PHY 的非活动负边沿，不豁免寄存器、功能
复位或 CLK250 内部路径；没有 multicycle 或 source-latency bias。十个未绑定符号
输入的 OOC hold 仍为 −1.658 ns；这份私有管脚可行性证明不能签核真实 MAC 输入。
证据在 `build/fpga/soc-return-control-20261006-r3/tx-quarter-ddr-probe/`。

生产 `native_rgmii`、时钟模块、单一 word-clock 复位 epoch 和默认 board top 已接入。
旧时钟模式仍可配置；F/D、issue 和外设开关不变。原 raw125 输入寄存保持完整 8 ns
MAC 周期；本地双半字仅在 raw+6 捕获，防止同一字节高低半字混用。软件仍须在启用
MAC 前读回 PHY TXDLY=0、RXDLY=1，不加入硬件 MDIO 初始化。

实际生产 TX 短测试通过 3072 字节、四种控制编码、三次复位、两次冷重锁定，
6165 次 setup 与 6165 次 hold 眼图检查，以及六个独立错误注入。RX 的原始模块
33.75°/0 ps 配置与外部眼图端点重新验证通过；真实 wrapper 接口综合验证六个
ODDR、DIV4/DIV2 和单一三阶段 TX 复位链。接口测试明确黑盒化 CPU/MIG/IP，
不能当作整板实现。时钟重命名两次仍保留测试 sentinel 引用，61 项门禁单测通过。
生产证据与初始失败尝试归档于同级 `tx-quarter-board/`。新整板候选冻结 561 个文件，
只复用未变 IP；必须重新检查完整时序、CDC/skew/DRC 和 routed ROM 后才可生成 bit。

发布前重新核对旧异步证明：managed-peripheral 的现行证明仍匹配，但较早的
native-GMAC 和 BUFGCE/时钟策略证明有输入散列变化，未直接复用。已从当前源码
重新导出仅 CDC 的 RTL，并完成短 xsim 正/负验证；新结果归档在
`build/fpga/soc-window-20261006-r2/cdc-short/{gmac,clock}/receipt.json`，分别为
`PASS_NATIVE_GMAC_CDC_CLOCK_POLICY_SHORT` 和 `PASS_MANAGED_CLOCK_GATE_CDC_SHORT`。
不重跑 CPU/MAC 引擎或整板时序仿真。本批实际 IP 的全部 32768 个 MIF 字与选定
3061 字节 BootROM 相同，记录为同目录 `bootrom-image-audit.json`；最终 routed
ROM 的全部 4176 个 INIT/INITP 属性已由本批 routed DCP 核对匹配；证据在
`routed-r2/path-review-r2/`，仅证明 r2 身份，后续新 candidate 仍须重新核对。

新增只读 `fpga/zu15eg/review_native_cdc_facts.tcl`，在旧 r1 已完成的 DCP 上核对
8 组板级复位/相位链、33 组 CdcResetRelease、43 组双 FF level 链、20 组 Gray
双级连接，以及 TX/RX 各 38 个实际 RAM payload 捕获端点。MIG RIU_ADDR/RIU_WR_DATA
原始与展开目标集合分别为 84/224，完全相同；早期加载的 empty-set 告警仍需结合
最终 exception coverage 审查，不把集合非空直接当作约束已经生效。证据在
`routed-r1/cdc-facts-review-r3/`。前两次工具名称解析失败保留；修正查找方式，
没有修改 DCP、预算或例外。该调查用于解释结构，不是新候选 CDC 或 STA 签核。
旧 CDC-1 的 txConfig bit3 在 D 端折叠了自身保持、valid、ack 和已同步 request
选择，CE 无独立控制；held→D 要求 8.000 ns、余量 7.444 ns。仍需在本批真实
routed 网表逐项核对，不能因为它属于 mailbox 就笼统忽略关键告警。

验证顺序是完成相关结构批次、统一编译、受影响短 GSIM、覆盖跨模块连接的时序分区，
最后一次整板综合布局布线。模块通过不代表整板通过；任何源码、板级 RTL、约束或
固件变化必须在最终验收中反映，不能用旧报告签核新源码。
bit 的完成条件是整板 setup/hold/pulse 全通过、所有网络布通、约束与 CDC/skew 覆盖
完整、DRC 无禁止发布项，以及 ROM/固件/时钟/波特率和生成 RTL 的散列一致。

双发射 bit 完成后独立评估三发射：真实 CPU 的正确性、依赖/竞争下的 IPC、资源和
时序，再比较频率乘 IPC。当前板级入口只接受二/四宽，三发射尚未支持；不得仅改一个
宽度或生成 RTL 就宣称完成，也不把三发射候选混入本轮的双发射交付配置。
三发射首先保持相同 ISA、缓存、ROB/PRF、固件和编译选项做宽度对照，分别核对
rename、issue、completion、commit 的真实端口能力及同包 RAW/WAW、回滚和背压。
用相同应用与依赖/竞争短程序比较 cycles/IPC，再用合格 routed 频率比较频率乘 IPC，
同时记录 LUT/FF/DSP/BRAM、拥塞及余量；不按二发射资源乘 1.5 估算是否能放下。
逐程序吞吐比按 `(F3 / F2) × (IPC3 / IPC2)` 比较，固定同一程序和编译选项，不以
独立 ALU 理想峰值代替应用收益。比如三发射若只能在 90 MHz 合格、双发射为
100 MHz，则 IPC 必须提升超过 11.1% 才能有吞吐正收益；这是评估门槛的算例，
不是三发射已实现或能达到 90 MHz 的测量结论。

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
- FPGA 封装：`BoardSocTop` 已有板级 RTL、Vivado 原生 ROM/XPM RAM 和集成脚本；
  通用 IP-XACT 封装、自动 BD 和整机时序通过不属于这些代码的隐含保证。

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
通用 `MachinePlatform` 默认关闭 TileLink；可选数据路径为单主，取指路径接入后为双主。
当前 `BoardSocTop`、OpenSBI GSIM 和 Linux GSIM 均开启 TileLink 数据/取指与 Sv39 I/D 译址。
板级另启用 32 行写回 L1、4 项非叶 PTE 缓存及响应缓冲；这些选择不改变通用模块默认值。
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
当成跳转命令。这里的基址是独立 IMSIC IP 参数。当前 `MachinePlatform` / `BoardSocTop`
没有把 IMSIC MSI 页接入 CPU 数据口；APLIC 使用内部 MSI 端口，CPU 通过间接 CSR 与
`mtopei/stopei` 操作中断文件。不能仅凭上述 IP 默认地址在设备树声明 CPU 可写的 IMSIC 门铃。
历史 `FpgaPlatformTop` 也不是当前板级 `BoardSocTop`。

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
M/S 文件电平已接入精确异步陷阱；平台已接 APLIC M/S 域、S 软件中断和 Sstc 定时中断，
VS/虚拟化路径仍待补齐。可选 I/D 译址平台已运行真实 OpenSBI 和 Linux GSIM 启动，
但 Linux AIA 中断设备树/驱动及多 hart SoC 仍不在已完成范围。
具体限制、NEMU 覆盖范围及命令见 [机器核合同](machine-core.md)。原整数基准仍保留异常停止配置。

新增 [MappedMachineCore 数据口映射](core-mmio.md)，程序可直接配置 APLIC；独立控制器接口保持不变。

UART已拆为CPU无关 `soc.ip.uart.UartConsole`，通过RegisterPort接入MachinePlatform，串行中断进入APLIC source3。当前是固定8N1、非FIFO的16550寄存器子集；旧仿真UART保留。见 [UART复用审计与合同](uart.md)。
