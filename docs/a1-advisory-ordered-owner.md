# A1 registered advisory exclusion / ordered owner readiness

## 结论与范围（2026-10-25）

本批是默认关闭的云端带宽/控制路径候选，不是物理签核或推荐 preset 升级。
在同工作量、同容量、同服务律的短 CPU 对照中，combined 热 load ROI 从359降到338拍；
**计入 drain 后总成本1085→1069拍，减少16拍（1.475%）**。
owner-only 在五个客体的495 scalar逐拍 trace及日志中保持 exact；combined 的冷 load、
Bare、VM stream/dependency 的 work+drain 没有改善。不能用局部 ROI 或组件理想供给率
替代端到端收益，也不能据此声称300MHz、Fmax改善、资源节省或整板性能。

基线提交：`51422f567dd8d15d72373ea4984d13ab3ed3650e`；开发分支：
`dev/a1-advisory-ordered-owner-20261025`。结果绑定下述源码、compile、emission和工具
receipt，不应仅凭分支名复用旧二进制。生产源码未因后续 host 恢复而更改。

## 配置与结构合同

新增 `registeredAdvisoryExclusion`、`orderedLsuResponseReady`，均 default OFF。
`FullR1M3OrderedOwnerReady` / `full-r1-m3-ordered-owner-ready` 是 owner-only 消融；
`FullR1M3AdvisoryOwner` / `full-r1-m3-advisory-owner` 是组合候选。
两者延续已有 buffered-return-flow-index 配置，旧 named policy 不隐式启用新选项。

### Advisory 只提供候选，不提供授权

`BufferedVirtualRamLoadPreparation` 新增一个 reset-zero 的16-bit register：

```text
mask[t+1] = indices(raw pre-edge D0,D1,T,R0,R1 valid owners)
          OR index(nominal queryAccept)
          OR index(nominal descriptorCapture)
```

这是每拍重新计算的一拍观察，不累计历史；无贡献即清零。不能替换成最终 next-valid，
不能把晚到的 issued cancellation、lookahead VA/size 冲突或 expiry 反向接入 mask。
原 nominal admission 的当前 full-key、epoch、freshness、权限条件仍有效；flush/stability
抑制 admission 是合法依赖。index-only ABA 最多暂时过度排除候选，不能产生 proof、
权限、live owner、execution credit或提前退休。完整 token/VA/size/epoch 的最终验证保留。

新组合模块 `OldestUncoveredMemoryPreparation` 在 eligible ordinary virtual loads 中，
先排除**原始 execution planner** 的 firstOwner/secondOwner，再排除 registered mask，
按 ROB circular age 取最老候选。不得从过滤后的 ordinary 集合重算前两名。
零 mask 与旧 rank-three 等价只适用于 all-ordinary eligible 集合，不适用于混合类型。
selector 无状态、零新增寄存延迟，每拍最多一个候选；复用第三路 source1 PRF read/AGU，
不改变两个 execution ranks。远端 advisory source 仍受 full-token source readiness、
无重分配/无 accepted overwrite 不变量保护。

### Ordered readiness 只适用于既定整数拓扑

`ParallelLoadStoreUnit` 的整数槽把 response.ready 专化为 registered response state，
其 ordered owner queue 同时设为 non-flow。前置 non-flow `RegisteredRequestQueue`
以及既定 StoreBuffer 路径保证新 owner 不会在同拍收到返回；不改变 generic start、
capture、result、publication 方程。FP LSU 不使用这一构造参数，tagged response-state
模式及其约束未被混同。取消已接受请求仍必须 drain；reset 仍要求协同复位。
这不是任意 direct-LSU 或零延迟 backing 接法的通用正确性声明。

### 不扩容审计

保持 ROB16、双发射、4 integer LSU、D2/T1/R2；15 logical PRF reads、30 bank reads
不增加。owner-only 无新增存储；combined 唯一新增存储为16-bit exclusion mask。
PRF、FP、request queue、StoreBuffer 的相应模块保持 exact。该结论是源码/FIR结构审计，
不是综合网表寄存器/LUT数量、布线或PPA测量。

## 性能口径

以下 control 为上批 buffered-return-flow-index，candidate 为 combined；周期是模型周期。
`work` 不含 drain；inspection 固定32拍，另列不混入有用工作。

| 客体 | ROI control→combined | work | drain | work+drain | 结论 |
|---|---:|---:|---:|---:|---|
| hot_loads | 359→338 | 1074→1053 | 11→16 | 1085→1069 | 净省16拍，1.475% |
| delayed_cold_loads | 358→358 | 902→902 | 7→7 | 909→909 | 无净收益 |
| vm_store_stream | 459→458 | 625→624 | 9→10 | 634→634 | 无净收益 |
| vm_dependency | 701→700 | 867→866 | 9→10 | 876→876 | 无净收益 |
| Bare ROM | 最终/ROI字段相等 | 6729→6729 | 无新增收益声明 | 不变 | 功能/周期不退化 |

