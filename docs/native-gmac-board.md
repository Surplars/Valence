# Native GMAC 整板实现与签核状态

当前使用 WSL 主工程，`ManagedBoardSocMain` 默认仍为双发射、RV64IMAC、CPU100 MHz、
UART460800。2026-10-05本轮整板候选显式选择RV64GC，开启完整基础F+D；全局默认与旧bit不变。
最新已完成的三分频局部候选仍是F/D关闭：CPU100、
RX采样及分频器复位释放通过；TX输出最差setup/hold改善至-0.036/-0.003 ns，
仍有2个setup端点、1个hold端点未通过。未生成新bit。
最新板级源码候选使用共用REF500、独立pad时钟和FPGA的TX相位，PHY由软件初始化，仍须最终物理签核，
不能宣称新native GMAC整板稳定100 MHz。旧GUI工程与可用bit均保留；
已完成基线见“共用参考时钟与独立TX输出时钟”，新整板进展见“开启浮点的整板重新实现”。

## 管脚来源

只读提取用户的 `XCZU15EG-F V1.0管脚定义.xls`，`MIPI & PL ETH!A17:C31`，
15 根 PHY 信号逐项与原理图及厂家 `12_UDP_TEST/pin.xdc` 交叉核对。
新的约束为 `fpga/zu15eg/native_gmac_pins.xdc`，与原 `board_ddr.xdc` 和已验证的
`pl_ddr4_pins.xdc` 一起使用，绝不覆盖 DDR MIG 的实际时钟/管脚约束。

修正旧 `self-gmac-board.json` 的管理信号转录错误：

| 信号 | FPGA ball | 核心网络 | 载板 J5 |
| --- | --- | --- | --- |
| PHY2_MDC | Y1 | B66_L22_N | 85 |
| PHY2_MDIO | Y12 | B66_L5_P | 87 |
| PHY2_RST | Y2 | B66_L22_P | 83 |

旧记录的 MDC=Y9、RST=Y11 无效；Y9 是 FMC_LA23_N，Y11 是 VCCO_66。
不能把电源脚当作复位输出。Bank66 / PHY RGMII 为 LVCMOS18。
PHY2_RST 经过 Q10 NMOS 反相：FPGA 输出高为断言 PHYRSTB 低，输出低为释放。

## 时钟与边界

- MIG 输入200 MHz、UI250 MHz，原生 Vivado AXI clock converter 承接 CPU100↔UI250。
- `clk_wiz_ddr` 提供CPU100、常开/原始UART50；默认候选的ETH PLL提供共用REF500，
  三只BUFGCE_DIV分别提供内部TX125、仅驱动五根data/control的pad TX125及后移2 ns的TXC125。
  原CPU Wizard的第三输出在本top不使用。
- RX为PHY提供的独立RGMII RXC，经IBUF、独立RX MMCM的22.5°相位及BUFG后进入采样域。
- UART、TX、RX 的 managed 时钟由真实 SYNC BUFGCE 控制；raw 时钟不能停。
- TX 增一组 raw 域字节/控制寄存器，再由 ODDRE1 输出上下沿半字节及 EN/EN xor ER。
- 默认候选RX四数据及CTL均经0 ps固定、PVT校准的IDELAYE3，再进入IDDRE1
  SAME_EDGE_PIPELINED和字节/DV/ER寄存器；ER为上下沿CTL异或。
- 校准参考时钟常开，复位在稳定500 MHz下保持128 ns，RX等待RDY及三级同步释放。
  Bank66实际区域X3Y2，RX MMCM位于MMCM_X0Y2；REF500使用同列PLL_X0Y4，
  两路pad输出根对准Bank66。各DIV的CLR在自身REF500上升沿后注册释放，
  转发DIV比raw/pad晚一个REF500周期，建立实体2 ns相位；所有CLR recovery/removal仍检查。
  TX数据和转发时钟各自另有三级异步断言、同步释放的复位链。
- 只宣称 1G/full-duplex，idle in-band status 不满足该模式则不认作有效链路。
- MDIO IOBUF 双向，输入两级 ASYNC_REG；只有第一级 pad 捕获用窄范围异步预算。
- PHY 复位在50 MHz常开域同步释放，计数器保持10 ms，不依赖 managed RX 时钟存在。

板级 top 为独立 `fpga/zu15eg/soc_top_gmac_ddr.sv`。旧 top / GUI 工程 / 原 bit 保留。
100 MHz DDR CPU 时间基准、OpenSBI/Linux 镜像原契约不变；新 native MAC 没有 Linux 驱动，
不能沿用 TEMAC 驱动或设备树 compatible。

## CMU 与 BootROM 默认策略

当前已实例化的外设冷复位后默认开钟：CMU STOP=0，policy 从 running 开始，
CE 命令经过原始时钟同步器自动打开 BUFGCE。BootROM 不需要先访问 CMU 才能打印；
未访问 CMU 的旧固件可继续初始化 UART。下载过程中 BootROM 不主动请求 UART 停钟。

UART / GMAC TX / GMAC RX 可以通过 CMU 排空、停钟、唤醒；CPU/AON/TIME/DDR_UI
目前是保护资源。默认开钟不表示 DMA/MAC 已启动，也不表示配置关闭的外设仍存在。
PHY RXC 是外部时钟，CMU 的 enable 不能保证板上 PHY 已输出该时钟。
DMA 等其他 CPU 域逻辑仍跟随 CPU 常开，并非所有外设已经有独立可门控的时钟域。

## RGMII 时序合同及未验证项

