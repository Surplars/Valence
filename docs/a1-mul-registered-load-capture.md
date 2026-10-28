# A1 MUL registered-load operand capture：默认 OFF 实验

**2026-10-28：短功能、匹配 CPU 检查与一次正常 tile 资源映射已通过独立终审。**
本实验让 MUL 在原共享 M 端口空闲时，从既有、成功的 LSU registered result 取得操作数，
进入乘法器原有的 operand capture。第四批同源 OFF/ON 比较中，CoreMark performance / validation
的等频 ROI 吞吐分别提高 **0.8306% / 0.8310%**，I/D 流量不变；其余 10 个正例配对的业务
stdout 逐字节相同。同流逻辑映射的代价是 **LUT +0.59524%**，同时 **MUXF −5.55806%**，
FF/RAM/DSP 不变。收益是小幅、固定 workload 的实测周期改善，不是普遍带宽、面积或频率提升。

当前证据包括原编译 epoch 的 **44 pure tests / 13 suites**、混合恢复来源的
**26 component positives + 2 observer negatives**，以及同源两模型的
**30 CPU role-cases = 24 positives + 6 candidate observer negatives**。
保留早期 emission/host failure 和尚未见证的角落；默认开关仍为 OFF。
**逻辑资源计数不是 packed area；Fmax、布局布线、功耗和板级性能未测，不提升生产默认或宣称 PPA 胜出。**

## 1. 精确基线与开关

源码起点为 `4d3668da7e708b693796f4e6a67208bd882cf42d`；这不是声称该 commit
已经包含新 MUL 逻辑。最终实测源码由 recovery-r2 compile receipt 与 source manifest 绑定。

| 项目 | Control | Candidate |
|---|---|---|
| Profile | `FullR1M3EfficiencyRefactor4` | `FullR1M3MulLoadOperandCaptureExperiment` |
| 选择名 | `full-r1-m3-efficiency-refactor-4` | `full-r1-m3-mul-load-operand-capture-experiment` |
| `registeredMulLoadOperandCapture` | false | true |
| Context-owned **instruction** prefetch | OFF | OFF |
| 第五批 load payload nomination | OFF | OFF |
| 继承第四批的 data next-line prefetch | ON | ON |

最终 effective config/core params 只差新开关。`FpgaNextConfig`、`OooParams` 默认 false，
既有命名 profile 保持 OFF；显式 `ExperimentalMulLoadOperandCapture` memory policy
验证这一组合，不允许把 instruction-prefetch 或 nomination 的变化混入结果。
旧板级 factory 不自动开启或接纳这个实验。

受支持结构仍为双发射/双写回、ROB 16、PRF 48、完整 64-bit tag、dual-owner completion；
要求原 registered MUL/DIV operands、registered load forwarding/capture、owner-local readiness
与 shared MUL/DIV operand reads。短 tag、load completion bypass、fast head-load retire、
MUL word preview bypass 等混合路径被配置检查拒绝。不是给所有参数组合开放新旁路。

## 2. 改动的职责与安全边界

### 先保留原赢家，再增加一个数值来源

后端独立构造**原 registered-ready** MUL/DIV mask，并判断：

```text
oldAvailableAny = (oldMUL.any && mulReady) || (oldDIV.any && divReady)
originalPortFree = !oldAvailableAny
```

只有 `originalPortFree` 时，stable registered-load promise 才能扩展 MUL eligibility。
原 DIV mask、`SplitMulDivSelector` 实现、原年龄仲裁不变；不能由扩展后的 selector 或
late authorization 反向推导“原端口空闲”。因此已有可用原 MUL/DIV 赢家不会被新机会抢走。
DIV 不接受新数值转发；已经 PRF-ready 的 MUL source 仍用原 operand value。

promise cone 只读取原 registered LSU completion destination、owner-ready、class/pending
及原 FU availability。完整 token/kill/age 等晚授权不回灌 rank/reservation，避免形成
recovery/branch/dispatch 组合依赖环。**能参与选择不等于允许 start。**

### 实际 capture 的完整授权

被选 MUL 的某个 source 必须尚未 PRF-ready、精确命中原 registered load destination，
才用该旧 LSU result 的数值。新 capture 还必须满足：

