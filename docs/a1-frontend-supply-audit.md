# A1 前端供给审查与独立基线

日期：2026-10-24。审查起点 `47f42fa0d7d5c845053e325928749422de9b350c`，共享工作分支
`dev/a1-nax-inspired-300m-20261024`。本轮前端改动只新增测试，不改变生产请求协议、预测器、缓存容量或预取。
300 MHz 是目标，不是本文验证结论；I1 的实现报告不能用作 A1 时序证据。

## 1. 实际启用配置

`CommonCpuProfile.A1 → CommonA1CpuTile → FpgaNextConfig.Selected.coreParams`，而非
`OooParams()` 默认值，也非所有 FPGA-next 实验选项的并集。

- 基线 rename/complete/commit 为 2/2/2，ROB16、PRF48、LSU2、SB2。公共 A1 时钟参数是
  CPU100/fabric250/TIME250 MHz；现有 `performance300-static` 选择器只接受 I1。
- 前端 packet cache 是 16 sets × 2 ways × 8 bytes = **256 B**，不是 32 KiB。
- 物理 I-cache 是 512 × 64-byte line = **32 KiB**，2-way，banked data；只缓存 executable RAM aperture。
- `RegisteredFetchWindow` 是三个 8-byte packet 的每拍快照，不是三项在途请求队列。
- `RegisteredFetchPacket` reservoir 是四条指令、每拍最多两条入/出，使用前一拍占用产生输入信用。
- 32-entry、2-bit、退休训练的 bimodal direction table；没有 GHR/gshare。
- 32-entry accepted-successor hint 保存完整 PC、指令与预测 next PC，是提前供给提示，不是一个正式 BTB。
- 8-entry RAS 在退休时 push/pop；`indirectTargetEntries=0`，独立间接目标表没有实例化。
- ITLB 为 8 entries，Sv39 walker 一个 miss owner；四项 non-leaf PTE cache。I/D walker 独立，但共享后端 PTE/data 仲裁。
- Selected 已有 identity fetch bypass、reply/request turnover、registered fetch window/packet、prediction-training stage。
  `fetchPreviousPacket`、aligned permission stage、address-before-PMP、compact fetch keys 不属于这个基线。

源码：[`CommonCpuProfile`](../src/main/scala/platform/CommonCpuProfile.scala)、
[`CommonA1CpuTile`](../src/main/scala/platform/CommonA1CpuTile.scala)、
[`FpgaNextConfig`](../src/main/scala/core/ooo/config/FpgaNextConfig.scala)、
[`BoardSocConfig.params/timingParams`](../src/main/scala/core/ooo/platform/BoardSocTop.scala)。
后端/内存本轮 opt-in 候选可能另有容量；本测试刻意使用未变的 Selected 前端基线。

## 2. 两条/拍供给的实际限制

### 2.1 从内存补给不是流水化的两条/拍

`SynchronousFetch` 明确只有一个 `pending` 和一个未接受的 locked offer；接受新 packet
必须等旧 response。同拍 turnover 只消除交接气泡，不增加在途容量。双宽分支仅请求
current/current+8，虽然对齐器能查看第三个 packet，并不会主动向更远的 sequential frontier 补给。

`InstructionTranslationAdapter` 又有唯一 `virtualPc/requested/firstPhysical/data/errors/pageFaults`
及八态 FSM。M-mode/Bare 最乐观路径仍是：接受 virtual request → send physical → 一拍 I-cache hit
response → registered virtual reply。因而持续消耗全新 packet、每包两条 32-bit 指令时，即便
所有物理 I-cache 命中且无其他 stall，单 owner 的结构上界也只有约 **8 B/3 cycles**，即
**2/3 条指令/拍**；普通 ITLB hit 多一个 translate phase，约 **8 B/4 cycles**。
这些是由状态边界推导的条件上界，不是测得的 core IPC；小循环命中前级 256 B packet cache 不受这个补给上界。
注册窗口、前端 cursor、真实 miss/ROM/fabric 服务还可能使实际值更低。

`InstructionRequestBuffer` 虽有两项、II=1，不能替上游 adapter 创造第二个 response owner。
`InstructionLineCache` 的 fill engine `entries=4` 同样不等于四个需求 MSHR：唯一 FSM/savedPc
只容一个 demand；公共 A1 明确 `prefetchEnabled=false`，两个 prefetch slot 不投入工作。

