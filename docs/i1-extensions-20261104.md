# R5 基线 A / C / F / D 扩展评估（2026-11-04）

基准为 `fbcb215`，硬件与最佳 `ccc68f9` 一致。默认 RTL、默认配置和最佳 R5 均保持不变。重新导出的 RV64IM 22 个 SV 文件与已实现的 R5 全部逐字节一致，因此基线复用原 routed DCP；其他五档分别完成同约束综合、布局和布线。

评估范围为顺序单发射 RV64、fpga8、timing-cuts、dsp-tiled 整数 MDU、BTB128、32KiB I-cache + 32KiB D-cache、64B 行。A 原子与保留单元、C 取指/解码、完整 F/D 执行和浮点寄存器均按实际配置接入。未启用 CPU monitor、SoC AXI/TileLink 互连或外设。F/D 使用现有 `I1FloatingPointResourceConfig.fpga`，保留完整指令组、格式内共享舍入器及乘法/FMA、每核一个浮点执行所有者。A 使用现有单 hart/独占运行时写者契约，本表不包含多核或 DMA 一致性互连。

器件 `xczu15eg-ffvb1156-2-i`；300MHz，setup uncertainty 0.100ns、hold uncertainty 0.080ns；相同四个模块端点组、相同 BUFG 站点、同一普通实现流程。没有新增 false path、multicycle、强制网复制或放宽时钟。Vivado 将请求周期 3.333333333ns 取整到 3.333ns。

## 布线后资源与固定二进制 IPC

| 配置 | LUT | FF（含端口寄存器） | BRAM36 等效块 | DSP | setup ns | hold ns | STA 估算 MHz | IPC L1 | IPC L12 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RV64IM（R5） | 9747 | 7789 | 16 | 16 | -0.030 | +0.012 | 297.3 | 0.597277 | 0.469589 |
| RV64IM+A | 11002 | 8327 | 16 | 16 | -0.511 | +0.011 | 260.1 | 0.597277 | 0.469589 |
| RV64IM+C | 10331 | 8241 | 16 | 16 | -0.186 | +0.012 | 284.1 | 0.514075 | 0.416583 |
| RV64IM+F | 13906 | 10807 | 16 | 19 | -0.182 | +0.011 | 284.5 | 0.597277 | 0.469589 |
| RV64IM+F/D | 22329 | 15418 | 16 | 28 | -0.376 | +0.011 | 269.6 | 0.597277 | 0.469589 |
| RV64IM+A+C+F/D | 23923 | 16134 | 16 | 28 | -0.408 | +0.010 | 267.3 | 0.514075 | 0.416583 |

频率列为 `1000 / (3.333333333 − setup slack)` 的线性 STA 估算。它保留该次布线和不确定度，仅用于同口径比较；不能代替在新周期重新实现/签核或板级实测。setup/hold 同时非负才表示本次 300MHz 内部同步路径收敛。原始 pad I/O 和板级时序不在结论内。

主表固定使用原官方 CoreMark RV64IM 二进制（GCC 13.2、O3、2000B、1 iteration），SHA256 `bc0bc1c5b5fdd7b4960b6e472d0a5d7aaf75eca748fdf7cd669904d1b2aba43b`。L1/L12 是相同双 burst 口轮询模型的首拍服务延迟 1/12 周期，其余每周期一拍。各档 ROI 均退休 345520 条指令；逐条 ISA oracle、最终内存和四个独立已知 CRC 均通过。这是短程序评估，不是正式 CoreMark 分数。

固定 IM 镜像的下一 PC 正确率：R5 / A / F / F/D 为 90.9584%，C / 全扩展为 87.5101%。分支预测器容量和策略不变；C 改变了索引的半字粒度。整数 CoreMark 没有执行 FP 或原子指令；它衡量启用这些硬件后的整数周期影响。扩展自身功能由下面的专门指令/数值检查验证，不能由此表推断浮点程序加速。

