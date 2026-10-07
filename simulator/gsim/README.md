# 新乱序核的 GSIM 仿真入口

Opt-in memory-capacity experiment (2026-10-07): `staged-fetch-turnover-mlp4`
changes only `memoryEntries` from 2 to 4 and preserves all existing profiles/defaults.
Run `python3 simulator/gsim/memory_capacity.py --tag UNIQUE_TAG` with the configured GSIM toolchain.
[Bounded checks and exact matched-RVC results](../../docs/memory-capacity-experiment.md):
486605 → 472290 ticks (2.94% fewer), byte-identical 360528-PC ROI and matching CRCs.
Physical timing/resources remain unverified; the candidate is not a default replacement.

Opt-in load-to-registered-issue experiment (2026-10-07): `staged-load-issue`
keeps existing profiles unchanged. [Contract and validation status](../../docs/registered-load-issue-forwarding.md).
Focused GSIM A/B passed: one-iteration board CoreMark ticks 834653 → 831768 (0.346% fewer); DDR essentially unchanged, including a 5-tick COPY regression. Physical timing remains unverified; this opt-in experiment is not a default bitstream replacement.

VL100 2GiB必要短验证（2026-10-06）：运行
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr2g.py --tag <fresh-tag>，
核对完整物理地址翻译、稀疏高地址DMA、精确译码、旧配置和独立负向oracle，并导出生产RTL。
通过记录：build/gsim/ddr2g-20261006-r8/receipt.json；
当前Home压力重测：build/gsim/network-packet-pressure-20261006-2g-r6/receipt.json。
不证明Debian运行、物理2GiB容量、新布线时序或bit，匹配配置见
[VL100 Debian BSP](../../docs/vl100-debian-bsp.md)。

系统/FPU/PMP/返回控制结构批次（2026-10-06）只跑受影响短验证：

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/soc_return_control_batch.py \
  --tag UNIQUE_TAG --coremark-baseline build/gsim/rv64gc-board-soc-window-20261006-r2/receipt.json
```

先完成整批源码，再统一编译；独立 128 位 byte-range PMP oracle 覆盖 2/4 宽及
XLEN/优先级边界，桥接覆盖乱序/背压/无效载荷扰动，SoftFloat 覆盖 fd/f/pruned，
最后跑真实 CPU NEMU/恢复、F/D 上下文和同二进制单迭代 CRC/tick 对照。
CoreMark 单迭代不是有效分数，短功能检查不是整板 STA/CDC/上板证明。
`--resume-units` 只接受已记录的桥负例退出码包装错误；要求源码/参考模型不变、
旧 artifact 散列及新导出的 FIR 完全一致，重新运行正/负例，不复用变化后的 CPU。

真实受管 UART/原生 GMAC/DMA adapter 必要短批次：

```sh
GSIM_CXX=/usr/lib/llvm-19/bin/clang++ python3 simulator/gsim/managed_peripherals.py --tag UNIQUE_TAG
```

真实引擎仍只用GSIM；单时钟alias/复位沿采样，不证明异步复位或物理门控。
真实BUFGCE/delay/proxy/bridge/counter仅CDC短xsim用
`fpga/zu15eg/run_managed_peripheral_cdc.py`，无UART/MAC/CPU xsim。生产可选入口、
证据与模块OOC限制见 [受管外设验收](../../docs/managed-peripherals.md)。

CMU局部短验证（2026-10-04）：

```sh
GSIM_CXX=/usr/lib/llvm-19/bin/clang++ python3 simulator/gsim/clock_management.py --tag UNIQUE_TAG
```

只跑常开CSR/策略、原生TL与两种真实MMIO Router，不执行CPU程序；四个独立错配负例必须失败。
生成 `build/gsim/clock-management-UNIQUE_TAG/receipt.json` 和分离的资源银行/CDC RTL。
BoardSoc默认CMU关闭；生产可选入口/受保护时钟清单见
[CMU寄存器](../../docs/soc-registers.md#cmu-v1独立常开时钟管理单元可选)。
物理门控CDC仅用已获授权的原生Windows短xsim：
`fpga/zu15eg/run_managed_clock_cdc.py RTL_CDC_DIR FRESH_OUTPUT_DIR`，需要Vivado自带BUFGCE/
glbl模型；没有CPU/MAC/PHY/整板仿真。不用GSIM不同输入边沿的单clock近似冒充CDC验证。

2026-10-04：`gsim-gmac-ready-test` 是三项前端优化的短 PMP/reservoir/NEMU/IPC A/B，
记录在 `build/gsim/gmac-ready-20261004-r1/receipt.json`。CPU 仿真仍只使用 GSIM。
由于固定 GSIM 的独立时钟探针不支持不同输入边沿，用户仅批准新增 CDC 模块用
`fpga/zu15eg/run_cdc_xsim.py` 做双时钟短 RTL 验证，不扩展为 CPU/整板 xsim；
实际模块与复位/约束边界见 [时钟域记录](../../fpga/zu15eg/clock-domain-plan.md)。

此目录运行独立于旧顺序核的 Chisel 模型。唯一受支持的仿真后端是 GSIM；Verilator 及旧 emu 入口已退役。
默认裸核测试可运行固定 32 位编码的整数、条件分支、调用/返回及 load/store 程序，包含编译的 C 栈/数组程序，并按提交顺序与 NEMU 比较。可选 RV64C 平台已运行混合 16/32 位固件和 CoreMark 工作负载；其覆盖范围及性能口径见 [RV64C 与 CoreMark](../../docs/rv64c-coremark.md)。
**LSU 默认四槽，普通 RAM load 可并行；显式普通 RAM 可提前 load，store 与其他地址读取只在队首执行，GSIM RAM 写已接四项不可撤销缓冲。独立 MachineCore 配置已支持基础 M/S CSR、同步陷阱委托、MRET/SRET 和 M/S IMSIC 文件桥接；已接 M/S 外部中断、SSI 和 Sstc 定时中断；MachinePlatform 另有默认关闭的共享读缓存，尚未完成完整 RV64I/RVA23 或生产 SoC。**

## 目录

2026-10-03 focused acceptance: `finalpaths-batch2b` 的必要短 GSIM、独立 NEMU A/B
和严格故障注入反例通过；collector 为 `throughput-ddr100-20261003-finalpaths-batch2-accepted`。
对应双发射冻结候选已完成真实整板 100MHz / UART460800 静态签核并生成 bit，
WNS+0.101ns/hold+0.010ns/pulse+0.081ns，详见 [FPGA 证据](../../docs/fpga-timing-windows.md)。
不因此声称完整 Linux GSIM、真实上板启动、DDR 带宽或正式 CoreMark 成绩通过；
匹配 OpenSBI+Linux 镜像的物理验收仍由用户进行。本批未重复全量/长 Linux 仿真。

晚间接续：用户已报告该整数版在实际板卡启动 Linux 并跑过 CoreMark CRC；
尚不等价于长压力验收。F/D 源码现已授权合入原 `/home/openion/Valence`，仍默认关闭，
完整基础 F/D 功能候选已实现且短验收通过，但不代表 F/D 整板 bit 或 Linux FP
上下文已验收。新增浮点时序批次和短 GSIM 验收见本页末尾。

`harness/` 存放 C++ 驱动与独立模型，`payloads/` 存放当前指令子集的汇编测试与链接脚本，
`config/` 存放工具链/参考版本锁和 NEMU 配置；`run.py` 与 `reference.py` 为统一入口。
可复用的旧汇编程序与参考配置位于 `../../legacy/simulator`；退役驱动和 firmware 已清理，见 [目录说明](../../docs/layout.md)。

## DDR50 focused 验证

### 自研 GMAC 公共模块短入口（2026-10-04）

```sh
GSIM_CXX=/usr/lib/llvm-19/bin/clang++ python3 simulator/gsim/self_gmac.py --tag 20261004-local1
```

只运行 `SelfGmacParamsSpec`、完整 SV 导出、RV64 软件 header 编译和 CRC / MDIO /
native TL-UL CSR 三个小模型（ASan/UBSan）；不跑 CPU/NEMU、全量 GSIM、Linux 或 Vivado。
标签必须唯一，拒绝覆盖旧证据。CRC 为独立逐位参考；MDIO 为独立线上位序和 TA 参考；
TL 为独立寄存器/信用模型，另含 TL→MDIO 启动、串行读写/无应答、忙背压、结果/IRQ、复位。
每个模型必须拒绝独立错误注入，TL→MDIO 位序也有自己的负例。
receipt 冻结输入、完整 SV、模型/驱动 hash，并核对所有非 Ethernet 的 main Scala 未变化。

r2 初始通过：CRC 20195、MDIO 96、TL 3045，状态 `passed_foundation_only`。
r3 最终全部通过，增加 CSR→MDIO 4 次完整帧、23 次请求、462 拍 busy START 背压，
noAck/IRQ/W1C/复位及位序负例；`build/gsim/self-gmac-20261004-r3/receipt.json`。
该入口没有 MAC 帧引擎、RGMII/DDR/DMA 联调、10G MAC/PCS 或板级时序资格；
不得把随机输入事件当作真正收发包。用户要求先千兆，10G 暂留 SFP1 规划。

### 自研千兆帧 / DMA 联动短入口（2026-10-04）

```sh
GSIM_CXX=/usr/lib/llvm-19/bin/clang++ python3 simulator/gsim/self_gmac_frames.py --tag 20261004-local1
```

一次Scala编译/3项参数检查和完整SV导出，三小模型：GMII TX/RX帧、DMA原生帧适配、
真实 `EthernetPacketDma` + adapter + TX/RX 联合。ASan/UBSan、独立逐位CRC/内存字节
参考与三独立错误注入；不运行CPU/NEMU/全量GSIM/长Linux/Vivado。标签唯一、输入冻结，
保护所有非Ethernet主源码（包括原DMA/CPU）哈希，禁止验收中漂移。

最终 `build/gsim/self-gmac-frames-20261004-r3/receipt.json` 为
`passed_single_clock_frames_dma_only`：帧246例/113 TX wire/117 RX、96适配例/23936 beats、
54真实DMA联合例/四项信用。RX坏FCS不写内存且下一好帧无需重arm，故障排空/重启、
全尾掩码、IRQ、满缓冲整帧丢弃与frame reset cancellation已覆盖。r1驱动编译失败保留；
r2功能通过但之后CAD发现RX多写端口推断回退，修复后的r3是最终候选。

RX只有单帧RAM，未做到持续线速；无RGMII PHY或独立输入边沿，也不验证Linux驱动。
新三模块轻量8/8/10ns OOC CAD单独记录，不重复CPU/整板；最终
`build/fpga/self-gmac-frames-20261004-r1/audit-final.json` 内部 setup/hold 通过。
这不是 PHY/CDC 接口资格，不能用这份单时钟 receipt 或模块报告生成一个假称
“网口可用”的 bit。资源、时序与下一步见 [DMA](../../docs/dma.md)。

### 原生帧/配置/事件 CDC 与安全停钟（2026-10-04）

固定 GSIM 不能验收独立输入边沿，本批按用户已授权的 CDC-only xsim 例外：
`ip.SelfGmacCdcSpec` 参数检查，`ip.SelfGmacCdcMain` 仅导出 CDC/retention policy，
Windows `fpga/zu15eg/run_self_gmac_cdc.py RTL FRESH_OUTPUT` 运行三时钟短测。
不实例化 CPU、GMII frame engine、DMA 或 PHY，不使用其他硬件仿真后端。
最终证据 `build/fpga/self-gmac-cdc-20261004-r1/functional-r4/receipt.json`。
4组独立时钟、双向20480拍、640配置拷贝、暂停时钟、计数回绕、完整位域与保持、
排空/唤醒/超时、共同冷复位和四独立负例通过。提前信用归还的失败 FIFO RTL 保留。
这不是完整网口/实际时钟门控/软件 PMU；合同见
[板级时钟域](../../fpga/zu15eg/clock-domain-plan.md)。

板级双/四发射只做必要的同镜像短回归：

```sh
GSIM_CXX=clang++-19 make gsim-instruction-packet-test
GSIM_CXX=clang++-19 make gsim-board-coremark-widths
GSIM_CXX=clang++-19 python3 simulator/gsim/board_coremark.py --issue-width 4 \
    --tag 20261001-prefetch-ab --no-instruction-prefetch
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_bench_app.py --cache-ways 2 --issue-width 4
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_bench_app.py --cache-ways 2 --issue-width 4 \
    --no-instruction-prefetch
