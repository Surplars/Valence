# Orbital-I1 第二批：分 bank 训练与同容量 BTB 索引折叠（2026-11-03）

本批基准为首批提交 `e2039094f3665af5e9ab73876f94e041a3319179`，分支仍为 `dev/a1-inorder-opt-20261103`，原始固定起点 `08dfdeacc4de76e210959b544a18cf1b2259fb10` 保持为祖先。工作根严格为 WSL `/home/openion/Valence-InOrder` 与 Windows `E:\VM\Share\Valence-rtl\Valence-InOrder`。首批数值单元的结果及限制见 `docs/i1-numerical-performance-20261103.md`；本批物理范围仅为预测器与一致的测试捕获寄存器。

CoreMark 反汇编和逐 PC 统计显示，直接索引让 `0x800028a0` 与 `0x800026a0`、`0x800004a0` 共用槽，前者 320/320 次错；`0x800026b0`、`0x800028b0` 也共用槽，合计 433 次错。本批在相同 CPU、缓存、MDU 和存储服务下比较三个版本。

| 角色 | 训练反馈 | 索引 | 表项 |
| --- | --- | --- | ---: |
| reference | 首批原结构 | 原直接/半字折叠 | 128 |
| local | 各 bank 本地读标签、计数器和写有效位 | 原索引 | 128 |
| hashed | 同 local | 再 XOR 一个上位 PC 分片 | 128 |

默认采用分 bank 训练结构；`hashedBranchIndex=false` 保持默认，需显式 `--predictor=128 --hashed-branch-index` 选择折叠。表容量、完整标签及目标宽度、RAM 载荷位数不变，没有增加 CPU 流水级、RAS、方向历史或 speculative training。原宽 training Entry 先跨 bank 选择再比较并回扇；本地结构把这些反馈各自留在 bank 内，并把有效位更新拆为等容量的各 bank 更新。

模块契约为组合查表、每周期可训练一个退休事件、无训练队列或反压。查表与训练允许同周期，查表观察边沿前的有效元数据；invalidate 在边沿清除全部有效位，优先于同周期训练，写 RAM 载荷不等于获得有效所有权。压缩长度、全 PC 标签、饱和、false-control 清除和 warm reset 保持原行为。XOR 的上位分片已存在于完整 tag，在合法对齐 PC 上，给定 tag 时索引可逆；原 C 折叠仍保留 bit1，不会丢掉用于区分地址的位。哈希只重分配冲突，不能保证所有程序获益。

独立完整 PC 账本检查公开输出，没有把 DUT 标签编码或解码函数当作 oracle。reference/local 的对应微基准、逐 PC 统计、CoreMark 和原 ISA 周期完全相同。参考类从固定 Git archive 独立重建，JVM class-load 日志核对实际来源；reference 重新测得的 CoreMark 与首批冻结收据逐项一致。

官方 CoreMark 固定 `1f483d5b8316753a742cbf5590caf5bd0a4e4777`，源码无修改；继续复用同一 GCC 13.2.0 `-O3` RV64IM 二进制、2000 字节、1 次迭代。SHA256 为 `bc0bc1c5b5fdd7b4960b6e472d0a5d7aaf75eca748fdf7cd669904d1b2aba43b`。核为 RV64IM fpga8 / timing-cuts / dsp-tiled，32 KiB I/D、64 字节行、直接映射精确写穿、BTB128；外存双端口 round-robin，首 beat 1/12 周期，后续每 beat 1 周期。

| 首 beat 周期 | 上一版 ROI 周期 | hashed ROI 周期 | 上一版 IPC | hashed IPC | 增益 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 578,232 | 574,645 | 0.597546 | 0.601276 | +0.624% |
| 12 | 735,529 | 731,942 | 0.469757 | 0.472059 | +0.490% |

ROI 均为 345,520 条退休指令，每种服务节省 3,587 周期。全程序退休 367,146 条，trace FNV64 `d48f4ba8fdb10bb`。各版 CRC 匹配已知值，最终 RAM 均逐字节匹配各自的独立 oracle；计时结果允许随周期改变，不要求不同版本的计时字段相同。每条退休指令均有独立 ISA 对照。相对第一批原 MDU 参考（两侧均采用修复后 CPU）累计 IPC 增益约 2.259% / 1.774%；不能理解为原始存在组合环的整核直接可运行。短程序没有达到正式 CoreMark 计分时长，不发布正式 CoreMark/MHz。

