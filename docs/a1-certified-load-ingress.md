# A1 certified load ingress

## 结论与范围（2026-10-25）

本批是默认关闭的云端带宽/延迟候选，接续 [advisory / ordered owner](a1-advisory-ordered-owner.md)。
同工作量、同容量与服务律下，VM dependency 的 work+drain **876→823拍，省53拍（6.05%）**；
热 load 的255/256个ROI请求完成驻留由5降为4拍，但热端到端仅1069→1068拍，净省1拍。
不能把局部一拍收益等同于持续每拍发射或整板带宽提升。
新路径延长前向 permission 组合锥，PPA、Fmax、实际频率和板级性能均未测，**不推荐默认晋升**。

基线 `d5805c648aae30cf6c7004fdd0c5a86a4a84b988`，开发分支
`dev/a1-certified-ingress-20261025`；结果绑定receipt及逐文件源码bytes，提交后的身份另以独立
post-commit binding记录，不用分支名或本文自引用commit SHA替代验证身份。
本批只新建一个CPU DUT；四个component DUT由一个旧DTA-OFF对象复用与三个fresh DUT组成。
独立U/C epoch及C/physical hint的CPU host-only补证及最终独立审核均通过；
覆盖仅限下述固定客体，不作完整权限证明。

## 配置、授权与传输合同

`certifiedLoadIngress` default OFF；候选为 `FullR1M3CertifiedIngress` /
`full-r1-m3-certified-ingress`，control为前批 `FullR1M3AdvisoryOwner`。
旧 `physicalLoadIngressFlow` 保持OFF及原拒绝guard，不将普通PA shortcut当作certification。

纯组合typed descriptor绑定**最终DTA upstream端口**，不是更早的integer FIFO。
StoreBuffer drain/fast/direct与FP选择之后，request、当前VmCsrState、authorization epoch、
sidecar、PMP/fault及next-line hint必须来自同一实际source。输入已是PA；DTA无原始VA或完整ROB
身份，不能靠这个descriptor声称独立证明VA canonicality。原始full-token/VA/size/epoch证明仍由
producer/preparation/LSU链提供。禁止store sidecar的有效输入不得被清零后冒充合法load。

```text
U.ready = I.rawEnqueueCredit
nominal = enabled && U.valid && I.rawEnqueueCredit
          && !I.headValid && !T.headValid && !waiting
          && certified ordinary cached load class && sidecarsAbsent
selectedDescriptor = nominal ? finalPortTypedDescriptor : legacySelection
pass = nominal && directQualifier && completeFinalPermission && C.rawEnqueueCredit
I.enq.valid = U.valid && !pass       // 此候选旧physical shortcut为OFF
```

`nominal`独立于permission、checked credit及下游ready/reply；失败不能把source mux切回旧head。
`directQualifier`（stable、supported virtual S/U等保守路由要求）与最终权限分开：仅拒绝shortcut
不等于最终fault。资格不符、权限拒绝或C满均保留原request/context/sidecars进入旧I路径，
其既有fault计算不变；之后可能合法physical issue。不得把direct拒绝变成sticky fallback fault。
最终权限仍包含原PMP、shape/lane、range、epoch/stale及actual-payload fault；新source不加入旧
false-fault bypass。hint重新计算且不能授予physical权限，权限与hint选择保持同source。

每个U fire恰好一个sink，只有真正pass才抑制I enqueue。接受计数仍在U fire，physical owner仍在
checked dequeue，故fault placeholder、取消后的已接受drain、精确完成/退休责任不提前解除。
C保持non-flow，C满不可借同拍dequeue credit；I ready不依赖C、physical或response ready。
无新存储或credit，不改变双发射、ROB16、4 integer LSU、D2/T1/R2、PRF读取端口及既有队列容量。
单路最大一拍一个accepted request/checked enqueue，II不等于CPU实测供给率。

理想成功路径为start s→U/checked capture s+1→physical s+2→reply s+3→completion s+4；
fallback保留原ingress一拍。checked、owner、LSU result/done寄存边界和同拍done-slot replacement保留。

## 同服务律性能