源码：[`InstructionRom.scala:SynchronousFetch`](../src/main/scala/core/ooo/platform/memory/InstructionRom.scala)、
[`InstructionTranslationAdapter`](../src/main/scala/core/ooo/mmu/InstructionTranslationAdapter.scala)、
[`InstructionRequestBuffer`](../src/main/scala/core/ooo/platform/bus/InstructionRequestBuffer.scala)、
[`InstructionLineCache`](../src/main/scala/core/ooo/cache/InstructionLineCache.scala)。

### 2.2 Reservoir 与 RVC

四条 reservoir 可在占用为 2 时连续两入两出。它不是“只能隔拍双发”：占用为 4 时的
同拍消费不向输入借信用，会丢一次 capture 机会，但随后恢复。扩大 FIFO 可以吸收短突发/分支恢复，
不能解决上述 byte/cycle 补给不足。

RVC 每条 2/4 bytes，由三个相邻 8-byte packet 拼接。32-bit 指令可在 packet、64-byte line、
4 KiB page 末尾跨界，必须保留第一/第二 parcel 的独立有效性与 fault tval。页末 PC=4094
不意味着一个 8-byte request 跨页：真实 request base=4088 与 4096 分别翻译，再由前端拼接。
现有通用 adapter 仍保留 4092 起始的 generic cross-page FSM，虽然这个 Selected aligned caller 不会进入它。

预测 taken 的早 lane 截断 raw packet；`IntegerCore` 又只接纳 sequential prefix，并在 earlier
prediction 后禁止后续 lane。因此“taken branch + 目标第一条同拍双发”不是当前接口能力，
即使 BTB/RAS 命中也不能无条件得到两条有效接纳。

源码：[`RegisteredFetchPacket`](../src/main/scala/core/ooo/frontend/RegisteredFetchPacket.scala)、
[`RegisteredFetchWindow`](../src/main/scala/core/ooo/frontend/RegisteredFetchWindow.scala)、
[`ParallelFetchAlignment`](../src/main/scala/core/ooo/frontend/ParallelFetchAlignment.scala)、
[`IntegerCore`](../src/main/scala/core/ooo/integration/IntegerCore.scala)。

## 3. 为什么 CPU-ROM 路径慢

ROM `0x80000000..0x8001ffff` 不在 RAM aperture `0x80200000..`。因此 32 KiB I-cache 的
`inRam/lineAllowed` 为 false，转入 `InstructionTileLinkBridge` fallback，每个新 8-byte packet
都走 TL Get、注册 fabric boundary/crossbar、ROM manager、同步 ROM、回程及翻译 adapter reply。
ROM 自身两 bank 可 II=1，并不说明 CPU 端能连续每拍送一个 request。

fallback 的一个 immutable 64-bit beat 只对 full+odd packet 重叠复用。这个 A1 前端 request
总是 8-byte 对齐，`startOdd=0`，所以不能借该 beat cache 跳过下一次 ROM Get。
实际重复代码主要依靠前级 256 B packet cache；128 KiB ROM 不享有大 I-cache 容量。

这解释了结构风险，不能据此给某个已测 ROM 程序分配精确 CPI 百分比。当前短 CPU-ROM
测试包含分支、依赖、访存、CDC 等开销；它不是单独的 L1 吞吐测试。
历史 `frontend-performance-diagnosis.md` 测量的是另一个 8/32-line board profile，也不是
当前 Common A1 的 512-line 证据，不应直接沿用其中的 miss rate 或 IPC。

源码：[`InstructionLineCache`](../src/main/scala/core/ooo/cache/InstructionLineCache.scala)、
[`InstructionTileLinkBridge/TileLinkInstructionRomAdapter`](../src/main/scala/core/ooo/platform/bus/InstructionTileLinkBridge.scala)、
[`CommonMachineFabric`](../src/main/scala/platform/CommonMachineFabric.scala)。

## 4. 预测与扇出边界

- PHT 用半字地址低位索引、无 tag 的 bimodal，alias 与没有历史相关性是容量/精度限制。
  两条同 index retirement 按程序顺序 fold；`CommitPredictionTraining` 延后一拍，II=1。
- RAS 只读 pre-edge 退休状态。未退休 call/return 不改变预测栈，短调用或多个嵌套未退休调用
  可能使用较旧栈状态。这是保守正确性方案，不是 speculative RAS。
- 间接跳转只有 adjacent AUIPC+JALR 已知目标、RAS return，以及未启用的可选 table 分支。
  一般 indirect 没有独立 predictor；raw successor hint 还可能与新的 decode prediction 不同，导致局部 correction。
- `ParallelFetchTagLookup` 对每个查询做 16 sets × 2 ways 的 full64 address/context 相等比较和归约，
  多个邻包查询共享宽 PC/上下文。payload 仍从寄存 packet arrays 选出。
