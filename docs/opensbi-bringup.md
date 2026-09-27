# OpenSBI v1.9 启动验证

`make gsim-opensbi-test` 使用新乱序核的 `MachinePlatform` 在 GSIM 中执行未修改的上游
OpenSBI v1.9 `generic` 平台 `fw_jump` 固件。源码按
[`simulator/gsim/config/opensbi.json`](../simulator/gsim/config/opensbi.json) 中的 tag 和提交
`cbf9f6734dd85a982c63e3cb5db7ffe09da839ca` 固定，拉取到忽略提交的
`simulator/build/opensbi-v1.9`。首次运行先执行 `make gsim-opensbi-setup`；还需要
`riscv64-linux-gnu-` GCC/binutils 和 `dtc`。构建产物和启动日志位于 `build/gsim/`。

启动布局为 0x80000000 的 8 KiB ROM 复位跳板、0x80010000 起 1 MiB 的 GSIM RAM、
0x80040000 的 `fw_jump`、0x800c0000 的设备树，以及 0x80100000 的 S 态测试程序。
`FW_TEXT_START=0x80040000` 使固件 RW 区域从 0x80080000 开始，符合 OpenSBI 域保护的
对齐要求。设备树声明单 hart、RV64IMAC、Sv39、0x10000000 的 8250 串口及 ACLINT
mtime/mtimecmp。此专用验证平台以每个运行周期一个 `timerTick` 驱动定时器；10 MHz
设备树频率不是物理时钟标定。默认生产平台的 RAM 容量和启动镜像并未改成这个配置。

成功条件由独立 C++ GSIM 驱动核对：串口解码出 `OpenSBI v1.9`，OpenSBI 打印
`Domain0 Next Mode : S-mode`，S 态程序发出 SBI BASE `get_spec_version` ECALL，
收到 `error=0` 和非零版本，随后写入完成标记。当前实测为 3,351,435 个 GSIM
运行周期、2,817,686 条提交指令，返回 SBI 规范版本 `0x03000000`。这些数字包含固件
探测和串口输出，不能用作应用 IPC 基准。固件探测不存在的 CSR/PMP 编号产生预期陷阱；
验证没有忽略意外总线错误。

`make gsim-opensbi-console` 启动交互式 GSIM 串口：OpenSBI 的 TX 字节解码后立即写到
终端，按键经 8N1 串行 RX 送进 SoC。交接后的 S 态小程序从 UART 收取字节并原样回显，
便于直接验证双向连接；终端用 Ctrl+D 或 Ctrl+C 退出。非终端标准输入也可用，
例如 `printf 'ping\n' | make gsim-opensbi-console`；输入读尽并全部回显后自动退出。
交互命令会重建并校验当前 GSIM 模型和 OpenSBI 固件，初次出现串口输出前需要完成编译和固件启动。
它不是 shell，也尚未启动操作系统。

本轮验证证明真实 OpenSBI 可以完成初始化和 S 态交接；S 态程序目前只做一次 SBI
调用。尚未启动 Linux、验证页表下的通用 S 态负载、AIA 中断委托、更多 SBI 扩展或
多 hart。下一阶段应先扩大 S 态探针覆盖计时器、页表和串口，再准备可装入当前
内存模型的内核与根文件系统；OS 启动还需要更大的 RAM/外部内存模型。
