# CPU + Spinor 双时钟布线结果（2026-11-04 启动，11-05 完成）

本轮完成一次组合布局布线；CPU 与 VPU 为独立时钟域，各约束 300 MHz。CPU setup −0.347 ns、VPU −0.190 ns，内部 hold 均 +0.010 ns，**两域均未收敛到 300 MHz**。单独保留原标量最佳 R12，不用组合结果覆盖它。

## 内部时序

| 域/版本 | setup/ns | hold/ns | 同路径线性频率估算/MHz | 300 MHz |
|---|---:|---:|---:|---|
| 标量 R12（原独立实现） | −0.111 | +0.010 | 290.3 | 未通过 |
| 组合内 CPU 域 | -0.347 | +0.010 | 271.7 | 未通过 |
| 组合内 VPU 域 | -0.190 | +0.010 | 283.8 | 未通过 |

线性估算保持当前路径、skew、uncertainty 不变；不是重新实现得到的 Fmax。表中内部时序按各域寄存器/RAM/DSP 起点与终点查询，包括本域 CDC 接收逻辑，不包括外部引脚到捕获寄存器。

## 布线后资源

| 范围 | LUT | FF | BRAM36 | BRAM18 | DSP |
|---|---:|---:|---:|---:|---:|
| CPU（含 A/C/F/D、32KiB I/D cache） | 24851 | 15563 | 16 | 0 | 28 |
| Spinor VPU | 19397 | 12606 | 0 | 0 | 7 |
| 六通道 CDC 边界 | 194 | 1498 | 0 | 0 | 0 |
| 访存适配与顶层剩余逻辑 | 5 | 13 | 0 | 0 | 0 |
| 实际组合 DUT | 44447 | 29680 | 16 | 0 | 35 |
| 外部端口捕获夹具 | 0 | 787 | 0 | 0 | 0 |
| 实现总计 | 44447 | 30467 | 16 | 0 | 35 |

R12 总计 24604 LUT、16242 FF、16 BRAM36、28 DSP，其中捕获夹具 1015 FF、CPU 本体 15227 FF。本轮夹具为 787 FF，因此总量差值不能直接当成 V 扩展的独立成本。按 CPU 层级，本轮相对 R12 增加 247 LUT、336 FF；布局上下文、端口可见性及控制逻辑均有差异，尚无同配置独立 A/B 实现。小型访存桥经自然展平，归入顶层剩余逻辑，不伪造独立零资源行。

## 实际关键路径与下一批 RTL 目标

CPU：`dcache/bankedTags/hits_readRow_6_reg[4]` → `core/idPacket_pc_reg[55]/CE`。12 级逻辑，数据路径 3.209 ns，其中逻辑 0.746 ns、布线 2.463 ns，时钟 skew −0.275 ns。优先处理 cache 命中/返回控制向前端流水使能的长反馈，避免盲目给运算数据再加级。

VPU：`vector/core/vpu/engine/state_reg[1]` → `vector/state_reg[1]/CE`。18 级逻辑，含 10 个 CARRY8；路径经过异常/返回信息选择、`SpinorIsolated` 的 `unchanged` 整包比较和外层完成状态使能。数据路径 3.214 ns，逻辑 0.952 ns、布线 2.262 ns（70.376%），skew −0.114 ns。该路径全在 VPU 域内，没有跨越 CPU 时钟域，也不是乘加运算器的最差路径。后续优先缩短隔离层的完成反馈，保留所有权和提交检查；本轮没有修改上游 VPU 或删除检查。

布线占比是本路径的组成，不代表 70% 的退化由集成新增。版本、接口和物理上下文各自的贡献仍需同配置独立对照量化。

原模块路径组有三个在优化后为空，已从同一 `routed.dcp` 按实际模块端点补报，未重新布局布线或改变约束：

| 终点模块 | 最差 setup/ns |
|---|---:|
| CPU | -0.347 |
| Spinor | -0.190 |
| CDC 边界 | +0.299 |
| MDU | -0.153 |
| I-cache | +0.075 |
| D-cache | -0.156 |

模块端点报告包含跨模块来源，不能当成独立模块实现的 Fmax；域级报告才是上述 CPU/VPU 内部时序判据。

## 为什么旧 VPU 的 300 MHz 结论不能直接沿用

可追溯旧凭据为 Spinor `reports/local-m53-resume/evaluation.md`：M53 标准顶层，同一 `xczu15eg-ffvb1156-2-i`，Vivado 2025.1，内部 setup +0.090 ns、hold +0.042 ns，18085 LUT、12490 FF、2 BRAM36、7 DSP。该 OOC 结果未指定 HD.CLK_SRC，外部输入/输出未设 IO delay。旧结果继续有效，不改写成失败。

