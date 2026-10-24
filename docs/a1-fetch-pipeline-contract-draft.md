# A1 pipelined fetch 接口契约草案

状态：**设计草案，未实现、未仿真、未物理资格化**。2026-10-24。
这是 `a1-frontend-supply-audit.md` 之后的独立前端重构边界，不计入当前后端/内存批次完成项。
Scala freeze 期间只写本文，不改变代码。目标是两 lane、8 B/CPU-cycle 的热命中供给能力，
不是保证所有程序 IPC=2，也不是保证 300 MHz。

## 1. 先区分四种资源

1. **Fetch transaction token**：一个已接受 packet 的翻译、权限、物理返回、错误聚合身份。
   生命周期从 fetch-command acceptance 到 response 被其预留接收槽正式接管，或 stale sink 正式接管。
2. **Ordered supply record**：从发请求前预留，到其字节被 aligner 消费或 redirect 取消。
   可以仍在 waiting，也可以已经 complete。已完成的年轻 record 等待较老 record，不占外存 source，
   但仍占 supply capacity，不能把同一份字节信用释放两次。
3. **I-cache line MSHR**：一个实际 line refill 的地址、victim、TL source/beat/error owner。
   多个 fetch packet 可以合法合并等待同一 line MSHR，不能将 packet token 数误报为独立 miss 数。
4. **Transport source / PTW owner**：分别属于外部 TL、页表读取服务。
   直到真实最后 D 或 PTE completion 才释放，不因 frontend redirect 提前复用。

当前一条 `InstructionPort` 隐式串行化这四类生命周期。新设计必须拆开其信用和完成事件，
不能只把 `pending: Bool` 改为计数。

## 2. 目标与非目标

- 每拍最多接受一个 **8-byte aligned fetch packet**，热 ITLB+I-cache 命中时 II=1；
  latency 可以增加，但应被明确的 token/返回/字节队列容量覆盖。
- 每拍最多输出两条 16/32-bit 指令，RVC跨包、跨64-byte line、跨4KiB页仍精确。
- 首版 packet size 独立于 rename width。8-byte transport 是首选比较基线；16-byte transport
  是单独候选，不能通过把 core 改成四发射隐式开启。
- 首版不启用 I-cache next-line prefetch、未经检查的 execute read、PMP/页权限失败旁路、
  speculative GHR/RAS、额外 PTW walker 或改变 cache capacity。
- 首版可以内部乱序完成，但有序向 aligner 交付；对外不声称 ready/valid 自带返回身份或有序保证。
- 有任意长 miss/backpressure、分支 target miss、page/access fault 时，任何有限队列都不可能保证
  永远两条/拍。目标是消除热命中结构性供给瓶颈，而非隐去正常 miss/recovery 成本。

## 3. 身份与 request 格式

以下为语义字段，不是已决定的 bit packing；首次实现应优先保留足够 identity，再做位宽优化。

### 3.1 Token

`token = {slot, generation}`，必须唯一标识一个尚未归还的 transaction。
`slot` 只指物理槽，不能单独授权 response 写入。generation 不可在旧 response 仍可能返回时复用；
wrap 之前必须证明不存在相同编码 owner，或强制全链 drain。

另有两个不同的版本：

- `streamEpoch`：预测供给路径身份，branch/decode correction/trap redirect 可以改变。
  只影响哪些 bytes 可进入当前消费路径，不假装取消外部事务。
- `contextEpoch`：SATP/ASID/root、effective privilege、PMP、SFENCE/FENCE.I 等权限/内容上下文版本。
  首版仍采用现有 drain barrier，**不允许在旧 context owners 活跃时更新这些上下文**。
  epoch 用于防错，不替代屏障。

`order` 是该 stream 内的 packet 顺序或已预留 supply-record identity；不等于物理 slot。
对 rollover 要和 token 一样有显式界限。PC 可能跳转或回绕，不能以 VA 大小判断年龄。

### 3.2 Fetch command

