# P1 physical fetch owner 合同：范围证据与等周期验收

2026-10-24。**P1 显式 owner context 已通过必要短测，原 A2 三个前端控制的 1710 个 cold/warm 字段
精确保持，主要 dual-slot 实际 CPU 的六 case、150 个字段及有效配置也精确保持。**
这是一项模块合同/防御性加固，不是已复现 privilege 扩大漏洞的修复，也不是新的吞吐提速。
未增加本批正常场景的周期或流量，不等于已经证明零面积/Fmax 成本。

## 1. 原风险推断已更正

A2 后续审计最初由 I-cache 使用 live privilege 推断，旧 S/U 的许可 8B 请求可能在 trap 升 M 后越权
扩大为 64B。这遗漏了当前 PMP 的 first-overlap whole-range-covers 规则，已撤回；公开更正文档
checkpoint 为 `502c7f3`，没有改写原 A2 receipt。

同 16 项、配置稳定、aligned/full-mask packet 已获 S/U execute 许可时，M 若批准包含它的整 line，
首匹配项必须全覆盖 line；它也是 packet 首匹配项，因此 X 必真，S/U 也批准整 line。
M/unlocked 仅绕过 RWX，不绕过 covers。partial/zero mask 又不走 linefill。
完整前提、证明与适用范围见 [a1-fetch-pmp-line-implication.md](a1-fetch-pmp-line-implication.md)。

所以没有接受“窄 TOR→切 live M→必须越权发64B”的假负例，也没有修改 oracle 或旁路 checker 来制造漏洞。
P1 改为让请求显式携带自身身份，避免未来拆分模块必须依赖上述跨模块隐含蕴含。

## 2. 实际生产改变

- `InstructionPort` 新增默认关闭的可选 typed `PhysicalFetchRequestContext.privilege`（2bit），
  共用原 request valid/ready，无独立握手；旧 generic 接口形状不变。
- S1 engine 输出已有保存 privilege；A2 permission owner 将 privilege 与 PA/mask 一起进入
  `FetchPhysicalCommand`，不从下一个 command 或 live CSR 重造。
- `InstructionRequestBuffer` 的原 Request/Mem/Queue payload 同时保存 PA/mask/context；
  empty-flow 三字段使用同一个选择条件，容量/ready/response/既有寄存边沿不变。
- I-cache context 模式用 owner privilege 做 demand 64B PMP；held payload 加观察断言。
  context+prefetch 在构造时明确拒绝，不能拿当前 demand 身份冒充预取 owner。
- Common A1 单/双 owner、buffered/direct 两条接线路径都保留 context；未开启 context 的其它平台
  不宣称得到本次资格化。PMP/SATP 写原 drain 不变，没有复制 PMP 配置或新增 epoch。

完整 scope 与 latency/II/capacity 合同见
[a1-fetch-owner-privilege-proposal.md](a1-fetch-owner-privilege-proposal.md)。
无新增功能 pipeline stage、owner、prefetch、packet 宽度或 demand 范围。新增 context 存储/布线/选择仍有未测 PPA 成本。

## 3. 独立 owner 与权限证据

### 3.1 Request buffer 三种实现

registered、flow、independentCapture 各用独立 accepted deque 核实 256 个请求的 PA/mask/privilege
与返回守恒，每模式 U=86、S=85、M=85，最大 queued=2。输入重复相同 PA/mask 并交替 privilege，
避免只靠地址偶合掩盖上下文串线。

| 真实 buffer 模式 | accepted/forwarded/completed | held | context turnover | empty bypass | registered delay |
|---|---|---:|---:|---:|---:|
| registered | 256/256/256 | 115 | 220 | 0 | 16 |
| flow | 256/256/256 | 110 | 115 | 110 | 0 |
| independentCapture | 256/256/256 | 110 | 115 | 110 | 0 |

