# C 扩展 IPC 修复与全扩展时序评估（2026-11-04）

C 固定 IM 镜像的 IPC 回退已消除；真实压缩 CoreMark 的 IPC 为 0.569764 / 0.452636，较原全扩展版本提升 49.84% / 38.86%。r14/r15 的功能门禁通过，但 routed 时序回退，保留 r12 为本轮最佳物理基线：setup −0.111ns、hold +0.010ns，按当前布线估算约 290.3MHz。**300MHz 尚未收敛；当前没有进行中的 Vivado 实现。** 最新 H/V 接入单独验证，不能继承该 CPU 物理结论。

## 基准与测量范围

历史扩展评估提交为 `a9986aac35c5263a854278ee1dc7330cd8cdd813`，其原 IM 硬件基准为最佳 `ccc68f9c79db3cd428a55f381cde8e341ce81cd1`。历史最佳名为 R5，本文 r5/r6/r7/r8 是本轮修复批次。

配置为 RV64 顺序单发射、fpga8、timing-cuts、DSP tiled MDU、BTB128、32KiB I-cache + 32KiB D-cache、64B 行。全扩展启用 A/C/F/D 与既有 FPGA 浮点资源配置。范围包括 CPU、私有缓存和完整端口捕获寄存器；未加入 monitor、SoC AXI/TileLink 互连或外设。A 沿用单 hart、独占运行时写者契约。

开发与 GSIM 根为 `/home/openion/Valence-InOrder`，Vivado 根为 `E:/VM/Share/Valence-rtl/Valence-InOrder`。r14 的源码、RTL 与证明分别由 `build/i1-c-fix-20261104-r14/source-at-model`、`candidate.patch`、两端相同的 `implementation-inputs.json` 绑定。

## RTL 修改与根因更正

- BTB 仅分配控制流指令，普通指令的 C 长度使用独立一位提示表，避免普通指令挤掉分支目标与方向计数器。索引、完整 PC 标签和 BTB 容量保留。
- 顺序长度错误在真实取指响应时修正，保留本条指令和较老流水工作，阻止尚未对外提供的错误下一请求。已对外提供并受反压的请求保持地址并按原 owner 排空。长度修正的停发候选独立于后端 flush，修正提交遵守 flush、FENCE.I、quiesce、IRQ 的优先级。
- C 对齐器允许旧响应完成与新请求同拍换手、复用已授权的新返回字；停顿时使用原响应寄存器。单 owner、fetchSpan、上下文失效和跨字错误契约保持。连续 32 条指令实测 33 周期、16 次字访问。
- 预测 PC 使用 bank 局部修正；ADDR 已知年轻 EX 属于错路径时提前取消纯数值计算，架构重定向仍随真实 ADDR 转移发生。
- FPGA cache tag/data/presence 使用本地可用端口预读，排除回填与延迟写冲突；RF/FPR 提前准备 ID 读值，RR 持有和 FP 串行准入保持操作数归属。
- 普通 cache 使用五个局部状态更新方程，burst 的 beat/failed 在非 receive 相位初始化，解除晚请求接纳对无关状态的共享使能依赖。fillKilled 保留原 owner 与 sticky invalidation 语义。
- FPGA offerPc 已保存正常预测或修正后的候选，因此 desiredPc 仅保存 held 请求等待期间的重定向目标。正常恢复保留 offerPc，killed 请求接受时准备保存的重定向，flush 优先；外部停止释放时恢复 architecturalNextPc。
- r8 在长度不匹配时，用寄存的 `!pendingShort` 提前选择修正的 +2/+4 PC。所有使用者都受 mismatch/repair 有效条件保护，此时真实长度必与旧提示相反；返回数据仍决定是否修正。该修改避免晚到长度同时控制宽修正数据和修正资格。

旧报告 `docs/i1-extensions-20261104.md` 曾把固定 IM 镜像回退归因于半字索引粒度，需更正：原基准已经折叠 bit1 并在 tag 保留 bit1，本轮未改变 index/tag 函数。旧 `allocate = selected && (controlFlow || withC)` 才使普通指令污染 BTB。独立长度表接入后、取指周转尚未修复时，固定镜像预测正确数已从 50958 恢复到 52966。后续收益来自 IF 长度修正与对齐器换手。旧报告测量与原始哈希保持不变。

