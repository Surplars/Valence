# Common A1 固定分支负载：新增配置验证点

2026-10-28。在公开源码 `5a0cb2993f177b498774fd570dbee9889901ca80` / tree
`96426d2c3eff810fa92bb2e01245bfa3d2fa8699` 上，新增一个独立校验的 common-host
分支/控制工作负载；**未改 RTL、默认值、cache/service 或已发布性能结论**。

## 同条件结果

| 指标 | 第四配置 OFF | 仅 MUL/load capture ON |
| --- | ---: | ---: |
| 总退休 / ROI 退休 | 240 / 236 | 240 / 236 |
| ROI cycles | 319 | 319 |
| whole-work cycles | 359 | 359 |
| drain / total cycles | 16 / 375 | 16 / 375 |
| I requests / bytes | 9 / 408 | 9 / 408 |
| D reads / writes | 0 / 0 | 0 / 0 |

**ROI 与 whole-work 的等频吞吐变化均为 0%；没有回归，也没有新增收益。**
完整结果及原始正例输出、四个 CPU 负例错误输出见
[`matched-result.json`](../simulator/gsim/fixtures/branch_control_common_v1/results/matched-result.json)
及同目录。保留原始业务字段，没有把参考解释器指令数当成 DUT 周期数。

两个配置分别为 `full-r1-m3-efficiency-refactor-4` 与
`full-r1-m3-mul-load-operand-capture-experiment`；实际配置差异只有
`registeredMulLoadOperandCapture`。Context instruction prefetch 与 load nomination
仍为 OFF，实验默认值不变。该负载不含 MUL 或普通数据 load/store，因此只是一个
新的控制路径配置/工作负载验证点，**不能证明 MUL 的更广泛收益，也不是所有配置组合的验证**。

## 固定 guest 与测量边界

复用已有 [`branch-program.S`](../simulator/gsim/payloads/branch-program.S)，保留其
284-byte 指令 body：循环、六种条件分支、JAL/返回、JALR 同源/目的寄存器及奇数地址场景。
测试专用 wrapper 将原 body 放在 `0x80200000`，附加两个退休 NOP 标记、EBREAK 与
推测取指 NOP padding；完整 `.text` 为 808 bytes。

- 保留同一个 `0x80000000` ROM AUIPC/JALR boot，所有初始 GPR 为零；boot 的 x31 写入纳入参考状态。
- ROI 为 `[roi_begin, roi_end)`，覆盖原程序成功路径，不含两条 boot 与两条尾部 NOP。
- `roi_end` 对应退休 NOP，不能与不退休的 EBREAK 共址。Terminal PC 为 `0x80200124`，cause=3、tval=PC。
- Whole work 截至 terminal trap；drain 独立报告。两边均不计复位步骤，并要求 owner/channel 完整排空及终止后无退休。
- 原 `.word 0` 错误路径必须拒绝；不能把“解释器也看到了非法指令”当作程序成功。

新 ELF SHA256 为 `e883f1ba4f951b87afd8388ebe70931a435b92e5bd22cf0ebe551006bcef62fd`，
symbols SHA256 为 `094b2462b68152b1f21499d41cc9f0b605f1684e58f0f4797b27286ee949c72a`。
它是 **Clang/LLD 新构建、重新资格化的 fixture**，不是找回的历史 GCC binary；
不能与旧 bare-core 直接供指环境的周期横比。ET_REL assembly object 也不叫可执行映像。

## 独立正确性与执行准入

源级解释器只读取原汇编及显式 boot/tail 契约，独立实现 RV64I 语义及源编码；不读取
DUT decode 或现有 ISA 实现。其结果先封存，再与真实 ELF 每个 text byte、既有软件 ISA
参考的全部 240 个事件、32 GPR、ROI 与终止边界交叉检查。覆盖 signed/unsigned 分支、
64-bit wraparound、x0、JALR 清 bit0，以及 rs1==rd 时先读旧源后写链接值。

实际完成的检查：

- 21 组源语义测试；31 个真实 ELF / transcript 变异拒绝；7 个 ISA 输入拒绝；
  14 个 native sealed-gold checker 变异拒绝。
- 两个真实 CPU 正例 exit 0、stderr 空、架构与 sealed source gold 完全一致。
- 每个配置各运行 retirement value 与 trap metadata 变异负例，四次均在预期检查器 exit 1。
- 独立于 fixture 实现的 root 审查通过后才执行 CPU。额外 reviewer 遇容量限制，未虚称第二份完成的审查。

新 branch host 只迁移 workload envelope 与 source-gold 比较；共享 CoreMark signature/oracle
未改。去除 donor 已标记的被动 MUL capture 观测段后，协议/service tick 保持字节一致：
首响应 3 cycles、每拍 8 bytes、16 live，以及原有背压、grant/ack、owner、trap/drain 检查。
没有新增 RTL tap。

恢复后旧 `.o` 不存在，因而从 byte-qualified 原生成 CPP/H **新编译**了两份对象，
不是复用历史 `.o`，也没有重新生成硬件。每份 object 编译受 2 CPU、900 秒、4 GiB sampled RSS
边界约束；实际编译峰值样本约 3.71/3.69 GB。Host 与 CPU 各阶段另有受限 gate。
250ms RSS 采样可能漏掉极短进程峰值，不能把零样本当零内存，也不宣称 kernel hard limit。

## 复现与范围

[Portable fixture README](../simulator/gsim/fixtures/branch_control_common_v1/README.md)
提供 guest 构建、源语义/ISA 检查、模型/object pin 检查与 host recipe。所有工具、源码、
新 guest 与结果 hash 均显式记录；不联网安装、不默默换 compiler、不自动生成 DUT 或启动广泛回归。
路径迁移的 reference-only 检查不等于新 CPU 性能样本。

本轮无 CoreMark 重跑、Linux 扩展、综合/映射、布局布线、Fmax 或实板结论。原有结果仍保留原范围；
这一点只增加“两个具体配置在一个额外固定分支负载上保持正确、周期不变”的证据。
