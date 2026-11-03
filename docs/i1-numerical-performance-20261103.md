# Orbital-I1 顺序核首批性能开发与真实程序评测（2026-11-03）

固定基准为 `08dfdeacc4de76e210959b544a18cf1b2259fb10`，工作分支为 `dev/a1-inorder-opt-20261103`。搭建时在所查询的 `Surplars/Valence` origin 中未找到 `dev/a1-coexisting-load-ingress-20261027` 引用；没有证据判断删除、改名或其他远程的情况。分支直接从用户指定完整 SHA 建立。

工作根严格为 WSL `/home/openion/Valence-InOrder` 和 Windows `E:\VM\Share\Valence-rtl\Valence-InOrder`。源码、参考快照、缓存、临时文件、日志、生成模型均留在 WSL clone 内；Vivado/xsim、RTL、DCP 和物理报告留在 Windows 根内。代码只涉及活动顺序核及其验证入口，没有改动 OoO、历史核或官方 CoreMark 算法。

本批默认实现缩短了 tiled MULW 的延迟，并移除了除法反馈寄存器的高扇出共用使能。官方 CoreMark 的 ROI 指令流、CRC 和最终内存一致，IPC 提升 1.625% / 1.277%。MDU 内部布线时序明显改善，实际面积基本持平；当前约束仍未闭合，不能据此宣称整核提频或上板通过。

默认 MDU 的接口和模块契约：

- 一个 EX 事务所有者，容量 1；请求只在 idle 且无 kill 时接受，没有旁路接单，没有增加 CPU 流水级。
- 完成状态来自寄存器；响应在 backpressure 时保持数据和所有权，kill 在时钟边沿优先清除所有权。完成状态与取消后的 VALID 分开使用，修复基准 compact5 M/FP 完成与重定向之间的组合环。
- RV64 `dsp-tiled` MULW 接受至响应延迟 4→3 周期；全宽 MUL/MULH 仍为 4，RV32 为 3。普通 RV64 DIV/REM 为 65 周期，W 运算和 RV32 为 33。上述均为固定 always-ready 的实际接口观测周期。单所有者下一次接受还需消耗响应并返回 idle，不能把这些延迟当成 II=1。
- quotient/remainder/count 在无所有权时可自由更新，`request.fire` 初始化覆盖默认更新；迭代乘法的专有更新优先。状态及有效结果的所有权仍受握手/kill 控制。此变化可能影响动态功耗，本批未测功耗。
- `I1RestoringDivideStep` 是无状态组合子模块，容量 0、无 ready/valid，用一次扩展减法同时得到借位和余数。覆盖 32/64 位的完整窗口（包含零除数）。
- `fastDivision=false` 保持默认。可选零被除数、零除数和 ±1 除数短路径为 2 周期，普通除法不变。合成压力程序收益不能替代应用收益：此选项在本次 CoreMark 上额外收益为 0，早期候选还增加面积，因此不提升为默认。

独立 `OrbitalI1.test` 现在只排除两份需要 `soc.platform` 的平台 fixture，它们仍留在完整 `IonSoC.test`。测试用子类观察真实流水中的预测及分支解析；生产顶层没有新增观察端口、计数器或状态。缓存评测仍使用实际 `FiveStageCachedCore` 缓存及总线连接。

