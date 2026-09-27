# Valence

Valence 是基于 Scala 2.13、Chisel 和 Mill 的 RISC-V 处理器与模块化 SoC 项目。产品线规划覆盖 MCU 到高性能 SoC；当前开发聚焦可配置的 2/4 发射 RV64 乱序核，以及以 TileLink 为内部互联的应用 SoC。6 发射和多核属于后续目标。RVA23S64/RVA23U64 是架构目标，XCZU15EG 是计划使用的 FPGA 器件；两者都不代表当前设计已经完成合规或板级时序验证。

GSIM 是目前完整硬件验证的受支持后端，NEMU 通过 DiffTest API 独立检查指令提交。Windows Arcilator 目前只有[原生 smoke 试验](simulator/arcilator/README.md)，尚未接入 CPU/SoC 回归。

## 当前状态

乱序核已有重命名、ROB、整数执行、分支预测、并行访存和可选写回 L1；2/4 发射配置已有定向验证，RV64IMAC、Zba/Zbb/Zbs 和 Zicond 的相关路径也经 GSIM 检查。4 发射前端已扩至 16 字节物理取指，并完成 CoreMark 与定向 IPC 测量；结果和瓶颈见[当前性能与证据边界](docs/performance-status.md)。这仍不是完整的 RVA23 CPU，也没有可据以宣称 FPGA 工作频率的时序结果。

SoC 已接 AIA 的 APLIC/IMSIC、UART、定时器、DMA、同步 ROM/RAM 和 TileLink 内存路径，另有独立验证的 AXI4 外存桥。单 hart 在 64 MiB GSIM RAM 上已由 OpenSBI 启动 Linux 并运行最小 `/init`；外部 DDR 接入、多 hart 整机与 Linux AIA 验收仍待完成。见[模块化 SoC 合同](docs/modular-soc.md)与[Linux 启动实验](docs/linux-bringup.md)。

旧顺序核源码保留，但不作为新核正确性的依据。旧 Verilator 仿真入口及 harness 已删除；退役 ChiselSim 测试留在历史参考目录，尚未迁移到 GSIM，不能算作当前验证覆盖率。

## 快速命令

```bash
make compile
make test-scala       # 仅配置和 Chisel 展开检查，不启动硬件仿真器
make gsim-setup       # 首次准备锁定版本的 GSIM
make gsim-core-test   # 新核程序执行、访存和 NEMU 差分
make gsim-ipc         # 默认裸核配置的确定性 IPC 基准
make coremark-setup   # 首次准备锁定版本的 CoreMark 源码
make gsim-coremark    # GSIM 裸机 CoreMark 工作负载与 guest 周期/IPC
make gsim-linux-setup # 从 ~/board/linux 构建独立内核镜像
make gsim-linux-test  # OpenSBI + Linux + 最小 /init 启动验收
make test            # Scala 检查 + 完整 GSIM 回归（make regress 等价）
```

开发时按修改范围选择 `gsim-smoke`、`gsim-backend-test`、`gsim-integer-test`、`gsim-predictor-test` 或 `gsim-core-test`。
依赖、支持范围和结果见 [GSIM 说明](simulator/gsim/README.md)。现有 CPU/SoC 回归不依赖 Verilator。
Mill 构建模块名暂沿用 `IonSoC`，因此现有 `make` 命令和脚本不需要随项目名称改变。

## 目录与文档

- `src/main/scala/core/ooo`：独立新核；[设计与验收规划](docs/ooo-core-plan.md)。
- `src/main/scala/isa`：新旧核心共享的标准编码与架构常量；[复用边界](docs/isa-reuse.md)。
- `src/test/scala`：当前配置/展开检查与 GSIM 模型生成入口。
- `simulator/gsim`：GSIM 驱动、工具链锁定和 NEMU 差分。
- `legacy/`：保留旧测试、可复用的汇编程序、参考配置与历史文档；旧 firmware 和退役驱动已清理，见 [历史索引](legacy/README.md)。
- [文档索引](docs/README.md)：区分新核当前状态与旧 SoC 历史记录。

完整目录与放置规则见 [目录说明](docs/layout.md)。

裸核接口、IPC 口径与结果见 [裸核 IPC](docs/bare-core-ipc.md)。

FPGA 同步 ROM＋双发射核＋同步 RAM 已运行 C 程序并通过 NEMU 差分；集成 RTL 导出与 Vivado 移交入口见 [FPGA 基线](docs/fpga-bringup.md)。当前没有 Vivado 实测频率或资源结果。

新应用 SoC 以 [RVA23S64 / RVA23U64](docs/rva23.md) 为架构目标；当前开发核尚未符合完整 profile。
