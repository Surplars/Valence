# A1 fetch 第一边界实施提案：真实 context / response 通道

状态：**S1已接入生产，r2增量编译、九场景全字段等价与新增短测全部通过**。2026-10-24。
完整结果与边界见 `a1-fetch-stage1-results.md`。
首批基线为 `aaa2af4fee09abc42e0b80c9baa1cc5e00897f6c`；其供给fixture/driver/oracle保持原字节。
本文承接 `a1-fetch-pipeline-contract-draft.md` 的S1/S2，不宣称多owner供给已完成。

## 1. 唯一选择：现有 translation-adapter 接受边沿

第一项实际改造选在 `InstructionTranslationAdapter` 当前
`if (p.registeredTranslationHeads)` 分支的 **virtual request/context接受寄存边沿**。

不是在 `SynchronousFetch` 外面再加一个FIFO/寄存器，也不是写一个没有接入生产链的token模块。
把该分支抽成真实使用的 `RegisteredInstructionTranslationEngine`，通过显式command/result通道工作：

```text
SynchronousFetch（不改）
  InstructionPort
InstructionTranslationAdapter（公共IO不变的兼容shell）
  InstructionFetchTransactionBoundary（真实token/credit/route）
    FetchTransactionCommand(VA, mask, SATP context, privilege, token)
  RegisteredInstructionTranslationEngine（原registered-heads逻辑）
    FetchTransactionResult(token, data, access/page faults)
  InstructionFetchTransactionBoundary（检查归属后返回原InstructionPort）
  InstructionRequestBuffer / I-cache / ITLB / PTW（全部不改）
```

Common A1及当前供给fixture本来就实例化这个adapter。因此上述模块在生产真实链中处理每个
accepted request、正常物理返回、translation fault、zero-mask fault-only和held reply；
不需要修改CommonA1CpuTile或IntegerCore来制造一个看似接入的旁路。

## 2. 本步增加什么、不增加什么

### 增加

- 真实command/result类型，request与translation context同一个acceptance事件运输。
- 一个有终结事件的transaction身份，用于result route与one-owner credit释放。
- 独立translation engine模块，IO不再由“裸VA请求+散落live VM输入+无身份response”组成。
- 明确的same-cycle旧response/new-command turnover优先级及独立错误注入。

### 不增加

- **新增流水latency=0**。复用原virtual-acceptance寄存边沿和原reply寄存边沿，不插额外拍。
- transaction capacity仍为1；frontend、translation、I-cache需求并发均不在本步扩大。
- 不扩大cache、reservoir、lookahead，不打开预取，不改变host service law。
- 不改PMP采样时间、不绕过execute检查，不加入speculative GHR/RAS。
- 不把unused/dummy的streamEpoch字段设为0后宣称已有epoch取消。当前stream stale处理仍由既有
  SynchronousFetch/上层redirect负责；本通道一律精确drain已经接受的owner。

这一阶段可以只保持性能。它的价值是：下一步能够独立替换translation owner执行策略，而不用
再次同时重写调用者、上下文采样、返回路径和Fault metadata接口。
它**不是**“已消除单pending”或“已达8B/cycle”。

## 3. 精确内部接口

### 3.1 FetchTransactionCommand

- `token`：首次采用64-bit generation identity；每次真实command acceptance前分配一个值。
  当前只有一个slot，不额外传一个恒零slot字段。后续N-owner时再规范slot+generation编码。
- `virtualAddress: UInt(64)`
- `requestMask: UInt(packetWords)`
- `satp: UInt(64)`，包括mode、rootPPN、ASID。
- `sum, mxr, privilege`：与原接受边沿完全相同的捕获值。

命令通道为Decoupled。合法上游trace必须维持held offer的VA/mask/context稳定；
command的acceptance与旧virtual request的acceptance在合法trace中一一对应。
这是caller前提，不是本boundary提前快照live VM的能力；尤其关闭turnover时，旧result释放拍
command可以valid而engine尚未ready，caller必须把VA/mask/context保持到下一拍真实acceptance。
不得额外提前接受一个旧adapter原本尚未接收的请求，否则会改变context采样、idle和流量。

### 3.2 FetchTransactionResult

- `token`：由engine在command fire时保存的原始token，而不是在返回时读取边界当前token后拼接。
- `data: UInt(packetWords*32)`
- `accessFaults, pageFaults: UInt(packetWords)`