```

宽度只改变 rename/issue/commit 及相应供指结构；ROB=16、PRF=48、LSU=2、
store buffer=2、前端缓存=16 sets、I-line cache=8 lines、D-L1=2 KiB 保持相同。
四路物理取指为 16 B，旧自动配置还开启两条顺序预取，故不能把结果视作
只改变 ALU 数量的孤立实验。`--no-instruction-prefetch` 单独关闭这项策略；
通用 MachinePlatform 的默认行为不变，板级默认仍为双发射。
单次 CoreMark 迭代只比较 guest ticks/固定参考 CRC：保留预期的
“不足 10 秒”提示，不作为正式分数、实机频率或 IPC。
目录 `board-coremark-compact{2,4}-20261001`、`...-20261001-fetch8`、
`...-20261001-prefetch-ab-noprefetch` 分别保存初测、取指包修正、预取 A/B。
Instruction packet 覆盖完整 64/128 位、同一行内全部合法 8 B 偏移、
跨行 fallback、PMP、填充错误、失效、连续命中和回复背压。
独立负向模型恢复旧 16 B 对齐限制后，测试按预期因 resident hit
额外访问 TileLink 而失败；不是把所有 GSIM 通过当作四发射已完成系统验收。

`GSIM_CXX=clang++-19 make gsim-board-ddr-test` 使用独立稀疏 AXI 模型，
验证 50 MHz / 1.5 Mbaud 板级 ROM 的下载、执行和缓存回写，以及 DDR
高地址、LR/SC、AMO；模型检查地址偏移、burst/4 KiB 边界与字节写使能，
并注入背压和响应延迟。它不模拟 MIG PHY 或真实跨时钟逻辑。
下载回归默认使用连续 8N1，无额外字符间空闲位，结果在
`build/gsim/board-ddr-fifo-50000000-1500000-8n1/test.log`（最新 FIFO RTL）。
旧 `build/gsim/board-ddr-50000000-8n1` / `board-ddr` 为升级前的历史记录。
原 UltraRAM 回归仍为 `make gsim-board-boot-test`。

新增 DDR 测速固件的必要验收为 `GSIM_CXX=clang++-19 make gsim-ddr-bench-app`，
对应 50 MHz / 115200 FIFO UART 和 early-issue 板级配置。
独立 AXI memory 直接装入实际可下载 `ddr_bench.bin`，最小 ROM stub 启用 FIFO 后调用入口；
只跑 4 KiB 顺序读/写/复制与指针环 smoke，不重复低波特率串行上传。
独立核对 AXI backing memory、带宽/时间单位与正常返回，不跑大容量测速或全量 GSIM。
结果在 `build/gsim/ddr-bench-app-50000000-115200/test.log`；
其中速率基于人工 AXI 时序，不能作为 FPGA DDR 成绩。
`make ddr-bench-host-test` 另检查 1 KiB..8 MiB 内核、完整指针环和错误拒绝。
上板 q/b 测量及缓存/计时口径见 [固件说明](../../fpga/firmware/README.md#ddr50--115200-cpu-visible-bandwidth-benchmark)。
2026-10-01 必要验收 PASS：3,713,840 周期、read bursts 1525、write bursts 711、AXI stalls 1614。
交付 BIN 为 5638 字节；最初全程 115200 串行上传尝试 600s 超时，不计作通过，
最终目标明确使用直接装载，q/b 大工作集留给 FPGA 测速。

## 使用

`make coremark-setup` 获取固定版本的官方源码；`make gsim-coremark` 编译并运行
RV64IMAC+Zba/Zbb/Zbs 的 2 KiB CoreMark 工作负载，输出 guest 周期和整体 IPC。
仿真缺少实测硬件频率，结果不是可发布的 CoreMark 分数。
报告还按零提交周期的 ROB 队首状态互斥分类，并用固定 ELF 的符号与反汇编注释
热点 PC；分类口径与 A/B 数据见[RV64C 与 CoreMark](../../docs/rv64c-coremark.md)。
较早的 MULW 三拍及已就绪 load 旁路/重叠回放版本单次迭代为 305,375 周期、IPC 1.0570；
`make gsim-coremark-cache`、`make gsim-coremark-delay12` 和
`make gsim-coremark-cache-delay12` 用同一二进制比较 128 行缓存与人工 12 拍 RAM 延迟，
四组结果见[共享读缓存](../../docs/shared-read-cache.md)。
`python3 simulator/gsim/run.py coremark-tune --issue-width 4`
使用同一裸机镜像生成独立的宽度配置报告；还可调整 `--rob`、`--physical`、
`--memory-entries`、`--store-buffer-entries`。报告写入
`build/gsim/coremark-n4-c4-r32-p64-m4-s4-x4.json` 等带参数的文件。
针对 2 路 load 延迟，可用
`python3 simulator/gsim/run.py coremark-tune --flow-tilelink-response`
对比最老 TileLink 数据响应直通配置；直通桥的背压/乱序检查为
`make gsim-tilelink-bridge-flow-test`，RAM、DMA 和原子平台检查为
`make gsim-tilelink-platform-flow-test`。周期对照与 FPGA 时序边界见
[RV64C 与 CoreMark](../../docs/rv64c-coremark.md)。
独立乘法单元与整核 NEMU 验证入口分别为 `make gsim-pipelined-mul-test` 和
`make gsim-core-test`。外部写入下的读序合同与验证见
[已就绪 load 旁路](../../docs/load-ready-replay.md)。
`make gsim-backend-recovery4-test` 用独立 ROB 记分板验证每周期回滚 4 项的配置，
覆盖寄存器映射恢复、释放与过期完成过滤。
`GSIM_CXX=clang++-19 make gsim-core-branch-pipeline-test` 用 8 槽裸核、寄存的
预测错误分支重定向及 4 项回滚运行 NEMU 对照，另写入
`build/gsim/ipc-branch-pipeline.json`。紧凑相干平台对应
`GSIM_CXX=clang++-19 make gsim-vm-data-compact-coherent-buffered-platform-test`。
该分支模式尚未触发核级多笔乘法同次取消事件；独立乘法单元仍有多槽取消验证，
不能据此声称新整核模式已覆盖该事件。
`make gsim-atomic-memory8-test` 验证 8 KiB 原子边界的上半区和末端，
`make gsim-atomic8-platform-test` 验证同一范围经过 CPU、原子边界及 TileLink RAM 的行为；
默认 4 KiB 对照仍用 `make gsim-atomic-test`。结果与限制见[原子访存](../../docs/atomic-memory.md)。

8 槽平台对照：`make gsim-machine-platform-memory8-test` 运行同步 RAM、DMA 和原子固件
各三个种子，结果见 `build/gsim/platform-memory8.json`；
`make machine-platform-memory8-rtl` 导出独立的 8 槽平台 RTL 和 `filelist.f`，
供后续 Vivado 资源及时序对比。默认平台仍为 4 槽。
`make gsim-machine-platform-latency-test` 用默认关闭的 40 拍有序 RAM 响应模型和
排空写入后的独立读取固件，对比 4/8 槽；三个种子均通过独立模型，
8 槽还覆盖 DMA 与原子固件各三个种子，
结果见 `build/gsim/platform-latency.json`，限制见[机器平台](../../docs/machine-platform.md)。
`make gsim-delayed-ram-test` 独立检查该返回队列满载背压、读写顺序和错误响应。
`make gsim-tilelink-bridge-test` 独立验证新核 TileLink A/D 桥的 8 笔并发读、
通用串行写、单 RAM 有序多笔写及混合读写、同 bank 写流水化、乱序 D 重排、读错误、背压与负向数据注入；
`make tilelink-bridge-rtl` 导出独立通用 RTL。
`make gsim-tilelink-platform-test` 验证可选同步机器平台的 RAM、DMA 与原子启动；
`make tilelink-machine-platform-rtl` 导出该可选配置。默认平台仍直连 RAM，
合同见[TileLink 内存桥](../../docs/tilelink-memory-bridge.md)。
`make gsim-tilelink-router-test` 独立验证双窗口请求路由、source 归属、
跨窗口乱序 D 和未映射错误；`make gsim-tilelink-split-platform-test`
使用跨两个 RAM bank 的启动镜像验收片上接线，详见[TileLink 路由](../../docs/tilelink-router.md)。
`make gsim-tilelink-arbiter-test` 独立验证双主 A 仲裁、source 命名空间、
乱序 D 返回、背压和负向注入；`make tilelink-arbiter-rtl` 导出该 IP，
边界见[双主 TileLink 仲裁](../../docs/tilelink-arbiter.md)。
`make gsim-tilelink-fetch-test gsim-tilelink-crossbar-test` 验证取指包转换、
只读 ROM beat 复用/复位、RAM 不复用、denied/corrupt 的逐 word 错误位及双窗口并发；
crossbar 测试还覆盖 64 字节 A/D burst 不交错与未映射 burst 的完整错误响应，
见 [burst 与一致性边界](../../docs/tilelink-burst-coherence.md)。
`make gsim-tilelink-burst-ram-test` 验证单 RAM manager 的 64 字节
Get/PutFullData、完整错误响应及单拍访问回退；现有 CPU/DMA 固件仍发单拍请求。
`make gsim-tilelink-line-fill-test` 验证 4 槽缓存行 Get 请求端的乱序 D、
背压、错误与槽位复用，并验证连接单 RAM manager 后的整行数据和越界错误；
`make tilelink-line-fill-rtl` 导出独立缓存行请求端 RTL。
`make gsim-tilelink-line-write-test` 验证 64 字节写主端的 8-beat A 锁定、乱序 D 确认，
以及可复用读写组合 IP 经单 RAM manager 的整行写后读回与并发仲裁；
`make tilelink-line-write-rtl tilelink-line-transfer-rtl` 导出独立写端和组合 IP RTL。
`make gsim-tilelink-line-acquire-test gsim-tilelink-line-probe-test` 分别验证
TL-C 的 AcquireBlock/AcquirePerm→GrantData/Grant→GrantAck 与
ProbeBlock→ProbeAck/ProbeAckData 64 字节事务端点，包括乱序、多拍背压和非法交错断言；
`make tilelink-line-acquire-rtl tilelink-line-probe-rtl` 导出独立 RTL。
`make gsim-tilelink-coherent-platform-test` 验证可选单 CPU 写回缓存的 UART、
CPU 脏行与 DMA 读写探测及原子固件；`make gsim-tilelink-coherent-fencei-test`
用 RAM 自修改代码验证脏行写回、`FENCE.I` 失效与后续取指；
`make gsim-instruction-cache-test` 验证压缩指令前端的多项取指缓存和显式失效。
`make gsim-instruction-line-cache-test` 验证物理侧两路整行 I-cache 的 TL 突发填充、
同组替换、失效和 PMP 精确回退。
`make gsim-tilelink-coherent-evict-test`
以 16 行容量覆盖 ReleaseData 脏逐出；`make gsim-coremark-coherent
gsim-coremark-coherent-delay12` 与对应直连 CoreMark 命令比较 IPC，
`make coherent-platform-rtl` 导出组合平台 RTL。该模式仍限单 CPU、单笔 home 事务。
home 的无探测 Acquire 当拍启动整行读取已通过单/双 hart 定向检查；
固定 CoreMark 结果与未验证的 FPGA 时序见[性能记录](../../docs/performance-status.md)。
`make gsim-tilelink-two-hart-coherent-test` 单独验证两个私有 L1 的 T 权限迁移、
脏数据探测、无缓存访问和同时请求；这不是双 hart CPU 启动测试。
单 hart ROB 队首完成当拍退休由 `make gsim-backend-test gsim-core-test`
覆盖令牌/异常/恢复及 NEMU 差分；固定 CoreMark 镜像的对照与频率限制见
[性能记录](../../docs/performance-status.md)。
写回 L1 连续读命中与两项响应背压由 `make gsim-tilelink-two-hart-coherent-test`
中的独立缓存代理用例覆盖；整机 UART/DMA/原子与脏逐出分别用上述两个
一致性平台目标检查。单 hart CoreMark 周期对照见同一性能记录。
LSU start 当拍发请求与零延迟响应、背压和恢复由
`make gsim-integer-test gsim-core-test` 的独立模型/NEMU 检查，
机器级访存由 `make gsim-tilelink-coherent-platform-test` 检查；
CoreMark 与 FPGA 时序边界见[性能记录](../../docs/performance-status.md)。
`make gsim-vm-data-coherent-platform-test gsim-vm-instruction-coherent-platform-test`
验证写回 L1 与 Sv39 数据/指令译址共存，包含脏 PTE 探测、虚拟 AMO、
PBMT=NC 别名和精确异常。热虚拟访存用例的 IPC 与限制见
[虚拟内存合同](../../docs/virtual-memory.md)。
`make gsim-tilelink-dual-platform-test gsim-tilelink-dual-split-platform-test`
运行可选双主平台的 RAM、DMA、原子固件、精确取指访问异常及
FENCE.I 后从 RAM 执行指令，
详见[TileLink 取指路径](../../docs/tilelink-fetch.md)。
`make gsim-tilelink-dual-latency-test` 用同一双主路径和 40 拍 RAM 响应延迟比较
4/8 槽 LSU，结果见 `build/gsim/tilelink-dual-latency.json`。
`make tilelink-fetch-rtl tilelink-rom-adapter-rtl tilelink-crossbar-rtl` 导出三块独立 RTL。
`make gsim-axi-bridge-test` 验证新有序 AXI4 内存桥的 8 笔读取、独立 AW/W 背压、
4 笔写在途、混合请求顺序及读值/写错误负向注入；
`make axi-bridge-rtl axi-bridge32-rtl` 导出两种地址宽度的独立 RTL。
桥尚未接入生产平台，合同见[AXI4 内存桥](../../docs/axi4-memory-bridge.md)。
make gsim-tilelink-axi4-bridge-test 验证独立 TL-UL→AXI4 组合桥的
64/32 位地址版本各 105 笔混合事务、8 笔读和 4 笔写在途、错误和背压；
另有 256 笔写的 1/4 槽完成时间对照，报告在 build/gsim/tilelink-axi4-write-stream.json；
make tilelink-axi4-bridge-rtl 和 make tilelink-axi4-bridge32-rtl 导出 RTL。
合同见[TileLink→AXI4 内存边界](../../docs/tilelink-axi4-bridge.md)。
项目只实现 AXI4 外部边界；Zynq-7000 PS HP 是 AXI3，使用时需由 Vivado IP 转换。
旧 SoC 的 TileLink 总线和新平台默认的直连数据口没有被 AXI4 桥替换，
拓扑选择见[模块化 SoC](../../docs/modular-soc.md)。

2026-09-23 Sstc M/S 路径：平台 `mtime` 送入机器核，增加 `time`、`stimecmp`、
`menvcfg.STCE`、`mcounteren/scounteren.TM`、STIE/STIP 与委托。比较结果寄存一拍；
STCE=0 时 M 仍可写 `mip.STIP`。两组机器核各新增 9 段定向程序，
`make gsim-machine-test gsim-timer-test gsim-machine-platform-test` 通过；日志为
`build/gsim/sstc-focused.log`、`build/gsim/sstc-timer-focused.log`、
`build/gsim/sstc-platform-focused.log`。专用 `make gsim-sstc-platform-test` 又以
两组机器平台以同步 `mtime` 驱动 S 态固件：两个调度种子均在第 5 次 tick 收到一次 STI，
处理程序核对 `time` CSR、更新 `stimecmp` 并从 SRET 返回，无重复中断；
日志为 `build/gsim/sstc-platform-boot.log`；完整平台回归也运行此镜像。
同一模型还通过原 RAM 启动镜像，
见 `build/gsim/sstc-platform/ram-baseline.log`；
功能与时序边界见 [Sstc 合同](../../docs/sstc.md)。

2026-09-23 SSIP 闭环：`mideleg[1]`、`mie/sie[1]` 和软件可写的 `mip/sip[1]`
接入原有精确中断路径；GSIM 机器核两组配置各新增 7 段定向程序，覆盖 SIE 屏蔽、
委托/未委托、S/U 接收、Direct/Vectored、CSR 清除及 SRET/MRET。仅运行聚焦的
`make gsim-machine-test`，记录于 `build/gsim/supervisor-ssip-focused.log`；
其他完整回归和 FPGA 综合/时序没有因本次变更重跑。设计合同见
[机器核合同](../../docs/machine-core.md)。

2026-09-23 S 文件外部中断闭环：M/S IMSIC 文件均接入机器核。`mideleg[9]`、
`mie/sie/sip` 的 SEI 位及 `siselect/sireg/stopei` 已支持；GSIM 两组机器核各新增
12 段定向程序、15 次中断，覆盖委托/未委托、SIE 屏蔽、M/S 同时待处理优先级、
M/S/U 权限下的入口和返回、Direct/Vectored、S 文件领取与背压。
当时平台 APLIC 仍仅 M 域；现已接入 S 子域及 UART 委托，见下文定向入口。
`make test` 的 33 项 Scala 与完整 GSIM/NEMU、负向注入通过；`make machine-core-rtl wired-machine-rtl`
导出通过，原裸核 44 项 IPC 测量逐项相同。日志：`build/gsim/supervisor-imsic-final.log`、
`build/gsim/supervisor-imsic-export.log`；功能边界见 [机器核合同](../../docs/machine-core.md)。

2026-09-23 有限 S 态同步陷阱里程碑：`make test` 与 `make machine-core-rtl` 通过。
两组机器核各新增三段程序，覆盖 MRET/SRET、U 态 ECALL 与非法 S CSR/SRET 委托、
`medeleg` WARL 读回及 SIE/SPIE 往返；每组 9 次委托陷阱、12 次合法 SRET。
S 态程序使用独立 C++ 模型，既有 M 态和裸核 NEMU 差分保留；33 项 Scala、完整 GSIM
与负向注入通过。原裸核 44 项 IPC 测量逐项不变，模型哈希因重新生成而变化。
日志：`build/gsim/supervisor-final.log`、`build/gsim/supervisor-export.log`。
详细能力边界见 [机器核合同](../../docs/machine-core.md)。

最新验收已包含可选共享读缓存、CPU原子访存、DMA共享边界、机器定时器及MTIP：Scala 33 项及 GSIM 全量通过；原整数裸核每组配置 278 个程序、380,406 条提交，
访存与寄存器均经过独立模型/NEMU 检查。新增确定性 IPC 基准和可编译 C 程序，
接口、限制、测量结果见 [裸核 IPC](../../docs/bare-core-ipc.md)，日志为 `build/gsim/load-overlap-final.log`；包含同步 ROM/RAM 执行平台、顺序预取与投机 store 地址消歧检查。
机器核两组配置保留原34个程序，另各增18个定时中断程序，CSR/中断负向注入通过；当前44条IPC相对定时器接入前逐项不变；启用系统指令的配置尚未测量IPC。详见 [机器核合同](../../docs/machine-core.md)。

2026-09-23 缓存命中流水化验收：`make test cached-platform-rtl`通过，日志`build/gsim/cache-pipeline-final.log`。
33项Scala、完整GSIM/NEMU、19项故障注入及60次平台启动通过；44项IPC、30次默认平台启动和无缓存CPU对照逐项不变。
命中每拍一项，12拍重用读由首版786降至277周期，未命中仍阻塞，缓存默认关闭；RTL已更新导出。

2026-09-23 可选共享读缓存最终验收：`make test`通过，日志`build/gsim/cache-final.log`；
四种原子/缓存整核配置各88个程序及60次平台启动通过，原44项IPC和默认平台30次启动周期逐项不变。
缓存默认关闭：长延迟重复读取有收益，流式读明显退化，详见[共享读缓存](../../docs/shared-read-cache.md)。

2026-09-18 公共 ISA 拆分后 `make test` 全部通过：Scala 14 项、完整 GSIM 回归及 NEMU 故障注入。
译码/提交覆盖与双宽吞吐保持原结果，记录见 [ISA 复用验收](../../docs/isa-reuse.md)。

2026-09-18 GSIM-only 入口验证：活动 Scala 配置/展开检查 13 项全部通过（此次 Mill 命令耗时 13 秒），
GSIM smoke 通过。两项均在 PATH 前置禁用 Verilator 的拦截脚本下运行；活动目录不含 ChiselSim 调用。
旧仿真 Make 目标已撤下，历史测试仍在归档目录，退役驱动已删除；尚未迁移的覆盖率不作通过声明。
日志为 `build/gsim/gsim-only-scala.log` 和 `build/gsim/gsim-only-smoke.log`。

依赖：现有 Mill/Java 环境、Python 3、Git、Make、GMP 开发库、Flex、Bison、Clang 19 或更新版本。
程序差分另需 GCC/G++、zlib 开发库、`riscv64-unknown-elf-gcc/objcopy` 及本仓库固定 NEMU 提交和锁定资源文件。
工具链版本固定在 `config/toolchain.json`，首次下载需要网络：

```bash
make gsim-setup
make gsim-test
```

`make test` / `make regress` 先运行活动 Scala 配置/展开检查，再运行完整 GSIM 回归。
`mill -i IonSoC.test` 不再发现已归档的旧 ChiselSim 测试；这不表示这些旧用例已迁移到 GSIM。

分别运行：

```bash
make gsim-smoke
make gsim-cache-test # 独立共享读缓存
make gsim-cache-core-test # 相同CPU开关缓存的NEMU/原子/DMA及性能对照
make gsim-cache-platform-test # 四种平台配置与五种启动固件
make gsim-atomic-core-test # CPU+原子边界，指令/排序/异常/DMA及NEMU子集
make gsim-atomic-test # 独立LR/SC与AMO共享内存IP
make gsim-timer-test # mtime/mtimecmp 逐拍模型、访问宽度、背压和回绕
make gsim-dma-test # 独立 DMA：多项在途、背压、错误排空及完成时序
make gsim-shared-data-test # CPU/DMA 内存仲裁：保序、公平性与背压
make gsim-machine-test # M/S CSR、同步异常委托、外部/软件/定时中断与 IMSIC 文件桥接
make gsim-sstc-platform-test # 平台 mtime→stimecmp→S 态处理程序的固件闭环
make gsim-router-test # CPU 数据口 / 寄存器接口与响应保序
make gsim-mapped-machine-test # 程序直接配置 APLIC 并处理中断
make gsim-aplic-test # 独立 M 域 APLIC
make gsim-aia-supervisor-uart-test # M 根域委托 UART 到 S APLIC/IMSIC
make gsim-machine-aia-s-uart-test # 整机 S 态 UART 外部中断与 TOPEI
make gsim-wired-machine-test # 中断线 → APLIC → IMSIC → CPU
make gsim-imsic-test # 独立 AIA IMSIC IP，不是整核中断验收
make gsim-backend-test
make gsim-integer-test
make gsim-predictor-test # 计数器饱和、索引冲突、同周期双更新
make gsim-core-test
make gsim-ipc           # 只跑默认配置 IPC，输出 build/gsim/ipc.json 与 ipc.csv
make gsim-core-memory8-test # 8 槽 LSU 整核差分及 IPC，输出 ipc-memory8.json 与 ipc-memory8.csv
make gsim-machine-platform-memory8-test # 8 槽同步平台 RAM/DMA/原子启动对照
```

`GSIM_CXX` 可指定 Clang 路径，`GSIM_BUILD_JOBS` 控制 GSIM 构建并发，默认 4。
构建工具链源码位于被忽略的 `simulator/build/gsim-src`。脚本要求源码提交与锁文件一致，
且没有已跟踪文件的修改；不下载上游示例 CPU 和其子模块，不修改系统安装。

生成的 CHIRRTL、C++、测试二进制和日志位于被忽略的 `build/gsim/<case>`。
每次执行都会重新生成模型，不依赖旧的生成结果。`toolchain-used.json` 记录实际编译器及 GSIM 提交。
生成、编译或运行失败时返回非零状态，并打印对应日志末尾。

## 已实现的硬件边界

- `src/main/scala/core/ooo/OooParams.scala`：后端参数和边界约束。
- `BackendTypes.scala`：重命名请求、物理映射、完成、提交、恢复及异常接口。
- `RenameRob.scala`：投机/已提交映射、物理寄存器身份分配、ROB、提交和反向回滚。
- `IntegerAlu.scala`：64 位加减、逻辑、移位、有符号/无符号比较及加减/移位 W 变体。
- `StoreBuffer.scala`：显式保证写成功 RAM 的不可撤销队首 store 缓冲，四项 FIFO、逐字节转发、按序排空。
- `LoadStoreUnit.scala`：单在途 valid/ready 数据口、掩码/扩展、对齐与访问错误；仅执行 ROB 头部许可的访问。
- `BranchUnit.scala`：六种条件分支、JAL/JALR、链接地址及 IALIGN=32 的目标对齐检查。
- `IntegerBackend.scala`：PRF 数据/就绪表、按 ROB 索引的保留槽、最老就绪选择、整数执行与提交连接。
- `IntegerDecode.scala`：独立整数机器指令译码，严格检查 opcode/funct 字段。
- `BranchPredictor.scala`：64 项两位饱和条件分支预测，双查询、按退休顺序双更新，同索引更新顺序折叠。
- `IntegerCore.scala`：条件分支方向预测、双路供指、预测跳转处截断 packet、执行校正、精确异常停止接口。
  JAL 和相邻 AUIPC→JALR 提前计算目标，普通间接跳转及返回仍顺序预测，无 BTB/RAS。

新核译码共享 `soc.isa` 的 opcode/funct 定义，异常结果共享 MCause 常量；
旧流水线控制表已移至 `core/pipeline/decode`，不参与新核译码。
GSIM C++ 独立指令表与 NEMU 不由 Scala 常量生成。复用范围见 [公共 ISA 说明](../../docs/isa-reuse.md)。

默认配置为双宽、32 项 ROB、64 个整数物理寄存器身份、64 位分配标识。
重命名、提交、完成端口分别由 `renameWidth`、`commitWidth`、`completionWidth` 配置，互不绑定。
`RenameRob` 单独维护寄存器身份和生命周期；`IntegerBackend` 加入数据与执行，已接四槽 LSU；LSU 完成优先占用完成端口 0，其余端口仍可执行整数指令。
LSU 启动与 ALU 共用 `completionWidth` 条/周期的发射预算（默认 2），禁止独立的第三条发射。
`OooParams` 的 speculativeRamBase/speculativeRamBytes 显式声明无副作用 RAM，默认不开放；
GSIM 平台开放 0x80010000 起 4 KiB。取消读取保持请求稳定、排空响应且不能写回。
LSU 完成旧结果时可锁存下一笔独立访存；默认四槽允许普通 RAM load 并行。
外部仍是一个请求/响应端口、无事务 ID，必须严格按请求握手顺序返回响应；
请求选择在背压下锁定，响应 owner FIFO 路由到原槽，取消事务排空后才释放槽。
store 与区间外读取串行化；`memory_entries`/`max_outstanding` 分别报告槽容量和外部峰值在途数。
1/2 槽目前只有展开检查；4 槽为默认 GSIM 行为配置，8 槽已通过独立整核/NEMU
程序和 26 条 IPC 基准。运行 `make gsim-core-memory8-test`，报告单独写入
`build/gsim/ipc-memory8.json`，不会覆盖默认 4 槽报告；资源/Fmax 尚待 Vivado。
旧非投机访存的保护独立保留至退休，新 RAM load 的启动或错误不能提前解除它。
ROB 索引投机 SQ 保存非队首 store 的准备位、地址和数据，准备使用整数发射槽且不报告架构完成。
分配/退休/恢复清除准备项，外部写仍只在队首获准；队首未准备的 store 保留直接执行路径。
最老 pending load 可越过已准备、对齐且普通 RAM 范围内的不相交较老 store；未知地址、
重叠或非 RAM store 仍阻塞。当前没有对未知地址的推测与重放，也未实现紧凑独立 SQ。
成功 store 完成时可向完整覆盖的下一笔 RAM load 转发数据，避免一次外部读请求；
部分覆盖、不同 beat、失败 store 和非普通 RAM 不转发。该完成窗口转发保留；另有下述不可撤销 store buffer。
GSIM 裸核显式启用 `bufferedRamStores`，普通 `OooParams` 默认关闭。启用要求上述 RAM 区域的对齐写
永不返回错误；区域外写仍等待真实响应并支持精确错误。队首 store 入缓冲后即可完成并退休，
缓冲写按序发出，真实响应后释放项；分支恢复和年轻异常不能清除缓冲。
缓冲内逐字节选择最新 store，全覆盖的 load 可直接得到数据；部分覆盖或不同地址先等排空。
MMIO 也等待排空。未实现 cache、权限检查或热复位时排空协议，不可默认用于任意 SoC RAM。
`storeBufferEntries` 可配 1/2/4/8；独立 GSIM 随机背压测试覆盖全部四种容量。
独立验证入口为 `make gsim-store-buffer-test`，包含写成功契约错误注入。
紧凑配置的地址匹配现先对各物理槽并行比较，再按 head/年龄选择 1 位匹配结果；
队列容量、转发优先级和本地应答延迟不变。独立 xczu15eg-ffvb1156-2-i、10 ns
模块布局最慢路径 4.060→3.635 ns，LUT 503→448、FF 373→372。
`make gsim-store-buffer-test`、`make gsim-store-buffer-registered-test` 和紧凑相干
数据平台定向测试通过；后者首陷阱前仍为 675 条/1577 周期。
这是 IP 级局部对照，不等于整机 WNS 或 FPGA 实际频率。
后端现在于 store 准备时寄存区间末端和 RAM/对齐标志，使年轻 load 的
不相交判定不再重复做每项宽位加法。`make gsim-integer-test` 的 8/32 项配置、
`make gsim-core-memory8-test` 的 NEMU 对照及紧凑相干平台定向测试通过；
后者首陷阱前仍为 675 条/1577 周期。xczu15eg-ffvb1156-2-i 单模块综合
最差路径 34.043→33.125 ns，代价为 +165 LUT、+1057 FF；整机布局收益未测。
实验开关 `registeredLocalStoreResponses` 可把本地缓冲写应答和全覆盖转发读应答
由请求同拍改为下一拍，外部写排空顺序和 2 槽容量不变；当前所有 FPGA 顶层默认关闭。
目标是切断 LSU↔StoreBuffer 组合反馈，而非承诺提高 FPGA 频率。
`make gsim-store-buffer-registered-test` 覆盖 2 槽、3 个随机种子、零/非零延迟与背压。
另可用 `make gsim-store-buffer-owners-test` 和
`make gsim-core-registered-owners-test` 单独复现实验性的响应归属寄存边界；
后者的测试内存按 valid/ready 保持被背压的响应。该选项默认关闭，
模块综合 18.446 ns，比未启用的 18.278 ns 略差。RAM 窗口的对齐幂次
比较重构已由默认 StoreBuffer 随机测试、整核 NEMU 及紧凑相干平台定向测试覆盖，
尚未测新版时序。
新的地址准备级可用 `make gsim-core-registered-memory-address-test` 单独验证；
与响应归属寄存组合用 `make gsim-core-registered-memory-address-owners-test`。
组合版整核 NEMU 282 程序与紧凑相干平台通过，但依赖访存链从
1026 增至 1282 周期，紧凑平台 IPC 0.428028→0.395199。
分支完成后延一拍退休的进一步实验用
`make gsim-core-registered-memory-address-owners-retirement-test`；NEMU 通过，
模块综合最差数据路径 14.328 ns，与未启用的 14.323 ns 基本相同，
不属于默认紧凑 RTL。本地应答寄存组合为 15.732 ns，也未采用。
早期恢复发射阻塞实验用
`make gsim-core-registered-memory-address-owners-early-recovery-test`
和 `make gsim-vm-data-compact-coherent-early-recovery-platform-test`；
NEMU 282 程序和紧凑相干平台通过，所测周期/IPC 均未变。
其后端未布局模块最差路径为 13.777 ns，默认仍关闭；
`CurrentSocTimingMain OUTPUT compact early-recovery-issue-block` 可单独导出 RTL。
两开关组合由
`make gsim-core-registered-memory-address-owners-early-recovery-retirement-test`
和 `make gsim-vm-data-compact-coherent-early-recovery-retirement-platform-test`
验证；紧凑平台 IPC 仍为 0.395199，模块综合最差数据路径 13.176 ns。
导出用 `CurrentSocTimingMain OUTPUT compact early-recovery-issue-block registered-retirement`。
进一步的错预测分支提前完成候选用
`make gsim-core-registered-memory-address-owners-precomplete-branch-test` 和
`make gsim-vm-data-compact-coherent-precomplete-branch-platform-test` 验证；
282 个 NEMU 程序、纯 ADDI 双发射及紧凑平台均通过，后者 IPC 仍为
0.395199。模块综合路径降至 12.318 ns、WNS -2.336 ns；导出命令在
`docs/fpga-timing-windows.md`。全部候选均非默认 RTL，且未达到 10 ns。
这版最佳候选的相同 RTL 经单独 `IntegerBackend` 布局后最慢数据路径为
13.251 ns、WNS -3.269 ns；未布线、未集成，不能当成板级 Fmax。
一次对齐 load/store 的 beat/字节掩码重叠比较实验通过同样的 282 个
NEMU 程序和紧凑平台，IPC 不变，但未布局模块最慢路径升至
13.898 ns，故已撤回。测试入口和报告位置见上述时序记录。
预选下一访存并保留未发射准备槽的修正版同样通过上述两条定向
整核/紧凑平台验证，IPC 不变；仅综合模块路径却为 13.003 ns，
再合用 bit-manip 一热结果选择为 13.018 ns，均已撤回。
前一版缺少更老访存抢占时出现死锁，不是可用的 FPGA 配置。
后续保持 staged token 校验，只移除无效访存候选对 size 的置零门；
上述两条定向命令及 `make gsim-core-branch-pipeline-test` 复测通过，
紧凑平台仍为 675 条/1708 周期，
IPC 0.395199。但模块综合最慢路径 12.318→13.158 ns，
所以 size 门控微调已撤回；index-only-memory 实验也因时序退化撤回。
逐槽寄存 load replay 重叠比较同样通过上述整核和平台对照，
但未布局模块最慢路径 12.318→12.710 ns、LUT 增加，已撤回；
反例数据与路径见 `docs/fpga-timing-windows.md`。
两项局部改动合用仍通过整核 282 程序和紧凑平台，但模块最慢路径
13.183 ns、WNS -3.287 ns，组合已撤回；详见同一时序记录。
真正的 replay 寄存实验用 `make gsim-core-registered-load-replay-test` 和
`make gsim-vm-data-compact-coherent-registered-load-replay-platform-test`；
再加非透传 LSU 请求队列用
`make gsim-core-registered-memory-requests-replay-test` 和
`make gsim-vm-data-compact-coherent-registered-memory-requests-replay-platform-test`。
两组均通过整核 282 个 NEMU 程序及紧凑平台；未布局模块最慢路径
分别为 12.720/12.490 ns，后组平台 IPC 降到 0.342292、C 数组
12 拍内存延迟增至 1598 周期。均默认关闭，不是推荐 FPGA 配置；
完整器件/约束/路径与报告位置见 `docs/fpga-timing-windows.md`。
固定紧凑相干数据程序运行 `make gsim-vm-data-compact-coherent-registered-platform-test`：
首陷阱前 675 条/1577 周期（IPC 0.428028），与未寄存应答的 2 槽+相干响应缓冲配置相同。
独立 StoreBuffer 长序列有吞吐代价：种子 17、非零响应延迟为 20626→21279 周期，
零延迟为 6627→7249 周期；该驱动并非整机 IPC 基准。
xczu15eg-ffvb1156-2-i、10 ns OOC 整机布局对照：未启用 WNS -23.198 ns、LUT 123208；
启用后 WNS -23.423 ns、LUT 122705。新最差路径转移到响应队列 RAM 写使能，
时序未改善且压力场景吞吐下降，故不在紧凑 FPGA 顶层默认启用；未做布线/板级签核。
实验 RTL 可用 `mill -i IonSoC.test.runMain ooo.CurrentSocTimingMain OUTPUT compact registered-local-response`
单独导出；`make fpga-compact-soc-rtl` 始终导出未启用的默认版本。
IPC 报告 `forwarded_loads` 计数有转发启动的周期（两条路径 OR），可能包含后来取消的读取；
`loads` 仍计外部读请求，二者均不等于退休 load 数。
ROB 暂存完成数据供提交验证；整数 PRF 写入和就绪置位服从 `completionAccepted`，非法操作不写 PRF。

输入分配采用连续前缀，`dispatchReady` 表示下游能接受该周期整个获准前缀，
`renamed.valid` 是已接受事件而非可独立反压的候选。未来调度队列必须与这个握手契约一致。
同周期提交释放的寄存器和 ROB 槽位到下一周期才参与分配，不构造提交到重命名的快速组合路径。
分支恢复保留边界指令，异常恢复可以包含边界；恢复期间每周期撤销一项，允许新的更老恢复边界。

分配标识不静默回绕：耗尽后阻止新分配，已有指令仍可完成和提交。
默认 64 位；8 位测试配置专门验证耗尽。重新复位前，外部执行/访存生产者必须一起复位或排空，
不能跨复位重放旧完成消息。后续若引入可复用世代标识，必须单独证明标识重用安全性。

## 整数执行接口与性能边界

`IntegerRequest` 输入已译码操作：`operation` 对应 `IntegerOp`，`word` 选择 W 运算，
`usePc`/`useImmediate` 分别选择 PC/寄存器和已扩展立即数/寄存器操作数。
`rename.instruction` 目前是提交和异常元数据，模块不检查它与操作控制字段是否匹配。
ALU 语义依据固定版本的 [RV32I 整数运算](https://docs.riscv.org/reference/isa/v20250508/unpriv/rv32.html)
和 [RV64I 扩展与 W 运算](https://docs.riscv.org/reference/isa/v20250508/unpriv/rv64.html)。
此后端接口自身不译码；`IntegerCore` 通过 `IntegerDecode` 接收机器指令。
`controlFlow` 选择六种条件分支或 JAL/JALR；分支操作使用真实寄存器值比较并计算目标。
分支恢复由执行端生成；后端仍支持外部恢复请求。尚无自动异常入口。
无效 operation 和不支持的 W 组合报告异常原因 2，并由 ROB 保持精确异常边界。

| 结构 | 周期级目标与约束 |
| --- | --- |
| 整数 ALU | 每实例每周期一条；默认两个实例，执行宽度暂取 `completionWidth` |
| 调度选择 | 每周期选择至多两条最老就绪操作；每路用平衡树比较年龄，后路排除前路已选项 |
| PRF | 默认 64 × 64 位；执行数据读端口为 `2 × completionWidth`、写端口为 `completionWidth`，另有提交值检查读口 |
| 就绪状态 | 每保留槽读取两个源的就绪状态；分配清零，获准且无异常的写回置位，下一周期可选中依赖者 |
| 保留槽 | 容量等于 ROB，避免额外调度队列容量冲突；取走后直到 ROB 释放仍保留该索引的容量归属 |
| 默认双宽吞吐 | 独立流填满后每周期两条分配/执行/提交；单依赖链填满后每周期一条 |
| 恢复 | 接受恢复当周期取消所有被杀保留项并过滤写回；保留路径继续执行，映射仍逐项回滚 |

独立流目标要求足够的物理寄存器；36 个物理寄存器配置故意验证资源不足时的反压，
不要求持续双宽。所有架构寄存器在本测试接口复位为零，这是 bring-up 契约，不是 RISC-V 通用复位规定。
选择树、PRF 读 Mux、ALU、写回授权尚处于同一组合路径；多路选择之间也有排除依赖。
寄存器阵列的复位、就绪读端口、宽选择网络和每周期一项回滚均需要综合与工作负载评估。
目前仅验收周期级行为，频率、面积、功耗及四/六宽实际吞吐均未验证。

## 最小取指与机器指令范围

`IntegerCore` 默认从 `0x80000000` 开始，供指端每周期提供 `fetchPc + 4*lane` 对应的有效前缀。
`accepted` 表示已分配事件；PC 按接受前缀推进，若该前缀包含预测跳转则改取其目标，执行重定向优先。
预测跳转后的 packet lane 不分配；预测分支未被接受时不能提前跳转。
未接受的指令需要按新 PC 重新提供，
因此部分接受和供指停顿不会跳过指令。目标是每周期最多 `renameWidth` 条，供指充足时不额外插泡。
当前是组合供指契约，尚未实现 ICache、异步取指响应、访问异常、跨行/跨页或压缩指令拼接。
译码到重命名的组合路径尚未做综合时序验收。

当前支持 49 种 RV64I 运算/控制流/访存编码：LUI/AUIPC；ADDI/SLTI/SLTIU/XORI/ORI/ANDI/SLLI/SRLI/SRAI；
ADD/SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND；ADDIW/SLLIW/SRLIW/SRAIW；ADDW/SUBW/SLLW/SRLW/SRAW。
另有 BEQ/BNE/BLT/BGE/BLTU/BGEU/JAL/JALR；LB/LH/LW/LD/LBU/LHU/LWU/SB/SH/SW/SD。
移位立即数、funct7 和 W 变体分别检查；未支持及保留编码报告原因 2。
这只是当前子集的拒绝策略，不意味着所有被拒绝编码在完整 RISC-V 中都非法。
报告异常前允许较老指令提交，之后停止供指和提交；尚无 trap CSR 更新、处理程序入口或返回，需复位开始新程序。

`integer-program.S` 通过独立的 RISC-V 汇编器生成 410 条指令的直线程序。
`branch-program.S` 覆盖循环、正负向跳转、六种条件分支、调用/返回、JALR 源/目的相同与奇数函数地址，
以及较年轻分支先重定向、较老分支随后撤销它的场景。
另有三个种子、各 6,000 条直线随机机器指令，以及三个包含有界循环、随机整数运算、分支和错误路径非法字的程序。
新增 `bare-start.S` / `bare-memory.c` 以 RV64I、`-O2` 编译，检查函数调用、栈访问和 64 项数组求和。
另有所有访存宽度/字节通道、三个种子的随机访存与依赖、错误路径 store、反压、同周期响应和异常用例。
这是受限执行环境，不代表支持普通裸机平台或完整编译器输出。

## 分支恢复与性能契约

当前条件分支使用 64 项两位饱和预测表，复位弱不跳转，按退休顺序训练。
JAL 与相邻 AUIPC→JALR 在接受时预测对齐目标；后者覆盖同包及跨包相邻指令，保留各自执行和提交。
普通寄存器间接跳转及返回仍预测 PC+4；尚无 BTB/RAS。
分支携带实际使用的预测下一 PC，每个执行槽有组合分支比较/目标计算；预测正确的分支与 ALU 一样可双宽完成，
实际下一 PC 等于预测值时不触发恢复，JAL 到 PC+4 仍正确写链接寄存器。
不同于预测值的对齐目标才请求重定向，最老的有效请求获胜。外部请求先经 ROB 的无副作用探测检查，
失效请求不能遮蔽内部重定向；年龄比较使用 ROB 索引位宽，分配标识仍用于身份验证。

选择逻辑不依赖自己生成的恢复结果，避免组合环。执行后用 ROB 的完成授权统一拦截错误路径的
完成、PRF 写入和就绪唤醒。同周期两个跳转只保留最老者；恢复中的更老边界可继续缩小保留集合。
若外部恢复保留了一个尚未完成的边界分支，该分支在自己的重定向获准前保持待执行，不能悄悄丢掉目标。
提交记录的 `nextPc` 来自获准的实际执行结果；有序提交时逐条与独立模型和 NEMU 比较。

恢复当周期与后续回滚周期暂停分配和提交。默认配置每周期撤销至多一个年轻 ROB 项；
紧凑 FPGA 候选与对应裸核对照每周期至多撤销四项，恢复后接受目标路径指令。
这是可测量的基线，不是最终低延迟恢复方案；已有基础 bimodal 方向预测，尚无 BTB/RAS 或重命名检查点。
紧凑候选将预测错误分支的重定向/完成结果寄存一拍；默认后端仍按同拍仲裁外部恢复。
最新模块综合最差路径 21.616 ns，仍经过共享发射选择、第二槽分支与 ROB 同拍提交，
频率/面积及整机布线需继续评估。
JALR 先清除目标 bit 0；跳转到非 4 字节对齐地址报告原因 0、tval 为目标地址，且不写链接寄存器。
不跳转条件分支不对未使用的目标产生对齐异常；这些事件仍只停机报告，不进入 trap 处理程序。

## NEMU 提交差分与参考审查

`core.cpp` 直接使用 NEMU 的 `difftest_init_v2/regcpy/memcpy/exec` API；尚未连接香山完整 `emu` 的探针传输框架。
每条提交先用独立指令表/软件求值检查 PC、指令、目标寄存器及写回值，再将 DUT 提交记录应用到架构影子，
调用 NEMU 执行一条并比较 PC 和全部 32 个整数寄存器。双提交依次检查，中间状态也必须匹配。
硬件已提交 PRF 值另每周期轮询一个寄存器，程序结束继续检查至少 32 周期。
不使用旧核心作期望值，不在运行中使用 skip 或 mismatch 后同步参考状态。

参考源码固定为 OpenXiangShan/NEMU `c00b6dd17fd6f9d196750af0babba167d271d1fe`。
`reference.py` 从 Git 对象导出到 `build/gsim/nemu-src` 后独立构建，不修改 NEMU 工作树、配置或 `.git` 文件。
构建显式禁用上游 Makefile 的自动 Git 提交。两个本地 checkpoint 资源按 `config/reference-lock.json` 校验哈希；
仅布局头文件参与编译，不执行 checkpoint 生成/恢复，不自动下载依赖。
独立 defconfig 设置 16 MiB RAM、M-mode 初始状态、无浮点/向量/虚拟化寄存器，显式启用 B 和 Zicond 并检查解析后的配置。
NEMU 本身仍支持此 DUT 尚未实现的指令，差分覆盖上述 49 种 RV64I 运算、控制流、访存、Zicond 两条指令、RV64M 13 条指令及 B（Zba/Zbb/Zbs）40 条指令。

已核对固定源码中的 `isa-def.h`、`isa_difftest_regcpy`、`difftest_memcpy/exec/init_v2` 和整数运算语义。
当前寄存器 ABI 是 32 个 GPR、18 个 CSR/模式字段和 PC，共 408 字节；加载时核对导出的大小，
配置变化导致 ABI 不符必须失败。CSR/模式字段用于初始化，尚不参与本子集的架构正确性声明。
`reference-used.json` 记录源码提交、资源、输入/解析后配置及共享库哈希和编译器版本。

NEMU 的内存拷贝不会清空译码缓存。每次装载新测试程序后，在参考端专用地址 `0x80ffff00`
执行一次 FENCE.I，再初始化程序 PC/寄存器，避免沿用前一个程序的译码。这只发生在测试启动前。
测试还主动篡改第一条提交后的影子寄存器，必须得到 NEMU mismatch 和非零退出，证明比较器不会静默放行。
非法指令和目标未对齐停止事件由独立模型按 DUT 的 IALIGN=32 检查，不推进 NEMU 到 trap；
参考模型可支持 C 扩展，不能用其较宽松的目标对齐规则作为当前 DUT 的异常期望。
每条 load/store 提交还比较独立字节内存与 NEMU RAM；外部 RAM 写流还按序与退休 store 的地址、宽度和有效数据字节匹配，允许写延后排出。
程序结束及异常停止时须排空缓冲，并检查无多余/遗漏 store，DUT RAM 与独立模型一致。
访存未对齐与访问错误按独立模型检查异常 PC/cause/tval，不执行 NEMU trap，错误写响应必须无副作用。
异常 CSR、MMIO 和中断差分仍待后续接入。

## 独立验证

`smoke.cpp` 验证寄存器复位、周期采样、64 位加法和同步内存的全部 16 种字节写掩码。
GSIM 的 `step()` 更新周期状态并计算本周期输出；驱动设置输入、调用 `step()`、检查本周期事件，
软件模型随后应用这些事件，在下一次 `step()` 检查新状态。测试不依赖内部 C++ 成员名。

`backend.cpp` 使用软件事务队列重建投机映射，以集合检查物理寄存器所有权。
它允许硬件选择任何空闲物理寄存器，不复制硬件的优先编码器实现，也不调用旧核产生期望值。
每组运行定向用例及三个固定随机种子、共 18,000 周期随机输入：

| 配置 | 目的 |
| --- | --- |
| ROB 8 / 物理寄存器 36 / 标识 64 位 | 寄存器不足、ROB 回绕、资源反压 |
| ROB 32 / 物理寄存器 64 / 标识 64 位 | 默认容量下的并发分配、完成、提交、恢复 |
| ROB 8 / 物理寄存器 36 / 标识 8 位 | 标识耗尽时禁止重用；不代表 18,000 周期始终有新分配 |

覆盖同包 RAW/WAW、x0、双提交、乱序完成、有序异常、错误路径完成、重复完成、
失效恢复请求、恢复中更老重定向、资源耗尽、映射及寄存器数量守恒。

`integer.cpp` 不使用物理映射计算期望值：重放架构写入求值，用生产者标识记录依赖，
比较实际执行结果和有序提交结果，并轮询检查已提交寄存器值。
覆盖 64/32 位算术边界与移位量截断、PC/立即数选择、同包 RAW/WAW、x0、年轻独立操作越过依赖链、
ROB 满/回绕、PRF 耗尽、提交反压、冲刷已执行/待执行操作、恢复中更老边界、失效恢复及精确异常。
两组配置（ROB 8 / PRF 36 和 ROB 32 / PRF 64）各运行三个种子、18,000 随机周期。
定向吞吐测试在 100 周期流中逐周期断言后 96 周期：默认配置持续双宽，依赖链持续单宽。
非法操作的异常恢复也必须排空依赖者，不允许测试以超时为正常完成。
另有五组恢复仲裁定向用例：失效外部请求、较老外部恢复、较年轻外部恢复、同边界保留重试及同边界包含清空。

`core.cpp` 对每组配置检查 136,072 个译码输入（穷举 opcode/funct3/funct7 组合加随机字段），
并测试供指/提交停顿、部分接受、x0、同周期提交覆盖同一寄存器、精确异常停止及机器指令流双宽吞吐。
分支程序按动态架构 PC 求值；循环不会靠线性数组位置推断提交顺序，错误路径上的非法字也不能触发架构异常。
GSIM 模型和驱动开启 ASan/UBSan；NEMU 使用锁定配置独立构建，未开启这些 sanitizer。

生成模型及测试驱动都启用 AddressSanitizer 和 UndefinedBehaviorSanitizer。
为兼容受限执行环境关闭 LeakSanitizer，不关闭地址或未定义行为检查。

2026-09-18 分支/跳转/恢复回归记录：Scala 编译及四项参数/展开测试通过。
锁定的 GSIM 提交配合 Clang 21.1.8，最终 `make gsim-test` 全部通过：
smoke、三组账本、两组整数执行、两组程序差分及故障注入检查。
两组整数测试共覆盖 36,000 随机周期；默认配置通过连续 96 周期双宽吞吐断言，
两组配置均通过连续 96 周期依赖链单宽吞吐断言，ASan/UBSan 未报告错误。
程序差分的两组配置各通过 136,072 个译码输入和 23 个程序测试，
各比较 28,618 条提交（含 18,000 条随机整数机器指令），并检查 9 个异常停止事件，含 3 个跳转目标未对齐事件。
每组检查 2,037 次重定向，其中 2 次由更老分支纠正较年轻分支已经改变的取指路径。
这两个程序级事件发生在此前回滚结束之后；恢复进行中收窄边界另由账本定向测试覆盖。
默认配置的独立整数流、不跳转分支流各连续 251 周期保持两条接受/两条提交；
小容量配置发生 3,044 次部分接受并正确续取。
固定的 64 周期提交暂停确保默认 ROB 也达到反压状态，之后再随机化供指/提交停顿。
主动篡改寄存器的负向测试以预期 NEMU mismatch 和退出码 1 结束。
以下为切换到 GSIM-only **之前**的历史记录，不再是当前回归要求：
仓库全量 ScalaTest 使用本机 firtool 1.135.0、Verilator 5.032，183 项中 182 项通过：
唯一失败是旧 `FrontendQueueSpec` 期待满队列同周期出入，而旧实现明确禁止该行为。
此前出现过 Verilator internal fault 的 Sv39 取指测试本次全量运行通过。
这些旧实现和测试均未修改，不用它们的结果作为新后端的期望值。
旧工程 `make verilator` 的 timer payload 通过（UART `S!!P`、退出值 0）；
受限环境中将 `CCACHE_DIR` 指向项目生成目录，并用 `CHISEL_FIRTOOL_PATH` 指向本机已有 firtool。
本批全量 Scala 和旧整机日志分别为 `build/gsim/scala-tests-branch.log`、
`build/gsim/legacy-verilator-branch.log`；
GSIM 全量日志为 `build/gsim/gsim-tests-branch-final.log`，负向检查日志为 `build/gsim/core/negative-test.log`。

另有 ScalaTest 参数/展开测试：

```bash
mill -i IonSoC.test.testOnly ooo.OooParamsSpec
```

四/六宽接口目前仅通过展开检查，不表示已验证或实现四/六发射 CPU。
这些模块级验证不等同于 ISA 差分、形式证明、综合时序检查或整核正确性。

预测器另有 10,000 周期独立 GSIM 测试，覆盖饱和、无效训练、PC 别名和双更新同索引顺序。
整核驱动独立维护预测计数器，在退休训练前计算本周期预测，检查取指 PC、packet 截断与供指/提交背压。
报告 `predicted_taken` 为接受的预测跳转事件（包含错误路径），`branch_mispredictions` 为条件分支
执行校正事件（也可能属于之后被清除的路径），不能直接用两者计算退休分支准确率。

## 当前 GSIM 兼容性处理

在锁定版本上实际遇到两个限制，已通过保持硬件语义的封装处理，上游源码未修改：

1. bulk-connect 后动态写入组合向量导致 `splitArray` 断言。重命名组合阶段改用逐元素 Mux 连接。
2. 顶层向量端口生成了标量 C++ accessor。测试顶层 `RenameRobGsim` 将两个 lane 展开成显式命名端口；
   生产模块仍保留 Vec 接口。

## 下一阶段

以已测 IPC 为基线，推进 LQ/SQ、地址生成与提交解耦、store-to-load forwarding 和分支预测，
再接缓存/平台与精确 trap 状态；当前基线与瓶颈见 [裸核 IPC](../../docs/bare-core-ipc.md)。
ISA 设计参考固定到 RISC-V 文档版本 `20250508`；当前仅声明上述经过测试的整数/控制流/访存子集。
[规范版本入口](https://docs.riscv.org/reference/isa/v20250508/unpriv/colophon.html)。

参考模型的整数子集构建与 ABI 已审查；完整平台的扩展、计时器、异常及中断配置仍需审查。
NEMU 子模块工作树链接仍指向旧的 `/home/openion/IonSoC` 路径，本次未修改其元数据或源文件。

## FPGA 同步取指验证

新增 `make gsim-fpga-fetch-test`：独立检查 Chisel SyncReadMem 双 bank ROM 的读延迟、奇地址 word 排列、
响应背压与范围边界；随机改变 PC 检查旧响应和请求背压稳定性；小 ROB 核直接连接同步 ROM，
运行循环、JAL/AUIPC-JALR、错误路径非法字及 ROM 上、下边界越界取指程序；正常提交前缀
经独立软件模型和 NEMU 比较，越界取指须在 ROB 队首报告 cause 1 和出错 PC。
该入口纳入全量回归，但与理想供指 `ipc.json` 分开，不能用后者代表 FPGA 前端性能。
导出与限制见 [FPGA 基线](../../docs/fpga-bringup.md)。

同步前端现已增加两组 packet 缓存、顺序预取和响应到供指旁路；独立检查连续 128 周期双供指、
停顿时有界预取及部分消费。240 条不写寄存器的 ADDI 吞吐用例经 NEMU 校验，不能代表一般程序 IPC。


## 同步 ROM / RAM 执行平台

`make gsim-platform-test` 已纳入完整验收：验证 Chisel 同步字节写 RAM 的连续吞吐、随机背压、
错误响应及最终内容，并连接 ROB32/PRF64 双发射核运行 C 栈/数组程序。
三次 C 运行与两个精确访问错误用例合计 3,934 条正常提交；C 执行由独立模型和 NEMU 检查，
负向寄存器注入必须被 NEMU 拒绝。ISA 软件求值器在 `harness/isa_model.h` 共享，不依赖 DUT 编码表。

无提交背压时 1,310 条指令 / 1,529 周期，IPC 0.856769130；跨 packet 供指后两个随机背压种子分别为 1,923 / 1,879 周期（原为 1,885 / 1,880）；
无背压周期不变，不能声称普遍提速。
`build/gsim/platform-ipc.json` 记录独立平台口径、工具版本及镜像哈希，不覆盖理想供指 `ipc.json`。
`make fpga-platform-rtl FPGA_IMAGE=build/gsim/bare-program.bin` 导出集成 ROM/RAM 顶层；
命令、测量限制和 Vivado 移交见 [FPGA 执行平台](../../docs/fpga-bringup.md)。

同步前端现支持跨 packet 双路拼接，独立验证缓存及当拍响应两种来源、后继未到时的单路供指和停用状态。
完整限制及前后测量见 FPGA 执行平台说明。


## RVA23 目标与 Zicond

应用 SoC 已以 RVA23S64（含 RVA23U64 必选能力）为目标，完整差距见 [架构目标](../../docs/rva23.md)。
当前只新增 Zicond 1.0.0 的 `czero.eqz` / `czero.nez`，不是完整 RVA23 实现。
两源参与现有重命名和就绪选择，共享双 ALU 与 issue 预算，拒绝 W 变体及相邻保留编码。
参考侧仅修改本仓库独立 defconfig 开启 `CONFIG_RV_ZICOND`，固定 NEMU 源码及 GPR/PC ABI 不变。
独立软件 mask/match 和语义表不从硬件生成；编译的 C 负载仍使用原 RV64I 参数，避免混淆基准。

Zicond 最终验收：Scala 19 项与完整 GSIM/NEMU 通过；每组裸核 79 个程序、66,238 条提交。
新增 5 个程序检查别名、x0、高位条件、随机依赖及默认配置的双宽吞吐；现有 IPC 基准不变。
日志：`build/gsim/zicond-final.log`。


## RV64M 多周期执行

`make gsim-muldiv-test` 独立检查单槽乘除单元，并已纳入 `make test`。
3,900 笔算术完成、39 次取消、15,611 个结果保持周期通过独立主机算术模型；
涵盖乘积高半、除零、溢出、W 符号扩展、输入变化与旧 token 取消后重发。

裸核通过全部 13 条 M 指令的译码、算术及 NEMU 比较，包含 832 组边界操作数、1,000 条随机 M、
源/目的别名、x0、分支撤销、较老 M 跨恢复保留和 LSU 完成仲裁。
新增 `rv64m_*` IPC 项（每配置四项），原有基准输入与 C 编译选项保持不变。
详细延迟、启动间隔和微基准见 [RV64M 合同](../../docs/rv64m.md)。
当前仍无完整 RV64I、B、CSR/MMU、浮点或向量，不能声明 RVA23 合规。

RV64M 最终验收：`make test` 的 Scala 19 项及完整 GSIM/NEMU（含负向注入）通过；
每组裸核 111 个程序、97,138 条提交。原有 28 条 IPC 测量不变，新增 8 条 M 测量。
日志：`build/gsim/muldiv-final.log`。


### 流水乘法

活动核将乘法与除法分开，`make gsim-pipelined-mul-test` 已纳入默认验收。
原 `gsim-muldiv-test` 保留串行算术模块回归；活动除法采用该模块的 divisionOnly 特化，不保留闲置乘法通路。
新乘法器延迟 6 拍、每拍最多接收一笔，八项预留结果容量，支持逐 token 取消与结果背压。
独立单元验证连续 256 拍吞吐、全部五种乘法边界、随机运算、满容量、长背压和多槽取消。
核级补充同时取消多笔乘法及较老乘法跨恢复保留，并检查乘除并发。

同一独立乘法微基准：ROB32/PRF64 从 899 降至 137 周期（IPC 0.948905109），
ROB8/PRF36 为 292 周期；依赖乘法链和除法周期不变，其余原有 IPC 记录不变。
这不构成 FPGA 频率/资源或通用程序加速声明。详情见 [RV64M](../../docs/rv64m.md)。

流水乘法最终验收：Scala 19 项、完整 GSIM/NEMU 和负向注入通过，两组裸核各 113 个程序、97,170 条提交。
日志：`build/gsim/pipelined-mul-final.log`。

## RV64 B 位操作验收

Zba/Zbb/Zbs 的 40 条 RV64 编码已接入，当前共支持 104 种编码（49 RV64I + 2 Zicond + 13 M + 40 B）。
`make test` 通过：Scala 19 项、完整 GSIM/NEMU 和负向注入；两组裸核各 278 个程序、380,406 条提交，
185,224 个译码输入，19 次精确停止。新增 7,680 组 B 操作数、3,000 条混合随机 B、40 个恢复/竞争程序，
并检查非法内部控制码和非法 W 组合。参考配置启用 CONFIG_RVB，固定 NEMU 版本和寄存器 ABI 不变。

默认双发射配置的独立 RORI/CLZ 基准为 2,049 条 / 1,027 周期（IPC 1.995131），
依赖链为 2,049 条 / 2,051 周期（IPC 0.999025）；原 36 条 IPC 记录完全不变。
同步 C 程序仍为 1,310 条 / 1,529 周期（IPC 0.856769），没有 FPGA 时序/面积实测结论。
合同、实现路径与详细验证见 [RV64B](../../docs/rv64b.md)，全量日志 `build/gsim/rv64b-final.log`。

## 模块化 AIA 中断 IP

独立 `soc.ip.interrupt.Imsic` 的合同、接线和状态见 [模块化 SoC](../../docs/modular-soc.md)。
`make gsim-imsic-test` 使用独立逐身份 C++ 状态模型验证三组配置、双口背压及原子操作，
包含故意破坏响应期望的负向测试。`make imsic-rtl` 可单独导出默认 IP，输出在 `build/ip/imsic`。
该独立 IP 验收本身不代表完整 AIA 实现；后续机器核/APLIC 组合进展见下文，PLIC 兼容适配和 NEMU AIA 差分尚待实现。

IMSIC 加入后的全量验收通过：Scala 21 项、三组 IMSIC、完整 GSIM/NEMU 及负向注入；
原 CPU 44 条 IPC 记录完全不变。日志 `build/gsim/imsic-final.log`，详细覆盖和统计见模块化 SoC 合同。

## 机器核 CSR / 同步异常 / 外部中断

`make gsim-machine-test` 验收独立 `MachineCore`（ROB8/PRF36、ROB32/PRF64）。支持六种 CSR 编码、
ECALL/EBREAK/MRET、最小 M CSR 集与 IMSIC M 文件 CSR 访问，处理程序可以保存/修改 mepc 后返回。
两组定向测试各 31 个程序、10,815 条退休、37 次同步异常、39 次外部中断、81 次 MRET、1,805 次 CSR 操作。
覆盖 MIE/MEIE 屏蔽、Direct/Vectored、空 ROB、U 标签抢占、load/store 排空、同步异常优先和重入。
定向日志 `build/gsim/irq-focused.log`；CSR 数据与中断原因负向注入均通过。
标准机器级程序与独立模型/NEMU 核对，AIA/低权限裸地址空间/指定访存故障使用独立模型；
执行过程中不重同步 NEMU。覆盖范围和限制见 [机器核合同](../../docs/machine-core.md)。

`make machine-core-rtl` 单独导出 `build/ip/machine-core`；已通过 RTL 导出，尚无 Vivado 综合/时序结果。
`FpgaPlatformTop` 和原整数 IPC 流仍使用原异常停止配置。新机器核已接 M/S 外部中断、SSI 和 STI，WiredMachineCore 已加 APLIC，MappedMachineCore 已接 APLIC 数据地址映射，尚未接 VS 中断、完整 SoC、
完整 S/U 环境、Sv39/MMU、计数器或完整 CSR 集，不是 RVA23 合规完成声明。MachinePlatform单独启用PMP，见[PMP合同](../../docs/pmp.md)。

## APLIC 与中断线组合

新增独立单 M 域、单 hart MSI-only APLIC，默认31路源，31/63路独立 GSIM 验收。
`WiredMachineCore` 用现有机器核/IMSIC 连接新 IP，中断线组合跑相同31个机器核程序。
寄存器端口支持一拍响应、持续 II=1；MSI 有序队列最多4项已发送未响应事务。
WiredMachineCore 保留独立控制口；MappedMachineCore 已将 M 根域及 S 子域映射到 CPU 数据总线。
sourcecfg.D 委托到单个 S 子域、UART source3 和 S IMSIC 文件已在独立与整机 GSIM 中验证；
多 hart APLIC 路由、VS 域、IDC 和 PLIC 兼容仍待实现。
命令、精确状态语义、模型覆盖和限制见 [APLIC 合同](../../docs/aplic.md)。

APLIC 加入后的完整验收通过：Scala25项、全部GSIM/NEMU及负向注入，原整数配置44条IPC记录不变。日志 `build/gsim/aplic-final.log`。

## 程序配置 APLIC

`MappedMachineCore` 用8项有序标签路由器连接 CPU 数据口与 APLIC，保留外部普通存储器接口。
独立路由定向检查15,234项事务、最大8项在途和连续282拍收单通过；两种核心配置各3个程序，
验证 SW 配置、LW/LWU 读回、访问错误、错误路径写取消及中断处理返回。
命令、覆盖和性能边界见 [数据口映射合同](../../docs/core-mmio.md)。

数据口映射加入后的完整验收通过：Scala26项、全部GSIM/NEMU及负向注入，原整数配置44条IPC记录不变。日志 `build/gsim/mapped-final.log`。


### 同步机器核启动平台

`make gsim-machine-platform-test` 执行 ROM 中编译的汇编/C 固件，覆盖 RAM 清零、数组求和、
CPU 配置 APLIC、IMSIC 领取中断、RAM 计数更新及 MRET，使用真实同步 Chisel ROM/RAM。
两种 ROB/PRF 配置各3次启动，分别5,373/5,376条提交，每组9次同步异常、3次外部中断；
结果376、计数1，MMIO 负向注入通过。新设备路径采用独立提交模型，原 NEMU 回归保留。
`make machine-platform-rtl` 导出带同一固件 ROM 初始化文件的生产 RTL。
本轮 `make test` 全部通过，27项Scala检查、全量GSIM/NEMU及负向注入通过，44条原整数IPC记录完全不变。
详细周期、构建入口与未验证的 FPGA 时序边界见 [平台合同](../../docs/machine-platform.md)。


### 串行UART与性能回归

以下为 FIFO 升级前的历史回归记录，不能当作当前 FIFO UART 的能力边界。
`make gsim-uart-test` 当时检查独立 `UartConsole`：8N1、可编程分频、真实TX/RX、非FIFO寄存器子集，
1,090次事务、384拍连续读、43个串行TX字符及错误注入通过。不是完整16550，旧仿真UART未改动。
`make gsim-machine-platform-test` 每种核心配置执行UART和原RAM两套启动固件：TX输出 `OK\n`，
RX输入 `Z` 触发APLIC source3/IMSIC/M中断，处理程序保存0x5a到RAM并返回。
UART路径ROB8/32分别提交5,938/6,029条指令，每组9次同步异常、3次外部中断，设备及串行负向注入通过。

`make gsim-privilege-uart-platform-test` 运行独立的M→S→U→S整机镜像：U态ECALL和越权CSR读
及被PMP禁止的APLIC读写、单指令取指委托至S态，S态串行输出`SU!\n`，并检查RAM异常计数、
MPRV访问、锁定条目、提交/陷阱模型及串行负向注入。
`make gsim-pmp-fetch-platform-test` 在双主TileLink整机运行同一镜像，检查PMP锁定后
无Get读取禁执行字，边界允许字改用32位Get；正常双字路径仍使用64位Get。
`make gsim-pmp-test` 用独立区间模型检查PMP优先级、整段覆盖、TOR/NA4/NAPOT和边界地址，
含6000组随机用例及负向故障注入。仍无Sv39分页或通用S/U软件环境。

PMP 首命中选择已改为一热并行掩码，保持首个重叠项优先、整段覆盖和权限语义。
定向16项、随机6000项、负向注入通过；`make gsim-pmp-fetch-platform-test` 和
`make gsim-vm-data-compact-coherent-buffered-platform-test` 也通过。
独立 Vivado 模块布局最慢路径 3.828→3.047 ns、LUT 2317→2295，
不等于整机 WNS 改善；复现入口见 [Windows 时序验证](../../docs/fpga-timing-windows.md)。

本轮 `make test` 通过28项Scala及全量GSIM/NEMU验收，日志 `build/gsim/uart-final.log`。
与 `build/gsim/ipc-before-uart.json` 对照，44条整数裸核IPC测量逐项一致；原RAM固件六组启动周期完全不变。
生产RTL含uartRx/uartTx引脚，已导出但未经Vivado验证。见 [UART审计、能力与测试边界](../../docs/uart.md)。


### 写缓冲并行排空

StoreBuffer把单项等待写响应改为独立发送指针和已发送计数，默认4项可连续4拍发出并保持4项在途。
槽位仍在响应后释放，未响应数据继续参与字节转发；MMIO/未完整覆盖load和中断继续等待排空。
`make gsim-store-buffer-test` 现在覆盖1/2/4/8项容量，每种3个随机种子及零/非零响应延迟。
全量 `make test` 通过28项Scala及全部GSIM/NEMU。12周期RAM下默认C程序IPC 0.463717→0.825977，
store/load链0.233952→0.428412，退休后写排空46→8周期；44条测量无周期退步。
同步片上RAM平台和启动周期不变，未验证Vivado频率与面积。详见 [优化合同与全部对照](../../docs/store-drain.md)。
日志 `build/gsim/store-pipeline-final.log`，基线 `build/gsim/ipc-before-store-pipeline.json`。


### 无字节冲突的RAM读提前请求

当所有旧写已发出，但响应尚未全部返回时，不相交普通RAM load可提前请求；完整覆盖转发保留，
部分覆盖仍等待，MMIO排空不变。复用原5项响应所有者队列，读/写各自最多4项，纯load并发仍为4。
独立RAM模型在响应消费时才实际写入，覆盖1/2/4/8项缓冲、同beat不相交字节、背压与零延迟，
增加读值负向注入；整核验证C程序确实存在读/写响应重叠。

全量 `make test` 通过28项Scala及全部GSIM/NEMU。默认C程序在12周期RAM下1,586→1,575周期，
IPC 0.825977→0.831746；小配置2,032→2,024周期。44条测量2条改善、42条周期不变，无周期退步；
同步平台和UART/原RAM启动记录不变。日志 `build/gsim/load-overlap-final.log`。
合同与限制见 [读写重叠](../../docs/load-overlap.md)，未验证FPGA频率与面积。

## FENCE 与 DMA

机器核支持队首完整排空式FENCE；独立慢响应测试检查写响应完成前禁止年轻读取，并覆盖FENCE.TSO、
忽略 rd/rs1。机器核的 FENCE.I 在同一排空边界刷新前端并重取；
独立前端测试覆盖背压旧请求及旧响应丢弃，双主单 RAM/双 RAM 平台测试覆盖写 RAM 后执行。
基础 FENCE 另进入已有 NEMU 机器核差分程序。
`dma.cpp` 用独立RAM模型覆盖48组拷贝/错误/重启/轮询用例，读写地址序列及整体内存结果均核对；
`shared_data.cpp` 验证双主设备请求/响应归属、公平性、8项信用、背压及每拍一项服务能力，两者均有负向数据注入。
机器平台另运行source4 DMA完成中断固件，两种ROB配置、三种退休背压种子；详见 [DMA合同](../../docs/dma.md)。
全流程仍只使用GSIM，平台设备参考采用独立软件模型，未宣称NEMU支持该自定义DMA设备。

2026-09-22 DMA验收：29项Scala、全部GSIM/NEMU和负向注入通过；独立DMA48组用例、6,612项请求，
仲裁12,607项请求，完整平台6次DMA启动均通过。1KiB DMA忙292–294拍，同期CPU仍获准35–36项RAM请求。
原44条裸核IPC及12组RAM/UART启动周期不变；模型源码哈希更新。日志 `build/gsim/dma-final.log`，
详细口径和限制见 [DMA验收](../../docs/dma.md)。

## 机器定时器与MTIP

独立MachineTimer使用同步tick和RegisterPort，支持64位与32位高/低半访问，比较后寄存输出中断。
机器核新增MTIE/MTIP与原因7，MEI优先于MTI；向量偏移由原因生成。
`gsim-machine-test`增加18个定向程序；`gsim-machine-platform-test`增加两种配置、三种背压下的两次定时中断启动固件。
平台时间由主机按固定四拍脉冲提供，独立软件模型检查比较值/中断；既有NEMU回归保持原覆盖，不宣称NEMU支持新定时设备。
合同和限制见 [机器定时器](../../docs/machine-timer.md)。独立RTL入口为 `make timer-rtl`。

2026-09-22 定时器验收：30项Scala及全部GSIM/NEMU/负向注入通过。独立IP13,587项访问，
两组机器核各新增18个定时相关程序，平台六次定时启动均完成两次MTI、计数2及C结果376。
44条裸核IPC和18组UART/RAM/DMA启动周期逐项不变，仅模型源码哈希更新。
定时器与平台RTL导出通过；日志 `build/gsim/timer-final.log`、`build/gsim/timer-rtl-export.log`。


## 原子共享内存IP（第一阶段）

`make gsim-atomic-test`验证独立AtomicMemory：W/D LR/SC、九种AMO、CPU/DMA竞争、保留失效、
响应错误、零/长延迟和随机背压；独立软件内存与下游序列模型，加结果篡改负向检查。
普通流连续501拍每拍一笔，12拍响应模式达到8笔在途；无背压1拍内存的AMO为6拍、12拍内存为28拍（包含请求/响应握手）。
以上是第一阶段IP级结果，当时MachinePlatform尚未接入；当前CPU接入状态与验证范围见下节，仍不宣称完整A合规。
接口和完整测试边界见 [原子内存合同](../../docs/atomic-memory.md)，性能口径见 [当前性能](../../docs/performance-status.md)。
独立RTL入口：`make atomic-rtl`；全量验收自动包含该IP测试。


2026-09-22 原子IP阶段验收：`make test`通过31项Scala、完整GSIM/NEMU与16项负向注入。
两组整数核各278个程序、380,406条提交；44条IPC测量字段与修改前逐项一致，24次UART/RAM/DMA/定时启动记录也保持一致。
独立原子RTL导出通过；日志`build/gsim/atomic-final.log`、`build/gsim/atomic-rtl-export.log`。


## 原子CPU接入（第二阶段）

机器平台默认启用22种W/D原子编码：LR/SC、九种AMO，所有aq/rl均采用队首授权、旧写排空和年轻访存阻挡。
裸核默认不启用，必须显式配置atomicMemory并连接AtomicDataMemory；DataPort原子rs2右对齐，返回为完整架构结果。
`make gsim-atomic-core-test`在两种配置各检查80程序、3072译码组合、52精确异常，覆盖DMA干扰与错误注入；
无外部干扰的AMO/LR/SC序列用现有NEMU差分，其余用独立模型。负向篡改必须检出。
`make gsim-machine-platform-test`增加六次原子/DMA/陷阱返回启动，保留原UART、RAM、DMA与定时器启动。
详见[原子合同及实测](../../docs/atomic-memory.md)。这仍不是多hart缓存一致性、完整A或RVA23合规声明。


2026-09-23 第二阶段最终验收：`make test`通过32项Scala、完整GSIM/NEMU与17项负向注入。
两种配置新增各80个原子集成程序，六次原子平台启动；原44条IPC测量字段及24次既有启动记录逐项不变。
生产机器平台RTL已重新导出，filelist包含AtomicMemory与AtomicDataMemory；Vivado仍未运行。
日志`build/gsim/atomic-core-final.log`、`build/gsim/atomic-core-rtl.log`。


## 可选共享读缓存

新增独立SharedReadCache及DataPort适配器：1KiB直接映射、64字节行/8字节有效扇区、写穿透与匹配行失效。
位于原子/DMA共享边界下游，MachinePlatform通过sharedReadCache显式开启，默认关闭。
独立GSIM检查命中/替换/错误/背压；缓存开关各两种CPU配置，每种88程序、3712提交，原子与DMA故障模型保持覆盖。
全量验收包括缓存平台及原平台各两种配置、五种固件、三种背压，共60次启动。
报告`build/gsim/cache-core.json`及`cache-platform.json`与原44项裸核IPC分开保存。
命中流水化后，12拍重复读取无缓存/首版/当前分别903/786/277周期，下游读256→1；
流式读取仍需3846周期（无缓存903），故不默认开启。独立512项热缓存请求514拍完成，并覆盖三项响应占用全满背压。
多笔未命中已实现，最新性能/平台代价见[合同与全部对照](../../docs/shared-read-cache.md)。
可选RTL入口`make cached-platform-rtl`，默认生产入口保持`make machine-platform-rtl`。

2026-09-23 多笔未命中缓存定向：8项有序返回槽、最多4笔下游请求；独立128项长延迟流式读峰值4笔在途，
同地址64次仅读下游1次。四种CPU配置各88程序、60次平台启动通过，结果见[共享读缓存](../../docs/shared-read-cache.md)。
缓存仍默认关闭；完整验收日志和RTL导出记录见该文档末尾。

2026-09-24 命中返回由3拍缩至2拍，缓存范围内的写只使匹配8字节扇区失效；
独立 `make gsim-cache-test` 包含每拍一项的热命中流、错误和背压检查。
在 MULW 快路径接入前，同一 CoreMark 二进制下，128 行缓存为377,421周期、直连RAM为346,307周期，
因此继续默认关闭。详情见[共享读缓存](../../docs/shared-read-cache.md)。

多笔未命中最终验收：`make test cached-platform-rtl`通过，日志`build/gsim/cache-mshr-final.log`；
33项Scala、完整GSIM/NEMU、14组缓存连续请求检查、19项故障注入及60次平台启动通过。
原44项IPC、30次默认平台启动和24条无缓存CPU对照逐项不变。

2026-09-23 缓存写路径归因与改进：`make test cached-platform-rtl`通过，
日志`build/gsim/cache-write-release-final.log`，逐次启动诊断`build/gsim/cache-stalls.json`。
33项Scala、完整GSIM/NEMU、60次平台启动及19项故障注入通过；
44项IPC、30次无缓存启动与48条整核对照逐项不变。
DMA缓存版6004周期，较上一版6426减少422周期，但仍慢于无缓存5440；默认关闭。
# 参数化页表遍历模块

`make gsim-sv-walker-test` 验证独立 `SvPageTableWalker` 的 Sv39/Sv48/Sv57
页表读取、超页、权限、异常与背压。SoC 可选翻译服务已有 TLB 和 TileLink
页表读取；机器核已有 `satp`、`SUM/MXR` 和全局 `SFENCE.VMA` 失效控制。
可选 I/D 两侧均已接入译址：GSIM 固件验证 MPRV=S 数据访存，以及 S-mode
虚拟地址取指、数据读取和跨页页故障；这仍不表示完整 S/U 软件或 RVA23 已合规。接口与性能边界见
[`docs/virtual-memory.md`](../../docs/virtual-memory.md)。

`make gsim-soc-translation-test` 检查 SoC 可选双路 TLB/页表遍历服务通过
TileLink RAM 读取真实 PTE，含 CPU 发起的失效、两路并发、非叶 PTE 缓存、
命中、失效、超页和 NAPOT。
此入口测试服务侧请求；`make gsim-vm-data-platform-test` 另用 MPRV=S 固件
验证 CPU 数据侧有效页 load/store、精确页故障和故障时不发出物理数据请求。
`make gsim-vm-instruction-platform-test` 验证 S-mode 映射页取指、页末指令执行及
下一页精确 instruction page fault。

## OpenSBI 启动

`make gsim-opensbi-setup` 拉取并核对上游 OpenSBI v1.9 固定提交；
`make gsim-opensbi-test` 使用 `riscv64-linux-gnu-` 工具链与 `dtc` 构建 `generic` 平台
`fw_jump`，通过 GSIM 真正执行固件，解码 UART，并由 S 态测试程序验证 SBI BASE ECALL。
`make gsim-opensbi-console` 把相同平台的 UART TX 实时输出到终端，键盘字节经串行 RX 注入；
交接后的 S 态探针回显输入，Ctrl+D/Ctrl+C 退出。
当前通过记录及内存布局见 [OpenSBI 启动验证](../../docs/opensbi-bringup.md)。

## Linux 启动

`make gsim-linux-setup` 从 `~/board/linux` 当前 Git 提交生成只读快照并构建独立
RV64 内核；`make gsim-linux-test` 通过 OpenSBI 在 64 MiB GSIM RAM 模型中启动它，
检查 Linux 串口日志和用户态 `/init` 标记。配置、内存布局与阶段性验证范围见
[Linux 启动实验](../../docs/linux-bringup.md)。
`make gsim-linux-profile ISSUE_WIDTH=4 LINUX_CACHE_MODE=coherent LINUX_PROFILE_CYCLES=10000000`
只采样指定周期数并输出 L1 读/写缺失、逐出和填充事件，不等待完整启动；
`LINUX_CACHE_LINES=256` 可做 16 KiB 容量对照。短窗口不能代表稳态 IPC。

## DDR50 范围/PMP 时序优化的定向检查（2026-09-30）

`GSIM_CXX=clang++-19 make gsim-ram-range-test` 使用独立 128 位数学模型，
覆盖 DDR 非自然对齐窗口、URAM、地址空间顶端/溢出及所有 1/2/4/8 字节访问。
1,274,016 组输入 × 12 种窗口通过，错误注入必须失败。
`gsim-pmp-test` 现增加 30,840 个边界用例，覆盖 size=0..7。

本轮只跑与改动有关的范围/PMP、StoreBuffer、寄存选址+响应归属整核、
紧凑 VM 和 DDR 测试应用；没有跑全量回归。功能与周期记录、模块综合对照、
UART 同步链审计及“尚未整机 post-route”的边界见
[时序台账](../../docs/fpga-timing-windows.md#2026-09-30ddr50-敏感路径组合逻辑优化)。

### 板级时序参数的定向 DDR 程序 A/B

```sh
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_test_app.py --timing-profile baseline
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_test_app.py --timing-profile early-issue
```

可选第三个值 `queued-memory` 用于试验带 LSU 请求寄存队列的候选。
省略参数则跟随 `BoardSocConfig.timingProfile`；显式参数使 A/B 配置不随默认值漂移。
每个显式参数使用独立的 `build/gsim/ddr-test-app-<profile>` 目录，
编译同一 BootROM/DDR 应用，检查真实板级拓扑的下载、执行和返回。
2026-10-01 early-issue 为 3642430 cycles / 2093 read bursts / 833 write bursts，与 baseline 相同。

可选 `registered-response` profile 对现有响应 FIFO 关闭 empty flow-through，
用于“多一拍响应换组合断链”的实验。2026-10-01 实测 3662888 cycles，
比 early-issue 增加 20458（+0.562%），读写突发数不变；未跑该候选的 Vivado。
当前板级默认 `early-issue` 已整机签核并生成 bit，没有启用这一额外响应拍。

### 45/50 MHz 连续串行下载 A/B（2026-10-01）

```sh
GSIM_CXX=clang++-19 python3 simulator/gsim/board_ddr.py --cpu-hz 45000000
GSIM_CXX=clang++-19 python3 simulator/gsim/board_ddr.py --cpu-hz 50000000
```

每个时钟使用独立目录，并以同一时钟编译 BootROM 和 Chisel UART。
发送端独立生成分数 bit 周期，默认无额外 stop/idle 位；`--extra-stop-bit`
用于保留较宽松的旧发送方式。两组均通过头部/分块/全镜像 CRC、保留内存边界、
重传与失效镜像禁止跳转、DDR 下载执行、fence.i 同地址重写后执行。

| CPU 时钟 / UART 1.5 Mbaud | cycles | UART bytes | read/write bursts |
| --- | ---: | ---: | --- |
| 45 MHz | 5678535 | 936 | 1098 / 554 |
| 50 MHz | 6278796 | 936 | 1098 / 554 |

这是下载场景，总周期含串口等待，不能据此比较 CoreMark IPC 或 CPU 性能；
也不能用 GSIM PASS 否定用户板上的 header rejected。未模拟 USB-UART、真实电气、
MIG PHY 和物理 CDC。本节是 FIFO 升级前的单字节 holding、固定 8N1 16550 子集记录，
FIFO 升级没有混入这组历史频率 A/B；当前版本见下节。细节见 [UART 合同](../../docs/uart.md)。

## 2026-10-01：FIFO UART 与两个板级串口配置

只跑此次改动必要的定向测试，未跑全量回归：

```sh
mill -i IonSoC.test.testOnly ip.UartParamsSpec
GSIM_CXX=clang++-19 python3 simulator/gsim/run.py uart
GSIM_CXX=clang++-19 python3 simulator/gsim/board_ddr.py --cpu-hz 45000000 --baud 1500000
GSIM_CXX=clang++-19 python3 simulator/gsim/board_ddr.py --cpu-hz 50000000 --baud 115200
python3 -m unittest discover -s fpga/firmware -p 'test_*.py'
python3 fpga/firmware/uart_probe.py --self-test
```

UART 独立用例通过 1339 笔事务、83 个串行字节、73885 周期；
检查 16 字节 FIFO、触发阈值/四字符 RX 超时、中断优先级、
overflow 保留旧数据、字符错误/读清、TX 背压与清 FIFO。
同一 `uart` 入口自动运行独立 `uart-formats` 驱动：
40 种 TX 帧格式、modem delta、loopback、break；两个期望篡改负向用例均被拒绝。
两项 Scala 参数检查、12 项下载协议单测和 probe self-test 均通过。

| 板级配置 / 连续 8N1 | cycles | UART bytes | AXI read/write bursts | stalls |
| --- | ---: | ---: | --- | ---: |
| 45 MHz / 1.5 Mbaud | 5677739 | 936 | 1098 / 554 | 1401 |
| 50 MHz / 115200 baud | 18387432 | 936 | 1098 / 554 | 1384 |

结果目录为 `build/gsim/board-ddr-fifo-{CPU_HZ}-{BAUD}-8n1`；
实际 BoardSoc + 新 BootROM 下载/头部拒绝/CRC 重试/保留区/
镜像失效/DDR 执行返回/原子/fence.i 覆盖通过，ROM 3061 字节，
sample 552 字节。测试模型与驱动开 ASan/UBSan，主机串口没有打开。
更低 baud 的总周期包含更长串口等待，不是 CPU IPC 下降。
真实 MIG PHY、物理跨时钟复位、电气/USB-UART 仍需板上测试；
两个 bit 的最终 Vivado 时序/CDC 结果另见
[时序台账](../../docs/fpga-timing-windows.md)。

## 2026-10-01 DDR / compressed-fetch optimization checks

BoardSoc source defaults to a two-way 2 KiB coherent L1. The original DDR50 FIFO
bit was direct-mapped; the user subsequently reported the two-way board benchmark
passing with 8 MiB COPY=17.214 MiB/s. Later replay RTL remains an unrouted candidate.
Capacity, SRAM hit latency, ordered responses and outstanding-line-miss count are unchanged.
The bounded home directory must match the L1 set/way organization.

```bash
GSIM_CXX=clang++-19 make gsim-cache-ways-test
GSIM_CXX=clang++-19 make gsim-fetch-offsets-test
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_bench_app.py --cache-ways 1
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_bench_app.py --cache-ways 2
GSIM_CXX=clang++-19 python3 simulator/gsim/run.py vm-instruction-wide
mill -i IonSoC.test.testOnly ooo.OooParamsSpec
```

Independent cache manager/backing/architectural model: alias residency, masked writes,
dirty eviction, probe, flush and ordered hit-under-miss under backpressure.
Fetch fixture checks mixed 16/32-bit instructions, two/four lanes, packet/64-bit wrap,
fault tval, invalidation/context and held request stability. All use ASan/UBSan.
The existing VM driver checks an executing four-wide core and cross-page faults.

Same 5638-byte benchmark/AXI model: read 4587/4583, write 7212/7214,
copy 59280/11419, chase 3662/3661 timed cycles for one/two ways.
Copy improves 5.19x, not total application IPC. Profile counters include preparation,
verification and UART, not exact timed-kernel events.
Only direct-loaded 4 KiB auto smoke was run, not UART upload or large q/b commands.
No full regression, physical MIG, new board bandwidth or full-route signoff claim.
Logs: `build/gsim/ddr-bench-app-50000000-115200-ways{1,2}-20261001/`.

## Dual-issue replay selector and BootROM provenance (2026-10-01)

Production replay target/ownership rules and cycle latency are unchanged.
The candidate compares all 61 PA beat bits, checks byte-lane overlap and chooses
the oldest younger load in circular ROB order. Default board issue width remains 2.

```bash
GSIM_CXX=clang++-19 make gsim-load-replay-test
GSIM_CXX=clang++-19 python3 simulator/gsim/run.py core-branch-pipeline \
    --registered-memory-address --registered-owners --early-recovery-issue-block
