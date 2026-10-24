# Debian 性能与监视工具

本工具包是 Debian 用户态候选。主机/QEMU 验证不是 SoC 跑分、板卡验证或任意频率资格。
所有程序默认不切频、不写 MMIO、不启动网络服务。只在用户明确运行 DMA `run` 时发起一次受限测试。
不要使用 devmem 调节频率。切频只使用另行审查的内核策略及已合格 profile。

## 已有系统工具

Debian 正式包提供 `top`、`free -m`、`ps`、`ip -s link show eth0`、`ping`、`iperf3`、`time`、`gawk` 和 Python3。
具体包版本绑定最终 Debian package lock，不是 BusyBox 的同名精简 applet。旧 BusyBox 不支持 `ip -s`，该错误已单独修复。
查看 `dpkg-query -W iperf3 iproute2 procps python3 time gawk` 可读实际版本。

无 RTC 的系统启动墙钟可能错误。`date -u` 检查；apt/HTTPS 需要正确日期及 ca-certificates。
可由用户设置正确时间，或明确启用自己信任的 NTP 服务。本包不自动向外联网、不自动开启 NTP/SSH/iperf server。
没有 Linux 硬件 PMU 驱动，不能把 perf 的硬件 cycles/instructions 假设为可用。下述 clockmon 是独立硬件接口。

## CPU / CoreMark

`valence-coremark` 使用官方固定源码 1f483d5b8316753a742cbf5590caf5bd0a4e4777，单上下文、静态2K数据、-O2 RV64GC LP64D。
默认自动选择至少10秒的运行次数。包装器核对性能种子及三个标准CRC，原程序必须打印最终验证通过。
`valence-coremark --iterations 1000` 仅供短功能检查；不足10秒时返回2并明确不提供有效得分。
保留完整输出、实际CPU/系统频率、编译器版本、负载、硬件/固件身份。QEMU 得分不是板卡得分，也不是官方提交成绩。

## FPU 上下文与算术

`valence-fpu-test` 检查 Linux 宣告 F/D、真实 F/D 指令以及两个进程各200轮的32个浮点寄存器/FCSR保持。
每轮要求带100微秒请求的 nanosleep syscall 成功；不声称测到恰好400次调度切换。
`valence-fpu-test --bench` 另测固定依赖链浮点点积，包含加载开销，不是峰值FLOPS。
QEMU用户态只验证工具/计算行为，不能证明目标内核在实际SoC上的FPU调度正确。

## 私有内存带宽

`valence-mem-bench --sizes-kib 32,256,4096,16384 --iterations 3 --mode both --eviction-mib 16`

仅分配本进程私有内存，不访问固定物理RAM、不覆盖Linux/内核。逐次读checksum、写pattern和copy比较，含前后guard。
输出 read64/write64/copy 的计时payload MiB/s和逻辑读+写MiB/s（copy后者为前者两倍）。
volatile读写和消费checksum避免删除loop；copy使用外部memcpy及compiler memory barrier，操作后验证。
首次触页、核验和独立eviction-buffer压力位于计时区间外。write还包含生成pattern算术；写回尾部未强制排空。
`warmed` 不保证全部命中cache，`pressure` 不保证完全冷cache。本工具不做特权cache flush，也不把CPU可见带宽称为DDR/MIG峰值。
短于1毫秒的总区间标 very_short_interval；可提高iterations或容量，不能用过短计时外推稳定峰值。
默认峰值私有分配约48MiB；大容量可能OOM。先用小容量确认，再按实际空闲内存调整。

## 只读窗口监视器

`valence-clockmon --count 10 --interval 1`

