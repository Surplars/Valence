# 历史参考资料

这里集中保留旧顺序核源码、验证和启动资料，不参与当前 `IonSoC` 的默认编译/测试发现。
Verilator、旧 emu 和 ChiselSim 仿真入口已退役，不在此提供重新运行它们的构建入口。

- [tests](tests/README.md)：旧总线、核心、缓存、外设、调试与 SoC 用例，尚未迁移到 GSIM。
- [hardware](hardware/README.md)：独立 `LegacySoC` 模块，保留旧核/旧 SoC 和 3 个历史测试/导出源文件。
- [simulator](simulator/README.md)：可复用的旧汇编程序与 DiffTest 参考配置；退役驱动和 firmware 已移除。
- [旧 SoC 架构](docs/architecture.md)
- [旧流水线](docs/core-pipeline.md)
- [ISA、CSR 与中断](docs/isa-csr-interrupts.md)
- [缓存与 TileLink](docs/memory-cache-tilelink.md)
- [旧仿真与固件](docs/simulation-firmware-debug.md)
- [Bring-up 问题记录](docs/bringup-bug-record.md)

文档中的旧命令、文件路径和当时的通过结果保留为历史证据，不代表当前入口或新核覆盖率。
已经清理的 firmware、Verilator harness、辅助 RTL、rootfs 与调试配置可从 Git 历史追溯。
复用这些资产前必须审查其预期行为，并补充独立 GSIM 验证。
当前开发见 [目录说明](../docs/layout.md) 和 [GSIM 说明](../simulator/gsim/README.md)。

2026-10-07 已将 51 个旧硬件文件和 3 个历史测试/入口文件按原相对布局迁入 `hardware/src`，
保持包名及字节内容。`make legacy-compile` 可编译历史模块；`make legacy-elaboration` 仅执行
配置与译码的纯展开检查，`make legacy-rtl` 导出历史顶层，不恢复旧硬件仿真后端。
未使用的 ELF 合并助手、旧模拟配置覆盖器及重复 NEMU 配置已移至仓库外归档；
有用的汇编、两份 NEMU 配置、故障记录和退役测试继续保留。
本次移动明细及源码备份见 [整理清单](../docs/repository-maintenance.md)。