work不含drain；inspection不混入有用工作。下表control→candidate均为模型周期。

| 客体 | ROI | work | drain | work+drain | 端到端变化 |
|---|---:|---:|---:|---:|---|
| hot_loads | 338→334 | 1053→1049 | 16→19 | 1069→1068 | 省1拍，0.094% |
| delayed_cold_loads | 358→357 | 902→900 | 7→7 | 909→907 | 省2拍，0.220% |
| vm_dependency | 700→650 | 866→816 | 10→7 | 876→823 | 省53拍，6.05% |
| vm_store_stream | 458→456 | 624→622 | 10→7 | 634→629 | 省5拍，0.789% |
| Bare ROM | final/ROI字段一致 | 6729→6729 | 不作新增收益声明 | 不变 | proof query为0 |
| native atomic/FP smoke | — | 328→328 | — | 不变 | 有界功能对照 |

热256个ROI owner：255 direct驻留4拍，一个fallback驻留5拍；start→U均1拍、
U→checked为255个0拍/一个1拍、checked→physical及physical→reply、reply→complete各1拍。
冷16个ROI owner：15 direct、一个fallback；physical→reply固定37拍，完成驻留为40拍×2、
41拍×1、76拍×13。服务律未缩短，拥塞下checked→physical仍可能等待37拍。
热translation requests/replies由15→16，prechecked starts497→496；不得称所有内部计数相同。

热连续一拍start gap191→194，二拍62→60。独立全owner时间戳复核表明候选剩余60个二拍gap
**全部存在同拍completion可回收slot**，均非四个不可回收owner占满所强制；真正供给原因尚unknown。
不能沿用早期合同报告的容量瓶颈推断，更不能以扩容或放松mask替代证据。

## 验证分层与精确覆盖

- **配置/compile**：11个短Scala suites / 33 tests在r2通过；最终r3 compile包含fixture修复，
  不把旧suite receipt改写为r3重跑。r4 emission绑定最终输入。
- **r2纯模型**：4,608个one-step状态、256个route/sidecar组合，100 seeds / 100,000刺激拍，
  含drain100,418拍，25,716 accepted全部按full-tag完成一次。七个原mutant及额外
  early-port/epoch/held-input/qualifier-as-fault负控被拒绝。仅为routing abstraction：
  finalPermission固定，不模拟动态排队权限重算、实际PMP/TLB、VA、实际仲裁或完整live guard。
- **真实DTA与chain组件**：OFF/ON两DTA、两actual chain，独立PA/order/data/fault/hint、
  full64 owner/cause/tval/atomic-phase/completion/final-source负控；覆盖backpressure、
  错误与取消drain、整数/FP及实际AtomicMemory相位。非法sidecar/未drain flush属于精准HW assert负例，
  不是合法fallback正例。reserved-mode qualifier-only defensive PA案例保留，但不宣称合法集成producer可产生它。
- **noncanonical**：实际TLB/producer以warm低VPN进行4 KiB、2 MiB验证，actual chain另有1 GiB；
  CPU OFF/ON各四个4 KiB/2 MiB高位案例，检查exact fault/mepc/tval及禁止非法physical访问。
  不能用standalone手造prechecked PA代替原VA证明。
- **CPU full-token joins**：独立join关联load start/U/checked/physical/reply/complete/retire；
  VM stream58 owners（7 direct）、dependency106 owners（55 direct）。原load日志两个epoch字段
  都复制start ledger，并非独立U/C采样，且无CPU load hint检查。因此旧
  `all_precise_fields_joined`不能泛称完整permission/epoch/hint观测。
  VM direct host已有U/C epoch实比；组件另有独立hint oracle与负控，生产payload assert补强，
  这些证据不应混写成CPU完整逐边界观测。
