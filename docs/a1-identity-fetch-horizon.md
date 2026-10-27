# A1 identity-only third-packet fetch horizon

## 结论与范围（2026-10-25）

接续 [certified load ingress](a1-certified-load-ingress.md)，本批只扩大**安全 RAM 内 identity fetch 的地址调度视野**，
不增加 outstanding 容量。默认关闭，保留双发射、two-owner / two-result / three-row window 和原 PRF。
短组件、真实 CPU、独立结构/运行轨迹审核及两项 host-only 补证通过；不作全回归或普遍不退化声明。

- 热 load：ROI **334→274**，完整 work+drain **1068→883（−17.32%）**。
- 延迟冷 load：ROI 357 不变，完整 **907→909（+0.22%，退化）**。不能只报 work 的改善。
- VM stream/dependency、Bare、native atomic/FP 的既有结果不变。
- PPA、Fmax、布局布线和本候选板级性能**未验证**；不晋升默认/推荐配置。

基线 `6b223f03c362b4a31d8dc95ef811cb21a21ef858`，分支 `dev/a1-identity-fetch-horizon-20261025`。
验证身份来自下列逐字节 source/compile/FIR/runtime receipts，不以分支名或本文未来提交 SHA 自证。
本批只新建 **1 个 CPU DUT + 4 个组件 DUT**；CPU control 复用 certified-ingress 对象。
后续 exporter r2 仅编译/emit 连续性检查；PBMT 和第三包 fault 补证仅重编 host，均为 0 新 DUT。

## 动机：已观测的漏发机会，不是权限证书

独立 frontend capture amendment 在旧热轨迹的 60 个 late-allocation 窗口中，均找到 full-address/context
一致的 `currentBase+16`：OLD demand/result count=1、无 held、当前及 +8 包 covered、目标缺失且无 owner，
但旧两地址 wanted/cachedTarget 禁止发出。再早一拍 count=2 的真实 response-turnover 机会单独统计，
不冒充 OLD-empty credit。实际后拍 mask=3 不能授权更早的请求。
`raw_capture_signal_sum` 是取消前 prefix 信号，不是实际捕获/退休吞吐；zero-capture 时完整 headException 未被观测。
这些证据只定位调度机会，性能由本批真实 CPU 对照另证。

## 配置、安全范围与模块合同

`fetchThirdPacketLookahead = false` 为默认值；显式候选 `FullR1M3IdentityFetchHorizon` /
`full-r1-m3-identity-fetch-horizon` 配合 `ExperimentalIdentityFetchHorizon` memory policy。
开启需双 owner、双 lane、compressed、registered window、aligned PMP 及实际 two-result translation adapter；
prepared/frontier/compact/history 等冲突配置继续拒绝。

集成必须传入 `Seq[SideEffectFreeFetchRange]`，包含正长度且不超 XLEN 的真实无副作用物理 RAM。
它不是 PMP execute permission，也不是“所有可缓存地址”。`CommonMachinePlatform` 从实际 `fabric.ramBytes`
构造范围；独立 tile 不能默认信任整个 aperture。CPU fixture 与本批 map 输入均仅为
**128 KiB `[0x80200000,0x80220000)`**，不能泛化为整板 2 GiB 资格。

```text
candidateWide = zeroExtend(currentBase) + 16    // 65 bits
lastWide      = candidateWide + 7               // 65 bits
thirdEligible = flag && !virtualized
                && !candidateWide[64] && !lastWide[64]
                && whole [candidateWide,lastWide] inside one explicit RAM interval
covered[i]    = live queried packet present || accepted nonstale owner(base[i], context)
priority      = oldest missing 0, then 1, then eligible 2
cachedTarget  = covered[0] && covered[1] && (!thirdEligible || covered[2])
```

仅通过完整范围证明后才使用 64-bit candidate。ROM/MMIO、VM、溢出和范围失败保留旧两包行为，
包括两个旧目标均 covered 时的 nominal nextBase。**不扩展 VM**：额外 PTW 可产生新的副作用访问，
PBMT/内存类型链未取得通用投机资格；“PA 落在 RAM”不能替代该证明。
frontend 的 virtualized/privilege 判定不等于数据 MPRV 状态：M-mode fetch 可在 SATP/MPRV 数据译址下仍为 identity。

