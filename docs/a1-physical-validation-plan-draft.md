# A1 ≥300 MHz 物理验证计划（草案；诊断扩展 native 未验证）

2026-10-24 初版源码核查、原 OOC 入口小扩展与控制流程短测；同日独立增加第 8 节诊断选项。
第 1–6 节的 HEAD、候选与入口现状是初版快照，不代表后续 M3/SoC 集成后的当前源码身份，
下一次执行必须重新冻结实际候选。早前 default 综合已启动后停止，尚无完成的物理结果；
本次新诊断选项未在 native Vivado 验证。该计划不是 native 运行 receipt、
300 MHz 结果、板级资格或启动 Vivado 的授权。本次不改 Scala/emitter、不安装工具、不运行本地 Vivado、
不提交/发布、不生成 bitstream。

## 1. 先冻结正确候选，不能混用历史对象

- 目标器件：`xczu15eg-ffvb1156-2-i`，Vivado `2025.2`。CPU 测试周期明确为
  `3.333333333333 ns`；任何更宽松周期都不能满足 ≥300 MHz 目标。
- 核查时本地 HEAD 为 `6b4a4b9be4931827cfbcd5227a4ffeb62d5c3a0f`，工作树有进行中的
  physical-fetch owner/privilege（P1）合同显式化。**这个 HEAD 本身不是待测最终源码身份。**
- P1 是 owner 合同显式化及未来模块独立性加固，不是修复已证越权：当前 PMP 对 M-mode 也要求完整
  range covers，因此先前仅由 S/U→M 推断可扩大未经授权 line 的前提不成立。
- 等 P1 完成、必要的 owner/context 独立 witness 和受影响短测通过，再冻结整批源码/配置，目的是
  绑定稳定实现，不是把待测版标成已修复安全漏洞。已有 A2 receipt 不能资格化正在修改的源码。
- 首选整批候选是显式 `CommonA1RebuildProfile.FullCandidate`，不是修改公共默认。
  它保留双发射，组合 dual-owner completion、parallel memory、execution-mailbox branch、
  `fetchTransactionSlots=2` 和 `alignedFetchSinglePage=true`。
  冻结时逐字段核对它与真实 CPU 对照的 `dual-slot + combined-branch` 配置相等；
  不凭 profile 名称推断相等。P1 稳定版本的 emitter、构造参数及 RTL 都要重新绑定。
- 不用 I1 DCP、旧 A1 repair-on 报告、缩小 cache 的前端 fixture、旧
  `CurrentSocTimingTop`/`CompactSocTimingTop` 替代新 Common A1 tile。
  不以仅运行原始整数 guest、对 coherent/data ports 作 tie-off 的 GSIM 顶层作物理顶层。

## 2. 已核入口与最小差距

1. `src/test/scala/platform/CommonA1RebuildSpec.scala` 的 `CommonA1RebuildTileMain`
   已支持 `<profile-name> <output-dir>`，导出真实 `CommonA1CpuTile` 的分文件 SV。
   它目前不输出完整 source/classpath/config receipt，必须由同一冻结包补齐，不能假装已有。
2. `fpga/vivado-ooc.tcl` 现已显式接受 `CommonA1CpuTile` 且不向它索要 ROM hex；旧四个顶层的准入和
   ROM/RAM 必需检查保留。时钟约束写入 `reports/ooc-clock.xdc`，通过
   `read_verilog → read_xdc -mode out_of_context → synth_design` 的官方顺序注册。
   `get_ports` 保留在 XDC 文本中，不在空 design 时求值；综合后检查 actual part/top/clock/period。
   **上述新流程只通过 mock 控制流测试，Vivado2025.2 native 行为仍待首次验证。**
3. `fpga/vivado-module-ooc.tcl` 也不接受该 tile，且把 data I/O delay 全设为 0；这是模块比较惯例，
   不是 CPU/fabric 边界预算。不要靠改名顶层或套用零延迟把它当作整 tile/整机资格。
