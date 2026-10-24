# Common A1 PMP packet→line 组合证明与 P1 合同范围

2026-10-24。此文更正 A2 后续审计曾提出的 live-privilege 越权扩大推断。
**当前规则下该反例不可达；P1 是显式 owner 合同加固，不是修复已复现的此项安全漏洞。**
本证明不扩大已有动态验收，不赋予板级、CDC、完整 ISA 或 300MHz/PPA 资格。

## 1. 已核前提

1. Common 的 adapter packet checker 与 I-cache line checker 使用同一份、同优先级的 16 项 PMP 配置。
2. PMP/SATP 写通过原 fetchQuiescent 屏障，不在旧 physical owner 仍活跃时改变配置；自动 trap 可以升 privilege，
   但不会自行改变这份 PMP 配置。这里只需要 PMP 配置稳定，不能把 privilege 稳定假设偷渡进来。
3. 进入 lineAllowed 的 physical packet 是 8B 对齐、完整 mask=3，两个 4B word 已获旧 S/U 的 execute 许可。
   partial/zero mask 或非对齐请求不进入 linefill；请求范围完全包含于待扩大的 64B line。
4. 两级 checker 都使用 first-overlap、whole-range-covers、execute/X 规则。当前
   `src/main/scala/core/ooo/mmu/PhysicalMemoryProtection.scala` 中，M/unlocked 只绕过 RWX，
   **不绕过 whole-range covers**，也不跳过较早但只覆盖部分范围的 entry。

前三项是当前 Common demand 集成的限定，不声称其它 standalone caller 或未开启 context 的预取拓扑具备它们。

## 2. 命题与证明

令 P 是上述已许可 packet，L 是包含 P 的 aligned 64B line，C 是不变的 PMP 配置。
命题为：S/U 允许 P，且 M 允许 L，则同一个 S/U 也允许 L。

- 若没有任何 active entry 与 L 交叠，则没有 entry 与 P 交叠。S/U 无匹配默认拒绝，与 P 已许可矛盾。
- 因而存在与 L 交叠的第一项 E。M 允许 L 仍要求 E 完整覆盖 L；否则即使 E 未锁，covers 失败也拒绝。
- E 完整覆盖 L，所以也覆盖 P；所有比 E 更早的项都不与 L 交叠，因 P 是 L 的子范围，也不与 P 交叠。
  故 E 同时是 P 的首匹配项。
- S/U 对 P 的 execute 许可要求 E.X 为真，不受 E.L 是否锁定影响。
- E 全覆盖 L 且 E.X 为真，S/U 对 L 同样许可。证毕。

packet 的两个 word 分别检查不破坏结论：当 M 的 line 许可前提成立时，E 同时覆盖并首先匹配两个 word。
如果 packet 的两个 word 恰好位于不同 PMP 区域，line 的 first-overlap 项不能全覆盖 L，M 也不能批准整线。

因此“某 line 内只有窄 8B TOR 可执行，旧 S/U packet 延迟后切 live M，便会发整 64B”不是当前实现的
合法反例。增加更多较晚 PMP entries 不能修补 first-overlap 项的 covers 失败。不能通过绕过 checker、
改变 oracle 或接受任意非零退出，制造一个所谓重现漏洞的负控。

## 3. P1 的实际价值和验证

P1 给 physical request 增加可选 typed owner privilege，与 PA/mask 同一请求、同一 buffer entry 和同一
empty-flow 选择传递，I-cache 明确按 owner 进行整线许可，不再依赖上述跨模块组合蕴含维持语义。
默认未开启的旧接口保持原形状；Common 单/双 owner 均开启；context 模式拒绝尚未携带 owner 的预取。
这减少后续独立重构 checker/transport 时的隐含前提，但不表示当前 A2 有已证实的扩大漏洞。

独立短检查包括：

- raw PMP 配置的 16-entry、逐字节 first-overlap/whole-cover 软件模型，检查上述蕴含并统计非空前提命中。
  有序重叠、locked/unlocked、匹配/无匹配与 packet/line 边界都要出现；不由 DUT 输出生成预期。
- 真正 MSU CSR/MRET/trap 产生 S/U→M，经过实际 adapter/buffer/I-cache 观察 TL Get 范围。
  窄 TOR 正测仍必须只访问允许的 4/8B，但明示旧 live 逻辑在这些前提下也不越界。
- buffer 的 registered/flow/independentCapture 三模式，独立 accepted owner deque 核 PA/mask/privilege
  原子性、held 稳定、满队列、empty-flow 和同拍周转。
- I-cache 合法组件合同用例：owner=M、live=S，完整 line 被未锁、X=0 的同一 PMP entry 覆盖。
  M owner 仍应使用合法 64B linefill，防止靠全局保守降为 S 禁用 M cacheability。
  这是接口合同输入，不宣称生产 MRET 可在未 drain 时造成这一状态。
- 该组件用例故意把 context 接错为 live S，实际只能 fallback；独立 oracle 必须拒绝缺失的合法 M
  整线行为。负控验证 owner 字段确实被消费，不把它称为扩大越权重现。

这些新检查已由统一冻结后的短验收通过，见
[a1-fetch-owner-context-results.md](a1-fetch-owner-context-results.md)。其中 raw property 是16384个软件样本、
7168个非空前提；两个 slot 进程重复同seed，不算双倍独立或DUT样本。源码证明本身仍不冒充 GSIM PASS。

## 4. 周期与范围验收边界

无新增功能寄存边沿、owner 或扩大需求范围。原三个 frontend profile 的九场景与 warm ROI 应逐字段
等于 A2 留存数据；只重建主要 dual-slot 实际 CommonA1 CPU 的六个 guest 和两项观察负例，与 A2 dual 比较。
不为本次接口加固重复构建单 owner CPU。新 MSU 小 fixture 不作 CPU 性能模型；正常周期保持也不证明 PPA 不变。
