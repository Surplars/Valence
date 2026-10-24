# NaxRiscv → Orbital-A1 微架构研究（固定源版本）

状态：架构研究与迁移建议，不是已实现功能清单，也不是 300 MHz 达标报告。

研究日期：2026-10-24。本文只使用 NaxRiscv 官方仓库、官方文档及本仓库源码；没有运行 NaxRiscv 仿真、Verilator、GSIM、综合或实现。研究期间未改生产 RTL。

## 1. 固定版本与真实 A1 基线

- NaxRiscv 源码固定于 [9f452d50560d02fb391bc8039f5453c54e0911af](https://github.com/SpinalHDL/NaxRiscv/commit/9f452d50560d02fb391bc8039f5453c54e0911af)，GitHub 官方提交日期 2026-01-23。本仓库 `FpgaNextConfig.naxReferenceCommit` 已记录同一个版本；本次重新检查实际实现，而非以已有参考声明代替阅读。
- Valence 研究起点为 `47f42fa0d7d5c845053e325928749422de9b350c`。以下位置相对该基线；后续重构可能移动行号。
- A1 是 `CommonCpuProfile.A1 → CommonA1CpuTile → FpgaNextConfig.Selected` 的组合，不是 `OooParams()` 默认值，也不是所有 FPGA-next 实验的并集。平台添加 `internalLineGrant=true`，A1 配置使用 `staged-fetch-turnover`。
- 真实后端是双宽 rename/completion/commit、ROB16、PRF48、LSU2、SB2；已有寄存 issue→execute 边界、owner-local ready、banked issue/ROB payload 和 LVT PRF。L1 为 512 条 64-byte line、2-way，即每个 L1 32 KiB；D$ 为 2 MSHR、2 response、2 writeback。
- 特别注意最终参数覆盖：`BoardSocConfig.timingParams` 中 `registeredLoadIssueForwarding` 的局部默认不代表 A1 最终值。`FpgaNextConfig.loadIssueForwarding=Some(true)` 再传入 `boardParams`，所以 A1 已启用该 forwarding。`heldAluIssueForwarding`、`registeredLoadResultReady`、tagged/posted proof 等仍不能当作 A1 已启用能力。
- `CommonA1CpuTile` 明文拒绝未发布的 tagged/posted CPU 候选，并固定 2 MSHR/2 response/2 writeback。改这些容量是接口/所有权重构，不是改一个参数就完成。

本地证据：[`CommonA1CpuTile.scala:8–30`](../src/main/scala/platform/CommonA1CpuTile.scala)、[`FpgaNextConfig.scala:287–335,450–457`](../src/main/scala/core/ooo/config/FpgaNextConfig.scala)、[`BoardSocTop.scala:145–242`](../src/main/scala/core/ooo/platform/BoardSocTop.scala)。

## 2. 总结：学什么、不学什么

最值得迁移的是“以 FPGA 存储和局部调度为中心的资源组织”，不是 SpinalHDL 插件语法或某个跑分数字：

1. rename、依赖、issue、PRF、ROB 各有明确状态所有者与阶段边界，不把全窗口控制、数据多路选择、执行、恢复拼在一拍。
2. 调度窗口与 ROB 容量独立；调度只携带必要上下文，宽 payload 留在适合 RAM 的存储中。
3. 固定延迟操作可以预告 wake，但只在无 stall 的时序契约成立时；变延迟 load/div/共享写口必须以真实事件唤醒。
4. LSU 队列、refill、victim/writeback、返回资源分别保有所有权，等待具体事件，而不是全局忙就阻塞全部工作。
5. 更长流水必须配合更早预测、恢复和有用请求并发，否则 fmax 上升可能被 IPC 下跌抵消。

不能照搬：NaxRiscv 官方明确以 FPGA、较低面积和较高 fmax 为取舍，并不以最大 IPC 为目标。其器件、位宽、缓存、工具、约束、资源与 Valence 不同；任何模块频率或历史整核成绩均不是 A1 达到 300 MHz 的证据。[官方定位](https://spinalhdl.github.io/NaxRiscv-Rtd/main/NaxRiscv/introduction/index.html)

## 3. Rename、freelist 与 PRF

### Nax 实际实现

- `TranslatorWithRollback` 保留 speculative RAM、committed RAM，以及每个架构寄存器一个 location bit。rename 更新 speculative，commit 更新 committed；rollback 清 location，读立即改选 committed。多 lane 同 rd 由较年轻 lane 获胜，包内 RAW/WAW 旁路显式处理。[RfTranslationPlugin.scala:36–88,143–163,184–222](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/frontend/RfTranslationPlugin.scala#L36-L88)
- 物理寄存器分配使用多口 RAM allocator；正常 commit 回收旧映射，丢弃指令回收新映射，x0 单独保护。[RfAllocationPlugin.scala:40–83](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/frontend/RfAllocationPlugin.scala#L40-L83)
- dependency storage 是 physical→ROB RAM 加 physical-indexed busy bits。代码 `busy` 深度为 `physDepth`，不要把官方概述中的 busy/ROB 表述误实现成另一个 ROB-indexed 表；同拍 reserve 覆盖 wake clear。[RfDependencyPlugin.scala:43–79,216–235](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/frontend/RfDependencyPlugin.scala#L43-L79)
- FPGA 多写 PRF 由每写口一份数据 RAM，加 narrow LVT 决定读哪个 bank。Nax 的 LVT 可由 XOR 多写 RAM 实现。写口按 sharing key 合并/仲裁，旁路按显式 latency 构建。[MultiportRam.scala:38–99](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/compatibility/MultiportRam.scala#L38-L99)、[RegFilePlugin.scala:245–288,320–330](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/misc/RegFilePlugin.scala#L245-L288)

### A1 映射与建议

A1 已有 [`OwnerBankedPhysicalRegisterFile`](../src/main/scala/core/ooo/rename/OwnerBankedPhysicalRegisterFile.scala)，每写 lane 一个 `Mem`，小 initialized/owner 表，明确冲突优先级。它不是“尚未采用 RAM PRF”。先保留它，量化真实读口数量、LUTRAM 推断、owner mux 和结果广播扇出；不要为追求形式上的 bank 数更多而扩大全部 PRF 端口。

[`RenameRob`](../src/main/scala/core/ooo/retire/RenameRob.scala) 当前同时拥有 RAT、committed map、bitmap freelist、ROB 和逆序 rollback。可把 map/free/retire 拆成独立模块与资源契约；首先保持现有行为和双宽包内依赖。RAM freelist 不是无条件优于 48-bit bitmap，必须比较小容量下 mux/allocator 路径、回收顺序、旁路和恢复复杂度。

重要差异：Nax map rollback 接的是 `reschedulingPort(onCommit=true)`。它是恢复到已提交状态，而不是在任意分支解析拍恢复到该分支检查点。A1 当前保留 redirect 前的未退休老指令，逆序恢复被杀年轻指令映射。如果只把 A1 RAT 换成“双表+一拍清位”，会错误丢掉仍需保留的推测映射。可选方案只有经过证明的 checkpoint / replay / 现有逆序恢复；不能混用语义。

## 4. Dispatch、issue、wakeup、select

### Nax 实际实现

- `Gen.scala` 默认 `dispatchSlots=32`、`robSize=64`，两者独立，decodeCount=2；这些是此版本默认参数，不是 A1 的选定目标。[Gen.scala:44–82](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/Gen.scala#L44-L82)
- issue queue 按双宽 row 插入；每次 push 全队列移动一行，未填满的 row 也占位。它没有任意空洞压紧。每 entry 用半矩阵 trigger bits 记录对更老 entry 的依赖，额外 self bit 使已发射但尚未唤醒的 producer 保有必要身份。事件清依赖位，ready 是其余 trigger 为零。[IssueQueue.scala:50–111](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/frontend/IssueQueue.scala#L50-L111)
- 对每 EU 选择最老 eligible entry；`eventFactor/eventOffset` 将同组 EU 可看的槽位分开，不是所有 entry 对所有 EU 完全对称的全互联。push-ready 是保守寄存信用，避免晚 select/clear 回灌前端。[IssueQueue.scala:114–138](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/frontend/IssueQueue.scala#L114-L138)、[DispatchPlugin.scala:147–178](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/frontend/DispatchPlugin.scala#L147-L178)
- selection 后的 context 读可拆为局部 one-hot mux 与下一拍平衡 OR；ROB-ID、physical destination、EU context 分别放在可配置阶段，避免全部跟随选择器串联。[DispatchPlugin.scala:218–295](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/frontend/DispatchPlugin.scala#L218-L295)
- 动态 wake 的 ROB-ID 转成当前滑动窗口的事件位；静态 wake 使用发射事件的固定延迟历史，并在 row 移动时同步移位。[DispatchPlugin.scala:301–345](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/frontend/DispatchPlugin.scala#L301-L345)

### A1 映射与建议

A1 `IntegerBackend` 的 pending、issue payload、memoryLive、store proof 等多类状态按 ROB slot 组织，`CircularIssueSelector` 已有并行 oldest-two 和 one-hot payload，因此不要将它描述成简单串行年龄比较链。真实风险是 eligibility、memory/M/CSR 仲裁、PRF 读和 late authorization 仍汇聚在大型集成模块。

第一批应提取独立调度器，保留现有 ROB token 与最多双发射的总预算：

1. 窄 ready/class/producer metadata 驻留调度表，宽 payload 留 banked storage；模块输出 owner/one-hot 与局部 grant。
2. 分离 ALU、memory preparation、M/CSR 的候选与资源信用，不以“某个资源满”阻塞不使用它的已就绪指令。
3. 先保留 16-entry window 和现有循环 oldest-two，验证新边界没有新增气泡，再决定是否将 IQ 与 ROB 容量解耦、分组或改成 matrix。直接换 Nax 的移位半矩阵会引入全表移动和固定列亲和性，未必有更高 IPC。
4. 尽量局部化 wake/event；但 A1 64-bit generation token 的 stale-result 防护不能直接删成裸 ROB index。任何压缩 token 方案需要明确最大悬挂寿命、复用条件与 wrap 证明。

本地对照：[`IntegerBackend.scala:404–476,716–743,2532–2542`](../src/main/scala/core/ooo/integration/IntegerBackend.scala)、[`CircularIssueSelector.scala`](../src/main/scala/core/ooo/issue/CircularIssueSelector.scala)、[`OwnerOperandReady.scala`](../src/main/scala/core/ooo/rename/OwnerOperandReady.scala)。

## 5. 执行与旁路：缩延迟不能破坏可用性

Nax 区分固定延迟静态 wake 与可 stall 的动态 wake。`ExecutionUnitBase` 将 context、PRF read、decode、execute 分级；有静态 latency 的入口不使用普通 ready 回压，执行契约保证结果按时到达。PRF 写口 sharing/priority 和数据 bypass 由专门服务管理。[ExecutionUnitBase.scala:150–185,209–240,281–300](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/execute/ExecutionUnitBase.scala#L209-L240)、[官方执行单元概述](https://spinalhdl.github.io/NaxRiscv-Rtd/main/NaxRiscv/execution_units/index.html)

A1 [`IssueExecuteStage`](../src/main/scala/core/ooo/issue/IssueExecuteStage.scala) 已是容量 1、最小 latency 1、目标 II=1 的弹性 slot，可同时消费旧 owner 和接受新 owner，但允许下游 stall。它的 cancel 不提供额外组合输入信用。这是需要保留的良好边界。

迁移规则：

- “被 selector 选中”不等于“已接受”。只能对真实 accepted、未取消且有保障写回/旁路的 owner 发固定延迟预告。
- 共享 WB、LSU、M、CSR 可以拖延结果时，先使用动态 wake；若要静态 wake，先预约未来 WB slot，或引入独立 completion buffer，使固定时序成为真的。
- 保留 load→issue 的既有寄存 forwarding；不要把尚未检查成功的 cache data 标成 PRF ready。
- 必须区分 data available、wakeup、ROB done、retire 四种事件；旁路值可用不自动允许 ROB 完成或提交。
- 300 MHz 下不宜形成 producer ALU→全窗口 wake/select→PRF/bypass→consumer ALU 的单周期链。可追求一拍依赖调度，但数据与事件要在固定边界相遇，不能仅删寄存器。

## 6. ROB、提交与恢复

Nax ROB 按字段/访问粒度建多 bank RAM；completion 可采用寄存 bits 或每 completion port 一份 toggle RAM，与 allocation snapshot XOR 比较。commit pointer/line mask 可 retime；先选择最老 pending reschedule，再按顺序退休，最终 reschedule 与资源 free 扫描分开。[RobPlugin.scala:65–127,129–187](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/misc/RobPlugin.scala#L65-L127)、[CommitPlugin.scala:73–97,101–157,159–245](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/misc/CommitPlugin.scala#L159-L245)

A1 已有 allocation payload banking 和可选 completion payload banking，不能重复算作新优化。最可移植的是：把 payload 读与完成有效性判断分开、每个字段只有必要的读口、head 状态提前寄存、释放工作和前端恢复分别核算。

不能直接搬 Nax toggle-done 或裸 slot completion：A1 会接受变延迟外部返回，并以 full token + live window + recovery 共同授权 ROB/PRF 写。不同 flush/drain 契约下，一个迟到结果不得给复用 entry 完成。`RenameRob.live` 与 `completionAccepted` 必须作为一致权威；精确异常、双 retire prefix、同拍 recovery/completion/allocate 的优先级需要独立验证。

恢复建议分阶段：先局部化 kill/epoch 分发并保持现有逆序 map walk；测出 branch recovery 实际损失后，再单独设计 bounded checkpoint。不要以降低 rollback 表面周期为理由，让错误路径 store、MMIO 或旧 completion 穿越恢复。

## 7. LSU 与 cache miss 并发

### Nax 实际实现

当前默认启用 `lsu2/Lsu2Plugin`，不是旧 `lsu/LsuPlugin`。默认 LQ16/SQ16；shared address/cache/translation pipeline 和 committed-store writeback 分开；D$ 默认 2 refill、2 writeback slot。[Gen.scala:196–290](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/Gen.scala#L239-L290)

LQ 保存等待原因：具体 refill mask、TLB refill、具体 SQ feed/writeback。相关事件到来才 redo。store 查更年轻已执行 load，发现 hazard 请求重调度；load 从匹配的较老 store 做同地址同 size bypass，不满足条件就等待。[Lsu2Plugin.scala:282–345,1065–1128,1306–1365](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/lsu2/Lsu2Plugin.scala#L282-L345)

load-hit predictor 提前 wake，事后检查失败（包括 IO、translation、依赖、miss 等）触发 reschedule。它不是失败时清一个 ready bit 即可。`Lsu2Plugin` 构造默认 `loadWriteRfOnPrivilegeFail=true`，但正常 `Gen.scala` 使用 `sideChannels=false` 覆盖为 false；不能在迁移中漏掉这个覆盖。[Lsu2Plugin.scala:68–83,969–976,1183–1219,1280–1287](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/lsu2/Lsu2Plugin.scala#L1183-L1219)

D$ refill slot 分别保留 address/way、cmdSent、victim/writeback hazards、完成/ack 状态；writeback slot 保留 victim 数据准备、发命令、收响应状态。miss/refill/WB 之间只按真正 alias/ownership 条件等待。[DataCache.scala:914–1056,1081–1108,1222–1282](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/lsu/DataCache.scala#L914-L1056)

一个不可忽视的接口假设：上述 refill 接收有单一 `wordIndex`，多 transaction ID 不代表任意逐 beat 交错都可直接接收。迁到 AXI/TL 必须匹配 burst ordering 或每 owner 保存 beat index，不能只看“支持多个 outstanding”。

### A1 映射与优先顺序

A1 [`ParallelLoadStoreUnit`](../src/main/scala/core/ooo/lsu/ParallelLoadStoreUnit.scala) 是两个 `LoadStoreUnit` reservation owner，普通 RAM 可并行，串行类别与未完成 owner 受到明确限制；CPU replies 默认有序，实际 A1 没有 tagged return。现有 D$ 不是 blocking-only，但 `independentDemandAdmission`、某些 speculative store-proof 扩展并未默认开启。

优先工作：

1. 从 ROB 索引的 memory preparation/older-store 全窗口扫描中抽出专属 LQ/SQ metadata；load 地址准备、store 地址准备、store 数据准备分别建状态，避免晚 store data 无谓阻塞其 address disambiguation。
2. 将“完成寄存器结果等待 WB”与“占有外存事务 owner”分开计数，允许已接收响应的事务尽快释放真正可释放的资源，但绝不早于错误聚合/一致性 ACK/返回所有权要求。
3. 先保证现有 2 个 LSU owner、2 MSHR 在合法独立需求下可同时工作，再评估 4/8 owner。增加 capacity 时同步检查 response entries、TL source/sink、MSHR、store buffer、TLB、MMIO/AMO/fence、缓存 victim reservation 与 shared Home，不只扩大 `memoryEntries`。
4. 使用按事件重试的 wait-reason 状态减少反复无效扫描；稳定等待者不要每拍重新驱动完整宽地址比较和 PRF 路径。
5. 首批保持 load-hit speculation 关闭，保留 checked-result wake。未知老 store 的推测越过、memory dependence predictor、失败恢复是独立的大功能，必须先具备精确 replay/kill 的证明。

本地大耦合位置：[`IntegerBackend.scala:1565–1616`](../src/main/scala/core/ooo/integration/IntegerBackend.scala) 的 store-overlap/unknown-store/system-barrier 归约；[`NonBlockingCoherentLineCache.scala:8–53`](../src/main/scala/core/ooo/cache/NonBlockingCoherentLineCache.scala) 的 capacity/ownership 约束。

## 8. 最大化有用总线利用，而非增加空流量

Nax 的启示是保持不同阶段真实 owner 并发，而不是靠预取把总线计数器刷满。A1 需逐项核对信用链：

`ready load → LQ/LSU owner → translation owner → D$ request/response ticket → MSHR + victim/WB → TL source/whole-line transport → Home → AXI ID/AW/W/R/B → 返回 → result/WB credit`。

在 A1 只有 2 个 demand load owner、2 MSHR 时，即使 DDR bridge 支持更多 outstanding，也不能保证供得上持续 line 请求。容量应来自观测 latency-bandwidth product，而不是照 Nax 或随意翻倍。

简单分析上界（不是实测）：line 大小为 L byte、目标有用带宽 B byte/cycle、owner 从分配到可复用平均 T cycle，则需要约 `M >= ceil(B*T/L)` 个真正独立 owner。若 64-byte line、8-byte beat、T=40 cycle，2 owner 的理想 miss-only 饱和上界也只有 `2*8/40=40%` beat duty。实际 bank conflict、DDR refresh、仲裁、CPU 依赖会再降低；CPU 与 DDR UI 不同频率时必须先统一时间单位。

需要输出而非猜测的计数：

- CPU 实际 accepted request/cycle，不能用 valid offer 代替；按 load/store/prefetch 分类。
- LQ/LSU/MSHR/response/WB/bridge occupancy 分布、full stall 周期和 allocation-to-release latency。
- AXI AR、AW、W、R、B 与 TL A/D 每通道 handshake duty、backpressure duty、连续 beat 段长度。
- 有用 demand byte/cycle、独立 miss 并发数、dirty victim 与读请求 overlap；prefetch useful/wasted/throttled 分开。
- 相同流量、地址依赖、时延模型、cache 容量和随机种子下比较；不得通过减弱 ordering 或提高模型内存速度取得假提升。

现有 [`TileLinkAxi4OutstandingBridge.scala:9–20`](../src/main/scala/core/ooo/platform/bus/TileLinkAxi4OutstandingBridge.scala) 已区分 AW/W owner FIFO、完整 burst buffering、可选 unordered responses 等契约。本文不据此宣称这些选项均在真实 A1 平台实例启用；必须再沿 `CommonMachinePlatform` 的实际构造检查。

## 9. 前端预测：增加流水深度的配套工作

Nax fetch 级 BTB 同时预测 target、branch 类型和 instruction slice，GShare 预测方向；decode 级可补 direct jump/RAS 或纠正错误类型。预测上下文保存到专属 branch context queue，commit 后训练；speculative history 在 redirect 时恢复。BTB 读、命中、跳转可放不同阶段。[BtbPlugin.scala:51–127](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/prediction/BtbPlugin.scala#L51-L127)、[GSharePlugin.scala:67–99,113–128](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/prediction/GSharePlugin.scala#L67-L99)、[HistoryPlugin.scala:134–155](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/prediction/HistoryPlugin.scala#L134-L155)

A1 [`BranchPredictor`](../src/main/scala/core/ooo/frontend/BranchPredictor.scala) 是 commit-trained bimodal；[`RetirementReturnStack`](../src/main/scala/core/ooo/frontend/RetirementReturnStack.scala) 也是 retirement-trained，而非 Nax 的 speculative RAS。更早 BTB + GShare、前端队列与可恢复 speculative RAS 有望减少更深流水的气泡，但属于新功能，不是换表大小。

尤其不要忽略 Nax 的一个取舍：官方文档说明 RAS 恢复指针，不恢复已被推测覆盖的值。若 A1 引入 speculative RAS，应明确选择 pointer-only（允许预测质量损失）还是 checkpoint/shadow/undo 机制；错误预测永远不得变成架构错误。[官方预测说明](https://spinalhdl.github.io/NaxRiscv-Rtd/main/NaxRiscv/branch_prediction/index.html)

## 10. 推荐的重构边界与验证门槛

保留现有 A1 为可运行对照，候选以一个 coherent batch 建立以下边界；不是建议一次性并入所有高风险特性：

| 子系统 | 第一批目标 | 暂不默认打开 |
| --- | --- | --- |
| Rename/ROB | 状态职责拆分，双宽前缀接受，原 rollback 语义 | 未证明 checkpoint、token 缩短、move alias 改法 |
| Issue | 独立模块，窄 ready/class，局部资源信用，原双发射预算 | 更宽 issue、无约束全互联、直接移植整表移位 |
| PRF/execute | 保留 LVT，读口审计，受控 forwarding，稳定 completion owner | 在可 stall 流水上按固定拍数提前 wake |
| LSU | 独立等待原因/地址与数据状态，checked wake，真实 owner 并发 | unknown-store speculation、load-hit predictor |
| Cache/fabric | 严格保持 source/response/victim ownership，测 duty | 擅自无序 MMIO、早回收源 ID、忽略晚 burst error |
| Frontend | 早预测与上下文边界的设计，计数失预测代价 | 未验证 history/RAS rollback 的复杂预测器 |

第一批接受标准必须同时包含功能、周期和物理证据：

1. Scala 编译/配置检查；一次必要的短 GSIM 独立 oracle 检查，按受影响模块选用，禁止 Verilator。
2. 包内 RAW/WAW/x0，双 lane 同 rd，wake+reserve 同拍、dispatch+kill 同拍、stale completion、full/empty turnover、wrap、head exception、ordered retire；PRF、ROB、ready 必须服从同一 accepted-owner。
3. LSU RAW/WAR/WAW、partial mask、unknown address、forward、PMP/TLB faults、SFENCE/FENCE/AMO/MMIO、response backpressure、迟到错误、cancel 后 drain；不能拿旧核控制逻辑作 oracle。
4. 至少依赖 ALU 链、独立 ALU、load-use、独立 miss、store/load alias、branch 密集、混合 WB 竞争及总线随机回压短场景；报 IPC、周期、accept duty 和 occupancy，而不是只报模拟速度。
5. 候选功能与周期通过后，才做一次组合综合/实现，与冻结 A1 用同器件、同约束、同工具设置比较。保持用户的成批验证工作流，不在每次小改后跑实现。

300 MHz 对应 CPU 时钟周期约 3.333 ns。只有目标 FPGA 上、完整受约束设计、post-route setup/hold 与 CDC 检查通过，才能宣称 300 MHz 收敛。综合估算、单模块 benchmark、无约束路径或降低功能配置都不够。板级稳定性与长时间运行是另一个验证层次，不可由 STA 代替；在完成前均标记“未验证”。

## 11. License 与来源边界

所读 Nax 核心 Scala 文件均有 `SPDX-License-Identifier: MIT`。仓库 [`LICENSES/MIT.txt`](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/LICENSES/MIT.txt) 载有 Charles Papon 2021 版权与 MIT 条款；另有 `CC0-1.0.txt`，不能据此推断所有文件都是 CC0。

本文以源码行为归纳原则，未将 Nax 代码复制入生产 RTL。如果后续实质移植/改写源码，保留适用版权和许可文本、标明来源与 commit，并单独审计 SpinalHDL/其他子模块和生成资产的许可证。Nax 核许可证与其 HDL 工具依赖许可证是两件事；“用 Chisel 重写”本身不能抹去复制或派生代码的归属。

官方在线文档为移动版本，仅用于解释；出现差异以本文固定 commit 的实际源码为准。未使用第三方架构文章，未把 Nax 的 area/frequency 数字移作 A1 承诺。
