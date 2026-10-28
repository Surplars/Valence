# A1 context-owned instruction prefetch：带 last-stale 抑制的实验 checkpoint

**2026-10-27：保留为默认 OFF 的可选实验，不提升为性能基线。**
新的 last-stale seed guard 减少了旧预取方案的 CoreMark 指令流量，但仍比第四批
control 多 **47.96%–52.44%**；CoreMark ROI 周期只减少 **0.0473%–0.0567%**。
独立 load 流的既有收益保留，依赖链没有收益，smoke 相对旧预取还有 6 拍回退。
功能通过不等于总体优化胜出；本 checkpoint 没有面积、功耗、Fmax 或布局布线结论。

已完成独立终审的是 **55 项纯检查、62 个受影响 cache 正例、18 个原 CPU candidate case**；
后者分为 **12 positive + 6 原 observer-negative**，其中 5 个固定 M/Bare 正例另带完整的
provenance ledger。**12 个历史 control 正例只复用封存结果，没有重跑**，不能写成新跑 30 例。
本页不把旧模型结果或静态准备清单计作新执行，也不声称完整回归通过。

## 1. 比较对象与配置

本文始终区分三个对象：

| 名称 | 含义 |
|---|---|
| 第四批 control | `FullR1M3EfficiencyRefactor4`；context prefetch OFF，load payload nomination OFF |
| 旧预取 | `FullR1M3ContextFetchPrefetchExperiment`，尚无 last-stale seed guard；旧完整结果保留 |
| last-stale 候选 | 同一 context-prefetch profile，只在 ON 分支收紧一次 seed 条件；本文最终候选 |

`contextOwnedInstructionPrefetch` 在 `FpgaNextConfig`、`OooParams` 中默认 OFF。
显式 profile `full-r1-m3-context-fetch-prefetch-experiment` 精确继承第四批并开启此项；
**不继承第五批 `loadPayloadNomination`**。第五批与本实验各自独立，旧命名 profile
和默认板级工厂不自动开启新预取，旧 instruction-prefetch 开关仍为 OFF。
`ExperimentalContextFetchPrefetch` memory policy 要求匹配配置和显式无副作用 RAM 范围；
旧 policy 不接受混入此开关。

双发射/双写回、原 demand owner/result ledger、cache/Home credit、ISA/FP、PMP/VM
及数据路径授权不因本次 seed guard 改变。旧预取相对第四批增加的上下文和可选预取
机制不能与“last-stale guard 不增加寄存器”混为一谈。

源码基点是本地第四批 checkpoint `9d2652b1e81d5c08b77879ca386b49d61edea9b7`，
不是声称新候选已经具有该 commit 身份。实测新候选由 source manifest 和编译 receipt
绑定，相关 SHA-256 见末节。第五批不作为本实验的性能或物理比较基线。

## 2. 可选预取的授权与不可撤销边界

物理 fetch context 始终保留 2-bit `privilege`；开启实验时再携带完整 64-bit
`sourceSequence` 与捕获时的 `identityTranslation`。后者来自 M/Bare 翻译模式，
不是以虚拟地址等于物理地址推测权限。buffer 在原 request handshake 上保存完整
context；权限使用原 privilege，不能把整个 packed context 当 privilege。

可选机会必须同时满足：

- 原 demand 接收、捕获的 identity provenance、完整 64-bit 新鲜度及 age usable 条件；
- 下一整条 64 B 位于显式无副作用 RAM 内，不跨 4 KiB 页，不溢出地址，完整 Execute-PMP 通过；
- 目标不已缓存、不 pending，单 speculative credit 空闲，不能链式预取；
- 无 invalidate 或 speculation kill；实际发出和安装仍检查原证书、权限及 stale 状态。

`K` 是现有 packet `cancel || rawCorrection`、redirect、trap、invalidate、pause、
VM/FENCE.I flush、recovery、park stop-admission 和 external hold 的并集。
它只是原控制的只读观察，不替代 demand 的 valid/ready 或原取消条件。
cutoff 使用 `C = nextToken + publicRequest.valid`，包括旧的 held、尚未接收的公开 offer。
wrap/rebase 处理不重编号 demand `nextToken`、`nextResult` 或结果 ledger。

**kill 不是撤销传输的许可。** fill engine 已接收但尚未提供 A、held A、A 已握手、
8 个 D beat、held completion 以及 joined demand 都保留原 owner 并必须完成 drain。
ON 时采用完整 payload 的 locked A 仲裁；不能只挑地址而混用另一生产者的 source/metadata。
已 join 的需求在后续 K 后仍收到正确数据；late error 按原 PC/mask 进行精确 fallback，
不能因“预取已 stale”吞掉需求。full fetch-idle 包含这些生命周期，不只检查前端队列。

