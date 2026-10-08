# Linux 启动实验

网络地址为固件随附的示例默认配置，实际部署需按本地网络调整；
`${VALENCE_ROOT}` 和 `${EVIDENCE_ROOT}` 代表可配置的工程与证据根目录。

## 2026-10-06：OpenIon VL100 Debian / 2 GiB BSP

官方签名 Debian13 riscv64 minbase、LP64D用户态、UP内核、五个自研驱动已构建，
自动初始化静态IP网口，新增CCF CMU、DMAengine/dma-bench与完整2GiB地址重构。
地址和Home大帧压力短回归通过，没有新bit或Debian板测，见 [VL100 BSP](vl100-debian-bsp.md)。

## 2026-10-06：r4 长帧卡死与 r5 Home 活性修复候选

用户已在 `native-rv64gc-netboot-20261006-r4` bit 上完成 BootROM TFTP 和 Linux
启动：6,806,956 B / 6.88 s，约 0.944 MiB/s。此为板测传输结果，不是千兆峰值。
但 Linux TCP TX/RX 测速均卡住且 Ctrl+C 无效。进一步板测：Windows 向板卡发送
32 B ICMP payload，3/3 回复且约 2 ms；1400 B ICMP payload 则板端 Linux 卡死。
Windows 不响应入站 ICMP 不能解释这一反向测试，故障不依赖 TCP 测速协议。
启动/小流量 IRQ 与 NAPI 计数正常不代表长帧路径已验收。

短 GSIM 复现到一个实际 RTL 缺陷：`CoherentLineHome` 已向下游提供普通读且被背压时，
后来出现的 L1 Acquire/voluntary Release 会撤销这个读。共享 TL 仲裁器却已锁定
普通请求的 A 生产者，Home 转而等待不能通过该仲裁器的 line refill，形成循环等待。
封存旧模型快照为 cache=fill、home=fillWait、line reader=send、outer arbiter locked
to ordinary bridge、backing replies=0，连续 2000 周期无 CPU/DMA 完成。
这是精确旧模块 FIR 的可复现缺陷，不是已取得的板卡内部总线轨迹；尚不能宣称
所有板端故障均已排除。

候选修复仅在 WSL 源码：保持被背压的普通读，直到下游接收，再准许 Acquire/Release。
正常读路径不插入额外流水级；未测新的整核 IPC、整板资源或 routed 时序。
新增夹具断言检查 Home 下游 valid/payload 在背压期间保持；独立 CPU word/byte
oracle 检查数据，不读取 DUT 私有状态生成预期（私有快照仅用于失败诊断）。
原有独立 MAC/DMA 大帧测试覆盖到 2048 B，但原一致性测试仅用 8/13 B，不能替代
新增长帧+CPU 4 KiB 工作集换入换出/原子/uncached/四 DMA credit 的并发验证。

本轮短验证：1-way/4-line、2-way/4-line、2-way/32-line（启用生产 Home metadata
优化）各 48 组压力与 8 组原有 probe/FIFO/home 回归，共 144+24 正例，三组独立
数据错误注入均按预期失败，ASan/UBSan 开启。32 行夹具仍是缩小的 8 KiB RAM
模块平台，不是执行 Linux、真实 CPU/IRQ、MIG、RGMII 或整板验证。
复用第一份已发射模型前严格核对未变 RTL/夹具，保留初版 TX 尾字 mask 错误的
夹具失败记录；最终夹具与真实 DMA 一致：TX 总是完整 64-bit 读，RX 才用尾字部分写。

证据：`build/gsim/network-packet-pressure-fixed-20261006-r5/receipt.json`；
相同最终压力驱动、封存旧 FIR 的失败对照在
`build/gsim/network-packet-pressure-control-20261006-r5/receipt.json`，只确认旧模型
预期死锁，不能单独作为新 RTL PASS。可复现入口（使用全新 tag，不覆盖旧日志）：

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/network_packet_pressure.py --tag NEW_TAG \
  --control-receipt build/gsim/network-boot-checks-20261006-r3/receipt.json