4. `CommonMachinePlatformMain` 目前只选择公共 `CommonCpuProfile`，没有 rebuild profile 入口。
   公共 A1 是 CPU100/fabric250，`performance300-static` 显式仅允许 I1。
   因而现有 `a1` 导出不能被标成 FullCandidate/CPU300；需后续显式整机集成与完整参数绑定。
5. `fpga/common/native_diagnostic.py` 是现有完整 native 诊断入口，支持有阶段/哈希的 DCP 续跑。
   它要求非空 IP XCI+DCP/products、pre-synth XDC 和 post-synth 约束；不能原封不动作为无 IP tile OOC。
   `outputs.json` 只表示命令返回/报告存在，明确不表示 timing/CDC/DRC PASS。
6. `fpga/common/signoff.tcl` 与 `manifest.py` 提供 same-DCP fail-closed 检查基础，但现有输出仍写
   `board_tested=false`、`full_cdc_signoff=false`。该门禁不能独自证明新 A1 的全 CDC/RDC/所有工作点资格。

**复用策略：**只扩展现有 `vivado-ooc.tcl`，不复制一套 A1 runner。
整机沿用 `native_diagnostic` 的明确输入/阶段约束机制及 common 的独立签核审计；不另造绕开 guard 的脚本。
新 `fpga/test_vivado_ooc.py` 仅为短 mock 测试，不是实现 runner，也不是 native API/时序资格。

## 3. 阶段 A：真实 CPU tile OOC300，只判内部路径与资源可行性

### A0：同一冻结包

最少绑定以下字段，并在 export/实现前后检查未漂移：

- commit、tree、分支，以及所有未提交/未跟踪输入的内容 SHA256；不能只写 HEAD。
- 所有生产 Scala、实际 emitter、资源/blackbox、`build.mill`、编译 receipt 和有效 compiled classpath。
- 完整最终 `FpgaNextConfig`、`coreParams`、memory profile、`CommonCpuTilePortParams`，含原有默认值和
  option-off 值；保留 ROB16/PRF48、双发射、32 KiB L1I/L1D、2-way、实际 LSU/DTLB/credit 数。
- 精确 Scala/Chisel/Mill/firtool/JDK 版本和可执行文件身份、导出命令/参数/宏、SV/include/init 文件顺序与哈希。
- Vivado 完整 build/version、exact installed part、许可证/设备支持、Tcl 与所有 XDC/helper 的 SHA256。
- 目标时钟、clock uncertainty/jitter/latency 假设、reset 合同、综合/实现 directives、线程请求与实际读回。
  “configured 8”不等于八个线程都在工作；综合/实现有效上限单独记录。
- 每一阶段 DCP、日志、报告的 SHA256 和 source→export→run 关联；明确 FAILED/PARTIAL/COMPLETE，
  不把仅有 checkpoint 或进程 exit=0 写为 timing PASS。

已有 source-matched 短测可复用；不得为了 receipt 重跑完整 GSIM/Linux，也不得生成假 PASS。

### A1：一次 fresh export

完成上述 gate 后，用已存在且版本固定的 Mill launcher 执行等价于：

```sh
mill -i IonSoC.test.runMain platform.CommonA1RebuildTileMain full-candidate FRESH_RTL_DIR
```

这条是待执行的 export 命令，不表示当前 PATH 中已有 `mill` 或本次已经导出。
输出目录必须新建且不混入旧 SV。检查 top/端口、FullCandidate 实际模块、完整几何、未预期 blackbox、
无 GSIM harness tie-off；P1 owner context 的真实链路必须存在。

### A2：原 OOC 入口已作最小扩展，待一次 native 综合/实现

同一脚本已实现，native 运行时仍需确认：

- 显式接受 `CommonA1CpuTile`，只对确需 ROM 的旧顶层要求 ROM hex，不填假 ROM 文件来绕过检查。
- 把 CPU clock 放进综合前注册的明确 timing XDC，并在综合后/opt/place/route 后验证 clock 对象、端点和
  实际周期。XDC 的 `get_ports/create_clock` 由 Vivado 在有 elaborated design 时处理，不能提前直接调用。
  读回允许最多 1 ps 的更短周期量化，不接受更长周期（例如 3.334 ns）；实际值保存在 boundary-scope 中。
