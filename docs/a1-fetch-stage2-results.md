# A1 A2：两项完整 fetch owner 的闭环结果

2026-10-24。S1 基线为 `4e8e7ca`。本阶段保留二发射、8B transport packet、
`current/current+8` demand 范围及关闭预取，新增真实接入的两项 frontend owner、
translation/PMP/send 与 physical-return 分离、预留式有序 result ledger。

**前端阶段通过：持续热供给 Bare 171→142 拍、Sv39 227→170 拍，每次验证 112 条指令，
TL Get/D beat/PTE 请求均为零。另一个真实 CommonA1 CPU 对照也通过 18 次短执行与 6 个负例，
见第 6 节；不把供给 fixture 的消费计数称为 CPU IPC。**
两项 owner 不是最终 8B/cycle 前端，300MHz、面积、功耗与实现后时序仍未验证。

## 1. 可归因的三个配置

| 控制 | transactionSlots | alignedFetchSinglePage | 含义 |
|---|---:|---|---|
| original | 1 | false | 原 Selected/S1 路径 |
| aligned-control | 1 | true | 只改变 aligned specialization |
| two-owner | 2 | true | 新完整 owner pipeline |

原 Selected 的 single-page 开关是 false，不以隐藏覆盖制造对照。两种单 owner 控制的原九场景
**各 342 个字段全部与留存 S1 receipt 精确相等**；两种控制的 warm 全字段也精确相等。
默认构造器仍为 slots=1，非法 slots、unaligned、prepared/frontier/compact-key 等混合在构造时拒绝。

供给 fixture 使用实际生产的 frontend、adapter、request buffer、I-cache、ITLB/PTW、RVC/window/
reservoir 链，只有 I-cache 从 Common 的 512 lines 缩为 8 lines（512B）。不是直接喂解码指令。
原 `a1_fetch_supply.py`、`driver.cpp`、`oracle.h`、`oracle_test.cpp` 保持原字节；旧 Scala fixture
增加显式参数与入口，因此不能再称整个旧 fixture 文件不变。服务律与精确字节 oracle 不变。

## 2. 原九场景结果与流量

下表为固定指令工作量的 `work_cycles`，非 drain 总周期，也非软件仿真耗时。
“外部匹配”要求 Get 数、D beat 数、Get address/size extent hash 同时相等。

| 场景 | S1/单 owner | A2 | 外部 Get 前→后 | D beat 前→后 | 外部匹配 | virtual packet bytes 前→后 |
|---|---:|---:|---|---|---|---|
| ROM32，128 条 | 580 | 517 | 65→66 | 65→66 | 否 | 520→528 |
| RAM32，128 条 | 332 | 299 | 9→9 | 72→72 | 是 | 520→528 |
| RVC 跨包，256 条 | 644 | 580 | 13→13 | 104→104 | 是 | 784→784 |
| reservoir 背压，256 条 | 688 | 663 | 14→14 | 112→112 | 是 | 784→784 |
| redirect 等待旧 reply，128 条 | 1034 | 1023 | 50→52 | 50→52 | 否 | 400→416 |
| Sv39 跨页，128 条 | 433 | 381 | 8→8 | 64→64 | 是 | 400→400 |
| 第二 parcel page fault，1 条 | 59 | 44 | 1→1 | 8→8 | 是 | 24→24 |
| 第二 parcel PMP fault，1 条 | 25 | 25 | 1→1 | 8→8 | 是 | 24→24 |
| 第二 parcel ROM fault，1 条 | 22 | 21 | 3→3 | 3→3 | 是 | 24→24 |

所有场景 PC、完整指令字节、精确 fault/tval、已消费指令 hash 都通过独立 oracle。
fault-only/denied transport 也计入 virtual packet bytes，这不是实际物理读取字节。
ROM32 与 redirect 虽然周期更少，但多发了尾部/旧路径请求，不把这两行当同外部流量提速。
RAM32 外部流量匹配但内部多一项尾部 8B 请求，也明确保留该差异。

## 3. 持续供给 witness

先通过真实链暖入 448B 指令流，足迹大于 256B frontend packet cache、小于 512B I-cache。
完整 drain 后仅执行普通 cursor redirect，不做 FENCE.I、不 invalidate I-cache/ITLB；再执行两个相同 ROI。
没有注入 cache 数据、提前填寄存器、加预取或缩短 host 服务。warm host 复用旧 `tick` 与字节/owner
oracle，只把原冷 Sv39 的“必须出现 walk”覆盖条件换成 warm 的“必须零 walk”。

| ROI（两个重复结果均相同） | 指令数 | work cycles 单→双 | 含 drain cycles 单→双 | 内部请求单→双 | 外部流量 |
|---|---:|---|---|---|---|
| warm Bare | 112 | 171→142（-17.0%） | 173→146 | 57→58 包 | Get/D/PTE/walk 全 0 |
| warm Sv39 | 112 | 227→170（-25.1%） | 230→175 | 57→58 包 | Get/D/PTE/walk 全 0 |