- 成功 ordinary-load producer、原 memory-live 身份、完整 64-bit producer token 一致，
  精确且非零的 physical destination；不把 error/pageFault/store/atomic 值当成功 load。
- consumer 仍 live/pending，所选完整 token 与该 local live row 一致；producer/consumer
  都在当前 ROB occupancy 内，按 circular age 严格先 producer 后 consumer。
- 两个 owner 都未被 kill；每个操作数要么原 ready，要么是同一已授权 stable load 值；
  owner-ready 与 PRF-ready 精确一致，转发 physical source 没有同拍重新 reservation。
- 原 system/recovery/head-exception 条件保留；实际 multiplier start 还要通过
  原 `mStart`、MUL grant 和新增 `captureAllowed`。

producer/consumer 的绑定继承原 allocation 是唯一 row writer、固定 row index 与 full token
标识该 allocation、pending/memory-live 在 start/completion/kill 上更新的生命周期不变量。
这里**没有新增独立 ROB-tag 读口或交叉读取**；不能把被动诊断曾做的额外 ROB-tag 检查
冒称为新生产硬件。动态 audit 仍独立核对被接收的完整 owner、数值与实际 capture。

### 不变的 latency、credit 与 backpressure 合同

- 使用的是已注册、稳定的 LSU result，不是 incoming memory response 的组合直通。
  不提前发布 PRF readiness、不提前退休 load，也不更改 load/PMP/VM/fault 权限。
- 使用 `PipelinedMultiply` 既有 operand registers 和原 start handshake；不新增 RTL
  寄存器、队列或结果 credit。源级没有新 Reg 不等于映射后的 FF/LUT 数量必然不变。
- 原 multiplier count `< 8` 才 ready，不能借用同拍 pop 的 credit；接受 start 才预留原结果槽，
  原 pending 仅按真实 start、completion/kill 等原规则清除。
- capture 不要求也不制造 LSU completion acceptance；数值应是旧 token/data/destination。
  CDB backpressure、结果保持、同拍消费/替换和 full-token writeback/retirement 规则不变。
  后面的覆盖章节明确区分这些设计合同与实际未见证的 stall/replacement 角落。

“原 M 端口空闲”不是“全局性能免费”：新 MUL 仍可能竞争 dispatch/completion/ROB 资源。
晚授权拒绝不 start、不消耗新 multiplier credit，也不因拒绝本身清除存活 pending；
但扩展选择仍可能保留 `reserveMulDiv`，占去同拍原 ALU side-dispatch budget。
本轮没有动态测到这项 rejection cost，不能宣称拒绝零影响，也不能为消除它把晚授权送回 rank。

## 3. 同源、同工具、同 workload 的 CPU 实测

本轮 OFF 和 ON CPU **都重新生成一次、各编译一次**，来自 tile-policy-recovery-r2
同一源码 epoch、同一 qualified native r3 工具链。不是复用旧 prefetch-ON object 当 control。
八类原业务 host 按两 role 共完成 16 次 host compile/link 配对，12 正例 × 2 role 加 6 个
candidate 原 observer 负控共 30 次。先五例与后续原 case 分开保存，没有为汇总重跑先五例。

| 固定 workload | ROI cycles OFF → ON | Whole-work cycles OFF → ON | 等频 ROI 吞吐变化 |
|---|---:|---:|---:|
| Smoke | 173 → 173 | 338 → 338 | 0% |
| Dependent load | 320 → 320 | 378 → 378 | 0% |
| Independent load | 90 → 90 | 148 → 148 | 0% |
| CoreMark performance | 359572 → 356610 | 384017 → 381055 | +0.8306% |
| CoreMark validation | 359864 → 356898 | 384639 → 381673 | +0.8310% |

两个 CoreMark input 分别减少 **2962 / 2966** 个 ROI 和 whole-work cycles；等频 whole-work
吞吐提高 **0.7773% / 0.7771%**。吞吐变化公式为 `old_cycles / new_cycles - 1`，
不是简单把百分比周期减少写成吞吐增加；未验证的 FPGA 频率不能代入这些同频结果。
Independent physical-request inclusive span 仍为 105 cycles，dependent interval 仍为 5 拍。
普通 load microbenchmark 没有获得新增持续供给或依赖链收益。