| 模块边界 | 容量/信用与时序合同 |
|---|---|
| `FetchDemandOwners` | `queryCount` 2→3 只扩展查询，仍两个 accepted entries；accepted+held≤2，真实 response 才允许同拍 turnover |
| 调度/return matching | wanted、wantedPacket、cachedTarget、owner query 和 OLD-head shifted-key index 0/1/2 同步；完整地址/context/stale 匹配 |
| held offer | 冻结完整 address/context/mask；后续 guard/context/redirect 变化不撤回 irrevocable offer，invalidate 标 stale 后 drain |
| permission/route/result | 仍经原逐 word PMP mask、translation/permission、ordered physical route、two-result ledger；不新增 response→PC/issue 旁路 |
| registered window/packet | 原 three-row snapshot 和 registered packet；fault 作为包 metadata，仅真实选择该指令才成为精确异常 |
| recovery | 原 pause→drain→invalidate、CSR/SATP/SFENCE/PMP 生命周期不缩短；query context 三位不等于完整地址空间身份 |

没有新增流水级或声称固定一拍执行吞吐；credit、注册返回和下游 backpressure 仍限制 initiation interval。
本批收益来自提前准入已有空位，不是移除延迟/权限检查或扩容。

## 真实 CPU：相同退休工作和服务律，不等于所有内部流量相同

| 固定客体 | ROI OFF→ON | work OFF→ON | drain OFF→ON | work+drain OFF→ON |
|---|---:|---:|---:|---:|
| hot_loads | 334→274 | 1049→873 | 19→10 | **1068→883** |
| delayed_cold_loads | 357→357 | 900→893 | 7→16 | **907→909** |
| vm_store_stream | 456→456 | 622→622 | 7→7 | 629→629 |
| vm_dependency | 650→650 | 816→816 | 7→7 | 823→823 |

Bare work=6729、retired=8570 及完整已记录指标相同；native atomic/FP=328。
热/冷退休数 557/79、测量 loads 256/16 及声明的 instruction/PTE/data service laws 相同，
load start→complete 分布也相同，支持“fetch supply 改善”，不是单个 load 服务加速。
热 instruction A/D=26/187、data A/Grant/E=1/1/1、PTE=3 不变；但内部 data-translation 请求16→15、
prechecked starts496→497。冷 instruction A/D=11/67→12/75，多一次实际读取，不能称所有 work/traffic exact。
独立 A-offer extent 发现新增 `0x80200140` 的 64-byte RAM offer；该 capture 不含 A-ready，
因此 extent 证据称 offer 而非 handshake，host acceptance counter 另证 11→12。

| 全 capture（含 drain/寄存器 inspection tail，**不是 ROI**） | accepted / sample cycles OFF→ON | packet-empty OFF→ON | ON third requests |
|---|---:|---:|---:|
| hot | 298/1100→306/915 | 794→474 | 291 |
| cold | 52/939→57/941 | 200→194 | 46 |

VM stream/dependency/Bare third=0，全部 911 个共享 raw fields 分别在 661/855/6768 个采样周期逐拍一致。
所有 10 个 CPU captures 的 held cycles 都为 0，故其 held 检查是 **vacuous**；动态稳定性来自
raw component 的 1034 held cycles 和 integrated VM supply 的 18 held cycles，不冒充 CPU held-third 证明。

## 验证、补证与保留的失败

1. 原 coherent batch compile 一次成功，9 suites / 28 Scala tests PASS。
   OFF FIR 比较只去 source annotations，9,899,136 字节相同；保留字符串、diagnostics 和所有逻辑字节，
   不沿用前批较宽 normalization。4 个 comparator negative calibrations 均拒绝。
2. raw 与 integrated supply 各 OFF/ON 共 4 个实际组件，11 场景及 17 negative controls PASS。
   RAM32 含 drain 320→264、mixed580→438、backpressure685→532；这不是 CPU IPC。
   五个 ROM/VM 场景的完整 metric dictionaries/request/PTE hashes 一致，不能改称完整波形字节相同。
   覆盖地址高位/溢出/范围、compressed straddle、mask、old-context fill、stale/turnover、五次 frontend reset、
   real walker/cross-page/parcel faults 和 backpressure。
3. 独立 actual SOURCE/FIR/graph/range checks PASS；runtime review 自行解析二进制轨迹，不导入 producer analyzer。
   保留三项 checker 校准失败：module-source-annotation parser、错误位置的 negative mutation、
   graph-negative 缺 diagnostic-edge metadata。它们不是 RTL bug，未通过 RTL 修复掩盖。