- `token, streamEpoch, contextEpoch, order`
- `virtualBase`：8-byte aligned，所有地址加法按 RV64 modulo arithmetic；不能丢高地址比较。
- `requestedWords[1:0]`：每位表示一个 32-bit word 的需求范围；零 mask 是 fault-only owner，
  不是任意地址的 read 授权。若改16-byte transport，相应扩展为4位且16-byte aligned。
- `context`：捕获的 SATP mode/rootPPN/ASID、effective privilege、SUM/MXR 与权限版本。
  可以通过不可变 context-bank id 引用，不能读请求之后变化的 live CSR 来重解释 owner。
- `supplyRecord`：已经为该请求预留的返回/排序槽。
- `origin`：正常需求路径/纠正后需求；独立的“预取”类型首版不存在。

接受条件：空 transaction token **并且** supply record/返回容量已预留 **并且** 当前控制允许新 owner。
地址、mask、context、token 必须一起接受。第一次有效 offer 后若 ready=0，则这些字段与 valid 保持不变，
直到 handshake；redirect 不能撤销已经形成的 irrevocable offer。
可在进入 offer 状态之前取消 prepared address，但必须与已 offered 状态分别记账。

## 4. 翻译、权限与 I-cache pipeline

### 4.1 翻译

- TLB hit pipeline 对每拍输入保留 token/context，不只保留一个 `virtualPc`。
- 当前8-entry ITLB与一个 miss walker可以保留。miss 建立等待 record；年轻 hit 只有在独立
  response reservation 足够且 context 相符时才可继续，不得覆盖 walker 的 saved request。
- 相同 VPN/context/access 的 miss 可合并等待一个 walk，但必须记录每个 fetch token 的完整 VA offset。
  不同页 miss 在无空 miss owner 时等待，不借用一个正在走的页表状态。
- Canonical VA、leaf permissions、A/D规则及 PTE read PMP 继续由实际 ISA/MMU模块决定；
  “TLB命中”不绕过物理 execute PMP。
- page/access fault 自身也是一个完整 response。未获许可的 word 不产生 external instruction Get。
- fault tval 始终为对应 **VA parcel**，不是 PA，也不是整个 packet base。

### 4.2 权限

- 在发外部 instruction transaction 之前，捕获最终 `permittedWords`、word faults 与权限版本。
  held request 不因 live CSR 或另一个 token 的结果改变。
- 全64-byte refill 仅在原有 RAM range、同页、整line execute PMP等条件全部成立时允许；
  不能把“目标8 bytes合法”扩展成“整line合法”。否则沿精确 word/packet fallback。
- 分支错路径上的请求仍必须经过完全相同的权限检查。不能采用“先读并提供数据，权限失败再kill”的策略。
- 全line失败不能把原本成功的 demanded word 自动变成失败。保留现有精确 fallback retry，
  retry 继续属于原 token，并有自己的真实 TL source/beat owner。

### 4.3 建议阶段边界（具体 latency 等实际实现确定）

1. F0：选择预测/顺序 fetch cursor，预留 token 与 supply record。
2. F1：捕获 context 的 ITLB hit/miss 查找；miss 移入等待队列，不占所有 hit pipeline。
3. F2：已捕获 PA 的 execute PMP/range qualification。
4. F3：I-cache tag lookup / banked SRAM address preparation。
5. F4：SRAM data / way selection 与 fault metadata 合并。
6. F5：有身份的 response 写入预留 supply record。

这是可能的分级方案，不意味着每项都必须单独一拍，也不允许为了缩 latency 串回一条
TLB→PMP→tag→way→SRAM→alignment→prediction→PC 的长链。II=1 与 latency 是分开的验收指标。
late redirect 只撤销 valid/epoch 可见性，不驱动全体宽 payload 的清零或 clock enable。

### 4.4 Line MSHR 与 hit-under-miss