| 每个 CoreMark input 的外部流量 | OFF | ON |
|---|---:|---:|
| I requests / I bytes | 159 / 10008 | 159 / 10008 |
| D reads / D-read bytes | 65 / 4160 | 65 / 4160 |
| D writes / bytes | 0 / 0 | 0 / 0 |
| Grants / release acks | 65 / 0 | 65 / 0 |

Performance 的 retired / ROI retired 保持 **384330 / 360525**，hash `eb74228486f9b622`，
CRC `8e3a1fd7e714e9f5`、final `e714`；validation 保持 **384290 / 360366**，
hash `fe7c19b5e0fe46c4`，CRC `8d840747e3c118f2`、final `e3c1`。
其余 10 个 positive pair 的业务 stdout 字节相同，positive stderr 全空；包括 VM JSON 在内，
完整 comparator 没有 error、未分类差异或 review-required 项。原 ISA/CRC/hash、precise-fault、
guest/service 和负控 rejection 合同未放宽。

### 实际 capture 事件，不是按机会数预测省拍

candidate common/dependent/independent 三类 host 加入只读 audit。每个 CoreMark 实际检查
**9506 MUL starts、9506 次随后 registered captures，其中 6477 次 stable-load numerical forward**。
期望数值独立来自旧 accepted PRF publication history 或已授权的旧 registered LSU result；
检查实际 capture payload/full token，而不只看到 eligibility 就算成功。

| 每次 CoreMark audit | Performance | Validation |
|---|---:|---:|
| Left / right forward | 2246 / 4231 | 2258 / 4219 |
| Both-source forward | 0 | 0 |
| MUL consumers retired / cancelled | 9494 / 12 | 9494 / 12 |
| 见到 result availability 的 owner | 9496 | 9496 |
| Open MUL lifetime / DIV start | 0 / 1 | 0 / 1 |

result availability 不是 completion acceptance；6477 个 forward 也**不是省了 6477 拍**。
此前 prefetch-ON 的被动轨迹同样出现过 6477 个授权机会，但那不是本轮 OFF/ON 的测试频率或
性能 control；只读轨迹分析不能代替新硬件匹配运行。本轮 6477 是实际新候选的捕获事件。

Smoke、dependent、independent 的 MUL starts 为 0，audit PASS 只能说明一致性，不能增加
数值转发覆盖。native、noncanonical、VM、fault、forwarding 家族保留原架构检查，
不自动继承完整 CPU capture audit。原退休 oracle 始终独立存在，不被 capture ledger 替代。

## 4. 验证覆盖与未见证边界

### 纯检查、结构与 OFF 连续性

初次全量 Scala compile 通过，44 tests / 13 suites 通过；后续仅补 tile policy allowlist
一行并增量编译一个生产 Scala 文件。**44 pure 结果保留在原编译 epoch，未重跑、未重新标为 r2。**
recovery-r2 新做 4 FIR emissions 和 4 个完整 hierarchy lowering/组合环检查；
最终编译绑定 1137 source inputs。纯检查和 lowering 不是硬件运行或综合时序验收。

OFF 相对本批初始 control 在仅去 source annotations 后字节相同。
相对封存第四批，严格 diff 有 **606 行**，原 `REVIEW_REQUIRED` 留存。
独审逐项验证 **260 个 module-scoped local identifier 的无冲突双射重命名**；不动 quoted strings，
所有表达式、类型、语句次序、ports/state/reference 在映射后一致，只剩一处已核实的
assertion location `MappedMachineCore.scala:160 → :163`。这是精确结构差异归类，
**不是 raw-file 相同、任意名字/数字过滤或综合/形式等价证明**。

### 实际 production backend 组件

26 positive descriptors = 同一 13 项 × OFF/ON，再加 2 个 ON observer-negative，共 28 个
验收 descriptor。它们来自 **10 个原成功 OFF receipt + 18 个恢复运行**；计入保留的初次
OFF page-fault 失败，一共发生过 **29 次 case invocation**，不能称首轮全部通过。
wrapper 使用实际 `IntegerBackend`、production decode/DTA/response buffer/translation boundary，
不是用重新实现的 eligibility mock 自证。

