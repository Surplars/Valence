# 2026-10-14：时序候选 73 与功能、性能证据边界

本轮选择显式 **73 项参数候选**进入后续综合与时序验证：保留 resident memory payload reuse、B1 held-ALU forwarding、registered load-result readiness 与 raw MAC handoff；`frozenStoreCheckedFlow=false`。冻结 store 的 checked-flow 机制保留为默认关闭实验，不进入本轮物理候选。这里的 71/73/74 指完整有序选项向量长度，不是硬件版本或吞吐率。

采用 `fpga/next/timing-ready73-profile.json` 与 `fpga/next/board_timing_ready73.py` 的显式入口。完整构造产品为 177 个 core 字段、94 个 profile 字段；历史 71 项候选的 175/92 记录保留为原始证据，不能直接当作新产品。不要把历史 `board_combined_cpu.py` 的 71 项入口用于本轮物理导出。

## 固定 CPU COPY 的回退与恢复

原 guest、DDR 服务、AXI 相位规则及独立 oracle 均未改变。每个模式复制有效载荷 128 KiB；inclusive cycles 包含原 ROI 和 clean/flush 尾部。下表速率按配置中的 100 MHz 换算，**不是板上实测带宽或 100 MHz 时序签核**。

| 配置 | Bare inclusive cycles | Sv39 inclusive cycles | Bare MiB/s | Sv39 MiB/s |
|---|---:|---:|---:|---:|
| 保留的 71 项基线 | 179,571 | 191,618 | 69.610349 | 65.233955 |
| 74 项：load-result-ready、frozen checked-flow、raw MAC 均开 | 179,571 | 197,361 | 69.610349 | 63.335715 |
| 本轮 73 项：仅从 74 关闭 frozen checked-flow | 179,571 | 191,618 | 69.610349 | 65.233955 |

74 的 Sv39 增加 5,743 cycles（+2.997%）；该负结果保留。随后同一生产源码与参数产品只关闭 frozen checked-flow，73 的 Bare/Sv39 **stdout、原始 AXI trace、原始 supply trace 均逐字节恢复到 71**，原七项 COPY 负控均仍拒绝。这个单变量结果支持本轮关闭该实验；不证明新的 workload 普遍提速，也不应把具体缓存/预取仲裁的全部变化归结为某个未直接观测的原因。

73 已进一步完成本轮必要 CPU 门：每模式原 105-field COPY 与七项原负控、同一模型对象的 NEMU hot/compressed 与 PMP short/word 及三项负控、一个实际 held-ALU capture 见证及两项到达的 value/owner 控制，共 19 次执行（7 个正例、12 个预期拒绝）。七份 NEMU/PMP 日志也逐字节等于原参考。74 原结果与 73 新结果分别保留，不能把前者重标为后者。

实际 held 见证仍为 P0 14:49 → C1 15:50，capture edge 780、C1 acceptance edge 781；49 条退休指令、1,558 cycles，架构 hash 6359470064314231515。更强 rollback/reuse/mixed 见证仍 **NOT_REACHED**，完整 held 集成资格仍 **INCOMPLETE**。这不是全 ISA/Linux 验证。

## 正确性覆盖随源码保留

- **Load-ready P1，实际组件：** 4 个 OFF/ON 正例、18 个到达预期 checker 的负控。覆盖真实 LSU 结果写入、完整高位 token、取消与延迟回复、0–4 holder、替换、两源 readiness、PRF/write/wake 交接和严格 reserve 优先级。该协议 sink 不是 ROB 接受证明。
- **Load-ready P2，实际 IntegerBackend/ROB：** 每侧 16 个固定场景、7 个到达预期独立拒绝的观测负控。覆盖未选中 holder 消费、完整 token/源 lineage、实际 ROB/PRF/wake 交接、分支恢复、旧回复责任与名称复用、B1/load 混合及 ALU II1。测试中的事件绑定内存服务是受控组件场景，不是 CPU 吞吐基准。
- **P2 未覆盖的更强同时性：** 同边沿“选中 load drain + 同槽替换 + 实际使用源 capture”计数仍为 0。独立的 drain/replacement、selected capture 和实际 PRF 交接已到达；不能合并宣称更强场景通过。
- **Frozen checked-flow，实际 adapter：** OFF/ON × 两种 head mux 共 4 个正例、80 个到达预期拒绝的负控。覆盖 direct/spill 互斥、满 FIFO/背压、完整 token/epoch/VA/PA/handle、最终 PMP/精确 fault、registered certificate 与真实回复。隔离测试中 acceptance→checked 从 2 降到 1 cycle，不替代上面的 CPU 负结果。

P1 的成功 store 初始非异常 cause 字段曾暴露 host 预期阶段错误；修正仅针对原 LSU 初始写入的 cause=5，完整元数据比较保留，并增加 5→7 损坏负控。Frozen 隔离 hit 测试的周期性 READY 曾使 ON 落到另一服务相位；只将双方隔离 hit 服务改为 always-ready，延迟/背压场景保留。两处原失败证据均保留，生产机制没有为迎合测试而修改。

测试 fixture 与独立 C++ host 位于 `src/test/scala/ooo` 和 `simulator/gsim/harness`，见[重跑说明](timing-closure-focused-tests.md)。导入本轮 177 字段树时，仅 P2 配置测试的历史 176 字段断言需作显式 schema 适配；此适配不冒充新的动态验证。

## 时序、资源与板级状态

源代码、FIR/native 声明分析显示 load-ready 与 frozen-flow 的已测 OFF/ON 对照没有增加生产状态容量或 PRF 端口。registered readiness 移开了原 holder 比较到 rank 的一段逻辑，但 holder 数据选择和 completion→credit→payload CE 路径仍在。frozen-flow 会改变 checked CE/选择控制。上述结果不是映射 LUT/FF、布线扇出或 Fmax 测量。

**本轮 73 的综合、布局布线、setup/hold、CDC/RDC、ROM INIT、板上运行与 PHY 结果仍待物理流程验证。** CPU GSIM 不实现 raw MAC 物理媒体/独立时钟；raw=true 的构造器核验不能替代 MAC 时钟交接动态证明或 CDC 签核。不要把更早候选的物理报告继承到本轮源码。

原始结果内容标识（SHA-256，用于区分证据；不作为新的重跑声明）：

| 证据 | SHA-256 |
|---|---|
| P1 bounded component qualification | `d785303cc2fb1851c886701a5b7351c0f3ac8c8d7d3855d9f15905cba74de504` |
| P2 bounded backend qualification | `4e96460f50dbe02af1d682a662f0961f06f170534b0b66b220d2608986936d06` |
| Frozen adapter qualification | `efadbd95646b03f6dde5dadecb516b84bd9f81d41629992595d409d7338bbcce` |
| 74 original-law CPU qualification | `a74b3fbe07360d65afab93e07aa206910aba17dc68ef53f904af99360d3d8686` |
| 73 bounded COPY/NEMU/PMP/actual-held CPU qualification | `11a34543fa5bce2cde9501cd403cf32b9256956df81b99eacd9a4de38dc448d0` |
| 73 original single-variable COPY diagnostic | `39d9e5faff14863671fa7c5be09b6c20450d1ec7dfdaac03acc3815911be42f9` |