每个 MSHR 单独保留 `{linePA, cache/fenceEpoch, victimSet/way, source, beatIndex, error,
outstandingDemandTokens}`。同 line join 不多发 Get，其他 line hit 不因一个 miss 全局停顿。
每个 victim 在填充完成/取消前有 reservation；旧 fill 不得覆盖新 owner 保留的 way。
返回 beat 可以乱序到不同 source，但每个 source 必须有独立 beat count/error aggregation。
“line engine有多个entry”不能代替上层需求记录与替换冲突处理。

## 5. Response route 与完成契约

逻辑返回：

`{token, streamEpoch, contextEpoch, order/supplyRecord, virtualBase, data,
parcelPresent, parcelAccessFault, parcelPageFault}`。

- `parcelPresent` 表示某16-bit parcel的结果（包括确定的 fault）已经存在，不表示数据一定有效。
  fault parcel 的 data 不作语义比较；不得用zero data冒充成功取指。
- 返回时首先匹配 live token+generation，再写指定 supply record；不能依据当前 cursor 猜返回归属。
- response 可乱序写入不同预留槽，aligner只看到当前 stream 中最老且必要parcel齐全的前缀。
- response 在 valid&& !ready 时所有字段不变。建议在发请求时预留完整返回槽，使内部返回接收
  不依赖 decode 的当拍 ready；backpressure 在 admission 前端消化。
- 同拍旧 response 完成与新 request 可复用物理 slot，但generation不同；检查和写入使用旧token，
  新owner初始化有明确优先级。不能用“slot相同”覆盖尚未提取的旧数据。
- PTW owner、TL source、fetch token、supply record分别在自己的终结事件释放。一次enqueue
  不能释放外部source，一次TL最后D也不能释放仍等待aligner的byte capacity。
- 不匹配、重复、已释放token response是协议错误，应被断言/独立oracle识别，不能悄悄写入或
  把它当成正常stale。正常stale仍有一个真实未释放owner。

## 6. Credits 与所需容量

设：packet P bytes，目标供给 B bytes/CPU-cycle，从接受request到其返回槽接管的固定latency为L cycles，
每拍至多一项P-byte request，返回端至少同等II。

理论最低 transaction owners：`N >= ceil(B * L / P)`。
这是可在完成同拍复用credit、无额外stall的理想边界，不是无条件配置值。

若为了切断 ready 链仍坚持“仅用拍前 occupancy 产生credit”，不能借同拍response释放的最后一个slot。
稳态每拍一项8B request时，保守值为 `N >= L + 1`；L项满时会在首个完成拍停一次，之后产生周期性空洞。
只有经过独立证明的已寄存release预约才能去掉这个额外slot，不允许重新引入decode-ready组合回路。

| L cycles | 8B packet，理想 owners | 8B，仅拍前credit保守值 | 16B packet，8B/cycle平均需求理想 owners |
|---:|---:|---:|---:|
| 1 | 1 | 2 | 1 |
| 2 | 2 | 3 | 1 |
| 3 | 3 | 4 | 2 |
| 4 | 4 | 5 | 2 |
| 5 | 5 | 6 | 3 |
| 6 | 6 | 7 | 3 |
| 8 | 8 | 9 | 4 |
| 12 | 12 | 13 | 6 |
| 20 | 20 | 21 | 10 |
| 40 | 40 | 41 | 20 |

16B列是假定每两拍一项request的平均供给；需要128-bit存储/返回能力以及能消化多出的字节，
只增加包宽但仍每次等response可能仍不够。其拍前credit余量需按实际发包节奏单独推导。

当前Bare单8B owner的L约3、普通TLB hit约4，所以“两项在途”本身仍不能得到每拍8B。
若新pipeline L=5/6，不应仍固定两个owner而称作流水化完成。

### 6.1 返回队列与 instruction queue

- 每个已接受request必须有返回空间，即“waiting+complete”的supply记录不能超过已分配capacity。
  增加transaction owners不同时增加对应返回预留，是潜在死锁/丢响应，而非吞吐优化。
- 若希望在外部完全停供H cycles时仍有每拍8B的既有有用字节，应在停供前至少存有 `8*H` bytes。
  RVC边界的保守实现再留一项packet余量，确保16-bit offset下跨packet的最后半字不被覆盖。