上述是设计契约与定向验证范围，不是所有配置、所有交错或一般 OS 场景的形式证明。

## 3. last-stale guard 的唯一行为变化

相对旧完整预取，在 `InstructionLineCache.scala` 的 ON seed 谓词追加：

```scala
(!hit || !prefetchStale(0) || nextLine =/= prefetchLine(0))
```

复用既有的单槽 line/stale：reset 时 stale 为 false；新的 reservation 替换 line 并清 stale；
terminal completion 释放 outstanding 后保留 line/stale。不增加 Reg、表、IO、epoch 或 credit。
不改变 K、full64 cutoff、PMP、join、安装、held A、普通需求或错误重试规则。

| 条件 | 结果 |
|---|---|
| reset 后首次合法 seed | 保留原机会 |
| 上次目标 stale 完成、源行命中且下一目标仍相同 | 只抑制新的可选尝试，跨源行访问仍保留这项历史 |
| 不同下一目标 | 按原规则允许；reservation 可替换这一项历史 |
| 源行冷 miss，包括 invalidate 后的冷访问 | `!hit` 绕过抑制，仍须所有原授权通过 |
| 真正需求访问被抑制的目标 | 走原 demand refill/回复，不能被黑名单拒绝 |
| 已接收/held 的可选事务或已经 joined 的需求 | 完全不受新 seed guard 改写 |

这不是“免费去掉无用流量”：曾 stale 的传输可能已经服务过 joined demand；guard 没有
保留“曾 join”位。后续真实路径需要同一下一行、而源行仍命中时，可能失去有用的提前请求，
只能等普通需求或历史被替换。实测 smoke 的回退说明这种代价不能忽略。

## 4. 为什么收紧 seed，而不削弱 K

旧预取的一次 **observer-only CoreMark performance 重放**使用原 DUT object、ELF、
memory service、业务 oracle 和 provenance ledger。移除新增 `PREFETCH_DIAG` 行后，
业务 stdout 与原记录逐字节相同；不是另一次更有利的性能选择。

- 337 seeds = 307 reservations + 30 cancellations；307 reservation 均有 terminal。
- 64 次安装、243 次 stale non-install、0 errors；其中 **18 次 stale 仍成功服务 joined demand**。
- 首次 stale：198 次仅 packet cancel，39 次 packet cancel + redirect，5 次仅 accepted-demand
  `!ahead`，1 次三者同时。238 次包含 cancel、6 次包含 `!ahead`，两者有一次重叠。
- 实际生成配置的 `rawCorrection` 为常量 false；198 次无 flush 的 cancel 来自
  expected-next mismatch，不能把它们归因为未发生的 rawCorrection。
- 首次 stale 时 235 次已经 A accepted 等 D，3 次 completion queued，另 5 次虽处于
  reserved 阶段但同拍已经 A 握手；不是可以随意撤销的总线流量。
- 所有 seed/reservation 的 shadow-cache 检查都没有发现目标已经 resident。
  原 `nextExecutable` 已含 `!nextCached`，不能把问题说成漏了缓存命中门。
- 热点 `0x802023c0 → 0x80202400` 有 126 次 reservation，均由局部 packet cancel
  变 stale，零 install、零 join，共 8064 B；这是实际观察到的重复浪费集中点。

诊断中的离线过滤只是在**不变历史轨迹**上标记机会，也会过滤掉有用安装/joins。
改变 admission 会改变后续时序、请求和 credit，所以不把这些离线计数当流量节省或周期预测。
下节只引用新 RTL 的实际匹配运行。

## 5. 同条件 CPU 实测：全部三方结果

表内顺序均为 **第四批 control / 旧预取 / last-stale 候选**；周期越少越好。

| 固定 workload | ROI cycles | Whole-work cycles | 外部 I-channel bytes |
|---|---:|---:|---:|
| Smoke | 173 / 166 / 166 | 338 / 321 / 327 | 536 / 728 / 728 |
| Dependent 65-load chain | 320 / 320 / 320 | 378 / 378 / 378 | 408 / 472 / 472 |
| Independent 65-load stream | 90 / 65 / 65 | 148 / 123 / 123 | 408 / 472 / 472 |
| CoreMark performance | 359572 / 359389 / 359402 | 384017 / 383732 / 383703 | 10008 / 25624 / 15256 |
| CoreMark validation | 359864 / 359616 / 359660 | 384639 / 384280 / 384287 | 10008 / 23576 / 14808 |

