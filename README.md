# Valence

Valence 是 OpenIon 的可配置 RISC-V SoC 工程，使用 Scala、Chisel 和 Mill。
当前 SoC 名为 **VL100**，乱序 CPU 核名为 **Orbital-A1**；板级基线为双发射，
4 发射属于独立实验配置。ISA、微架构和外设配置分别控制，不能由某个板级配置推断所有配置的能力。
RVA23 和多 hart 是后续目标，不代表当前已完成 profile 合规。

## A1 云端候选（2026-10-27）

[第五批 A1 load payload nomination](docs/a1-efficiency-refactor-5.md)：默认 OFF，宽 payload 选择与完整授权分离。
50 项纯检查、11 个组件和 30 个 CPU 执行通过；与第四批实测周期相同，新增性能/带宽收益为 0。
同流映射 LUT 增加 0.79017%、MUXF 减少 5.38407%，其余主要资源不变；非优化胜出，后续性能基线仍为第四批，物理 Fmax 未测。

[第四批 A1 普通物理 load 入口优化](docs/a1-efficiency-refactor-4.md)：默认 OFF，保留双发射、原注册/授权链和完整 owner。
同条件 CoreMark 全工作量速度提升 5.4125%/5.4815%，ROI 提升 5.5797%/5.6574%；依赖 load 间隔 6→5 拍。
独立持续供给 ROI 和请求跨度不变，不能宣传为持续带宽提升。44 项纯检查、11 个组件和 30 个 CPU 执行均通过。
正常映射逻辑 LUT 增加 2.4853%、MUXF 增加 21.0641%，FF/RAM/DSP 不变；保持默认 OFF 实验选项，物理 Fmax 未验证。

[第三批 A1 ROB completion payload重构](docs/a1-efficiency-refactor-3.md)：一个默认OFF开关，保留双发射/双写回及完整64位owner。
正常同流映射logic LUT再减4.1078%、FF再减5.5521%，代价为新增50个RAM32M16；BRAM36/DSP不变。
历史短GSIM报告CoreMark与依赖load周期不变；恢复后39项纯Scala检查通过，历史日志缺失与本次映射证据分开记录。
不是新IPC/带宽增益、物理Fmax或完整ISA签核。

[第二批 A1 efficiency refactor](docs/a1-efficiency-refactor-2.md)：新增两个默认OFF开关，保留完整功能与二发射/二写回。
CoreMark同频吞吐在首批基础上再增+1.7630%/+1.8029%；正常同流映射logic LUT再减0.9965%、FF不变。
30个CPU与82个组件用例及独审通过；依赖load仍6拍，零收益、局部尾延迟与失败恢复历史保留。
不是完整ISA/Linux或物理Fmax签核。

[首批 efficiency refactor](docs/a1-efficiency-refactor.md)：显式实验配置，五开关默认OFF。
同程序 CoreMark 同频吞吐 +8.264%/+8.163%；同工具正常映射 logic LUT −5.869%、FF −7.330%。
依赖load退休间隔7→6拍；保留原LD/MUL/DIV零收益结果。不是完整ISA/Linux或物理Fmax签核。

[Identity-only fetch horizon](docs/a1-identity-fetch-horizon.md)：默认OFF，仅完整安全RAM第三包，容量不变。
热load含drain1068→883（−17.32%），冷907→909（退化0.22%）；短CPU/组件及独立补证通过，PPA未验证。

[Certified load ingress](docs/a1-certified-load-ingress.md)：默认OFF，VM dependency含drain省53拍（6.05%），
热load含drain仅省1拍；容量不变，PPA未测，不提升推荐配置。证据与覆盖限制见文档。

## FPGA-next 独立配置

新的 FPGA 优先 SoC 入口与逐模块证据见 [FPGA-next](fpga/next/README.md)。
Selected v2 组合 RAM 存储、浮点共享运算、控制路径优化和指令缓存修正，保留 RV64GC、双发射、
32+32 KiB 缓存、2 GiB DDR 与 100 MHz 目标。三速 MAC 和 JTAG 预留有单独的原生时钟/物理验证边界；
已有板级入口和历史物理记录保留，不能替代新配置的布局布线验收。

## dev 分支增量（2026-10-08）

已核对的源码与短验证批次见 [dev 交付记录](docs/dev-delivery-20261008.md)。
本轮 Vivado 物理验证仍待完成，本轮物理时序/整板签核尚未验证；virtual-load precheck 默认关闭。
此分支仅交付源码、脚本、测试与文档，不包含编译中间文件或固件/仿真/Vivado 生成物。

## 历史板级状态（2026-10-07）

以下为旧 r6 的历史记录，不能用于当前 dev 候选的物理验收。