| CoreMark ROI 指标 | reference/local | hashed |
| --- | ---: | ---: |
| next-PC 正确 | 52966/58231 (90.9584%) | 53564/58231 (91.9854%) |
| 有效方向正确 | 48684/53378 (91.2061%) | 49120/53378 (92.0229%) |
| 返回类目标正确 | 1213/1374 (88.2824%) | 1210/1374 (88.0640%) |
| 其他间接目标正确 | 1332/1378 (96.6618%) | 1205/1378 (87.4456%) |
| 分支 MPKI | 15.2379 | 13.5072 |

总体少错 598 次，但返回少正确 3 次，其他间接少正确 127 次。方向按 next-PC 是否等于 fall-through，排除目标本身等于 fall-through 的分支；返回类按 JALR rd=x0、rs1=x1/x5、imm=0 分类，不能当作 RAS 已验证。热身排除各静态 PC 前 8 次退休；redirect 到目标退休的延迟包含传播和服务等待，不是纯损失周期。不能把总体改善宣称为每种指标均改善。

| PC | ROI 次数 | 旧错误 | hashed 错误 |
| --- | ---: | ---: | ---: |
| 0x800028a0 | 320 | 320 | 1 |
| 0x800026b0 | 432 | 216 | 1 |
| 0x800028b0 | 400 | 217 | 2 |
| 0x800028f4 | 176 | 104 | 4 |
| 0x80000870 | 26 | 25 | 6 |
| 0x80000270 | 110 | 14 | 2 |
| 0x800029e8 | 512 | 3 | 100 |
| 0x80002698 | 1024 | 88 | 176 |
| 0x800007e8 | 79 | 7 | 31 |
| 0x8000024c | 15 | 1 | 15 |
| 0x800001e4 | 110 | 2 | 14 |
| 0x80000858 | 110 | 4 | 16 |

本批短验收为 7 个预测器模型（32/64 位、最小 2/最大 1024 项、C 长度、无 timing-cuts、同槽读写、连续训练、完整标签、候选掩码、饱和、false-control、失效和 warm reset），3 个原独立 ISA/bus 核模型，3 版本 × 9 workload × 2 固定延迟 = **54 个 IPC/预测样本**，6 个 CoreMark 正例。另有配置 21/21、平台 quiesce 展开 1/1，以及 22 次故障注入拒绝：7 predictor、9 bare ISA/store/prediction、6 CoreMark。C 覆盖仅针对预测器模块。9 个短 workload 的对应性能均不变，小 footprint 没暴露本次索引冲突；不能将 CoreMark 收益当作通用 IPC 增益。三者原 ISA 对照均为 1244 退休、low 20,044 / blocked 24,336 周期。

<!-- PHYSICAL_RESULTS -->
三组同流程实现均完成。同步内部路径限定在寄存器/分布式 RAM 的状态边界，另外保留全部 I/O 路径结果；没有通过时序例外隐藏接口违例。

| 角色 | 同步 setup ns | 同步 hold ns | CLB LUT | FF | lookup setup ns | 全路径 setup ns | 全路径 hold ns |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| reference | -1.411 | +0.010 | 1535 | 428 | +0.044 | -1.411 | -2.597 |
| local | -0.810 | +0.011 | 1595 | 431 | +0.149 | -0.810 | -2.244 |
| hashed | -0.740 | +0.010 | 1582 | 388 | -0.012 | -0.740 | -2.095 |

bank-local 的实际 CLB LUT 增加 60（3.909%），同步最差 setup 改善 0.601 ns；组合候选增加 47 LUT（3.062%）、FF 减少 40，同步 setup 改善 0.671 ns。上述是当前捕获夹具的映射结果，不是整核面积或频率。训练/清空仍为最差同步路径，组合候选 lookup 本身也差 0.012 ns，故三组在该预算下都未完全闭合，不能宣称整核提频。名义表容量与载荷位数不变，物理映射/复制会改变实际 LUTRAM/FF 用量。