GSIM_CXX=clang++-19 python3 simulator/gsim/board_coremark.py \
    --issue-width 2 --tag replay-selector-20261001
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_bench_app.py --cache-ways 2 --issue-width 2
GSIM_CXX=clang++-19 python3 simulator/gsim/board_ddr.py --cpu-hz 50000000 --baud 115200
python3 -m unittest discover -s fpga/firmware -p test_audit_bootrom.py
```

Selector: 16892832 vectors (all 16 heads/owners x all eligibility masks, full PA,
byte lanes, invalid/wrap) and injected oracle mismatch PASS. Executing core:
282 programs, 18000 random instructions/3 seeds, live NEMU and negative mismatch,
same-address/partial-overlap replay, precise exceptions and rollback PASS.
CoreMark one iteration remains 639000 ticks; this is NOT a valid CoreMark score.
DDR auto smoke remains 4583/7214/11419/3661 ticks. Actual BootROM download/CRC/range/
fence.i/run/return PASS: 18319290 cycles, ROM=3061 B, sample=552 B.
ASan/UBSan enabled; no full GSIM or physical MIG claim.

The prior `release-2way` selected a stale original-project ROM DCP. Its candidate
and bit matched each other but not latest firmware. Release now requires expected
ROM DCP/BIN and audits every MIF word plus INIT/INITP; stale reference negative
test rejects that exact old candidate. The independently signed BootROM-only ECO
bit retains the board-tested CPU/cache, not the newer replay RTL.

## Optional registered replay and exact DDR50 Linux image (2026-10-01)

The default board timing profile stays `early-issue`, issue width 2. Evaluate the
registered replay + ROB-retirement boundary explicitly, with separate artifacts:

```bash
GSIM_CXX=clang++-19 python3 simulator/gsim/run.py core-branch-pipeline \
    --registered-memory-address --registered-owners --early-recovery-issue-block \
    --registered-retirement --registered-load-replay