result在原来的reply状态有效，原有data/errors/pageFaults寄存器保持方式不变。
不另加response FIFO或empty-flow特殊路径。

### 3.3 PMP与epoch的诚实边界

`pmpState` 在首步仍按现有registered-heads实现送入engine，物理发送阶段首次offer时捕获mask/fault。
不改成在virtual-acceptance时快照整个PmpState，否则会改变已有语义和成本。
上层现有PMP/SFENCE/fetch drain屏障仍确保owner活跃期间权限上下文稳定。

首步的transaction token是**完成身份**，不是branch epoch，也不是PMP版本。
正式streamEpoch/contextEpoch只会在后续调用者提供真实取消/发布事件的阶段接入；
不能从PC是否跳变猜epoch，更不能把这个小改造写成已有完整epoch恢复链。

## 4. Boundary的真实状态、credits和优先级

状态只包括 `occupied`、`activeToken`、`nextToken`。VA/context本体留在engine原来的接受寄存器，
不无意义再复制一份宽context。

### Acceptance

1. engine必须有原来的接受资格：idle，或者开启fetchReplyTurnover且旧reply真实消费。
2. boundary必须为空，或者本拍旧token的result真实被virtual response消费者接管。
3. 两者同时满足时，`upstream.request.fire == engine.command.fire`。
4. engine在原接受边沿保存command token/context；boundary保存同一个activeToken并增加nextToken。

不依据`result.valid`独自释放credit，也不因为redirect、PMP fault或某个physical request enqueue释放credit。
一项fault-only请求同样占owner，直到其fault response被真实接管。

### Return route

1. engine result.valid时必须同时有occupied且token==activeToken，否则断言为协议错误。
2. 返回payload/错误位只从这个已匹配owner传给virtual InstructionPort。
3. result fire与virtual response fire必须相同；只有这个事件释放occupied。
4. `result.valid && !ready`时token/data/faults稳定，全部维持旧owner。

### 同拍旧返回与新请求

组合可见的result属于旧activeToken；同拍command使用nextToken。
边沿更新中，新allocation优先于旧release清空，形成新的occupied/activeToken。
engine的旧result data在该边沿之前有效，新的request初始化只影响边沿之后的数据。
不能把new command token组合回到旧result，也不能让旧clear覆盖新owner。

### Idle与wrap

`adapter.idle = boundary.empty && engine.idle`，在所有合法trace下必须与旧adapter.idle同拍一致。
nextToken按模2^64增加。64位是首步保守诊断选择，不是源自ROB tag宽度，也不是单owner正确性所需的最小宽度。
当前一个owner必须完全终结后才能复用slot；对相同编码的回绕复用还要求旧token已无外部义务。
独立fixture另用2-bit参数检查256个合法事务/64次drained回绕，不声称它能区分回绕后任意迟到重复包。
64-bit不是对任意恶意无限迟到重复包的永久唯一性保证；外部TL/PTW所有权规则仍不可省。

## 5. Engine机械抽取规则

只移动旧registered-heads分支，不改其状态图或计算策略：

- `idle / translateFirst / translateSecond / sendFirst / waitFirst / sendSecond / waitSecond / reply`
- 原identity translation选择、reply turnover、zero mask处理。
- 同页/跨页路径、secondVirtualPc/secondPhysical与precise first/second-word fault聚合。
- alignedFetchSinglePage/fetchReadyDataClear等已有配置分支保留，不趁抽取删掉generic支持。
- 首次physical offer的permissionCaptured/allowed/errors/pageFaults与背压稳定性不变。
- 原request初始化、translation response、physical response、old reply release之间的覆盖优先级不变。

引用替换是受审查的小集合：

- 原virtual.request/mask + live vmState/privilege接受值 → command.bits的相应字段。
- 原virtual.response及fault vectors → result的payload字段。
- 新增activeEngineToken在原request fire时捕获，reply token来自该寄存器。
- physical InstructionPort、SvTranslationPort、pmpState均直接作为engine IO向外连接。

未使用registeredTranslationHeads的其余两个adapter实现分支完全不动。
不为“顺便简化”改变inactive payload、mask计算、PMP helper或cache的任何逻辑。

## 6. 本步latency / II / capacity矩阵