实验分支保留 bank-local 结构以推进训练时序；这轮明确接受了局部 LUT 代价，没有完成降低面积的目标。索引折叠保持默认关闭，其 IPC 收益仅在显式配置启用时生效。下一批优先处理 invalidate 到有效位清空的长路由、比较/方向反馈的 LUT 代价，并扩展到完整 IF 输出捕获及实际 CPU 边界。

三组都没有无时钟寄存器或未约束内部端点，布线错误为 0，但全路径仍有 setup/hold 违例。r2 原始 result.json 的 clock-domain 查询也包含 I/O，不能把其 hold 字段作为纯内部值；最终采用 physical-audit-r1 中显式 FF/RAM 边界的只读 DCP 查询，原始文件不改写。端点对象的合并计数用于查询覆盖，不等于独立物理存储容量。
<!-- END_PHYSICAL_RESULTS -->

物理上下文是 Vivado 2025.2、`xczu15eg-ffvb1156-2-i`、真实 3.333 ns 单时钟、setup uncertainty 0.100 ns、I/O max 0.333 / min 0 ns、同一明确 BUFGCE 假设与相同输入/输出捕获寄存器。`prediction_ooc.tcl` 在该真实时钟的同步路径上施加更严格 3.000 ns 模块预算，lookup/training 分组记录端点覆盖，没有 false path、多周期或虚构时钟。CLB LUT 来自实际利用率，不能用映射 cell 数替代。捕获寄存器只提供相同同步上下文，没有向 CPU 增级。当前物理夹具捕获 nextPc/hit；FPGA 核还使用 candidateMask/candidateValues，其完整接口反馈路径未纳入该夹具的全部输出捕获。因此这里的资源与时序不代表完整 IF 路径或整核，后续仍需实际 CPU 边界验证，全路径违例也必须保留。

首次参考实现已保存布线 DCP，随后 Vivado 在分组 hold 报告处报内部异常。修订脚本重新查询布线后端点，从该 DCP 只读恢复报告；参考不重新综合/布线，local/hashed 仍各实施一次。失败日志和原脚本完整保留于 `prediction-20261103-r1`，`report-recovery.json` 记录前后脚本、DCP 哈希，不覆盖原证据。

本机复现需先载入指定环境，始终使用新目录：

```bash
cd /home/openion/Valence-InOrder
source .local-dev/env.sh
python3 -B simulator/gsim/inorder/prepare_prediction_reference.py --output build/NEW-prediction-reference
mill -i -j 2 OrbitalI1.test.compile
mill -i -j 2 show OrbitalI1.test.runClasspath
mill -i -j 2 OrbitalI1.test.testOnly inorder.FiveStageConfigSpec
mill -i -j 2 IonSoC.test.testOnly inorder.I1ExternalQuiesceSpec
python3 -B simulator/gsim/inorder/prediction_acceptance.py --reference build/NEW-prediction-reference/reference.json --coremark-reference build/i1-numerical-20261103-r1/coremark-r2/receipt.json --output build/NEW-prediction --rtl-output /mnt/e/VM/Share/Valence-rtl/Valence-InOrder/NEW-prediction/rtl
```

`--coremark-reference` 指向首批匹配的已验收固件收据；新机器应按首批报告重建它，不可更换编译参数或二进制。普通 RTL 在本批短检查全部通过后才导出。Windows 先载入根内 tools/env.ps1，把本次脚本复制到本次 tools，令 cwd/log/journal 均在该根，调用 `prediction_ooc.tcl PAIRED_RTL_ROOT FRESH_REPORT_ROOT 3.333`；可选第四参数为已冻结的参考布线 DCP，供报告恢复使用。`prediction_reports.tcl COMPLETED_PHYSICAL_ROOT FRESH_REPORT_ROOT` 只打开已有 DCP，生成显式同步边界报告，不综合、不布线、不改约束。

证据为 `/home/openion/Valence-InOrder/build/i1-prediction-20261103-r1/acceptance-r1` 与 Windows `prediction-20261103-r1/physical-r2`、`physical-audit-r1`。相邻 JSON 保存收据哈希、115 份源码冻结、各模型结果、逐 PC 变化和物理报告哈希。生成模型、缓存、固件和 DCP 不提交 Git。没有运行全量 GSIM、Linux、RTOS、bit 生成或上板；首批 MDU 预算未闭合和旧 bscan_qualification fixture 等已知限制仍保留。
