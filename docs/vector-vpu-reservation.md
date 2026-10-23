# V 扩展 / 外接 VPU 接入预留（M0）

## 状态和本次代码边界

2026-10-22：仅增加独立 `soc.ip.vector` 契约、禁用端点和纯 Scala/Chisel elaboration 检查。
没有接入 CPU、没有向量执行、没有新增板级引脚或 fabric client、没有改变现有软件 ABI。
`VectorAttachmentConfig.enabled` 默认 false，true 明确报错；`advertisesV` 恒为 false。
这不是标准 RVV 实现，也不是用自定义协处理器指令替代标准 V 扩展。

新增文件：

- `src/main/scala/ip/vector/VectorAttachment.scala`
- `src/test/scala/ip/vector/VectorAttachmentSpec.scala`
- 本文档

现有 I1/A1 的 decode、CSR、misa、ISA 字符串、DTB 和默认平台配置均不修改。
新增参数现在是独立的接入预留，不是可启用的 SoC 配置项。不能仅切换布尔值获得 VPU。
独立 OrbitalI1 Mill 模块尚不包含这个未使用目录；真正接入时才增加其依赖。

## 当前架构审查和后续接入点

- `platform/CommonCpuProfile.scala`、`CommonI1CpuTile.scala`、`CommonA1CpuTile.scala`：
  同一平台选择 I1/A1。VPU 执行端口应由两个 CPU adapter 分别实现，再共享独立契约，
  不把任一核心的私有 ROB 或 pipeline control 放进 `soc.isa`。
- I1：`FiveStageDecode.scala`、`FiveStageCore.scala` 的 serialDrain / olderSerial 已具备
  保守串行入口；`FiveStageMachineState.scala` 管理 CSR/trap。后续必须在这三处统一
  序列化向量命令、标量操作数、CSR 权限和精确异常，而不是只增加 opcode 命中。
- A1：`decode/IntegerDecode.scala`、`integration/IntegerBackend.scala`、
  `system/MachineSystemUnit.scala` 提供独立译码及 ROB-head system 路径。
  现有 FP memory epoch 明确先排空整数 LSU/store buffer，并保持独占到真实退休；
  可借鉴这个所有权原则，不能简单复用 FP token 或把 FP 完成当成向量退休。
- I1 `FiveStageMachineState` 的 misa 和 A1 `OooParams.misaValue` 都没有 V 位；
  当前 mstatus/sstatus 未提供完整 VS/向量 CSR 状态。本次保持不变。
- `CommonCpuTilePort.scala` 的 coherence、lineGrant、scalar owner 和 maintenance epoch
  是平台边界，不是向量指令完成协议。VPU 本地 drained 不能替代 Home、DDR、CDC、
  grant/probe、DMA 和未返回 store 的全局 drain 证明。

## 预留契约和性能边界

这是保守 bring-up 边界，不是最终高吞吐微架构：RV64、VLEN 默认128 bit，可配置为
128..65536 的二次幂；ELEN 8..64 的二次幂；最多一个不可撤销命令及一个元素内存请求。
VLEN 不是传输总线宽度。禁用端点容量为零，无状态，无组合数据处理链，不接受命令或响应，
不发请求或完成，始终本地 drained。端点未实例化在现有 top 中。

未来运行态目标：command/result 各一个 ready/valid 通道，生产者在阻塞时保持 valid/payload。
首次命令到完成的延迟由 VPU/内存决定；不保证每拍命令、同拍 refill 或固定周期数。
元素请求最多 8 字节、无 burst、无 AMO，保守吞吐受真实返回及退休约束。
更宽、多 outstanding、重命名及 speculative vector execution 必须另设阶段和性能验收。
综合时序、面积、板上行为以及 RVV 合规均未测量，不能由 elaboration 推导。

### 指令、状态与异常

CPU adapter 只能在最老合法指令、较老内存完全排空时授权 command.fire，并冻结上下文。
此后不能因年轻分支 flush 抹掉命令或已完成元素；年轻指令不得越过。
owner+epoch 完整回传且不可在旧响应仍可能到达时重用；A1 必须映射完整 ROB 身份，
不能截断代数/tag。requireIdentityCapacity 检查映射宽度，宽度可配不是防 ABA 的证明。
旧 owner/epoch 仍可能返回时不允许复用；独立复位不允许将代数清零后接纳旧流量。

命令传 instruction/PC、rs1/rs2、FP 标量及向量 CSR 快照；向量寄存器由未来 VPU 持有。
完成传 scalar destination/value、CSR 更新、FP flags、精确 cause/tval/vstart。
exception 时禁止 scalarWrite，但已完成前缀的 Dirty/flags/saturation 可以保留；
成功必须令 vstart=0。fault-only-first 的非异常完成可以减小 vl；更新 vl/vtype 时传完整对，
保持不变的字段也必须回传正确值，不能将 fault-only-first 误当成普通异常。
CPU 在匹配 token 的 complete.fire 同步提交或进入 trap，VPU 必须先完成全部副作用记账。
异常允许架构认可的已完成元素前缀，不得套用“所有向量写回只能最后一次原子提交”的错误模型。
后续 CSR 读写、VS/FS Dirty、上下文保存恢复、调试及中断恢复需要独立实现。

