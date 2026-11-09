# A1 兼容优化整合包（2026-11-08）

这是源码整合和本地 Vivado 时序评估输入，不是“所有实验无条件合并”，也不是已通过综合/布局布线的板级发布。

## 源码与器件

- 基于 Surplars/Valence 的 `dev/hypervisor-aia-gsim-20261107`，精确基线 `e437ba20960a7123ba60e7a91f3dbeec86117b8c`。
- 在独立工作树 `integration/all-compatible-20261108` 整合，不覆盖原工作树，不修改远端分支。
- 本地目标为仓库现有板级脚本一致指定的 `xczu15eg-ffvb1156-2-i`。启动时再由本机 Vivado `get_parts` 校验，缺少器件支持直接停止。
- 主体是 A1 CPU、真实 CPU/fabric CDC、真实共享 fabric/Home/DDR AXI 管理器和 DMA 的 OOC 组合；未包含 MIG、板级管脚、电气约束、PHY/厂商时钟/debug shell。

## 主推实验组合

`efficiency4-candidate` 使用现有完整 `FullR1M3EfficiencyRefactor4` 依赖链，不将不同实验的开关直接取并集。保留 ROB16、PRF48、两发射、LSU4、RV64GC、PMP/MMU 和原本权限/顺序/回压保护。

包含现有双完成、独立分支、四 owner 内存并行、checked-flow、准备 store、elastic load proof、guarded PMP、split tag、third-rank/return flow、ordered/advisory ownership、certified ingress、fetch horizon 和效率重构1–4。CPU/fabric 传输仍为原生有序接口；共享 DDR 四槽/两写槽、Home 两 Acquire/两 writeback owner不变。

新增或显式接入：

1. W11：仅立即数 RAM 改为 signed32 存储，读取重新符号扩展为64位；仅显式实验开启。普通任意64位 API 默认保留。接受写入时断言 canonical signed32；所有 owner/read-enable 保护保留，没有 W12 裁剪。ROB16 逻辑数据减少512位，不等于已测 LUT 节省。
2. W14：16项间接目标表的 banked 实现通过配置实际接入当前整核。需要两 lookup/commit、RVC、registered training，非法组合拒绝。新增表相对无表有资源成本；不能直接引用历史 ROB32/PRF64 的性能数字。
3. 总线/Home/DMA：采用已有 `probe-acquire` 显式模式，含 completion flow、disjoint DMA-read/Acquire overlap、dirty-Probe/older-Acquire overlap、line DMA及threshold rewrite。`singleReadWait` 保持关闭。
4. PMP/FP 及其他源码级修复保留最新分支内容，是否在某组合被实例化以 `ooc-identity.json` 和实际 RTL 为准。

`efficiency4-baseline` 保持同一 CPU/fabric、相同16项间接表，使用寄存器表、64位立即数；它用于隔离 W11/W14 的结构影响，不是“所有优化前”的旧基线。保守 `candidate`/`baseline` 模式使用 Selected LSU2；`unselected` 只关闭显式总线模式，仍保留16项表。

取指 horizon 只允许现有 benchmark 使用的物理 RAM 范围 `[0x80200000,0x80220000)`，不是整个DDR的无条件推测权限。

## 明确未混合的实验

- W12/W18：旧专用后端的 owner/rank guard 裁剪没有当前整核的完整生命周期证明。W18还留有53条有限路径层数退化，不能仅看面积数字移植。
- W15/W16：历史比较器 graft，存在 LUT/MUX 或路径回退，没有足够收益支持本批孤立启用。
- W17：未找到可独立确认的维护实现，不声称已集成。W19已拒绝，保持排除。
- resource74：posted/frozen/pending store、tagged returns、旧physical ingress 属另一条接口/所有权路线，与 CommonA1 有序无tag返回和 efficiency4 的约束直接冲突，不能拼接。其源码/文档保留在源码树，不冒称合并。
- efficiency5、context-prefetch、MUL-load capture 是后续或分叉实验，非自动相加；既有证据没有确立其相对 efficiency4 的普遍吞吐收益。
- I1 是不同的顺序核；H/guest-FP采用另一套显式guest翻译和实验入口，不能作为此host A1的优化开关。V不是已闭合的整核向量执行路径。这些源代码保留，不在本OOC设计中宣称启用。

## 验证界限

本次精确执行结果见 `VALIDATION.json` 和附带日志。组件正确性、整核连接的 elaboration/lowering、真实整核运行、板级实现是不同层级。

未运行用户本机 Vivado；未运行云端 Vivado、Yosys行为仿真或 Verilator。没有本批 LUT/Fmax、布线WNS/TNS、物理CDC或板卡运行通过结论。历史测试记录不得视作该新 CPU+fabric 组合已运行。

## 本地使用

解压后进入某个 `rtl/<mode>` 子目录，执行 `python run_local.py --verify-only`，再执行 `python run_local.py --out <新的输出目录>`。默认 CPU10ns、fabric4ns，可显式传 `--cpu-period` / `--fabric-period`，改变目标不代表已达频率。

每次只跑一轮综合→优化→布局→物理优化→布线，保存三个阶段 DCP、资源、setup/hold、未约束路径、clock interaction、DRC、CDC和route status。没有自动重试、策略搜索或bitstream生成。`COMPLETED.txt` 只说明命令走完，必须看报告是否违反时序/DRC。

跨域路径未通过宽泛false-path或clock-group假切断；外部端口时序未伪造为板级约束。因此OOC WNS不能当整板Fmax，跨域、边界及恢复/移除必须分别评审。后续接MIG和真实板级shell仍须通过原有严格身份和接口准入，未修改这些guard。