- 若最终队列以已对齐指令计数，完全停供H拍需要至少 `2*H` 条可消费指令；当前四条仅覆盖最多两拍。
  bytes queue与instructions queue是不同资源，不能把“3个window snapshot+4条reservoir”简单相加成owner。
- 为切断每拍ready回灌，应预留至少一份enq packet的slack，或者正式证明弹性队列同拍出入逻辑；
  不能假设“全满时反正会出两条”而借没有保证的decode credit。

可变latency时，Little's law给 `N >= ceil(requestRate * meanOwnerLifetime)` 的平均下界；
尾部latency、burst、head-of-line completion与backpressure还要余量。任意stall没有有限worst-case容量保证。

### 6.2 冷line的MSHR与跨时钟带宽

冷顺序流每8拍需要一条64-byte line。若line owner从发出到释放是T CPU cycles，要维持8B/cycle，
理想 `MSHR >= ceil(T/8)`；例如T=40需要至少5个独立line owner，而不是把40个8B token称作40个miss。
如果多个packet同属一条line，必须join同一MSHR，不能重复请求整line来刷bus duty。

所有latency/带宽必须先归一到同一时钟。若未来A1 CPU300、fabric250 MHz仍使用64-bit instruction TL，
即便每个fabric拍都传一个有效data beat，跨域冷流量上限也只有
`8 * 250/300 = 6.667 B/CPU-cycle`。纯32-bit冷代码因此无法从这条物理通道得到2条/CPU-cycle；
更多owners不能突破链路宽度。热L1命中不走该通道，所以8B/cycle热供给目标仍有意义。
这些是接口算术上界，不是已测fabric duty，也不是A1 300MHz时序资格。

## 7. Redirect、FENCE与旧返回

### Stream redirect

1. 在接受redirect的边沿发布新streamEpoch/target；新流的cursor只从新target开始。
2. 丢弃旧epoch已完成但未消费的supply records；尚未offer的prepared commands可以取消。
3. 已经held-valid的offer继续以原token/context/address/mask送出，并标stale；已接受的TL/PTW事务照常drain。
4. 旧response只写stale sink或其仍预留的dead record，绝不能重新使当前epoch的parcel valid。
5. 每个旧owner仍完成且释放一次；只有已确认不存在外部义务的局部记录才可提前回收。
6. 新epoch可用真正空闲的token继续，但不能假设旧slot因redirect自动空闲。排队旧miss占满所有owner时，
   恢复仍会等待，这个代价应被计数，而不是违反外部协议撤销它。

### Context/fence change

首版保留“停admission→drain translation/held offers/cache miss/TL/PTE/returns→invalidate→发布新context”的
顺序。FENCE.I还须保留现有dirty writeback和shared-fabric epoch完成契约。
`quiescent` 必须覆盖所有这些owner，而不是检查一个FSM idle。

物理cache安装与stream交付是两个问题：一条已完全授权的旧branch-path fill是否允许安装，可保留既有
cache policy；但它不获得新stream的供给权限。跨FENCE.I/content/context失效的fill不得安装。
任何取消安装仍须收完最后D并释放原victim/source。不能让分支epoch与cache invalidation epoch混成一个位。

## 8. RVC parcel alignment queue

每个parcel携带其VA、16-bit data、present/fault、stream/context身份；PA在这里不再用于推导相邻关系。

- 最老parcel没有结果则不出指令。它有fault时输出fault record并终止该前缀，不从不可用data猜长度。
- 第一parcel合法且low2!=3时，消费一个parcel并输出16-bit instruction。
- 第一parcel合法且low2=3时，需要下一个VA=PC+2、同stream/context的parcel结果。
  两个parcel可以来自不同packet、line、页、PA映射；不能要求PA相邻。
- 第二parcel尚无结果则等待，不能zero-fill后误判compressed；若第二parcel fault，输出PC为第一parcel
  的一条fault instruction，tval为第二parcel VA。