### 内存和 flush/drain

预留的是受保护的虚地址元素服务，不是绕过标量 MMU/PMP/cache 的 DMA 主口。
CPU 冻结有效权限、satp、SUM/MXR/MPRV、PMP；内存 adapter 必须验证完整 token/context，
通过正常 translation、PMP、PMA/MMIO 策略和 cache coherence 路径。
每个元素/segment field 的返回必须匹配；masked-off 元素不得产生请求。
misalignment 必须在副作用前由 adapter 处理或报告正确 fault；禁止把跨页拆分静默漏掉。

quiesce 是持续的停止 CPU 新 offer 请求，不是异步取消或 VPU ready 门控。
已经拉高并保持 valid 的命令仍可握手并排空；CPU 本地 held command 也计入全局 drain，
不能只看 VPU drained。quiesce 不得阻塞 complete.ready，否则停机可能死锁。
已接受命令、内存请求、持有响应和
部分写入继续排空；drained 包含持有的完成消息。禁止在阻塞 valid 时丢请求。
CPU flush 只能取消尚未授权的工作，运行中的向量指令需要正常完成或精确 trap 前缀。
当前未设计中途抢占端口：初期中断可在指令边界进入；若要求有界中断延迟，必须增加
精确元素边界停机协议，而不是拉高 quiesce 就宣称可复位或换频。
平台把本地 drained 与共享内存/CDC 证明合并后才可切换上下文或时钟。
冷复位必须同步清空所有关联端点/owner；不支持单独复位 VPU 后让旧回复命中新命令。

## 分阶段实现与准入

1. M0（本次）：审查、独立契约、默认禁用、参数负测与端口 elaboration；现有硬件不改变。
2. M1：分别完成 I1 serial 与 A1 ROB-head adapter，标准指令分类及 CSR/VS/FS 门控，
   用可控 mock VPU 验证 backpressure、token/epoch、重复/过期回复、trap/interrupt、
   flush 优先级、部分前缀及 fault-only-first 的 vl 更新。使用独立 GSIM oracle。
3. M2：加入正常 MMU/PMP/coherence 的元素内存桥、page/access faults、masked/segment/
   indexed/strided accesses、MMIO、FENCE/SFENCE.VMA/FENCE.I、LR/SC reservation 相互作用，
   并把 VPU 纳入运行时 maintenance/debug/clock drain。专门测试请求/返回被阻塞期间的退出。
4. M3：接真实 VPU，执行 vset*、全部目标 V 指令类别、向量寄存器和 CSR 保存/恢复，
   标量/向量 FP 交互、尾部/掩码策略和 trap restart；运行独立参考差分与标准架构测试。
   区分完整 V 与某个 Zve 子集，不把子集或自定义协议宣称为完整 V。
5. M4：证明硬件/软件契约完整后，单独审查 misa.V、DTB/ISA 字符串与软件工具链，
   再开放配置；以合并候选做必要短验收和一次综合/时序对比，不逐项启动全流程。

## 规范依据与检查

固定参考 RISC-V ISA 20240411 版本库的
[V 指令扩展章节](https://docs.riscv.org/reference/isa/v20240411/unpriv/v-st-ext.html)
及 [Machine-Level ISA](https://docs.riscv.org/reference/isa/v20240411/priv/machine.html)，
核查向量参数、CSR、上下文状态和精确异常。该向量页面标题标 V1.0，但正文保留
“1.1-draft”历史文字；正式合规阶段须再固定 ratified V1.0 归档及测试版本，不能混用草案。

规范约束：VLEN/ELEN 为二次幂且 VLEN 至少为 ELEN，VLEN 上限65536；完整 V 要求
相应标准子集而非仅有向量寄存器。vstart 指示 trap 恢复元素位置；正常完成时清零。
VS 管理向量上下文，Off 状态禁止向量指令/CSR；SD 汇总 Dirty 状态。
向量 FP 同时涉及 FS/浮点状态。精确 trap 保留已完成元素前缀并阻止年轻架构提交。

运行本次短检查：

```sh
source scripts/cloud/env.sh
mill -i IonSoC.test.testOnly ip.vector.VectorAttachmentSpec
```

这里只验证配置/端口形状/禁用常量，不声称协议行为或CPU执行验证。
因没有修改或实例化运行态硬件，不启动 GSIM、Vivado、长 Linux 或全回归；
真正接线的 M1/M2 批次必须增加必要的短 GSIM 独立检查。禁止 Verilator。

### M0 自审负例

增加独立测试内协议模型，明确拒绝 owner/epoch 截断、旧 token 完成、响应未排空时完成、
重复完成和 owner 在活动期复用；验证 quiesce 前已 offer 命令仍可接受并完成退出。
这只固定契约反例，不是硬件实现或 RTL 行为证明。M1 必须将相同场景接真实 GSIM DUT。