r9 另将 cache 请求载荷和初始化元数据的准备改到本地空闲/旧响应完成时，实际接纳仍独立建立 owner。r10 在 RR 转移前先按年龄确定最近生产者，再映射到转移后的位置；新来源的 fallback 由当前匹配存在性决定，保留来源的 fallback 使用与原 advance OR 完全等价的表达式。两项均不增加流水级、寄存器或周期。r10 新跑三档 cached CPU、裸 C、quiesce/default trap、数值与 frontend/length 恢复及 CoreMark，指标逐项等于 r9；raw cache 依赖未变，复用 r9 十档证明。证据在对应 `build/i1-c-fix-20261104-r10/`，frontend receipt 实际位于 `frontend-recovery/attempt-1/receipt.json`。

## 同一未压缩镜像

官方 CoreMark 源码固定为 `1f483d5b8316753a742cbf5590caf5bd0a4e4777`，GCC 13.2、O3、LP64、2000B、1 iteration。IM 镜像 SHA256 为 `bc0bc1c5b5fdd7b4960b6e472d0a5d7aaf75eca748fdf7cd669904d1b2aba43b`。L1/L12 是相同双 burst 口轮询服务的首拍延迟 1/12 周期，后续每周期一拍；ROI 均退休 345520 条，全程序 367146 条。这是短程序评估，不是正式 CoreMark 分数。

| 硬件 | 原 ROI 周期 L1 / L12 | 当前 ROI 周期 L1 / L12 | 原 IPC L1 / L12 | 当前 IPC L1 / L12 |
|---|---:|---:|---:|---:|
| RV64IM | 578492 / 735792 | 578492 / 735792 | 0.597277 / 0.469589 | 0.597277 / 0.469589 |
| RV64IM+C | 672120 / 829415 | 578419 / 735718 | 0.514075 / 0.416583 | 0.597352 / 0.469636 |
| RV64IM+A+C+F/D | 672120 / 829415 | 578419 / 735718 | 0.514075 / 0.416583 | 0.597352 / 0.469636 |

同镜像开启 C 的 IPC 回退已消除，相对原 C/full 提升 16.20% / 12.74%。纯 IM 的架构轨迹、ROI 周期、IPC 和预测保持历史最佳；不声称所有辅助计数相同，MDU stall 计数曾从 28603/28603 变为 28630/28729。r8 纯 IM 通过新 FIR 与 22 个 SV 文件逐字节等于已验证 r7 的证明复用，没有重复运行 GSIM。

此整数镜像不执行原子或浮点指令；扩展本身由专门集成向量验证。

## 同一真实压缩镜像

相同源码和校验端口以 `rv64imc_zicsr_zifencei` / LP64 / O3 编译。C 镜像 SHA256 为 `20b72cf30c75c4b229b49afdcd49f20f74b92bd7d32f409afaee2e4943ca8eea`，12368B，较 IM 的 16368B 减少 24.44%。下表前后使用完全相同的 C 镜像；它与 IM 镜像代码布局不同。

| 硬件 | 原 ROI 周期 L1 / L12 | 当前 ROI 周期 L1 / L12 | 原 IPC L1 / L12 | 当前 IPC L1 / L12 | IPC 提升 |
|---|---:|---:|---:|---:|---:|
| RV64IM+C | 908113 / 1059369 | 606427 / 763350 | 0.380481 / 0.326156 | 0.569764 / 0.452636 | 49.75% / 38.78% |
| RV64IM+A+C+F/D | 908652 / 1059961 | 606427 / 763350 | 0.380256 / 0.325974 | 0.569764 / 0.452636 | 49.84% / 38.86% |

真实 C 镜像仍有跨字与提示失误成本，IPC 比当前 IM 镜像低 4.62% / 3.62%。没有宣称所有压缩程序都不再有额外代价。

| 预测与修正观测 | 原 C/full | 当前 C/full |
|---|---:|---:|
| 固定 IM ROI 下一 PC 正确数 / 分支数 | 50958 / 58231（87.5101%） | 52966 / 58231（90.9584%） |
| 真实 C ROI 下一 PC 正确数 / 分支数 | 51143 / 58231（87.8278%） | 53445 / 58231（91.7810%） |
| 真实 C 全程序 ADDR 非控制流长度修正 | 32473 | 0 |
| 真实 C 全程序 IF 长度修正 L1 / L12 | 未实现该机制 | 29027 / 29034 |
| 固定 IM 全程序 IF 长度修正 L1 / L12 | 未实现该机制 | 3 / 3 |

当前“下一 PC 正确率”是 IF 修正后指令携带到解析/退休的有效预测，不能称为原始 BTB 输出成功率。IF 提示失误另计，包含未退休的错误路径请求，分母与 ROI 分支数不同；ADDR 修正为 0 不代表原始长度预测完全正确。

## 功能与独立证据