实际见证包括：

- ON source1、source2、同一 producer 满足两 source，分别检查真实 capture/算术/CDB/退休。
- two-producer、WAW 各一次 forward；head-wrap 有 40 次 forward 与实际 generation reuse。
  ON 正例共 49 次 forward 是定向事件数，不是性能指标。
- 实际同拍 original-ready MUL/DIV 竞争满足 witness 要求，没有用用例名称代替碰撞证据。
- consumer-only kill、producer+consumer kill 分别取消 1、2 个 owner；access-error/page-fault
  各一精确 trap，未发生 dependent MUL start。PTE/service/cause/tval witness 保留。
- 两个负控只修改观察副本，在预期 witness/错误信息处 exit 1；**不是移除 RTL guard 的 mutation**。

**未见证的角落不能写通过：** component 最大 multiplier credit 是 7，`full_pop=0`、
`lsu_held=0`、`late_rejected=0`。没有动态 count=8 同拍 pop、CDB-held LSU result、
专门 old-slot consume/replacement、孤立晚拒绝后存活重试或可归因 ALU ticket loss 证据。
CPU 也未出现 late authorization rejection 或 full-pop，CoreMark 未出现 both-source forward。
source1/source2/both 的组件 witness 不能替代缺失的 stall/credit/recovery 交错。

非法 live full-token rebind、只杀更老 producer 却保留 dependent younger consumer 等破坏原
rename/lifetime 不变量的状态，未通过生产接口被人为注入；不冒称 high-tag RTL 拒绝动态覆盖。
相关 source-level 最终 start implication 与原 full-owner/credit 合同仍保留，但不包装成完整 formal
或全组合安全签核。没有全 ISA、长 Linux、外部 coherent probe、多 hart 或板级验收结论。

## 5. 保留的失败与最小恢复

1. **初次 candidate emission 失败。** 新 profile 漏列 tile 的 explicit identity-fetch-horizon
   policy allowlist；初始 source/classes、失败输出保留。补丁只增加这一 profile 项，
   memory policy validate、RAM range 和硬件表达式不改。一次单源增量 compile 后，
   重新 emission/lowering 并重新绑定最终 source；初次 pure PASS 不等于当时 candidate 可展开。
2. **初次 OFF page-fault component 失败。** host 误要求 `error=false && pageFault=true`，
   而实际 Native/DTA 使用 aggregate error。恢复只把期望 `error == e.error` 改为
   `error == (e.error || e.page)`；仍严格检查 pageFault、cause 13、tval、invalid PTE、
   没有 physical request、没有 dependent MUL start/retirement。DUT/生成模型不改，
   原 10 个已通过用例未重跑。旧失败 host/executable/receipt 与恢复证据分开保存。
3. **CPU observer 静态绑定先行失败。** 两个 local tag 名被优化消失；保留初次绑定失败，
   用原有 CURRENT tag 表达式的相同 low-64 projection 重新绑定。没有改 DUT、guest 或 golden。
   extractor 的 145 lexical names 实为 **137 actual members + 8 regex false positives**，
   不是 145 个硬件 observation taps。所有本轮 CPU model/host/case execution 均无执行重试。
4. **资源 map 的 pre-export 环境检查失败。** 已合格 firtool 未在 map-local PATH 中，
   在 export/DUT 工具启动前就被检查截住。仅补现有精确工具的 PATH，刷新独立 gate，
   保留旧环境/失败 helper/gate；未换源码、二进制或 recipe，没有因此多跑 DUT compile/map。

恢复是修正 policy/host/observer 与生产合同的具体不一致，不通过删除 fault、token、credit
或独立 oracle 检查换取通过；原始失败不会被新成功 receipt 覆盖。

## 6. 工具、指标与复现边界

