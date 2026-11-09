# I1 H/V 接入进展（2026-11-04）

> 当前状态（2026-11-05）：总线、CMU、CPU H 状态/两阶段 MMU 与现成 Spinor 已接入，定向 GSIM 已通过，整机 300 MHz 仍在收敛。请以 [最新整机报告](i1-system-hv-20261105.md) 为准。下文保留历史阶段，早期“未接入/待实现”描述不代表当前状态。

用户已授权与顺序核性能优化同步推进 H/V；V 扩展复用用户提供的现成 VPU，不开发新的向量执行数据通路。用户已提供 [Surplars/Spinor](https://github.com/Surplars/Spinor)，锁定 `e151f80e1da3a566d1a6ff5157052757fac0ddcb`，以未修改源码复用其真实执行器。开发/GSIM 继续在 `/home/openion/Valence-InOrder`，Windows 交付与 Vivado 在 `E:/VM/Share/Valence-rtl/Valence-InOrder`。

## 已完成的 H 基础组件

`I1HypervisorDecode` 独立识别 H 1.0 新增的 HLV/HLVX/HSV、HFENCE.VVMA/GVMA；核对 U/HS/M、VS/VU、HU/TVM 权限，区分 illegal 与 virtual-instruction trap。组合逻辑，无 owner、寄存器、执行副作用或新增流水级；接口吞吐 II=1。32 位保留 HLVX.WU，拒绝 RV64 专属编码。未知编码交由 CPU 基础译码处理。

参考 [RISC-V 20240411 H 1.0](https://docs.riscv.org/reference/isa/v20240411/priv/hypervisor.html)。编码事实独立核对官方 [rv_h](https://github.com/riscv/riscv-opcodes/blob/master/extensions/rv_h)、[rv64_h](https://github.com/riscv/riscv-opcodes/blob/master/extensions/rv64_h)；Git blob SHA1 分别为 `84a361d4090eabff26cba6a96c9e99e922ec9a06` 和 `75589e1ab2965e1829c27e91d82a0c8c57121e5a`，记录在 `simulator/gsim/config/hypervisor-h10-decode.json`。

GSIM + ASAN/UBSAN：RV32、RV64 各 913800 检查，共 1827600；完整寄存器组合、固定编码位翻转、30000 个随机指令和五种架构模式，HU/TVM 各两种取值。两档错误预期异常码均被独立 mask/value oracle 拒绝。证据 `build/i1-hv-foundation-20261104-r1/decode/receipt.json` 绑定源码、模型、可执行文件、正负日志和命令。未把 DUT 的位域函数或控制表作为软件 oracle。

```sh
source /home/openion/Valence-InOrder/.local-dev/env.sh
mill -i OrbitalI1.test.compile
python3 simulator/gsim/inorder/hypervisor_decode_assessment.py --output build/FRESH_H_DECODE
```

## 后续 CPU 接入顺序

| 工作 | 当前状态 | 验证重点 |
|---|---|---|
| H 新指令编码与权限 | 独立硬件 GSIM 通过；尚未接入 CPU | 非法编码、权限与异常分类 |
| H/VS CSR、V 模式、trap/xRET | 待接入现有 MachineState | CSR 权限、委托、中断、精确恢复 |
| VS/G 两阶段地址转换 | 待扩展现有 Sv39/MMU | 上下文身份、页故障、失效、PMP/PMA |
| VPU 实体适配 | 已接入真实 SpinorIsolated；原生顶层 GSIM 通过 | standard、host FCSR、VLEN128/ELEN64、80 位 token |
| V CPU 侧 CSR/串行入口 | CPU 译码、VS、串行 WB、FCSR 接入；整核物理内存程序与关闭扩展回归通过 | vset/CSR、f0、FCSR flags、非法指令与所有者释放 |
| V 元素内存接入 | TL A/D 单 owner 接入共享 atomic/D-cache，Bare 初测通过 | 虚拟内存、页故障与精确前缀恢复尚未合核验证 |

现有 `soc.ip.vector` 的 M0 预留接口未用于本次绑定。新增可选 `SpinorHost` 模块直接连接 SpinorIsolated 的 offer/preview/grant/done，完整保留 80 位 token。CPU owns FCSR；Spinor owns VRF 与向量 CSR。系统原设计保持 **CPU 与 VPU 独立时钟域，VPU 独立 300MHz**。此前同钟直连属于临时功能联调接法，不是生产时钟架构；现已将该顶层移到测试源码 `I1SpinorSameClockBringup`。CPU/VPU 的六通道异步桥与双时钟顶层现已实现并通过编译、FIR/SV 导出，独立边沿功能与物理 CDC 尚未验收，不能把同钟 GSIM 通过记为独立时钟域验收。跨域必须完整传递命令、preview/grant/done、FCSR 命令快照及访存 A/D 事务，保留完整 token、所有者和反压。

实际 CPU 程序 GSIM 最终证据：`build/i1-spinor-cpu-20261104-r1/native-final/receipt.json`（SHA256 `bd6a94309e797b2d76fae77f1ee9f94cb02dde65fcf2b8913783177cb2b0108d`）。初次记录 `native-attempt1` 另保留。L1/L12 各 62 条退休、17 条 VPU 命令、2 个精确非法异常；检查 VS=Off 时不发命令、vsetvli、vle32/vadd.vi/vse32、向量 CSR、共享 cache 读回、向量存储使 LR/SC 失效、f0 源/目的、RUP 舍入与 NX 合并、native 只读 CSR 异常和返回。两个错误值/flags oracle 均被拒绝，ASAN/UBSAN 通过。该结果不是完整 V 指令集合规、向量虚拟内存、guest OS 或性能评测。

CPU 本地接口与访存适配在 `src/main/scala/core/inorder`、`integration/spinor/src/main/scala`，同钟组合顶层和观察端口仅放入 test fixture；关闭 `spinor` 不实例化 VPU、不增加控制包字段。物理基线为冻结 r12；CPU+VPU 尚未综合/布局布线，不能把 r12 的约 290MHz 频率用于组合系统。

当前 CPU 尚未宣告 H/V，也未完成 guest OS、H/V 全指令合规或其面积/时序评估。仅上述受限物理内存向量程序通过。当前 300MHz 实现输入仍是已冻结的 RV64IMAFDC 单发射 CPU；H 组件的独立通过不能替代 CPU 接入验证。完成实际接入后单独列出 H/V 的 LUT/FF/BRAM/DSP、频率与程序指标。

## 关闭 Spinor 的基线保护

`build/i1-spinor-cpu-20261104-r1/scalar-off/receipt.json` 为新跑全 A/C/F/D GSIM：L1/L12 各 53 条、22 次 FP 写回；固定 IM CoreMark ROI 578419/735718 周期、IPC 0.5973524383/0.4696364640，全部原始 CoreMark 字段与 r12 相等。独立值注错通过拒绝。

`scalar-off-equivalence.json` 对齐 r12 与当前关闭 Spinor 后导出的全部 56 个 SV；仅删除行末 Scala 源码位置注释后，完整文本逐字相同，保留名字、RTL、字符串、属性、指令与其他注释。记录每个原始/新 SV 及正规化文本 SHA256。该证明保护原标量硬件输入；组合 CPU+VPU 的面积/时序仍没有测量结果。

实际 CPU 测试 L1/L12 分别 1454/1699 周期；这是含初始化与异常处理的定向功能程序，不是向量吞吐或工作负载 IPC 评测。向量串行准入、preview/grant/done 的延迟与未来并行策略需单独量化。

## 时钟与评估边界修正

VPU 独立 300MHz，不由 CPU 当前约 290MHz 的最佳结果决定。CPU、VPU 分别保留各自模块的冻结实现证据；独立时钟不代表跨域接口自动满足时序。仓库已有的 Vivado 300MHz 物理结果见 Spinor `reports/local-m53-resume/evaluation.md`：标准顶层内部 OOC setup +0.090ns、hold +0.042ns，18085 LUT、12490 FF、2 BRAM36、7 DSP。该证据对应 M53；当前锁定源码提供 M61 的可选隔离接口，不把旧结果自动升级为这个新顶层的器件验收。

本轮选定的 r12 CPU 物理基线以及 CPU+VPU 同钟功能 fixture **均未装配 SoC 总线互连和 CMU**。CPU 包含私有 I/D cache，VPU 自带 TL A/D 访存端口；临时桥只把这些单事务访问送入 CPU 的 atomic/D-cache 路径。其存在不代表已经接入 SoC AXI/TileLink fabric、DDR 控制器、CMU 时钟门控/变频或相关外设。仓库其他 SoC 顶层已有这些组件，与本轮实例化范围分开记录。

## 双时钟接入 RTL（本轮更新）

已新增 `I1SpinorClockBoundary`、`I1SpinorDualClockCore`。复用六个 `CdcMailbox`，完整传递命令/FCSR、preview、grant、done、TL A、TL D；CPU/VPU 时钟分别输入，cold reset 在各域同步释放，原 CPU/VPU 模块的同步复位接口保留。全部 205 个 SV 已导出到 Windows 指定目录；没有新增 SoC 总线或 CMU。详细数据流及未完成项见 `docs/i1-spinor-dual-clock-20261104.md`。

GSIM 当前工具实测仍不能识别独立时钟边沿，七种边沿场景均失败，运行后的 AsyncReset 也失败。证据为 `build/i1-spinor-dual-clock-20261104-r1/assessment/receipt.json`。状态明确为 `ELABORATED_DUAL_CLOCK_RTL_GSIM_INDEPENDENT_CLOCK_RESET_UNSUPPORTED`，没有把工具限制记为新桥通过；尚未进行该双时钟整核的功能验收或 Vivado 实现。H CPU CSR、虚拟化模式与两阶段 MMU 仍待接入，misa.H/V 仍为 0。

## r2 更新：独立边沿数字功能已通过

新增可选 GSIM 显式边沿工具，默认工具冻结。七种独立时钟探针、异步复位及 90000 组成对求值/1534 次 mailbox 传输通过，真实 CPU+Spinor 双时钟的四组程序及两类负控制通过；完整结果与复现见 `docs/i1-spinor-dual-clock-20261104-r2.md`。此前 r1 工具限制不改写，其冻结二进制仍不支持独立边沿。

V CPU 侧译码/VS/FS/FCSR/串行退休和六通道 CDC 已取得本次受限双时钟功能证明；向量虚拟内存、上下文、完整合规及物理 CDC/组合时序仍未验收。H CSR/MMU 与 SoC 总线/CMU 状态没有变化。

## r3 功能与组合物理结果（2026-11-05）

修正 protocolError 的源域寄存后，r3 四组双时钟 CPU/VPU GSIM 与两个负控制通过。r2 组合实现已完成：CPU setup −0.347 ns、VPU −0.190 ns、两域内部 hold +0.010 ns；均未通过 300 MHz。总资源 44447 LUT、30467 FF、16 BRAM36、35 DSP，其中夹具 787 FF。714 条实际跨域路径的局部最大延迟与五组总线偏斜均满足，复位/CDC 警告与外部 OOC hold 未签核，不能称为完整 SoC/CDC 通过。详见 [双时钟物理报告](i1-spinor-ppa-20261104.md)。前文“尚未测量”的记录为当时阶段；本段及该报告是当前物理状态。H CSR/MMU、SoC 总线与 CMU 仍未接入。

## 2026-11-05 批量 CPU/VPU 优化

当前组合优化基线为 spinor-opt-20261105-r1：setup CPU −0.072 ns、VPU −0.011 ns，内部 hold 均 +0.010 ns；CPU/VPU 违例端点从 1108/324 降为 15/1，总 LUT 44447→44198，FF 30467→30477。300 MHz 仍未完全收敛。13 档组件门禁、四组独立时钟真实 CPU/VPU 程序及新跑固定 IM/真实 C CoreMark 通过，IPC/预测统计逐字段等于 R12。上游锁定 clone 干净，四个 VPU 文件通过明确的本地源码替换参与编译，不能将当前实现说成完全未修改的 VPU。活动 Vivado 流程线程上限为 8。详见 [本批物理及功能报告](i1-spinor-opt-20261105.md)。原纯 CPU R12 与上一轮组合实现均保留；H、SoC fabric、CMU 范围不变。

## 2026-11-05 总线、CMU 与 H 接入边界

当前最佳时序组合仍为冻结 R1。R2 的 GSIM/IPC 通过、面积下降至 43987 LUT / 30471 FF，但 setup 为 CPU −0.095 ns / VPU −0.017 ns，共 20/3 个负端点，内部 hold 均 +0.010 ns，因此没有替代 R1。R3 六文件结构批次已通过 18 档组件/恢复门禁、新跑 A/C/F/D、固定/压缩 CoreMark、数值恢复和四组独立时钟真实 CPU/VPU 程序；原始性能数据不变。R3 已冻结并进入 8 线程 Vivado 综合，物理结果待出。

总线与 CMU 的实现边界已核对：

| 接入项 | 可复用模块与当前端口 | 尚需完成的合核工作 |
|---|---|---|
| 最小内存互连 | 双时钟组合顶层暴露两个 `FiveStageBurstPort`；`FiveStageTileLink` 可转换为单 source TL A/D | I/D 仲裁与 source 身份、逐拍错误/反压和末拍归属；VPU 继续通过共享 CPU atomic/D-cache 路径访问，保留 LR/SC 失效规则 |
| 独立 fabric 时钟 | `I1IndependentClockSoc` 与既有 TL/有序数据 CDC | 复用接口合同；现有独立时钟 SoC 明确要求 CPU/fabric 常开，transport empty 不能替代全系统排空证明 |
| CMU | `ClockManagementUnit`、`ClockResourceControl`，已有 CMU MMIO 路由槽 | 接通停止接收、CPU/VPU/访存 owner 排空、同步应答与持久唤醒；目前组合顶层只有 CPU/VPU CDC idle，没有 CMU 控制闭环 |
| 实际门控 | CMU 的 `clockEnable/quiesce/isolate/allowAdmission` | 仅对完成端到端排空与停启验证的资源设置 canGate；当前 CMU 本体不提供热复位或运行时变频，变频属于独立 ClockRate 管理组件 |

正式合核按“固定 CPU/VPU 300 MHz 基线 → 最小总线与内存管理端 → CMU 控制及停启闭环”逐层验证和测量开销。接口准备可先进行，不把总线/CMU 的资源和路径混入当前裸组合基线。当前 GSIM 显式边沿工具可驱动独立顶层时钟及暂停/恢复；生成/门控时钟网本身尚未在该工具中取得支持证明，后续门控测试需明确区分 CMU 控制合同与实际时钟原语映射。

H 进度没有隐含升级：`I1HypervisorDecode.scala` 哈希仍与 `build/i1-hv-foundation-20261104-r1/decode/receipt.json` 一致，状态为 `PASS_H10_32_64_ENCODING_PERMISSION_VIRTUAL_ILLEGAL_ORACLES`。只有独立译码和权限分类通过，CPU 仍没有 H/VS CSR、V 虚拟化状态、H trap/xRET 或 VS/G 两阶段转换。`FiveStageMachineState` 当前只有 M/S/U 和可选单阶段 Sv39；代码中的向量 VS 脏状态不是 hypervisor VS 寄存器组。`misa.H` 仍为 0。

H 下一批接入顺序是 H/VS CSR 与 V 状态、WB 精确 trap/xRET/中断委托，再接 H 访存和 HFENCE，最后结合现有 Sv39 walker/TLB 实现并验证 VS/G 两阶段转换。CSR 与模式状态工作不依赖总线或 CMU，但独立译码通过不能作为 CPU H 扩展就绪或 guest OS 通过的证据。
