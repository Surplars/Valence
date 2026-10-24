# P1 显式合同候选：physical fetch owner 权限贯穿到整线授权

2026-10-24，**原修复动机已有重要更正；已作为显式合同加固通过必要短测与等周期对照**。
A2 实验 checkpoint 为 `6b4a4b9`，其已测周期结果保留；没有新增上板、300MHz/PPA 资格。
最终结果、fixture 构建失败/最小修复与复用记录见
[a1-fetch-owner-context-results.md](a1-fetch-owner-context-results.md)。

**更正：**当前 PmpChecker 对 M/unlocked 仍强制 first-overlap whole-range covers，仅绕过 RWX。
稳定相同 PMP、aligned 全 mask packet 已获旧 S/U 许可时，M 若批准其整 line，则同一首匹配项必覆盖
line 且 X 为真，S/U 也批准该 line。partial/zero mask 不走整线。原先根据 live privilege 连接直接推断
“升 M 会把仅许可 8B 扩大成越权 64B”遗漏了此条件，已撤回并独立复核。
原定 live-M 扩大负控不可达，**不得实施旁路 checker 的假反例**。
本候选改为显式 owner 合同加固，并独立证明范围蕴含与上下文运输，而非已复现漏洞修复。
完整证明与已批准新验证范围见 [a1-fetch-pmp-line-implication.md](a1-fetch-pmp-line-implication.md)。

## 1. 接口事实与不改变的合同（风险推断已更正）

S1 engine 和 A2 permission stage 已保存命令的 privilege，8B PA/mask 的 PMP 检查归旧 owner。
Common 的 `InstructionLineCache.io.privilege` 仍直连 live core privilege；`safeTrap` 不等待
fetchQuiescent，automatic trap 也不等于 `systemInvalidate`。但它不能单独证明越权扩大，必须同时考虑
上述 first-overlap/covers 组合不变量。PMP/SATP 写原有 drain 保证配置稳定，正是该证明的前提。

本次只闭合 demand physical request 的权限归属。不增加 owner、packet 宽度、lookahead、预取，
不增加 pipeline cycle，不改 trap 时刻/公共虚拟请求协议，不把所有请求强行按 U/S 检查。
合法 M-mode demand 仍按其原始 M privilege 检查整线，因此不会靠禁用 M-mode I-cache 掩盖问题。

## 2. 最小 typed 接口

新增 `PhysicalFetchRequestContext` Bundle，当前只有 `privilege: UInt(2.W)`。
PA 已经完成地址翻译，SATP/SUM/MXR 不参与后续 physical PMP；PMP 配置仍由原全 drain 屏障保证不变，
所以本次不复制整份 PMP/SATP，也不捏造未经定义的权限 epoch。

`InstructionPort(packetWords, withRequestContext = false)` 增加可选的 typed `requestContext`。
默认 false 保留旧端口形状，旧 generic/ROM/bridge/test caller 不必改；Common A1 的 adapter→buffer→cache
物理链显式开启，单/双 owner 都如此，虚拟端口仍关闭。

context 没有独立 valid/ready：它与现有 request.bits/word mask 共用一次 request handshake。
三者构成一个不可分离的 owner payload。使用旧地址+mask 分离式端口表示只是兼容方式，
**不能另做一个 live sideband 寄存器，并在下一项请求时覆盖上一项的权限**。

### 生产者

- S1 registered engine：直接输出已有保存的 `privilege`，同一 owner 的 sendFirst/sendSecond 都使用它。
  不改变 command 采样、PMP first-offer 时刻、cross-page 与 zero-mask 语义。
- A2：`FetchPhysicalCommand` 增加 typed context；从 `FetchPermissionCommand` 的保存 privilege 赋值，
  permission/send owner 持续有效期间保持，随真实 physical.request.fire 进入下游。
- adapter wrapper 只透传。非 registered 两个旧分支如显式开启 context，也从已有 privilege 寄存器输出，
  不改 FSM；不因接口添加顺手重写旧翻译路径。

### InstructionRequestBuffer

现有 Request Bundle 从 `{address, mask}` 扩为 `{address, mask, optional context}`。

