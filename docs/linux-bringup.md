# Linux 启动实验

`make gsim-linux-setup` 从 `~/board/linux` 的当前 Git 提交只读生成源码快照，构建独立的
RV64 Linux 内核和小型内建 initramfs；不会改动上游 Linux 源码。`VALENCE_LINUX_SOURCE`
可指定其他本地 Linux 源码目录。当前本地提交为
`165768bb70265b5c38cf0b73fafd75be235f8b14`，版本 `7.3.0-rc4`。
快照、配置、镜像和构建日志在 `build/gsim/linux-source` 与 `build/gsim/linux-riscv`。
源码提交变化时应另建构建目录；脚本会拒绝把新提交混入旧快照。

`make gsim-linux-test` 构建固定版本的 OpenSBI `generic` 平台 `fw_jump`、Linux 设备树与
64 MiB GSIM RAM 平台，加载真正的 RISC-V `Image` 并执行。首次运行还需现有的
`make gsim-setup` 和 `make gsim-opensbi-setup`。测试要求观察到 Linux 版本日志、
用户态指令提交和 `/init` 的 `VALENCE_LINUX_INIT_OK` 标记，否则输出周期、PC、陷阱与串口日志。
启动固件仍是上游 OpenSBI v1.9，没有修改其源码。

专用仿真地址布局：8 KiB ROM 复位跳板在 `0x80000000`，64 MiB RAM 从 `0x80010000`
到 `0x8400ffff`；OpenSBI 在 `0x80040000`，设备树在 `0x800c0000`，Linux `Image`
在 2 MiB 对齐的 `0x80200000`。OpenSBI 根据域权限自动向设备树写入 M 态固件保留区。
这份 64 MiB RAM 是 GSIM 启动模型；默认 `MachinePlatform` 仍为 4 KiB，FPGA DDR
接口、资源占用和时序均未由此验证。

内核配置从 `tinyconfig` 生成，启用 RV64/Sv39、SBI、TTY、8250、SBI earlycon、SBI HVC、
ELF、内建 initramfs 和 `/dev/console`，禁用图形虚拟终端。启动命令行目前使用
`earlycon=sbi console=hvc0 rdinit=/init`；串口物理 TX/RX 经 OpenSBI DBCN 到 UART，
Linux 8250 的独立中断与控制台路径尚需后续验证。`/init` 为独立的最小系统调用命令循环，
可启动独立的 `/bin/coremark` ELF；它不是完整发行版或通用 shell。

运行 `make coremark-setup` 获取锁定的 EEMBC CoreMark 源码，然后执行
`make gsim-linux-console`。内核启动并出现 `valence#` 后，在交互式 UART 输入
`coremark 1` 可快速检查进程、CRC 和输出；输入 `coremark` 使用 CoreMark 自动校准迭代数，
运行至少 10 秒的目标机时间才能取得有效成绩。输入 `exit` 或按 Ctrl+D 退出 GSIM。
当前交叉 glibc 没有 `lp64` 静态库，所以 `/bin/coremark` 使用官方算法源码和本地
Linux 系统调用适配层，编译为 RV64IMAC 软浮点 ABI 的静态 ELF。计时使用 Linux
`clock_gettime(CLOCK_MONOTONIC)`；无 FPU 构建输出整数秒和整数 `Iterations/Sec`，
短迭代测试中出现的最短时长错误符合 CoreMark 规则，不是 CRC 错误。
本地 GSIM 交互验证中，`coremark 128` 输出 `Total ticks: 11099`（毫秒）、
`Iterations/Sec: 11`、`Correct operation validated`，随后返回 `valence#`；
整数秒输出会截断小数，因此精确吞吐应由迭代数除以毫秒时间计算。
该值是当前 GSIM 时钟配置下的 guest 结果，不代表实际 FPGA 主频或板级成绩。