当前实现包含重命名、ROB、整数/分支执行、RV64C、原子访存、Sv39、可配置缓存及 F/D 路径。
F/D 使用 Berkeley HardFloat 算术模块并接入本项目的译码、浮点状态、访存和提交控制；
通用配置的浮点开关默认关闭，RV64GC 板级配置开启。支持范围与验收边界查
[datasheet](docs/soc-datasheet.md) 和 [当前性能记录](docs/performance-status.md)，不是完整 ISA 合规声明。

当前板级平台已接 PL DDR4、UART、通用 DMA、自研千兆 GMAC 及其专属 DMA、
CMU 和多时钟域。较早板级版本已运行 OpenSBI/Linux，用户上板报告了 CoreMark 和网络启动结果。
最新 r6 发布配置为 RV64GC、双发射、CPU 100 MHz、UART 460800 baud、完整 2 GiB DDR；
整板布局布线后 setup/hold/pulse、接口时序及 bus-skew 检查通过并已生成 bit。
但 setup 仅 +0.000 ns（报表舍入）、hold +0.005 ns，工程裕量仍不足，
**最新 r6 bit 的板级复测尚待用户完成**。静态签核不等同于稳健性或性能验收。
详见 [Vivado 时序记录](docs/fpga-timing-windows.md) 和 [Debian BSP](docs/vl100-debian-bsp.md)。

GSIM 是当前 CPU/SoC 的硬件验证后端，NEMU 提供独立提交参考。
CDC 的短双时钟 RTL 检查另使用 Vivado xsim；不恢复旧 Verilator/ChiselSim 回归。
Windows Arcilator 仅有 [smoke 试验](simulator/arcilator/README.md)。

## 构建与验证

```bash
make compile
make test-scala       # 当前模块的配置/展开检查
make gsim-smoke       # 最短基础仿真链路检查
make gsim-core-test   # 按需选择 CPU 执行/访存/NEMU 差分
make gsim-ipc         # 裸核确定性 IPC 基准，不是 Linux IPC
make gsim-coremark
# make test / make regress 是完整回归；不要为小范围修改默认执行
```

本机 GSIM 的 C++ 编译器可显式指定：`GSIM_CXX=clang++-19 make gsim-smoke`。
首次部署、锁定版本和定向入口见 [GSIM 说明](simulator/gsim/README.md)。
当前 Mill 模块名保留 `IonSoC` 以兼容已有脚本；它与历史硬件类 `soc.IonSoC` 不同。

## 源码边界

| 位置 | 内容 | Mill 模块 |
| --- | --- | --- |
| `src/main/scala/core/ooo` | Orbital-A1、当前 VL100 平台和核心侧适配 | `IonSoC` |
| `src/main/scala/ip` | 可复用 UART、CMU、DMA、GMAC、互联等 IP | `IonSoC` |
| `src/main/scala/isa`、`bus/tilelink/TileLink.scala` | 公共 ISA 编码与 TileLink 类型 | `IonSoC`，历史模块通过依赖复用 |
| `src/test/scala` | 当前配置/展开检查和 GSIM 模型入口 | `IonSoC.test` |
| `legacy/hardware/src` | 旧顺序核、旧 SoC 和旧控制适配 | 显式 `LegacySoC` / `LegacySoC.test` |
| `legacy/tests` | 退役 ChiselSim 用例，仅供审查 | 不参与任何模块测试发现 |

当前模块不依赖 `LegacySoC` 或旧 Scala `DifftestLib`；历史模块反向依赖公共定义和旧 DiffTest 库。
`make legacy-compile`、`make legacy-elaboration`、`make legacy-rtl` 仅用于历史构建；
`make sim-verilog` 是历史 RTL 导出别名，不是当前 VL100 板级导出。
旧核有已知问题，不能作为新核正确性的参考。

## 文档与产物

- [文档索引](docs/README.md)、[目录说明](docs/layout.md)、[本次整理与提交清单](docs/repository-maintenance.md)。
- 软件适配：[datasheet](docs/soc-datasheet.md)、[寄存器](docs/soc-registers.md)、[OS 移植](docs/os-software-porting.md)。
- 板级源码：`fpga/firmware` 与 `fpga/zu15eg`；历史资料见 [legacy 索引](legacy/README.md)。
- `build/` 是可再生输出，`out/` 是 Mill 缓存，`simulator/build/` 是工具/软件源码缓存，均不提交。

2026-10-07 整理前的源码、全部 build 产物和最新 r6 发布报告已校验归档到
`${LOCAL_ARCHIVE_ROOT}/20261007-precommit`，不放入 Git。
历史文档中的旧 `build/...` 回执路径保留原始口径，恢复方法见整理清单。