4. r2 软件模型修正 r1 的 cache-fill context gap：非 stale 的旧 owner 返回应保留自己的 context-tagged fill，
   只有 live return bypass 要求当前 query context 相同。r1 曾短暂原地修改，随后恢复原 hash；r2 单独发布。
   r2 记录 8064 bounded cases、80000 seeded cycles、3888 shifted-key cases、9 directed/9 killed mutants；
   独审未重跑，模型不包含真实 PMP/PTW/reset/window/decode/trap，不能替代 DUT。
5. 后加正常 tile exporter 的显式 RAM 参数/parser 是单独 r2 source revision，不把它藏进“只编译一次”。
   r2 compile 和 4 个纯测试 PASS；两份 fresh CPU FIR 对 r1 **全字节相同**（不做 normalization）。
   仅一个 test/exporter 源文件变化、4 existing class +2 parser class、其余5127 classpath files不变。
   r2 structure receipt 重新绑定旧 graph，**没有重跑 graph/DUT**。

### PBMT=2 输入下的 VM exclusion 补证

复用两份 integrated supply 对象，404 cycles 含 drain、128 instructions、零 fault；实际 walker 消费
2 个 PBMT=2 leaf +2 个 PBMT=0 pointer responses，共4 PTE请求/2 walks。OFF/ON logs 字节完全相同，
17 artifacts 经独立重 hash，补证独审 PASS。r1/r2 preflight failures 因显式绑定 exporter/class 连续性而保留，
无 RTL/simulation 修复。只证明该 PBMT2 输入下 VM 事务序列未扩展；优化后的端口无 PBMT output observation，
**不证明 IO/noncacheable 类型执行、CPU Svpbmt ISA、真实 MMIO 副作用安全**。

### CPU speculative third transport-fault 生命周期补证

复用两份 CPU 对象，固定 64B denied instruction line 和独立 host oracle。ON 实际见证：

```text
cycle38  third request token11, current=0x80200030, address=0x80200040, mask3/context3
cycle57  exact token/base fault return, errors3/pages0
cycle111 first packet flush after third; taken branch retires cycle115
cycle166 success marker retires,此前无trap
cycle169 later real demand: cause1, PC=tval=0x80200040
cycle201 handler/terminal breakpoint; cycle218 fully drained
```

CSR handler 值、21 条退休和完整 drain 检查通过；独审重查17 artifacts及5 negative observation controls，PASS。
cycle111 是实际 packet flush，**不是直接 branch resolve tap**；未直接观察内部 cache-error storage。
本例证明 transport access fault，不是 PMP denial/VM speculative fault 的新覆盖。
OFF=198、ON=218，ON 多4 reads；这是正确性成本，不是性能收益。
attempt1 host syntax 因本地 `Expected` 类型名冲突失败，attempt2 仅改名、固定 guest/service 不变。
明确保留该 host 准备修复，不宣称所有 host 一次成功；无新 DUT/RTL/runtime 修复。

### 仍未建立的范围

- 每个 full-engine/route/ledger phase 的 reset 穷尽覆盖；五个 frontend resets 不够。
- CPU held-third 的 context cancellation 动态覆盖（已有 CPU captures held=0）。
- 通用 VM 第三包、完整 ISA/PBMT 类型合规、所有权限/异常组合及所有程序无性能回退。
- 本候选 Vivado/routed timing、Fmax、物理资源和板级结果；本地旧 51422 run guardian stop 且无 DCP，不构成资格。

云端正常 untapped tile export 已完成：179 个 SV modules、256 ports / 4482 bits，显式输入为上述128KiB。
**map 尚未执行**，功能 checkpoint 不等待该独立物理代理结果。对旧51422的累计比较发现一处
`TranslatedDataRequest` queue RAM 为8×350→8×351（pre-synthesis +8 bits），槽位数不变。
源级追踪确认已有 `request.prefetchNextAllowed` 字段因 `certifiedIngressNominal` 的完整head/descriptor
断言而在 emitted SV 保留（dequeue bit171）；唯一非声明/端口 consumer 位于 `ifndef SYNTHESIS`。
这是断言导致的字段 liveness，且51422→当前跨三个批次，不能归因于本次 horizon 单独造成。
`-DSYNTHESIS` 后是否实际消除此字段仍待 mapped inventory，不能把raw +8 bits报作物理FF/LUTRAM增加，
也不能预先保证物理资源不增加。归因记录：
`build/identity-fetch-horizon-full-cpu-mapping-20261025-r1/extra-storage-field-review.json`，
SHA256 `cb74f0608e2e3dd9bb2ff80f3b1abb4703bd63af268226d845fe208ace0e93cf`。
即使后续 Yosys map 完成，也只是资源/结构 proxy，不能替代 Vivado timing/Fmax；不与2GiB board profile混用。