| 配置 | CPU 内 FF | 时序端口上下文 FF | LUT 相对 R5 | FF 总量相对 R5 | 300MHz 内部同步路径 |
|---|---:|---:|---:|---:|---|
| RV64IM（R5） | 6854 | 935 | +0.00% | +0.00% | 未收敛 |
| RV64IM+A | 7389 | 938 | +12.88% | +6.91% | 未收敛 |
| RV64IM+C | 7299 | 942 | +5.99% | +5.80% | 未收敛 |
| RV64IM+F | 9801 | 1006 | +42.67% | +38.75% | 未收敛 |
| RV64IM+F/D | 14413 | 1005 | +129.09% | +97.95% | 未收敛 |
| RV64IM+A+C+F/D | 15122 | 1012 | +145.44% | +107.14% | 未收敛 |

所有 CPU I/O 均有与基线一致的捕获寄存器；它是时序上下文，不是弹性流水级或外设。新增 A/F 端口的寄存器计入总 FF，上表另列 CPU/上下文 FF。LUT/BRAM/DSP 为相同测量范围。

## 实际压缩编译的 CoreMark

额外将同一官方源码与同一启动/校验端口编译为 `rv64imc_zicsr_zifencei` / LP64 / O3。镜像从 16368B 降为 12368B。以下固定运行相同的压缩镜像；它与主表程序的代码地址/布局不同，分别报告，不能把它当作启用硬件的单变量比较。

| 硬件 | ROI 指令 | ROI 周期 L1 / L12 | IPC L1 / L12 | ROI 下一 PC 正确率 | 全程序非控制流长度修正 |
|---|---:|---:|---:|---:|---:|
| RV64IM+C | 345520 | 908113 / 1059369 | 0.380481 / 0.326156 | 87.8278% | 32473 |
| RV64IM+A+C+F/D | 345520 | 908652 / 1059961 | 0.380256 / 0.325974 | 87.8278% | 32473 |

当前 C 前端存在逐指令长度预测/修正开销。固定未压缩二进制时，C 改变预测器索引粒度，并增加取指周期；实际使用压缩代码时还发生顺序指令长度修正。GSIM 观察账本已独立对齐这些修正的 ADDR 事件与退休 PC/指令长度，分支正确率不混入非控制流长度修正。这里没有为改善结果修改 RTL。

## 功能与独立证明范围

- 六档生产 cached CPU：两种服务延迟下逐条指令检查，覆盖 A 的 LR/SC 成功/失败和读回，C 混合半字/跨字与跳转恢复，F/D 载入、运算、FMA、除法、平方根、转换、存储、整数/浮点写回及 fflags。所有档位均有注入错误结果的负控制。
- C：独立软件展开 oracle 穷举 65536 个编码；抽取共用 oracle 后又重跑原 GSIM 穷举及负控制。
- C 取指：1515 个边界/部分故障/背压/失效场景，使用现成 scalar fixture 绕过固定 GSIM 的 aggregate getter 生成缺陷。
- A：1420 个 RV64 LR/SC/全部 AMO.W/D、保留失效、物理地址、错误与背压场景；负控制拒绝。
- F 和 F/D：各 27840 组锁定 Berkeley SoftFloat 独立向量、39 个非法编码、全部五种舍入模式/五类标志、boxing、全 token、流水取消、背压、完成与延迟/II 合约。各自注入错误数值被拒绝。
- 官方 CoreMark：独立逐指令/内存 oracle、已知 CRC、相同服务和负控制；扩展后的软件 oracle 对六档原 IM 镜像的所有既有指标逐项复现。

C + F/D 另覆盖 8192 个压缩浮点访存编码，开启/禁用合法性与独立负控制均通过。只运行受影响短 GSIM 验证；未跑全量回归、xsim、Linux 长测或 bitstream。

## 复现与证据

WSL 工作根：`/home/openion/Valence-InOrder`；Windows Vivado 根：`E:/VM/Share/Valence-rtl/Valence-InOrder`。

```sh
source .local-dev/env.sh
for profile in im ima imc imf imfd imafdc; do
    python3 simulator/gsim/inorder/extensions_assessment.py --profile "$profile" --output "build/FRESH/$profile" --rtl-output "/mnt/e/VM/Share/Valence-rtl/Valence-InOrder/FRESH/rtl/$profile"
done
python3 simulator/gsim/inorder/extensions_units.py --output build/FRESH/units
python3 simulator/gsim/inorder/compressed_coremark_assessment.py --models build/FRESH --compressed-model build/FRESH/units/compressed --output build/FRESH/coremark-c
```