依据原理图，RTL8211F TXDLY、RXDLY均上拉。因此不能依赖strap直接使用新的FPGA相移。
默认源码候选`FPGA_TX_CLOCK_SHIFT=1`：FPGA的TXC物理后移90°（2 ns），软件必须先关闭
PHY TXDLY（page0xd08 reg0x11 bit8=0），开启RXDLY（reg0x15 bit3=1），读回确认并恢复MDIO page。
Linux对应`phy-mode="rgmii-rxid"`；MAC驱动仍需提供MDIO总线并接入PHY框架，不能仅加设备树。
Chisel MAC的control冷复位值为8，TX/RX使能位均为0；软件完成PHY初始化后才开启收发/DMA。
PHY软复位后须重新配置，不能让PHY与FPGA重复加入TX相位。
`FPGA_TX_CLOCK_SHIFT=0`保留原不相移TXC、PHY提供TXDLY的旧模式，供历史对比。
参考 [Linux 原生 Realtek PHY 驱动](https://raw.githubusercontent.com/torvalds/linux/master/drivers/net/phy/realtek/realtek_main.c)
及 [Realtek RTL8211F rev1.4 Table60](https://www.szcxwdz.com/uploads/pdf/REALTEK/1fb88e5d8a54729cd0cf43401f1f0bca.pdf)。

RX采用最小1.2 ns setup/hold，并各扣0.25 ns相对板级走线偏差，合同未改。
新TX模式用实际转发DDR CLK生成pad捕获时钟，无额外虚拟2 ns偏移；PHY setup/hold要求1 ns，
加原有0.25 ns走线预算形成±1.25 ns约束。PLL/MMCM抖动、相位误差和插入延迟仍由STA计算。
旧PHY延时模式保留名义2 ns和±0.5 ns内部延时容差，输出预算仍为±1.75 ns。
约束覆盖双边沿，不能用零 I/O delay 或全局异步 clock groups 取代。
这些走线预算是明确设计假设，不是 PCB 实测；PHY 实际 strap/25 MHz参考及链路仍需上板确认。

## 本轮证据

- `build/fpga/native-board-20261004-r1/pin-table.json`：原始工作簿 hash 与单元格值。
- `build/fpga/native-board-20261004-r2/inputs.json`：15根管脚、192个未变主RTL哈希，
  复用已通过的必要短GSIM；没有因板级接线重跑全量CPU/长Linux。
- 三项 `ip.ManagedPeripheralsSpec` 结构检查通过。
- RGMII DDR-I/O 双时钟短xsim：16 TX/16 RX字节、错误控制、idle速率筛选、复位通过，
  TX/RX各一独立损坏负例均被拒绝。不仿真 CPU 或真实 MAC 引擎。
- `bootrom-inputs.json`：最新无菜单 Bootrom V0.1，3061 bytes，所有32768个MIF字完全匹配。
- 第一轮完整综合8m30s通过，综合网表保存；XDC中不支持foreach被严格审计阻止，未布局/生成bit。
- 第二轮只重组已保存的SoC网表及修正PHY外壳；保存完整网表后，严格复位审计因
  CIRCT 实际寄存器名为 `release_0_reg` 而非 `stages_reg` 停止。修正了名称匹配，
  仍要求三阶段、ASYNC_REG、共用异步复位、第一阶段 D=0、后续阶段直接连接前一级 Q。
- 第三轮从上述完整网表继续，管脚和 CDC 端点审计通过；Vivado 自动 MIG PHY 子综合
  在 RTL 展开前报 `can't read rt::result`，未进入布局，也未生成 bit。
- 第四轮仍复用同一完整网表，仅在 `opt_design` 的内部 IP 生成期间设置
  `general.maxThreads=1`，随后恢复为8。MIG PHY 子综合已完成，零错误和零 Critical
  Warning；整板优化通过且无功能黑盒，8线程布局和路由已完成。CPU RTL、IP 参数和时序要求未变。
- 第四轮 pre-opt 整板资源为187473 LUT、92144 FF、64 RAMB36、3 RAMB18、22 DSP；
  这不是最终路由资源。MIG stitching 导入出现两条空目标 `set_false_path` Critical
  Warning，须结合最终约束覆盖核查，不能将缺失对象当作有效例外。
- `build/fpga/native-board-20261004-r3/inputs.json` 和 `...-r4/inputs.json` 均保存实际
  候选文件 hash、15行管脚证据与192个未变的短 GSIM 主源码 hash。历史失败记录保留。

## 上一版 Routed 检查结果

实际 routed 全设计 setup WNS=-7.530 ns、hold WHS=-5.241 ns、pulse-width裕量
+0.081 ns。229706个可路由网络全部完成，routing errors=0；普通 DRC 没有 Error
或 Critical Warning，但这不等于时序或 bitstream 签核通过。最终资源186728 LUT、
92777 FF、64 RAMB36、3 RAMB18、22 DSP。

| 路径类别 | 实测结果 | 结论 |
| --- | --- | --- |
| CPU内部寄存器到寄存器 | WNS=-3.169 ns，data delay=13.073 ns | ROB `head_reg[3]_rep` 到乘法器 DSP M级；11.368 ns为布线，占约87%。不能用MDIO最差值替代CPU内部结果，也不能宣称100 MHz通过。 |
| MDIO管理输出 | WNS=-7.530 ns | 当前输出约束误建模为100 MHz同步捕获；实际Clause22的MDC为2.5 MHz、数据在下降沿更新。下一批须按真实协议建模并保留物理延迟预算，不能直接删除检查。 |
| RGMII RX | hold=-5.241 ns | 须联合核对PHY延迟、DDR上下沿数据窗口及FPGA采样时钟插入延迟；尚未增加经校准的输入延迟，不宣称接口已过。 |
| RGMII TX | setup=-0.425 ns、hold=-0.415 ns | 同时缺setup/hold裕量，须复核转发时钟合同及MMCM/BUFG与Bank66的物理位置。 |

CDC 明细仍有11个 CDC-11 Critical，保留原报告，尚未逐项验收或豁免；bus-skew和
接口预算也不能由功能短测试代替。完整实现约38分钟（含打开检查点、MIG展开、布局、
路由和报告），没有再次综合CPU。

`diagnose_native_boundary.tcl` 分别读取 CPU 内部与管理输出路径，仅在内存中重新应用
既有的窄范围 CDC/复位合同，不保存 ECO 或 bit。实际诊断确认 MIG PHY stitching 后
须重审计这些合同：三个构建入口已增加 `opt_design` 后的同一结构审计和
`optimized.dcp` 保存。只例外已核对的复位同步器 PRE/CLR，不切断功能CPU数据路径。

原始实现、两次布局诊断及最终 routed 诊断的日志/报告归档于
`build/fpga/native-board-20261004-r4/windows-run/`；大型检查点留在独立Windows候选
`E:/VM/Share/Valence-rtl/native-board-20261004-r4/implementation/`，旧结果不覆盖。

只有实际 routed setup/hold/pulse-width、接口预算、CDC/Gray/held payload约束覆盖、
全部板级管脚、ROM INIT及DRC检查通过后才允许写 bit。历史外设OOC正裕量不替代本轮整板资格。

## 当前批量优化与短验收

本批以同一份routed报告处理三类相关链路：RV64M操作数到算术、取指游标反馈、
native PHY物理边界。完整候选位于 `E:/VM/Share/Valence-rtl/native-timing-20261004-r1/`，
完整综合、整板布线及局部原语接线修复均已完成。CPU域内部100 MHz通过，
整板PHY/CDC边界仍未签核，未生成bit；最终数据见本节末尾。

| 改动 | 结构与代价 | 已测短验收 |
| --- | --- | --- |
| M操作数锁存 | `registeredMulDivOperands`通用默认关闭，FPGA throughput及后续profile开启；接单仍立即预约原槽。MULW 2→3拍，全宽MUL 6→7拍；DIV64 66→67拍、DIVW 34→35拍。乘法启动间隔保持1，8预约槽不变。 | 新旧单元分别3000乘法、3900除法/单槽结果；取消、背压、标签及故障注入通过。真实CPU另有30程序/30412提交，832边界对、1000随机M及分支多槽撤销通过NEMU。 |
| 取指并行进位 | lane偏移先与符号立即数合并，再作一次21位游标加法；43位高进位/借位直接从原游标并行产生，不改变预测、取指延迟、容量或发射宽度。 | 2宽压缩、2宽非压缩、4宽压缩的独立PC oracle及负例通过，包含2MiB边界、RV64回绕、错误路径和hint别名。4宽仅为模块参数检查，不是4发射CPU资格。 |
| PHY和管理输出 | MDIO改用移位寄存器而非64选1数据mux；每条管理输出腿保留20 ns物理预算。RX虚拟DDR源时钟相位2 ns、delay范围±1.05 ns，保留原±0.95 ns采样眼。加入校准延时和本地Ethernet时钟资源，TX外部预算未放宽。 | 96 Clause22事务含64读/32写/9无ACK/8复位；实际UNISIM校准后16 TX/16 RX、ER和idle状态通过，两项损坏字节负例均拒绝。整板setup/hold仍需routed检查。 |

短验收凭据为 `build/gsim/native-timing-20261004-r3/receipt.json` 和其
`rv64m-core/receipt.json`。13项同二进制短IPC负载的周期数与原冻结模型完全一致，
独立ALU为1024提交/515周期，IPC=1.98834951；该组不是乘法密集应用或CoreMark，
不能抵消M依赖延迟增加的一拍。是否获得整体性能收益仍取决于实际频率及应用M占比。

另复用相同新旧CPU模型运行固定128条M微基准，均130次退休、逐条NEMU一致。
仅重跑现有`--ipc`短程序，未重新生成模型；两份accepted日志与主receipt同目录。

| M微基准 | 原周期 | 新周期 | 抵消周期代价所需频率增幅 |
| --- | ---: | ---: | ---: |
| 独立MUL | 138 | 139 | 0.72% |
| 连续依赖MUL | 900 | 1028 | 14.22% |
| DIV64 | 8580 | 8708 | 1.49% |
| DIV32 | 4484 | 4612 | 2.85% |

频率增幅为`新周期/原周期-1`，是该微基准的盈亏平衡计算，不是实测Fmax。
不能将此表推广为CoreMark/Linux整体下降比例，也不能宣称新100 MHz已抵消代价。

`build/fpga/native-timing-20261004-r1/inputs.json`核对15管脚、186个未变主源码与
6个重新验证主源码的hash，禁止用旧192个未变源码凭据冒充新候选。校准参考选择依据
[DS925的300至800 MHz要求](https://docs.amd.com/r/en-US/ds925-zynq-ultrascale-plus/Input/Output-Delay-Switching-Characteristics)，
时钟资源就近放置依据[AMD RGMII物理时序指导](https://docs.amd.com/r/en-US/pg051-tri-mode-eth-mac/Timing-Violations-on-I/O-Paths-in-GMII/RGMII-UltraScale-Architecture-Devices)。
实际2025.1 UNISIM拒绝1200 ps，合法1100 ps配置通过；失败日志另存，不当作通过。
本批整数板配置仍关闭F/D，不把既有FPU或整核历史正裕量当作本次整板资格。

## 2026年10月5日 完整实现与早期局部修复结果

一次完整CPU/板级综合约9m44s。第一入口在综合后因审计未使用的旧
`io_peripheralClock`引脚而停止；改查UART/AON/TX/校准实际消费者，复用
`post_synth_unconstrained.dcp`继续，未重复综合CPU。MIG内部生成仍只在opt阶段
串行，随后恢复8线程；完整实现39m41s正常退出，证据位于`implementation-resume-r2/`。

布局报告另发现5个IDELAYE3控制CLK误接500 MHz，违反3.195 ns最小周期。
[UG571的FIXED模式CLK不使用](https://docs.amd.com/api/khub/documents/kFbaUC5HGcXyGNauhgU6Gw/content)，
源码将该端口明确接GND，IDELAYCTRL参考仍为500 MHz。原语短xsim正例和两项
独立错字节负例重新通过；`fixed-clock-inputs-r2.json`核对471个短验证输入及
211个冻结候选文件未变，仅允许这一处五引脚接线差异。修复脚本同时检查
FIXED/TIME、原500 MHz连接与GND驱动，复用routed网表，不重新综合CPU或放宽约束。
该补救含重新布线和报告14m07s正常退出；最终候选为`implementation-fixed-clock/`。

| 类别 | 上一版 Routed | 本批最终 Routed | 判定 |
| --- | ---: | ---: | --- |
| CPU100内部setup WNS | -3.169 ns | +0.335 ns，TNS=0 | 100 MHz内部通过，余量仍需加厚。 |
| 乘法器输入setup WNS | -3.169 ns | +0.375 ns | data delay 13.073→9.361 ns；DSP A/B输入寄存级已推断。 |
| 除法器输入setup WNS | -2.343 ns | +0.564 ns | data delay 12.106→9.469 ns；选择与初始化分拍。 |
| 取指反馈setup WNS | -2.066 ns | +0.366 ns | data delay 11.919→9.404 ns；不增加取指延迟。 |
| RGMII TX setup/hold | -0.425/-0.415 ns | -0.427/-0.416 ns | 仍不通过，靠本地MMCM/BUFG放置不足以解决此预算。 |
| RGMII RX hold | -5.241 ns | -0.585 ns | 仍不通过。旧DDR建模纠正与实际输入延时均参与，不能全算作物理延时收益。 |

CPU组hold +0.011 ns、pulse +4.458 ns；当前最紧setup为
`backend/head_reg[0]_rep__4`→`storeSafeRange_12_reg/D`，21级、data delay 9.430 ns，
其中7.470 ns（79.2%）为布线。取指次紧仍由纠正PC驱动缓存/槽位反馈。
第一份完整结果的CPU WNS为+0.048 ns；最后局部修复后的重新布线到+0.335 ns，
不能把后者说成仅接地五个引脚就产生了同等逻辑性能收益。

全设计最终WNS=-0.427 ns、TNS=-1.861 ns、5个setup端点失败；
WHS=-0.585 ns、THS=-4.698 ns、10个hold端点失败，均为RGMII数据/CTL。
整板pulse +0.081 ns、零pulse违例，原语控制时钟问题已消除。
229285个可路由网络全部完成，routing errors=0。资源185529 LUT、93216 FF、
64 RAMB36、3 RAMB18、0 URAM、22 DSP；较旧native板减少1199 LUT、增加439 FF。

仍有下列独立签核缺口，不因CPU内部通过而豁免：

- bus-skew复核更正（2026-10-05）：此前误将`Actual(ns)`列的负数当作
  `Slack(ns)`。逐项明细全部`MET`；厂商AXI CDC最小裕量+3.785 ns，native
  GMAC最小裕量+7.072 ns。原4/8 ns预算与路由均保留，不需对此做修复。
- CDC-1 Critical 1、CDC-10 Critical 2、CDC-11 Critical 24；大部分为共用异步复位
  扇出，另有配置邮箱位及CMU quiesce双消费者，尚未逐项做物理/协议验收。
- DRC无Error，但PDRC-203有17个重复Critical Warning，均指向`eth_txd[1]`在
  同字节校准期间不可用。应先证明PHY/TX在校准期间保持复位/不使用，再按真实
  启动合同处理，未设置`UNAVAILABLE_DURING_CALIBRATION`来掩盖问题。
- check_timing的no_clock、内部未约束端点、组合环均为0。外部DDR reset输出预算
  仍缺；MDIO/UART异步输入和转发TXC须与各自窄范围合同一起审阅。

必要日志、两份完整报告、修复脚本及边界短例归档在
`build/fpga/native-timing-20261004-r1/windows-run/`，最终哈希与指标见`completion.json`。
大型DCP留在Windows独立候选目录。旧GUI、旧bit和所有历史失败证据保留，CAD已退出。

下一批优先处理RGMII RX采样时钟插入延迟、TX双边沿捕获窗口及CDC协议结构
审计（物理bus-skew已通过）；CPU则加厚store-safe秩/范围链和纠正取指反馈余量。不能继续盲加RX数据
延时：当前RX setup只约+0.531 ns，单纯再延时0.585 ns会挤掉另一侧预算。

## 2026年10月5日 板级边界复核与候选筛选

本轮只处理板级时钟和RGMII边界，未重新综合CPU，未生成bit。
CPU仍为双发射100 MHz整数配置，F/D关闭；471项CPU短验收输入重新核对hash全部未变。
CPU内部setup/hold/pulse为+0.335/+0.011/+4.458 ns，不能据此宣称整板或FPU配置通过。

| 有完整STA覆盖的版本 | RX setup/hold | TX setup/hold | 选择 |
| --- | ---: | ---: | --- |
| 校准复位保护及raw时钟根局部修复 | +0.492/-0.516 ns | -0.427/-0.416 ns | 保留有效基线，整板仍未达标。 |
| raw与managed改为并行BUFG | +0.492/-0.516 ns | -0.427/-0.416 ns | 未改善pad路径，hold失败端点12→17，不作为交付版本。 |
| 新RX PLL与200 ps输入延迟 | +1.619/-1.833 ns | -0.427/-0.416 ns | RX hold恶化，拒绝合入。 |

有效基线的DCP为`E:/VM/Share/Valence-rtl/native-signoff-20261005-r1/routed.dcp`。
并行候选修正后的证据在`build/fpga/native-actual-clock-20261005-r1/`；
RX PLL候选证据在`build/fpga/native-rx-deskew-20261005-r1/`。
大型DCP留在独立Windows候选目录，小型报告、确切执行脚本、模块短测试及hash均归档回WSL。
两个实验均保留所有原CPU/数据单元的LOC/BEL；PLL实验只允许新反馈BUFG选择合法位置。
局部route约2m40s，不包含读DCP、修改网表、保存和完整报告时间。

复核发现UltraScale+当前ODDR转换后的有效输入是`u_rgmii/tx_clock_ddr/CLK`，
而非未使用的`CLKDIV`。误用后者产生`Timing 38-285`和`generated_clocks (1)`，
TX报告为无限裕量；该结果无效，不能称为setup通过。
三个诊断/ECO入口已改成实际CLK，要求唯一8 ns主时钟。
修正后的报告检查全部五条TX data/control端点的有限setup/hold路径，
`generated_clocks`和内部未约束端点均为0，原2 ns PHY相位与±1.75 ns预算未放宽。
器件差异见[UG571的ODDRE1模式说明](https://www.amd.com/content/dam/xilinx/support/documents/user_guides/ug571-ultrascale-selectio.pdf)。

模块短测试与物理时序分开验收。并行时钟的实际UNISIM测试覆盖三种频率、12次停止/
唤醒/冷复位，反相输入负例被拒绝。RX PLL短例通过16 TX/16 RX字节、ER、idle状态，
错字节与绕过失锁保护的负例被拒绝，但其真实布线仍失败。
现用`native_rgmii.sv`保持1100 ps和FIXED控制CLK接地，板级top未实例化实验PLL。
RX失锁保护仅作用于pad三拍复位链，未改变ManagedGmac各FIFO/邮箱共用的冷复位。
热插拔、时钟丢失时的半帧恢复以及完整CDC协议审计仍未验收。

校准复位保护已由实际top片段证明：PHY/TX等待聚合IDELAYCTRL RDY，PHY再等10 ms；
删除PHY或TX保护的负例均被拒绝。新XDC仅对`eth_txd[1]`声明校准期间不可用，
不是全局降低DRC等级。旧DCP不会自动读取更新后的XDC，下一有效候选需显式应用此属性；
早期DCP仍有单项PDRC-203；后续MMCM候选已显式应用该校准属性，最终DRC无Error。
原4/8 ns bus-skew约束全部通过。

下一结构候选应先解决采样时钟的真实插入延迟与反馈匹配，不继续盲加RX数据延迟。
前一PLL实验的setup/hold最差交集为负，不能单纯平移相位。下节记录反馈缓冲
被移除的原因及新的候选；前一失败结果仍保留，不能用属性诊断报告替代物理验收。
反馈去偏斜的结构依据见[AMD XAPP1324输入时钟拓扑](https://docs.amd.com/v/u/en-US/xapp1324-design-selectio-component-primitives)。
TX仍须复核匹配输出结构及PHY实际延迟模式；当前0.25 ns PCB
预算与0.5 ns PHY内部延迟容差均是工程假设，不能当作厂家对本板实测的保证。

## 2026年10月5日 反馈缓冲保护与眼图端点验证

独立两原语综合定位了前一PLL候选的结构问题：RTL使用`AUTO`，综合先选择
`BUF_IN`，但`opt_design`移除反馈BUFG后选择`INTERNAL`。本机Vivado的
`Opt 31-1282`明确要求对反馈BUFG设置`DONT_TOUCH`才能保留这种补偿；
补偿还要求PLL与输出时钟根位于同一clock region，不能仅修改STA属性。
保留反馈后的正常综合和优化已验证`BUF_IN`，不是把一次属性切换当作硬件通过。

曾尝试RX PLL的`CLKOUT0_PHASE=-11.25`和200 ps数据延迟，但进一步按
[UG572的PLL专用属性规则](https://docs.amd.com/r/en-US/ug572-ultrascale-clocking/PLL-Attributes)
复核：PLL相位步长为`360/CLKOUT_DIVIDE`，不能套用MMCM的VCO/8规则。
因此该候选即使模块短例通过也不能签核，历史ECO入口已禁止再次运行。
组合布线也出现329个hold失败端点，不能当作局部改善合入。
正常AUTO降级为`BUF_IN`的证据只证明反馈模式，不证明任意细相位可实现。
ETH独立综合代理曾保留输入BUFG，以反映实际已经全局缓冲的MIG UI输入；
不等价的直接pad输入会选择`ZHOLD`，这部分诊断仍保留。
实际Bank66中的ETH MMCM为`MMCM_X0Y2`，已经位于本地，并非远端MMCM。

短xsim使用真实UNISIM原语，PHY激励仍跟随独立pad时钟，不跟随DUT采样时钟。
测试覆盖输入转换位置0.95/2.00/3.05 ns，每例16 TX/16 RX字节、ER编码和idle
速率状态；125/500 MHz周期分别由独立计时断言检查。RX错字节、TX错字节及
绕过失锁保护三项负例均被拒绝。先前750 MHz VCO、提前333 ps的候选在晚端
发生错位，已按失败保留，未放宽眼图输入或字节期待。
这一失败结构的短例记录位于`E:/VM/Share/Valence-rtl/native-feedback-short-20261005-r4/receipt.json`；
不能将其PASS扩展为时钟参数合法或硬件通过。
这不是SDF仿真，也未覆盖整MAC的半帧恢复或热插拔。

第一组合法候选将已有本地MMCM用于RX全局树反馈去偏斜，125 MHz输入和输出、
1 GHz VCO、零相位，数据IDELAY=0；已有PLL则使用UI250输入生成TX125和
校准500 MHz，零相位、INTERNAL频率合成。不增加CMT，取消无必要的TX反馈BUFG。
PHY释放和CPU冷复位仍依赖UI侧PLL锁定，不依赖可能停钟的RX MMCM，防止启动死锁。
RX pad失锁保护仍仅作用于原三拍复位链，未单边复位异步FIFO。

该候选已通过同样的三个PHY眼图位置和三个负例，正常OOC综合/优化分别证明
RX MMCM的`ZHOLD`及ETH PLL的`INTERNAL`模式。
证据位于`E:/VM/Share/Valence-rtl/native-mmcm-pll-short-20261005-r1/`及对应两个OOC目录。
同时复用hash匹配的CMU并行缓冲短验证，将raw/managed输入改成共享CMT输出，
去掉串接的额外BUFG插入延迟，并把反馈与raw/managed时钟根统一到Bank66。
局部ECO只允许移动两只外设managed BUFG，所有CPU/数据单元LOC/BEL必须保持。
独立正常综合源码逐字匹配短测试源码，PHY setup/hold预算不变。
该零相位候选的完整局部routed结果为RX setup=-0.065 ns、hold=+1.053 ns，
TX输出仍为setup=-0.427 ns、hold=-0.416 ns；并行TX门控树又引入4项内部hold违例。
不能因为短例通过而合入。证据已归档WSL `build/fpga/native-mmcm-pll-20261005-r1/`。
现用板级top尚未接入新时钟模块，整板未通过。
本次仍按用户要求不生成bit。

## 2026年10月5日 RX采样闭合与TX残留

最后一轮复用已有routed DCP，只调整两组外设时钟边界，不重新综合CPU：

- RX使用上述反馈MMCM，采用合法22.5°相位（125 MHz下后移0.5 ns），IDELAY=0。
  旧DCP的managed RX仍直接来自PHY pad、绕过新采样时钟，已将其与raw RX统一到MMCM输出。
- TX恢复raw BUFG→CMU SYNC BUFGCE串联门控，保持原CE/冷复位策略。
  串联树不再要求与上游raw树匹配同一CLOCK_DELAY_GROUP，消除了并行候选的内部hold违例。
  原短验证已经同时覆盖串联/并行逻辑等价、3档频率和12轮停钟/唤醒/复位。

RX新相位通过真实UNISIM的3个独立PHY转换位置及3个负例；正常小模块综合/优化保留
反馈BUFG、ZHOLD模式和22.5°相位。测试生成源码与OOC源码逐字匹配。
这不涉及先前被拒绝的PLL细相位，也不是SDF或整板功能测试。

最终布线保持全部351550个已有单元LOC/BEL，229291个可布线net全部完成、routing errors=0。
CPU原短GSIM/NEMU验收的471个输入重新hash检查未变，没有重跑全量CPU或Linux仿真。

| 检查范围 | Setup最差余量 | Hold最差余量 | 本轮结论 |
| --- | ---: | ---: | --- |
| CPU100，双发射RV64IMAC，F/D关闭 | +0.335 ns | +0.011 ns | 保持通过 |
| RX五条data/control采样 | +0.435 ns | +0.553 ns | 时序通过 |
| TX域内部 | +3.398 ns | +0.023 ns | 时序通过 |
| TX五根data/control输出 | -0.427 ns | -0.416 ns | 未通过 |

整板WNS=-0.427 ns、TNS=-1.861 ns，5个setup失败端点；WHS=-0.416 ns、
THS=-1.924 ns，5个hold失败端点。所有失败端点均为`eth_txd[0..3]`及`eth_tx_ctl`。
整板脉宽最差余量+0.081 ns；无未定义clock、未约束内部端点、失联generated clock或组合环。
总线skew原预算未改且全部通过；DRC只有Warning，没有Error或Critical Warning。
RX相比先前有效候选的hold=-0.516 ns，提升到+0.553 ns；不能将局部闭合表述成整板达标。

TX只读模型复核也已保留：将PHY相位移到output delay的表达选中了不同DDR hold边，
不等价、不可用于签核；显式OQ转发模型仍失败，setup最差-0.445 ns。
当前仍保留实际OSERDESE3 CLK作为转发源、2 ns PHY名义延迟与±1.75 ns输出预算，
没有增加false path、理想clock latency或缩小PHY/PCB假设来制造通过。
本次`route_design -preserve`未能通过路由绕行补足固定/专用IO路径的hold；
该结果不证明所有新布局/IO结构都无解。下一步需独立验证TX输出结构和PHY延迟，
不再在整板DCP里连续扫时钟参数。PHY配置读回及实板时序/链路验证尚缺，不能从STA推断已通网。

验收包：WSL `build/fpga/native-mmcm-trim-20261005-r1/completion.json`，状态
`CPU100_MET_IO_CANDIDATE_NOT_QUALIFIED`。其中含报告、短例、OOC、诊断及实际执行的ECO脚本。
大DCP保留在Windows `E:/VM/Share/Valence-rtl/native-mmcm-trim-20261005-r2/routed.dcp`供Vivado续用。
`source_integrated=false`：这些是未交付的物理候选，现用`soc_top_gmac_ddr.sv`和ROM/固件未改变。
依用户要求本轮收尾后停止加跑，不生成bit；保留旧GUI和可用bit，不宣称FPU100或整板已验收。

## 2026年10月5日 TX边界逻辑与路由复核

继续优化后的最终结论仍是整板未达标。CPU100、RX五条采样路径和TX域内部保持通过，
五根TX data/control输出仍为setup最差-0.427 ns、hold最差-0.416 ns。
没有用路由中间值替代最终报告，也没有生成bit或切换PHY延时模式。

本轮批量处理两项TX边界逻辑：

- `native_rgmii.sv`将下降沿控制符号`TX_EN ^ TX_ER`移到既有pad阶段的寄存器前，
  与数据和上升沿控制共享原延迟，不增加一拍。四种DV/ER组合均保留。
  当前板级MAC的TX_ER恒为0；正常综合确认下降沿控制寄存器与TX_EN寄存器合并，
  原板级网表也没有该XOR。因此这项通用逻辑改进不能算作本板残留输出路径的时序改善。
- 增加默认关闭的`ISOLATE_TX_PAD_CLOCK`参数。局部物理候选增加一只常开BUFG，
  与原raw树共享PLL125源，只驱动六只pad DDR，stage FF和CMU保持原时钟与CE策略。
  同时放开六根OQ到输出缓冲的网络重新布线；原CPU、DDR和数据单元全部保持位置。
  默认板级top仅补接新增时钟输入，仍使用原单时钟树，未接入此失败物理候选。

独立短xsim使用真实UNISIM。新增TX oracle穷举256种字节及四种DV/ER编码，
共3072个字节、三次异步复位/重启，持续8 ns一字节；数据和控制错误注入均被拒绝。
RX边界短例重新覆盖独立PHY的0.95/2.00/3.05 ns转换位置及原三个负例。
正常小模块综合/优化另行确认六只ODDR模式OSERDES共用隔离树、控制直接来自FDCE，
以及ETH PLL的INTERNAL模式。这些不是SDF仿真、完整MAC协议测试或实板链路验证。

最终局部路由保持全部351550个原有LOC/BEL，229292根可布线网络全部完成，
routing errors=0。CPU setup/hold仍为+0.335/+0.011 ns，RX为+0.435/+0.553 ns，
TX域内部为+3.398/+0.023 ns。整板仍只有五个setup和五个hold失败输出端点，
脉宽余量+0.081 ns；原4/8 ns bus-skew约束全部通过，最小余量+3.785 ns。
缺失时钟、未约束内部端点、generated clock错误和组合环均为0，最终DRC只有Warning。
原短GSIM/NEMU的全部471个输入重新hash未变，不重新编译CPU或运行全量GSIM/Linux。

只读复核中，将转发时钟源改为同一125 MHz时钟的其他实际祖先，结果没有变化。
TX的DRIVE2/4/6和前轮12/16候选均未优于DRIVE8；最终仍保持DRIVE8/FAST。
隔离候选路由中间曾显示hold约-0.271 ns，但完整时序更新后回到-0.416 ns，不能声称改善。
Vivado再次提示固定/专用IO路径无法靠路由绕行修复hold；这只否定当前局部候选，
并不证明更换输出结构或延时分配方式都无解。

原2 ns PHY名义TX延时、1 ns setup/hold要求、0.25 ns PCB预算和0.5 ns PHY延时容差
全部保持，输出预算仍是±1.75 ns。后两项仍是工程假设，不是本板实测保证。
这组DDR预算在4 ns半周期内只留0.5 ns窗口；当前五根输出的setup和hold均为负，
只平移相位不能同时闭合。继续重复同一类时钟参数或绕线试验没有新的成功证据。

建议的下一结构是FPGA提供TXC的90°相位（2 ns），同时通过MDIO关闭并读回确认
RTL8211F的TX延时，RX延时保持开启；不能让FPGA与PHY重复加入TX相位。
这会改变实体时钟和PHY初始化，而不是直接缩小现有预算。
此处为当时的方案建议；用户随后已确认。当前实现及验证状态见下一节，不能据此认定新方案已闭合。
该时钟方式见[AMD PG160的TX时钟说明](https://docs.amd.com/r/en-US/pg160-gmii-to-rgmii/RGMII-Transmit-Clock-to-the-External-PHY-Device)。
RTL8211F的TX延时位为page 0xd08、register 0x11、bit 8，依据
[Linux Realtek PHY驱动](https://github.com/torvalds/linux/blob/master/drivers/net/phy/realtek/realtek_main.c)。
后续必须配套寄存器读回和实际PHY状态验证，不能仅改XDC或依赖未知strap状态。

验收包已回WSL：`build/fpga/native-tx-isolation-20261005-r1/completion.json`，
状态`CPU100_MET_IO_CANDIDATE_NOT_QUALIFIED`。包含本轮短例、正常小模块综合、
完整路由报告、只读诊断、实际执行脚本与源码hash。
大DCP位于`E:/VM/Share/Valence-rtl/native-tx-isolation-20261005-r5/routed.dcp`。
`source_integrated=false`；下一轮应保留此前不额外占用BUFG的MMCM-trim候选作为有效物理基线。
100 MHz整板目标尚未完成，FPU100和硬件网络功能也未验收。所有本轮命令行Vivado已结束，
旧GUI与可用bit保持不动，不留后台综合。

## FPGA TX相位与软件PHY初始化

2026-10-05新增板级候选：TX数据保持125 MHz，独立转发时钟物理后移2 ns；
RX复用已通过的MMCM ZHOLD、22.5°、0 ps采样边界。CPU、DDR、UART及Chisel MAC未修改。
上一有效物理基线的五个失败端点全部位于RGMII TX pad路径，路径只有OSERDESE3和OBUF，
不是CPU的Chisel组合长链。CPU100 setup/hold为+0.335/+0.011 ns，RX为+0.435/+0.553 ns；
这些是保存基线的数值，不替代新候选最终报告。

PHY寄存器配置归软件驱动。板级`HARDWARE_PHY_INIT=0`为默认值，直接复用SoC的MDIO控制器；
通用Chisel MAC不绑定RTL8211F寄存器。先前新增的板级自动初始化器仅作为可选调试功能，
不作为默认MAC依赖；其独立协议测试不是当前完整板级初始化验收。

新TX与双相位复位的独立短xsim已通过3072字节、四种DV/ER编码、三次异步复位重启，
每条复位链必须等自身第三个时钟边沿释放。数据、控制和相位错误三个负例均被拒绝。
正常小模块综合确认ETH MMCM的INTERNAL模式、125 MHz的0°/90°两路与REF500，
RX MMCM的ZHOLD模式和反馈BUFG保留，复位映射为两条各三个FDPE的链。
当前局部物理候选复用原整板DCP，只更换ETH PLL/两只ETH BUFG并增加转发时钟和三级复位，
351547个其余原有单元位置保持不动。正常板级wrapper综合也确认了两只MMCM和两条三级TX复位链，
默认硬件PHY初始化被剪除。该wrapper检查仅保留CPU/IP接口黑盒，不是完整SoC物理验收。

首次TX90物理报告使用UltraScale+默认LATENCY相位表示，波形未含物理2 ns，相位被计入插入延迟，
外部DDR检查选错相邻边沿，hold报告为-3.476 ns。随后仅将ETH MMCM的`PHASESHIFT_MODE`改为
`WAVEFORM`并重新派生实际pad时钟，得到2/6 ns波形和setup +2 ns、hold -2 ns的正确关系。
实体`CLKOUT1_PHASE=90`、输出预算、时钟不确定性和六棵已布时钟树均未改变；没有增加
false path、multicycle或理想clock latency。RX的原LATENCY表示未改变。
相位表示参见[AMD UG906 2025.1](https://docs.amd.com/r/2025.1-English/ug906-vivado-design-analysis/MMCM/PLL-Phase-Shift-Modes)。

首次最终DRC还报MIG UI BUFG到相邻同列ETH MMCM的级联区域错误。明确设置
`CLOCK_DEDICATED_ROUTE=SAME_CMT_COLUMN`后允许同列全局专用时钟骨干，不使用`FALSE`
或fabric绕行，也不降低DRC严重级别。参考[AMD UG949的专用路由说明](https://docs.amd.com/r/en-US/ug949-vivado-design-methodology/Using-the-CLOCK_DEDICATED_ROUTE-Constraint)。

| 最终检查范围 | Setup最差余量 | Hold最差余量 | 结论 |
| --- | ---: | ---: | --- |
| CPU100，双发射，F/D关闭 | +0.335 ns | +0.011 ns | 保持通过 |
| RX五条data/control采样 | +0.435 ns | +0.553 ns | 保持通过 |
| TX五根data/control输出 | -0.271 ns | -0.203 ns | 改善但未闭合 |

整板WNS=-0.271 ns、WHS=-0.203 ns，仍各有5个失败端点；脉宽最差+0.081 ns。
229296根可布线网络全部完成、routing errors=0；最终DRC没有Error/Critical Warning。
无缺失时钟、未约束内部端点、generated clock错误和组合环，27项原bus-skew预算全部通过，
最小余量+3.785 ns。新方案不是仅修正模型就能过关，仍需优化真正的TX clock/data输出边界。
setup和hold同时为负，不能通过单纯平移相位同时闭合，下一步应改善共用时钟路径与校准I/O结构。

CPU原短GSIM/NEMU验收的全部471个输入再次hash未变；本轮CPU逻辑、流水拍数及IPC未改。
没有重跑完整CPU综合、全量GSIM或Linux仿真，也没有生成bit。PHY软件读回及实板网络未验证。
验收记录位于WSL `build/fpga/native-tx90-software-phy-20261005-r2/completion.json`，状态仍为
`CPU100_MET_IO_CANDIDATE_NOT_QUALIFIED`。大DCP保留在
`E:/VM/Share/Valence-rtl/native-tx90-model-20261005-r1/routed.dcp`。
板级候选源码已经更新，但`source_integrated=false`表示完整源码重组等价性/整板交付尚未验收；
不能把wrapper接口黑盒检查或局部ECO报告表述为新工程已可直接上板。

## 共用参考时钟与独立TX输出时钟

本轮没有修改CPU、DDR、UART、BootROM或通用Chisel MAC。保留已通过的CPU100布局，
在完整整板检查点上批量修改TX时钟来源、pad负载隔离和分频器CLR释放。
冻结CPU仅为减少重复实现时间；检查范围仍是包含CPU、DDR及所有已实例化外设的整板STA，
不是只检查CPU模块。

当前`native_gmac_divided_clock.sv`用一只PLL和共用500 MHz全局树驱动三只DIV4。
内部raw树保留CMU门控和TX边界寄存器；独立pad树只驱动四数据及控制的五只DDR单元，
与转发TXC树使用同一CLOCK_DELAY_GROUP。板级top显式开启`ISOLATE_TX_PAD_CLOCK`；
连接pad端口本身不会开启该默认关闭的通用参数。所有旧已放置单元在本轮ECO中锁定位置，
只增加一只pad DIV并重建相关时钟树；未完成逐单元LOC/BEL前后比较，不声称该比较已通过。

REF500的三级异步断言、上升沿同步释放链使forward DIV比raw/pad DIV晚一个源周期启动。
当前真实UNISIM短xsim通过3072字节、256种数据及四种DV/ER编码、三次冷复位与PLL重锁，
raw/pad同相、forward后移2 ns；数据、控制及相位三个负例均被拒绝。
RX短例也通过0.95/2.00/3.05 ns三个独立PHY转换位置及三个负例。
正常时钟小模块综合保留一只PLL、三只DIV及三只上升沿FDPE，当前源码与短例副本逐字匹配。
当前板级外壳接口综合另确认五只data/control DDR的CLK均来自pad DIV，
默认硬件PHY初始化被剪除、两条三级TX释放链保留；源XDC的真实层次及0/4、2/6 ns波形检查通过。
外壳检查明确保留CPU/IP接口黑盒，仅证明连接和基础约束关系，不是完整源码重组签核；
源XDC日志也保留自动派生时钟覆盖告警，依赖约束仍需审查。
这些是边界功能检查，不是整板SDF、网络协议或真实PHY读回验收。

生成时钟必须保留真实PLL/CLKOUT0到DIV输出的传播关系。此前显式`-edges {1 5 9}`
在当前Vivado模型中造成两个generated-clock traversal错误，相关极差I/O结果不能用作签核。
复核实际PLL、REF缓冲及DIV节点后，采用工具认可的divide4波形和forward的折叠边沿表达；
三个等价源节点表达给出相同有限结果。2 ns相位同时由实体CLR顺序及短例验证，
不能仅由XDC声明。当前未使用负source latency、I/O延时级联或放宽±1.25 ns输出预算。

| 最终检查范围 | Setup或Recovery最差余量 | Hold或Removal最差余量 | 结论 |
| --- | ---: | ---: | --- |
| CPU100，双发射，F/D关闭 | +0.335 ns | +0.011 ns | 保持通过 |
| RX五条data/control采样 | +0.435 ns | +0.553 ns | 保持通过 |
| 三只DIV的CLR释放 | +0.342 ns | +0.783 ns | 通过 |
| TX五根data/control输出 | -0.036 ns | -0.003 ns | 仍未闭合 |

最终setup失败为`eth_txd[2]`的-0.036 ns及`eth_tx_ctl`的-0.009 ns，
hold失败为`eth_txd[0]`的-0.003 ns。整板TNS=-0.045 ns、THS=-0.003 ns，
脉宽最差+0.081 ns；229300根可布线网络全部完成、routing errors=0。
缺失clock、未约束内部端点、失联generated clock和组合环均为0；
27项原bus-skew预算全部通过，最小余量+3.785 ns，最终DRC无Error/Critical Warning。
运行日志另保留自动派生pad时钟被显式时钟覆盖的Critical Warning；这不能由最终DRC无错误
替代审查，后续完整源码重组还须核对被覆盖时钟的依赖约束和CDC报告。

相对上一有效TX90候选的-0.271/-0.203 ns，TX setup改善0.235 ns、hold改善0.200 ns。
独立PLL对及单TXC校准延时候选均没有同时闭合setup/hold，其失败证据保留，
不作为当前默认板级结构。原短GSIM/NEMU全部471个输入重新hash未变，没有重跑全量CPU或Linux。
本轮CPU拍数、IPC和100 MHz频率均未改变，不能将I/O余量改善称为CPU性能增幅。

冻结布局的局部实现仍未达标。下一步建议在已验证的时钟结构和原接口预算下，
重组当前板级源码、复用未变的SoC综合网表，再放开整板布局及物理优化作一次对照。
重新布局可能改善时钟树匹配与布线，但不保证自动闭合，也可能降低CPU已有余量；
须以新整板最终setup/hold/pulse、完整CDC和约束覆盖结果决定，不能只看最差WNS。
本轮没有启动此全量重新实现，没有生成bit，旧GUI和可用bit保留。

整板报告、当前短例、正常小模块综合和源模型诊断已归档到WSL：
`build/fpga/native-divided-pad-20261005-r2/completion.json`，状态仍为
`CPU100_MET_IO_CANDIDATE_NOT_QUALIFIED`。大型DCP保留在
`E:/VM/Share/Valence-rtl/native-divided-pad-eco-20261005-r3/routed.dcp`。
`source_integrated=false`：当前源码重组等价性、真实PHY配置和网络功能仍未验收，
不得将实验ECO结果当作新整板bit的交付资格。

## 开启浮点的整板重新实现

2026-10-05本轮显式使用`rv64gc`、双发射、`staged-fetch-feedback`、CPU100 MHz、
常开及原始UART50 MHz、UART460800、DDR UI250 MHz。新增FPU使旧整数CPU综合网表不可复用，
因此一次完整综合后放开CPU及普通逻辑的整板布局；只保留实际板级管脚、DDR和必要局部时钟约束。
未改全局整数默认值、现有GUI工程或旧bit，也不在本轮生成bit。

当前源码的两个受影响短模型已经通过，凭据为
`build/gsim/rv64gc-native-20261005-r1/receipt.json`：真实CPU通过1,212组独立SoftFloat向量、
61,865次提交、77,748周期及错误注入负例；当前板级CPU/cache/AXI配置通过31,960周期、
32个FPR及FCSR保存恢复、S-mode调用、Sv39上下文和压缩浮点访存检查。
板级模型为单时钟，不包含真实受管UART/GMAC CDC；它不是Linux浮点调度验收、整板SDF或ISA认证。
外设复用证明仅覆盖重新hash未变的49个IP/bus源文件，MDIO另使用当前96事务独立验收，
不将旧整数CPU全部471输入验收套用到新的F/D CPU。

DIV自动时钟先仅改名，再给同名forward时钟赋已验证相位，防止覆盖不同名称的自动时钟时
丢失其依赖约束。独立小测试保留setup/hold uncertainty及max-delay三个哨兵约束，重复应用后均存在，
本次没有`Constraints 18-1055`。哨兵只进入测试DCP，绝不进入整板预算；forward仍为实体CLR建立的
2 ns相位，±1.25 ns输出预算、时钟不确定性和复位释放检查未放宽。
机制参考[AMD自动时钟改名说明](https://docs.amd.com/r/en-US/ug903-vivado-using-constraints/Renaming-Auto-derived-Clocks)。

`stage_native_rv64gc.py`核对短验证来源、15根PHY管脚、FPU实际RTL实例、misa及ROM初始化。
新构建BootROM为简洁下载版、3,061字节，COE与已综合BMG初始化内容逐字相同；复用厂商IP生成物。
MIG及四个厂商IP均复制到私有候选，不再引用GUI工程的可写生成目录。
整板候选位于`E:/VM/Share/Valence-rtl/native-rv64gc-20261005-r1/`，
完整RV64GC源码导出与固件也保留在WSL `build/fpga/native-rv64gc-20261005-r1/`。

实现于2026-10-05 18:26启动，完整F/D综合约7分半、0错误、0综合Critical Warning。
初次进入板级约束时因打包遗漏`cdc_constraints.tcl`停止；补齐依赖后18:40从本轮自身的
`post_synth_unconstrained.dcp`续跑，未再次综合。原失败日志和输入清单保留，续跑输入见
`inputs-resume-r2.json`，输出为`implementation-resume-r2/`，不是复用旧整数CPU检查点。
综合阶段整板211,656 LUT/98,723 FF/44 DSP，浮点系统23,423 LUT/6,127 FF/22 DSP；
该初步统计仍可能随整板物理优化变化。MIG初始化期间两条空目标false-path告警保留待审查。
最终实现于20:13完成，记录为`build/fpga/native-rv64gc-20261005-r1/completion.json`。
CPU100 setup -0.685 ns、9,683个失败端点，hold +0.003 ns；TX setup -0.037 ns、hold -0.003 ns，
RX setup -0.090 ns、hold +0.858 ns。整板setup失败9,689个、hold失败1个，仍未达标。
DIV CLR recovery/removal为+0.318/+0.797 ns；27项bus-skew通过，最小余量+3.696 ns。
259,909根可布线网络全部完成，无routing error，最终DRC无Error/Critical Warning。
两条MIG空目标false-path运行告警仍保留，不以最终DRC无错误替代审查。
最终整板211,164 LUT/99,366 FF/44 DSP，浮点系统23,551 LUT/6,127 FF/22 DSP。
实现完成时主源码已进入下一批重构，旧输入清单还包含续跑时修正的打包脚本差异，
因此`source_integrated=false`；这是冻结旧候选的时序基线，不是新源码或可用bit资格。
历史FP核心内部WNS +0.090 ns与历史整数整板CPU WNS +0.335 ns不能代替本次负结果。
浮点仍为ROB-head单未完成操作，不宣称FP双发射或新IPC增幅。
PHY初始化归软件，要求TXDLY=0、RXDLY=1读回；没有据此宣称真实网口或Linux驱动已通过。

## 批量长链重构与短验证

2026-10-05按用户要求扩大批次，先合并相关改动，再统一短验证和一次整板实现。
最差旧路径为TL occupied到取指响应，-0.685 ns、10.502 ns数据延迟，布线占90.8%；
同时包含correctionPending到取指请求、65位storeEnd进位和FPAddD输入至raw结果。
只读200条CPU路径报告保留在旧候选的`path-review/`，没有为报告重复实现。

| 重构范围 | 合并的具体改动 | 周期和接口代价 |
| --- | --- | --- |
| 存储依赖 | 用61位beat分块相等与8位字节掩码替代65位区间端点加法及比较；store流水传递byte lanes | 合法对齐请求不加拍；未对齐load保守等待并保持原精确异常 |
| FPU算术 | S/D加减、S/D乘法各增加输入recoding寄存边界 | 每单元延迟2→3、最小II 3→4；不是FP并行发射 |
| FPU状态与完成 | 三个FPR读口8词分组one-hot；misc结果与10路完成采用互斥one-hot；FP访存完成加两项队列 | 读口/misc无新增拍；FP访存完成加一拍，trap取消和busy排空保留 |
| TileLink | A源占用译码复用；D owner/source并行查询；router owner改三位one-hot | 不加协议拍，不提前释放source，不改变burst锁与背压 |
| 取指 | hint全字段分组one-hot；正常/纠正PC进位并行计算，最后选择 | 不增加正常流或redirect拍数，保留跨界压缩指令及地址回绕 |
| RGMII | RX实际MMCM相位0.50→0.75 ns；隔离pad DIV移至同区域相邻站点 | 实体时钟改变，非仅XDC改波形；±1.25 ns TX预算不变，布线收益待测 |

短验收`build/gsim/rv64gc-path-batch-20261005-path-b3/receipt.json`已通过：
54,576个独立访存区间判定、7,875周期FP状态、27,840组SoftFloat数值与全阶段kill/backpressure、
两种取指宽度及hint容量、legacy/raw两类TL及多拍读写、错误响应和错误bank负例。
真实整数CPU完成13个短吞吐负载、50个控制/访存程序及11个恢复程序的NEMU比较。
只复用了源码未变且再次执行的隔离单元模型；fetch、整数CPU、F/D CPU和板级模型均重新生成。
runner退出码与路径修复的失败记录保留，不将它们伪装成硬件失败或删除。

13项整数短基准与`native-timing-20261004-r3`周期全部相同：独立ALU IPC 1.98834951，
相同内存模型下load/use、memory/ALU和编译sum均未退化。这不是CoreMark或Linux提速结论。
真实F/D CPU仍为1,212组向量、61,865次提交、77,748周期；当前profile板级上下文32,014周期，
比31,960增加54周期（0.17%），覆盖32 FPR/FCSR、S-ECALL、Sv39和压缩浮点访存。
FP新增级的真实应用成本仍需浮点负载测量，不能用整数IPC不变推断FP吞吐不变。

真实板级RX模块直接进入UNISIM短例，独立检查0.75 ns物理相位、125 MHz周期、三种PHY眼图转换
及lock复位；TX另验证实体2 ns相位与数据/控制/错误相位负例。两者已通过，但无SDF或真实PHY资格。
47个未变IP/bus文件继续核对旧外设凭据；本批修改的两个TL文件必须有新burst/owner/CPU证据，
打包器遇到缺失证据、source/model/CPU哈希漂移时拒绝，门禁与报告解析14项单元测试通过。
最终来源检查还包含物理时钟、top、XDC与实现Tcl的当前源码对照，不能仅检查Chisel。

新候选为`E:/VM/Share/Valence-rtl/native-rv64gc-20261005-path-b3/`；完整RTL、固件位于
WSL `build/fpga/native-rv64gc-20261005-path-b3/`。CPU100/双发射/F+D/UART460800保持，
BootROM仍为3,061字节下载版，COE与原BMG初始化一致。20:39开始统一综合布局布线，
逻辑综合约7分26秒、0错误；IP合并后的综合命令约8分43秒完成，3条未实例化旧
`clk_wiz_eth`的XDC告警保留。当前Ethernet实体使用自研PLL/DIV，不以此忽略真实时钟检查。
CPU不冻结、不复用旧CPU检查点；当前最终setup/hold/pulse、资源、CDC与PHY结果仍待验收。
本轮不生成bit，不覆盖GUI工程或原可用整数bit。