这证明端到端持续供给实际改善，而非仅局部 command II 改善。两种 ROI 均出现两个 virtual owners；
热 I-cache 物理请求的最大在途仍为一，重叠发生在不同 command 的 translation/send/return/result 义务之间。
暖场景内部 456→464B 的尾部请求增加没有隐藏；所称匹配是同固定指令字节流和相同外部零流量，
不是每个内部握手的逐值相等。112/142 与 112/170 是供给 fixture 的消费率，不是 CPU IPC。
结果也没有达到每拍持续两条/8B，后续仍需扩大合法需求可见性、容量并继续逐阶段端到端归因。

## 4. 所有权与正确性 witness

生产边界是 `FetchDemandOwners`、`FetchCompletionLedger`、`AlignedFetchPermissionStage`、
`OrderedFetchPhysicalReturns`、`PipelinedAlignedFetchEngine` 及公共 wrapper，均真实出现在 emitted FIR。
global result 在 command 接受时预留；fault 也占用 slot；physical route 仅在真实 request.fire 入队。
本地 fault 可以先完成，但不能越过旧 head 交付。默认 S1/generic 路径保留，I-cache/ITLB/PTW 未改。

三个独立小模型的实际计数：

- frontend owners：256 accepted/256 retired，max=2，held=258，stale replies=232，
  cancelled-held=13，旧回复/新请求同拍=127。
- result ledger：256/256，年轻先完成=110，held result=216，turnover=254，满 credit=2141 拍。
- aligned adapter：128/128，max=2，turnover=87，held result=90，held context churn=518 拍，
  年轻 fault 先于旧 physical=4，同拍 TLB 请求/回复=31，physical overlap=25，
  physical/local completion 竞争=2，首次 physical request 同拍 response offer=1。

自动 trap 并不等待 fetchQuiescent，可能直接改变 live privilege。因此新 public wrapper 在**首次公共
valid&&!ready**冻结完整 VA/mask/SATP/privilege/SUM/MXR，而非等内部 credit 可用再采样。
host 在旧 S/U offer held 时切换 live M/Bare，实际 TLB 字段仍必须归首次 offer。
这是独立证明的正确性修复，不用“新旧同错”作为等价论据。PMP/SATP/SFENCE 正常写入继续要求 drain；
idle 包括 held、translation、permission、physical route 与全部 result 义务，不只看 send stage。

**2026-10-24 后续审计更正：**原报告把 I-cache 使用 live privilege 推断为旧 S/U demand 可能在 trap
升 M 后越权扩大 64B，这是过强推断，现撤回。接口事实不变：Common live privilege 可先于旧 fetch drain
改变，physical request 尚未显式携带原权限；但 `PhysicalMemoryProtection.scala` 的 checker 对 M/unlocked
也始终要求 first-overlap 项完整 covers 请求，M 只绕过 RWX，不绕过整体范围覆盖。

在 Common 当前的稳定 PMP、同 16 项 checker、aligned 8B、全 mask 且已获 S/U 执行许可的前提下：
若 M 允许包含该 packet 的整 line，则第一项必须 covers 整 line，且无更早项与 line 交叠；它也必然
是 packet 的首匹配项。packet 获 S/U 许可意味着该项 X 为真，因此 S/U 同样允许整 line。
M 无匹配直接允许的情况与 packet 已获 S/U 许可矛盾；partial/zero mask 又不会走 linefill。
所以拟议的“窄 TOR 只许 8B，切 live M 即扩大 64B”负例在当前实现不可达，不能伪造此负例或称已复现漏洞。

这是一项源码级组合证明并经独立复核，不是新增动态测试；也不泛化到可变 PMP、不同 checker、非对齐桥或
预取拓扑。typed owner context 可作为后续显式接口合同加固，但不能把它描述成修复已证实的此项越权漏洞。
原九场景与 bare-M CPU guest 的实际测试范围没有因这项更正而扩大。

允许首个 physical.request.fire 同拍出现合法 response **offer**；ready 仍等 route 注册后才拉高，
响应必须保持到实际 fire。没有加入 response bypass 或额外时序边沿。route-empty 且无新 request.fire
仍是错误。native InstructionPort 返回无 tag，必须有 ordered/exactly-once 下层合同：FIFO 不能识别
在另一个 live owner 期间伪装成其回复的任意同 payload duplicate；真实 TL source oracle 独立检查。

12 个负例均要求指定诊断，不能把任意非零退出当 PASS：
owners 的 unowned/held payload，ledger 的 wrong generation/duplicate/unowned/result payload，
engine 的 ordered payload/unowned physical，以及整链 PC/data/tval/TL source 四项。
硬件断言负例另外要求注入 marker；ASan/UBSan 错误不能冒充预期失败。

## 5. 可复验 evidence 与尚未证明的范围

- 一次统一增量 Scala 编译与两个配置 suite（5 tests）通过：
  `build/a2-20261024-r1/compile-receipt.json`。