```

本轮未重新综合、布局布线或生成 bit；已交付 r4 bit/固件及其 SHA256 完全不改。
该硬件修复不能通过替换 Linux 镜像交付，须后续签核新 bit，再板测大小包和
TCP TX/RX。当前 BusyBox `ip` 不支持 `net-status` 中的 `ip -s`，诊断先用
`cat /proc/net/dev`，不要把其 Usage 输出当成网卡状态。

## 2026-10-06：BootROM 网络启动开发阶段记录（当时未发布新 bit）

此开发阶段 r3 镜像是 RV64GC/lp64d、双发射、CPU/timebase 100 MHz、UART 460800、
native GMAC IRQ/NAPI；用户已启动 Linux 和打通 ping，但大块 TCP TX 会卡住，
不能据此宣称网卡吞吐或稳定性验收。下方 DDR50 和旧 DDR100 章节仍是历史记录。

新网络引导在 BootROM 内完成，不是 Linux wget，也不是主机主动向任意地址写 RAM：
上电从 SoC 192.168.137.30 向同网段电脑 192.168.137.1 发 ARP + TFTP RRQ，
取 valence.vld，校验头部/范围/流 CRC/实际 DDR CRC，安全停止 DMA/MAC 后
以 M-mode 跳到 OpenSBI 0x80200000（a0=a1=0）。Linux 仍位于镜像内的 0x80400000。
主机只需先启动服务；没有自动修改防火墙或启动测试流量。

这是可配置实验：build.py 默认 UART-only；--ddr --netboot 才启用网络自动尝试。
失败回到 UART；d 可中断尝试进入 UART 下载，n 可重试 TFTP。不增加 > 提示符或 ROM 测试菜单。
网络配置可由 --netboot-ip、--netboot-server、--netboot-file 选择。
本阶段无 DHCP、跨网关路由、TFTP options、IP 分片或安全签名；只在可信直连网络使用。

ROM 容量仍 128 KiB，网络版代码约 10 KiB；尾部 16 KiB 引导保留区不变，
globals/RX/TX 缓冲限制 8 KiB，另留至少 8 KiB 栈，不侵入下载镜像。
需要本批 RX_STOP-capable 新 RTL/ROM 一起生成 bit，不能直接给旧 bit 替换这份 COE。
新 100 MHz 整板时序、PHY/网络启动、TCP 冻结是否消失均未板测。

WSL 编译及协议短验收（不跑 Linux/整板 GSIM/综合）：

    python3 fpga/firmware/check_netboot.py --out build/fpga/bootrom-netboot-checks-20261006-r1
    GSIM_CXX=clang++-19 python3 simulator/gsim/network_boot_checks.py --tag NEW_TAG

主机脚本位于 fpga/firmware/netboot_host.py，先 pack 原有完整 OpenSBI fw_payload BIN，
不是只打包 Linux Image；默认入口 0x80200000：

    python netboot_host.py pack opensbi_linux_rv64gc_cpu100_u460800_gmac_fpu.bin --out valence.vld
    python netboot_host.py serve valence.vld --bind 192.168.137.1 --board 192.168.137.30

服务使用 UDP 69 收 RRQ，再用动态 UDP TID 传数据；若 Windows 防火墙拦截，应由用户
为此 Python 进程在指定直连网络放行，而不是只放 UDP 69。换 valence.vld 不用重新综合，
首次接入新 BootROM/DMA 功能则需要更新 bit。速度以板测为准，不宣称千兆线速。

本文记录 **DDR50 / 512 MiB 板级 Linux 镜像**、未发布的 **DDR100 / 460800 候选**
与历史 **64 MiB GSIM 配置**。
历史周期、提交数和版本保留为对应运行记录，不是本次重新跑出的结果。
软件适配先读 [OS 移植指南](os-software-porting.md)，完整地址和寄存器分别见
[SoC datasheet](soc-datasheet.md) 与 [寄存器手册](soc-registers.md)。

## 当前源码调整（2026-10-08）

新构建已移除自编译 fastfetch、相关源码/CMake 工具包依赖和开机调用；基础 BusyBox、
联网和 Debian 三条 rootfs 流程均不再依赖该程序。BusyBox shell、CoreMark、原有网络与
诊断工具继续保留。长 Linux GSIM 的用户态检查改为 shell、`uname -m` 和返回提示符。
本轮未重建大镜像、未跑长 Linux GSIM、未板测。下节已有镜像及其大小/哈希/fastfetch
记录保留历史事实，不表示当前源码还要求 fastfetch。当前命令及源码说明见
[固件 README](../fpga/firmware/README.md) 和 [Debian BSP](vl100-debian-bsp.md)。

## DDR50 板级镜像：BusyBox + fastfetch（2026-10-01 历史）

保持已板测的双发射、2 KiB 两路 D-L1、CPU/timebase 50 MHz 和 UART 115200 8N1。
128 KiB ROM 下载监控程序进入 M-mode，`a0=a1=0`；因此不能把 Linux Image
直接作为 UART 入口。新的单一平坦 BIN 是 OpenSBI v1.9 `fw_payload`，包含设备树、
Linux 和 gzip 内建 initramfs；无须增加 F/D 扩展或为换程序重新综合。

| 区域 | 地址/范围 | 用途 |
| --- | --- | --- |
| PL DDR | `0x80200000..0xA01FFFFF`，512 MiB | CPU 可见容量，不冒充完整颗粒容量 |
| OpenSBI / BIN 入口 | `0x80200000` | M-mode 固件，自动添加固件保留区 |
| DTB 搬迁槽 | `0x80300000..0x8030FFFF` | 固件内嵌 DTB，传给 Linux 的 a1 |
| Linux Image | `0x80400000` | 2 MiB 对齐的 S-mode 入口 |
| BootROM 监控程序保留区 | `0xA01FC000..0xA01FFFFF` | Linux `no-map`，不得用作普通内存 |

本地 Linux 提交 `551c722f40809618230001baccf219193e22fc5a`，版本 `7.3.0-rc5+`；
OpenSBI 提交 `cbf9f6734dd85a982c63e3cb5db7ffe09da839ca`。
上游源码没有修改，均使用独立 O= 构建目录。
用户态是静态 musl 1.2.5、BusyBox 1.37.0 和真正的 fastfetch 2.69.0，
ISA/ABI 为 `rv64imac/lp64`；ELF 静态链接/soft-float/无 F/D/V 属性已检查。
`float/double` 软件运算仍可使用，但通用发行版的 `lp64d` 程序不能原样运行。
Kernel `CONFIG_FPU` 关闭，设备树不宣告未实现扩展。

```sh
# WSL ${VALENCE_ROOT}；先准备脚本列出的固定版本源码/交叉工具
python3 fpga/firmware/build_rootfs.py --jobs 16
python3 fpga/firmware/build_linux.py --jobs 16
python3 -m unittest discover -s fpga/firmware -p test_linux_image.py
GSIM_CXX=clang++-19 python3 simulator/gsim/board_linux.py \
    build/fpga/linux-ddr50-busybox/opensbi_linux_ddr50.bin