GSIM 与 ASAN/UBSAN；观察只在测试顶层，不计入物理 CPU。独立软件账本核对真实握手、单 fetch owner、编码长度、ISA 结果、存储及预测修正；结果、存储、预测、长度与恢复 PC 的注错均被拒绝。

r12 新跑三档 cached CPU、固定 IM CoreMark 和 C/full 真实 C CoreMark（均 L1/L12）；full 功能 53 条、22 次 FP 写回。另有裸 C 24 例与 3 负例，长度/flush 两例，frontend 四种 IRQ/held-fetch 恢复与 3 PC 负例，数值恢复 12 例，quiesce 271 例、273 次重启，default trap 3 例；均通过。

r12 的 A 模块测试覆盖 32/64 位、compact/FPGA 四种配置：分别 1347/1420 例，包括全部 AMO、LR/SC、物理 reservation、非法对齐、错误、反压和排序。F 与 FD 分别 27840 个 SoftFloat 向量、39 个非法指令，核对舍入、标志、token、暂停和取消；均通过。四档预测器与独立 C 账本共 92992 次检查、5 负例，逻辑索引与预测结果不变。

r12 沿用未修改的十档 raw cache 与 198656 个 load extraction 向量；复用前核对实际依赖源码、FIR、可执行文件和正/负日志哈希。raw cache 不实例化此次修改的 atomic、predictor、FP execute 模块，排除项与原始逐配置产物均明确记录；没有以新哈希覆盖旧证明。

证据根为 `build/i1-c-fix-20261104-r12`：`implementation-inputs.json` 绑定 121 个模型来源、56 个 full SV 和 15 份证明；`qualification.json` 记录门禁通过。frontend receipt 实际位于 `frontend-recovery/attempt-1/receipt.json`。首次复制裸核脚本保留旧的准备哈希，校验在 elaboration 前拒绝；原失败日志保留，R12 显式准备哈希及重跑证据单列，未放宽硬件或 oracle。

此前 parcel 检查 1515 旧例加 12 换手流、2 负例仍有效，相关模块未再修改。FP wrong-path 集成场景核对现有串行准入抑制与恢复；FP 模块独立向量另覆盖执行中取消。

r11 将 load extraction 改为并行字节/符号选择，并让 queued prediction 数据选择独立于 transfer VALID。r12 针对实际长路径合并：AMO 只选择自然对齐的 W/D lane；RR 载荷使用带 serial 保护的 flat vacancy；EX 生产者载荷按本地空位准备；FP completion 数据先于晚 CPU 接纳/取消准备，仅 owner 位按原条件提交；预测器低逻辑索引位选择物理 bank，逻辑 index/tag/冲突/容量保持。无新增流水级、owner 或延迟。RR 载荷 CE 的 256 种布尔组合也与原条件完全一致。

## Vivado 资源与时序：最佳保留 r12，300MHz 未收敛

器件 `xczu15eg-ffvb1156-2-i`，300MHz，周期 3.333333333ns（工具取整到 3.333ns），setup/hold uncertainty 为 0.100/0.080ns。脚本、XDC、BUFGCE_X0Y48 和模块端点分组与历史基准相同，无新增时序例外或强制网复制。

| 全 A/C/F/D | LUT | FF 总量 | BRAM36 | DSP | 内部 setup ns | 内部 hold ns | 300MHz |
|---|---:|---:|---:|---:|---:|---:|---|
| 原扩展基准 | 23923 | 16134 | 16 | 28 | -0.408 | +0.010 | 未收敛 |
| 本轮 r5 | 25004 | 16341 | 16 | 28 | -0.134 | +0.012 | 未收敛 |
| 本轮 r6 | 24541 | 16276 | 16 | 28 | -0.236 | +0.011 | 未收敛 |
| 本轮 r8 | 24467 | 16232 | 16 | 28 | -0.282 | +0.011 | 未收敛 |
| 本轮 r9 | 24452 | 16222 | 16 | 28 | -0.277 | +0.010 | 未收敛 |
| 本轮 r10 | 24439 | 16229 | 16 | 28 | -0.182 | +0.011 | 未收敛 |
| 本轮 r11 | 24518 | 16296 | 16 | 28 | -0.276 | +0.011 | 未收敛 |
| 本轮 r12 | 24604 | 16242 | 16 | 28 | -0.111 | +0.010 | 未收敛 |
| 本轮 r14 | 25062 | 16407 | 16 | 28 | -0.331 | +0.010 | 未收敛，未选用 |
| 本轮 r15 | 24398 | 16221 | 16 | 28 | -0.314 | +0.010 | 未收敛，未选用 |