官方 [EEMBC CoreMark](https://github.com/eembc/coremark/tree/1f483d5b8316753a742cbf5590caf5bd0a4e4777) 固定为 `1f483d5b8316753a742cbf5590caf5bd0a4e4777`，源目录 Git 状态干净。GCC 13.2.0，`-O3 -march=rv64im_zicsr_zifencei -mabi=lp64`，2000 字节、1 次迭代；所有模型复用同一二进制（16368 字节），SHA256 为 `bc0bc1c5b5fdd7b4960b6e472d0a5d7aaf75eca748fdf7cd669904d1b2aba43b`。

核配置为 RV64IM / fpga8 / timing-cuts / dsp-tiled，32 KiB I-cache + 32 KiB D-cache，64 字节缓存行，直接映射、精确写穿，128 项 tagged bimodal BTB。外存使用相同的双端口 round-robin burst 服务、每端口一个所有者，首 beat 延迟分别为 1/12 周期，后续每 beat 1 周期。两个定时器读取之间为 ROI，退休指令均为 **345,520**。

| 外存首 beat 周期 | 原 MDU ROI 周期 | 默认新版 ROI 周期 | 原 IPC | 新 IPC | IPC 增益 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 587,628 | 578,232 | 0.587991 | 0.597546 | +1.625% |
| 12 | 744,925 | 735,529 | 0.463832 | 0.469757 | +1.277% |

两种服务均减少 **9,396 ROI 周期**。整个程序退休 367,146 条，trace FNV64 为 `d48f4ba8fdb10bb`。每条退休指令均与独立软件 ISA oracle 比较；四个已知 CRC 为 `e9f5/e714/1fd7/8e3a`，CRCfinal 为 `e714`，最终 RAM 逐字节一致。whole-run MDU stall 从 38,100→28,603，这一计数覆盖初始化/校验，不能与 ROI 周期差直接等同。fastDivision=true 的两行 CoreMark 结果与默认新版完全相同。

这是一轮有独立正确性检查的短程序比较，没有达到正式 CoreMark 计分运行时长，端口不提供正式秒数换算，故不发布 CoreMark/MHz 或正式分数。本轮未运行 RTOS、完整 SoC 启动、Linux、bit 生成或上板。

CoreMark ROI 分支预测基线（所有 MDU 版本一致，本批未改预测器）：

| 指标 | 分子/分母 | 准确率 |
| --- | ---: | ---: |
| 实际 next-PC 预测正确 | 52,966 / 58,231 | 90.9584% |
| 条件分支有效方向正确 | 48,684 / 53,378 | 91.2061% |
| 返回类目标正确 | 1,213 / 1,374 | 88.2824% |
| 其他间接跳转目标正确 | 1,332 / 1,378 | 96.6618% |
| 各静态 PC 前 8 次后 | 51,851 / 56,818 | 91.2581% |

ROI 分支 MPKI 为 15.2379。方向统计按 next-PC 是否等于 fall-through，排除目标本身等于 fall-through 的条件分支。返回类按 `JALR rd=x0, rs1=x1/x5, imm=0` 分类，不能视为已验证 RAS。预测来自真实所有者携带的 next-PC，在解析和退休两个边界核对；寄存器期望来自独立 ISA oracle。BTB 关闭时四字节顺序预测为隐式 PC+4，不能把未使用的零载荷误算为预测。

最主要的 CoreMark 静态分支失误位置如下，保留分母供下一批按反汇编定位；不能把多个循环的聚合准确率当成单个困难分支的准确率。

| PC | ROI 次数 | 错误数 |
| --- | ---: | ---: |
| 0x80001b48 | 2916 | 328 |
| 0x80001c60 | 2916 | 325 |
| 0x800028a0 | 320 | 320 |
| 0x8000273c | 1304 | 312 |
| 0x80002744 | 1312 | 272 |
| 0x800026a4 | 864 | 241 |
| 0x800028b0 | 400 | 217 |
| 0x800026b0 | 432 | 216 |

另外完成 9 个短 workload × BTB 关闭/128 × 固定存储延迟 1/7，共 36 个样本。以下为 BTB128、延迟 1 的数据。whole IPC 含填充/排空，retirement-window IPC 从首个至最后一个普通退休计数。

| workload | whole IPC | retirement-window IPC | 聚合 next-PC 准确率 |
| --- | ---: | ---: | ---: |
| alternating_direction | 0.426514 | 0.429049 | 49.80% |
| alternating_indirect | 0.490159 | 0.495189 | 65.62% |
| alternating_return | 0.558824 | 0.563736 | 79.22% |
| alu_dependent | 0.941176 | 1.000000 | — |
| alu_independent | 0.941176 | 1.000000 | — |
| dependent_load_store | 0.545763 | 0.553265 | 98.44% |
| fixed_return | 0.946903 | 0.969789 | 98.96% |
| lfsr_direction | 0.756211 | 0.759988 | 74.80% |
| predictable_loop | 0.970996 | 0.990991 | 99.22% |

交替方向静态 PC `0x80000010` 热身后正确率为 0%，交替返回 PC `0x80000020` 热身后为 50%，交替间接目标正确率为 0%；聚合统计包含容易预测的回边。恢复指标是 redirect 解析到第一个目标指令退休的时间，含流水传播与服务等待，不是纯粹损失周期。每个样本核对 redirect、退休错误、恢复次数和逐 PC 分母。

物理验证使用 Vivado 2025.2、`xczu15eg-ffvb1156-2-i`，真实单时钟 3.333 ns，setup uncertainty 0.100 ns，输入/输出 max=0.333 ns、min=0 ns，并使用同一明确外部 BUFGCE 位置假设。`numerical_timing.tcl` 将 divide_feedback、numerical_result、numerical_control 分组，各组同步 max-delay 3.000 ns（保留 0.333 ns），其余路径保留原时钟；没有增加 false path、多周期或虚构时钟。

配对普通流程为相同 synth/opt/place/phys_opt/route Default。参考 RTL、时序 helper、器件/时钟/接口契约一致，旧参考 DCP 只读复用。额外一次配对后处理只对两侧 DCP 各运行相同 AggressiveExplore + Explore，不重新综合、不更改约束。两组结果分别保留，不能挑选不同流程两侧拼成比较。

| 同流程角色 | 内部 setup ns | 内部 hold ns | 全路径 setup ns | 全路径 hold ns | CLB LUT | FF | DSP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| route_reference | -1.591 | +0.019 | -2.071 | -2.246 | 1433 | 729 | 16 |
| route_default | -0.137 | +0.021 | -0.302 | -1.260 | 1432 | 729 | 16 |
| postroute_reference | -1.338 | +0.012 | -1.775 | -2.246 | 1438 | 729 | 16 |
| postroute_default | -0.249 | +0.021 | -0.305 | -1.260 | 1438 | 729 | 16 |

普通流程内部最差 setup 改善 1.454 ns；divide_feedback 从 −1.591→+0.098 ns，result 从 −0.144→+0.023 ns，control 仍为 −0.137 ns。一次相同后处理未使新版闭合（control −0.249 ns），保留普通流程较好的新版 DCP。CLB LUT 为 1433→1432，可判定面积基本持平，不能宣称显著降面积；`get_cells REF_NAME=LUT*` 的映射 cell 数与实际 CLB LUT 占用不同，不能混用。

所有已报告设计均无无时钟寄存器、无未约束内部端点、无缺失输入/输出 delay，布线错误为 0。但 OOC 接口仍有 setup/hold 违例（见全路径列），内部数值组也未全部通过。**本批物理状态是未收敛**，不能推算整核 Fmax；后续应在实际上下游时钟/接口和整核环境验证。

早期同时常开短路径的候选 CLB LUT 为 1573，参考为 1433，且 CoreMark 未受益，未采用。另一个旋转商方案内部 setup −2.222 ns，已撤回源码。历史失败证据保留，不覆盖成功收据。

当前验收范围：配置 20/20、平台 quiesce 1/1；32/64 restoring-step 各 12,072 个独立样本；MDU 算术/hold/kill/warm-reset + compact5/fpga8 原/默认/可选实现合计 14 个正模型及 14 次故障注入拒绝；性能 36 个样本和 4 次故障注入拒绝；CoreMark 6 个正例和 6 次寄存器/预测观察故障注入拒绝。默认 DSP（非 tiled）compact5 也通过独立短 ISA 检查与负控。GSIM C++ 使用 ASan/UBSan。没有运行全量 GSIM。FP 取消接口的 Scala/平台展开已覆盖，但本批没有重跑完整 FP 数值验收。

参考 MDU 来自固定基准的原始 3 个 class 文件，JVM class-load 日志核对来源，不依赖编译顺序猜测。原 CPU 在修复前有完成/取消组合环，因此 CPU 比较两侧都使用相同的修复后 CPU，仅替换原/新 MDU；它不是“原始未修复整核可以运行”的声明。新增的 `prepare_numerical_reference.py` 从固定 Git archive 在 clone 内重建参考，两份参考源码及 class 哈希逐项一致。

本机复现入口（必须先载入环境；输出标签始终使用全新目录）：

```bash
cd /home/openion/Valence-InOrder
source .local-dev/env.sh
python3 -B simulator/gsim/inorder/prepare_numerical_reference.py --output build/NEW-reference
mill -i -j 2 OrbitalI1.test.compile
mill -i -j 2 show OrbitalI1.test.runClasspath
mill -i -j 2 OrbitalI1.test.testOnly inorder.FiveStageConfigSpec
mill -i -j 2 IonSoC.test.testOnly inorder.I1ExternalQuiesceSpec
python3 -B simulator/gsim/inorder/numerical_acceptance.py --reference build/NEW-reference/reference.json --output build/NEW-numerical --rtl-output /mnt/e/VM/Share/Valence-rtl/Valence-InOrder/NEW/rtl
python3 -B simulator/gsim/inorder/performance_acceptance.py --output build/NEW-performance
python3 -B simulator/gsim/inorder/numerical_coremark.py --reference build/NEW-reference/reference.json --output build/NEW-coremark
```

CoreMark 源码预期已在 `simulator/build/coremark-src`，固定到上述 pin 且没有本地修改。工具环境为 Java 17.0.20.1、Mill 1.1.7、Scala 2.13.17、Chisel 7.3.0、firtool 1.135.0、Clang 19、GCC RISC-V 13.2.0；使用项目修复 GSIM（不是 pristine 诊断版），SHA256 `503dad6a496ba72e9c32044bee2843f194cf88dea719f40476fe337e4045c413`。`performance_acceptance.py` 使用显式 fastDivision=true 的算术配置，但这些分支/访存 workload 没有 M 指令；默认配置的真实应用指标来自 CoreMark default。

Windows 局部综合复现需先载入指定根内的 `tools/env.ps1`，将仓库 `fpga/inorder/numerical_*.tcl` 拷到该次证据目录的 tools，所有日志、journal 和 cwd 均设在该根；`numerical_ooc.tcl PAIRED_RTL_ROOT FRESH_REPORT_ROOT 3.333` 默认比较 reference/candidate，`default-only` 可复用已冻结的参考 DCP。后处理为 `numerical_postroute.tcl REFERENCE_DCP DEFAULT_DCP FRESH_REPORT_ROOT`。真实运行参数及结果哈希见相邻 JSON，不需要重复实施来查询已有 DCP。

证据根为 WSL `/home/openion/Valence-InOrder/build/i1-numerical-20261103-r1`（当前 `acceptance-r5`、`performance-r5`、`coremark-r2`，另有 `reproduced-reference`）和 Windows `numerical-20261103-r5`（旧参考在 r2）。相邻 JSON 保存源文件 SHA256、完整结果收据 SHA256、编译器/二进制元数据、精简 CoreMark 数据和物理报告哈希；原始日志、生成模型及 DCP 不进入 Git。源码冻结核对：数值/性能各 111 文件、CoreMark 116 文件均匹配。提交整理时仅去除 i1_prediction_metrics.h 末尾的多余空行；相邻 JSON 保留测试时和提交时的两个 SHA256 及精确字节变换，此纯格式修改未重复运行硬件验收，其他文件仍完全匹配。

下一批应先按真实 CoreMark 的热点失误分支、返回与 LSU 等待定位收益，再比较策略/面积代价；模块约束继续扩展到 IF、LSU、缓存与恢复控制。当前 stale bscan_qualification fixture 的内部信号不匹配仍保留为已知问题，两项 xsim 环境冒烟不能当作完整 CDC 通过。RTOS 的中断、定时器、任务切换和同步语义尚需独立验收。
