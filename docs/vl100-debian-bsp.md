# OpenIon Valence VL100 Debian BSP（2026-10-06）

厂商 OpenIon，SoC Valence VL100，CPU Orbital-A1。目标为单 hart、双发射、
RV64GC/LP64D、CPU 100 MHz、UART 460800、完整 2 GiB PL DDR。
本轮软件构建、必要短 GSIM 和新 RTL 整板 100 MHz 静态时序签核已完成，
**匹配 2 GiB 的 r5 bit 已生成；Debian 尚未板测**。
冻结 r4 bit 仍为 512 MiB，且有大帧活性故障，不可加载本设备树。

## r5 硬件交付

已知 r5 UART 勘误（板测确认）：ROM 初始化 DLL=7，实际约 65828.57 baud，
不是标称 460800。ManagedUart 的原始时钟为 50 MHz，但 16550 参考时钟为
7,372,800 Hz；DLL 应为 1。r6 正在重编 ROM 并批量优化 CPU 时序，
使用实际 ROM 指令执行审计与 RTL/DTS 参考时钟交叉检查；未签核前不能当作已发布 bit。

固件目录内 `valence_vl100_rv64gc_2g_cpu100_u460800_r5.bit`，28,700,918 字节，
SHA256 `f3a7a4f902cf8c23e703320e554bcd7fc06928997c49f8e1f3b8a03ca9c24f1a`。
整板 setup/hold/pulse 为 +0.003/+0.003/+0.081 ns，失败端点均 0；
MAC TX setup/hold +0.066/+0.138 ns，RX +0.161/+0.589 ns。
686 项当前 CDC 记录逐项审查，原生 TX 相位/PHY 延时策略不变；
实际 ROM 4,176 项 INIT/INITP 与新 2 GiB BMG 初始化完全一致，bitstream DRC 无错误。
资源 212,161 LUT、105,021 FF、64 RAMB36、3 RAMB18、44 DSP。
F/D 真实启用，不复用旧 CPU 网表；私有工程采用现有板级/DDR/MAC XDC。
旧 GUI 工程和 r4 发布保留，未烧录板卡或代用户启动网络流量。

本轮增量参考读取遇到缓存错误，保留失败日志，改从自身干净 optimized.dcp
进行完整布局布线；最终又从自身 routed.dcp 优化取指链，未重跑综合、
降频或放宽约束。早期汇总 +0.003 ns 曾被最后全局复查的 -0.005 ns 否决；
交付使用再次优化后、重新打开检查点仍通过的结果，不沿用早期汇总。
所有必要 bit/检查点/报告/发布证据归档在
`build/fpga/ddr2g-20261006-r5/release-qualified`，
当前路由审查在同根 `routed-proof-r2/completion.json`。
裕量薄；先复测启动、2 GiB 高地址、长 ping 和 DMA，再做性能压力测试。

## 内存和硬件

| 区域 | CPU 物理地址（两端包含） | 用途 |
| --- | --- | --- |
| BootROM | 0x80000000–0x8001ffff | 128 KiB BMG，UART/TFTP接收与引导 |
| DDR | 0x80200000–0x1001fffff | 完整 2 GiB，跨 4 GiB |
| OpenSBI | 0x80200000 起 | 固件在运行时添加自身保留区 |
| DTB | 0x80300000–0x8030ffff | 嵌入 OpenSBI，启动时搬运 |
| Linux | 0x80400000 起 | 包含 Debian initramfs |
| ROM 工作区 | 0xffff8000–0xffffbfff | 16 KiB，DT no-map |

ROM 编译采用 medany；若将工作区直接移到新 RAM 顶端，会超出有符号 PC-relative
寻址范围。因此工作区保留在 4 GiB 以下，Linux 仍发现完整 DDR 并扣除正常保留区。
连续平坦下载上限为 0x7fdf8000 字节，不是全部 DDR 可用容量。
v1 下载头的 32 位 base/entry/length 足够此连续区，不支持随意加载 4 GiB 以上 ELF 段；
Linux/DMA 的运行时物理地址保持 64 位。

容量参数改为 BigInt，旧默认仍为 512 MiB，新配置显式指定 2147483648。
TL→AXI 接受请求时先按完整物理地址减 0x80200000，再产生 MIG 偏移：
0x100000000 → 0x7fe00000，最后 8 字节偏移为 0x7ffffff8。
越界读写 denied且无 AXI流量；MIG 31 位偏移/物理颗粒配置保持不变。
不能先截断 CPU地址、不能只改 DT。

生产 RTL 导出（不是综合命令）：

    mill -i IonSoC.test.runMain ooo.ManagedBoardSocMain <fresh-output> 100000000 staged-fetch-feedback 460800 rv64gc 50000000 50000000 250000000 2147483648
    python3 fpga/firmware/build.py --ddr --ddr-bytes 0x80000000 --netboot --cpu-hz 100000000 --uart-divisor 1 --uart-reference-hz 7372800 --uart-baud 460800 --out <fresh-ROM-output>

新 bit 必须同时采用 Home 被背压普通读保持修复、完整地址映射和新 ROM 数据。
本轮生成 ROM 10,376 字节；工作区/栈链接成功，未装入任何旧 Vivado 工程。

## Linux 驱动