- Queue 路径：context 在同一个 enq/deq payload、同一个写入与读出索引内。
- independentCapture 路径：同一次 capture 将完整 payload 写入同一个 `Mem(2, Request)` entry。
- empty-flow：address/mask/context 均用同一个 empty 选择条件，不从 saved 地址配 live privilege。
- 不改 occupancy ready、push/pop、pipe/flow、响应背压，容量仍 2，原默认 latency/II 不变。
- 在 context 模式加入 held offer 的完整 payload 稳定断言，断言只观察，不参与 ready/valid 控制。

### I-cache 消费者

context 模式下，demand 64B PMP checker 的 privilege 改为 `io.fetch.requestContext.privilege`。
地址仍为同一个 request 的 line base，mask/range/alignment 检查保持。
lineAllowed 在当前 offer 形成，实际 request.fire 才选择原 hit/fill/fallback FSM；held offer 保留同一上下文。
接受后的 fill 使用已保存的 line/状态，不重新从 live core privilege 授权。

精确 fallback 不扩大 word mask，故无需把 context 再透传到 TL bridge/ROM；它们只履行已授权字节范围。
response 不需要回送 privilege，原 FIFO/token/slot 仍负责完成归属。

`withRequestContext && prefetchEnabled` 在构造时拒绝。本次 Common A1 本就 prefetch=false。
旧非 context 的预取分支保持原限定，**不宣称其跨 trap 权限已被本次资格化**；未来若要开启必须给
prefetch candidate/outstanding owner 同样保存来源上下文，而不是用 demand 的当前 context 代替。

## 3. 无额外 cycle 与成本边界

| 边界 | 新增存储/逻辑 | 新增 latency | II/capacity 改动 |
|---|---|---:|---|
| S1 adapter→physical | 已有 owner privilege 接线 | 0 | 无 |
| A2 permission→physical | 同一 owner payload 加 2bit | 0 | 无 |
| request buffer | 两 entry 每项加 2bit；原 flow mux 多 2bit | 0 | 无 |
| I-cache line PMP | privilege 输入换成 owner 字段 | 0 | 无 |

PMP 检查并未移除，也未加 authorization bypass。零周期不等于 PPA 等价：新增 2bit 存储/布线与
原 flow mux 到 PMP 的输入路径仍需以后统一物理评估，不在本窄修复承诺 Fmax。

## 4. 精确文件 scope 与 ownership

frontend owner 拟修改：

1. 新 `interfaces/PhysicalFetchRequestContext.scala`：typed context。
2. `platform/memory/InstructionRom.scala`：只改 `InstructionPort` 可选字段/构造参数，不动 SynchronousFetch。
3. `platform/bus/InstructionRequestBuffer.scala`：原 payload 原子扩展，三个捕获/流通模式。
4. `mmu/RegisteredInstructionTranslationEngine.scala`：可选 physical port 参数与保存 privilege 输出。
5. `mmu/PipelinedAlignedInstructionTranslation.scala`：physical command context 与各 wrapper 同值透传。
6. `mmu/InstructionTranslationAdapter.scala`：显式开启参数及旧分支保存 privilege 输出。
7. `cache/InstructionLineCache.scala`：可选 owner-context demand 授权与无 context prefetch 的明确拒绝。

root/平台 owner 协调：

8. `platform/CommonA1CpuTile.scala`：单/双 owner 三模块同值开启；不再把 live core privilege 当 context 模式
   demand 的授权来源。未 buffered 分支直接连同 typed context，不独立采样。

验证文件：

- `A1FetchSupplyGsim.scala`：真实三控制 fixture 显式开启 context，旧 byte driver/oracle/service 不改。
- 新 `FetchRequestContextGsim.scala`、`FetchOwnerPermissionGsim.scala` 与独立 C++ driver/runner。
- `A2FetchConfigurationSpec.scala` 或独立新 spec：可选接口旧形状、真实接线及 context+prefetch 拒绝。
- 真实 CPU fixture/guest/host 不改，直接复用 A2 的三控制 18 case 基线。

不改 OooParams/FpgaNextConfig preset、后端、PMP 算法、ITLB/PTW、TL bridge、MachinePlatform 老平台或
宽包/预取拓扑。本次明确资格化 Common A1 demand 链，不把其它未接入 context 的平台顺带称为已修复。