- 每拍组合最多两条指令，最多消费四个parcel。两条输出必须是已定义的contiguous instruction prefix；
  每个parcel只消费一次。剩余半字保留，支持packet tail与next packet head拼接。
- 任何fault终止该次供给前缀；不让其年轻指令靠猜测长度跨过fault继续进入当前架构路径。
- branch raw prediction可截断packet的有效消费边界，但不能回收仍有外部owner的数据slot；
  未来是否支持branch+target双lane是另一个dispatch语义变化，不在本合同内默认开启。
- redirect先撤销旧epoch的可消费性；同拍return、两laneconsume、partial parcel与flush的优先级必须显式。

## 9. 验证与matched-traffic规则

独立模型必须是“字节memory+身份ledger+parcel队列+权限事件”，不能照抄DUT状态机，也不能只做old/new equality。

### 首批必需性质

- 每个accepted token恰有一个终结响应；slot复用/epoch wrap/同拍old-return+new-request不混淆身份。
- TL source直到最后D才回收；每source独立beat数和error；两个source返回交错/逆序不串数据。
- random backpressure下offer/response稳定，不撤valid、不改地址/mask/fault metadata。
- 两个ITLB hit、hit绕过miss、两个不同页miss串行、same-page miss join；fault页不发instruction Get。
- 32/RVC在8B/64B/4KiB/XLEN wrap边界；不同VA页映到不相邻PA；第二parcel access/page fault与正确tval。
- redirect发生在prepared、held A、TL已接受未归还、部分line已归还、response已到但排序等待、partial
  RVC消费等每个边界。旧response必须被drain且不得成为新流指令。
- FENCE.I/SFENCE/PMP/privilege更新前，所有owner真正drain；旧fill不安装到新内容epoch。
- 同line join、不同line victim冲突、miss失败精确fallback、hit-under-miss与返回slot满的死锁排查。
- 有意义negative：错误generation、重复D、越界word请求、错PC/parcel、错fault/tval、提前credit释放。

### 吞吐测量

1. 先用固定的K个合法8B命令、相同地址序列、相同cache初始状态/容量和服务律，验证热命中II=1、
   owner BDP与返回背压。不要用新的next-line prefetch或更快memory model替代pipeline改造。
2. 实际front stream使用相同instruction字节/分支结果/已消费指令数。报告所有Get extent/地址/数量，
   demanded useful bytes与discarded wrong-path bytes分别统计。
3. 更多fetch owners会改变lookahead以及分支前后实际traffic，不能把“不是cache预取”当作traffic相同。
   集成workload若Get trace不同，只报告这种真实取舍，不把它标成严格matched-traffic结果。
4. 报 accepted requests/cycle、response handoff/cycle、bytes/cycle、每拍0/1/2条供给、所有owner/queue
   occupancy/latency、full stall原因、misroute/stale discard与cache-hit/miss/fallback。
   不用valid-offer代替acceptance，也不用供给吞吐冒充core IPC。
5. 最后在相同二发射核心、同binary/内存模型上检查实际retire IPC与guest cycles；短功能/供给测通过后
   才进入一次合并A1综合/布局布线比较，实际STA之前不声称达到300MHz。

Nax只提供可借鉴的分级、同步预测存储与context运输方式。其speculative history/RAS和权限/side-channel
选择不自动授权迁移；本合同没有放松任何execute权限、fault精度或旧owner归还要求。

## 10. 模块拆分与 latency / II / capacity / credits 矩阵

依据用户2026-10-24新要求：模块拆开，每新增一级都查看**端到端持续供给及总体性能**。
不能等所有模块和寄存边界一次改完后才找哪个级造成吞吐下降。
下表是第一版可实现的合同草案，数字是设计预算，不是综合或仿真已确认值。
“II=1”均限定输入有合法可用工作、所需资源有credit、下游可接收；miss/redirect另行计量。