- 六个重新生成的 GSIM 模型、12 个精确负例、warm 复用生成模型通过：
  `build/gsim/a2-fetch-20261024-r1/receipt.json`，SHA256
  `138098e67062a05d153231fefaba765f8706d4e6d13a2a0cf666a40df87779f6`。
- 冻结源 manifest：`build/a2-20261024-r1/source-manifest.json`，SHA256
  `c8dc09bee77cb93cf6f8627b76c69625584cf6c7d3ed40ac46d0dd289532cf40`；源漂移检查为空。
- 详细日志、FIR、生成 C++、模型和负例 hash 位于
  `build/a2-20261024-r1/frontend-phase-receipt.json`。
- 命令：`python3 simulator/gsim/a2_fetch.py --gsim <pinned-gsim> --tag <fresh> --baseline <S1-receipt>`。
  留存 S1 baseline 未重新执行；当前 original/control 是新源码重新 emit 的模型。

本阶段未跑 Verilator、完整 GSIM/Linux、Vivado、综合或 STA。新 ledger、两个 token/context、
64bit generation 比较、credit/permission/route 组合锥均有未知 PPA 成本，零新增 cycle 不意味着零逻辑或 Fmax 成本。
目标器件按已核 Common 平台的 UltraScale+ `xczu15eg-ffvb1156-2-i`，不能用旧 I1 的 timing 报告替代 A1。
真实 CommonA1 tile 的独立退休结果由下节单独 receipt 绑定，不在前端 receipt 中。

## 6. 实际 CommonA1 CPU 退休对照

独立验收使用真实 `CommonA1CpuTile`，三个配置固定同一个 CombinedBranch/B2 backend base，
仅改变 slots/single-page 控制；这不是把当前 legacy 控制误称原生产 A1 全机基线。
实际 32KiB L1I/L1D、ROB16/PRF48、VM/PMP/FPU 等结构均保留，host 只送原始指令字节。
精确合同、固定 raw TL service、独立 ISA oracle、work/ROI/drain/inspection 定义见
[a1-common-cpu-retirement.md](a1-common-cpu-retirement.md)。

三个模型各执行同一组 6 guest，并各执行退休数据/TL source 两项观察负例，共 18 次实际执行与
6 个负例 PASS。`legacy(1,false)` 与 `single-page(1,true)` 全部 metric 逐字段相等。
每次退休的 PC、raw instruction、目标寄存器/写入值、next PC、token 唯一性、最终 EBREAK trap
和 32 个最终 GPR 由预先运行的独立 raw-byte ISA oracle 检查，不拿 DUT 结果产生期望值。

| guest / 放置 | 退休数（不变） | work 单→双 | work+drain 单→双 | 总 TL Get 单→双 | 总 D beat 单→双 |
|---|---:|---|---|---|---|
| independent ALU / ROM | 482 | 1217→976 | 1225→986 | 244→245 | 244→245 |
| dependent chain / ROM | 481 | 1214→974 | 1221→982 | 243→244 | 243→244 |
| branches / ROM | 452 | 365→360 | 372→370 | 9→11 | 9→11 |
| independent ALU / RAM | 484 | 1146→1027 | 1153→1034 | 33→34 | 250→251 |
| dependent chain / RAM | 483 | 1145→1027 | 1152→1034 | 33→34 | 250→251 |
| branches / RAM | 454 | 377→375 | 393→382 | 4→5 | 18→19 |

RAM 的 work 与退休数包含固定的两条 ROM bootstrap，不能与 ROM case 当同起始状态互比。
work 结束于已核实的 terminal trap，之后才拉 hold；不因提前停取指/停退休制造漂亮数字。
work+drain 不含随后 32 拍 GPR inspection。六项从开始到完整 quiescent 都缩短，但 TL 总数均增加
1–2：这是相同程序/放置/服务律下的周期改善，不是外部 trace 等价、总线效率全面提高或任意负载加速。

证据：

- `build/gsim/a2-common-cpu-retirement-20261024-r2/receipt.json`，SHA256
  `fc90bac63295b11597a74e279bbc56ff27787ded811690e139d0e9eb1950f76b`。
- 紧凑逐项表：`build/a2-20261024-r2/cpu-stage-comparison.json` 与同名 CSV。
- r1 首次完整 tile 已成功 elaboration/lowering，但新 host 有三处 GSIM 类名遗漏 `S` 前缀而编译失败，
  没有执行 CPU guest。r2 最小修复 host 后，保留复用该 legacy FIR/header/generated C++，重新编译 host
  并完成三个配置；失败记录保留，不把 r1 描述成干净通过。A2 生产/前端 fixture/host 的 14 项冻结输入未变。

CPU guest 只覆盖 M-mode/Bare 整数/branch，不资格化 VM/PMP protection/FPU 语义、完整 ISA、数据内存、
真实 ROM/DDR 时序、Common fabric、CDC、Linux 或板级运行；没有直接动态覆盖第 4 节的 trap/PMP 组合合同。
仿真硬件 cycles 改善不保证在真实器件有相同 MHz、面积或能耗，最终仍需统一物理资格检查。