- **CPU host-only补证**：复用原candidate对象，零DUT生成/构建，仅新编译一个host。hot512、
  cold32个owner分别在实际U、C、physical各观察一次；prechecked start epoch与实际U/C比对，
  raw epoch只检查U→C传输，physical端private epoch必须清零。next-line hint以固定客体的
  same-page/RAM/TOR独立算术oracle检查C及physical，epoch/hint注错各被精准诊断拒绝。
  544个owner的hint均为1：仅固定允许case加flip负控，不覆盖CPU hint-deny边界（后者有组件覆盖）。
  原functional log逐byte一致，原CPU receipt/host和DUT artifacts不变；不证明任意CPU PMP配置，
  最终独立审核通过，544 owners / 1632边界记录全join并独立确认剥新增行后原log bytes exact。
- **native smoke**：80退休、11 atomic replies、17 physical requests/replies、8 FP退休；
  CPU使用native host atomic transport，不是tile AtomicMemory验证，后者仅由真实组件链覆盖。

所有测试有界；host观测注错、图边注错不是RTL mutant或形式化证明。未跑本批full GSIM、
长Linux、完整NEMU/ISA回归、综合/map、实现/STA、bit或上板。

## 独立结构与OFF兼容

完整full-tile fail-closed last-connect/control-aware图：candidate185,178 vertices /
1,364,747 edges，control184,860 / 1,364,171；均0 SCC，分别20/8项路径检查通过。
29个micro校准及6个actual-graph负控通过。门涵盖nominal与fault/credit解耦、typed descriptor
不依赖live TLB/reply、final-port/context正向到达、checked真实寄存边界、occupancy-only ready、
无reply→complete/start/issue组合反馈。同source具体语义还依赖源码与行为，不由reachability独证。
共享legacy raw TLB→PMP弧未被虚假排除。

图**实际运行于r2 FIR**；r3/r4的candidate/control完整FIR逐byte一致后复用，非重跑图。
OFF与d580不是raw FIR exact：唯一允许的assert source locator映射为
`MappedMachineCore.scala:150→153`，恰好一次，原/新assert源码相同；除此normalized FIR exact。
五个独立负控拒绝diagnostic line/body、functional statement、重复映射及predicate改变。
不可推广为任意locator忽略，亦不能称raw exact。

## Receipt入口与复核

路径相对repo；build产物需与manifest保留，不包含在源码交付中。先核对compile、emit、工具epoch、
source/artifact hashes与`inputs_unchanged`，再看日志/负控与full-token joins，最后重算work+drain。

| 内容 | 路径 |
|---|---|
| 源码合同及负例审查 | `build/certified-ingress-contract-review-20261025-r1/{report,source-review,model-review,component-negative-review}.md` |
| 修正模型 | `build/certified-ingress-routing-model-20261025-r2/{report.md,results.json,manifest.json}` |
| 最终compile | `build/certified-ingress-20261025-r3/scala/compile-receipt.json` |
| Scala suites | `build/certified-ingress-scala-tests-20261025-r2/receipt.json` |
| 最终emission | `build/gsim/certified-ingress-cpu-20261025-r4/emit-receipt.json` |
| 结构/OFF/continuity | `build/certified-ingress-independent-graph-20261025-r1/structure-receipt.json` |
| component恢复 | `build/gsim/certified-ingress-components-recovery-20261025-r2/receipt.json` |
| CPU最终 | `build/gsim/certified-ingress-cpu-20261025-r4/receipt.json` |
| CPU noncanonical/native | 上述CPU目录的`noncanonical/receipt.json`、`native-atomic-fp/receipt.json` |
| 独立runtime复核 | `build/certified-ingress-runtime-independent-review-20261025-r1/{joins.json,receipt-checks.json,hot-two-gap-capacity.json,boundary-joins.json,report.md,evidence-index.json}` |
| CPU epoch/hint补证及封存 | `build/certified-ingress-cpu-boundary-observer-20261025-r1/{receipt.json,post-exit-finalization.json}` |
| 最终身份索引/source-host freeze | `build/certified-ingress-final-validation-20261025-r1/{REPORT.md,evidence-index.json,frozen-source-hashes.json}` |
| GSIM epoch | `build/gsim-init-bytefix-20261025-r1/receipt.json` |

关键SHA-256：