只读内核 coherent snapshot，一次返回CPU/fabric同publication sequence、timestamp和window。
valid=0或当前失效中的窗口不生成速率；flags bit2是正在失效，不是overflow指示。
拒绝未知字段、无效窗口及可能多次回绕的配置；硬件不提供独立overflow计数，不能宣称已观测到溢出。
输出硬件窗口平均，不是瞬时或两次轮询间平均。重复sequence不算新采样；sequence倒退标reset_or_wrap，不相减推测。
raw total是模计数，不跨任意长轮询间隔做差。I1 的 retirement_lanes=1、scalar_request_lane=1 明确表示
retire_lane0 不代表总双发射IPC，scalar_lane1_request_fire也不是退休。旧 I1 无这两个字段的文本标为 legacy_i1_text。
新实验 A1 必须由驱动同时提供 retirement_lanes=2、scalar_request_lane=0：CPU meter ABI2 的 event1 是两条
独立同步退休计数之和模 counter_bits，输出 retire_total_two_lanes_per_cycle；event2 是 scalar_lane0_request_fire，
不是第二种退休计数；event7 是两条 lane 都没有退休。fabric 仍 ABI1。拒绝字段缺半、错配或未知字段。
两 lane 的回绕安全上界是 window*12 <= (1<<counter_bits)-1，I1 是 window*6，fabric 是 window*5。
这些标签来自驱动已经校验的 descriptor/profile 契约，不靠 CPU 名字或计数值猜测。旧 A1 没有监视硬件仍报 unavailable。
工具支持实验 A1 文本不等于 A1 硬件、调频、Linux 或板测已合格。
CPU完整lineGrant可乘64得到该接口refill速率；fabric AXI R/W 只是握手beat，未计字节strobe，不能冒充有效DDR字节带宽。
缺失硬件/不支持profile应明确 unavailable，不能猜地址访问。`--file snapshot.txt` 可离线解析保存的内核文本。

## DMA：状态不是启动

`valence-dma-bench status` 仅展示上次结果，不启动测试。
第一次明确测试：`valence-dma-bench run --bytes 4096 --iterations 1`。
驱动拥有两块 coherent DMA allocation，初始化后copy并逐byte核验，不接受用户物理地址。
只有root可run；8..8388608字节、8字节对齐，1..64次；每次最多等待10秒。
只发一次sysfs写入，EINTR/短写/超时均不自动重试；读回run_sequence、大小、次数、完成/验证和精确速率关系。
超时或fault请保存 status/dmesg，不盲目重复。fault_latched表示可能存在pin住的DMA/内存，需要按驱动诊断恢复。
结果是提交到callback的payload速率，CPU初始化/核验排除；逻辑读+写另列，不是DDR峰值。
避免并发从另一个shell写同一benchmark；generation异常不能归因给本次请求。

## 网络 / netboot

Linux网络容量需独立通信对端。用户在PC明确启动 `iperf3 -s` 后，板上可运行 `iperf3 -c 192.168.137.1 -t 10`，反向加`-R`。
不在无人值守启动server、不替用户改防火墙。区分TCP payload与线速；保存两端实际频率、丢包、重传、协商链路。
`ip -s link show eth0` 和 `/proc/net/dev` 是累计流量，不是容量测试；两次差值需要除以实际经过时间。
`valence-netboot-report host.log uart.log` 离线分析现有TFTP STATS/NB totals，无socket/板卡操作。
主机ACK完成不证明板端最终CRC或Linux启动。板端计时按timebase换秒，不用CPU频率替代。
RX等待含DMA/MMIO/descriptor处理；嵌套/重叠阶段不能简单相加。不得凭低带宽就归因50MHz。

## 构建与安装

`build_tools.py` 使用独立官方交叉工具缓存与已逐byte核验CoreMark源，生成tools-build.json。
所有ELF静态RV64GC/LP64D；Python工具仅标准库。编译后检查实际ELF ISA/ABI/program headers，不只相信文件名。
Debian打包器验证每个SHA、大小和目标路径，再安装到/usr/local/{bin,lib/valence-tools,share/valence-tools}，不覆盖旧文件。
各工具源与链接对象保留在私有构建交付中，CoreMark及系统库许可另附。测试receipt明确host/QEMU-only。