GSIM_CXX=clang++-19 python3 simulator/gsim/board_coremark.py --issue-width 2 \
    --tag replay-stage-20261001 --timing-profile registered-replay
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_bench_app.py --cache-ways 2 \
    --issue-width 2 --timing-profile registered-replay
```

NEMU 282 programs/18000 random instructions/3 seeds/negative oracle PASS.
Same short CoreMark BIN: 642274 versus 639000 ticks (+0.512%); not a valid score.
Same DDR smoke: 4594/7216/11469/3661 read/write/copy/chase ticks; backing checks PASS.
No full regression or new board/route qualification.

The new image-specific Linux test is distinct from the historical 64 MiB platform:

```bash
python3 fpga/firmware/build_rootfs.py --jobs 16
python3 fpga/firmware/build_linux.py --jobs 16
GSIM_CXX=clang++-19 python3 simulator/gsim/board_linux.py \
    build/fpga/linux-ddr50-busybox/opensbi_linux_ddr50.bin
```

Uses DDR50/115200, 512 MiB CPU aperture, issue=2 and D-cache ways=2, default
`early-issue`. Companion ELF identifies the exact OpenSBI semihosting probe PC.
The observer permits architectural ECALL/page-fault/misaligned/timer handling
and firmware CSR probes; unexpected access faults or user/kernel illegal
instructions fail. UART must show real user-mode init, BusyBox command results,
fastfetch 2.69.0 and the next prompt; echoed command text cannot satisfy markers.
Characters are paced for polling hvc0, not claimed IRQ-driven UART service.
Exact BIN preload skips serial upload, not the independent sparse AXI DDR
latency/backpressure model. It does not verify physical MIG/CDC or the board.
No ASan/UBSan on the long Linux run; shorter core/cache/DDR tests retain them.
See `docs/linux-bringup.md` and the image manifest for qualification status.

This image's long GSIM attempt was stopped at the user's request for direct board
debug: last progress 320000000 cycles, kernel running initramfs gzip unpack.
OpenSBI/S-mode/Linux/RAM/timer were observed, but user init/shell/fastfetch and
console commands were NOT completed and this attempt is NOT a PASS.
Do not rerun the long Linux test by default; retain focused checks for subsequent
hardware edits and use user-supplied board logs for the next bring-up step.

## Physical response ownership timing cut (2026-10-01)

BoardSocTop keeps two-wide `early-issue`, ROB16/PRF48/LSU2/SB2 and 2 KiB two-way
L1. It disables empty-owner flow in both the physical system arbiter and the
ordinary CPU/DMA AtomicMemory queue. Generic IP defaults remain flow-through.
No response data register or atomic FSM stage is added. Already delayed managers
have unchanged response latency; a zero-cycle manager must hold valid/data until
ready. Registering the two queues is parallel ownership tracking, not two data
pipeline stages. MachinePlatform rejects this option without ordered TileLink
memory and the translation service.

Focused checks (do not run full GSIM/Linux by default):

```bash
GSIM_CXX=clang++-19 python3 simulator/gsim/run.py shared-data --registered-physical-owners
GSIM_CXX=clang++-19 python3 simulator/gsim/run.py atomic --registered-physical-owners
GSIM_CXX=clang++-19 python3 simulator/gsim/run.py vm-data-compact-coherent-buffered-platform \
    --early-recovery-issue-block --registered-physical-owners