- 保持只测内部路径的 scope；I/O 未预算就如实报告为未约束，不补 0-delay 或 false path。
- 在同一次流程保存 post-synth、post-opt、placed、routed DCP，尽量先保存再运行昂贵报告；
  route 失败保留已完成阶段。不要报告失败后重新综合只为提取另一个 report。
- 运行全 min/max timing summary、check_timing、clocks、route、DRC、资源和内部最长/最短 path 细节。
  需要层级资源归属时在这次综合预先固定 hierarchy 策略，不在后面无意追加第二次综合。

待源码稳定且物理执行获准后，计划使用的命令形式为：

```sh
vivado -mode batch -source fpga/vivado-ooc.tcl \
  -tclargs FRESH_RTL_DIR xczu15eg-ffvb1156-2-i 3.333333333333 CommonA1CpuTile
```

入口现在已接受这个 top；仍未在 Vivado 验证，不把 mock 通过当作此命令已成功执行。
若 `reports` 已存在则拒绝覆盖，需使用新的冻结 RTL 目录，保留先前失败/部分完成的 DCP 与报告。
不得设置 `VALENCE_PLACE_ONLY=1` 后把 placement 当 route PASS；也不为“找好结果”重复扫周期/seed。

### A3：结论与报告边界

- 同一 routed DCP 上，实际 CPU 时钟必须是上述周期；内部 sequential→sequential setup/hold 均无负 slack，
  TNS/THS 与失败端点数为零，适用的 pulse-width/内部 recovery/removal 检查也不得遗漏。
- 保存所有 no-clock、multiple-clock、unconstrained internal endpoint、loop 与例外清单。
  允许的顶层未预算端口必须逐组列出，不能把内部未约束路径藏在“OOC”理由里。
- 明确 reset 是同步输入还是异步控制、实际映射到哪些 pin。若 OOC reset 入口无外部时序合同，
  只能报告 reset 边界未资格化；不以 reset false path 消掉恢复/移除检查。
- 报 LUT/FF/BRAM/URAM/DSP、clock resources、拥塞和 route 完成度；报告长链的起止点、逻辑/布线比例、
  fanout 和所属模块。层级重建/优化可能改变归属，不把原生声明 bit 数当 LUT/FF 结果。
- 即便通过，也只能写“该精确 tile 在指定 OOC 假设下内部 300 MHz 可行”。没有 fabric、实际 clock tree、
  CDC、板级 I/O、整机拥塞/资源竞争，因此不是 A1 300 MHz 整机/上板资格。
- 旧物理结果只在 part、工具、scope、约束、宏和完整配置均可比时作定量差异；否则并列且标不可比。
  没有新 source-matched baseline，不声称 PPA 改善。功能 cycles 与 MHz 分开；固定同一 service law
  检查端到端性能，不能用局部高频隐藏吞吐/周期回退。

## 4. 阶段 B：整机同源 fresh synthesis、all-clock signoff

这个阶段有独立前置条件，不能从阶段 A 的 PASS 自动获得。

1. 在公共 common 平台上显式集成 FullCandidate/P1，不改变公共默认；绑定 CPU300 时钟生成、CMU/固件频率
   元数据及新配置的真实 affected-functional receipt。当前 I1-only 的 clock-profile guard 不可简单删掉。
2. 明确 static 还是 runtime-dynamic。≥300 MHz 目标本身不授权新增 DVFS。
   静态方案仍应核 CPU 与 fabric 的真实 clock source/关系；动态方案另需启动、切换、停钟、reset/隔离/复位
   释放及所有声明支持工作点的证据，不以最高频静态一张 STA 报告替代。