- Scala 2.13.17、Chisel 7.3.0、Mill 1.1.7；GSIM pin
  `93b8cd23edd3228807c4f2a08c19c3936a463cb2` 加项目已验证 deterministic
  `simulator/gsim/tool_fixes/init-byte-span.patch`。随机初始化不在本轮资格内。
  native r3 使用 Clang 19.1.7、C++20、`-O1 -g`、ASan/UBSan 和 fail-fast sanitizer flags；
  LSAN 关闭、外部 symbolization 不可用，这些限制保留。
- CPU top 为 `MulLoadOperandCaptureBenchmarkGsim`，control 是第四批相同 benchmark boundary；
  同一 single-hart passive RAM fixture、真实 coherent D/ReleaseAck、无外部 probe。
  第三 fetch 包安全范围仍为 `[0x80200000,0x80220000)`；未改变 memory service 延迟、
  backpressure、A 时数据快照、ELF/symbol、ISA/CRC/trap oracle 或 stop boundary。
- ROI 使用原 `roi_begin` 至 `roi_end` 半开退休窗口；whole-work 为到 terminal trap 的周期，
  不把 drain/inspection 混入。I bytes 是原 8 B/beat 外部读 service 计数，包括实际 fetch 流量，
  不是 retired instruction bytes。软件编译/host wall time 与 sampled RSS 都不是硬件指标。
- 执行 guard 为 2 CPU affinity、4 GiB sampled owned RSS、512 MiB memory/disk reserve，
  CPU invocation 900 s bound。cgroup 文件不可用，不能称内核硬限；极短过程采样为 0
  也不代表实际零内存。accepted 终态无 sanitizer/timeout/owned-process 遗留。
- 可移植 source 已落在
  [`simulator/gsim/harness/mul_registered_load_capture/`](../simulator/gsim/harness/mul_registered_load_capture/CPU_README.md)，
  backend 与 CPU 三 host 子集的 include/path 迁移已通过 9 个短例连续性独审，范围见下段。
  这不是完整 30-case 迁移、所有工具/guest 重建或普通干净 checkout 一键复现承诺。

已有入口包括 `MulLoadOperandCaptureConfigSpec`、`MulLoadOperandCaptureBackendGsimMain`、
`MulLoadOperandCaptureBenchmarkGsimMain`；精确选例、命令、工具和原始输入以冻结 plan/receipt 为准。
不为文档重复重编译、重跑全 GSIM 或引入已退役的 Verilator/ChiselSim。

### Portable host 的最小连续性验证

- Backend 复用既有 OFF/ON 两个正确 profile 的 DUT objects，各 compile/link 一个迁移后 host；
  跑 OFF `ready-variants` 及 ON `source1`、`source2`、`same-producer`、`load-error`、`page-fault` 六正例。
- CPU 复用既有 candidate object，compile/link `common`、`dependent`、`independent` 三 host，
  只跑 `common-smoke`、`dependent-positive`、`independent-positive` 三短例。
- 合计 **5 host compile/link pairs、3 个原 DUT objects、9 个短运行**；全部原 stdout/stderr
  逐字节相同，CPU 包括完整 capture audit，exit 0、无 sanitizer 或 owned-process 遗留。
  没有新 DUT generation/compile，没有重跑 CoreMark、全部 28 组件或 30 CPU。
  三个 CPU 短例 MUL starts 为 0，因此不是新增数值转发覆盖或性能样本。
- CPU include-path-only copy 有逆转换核对，frame/types/ledger/shared 输入保持精确字节；
  [`check_cpu_binding.py`](../simulator/gsim/harness/mul_registered_load_capture/check_cpu_binding.py)
  要求实际生成 CPP/header 的精确 pin。它只是只读 pin check，不授予任意新 model 的 ABI/phase 资格。
  仍须实际模型 full64/CURRENT/NEXT/capture phase 复核；不能为了通过而随意更新 hash。

迁移的 [`CPU_README.md`](../simulator/gsim/harness/mul_registered_load_capture/CPU_README.md) 与
[`BACKEND_README.md`](../simulator/gsim/harness/mul_registered_load_capture/BACKEND_README.md)
保留命令形状、qualified-tool/guest 约束及写作时的计划语句；上述独审是后续实际运行的终态。
原资格覆盖 8 类 CPU business hosts、105 business fields；可移植 CPU 子集仅 3 类，
137 actual capture members 也不是扩大到一般 VM/FP/OS 的授权检查覆盖。