GSIM_CXX=clang++-19 python3 simulator/gsim/board_coremark.py --issue-width 2 \
    --tag complete-owner-cut-20261001
GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_bench_app.py --tag complete-owner-cut-20261001
GSIM_CXX=clang++-19 python3 simulator/gsim/board_ddr.py --cpu-hz 50000000 --baud 460800
```

Use a separate `--tag` for CoreMark/DDR A/B records. VM comparison must use the
same source/profile, not the older historical trace. Atomic/arbiter tests retain
negative-oracle injection and ASan/UBSan. The 460800 test is digital BootROM/UART
download qualification only: it does not change the released 115200 bit/DTB or
prove physical UART/CDC/timing. No COM port is accessed by these tests.

## Batched staged-fabric acceptance (2026-10-01)

IMPORTANT user workflow: finish a coherent multi-change candidate first, run only
short affected checks, then synthesize the combined RTL once. Do not launch GSIM
or Vivado for every small edit, full GSIM, long Linux, route, or bit generation by
default. Reuse the accepted checkpoint for further report queries.

`staged-fabric` keeps issue width 2 and all board memory/core capacities. It combines
the already tested registered replay/ROB-retirement profile with a 2-entry checked
PMP request queue, a 2-entry Home request/CPU-owner buffer, and parallel APLIC and
timer/UART/DMA decoders. Stable `early-issue` and released bit/DTB remain unchanged.

```bash
GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=6 make gsim-staged-fabric-test
# Separate artifacts when repeating a new candidate:
GSIM_CXX=clang++-19 python3 simulator/gsim/staged_fabric.py --tag next-batch
```

The batch checks Scala contracts, independent mixed-port ordering/byte lanes/
errors/backpressure/atomic bypass and CPU-owner capture, negative oracle injection,
compact coherent VM/fault/atomic execution, and exact-binary one-iteration CoreMark
plus 4 KiB DDR application smoke. The two board applications reuse ONE generated
and compiled BoardSocGsim model. ASan/UBSan remain enabled. `--only` is for failed
check diagnosis and records `partial-pass`, never full batch acceptance.

Logs and results: `build/gsim/staged-fabric-TAG/`. No serial port or Vivado is opened
by the script. Application ticks are synthetic cycle-cost comparisons, NOT valid
CoreMark scores, board DDR bandwidth, Linux qualification, or routed timing.

## Batched control-path candidate (2026-10-01)

`staged-control` builds on `staged-fabric`, still two-issue with identical core and
memory capacities. It enables the previously tested branch precompletion (the
registered redirect no longer waits for a non-branch completion port), parallel
fresh-register prefix admission, and stable fetch fault payloads. Default
`early-issue` and the earlier fabric-only profile remain unchanged.

`RenameAllocationCapacity` is a stateless, balanced at-least-k threshold tree:
each lane checks the fresh-register prefix, independently of an earlier lane's
accepted priority-encoder destination. No-write and move-alias lanes consume no
fresh registers; actual RAT/PRF ownership and same-packet RAW/WAW mapping are still
maintained by RenameRob. II=1, no additional pipeline cycle.

Fetch errors/pages/data are meaningful ONLY when the corresponding instruction
lane is valid. With `stableFetchFaultMetadata`, disable/invalidate suppresses valid
without rewriting payload/exception bits. Cache invalidation and stale-request
drain are unchanged. Consumers must not treat metadata on an invalid lane as an
exception. Stable metadata does not delay invalidation or permit stale allocation.

```bash
GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=6 make gsim-control-stage-test
GSIM_CXX=clang++-19 python3 simulator/gsim/control_stage.py --tag next-control-batch
```

One combined short batch checks contracts, independent capacity thresholds,
compressed 2/4-lane and uncompressed fetch/error/invalidate/backpressure, one
affected bare-core NEMU profile, compact coherent VM, and exact-binary single-round
CoreMark/4KiB DDR. Negative oracle injection and ASan/UBSan remain enabled. The
NEMU library is reused only after checking its pinned manifest/config/library
bytes; otherwise the isolated reference builder is used. The two board programs
reuse one generated/compiled model. This is NOT full-project GSIM, long Linux,
four-wide CPU qualification, FPGA bandwidth, or a valid CoreMark score.

Evidence: `build/gsim/control-stage-TAG/`; combined SoC synthesis is separate and
must follow accepted short checks. Further path queries reuse the saved checkpoint.
## Batched staged-data timing acceptance

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=6 make gsim-data-stage-test` checks the
two-issue `staged-data` candidate without full GSIM, Linux, or Vivado. It inherits
`staged-control`, enables the existing non-flow LSU-to-StoreBuffer request FIFO,
and relocates (does not stack) the existing two flow-through CPU response credits
ahead of the translation adapter. APLIC and fault placeholders now receive the
same response-ready isolation as external L1/MMIO. StoreBuffer local ACK/forward
semantics remain unchanged. The request FIFO adds one cycle; the response FIFO
adds none when empty and cannot borrow dequeue credit when full.

The short runner groups configuration, independent credit/hold/fault-payload
checks, range vectors, NEMU core, burst manager, 128KiB ROM, precise VM and same-BIN
CoreMark/DDR application checks. Two board applications reuse one generated and
compiled model. `--only` is for affected failure repair, records `partial-pass`,
and is not whole-batch acceptance. Aggregate evidence must list all passed groups
and any repairs; do not claim an uninterrupted first-pass run after a failure.
ASan/UBSan and pinned byte-verified NEMU remain enabled. No physical UART,
100MHz routed timing, Linux userspace, or four-issue qualification is implied.

## Batched staged-execute timing acceptance

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=6 make gsim-execute-stage-test` inherits
staged-data, separates early ranked operand evaluation from late slot grants, and
derives retirement RAS call links from committed PC+2/4. No execution latency is
added; all architectural updates retain the original valid/ownership checks.
This candidate explicitly requires the two-slot ranked scheduler; a four-wide
profile is rejected, not silently treated as qualified.

The affected short batch checks Scala contracts, an independent circular RAS
oracle with poisoned completion payloads and negative injection, the byte-verified
pinned NEMU core profile, compact coherent VM, and same-binary CoreMark/4KiB DDR.
Both board applications share one generated/compiled model. ASan/UBSan stay on.
Unchanged credits/range/burst/ROM groups are not needlessly rerun. `--only` records
partial-pass, not whole-batch acceptance. Evidence is in
`build/gsim/execute-stage-TAG/`; synthesis follows all passing short checks once,
then `fpga/zu15eg/report_execute_stage.tcl` reuses the real-ROM checkpoints.
Neither the test runtime nor OOC timing establishes routed board frequency.

## Batched staged-rename timing acceptance

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=6 make gsim-rename-stage-test` combines
stable frontend prediction payloads, early fresh destination candidates and
static parallel PRF ready updates. It inherits staged-execute; no new pipeline
cycle, late allocation/recovery/exception/complete authorization is preserved.
Early destinations require parallel admission and reject alias mode explicitly.

Only affected contracts, independent selector/ready vectors, compact ledger,
mixed-length call/return and AUIPC/JALR packet programs, NEMU, compact coherent VM
and same-binary CoreMark/4KiB DDR are run. Packet tests use public PC IO with
deliberate supply bubbles, LSU4/predictor64: not a board IPC measurement. The
board programs use the real compact profile and share one generated/compiled
model. Negative injection and ASan/UBSan remain enabled. Failed/unrun groups can
be resumed with --only, which records partial-pass; aggregate evidence must
disclose repairs. The new packet wrapper initially violated the shared predictor
parameter requirement; fixing that test setup is not evidence of a DUT repair.

Evidence: build/gsim/rename-stage-TAG; after all affected groups pass, one combined
SoC synthesis, then read-only report_rename_stage.tcl checkpoint queries.

## Batched staged-retire timing acceptance

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=6 make gsim-retire-stage-test` batches
balanced byte-wise branch comparisons, a separately qualified same-cycle
retirement fault path and parallel two-lane ordered RAS control. It inherits
staged-rename and adds no pipeline cycle. Full exceptions still update ROB/PRF/
trap logic; an assertion requires the fast fault to equal the full exception
whenever an accepted completion may retire immediately. RAS speculation is
payload-only; valid controls all state updates and lane 1 wins colliding writes.

Only affected Scala contracts, independent branch mathematics/results (both
IALIGNs), existing RAS/ledger/packet oracles, NEMU, compact coherent VM and pinned
CoreMark/4KiB DDR applications run. The board applications share one generated/
compiled model. ASan/UBSan and negative injection stay enabled. Bare NEMU tests
cover branch/fault cuts; compressed packet, RAS, VM and board tests also exercise
the new RAS mode. No wider CPU or Linux qualification is implied. `--only`
means partial-pass. Evidence is in build/gsim/retire-stage-TAG; initial compiler
type-error logs are preserved. After all checks pass, one SoC synthesis and
read-only real-ROM checkpoint reports; no default implementation/bit flow.
## Redirect-capture candidate (2026-10-02)

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=6 make gsim-redirect-stage-test` reuses the
retirement short runner with `--profile staged-redirect`. It checks the combined
early kill qualification/static pending-slot clear/native carry comparison
candidate, keeping two issue slots and all previous retirement/RAS cuts.
The independent capture oracle exhausts two-lane flags, both priority directions,
indices, blocked state and selected kill patterns, then adds seeded random masks.
It specifically rejects killed-oldest-to-younger fallback; negative injection
must fail. Existing branch/packet/NEMU/VM/board application oracles stay unchanged.
CoreMark and DDR share one generated board model; no Vivado or full Linux run.
`--only` is a diagnostic subset, not complete acceptance.

## Memory-preparation / aligned-fetch candidate (2026-10-02)

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-preparation-stage-test` uses
`retire_stage.py --profile staged-preparation`. It inherits staged-redirect and
adds two early memory payloads followed by a late issued-owner exclusion, plus
packet-aligned four-byte fetch PMP endpoints without XLEN lane/end additions.
No new pipeline cycle, capacity, issue width, default profile or board clock.

The new selector oracle scans circular ages procedurally at ROB16/32, independently
reselecting after removing the issued owner. The existing 128-bit PMP interval
oracle is unchanged; an extra aligned-word case per random table exercises the
specialized path, while generic sizes/alignment/wrap cases still run. Mixed-length
fetch tests cover widths 2/4, backpressure, invalidation and precise fault metadata.
A separate compressed-fetch PMP driver checks permission masks and frozen address/
mask under context changes and invalidation; the legacy uncompressed fetch driver
is not a compressed-instruction oracle. Negative injection must fail all new oracles.

Existing compressed prediction packets, bare-core NEMU, compact coherent VM and
same-binary CoreMark/4KiB DDR applications complete this affected short batch.
Board applications share one generated/compiled model. ASan/UBSan stay enabled;
no full GSIM/Linux or Vivado is invoked by this target. `--only` records partial-pass.
Logs are under build/gsim/preparation-stage-TAG. Subsequent single synthesis can
pass a fifth period argument to synth_soc_partition.tcl to load the clock XDC
before mapping; post-synthesis reconstraint alone is not timing-driven synthesis.

## Circular issue / raw fetch payload candidate (2026-10-02)

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-payload-stage-test` runs
`retire_stage.py --profile staged-payload`. The coherent batch replaces repeated
age tournaments/index re-decode with circular one-hot payload selection, removes
late grant from completion owner payload and removes invalidate from raw request
packet-presence preparation. Original grants, precise faults and locked/stale fetch
protocol remain; no extra pipeline cycle or capacity. Default profile is unchanged.

