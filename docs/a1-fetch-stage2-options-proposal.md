# A1 fetch S2选项与建议scope：真实重叠，不重复实现已有turnover

2026-10-24。**A2最小闭环已完成一次统一编译、六模型/12负例与持续热供给短测；
实际结果见[a1-fetch-stage2-results.md](a1-fetch-stage2-results.md)。本提案的预期因果不是实测数值**。
S1 commit：`4e8e7ca`；实测基线仍为580/332及九场景全部字段。

## 决策摘要

建议先A：8B packet不变，**两项完整frontend owner + aligned adapter的发送/返回owner分离**，
复用现有I-cache hit turnover。两项是最小可归因的完整闭环，不是最终8B/cycle所需capacity。

B：rename/issue仍2，fetch response可16B，是可保留的独立带宽摊销选项。
它需要真正解耦packet宽度，不能改rename=4；也不等于流水化完成。
ROM仍经两个串行8B Get，且扩大bundle lookahead会改变额外字节，不能把它当纯接口优化。

不建议“先加prepared/held模块消除front reply bubble”：该能力已经存在。

## 1. 已有能力及实际证据

`platform/memory/InstructionRom.scala`的compressed路径：

- 405行：newRequest包含`(!pending || reply)`；reply就是`response.valid && pending`。
- 465行：response.ready固定true。
- 481/528行：先处理旧response，再由新request.fire覆盖pending及其完整地址/context。
- 367行开始：调度看LIVE cache/return bypass，不等待registered decode window。
- Selected的fetchAddressBeforePmp=false，不走额外prepared阶段。

`cache/InstructionLineCache.scala`的158行开始允许hitReply/lineReply消费拍接受下一个请求。
**fallbackActive并不包含在acceptWindow中**；ROM fallback返回后仍有本地接收间隔，不能与RAM hit混算。

九场景receipt中，rom32总588拍、单owner latencySum585；ram32总351拍、latencySum348。
各仅3拍不被已接受owner区间覆盖。这不能列出每次turnover的准确次数，但足以否定“每包还有一个front空拍”。
RVC/背压的其它空隙还包含需求窗口、registered window、capture/consume节奏，不能统一归因于request握手。

## 2. A：最小真实闭环

### 2.1 模式开关

新增显式`FpgaNextConfig.fetchTransactionSlots`配置，仅允许1/2；默认1保持S1路径。
不改由B2 owner持有的OooParams；两个生产构造器使用显式`transactionSlots=1/2`，Common同值透传。
Selected原alignedFetchSinglePage=false，所以分别比较(1,false)、(1,true)、(2,true)，
先单独证明aligned specialization没有改变原九场景，再归因owner并发变化。
Common A1候选选2，二发射、8B packet、cache容量、预取开关不变。
同源码的owner1/owner2必须能各自生成真实整链模型；不把新模块接成不可达旁路。

初次owner2仅支持Selected的compressed、two-lane、aligned-single-page、registered-heads路径。
不把generic跨页/四字packet一起重写；那些配置留在S1 engine，并拒绝不受支持的owner2组合。

### 2.2 Frontend accepted-owner模块

从SynchronousFetch抽出真实的ordered owner模块，保存两项：

- accepted base、完整地址/移位keys、privilege/virtualized context、stale状态；
- 一个独立held offer，保存base/context/mask；它是尚未accepted但不可撤回的offer，保留可用slot的资格；
  accepted数量加held reservation在边沿后不超过2，不能凭第三项offer突破capacity；
- response只归FIFO旧head；同拍旧head释放与新tail接收有明确顺序；
- 每个返回按head metadata写现有8B packet cache/window，不从当前PC重造owner。

只挑当前`currentBase/currentBase+8`范围内的missing且未owned packet，先current后next。
已经pending不等于data present，只用于阻止重复请求及允许选择另一个合法缺包；alignment仍只能消费真实数据。
不打开新line预取，不扩大到任意顺序地址扫描。这会限制owner2收益，必须如实测量。

invalidate将所有accepted entries和held offer置stale但不丢弃外部义务。held offer仍以旧payload握手并drain。
普通branch redirect本来不等价于FENCE.I：生产只改变fetch cursor，合法same-context旧packet可仍按地址缓存，
但不能作为新PC的无标签数据消费。不得从PC变化猜streamEpoch；若要新增显式取消/epoch，必须单列接口扩展。

