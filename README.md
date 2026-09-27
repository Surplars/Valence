# IonSoC

IonSoC 使用 Scala 2.13 / Chisel 和 Mill，当前独立重写双发射乱序核。**GSIM 是唯一受支持的硬件仿真后端**，NEMU 通过 DiffTest API 检查有序提交。

## 当前状态

新核已实现重命名、ROB、整数执行、最小取指/译码、条件分支预测、JAL/相邻 AUIPC-JALR 目标预测及恢复，已接四槽 LSU、ROB 索引投机 store 准备/地址消歧和可选四项 store buffer（普通 RAM load 可并行，缓冲写要求平台保证成功，响应须按序），支持 49 种 RV64I 运算/控制流/访存编码、两条 Zicond 条件置零指令、13 条 RV64M 乘除指令及 40 条 B（Zba/Zbb/Zbs）位操作指令。可选 RV64C 整数路径已运行混合长度固件和 CoreMark，见 [验证与性能口径](docs/rv64c-coremark.md)。当前仍不是完整 RVA23 CPU 或 SoC。

SoC 按可复用 IP 组织，应用中断架构选择 AIA。独立 APLIC/IMSIC 位于 `src/main/scala/ip`；`MappedMachineCore` 已支持程序通过数据总线配置 M 根域与 S 子域 APLIC，并处理 M/S 外部中断。新增 [同步机器核启动平台](docs/machine-platform.md)，接入 Chisel ROM/RAM、汇编/C 固件、[8N1 UART控制台](docs/uart.md)、[FENCE / DMA共享内存路径](docs/dma.md)和[机器定时器](docs/machine-timer.md)。单 hart S 态已在 64 MiB GSIM RAM 上经 OpenSBI 启动本地 Linux 并运行最小 `/init`，见 [Linux 启动实验](docs/linux-bringup.md)；S 态 UART 中断已由独立 GSIM 固件验证，Linux AIA 设备树/驱动与 VS 路径仍待完成。PLIC 留作兼容替换路线，见 [模块化 SoC 合同](docs/modular-soc.md)。

旧顺序核源码保留，但不作为新核正确性的依据。旧 Verilator 仿真入口已撤下；依赖它的 ChiselSim 测试和 harness 移至历史参考目录，尚未迁移到 GSIM，不能算作当前验证覆盖率。

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
依赖、支持范围和结果见 [GSIM 说明](simulator/gsim/README.md)。不需要 Verilator，也不回退到其他仿真器。

## 目录与文档

- `src/main/scala/core/ooo`：独立新核；[设计与验收规划](docs/ooo-core-plan.md)。
- `src/main/scala/isa`：新旧核心共享的标准编码与架构常量；[复用边界](docs/isa-reuse.md)。
- `src/test/scala`：当前配置/展开检查与 GSIM 模型生成入口。
- `simulator/gsim`：GSIM 驱动、工具链锁定和 NEMU 差分。
- `legacy/`：统一存放旧测试、仿真资产、调试配置与历史文档，见 [历史索引](legacy/README.md)。
- [文档索引](docs/README.md)：区分新核当前状态与旧 SoC 历史记录。

完整目录与放置规则见 [目录说明](docs/layout.md)。

裸核接口、IPC 口径与结果见 [裸核 IPC](docs/bare-core-ipc.md)。

FPGA 同步 ROM＋双发射核＋同步 RAM 已运行 C 程序并通过 NEMU 差分；集成 RTL 导出与 Vivado 移交入口见 [FPGA 基线](docs/fpga-bringup.md)。当前没有 Vivado 实测频率或资源结果。

新应用 SoC 以 [RVA23S64 / RVA23U64](docs/rva23.md) 为架构目标；当前开发核尚未符合完整 profile。