## 7. 一次正常 tile 资源映射：小幅性能收益伴随 LUT 成本

使用第四批 normal `CommonA1CpuTile` 的封存映射作同流基线，非第五批或 prefetch 候选。
保持第四批真实 xcup/noiopad/noclkbuf/flatten/no-SAT recipe；除输入 Verilog 路径外，
`read_verilog` 后 recipe 逐行一致，没有插入 generic SAT-sharing，也没有重综合 control。
Yosys 0.52-2、独立 yosys-abc 0.52-2、sv2v 0.0.13 的工具/数据字节核对，
当前 host shared-library closure 单独获得资格，不冒称历史 OS 完全相同。

preflight 核对正常 ABI **256 ports / 4482 bits**、PRF 13 logical / 26 bank reads、BHT 256、
canonical 2052、60 recursively expanded memories 和六个 completion banks；原存储形状不变。
使用既有 recovery-r2 编译产物，**只做一次 combined candidate map，没有 map 重试或挑选结果**。
terminal mapped census、最终 log stat 与 receipt 一致，CHECK 0 problems，无残余 generic
memories/processes；32 条 warning multiset 与第四批一致，DSP/BRAM/LUTRAM/SRL/FF 参数模式一致。

| Primitive | 第四批 normal map | MUL candidate normal map | Delta |
|---|---:|---:|---:|
| Logic LUT | 181606 | 182687 | +1081 / +0.59524% |
| FF | 51918 | 51918 | 0 |
| LUTRAM | 698 | 698 | 0 |
| MUXF | 31036 | 29311 | −1725 / −5.55806% |
| CARRY | 5596 | 5597 | +1 |
| INV | 1979 | 1975 | −4 |
| BRAM36 | 16 | 16 | 0 |
| DSP | 30 | 30 | 0 |

实际运行 **2481.58 s**，peak sampled owned RSS **4,505,415,680 B**，exit 0，map/query
owned cleanup 为空。guard 为 4 CPU affinity、6 GiB sampled RSS、512 MiB memory/disk reserve、
3600 s timeout；cgroup 不可用，不是内核硬限。这些 wall-time/host memory 是工具执行开销，
不是硬件延迟或芯片资源。

结论是 **约 0.83% 等频 ROI 收益伴随约 0.60% logic LUT 增加**；较少 MUXF 不能与异类 LUT
计数直接相抵而宣布“总面积降低”。LUTRAM 也是 primitive-instance count，非等价 LUT 面积。
全局重映射不能证明全部差值来自某条局部 capture path。没有 packed area、depth、物理 Fmax、
routed timing、power 或上板性能结果，也不将两个百分比拼成未定义的综合效率胜出。
**保持默认 OFF、不提升性能基线**，同时保留小幅实测收益与真实资源成本。

## 8. 证据索引

均为工程相对路径；`build/` 生成物不意味着已经提交，源码 checkout 也不自动包含历史 artifacts。
早期 [source draft](mul-registered-load-capture-draft.md) 保留其写作时未执行状态；本文依据后续终审，
不反向修改旧 draft/receipt。

| Evidence root | 内容 |
|---|---|
| `build/mul-load-structure-validation-20261028-r1/` | 初始编译/pure/emission 失败，snapshot，recovery-r2 source/compile/FIR/loops |
| `build/mul-load-component-runtime-20261028-r1/` | 两模型、初始 page-fault 失败、recovery-r2 的 28 descriptor 混合来源与全部原输出 |
| `build/mul-load-cpu-preparation-20261028-r1/` | 原业务输入来源、冻结计划、实际字段绑定、read-only capture ledger/host 逆剥离 |
| `build/mul-load-cpu-runtime-20261028-r1/` | 两个 fresh CPU generated/object identity 与 receipts |
| `build/mul-load-cpu-host-runtime-20261028-r1/` | 16 host compile/link pairs、30 role-case 的参数/binding/stdout/stderr |
| `build/mul-load-cpu-first-five-comparison-20261028-r1/` | 先五例独立保存，不被总表覆盖 |
| `build/mul-load-cpu-full-comparison-20261028-r1/` | 完整 comparison 和逐项 raw differences |
| `build/mul-load-source-independent-review-20261028-r1/` | source、failure recovery、实际 ABI/phase、结构/组件/全 CPU 独审 |
| `build/mul-load-normal-map-plan-20261028-r1/` | 单次正常资源映射计划与历史基线/recipe 绑定 |
| `build/mul-load-full-cpu-mapping-20261028-r1/` | export/preflight、正常 mapped JSON、运行/资源 receipt、warning/mode census |
| `build/mul-load-portable-component-runtime-20261028-r1/` | 两个迁移 host、6 个短组件连续性运行 |
| `build/mul-load-portable-cpu-runtime-20261028-r1/` | 三个迁移 CPU host、3 个短例与原始输出逐字节比较 |