quiescent必须要求accepted FIFO空、held offer空；不能只看发送stage空。

### 2.3 Adapter：不是只加admission FIFO

S1单FSM的`waitFirst/reply`不能继续阻塞所有后续translation。新aligned路径由下面实际模块边界组成：

1. **command/全局reservation**：acceptance同时预留完整context与一个最终result slot，token持有到公共result消费。
2. **translation准备**：按command顺序发真实ITLB请求，保存miss owner，hit当拍response必须绑定该请求而不是先pop空FIFO。
   identity使用原接受边沿生成后续permission-stage输入，不为了统一路径额外加一拍。
3. **PMP/physical-send stage**：保存PA/token/mask；首次物理offer时捕获permission结果，held offer稳定；
   physical.fire后本发送stage即可接下一个context，不再等待该physical response。
4. **physical route FIFO**：只由真实physical.request.fire入队，绑定global slot+generation及精确fault合成信息；
   只有physical.response.fire出队。被request buffer接管不释放最终slot。
5. **tagged completion slots + 有序result head**：physical返回和本地translation/PMP fault按token写原slot；
   只允许最老command的done slot对外result.valid。年轻fault可以先done，但不能越过旧physical miss交付。

返回存储在command接受时已预留，因此不能因output backpressure让已合法接受的physical reply无处存放。
若physical与本地fault同拍完成，必须明确写端口或仲裁。最小实现可physical优先、本地fault stage保持valid直到被接管，
不得静默覆盖。无物理请求的zero-mask/fault同样持有完整global credit，直到有序result终结。

自动trap不等待fetchQuiescent，会直接改变live privilege，因此A2 public wrapper在首次
virtual.request.valid&&!ready冻结完整VA/mask/SATP/privilege/SUM/MXR，token仍只在真实acceptance分配。
这是真实正确性修复，不以旧/new同错等价来验收；独立host在held期间故意切成M/Bare，必须仍按首次S/U context翻译。

PMP/SATP/SFENCE仍沿现有drain屏障更新。不能因发送stage空就允许CSR换context；adapter.idle包括全部context、
miss、PMP/held、physical-route与completion义务。PMP仍在first physical offer采样，不能擅自改成command admission。

### 2.4 复用而不改的模块

InstructionRequestBuffer、InstructionLineCache、InstructionTileLinkBridge、SvTranslationService、
SvPteDataBridge、RegisteredFetchWindow、RVC alignment、RegisteredFetchPacket、IntegerCore/IntegerBackend。
不改cache miss engine，不宣称hit-under-miss，也不宣称ROM多Get并发。

ITLB真实接口并非固定II2：SvTranslationService 148–152行的idle+fast hit当拍请求/返回，且hit不离开idle，
下游ready充分时可以每拍一个hit。miss则只有一个I-side walker；replying终结拍尚不能接受新request。
Common I/D是两个service，但PTE读共享SharedDataArbiter。这些限制本步保留。

### 2.5 latency / II / capacity / credit目标

| 模块/边界 | latency目标 | II目标/约束 | capacity/credit终结 |
|---|---|---|---|
| frontend accepted owners | 无人为增加reply边沿 | 最多每拍一accept/一reply | 2；response.fire释放 |
| command→identity send | 保持原1拍 | P-stage空或旧send被接管可turnover | global slot始终保留 |
| command→ITLB hit→send | 保持原2拍 | hit接口可1；miss阻塞translation stage | miss response归原token |
| physical request buffer | 原empty-flow行为 | 原II1 | 原2 entries，不当result credit |
| I-cache RAM hot hit | 原1拍 | 已有II1 turnover | 原single demand FSM |
| I-cache ROM fallback | 原latency，额外发送不旁路 | fallbackActive接收间隔仍在 | 原single demand FSM |
| physical return→virtual result | 保持原reply寄存边沿 | ordered head可每拍交付 | completion slot在virtual.fire释放 |
| hot bare / ITLB-hit整owner | 尽量保持原最乐观3/4拍 | 由N、窗口、service共同限制 | N=2不是满带宽配置 |