满队列不借下游当拍 credit、同拍 pop/push、held、响应 fault/backpressure/即时返回均经过独立检查。
三个 context 观察负例各要求明确 marker、独立 mismatch 文本与 host 退出 1，不把任意失败当成功。

### 3.2 PMP 蕴含 property 的准确口径

独立 raw 16-entry 软件模型逐字节处理 OFF/TOR/NA4/NAPOT、first-overlap、whole covers、X 与 locked M。
共 **16384 个不同 trial/offset/privilege 样本**，7168 次非空命题前提（U/S 各3584），
priority overlap=12784、locked first=3072、no match=2048、partial first=6144。

该检查在两个 slot 模型进程中重复相同确定性 seed，不算两倍独立样本，更不是 16384 个 DUT PMP case。
它验证独立软件命题；源码证明解释为何一般前提成立。真正硬件范围检查是下一节的小链路。

### 3.3 实际 MSU→adapter→buffer→I-cache→TL

fixture 用实际 MachineSystemUnit CSR/MRET/trap 产生 privilege，SATP Bare、VM-capable adapter/PMP16
保留，I-cache 采用 Selected 的 banked 模式，但容量缩为四行、RAM test aperture 64KiB；该小 fixture
关闭未使用的 FPU 及其未实例化 backend 的 head-sharing 配置，不作为 CPU/PPA 模型。
host 扮演合法 trap issuer，未声称覆盖整个 ROB 的异常选择。

PMP 只在 owner 全空时配置。旧 S/U 已接受请求在 buffer 或真实 cache held offer 时经历 trap 升 M，
独立 oracle 保存首次请求身份，核 actual TL A 的 address/size/mask 与 byte range，而非只核返回数据。
旧 S/U 的窄 TOR 正测也符合未修改 live 逻辑的上述安全蕴含，不把它称为重现并修复越权。

| 模型 | accepted/returned | 4B /8B /64B Get | trap old-held | trap cache-held | S/M mixed queue | max owners |
|---|---|---|---:|---:|---:|---:|
| slots=1 | 14/14 | 2/3/7 | 4 | 0 | 0 | 1 |
| slots=2 | 19/19 | 2/6/9 | 6 | 1 | 1 | 2 |

mask1/2 各实际产生4B；旧 S/U 8B、locked M 8B、合法 M 64B 均有 witness。
每模型 `fault_only=2` 包括一个 mask=0 terminal owner 和一个全 PMP deny，不是两个架构异常。
public response held=49/53、A held=8/9；**D held=0，不宣称该小链路覆盖 D 背压**。
两模型均完整检查 source lifetime、beat 数、返回 owner、精确数据/fault 与最终 drain。

为直接证明 I-cache 消费 owner context，另用合法组件输入 owner=M/cache-live=S、未锁 X=0 整 line，
正确 context 必须实际发64B，防止靠一律降为 S 禁用 M cacheability。
负例在首次 cache offer 前把 context 故意接错成 live S；实际 fallback8B 触发独立诊断
`owner context not used for legal M line authorization` 和 `INJECT cache context`。
这是组件合同接线负控，不是未 drain MRET 的生产可达漏洞，也没有把 expected 值改成 DUT 输出。

## 4. 端到端等周期，而非局部声明

原 A2 byte driver/oracle/service 与 warm host 不变，三个重新生成的 frontend profile 分别比较其原 A2
receipt：九场景全部字段和六行 warm/warmup 全部字段合计 **1710 项精确相等**。
包括 work/drain 周期、Get/beat/extent、request counts、fault 计数、instruction hash 和供给直方图；
精确 tval 仍由未改 byte oracle 检查，不是 receipt 的单独输出 metric 字段。

主要供给数值保持：

- original/aligned-control：ROM32 580、RAM32 332；warm Bare171、Sv39227。
- two-owner：ROM32 517、RAM32 299；warm Bare142、Sv39170。
- A2 已披露的尾部/旧路径额外请求仍原样存在，P1 不通过改流量制造“等周期”。

