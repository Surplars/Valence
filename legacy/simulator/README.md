# 退役的仿真驱动

原 `simulator/harness` 的两个 Verilator C++ 驱动原样保留在 `harness/`，仅供历史问题和接口迁移参考。
活动 Makefile 不再提供 Verilator、旧 emu、旧固件/Linux 仿真或其回归入口。
当前唯一仿真入口是 `simulator/gsim`；NEMU 差分由该目录直接调用参考库，不依赖旧 emu。

`payloads/`、`rtl/`、`firmware/`、`rootfs/`、`difftest/` 分别保留旧程序、辅助 RTL、固件、根文件系统工具和参考平台配置。
本地固件检出被忽略，内容原样保留；旧文档中的原路径只作为历史记录。