## 5. 独立验证，先范围再性能

### 5.1 原子运输

新小 fixture 驱动真实 `InstructionRequestBuffer` 的 registered、flow、independentCapture 模式，
输入交替 S/U/M、不同 PA/mask，独立 accepted deque 核完整 payload、顺序和 exactly-once。
覆盖 empty bypass、full stall、同拍 pop/push、held downstream、旧 S owner 尚在队列时新 M owner 写入，
禁止新 context 覆盖旧地址。observer context/data 错配负例要求指定诊断与实际注入计数。

### 5.2 trap + 部分 PMP 区域 + 实际 TL Get 范围

核心 witness 使用真实 adapter→request buffer→I-cache→TL 链，slots=1/2 分别运行。
PMP 设为一个 64B RAM line 内仅指定对齐 8B（或 16B）在 S/U 可执行，边界外不可执行；配置不锁，
该窄区域不使 M 绕过 first-overlap 的 whole-cover 要求。发出并接受旧 S/U request，故意延迟它进入
I-cache，然后升 M，再释放请求；这是正向范围保持测试，旧 live 逻辑按上述蕴含也应通过。

为避免只用 host 更改 privilege 冒充执行了 trap，拟在此 fixture 使用实际 `MachineSystemUnit`：
只在所有 fetch owner 空时经其 CSR start/complete 配置 PMP/MPP/MEPC，通过 MRET 进入 S/U；
旧请求 pending 时给其合法 trap 输入，观察真实 trapReady 与 privilege 升 M。
host 在这里扮演已授权的 trap issuer，不声称覆盖整个 ROB 的异常选择；生产 safeTrap 不 drain 的条件已独立审计。
需要保持小配置时仅关闭这个独立 system-unit fixture 的 FPU，并明确不作为 CPU/PPA 性能模型。

输入阻塞阀仅在测试接线中原子门控 buffer→cache valid/ready，不能改变 payload 或 production 模块。
同时测 accepted buffer entry、empty-flow held offer、两个不同 privilege owner、后续合法 M demand。
独立字节/PMP oracle 在**首次公共请求**保存原始身份和允许范围，逐个检查实际 TL Get address/size：

- 旧 S/U demand 只能发许可 8B/4B Get，不能因 trap 发整 64B；数据正确仍不足以通过。
- 旧 M demand 在 live privilege 改变后仍绑定 M owner，合法 M demand 可以实际发 64B，防止保守禁用缓存。
- locked PMP 情况不能由 M 绕过；partial mask 不扩大字节；无请求的 fault-only owner 不产生 Get。
- 所有 response/route/source 完整 drain，未改变 PMP/SATP 配置期间必须有独立 drain 断言。

另加 owner=M、组件 live=S、整个 line 为未锁 X=0 区域的合法组件合同例，M owner 应真实发 64B。
强负例在首次 cache offer 前将 context 接错为 live S，实际 fallback 会被独立 oracle 以
“owner context not used for legal M line authorization”拒绝，而不是认任意断言/非零退出。
这不是生产 MRET 可达漏洞；不篡改生产 RTL，不让 oracle 学习错误 DUT 的范围。

### 5.3 等周期门槛

一次 source freeze 与统一增量 compile 后，仅必要短 GSIM：

- 原九场景三控制逐字段等于 A2 留存 receipt，包括 work/drain、Get/beat/extent、fault/tval/hash。
- 相同 retained-cache warm ROI 三控制逐字段等于 A2，不能接受权限修复通过降速或额外缓存命中实现。
- 仅重建主要 dual-slot 完整 CommonA1 CPU，六 guest/两负例全字段等于 A2 dual receipt，含 work/drain与尾部流量；
  不重复构建两个单 owner CPU。
- 新范围 witness 不作速度比较；S/U→M正测不应声称旧实现有越权差异，独立验证 M 合法整线仍用64B。

旧 evidence 只读留存，不重跑 baseline、不修改 host 语义/服务律来适配 DUT。
不运行 Verilator、Linux、全回归或即时 STA。发现失败先定位 source/fixture/oracle 边界，保留失败记录再重冻。