- 新 CoreMark I bytes 相对旧预取少 **40.46% / 37.19%**，但相对 control 仍多
  **52.44% / 47.96%**。旧预取为 control 的约 2.56× / 2.36×，问题没有被低流量版本完全解决。
- 新 CoreMark ROI 相对 control 仅少 **0.0473% / 0.0567%**；相对旧预取反而多
  **13 / 44 拍**。Whole-work 相对旧预取是 **−29 / +7 拍**，保留两个方向的变化。
- Smoke ROI 不变，但 whole-work 相对旧预取 **321 → 327**，少一次 join 且 I bytes 不降。
- Independent ROI 保持 **90 → 65** 的既有收益；physical request inclusive span 保持
  **105 → 80**，warm interval 保持 `1:63,2:1`（control `1:60,2:1,6:1,11:2`）。
  Dependent interval 仍为 `5:64`、ROI 320。不能把前端受限 microbenchmark 改善说成依赖链提升。
- 所有固定五例的 architectural hash/CRC/retired 与 D traffic 保持原值；CoreMark D reads
  均为 65 次 / 4160 B、writes 为 0。减少 I bytes 不是更少执行程序或缩小数据工作量的结果。

| CoreMark 可选行为 | Performance 旧 / 新 | Validation 旧 / 新 |
|---|---:|---:|
| Reservations | 307 / 140 | 281 / 138 |
| Stale completions | 243 / 81 | 211 / 74 |
| Installs | 64 / 59 | 70 / 64 |
| 新候选 cancellations | 27 | 24 |

每个 CoreMark terminal ledger 仍有一条未使用的 installed resident line；它不是未 drain 的
transport credit。stale、unused install、未发出的 canceled seed 是不同代价，不合并成“无用次数”。
额外的完整 cache-line Get 占用 I 通道服务和 speculative credit，即使最后不安装仍付出传输成本；
本轮没有测能耗，不能从 bytes 直接推出功耗。

### 工具、fixture 与指标口径

- Scala 2.13.17、Chisel 7.3.0、Mill 1.1.7；GSIM pin
  `93b8cd23edd3228807c4f2a08c19c3936a463cb2` 加已验证的
  `simulator/gsim/tool_fixes/init-byte-span.patch`。仅 deterministic initialization；
  `RANDOMIZE_INIT` 未在本轮获得资格。C++ 使用 Clang 19.1.7、C++20、`-O1 -g`、
  ASan/UBSan、`-fno-sanitize-recover=all`，断言保留；LSAN 关闭。
- CPU top 是 `ContextFetchPrefetchBenchmarkGsim`；与第四批相同的 passive single-hart
  RAM fixture，实际 coherent D 返回 ReleaseAck，不发外部 probe。显式安全 fetch 范围
  为 `[0x80200000,0x80220000)`。不是板级 DDR、真实多 hart 或 Linux workload。
- 固定五例复用原 ELF、symbol、ISA/CRC/store oracle、service latency/backpressure、停止边界。
  匹配 memory model 首响应延迟 3 拍、8 B/beat、每通道最多 16 live；64 B 读按 8 个概念
  beat 服务，A 接收时冻结数据快照，consumer stall 延后后续服务。没有预热或增加时钟频率。
- `ROI` 是原 `roi_begin` 到 `roi_end` 标记的半开退休窗口；`work` 是从开始到 terminal trap
  的 `trapCycle + 1`，不混入后续 drain。`cycles` 还可能含 drain/inspection，不代替上述指标。
- `I_bytes` 是原 service counter：接收读请求时按 8 B beat 计数，含 demand、optional
  line 和最终 drain 对应的传输，不是 ROI-only、retired instruction bytes 或有效负载率。
  物理 load span、退休 interval 与 I bytes 属不同指标，不互相替代。
- 本轮新生成并编译一次 candidate CPU object，五例由三个原审计 host 执行；第四批控制 object
  和已封存 control/旧预取输出复用，**没有重生成、重编译或重跑 control**。
  实际生成字段绑定重新核对；只调整 cache write-enable 的观察映射，不改变 golden 或要求预取次数。

## 6. 验证分类与覆盖边界

### 新 last-stale epoch

1. **结构：PASS。** 一次全新 1133-source Scala compile；55 tests / 16 suites，无 ignored/aborted。
   CPU ON/OFF 与 flat/banked cache 共 4 个 FIR emission，3 个 ON whole-hierarchy firtool
   lowering/组合环检查通过；不是综合或时序验证。