| 边界/模块 | 之前 | 本步之后 | 本步验收 |
|---|---|---|---|
| virtual accept → context保存 | 原接受边沿 | 同一边沿，真实command | handshake/context完全一致 |
| transaction credits | 由FSM隐含1项 | boundary明确1项+engine原资格 | 同拍turnover不丢credit，不提前接收 |
| Bare+I-cache hit virtual response | 最乐观约3 cycles | 不变 | per-owner latency trace一致 |
| ITLB-hit virtual response | 最乐观约4 cycles | 不变 | translation request/response周期一致 |
| adapter持续packet II | 单owner受完整latency限制 | 不变 | 不宣称II=1热命中系统 |
| physical request queue | 2 entries/empty flow | 原模块不改 | offer/ready trace一致 |
| I-cache | Common512 lines，fixture8 lines | 不变 | Get地址/size/source/数量/周期一致 |
| window/RVC/reservoir | snapshot3 packets + 4 instructions | 原模块不改 | consumed PC/data/fault/tval及周期一致 |
| 新增流水寄存级 | 0 | 0 | 不将抽取称为新增时序级或fmax提升 |

第一步若580/332变成任何其它值，或者Get trace改变，视为unexpected regression/change，
先定位而非用“这是重构正常代价”放过。下一步真正新增一级时才按BDP补owner/返回信用并测吞吐。

### 物理成本尚未证明

虽然没有新增cycle，boundary新增occupied、nextToken、两侧保存的activeToken及64-bit equality。
`matches → response.valid/result.ready → releasing → credit → command.valid/request.ready` 是新增组合路径。
综合可能合并两侧同事件保存的token，但尚未验证；不得将零cycle写成零面积/零Fmax代价或300MHz保证。
未来缩短tag必须建立有限owner、terminal/drain和复用合同后独立验证，不为缩短路径删除身份核验。

## 7. 精确文件scope（已经批准）

### 生产源码

1. 新增 `src/main/scala/core/ooo/interfaces/FetchTransaction.scala`：command/result bundle及字段约束。
2. 新增 `src/main/scala/core/ooo/mmu/RegisteredInstructionTranslationEngine.scala`：移动现有
   registered-heads分支，接口换成typed command/result，保持原边沿和状态转移；同文件包含独立的
   `InstructionFetchTransactionBoundary` helper模块，负责真实one-owner credit、token分配、result route与断言。
   不额外创建另一个生产文件，便于遵守批准的engine/types/wrapper范围。
3. 修改 `src/main/scala/core/ooo/mmu/InstructionTranslationAdapter.scala`：只将registered-heads
   分支换成上述两个实际子模块及连接，其余分支与公共IO保持不动。

不改CommonA1CpuTile、IntegerCore、SynchronousFetch、InstructionRequestBuffer、I-cache、ITLB/PTW、
FpgaNextConfig、OooParams或公共Selected容量/ISA/prefetch配置。
这是cycle-preserving decomposition，优先不增加一个永久实验配置开关；若root要求显式off/on，
应另行批准profile plumbing范围，不能偷偷扩到多个config/平台文件。

### 新增验证

4. `src/test/scala/ooo/FrozenInstructionTranslationAdapterBeforeTransactionBoundary.scala`：
   从已冻结源保存原adapter，仅改class name，用作cycle comparison，不作为ISA/fault唯一oracle。
5. `src/test/scala/ooo/FetchTransactionBoundaryGsim.scala`：host驱动typed engine端的独立boundary fixture。
6. `src/test/scala/ooo/InstructionTranslationTransactionGsim.scala`：旧/新真实adapter共享外部stimulus的
   cycle comparison，覆盖正常/背压/fault/turnover，不改变production inputs。
7. 新增 `simulator/gsim/fetch_transaction_boundary/` host oracle/driver及
   `simulator/gsim/fetch_transaction_boundary.py` 短检查入口。
8. 当前 `A1FetchSupplyGsim.scala`、其driver与固定service law**保持原字节**，直接跑生产新adapter
   并对比已保存 `a1-fetch-supply-20261024-r1` receipt。不是换一个更容易通过的新benchmark。
9. 更新本文/结果说明，附源与工具哈希、旧/新trace/hash以及未覆盖范围。

## 8. 必要正例与负例

### Boundary独立事件模型