Linux GSIM 顶层也可选择 4 issue：`make gsim-linux-console ISSUE_WIDTH=4`；
非交互启动检查用 `make gsim-linux-test ISSUE_WIDTH=4`。默认仍为 2 issue。
宽度参数同时控制重命名、执行发射/完成与提交，驱动按顺序记录全部四个提交端口；
2/4 issue 的 GSIM 产物分别在 `build/gsim/linux-platform` 和
`build/gsim/linux-platform-4issue`，共用同一内核、OpenSBI 与设备树。
4 issue 只是宽度配置，不能直接视为最快配置或 FPGA 性能结论。

写回数据 L1 可显式启用：`make gsim-linux-console ISSUE_WIDTH=4 LINUX_CACHE_MODE=coherent`；
非交互检查用同样参数运行 `make gsim-linux-test`。默认 `LINUX_CACHE_MODE=direct`，
两种缓存配置使用独立的 GSIM 产物目录，4 issue + L1 位于
`build/gsim/linux-platform-4issue-l1`。L1 是 128 行、每行 64 字节的直接映射写回缓存。
单 hart 一致性 home 仅记录与 L1 索引对应的 128 个带物理标签所有权槽位，
不会随 64 MiB RAM 容量生成百万项目录；多 hart home 仍有独立的完整性工作。
4 issue + L1 已完成非交互启动，观察到 `/init` 标记与用户态提交。
使用同一份 Linux `Image`、OpenSBI 与设备树的定向 A/B：直连在 128,892,266 周期、
L1 在 175,413,979 周期到达标记（后者多 36.1%）。直连日志在
`build/gsim/linux-platform-4issue-l1/direct-compare.log`；L1 的完整启动日志未保留，
上面的周期数是此前运行记录。启动包含计时器与内核调度工作，
两次退休条数不同；该差值是启动配置结果，不能直接当作缓存缺失惩罚或稳态 IPC。
当前 L1 一次只处理一个缺失，因此保留显式开关，不把它设为 Linux 默认配置。

不等完整启动的固定窗口采样可运行
`make gsim-linux-profile ISSUE_WIDTH=4 LINUX_CACHE_MODE=coherent LINUX_PROFILE_CYCLES=10000000`。
结果写入对应 GSIM 目录的 `profile-10000000.log`，不会覆盖完整启动的 `test.log`。
同一份 `Image` 与 OpenSBI、前 1000 万周期的 128/256 行直接映射 L1 对照：

| L1 行数 | 退休指令 | 缺失 | 已占用槽位替换 | 脏行逐出 | 填充状态周期 | 逐出状态周期 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 | 5,614,331 | 63,879 | 62,401 | 57,145 | 1,534,146 | 1,331,921 |
| 256 | 5,632,610 | 62,656 | 61,025 | 57,019 | 1,504,674 | 1,325,320 |

128 行配置的缺失分为 37,559 次读、26,320 次写。两倍容量只减少 1,223 次缺失
（约 1.9%）；这个短窗口里逐出和整行填充比容量更值得优先处理。
这些是相同周期数的启动前段采样，退休指令数不同，不代表稳态 IPC 或完整启动加速。

当前 GSIM 运行已观察到内核完成 SBI 扩展检测、内存分区、clocksource 切换、
`devtmpfs`、initcall、HVC 和 8250 初始化，最终运行内建 `/init` 并打印标记。
正式 `make gsim-linux-test` 在 178,584,239 周期达到标记，提交 49,655,635 条指令，
并观测到用户态提交；这是启动总量，不能当作稳态 IPC。完整日志保存在
`build/gsim/linux-platform/test.log`。
`make gsim-linux-test ISSUE_WIDTH=4` 在 128,943,169 周期达到同一标记，
提交 45,611,696 条指令，并观测到 220 条用户态提交；日志位于
`build/gsim/linux-platform-4issue/test.log`。两者的启动周期不能代表稳态 IPC。
当前设备树未给 8250 指定可用的 S 态外部中断；内核因此以 IRQ 0 识别 `ttyS0`，
此启动验证证明串口轮询输出，不证明 Linux 串口中断收发。