| 日志/驱动名 | 模块 | 作用 | IRQ |
| --- | --- | --- | --- |
| valence-soc | valence_soc.ko | 标准 SoC bus 配置身份，不伪造 silicon revision | 无 |
| valence-aia | valence_aia.ko | 单 hart CSR IMSIC/APLIC适配和自检 | CPU SEIP |
| valence-cmu | valence_cmu.ko | 0x10080000，CCF 固定频率提供者 | 本版不启用 CMU IRQ |
| valence-dma | valence_dma.ko | 0x10001000，通用 memcpy DMAengine | APLIC 4 |
| valence-gmac | valence_gmac.ko | MAC 0x10040000，专属 packet DMA 0x10002000，IRQ+NAPI | APLIC 6 |

通用 MemoryCopyDma 在 MachinePlatform 常驻启用，GMAC packet DMA 是独立引擎，
二者共享一致性 Home。通用 DMA：8 字节对齐、RAM内不重叠复制、四个信用、
单 channel；没有 SG、字节尾部、memmove、外设握手或强制中止。
测速超时而硬件未排空时保留 channel/buffer，并报 RESET REQUIRED；
不释放仍可能被 DMA 写入的内存。

CMU 通过 CCF管理固定频率资源0–6，只允许已接真实门控的 UART/TX/RX叶子域。
UART critical，CPU/TIME/AON/DDR 不停；GMAC获取 TX/RX 时钟并保持运行。
没有 GMAC runtime-PM 自动停钟、动态调频、热复位或可写 sysfs门控。
默认时钟已使能，BootROM 不需要先加载 Linux 驱动。CMU wake IRQ默认关闭，
避免持久 RX wake引起中断风暴。

自研驱动统一 valence-* 日志，上游 Realtek PHY/UART 仍保留上游名称。
现有 compatible 字符串保持 ABI，新增 OpenIon CPU/SoC 身份。
不能直接替换 Debian通用 SMP内核：当前 IRQ适配无多 hart/标准 MSI aperture。

## Debian 软件和启动

Debian13 trixie riscv64官方 minbase，113 个包，通过官方 keyring/InRelease签名校验。
QEMU-user 仅用于 WSL外架构包安装与工具检查，不是 Valence硬件验证。
含 bash/glibc/apt/dpkg、iproute2/ping/ifupdown、ethtool/iperf3/tcpdump/strace/procps，
另带 coremark、fpu-test、fastfetch、net-bench。
项目 UP Linux7.3.0-rc5+、OpenSBI v1.9、五个同版本驱动构建匹配。

轻量 /init → BusyBox init → Debian login/bash，不是 systemd。
串口 root自动登录，无 SSH服务，无持久块设备；apt安装结果复位后丢失。
自动加载 SoC/AIA/CMU/通用DMA；AIA自检通过后 GMAC/ifup eth0。
失败仍保留串口 shell，不自动测速。内核/初始化日志带时间戳。

静态IP在 /etc/network/interfaces，默认192.168.137.30/24、网关192.168.137.1，
不写死在驱动。DNS在 /etc/resolv.conf；PC .1需提供共享/DNS服务才能当DNS。
无 RTC，启动明确用镜像构建时间初始化 UTC。
100 MHz FPGA上 Debian比 BusyBox重，约60MiB压缩 initramfs解压/程序启动会增加耗时，
不应视为性能优化。

BootROM请求的文件名必须为 valence.vld。仅新 2 GiB bit 可用：

    python .\netboot_host.py serve .\valence.vld --memory ddr2g --bind 192.168.137.1
    python .\uart_load.py COM4 .\opensbi_debian13_riscv64_vl100_cpu100_u460800.bin --memory ddr2g --baud 460800 --run --console

板端先执行：

    valence-info
    net-status
    fpu-test
    dma-bench 1048576 4
    dma-bench 8388608 4

DMA报告 payload B/s、logical R+W B/s、DMAengine submit→callback时间。
CPU填充/比较及 UART输出不计时，仍含 IRQ/调度开销，不是 MIG峰值。
主机 iperf3 -s，板端 iperf3 -c 192.168.137.1 -t 10；先验证长ping/IRQ/DMA再施压。
本轮未代用户启动主机或板端网络服务。

## 证据及尚未验证项

- build/gsim/ddr2g-20261006-r8/receipt.json：新AXI24事务、DMA10场景、62,805解码向量；
  旧桥9事务、旧DMA48场景；5组负向oracle拒绝，ASan/UBSan，生产 RV64GC+2GiB RTL导出。
- build/gsim/network-packet-pressure-20261006-2g-r6/receipt.json：144大帧压力+24一致性正例，
  3组独立数据错误注入拒绝，缩小8KiB模块平台，不是2GiB板测/Linux运行。
- build/fpga/debian-vl100-2g-20261006-r4/kernel-build.json：五驱动 W=1无警告、vermagic匹配；
  不完整 DMADEVICES配置失败尝试保留在 failed-attempts。
- build/fpga/debian-riscv64-20261006-r2/rootfs-build-vl100-2g-r5.json：签名来源、
  包清单、五模块depmod/dry-run、init语法和GNU工具检查。
- build/fpga/debian-vl100-2g-firmware-20261006-r6/manifest.json：exact gzip rootfs/DTB、
  OpenSBI/kernel布局和镜像哈希；未板端启动。

新 routed 时序/bit 已完成；IRQ 驱动运行、DMA 带宽、2 GiB 物理容量和
Debian 稳定性仍待板测。签核使用 r5 新检查点，不继承 r4 的小正 WNS。