- 一项command接受后分别延迟1/2/7/17拍完成；upstream和engine两边独立ready节奏。
- old result与new command同拍：旧payload/旧token返回，新context/新token捕获。
- old result释放但engine commandReady=false：offer保留，下一拍原context/token接受，不先快照live VM。
- result停顿时试图送新command，必须保持credit不足，不覆盖activeToken。
- mask=0、仅word0/word1、正常mask；正常data/access/page fault都通过相同终结协议。
- 在合法context发布边界切换SATP/ASID/privilege，并检查command捕获值与后续held结果。
- reset清空本模块时只在整个fixture无外部义务的初始边界使用；不靠reset逃避drain。

独立negative至少四项：

1. 完成token改成另一个generation，必须在route处拒绝，而不是把任意data交给当前请求。
2. 已释放owner再次返回同一token，必须检测无owner/重复completion。
3. held result改一个fault位或data位，host稳定性oracle必须拒绝。
4. 同拍turnover故意将新context/token归到旧result，独立ordered history必须拒绝。

### Adapter全链语义

- 旧/新virtual/physical/translation valid/ready、idle及所有有效payload逐拍一致。
- 同拍translation request/response（hit），长PTW wait，page/access fault，PMP zero/partial mask。
- exact Selected two-word stream、generic two-word cross-page stream以及four-word isolated分别核。
  Selected stream包含identity与turnover；generic stream保留identity但关闭turnover，
  实际持续offer下覆盖old reply释放、新offer需held到下拍的窗口；four-word保持
  turnover=false/identity=false，并含同拍translation请求/返回。
  独立host沿用已有byte-range PMP oracle，不因Selected不走generic路径而删掉它。
- physical request/result背压下payload/permission mask稳定；new request与old reply turnover。
- 独立parcel/byte oracle仍检查指令与fault，避免old/new复制同一个错误后互相“证明”。

### 端到端基线必须精确保持

| 原场景 | 指令数 | work cycles |
|---|---:|---:|
| ROM32 | 128 | 580 |
| RAM32 | 128 | 332 |
| RAM RVC边界 | 256 | 644 |
| RAM backpressure | 256 | 688 |
| ROM redirect旧reply | 128 | 1034 |
| Sv39跨页 | 128 | 433 |
| Sv39第二parcel fault | 1 | 59 |
| PMP第二parcel fault | 1 | 25 |
| ROM第二parcel fault | 1 | 22 |

所有instruction hash/Get extent hash、owner数、latency总和、直方图与drain结果也应相同，
不只看两项cycles。沿用四个PC/data/tval/source observation negatives及host ASan/UBSan oracle。
这些是供给统计，不是core IPC；还要复用本批已有的必要短core同binary检查确保实际接入无功能回退。

## 9. 接下来如何逐项解除限制，而不是一次重写

### F2：先改变adapter的owner实现，保持调用者/缓存不动

typed command/result已是实际接口后，将context admission/translation-hit/permission/return分别拆成
有界模块。先通过可同时输入多个typed commands的独立fixture验证N-owner，不把当前
SynchronousFetch仍为one-pending的整链称为已加速。
legacy physical InstructionPort可使用真实accepted-command的ordered route FIFO对返回绑定身份，
因为现有I-cache返回有序且hit能turnover；先不把I-cache一起重写。

### F3：激活供给侧真实多owner

在adapter已能保存所有contexts、返回route和completion slots后，修改SynchronousFetch：
请求cursor与parcel消费cursor分离，streamEpoch来自明确的取消事件，按预留返回credit发command。
这才解除frontend单pending，实际全链应开始体现热供给变化。
必须新增长热命中持续供给witness，同时保留当前九个相同byte/service场景和真实miss/redirect。
不能简单把current/current+8选择器改成无界prefetch扫描。

### F4：逐个增加真正的时序级

每次只在已owner-complete的链上插一个级，重新测L与II并调整N/Q/D。
不允许“加一级但仍只有一个pending”造成吞吐下降后继续加级。
每级都做端到端供给与短core同binary对比；初次抽取保留性能并不免除后续真实流水级的这个要求。

### F5：再解除cache miss全局阻塞

单独引入多个需求line owner/hit-under-miss、同line合并、victim reservation与精确fallback并发。
cache hit本身已经能够turnover，应该先利用它建立热路径，不把所有refill/ROM改造捆绑到第一步。

每一阶段的完成定义必须写清：第一步是“真实生产context/result通道已接入且cycle-equivalent”，
后续才分别是“adapter可多owner”“实际供给侧已并发”“某新增级保持全链持续供给”“miss可并发”。