`compressed_coremark_assessment.py` 复用六档 GSIM 模型对象；独立 C 穷举对象由 `--compressed-model` 显式传入（本轮实际复用 `units-r2/compressed`；共用 oracle 重构后的完整组件验收为 `units-final`），其余所有实际命令均记录在 receipt。SoftFloat zip 使用 `simulator/gsim/config/floating-point-dependencies.json` 固定 revision/SHA256；依赖与所有构建输出保存在 clone 的 build/ 内。

物理流程：`fpga/inorder/core300_ooc.tcl FROZEN_RTL FRESH_OUTPUT`，本轮冻结脚本在 Windows `extensions-20261104-r1/core300_ooc.tcl`；旧 RV64IM 结果复用 `convergence-20261103-r1/physical-natural-r5`，其他配置在 `extensions-20261104-r1/physical/`。

完整数据、路径、脚本参数、逐条命令、模型/source/RTL/report SHA256 在配套 JSON 及 WSL `build/i1-extensions-20261104-r1` 的 receipt 中。最初六档生成时的源码另存 `source-at-gsim`；随后仅扩展 C/预测的独立 C++ 测试 oracle，生产 RTL 没有变化。

## 顺序双发射的后续评估边界

本轮先完成单发射 ISA 成本矩阵。双发射必须保持此基线范围，分别测真正的 GSIM 退休 IPC 与 Vivado 布线后频率/面积；不能将理想配对率当作实现 IPC，也不能直接按执行单元翻倍估算面积。C 前端带宽/长度修正和四读两写寄存器端口是必须单列的结构成本。

## 可选模块端点时序

直接打开同一 routed DCP 查询，不重新综合/布线，也不改变时钟、路径组、例外或预算。所有结果来自同一固定流程的一次配置实现，局部余量也受全核布局影响。下表覆盖所有进入该模块真实时序端点的路径；它包含跨模块源，不能当作孤立 IP 的最高频率。浮点执行端点不包含独立浮点寄存器文件/CSR，整个 CPU 的结果见主表。

| 配置 | 端点模块 | setup ns | hold ns | 寄存器/RAM/DSP 状态单元 |
|---|---|---:|---:|---:|
| RV64IM+A | atomic | -0.277 | +0.031 | 382 |
| RV64IM+F | execute | -0.070 | +0.011 | 2362 |
| RV64IM+F | fpr | -0.018 | +0.013 | 311 |
| RV64IM+F/D | execute | -0.249 | +0.011 | 6788 |
| RV64IM+F/D | fpr | -0.376 | +0.017 | 555 |
| RV64IM+A+C+F/D | atomic | -0.191 | +0.028 | 384 |
| RV64IM+A+C+F/D | execute | -0.068 | +0.010 | 6785 |
| RV64IM+A+C+F/D | fpr | -0.110 | +0.020 | 555 |

RV64IM（R5） 最差 setup 路径：`cpu/core/leftAluSelect_reg[1]/C` → `cpu/core/addrPacket_result_reg[34]/D`。

RV64IM+A 最差 setup 路径：`cpu/core/offerPc_reg[4]_rep/C` → `cpu/core/offerPc_reg[3]_rep_replica/D`。

RV64IM+C 最差 setup 路径：`cpu/dcache/valid_reg[274]/C` → `cpu/core/idPacket_instruction_reg[23]/CE`。

RV64IM+F 最差 setup 路径：`cpu/dcache/valid_reg[110]/C` → `cpu/core/offerPc_reg[1]/D`。

RV64IM+F/D 最差 setup 路径：`cpu/dcache/bankedTags/hits_readRow_5_reg[0]/C` → `cpu/core/fpr/collision_2_reg/CE`。

RV64IM+A+C+F/D 最差 setup 路径：`cpu/core/offerPc_reg[2]_rep__1/C` → `cpu/core/offerPc_reg[35]/D`。