| 模块 | 输入→输出最小latency预算 | 连续服务目标 | 自有capacity | admission / release credit |
|---|---|---|---|---|
| `FetchPlanCursor` | 1拍prepared cursor；不计入accepted-command寿命 | 1个8B command/拍 | 1 prepared + 1 irrevocable offer | supply-record/token预留后offer；仅handshake或未offer取消释放 |
| `FetchOwnerLedger` | 接受边沿登记，不另加payload级 | 1 alloc + 1 terminal/拍 | 参数N，不固定为2 | token+generation；terminal response已被预留槽或stale sink接管才释放 |
| `FetchTranslationPipe` | TLB hit预算1拍；miss可变 | hit 1 request/拍 | 每流水级1 owner + 独立miss等待表 | 只吃本级及下级已预留credit；walk完成不直接释放fetch token |
| `FetchExecutePermission` | 预算1拍 | 1 packet/拍 | 1弹性owner | 已捕获PA/context；最终mask/fault与token原子传出 |
| `FetchPhysicalCommandQueue` | 预算1拍，是否empty flow单独评估 | 1 packet/拍 | 至少2 entries | registered occupancy；不得从late cache/decoder ready借最后credit |
| `InstructionCacheTagPipe` | 预算1拍 | hit lookup 1/拍 | 每流水级1 + reserved victim/miss tickets | hit可向已预留return slot前进；miss等待具体line owner，不全局busy |
| `InstructionCacheDataPipe` | SRAM read预算1拍 | 8B/拍 | 每流水级1 + held reply | bank/way与token同行；无same-address未定义RAM bypass |
| `FetchResponseRouter` | 预算1拍capture | 1 packet/拍；其它源需显式仲裁 | 每源response槽已预留 | 校验token/generation，commit到supply record后释放transaction token |
| `FetchSupplyRecords` | 完成记录最早下一拍读 | 1 packet等价/拍，支持partial parcel | Q个record，waiting+complete总和 | 发request前预留；其bytes消费/取消后释放，与source信用分开 |
| `RvcParcelAligner` | 预算1拍；跨界等待可变 | 2条16/32-bit instruction/拍 | 至少两个邻packet可见 + partial parcel | 仅消费present前缀；不因fault/flush丢owner或捏造字节 |
| `AlignedInstructionQueue` | 预算1拍 | 2入/2出每拍 | 参数D；当前4只是基线 | 采用足够slack的拍前credit；consume或epoch取消释放 |
| `InstructionLineMissTable` | miss可变，非hit串行级 | 多owner overlap；每拍最多1真实line command | M个line owner，单独算BDP | 分配victim/source/返回空间后发Get；最后D/error retry终结后释放 |
| `InstructionPtwOwner` | walk可变 | 首版保持一个walk | 1 walk + 有界同页waiter ids | 每个PTE真实response归还；translation faults也完成所有相应token |

若按表中accepted fetch-command之后的 TLB/PMP/physical queue/tag/data/response 六个边界全部独立计拍，
热命中transaction寿命预算L=6，理想N>=6，仅拍前credit时N>=7；不是N=2。
另外aligner和instruction queue的两拍会增加instruction-delivery latency，但在response router后
已移交payload所有权，所以应加在byte/instruction buffering预算，而不能错误延长外部TL source寿命。

实际实现可能合并或empty-flow其中某级，使L不同。每次接入都应由trace实测accepted-command→terminal
latency，然后重算N/Q/D。参考起点可以是N=7、Q至少N+2个完成buffer+1个partial-packet余量，
即Q>=10；它是保守结构预算，不是最终面积最优值。若为时序再添一级，必须同时检查N至少增加1、
Q有相应预留空间，或证明现有余量足够，不可只插寄存器后保留相同owner限制。

## 11. 逐级接入顺序与每一步验收

### S0：冻结已有事实和端到端基线

先完成当前`A1FetchSupplyGsim`九组短测及其receipt；保存实际raw/capture/consume直方图、
request duty、owner latency、Get stream和fault/redirect结果。它当前用8-line I$，不冒充公共32KiB数据。
在开始新pipeline前，增补固定热命中请求流、纯32-bit持续供给和长期ready consumer witness，
否则几个两条capture瞬间不足以证明稳态2/拍。冷miss、固定服务stall和redirect同时保留。