- raw cursor → RVC length/alignment → hint/full-PC match/direct target → prefix capture/correction，
  以及 retire→RAS/PHT fanout，都是需要实际 A1 STA 检查的候选路径。已有寄存/并行资格检查不能
  当作零路径代价；本审查没有将逻辑深度、source mux 数或 I1 fmax 换算成 A1 MHz。

源码：[`BranchPredictor`](../src/main/scala/core/ooo/frontend/BranchPredictor.scala)、
[`CommitPredictionTraining`](../src/main/scala/core/ooo/frontend/CommitPredictionTraining.scala)、
[`RetirementReturnStack`](../src/main/scala/core/ooo/frontend/RetirementReturnStack.scala)、
[`ParallelFetchTagLookup`](../src/main/scala/core/ooo/frontend/ParallelFetchTagLookup.scala)。

## 5. 本轮新增：独立实际生产模块供给 fixture

入口：`src/test/scala/ooo/A1FetchSupplyGsim.scala` 与 `simulator/gsim/a1_fetch_supply.py`。

生产链保持为：Selected SynchronousFetch → InstructionTranslationAdapter → empty-flow request buffer
→ InstructionLineCache → 返回链 → registered window/alignment → FetchPacketPermission →
RegisteredFetchPacket。另接真实 8-entry ITLB、三级 walker、4-entry nonleaf cache。
只把 physical I-cache 从 512 缩到 8 lines，以保持检查小而清晰；不能拿该容量的 miss 数据代表公共 A1。
没有 IntegerCore、真实 rename/执行/retire、Common fabric/CDC 或 ROM manager；TL/PTE 服务由固定 host law 提供。

九组 fixed-work 输入：ROM32、RAM32、混合 RVC 边界、consumer/TL/PTE backpressure、
redirect 后旧 response、Sv39 跨页、Sv39/PMP/TL-bus 第二 parcel fault。外部内存由独立字节函数生成，
逐 consumed instruction 核 PC/data/fault/tval；TL source 与 ordered virtual/physical owner 各自记账，
只有最后 D beat 才释放 source。每项最后 pause 新工作并 drain 已接受事务，不用 reset 丢弃 owner。

统计 raw/capture/consume 0/1/2、reservoir 0..4、request/reply latency/inflight、TL Get extent/beat、
ITLB hit/PTW/PTE。周期直方图独立检查总和。输出是 **供给周期统计，不是 core IPC**。
四个 observation negatives 注入 PC/data/tval/source；另有不依赖 GSIM 的 byte/ownership/histogram negatives。
它们不是 DUT source mutants；branch training、SFENCE context churn、同时 I/D PTW 争用另行验证。

固定 service law 与资源写入 receipt，后续对比同时检查相同 instruction stream 与 TL Get
地址/extent/数量。外部服务律没变但 traffic 不相同，不能称作 matched-traffic 性能提升。

```sh
source /workspace/shared/valence-a1-toolchain-r1/env.sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/a1_fetch_supply.py --oracle-only
GSIM_CXX=clang++-19 python3 -B simulator/gsim/a1_fetch_supply.py \
  --gsim /path/to/reviewed/gsim --tag a1-fetch-supply-UNIQUE
```

统一批次检查已完成：host-only ASan/UBSan oracle、真实模块九组GSIM场景与四个observation negatives全部通过。
证据为 `build/gsim/a1-fetch-supply-20261024-r1/receipt.json`、`test.log`；统一运行日志在
`build/a1-candidate-20261024-r1/frontend-run.log`。receipt绑定完整production源、fixture/driver/oracle、
工具哈希及固定service law，没有用旧报告替代本次执行。没有运行Verilator、长程序、完整回归或综合。

### 本次供给结果（不是core IPC）

| 场景 | 独立核验指令数 | work cycles | 关键实际事件 |
|---|---:|---:|---|
| ROM32 | 128 | 580 | 65个8B Get，64个双条消费拍，516个无消费拍 |
| RAM32 | 128 | 332 | 总9个64B Get，其中8个在工作ROI；64个双条消费拍 |
| RAM RVC边界 | 256 | 644 | 64个单条、96个双条消费拍，逐字节与PC全核验 |
| RAM backpressure | 256 | 688 | reservoir满4条共65拍，无丢失/重复 |
| ROM redirect旧reply | 128 | 1034 | 确实归还1个旧stream response，新路径PC全核验 |
| Sv39跨页 | 128 | 433 | 48 TLB hits、2 walks、4个真实PTE reads |
| Sv39第二parcel fault | 1 | 59 | 正确page fault及VA tval，不对失败页发instruction request |
| PMP第二parcel fault | 1 | 25 | 正确access fault及VA tval |
| ROM第二parcel fault | 1 | 22 | 总线拒绝传到正确access fault及VA tval |

