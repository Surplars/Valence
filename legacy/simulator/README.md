# 历史仿真资产

这里仅保留可能用于独立审查的旧汇编程序（`payloads/`）和 DiffTest 参考配置（`difftest/`）。
`make payload` 可组装旧程序，但不表示它通过当前新核的 GSIM 验证。

保留的 NEMU 配置在 `difftest/nemu-configs/`：`riscv64-ionsoc-ref_defconfig` 和
`riscv64-ionsoc-linux-ref_defconfig`。未使用的 `merge_elf.py`、`ionsoc_config_override.cpp`
和外层重复配置在 2026-10-07 移至仓库外归档，不再提供默认执行入口；
详见 [整理清单](../../docs/repository-maintenance.md)。

退役的 Verilator 驱动、辅助 RTL、固件检出、rootfs 工具及调试配置已删除；
需要查阅原内容时使用 Git 历史。当前唯一受支持的硬件仿真入口是 `simulator/gsim`。