The selector oracle scans circular ages independently, checking both one-hot masks,
indices and actual selected payload including empty masks at ROB16/32. Fetch width
2/4 and compressed PMP checks retain independent expectations, held-context changes
and stale suppression. RAW_FETCH_PRESENCE adds a cached-next-packet invalidation
witness: no instruction/new request escapes, then the cleared cache refetches.
Negative injection and ASan/UBSan stay enabled. Existing prediction/NEMU/compact VM
checks and same-binary CoreMark/4KiB DDR complete this short batch; one board model.
No full GSIM/Linux, synthesis, route or bit is invoked by the runner. `--only` is
partial-pass. Logs: build/gsim/payload-stage-TAG. One subsequent synthesis uses the
same pre-mapping 10 ns XDC as staged-preparation; checkpoint queries also verify
that invalidate cannot reach fetch PMP address payload but still reaches lane valid.

## Registered returns / direct physical operands candidate (2026-10-02)

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-return-stage-test` runs
`retire_stage.py --profile staged-return`. It combines a real translated-response
register, memory reply bypass of local MMIO lane shifts and parallel one-hot physical
operand reads, inheriting staged-payload without widening or changing defaults.
Only response return latency adds one mandatory cycle; ALU execution is unchanged.

The operand oracle uses a procedural owner scan and ordinary software array read,
not hardware decode/OR equations. It exhausts selected source pairs at ROB16/PRF48
and ROB32/PRF64, then seeded random values/owners and invalid unselected IDs/empty
masks. The response-credit driver retains the old default-flow checks and separately
asserts registered output-valid equals pre-edge occupancy, no empty bypass, exact
two-credit ready/order/error semantics, backpressure, streams and reset epochs.
The original ordered fabric/byte-lane oracle is unchanged. Negative injection and
ASan/UBSan remain; existing prediction/NEMU/VM plus same-binary board CoreMark/DDR
finish the short batch. One board model; no full GSIM/Linux or Vivado in this target.
`--only` is partial-pass, logs build/gsim/return-stage-TAG. Subsequent one synthesis
uses pre-mapping 10 ns XDC and checkpoint queries prove the payload register cut.

The pinned GSIM C++ generator cannot assign top-level input Vec setters. The
operand wrapper therefore exposes scalar Record fields and wires them into the
unchanged DUT Vec ports; no simulator/vendor/generated-code patch. Chisel's plugin
owns Record cloning. Initial generator/clone failures remain in the evidence.
Registered-credit coverage adds 200 legal isolated returns to the saturated stream:
the enqueue edge cannot bypass, invalid input payload is poisoned while the valid
queued reply is held, and the reply consumes exactly once. The original >100 empty
return coverage threshold and independent oracle remain, rather than being relaxed.

VM UBSan also caught an unqualified local MMIO barrel shift with an undefined
owner offset. The DUT now places local data with eight fixed constant shifts and
an explicit zero default; memory still bypasses local placement. No sanitizer
disable, generated-code edit or valid feedback on the memory payload. The original
fabric and VM checks were rerun after this source fix; previously passed independent
operand/credit/NEMU/prediction checks were reused, not reported as one uninterrupted
runner pass. Raw subset JSON stays partial-pass; aggregate evidence names all groups.

For return-stage-20261002, 37 Scala checks and all affected hardware groups pass.
The unchanged firmware hash gives CoreMark 731130 ticks versus 707697 (+3.31%);
4KiB DDR read/write/copy/chase 5295/7714/12987/3847 versus 5030/7642/12567/3786.
VM's first fixed milestone is 2525 cycles/675 retired versus 2261/675 (+11.68%);
total commits use a fixed 3000-cycle observation window, leaving different post-trap
loop budgets, so they are not an equal-work comparison. All 26 full bare-core IPC
records are identical, but that model does
not include the SoC response register. One-iteration CRC checks are not a formal
CoreMark score, and synthetic AXI timing is not physical DDR bandwidth.

## Fetch-address feedback / compact PRF candidate (2026-10-02)

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-fetch-address-stage-test` selects
`retire_stage.py --profile staged-fetch-address`. Early fallback address sums and
exact prefix TL range decoding remove late carry/range control from the ROM reply
to next-request feedback; the high-area one-hot physical operands are disabled,
not removed. No new pipeline cycle or capacity; real translated return stays.

Independent 128-bit interval math checks 32/64-bit small and unaligned DDR windows
and a high64 base, random and boundary addresses; negatives must fail. The original
router/crossbar/fetch drivers and wrong-owner/source injections are unchanged.
Line cache checks packets2/4, precise fault retry/invalidation and wide prefetch;
original prediction/NEMU/data-VM plus baseline/cross-page instruction VM cover
actual integration. The same pinned CoreMark and DDR binaries share one board model.
ASan/UBSan remain. Outputs build/gsim/fetch-address-stage-TAG; subsets partial-pass.
No full GSIM/Linux, Vivado, clock/reset/IP/default or bit changes in this runner.

For fetch-address-stage-20261002, all ten required groups pass when aggregated
across the initial run, repaired prefetch checks and the resumed five-group run.
The original failed JSON and resumed partial-pass JSON remain unchanged. Scala
checks total 23 (3 fetch-address, 3 return, 17 params). Five independent decoder
configurations each pass 56565 or 62805 vectors and intentional reference faults.
The router/crossbar/fallback original oracles and owner/source injections pass.

The initial 4-word prefetch driver assumed a 64-bit packet. Its repaired wrapper
reads both existing scalar low/high outputs, compares both halves against separate
software memory beats and flips the HIGH half in the 4-word negative test (the
2-word negative flips the low half). Another driver failure assumed the wide ROM
adapter could not accept a packet while its narrow Get was stalled. The driver now
tracks that legitimate request handshake, stops presenting it after acceptance,
and still checks stalled prefetch A payload stability. No DUT, oracle instruction
values, sanitizer, capacity or protocol rule was changed for these repairs. Both
2/4-word demand and prefetch checks pass; production two-issue fetch uses two words
and DOES NOT activate the four-word-only prefetch engine.

The unchanged prediction and NEMU checks pass (20 prediction programs, 282 NEMU
programs, 380429 commits, 18000 random instructions/3 seeds). All 26 IPC rows match
staged-return by full configuration, cycles, retired and IPC; names alone are not
unique because some run at multiple memory latencies. Baseline/cross-page virtual
fetch each gives walks3/PTE5/TLBhits19; data VM first fixed milestone remains
2525cycles/675retired. Same-binary board CoreMark731130ticks and DDR four ticks
5295/7714/12987/3847 are unchanged from staged-return. They are CRC/cycle regression
evidence, not a valid CoreMark score or physical DDR rate. Logs and firmware hashes
are archived with the one board model's evidence in staged-fetch-address/short-tests.json.

## Fetch-control candidate short gate (2026-10-02)

`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-fetch-control-stage-test` selects
the three related ROM-credit/TL-reply-metadata/direct-prediction changes together.
Nine affected groups only; no full GSIM/Linux/Vivado or clock/reset/IP/bit changes.
Results live in build/gsim/fetch-control-stage-TAG; subsets remain partial-pass.

Prediction oracle performs literal full64 target/successor addition, including
wrap, both instruction lengths and alignment16/32; it does not copy the DUT's
cancelled comparison. Original router/crossbar and ROM boundary drivers remain.
A new independent ROM physical-capacity model checks two queued replies plus one
native reply, no borrowed full/dequeue credit, ordered data/source/size/denied,
held payload, pending coordinated reset, empty bypass and sustained II=1. Tests
include intentional oracle corruption and owner/source violations. Existing
prediction packet/NEMU and both VM paths cover integration; identical pinned
board binaries share one model to expose cycle costs. Sanitizers stay enabled.

For fetch-control-stage-20261002 all nine groups pass in the final complete run.
27 Scala checks, 50360 full64 prediction vectors, original routing/ROM boundaries,
independent ROM credits (2403 accepts, 2400 completions, three pending-reset
discards, peak3, fullNoBorrow321, emptyBypass1200, sustainedII1=1199), prediction
packets and NEMU plus all negatives pass. Baseline/cross-page instruction VM and
coherent data VM pass. The original router/crossbar narrow tests do not establish
new burst behavioral coverage; inspected burst/ownership state remains unchanged.

The initial two contract failures were hierarchy-name assumptions (Chisel emits
produced_replies inside the produced expression), not functional failures. A
stable naming hint was added and the structural/query selectors fixed; raw logs
and failed status JSON remain. No behavioral driver/oracle/sanitizer was relaxed.
All 26 complete IPC rows, VM first milestone2525/675, same-image CoreMark731130
and DDR5295/7714/12987/3847 match staged-fetch-address. These short board checks
are CRC/cycle regression, not formal CoreMark or physical FPGA DDR bandwidth.
The inherited CPU return cycle/cost relative to staged-payload still applies.
One separate pre-mapping10ns combined synthesis and46 checkpoint-only reports
completed: global10.590ns/WNS-0.608ns, LUT129718/FF61440. ROM external ready credit
and late TL source-lookup cuts are proven, prior registered CPU return remains.
No new cycles measured, but predictor/PRF/RAS/frontend setup still fails. No route,
bit/default promotion, actual100/150MHz or physical frequency*IPC acceptance.
RTL/UART/timebase parameters still50MHz/115200; 10ns is a synthesis/query target.

### Recovery control short batch (2026-10-02)

GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-recovery-control-stage-test
combines original-candidate recovery admission, per-slot kill/retention and
pre-authorized full-token redirect matching on the same two-issue baseline.
Eight groups only: contracts/recovery/ledger/prediction/core/system/vm/board; one reused
board model runs the pinned CoreMark CRC/cycle and DDR4KiB firmware. Independent
recovery checks compare against the original procedural serialized algorithm,
not the DUT's parallel Boolean expression; both16/32-entry geometry, full64 tags,
strict shrink, stale candidates, masks, trap priority and negative injection.
Ledger checks use8/64-bit tags including exhaustion/rollback/stale completions.
ASan/UBSan and existing packet/NEMU/VM checks stay. This command does not invoke
Vivado, full GSIM or Linux. No new cycle is intentionally inserted; measurement
and separate single synthesis/DCP queries must establish the actual cost/benefit.

The system group reuses machine.cpp's original fixed32/direct-IRQ oracle unchanged.
Its wrapper has the same staged backend but disables compressed helpers and the
separate IMSIC IRQ output register. Production-registered old/new fixtures both
fail that oracle's zero-delay eligibility assertion; failure logs and FIR are
archived. Direct-IRQ pass is NOT production registered-IRQ temporal acceptance.
Use RecoveryMachineCoreGsimMain OUT PROFILE registered-irq to reproduce the
registered fixture. Do not remove assertions or promote100MHz from this test.

Actual20261002 acceptance is seven original groups plus a system-only direct-IRQ
supplement, not one fabricated all-pass run. Thirty Scala checks and810304
independent recovery/token vectors pass; original8/64tag ledger, packet/NEMU/VM
and identical board binaries pass. All26 complete IPC rows, VM2525cycles/675retired,
CoreMark731130ticks and DDR5295/7714/12987/3847 are unchanged. Six negative
injections and sanitizers remain. Registered old/new fixture failure logs/FIR are
kept separately; production registered IRQ temporal validation is outstanding.

The separate single synthesis and49 DCP-only queries completed: recovery control
through-paths improve, but global10.590->10.931ns/WNS-0.608->-0.949ns regresses
to PRF writeback. LUT decreases1687 to128031, FF61426; this is not a promoted
100MHz result. All16 endpoint families and new3 scopes, logs, firmware and frozen
sources are under E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-recovery-control.
No full GSIM/Linux, route or bit. Existing50MHz/115200 release and defaults stay.

### Execute/result/writeback selection short batch

GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-execute-select-stage-test
selects staged-execute-select (exact2-issue recovery baseline plus parallel rank,
ALU result and complete-payload selection). Eight affected groups only:
contracts/selection/execute-selection/prediction/core/system/vm/board.
Independent procedural circular scan covers16/32 entries; the unmodified unsigned
ISA model checks old and new ALU outputs including illegal controls and word
combinations, not merely mutual equivalence. Complete payload fields/full64 tags
and all32 source masks are checked against procedural highest-priority selection.
Arithmetic, payload-bit63, rank, packet, NEMU and system negatives stay. VM and
same-image board CoreMark/DDR reuse existing drivers; no fullGSIM/Linux/Vivado
is invoked by this target. System scope is fixed32/direct-IRQ, not production
registered IMSIC latency. Default/IP/clock/reset/bit are unchanged.

The20261002 gate passes as33 Scala checks plus seven runtime groups (runtime raw
partial-pass, preserved). Initial inferred-width .pad elaboration and new-driver
Memory/dataBase header dependency failures are archived; only normalization/
driver context was repaired, no oracle relaxed.1087008 arithmetic,20384 payload,
28736/87648 circular-scan vectors and8 negatives pass. Original packet/NEMU,
direct-IRQ system and coherent VM pass. All26 complete IPC rows and VM2525/675,
same-image CoreMark731130 and DDR5295/7714/12987/3847 match recovery-control.
One separate121-SV pre-mapping10ns synthesis is running; no Fmax/area/100MHz claim.
Evidence:E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-execute-select.

### Independent clock scheduling capability probe (not CDC acceptance)

GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 python3 simulator/gsim/clock_probe.py
builds only IndependentClockProbeGsim: two unrelated Clock inputs, separately
enabled16-bit counters, and AsyncReset inputs. The procedural oracle counts only
each input's rising edges. It covers held-low/high, A-only/B-only, simultaneous
edges and unequal5:3/5:7 ratios with phase offsets. Outputs settle with enables
disabled; initial-zero, disabled-hold and enabled-progress sanity are checked.
Post-activity asynchronous reset is separately required without another edge.
No CPU regression, synthesis, vendor change or generated-DUT patch is involved.

Pinned93b8cd23 current behavior does NOT qualify: all seven edge cases mismatch;
held-low16step produces16/16 instead of0/0, and5:3 produces300/300 instead of50/30.
Post-activity AsyncReset leaves32/32 instead of0/0. The first attempt's reused
model fails reset sanity; its driver/FIR/logs remain in independent-clock-probe-
20261002. The v2 run uses fresh instances per edge case and separately observes
reset, without weakening either oracle. --observe exit0 is investigation only;
the same binary without that option fails the unchanged acceptance contract with
exit1. results.json says clock-or-reset-not-supported/independent_edges_verified
false, not PASS. ASan/UBSan remain enabled. Archive: staged-execute-select/clock-probe.

Unmodified independently clocked wrappers must not serve as dual-clock CDC/RDC
acceptance evidence in this pinned flow. Single-clock functional short checks
are not independent-edge/phase coverage. Dedicated multi-clock simulation would
need an explicitly approved workflow exception; no alternative backend is enabled
by this probe. See fpga/zu15eg/clock-domain-plan.md for the pending bridge gates.

### 2026-10-02 staged-frontend-select short acceptance

Run GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 make gsim-frontend-select-stage-test.
The 20261002 combined run passed36 Scala checks and contracts/frontend-selection/
fetch/prediction/core/system/vm/vm-fetch/board. Independent control encodings,
literal full64 AUIPC/JALR arithmetic and selected-set tag scans passed277728
vectors; all10 negative injections failed as expected. Two/four-wide mixed
fetch, PMP/context/kill and cross-page fetch retain their original oracles.

Actual board FIR contains two FrontendControlDecode, one
AuipcPredictionQualification and three ParallelFetchTagLookup instances.
All26 IPC rows (23 fields each), VM2525/675, same-BIN CoreMark731130 and DDR
5295/7714/12987/3847 match staged-execute-select. One board model is reused.
CoreMark one iteration is CRC/cycle regression, not a valid benchmark score;
DDR is synthetic AXI timing. Fixed32/direct-IRQ system is not registered-IRQ
temporal acceptance. No full GSIM/Linux or alternative simulator was invoked.

196 source snapshots and78 byte-verified raw log/FIR/firmware artifacts are in
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-frontend-select.
No export/synthesis yet for this profile; the prior frozen121-SV synthesis
remains separate and running. Clock/reset/IP/default/released bit are unchanged.

### 2026-10-02 10:41 停止异常综合（覆盖上文“仍运行”的历史状态）

用户要求“看看为何卡死，过于异常就停住”。已确认staged-execute-select本次
08:31开始的命令行综合在Timing Optimization异常耗时超过两小时：
主日志08:35:35后未写，内部文件08:41:10后未写；3秒采样主线程CPU增加3.109秒，
读/写字节均不变。系统仍有约11GiB物理内存可用，未见内存耗尽或等待磁盘证据。

现场保留520619929字节的timing文本（6490668条c记录），这不是LUT使用量，也不能
仅凭文件大证明因果。怀疑新组合图触发时序优化算法异常耗时，尚未区分RTL触发、
工具缺陷或定位唯一模块；无栈采样，日志未报latch/组合环/多驱动/fatal错误。

已按用户授权停止PID49884及专属辅助进程，10:41:53确认全部退出；GUI PID37688
及原bit未动，未删文件、未另起综合。CLI exit1由人工停止造成，不记作工具自身报错。
无soc_blackbox/soc_candidate DCP，因此不能继续checkpoint查询或宣称新时序/面积。
两批功能短测结论保持，但staged-frontend-select仍未导出/SYN。