```text
compile r3: abd33852215f19a2560dd5402e081b3cea438557a676927fa4313b27688b6e7a
emit r4: 83b7ae240b0e0fb97b8e9b413953acc14f58f244f3c1e9fc04e20208d1121063
structure: 8b1cd9c07acd95a20641c08283cbc47a8ff383e076bcedea035dff85d8e2e2b5
components recovery r2: aad84f95b2a29efe055afd19219585ff29c38ac1bcda6a7c676576c0e07ad4ac
CPU r4: 9547f0e498e985d97c3d1b22a808e6468c82c32bea3d9708e3931e10fff2c37b
boundary observer original: ea785d6b3c95c910500286af32ecf6ca20894da816e558a827db44345a65d7ce
boundary post-exit seal: f879196385940f71b25e299de812e9c23875e49fdcf0178cec1603e073bf6764
independent review: afcfb72f757e0f7a76179f2685f335cd7c4267cb1c9ed0bfd2e192d5daa01268
independent review index: 2f8aaf1789e0d47f8c3ba751714ae4ac94389441bc628ae2c4cb946684da3f00
```

CPU receipt历史status为`PASS_CERTIFIED_INGRESS_FOCUSED_CPU_AWAIT_INDEPENDENT_REVIEW`；
后来的独立复核由独立报告承担，不覆写原receipt伪造当时完成状态。
GSIM pin为`93b8cd23edd3228807c4f2a08c19c3936a463cb2`加原初始化byte-span修复，非静默换工具。
runner位于`simulator/gsim/`：`certified_ingress_components.py`、
`certified_ingress_components_continue.py`、`certified_ingress_cpu.py`、
`certified_ingress_noncanonical_cpu.py`，以各receipt记录的输入/命令为准；
host-only补证入口为`build/certified-ingress-cpu-boundary-observer-20261025-r1/run.py`。
重新运行必须新tag/输出目录并核对emit/build门，不覆盖失败及旧二进制。本文编写不触发任何重建。

## 保留失败与恢复

1. r1 compile通过，但配置guard过早读取派生`issueWidth`导致13/33 tests失败，
   移同一predicate至初始化之后；初次test调用用系统Java，不称qualified，r2使用pinned环境通过。
   首次OFF源码隔离检查发现常量禁用仍改变FIR表达式，改为Scala elaboration条件分支保留原表达式；
   未放宽OFF检查。
2. 最初CPU emit工具门在emission之前拒绝默认PATH缺pinned mill，恢复既有环境后通过，
   不跳过工具绑定。OFF fixture对literal执行bore失败，改为Scala `if`分支，仅fixture修正；最终r3 compile与r4 emission
   重新绑定输入，CPU FIR与r2/r3连续。不能把这些compile/emit轮次称作多次CPU DUT构建。
3. component r3把非法canonical origin+certified load误当合法正例，触发既有assert。
   只将该刺激移为专用marker、非零退出及完整既有诊断匹配的HW assert负控，无RTL放宽。
4. recovery r1的undrained flush matcher仅预期accepted-count assert，实际先触发同条件的idle assert。
   recovery r2精确允许这两条既有完整诊断之一，要求SIGABRT与唯一marker，拒绝sanitizer错误和
   “assert未发生”；不是任意失败即PASS。原失败receipt/objects完整保留。
5. actual-graph初次负控在报告已发现路径时缺少synthetic reason metadata而KeyError；
   修复测试metadata后六项通过，未改parser、RTL或放松端点。历史日志保留。

6. host-only observer原receipt快照早于runner最后PASS输出，只有`runner.log`追加精确PASS行。
   `post-exit-finalization.json`证明删除该已知后缀可还原原hash，核对其他artifact不变并绑定最终hash；
   保留原receipt，零重跑/重建，不把原artifact manifest声称成无差异。

## 下一步判断

现有tap的host-only epoch/hint补证及独立审核已完成，结论限于上述source/structure/组件/CPU固定客体；
本批验证范围无pending，不代表物理资格或任意权限证明。
热端到端收益很小，剩余供给gap原因未定；后续应在固定容量/服务律下检查proof可用性、
issue选择及有效请求占比，不因4拍局部驻留就宣称一拍一请求，也不立即提升默认配置。