本次我选用锁定 M61 源码的 `SpinorIsolated(hostFcsr=true)`，具有 preview/grant/done 隔离和整包一致性检查；同时使用 Vivado 2025.2、双域时钟源位置模型、完整端口捕获及组合布局。该条件不是原 M53 标准顶层的同配置复现。当前只能确定上述新增接口完成链是本次瓶颈，不能仅凭本轮认定相同 M61 独立实现也失败，或把差值全部归因于 CPU 布局竞争。

## CDC、覆盖和 OOC 边界

- 实际跨域端点 714 个：CPU→VPU 429、VPU→CPU 285；全部在局部约束范围内。最大延迟最小裕量 +2.233 ns，五组总线偏斜最小裕量 +2.015 ns。
- 701 个保留数据位采用 held/captured mailbox；13 个控制同步器均为两级 ASYNC_REG，源为本域 FF。未消费的 preview 数据位自然裁剪，握手保留；常量 hartId 等位也允许自然裁剪，不加保留强制。
- 无显式全时钟切断、false path、multicycle 或周期放宽。局部 `set_max_delay -datapath_only` 隐含排除这些异步路径的 hold；同步器两级之间仍检查本域 setup/hold。18 条旧 DPO 约束被物理优化后同值刷新覆盖，实际预算仍为 3.333333333 ns，不是 18 条漏约束。
- CDC 报告保留 701 条 CDC-15（held-data/使能控制结构）及 8 条 CDC-26。后者原文标签为 LUTRAM potential collision，实际全部为 `commonColdReset`→VPU 域复位同步器 PRE。只读检查确认 48 个复位 FF 均有 ASYNC_REG，三段链在本域连接；未做板级冷复位/RDC 签核，不将告警静默豁免。
- `check_timing` 的 12 类覆盖计数均为 0，未发现缺失时钟、缺失 IO delay、未约束内部端点或组合环。65253 条可布线网络全部完成，路由错误 0；两条 explicit gap 为 OOC 输入 `cpuClock`、`vpuClock`，不宣称板级无间隙布线。
- 全顶层 hold 最差 −2.374 ns（251 个失败端点），示例为 `io_time[32]`→端口捕获 FF，使用合成的输入最小延迟 0。此 OOC 外部接口未签核，不能用内部 hold +0.010 ns 掩盖它；全顶层 setup −0.347 ns，pulse width +1.124 ns。
- 时钟周期均 3.333333333 ns，setup/hold uncertainty 为 0.100/0.080 ns；CPU/VPU HD.CLK_SRC 分别 BUFGCE_X0Y48/Y49，仅表示 OOC 时钟源位置模型，不代表板上 PLL/时钟树签核。
- 仍无 SoC fabric、DDR 控制器、外设或 CMU；CPU 私有 cache 与 VPU 单事务访存适配属于此 DUT。H 仍仅独立译码已测，H CSR/虚拟化状态/两阶段 MMU 未接入，misa.H/V 不宣告完整扩展。

上述异步约束语义依据 [AMD UG903 2025.2](https://docs.amd.com/r/2025.2-English/ug903-vivado-using-constraints/Constraining-Asynchronous-Signals) 与 [UG835 set_max_delay](https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/set_max_delay)。

## 源码与功能证据

VPU protocolError 先在源域注册，再进入两级同步；r1 仅保留诊断综合，没有进行实现。所选 r2 使用修正后的 r3 功能凭据；四组真实 CPU/Spinor 独立边沿定向程序、两个值/flags 负控制及 ASAN/UBSAN 通过，四组周期 1453/1715/2625/2871。这些周期包含初始化、异常与时钟暂停，不当成向量 IPC 或吞吐指标。

170 份导出源码、212 个 SV（含 verification 子目录）、综合检查点、实现 Tcl/XDC 和 161 个功能生产依赖逐项核对；当前生产源码与冻结输入无差异。上游 Spinor 与默认 GSIM clone 保持原样；独立边沿 GSIM 使用已验证的可选补丁版本。关闭 Spinor 的原 56 个标量 SV 与 R12 的正规化等价证明继续保留。

完整采集凭据：`build/i1-spinor-ppa-20261104-r2/physical-summary.json`，SHA256 `6d42be18acdce0e3e4c79777d261d5de21671119fb60d4b04671408437f3ef8f`。
Windows 复核目录：`E:/VM/Share/Valence-rtl/Valence-InOrder/spinor-ppa-20261104-r2`。关键文件为 `physical/{cpu,vpu}_setup.rpt`、`physical/{cpu,vpu}_hold.rpt`、`physical/routed.dcp`、`audit/*_module_setup.rpt`、`physical-summary.json`、`implementation-inputs.json` 和 `source-at-export/`。

采集入口 `python3 fpga/inorder/collect_spinor_ppa.py --revision 20261104-r2` 只读取现有冻结结果；复位/模块/间隙核对使用 `spinor300_audit.tcl` 只读打开检查点，没有重复综合、布局布线或生成 bitstream。
