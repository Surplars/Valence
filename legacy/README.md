# 历史参考资料

这里集中保留旧顺序核工程的验证和启动资料，不参与默认 Scala 测试发现。
Verilator、旧 emu 和 ChiselSim 仿真入口已退役，不在此提供重新运行它们的构建入口。

- [tests](tests/README.md)：旧总线、核心、缓存、外设、调试与 SoC 用例，尚未迁移到 GSIM。
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