在8B packet、目标8B/cycle下，owner下界是L；L=3/4至少要3/4项，若信用只能下一拍归还需额外余量。
本次两项不满足这个最终目标，只用于不扩当前16B需求范围的最小真重叠。
如果实现无额外cycle仍无法在真实整链提高持续供给，应停止并定位窗口/阶段限制，不把局部II1当完成。

### 2.6 已批准的精确生产文件scope

- 新增`frontend/FetchDemandOwners.scala`：真实accepted/held/return owner helper。
- 修改`platform/memory/InstructionRom.scala`：owner2分支接入helper，复用现有cache/window/align，owner1保持旧路径。
- 新增`mmu/PipelinedAlignedInstructionTranslation.scala`：上述command/translation/PMP/send/route/completion模块。
- 修改`mmu/InstructionTranslationAdapter.scala`：独立owner2选择；S1分支与generic分支保留。
- root修改`config/FpgaNextConfig.scala`：受约束的1/2开关与明确profile传递；不改OooParams。
- `src/main/scala/platform/CommonA1CpuTile.scala`仅frontend参数接线，需与root/平台owner协调。
- 如果同一配置经过`FpgaIntegerCore.scala`或`MachinePlatform.scala`，仅明确透传或拒绝unsupported模式；
  不默默忽略开关，不改平台memory/fabric逻辑。
- 新增阶段fixture/runner；原九场景host driver/oracle/service law保持原字节。
  现有fixture必要的owner配置接线变动必须在新manifest中明示，不能再宣称fixture五文件全部未变。

## 3. B：two-issue与16B fetch bundle解耦备选

B仍单owner、rename/issue/commit均2。新增独立packetWords=2/4，不能从renameWidth推导。

需要改的真实边界：OooParams/FpgaNextConfig、SynchronousFetch transport宽度、adapter/engine宽度选择、
Common的硬编码packetWords=2、FPGA/旧platform wrapper的fetchWords推导、fixture。
RequestBuffer/InstructionPort/I-cache已有4字能力可以复用，ROM使用已有WideInstructionAdapter。

但必须处理：

- packet transport按16B对齐，frontend packet cache仍是8B单位，一次return原子填两项，各自fault位完整保留。
- decode窗口与lane数仍2；16B bundle ownership和8B cached-unit匹配不可混为同一个宽度。
- 32-bit指令可从bundle末尾14跨到下一bundle，也可跨4KiB页；两个16B包各自翻译，第一失败parcel决定tval。
- 四个word独立PMP/页面/物理fault，partial mask走精确fallback；不跨permission hole扩大Get。
- 当前two-lane wanted范围只到current+8。16B返回补齐两包后，旧reply拍没有下一个request目标，
  可能等cursor前进后才发next bundle。若改为提前请求下一16B bundle，必须显式披露更大的lookahead和额外字节。
- WideInstructionAdapter low reply才发high，两个8B Get串行；不是128-bit ROM传输，不可声称ROM吞吐翻倍。
- 不因为旧wide profile习惯而打开I-cache prefetch。Common仍保持prefetch=false、原line容量。

PPA差异：response/result寄存和选择路径从64到128 bit，PMP word checker可从2增到4，packet cache同时写两个
8B位置；banked I-cache需两个64-bit bank选择。存储总容量不必翻倍，但返回bus/mux/使能/比较成本增加，未测。

单owner若L=3，即使每次16B、完全连续demand，也最多16/3 B/cycle，仍低于最终8B/cycle。
B可以摊销owner控制开销，却不替代A的owner-complete流水链。

## 4. 同九场景的预期因果，不预报未运行周期