热 ROI 减少21拍（5.850%），但这是窗口内结果。256个ROI load的 start→physical仍为3拍，
physical→reply仍为1拍，start→complete仍为5拍；收益来自供给间隔分布，不是单条load
延迟缩短。连续一拍 start gap由169增至191，二拍 gap由85降至62。
冷热的translation/PTE计数与工作量一致；冷 load 的37拍 physical→reply 服务延迟未改变。
冷load整体虽不变，completion residence的76拍计数12→11、77拍计数1→2，不能称全延迟相同。
组件的理想两/三rank供给实验只用于合同校准，不能外推CPU IPC。

owner-only 五客体495 scalar trace逐拍 byte/log exact：原四客体每variant 14,382,720 bytes，
Bare另有每variant 26,801,280 bytes。
trace合同只在有效事件下比较相应payload；`returnFlow.outputReady`在outputValid=false时
属于明确的无效ready例外，不应说所有原始引脚无条件全相等。
combined Bare 的完整诊断trace **不是**全byte exact：只有128拍 `bufferedProof.live`
发生变化，且这些拍五个owner.valid全0；其余494字段 exact，最终/ROI字段相等。

## 验证分层与盲区

- **配置/Scala**：最终r3 compile receipt通过，八个短Scala suites / 24 tests通过；不是全回归。
- **advisory组件**：11,932拍精确 temporal-mask oracle，7个phase定向、59个PMP案例；
  selector共1,214,116案例，其中mask/head穷举1,048,576。13类host采样负控均预期拒绝，
  包括missing query/capture/raw、phantom、self-hold、final-valid以及owner/权限/credit。
- **真实组件返回链**：baseline/owner_pair覆盖整数payload/fault/backpressure、取消drain、
  直接写ACK、local store转发与late drain、FP load/store完成、实际AtomicMemory的delayed/
  zero-cycle阶段、DTA invalid PTE/PMP拒绝、local fault、posted drain、协同reset。
  独立tag/data/cause/tval/atomic-phase/completion负控按两variant检查。
- **返回链补充r3**：48次start、16个index三代ABA、最大4 owner；取消与completion同拍时
  无架构完成且discard=1；成功VM epoch ABA四完成、六PTE读、两个epoch。
  两variant有效事件trace共278,528 bytes exact；tag/discard/epoch六个负控均拒绝。
  `cancel_before_request` 在固定ordinary拓扑不可达，明确不声明generic LSU覆盖。
- **CPU native atomic/FP smoke**：owner-only/combined各328拍、80退休、11 atomic replies、
  17 physical requests/replies、8 FP退休（FP epoch60拍），独立固定编码/期望值oracle通过，
  retirement observation负控拒绝。这是CPU native host transport，不是tile内AtomicMemory
  phase验证；后者只由上面的实际组件链补足，不能把两者拼成完整ISA/整板验证。

负控主要篡改host观测，不是重新构建RTL mutant。所有刺激有界，非任意状态形式化证明。
未跑本批 full GSIM、长Linux、完整NEMU/ISA回归、综合、实现、bit或上板。

## Full-tile结构与OFF兼容门

独立fail-closed层次FIR图包含最后连接语义与smem/invalid校准；三个variant完整图均无SCC。
门覆盖：无late issue/VA→mask/selector反馈、index所有消费者、ordered owner ready隔离、
无consumer ready→physical ready路径、无live reply→completion旁路和不扩容。
图在r2 emission执行，最终emission的FIR hash独立相等；这是identity延续，不冒称重跑图。

**`raw_source_only_fir_exact=false`。** 只批准13个assert source locator迁移：

| 文件 | 旧→新行 | 次数 |
|---|---:|---:|
| LoadStoreUnit.scala | 352→358 | 5 |
| ParallelLoadStoreUnit.scala | 276→277 | 4 |
| ParallelLoadStoreUnit.scala | 277→278 | 4 |

assert predicate/body不变；除此之外normalized bytes exact。四项校准
`diagnostic_body`、`assert_predicate`、`logic`、`unapproved_source_line` 均必须拒绝。
不能泛化成任意source locator忽略，也不能写成raw FIR byte exact。

## Receipt索引与复核顺序

所有路径相对仓库根；build产物不是源码交付的一部分，复核需保留原目录/manifest。

| 内容 | 路径 |
|---|---|
| 最终compile | `build/advisory-owner-20261025-r3/scala/compile-receipt.json` |
| Scala suites | `build/advisory-owner-scala-tests-20261025-r2/receipt.json` |
| emission | `build/gsim/advisory-owner-cpu-20261025-r2/emit-receipt.json` |
| 独立结构/容量/OFF | `build/advisory-owner-independent-structure-20261025-r1/structure-receipt.json` |
| advisory组件 | `build/gsim/advisory-exclusion-components-20261025-r2/receipt.json` |
| 返回链 | `build/gsim/ordered-owner-chain-20261025-r1/receipt.json` |
| 返回链identity延续 | `build/ordered-owner-chain-r3-continuity-20261025-r1/receipt.json` |
| 返回链补充 | `build/gsim/ordered-owner-supplement-20261025-r3/receipt.json` |
| CPU最终恢复 | `build/gsim/advisory-owner-cpu-recovery-20261025-r1/receipt.json` |
| 性能明细 | `build/advisory-owner-runtime-summary-20261025-r1/summary.json` |
| native smoke最终 | `build/gsim/advisory-owner-native-smoke-20261025-r2/receipt.json` |
| 最终验证/35文件identity | `build/advisory-owner-final-validation-20261025-r1/evidence-index.json`、`final-source-hashes.json` |
| 独立runtime复核 | `build/advisory-owner-runtime-independent-review-20261025-r1/REPORT.md` |
| GSIM工具epoch | `build/gsim-init-bytefix-20261025-r1/receipt.json` |