3. 收齐 exact board pin/IOSTANDARD/MIG、真实 clock/ROM 等 XCI、DCP 及所有 generated products。
   Vendor IP 可复用的前提是版本、器件、参数、生成物和原始生产证据一致；不复用旧 I1/旧 A1 设计 DCP
   作为新 CPU 的 raw/synthesized/placed/routed 输入。新 CPU 的首轮必须 fresh synthesis。
4. 明确每个阶段的约束清单和顺序：base/pin/IP XDC → LATE timing targets → post-synth → post-opt →
   preplace → optional phys-opt → placement-dependent pre-route。所有 source 的 helper 都在 manifest 内。
   缺对象、匹配数变化、错误/不支持命令必须停止，不静默略过旧 CDC/reset/ROM/MAC 约束。
5. 复用现有命令：`native_diagnostic.py prepare SPEC MANIFEST`，`check MANIFEST`，
   `run MANIFEST NEW_OUTPUT --vivado VERIFIED_EXECUTABLE`。SPEC 使用新候选来源、完整 IP 和约束输入，
   不是把旧恢复 manifest 改名。当前 README 明确指出此新入口的 Vivado2025.2 运行/API 验证仍待完成。
6. 保存新 candidate 的每阶段 DCP；后续报告或恢复仅用同一来源、实际完成阶段与 SHA 匹配的 checkpoint。
   `routed` resume 只查报告，不重跑 synthesis/place/route，也不把外来 DCP 的 hash 当来源证明。
7. 从同一个 SHA256-bound routed DCP 做全局 min/max、timing coverage、route、DRC、clocks、
   clock interaction、CDC、bus skew、例外覆盖/ignored paths、reset recovery/removal 与 pulse-width 审计。
   必须结合每类 CDC 的结构、端点匹配和 max-delay/bus-skew 物理预算；`report_cdc` 只是结构分析，不给 timing slack。
8. 盘点所有实际 clock，包括 CPU300、fabric/TIME/DDR UI250、AON/UART50、GMAC TX/RX/forward/pad/ref、
   debug/TCK 与启动辅助 clock。以上 common 默认值只作待核合同，实际方案/工具对象必须逐个核实；
   不仅遍历现有 signoff 的六个核心 domain 就声称“所有 clocks”。每种网络 rate/scenario 从同一 DCP 重开。
9. 核完全部 setup、hold、recovery/removal、pulse-width、所有有效 clock pairs、I/O 和明确 CDC 约束，
   无未解释内部未约束路径/黑盒、未完成 route、Error/Critical DRC 或未审 CDC Critical，才可作有边界的整机 STA 结论。
   现有 common 签核脚本的 scope 和报告 parser 还须在 2025.2/新 A1 上验证；未知格式按 BLOCKED，不伪造 marker。
10. 报告签核不等于板稳定性、完整 ISA/Linux/所有运行条件证明。bitstream、上板和长时测试另行明确安排，
    本计划不运行也不请求生成 bitstream。

## 5. 还需补齐的最小信息/能力

- **执行环境**：本次可用云工作区未发现 Vivado 可执行文件。物理运行需要一个明确获准的已有
  Vivado2025.2 执行环境、精确可执行路径、
  该 part 的设备支持/许可，以及足够内存/磁盘。没有本机运行授权就停在计划，不擅自安装/转移执行。
- **构建工具**：使用 owner 已有的固定编译/export 环境和 launcher，不因当前 shell 找不到 `mill` 就新装。
  若转移完整已冻结 SV，则仍携带原 compile/export 证据；不是要求物理执行器重新运行 GSIM。
- **tile 边界**：至少确认 clock/reset；若要把 OOC 扩展到输入/输出路径，还需每组端口的真实 launch/capture
  clock/phase、min/max arrival/required time、uncertainty、input transition/output load 和 reset-release 合同。
  暂缺这些不阻止严格限界的内部路径研究，但阻止接口与整机资格。
