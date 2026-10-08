# Valence

Valence 是 OpenIon 的可配置 RISC-V SoC 工程，使用 Scala、Chisel 和 Mill。
当前 SoC 名为 **VL100**，乱序 CPU 核名为 **Orbital-A1**；板级基线为双发射，
4 发射属于独立实验配置。ISA、微架构和外设配置分别控制，不能由某个板级配置推断所有配置的能力。
RVA23 和多 hart 是后续目标，不代表当前已完成 profile 合规。

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