只重新构建一个主要 dual-slot 的实际 CommonA1CpuTile 模型，复用不变 raw guests/host/service，
六 case ×25 字段 **150 项及 effectiveParameters 精确等于 A2 dual**；两个 CPU 观察负例也通过。
没有为本次合同加固重复构建 single-owner CPU。

| guest / 放置 | P1=A2 work cycles | P1=A2 drain cycles |
|---|---:|---:|
| independent ALU / ROM | 976 | 10 |
| independent ALU / RAM | 1027 | 7 |
| dependent chain / ROM | 974 | 8 |
| dependent chain / RAM | 1027 | 7 |
| branches / ROM | 360 | 10 |
| branches / RAM | 375 | 7 |

CPU 保持真实32KiB L1I/L1D、ROB16/PRF48、VM/PMP/FPU 配置。测试仅 Bare/M 整数/branch，RAM work
含固定两条 bootstrap。精确 cycle/ROI/drain/inspection 合同仍见
[a1-common-cpu-retirement.md](a1-common-cpu-retirement.md)。

## 5. 冻结、失败与复用记录

生产/前端逻辑自首次 P1 freeze 后没有修补。新范围 fixture 出现两次构建错误，保留原失败而不冒称首轮全过：

1. r1：`copy(fpEnabled=false)` 使用 derived def 而非 constructor 参数，Scala test 编译失败，未运行模型。
2. r2：改为真实 FP constructor 字段后编译与8 specs通过，3 buffer模型及负例通过；范围 fixture
   elaboration 触发 Selected `shareProtectedHeadPayload ⇒ fpEnabled`，没有生成范围模型。
3. r3：仅小 fixture 显式关闭其未实例化 backend 的 head-sharing 选项。编译/8 specs通过；
   保留复用源/模型未变的 r2 三个 buffer，不重复生成/运行。其余范围、前端与唯一 CPU 均由 r3 验收。

最终15项源清单：`/tmp/p1-owned-sha256.txt`，SHA256
`4afc938b376506fecb6488bc49f26508085f94bfbdb3dd9e69cb748b79226459`。
最终范围 fixture SHA256 为 `105d9d30b9f46086cb699919387928e6d6e3afc1da31f94dfb59f82462dba835`。
持久证据由以下 receipt 与冻结 source tar 绑定，不依赖临时清单长期存在：

- leaf：`build/gsim/p1-fetch-owner-context-20261024-r3/receipt.json`，SHA256
  `fbe442a722424f95ecb162df9fd305b32bb82ad3868f18770390569a9228e28b`。
- 外层：`build/p1-20261024-r3/validation-receipt.json`，SHA256
  `d63d71668e37a2155a1a0231dd68bdafbb0896d2bbc9ff6c4b2c7484b1b50ac2`，绑定 r3 结果与 r2 buffer 复用；
  r1/r2 失败记录由最终总 checkpoint 分别绑定，不将 r3 外层误称为包含全部历史失败。
- 真实 `full-candidate` CommonA1CpuTile 导出174个SV文件通过，非测试harness：
  `build/p1-20261024-r3/tile-export-receipt.json`，SHA256
  `c0ee917d916a64fc8f6d581d7061d018db36f534294e4a7b5710c8d2697c3061`。
  配置绑定于刚执行的dual-slot CPU参数；只证明elaboration/lowering，不是综合、STA或上板通过。
- 负例：3 buffer +2 cache-context +4既有前端观察 +2 CPU观察，合计11，均精确诊断通过。

重现入口 `simulator/gsim/fetch_owner_context.py --gsim <pinned> --tag <fresh> --baseline <A2-front-receipt>
--cpu-baseline <A2-CPU-receipt>`；缺省省略最后参数只资格化前端/小合同模型，不自动宣称 CPU 通过。
本次无 Verilator、完整 GSIM/Linux、综合、STA、CDC 或板级测试。最终物理频率/资源/功耗仍未验证。