2. **OFF graph：有严格限定的等价结果。** 保留 raw 与 annotation-only diff；只在字符串外去掉
   source annotations 后，唯一差异是已知 `MappedMachineCore.scala:160 → :163` assertion
   diagnostic。仅替换这一处经核实字面值后，全 normalized FIR 字节相同。
   不是 raw-file identical，也没有过滤任意数字、字符串或 ILC 逻辑。
3. **受影响组件：62 / 62 positive PASS。** flat/banked 各原 27 项加 4 新项：重复失败目标
   hit 抑制、cold-miss bypass、different-target/replaced-history 恢复、reset 后 first-hit seed。
   普通需求必须照常完成；原 full64、full-line PMP/RAM/page、held A 两方向、pre-A owner、
   joined-success-after-K、late-error exact fallback、安装/读冲突、credit reuse 等正例保留。
   **这 62 项全部期望 exit 0，不包含 observer 或 RTL assertion 负例。**
4. **CPU：5 / 5 fixed M/Bare positive PASS。** 原 architecture/service 和独立 provenance ledger
   均通过；10 份三方 raw comparison 留存，无 architecture error 或未分类字段。
   dependent/independent 的完整 stdout 与旧预取逐字节相同。
5. **原 candidate 其余 13 项：终审 PASS。** 包括 native、noncanonical、VM、三个 fault、
   forwarding 共 7 正例，以及原 6 observer 负控。7 例期望 exit 0、6 例期望 exit 1；
   负控恰在原 reach/failure marker 拒绝，不出现业务/audit PASS。这 13 例的 stdout/stderr
   全部与旧预取逐字节相同。另 5 个原 host 只构建一次，复用前述 CPU object 与三个已成功
   executable；没有重跑已完成五例或 control。合计新 candidate **18 = 12 正例 + 6 observer 负控**。

剩余七正例与历史 control 的比较只留下 prefixed VM JSON 需要解释。原 comparator 因只识别
整行 JSON 而保留 `REVIEW_REQUIRED_DIFFERENCES`，**没有将该输出改写成自动 PASS**。
独立 prefix-aware review 核对全部 8 records：只有 2 个 RAM CPU row 的 14 项
timing/fetch/IPC 字段变化，4 个 stage row 与 2 个 ROM CPU row，以及退休、架构和 D/PTE/certificate
指标不变。RAM `independent_alu` 的 work/ROI 为 **817 → 457 / 805 → 445**，work I beats
**251 → 257**、含 drain 的 all I beats **251 → 259**；RAM `branches` 周期不变，physical fetch
**15 → 16**、I beats **19 → 27**。新候选与旧预取仍逐字节相同，所以这些不是 last-stale 新增收益或
回退。逐字段独审闭合这一项，不做通用 JSON 豁免或放宽 ISA oracle。

编译用了 250.22 s，峰值 sampled owned RSS 为 4,264,792,064 B；这不是硬件性能指标。
执行采用 2 CPU affinity、4 GiB sampled RSS 与 512 MiB reserve 的 guard；cgroup 不可用，
不能声称内核硬限或充足内存余量。已终审命令的进程清理为空，无 sanitizer/timeout 失败。

### 保留的旧预取证据，不重新计为本轮执行

- 原组件：7 models、65 cases = 59 positive + 5 observer-negative + 1 real RTL assertion-negative。
  其中 age/wrap/held cutoff、buffer 三模式及 translation 的原证据保留；本轮未重跑其 6 个负例。
- 原 CPU：30 role-cases = 12 control positive + 12 candidate positive + 6 candidate observer-negative；
  另有 4 个独立新增 observer-only sensitivity negative，分别破坏 captured owner、reservation
  target、stale install、installed payload。它们不是生产 RTL assertion 失败，也未计入新五例。
- 旧首次生成/ABI 阻断和恢复记录保留；本轮没有改写旧证据来制造新 epoch 或覆盖不利结果。

**两种 CPU 检查证据不能混写：** common smoke/CoreMark 与 dependent/independent 五个固定 M/Bare、
PMPzero workload 有独立 full64 provenance、A/D owner、完整安装 payload ledger；其他
VM/FP/PMP/fault/forwarding host 是各自原 architectural/service 检查，不能自动等同于一般 VM
情况下完整投机授权的 CPU 检查证据。原固定 CPU I service 不注入 denied/corrupt；late-error、
wrap 仍是组件定向覆盖，本轮 CPU 未实际观察 wrap。忙态 SFENCE/FENCE.I、全部 PMP 组合、
外部 coherent probe、真实多 hart、完整 ISA/Linux/板级验收均不据此宣称通过。

## 7. 可审计证据与结论

以下是工程 evidence root；`build/` 生成物不意味着已纳入 Git 或可从源码 checkout 直接获得。
旧、新输出分开保存；引用旧 root 时以旧预取树为相对根，不重指其绑定路径。

