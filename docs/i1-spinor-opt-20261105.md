# CPU / VPU 批量 RTL 优化结果（2026-11-05）

> 构建绑定勘误：旧 spinor-opt R2/R3 部分 VPU Scala 修改未进入对应 SV。物理数字仅对应冻结 RTL，不再将改进归因于未编译修改。新系统运行已使用单一显式 classpath target 并绑定 production class；详见 [整机报告](i1-system-hv-20261105.md#构建绑定勘误)。

本批完成一次统一编译、针对性 GSIM 和一次综合/布局布线；CPU、VPU 均改善，总 LUT 降低。**300 MHz 仍未完全收敛：CPU 差 0.072 ns，VPU 差 0.011 ns。** 保留本批作为后续组合优化基线，同时完整保留上一轮组合 r2 与原纯 CPU R12。

## 全部违例与双域时序

上一轮并不是只有一条负路径：全顶层 1432 个 setup 违例端点，包含 CPU 1108、VPU 324。此前给出的路径只是每域最差者；大量端点共用控制链。按每个实际 endpoint pin 的最差路径枚举，不把端点数量误作独立 RTL 问题数量。

| 域 | 原 setup/ns | 本批 setup/ns | 原违例端点 | 本批违例端点 | 本批内部 hold/ns |
|---|---:|---:|---:|---:|---:|
| CPU | -0.347 | -0.072 | 1108 | 15 | +0.010 |
| VPU | -0.190 | -0.011 | 324 | 1 | +0.010 |

总 setup 违例端点从 1432 降到 16；TNS 从 −158.602 ns 降到 -0.584 ns。两域内部 hold 违例均为 0。
CPU 最差反馈为 `core/offerPc_reg[1]`→`core/offerPc_reg[29]/D`，9 级逻辑，3.195 ns 数据延迟（布线 2.394 ns）、skew −0.099 ns。剩余 15 个端点分别为：预测 PC 数据反馈 5、恢复/PC 更新使能 9、ADDR 结果旁路/计算反馈 1。
VPU 最差为 `engine/state_reg[3]`→`engine/state_reg[4]/D`，9 级 LUT 逻辑、无 CARRY8，3.140 ns 数据延迟（布线 2.294 ns）、skew −0.095 ns。原外层整包比较长链已不再是最差路径，当前剩一条访存引擎状态转移违例。

按当前路径、skew、uncertainty 保持不变的线性估算，CPU 为 293.7 MHz，VPU 为 299.0 MHz；这不是重新实现或板上测得的 Fmax，不能当成 300 MHz 通过。

## 布线后资源

| 范围 | LUT | LUT 变化 | FF | FF 变化 | BRAM36 | DSP |
|---|---:|---:|---:|---:|---:|---:|
| CPU + 私有 I/D cache | 24887 | +36 | 15469 | -94 | 16 | 28 |
| Spinor VPU | 19118 | -279 | 12710 | +104 | 0 | 7 |
| 六通道跨域桥 | 188 | -6 | 1498 | +0 | 0 | 0 |
| 访存适配及顶层逻辑 | 5 | +0 | 13 | +0 | 0 | 0 |
| 实际 DUT | 44198 | -249 | 29690 | +10 | 16 | 35 |
| 端口捕获夹具 | 0 | +0 | 787 | +0 | 0 | 0 |
| 实现总量 | 44198 | -249 | 30477 | +10 | 16 | 35 |

总 LUT 44447→44198，减少 249；总 FF 30467→30477，增加 10。CPU 本体 LUT 小增 36、FF 减少 94；VPU LUT 减少 279、FF 增加 104。没有把总面积下降误记为每个模块的每项资源都下降。两版捕获夹具均为 787 FF，BRAM36=16、BRAM18=0、DSP=35、URAM=0。

## 同一批完成的 RTL 修改

- CPU 标签在现有读边沿前比较，捕获每个 bank 的命中位；数据/标签/存在位仍对应同一预取地址，延迟 1、II=1，不新增缓存响应周期。
- RR 操作数数据按本地 RR owner 保持，独立更新 rrCaptured 身份标记，去掉晚到 idFire 对 128 位数据保持使能的限制。
- 下一 PC 的四个候选使用编码后的原生 4:1 选择，减少 C 长度修复信号进入宽数据掩码的层次；重定向、背压和 PC 保持契约不变。
- 原子 MIN/MAX 共享分块无符号比较，符号选择独立于 XLEN 数据归一化；消除 W 操作不需要的宽符号扩展 mux。
- 利用 `−(2p+b)=2(−p−b)+b` 并行准备除法末位的负商前缀，避免最后一次比较/减法再串一个完整取负进位链；无额外 MDU phase。
- VPU 完整结果包、token、指令身份比较采用短 XOR 分组归约；保留原来的整包不变、身份、grant 授权、malformed/poison 检查，没有删除错误检测或缩短 80 位接口。
- VPU VSET 的源格式/AVL 选择前移到现有 command 捕获边沿，复用命令字段；VL/VTYPE 等架构状态仍在原 completion.fire 提交。

未添加 CPU/VPU 流水边沿，程序周期无变化；实际 FF 数量仍会因综合共享和物理优化而变化。四个 VPU 原生文件的本地替换及 `VectorTiming.scala` 在 `integration/spinor/overrides/`；锁定上游 e151f80e1da3a566d1a6ff5157052757fac0ddcb clone 保持干净。`SpinorI1.sources` 的实际编译文件与哈希单独记录，避免只记录上游却遗漏本地修改。完整差异在 Windows `candidate.patch`。

## 功能、IPC 与预测精度

针对性 GSIM 共 13 档：32/64 位 compact/FPGA MDU 和 LR/SC/AMO 共 8 档、数据/指令/32 位/最小缓存共 4 档、65536 组 80/320 位比较与 VSET 源选择 oracle 1 档，均含独立错误注入并通过 ASAN/UBSAN。没有运行全量回归。
真实 CPU+Spinor 独立时钟程序四组和错误值/flags 两类负控制通过；CPU 周期仍为 1453/1715/2625/2871，每组 62 条退休、17 条向量命令、2 个精确异常。覆盖 VS/FS、FCSR、f0、cache 共享、LR/SC 与暂停时钟。周期包含初始化/异常/暂停，不把它解释为向量 IPC 或吞吐提升。
默认关闭 Spinor 的新全 A/C/F/D CPU 模型通过两档 53 条指令/22 次 FP 写回检查；同一新模型运行固定 IM 与真实 C CoreMark，每档完整原始指标均逐字段等于 R12：

| CoreMark 镜像 | 内存首 beat 延迟 | ROI 周期 | ROI 指令 | IPC | 有效 next-PC 预测准确率 |
|---|---:|---:|---:|---:|---:|
| 固定 IM | 1 | 578419 | 345520 | 0.597352438 | 90.95842% |
| 固定 IM | 12 | 735718 | 345520 | 0.469636464 | 90.95842% |
| 真实 C | 1 | 606427 | 345520 | 0.569763549 | 91.78101% |
| 真实 C | 12 | 763350 | 345520 | 0.452636405 | 91.78101% |

真实 C 的条件方向准确率为 49056/53378 = 91.90303%。CRC、退休轨迹、总周期、stall、总线请求/beat、修复和预测计数也全部一致；不是只比较 IPC 汇总。CoreMark 为确定性短评测，formal_score=false，不声称官方 CoreMark 分数。CoreMark 此处用于标量 CPU 的周期保护，不是 VPU 工作负载评测。

## 约束、线程、覆盖与边界

Vivado 2025.2，xczu15eg-ffvb1156-2-i，两域周期均 3.333333333 ns，setup/hold uncertainty=0.100/0.080 ns；HD.CLK_SRC 仍分别为 BUFGCE_X0Y48/Y49。context.xdc 与上一轮逐字相同。没有显式 false path、multicycle、全时钟切断、周期放宽或强制复制/保留属性。原生 ASYNC_REG 属性继续用于同步器。
活动 in-order Tcl 的 general.maxThreads 已设为 8，并写入 AGENTS.md；综合、实现、只读报告均记录 VIVADO_THREADS 8，物理优化日志也明确最大 8 CPUs。上一轮线程上限为 4；本表比较真实实现结果，不把布局差异全部归因于单个 RTL 表达式。
714 个实际跨域端点全部覆盖；最大延迟最小裕量 +2.238 ns，五组总线偏斜最小裕量 +2.007 ns。局部 datapath_only 仅对这些异步路径隐含排除 hold，同步器两级之间保留本域检查。18 条早期同值 DPO 被后次同值刷新覆盖，没有放宽预算。
12 项 check_timing 计数均为 0；65352 条可布线网络全部完成、路由错误 0。explicit gap 仍为 OOC 时钟输入 cpuClock/vpuClock 两条。
CDC 报告仍为 13 条同步器 Info、701 条 held-data 结构 CDC-15 告警和 8 条 raw cold-reset→VPU 复位同步器 PRE 的 CDC-26 告警；48 个复位 FF 的 ASYNC_REG/本域链路另有只读核对。没有把数字 GSIM 或局部物理约束通过升级为完整 CDC/RDC 签核。
全顶层 OOC 外部接口 hold 最差 -2.366 ns、251 个失败端点，pulse width 最小 +1.124 ns。内部 hold +0.010 ns 不能替代外部引脚和板级时钟/复位签核。
本 DUT 仍无 SoC fabric、DDR 控制器、CMU 或外设；H 仍为独立译码基础，CPU H CSR/虚拟化状态/两阶段 MMU 未接入，misa.H/V 不宣告完整扩展。未跑 xsim、bitstream 或板测。

## 下一批目标与证据

下一批围绕现有 16 个端点：CPU 的 BTB/PC 反馈和恢复控制扇出、ADDR 结果旁路反馈，以及 VPU 访存引擎状态转移。保持功能账本、周期、token、提交和背压契约，再做一批 RTL 后统一验证。
R12 继续作为纯 CPU 独立物理对照，本轮没有单独重跑纯 CPU 实现。旧的关闭 Spinor 后 56 个 SV 与 R12 等价证明属于历史版本；本批默认 CPU 已有 RTL 变化，当前证明是新跑的功能/IPC 检查。
完整凭据 `build/i1-spinor-opt-20261105-r1/physical-summary.json` SHA256 `fe4236c02af56cf7795211e8c1ad973fcd1255807116be13ecffd1785741127b`。
Windows 复核根：`E:/VM/Share/Valence-rtl/Valence-InOrder/spinor-opt-20261105-r1`；含冻结源码、RTL、candidate.patch、四份功能凭据/日志/oracle、原组合全负路径清单、新 routed.dcp、当前全部负端点、模块报告及同值约束审计。
收集命令 `python3 fpga/inorder/collect_spinor_ppa.py --variant opt --revision 20261105-r1` 只读现有结果，不重复实现。所有综合/实现输入与 180 份导出来源、212 个 SV、173 个模型/导出共同来源逐项匹配，当前生产代码无漂移。