完整物理结论均由对应 `physical-summary.json` 绑定：固定脚本/XDC、完整同步状态路径、12 项 check_timing、异常、路由、资源和原始报告/DCP 哈希。保留 OOC context 的 explicit gap=1；没有板级签核结论。r3 中止无 routed 结果，r4/r7/r13 未单独实现；r13 合并算术长路径修改进入 r14。

频率估算为 `1000 / (3.333333333 − setup slack)`，仅描述既有布线，不能代替新频率实现或实测。300MHz 结论要求全部内部同步 setup/hold 均满足且约束、路由覆盖通过。整顶层还含未签核的 OOC pad 路径：r5/r6 的全顶层 hold 为 -1.986/-2.422ns，不能用内部正 hold 代替板级签核。未生成 bitstream、未做板测或功耗评估。

r14 将取指队列改为两个局部占用位，保持原容量 2、full 后一拍开放和 II=1；空闲 write slot 只按本地 credit 准备载荷，实际 enqueue 才建立 owner。pending 预测元数据、MEM 和 CMP 空位同样提前准备，实际握手与 valid 提交保持；ADDR/EX 使用等价展开空位表达式。没有增加寄存器、流水级或周期。

r14 重新通过三档 cached CPU、两种程序/两种延迟、裸 C、数值/长度/frontend 恢复及 quiesce/default trap；取指队列复用 r13 独立 30000 周期证明，连续 2000 周期退休 1999 条；r14 新跑 MDU/A 的 32/64 位 compact/FPGA 共八档独立检查。F/FD、预测器、raw cache、load extraction 的原证明仅在未变实际依赖和原产物核验后复用。`build/i1-c-fix-20261104-r14/implementation-inputs.json` 绑定 121 个模型来源、56 个 full SV 与 13 份证明，`proof-reuse/receipt.json` 明列未实例化排除项。首次导出因复制脚本仍指向已存在的 r12 目录，在 elaboration 前被 fresh-output 校验拒绝；原记录保留，未覆盖 r12 证据，随后使用新的 r14 目录通过。

r14 进一步针对 r12 实测的 19 级 MDU 重组路径，用既有原生分块进位逻辑限制连续宽加法；AMO 共享 W/D 无符号与有符号比较，使用互斥操作并行选择，并缩短加法进位。MDU MUL/MULH 仍为 4 周期、MULW 为 3 周期，除法、取消及反压契约不变，所有 CoreMark 字段逐项等于 r13。r14 冻结之后新增的 H 独立译码组件尚未接入 CPU，不属于该物理输入。

## 复现与交付

在既有 WSL 根加载 `.local-dev/env.sh`，`mill -i OrbitalI1.test.compile`；`simulator/gsim/inorder/extensions_assessment.py --profile im|imc|imafdc --output build/FRESH/ROLE --rtl-output /mnt/e/VM/Share/Valence-rtl/Valence-InOrder/FRESH/rtl/ROLE`。新目录不覆盖证据。实际各门禁入口、命令、冻结源、模型、载荷与产物哈希保存在 r12 receipts 和脚本中；真实 C 入口为 `run_compressed.py`，单位数值入口为 `run_numerical_units.py`。

Windows 加载 `E:/VM/Share/Valence-rtl/Valence-InOrder/tools/env.ps1`，固定 `core300_ooc.tcl FROZEN_RTL FRESH_OUTPUT`。最佳冻结 RTL 在 `c-fix-20261104-r12/rtl/imafdc`，实现目录为同根 `physical/imafdc`。r14/r15 已完成各自的 `collect_physical.py` 收集；该脚本 仅读报告核对来源/RTL、约束、完整同步 setup/hold、覆盖与路由，输出两端 `physical-summary.json`；附加分模块查询只打开 routed checkpoint，不改约束或重跑布局布线。

当前物理状态：ROUTED_INTERNAL_TIMING_NOT_CLOSED，最佳为 r12。r15 虽降低面积，但路径回退；其试验源与证据保留在对应 build/Windows 目录。开发工作树已恢复 r12 的五个试验相关模块，再开展默认关闭的 Spinor 接入；当前工作树尚无新的物理结果。未运行 xsim、Verilator、全量回归、长 Linux/RTOS、bitstream 或板测；顺序双发射尚未开始。

## 2026-11-05 后续状态

R12 的纯 CPU 物理证据继续冻结保留。当前 CPU/VPU 批量优化已修改 CPU RTL，不能继续沿用旧的标量 SV 等价结论；本批新跑固定 IM/真实 C CoreMark 的全部指标与 R12 相同。组合实现 CPU/VPU setup 分别 −0.072/−0.011 ns，详见 [本批报告](i1-spinor-opt-20261105.md)。该组合结果不替代未重跑的纯 CPU 实现。