- **whole-SoC 边界**：新 A1 的明确板版入口/时钟方案、source-matched functional receipt、MIG/clock/ROM IP，
  完整 board/PHY/PCB I/O min/max 模型（含两边沿/各速率）、reset/CDC 端点和例外依据。已有 PHY 数值只在
  同一硬件/模式假设可证明时复用。不能只补 `set_input_delay/set_output_delay` 就宣布整机完成。
- **最小代码准备**：审查已实现的 OOC top/ROM/综合前 XDC 小扩展，补齐稳定版 source/config receipt。
  whole-SoC admission 是另一个明确的集成工作，不把改 metadata 或绕过 guard 当成实现。

## 6. 参考与核查来源

- 仓库：`fpga/vivado-ooc.tcl`、`fpga/vivado-module-ooc.tcl`、
  `src/test/scala/platform/CommonA1RebuildSpec.scala`、`src/main/scala/platform/CommonA1RebuildProfile.scala`、
  `src/test/scala/platform/CommonA1CpuRetirementGsim.scala`、`src/test/scala/platform/CommonMachinePlatformMain.scala`、
  `src/main/scala/platform/CommonCpuProfile.scala`、`fpga/common/{README-native-diagnostic.md,native_diagnostic.py,native_diagnostic.tcl,signoff.tcl,manifest.py}`。
- 扩展前 OOC Tcl SHA256：`cd842d9f48762fa06d99f29f588aa2e2b6e8e2c15a4bee7b22598dc4c6e4d0df`。
  待最终冻结时重新记录扩展后 Tcl/test/文档哈希；旧哈希不绑定本次扩展或未来候选。