## 可复核入口与证据身份

以下路径相对 repo；`build/` 为未提交产物，恢复/移交时需一并保留，不能只凭本文重建原验证身份。
现有 receipts 的 `AWAIT_*` 状态保留原写入时刻，后续独立 review 另行追加，不改历史 receipt。
最终 seal 已复核21 receipts、333 artifact entries、53 supplement files及32个当前code文件；
r2 public compile verify PASS，无遗留功能验证进程。此处不是额外一次DUT运行。

- 动机：`build/fetch-packet-supply-assessment-20261025-r1/front-capture-amendment.md` 与 witnesses。
- 合同/模型：`build/identity-fetch-horizon-contract-review-20261025-r1/{report.md,model-r2-review.md}`；
  `build/identity-fetch-horizon-model-20261025-r2/manifest.json`。
- 汇总：`build/identity-fetch-horizon-final-validation-20261025-r1/{REPORT.md,evidence-index.json}`。
- 最新 source closure：`build/identity-fetch-horizon-exporter-continuity-20261025-r2/all-source-hashes.json`；
  原 r1 source manifest 保留，不能用 r2 覆盖。

| Receipt/review（`build/` 下） | SHA256 |
|---|---|
| `identity-fetch-horizon-final-validation-20261025-r1/final-seal.json` | `f7db4ac4888375413c35045d0523b2680514e215675cb17f1b5a48493f784977` |
| `identity-fetch-horizon-final-validation-20261025-r1/evidence-index.json` | `764ba59ad95b61fcffbca81fa7587cf0ef551a68070ecb5c1288afc80f55e3f6` |
| `gsim/identity-fetch-horizon-cpu-20261025-r1/receipt.json` | `192c193b056623943f84a33bcee07377b2ecb2c3afb0092b469ea589a3e29253` |
| `identity-fetch-horizon-runtime-review-20261025-r1/receipt.json` | `466c88b7c310127c6cc813901a18364baff85144f76b272a8fb05f104a7df3aa` |
| `identity-fetch-horizon-exporter-continuity-20261025-r2/receipt.json` | `b28aceeb99bb8eacf0e0e82ffd12c772580b8b2eff2390ceeb0862f464bd643c` |
| `identity-fetch-horizon-independent-graph-20261025-r2/structure-receipt.json` | `2e84afb1167890060539344aab8f80277b0180d1828787820698877cbf41c32a` |
| `identity-fetch-horizon-pbmt-supplement-20261025-r3/receipt.json` | `b9676ca416a253b0942d172b30eb297ffbff8c2c51692e217b2f04ef70963684` |
| `identity-fetch-horizon-pbmt-independent-review-20261025-r1/report.json` | `26c46a5725bf2f681b9c9ad04461975a2283dc09901f0b5793e2c6f9f420f479` |
| `identity-fetch-horizon-third-fault-supplement-20261025-r1/attempt2/receipt.json` | `8367826672ff4496d72845ac0494a36c8a4e2051f7eb552018a29ddbca7cdb2e` |
| `identity-fetch-horizon-third-fault-independent-review-20261025-r1/report.json` | `c274e41b3bd8d45ce4f38c67acd997e03771fe5581d61d1302daae97105f21da` |

受控 runner：`simulator/gsim/identity_fetch_horizon_components.py`、`identity_fetch_horizon_cpu.py`，
均分 `--emit` / `--build-run`，要求显式 tag 和对应 compile/tool receipts；CPU 还要求 structure/component receipts。
`identity_fetch_horizon_off_fir.py` 是严格 OFF 比较器，CPU host 位于 `identity_fetch_horizon_cpu_host.py`。
复核已有结果优先只读 receipts/hash/轨迹；不能为了文档验证再次 compile、生成 DUT 或 map。