诊断、日志/journal/timing哈希及停止证据见
E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-execute-select/synthesis-hang-diagnosis.json；
两个候选results.json已更正。建议先做rank/ALU/completion局部定位，未经确认不重跑
整颗SoC。官方debug_log、RuntimeOptimized/no_timing_driven可用于后续经批准的诊断，
但减少/关闭时序驱动的结果不等价于原10ns候选签核。
[AMD2025.1综合设置](https://docs.amd.com/r/2025.1-English/ug901-vivado-synthesis/Using-Synthesis-Settings)。

### 2026-10-02 post-short-test synthesis and generated-output cleanup

The unchanged, short-tested staged-frontend-select hardware was exported once
(124 SV, dual issue,50MHz/115200) and synthesized once with a10ns pre-mapping
clock, RuntimeOptimized/debug_log and a25-minute descendant-only guard.
It completed normally in430.5s (synth_design308s). No new GSIM/Linux/full suite
was run for these workflow/report-only changes; the36 Scala/nine-scope
acceptance and26 complete IPC-row equality remain the recorded functional evidence.

57 checkpoint reports are complete: WNS-0.313ns, CPD10.295ns, TNS-68.758ns,
2062 failing endpoints. The first query stopped on an incorrect expectation of
three surviving tag-helper instances; read-only inspection found two (RTL
contains three), with both control decoders and AUIPC qualification retained.
Only seven missing reports were added; failed logs were retained. No DUT,
oracle, default or bit change. Changed synthesis strategy confounds RTL-only
attribution; synthesized OOC results do not qualify actual100MHz/CDC/RDC.

Removed278 regenerable model/object/executable files from nine older staged
directories (932954165 bytes). Raw logs, FIR, firmware BIN/ELF, user-authored
source and current frontend models remain. The old failed synthesis .Xil was
fully verified and archived before deletion; total net space released1.37GiB.
Exact files and recovery notes: E:/VM/Share/Valence-rtl/ddr-opt-20261002/
cleanup-20261002.json. Detailed QoR and pending gates: docs/fpga-timing-windows.md.

### 2026-10-02: combined sensitive-path candidate, not promoted

Run the necessary combined acceptance with a fresh tag:

```bash
GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 \
  python3 simulator/gsim/retire_stage.py --profile staged-sensitive-paths --tag 20261002-r1
# Convenience target: make gsim-sensitive-paths-stage-test
```

This exact frontend-select baseline adds only parallelPredictionSources,
parallelAddressSums and bufferedFetchRequests; issue2/ROB16/PRF48/tag64 and
cache/LSU/SB/predictor capacity are unchanged. Independent target qualification
preserves presence-before-eligibility priority. Seven fixed full64 Zba sums
move opcode/UW selection after arithmetic without another execute register.
The two-entry non-flow/non-pipe instruction request queue has II1, occupancy-only
enqueue-ready and +1 physical request cycle; address/mask/fault/response
backpressure and ownership are preserved. It is not a new clock domain.

All ten requested scopes passed:39 Scala/eight suites;4096 priority vectors;
14337 completed requests each for2/4 words, full/reset/zero-mask/fault/immediate
reply and1000 streaming cases;1087008 arithmetic and20384 arbitration vectors;
packet/core-system NEMU/data-VM/cross-page fetch. Nine negative-oracle logs
are retained. The first attempt failed on a missing Cat fixture import;
the corrected r1 full short batch passed. No vendor/oracle modification.

All26 bare-core IPC rows match all23 fields; that fixture bypasses the new
physical request queue. Same-BIN platform results: VM first trap2525->2530
cycles/675 retired; CoreMark single iteration731130->761601 ticks (+4.17%);
DDR read/write/copy/chase5295/7714/12987/3847->5323/7733/13006/3849.
One board model serves both applications. Original short-run CoreMark warnings
remain; the harness checks established list/matrix/state CRCs and exit.
These are not official CoreMark scores, FPGA bandwidth or full Linux acceptance.
Registered production IMSIC temporal behavior remains unverified.

One127SV export and one RuntimeOptimized, pre-mapping10ns synthesis completed
normally in484.5s (synth_design376s), matched to the immediate baseline strategy.
One178.6s checkpoint query produced all59 reports; no second synthesis.
CPD10.291/WNS-0.309/TNS-5.783,244 failing endpoints (baseline2062).
PRF9.934/stateCE6.562/issuequeue9.538 are positive, but RAT10.291/PC10.014
remain negative and PRF has only48ps. LUT+814/FF-1, BRAM/DSP unchanged.
Sources2/buffer1/ready feedback0 and all previous response/rank/fault isolation
contracts survive. The ~0.04% OOC period estimate does not offset CoreMark
cycle cost; this candidate is retained but not promoted. No route/bit/default/
MMCM/full GSIM/Linux/third domain/DFS changes.

Evidence: E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-sensitive-paths/
results.json, short-tests.json,86 short-raw files,59 checkpoint-query/reports,
timing-comparison.json and source/rtl manifests. Detailed measured path table,
including regressions and remaining gates: docs/fpga-timing-windows.md.

### 2026-10-02 decode/alignment and request-latency batch (two issue)

Reproduce the complete focused twelve-scope candidate, without Vivado:

    GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 \
      python3 simulator/gsim/retire_stage.py --profile staged-decode-align --tag YOUR_FRESH_TAG
    # Convenience target: make gsim-decode-align-stage-test

This exact sensitive-paths baseline adds parallelFetchAlignment,
parallelDecodeLegality, flowThroughFetchRequests and parallelMinMaxResults.
Fixed halfword candidates prepare both second-lane offsets before length selection.
Class-parallel legality preserves the original B input and full request/operation
priority. MIN/MAX qualifies operands before shared result masks, with unchanged
full64 signed/unsigned comparisons and W semantics. All are stateless, II1.
The two-entry queue flows only when empty, remains pipe=false, and never borrows
full-queue dequeue credit. Responses/faults/backpressure/owners are unchanged.
No new CPU pipeline cycle, capacity change, four-issue claim or clock domain.

Acceptance covers42 Scala/nine suites,655552 decode vectors/four configurations,
131072 alignment cases each for widths2/4,14337 requests each for words2/4,
1087008 arithmetic/20384 completion-arbitration cases, packet/core-system NEMU,
data VM/cross-page fetch and two original binaries sharing one board model.
Fourteen injected-negative logs remain. The first attempt passed contracts/decode/
alignment then failed to compile a new C++ getter (one $ instead of two).
Only the fixture was repaired; the remaining nine scopes were continued.
Preserved first JSON=failed, continuation JSON=partial-pass; aggregate acceptance
is passed, not a rewritten claim of one flawless full run.

All26 bare-core IPC rows match all23 fields. Same-image CoreMark761601->731130
cycles (-4.00%, same-frequency model throughput+4.17%); DDR4K read/write/copy/chase
5323/7733/13006/3849->5295/7714/12987/3847; VM first trap2530->2525/675 retired.
These recover the older frontend-select cycle counts rather than improve on them.
One-iteration CoreMark warnings remain; fixed CRCs/exit pass. No valid official
score, FPGA bandwidth, production registered IMSIC temporal or Linux acceptance.

One129SV export/425.4s RuntimeOptimized pre-mapping10ns synthesis completed.
The54-report first query stopped on stale tag-helper count2; the candidate retains3.
Report-only fix and seven-report supplement produced all61 using the same DCP.
Original logs/query snapshot remain. No re-synthesis or DUT/oracle relaxation.
CPD10.178/WNS-0.196,106 failing endpoints; TNS worsens to-12.991.
PC9.795 is positive; B legality->second destination/free/RAT remains negative.
PRF9.941 has only41ps and scoreboard9.921 only61ps (both margin regressions).
LUT+580/FF+2, BRAM/DSP unchanged. No default promotion, route, bit, MMCM/MIG,
full GSIM, long Linux, third domain or DFS. Actual RTL remains50MHz/115200.

Evidence: E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-decode-align/
results.json, short-tests.json,122 short-raw files,61 checkpoint-query/reports,
timing-comparison.json, source/rtl manifests and report-query-fixes.
Full path table, regressions and unverified physical gates: docs/fpga-timing-windows.md.

## 2026-10-02 word/destination timing candidate

The opt-in staged-word-destination inherits staged-rank-legality and adds early raw architectural-rd payloads plus per-class W/address-result preparation. Two issue, ROB16/PRF48, no new state or execution cycles, unchanged default/release. Raw rd is never authorization; every authorized writer must match the public decoded rd. The ledger fixture deliberately supplies unrelated raw rd for nonwriters; the independent oracle remains unchanged.

Reproduce only the affected short batch (8 scopes; no Vivado/full regression/Linux):

```sh
GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 python3 simulator/gsim/retire_stage.py \
  --profile staged-word-destination --tag your_unique_tag
```

Acceptance: 48 Scala tests/11 suites, ALU arithmetic1087008 plus illegal653861, independent ledger tag8/64 18000 cycles each, prediction/NEMU/system/coherent VM and one board model reused for CoreMark+DDR; all pass, 6 injected negative controls rejected. CoreMark731130 and DDR5295/7714/12987/3847 ticks match byte-identical binaries; 26 IPC rows×23 fields and VM2525/675 match decode-align. The one-iteration CoreMark raw under-10s ERROR remains archived: CRC/exit smoke only, NOT a score or FPGA bandwidth.

Frozen228 inputs,131SV+1resource,70 raw files and66 DCP reports have SHA256 indexes under E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-word-destination/. Original failed compile, failed/partial-pass/passed driver reports and first-source overlays are retained; neither DUT expectations nor independent ISA/NEMU/ledger gold were relaxed. OOC 10ns WNS=-0.115, CPD=9.915, setup failures=80; NOT routed/board100MHz evidence. No bit/default/clock-IP promotion. Full family and regression table: docs/fpga-timing-windows.md.

Primary66 reports aggregate the retained57-query plus9 successful primary supplements. The two broad-NAME query failures and later optimized-checkpoint frontend-contract failure remain archived; they are NOT labeled wholly successful. Only the live report helper changed after source freeze; hardware/oracles remain frozen. Post-synthesis opt_design was not selected because slack regressed to-0.147ns.

## 2026-10-02 request-capture/parallel directory timing candidate

staged-request-capture inherits staged-word-destination, adds only opt-in independentFetchCapture
and parallelHomeQualification, keeps two issue and defaults/releases unchanged. Three combined
changes: capture-on-enqueue independent of downstream ready, parallel physical way-tag matches,
exact static half-open RAM prefix qualification. Capacity2/flow=true/pipe=false/II1 and visible
latency/backpressure/faults remain identical. Empty bypass may perform an invisible RAM write;
dynamic power is unmeasured.

Run only the affected batch (no full regression/Vivado/Linux):

```sh
GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 python3 simulator/gsim/retire_stage.py \
  --profile staged-request-capture --tag your_unique_tag
```

51 Scala tests/12 suites, 2/4-word FIFO14337 each, 360000 independent directory/range vectors,
5 rejected mismatch injections, coherent VM and virtual cross-page fetch plus one board model
reused for both unchanged firmware binaries passed. CoreMark731130, DDR5295/7714/12987/3847,
VM2525/675 are unchanged. Prior bare-core NEMU/26IPC evidence is retained, NOT rerun this batch.
The raw short-CoreMark under-10s ERROR remains; no official score or real DDR bandwidth claim.

One700.7s pre-map10ns RuntimeOptimized synthesis and189.1s reused-DCP query71 reports: WNS+0.234,
setup failures0, native capture WE1.011ns, ready-to-WE and ready-to-enqueue feedback paths0.
LUT-31/FF+1. ROM response/next-request feedback still has only234ps; not all edge risks solved.
No route/bit/default promotion/clock changes; physical100MHz/150MHz, third domain/DFS unverified.
Evidence: E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-request-capture/ (232 inputs,131SV+1resource,
66 raw files,71 reports and hash indexes); see docs/fpga-timing-windows.md for every family.

## 2026-10-02 ROM/fabric registered-boundary candidate

`staged-rom-boundary` inherits `staged-request-capture` and adds only the opt-in
`registeredFabricBoundary` flag. Defaults and two-issue ROB16/PRF48/cache geometry
remain unchanged. The related batch replaces the two-entry physical data FIFO's
pointer-indexed read with dedicated head/tail registers, registers TL A and D
before each physical crossbar master, and removes invalid-cycle source selection
from the associated arbiters. No instruction execution stage or ROM IP interface
was changed. New boundaries have capacity two beats per direction, II=1, no empty
bypass and no full-queue credit borrowing; the fabric adds one request and one
response cycle. Sources, errors, masks and burst beats remain ordered together.

```sh
GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 python3 simulator/gsim/rom_boundary.py \
  --tag your_unique_tag
```

Affected checks only, no full GSIM/NEMU/Linux simulation: 23 Scala checks,
independent 50,000-cycle A/D FIFO oracle (32208/27813 consumed beats, 14059 full
dequeues, 29057 simultaneous transfers, four reset-cancelled beats), data/MMIO
classification, crossbar negative controls, coherent virtual data and cross-page
fetch, and one exact 100 MHz/460800 board model reused for CoreMark, DDR and UART
download. ASan/UBSan remain enabled. The queue reset driver was first corrected
to quiesce offers during reset; the original failed log remains archived.

Byte-identical CoreMark BIN: 731130 -> 743778 ticks (+1.73%), CRC/return PASS;
DDR BIN SHA256 `46d728ef19758a8273dc488b4f5399f8951e3e9934fe507087b5f27926773110`
is identical to the previous candidate, with ticks 5295/7714/12987/3847 ->
5406/7970/13369/3997. Its reporting constants deliberately remain 50 MHz; the
model uses 100 MHz/460800. `APP_TIMEBASE_HZ=50000000` keeps the independent rate
arithmetic oracle aligned with that known firmware build and checks its banner,
rather than deriving expected values from DUT output. The first mismatched
test configuration and separately resumed PASS are retained; this is neither a
formal CoreMark score nor a physical DDR bandwidth measurement.

Virtual data first trap is still 675 retired instructions, 2525 -> 2585 cycles.
Exact-clock download regression passed in 16778721 cycles/936 UART bytes,
including continuous 8N1, CRC retry, bounds, rewrite/fence.i and image invalidation.
The original failed aggregate reports were not overwritten: `short-tests.json`
records the passed checks and resumed logs in the frozen candidate directory.

Evidence: `E:/VM/Share/Valence-rtl/ddr-opt-20261002/rom-boundary-board100-u460800/`,
500 captured source files, 133 SV plus one memory resource, and 64 short raw files
with hashes. Default/rebuilt synthesis was stopped after 3383.8s without a DCP;
exit7/timed_out=False reflects an external stop, not successful completion.
Fresh RuntimeOptimized/rebuilt synthesis used unchanged RTL and pre-map10ns,
completed exit0 in644.8s with real ROM/BB0, OOC WNS+0.539/TNS0/data9.443ns.
Board assembly/implementation started. There is no
new routed signoff, bit, physical UART/DDR verification, third peripheral clock
domain or runtime DFS claim. Only full board signoff permits 100 MHz delivery.

The ROM-boundary board flow hit its combined implementation guard at 22:33 on
2026-10-02, after placement/route verification but before a routed checkpoint.
It did not pass 100MHz signoff. See docs/fpga-timing-windows.md for the saved
placement's per-family long-path audit and the staged-control-heads batch.

Reproduce the affected short acceptance (no full regression or Linux simulation):
`GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 python3 simulator/gsim/rom_boundary.py --profile staged-control-heads --tag UNIQUE`.

For the opt-in two-issue operand/raw-fetch pipeline candidate, finish the whole
related batch before running the affected short checks:

```sh
GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 python3 simulator/gsim/rom_boundary.py \
  --profile staged-throughput --tag UNIQUE
GSIM_CXX=clang++-19 GSIM_BUILD_JOBS=8 python3 simulator/gsim/throughput_perf.py \
  --tag UNIQUE --baseline-model build/gsim/control-heads-ddr100-20261002-batch5/core
```

The short runner covers contracts, execution/fetch register oracles with negative
controls, virtual data/instruction translation and one reused 100MHz/460800 board
model for same-BIN CoreMark/DDR. It does not repeat the unchanged long UART upload.
The performance runner reuses the byte-pinned baseline model, runs 12 short A/B
ISA/NEMU workloads and 50 control/memory checks, and requires actual forwarding,
held-port independence and older-lane0 recovery witnesses. Source manifests must
match between both runs and candidate export. Store preparation/LSU starts are
issue grants, not necessarily unique retired instructions; use commit IPC for
architectural throughput. Correctness PASS is not a performance-improvement claim.

October3 follow-up was PREPARED at the read-only diagnostic snapshot; the newer
expanded final-path batch described below supersedes that source status.
The same five short check groups now additionally require full64 adjacent-tag
selection, stateful width2/4 compressed cache offsets/fault/invalidate checks,
width2/4 plain/compressed raw packet hint qualification, and trusted head-trap
ledger directed/random positive and injected-negative checks. The eight original
machine IRQ cases (external/timer, empty/load/store/synchronous-fault priority)
retain the independent SystemModel and original program construction; they use
DIRECT-IRQ, not production registered IMSIC, and are not NEMU IRQ co-simulation.
Actual head-trap/empty-trap witnesses are required. The current explicit manifest
`config/throughput_feedback_inputs.json` binds42 listed wrapper/harness/contract/
runner/payload/config hashes before/after execution and the collector checks the
exact path set and live hashes twice. It is not a complete transitive build-input
closure. Old logs cannot qualify the new flags. Keep the pinned NEMU A/B runner
as separate architecture/performance evidence.

The expanded batch adds a6000-cycle independent physical-scoreboard/age-walk
oracle for owner readiness, store-top2 grant coverage and MUL/DIV availability,
plus four independent instruction permission configurations: 2word generic,
2word aligned and4word aligned retimed, and2word generic historical. Successful
physical launch must remain last-translation+1; fully PMP-denied fault response
is explicitly+1 later in the retimed profile. CSR update draining and held first-
offer permission ownership remain mandatory. Each new negative control must
exit1 by its named oracle, never a PASS or sanitizer crash. The helper alone does
not verify Backend wake-token filtering/latekill/budget or early physical replies/
all physical-fault relocation cases; short core-NEMU/VM/board integration remains.
`finalpaths-batch1` passed all five scopes, and the separate pinned NEMU A/B plus
collector passed. Same-BIN CoreMark799934/DDR5369/8010/13361/3975 and VM2721/675
match the saved throughput-credit batch; no additional cycle cost is measured.
Receipt: `build/gsim/throughput-ddr100-20261003-finalpaths-accepted/`.
No new synthesis or routed result is asserted yet; keep the existing pipeline
cycle regressions visible when reviewing frequency-times-IPC.

Final October3 evidence: `throughput-20261003-batch3` plus
`throughput-perf-ddr100-20261003-batch2`, all required checks passed. ALU steady
state remains two/cycle; jump132 vs130, loop147 vs139, single-iteration board
CoreMark799934 vs743697 ticks. The same-clock 12-case geometric mean is0.98373676;
the CoreMark cycle cost requires more than7.56% usable clock improvement to offset.
No official CoreMark score, FPGA bandwidth, routed100MHz or board Linux claim.
It checks retirement-training events/reset/aliasing, registered response credits,
parallel memory rank/PRF payload selection, independent PMP boundary permissions,
short control/memory execution against NEMU, VM data/fetch, and one shared exact
100MHz/460800 board model for CoreMark, DDR and BootROM download. The bare NEMU
model uses the board's 2-issue/ROB16/PRF48/2-slot/32-BHT geometry, but uncompressed
instructions; VM and board models cover compressed fetch. Four-lane helper tests
are not four-issue CPU acceptance. Predictor-training expected events are derived
from the independent ISA model, then delayed one cycle, not copied from the DUT.

The accepted finalpaths-batch1 hardware has now completed board routing and failed
strict100MHz release: final WNS-0.885ns/TNS-5393.550/15262 setup failures. Hold,
pulse,14 bus-skew checks, routing, CDC and error-level DRC passed; no bit was made.
New live-source head-system/shared-decode/store/raw-fault cuts are NOT covered by
that old acceptance. Finish the entire batch before the next short invocation.
The new runner retains all five affected scopes and independent NEMU separately;
adds independent three-client physical-decode checks, retain1 ledger/alias checks,
and legal FENCE.I flush-backpressure SystemModel A/B cases with actual collision/
rollback witnesses and strict injected negatives. Raw-fault readiness and store
decoupling checks are still being completed. Before execution, extend the exact
enumerated input set for every newly selected fixture/helper; do not relabel old
receipts, infer board stability from OOC, or remove independent oracle failures.

Finalpaths-batch2b now passed the complete necessary short set and independent
NEMU A/B. Fresh collector receipt is
`build/gsim/throughput-ddr100-20261003-finalpaths-batch2-accepted/` (159hardware
Scala/53 enumerated test inputs). Initial finalpaths-batch2 failed only at an
illegal alias-fixture parameter combination; its logs remain preserved and the
non-aliased-only production guards were not relaxed. Store6000cycles/4500 invariant
pairs, raw-fault40/48 each288cases, three independent physical clients and trusted
retain1 ledger/MachineCore A/B all passed their named strict negatives. Raw-fault
fixtures cover rename/ready only, not retirement/recovery/refcount recycling.
Legal system backpressure24cases/1663cycles matched the generic recovery path;
DIRECT-IRQ limitations remain. NEMU12 workload records, VM2721/675, same-BIN
CoreMark799934/DDR5369/8010/13361/3975 match the previous batch. No new measured
cycle cost, official CoreMark score, physical DDR rate or100MHz stability is claimed.

That exact fresh acceptance now binds the successfully signed authorization-board100-
u460800 candidate: actual routed100MHz WNS+0.101/TNS0, hold+0.010/pulse+0.081,
14bus-skew/route/reset/CDC/bitstream DRC/expected ROM identity PASS. Bit and
matched100MHz/460800 Linux image are released. This is static FPGA signoff only;
the existing Linux manifest correctly retains physical/long-GSIM verification=False.
No repeated full regression, relaxed timing exceptions, extra measured cycles,
dynamic-frequency or external Linux IRQ validation is implied by release.


## F/D isolated development: FLEN64 transaction state (2026-10-03, M1)

`FloatingPointState` is a standalone 32x64 architectural FP register file and
single-outstanding, ROB-head-authorized transaction boundary. It has three
combinational reads and one retirement write (including writable f0). Issue,
execution, completion and retirement have registered boundaries; the external
producer has at least one-cycle latency. Capacity is one, with no same-cycle
refill. Execute and completion payloads hold under backpressure. Full ROB tokens
reject stale results and retirement; flush wins over results and retirement.
IEEE64 / boxed IEEE32 are the architectural transport, never HardFloat recFN.
The path through the 32-entry read mux and boxing is not synthesis-qualified.

FP registers, accrued flags and Dirty state change only on authorized retirement
or idle CSR/FS access. FS=Off and reserved effective rounding trap; non-rounding
operations ignore reserved rounding fields. Context writes serialize with all
in-flight FP work. Reset clears architectural state; integration must also reset
or drain the producer and avoid reusing live token generations. An exception
completion must be resolved by the future precise-trap adapter, not counted as
an architecturally retired instruction.

The scalar GSIM wrapper fixes generated C++ Vec-port API incompatibility without
modifying the production Vec interface or generated simulator sources. Run:

```
GSIM_CXX=clang++-19 GSIM_SOURCE=/path/to/pinned/gsim make gsim-fp-state-test
```

Positive ASan/UBSan run passed 7875 cycles, 647 accepted requests, 609 resolved
entries, 619 stale/drained responses, 1208 blocked context accesses, 278 operand
boxing canonicalizations and exactly 28 illegal instructions. Send/wait/complete
flush coverage is 12/12/11; four reset boundaries and a simultaneous matching
response+flush are checked. Injected FCSR mismatch was rejected (exit 1 at cycle
100). Evidence: `build/gsim/floating-point-state-m1/{test.log,negative.log,receipt.json}`.
The initial 6066-cycle failure is preserved in the `-initial-coverage-failure`
directory: its original matrix contained exactly 20 illegal cases while its
coverage assertion required >20. The updated test pins that count and adds eight
FS=Off non-rounding cases plus nine reserved-but-unused rounding cases.

This does not implement CPU F/D decode, FP load/store, integer-result routing,
privileged FS/SD aliases, arithmetic, Linux FP context switching or board timing.
F/D misa bits and device-tree advertisements remain disabled. Future integration
must serialize fcsr, connect mstatus/sstatus FS/SD with privilege masks, preserve
raw store/move bits and boxed load semantics, and test precise LSU fault/flush
handling. The independently checkpointed two-issue 100MHz board baseline is not
an F/D timing result. HardFloat dependency evaluation is separately pinned in
`simulator/gsim/config/floating-point-dependencies.json`.


## F/D isolated development: FADD.S / FSUB.S producer (2026-10-03, M2a)

`FloatingPointAdd` accepts `FloatingPointExecution` and returns a held
`FloatingPointResult`: one issue port, one result port, capacity one, one-cycle
latency, minimum initiation interval two cycles (no same-cycle refill). Flush
cancels acceptance/results. A full 64-bit ROB generation is retained. IEEE/boxed
operands and results stay outside HardFloat; recFN is internal only. Canonical
NaN, five resolved rounding modes and after-rounding tininess are explicit.
Unsupported operations or unresolved/reserved rounding return illegal metadata.
The producer assumes decoded/resolved rounding from the state boundary; it is
not a CPU ISA decoder. Add/normalize/round is combinational and FPGA frequency,
resource use and timing are unmeasured.

The eight required HardFloat sources at
`c1105e6ac6a0dd90fc80893efc4830ab609005d3` compile with the unchanged project
Scala 2.13.17 / Chisel 7.3.0. A local bit-equivalent unsigned alignment expression
works around a pinned GSIM signed-Mux slice lowering error. The original failing
minimum-subnormal + maximum-subnormal case, generated model, upstream/local
hashes, patch and independent 1,048,576-pair expression check are preserved.
See `third_party/berkeley-hardfloat/README.md` for the migration and comparison
with official Verilog (whose GSIM blackbox bridge remains unverified).

`make gsim-fp-add-test` builds fixed SoftFloat revision
`a0c6494cdc11865811dec815d5c0049fba9d82a8` independently (8086-SSE specialization;
canonical output NaNs and explicitly mapped exception flags). Ten known-answer
anchors check the reference adapter, then all 34,840 edge/random vectors are
numerically compared, including all five rounding modes, zeros, subnormals,
normal/subnormal boundary, cancellation, overflow, infinities, qNaN/sNaN and
malformed boxing. Every cancelled vector is compared before flush. The producer
also checks held-result backpressure, blocked same-cycle refill, six illegal
requests, full tokens and reset of an occupied buffer. Add/sub cannot generate
divide-by-zero or inexact underflow in the same binary format; observed NV/OF/NX
coverage is required instead of claiming unreachable flag coverage.

An additional GSIM fixture wires the actual producer into `FloatingPointState`:
500 SoftFloat vectors, static/dynamic rounding, retirement-only flags/Dirty/RF
updates, stale/unauthorized retirement, three cancellation phases and one illegal
instruction. Register seeding uses an explicit test-only raw result path, not an
implementation of FLW/FLD or instruction decoding. Both test drivers reject an
injected numerical mismatch. ASan/UBSan are enabled. M1 state positive/negative
acceptance was repeated successfully after the scalar fixture extension.

Evidence: `build/gsim/floating-point-add-reference/receipt.json`, plus producer
and integration `test.log` / `negative.log` under `floating-point-add-m2` and
`floating-point-add-state-m2`. Reproduce with:

```
GSIM_CXX=clang++-19 GSIM_SOURCE=/path/to/pinned/gsim \
SOFTFLOAT_ARCHIVE=/path/to/pinned/softfloat.zip make gsim-fp-add-test
```

The runner checks the reference archive hash and extracted source identity;
the manifest and README provide source URLs and full revisions. F/D CPU decode,
FP load/store, integer-result paths, FS/SD privileged aliases, multiply/FMA,
divide/sqrt/comparison/conversion, binary64 arithmetic, Linux context switching
and FPGA timing are still pending. misa/device-tree F/D remain disabled; existing
100MHz board results do not qualify these additions. This is a first arithmetic
milestone, not completion of either extension.


## Experimental real-CPU FP subset (2026-10-03, M3)

`experimentalFloatingPoint` defaults to false and requires `machineSystem`.
The enabled configuration decodes and executes FMV.W.X, FMV.X.W, FADD.S and
FSUB.S through the real two-issue CPU. FP register numbers are excluded from
integer renaming; FMV.W.X reads an integer operand, while FMV.X.W produces an
integer result preserving raw low-32 bits and sign extension. The existing
protected ROB-head system transaction authorizes all FP execution. Full-token
real ROB retirement updates FP registers, arithmetic flags and Dirty state.
fflags/frm/fcsr accesses and mstatus/sstatus FS/SD aliases use the existing
irrevocably authorized head CSR path. A separate trap-ready signal permits a
faulted, still-busy FP transaction to take its own precise trap and release state.

`FloatingPointSystem` is a conservative baseline: one input, one completion
port, one outstanding operation, no FP renaming and no same-cycle refill.
A legal accepted command crosses registered execute, producer and result
boundaries before completion (three cycles without backpressure), then waits
for the system completion and actual ROB retirement. Illegal FS/rounding
commands bypass the producer and offer completion after one cycle. Initiation
interval is retirement-bound and increases with commit stalls; wider integer
issue does not increase FP throughput. Add/normalize/round remains combinational.
No synthesis frequency, area, power, routed timing or board result is claimed.

The new fixture wraps `MachineCore` and supplies real instruction words. FP
registers are initialized only by decoded FMV.W.X instructions; observational
probes cannot inject results. An independent architectural model checks ordered
integer/FP commits, all 32 FP registers, f0, raw NaN moves, five rounding modes,
static/dynamic rounding, accumulated flags, FS/SD aliases, CSR read/write/set/
clear, reserved encodings, precise cause/PC/tval and MRET. SoftFloat values are
looked up using the model's current architectural operands, not DUT state.
CPU arithmetic covers 123 cases per seed; the earlier M2 producer acceptance
is the broader 34,840-vector numerical test and is not repeated by this target.

Both CPU seeds passed: each committed 2,538 instructions including 587 FP
operations (123 add/sub, 464 moves), took 15 precise illegal-instruction traps,
held retirement for 4,172 cycles and observed 596 held completions. Three
wrong-path FP/CSR instructions were accepted by the frontend but never executed.
Enabled and disabled configurations each passed the existing MachineCore short
suite: 34 main programs, 10,947 commits, 76 traps and 39 interrupts, plus its
supervisor/timer subtests. The CPU checker and both integer checks rejected
injected mismatches. C++ checks used ASan/UBSan. Existing `OooParamsSpec` passed
17 configuration/elaboration tests. NEMU is the pinned FPU_NONE integer/system
reference; it is not an FP differential oracle.

Reproduce after the M2 reference vectors have been generated:

```
GSIM_SOURCE=/path/to/pinned/gsim GSIM_CXX=clang++-19 \
NEMU_REFERENCE=/path/to/riscv64-nemu-interpreter-so \
NEMU_RECEIPT=/path/to/reference-used.json make gsim-fp-cpu-test
mill -i IonSoC.test.testOnly ooo.OooParamsSpec
```

Evidence is in `build/gsim/floating-point-cpu-m3/{receipt,final-source-receipt}.json`,
the CPU and `fp-integer-{disabled,enabled}-m3` positive/negative logs, and
`build/gsim/fp-cpu-m3-scala.log`. The final-source receipt records content-preserving
line-ending normalization relative to the tested source hashes.

This bounded milestone stops here. FP loads/stores, remaining F operations,
binary64 arithmetic, S/U-mode FP context behavior, Linux FP context switching,
concurrent multi-operation FP execution and FPGA timing remain unverified or
unimplemented. misa and device-tree F/D advertisements remain disabled. GSIM
is the only supported RTL backend in this checkout; a second RTL simulator was
not validated. SoftFloat supplies an independent arithmetic reference, not a
second hardware simulation backend. At the historical M3 handoff, the original
checkout was not modified; the later main integration below supersedes that state.

## Experimental FP memory batch (2026-10-03, M4)

The default-off real CPU subset now also executes FLW/FSW/FLD/FSD. It reuses
the ordinary LSU and external CPU DataPort with ROB-head authorization, drained
integer buffered writes, exclusive memory ownership until retirement, physical
PMP/data-privilege checks and virtual-request metadata. Loads retire into FPRs
with correct NaN boxing; stores preserve raw bits. FS=Off, misalignment, PMP,
bus and injected page faults are precise and leave FP state unchanged. FCSR
is unchanged by transfers; stores do not dirty FS. This is a serialized bring-up
baseline, not complete F/D, OS FP-context acceptance or measured FPGA performance.

`floating_point_memory.py` compiles the finished batch once, then uses only
focused GSIM fixtures: fresh M3 subset, actual CPU FP memory with direct and
buffered/registered-request configurations, and integer NEMU with FP off/on.
It rechecks retained M1/M2/M3 models separately without rewriting old receipts.
All C++ models use ASan/UBSan. Two FP-memory seeds per configuration each pass
3,085 commits, 75 FP loads, 104 FP stores, 800 FP retirements, 189 ordered
requests/responses and 57 traps. Nine fresh negative controls reject intended
commit/FPR/request-payload mismatches. Scala's 17 checks and both integer NEMU
short suites also pass. The FP arithmetic oracle remains independently built
SoftFloat, not NEMU or DUT output. Actual FLD now supplies malformed-box operands.

Evidence: `build/gsim/floating-point-memory-m4-r2/receipt.json`, `scala.log`,
and sibling `-subset`, `-direct`, `-buffered`, `-integer-disabled`,
`-integer-enabled` directories. The receipt includes source and generated
model/binary hashes. Failed earlier attempts are retained, not relabeled PASS.
Page-fault checks inject responses at the CPU boundary after real satp/MPRV
programming; a translated platform, S/U task contexts and Linux FP are not
validated by that fixture. Remaining F/D arithmetic, compressed FP transfers,
second RTL simulator, FPGA timing/area and multi-operation FP execution remain
pending. misa/device-tree F/D and the experiment default remain disabled.

Reproduce in this checkout after the M1/M2/M3 retained models and M2 pinned
SoftFloat vectors exist. Pick a fresh tag; accepted receipts are never overwritten:

```sh
GSIM_SOURCE=/home/openion/Valence/simulator/build/gsim-src GSIM_CXX=clang++-19 \
NEMU_REFERENCE=/home/openion/Valence/build/gsim/nemu-src/build/riscv64-nemu-interpreter-so \
NEMU_RECEIPT=/home/openion/Valence/build/gsim/reference-used.json \
python3 simulator/gsim/floating_point_memory.py --tag m4-repeat-1
```

Those tool/reference artifacts were consumed read-only in the independent M4
worktree; after main integration, new outputs are in the original project's
`build/gsim`. Equivalent pinned paths may
be selected on another machine. `make gsim-fp-memory-test` is the first-run
default tag entry point. It does not run full GSIM, Linux or Vivado.

The former Windows handoff is archived at `build/fd-handoff/20261003-windows`:
65 files verified individually by SHA256/length before removal of their Windows
copies. M3 completion is `fd-evidence/m3-completion.json` within that archive.
Old staged code/scripts are historical evidence and still contain old path
assumptions: do not execute them or copy them over current source. Use the
current WSL runners above; no Windows evidence path is needed for M4.

## 原 Valence 接续 / 100 MHz 浮点时序批次（2026-10-03 晚）

主开发目录已为 `/home/openion/Valence`。38 个 F/D 文件以原脏工作区快照为基准
增量合入，未合并或提交 Git，不丢弃既有修改；合入凭据及可恢复 Windows 归档在
`build/fd-handoff`。实验开关默认 false，misa/设备树 F/D 仍关闭。
M1/M2/M3/M4 是部分实现，完整 F/D、OS 浮点上下文与带 F/D 的整板 bit 尚未验收。

本轮只批量切两条浮点执行链：加减 raw/round 寄存器边界、访存 AGU/PMP 地址边界。
算术容量 1、延迟 2 拍、最小 II=3；访存多一拍，仍与 LSU 同拍真正接受、权限无旁路。
没有整数 issue 宽度/流水或板级频率修改。

原工程短批次 `floating-point-memory-main-timing-20261003` 已通过：

- 34,840 个 SoftFloat 数值向量；500 个状态集成向量；流水原始结果/保持结果
  的 flush/reset、动态舍入、NaN boxing 和完整 token。
- fresh M3、真实 CPU direct/buffered 浮点访存各两个 seed（每个 75 loads、
  104 stores、800 FP retirements）；FP off/on 各 34 主程序整数 NEMU。
- 11 个新严格负例，以及 4 个旧里程碑模型的正/负复核；ASan/UBSan。
- receipt 的 111 个源码哈希、32 个模型/可执行文件哈希重新匹配。

重现同样使用上面的环境变量，但必须选择新 tag：

```sh
cd /home/openion/Valence
GSIM_CXX=clang++-19 \
NEMU_REFERENCE=/home/openion/Valence/build/gsim/nemu-src/build/riscv64-nemu-interpreter-so \
NEMU_RECEIPT=/home/openion/Valence/build/gsim/reference-used.json \
python3 simulator/gsim/floating_point_memory.py --tag main-repeat-1
```

该 runner 现在总是新建 producer 和状态集成模型，不以旧数值 binary 代替新
流水化算法验证。必要的 SoftFloat vectors/receipt 与旧四个模型已迁入主工程，
历史凭据不重写。第二 RTL 后端仍未支持；只使用 GSIM。

模块导出：`mill -i IonSoC.test.runMain ooo.FloatingPointTimingMain <fresh-dir>`。
`fpga/vivado-fp-modules.tcl` 一次测三个小模块的综合/布局/布线；10 ns、PMP16、
双发射板级容量，结果位于 `build/fpga/fd-100mhz-20261003`。模块内部保持报告
和零 I/O 延迟比较边界分别记录；不是整板 100 MHz 签核。没有全量 GSIM、
长 Linux 仿真或新 bit 生成，旧整数版 bit 和 GUI 项目保留。

候选模块布线已完成：加减 WNS +3.339 ns、状态 +5.712 ns、整桥 +2.526 ns；
内部 hold 均正。零 I/O delay 的边界 hold 仍 -0.080 ns，未隐藏，不作为整板
全时序验收。完整基线对照、资源代价、DCP 与哈希索引见时序文档最新章节。

## 2026-10-03 完整 RV64 F/D 候选短验收

`simulator/gsim/floating_point_full.py` 在全部指令组接入后集中编译与验证；
不是逐条指令跑仿真/综合。仅需已锁定的 GSIM、Clang 19+、NEMU 整数参考及
固定 SoftFloat ZIP；缺依赖时报错，不自动更换版本或下载其他后端。

```sh
cd /home/openion/Valence
GSIM_CXX=clang++-19 python3 simulator/gsim/floating_point_full.py --tag fresh-fd-tag
```

范围：58 种 S/D 运算编码、27,840 个独立 SoftFloat 数值/flags 向量、五种舍入，
F+D/F-only/裁剪三配置；39 种非法格式/字段/保留舍入组合；
结果停顿、完整 token、结果级冲刷和迭代单元冲刷/复位；
8,192 种压缩 FP 编码的独立展开穷举及关闭配置非法检查；
真实 CPU 全运算组、动态 frm、FPR/FCSR 精确提交和四种压缩访存；
必要 M4 直接/缓冲访存的 PMP、FS Off、对齐、错误响应、错路和整数存储排序；
FP 关/开两配置的整数 NEMU 对拍。均启用 ASan/UBSan 和严格负例。

当前批次目录 `build/gsim/floating-point-full-20261003-r4`，最终状态看 receipt；
状态已为 `PASS_FUNCTIONAL_CANDIDATE`，9 个正向模型、12 个严格负例通过。
真实 CPU 为 1,212 个用例/61,864 次提交，133 个源码哈希与 36 个模型/
可执行文件哈希均重新核对匹配。
其 source/artifact/reference hashes 必须与对应构建匹配。NEMU 的 FPU_NONE
只用来检查整数回归，不是 FP 数值参考。配置测试也验证纯整数无 FP 模块、
F-only 无 D 模块、裁剪后转换/乘加/除法开方/访存不被实例化。

所有输出保存在原 WSL 工程，无新 Windows 侧工作副本。实验默认关闭；
数值与真实 CPU 验收不代替 Linux 浮点上下文、独立 RTL 后端交叉验证、
100 MHz 新完整 F/D FPGA 时序/资源签核或上板结果。

## 2026-10-04 RV64GC 显式配置与无额外周期的 NaN 长链优化

最新功能凭据：`build/gsim/floating-point-full-20261004-nan-cut-r1/receipt.json`，
`PASS_FUNCTIONAL_CANDIDATE`。旧目录均保留。两个 F/D 配置 Scala 测试通过，
真实 CPU 实际读取 `misa=0x800000000014112d`，1,212 个用例/61,865 次提交/
77,748 周期；与输出适配优化前周期相同。F+D/F-only/裁剪配置各 27,840 向量，
独立参考增加到 21 个已知答案锚点，并定向覆盖双 NaN、正负零和 FMA 0×inf；
每个数值组新增 delay=0..6 的 stage/held-response flush。所有必要内存与整数
回归、12 个严格负例通过。没有修改 HardFloat 或 GSIM 来迎合参考。

生产 BoardSocMain 和 BoardSocGsimMain 的最后一个可选参数为
`rv64imac`（默认）/`rv64imafc`/`rv64gc`。完整配置才允许声明 F/D；实验裁剪
由参数继续支持，但宣告开关强制拒绝。所有原 8 参数调用保持默认整数。

真实板级缓存/AXI/原子操作与 S-mode 32 FPR/FCSR 保存恢复的短入口：

```sh
GSIM_CXX=clang++-19 python3 simulator/gsim/rv64gc_board.py --tag fresh-board-gc
```

固件源 `fpga/firmware/rv64gc_smoke.S`，按 RAM 入口 0x80200000 链接，
运行最多 150,000 模型周期；有错误 ISA 锚点故障注入。已测目录
`build/gsim/rv64gc-board-20261004-nan-cut-r1`：31,580 周期、43 个 DDR 读 burst、
32 FPR/FCSR 上下文、一次 S-mode ECALL、压缩退休、严格错误锚点负例通过。
这只能证明硬件上下文机制，不是 Linux 调度/信号浮点上下文验证。
模块时序导出与 Native Vivado 对照见 [时序台账](../../docs/fpga-timing-windows.md)。

后续短固件已加入真实 Sv39 非同址映射：FP 上下文 VA 0x40220000 对应
PA 0x80220000，页表根 0x80210000；32 FPR+FCSR 保存/别名恢复，并以整数恒等
视图交叉校验，FS/SD 与 S-ECALL 继续检查。已测
`build/gsim/rv64gc-board-20261004-sv39-context-r1`：31,960 周期、49 DDR 读 burst，
严格负例通过，192 源码和原模型哈希重新匹配。只修改固件/运行入口时可复用：

```sh
GSIM_CXX=clang++-19 python3 simulator/gsim/rv64gc_board.py --tag fresh-sv39 \
  --reuse-model build/gsim/rv64gc-board-20261004-nan-cut-r1/receipt.json
```

任何 DUT/harness/模型/二进制或输入集合变化都拒绝复用，需生成新模型。
没有运行长 Linux，也不能代替 Linux FP 调度/信号上下文验收。
旧完整验收 receipt 的 limits 最后一条“不宣告 F/D”已过时：完整显式 profile
现在一致宣告 misa/DT，默认与裁剪配置仍不宣告。封存 receipt 不追改，runner
仅修正资格文字；`fpga/audit-rv64gc-evidence.py` 验证精确 metadata-only 差异，
并锁定当前数值/真实 CPU/BoardSoC/模块时序证据。整核时序独立判定。

最终 `build/fpga/fpu-rv64gc-20261004/audit-final.json` 已同时锁定完整功能候选、
Sv39 上下文、匹配的整数/GC 设备树解析、13 FPU 及真实 MachineCore route。
状态 `FUNCTIONAL_AND_INTERNAL_10NS_MET_BOUNDARY_UNQUALIFIED`：Core 内部
WNS +0.090 ns、TNS 0、hold +0.023 ns；完整 FPU System WNS +1.603 ns。
Core 的零预算接口 hold 仍 -0.046 ns，模块 IO/reset 与整板、Linux FP
运行资格明确不通过本次内部判据自动获得。原 GUI/整数 bit 保留；无新 bit。

## 2026-10-04 自研网络 DMA 与 TileLink 部分写

```sh
cd /home/openion/Valence
GSIM_CXX=/usr/lib/llvm-19/bin/clang++ python3 simulator/gsim/ethernet_dma.py --tag fresh-tag
```

一次必要短验收：154 组收发/错误/背压/IRQ 用例；三种子真实 coherent home
链的 CPU 脏 TX 探测、RX 缓存失效和尾字保护；原 memcpy 48 例；TL 有序响应、
RAM 256 mask/2048 beat、AXI 单拍与多拍部分写、错误与独立故障注入。
还检查实际 `EthernetSocTop` 生产 RTL 导出和软件头文件交叉编译。
接入通过不表示 PHY、Linux 网卡驱动、千兆线速或完整整板时序通过；
仅新 CDC 模块用短双时钟 xsim，不跑整板/CPU 时序仿真。

## 整数与 native PHY 批量时序短验证

```sh
GSIM_CXX=clang++-19 python3 simulator/gsim/native_timing_batch.py --tag fresh \
  --baseline build/gsim/fetch-feedback-20261004-r5/receipt.json
GSIM_CXX=clang++-19 python3 simulator/gsim/rv64m_core_short.py \
  build/gsim/native-timing-fresh/receipt.json
```

仅受影响M单元、混合取指、Clause22和真实CPU短NEMU；第二条复用已验收CPU模型，
只选RV64M恢复/竞争用例，不重跑其他ISA和随机全套。两种M锁存配置均保留独立
延迟/吞吐和负向注入检查。`--reuse-units`仅允许完成单元测试后的runner-only修复，
核对原receipt全部输入，DUT/harness变化不允许复用。

已测 `build/gsim/native-timing-20261004-r3/receipt.json`：13项短IPC周期完全不变；
其 `rv64m-core/receipt.json`：30程序/30412提交、832边界对、1000随机M及实际
分支取消通过。乘法II=1，但MULW/全宽MUL依赖延迟增加一拍。未跑长Linux，
未证明CoreMark提升、F/D整板资格或PHY实机链路；详见`docs/native-gmac-board.md`。

## 批量存储取指总线与浮点长链短验证

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/rv64gc_path_batch.py --tag fresh-path-batch
```

一次统一受影响验收：独立区间oracle、FP状态及SoftFloat数值、混合压缩取指、
legacy/raw TL单拍与burst、错误bank、13项双发射IPC/NEMU、控制/访存/恢复，
再各生成一个真实F/D CPU与当前cache/AXI板级上下文模型。不运行全量GSIM、长Linux或CAD。
默认开关仍纯整数；显式rv64gc短检查不是ISA认证、Linux FP调度或F/D bit资格。

已测`build/gsim/rv64gc-path-batch-20261005-path-b3/receipt.json`全部通过；
整数13项周期与旧基线一致，浮点板级上下文32,014周期。
`--resume-units`仅处理明确runner/fetch修复，严格核对源码集合、变化列表和旧失败类型，
只复用不含变化模块且重新执行通过的隔离模型；fetch/core/board必须重新生成。
新整板时序见[板级台账](../../docs/native-gmac-board.md#批量长链重构与短验证)，不能由短功能PASS推断。

## 整 SoC 流水边界重构的必要短验收

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/soc_pipeline_refactor.py --tag fresh-soc-refactor
```

该入口只检查本轮游标邻接、自然对齐 PMP、浮点 AGU/请求/回复/完成边界、排队 VM
上下文和混合压缩取指，再复用一个整数模型做 13 项短 IPC、50 项控制/访存 NEMU、
11 项恢复，并生成本轮真实 RV64GC CPU/板级模型；不是全量 GSIM 或长 Linux。
独立参考与负对照必须通过，源码冻结，旧 CPU/取指模型不能跨硬件改动复用。
`build/gsim/soc-pipeline-refactor-soc-restructure-20261005-r1/receipt.json` 已通过。
真实 F/D CPU 1212 向量、61865 提交、77762 周期；板级上下文 32231 周期，包含 Sv39
非同址 FP 保存恢复。13 项短整数周期不变，FP/板级的额外访存周期仍需单独评价。
局部 10 ns OOC、额外周期和整板签核状态见
[模块合同与重构验收](../../docs/modular-soc.md#整-soc-重构和验收)。模块或功能通过不能
代替整板 F/D 100 MHz bit 资格；双发射交付完成后才评估三发射。

系统周期对照可用 `soc_refactor_coremark.py --tag <新标签> --baseline <旧板级receipt>
--current <当前板级receipt>`：同一二进制、单迭代，严格核对现有 FIR/C++/驱动散列，
不生成 GSIM 模型、不覆盖旧通过的二进制/日志、不跑 Linux。本轮 CRC/tick 对照通过，
794923 → 818225 ticks（+2.931%）。只是相同模型条件下的周期代价，不是有效 CoreMark
分数或已证明的频率×IPC提升；最终还须结合通过整板签核的实际可用频率判断。

## Cache window / FP 转换 / store / line writer 批量短验收

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/soc_window_batch.py --tag fresh-window-batch
```

仅检查 3/5 行寄存化取指 window、FP 状态、FD/F/裁剪三种数值配置、四在途 line
writer 与 RAM 回读，再一次生成真实 CPU/板级模型及短 NEMU 性能/控制/恢复。
不跑全量 GSIM、长 Linux 或 CAD。`--resume-units` 只接受记录中的纯整数夹具
配置失败：变化限夹具与 runner，旧 fixture 散列可还原，每个隔离模型须重新
elaboration 且 FIR 相同，重新跑独立正/负检查；CPU/板级不得复用旧生成模型。

`build/gsim/soc-window-batch-soc-window-20261006-r2/receipt.json` 已通过。FP CPU
77762 周期不变，板级 32244 周期；11 项整数周期不变，低延迟 memory/ALU 421 →
391，高延迟竞争 865 → 1015。缓存模型同二进制 CoreMark 单迭代 818225 → 844297
ticks（+3.186%），不是正式分数/真实 MIG 或 FPGA 吞吐；不据功能 PASS 宣称时序
或性能全面改善。三发射评估在合格双发射交付后独立进行。

## 2026-10-06 长帧 / CPU 缓存 / Home 活性短验证

```sh
GSIM_CXX=clang++-19 python3 -B simulator/gsim/network_packet_pressure.py --tag NEW_TAG \
  --control-receipt build/gsim/network-boot-checks-20261006-r3/receipt.json
```

只生成缩小的 cache/atomic/request-FIFO/home/TL-RAM 模型，不执行 CPU、Linux、
IRQ、MIG 或 PHY，不启动 Vivado。每个夹具跑 48 组 64..2048 B DMA 访存与 CPU
4 KiB 缓存压力、原子、uncached、四在途 credit 和回复背压，再跑 8 组旧 probe
回归及独立数据错误注入。夹具为 1-way/4-line、2-way/4-line、2-way/32-line；
后一项仅采用生产缓存容量及 Home metadata 优化，不等于整板平台。
公共 Home 下游请求必须在背压期间保持 valid/payload；独立 byte/word oracle
与有界完成检查不依赖 DUT 私有状态，私有快照只用于失败诊断。

`network-packet-pressure-fixed-20261006-r5/receipt.json` 的 144+24 正例和三组
负向数据注入已通过。`network-packet-pressure-control-20261006-r5/receipt.json`
用相同最终驱动和封存旧模块 FIR 在两种 ways 中重新确认预期死锁，证明普通读
撤回与 TL 仲裁锁之间的活性缺陷；不是物理板卡内部轨迹。
`--controls-only` 仅允许配合 `--control-receipt`，状态为
`expected_controls_confirmed`，不能当作当前 RTL PASS。
硬件修复位于 `CoherentLineHome`，尚无本轮 routed 时序、IPC 或上板验收；
详见 [Linux 长帧故障台账](../../docs/linux-bringup.md)。