- AMD 2025.2：[OOC constraints](https://docs.amd.com/r/2025.2-English/ug903-vivado-using-constraints/Out-of-Context-Constraints)、
  [综合前后 XDC 的官方顺序](https://docs.amd.com/r/2025.2-English/ug903-vivado-using-constraints/Synthesis-and-Implementation-Constraint-Files)、
  [I/O delay 的外部时序模型](https://docs.amd.com/r/2025.2-English/ug903-vivado-using-constraints/About-Constraining-I/O-Delay)、
  [timing summary](https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/report_timing_summary)、
  [setup/recovery 与 hold/removal](https://docs.amd.com/r/2025.2-English/ug906-vivado-design-analysis/Timing-Path-Details)、
  [CDC 结构分析范围](https://docs.amd.com/r/2025.2-English/ug906-vivado-design-analysis/Report-Clock-Domain-Crossings)。

## 7. 本次短测试结果及限制

`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s fpga -p test_vivado_ooc.py -v`
通过 22 项 Python/Tcl mock 测试：新 A1 无 ROM、旧四顶层/默认顶层、旧 ROM/RAM guard、
非法 top/period/part、综合后 identity/clock/period、XDC 注册失败、缺时钟/opt 后时钟丢失、
fresh reports 防覆盖、route 失败保留 placed、报告失败保留 routed、place-only 明确部分完成。
`general.maxThreads=8` 的请求和实际读回写入 `reports/inputs.txt`；读回低于 8 或失败即停止，
实际活跃 worker 数明确为未测量，不把配置上限当 CPU 利用率。
mock 明确禁止设计产生前的 `get_ports/create_clock`；把延迟 XDC 改为立即 `source` 的负例确实失败。
测试禁止 I/O delay、false path、导入设计 DCP 和 bitstream 操作。
新增覆盖默认/显式 default 的综合实参及完整阶段不变、仅追加 RuntimeOptimized directive、
非法环境变量 fail-closed、synth-only 保留非空 DCP 与报告、不能跳过 clock/part/DCP 校验、
报告失败不写完成标记，以及 directive 被拒绝时不隐藏错误/不自动换拼写重跑。

这些结果只验证 Tcl 分支、顺序和错误传播，不验证 Vivado 的实际 XDC 解析/对象 API、映射结构、时序或资源。
本次没有 Scala compile/export、硬件 simulation、synthesis/place/route/STA 新结果。

## 8. 可选快速综合诊断，不替代 default 物理比较

仅为下一次明确许可后的独立诊断准备，不自动启动 Vivado。当前默认调用、XDC 注册顺序、
`3.333333333333 ns`、exact part、`out_of_context`、`rebuilt`、defines 和其余综合选项保持原样。

- `VALENCE_SYNTH_DIRECTIVE` 未设置或为 `default`：不向原综合命令追加任何 directive 参数。
  显式设为 `RuntimeOptimized` 才追加 `-directive RuntimeOptimized`；其它值（包括空值、其它大小写
  和夹带额外参数）立即拒绝。它减少部分时序/RTL 优化，不移除时钟、不降低 STA 精度，也不禁用必要逻辑。
- **不要改用整套 `Flow_RuntimeOptimized` strategy**：官方预设还改变 hierarchy 和 FSM extraction。
  本入口只改变一个 directive；不使用 `-no_timing_driven`，不放宽约束、不加无依据例外。
- `VALENCE_SYNTH_ONLY` 未设置或为 `0`：仍继续原 `opt_design/place_design/route_design`。
  显式设为 `1`：先综合并核 part/top/clock/period，成功写 `post_synth.dcp` 且确认文件非空，
  再完成 post-synth utilization、hierarchical utilization、min/max 与 unconstrained timing summary、clocks
  报告后停止。输出 `SYNTH_ONLY_COMPLETED_NOT_FULL_OOC_NOT_TIMING_SIGNOFF`，不生成 placed/routed DCP。
  非空检查不是另一次 native DCP 重开证明；失败不写完成标记。其它值拒绝。
  若同时有 `VALENCE_PLACE_ONLY=1`，显式 synth-only 在更早阶段停止，绝不算 placement 完成。
- `reports/inputs.txt` 记录实际构造并执行的完整 `synth_command`、directive、synth-only 和阶段；
  stdout 同样打印命令/阶段。RuntimeOptimized 单独标记
  `DIAGNOSTIC_RUNTIMEOPTIMIZED_NOT_PPA_COMPARABLE_WITH_DEFAULT`；所有模式均写 `ppa_guarantee=NONE`。
  这不是工具内部有效参数的额外 readback；安装版接受情况由 native 日志佐证，错误直接传播、不自动 fallback。
  原冻结要求仍适用：源/配置/XDC/Tcl/tool/part/线程读回与输出 DCP/report 的 SHA 必须绑定。
- 该诊断旨在尝试较早取得首份综合网表和路径线索，**没有 native 耗时测量，不能保证更快、
  一定结束或修复先前长时间优化问题**。减少优化可能损失时序/面积 QoR，这是待实测的工程风险，
  不保证影响方向。报告的关键路径属于该 directive 的综合网表，不假定等同 default；
  与 default 或不同候选混用不能证明 PPA 改善。候选对比必须双方使用相同完整设置；
  post-synth slack 和功能 cycles 改善均不能替代 routed 300 MHz/整机资格。

参数与限制的 AMD 2025.2 官方来源：

- [synth_design 参数表](https://docs.amd.com/r/2025.2-English/ug835-vivado-tcl-commands/synth_design)
  列 `RuntimeOptimized`，但同页正文写 `runtimeoptimized` 并称大小写敏感。
  [UG901 设置说明](https://docs.amd.com/r/2025.2-English/ug901-vivado-synthesis/Using-Synthesis-Settings)
  也列 `RuntimeOptimized`。本实现采用参数表/UG901 的拼写；**首次获准 native 运行前，保存安装版
  `synth_design -help` 确认该精确值，当前 mock 不证明拼写已被 Vivado 接受**。
- [完整预设的其它选项](https://docs.amd.com/r/2025.2-English/ug901-vivado-synthesis/Vivado-Preconfigured-Strategies)
  说明为何只追加 directive、不切换整个 strategy。
- [增量综合限制](https://docs.amd.com/r/2025.2-English/ug901-vivado-synthesis/Incremental-Synthesis)：
  OOC 不支持 incremental synthesis；本诊断仍为 fresh RTL synthesis，不读旧 DCP 替代。