```

构建产物在 `build/fpga/linux-ddr50-busybox`；manifest 记录全部镜像/配置/源码哈希。
打包逐字节核对内核，允许且只允许 OpenSBI 汇编/链接对齐产生的有限零填充。
512 MiB 是物理内存窗口，内核运行时大小、DTB 与 ROM 保留区均独立检查。
`--rootfs minimal --out build/fpga/linux-ddr50-minimal` 是无 BusyBox 的诊断选择，
不能把它当作最终用户态镜像。

使用匹配的 DDR50/115200 FIFO bit；最新 ROM-only 修复版为
`${EVIDENCE_ROOT}/ddr-opt-20261001/bootrom-fix/release/valence_ddr50_uart115200_fifo.bit`，
SHA256 `FBADD8F0CA86BA847A86F42DB93105C6F4193DB8458E884F9F184F2D04C9277C`。
该 bit 不包含新的 registered-replay 候选。关闭其他串口窗口、复位回下载模式后运行：

```powershell
python .\uart_load.py COM4 .\opensbi_linux_ddr50.bin --memory ddr --baud 115200 --run --console
```

不要把 `--entry` 改到 `0x80400000`。约 5.15 MiB 镜像以 115200 8N1 上传的线速下限
约 7.8 分钟，校验/协议还会增加时间；显示 Upload 进度时不是内核卡住。
预期输出 OpenSBI、Linux、fastfetch 系统信息，然后进入 `valence#` BusyBox ash。
可输入 `uname -a`、`free -m`、`cat /proc/cpuinfo`、`fastfetch`；
`coremark 0 0 0 1` 只作短功能检查，不是有效成绩。

控制台经 SBI DBCN/hvc0 轮询；UART 参考频率是 1,843,200 Hz，不是 CPU 50 MHz。
未宣告标准 PLIC/AIA：现有 IMSIC 内部 MSI 接口并非标准 CPU MMIO 门铃，
不能仅加 DT 节点就声称 Linux 外部中断驱动已适配。
没有网络、SD/eMMC、块设备或持久化根文件系统；复位会丢失 RAM rootfs 改动。
GSIM 直接预载相同 BIN，仅跳过 UART 上传；使用独立 AXI 延迟/背压模型，
不是 MIG、CDC、电气或真实板级验收。实际启动结果以 manifest 和用户板测为准。