| 场景/旧work cycles | A预期变化原因 | B预期变化原因/风险 |
|---|---|---|
| ROM32 /580 | 让下一物理请求提前排队，可能消除adapter等待后再send的间隔；ROM fallback本地间隔与7拍服务仍在 | 两次8B Get仍串行；摊销有限，wide准备与更窄lookahead可能抵消收益 |
| RAM32 /332 | 已填line内的translation/PMP/send可与前一hit返回重叠；64B冷miss服务不变 | 每个16B覆盖四条32-bit指令，减少adapter请求；line Get本体不变，尾部字节可能增加 |
| RVC /644 | 两个相邻包可同时owned，跨包等待可能缩短；registered window仍有固有边沿 | bundle14位置/页面边界仍会跨；不能按每包四条指令估算混长流 |
| backpressure /688 | owner/result credits可吸收返回，但full reservoir/consumer zero-budget仍限制 | 多字返回更易积压；不能增加reservoir容量来掩盖差异 |
| redirect oldreply /1034 | 可能有两项旧义务需drain，恢复时间不保证更快；必须零错路径消费 | 丢弃/无效字节更多；high-half Get仍须精确drain |
| Sv39跨页 /433 | hit translation能与旧physical返回重叠；两次真实walk与PTE service保留 | 每包翻译次数可少，但页边界仍两次权限；不得绕过第二页 |
| Sv39 fault /59 | 年轻fault可先done，必须等旧物理owner有序交付 | 包的多word fault聚合变化，tval仍首个所需失败parcel |
| PMP fault /25 | 不越过PMP denial发physical；fault-only slot仍要有序终结 | 四word部分允许/拒绝与高half零mask需核 |
| ROM fault /22 | 先后完成不改变消费指令/精确fault；drain请求数可能变 | 不能因high-half额外Get读取越界或抹掉low-half fault |

以上是可检验假设，不是新的cycles承诺。旧580/332等值保留，新的数字只能来自重新emit的整链模型。
尤其不得把较早发更多请求带来的变化混称同流量提速。

## 5. 验证与性能接受门槛

1. 原九场景同host、同service law继续运行。指令PC/data/fault/tval/hash必须相同；记录所有原计数。
2. 新增单独的持续hot-L1/cold-packet-cache witness：先经真实链暖好不超过I-cache容量的地址集合，
   再做不带FENCE.I的合法cursor重定向；循环足迹大于256B packet cache但小于512B fixture I-cache。
   两模式运行完全相同warmup/ROI字节，ROI要求TL Get=0，不能由预填寄存器或更快host服务制造热命中。
3. 增加virtual/physical accepted bytes、unique byte extent、ROI与drain分开的TL地址/size/beat数，
   区分A的请求时间重叠与B的更宽/冗余字节。原九场景如果Get extent/count不同，单独标流量不匹配，
   不将该行作为严格sametraffic速度结论；warm witness才是额外的匹配流量归因门槛。
4. A必须出现真实front/adapter最大owned=2及同拍不同token阶段重叠，并使whole-front持续供给改善；
   只有模块command每拍接受而整链不变不算通过性能门槛。
5. ordered host ledger独立核：旧miss延迟17拍而年轻translation/PMP fault先done；physical与本地完成冲突；
   result长背压；旧reply/newrequest同拍；redirect时两项accepted及accepted/held的所有合法组合；SATP/PMP/SFENCE drain；
   wrong-generation、duplicate、unowned physical reply、漏/重复parcel、错误tval负例。
6. B若后续选用，另加16B边界14、4KiB边界4094、XLEN wrap、high-half fault、mask0/partial、
   两个8B填入相邻/绕回cache set且不覆盖活跃packet、两段fallback各自held/错误返回。
7. 统一freeze后一次增量compile与必要短GSIM；保留owner1/owner2模型、输入/工具hash及失败证据。
   后续短同binary core检查和统一PPA由root协调；供给指标不是CPU IPC，零cycle或局部II不是300MHz证据。

## 6. 当前实现/验证入口

- 真实新模块为FetchDemandOwners、FetchCompletionLedger、AlignedFetchPermissionStage、
  OrderedFetchPhysicalReturns、PipelinedAlignedFetchEngine和public wrapper。
- `simulator/gsim/a2_fetch.py --gsim PATH --tag FRESH --baseline S1_RECEIPT`生成3个unit及3个整链模式；
  每个整链模型复用生成C++运行warm witness，不重复emit。
- `ooo.A2FetchConfigurationSpec`检查新模块实际在FIR、默认路径保留以及非法组合拒绝。
- 原driver、byte oracle、oracle test与service-law入口四文件保持原字节；A1FetchSupplyGsim仅显式参数化。
- Native physical InstructionPort无response tag，须有序且exactly-once；route FIFO无法识别另一live owner下
  伪装的重复response。负例分别验证route-empty、global-generation/duplicate，以及独立TL source所有权，
  不夸大FIFO本身的检测能力。
- 后续真实Common A1 tile退休同binary对照由root协调，不能用本供给测试替代。