关键identity（SHA-256；其余见evidence-index）：

```text
build/advisory-owner-20261025-r3/scala/compile-receipt.json
  bd86525fa20b03084457ff0a365076c76f810d79663ccbca9b82a23b5bbbbe0a
build/advisory-owner-independent-structure-20261025-r1/structure-receipt.json
  b5aba91646c2c4e01f00180cdcec8836083e8d6506d14dac6192334e3dde0ceb
build/gsim/advisory-owner-cpu-recovery-20261025-r1/receipt.json
  53fc456014e4d9b6c922bebe01fa5b2a2c8eac1e907e35ab437dc9a8f84c6036
build/gsim/advisory-owner-native-smoke-20261025-r2/receipt.json
  22a7e9d1aadc412492ca08cfa9878c1b1aad911035762f99eef9f34903696e62
build/advisory-owner-final-validation-20261025-r1/final-source-hashes.json
  9116db8b0fecc03418289362853855b4643041f7c2fa1f91ab797dd0b21c5151
```

性能summary的历史status仍写native smoke pending；最终smoke状态以上表r2 receipt为准，
不覆写历史summary冒充当时已完成。工具epoch为GSIM pin
`93b8cd23edd3228807c4f2a08c19c3936a463cb2` 加独立初始化byte-span修复，
不是静默更换上游工具。所有host/model输入以receipt逐文件SHA-256为准。

复核先核对compile输入、emission绑定、工具epoch，再检查各receipt `inputs_unchanged`、
artifact hash、负控诊断与日志，最后按上述work+drain重新计算，不只读取PASS标签。
runner入口为 `advisory_exclusion_components.py`、`ordered_owner_chain.py`、
`advisory_owner_cpu.py`、`advisory_owner_cpu_continue.py`、
`advisory_owner_cpu_smoke.py`、`ordered_owner_supplement.py`（均在`simulator/gsim/`）。
CPU runner有分离的emit/build-run与compile/tool/structure/advisory/owner receipt门；
continuation要求failed receipt和continuity receipt，拒绝不匹配的已生成字节。
新执行必须使用唯一tag和新的输出目录，不覆盖旧receipt；当前文档复核不触发任何重建。

## 保留失败与恢复记录

1. r1 Scala compile通过，随后发现旧五个Spec的descendant allowlist漏列新配置，补充两个名字到r2；
   不声称这些测试在实际运行前失败。组件fixture又因
   旧保留词命名失败而改名至r3。保留原失败，不把前一轮compile PASS改写成整轮PASS。
2. CPU首次两个模型顺序构建遇到global compiler wrapper嵌套，报
   `exactly one independent host required for real-header API gate`。恢复修复host gate并先做
   两次顺序mock及missing-host负控，重用exact generated bytes；总计生成两个不同DUT，
   两个不同DUT最终实际完成编译。combined初次另有一次失败尝试，被wrapper挡在0个object，
   因而不能把“两DUT”理解为仅两次构建调用。恢复新增generation=0、完成DUT build=1。
   原CPU r2失败receipt及原artifacts保持不变，owner-only已完成运行不重复。
3. 返回链supplement r1/r2 host的VM epoch预期与reset相位不一致。r3在两个协同reset步骤前
   明确建立VM/PMP配置，独立相位预期从1到ASID/flush后的2，不读取DUT初始化oracle；
   保留失败并严格检查PTE计数[3,0,3,0]及新PA，不作宽泛豁免。
4. native smoke r1 host错误假设下游RAM/cache adapter的scalar lane0；改为strict lane1后r2通过。这是host oracle修正，
   非RTL修复；r1 receipt记录一次host编译，最终r2新增两次host编译（两variant），
   合计三次host编译；两轮均零新增DUT编译，旧失败保留。
5. 返回链补充r3复用原模型与continuity封存，只新编译两个host；无新增Scala或DUT构建。

## 物理状态与下一步判断

本批只建立有界功能、结构与模型周期证据。此前本地51422 Vivado运行被guardian预算停止，
没有DCP，最终exit未知；guardian v2仅dummy修复验证，没有第二次真实run。
该本地失败不能当作本批云端候选的成功或失败物理结果。

热供给收益已经出现，但冷延迟和VM端到端仍未改善；下一次优化应继续按固定服务律观察
有效请求/返回占比、owner占用与drain，不借扩容或更多PRF端口制造收益。
保留default OFF，物理PPA、实际频率与板级性能均未测。