所有场景观测到virtual/physical request最大在途数均为1。ROM32的virtual累计latency为585、physical为455，
差为`2×65`；RAM32分别348、218，同样差为`2×65`。这直接验证了该Bare路径每packet额外两个adapter周期，
但没有单独测完“所有I-cache hits”的稳态8B/cycle witness；下一批S0明确要求补齐它。

报告口径：work cycles及raw/capture/consume/occupancy直方图、`roi_get*`只覆盖工作ROI；
virtual/physical request与latency、总Get/D beat包括最后drain。RAM32的第9个cache miss在ROI内接受，
对应Get在drain发出，故不能把9与`roi_get64=8`当作账错，也不能将全程latency总和除以ROI请求数。
ROM/RAM同128条plain32的instruction hash相同，但外部Get形状不同；这是两个路径的诊断，不是
某个改造前后的matched-traffic speedup。cache仅8lines、host TL首beat latency=7等范围限制仍然适用。

## 6. 后续首批生产前端结构建议，尚未实现

### 必须作为完整 owner 链设计，不能只把 pending 改成计数

1. 定义 fetch request/response 的 slot+generation/context 身份，先保持两项有序输出；内部服务可以
   完成乱序，但完成槽必须保留 bytes、mask、per-word access/page fault、VA/PA、epoch。
2. 两项 translation owner 与两项 physical/return credit 配套。ITLB hit 可流水，miss 单独占 miss owner，
   不能让 hit 偷用等待 PTW 的请求上下文。先不扩 walker 数量。
3. 两项 demand I-cache owner 与 tag/data read pipeline、miss ticket、response slot、TL source 一起设计。
   fill 的每 owner beat count、victim reservation、line-error→精确 word retry 都不能共用唯一 saved*。
4. frontend reservation ledger 与 parcel/window supply 分离。redirect 取消可见性，不撤销已接受的外部事务；
   stale response 必须 drain，且不得覆盖较新 generation 的 live payload。
5. credit 释放只依据真实 response consumption；FENCE.I/SFENCE/PMP/privilege 变化继续等待全部 owner drain，
   including locked-but-unaccepted offers。容量变化必须同时更新 quiescent/runtime park/fence 路径。

单独的这五项已经跨越 SynchronousFetch、InstructionPort、translation adapter、request buffer、I-cache、
fallback、TL source、VM/fence 集成与验证，**不计入当前已完成改动**。
两 owner 也不是保证 8 B/cycle 的充分条件：在三拍 owner 生命周期下，两个 8-byte owner 仍不足以理论持续
8 B/cycle，需要进一步将 hit path 流水化、增加有界信用或扩大一次返回的有效 bytes，并用 oracle 保持 fault 边界。

### Nax 的可迁移组织方式

固定 Nax commit `9f452d50560d02fb391bc8039f5453c54e0911af` 的
[BtbPlugin](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/prediction/BtbPlugin.scala)
将同步表读、hit、jump 分阶段；
[GSharePlugin](https://github.com/SpinalHDL/NaxRiscv/blob/9f452d50560d02fb391bc8039f5453c54e0911af/src/main/scala/naxriscv/prediction/GSharePlugin.scala)
将 history/index/counter context 随 fetch/branch 运输。A1 可采用同样的“早预测+显式阶段所有者”，
不应只往现有晚 decode critical path 加更大的异步表。

之后可独立评估小同步 BTB、gshare、checkpointed speculative RAS/GHR；必须给每个 accepted
control instruction 保存训练/恢复 context，同 index 多训练有顺序，同拍 redirect/训练有优先级。
仅回滚 RAS 指针无法恢复推测 push 已覆盖的旧栈项；应使用 undo log、checkpoint payload 或
受证明的 committed/speculative 双份策略。当前 commit-only predictor 应在这项证明完成前保持不变。

独立 oracle 应扩充为 parcel queue + fetch owner ledger + predictor serial model，覆盖两个返回
交错/同拍 turnover、错误页与有效页混合、C.J/C.JALR/regular JALR、GHR rollback、RAS overflow/underflow/
overwrite、PMP/SFENCE drain、stale generation/wrap。始终保持实际所需字节和服务律，不靠新增越界预取
或更多无用 traffic 掩盖需求供给不足。关于更广的 Nax 研究见
[`naxriscv-a1-microarchitecture-study.md`](naxriscv-a1-microarchitecture-study.md)。