本轮镜像 5,394,424 B，SHA256
`2EDF8701DF17F6837A88E03149DBD53BF60161E944C3FBB5F402B555DEC0763D`。
GSIM 已观察到 OpenSBI→S-mode Linux、512 MiB 内存和 50 MHz timer，
最后进度为 320,000,000 cycles/73,342,600 commits，正在 gzip 解压/创建 rootfs 文件。
用户要求直接上板调试，已仅终止本轮长测试；**未完成用户态 init/shell/fastfetch/交互验证**，
不计作 PASS。完整日志随镜像以 `gsim-interrupted.log` 保存。
发布目录 `${EVIDENCE_ROOT}/linux-ddr50-20261001`，包含同哈希 BIN、ELF、
Image、DTB、配置、manifest、下载工具与使用说明；板级启动仍需用户验证。
后续用户要求优化 SoC 后试 460800：需同时修改 RTL UART 参考时钟、BootROM、DTB，
完成新 bit 签核/板测；当前 115200 镜像不随主机 `--baud` 自动改变。

## DDR100 / 460800 候选镜像（2026-10-02，尚未发布 bit）

用户选择 CPU 100 MHz，且只有整板时序签核通过才交付 bit；不能以 OOC 综合
正裕量代替整板验收，也不能自动退回 50 MHz。新候选仍为两发射，采用
`staged-request-capture`。BootROM、RTL UART 参考频率和设备树已经统一为
100,000,000 Hz timebase、460800 baud、7,372,800 Hz UART 参考频率。

候选目录为
`${EVIDENCE_ROOT}/ddr-opt-20261002/request-capture-board-u460800/`；
镜像在 `linux-final/opensbi_linux_ddr100_uart460800.bin`，大小 5,394,424 B，SHA256
`ee6acac8ea584092014129bad3ff8f4c52466aba34afc5b8a0a1612f4d6f84ca`。
入口仍是 `0x80200000`，Linux/DTB/保留区布局不变。复用已构建的同哈希内核和
BusyBox/fastfetch initramfs，仅重编 OpenSBI payload 与参数化 DTB，逐字节核对
嵌入内核/DTB及运行时地址；没有重新构建或修改上游内核。

此镜像 **不能与旧 DDR50/115200 bit 配套使用**。当前 manifest 的
`on_board_verified=false`、`gsim_verified=false`：没有声称新 Linux 镜像已经
启动到 shell。为节省时间未运行长 Linux 仿真；只运行了匹配 100 MHz/460800 的
BootROM/UART 短回归，覆盖连续 8N1、头部/分块/全镜像 CRC、边界、重传、
DDR 大镜像头部及 RAM sample 的下载/执行，16,775,778 cycles，通过。
GSIM 不证明物理 UART 波形、MIG PHY、板级 CDC 或真实 100 MHz 时序。

只有对应新 bit 通过整板 setup/hold/pulse-width、CDC/reset、bus-skew、完整布线
和 DRC 签核后，才可用该镜像在 460800 baud 上板；旧稳定 bit 和镜像保持不变。
本次整板实现的布局 WNS -0.932 ns，拥塞布线在有界超时后停止，未生成可签核
routed checkpoint 或 bit；因此目前不能将这个候选当作可上板发布。
详见 [本次整板实现记录](fpga-timing-windows.md)。

## 历史 64 MiB GSIM 平台

下列记录属于另一套仿真平台，不是 DDR50 板级镜像。此前 ZU15EG 使用 128 KiB ROM、
`0x80200000` 起 1 MiB UltraRAM；这已由 DDR50 配置扩展到上述 512 MiB PL DDR。
现有历史 GSIM Linux 成功不证明新板级启动或 FPGA 时序。

`make gsim-linux-setup` 从 `~/board/linux` 的当前 Git 提交只读生成源码快照，构建独立的
RV64 Linux 内核和小型内建 initramfs；不会改动上游 Linux 源码。`VALENCE_LINUX_SOURCE`
可指定其他本地 Linux 源码目录。下述启动记录使用的本地提交为
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
这份 64 MiB RAM 是历史 GSIM 启动模型；默认 `MachinePlatform` 仍为 4 KiB，旧 UltraRAM 板级为 1 MiB。
Linux 的 `0x80200000` 在这里是 RAM 内的内核装载地址，板级同一地址才是 RAM 起点。
FPGA DDR 接口、资源占用和时序均未由此验证；原样复用当前 GSIM 的镜像布局会落到板级 RAM 之外。

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
