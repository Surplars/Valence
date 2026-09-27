# 历史仿真资产

这里仅保留可能用于独立审查的旧汇编程序（`payloads/`）和 DiffTest 参考配置（`difftest/`）。
`make payload` 可组装旧程序，但不表示它通过当前新核的 GSIM 验证。

退役的 Verilator 驱动、辅助 RTL、固件检出、rootfs 工具及调试配置已删除；
需要查阅原内容时使用 Git 历史。当前唯一受支持的硬件仿真入口是 `simulator/gsim`。