| 相对 evidence root | 内容 |
|---|---|
| `build/context-prefetch-last-stale-suppression-20261027-r1/` | source freeze、compile receipt、55 pure、FIR/OFF/loop、冻结计划 |
| `build/context-prefetch-last-stale-component-runtime-20261027-r1/` | 两个实际 cache model、62 case 的 receipt、binding、原 stdout/stderr |
| `build/context-prefetch-last-stale-cpu-runtime-20261027-r1/` | 新 CPU generated/object identity |
| `build/context-prefetch-last-stale-cpu-host-runtime-20261027-r1/` | 原三个 host 与新五例输出 |
| `build/context-prefetch-last-stale-cpu-comparison-20261027-r1/` | 三方指标、全部 diff 和分类 |
| `build/context-prefetch-last-stale-remaining-cpu-runtime-20261027-r1/` | 另五 host、其余 13 case 的 receipt/binding/stdout/stderr |
| `build/context-prefetch-last-stale-remaining-cpu-comparison-20261027-r1/` | 13 case 的完整比较与 prefixed VM JSON 分类 |
| `build/context-prefetch-last-stale-independent-review-20261027-r1/` | 独立准入、实际 ABI/phase、结构/组件/五例/其余 13 例终审、分类补充 |
| 旧树 `build/context-prefetch-independent-review-20261027-r1/` | 原 65 组件、30 role-case、4 observer 负控及诊断终审 |
| 旧树 `build/context-prefetch-traffic-diagnostic-20261027-r1/` | 一次诊断重放、原始事件、逐字节业务比较、离线分析 |

| Evidence | SHA-256 |
|---|---|
| 新 `InstructionLineCache.scala` | `0e4f1908e5dee0fa304079f0c80a97f6e70bae7d75eebaf34ccedb54b1f7aa95` |
| 新 `structure/scala/compile-source-inputs.json` | `6f1ea92ca0485e985d2018d68b834737c0bf4ba1516da289a183a45861f20bbd` |
| 新结构 terminal review JSON | `83e947dfb6c7fc21332e673787665d6a28022e24b781a9ea9efa50d38284aa0b` |
| 新组件 terminal review JSON | `e80938a1af7b77f4d09541e5d6eec583a0d4342ca19efeb4d487257eb7268df7` |
| 组件分类 clarification Markdown | `4c904636979b37b9418639ba35aeb322ac616ba46de3bb0a80e198e957d21bed` |
| 新 CPU five terminal review JSON | `d87c7d20dd60735706dad8f3fb13eda4025dfb2436caac7e9785a5f0aa5aed0f` |
| 新 CPU comparison JSON | `7f8a0bbfd9afbb9cadd504c959aa05ef1932453a1d56c25c67c41bd32f09424e` |
| 新 CPU remaining-thirteen terminal review JSON | `0874ec9a2db76282dfbb53f010cb86cd1b78271a7d0b18fa1881a8d8a2d89bae` |
| 新 CPU remaining VM JSON independent review | `5c80426d40ff8b3857529feb84b3bb7febfa731a38c6ef9467862fe7d7eebc89` |
| 新 CPU remaining comparison JSON（原 REVIEW 状态保留） | `e1d5820f99df9fb3ff77d7c1ac5d6bfe08222b570fbf254e52e9e85dab8bdc71` |
| 旧 CPU matched terminal review JSON | `cdc06379013cceb3781b390c08ea906cfc388447a857292b0114a8307cae0fed` |
| 旧诊断 terminal review JSON | `c44ce67854dff6285ef825d7abc1a0fbd30d0e89cedb2f8baaed90bec8437935` |

早期 [integration draft](experiments/context-fetch-prefetch-integration-draft-20261027.md)
保留其写作时的“尚未执行”状态；本文才是截至上述终审的实测 checkpoint，不能反向改写历史。
本页与 README 入口是验证结束后的 documentation-only delta；原 source freeze 和原 README
字节另外封存，不声称旧 gate 的文档哈希直接覆盖新文本。RTL、业务 host、工具和原结果不因此修改。

结论仍是 **默认 OFF、可复现的实验选择，不推广**。独立流 microbenchmark 的明确收益不代表普遍收益；
本轮工程选择不以 CoreMark 的少量省拍接受额外 I 流量和机会损失，
这不是把周期与 bytes 换算成一个已测综合性能或能耗分数。
没有新 synthesis、logic/packed area、power、Fmax、routed timing、board result，
也没有新的 NaxRiscv 胜出、完整回归、正式 CoreMark 分数或生产签核结论。