| 已核实 evidence | SHA-256 |
|---|---|
| `IntegerBackend.scala` | `c3d91fb33a4bc43a203c71fc5a3e23867e941d99b8c33641c61dde0bad9216f1` |
| recovery-r2 `compile-source-inputs.json` | `1611b466e59ed358cf65d448dde7dff4b996dcb79030546b90338b79a93ea899` |
| Structure terminal independent review | `13b03fffc4c1c9392ae021f40c7e474b522ab00ff4abe53cff42f346201ed232` |
| OFF exact local-name mapping review | `7bee6e58e4802874f8e5ba348aec9bcc1180f5591ceaeb25287169fb8867a7da` |
| Tile policy allowlist fix review | `a2d85aeb72a216574f8a857cad9b265fd28cb0d471615367f1ef6d3284314bee` |
| Page-fault host failure review | `3cbbe9120c81605042a0d58ed5f74a78f4a5437541cc0caeb3772245c1b3489f` |
| Component terminal independent review | `bb5236b03baa8a258c010534b20a7418a81dceb5c92cbe059a0135784cafac8b` |
| Full CPU terminal independent review | `6da6bd9b812c168a79c4cd98fdd14bf2d183b6f1dd41e04d1af27db311d5fb13` |
| Full CPU comparison | `25fc6bd69a6dac6683e9aa892a24a0abdadbb4cbfad98339fa6da71887774a1a` |
| CPU report facts/scope review | `9082c5024e9425f649bd9d659b5d1702ad8e53a199f0e8de391c8bbe2db21b07` |
| Normal map terminal independent review | `c41788c29e451c3b1f34cf52e62fb339dd8e15c0406a7b75f1cad11a3049eb24` |
| Normal map resource receipt | `00119b8ad3f613a7e5219a71896326d0acd43c7fdc61190524d21d97289508dd` |
| Normal map sealed `receipt.json` | `1cb89e55884722a253981e79efc04f3ba47ef9d69bd91d90751806e41422c8e8` |
| Normal map sealed `manifest.json` | `2895965932e96e1d20f6db01c68fc705a4ba8880beb02923a9abe9824dfe0c5b` |
| Candidate mapped JSON | `4fbab7c755ad529d1c7a169ab3cb981d9c5cfc7d4e94861b49e6da9251c9be95` |
| 第四批 baseline mapped JSON | `feda301192b011f4397881dcbbe000ca79abd354461a5a8e317f68fb1481051f` |
| Portable component terminal independent review | `5debf16fd2f328eeb2cdeac0d6af4d1d6d5aafe6da3a050e4fe46ae9fb7194b3` |
| Portable CPU terminal independent review | `90121525df3b198a4841e0dc2c4adce258db691fd613bfaca34c888ac5bd547d` |

本报告与 README 入口属于终态后的 documentation-only delta，旧 README 字节另外保全。
原 source/tool/model/host/receipt 不因文档改写，也不声称旧 gate 自动为新文本背书。

结论：**数值 capture 的固定-suite 功能证据与小幅等频 CoreMark 收益成立；实验保持默认 OFF。**
资源映射显示小幅 LUT 增加，可移植 host 的 9 个短例仅证明路径迁移连续性；
不宣称完整 ISA、安全形式证明、完整 checkout 全套重建、生产配置提升、PPA 或与其他 CPU 的新增胜出结论。