### S1：只拆模块，不改边沿或所有权语义

顺序抽出cursor/packet-store+lookup/window/RVC aligner/reservoir、translation owner、physical request
boundary、cache tag/data与fallback/MSHR control。每次抽取保留原来时序和1-owner policy，
要求全部可见handshake/payload/cycle trace一致。此阶段应是边界清理，不把结构拆分误报成吞吐提升。

### S2：明确token/return route与credits，不立即堆流水级

引入ledger、supply-record身份和legacy ordered-port兼容route。旧`InstructionPort`没有token，
兼容route必须在每次真实physical acceptance记录其owner，并按旧端口严格有序的response对应；
不能从当前PC重建身份。暂保持既有最大1-owner admission，证明cycle-equivalent。
对新ledger单独用2..N owner交错/同拍事件的独立模型测试，但不称集成已并发。

### S3：闭合最短多owner热路径，先去掉结构性串行瓶颈

先将translation hit/permission/response storage按token组织，再将frontend request cursor与
aligner消费cursor解耦，用已预留supply-record控制有限的后续command。
原I-cache hit本来可旧reply/新request同拍turnover，可以先通过有序route复用该能力；
不要求第一天就重写所有cache miss逻辑。

所有相关模块在既有边沿能正确保存多owner后，单独开启N-owner admission，测热路径稳态供给。
这一步是必要的跨接口激活点，应明确归因于“多owner并行”而非新增寄存器。
若上游仍只有一个pending而下游新增stage，即便局部II=1也不能通过本阶段：全链会按更长latency饥饿。

### S4：逐个加时序级，每一级独立比较

推荐按真实A1路径证据选择 TLB→PMP、PMP→cache lookup、tag→bank address、SRAM→response、
response→aligner、aligner→instruction queue的切点；不预设全部都要新增寄存器。
一次只启用一个新边界，并同步提供这一级所需credit/elastic容量，然后：

1. 运行该模块独立oracle，验证1 alloc/1 completion/拍、held payload与flush优先级。
2. 运行同一个端到端供给模型，使用相同bytes、命令序列、service law、cache容量，比较
   热持续供给、长下游ready、短/长backpressure、真实miss、redirect恢复。
3. 运行必要短core workload，以同binary核retired work、guest cycles、实际IPC与功能oracle。
   只看局部II或模型执行速度不能代替这一步。
4. 报新增latency、实际II、max/mean owners、空队列周期与branch/fault恢复代价。
   热持续供给出现周期性空洞时，先修credit/队列/owner配置或撤回该级，不继续叠后续stage。

每级需要的是短行为/吞吐对比，不是每个小改动都做一次完整STA。物理实现仍在行为与供给候选闭合后
做一次合并A1资格化，除非用户另行要求更频繁STA。

### S5：独立关闭miss与ROM的剩余供给缺口

热hit链先达到合同后，再独立接入line MSHR/hit-under-miss、精确fallback并发或ROM缓存策略。
每一项保持old/new相同service law与需求字节，报告Get数量/extent差异。
ROM加入I-cache不只是改变tag范围：必须定义128KiB ROM aperture、可编程测试ROM/FENCE.I内容epoch、
PMP精确fallback与共享ROM读取语义。没有独立证据前不能把ROM“快了”归因于流水化。

### S6：预测升级单独归因

同步BTB、gshare、speculative RAS/GHR只在前述供给链已经稳定后另做。每个预测级需要同时比较
预测准确性、错路径bytes/traffic、redirect latency与整体core cycles，不允许用更长预测pipeline的
局部fmax目标掩盖branch IPC回退。当前commit-only正确性基线保留作独立对照。

每次报告都应区分“模块拆分完成”“某一级II=1”“端到端持续8B/cycle”“实际核心性能”和“物理频率”；
五者互不替代。没有输入供给或下游不ready的周期可以单列，但不可从真实miss/redirect总体结果中删除。
