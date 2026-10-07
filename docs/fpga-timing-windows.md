# 在 Windows Vivado 检查当前 SoC 的内部时序

2026-10-07 归档提示：本文按日期保留的 `build/...` 日志、回执和检查点已移入仓库外
`/home/openion/Valence-archive/20261007-precommit/build-before-cleanup.tar.gz`，
不是当前工作树中的活动路径。最新 r6 发布目录另可直接读取该归档下的 `current-release-r6/`，
最终签核见其中 `phase-placement-completion-r11-final.json`；已交付 Windows bit 不受此次清理影响。
完成的一次性本机恢复作业保存在归档的 `completed-local-jobs/`，不再作为仓库生产入口。
需要恢复旧证据时解包到新的空目录，不覆盖当前工程；详见 [整理清单](repository-maintenance.md)。

## 当前批次（2026-10-06 r6）：UART 修复、取指／发射／访存裕量

基线为 RV64GC、双发射、CPU 100 MHz、UART/AON 50 MHz、MAC 125 MHz、
完整 2 GiB DDR。r5 最终整板 setup/hold 仅 +0.003/+0.003 ns；
head→M/D 右操作数、rawCursor→窗口匹配→cursor CE、store→访存地址仍在边缘。

本轮一次性实施三组结构调整，再运行必要短 GSIM，未增加流水拍或降频：

| 链路 | 结构调整 | 当前验证 |
| --- | --- | --- |
| 取指地址匹配 | 三个共享 58-bit 区域 tag + 每 key 3-bit offset，保持完整地址／上下文语义 | 两种容量各 20,208 次检查，含 64B/4GiB/XLEN 回绕及失效 |
| ROB head→发射 owner→PRF | 同提交边沿预译码 head 边界，供 ALU/store/LSU/M-D 选择器共用 | 65,536 候选集合、4,101 次回绕，独立 oracle 与负控通过 |
| 访存候选→地址寄存器 | payload 每拍捕获，授权仍由 valid+token+pending 控制，移除晚到的宽 CE | 真实 CPU 的短访存、精确恢复及 NEMU 逐提交对照通过 |

新增 `registeredIssueHeadMask`、`unconditionalMemoryPayloadCapture` 参数默认关闭，
`staged-fetch-feedback` 板级配置启用；原有 ISA 和发射宽度配置保持独立。
短 13 用例周期数全部与 r5 前端／返回控制基线一致：独立 ALU 1024 条／515 拍，
IPC 1.98835；此次不能宣称同频 IPC 提升。实际 RV64GC 板级短模型
32,326 拍完成 FPR 上下文／Sv39／压缩指令检查，不等同 Linux 调度或板测。
回执 `build/gsim/soc-uart-margin-20261006-r6b/receipt.json`；
地址／DMA与生产导出 `build/gsim/ddr2g-uart-margin-20261006-r6/receipt.json`；
网络压力 `build/gsim/network-packet-pressure-uart-margin-20261006-r6/receipt.json`。

r5 ROM 将 DLL 误设为 7，板测在 65829 baud 正常，定位为软件分频配置错误，
并非据此证明 100 MHz 不稳定。r6 使用 7,372,800 Hz 参考、DLL=1、FCR=7，
实际编译指令的独立 16550 模型执行审计通过；旧 ROM 负控被明确拒绝。
新 ROM 10,384 字节，SHA256 `e59abd1e6cc3384efeffae36b81c7ef1b479826f2e500ae1bec7510b7b6f1441`。
32,768 MIF 字与 bin 完全一致。发布还须逐项比对最终网表 INIT/INITP。

新私有候选 `E:/VM/Share/Valence-rtl/native-rv64gc-uart-margin-20261006-r6`：
237 个生产 SV、549 个已验收输入文件、780 个冻结候选文件。
一次整板新综合／正常布局布线已启动，使用原 XDC，不复用旧 CPU checkpoint。
首次完整路由／`Explore` 物理优化于 23:21（UTC+08）结束：
**整板 WNS -0.141 ns、WHS +0.005 ns、WPWS +0.081 ns，53 个 setup 失败端点；
CPU setup -0.013 ns（51 端点）、hold +0.005 ns；未生成 r6 bit。**
其余两个 setup 失败端点为 500 MHz 相位时钟的 `phase_reset[1]`→
`quarter_div/CLR`（-0.141 ns）及 `raw_div/CLR`（-0.104 ns）。
CPU 最差为 `correctionPending`→`fetchAdapter/data[60]/R`，13 级，
数据延迟 9.654 ns，其中布线 8.597 ns（89.1%）；
另有 `rawCursor[37]`→`fetchAdapter/requested[0]/D` -0.012 ns，18 级。
266,530 条可路由 net 全部完成，0 routing error，候选输入／源码漂移均为 0。
首次路由资源为 210,596 LUT / 104,981 FF / 64 RAMB36 / 3 RAMB18 / 44 DSP；
实际 FPU 25,101 LUT / 8,401 FF / 22 DSP，仍启用 F/D。
证据 `build/fpga/uart-margin-20261006-r6/routed-proof-r1/completion.json`，
原检查点保存在候选 `implementation/routed.dcp`。
一次自身检查点 `AggressiveExplore` 后处理于 23:29（UTC+08）结束：
CPU setup **+0.000 ns（报表三位小数）、0 失败端点**，hold +0.005 ns；
整板 setup **-0.141 ns、2 失败端点**，hold +0.005 ns、pulse +0.081 ns。
仅剩上述两个相位复位 recovery 端点；路径报告第二条仍为 -0.104 ns，
总负余量汇总为 -0.246 ns，不应由已舍入的单条 slack 反推精确总数。
CPU 最边缘路径变为 `branchRedirectValid`→`captured_0_base[31]/D`：
12 级，10.053 ns 数据延迟，布线 8.776 ns（87.3%）；不能把 +0.000 当成足够裕量。
27 条 bus-skew 全通过（最小 3.696 ns），路由错误／DRC Error/Critical 为 0，
候选与源码均无漂移。**整板仍未通过；驱动已停止，未生成或复制 r6 bit。**
最终状态 `STOPPED_TIMING_OR_MARGIN_NOT_MET`，证据及驱动／日志已归档到
`build/fpga/uart-margin-20261006-r6/completion-job.json`，两轮检查点和原报告均保留。
Windows/WSL 结束报告 SHA256 同为
`a5f3c22d92f00f38f36471899092a0dc3398c83c1cf33b76374edcbb1b36e8ba`。

进一步优化应针对相位复位的物理边界，而不是继续盲目整板循环：当前
`phase_reset[1]` 位于 `SLICE_X114Y77`，其到 quarter-divider CLR 的线路为 1.056 ns，
总路径 1.137 ns、时钟 skew -0.870 ns；r5 合格参考位于 `SLICE_X115Y90`，
相同 recovery 路径 +0.019 ns、skew -0.845 ns。
这支持优先检查复位同步链局部摆放／线路及专用 clock-divider 边界；
不是 PMP/FPU 算术长链，也不能通过给复位加 blanket false path 跳过。
CPU 则需同时继续收紧重定向→地址 payload 与 fetch-adapter 反馈的零裕量链。
上述 23:29 记录截止时尚未做新的 ECO；未导入旧 CPU 网表、未修改用户 GUI 工程。
整板综合已成功，0 Error/0 Critical Warning。同阶段 r5→r6：
LUT 212,445→211,333（-1,112），FF 104,408→104,359（-49）；
IntegerCore LUT 138,404→137,308（-1,096），FF 43,127→43,134（+7）。
FPU LUT 25,171、FF 8,401、DSP 22 不变；整板仍 64 RAMB36/3 RAMB18/44 DSP。
这不是用不同阶段的资源数做对比，也不是布局布线后结果。

原后台 `fpga/zu15eg/finish_uart_margin.ps1` 等自身整板报告，没有人为截止时间；
已于上述 23:29 后以不满足时序结束，后续局部 ECO 使用独立接续驱动。
本轮额外工程裕量目标：CPU setup≥0.100 ns、hold≥0.010 ns，
整板 setup≥0.020 ns、hold≥0.010 ns。完整 STA/IO/CDC/skew/ROM/DRC 是不可省略的签核条件。
最多从自身 routed.dcp 再做一次物理优化；失败结果与原路由均保存，
不会重跑综合、放宽 XDC、降频或生成时序不合格 bit。
用户随后指示“若满足时序就生成 bit”：本次后台驱动显式使用 `-AllowNominalRelease`，
允许额外裕量目标不足但完整 10 ns 静态签核通过时，选自身合格路由生成 bit；
`engineering_margin_met` 必须如实记录，不能把 nominal 通过说成额外裕量目标完成。
后处理状态写入候选 `completion-job.json`；通过时最终 bit 复制为配套固件目录的
`valence_vl100_rv64gc_2g_cpu100_u460800_r6.bit`，之后仍需真实板测。
全套纯软件 firmware 测试与 CDC 发布门禁测试通过，日志保存在
`build/fpga/uart-margin-20261006-r6/firmware-unit-tests.log` 与 `release-guard-tests.log`。
后台驱动曾在预检查中发现 Python `-I` 去掉脚本目录、阻止同目录工具导入；
已用隔离 `runpy` 启动显式添加冻结工具目录，不改冻结 RTL/验收工具/XDC。
同后台 Windows PowerShell 5 运行时导入复核、正常裕量／薄裕量／失败状态门禁通过；
只重启等待驱动，Vivado 进程未中断。当前后处理日志为 `finish-job-r2.log/.err`。
原 r5、GUI 工程与未提交改动保留；没有烧录、串口访问或网络流量。

### 2026-10-07 接续：相位复位的局部物理 ECO（完整静态发布通过）

CPU 逻辑资源减少并不保证每次整板路由的 WNS 单调提高。
当前相位复位 recovery 路径约 93% 为布线；相对 r5，quarter CLR 线路增加约
0.135 ns、时钟 skew 恶化约 0.025 ns，足以消耗原有 0.019 ns 余量。
不能将此归咎于 FPU 算术，也不能据此判断短 GSIM 的架构功能回退。

新 `repair_native_phase_reset_placement.tcl` 仅打开自身 `physical-opt-r1/routed.dcp`，
在实测附近选择无 FF/RAM/SRL 占用的位置，整体移动三拍 `ASYNC_REG` FDPE，
不搬 DDR/CPU 占用单元。原参考位置 `SLICE_X115Y90` 本轮已被 DDR 校准逻辑占用；
扩展搜索后选中 `SLICE_X112Y85`。首次实际重布线 `reset-placement-r5`
被保护检查拒绝：Vivado `route_design -preserve` 虽关闭 PSIR，仍重建了
CPU 时钟网 `clk_soc`，并出现 router estimate WNS -0.079 ns；该中间估算
不是合格整板 STA，也没有生成 bit。当时 `reset-placement-r6` 的方案为：
显式 `IS_ROUTE_FIXED=true` 固定所有非关联的已完成路由（包括 CPU 时钟），
不更改时序预算／clock period／false path，之后仍逐项比对实际 ROUTE。
脚本保存并比对其余全部 primitive 的 REF/LOC/BEL、非关联 net 的 ROUTE，
以及时钟集合、频率、波形和复位寄存器 INIT/ASYNC_REG；不重综合、改周期或加例外。
空位置属性查询与 ASYNC_REG 数值编码的诊断问题已修正，失败诊断均保留，
不应当作硬件功能或时序结果。

`finish_phase_placement.ps1` 仅在局部保护检查及完整整板时序通过后接续
当前网表 CDC、mailbox、ROM INIT、IO/skew/DRC 和发布契约验收，然后生成 bit。
旧 `completion-job.json` 不覆盖；本次新结果为 `phase-placement-completion-r6.json`，
此前 r4/r5 失败诊断及结果均保留，不混作发布结果。
额外工程裕量不足会单独记录，不因 nominal 通过而声称已满足裕量目标。
本次未增加新 CPU 流水拍，周期数／IPC 不应因物理摆放改变；真实板测仍待交付后进行。

2026-10-07 上午接续：`reset-placement-r6` 完整报告确认整板 WNS **-0.078 ns**、
TNS -0.147 ns、2 个失败端点；hold **+0.005 ns**、pulse **+0.081 ns**。
CPU setup **+0.000 ns、0 失败端点**，hold +0.005 ns，故 router 中间估算
-0.092/-0.079 ns 不能作为 CPU 时序回退的结论。两个实际失败均为相位复位 recovery：
quarter CLR -0.078 ns、raw CLR -0.070 ns，数据路径 1.078/1.070 ns，
其中布线 0.998/0.990 ns、skew -0.865 ns；removal +1.041/+1.048 ns。
该尝试仍因 637 个层级 ROUTE 字符串不一致而被保护检查拒绝，保留完整未合格
`reset-placement-r6/routed.dcp` 和报告，未生成 bit；尚不能以字符串差异直接
断言对应的全部物理 PIP 均改变，也不能忽略该保护结果。

新 `repair_native_phase_reset_route.tcl` 从此自身完整检查点，仅重布
`phase_reset[1]` 一个信号网；明确验证 Q→phase_reset[2]/D、raw/quarter CLR
的四个实际 pin，不执行 placement 或全局时钟重布。使用单 net shortest-delay
路由，随后核对所有 primitive 位置、其他规范化物理 net 的 ROUTE、时钟与
复位 INIT/ASYNC_REG，并执行相同整板 setup/hold/IO/CDC/skew/DRC 检查。
`reset-placement-r7` 单网路由耗时 22 秒，物理保护检查无违反，完整 STA 仍为
整板 -0.084 ns、两个 recovery 失败端点，CPU +0.000 ns、hold +0.005 ns。
单纯压短信号线不足以弥补本轮时钟偏斜，未生成 bit。无新功能或 CPU 流水拍
变化，原短验证仍保持输入 hash 一致。

后续 `repair_native_phase_reset_half_slice.tcl` 将三拍复位链交换到旧参考
`SLICE_X115Y90`，使用自身 r6 完整检查点，不导入旧 CPU 网表。只移动目标
slice 下半部的两个 DDR 校准 FDRE 到 `SLICE_X112Y85`，保留上半部七个 FF。
两颗 DDR FF 原最差 setup 分别 +2.494/+1.735 ns，先检查后移动；原逻辑连接、
INIT、ASYNC_REG、时钟 period/waveform 必须一致。不相关信号路由和其余
390,042 个 primitive 位置受保护；允许真实时钟树的物理刷新，但全部时序
检查仍以新完整路由为准，不以保护通过代替时序签核。

| 局部尝试 | 确定的阻塞原因 | 处理 |
| --- | --- | --- |
| r8 | CFF2 数据入口与固定 C6 LUT 输入共享 | 缩小 DDR 交换范围，不使用 CFF2 |
| r9 | AFF 数据入口与固定 A1 LUT 输入共享 | 查询实际 site pin，占用不凭空位坐标判断 |
| r10 | D6 未被 LUT 使用，但固定 `mcal_DQIn_r_reg_n_0_[227]` 路由仍占用该入口 | 保留失败日志，停止无效路由，不生成 bit |

r11 对该**唯一 DDR 冲突信号网**增加 setup/hold 前检查，允许它与五颗 FF
连接网一起重布，其余信号路线仍逐项比较。目标复位 BEL 为 AFF2/BFF2/DFF2，
不改变同步级数或逻辑语义。该 DDR 信号网前检查为 setup +3.257 ns、
hold +0.084 ns。最终必须同时通过整板 setup/hold/pulse、RGMII IO、bus-skew、
CDC、ROM INIT 与 DRC，才能生成 bit。
新接续结果为 `phase-placement-completion-r11.json`；失败历史和原检查点均保留。

09:49（UTC+08）r11 完整路由及独立审计已通过：整板 setup **+0.000 ns**、
hold **+0.005 ns**、pulse **+0.081 ns**，三类失败端点均为 0；CPU setup
+0.000 ns、hold +0.005 ns，原短 GSIM 周期不变。两个 recovery 端点均为
**+0.015 ns**（quarter -0.078→+0.015、raw -0.070→+0.015 ns）；线路均
0.930 ns、skew -0.840 ns。removal 最小 +0.997 ns。
266,533 条可路由 net 全部完成，0 routing error，DRC Error/Critical 为 0；
27 条 bus-skew 均通过，最小 +3.696 ns；候选／源码 hash 无漂移。
保护比较确认 **0 时钟路由刷新、0 不相关位置／路由违反**，只改变声明范围。
RGMII TX setup/hold +0.066/+0.138 ns、RX +0.188/+0.604 ns。
已采用自身合格检查点，原 implementation 可恢复归档保留；独立回执
`build/fpga/uart-margin-20261006-r6/phase-placement-adopted-r11-proof/completion.json`。
随后发布阶段 CDC/mailbox/ROM INIT 与契约检查通过；686 条当前 CDC finding
按现有模块证据逐类复核，最终 4,176 个 ROM INIT/INITP 属性与选定 ROM IP 一致。
额外工程裕量目标仍未达到，不能将报表舍入的 +0.000 ns 称为充足裕量。

09:56:15（UTC+08）Vivado `write_bitstream` 正常完成，0 Error/0 Critical Warning。
交付为 `E:/VM/Share/Valence-rtl/firmware-debian13-vl100-2g-20261006-r1/valence_vl100_rv64gc_2g_cpu100_u460800_r6.bit`，
28,700,918 字节，SHA256
`d7568fd2102cc3b549c1f05bd742bab80ea5f962f91db9ad425c515870ac2fc5`。
配置仍为 RV64GC F/D ON、双发射、CPU 100 MHz、UART 460800、完整 2 GiB DDR；
沿用现有 Debian 配套 payload，无需为 DLL 修复重编 OS。
生成后驱动的 PowerShell 5 `Get-FileHash` 模块查找失败，未影响 bit 或静态签核；
原失败回执保留，另用运行时 SHA256 核对原件／交付副本，并在 PS5 验证修复。
补做当前网表契约／CDC 报告／冻结源码审计，发布物和两个必要 DCP 已归档 WSL。
最终回执 `build/fpga/uart-margin-20261006-r6/phase-placement-completion-r11-final.json`，
状态 `PASS_STATIC_RELEASE_BOARD_RETEST_REQUIRED`，`engineering_margin_met=false`。
静态通过不是实体板运行证明；UART、跨 4 GiB DDR、大帧网络压力及 Linux
浮点上下文仍需烧录此 bit 后复测。本轮没有访问串口、烧录或发送网络流量。

## 最新未推广候选（2026-10-04）：取指反馈 + 自研网络 DMA

`staged-fetch-feedback` 在完整 F/D、双发射、相同 production CPU 端口的 10 ns OOC
布线通过内部 setup/hold：**WNS +0.290 ns、内部 hold +0.024 ns**。
相比上一 `staged-ethernet` 内部 -1.512 ns，改善1.802 ns；141737 LUT / 41259 FF / 41 DSP，
旧为141077 LUT / 41191 FF / 41 DSP（+660 LUT / +68 FF）。
同二进制短 NEMU A/B 13项周期不变；实际 board RV64GC/权限撤销检查通过，未新增流水拍。

本轮 DMA/TileLink 短验收 `build/gsim/ethernet-dma-20261004-r7/receipt.json` 通过；
真实 MAC/初始化 ROM/CPU/DMA 联合综合无残余功能黑盒，200903 LUT / 85740 FF /
43 RAMB36 / 41 DSP。其中网络 DMA 本体为1805 LUT / 729 FF / 2 RAMB36，默认关闭。
四个 FIFO/八组 Gray 指针约束全部命中，CDC-only 双时钟 xsim通过。
**接口 hold=-0.049 ns、联合网口 CDC Critical仍未签核**；无MIG/PHY管脚整板布线，
无Linux网卡驱动/真实收发/千兆线速资格，MAC硬件授权仍未确立。不生成新bit或改旧工程。

新最差内部链为 head→store owner/PRF→地址/范围→storeSafeRange，22级、9.691 ns，
其中布线7.558 ns（约78%）。局部 head fanout406 和 PRF fanout64/2.103 ns网线是后续裕量重点。
严格审计 `build/fpga/ethernet-dma-20261004-r2/audit-final.json`，必要原生报告/checkpoint、
已验收源码及审计工具逐文件核对并归档到同目录 `native-results/`。
这是一次 CPU 综合/布线、一次外围联合综合；旧已交付的整数 100 MHz bit资格与下节记录不变。
接口与未签核项详见 [Ethernet台账](../fpga/zu15eg/ethernet-integration.md)。

## 最新交付状态（2026-10-03 17:32，UTC+08）

双发射 `staged-throughput` 的真实整板 **100 MHz / UART 460800** 已完成严格静态
签核并生成 bit，未降低时钟或放宽约束。最终 WNS +0.101 ns、WHS +0.010 ns、
WPWS +0.081 ns，setup/hold/pulse 的总负余量和失败端点均为 0；14 条 bus-skew、
路由、复位/CDC、bitstream DRC 与实际 BootROM 初始化一致性审计通过。

交付目录为 `E:/VM/Share/Valence-rtl/ddr-opt-20261003/authorization-board100-u460800/release/`：
`valence_ddr100_uart460800_fifo.bit`、配套 OpenSBI+Linux/BusyBox/fastfetch 镜像、
100 MHz DTB、串口下载器、`signoff.txt`、固件与短验证清单均在同一目录。
最差余量仍只有 0.101 ns；这不是更高频率保证，也不等同于真实板卡 UART/DDR/Linux
压力测试通过。旧 50 MHz 可用 bit 和用户 GUI 工程未被替换。完整本轮证据见文末。

## 历史板级状态与证据优先级（2026-10-01）

当前 DDR 板级 profile 是 `BoardSocTop`：双发射、128 KiB BMG ROM、
PL DDR4（物理 2 GiB，CPU 当前映射前 512 MiB）。最新两版为
45 MHz / 1.5 Mbaud 与 50 MHz / 115200，均启用 FIFO UART；MIG UI 保持 250 MHz。
Board40 的 1 MiB UltraRAM 是保留的另一配置，不应拿它的旧报告代表 DDR50。
软件合同见 [datasheet](soc-datasheet.md)，工程步骤见 [ZU15EG 说明](../fpga/zu15eg/README.md)。

| 对象/阶段 | 结果 | 正确解读 |
| --- | --- | --- |
| DDR50 已有 routed DCP / V0.1 BootROM bit | WNS +0.001 ns，WHS +0.008 ns，WPWS +0.081 ns，TNS/THS/TPWS 0 | 原版本静态时序通过但裕量很小；不能据此认定 UART 接收故障是时序故障 |
| 新 early-issue DDR50 bit | CPU WNS +0.328 ns；整机 WNS +0.267 ns、WHS +0.010 ns、WPWS +0.081 ns | 新整机静态签核通过；用户上板反馈仍拒绝下载头部，UART 物理验收未通过 |
| 旧 DDR45 降频对照（未发布，FIFO 升级前） | CPU WNS +2.489 ns；整机 WNS -2.011 ns、WHS -0.114 ns，复位同步 PRE 违例 | CPU 主数据路径裕量增加，但复位 CDC / 约束需单独审查；未生成 bit |
| 新 FIFO DDR45 / 1.5 Mbaud bit | CPU WNS +2.489 ns；整机 WNS +0.267 ns、WHS +0.010 ns | UART hold 与复位旁路已修正，完整静态签核通过；待上板 |
| 新 FIFO DDR50 / 115200 bit | CPU WNS +0.328 ns；整机 WNS +0.267 ns、WHS +0.010 ns | 完整静态签核通过；未新增 CPU 流水级，待上板 |
| UART RX 同步链 | 新实现两级 ASYNC_REG 均 TRUE，已进入布局布线并签核 | 同步链属性修复完成，但未证明它是串口故障原因 |

已发布基线位于
`D:\TOOLS\projects\vivadoProjects\ZU15EG\src\board-ddr50\bootrom-v01-noprompt\release`。
范围/PMP 历史候选保留在 `E:\VM\Share\Valence-rtl\ddr-range-20260930`。
early-issue 历史候选在 `E:\VM\Share\Valence-rtl\ddr-feedback-20261001`。
最新 FIFO UART 候选根目录为 `E:\VM\Share\Valence-rtl\uart-fifo-20261001`，
两组独立 RTL/固件/分区/签核报告分别保留。默认板级 timing profile 为 early-issue；
旧 GUI 工程引用和已发布 bit 未被替换。

目标是先让 50 MHz 具有可靠的时序与 CDC 证据，再争取更高频率；50 MHz 不是上限。
频率收益与同一工作负载 IPC 一起评估，不能把不同配置的 IPC 与 Fmax 相乘。
默认按模块迭代、仅跑必要 GSIM，收敛后再做一次整机布局布线。
下面保留历史实验记录；历史“未验证/下一步”仅对应当时阶段。

## 历史时序 profile 与 OOC 工具

在 WSL 或 Linux 虚拟机中运行 `make fpga-current-soc-rtl`，也可用
`make fpga-compact-soc-rtl` 导出较小的双发射配置。命令分别导出
`build/fpga-current-soc/` 或 `build/fpga-compact-soc/`，其中包含生成的 SystemVerilog、
`vivado-ooc.tcl`、`vivado-module-ooc.tcl`、`vivado-hierarchy-audit.tcl` 和 Windows 批处理入口。通过共享文件夹或直接复制整个目录到
Windows；RTL 约数 MiB，不需要在虚拟机安装 Vivado。

在 Vivado GUI 的 Tcl Console 中先用 `get_parts *xczu15eg*` 查出本机安装的
完整器件名（包括封装和速度等级）。另开 Windows 命令提示符，先运行 Vivado
安装目录中的 `settings64.bat` 设置命令行环境，再进入复制得到的目录运行：

```bat
run-current-soc-timing.bat FULL_PART 10
```

`10` 是目标周期 10 ns，不代表已经达到 100 MHz。脚本运行 OOC 综合、布局布线，
并在 `reports/post_route_timing.rpt` 和 `reports/post_route_utilization.rpt` 留下时序与资源结果；
`reports/check_timing.rpt` 显示约束问题。先看 worst negative slack、total negative slack
和未约束路径，再看资源是否溢出。若命令提示符找不到 `vivado.bat`，
检查 `settings64.bat` 是否来自同一 Vivado 安装。

`CurrentSocTimingTop` 实例化当前 4-issue 压缩指令核、128 组前端缓存、16 行整行
I-cache、128 行写回数据 L1、Sv39 指令/数据译址、TileLink、UART、DMA 和中断模块。
为避免把 Linux 仿真用的 64 MiB RAM 当作片上存储综合，它使用 16 KiB 可编程 RAM
和 8 KiB 可编程 ROM。这个顶层用来寻找当前逻辑的内部时序瓶颈；它不包含
板级 DDR/AXI4 接口和 I/O 时序约束，也不能运行 Linux 或证明最终板级频率。
当前导出用单写口推断 RAM 消除 Vivado 不支持的多写口存储模式；产品版若替换成
Vivado BRAM/DDR IP，需要在最终连接和时钟约束下重新布局布线，不能沿用此报告的频率。
模块级迭代不必每次跑完整 SoC。把一次导出的 RTL 复制到独立目录，在 Windows
Vivado 中运行如下命令；`PmpChecker` 可换为 `StoreBuffer`、`MachineSystemUnit`
或 `IntegerBackend`，最后一项可选 `synth`（默认筛选）或 `place`（确认局部布局）。

```bat
vivado.bat -mode batch -source vivado-module-ooc.tcl -tclargs . xczu15eg-ffvb1156-2-i 10 PmpChecker synth
```

每个候选使用独立目录，比较 `reports/post_synth_timing.rpt`、
`reports/post_synth_utilization.rpt`；需要时再比较 `post_place_*`。
脚本对模块边界使用零输入/输出延迟，以便同口径比较；这不是外围电路的真实时序预算。
特别是 `IntegerBackend` 内的跨单元路径仍可能受整机布线和拥塞改变，模块结果
不能代替最终一次整机布局。单次 Vivado 的 `general.maxThreads` 已设为 8，
这是 Vivado 2025.1 布局等任务的线程上限；增加机器核心数不会再提高该任务的线程数。

需要准确区分子模块资源时，用仅综合的层次审计脚本：

```bat
vivado.bat -mode batch -source vivado-hierarchy-audit.tcl -tclargs . xczu15eg-ffvb1156-2-i 10 CompactSocTimingTop
```

它使用 `-flatten_hierarchy none`，不运行布局。默认重建层次的资源报告可能把
跨模块优化后的逻辑错误归到某个实例；2026-09-28 旧报告给
`MachineSystemUnit` 记了 52,801 LUT，但当前紧凑 RTL 在保留层次的整机综合中为
**5,163 LUT**，独立模块综合为 **5,039 LUT**。同次保留层次综合的整机为
119,387 LUT，`RenameRob` 为 9,068 LUT，`IntegerBackend` 自身逻辑为
31,051 LUT（不含子模块）；这些是综合值，不是布局后资源。最差综合路径
`ready` → 平台响应队列写使能为 35.628 ns、135 级逻辑。原有布局路径与此
分析口径不同，不能直接作 A/B 时序比较。

把平台响应队列的 `flow` 关掉能建立寄存边界，但紧凑相干 GSIM 中 263 次
物理数据请求使首个 trap 恰好多了 263 周期（1577→1840，IPC 0.428→0.367）。
因此未采用该每次访存增加一周期的方案，继续优化后端组合判断。

IntegerBackend 的旧 store 区间末端和普通 RAM/对齐条件现于 store 准备时寄存，
年轻 load 发射时只做已寄存边界的重叠比较。相同 RTL/器件/10 ns 边界条件下，
单模块综合最差路径 34.043→33.125 ns，逻辑级数 135→127，CARRY8 1700→1590；
代价为 LUT 59062→59227、FF 26714→27771。紧凑相干 GSIM 首陷阱前仍为
675 条/1577 周期，8/32 项后端随机测试和 8 槽整核 NEMU 对照通过。
这是综合估算，尚未确认布局或整机时序改善。

随后仅调整 LSU 完成与取消的同拍握手反馈，不给正常访存固定加拍。
相同 `IntegerBackend` 模块综合口径下，先将 `complete.ready` 与 ROB 完成授权解耦，
最差数据路径 33.125→32.985 ns；再去掉槽位 `cancel` 到 `start.ready` 的组合反馈，
最差路径为 32.710 ns、127 级，LUT 59,207、FF 27,772。关键路径仍从物理寄存器
`ready` 跨发射选择、分支恢复、LSU `start.valid`、StoreBuffer 同拍请求/响应握手，
终点为 StoreBuffer owner 队列写使能。这些局部改动没有建立时序寄存边界，
对 10 ns 目标仍远远不够。8/32 项后端随机、8 槽整核 NEMU 及紧凑相干平台定向 GSIM
通过；后者保持 675 条/1577 周期、IPC 0.428028。尚未针对新 RTL 跑布局或整机 Vivado。

紧凑配置现试用 `registeredBranchRedirect`：预测错误的分支把重定向与完成结果保存在
一个带 token 的寄存器槽中，待下一拍恢复获准才完成；默认后端仍保留同拍外部恢复仲裁。
第一版单模块综合的最差路径为 23.703 ns、90 级，LUT 57,906、FF 28,167；
配合 `recoveryWidth=4` 与第二执行槽的非控制指令放行后，为 21.616 ns、83 级，
LUT 60,258、FF 28,175。相对 32.710 ns 基线有进展，但该第二次 A/B 同时包含
回滚宽度和发射门控变化，不能把 2.087 ns 差异单独归因于回滚宽度。
最新路径从 PRF `ready` 经过 LSU 发射选择、第二槽分支结果和 ROB 同拍提交，
到已提交寄存器映射表使能；WNS -11.720 ns，仍未达到 10 ns。
这些均为零端口延迟的**未布局模块综合估算**，尚无本版整机布局/布线频率结论。

同一裸核载荷、32 ROB/64 PRF/8 LSU 槽的 GSIM 对照中，4 项回滚的新模式
`compiled_c_array_sum` 在内存延迟 1/4/12 拍分别为 1065/1090/1028 周期，
旧同拍分支、1 项回滚为 1199/1228/1219 周期；两组均退休 1310 条。
独立 ALU 等无恢复负载基本不变；紧凑相干平台首陷阱仍为 675 条/1577 周期。
新模式整核 NEMU 282 个程序通过，但本次测试未触发“同次取消多笔乘法”事件，
该微结构覆盖仍需单独补齐。下一处寄存边界应切断共享发射选择至分支完成/ROB
同拍提交的组合链，同时保留双发射能力与精确恢复；不再靠小幅组合整理反复综合。

随后针对双发射、非 fast-store 的紧凑配置把 ALU 最老/次老候选先独立排序，
只在末端分配执行槽。第一步消除 LSU 端口占用对第二槽整棵候选树的反馈，
模块综合最差路径 21.616→18.530 ns、83→73 级，LUT 60,258→60,318。
再令槽 1 固定取最老候选、槽 0 仅在空闲时取次老候选，双重定向按槽 1 优先；
最差路径为 **18.278 ns、72 级**，WNS -8.382 ns，LUT 60,082、FF 28,173。
这两步的 8 槽整核 NEMU 282 程序及紧凑相干平台定向 GSIM 均通过，
`compiled_c_array_sum` 1/4/12 拍延迟仍为 1065/1090/1028 周期，
紧凑平台首陷阱仍为 675 条/1577 周期。最后的最差路径仍从 PRF `ready`
经 LSU 普通 RAM 判定、内存/M 发射占用、分支比较、ROB 当拍提交到架构映射使能。
继续整理组合门控的收益已不足以覆盖到 10 ns 的差距；下一轮应专门建立
LSU 发射决定或分支完成至 ROB 提交的流水寄存边界，并量化周期及 IPC 代价。
本轮只进行模块综合，没有新的布局或整机频率结论。

2026-09-28 的两个寄存边界反证：仅让分支完成延后提交，定向整核 NEMU
282 程序通过、C 数组延迟 1/4/12 拍仅增加 2/2/1 周期，但同口径
`IntegerBackend` 综合最差路径 **18.278→18.955 ns**，终点转到
StoreBuffer owner 队列写使能；此改动已撤回。再把 StoreBuffer 响应归属
队列从同拍透传改为寄存，可通过 282 程序、StoreBuffer 随机测试及
紧凑相干平台（675 条/1577 周期），裸核 C 与 store-load 链周期不变，
但零延迟 StoreBuffer 压力测试 6627→7388 周期；模块最差路径仍为
**18.446 ns**、WNS -8.550 ns、72 级，转到未完成读取计数器。
因此它仅保留为可选实验，紧凑 FPGA 顶层默认关闭。两者均为未布局
模块综合估算，不是整机 100 MHz 的达成证据。

随后把对齐、2 的幂大小的 RAM 窗口判定重构为高位相等与低位最大起始
地址比较，从 LSU 与 StoreBuffer 的 RAM 窗口判定中移去 64 位区间末端加法；
重叠检测仍保留原有区间计算。
其他窗口仍走原通用比较。StoreBuffer 1/2/4/8 槽随机及错误注入、
8 槽整核 NEMU 282 程序、紧凑相干平台定向 GSIM 均通过，后者仍为
675 条/1577 周期。**此最新版尚未重新综合或布局，时序改善未确认。**
若再追 10 ns，应优先给 PRF 就绪/LSU 选址与地址/PMP/发请求之间
建立真正的流水边界，并用定向载荷量化额外访存拍数；仅在响应尾端
寄存不足以切断这条约 18 ns 的跨模块组合链。

随后紧凑配置加入可选的 `registeredMemoryAddress`：用独立地址准备级
先寄存访存 token、地址和写数据，下一拍重验 ROB 存活后再做 PMP、
乱序检查及 LSU 发射；已发射候选从下一拍准备选择中排除，可连续
准备不同访存。与此前 18.278 ns 参考相比，当前 RAM 窗口重构加
地址准备级的 `IntegerBackend` 模块综合最差路径为 **14.729 ns**，
53 级、60,073 LUT、28,392 FF；由于参考 RTL 尚未单独综合新的窗口
比较，不能把 3.549 ns 差值全归因于地址级。再同时寄存 StoreBuffer
响应归属，最差路径为 **14.323 ns**、53 级、60,216 LUT、28,392 FF，
WNS -4.427 ns。最新最差路径从后端待执行项经分支目标/错预测判断
到 ROB 同拍架构映射提交，地址/响应通路已不再居首。

两级组合已通过 8 槽整核 NEMU 282 程序及紧凑相干平台定向 GSIM。
但首陷阱前 675 条指令从 1577 增至 1708 周期，IPC 0.428028→0.395199；
裸核 store-load 依赖链 1026→1282 周期，C 数组在 1/4/12 拍 RAM
延迟下由 1065/1090/1028 增至约 1135/1155/1172 周期。
因此它是换 Fmax 的方案，不是 IPC 优化；只有布局布线后确认频率
收益超过 IPC 损失，才能声称实际每秒吞吐提升。10 ns 仍未达到，
且上述均是**未布局模块综合**，不代表整机或板级频率。

针对新最差路径又验证了可选的分支完成后延一拍退休：NEMU 282 程序通过，
紧凑平台首陷阱仍为 675 条/1708 周期，C 数组在组合方案上只多约 3 拍。
这一额外边界不进入默认 `make fpga-compact-soc-rtl`；
需要独立导出时使用
`mill -i IonSoC.test.runMain ooo.CurrentSocTimingMain OUTPUT compact registered-retirement`。

同日按相同器件、10 ns 约束和未布局 `IntegerBackend` 模块综合口径，
上述分支延后退休候选最差数据路径为 **14.328 ns**、WNS -4.346 ns、
51 级，LUT 58,285、FF 28,387。相对默认组合的 14.323 ns 没有实际
数据路径收益，瓶颈移至 `orderCheckBeat` 经 load replay/ROB 恢复授权、
LSU 发请求、StoreBuffer 同拍本地响应到 LSU 结果寄存器。另仅启用已有的
StoreBuffer 本地响应寄存候选，紧凑相干平台定向 GSIM 仍通过
（675 条/1708 周期，IPC 0.395199），但模块最差路径反而为
**15.732 ns**、WNS -5.836 ns、56 级，LUT 60,030、FF 28,390；
路径转向同一恢复/发请求链末端的 StoreBuffer 未完成读取计数器。
因此两个候选均保持非默认，不能只靠响应或退休末端寄存来满足 10 ns。
下一处应在恢复仲裁与 LSU 发射之间减少同拍反馈，并严格保持 replay、
异常和外部恢复时不发出错误路径访存；改动前须先定义保守取消/阻塞条件，
用定向 GSIM 验证，再做一次模块综合。上述两次均未布局，更无整机频率结论。

可选的 `earlyRecoveryIssueBlock` 进一步让 LSU 发射只依赖原始 replay、
分支/系统重定向及异常恢复请求的保守阻塞，而不等待 ROB 恢复授权绕回；
真正的恢复和取消仍按 ROB 令牌检查。8 槽裸核 NEMU 282 程序、紧凑相干
平台定向 GSIM 通过。C 数组、独立 load 和 store-load 链在 1/4/12 拍
内存延迟下与未启用时周期数完全相同；紧凑平台仍为 675 条/1708 周期。
同口径 `IntegerBackend` 模块综合最差数据路径 **14.323→13.777 ns**，
WNS -4.427→-3.881 ns，51 级，LUT 60,216→61,798、FF 28,392→28,391。
当前最差路径改由 PRF 就绪经分支目标/错预测判断到 ROB 同拍提交。
按 `10 ns - WNS` 估算周期，且仅对相同测试的 IPC 计算，频率×IPC
代理指标约提升 **3.9%**；相对早前 18.278 ns、IPC 0.428028 参考，
组合候选约提升 22%，但前后 RTL 还包含 RAM 窗口等变化，不能把全数
归因于此门控。所有这些仍是未布局模块估算，不是整机或板级 Fmax；
额外 LUT 与拥塞可能抵消收益，故该开关暂不进入默认紧凑 RTL。
可用 `mill -i IonSoC.test.runMain ooo.CurrentSocTimingMain OUTPUT compact early-recovery-issue-block`
单独导出候选，报告见 `E:\VM\Share\Valence-rtl\backend-early-recovery-20260928\reports`。

2026-09-29 将上述早期恢复阻塞与分支延后退休**组合**后，紧凑相干
GSIM 首陷阱仍为 675 条/1708 周期；8 槽裸核 NEMU 282 程序通过，
C 数组在 1/4/12 拍内存延迟下各多 3 拍（1138/1158/1175），
独立读取和 store-load 链不变。同口径未布局 `IntegerBackend` 综合的
最差数据路径 **13.777→13.176 ns**、WNS -3.881→-3.280 ns，
LUT 61,798→60,610、FF 28,391→28,388。最差路径仍从调度项/PRF
经过分支目标加法、预测比较、ROB 同拍提交至 committed 映射使能。
对**同一紧凑相干载荷**，以 `10 ns - WNS` 作周期代理，频率×IPC
相对只开早期阻塞约 **+4.5%**，相对当前默认紧凑 RTL 约 **+8.6%**。
这不是布局后 Fmax；裸核 C 载荷与紧凑 RTL 的配置不同，不能将其
IPC 与该时序报告直接相乘作为实测吞吐。组合候选可用
`mill -i IonSoC.test.runMain ooo.CurrentSocTimingMain OUTPUT compact early-recovery-issue-block registered-retirement`
导出，报告在 `E:\VM\Share\Valence-rtl\backend-early-recovery-retirement-20260929\reports`。
进一步尝试把同拍退休事件与完成授权分离，GSIM/NEMU 仍通过但最差路径
回升至 **14.129 ns**、WNS -4.233 ns，故已撤回，保留 13.176 ns
组合逻辑。尚未运行整片布局布线，也未满足 10 ns。

随后试过把所有分支（包括预测正确的分支）统一送入单个寄存完成槽，企图
截断分支目标到 ROB 提交的路径。该候选在不含分支的 512 条独立 ADDI
双发射基准中也退化为隔拍单发射；直接去掉单槽互斥又触发了两条分支
同拍捕获的硬件断言。因此此实验已撤回，没有运行 Vivado，也不能把
13.176 ns 报告当成该实验的时序结果。下一轮若继续拆此路径，应先
明确两个完成槽的分支归属及同拍双分支规则，并保持纯 ALU 双发射断言；
只有 NEMU/GSIM 和紧凑平台功能、IPC 均过关后再做一次模块综合。

随后更窄的可选 `precompleteMispredictedBranch` 仅让**预测错误**的分支
在执行当拍写 ROB，重定向仍由原寄存槽下一拍处理；寄存槽非空时暂停
退休，避免该分支先于重定向变为架构状态。8 槽裸核 NEMU 282 程序、
独立 ADDI 双发射断言和紧凑相干平台均通过；紧凑平台首陷阱仍为
675 条/1708 周期、IPC 0.395199。裸核 C 数组在 RAM 延迟 1/4/12 拍时
由 1138/1158/1175 变为 1136/1157/1174 周期，分支环保持 523 周期。
同器件、10 ns、零端口延迟的 `IntegerBackend` **未布局模块综合**
数据路径 **13.176→12.318 ns**，WNS **-3.280→-2.336 ns**，
逻辑级数 48→43，LUT 60,610→60,265，FF 28,388→28,128。
在相同紧凑平台 IPC 下，用 `10 ns - WNS` 作周期代理，频率×IPC
相对前一组合约 **+7.7%**。新最差路径从调度项 token 经 LSU 发请求、
StoreBuffer 同拍本地响应到 LSU 结果寄存器，仍差 2.336 ns；
报告在 `E:\VM\Share\Valence-rtl\backend-precomplete-branch-20260929\reports`。
可用 `CurrentSocTimingMain OUTPUT compact early-recovery-issue-block registered-retirement precomplete-mispredicted-branch`
单独导出，默认紧凑配置不变。尚未布局或整机验证，不能声称已达 100 MHz。

`indexOnlyMemoryStage` 反例：仅用调度项索引选择寄存的内存地址、删除
同拍 64 位 token 比较，在 GSIM 断言下裸核 282 个 NEMU 程序和紧凑
相干平台均通过，平台 IPC 仍为 0.395199。相同器件和 10 ns 约束下的
一次未布局 `IntegerBackend` 模块综合，LUT 60,265→59,567、FF
28,128→28,053，但数据路径 **12.318→13.119 ns**、WNS
**-2.336→-3.223 ns**，级数 43→48。相同 IPC 的频率×IPC 代理
反而约 **-6.7%**，关键路径转为 `orderCheckLanes` 经 load replay/ROB
提交到 `ledger/committed` 的使能。因此此实验开关已撤回，不作为当前
推荐配置；反例报告保留在
`E:\VM\Share\Valence-rtl\backend-index-only-memory-20260929\reports`。

后续仅去掉无效 `memoryChoice` 对 `memorySize` 的置零门控，保留完整
token 比较：访存 size 在 `lsu.io.start.fire` 前不更新状态，避免让
token 有效性继续穿过 RAM 范围判断。8 槽整核 NEMU 282 程序及
双发射检查通过；非寄存访存选择的整核 282 程序也通过；紧凑相干
平台仍为 675 条/1708 周期，IPC 0.395199。
同器件、10 ns、零端口延迟的未布局模块综合显示 LUT
60,265→59,677、FF 28,128→28,124，但最慢数据路径
**12.318→13.158 ns**、WNS **-2.336→-3.262 ns**，级数
43→48；新关键路径从 `orderCheckBeat` 经 load replay 和 ROB 恢复
到已提交映射表使能。按 `10 ns - WNS` 与相同 IPC 计算，
频率×IPC 代理约 **-7.0%**，
因此此微调已撤回。反例报告保留在
`E:\VM\Share\Valence-rtl\backend-memory-size-20260929\reports`。

逐槽寄存 load replay 的 beat/lane 重叠位（替换 61 位 beat + 8 位 lane
寄存器）也在 8 槽整核 NEMU 282 程序、DMA replay 和紧凑相干平台
通过，后者仍是 675 条/1708 周期、IPC 0.395199。一次同口径未布局
模块综合使 replay 比较离开最差路径，但路径回到
`stagedMemoryIndex`→LSU 发射→StoreBuffer 同拍响应→LSU 结果寄存器；
最慢数据路径 **12.318→12.710 ns**，WNS **-2.336→-2.728 ns**，
LUT **60,265→60,651**、FF **28,128→28,062**。相同 IPC 的
频率×IPC 代理约 **-3.1%**，因此也已撤回。反例报告保留在
`E:\VM\Share\Valence-rtl\backend-registered-load-overlap-20260929\reports`。
两条瓶颈会互相接替；不能只看某一条路径被切断就判断全局改进。
下一轮应把 LSU 同拍响应链与 replay/ROB 恢复链作为一组流水边界
处理，并量化相同载荷的 IPC。仅按当前未布局模块的 `10 ns - WNS`
周期代理 12.336 ns 计算，若真把周期压到 10 ns，新方案 IPC
高于约 **0.3204** 才比当前 0.395199 IPC 的吞吐代理更好；这是
设计筛选阈值，不是整机或板级频率承诺。

两项局部改动同时启用的组合候选也已实测：8 槽整核 NEMU 282 程序、
DMA replay、双发射检查和紧凑相干平台均通过，平台仍为
675 条/1708 周期、IPC 0.395199。相同器件、10 ns 和零端口延迟的
未布局 `IntegerBackend` 综合，LUT 60,265→59,473、FF
28,128→28,073，但最慢路径 **12.318→13.183 ns**、WNS
**-2.336→-3.287 ns**，逻辑级数 43→49。新路径从 `memoryLive`
经 replay/恢复仲裁到 `ledger/committed` 使能；相同 IPC 下
频率×IPC 代理约 **-7.2%**。组合候选亦已撤回，报告保留在
`E:\VM\Share\Valence-rtl\backend-memory-size-overlap-combined-20260929\reports`。
下一步不能再仅移动 overlap 比较器：要将 replay 决定与 ROB 提交
之间建立真正的寄存边界，并确保等待判定的年轻 load 不会提前退休；
同时须缩短 LSU 同拍响应路径，量化新增停顿是否仍满足上述 IPC 阈值。

真正寄存 replay 决定并在检查周期暂停退休、同时寄存 StoreBuffer 本地
应答的可选实验已通过 8 槽整核 NEMU 282 程序、DMA replay 和紧凑
相干平台。平台首陷阱仍为 675 条/1708 周期、IPC 0.395199，
但裸核 C 数组在 12 拍内存延迟下 1174→1403 周期。相同未布局
`IntegerBackend` 综合最慢路径为 **12.720 ns**、WNS **-2.824 ns**，
LUT 59,265、FF 28,256；关键路径转到 token 经访存发射与
StoreBuffer 握手至 `stores/reads` 计数器使能。此配置不优于
12.318 ns 基线，不推荐采用；报告在
`E:\VM\Share\Valence-rtl\backend-registered-replay-local-20260929\reports`。

再于 LSU 与 StoreBuffer 之间增加 2 项非透传、保持响应顺序的请求队列，
整核 282 个 NEMU 程序和紧凑平台仍通过。平台首陷阱为
675 条/1972 周期，IPC **0.342292**；裸核 C 数组 12 拍延迟下
增加到 **1598 周期**。未布局模块最慢路径仍有 **12.490 ns**、
WNS **-2.508 ns**，LUT 60,035、FF 28,260；瓶颈转到 PRF
`ready_39` 经 ALU/完成仲裁写 `ledger/entries_0_data`。按
`10 ns - WNS` 与平台 IPC 估算，频率×IPC 比 12.318 ns 基线
约 **-14.6%**，且 C 数组退化更大；既没有达到 10 ns，
也不适合作为推荐配置。报告在
`E:\VM\Share\Valence-rtl\backend-registered-replay-requests-20260929\reports`。
这两个模式均默认关闭，仅保留实验入口以便后续 A/B；下一处需
切短 ALU 完成→ROB 数据写入，同时避免再次给常见依赖链固定加拍。

2026-09-29 对上述 12.318 ns 最佳候选的**字节一致 RTL**又做了一次
`IntegerBackend` OOC 模块布局（未布线、零端口延迟）。布局后 WNS
**-3.269 ns**、最慢数据路径 **13.251 ns**，起点是
`stagedMemoryIndex`，终点是 `stagedMemoryAddress`；路径穿过访存选择、
65 位访问末端及旧 store 重叠检查，54 级逻辑中估算连线延迟
**9.635 ns（72.7%）**。前 20 条路径还包括 StoreBuffer owner 出队、
ROB 数据写入和 PRF 写回，余量接近。模块布局比未布局综合的
WNS -2.336 ns 更差，不能把 12.318 ns 当成实际周期；本次布局也没有
时钟源 `HD.CLK_SRC`、整机边界或最终布线，不能推断板级 Fmax。
报告在 `E:\VM\Share\Valence-rtl\backend-precomplete-branch-place-20260929\reports`。

随后以已寄存、对齐且在 RAM 内的旧 store 为前提，将 load/store
区间不交叠检查改为 8 字节 beat 地址与字节掩码比较；未对齐 load
保守阻塞。Scala 测试、裸核 NEMU 282 程序、DMA replay 和紧凑相干
平台均通过；C 数组 1/4/12 拍仍为 1136/1157/1174 周期，平台仍为
675 条/1708 周期、IPC 0.395199。相同 OOC **未布局综合**下 LUT
60,265→59,451、FF 28,128→27,211，但最慢路径
**12.318→13.898 ns**、WNS **-2.336→-3.916 ns**，转到 PRF `ready`
至 ROB `entries_0_data`；以相同平台 IPC 估算频率×IPC 约下降 11%。
因此已撤回这项变换，仅保留反例报告在
`E:\VM\Share\Valence-rtl\backend-beat-lanes-20260929\reports`。
两份时序的阶段不同，不能把新候选的未布局 13.898 ns 与旧候选的
布局后 13.251 ns 直接作 A/B。后续优化应同时考虑访存准备与
PRF→ROB 完成路径，先做功能/IPC 筛选，再按相同阶段比较时序。

沿布局后 `stagedMemoryIndex`→`stagedMemoryAddress` 路径又试了消除
`memoryIssued` 对下一候选排序的同拍反馈：预选其他访存，未发射时
保留准备槽。初版在年轻 load 等待旧 store 时死锁；修正版允许
更老的候选抢占，裸核 NEMU 282 程序、DMA replay、双发射及紧凑
相干平台通过。C 数组 1/4/12 拍为 1136/1157/1174 周期，平台
仍为 675 条/1708 周期、IPC 0.395199。但同口径**未布局综合**
最慢路径 **12.318→13.003 ns**、WNS **-2.336→-3.021 ns**，
LUT 60,265→59,228、FF 28,128→28,124；路径转到 PRF `ready`
经 ALU/bit-manip 到 ROB `entries_0_data`。频率×IPC 代理约下降
**5.3%**。报告在
`E:\VM\Share\Valence-rtl\backend-preselect-hold-20260929\reports`。
再将 bit-manip 结果从多路选择改为并行一热，RV64B 随机和整核
NEMU 仍通过，但与上述访存方案合用时最慢路径 **13.018 ns**、
WNS **-3.036 ns**，LUT 58,998；没有时序收益。组合报告在
`E:\VM\Share\Valence-rtl\backend-preselect-onehot-20260929\reports`。
两项实验均已撤回，当前最佳 RTL 不变。此轮没有再对实验版做布局；
要靠近 10 ns，应给 ALU 完成/ROB 数据写入建立真实寄存边界，
同时维护双发射、恢复、旁路及完成端口容量，实测依赖链 IPC。
只以本次模块布局 `10 ns - WNS = 13.269 ns` 与紧凑平台
IPC 0.395199 作筛选代理，未来若真达到 10 ns，新方案在同一
载荷下 IPC 需高于约 **0.298** 才提高频率×IPC；实际整机/板级
频率与 IPC 仍须集成验证，不能把该阈值当作签核标准。

访存发射反馈与 ROB 边界实验（均已撤回）：先移除 `memoryIssued` 对
下一访存预选的同拍过滤，虽然预期可切掉已布局的
`stagedMemoryIndex`→`stagedMemoryAddress` 长链，但 GSIM 的独立加载
并发覆盖失败，C 数组 1 拍 RAM 从 1136 增至 1324 周期；未跑 Vivado。
再仅在自然对齐、2 的幂 RAM 窗口中，把旧 store/新 load 的区间不相交
比较缩到窗口内偏移，其他窗口保留 65 位原逻辑。核心 NEMU 282 程序、
RAM overlap 与紧凑相干平台通过；C 数组 1/4/12 拍仍为
1136/1157/1174 周期，平台 IPC 仍为 0.395199。但同口径未布局
模块综合最慢路径 **12.318→13.534 ns**、WNS **-2.336→-3.638 ns**，
转为 `ready` 经 ALU/分支异常到 ROB committed 使能；报告在
`E:\VM\Share\Valence-rtl\backend-window-offset-20260929\reports`。
随后让寄存退休模式的所有完成结果统一下一拍退休，核心功能仍过，
但 C 数组变为 1268/1288/1306 周期，紧凑平台首陷阱 IPC
**0.395199→0.341426**。组合候选综合最慢 **13.712 ns**、WNS
**-3.730 ns**，路径转为 issue 源寄存器到 ROB 数据寄存器；同阶段
频率×IPC 代理相对最佳配置约 **-22%**，未达到弥补 IPC 损失所需的
约 10.64 ns。报告在
`E:\VM\Share\Valence-rtl\backend-window-offset-deferred-retire-20260929\reports`。
两项实现均已撤回，未做布局。证据表明单独缩短访存检查或推迟提交
只会暴露 execution→ROB 数据写入；后续需在 issue/执行/完成之间
建立真实寄存边界，同时测量依赖链和访存 IPC。

双 B 执行槽实验（已撤回）：为缩短组合 ALU 的 RV64B 路径，把两个
bit-manip 结果各寄存一拍，并由寄存结果旁路唤醒后继指令。裸核
NEMU 282 程序、RV64B 随机及双发射检查通过；最初的独立 B 指令
2049 条/1027 周期，紧凑相干平台 675 条/1708 周期。然而相同
`IntegerBackend` 未布局模块综合最慢路径从当前最佳 **12.318 ns**
恶化为 **13.739 ns**，B 结果 token 经动态旁路、分支判断到 ROB
提交。仅让 B 延后一拍退休后为 **14.281 ns**；该实验配置中让
所有完成都延后一拍退休，独立 RORI 变为 2049 条/1028 周期，
最慢路径仍为 **14.585 ns**，这次经旁路、分支选择到 `pending`。
三次均未布局；最后一次 WNS **-4.605 ns**、57 级逻辑、估算连线
占路径 77.0%。可见只寄存执行结果而保留同拍动态 token 查表、
旁路唤醒和 issue 反馈，不能构成真正的短流水级。实验实现和命令
开关已撤回，报告分别保留在 `backend-pipelined-b-20260929`、
`backend-pipelined-b-retire-20260929`、
`backend-pipelined-b-registered-retire-20260929` 目录。下一轮若拆
流水线，应先定义局部唤醒/选择的寄存边界和依赖链 IPC 预算，
而非仅在 ALU 输出加寄存器。

PMP 一热优先匹配实验：同一 xczu15eg-ffvb1156-2-i、10 ns、零边界延迟下，
模块布局最慢路径 3.828→3.047 ns，LUT 2317→2295；独立 GSIM 16 项定向、
6000 项随机及错误注入通过，PMP 取指和紧凑相干数据平台定向测试也通过。
这不是整机 WNS 或最终板级频率的改进量；该轮未重跑整机 Vivado。

StoreBuffer 并行物理槽地址匹配：同一约束下单模块布局最慢路径 4.060→3.635 ns，
LUT 503→448、FF 373→372。1/2/4/8 槽随机 GSIM、可选寄存应答和紧凑相干
数据平台均通过；同样不能据此推算整机时序。

2026-09-29 ALU 完成寄存级实验（已撤回）：先试 ROB 静态物理槽写入，
Scala 测试、裸核 NEMU 282 程序与独立 ROB GSIM 均通过，但相同
`IntegerBackend` 未布局综合最慢路径 12.318→13.112 ns，WNS -3.216 ns，
转为内存排序检查到 ROB 提交使能；报告在
`E:\VM\Share\Valence-rtl\backend-static-rob-write-20260929\reports`。
再尝试两条 ALU 完成通道各加一项寄存级，使用已寄存物理目的寄存器
直接旁路，并在端口占用时反压 issue。裸核 NEMU 282 程序、
RV64B 随机、回滚/DMA 与紧凑相干平台通过；独立 ALU 4096 条
2049→2050 周期，依赖 ALU 4097→4098 周期，C 数组 RAM 延迟
1/4/12 拍分别由 1136/1157/1174 变为 1199/1198/1218 周期。
平台首陷阱仍退役 675 条，周期 1708→1840，IPC
0.395199→0.366848。相同 OOC 未布局综合最慢路径
**12.318→13.300 ns**，WNS **-2.336→-3.318 ns**，
LUT 60,265→59,432，FF 28,128→28,672。新最慢路径从 issue
队列 token，经访存选择、LSU 请求、StoreBuffer 同拍本地应答，
到 LSU result_data 寄存器，47 级逻辑、估算连线占 77.9%。
按 `10 ns - WNS` 估计，频率×IPC 同阶段代理约为基线的 0.86 倍，
既不满足 10 ns，
也不能抵消 IPC 下降；未做布局，实验开关与实现已撤回。
报告保留在
`E:\VM\Share\Valence-rtl\backend-registered-alu-20260929\reports`。
这说明单独寄存 ALU 完成会暴露 LSU 同拍请求→应答链；
下一轮应优先按该链的独立模块契约切分，并对同一平台测吞吐，
不能以 ALU 路径被遮蔽就推断整核时序改善。

2026-09-29 LSU 请求/应答切分实验（均已撤回）：首先仅将 StoreBuffer
转发的 load 应答寄存一拍，保留缓冲写同拍确认；独立 StoreBuffer
多种随机种子、零延迟/延迟下游、背压与顺序 oracle 均通过。
裸核 NEMU 282 程序及紧凑相干平台通过，平台首陷阱仍为
675 条/1708 周期，IPC 0.395199；C 数组 1/4/12 拍 RAM 为
1136/1158/1175 周期，store-load 链仍为 1282 周期。但同口径
`IntegerBackend` 未布局综合最慢路径 **12.844 ns**、WNS **-2.948 ns**，
瓶颈从 LSU 结果数据转至 StoreBuffer `reads` 计数器使能。
报告在 `E:\VM\Share\Valence-rtl\backend-registered-forward-20260929\reports`。

继而利用并行 LSU 已有的响应 owner 队列，把每个 slot 的
`response.ready` 改为 owner 保护下常态 ready，移除 request.ready
绕回 response.ready 的一段组合反馈。与上述转发寄存组合时，
裸核 NEMU/平台功能与平台 IPC 不变；未布局综合为 **12.306 ns**、
WNS **-2.324 ns**，LUT 60,147、FF 28,124。比基线
12.318 ns 仅少 **0.012 ns**，尚未布局且不足以支持 10 ns 目标；
最慢路径仍从调度 token 穿过同拍请求、owner 透传与应答有效，
到 LSU 结果数据寄存器。报告在
`E:\VM\Share\Valence-rtl\backend-forward-owner-ready-20260929\reports`。

最后使 LSU owner 队列非透传，真正切断同拍请求→应答归属链；
保持 owner 容量和每拍请求能力，但零延迟应答最早下一拍接收。
裸核 NEMU 282 程序和紧凑相干平台通过，平台首陷阱仍为
675 条/1708 周期。可是 C 数组 1/4/12 拍变为
1265/1286/1303 周期，store-load 链 **1282→1538** 周期；
同口径未布局综合最慢 **12.663 ns**、WNS **-2.767 ns**，
LUT 60,084、FF 28,125，瓶颈转至 `orderCheckBeat` 经排序检查
到 ROB committed 使能。对 store-load 负载按 `10 ns - WNS`
估算，频率×IPC 仅约为基线的 **0.81 倍**。报告在
`E:\VM\Share\Valence-rtl\backend-registered-lsu-owners-20260929\reports`。
三组都未布局；实验开关与逻辑已撤回，保留此前最佳 RTL。
仅在应答末端加寄存器无法解决访存选择、排序/恢复及 ROB 提交
彼此轮流成为关键路径的问题；下一轮应考虑更靠前的访存调度边界，
并将常见 store-load 依赖链作为硬性吞吐门槛。

2026-09-29 模块优化台账（xczu15eg-ffvb1156-2-i，10 ns）：

| 模块 | 状态/改动 | 最差数据路径，ns | LUT | FF | 验证/结论 |
| --- | --- | ---: | ---: | ---: | --- |
| PmpChecker | 已保留：一热优先匹配 | 布局 3.828→3.047 | 2317→2295 | — | 独立随机/错误注入、取指与数据平台 GSIM 通过；路径缩短 0.781 ns、LUT 减 22。 |
| StoreBuffer | 已保留：并行物理槽匹配 | 布局 4.060→3.635 | 503→448 | 373→372 | 随机/背压 GSIM 通过；路径缩短 0.425 ns、LUT 减 55。 |
| InstructionLineCache | 仅测基线，未改 | 综合 4.956 | 5740 | 3387 | WNS +4.968 ns；最差路径为取指地址经 PMP、回退端口 ready 到状态使能。 |
| CoherentLineCache | 已保留：对齐 2 的幂缓存窗口用高位匹配和低位边界比较替代 65 位末端加法 | 综合 3.253→3.043 | 4674→4637 | 5478→5478 | WNS +6.411→+6.593 ns，8 BRAM 不变；路径缩短 0.210 ns、LUT 减 37。紧凑相干 VM 数据 GSIM 通过，675 条/1708 周期，IPC 0.395199。 |
| InstructionTranslationAdapter | 仅测基线，未改 | 综合 3.605 | 4680 | 336 | WNS +6.405 ns；最差路径从翻译应答物理地址经 PMP 到允许位寄存器。 |
| SvTranslationService | 仅测基线，未改 | 综合 3.998 | 3090 | 1821 | WNS +5.984 ns；最差路径在页表遍历器状态机。 |
| DataTranslationAdapter | 已保留：复用对齐 RAM 窗口比较器，移除独立 65 位末端加法 | 综合 4.430→4.450 | 2652→2617 | 98→98 | LUT 减 35（1.3%）；路径差 +0.020 ns，不计作提频。紧凑相干 VM 数据 GSIM（含虚拟 AMO）通过：675 条/1708 周期，IPC 0.395199。 |

表中前两项是**布局后**模块对比，其余是**未布局综合**；不能跨阶段
比较，也不能据此宣称整机达到 100 MHz。未改的三个模块在当前
模块约束下已满足 setup 10 ns，暂不为了局部数字改动其握手或增加
流水级。未布局报告使用零输入/输出延迟且缺少板级时钟源约束；
保持和基线相同条件只用于 A/B 排序。模块基线
报告分别在 `E:\VM\Share\Valence-rtl\icache-module-baseline-20260929\reports-icache`、
`reports-coherent`、`reports-itranslation`、`reports-svtranslation`、
`reports-dtranslation`；数据翻译改后报告在
`E:\VM\Share\Valence-rtl\dtranslation-range-20260929\reports`，
相干缓存改后报告在
`E:\VM\Share\Valence-rtl\coherent-range-20260929\reports`。
以上检查仅用了单模块综合和一项定向 GSIM，未跑整机 Vivado/全量 GSIM。

2026-09-29 超标模块筛选与后端继续优化（相同器件/10 ns、零边界延迟）：

| 模块/候选 | 阶段 | 最差数据路径 | WNS | LUT / FF | 决定 |
| --- | --- | ---: | ---: | ---: | --- |
| RenameRob | 独立综合 | 6.027 ns | +3.955 ns | 10,762 / 7,554 | 模块内部达标；最差路径为 ROB tag 到 RAT。 |
| LoadStoreUnit | 独立综合 | 2.442 ns | +7.523 ns | 979 / 346 | 模块内部达标。 |
| IntegerAlu | 独立综合 | 3.328 ns | +6.647 ns | 2,590 / — | 纯组合模块内部达标。 |
| IntegerBackend 原基线 | 独立综合 | 12.318 ns | -2.336 ns | 60,265 / 28,128 | 仍超标；跨发射、LSU、StoreBuffer 的同拍链。 |
| 访存发射反馈移至预选末端 | 独立综合 | 12.605 ns | -2.623 ns | 60,256 / 28,112 | 恶化 0.287 ns，已撤回；新最慢路径从 `stagedMemoryIndex` 到 LSU 结果。 |
| StoreBuffer 本地应答数据选择不依赖 `request.fire` | 独立综合 | **12.168 ns** | **-2.272 ns** | 60,247 / 28,128 | 暂保留；比原基线数据路径短 0.150 ns，LUT 减 18，未达 10 ns。 |

独立模块达标而集成模块超标，说明应优化跨模块握手/结果捕获边界，
不能把 LSU 单模块 2.442 ns 与 ROB 单模块 6.027 ns 简单相加预测整机。
本地应答数据选择改动只影响 `response.bits.data` 在无效周期的 don't-care
值，不改 `valid`、`ready`、响应周期或有应答时的数据。StoreBuffer 的
1/2/4/8 槽定向随机、零延迟/背压及错误注入 GSIM 通过；紧凑相干 VM
数据平台通过，首陷阱仍为 675 条/1708 周期，IPC 0.395199。
新最差路径转为 `orderCheckBeat` 经 load replay/恢复到 ROB committed
映射使能；这是下一轮超标优化的具体目标。当前正向差值仅为**未布局综合**
筛选结果，尚无布局后或整机频率改进结论，不据此重跑整机 Vivado。
三份模块筛选报告在
`E:\VM\Share\Valence-rtl\coherent-range-20260929\reports-rob`、
`reports-lsu`、`reports-alu`；两个后端候选分别在
`E:\VM\Share\Valence-rtl\backend-late-issued-mux-20260929\reports` 和
`E:\VM\Share\Valence-rtl\backend-local-data-select-20260929\reports`。

## 2026-09-30：DDR50 整机布线与增量物理优化

独立 DDR50 候选在原板级引脚 XDC 上完成整机测试。第一次路由发现 AXI
Clock Converter 的 AWREGION/ARREGION 共 8 位悬空；已修正顶层源码，并在
保留检查点中等价接零、增量布线。修复后的路由 WNS -0.597 ns，经过一次
post-route Explore 后 WNS **+0.001 ns**、WHS **+0.008 ns**，setup/hold
失败端点均为 0；全部可路由网完成，路由错误为 0。MIG UI 250 MHz 的 WNS
为 +0.307 ns。未新增 CPU 流水级，不引入流水延迟型 IPC 代价。

这只说明**本次保留检查点**在现有约束下满足 CPU 50 MHz；setup 仅 1 ps
裕量，不代表重跑仍会收敛、更高频率可用或 DDR 已通过板上校准。
新关键路径为后端 token tag 到 predictor counter；翻译/PMP 到 LSU 的
路径也仅剩 +0.005 ns。LUT 132,002、FF 78,124，未使用 URAM。
本轮同时将 DDR ROM 下载上限扩为 512 MiB 减 16 KiB，监控工作区移至
0xA01FC000。10 项主机测试、DDR 和原 URAM 定向 GSIM 均通过，未跑全量。

未生成 bit。原候选工程 impl_1 保留首次路由失败状态，修复/收敛结果在
src/board-ddr50/timing50-repair/optimized_routed.dcp，不要把原失败运行当成
最终产物。完整路径、阶段对比、约束覆盖及剩余警告见
[PL DDR4 整机记录](../fpga/zu15eg/pl-ddr4-integration.md#2026-09-30-full-implementation-and-timing-result)。

## 2026-09-30：无提示符 Bootrom V0.1 的 DDR50 bit 已生成

本轮只更新 ROM 固件，不重做 CPU 综合/布局布线。独立综合新 ROM IP 后，
核对新旧原语、非存储参数和连线完全一致，再在已闭合的 DCP 中更新 82 个 INIT 参数，
逐项读回核对全部 29 个 BRAM 的初始化值。沿用原工程 XDC 所对应的实现结果。

更新后重新检查：50 MHz（20 ns），WNS +0.001 ns、WHS +0.008 ns、WPWS +0.081 ns；
TNS/THS/TPWS 均为 0，161529 条可布线网络全部完成、无布线错误，14 项 bus skew 全通过。
Bitstream DRC 无错误和严重警告，仍有 63 条普通警告。1 ps 建立裕量仅表示本次刚好达标。

2026-09-30 22:13（Asia/Shanghai）生成：
`D:/TOOLS/projects/vivadoProjects/ZU15EG/src/board-ddr50/bootrom-v01-noprompt/release/valence_ddr50_bootrom_v01.bit`。
同目录有新 routed DCP、LTX 和完整检查报告。没有执行上板烧录；MIG/DDR 实测尚待完成。

ROM 3061 字节，启动打印 `Valence Bootrom V0.1`、`download mode (UART)`，不再打印 `>`。
须使用已更新的下载脚本（等待 `ready to boot`），波特率仍为 1500000。
12 项脚本测试及必要 DDR GSIM 引导回归通过（6339996 cycles），未跑全量回归。
旧 `timing50-repair/optimized_routed.dcp` 不变，不能当成新固件的检查点使用。

## 2026-09-30：DDR50 敏感路径组合逻辑优化

### 已布线基线定位

在 V0.1 BootROM release 的 `timing_paths.rpt` 中：

- 最差 setup 路径由后端 queue token，经 LSU 的 `accessEnd` 范围运算、恢复/完成/提交，
  到分支预测器计数器：19.848 ns、56 级、WNS +0.001 ns，布线占 76.36%。
- 第二类路径由译址请求队列，经 PMP、外设路由、缓存/总线请求及返回到 LSU：
  19.871 ns、66 级、WNS +0.005 ns，布线占 72.80%。
- 这说明应优化跨模块组合链，不是简单缩短 UART 波特率计数器。
  但正 slack 不是物理故障证据，串口线缆/收发协议/软件服务速度/DDR 仍需独立排查。

### 本轮改动（没有新增流水级）

1. `SpeculativeRamRange` 按窗口两端的共同对齐拆分比较。
   DDR `[0x80200000, 0xa0200000)` 大小为 512 MiB，却只按 2 MiB 对齐；
   以前只优化自然对齐的二次幂窗口，因此 DDR 仍退回宽位末地址加法。
   新算法用块编号比较，只有最后一块检查剩余字节；未对齐配置保留溢出安全的通用算法。
   LSU 原子边界检查也改为复用它。窗口、MMIO、原子权限不变。
2. PMP 将 `(1 << size) - 1` 预译码为 7 位偏移，再做一次 65 位末地址加法，
   避免生成 72 位动态移位/加减链。保留 XLEN 溢出、首重叠项优先、权限和部分覆盖异常。
3. StoreBuffer 不再用较晚到达的 `request.valid` 选择 size；
   payload 预译码，握手与副作用仍由 valid/fire 授权。
   目的是去掉重放/恢复 valid 到 RAM 判定再返回 ready 的额外组合依赖。

### 同口径模块对照

Vivado 2025.1，`xczu15eg-ffvb1156-2-i`，20 ns，零边界延迟，
`fpga/vivado-module-ooc.tcl`，**综合后、未布局**。
baseline 是本轮修改前导出的 DDR50 源码；不冒充已发布 routed DCP 的复现。
下面的延迟不能直接取倒数当整机 Fmax。

| 模块/阶段 | 最差数据延迟 ns（前→后） | LUT（前→后） | FF（前→后） | CARRY8（前→后） |
| --- | --- | --- | --- | --- |
| LoadStoreUnit / range-only | 2.442→2.453 | 977→836 | 346→342 | 24→10 |
| DataTranslationAdapter / range+PMP | 4.430→4.215 | 2649→2506 | 98→98 | 346→331 |
| IntegerBackend / 最终 candidate-v2 | 15.641→15.719 | 59144→58064 | 28188→28184 | 1480→1386 |

后端最终 WNS +4.177 ns（20 ns 模块约束），最差仍是
`orderCheckBeat → recoveryAccepted → LSU → StoreBuffer → reads/CE`，59 级。
相对中间候选 16.119 ns 减少 0.400 ns，但相对最初基线仍慢 0.078 ns：
**没有证据声称整后端已提速**。保留范围/PMP的逻辑简化与 1080 LUT 减少，
作为待整机验证候选，而非替换已发布 bit 的依据。
后续更高频率的主要工作仍是缩短恢复授权/发请求/返回 ready 的跨模块串联，
必要时再比较流水边界的 IPC 代价。

第一轮只有范围/PMP 修改时，后端 LUT 降低但最差延迟反而是
15.641→16.119 ns，因此没有把“资源下降”当作时序达标。
随后才针对报告中的 valid→size 依赖继续修改。
本轮最终候选仍需新整机 post-route 验证；旧 bit/DCP 均保留。

### 功能验证与性能边界

仅运行相关 GSIM，不跑全量：

- `GSIM_CXX=clang++-19 make gsim-ram-range-test`：
  独立 C++ 128 位数学模型，1,274,016 组输入 × 12 种窗口；
  覆盖 DDR、URAM、所有 1/2/4/8 字节长度、边界前后、未对齐端点、
  空窗口、地址空间顶端溢出；故意注入错误被拒绝。
- `make gsim-pmp-test`（同 GSIM_CXX）：16 定向、6,000 随机、
  30,840 边界检查，包含 size=0..7；错误注入通过。
- `python3 simulator/gsim/run.py store-buffer --registered-owners`：
  与板级相同的 2 项/寄存归属模式，零延迟及背压内存通过；
  普通 1/2/4/8 项模式与读值/非法写响应错误注入也通过。
- `make gsim-core-registered-memory-address-owners-test`：
  GSIM + NEMU 282 程序、185,224 译码用例通过，含重放、精确异常、背压与错误注入。
- `python3 simulator/gsim/run.py vm-data-compact-coherent-buffered-platform`：
  1810 commits、5 walks；首陷阱 675 条 / 1723 周期，虚拟内存、PMP、相干原子路径通过。
  此数值不是旧文中其他版本/配置的直接 IPC A/B。
- `make gsim-ddr-test-app`：范围/PMP 改动后实际 BootROM 下载 DDR 测试程序、
  执行并返回通过；3,642,430 周期、2,093 read bursts、833 write bursts，与改前一致。
  StoreBuffer 最后一步另由上述整核与随机回归覆盖。

这些修改不增加访存/提交延迟，不改变缓存容量或发射宽度；
尚未测新的板级 CoreMark，也不能用 GSIM 墙钟耗时衡量硬件性能。

### UART / CDC / 复位审计

`fpga/zu15eg/audit_ddr50_stability.tcl ROUTED_DCP REPORT_DIR [CANDIDATE_XDC]`
只打开已有 DCP 做报告，可选 XDC 仅在内存中验证，不写 checkpoint/bit、不重新布局。

旧 DCP 确认：

- `uart_rxd → rxMeta → rxSync` 两级 FF 存在，rxMeta 只驱动 rxSync；
  两级 ASYNC_REG 均为空。新 `board_ddr.xdc` 准确选中两级，设置 ASYNC_REG，
  读取新约束后两者均为 1。没有新增 false-path 或放宽 SoC 时钟约束。
- 旧 rxMeta→rxSync 路径 setup slack +19.644 ns、hold slack +0.063 ns；
  本身没有发现 setup/hold 违例，缺属性不等于已经证明 UART 故障原因。
- CPU/MIG UI 的异步置位、同步释放复位链已有 ASYNC_REG。
- 时钟 CDC 报告中的已分析路径无 unsafe/unknown；
  未约束外部输入不会被 report_cdc 覆盖，因此另行审计 UART 链，不能声称 CDC 报告覆盖一切。
- `check_timing`：no_clock=0、unconstrained_internal_endpoints=0、loops=0。
  输入 button_n/sys_rst_n/uart_rxd 及输出 c0_ddr4_reset_n/led/uart_txd 各有 3 项无 I/O delay，
  它们是复位/异步串口/状态接口，保留告警与板级合同审查，未用宽泛例外隐藏。

后续验收需检查新整机 50 MHz 的 setup/hold/pulse width、CDC、bus skew、约束覆盖，
再做 UART 重复下载 CRC、DDR 压力及应用回归。若继续拆跨模块流水边界，
需同时给出频率收益和同一负载 IPC 代价；不能只依据模块综合宣布稳定或更高频率。

## 2026-10-01：DDR50 恢复/访存反馈断链候选

在 9 月 30 日 range/PMP/StoreBuffer candidate-v2 基础上，比较已有参数的两个方案。
板级导出与 GSIM 都可显式传入 `baseline`、`early-issue`、`queued-memory`；
第三个方案只用于 A/B，不默认启用。

| IntegerBackend / 未布局综合、20 ns | 数据路径 ns | WNS ns | LUT | FF |
| --- | ---: | ---: | ---: | ---: |
| baseline（candidate-v2） | 15.719 | +4.177 | 58064 | 28184 |
| early-issue | **13.618** | **+6.364** | 58509 | 28189 |
| queued-memory | 14.247 | +5.649 | 57533 | 28198 |

选择 `early-issue`：用已有恢复/异常候选提前保守阻止新的 LSU 发射，
去掉等待 ROB 授权结果再返回 LSU start 的串联依赖；恢复接受、精确提交和副作用
归属仍由原来的 token/ROB 规则授权，没有增加流水级。
最差路径缩短 2.101 ns（13.37%），成本是该模块多 445 LUT / 5 FF。
`queued-memory` 另增加 LSU 非直通请求队列，给请求多加一拍，
本次模块路径反而比 early-issue 长 0.629 ns，因此不采用。
以上是模块筛选，不是整机 post-route 或板上稳定性结论。

必要功能和周期 A/B：

- `GSIM_CXX=clang++-19 make gsim-core-registered-memory-address-owners-early-recovery-test`：
  282 程序、185224 译码用例，NEMU 差分与错误注入通过；380429 commits。
  与无 early-recovery 参数的同规格日志逐项比较，26 条 IPC JSON 全部一致。
  这组整核测试使用 ROB32/PRF64/memory8；不冒充板级 ROB16/PRF48/memory2 的全负载 IPC 结论。
- `GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_test_app.py --timing-profile early-issue`：
  使用实际 BoardSoc 配置，BootROM 下载、执行 DDR 测试再返回；
  3642430 cycles / 2093 read bursts / 833 write bursts，与 baseline 完全一致。
- 未运行全量 GSIM、未重新测板级 CoreMark。保守发射阻止可能影响其他冲突负载，
  不能把这两组“零变化”泛化成所有程序绝对没有代价。

报告根目录：`E:\VM\Share\Valence-rtl\ddr-feedback-20261001`。
其中 `early-issue/reports`、`queued-memory/reports` 是模块筛选报告。
保留 V0.1 的旧 routed DCP/bit。旧 routed 检查点跨层物理优化后的 `u_soc`
有 1694 个额外内部端口，不能安全整块替换；已改为在新工程中拼接已综合 SoC
及现有 MIG/时钟/AXI CDC，从 .xci 加载原 IP 约束，重新做整机布局布线。
实测 clock report：200 MHz 输入、MIG UI 250 MHz、CPU 50 MHz，均是真实 MMCM 派生时钟。
没有放宽 CPU 20 ns，也没有新增 false-path。

整机候选状态：已完成新整机布局布线与 bit 生成，见下文最终签核。

### 新整机 post-route 与 bit（2026-10-01 已完成）

采用 early-issue，未启用请求队列或寄存响应候选。CPU 50 MHz、MIG UI 250 MHz，
新顶层拼接时复用 SoC 综合检查点和原 IP 的 .xci / 已综合结果 / XDC，
没有重综合 CPU、没有改变 DDR 型号或引脚，也没有放宽时钟或增加 false-path。
正常整机实现耗时约 29 分钟（包含顶层拼接、opt/place/route/报告），
此次额外工具兼容排查耗时不算作实现加速的公平 A/B。

| 已布线指标 | 旧 V0.1 release | early-issue 新候选 |
| --- | ---: | ---: |
| CPU WNS / 20 ns | +0.001 ns | **+0.328 ns** |
| 整机 WNS（新最差为 MIG UI） | +0.001 ns | **+0.267 ns** |
| WHS / WPWS | +0.008 / +0.081 ns | +0.010 / +0.081 ns |
| TNS / THS / TPWS、失败端点 | 全 0 | 全 0 |
| LUT / FF | 132002 / 78124 | **129178 / 78077** |
| BRAM36 / BRAM18 / DSP / URAM | 62 / 1 / 22 / 0 | 62 / 1 / 22 / 0 |

首次完成 route 时全局 WNS +0.259 ns，post-route Explore 后为 +0.267 ns；
不能把路由中间的 -1.171 ns 或 +0.259 ns 当作最终签核值。
CPU 最差已转为 `pc_reg[3]_replica → pc_reg[4]_replica_3`：
19.539 ns、47 级，布线占 78.284%。下一轮更高频率应优先分析取指/PC 反馈及其高扇出，
响应链加拍不一定会改善这条新的最差路径。当前不能据模块 13.618 ns 宣称 70+ MHz，
也没有通过改变 Clock Wizard 实测更高频率。

签核通过：

- 161366 个可布线网络全部完成，route errors 0，14 项 bus skew 全通过。
- no_clock=0、unconstrained_internal_endpoints=0、loops=0、latch_loops=0。
- CDC 已分析路径全部 safe，unsafe/unknown/缺 ASYNC_REG 均为 0；
  无 I/O delay 的异步 UART/按钮等仍单独审计，不宣称 CDC 报告覆盖它们。
- 两级 UART ASYNC_REG 读回均为 TRUE；8 个 AXI REGION 输入为 GROUND。
- 全部 29 个 ROM BRAM 的 4176 个 INIT/INITP 值与候选 SoC 检查点逐项相同。
- Bitstream DRC 没有 Error/Critical Warning，仍有 63 项普通警告。
- 约束数量检查移到批处理 Tcl；board_ddr.xdc 不再使用 XDC 不支持的 if 命令，
  ASYNC_REG 的实际约束不变。

2026-10-01 01:41:44（Asia/Shanghai）生成，28700913 bytes：

`E:\VM\Share\Valence-rtl\ddr-feedback-20261001\release\valence_ddr50_early_issue.bit`

SHA256：
`A2979EE9698E749A1322B7401D42F2B2A50D6FDA11DBD5A604B3383515F19510`。
`release/signoff.txt` 和同目录完整报告可核对；实现检查点在 `assembly-v3/routed.dcp`。
新默认 BoardSocConfig.timingProfile 已改为 early-issue；以默认配置再次导出的
97 个 SV 文件与实际实现的 early-issue 目录逐文件 SHA256 相同。
原 GUI 工程/源文件引用与旧发布 bit 均未覆盖，旧 bit SHA256 保持不变。

**这是新的 50 MHz 静态签核候选，不是板上稳定性证明。**
本流程没有自动烧录。随后用户反馈该版本仍出现 `header rejected: invalid header`；
需要继续检查 UART 下载/CRC 和物理接收链路，再完成 DDR 压力测试与应用运行。
串口故障原因依旧未被单独证实，不能宣称本次仅凭 timing report 已解决。

### 寄存响应备选的周期代价（未纳入发布 bit）

增加可选 `registered-response` profile：保留 early issue，现有两项响应 FIFO 关闭
empty flow-through，使物理返回到 CPU 多一拍。MachinePlatform 默认仍不启用该选项。

`GSIM_CXX=clang++-19 python3 simulator/gsim/ddr_test_app.py --timing-profile registered-response`
通过：3662888 cycles、2093 read bursts、833 write bursts。
相同完整测试比 early-issue 增加 20458 cycles（+0.562%）。
这包含 UART 等待，不能当成 CoreMark IPC 的精确代价。
未进一步跑 Vivado；当前无额外加拍的 early-issue 已满足 50 MHz，且新最差已是 PC 反馈，
因此不为这个备选再重复一次整机实现。

## 2026-10-01：45 MHz 降频对照与 UART 连续接收

用户反馈 early-issue DDR50 版本仍拒绝下载头，提出将时钟降低到 45 MHz。
原 GUI 的 `ZU15EG.xpr` 仍引用旧 `board-40m` RTL，用户修改的是 200 MHz
输入的 `clk_wiz_0`；本轮 DDR 批处理使用独立工程/检查点，CPU 时钟来自
MIG UI 250 MHz 输入的 `clk_wiz_ddr`，不会自动继承 GUI 的时钟更改。

对照目录：`E:\VM\Share\Valence-rtl\ddr45-compare-20261001`。
按 45000000 Hz 导出同一个 early-issue BoardSoc；97 个 SV 与 DDR50 逐文件
SHA256 比较，96 个相同，只有 `UartConsole.sv` 的波特率常量改变。
BootROM 的 CPU_HZ 与 DDR 测试程序一起重建为 45 MHz；串口仍是 1500000、8N1。
45 MHz 每位恰好 30 个 CPU 周期，而 50 MHz 需分数周期平均 33 1/3。
没有更改 FIFO、MMIO 布局、下载协议、CPU 流水级或 MIG 型号/引脚。

仅重新综合小 UART/Clock Wizard/ROM 分区；在旧 routed DCP 的内存副本中
更换 UART、按独立 Clock Wizard 生成结果修改 MMCM 硬件参数、更新 ROM INIT。
旧 routed UART 边界有额外物理 reset 输入，使用严格 215 端口匹配；
上下文优化掉的 size[2] 驱动依据 CoreRegisterRouter 的零扩展 RTL 恢复为 GND。
锁定原有已放置逻辑后局部布局/保留路由，并逐项核对 UART 之外
274284 个原有 primitive 的 LOC/BEL 未改变。
`place_design -eco` 不适用于本机 UltraScale+，不能作为通用加速命令。
工具兼容性排查耗时没有计入公平性能 A/B。

`eco/routed.dcp` 生成于 11:23:42（Asia/Shanghai）；它是**未签核候选，不是可发布 bit**：

| 已布线检查 | 45 MHz 对照 |
| --- | ---: |
| 真实 CPU / MIG UI 周期 | 22.222 / 4.000 ns |
| CPU setup WNS / hold WHS | +2.489 / +0.011 ns |
| CPU 最差数据延迟 / 逻辑级数 | 19.539 ns / 47 |
| 整机 WNS / TNS / setup 失败端点 | -2.011 / -6.033 ns / 3 |
| 整机 WHS / THS / hold 失败端点 | -0.114 / -0.342 ns / 3 |
| WPWS / TPWS / pulse-width 失败端点 | +0.081 / 0 ns / 0 |
| 完全布通 / 可布线网络；route errors | 161254 / 161254；0 |
| bus skew | 14 项全部 MET |

CPU 最差仍是 PC 反馈，与 DDR50 的数据延迟完全一致；正余量增加主要来自更长周期，
不是新 CPU 优化。整机违例位于异步置位、三级同步释放复位链：
`calDone_gated_reg → reset_pipe_reg[0]/PRE` 的 recovery，
以及 `ui_reset_pipe_reg[2] → reset_pipe_reg[0]/PRE` 的 removal。
250/45 MHz 的最小边沿关系为 0.444 ns，暴露了复位同步入口的时序例外/CDC审查需求。
本轮没有加宽泛 false-path、没有剪掉真实同步数据路径，也没有绕过签核生成 bit。
后续应核对完整同步链拓扑、ASYNC_REG、同步释放和仅作用于异步复位入口的约束；
不能把以上数值直接当成 CPU 达不到 45 MHz，也不能声称串口故障已定位。

必要验证改为独立主机连续 8N1，默认不再插入额外空闲位：

- `GSIM_CXX=clang++-19 python3 simulator/gsim/board_ddr.py --cpu-hz 45000000`：
  PASS，5678535 cycles、936 UART bytes、1098 read bursts、554 write bursts。
- 同命令 `--cpu-hz 50000000`：PASS，6278796 cycles、936 UART bytes，
  相同 burst 数。日志分别在 `build/gsim/board-ddr-45000000-8n1/test.log`
  与 `board-ddr-50000000-8n1/test.log`。
- 12 项 host 协议单测与 `uart_probe.py --self-test` PASS；没有打开 COM4。
- 未运行全量 GSIM、未模拟真实 MIG PHY/USB-UART、电气或亚稳态；
  包含串口等待的周期数不是计算 IPC 或 CoreMark 对照。

本节为 FIFO 升级前的历史 A/B，当时是非 FIFO 8N1 16550 子集，FCR=0x06。
当前 FIFO/中断/错误状态和统一参考时钟模型见下节与 [UART 合同](uart.md)。

## 2026-10-01：FIFO UART / DDR45 与 DDR50 最终发布

本轮已完成用户要求的两版，输出根目录
`E:\VM\Share\Valence-rtl\uart-fifo-20261001`。均为 early-issue CPU、
128 KiB ROM / 512 MiB CPU-visible DDR / MIG UI250MHz；旧工程与旧 bit 保留。
没有重综合 CPU：97 个 SoC SV 中 96 个与已签核 early-issue 基线一致，
仅 UART 源码改变。UART 外 274284 个原有 primitive 的 LOC/BEL 逐项不变。

### 优化与签核

- UART 增加 16 字节 RX/TX FIFO、16x 中心三点多数采样、
  RX 四字符超时、阈值/中断优先级、逐字符错误及 LSR/OE 读清，
  可编程帧格式、loopback/modem delta/break。BootROM FCR=7。
  全部 divisor 统一使用参考时钟，不再仅对 divisor=1 特判：
  DDR45 为 24 MHz reference，DDR50/115200 为 1.8432 MHz reference。
  地址、字节访问、APLIC source3 与 VLD1 协议不变；不是完整芯片认证。
- Quick 局部布线发现 UART response queue 的 FF→LUTRAM 写地址短路径：
  同一网络的 16 个 hold 端点，45 MHz WHS -0.060 ns、50 MHz -0.004 ns。
  验证该网络的全部驱动/负载都属于 UART 后，仅解开它，用 Default
  `route_design -preserve` 做 hold 绕线，全部原有位置不变。
  不能靠降频修复 hold，也没有给这条数据路径加 false-path。
- 完整结构审查 UI/CPU 两条三阶段 FDPE 复位链：ASYNC_REG、
  共享异步 PRE、首级 D=0、中间级只有下一 D 负载。
  XDC 仅例外六个 PRE 入口；同步 Q→D 和所有真实 CPU 数据仍计时。
  最后 CDC 暴露原 `calDone → LUT → CPU PRE` 组合旁路，
  改为所有 board/UI/calibration/clock-unlock 原因先进入 UI 链，
  `ui_reset_pipe[2]/Q` 直接驱动 CPU 三个 PRE。
  独立检查旧 64 项/新 LUT2 4 项真值表、驱动/负载，全部原有布局不变。
  最終 CDC 无 Critical/unsafe/unknown/缺 ASYNC_REG；没有 CDC waiver。
  这些复位改动只影响启动/复位资格，不增加正常 CPU 流水延迟。

| 最终 release 已布线指标 | DDR45 / 1.5 Mbaud | DDR50 / 115200 |
| --- | ---: | ---: |
| 真实 CPU 周期 | 22.222 ns | 20.000 ns |
| CPU setup WNS / hold WHS | +2.489 / +0.011 ns | +0.328 / +0.011 ns |
| 整机 WNS / WHS / WPWS | +0.267 / +0.010 / +0.081 ns | +0.267 / +0.010 / +0.081 ns |
| TNS/THS/TPWS / 失败端点 | 全 0 | 全 0 |
| CPU 最差数据延迟 | 19.539 ns | 19.539 ns |
| 完全布通网络 / routing errors | 161822 / 0 | 161809 / 0 |
| bus skew | 14/14 MET | 14/14 MET |
| CDC 已分析 unsafe/unknown/缺 ASYNC_REG / Critical | 全 0 | 全 0 |
| bitstream DRC Error / Critical Warning | 0 / 0 | 0 / 0 |
| ROM INIT/INITP 比对 | 4176/4176 | 4176/4176 |

仍有 63 条普通 DRC（DSP 流水建议、debug LUT 项、无负载网），以及
3 个输入/3 个输出缺同步 I/O delay 的既有异步/状态接口告警。
不能把已分析 CDC 的零违例当作外部 UART 电气/亚稳态的完整证明。
整机 WNS 仍由 MIG UI 决定；CPU 最慢仍是 PC 反馈，不是 FIFO UART。
45 MHz 的额外 setup 裕量来自更长周期，不能冒充新的 CPU 数据路径提速。

### 必要 GSIM

`run.py uart` 通过 1339 笔事务、83 个串行字节、73885 周期，
`uart-formats` 通过 40 种格式与 modem/loopback/break；两项期望篡改被拒绝。
两项 Scala 参数检查、12 项主机协议测试与离线 probe self-test 通过。
真实 BoardSoc + BootROM 连续 8N1：

| 配置 | cycles | UART bytes | AXI read/write bursts | stalls |
| --- | ---: | ---: | --- | ---: |
| 45 MHz / 1500000 | 5677739 | 936 | 1098 / 554 | 1401 |
| 50 MHz / 115200 | 18387432 | 936 | 1098 / 554 | 1384 |

覆盖下载头、CRC/重试、镜像失效、范围/保留区、DDR 执行返回/原子/fence.i，
ROM 3061 字节、sample 552 字节。周期含 UART 等待，不是 IPC A/B。
未跑全量、未重测 CoreMark；此 GSIM 不模拟 MIG PHY/真实跨时钟复位/USB-UART。
新的配套 DDR tester 为 6088 字节，按对应 CPU_HZ/baud 编译；
本轮板级 GSIM 执行的是 sample，不把旧 DDR tester smoke 结果冒充新 binary 的再验收。

### bit 与配套下载

两份 bit 均为 28700913 bytes，2026-10-01（Asia/Shanghai）：

- `E:\VM\Share\Valence-rtl\uart-fifo-20261001\ddr45-b1500000\release\valence_ddr45_uart1500000_fifo.bit`，2026-10-01 13:02:03；SHA256 `CA550E15A99099F09DC22BCB6AF652D4E06C272E6B4A9A6903FA6EFB2CA84550`。

- `E:\VM\Share\Valence-rtl\uart-fifo-20261001\ddr50-b115200\release\valence_ddr50_uart115200_fifo.bit`，2026-10-01 13:02:19；SHA256 `833BA466897BCD03DD2AF58740B1C046D028BCA1ECE971A803936F0206EC3D98`。

每组 `release/` 保存同名 LTX、`signed_routed.dcp`、signoff 与全套报告；
`firmware/` 提供对应时基的 sample / DDR tester 和双向 console 下载工具。
`validation/` 保存必要 GSIM 证据（negative 日志中 FAIL 是预期错误注入）。
第一版 45 MHz bit 在最后 CDC 审计前产生，已移到
`ddr45-b1500000/pre-reset-audit-unreleased`，**不要使用该初稿**。
只有上述两个正式 `release/` bit 为交付产物；失败脚本日志没有被重新标成 PASS。

先建议上板试 DDR50/115200，建立串口可靠性基线；关闭其他 COM4 终端并复位：

```powershell
cd E:\VM\Share\Valence-rtl\uart-fifo-20261001\ddr50-b115200\firmware
python .\uart_load.py COM4 .\ddr_test.bin --memory ddr --baud 115200 --run --console
```

45 MHz 切换到该 profile 的 firmware 目录，并使用 `--baud 1500000`。
DDR tester 覆盖的内存会被改写，不要和 OS 共用测试区。
测试重复下载/CRC、串口输入、DDR smoke/quick 后再尝试大镜像。
旧 OpenSBI/OS 必须匹配新的 UART reference 和 45/50 MHz timebase，
尤其不要保留旧 divisor=22 的速率解释。

**静态时序与必要功能验证均通过，但尚未执行板上烧录或稳定性压力测试。**
不能据此宣称用户之前的 header rejected 已被实体板验证解决。
旧 early-issue bit 的 SHA256 仍是
`A2979EE9698E749A1322B7401D42F2B2A50D6FDA11DBD5A604B3383515F19510`。

## 2026-10-01：DDR 吞吐与 PC 反馈优化候选

MIG tCK=1000 ps、x32、AXI64/UI250 MHz、CPU50 MHz、UART115200、
ROM、下载协议与 MMIO 不变，没有更新已有已上板/签核 bit。
本轮在原 2 KiB 容量和零新增流水拍下改善 copy、削短 PC 反馈。

已修改：

- CoherentLineCache 支持 1/2 ways，32 physical slots 不变；两路 16 sets，
  invalid-first/二路 LRU，pending slot 寄存、正确 victim address 重建，
  masked write/probe/flush/hit-under-miss 和有序响应保留。
- CoherentLineHome 的 bounded directory 与相联度匹配；tag 查所有者，
  GrantAck 分配同 set 空 slot。初次只改 L1 触发旧单路目录断言，
  随后修正 home 并重测通过；没有删断言或将失败改称 PASS。
- SynchronousFetch 的压缩指令包/半字选择用 5-bit 相对偏移，
  完整地址仍用于 request/tag/fault tval；四路和 64-bit wrap 保留。
- IntegerCore 预计算顺序/lane/successor PC，late acceptance 只作选择。
  没有新增流水级。

### Vivado 模块 A/B

同 Vivado 2025.1、xczu15eg-ffvb1156-2-i、20 ns、8 threads、
out-of-context/flatten none/零边界 delay；均综合、opt、布局完成。
未做整机实现/route/CDC/hold/bit 签核；OOC 时钟源警告仍存在。
data delay 是各自最差 slack 路径的数据延迟，不直接换算整机 Fmax。

| 模块 | 基线 / 候选 data delay | 基线 / 候选 WNS | LUT | FF | BRAM tile |
| --- | --- | --- | --- | --- | --- |
| SynchronousFetch | 8.450 / 6.691 ns | +11.515 / +13.291 ns | 9408 / 7738 | 4421 / 4419 | 0 / 0 |
| CoherentLineCache | 4.060 / 4.414 ns | +15.573 / +15.221 ns | 4531 / 4668 | 5478 / 5528 | 8 / 8 |

前端 LUT -1670（-17.75%）、最差 data delay -1.759 ns（-20.82%）。
缓存 +137 LUT/+50 FF、同容量/8 BRAM，模块 setup 裕量仍较大。
Home/IntegerCore 单独时序/资源未测，不把各模块相加冒充整机面积。
旧已布线 CPU 的 PC→取指→解码/接受→PC 仍为 19.539 ns、
47 级、78.284% 布线、WNS +0.328 ns；这是旧版事实。
新整机是否继续满足 50 MHz、能否升频，尚未进行 post-route 验证。

产物根目录：`E:\VM\Share\Valence-rtl\ddr-opt-20261001`。
frontend-candidate/ 保存最终候选 RTL，其 reports/ 为前端 OOC；
cache-baseline/、cache-candidate/ 保存 L1 A/B 报告及 DCP。
前端基线报告在旧 RTL 导出目录新增 reports/；旧 release 报告/bit 未覆盖。
模块脚本第六可选参数 REPORT_DIRECTORY 防止覆盖，支持保存 synth/place DCP。

### 必要验证

- 编译、原 active Scala suite、补充 OooParamsSpec 的 14 项检查通过。
- 单/双路独立 TL manager：同索引 residency、masked write、
  dirty eviction、9 次 probe、flush/backing 一致性、有序 hit-under-miss、
  A/C/D/E 回压通过。
- 二/四路 fetch fixture：4745/14375 条指令、741/2435 个 fault 检查，
  packet/wrap/context/invalidate/held request 通过。
- 四路真实 core 的虚拟取指 baseline/cross-page 通过；
  各 walks=3、PTE reads=5、TLB hits=11、data walks=2。
- 同 5638 字节 benchmark，单/双路总周期 3713840/3674723，
  timed copy 59280→11419 cycles（5.19×），read/write/chase 基本不变；
  source/destination/ring 在独立 AXI backing 中逐项正确。
  总周期含 UART 不是 IPC；只做 4 KiB auto smoke，直接加载不是 UART 上传。

没有全量 gsim-test、真实 MIG PHY/跨时钟模拟、COM4/烧录或整机重新签核。
已上板 DDR50 bit 的 SHA256 保持
`833BA466897BCD03DD2AF58740B1C046D028BCA1ECE971A803936F0206EC3D98`。
下一步只需一次候选整机 post-route，再用原测速程序上板 A/B。

## 2026-10-01：双发射 2-way 整机签核与紧凑四发射评估

本阶段没有把板级默认切到四发射。`BoardSocConfig.issueWidth=2`，
新可选四路的 rename/issue/commit=4；ROB16/PRF48/LSU2/SB2、frontend16 sets、
I-line cache8 lines、D-L1 2KiB/32 slots 均保持相同。
四路物理供指从8B变16B、原平台顺序预取自动打开，不能把它称为孤立的 ALU 加宽。
关闭预取作为显式对照，通用平台默认与双路默认均保持不变。

### 同流程完整 SoC 分区资源

Vivado 2025.1、xczu15eg-ffvb1156-2-i、OOC synthesis、flatten none，
均导入真实初始化 BMG ROM，功能黑盒数为0，20ns/8 threads。
这里的 LUT 是 SoC 分区（含 ROM/L1/外设），**不含外部 MIG/CLK/AXI CDC/debug hub**；
单/双路 cache 的旧 OOC 模块数据不与本表相加或混作同阶段结果。
该 FPGA 有341280 LUT，不能把700k+逻辑资源直接等同于700k LUT。

| 候选 | LUT | FF | RAMB36 | DSP |
| --- | --- | --- | --- | --- |
| 双发射、两路相联 L1 | 118861 | 62602 | 37 | 19 |
| 四发射、原指令预取，取指偏移修正后 | 185896 | 63013 | 37 | 19 |
| 四发射、关闭指令预取 | 178574 | 62818 | 37 | 19 |

无预取四路比双路 +59713 LUT/+216 FF（LUT +50.24%），存储/DSP不增长。
关闭预取相对四路原策略 -7322 LUT/-195 FF。
无预取四路占全芯片 LUT **52.3%**，未超资源；按本轮双路整板外部IP占用
概算四路整板约190726 LUT/55.9%，这是估算，**不是四路整板实现报告**。
更大 ROB/PRF/cache 的四路不在此结论之内；局部拥塞仍可能限制实现。

同阶段热点：

| 模块 | 双路 LUT | 四路无预取 LUT |
| --- | --- | --- |
| IntegerBackend（含下列 RenameRob） | 57822 | 98914 |
| RenameRob | 9740 | 22702 |
| SynchronousFetch（含 PMP） | 7991 | 15017 |
| InstructionLineCache | 5561 | 5685 |

嵌套资源不可重复相加。主开销是 rename/ROB多端口、PRF选择/写回及调度，
不只是多两套ALU；四路 ALU各2580 LUT，乘除/存储规模未随宽度翻倍。
四路综合最差 queue token→core entry CE 为23.281ns/84 levels、
WNS -3.385ns（20ns，77.406% estimated routing）。
OOC尚无真实时钟源/实际布线，**不能换算为四路 FPGA Fmax，也不能说四路已过50MHz**。

### 同镜像必要 GSIM

18140B CoreMark BIN、RV64IM -O2、1 iteration，
同DDR50/115200/AXI backpressure，固定参考CRC全正确：
双路639000 ticks，四路原预取697141，四路无预取587055。
同频 +8.85%；相对50MHz双路四路至少45.935MHz才打平。
不是正式CoreMark分数、实机频率或Linux IPC。完整证据见
[性能记录](performance-status.md#2026-10-01紧凑双四发射同镜像对照)。
四路无预取原5638B DDR bench也通过：4548/7137/11228/3636 ticks；
其中copy只比双路两路相联的11419快约1.7%，受访存限制，并非两倍吞吐。

独立物理 I-cache现在允许行内16B包的8B偏移（0..48），offset56跨行保持fallback；
64/128bit高低半包、1packet/cycle、回压、PMP、error fill、失效通过。
负向模型恢复旧16B对齐条件后按预期被测试抓住。
板级宽前端本来16B对齐，因此该IP修正未改变四路CoreMark周期，不虚报收益。
参数测试15项、源码diff/Python语法通过；未跑全量GSIM、四路OS/中断/压力验收。

导出四路无预取（不改变默认）：

```sh
mill -i IonSoC.test.runMain ooo.BoardSocMain build/fpga/compact4 \
    50000000 ddr early-issue 115200 2 4 0
```

末三项为data-cache ways/issue width/instruction-prefetch(0或1)；
原六参数调用仍兼容。
四路产物在`ddr-opt-20261001/compact4-noprefetch-rtl`与`soc4-noprefetch`。

### 双路新 L1 候选：唯一一轮完整实施及 bit

复用既有ROM/MIG/50MHz CLK/AXI CDC分区；只对双路新L1候选完成一次
opt/place/phys_opt/route/phys_opt。原GUI工程及旧bit均未覆盖。
默认双路在本轮新增参数/取指修正后重新导出，97个SV逐一SHA256完全相同。

| 项目 | 本轮整板 post-route |
| --- | --- |
| CPU/MIG UI | 50MHz / 250MHz，真实generated clocks |
| CPU/global WNS | +0.163ns / +0.163ns |
| WHS / WPWS | +0.011ns / +0.081ns |
| Setup/hold/pulse violations | 0 |
| LUT / FF | 131013 / 78479 |
| RAMB36 / RAMB18 / DSP | 62 / 1 / 22 |
| Bus skew / route / timing coverage | 14全部MET / routing errors0 / 无missing clock或未约束内部端点 |
| ROM/CDC/reset/DRC | 4176 INIT/INITP一致；CDC unsafe/unknown/missing ASYNC_REG/Critical=0（分析路径）；无DRC Error/Critical |

setup裕量比旧已上板版CPU WNS +0.328ns更小，**不能宣称这轮整机提频成功**；
50MHz静态签核通过不等于新bit已实机验证。
新最差path为 backend/orderCheckBeat_reg[4]→pc_reg[4]，
19.449ns（logic4.946/route14.503，74.569%routing）、55levels、
clock skew -0.313ns、uncertainty0.099ns。
源码对应load overlap tournament→replay/recovery授权/ROB反馈→PC；
原19.539ns PC供指回环不再是最差起点，但回放/重定向反馈成为新热点。
后续优先模块化处理这条链和四路RenameRob/PRF，不只继续增加供指宽度。
拥塞等级6是本轮router的实际估计，仍需关注局部布线而非只看全局LUT百分比。

独立发布候选：

- `E:\VM\Share\Valence-rtl\ddr-opt-20261001\release-2way\valence_ddr50_uart115200_fifo.bit`
- 大小28700913B，SHA256
  `CB59BFE12D0B6DF01CC1ACEFBC8489633C742DECA9C08CFC5D1E2993358405C8`
- 同目录`signed_routed.dcp`、`signoff.txt`、时序/CDC/DRC/bus-skew报告和LTX。
- `soc2-route`保存完整实现报告；`width-comparison.json`保存四路A/B配置/资源/周期。

旧稳定bit SHA256
`833BA466897BCD03DD2AF58740B1C046D028BCA1ECE971A803936F0206EC3D98`保持不变。
新bit未烧录、未访问COM4，先用原ddr_bench在板上q/b复测，再决定是否替换基线。
四路只完成必要GSIM和综合资源，没有四路全实现/bit。

## 2026-10-01：双发射回放链候选与 BootROM 缓存回退修复

继续以双发射/ROB16/PRF48/LSU2/SB2/2KiB两路相联 L1 为基线。
用户反馈该 L1 板测全部 PASS，8MiB COPY payload=17.214MiB/s（原3.130），
READ/WRITE/CHASE基本不变，详见 [性能记录](performance-status.md)。
该反馈不是代理烧录或读回确认 bit SHA，不作为新回放候选的实板证据。

### 同周期回放选择重构：小幅面积收益，尚未解决整机频率

`LoadReplaySelector` 把全部61位beat比较分成短段，完整保留PA和byte-lane冲突检测；
以环形ROB顺序选择最老的younger load，生产候选独热读取token/PC。
不新增生产流水拍/容量，不开启registeredLoadReplay/registered retirement。
新selector是可独立验证/测量的组合模块，不把宽度变更当作优化。

相同寄存边界的16-entry回放→64bit PC/64bit tag测试夹具，
Vivado2025.1/-2-i/20ns/flatten none，均只综合和布局、未route：

| 夹具方案 | post-place LUT | FF | data delay | logic delay | levels | CARRY8总数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 旧tournament/index读取 | 1019 | 3379 | 3.972ns | 1.143ns | 14 | 48 |
| 新环形选择/独热payload | 1627 | 3379 | 4.087ns | 0.917ns | 11 | 0 |
| 新环形选择/索引payload | 1109 | 3379 | 3.899ns | 1.157ns | 12 | 0 |

新独热夹具虽减逻辑层数，却多LUT且布局估计略慢，**不是成功的模块提频**。
索引变体只在小夹具更好，尚无整机候选资源/时序对照，不据此替换生产候选。
完整独热候选SoC综合显示 LUT **118861→118181（-680/-0.57%）**、
FF62602→62606、RAMB36=37/DSP=19不变；层次共享/优化结果不同，
不能把夹具LUT直接加到整机。真实ROM已导入，无功能blackbox。

对相同SoC OOC blackbox checkpoint仅定向查询orderCheckBeat→pc：
data delay **15.183→15.053ns**（-0.130ns/-0.86%），logic3.640→3.582ns，
estimated route11.543→11.471ns，levels57→53，路径CARRY8从9到6。
起点bit3→45，全部高PA比较仍保留。绝大部分反馈链未消除。
总体综合最差仍为translated队列deq pointer→LSU state CE，20.919ns/83levels、
WNS-1.023ns（20ns），两版相同；**没有整体综合时序改善**。
OOC无真实MMCM源/布线，不能和旧整机post-route19.449ns混比或换算新Fmax。
新回放候选未执行整机route/signoff/bit，下一阶段需进一步处理恢复授权反馈，
若引入寄存边界必须同时评估precise retirement/IPC，而不是直接增加频率。

证据目录：`ddr-opt-20261001/replay-candidate/{module-baseline,module-candidate,module-indexed,soc,cone-reports}`。
默认仍双发射。选择器16892832组/负向、执行核心NEMU282程序/回放/异常、
参数15项、新BootROM下载及CoreMark/DDR定向检查通过，无全量GSIM。
CoreMark仍639000ticks，DDR四项仍4583/7214/11419/3661；不声称同频IPC提高。

### BootROM回退根因及不重新布线的独立修复bit

上一版 `release-2way` 引入原工程缓存ROM DCP，发布只核对candidate==routed INIT，
未核对最新固件。这是构建来源错误，不是用户应用或UART下载协议问题。
重新编译50MHz/divisor1 DDR固件，3061B BIN SHA256
`987FA3687E82620B8A708E03B93791D8F3A2AE181BFFAAF3FE533174A744E1F2`。
与既有独立FIFO ROM IP全部32768 MIF字及padding完全一致，可安全复用该IP。
原工程ROM DCP当前历史路径不再存在；从保存SoC checkpoint提取确切旧ROM作参照。
严格证明新旧29个BRAM拓扑/非INIT配置/端口一致，并验证全部旧值之后，
只更新**83个INIT属性**，原LOC/布局/布线不变，同时更新逻辑SoC参考。

发布入口现在必须给 `EXPECTED_ROM_DCP EXPECTED_ROM_BIN`；
BIN/MIF/DCP时间/哈希及期望IP→candidate→routed全部4176 INIT/INITP都检查。
用旧candidate的真实负向发布按预期拒绝`Candidate contains stale/wrong BootROM`，
没有生成bit；6项Python正负单测通过。检查构建来源，不宣称安全启动。
Vivado调用Python用`-I`隔离其PYTHONHOME/PYTHONPATH，避免标准库版本污染。

最新独立修复版：

- `E:/VM/Share/Valence-rtl/ddr-opt-20261001/bootrom-fix/release/valence_ddr50_uart115200_fifo.bit`
- 28700913B，SHA256 `FBADD8F0CA86BA847A86F42DB93105C6F4193DB8458E884F9F184F2D04C9277C`
- 保持原已板测双发射2-way CPU/L1，**不含新回放重构**；只恢复最新BootROM。
- WNS +0.163ns/WHS +0.011ns/WPWS +0.081ns，与原路由不变。
- setup/hold/pulse/14 bus-skew/route/DRC/reset/CDC/全部ROM检查通过。
- 原`release-2way`和旧单路稳定bit未覆盖；代理未访问COM4、未烧录。

重启只输出`Valence Bootrom V0.1`、`download mode (UART)`；
无`CPU OK`、测试菜单和`>`。下载协议/地址/容量/UART波特率不变。
代理的当前源码BootROM GSIM下载/CRC/保留区/fence.i/执行返回通过
18319290cycles、936 UARTbytes、3061B ROM；实际新bit启动仍需用户验证。

## 2026-10-01：registered-replay 实际 SoC 寄存切分评估

可选 profile `registered-replay`，不是新默认或已发布 bit。
双发射/紧凑存储容量不变；启用 registered replay/ROB retirement/early issue block。
源码保留地址与 ownership 的流水约束；16 项参数检查及执行核心 NEMU/
精确回放/短板级 CoreMark/DDR PASS，成本见 [性能记录](performance-status.md)。

```sh
mill -i IonSoC.test.runMain ooo.BoardSocMain build/fpga/replay-stage \
    50000000 ddr registered-replay 115200 2 2 1
```

同一真实 BMG ROM DCP 导入 SoC 综合，无未解析功能 blackbox。
资源119567 LUT/62731 FF/37 RAMB36/19 DSP；相对无新增拍的 selector 候选
多1386 LUT、125 FF，独立于外部 MIG/Clock/AXI CDC。
定向查询中 orderCheckBeat→pc 不再有直接组合路径。
新增 `fpga/zu15eg/report_replay_stage.tcl` 同时报告切分两侧，不把“无路径”当作测试失败。

| 同一 20ns SoC OOC 条件 | data delay | logic / estimated route | levels | slack |
| --- | ---: | --- | ---: | ---: |
| beat→replayPending D/CE | 3.508ns | 0.956/2.552ns | 11 | +16.474ns |
| replayPending→PC D | 13.324ns | 2.810/10.514ns | 48 | +6.658ns |

上一版 orderCheckBeat→PC 综合估计15.053ns，切分后最长定向段13.324ns（约-11.49%），
代价是 recovery 多一拍，以及相同短 CoreMark +0.512% ticks。
检查对象是该 beat 的反馈链，不冒称覆盖所有 valid/head/exception 恢复起点。
全 SoC 最差综合路径仍为 translated queue deq pointer→LSU slot state CE：
20.919ns、83 levels、WNS-1.023ns，与原候选相同。
这些为综合估计，不是 post-route，不能推导板上稳定频率。

产物 `E:/VM/Share/Valence-rtl/ddr-opt-20261001/replay-stage/`：
`rtl`、`soc`、`stage-cone/{overlap_to_stage,stage_to_pc}.rpt`、`results.json`。
旧 `cone` 查询要求直接路径，因此报 missing path，已由两段查询取代；保留原日志。
未执行候选整板 route/bit，保留已签核 DDR50/115200 ROM 修复版供 Linux 首启动。

## 2026-10-01：物理响应 owner 双旁路切分

在默认双发射 `early-issue` 上推进，不启用 registered-replay；ROB16/PRF48/LSU2/SB2、
2 KiB/2-way L1、50 MHz CPU、115200 UART、512 MiB DDR aperture不变。
旧最差链由 translated queue 地址经过 PMP、MMIO路由、L1/Atomic仲裁、Home/TL
request grant，再经空 owner 的flow直通返回 response valid，最后进入LSU state CE。
OrderedTileLinkBridge 的非flow order队列已经保证新DataPort请求不能同拍返回，
因此在该边界取消空owner旁路不必增加响应数据流水级。

`MachinePlatform.registerPhysicalResponseOwners=true` 同时禁用两处 owner flow：
physicalData_systemArbiter 和 shared/unit（AtomicMemory普通CPU/DMA响应）。
BoardSocTop启用；通用IP默认保持原行为。只切第一处并不足够：第一阶段整体链
仍经AtomicMemory空owner返回，最长路径几乎不变。第二阶段才切断这条反馈。

| 相同20ns SoC OOC综合条件 | 最长data delay | levels | WNS | LUT | FF |
| --- | ---: | ---: | ---: | ---: | ---: |
| 之前selector候选，两个owner flow | 20.919ns | 83 | -1.023ns | 118181 | 62606 |
| 仅系统仲裁owner非flow（中间状态） | 20.880ns | 83 | -0.984ns | 118172 | 62606 |
| 系统仲裁+Atomic普通owner均非flow | 19.318ns | 78 | +0.482ns | 118171 | 62606 |

最终相对基线最长路径缩短1.601ns（7.65%），RAMB36=37/DSP=19均不变。
最终logic/estimated route为4.642/14.676ns，routing估计仍占75.97%。
新最差链是 translated/deq_ptr_value_reg[1]→DataTranslationAdapter owners RAM WE，
即请求授权/入队反馈仍长；后续优先PMP/地址路由、Home/TL grant和翻译适配器请求边界，
而非继续只盯LSU响应。保存的30条路径用于下一阶段定位。

共享仲裁小模块同资源93LUT/10FF，综合最长2.134→1.501ns；定向ready→response-valid
旁路原0.703ns，新版无该组合路径。`report_atomic_owner_cut.tcl`复用两阶段SoC
blackbox checkpoint，进一步证实物理grant→Atomic CPU response组合路径从20.880ns
变为不存在；该定向查询不经过ROM。整体资源/时序来自导入真实初始化BMG的完整SoC，
没有未解析功能blackbox，不把ROM黑盒的局部查询当整机验收。

参数19项、共享仲裁/原子IP的独立模型与负向注入、VM/单轮CoreMark/DDR短测PASS。
VM同源码1810 commits/1723 firstTrapCycles/675 retired不变；CoreMark639000ticks，
DDR read/write/copy/chase=4583/7214/11419/3661，均与基线一致。
没有全量GSIM或再次长时间启动Linux；460800数字下载单列，不能代替物理串口验收。

最终两处切分后的50 MHz/460800连续8N1 BootROM定向检查通过：8481736 cycles、
936 UART bytes，3061B最新ROM/552B sample；头/块/整镜像CRC、保留区/最大DDR
头部边界、重写同地址指令/fence.i、旧镜像失效均PASS。实际460800 bit尚未生成。
后续上板须同步UART reference=7372800 Hz、DTB UART时钟及loader波特率，不能只改host baud。

证据：`E:/VM/Share/Valence-rtl/ddr-opt-20261001/response-owner-cut/`，第一阶段在
`soc`，最终在`complete-cut/{rtl,soc,atomic-cone}`；`results.json`记录对照和测试状态。
仅SoC综合，无整板布局布线/新bit；+0.482ns为综合估计，不证明50 MHz真实布线裕量，
更不据此承诺更高稳定频率。已发布115200 ROM修复bit、Linux镜像和DTB未改动。

## 2026-10-01：staged-fabric 批量结构优化

用户明确要求已写入根目录及 OoO 的 `AGENTS.md`：一次完成相关改动，合并必要短
GSIM，成功后只综合整批候选一次；失败先修复，不逐个小修改跑综合，不默认全量
GSIM、长Linux或整板实现。此次按该规则生成独立候选，复用真实初始化ROM IP。

候选 `staged-fabric`（默认仍 `early-issue`）合并四部分：

- PMP/原子范围检查之后，2项非直通 checked FIFO 捕获请求和异常决策。
- Home入口，2项非直通请求FIFO捕获完整数据及CPU/DMA/walker归属，隔离ready反馈。
- M/S APLIC、timer/UART/DMA各改为一次并行译码和统一8项owner，不再串联五个路由。
- 复用已验证的registered replay/ROB retirement；仲裁改显式二选一，避免空owner元数据作动态Vec索引。

仍双发射、ROB16/PRF48/LSU2/SB2、2KiB两路L1、512MiB DDR aperture、50MHz/115200。
新请求级各增加一拍；MMIO响应owner级数减少，实际周期成本另测，不能说零代价。

| 同20ns SoC OOC/真实ROM/同器件条件 | 最长data delay | levels | WNS | LUT | FF |
| --- | ---: | ---: | ---: | ---: | ---: |
| 双physical owner切分基线 | 19.318ns | 78 | +0.482ns | 118171 | 62606 |
| 整批staged-fabric | 15.047ns | 53 | +4.849ns | 119401 | 62716 |

最长路径缩短4.271ns（22.11%），LUT增加1230（1.04%），FF增加110；RAMB36=37、
DSP=19不变，WHS=+0.006ns/TNS=0。Vivado只执行一次synth_design，20:51:03至
20:57:21完成整套综合/ROM导入/报告，未route。8线程，实际综合最多7个helper进程。
新最长路径logic/estimated route为3.016/12.031ns，routing估计仍占79.96%。

只读复用完整 `soc_candidate.dcp` 的边界查询通过：

- translated/PMP之前的队列寄存器→physical response-owner WE，已没有直接组合路径。
- Home grant→system arbiter request ready，已没有直接组合路径。
- `translated_to_checked_we.rpt` 为新增队列的入队控制查询（1.366ns），不是完整PMP权限数据延迟。
- 剩余Home grant控制路径10.799ns，终点是physicalRequests出队指针；仍超过10ns目标。

全局新顽疾已转移为 multiplier/live_3 → completion有效/branch-recovery仲裁 →
ledger.recoveryAccepted → trap/invalidateFetch → frontend供指/页错误门控 → rename接受 →
pc_reg[0]/CE。它不是乘法DSP算术数据路径；扇出377/281/220等控制节点及跨模块反馈
需要下一批一起重构，不能仅继续增加乘法流水拍。15.047ns依然不满足10ns，亦不能据此
承诺板上稳定66MHz。60MHz是值得进一步整板验证的候选目标，不是本轮已验收的频率。

必要短测PASS：21项Scala，fabric11081事务、两种共享仲裁各12596事务及负向oracle，
VM页错/相干/原子，同镜像CoreMark单轮和DDR4KiB应用。ASan/UBSan保留；CoreMark/DDR
共用一次生成和编译的BoardSocGsim。初次VM短测暴露空owner的无效动态索引，已用
等价标量Mux消除并验收两种模式；未修改生成GSIM模型或关闭sanitizer掩盖问题。
其他初期失败是新增参数测试遗漏machineSystem及仲裁测试宏不匹配，均先修复后再综合。
周期成本及频率×IPC收支见 [性能记录](performance-status.md)：CoreMark+6.06%，相对
50MHz基线需超过53.03MHz才抵消该工作量代价。全部为合成模型，不是上板性能。

证据 `E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-fabric/`：`rtl`、`soc`、
`focused-logs`、`boundary-query`、`results.json`。102个SV的文件名/哈希清单整体SHA256：
`7c83c4c910ccdea587e7a9d296a457709f953620a21ad834205506d497a7a080`。
不要仅用BoardSocTop.sv哈希辨别候选：顶层端口/实例不变，其哈希与上一版相同，实际
修改位于MachinePlatform及其依赖。已发布115200 ROM修复bit SHA256仍
`fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c`。
无新bit、板级频率/460800物理UART/Linux用户态均未新增验收。

## 2026-10-01：staged-control 合并控制路径优化

遵循重要批量规则：完成三项控制修改，一轮合并必要短测全部PASS，随后只运行一次
联合SoC OOC综合。候选 `staged-control` 继承上一批fabric，仍两发射及全部原容量；
默认 `early-issue`、旧fabric候选和已发布bit不变。

一次组合分支预完成（不再等非分支完成端口空闲）、前端错误/page payload与valid
门控解耦、平衡阈值树的并行rename寄存器信用。无新正常取指流水拍，精确异常/
回滚/旧token拒绝和同包映射合同不变。详细接口见 [核心计划](ooo-core-plan.md)。

| 同20ns/真实ROM/xczu15eg-ffvb1156-2-i SoC OOC | 最长data delay | levels | WNS | LUT | FF |
| --- | ---: | ---: | ---: | ---: | ---: |
| 上一批 staged-fabric | 15.047ns | 53 | +4.849ns | 119401 | 62716 |
| 此批 staged-control | 14.831ns | 53 | +5.065ns | 118723 | 62457 |

全局仅缩短0.216ns（1.44%），LUT减少678（0.57%）、FF减少259；不能把恢复链的
局部改善当成整机大幅提频。RAMB36=37、DSP=19、WHS=+0.006ns、TNS=0。
真实ROM导入且无功能blackbox。8线程，21:40:21至21:46:29完成本轮综合/报告（368s）。
新最差logic/estimated route=3.335/11.496ns（routing 77.51%）。尚未route/出bit，
14.831ns仍不满足10ns，不能宣称稳定67MHz或已提高板级频率。

复用前后两个完整checkpoint的只读查询，三处都是baseline=1条、candidate=0条：

- multiplier.complete.valid → ledger.recoveryAccepted。
- backend.invalidateFetch → frontend.instructionPageFaults(0)。
- ledger.renamed(0).destination → ledger.renamed(1).valid。

查询结果表明原控制反馈确实消失，不是仅改了代码外观；无需再综合。
新最长从 `backend/queue_15_renamed_token_tag_reg[0]/C` 到
`core/parallelRouter/owners/deq_ptr_value_reg[0]/CE`。具体经过队列token/访存选择与
范围判定→reserveMemory/LSU start→StoreBuffer的VA输出→DTLB fast-hit ready→
LSU request grant→LSU零拍response.ready→StoreBuffer/译址owner→M/S APLIC owner出队。
这是访存请求授权反向串入回复ready的跨模块链，不是乘法算术，也不只是完成token比较。

下一批优先联合：译址前的请求信用边界、覆盖M/S APLIC及fault占位的CPU响应信用边界，
以及LSU零拍应答合同。平台原有响应FIFO在APLIC之后，不能保护本地APLIC回复；优先
评估前移/复用而非叠加FIFO。StoreBuffer本地转发/ACK仍可能零拍，不能不经验证直接
删除LSU的零拍处理。需同时记录新增请求延迟与频率×IPC收支，再一次短测/联合综合。

合并短测24项Scala、容量131072向量、取指2/4路及未压缩错误/失效/背压、裸核
NEMU282程序/18000随机整数3seed及负向检查、VM/单轮CoreMark/DDR均PASS。
CoreMark677729→677047ticks（同镜像-0.101%），DDR四项4757/7272/11860/3748及
VM首异常1997拍/675retired不变。两个板级应用共用一次模型生成/编译；ASan/UBSan开启。
没有全量GSIM、长Linux、再次route或bit。实际频率、物理460800及Linux用户态未新增验收。

证据 `E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-control/`：`rtl`、`soc`、
`focused-logs`、`control-query`、`results.json`。103个SV的文件名/SHA清单整体哈希：
`bd09278f03c1b601b41d03ecbf9845988aeb7dc289b67a4ca7a760ffbf19de4b`。
## 2026-10-01：staged-data 访存信用整批结果

同双发射/ROB16/PRF48/LSU2/SB2，继承staged-control。一次组合LSU到StoreBuffer的
非直通请求FIFO、既有CPU返回信用前移到翻译层前、size与地址共寄存及末端越界
并行译码。返回信用没有叠加，空时仍直通；请求增加一拍。本地StoreBuffer ACK
仍零拍，不能删除LSU即时应答合同。默认early-issue及已发布bit不变。

| 同20ns/真实ROM/xczu15eg-ffvb1156-2-i SoC OOC | 最长data delay | levels | WNS | LUT | FF |
| --- | ---: | ---: | ---: | ---: | ---: |
| staged-control | 14.831ns | 53 | +5.065ns | 118723 | 62457 |
| staged-data | 13.091ns | 43 | +6.891ns | 119658 | 62473 |

缩短1.740ns（11.73%），LUT增加935（0.79%）、FF增加16；RAMB36=37/DSP=19不变。
8线程、综合helper上限7，22:41:34至22:48:47，共433秒（含ROM导入/报告）；
**本轮仅一次synth_design**。真实初始化ROM导入、最终功能blackbox为0。
比较clock在综合后施加，与旧checkpoint口径一致，不是已约束布线的Fmax。
logic/estimated-route=2.742/10.349ns（routing 79.05%）。未做place/route/bit。

复用前后完整clock-free checkpoint查询，均baseline=1、candidate=0：

- LSU.start.valid → DataTranslationAdapter.translation.request.ready。
- LSU.memory.response.ready → M/S APLIC ParallelRegisterRouter.upstream.response.ready。

说明两处请求/返回反馈确实切断，未使用false-path或多周期约束隐藏。
同一checkpoint重加10ns clock（无第二次综合）的WNS=-3.109ns、TNS=-52469.008ns，
38840/138683 setup endpoints违反；WHS=+0.006ns。**仍未达到10ns/100MHz**，
亦不据13.091ns倒数承诺板上76MHz。大量endpoint违例不是只改一个报表终点就保证达标。

新最差从backend/pending_4_reg/C到IntegerCore/entries_0_reg[6]/D，即返回地址栈：
发射资格/预约选择→late-valid门控PRF操作数→ALU bitManip→完成data→commit data
旁路→RAS写入。source2选择扇出384、bitManip右操作数扇出258；不是DDR延迟或
先前APLIC出队链。下一批先让RAS call link从committed PC+2/4等价产生，不走
通用commit.data，再解耦发射授权与操作数payload。若仍需要执行流水，仅对量到
的复杂链拆分，不能不评估依赖IPC就把全部简单ALU改两拍。

必要短测各组最终PASS（26项Scala/23669信用事务/1274016×12 range/NEMU282程序/
burst/128KiB ROM/精确VM/CoreMark/DDR）；新激励及空FIFO size曾暴露问题，局部
修复并复跑受影响组，ASan/UBSan与负向oracle保留。最后subset JSON是partial-pass，
聚合记录明确列出全部组，不能称一次不间断全绿。两个板级应用共用一个生成/编译模型。
CoreMark707697对前677047拍+4.53%，VM2261对1997拍+13.22%，DDR四项
5030/7642/12567/3786；周期收支见 [性能记录](performance-status.md)。

证据 `E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-data/`：`rtl`、`soc`、
`focused-logs`、`data-query`、`results.json`。106SV的文件名/SHA清单整体SHA256：
`7d8744ea49630d6dff5eaf538c59deb228e9764340cf4ef31712cfe1a28071bd`。
稳定ROM修复bit SHA256仍fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c。
没有新bit、物理UART/更高板频/Linux用户态新增验收，也未升为默认配置。

## 2026-10-01：staged-execute 两条链联合优化

按用户要求每批2–3条相关路径。本批一次合并发射授权与PRF操作数解耦、
RAS call link改由committed PC+2/4派生；继承staged-data全部信用/恢复配置，
仍双发射及原容量。无新增执行流水拍，实际授权不放宽。默认early-issue与发布bit不变。

| 同20ns/真实ROM/xczu15eg-ffvb1156-2-i SoC OOC | 最长data delay | levels | WNS | LUT | FF |
| --- | ---: | ---: | ---: | ---: | ---: |
| staged-data | 13.091ns | 43 | +6.891ns | 119658 | 62473 |
| staged-execute | 12.382ns | 45 | +7.600ns | 119473 | 61454 |

缩短0.709ns（5.42%）；LUT减少185（0.15%）、FF减少1019（1.63%）。
RAMB36=37/DSP=19、WHS=+0.006ns不变。RenameRob综合FF6375→5360，解释大部分FF
差值，但ROB16/PRF48等逻辑容量未削减；不能把综合移除未用寄存当成减少架构状态。
23:18:47至23:24:32共345秒（含导入/报告），synth_design自身246秒；8线程/最多7helper。
本批仅一次synth_design，clock在综合后施加，真实ROM导入、最终功能blackbox=0。
logic/estimated route=2.693/9.689ns（routing78.25%）；未place/route/bit，不是板级Fmax。

只读复用前后clock-free完整checkpoint，两项baseline=1条、candidate=0条：

- ALU.io_result → RAS entries.D（一般完成数据不再进入RAS存储data路径）。
- LSU.io_issueAvailable → ALU.io_right（晚到访存预约信用不再控制该操作数载荷）。

这不表示RAS所有控制链都消失。10ns重约束同一netlist（无第二次综合）结果：
WNS=-2.400ns、TNS=-41926.617ns、34367/135632 setup endpoints违反；WHS=+0.006ns。
旧版10ns为WNS=-3.109/TNS=-52469.008、38840/138683 endpoints；总数也变化，
不能简单按违例个数当同一集合的质量比例。仍未达到10ns/100MHz，不能承诺板上80MHz。

独立终点类别防止只看最差终点（这是类别边界报告，不是每个模块内部OOC/Fmax）：

| 类别/限定终点 | staged-data delay | staged-execute delay |
| --- | ---: | ---: |
| RAS entries.D | 13.091ns | 11.963ns |
| PRF values.D | 12.793ns | 11.650ns |
| ROB ledger registers.D | 12.825ns | 12.123ns |
| reservation queue.D | 12.097ns | 11.911ns |
| frontend PC.D | 11.647ns | 11.879ns |
| selected owner queue.CE | 9.045ns | 8.520ns |

前端PC局部回退0.232ns（1.99%），已记录；不能声称所有模块都改善。
RAS仍11.963ns是ready/排序/控制选择路径，不再是ALU result数值路径。
新全局最差：ledger/head_reg[1]_rep__3/C → backend/ready_40_reg/D。
经过pendingException→external recovery probe/accept→恢复token授权→invalidateFetch→
frontend valid→allocate/renamed0 valid→lane1目的寄存器优先选择→PRF ready更新。
45levels中含6个CARRY8；高扇出恢复token索引261/276、renamed0 valid286。

下一批组合2–3处：恢复/前端valid授权与payload分离、rename候选目的寄存器提前选择、
PRF ready更新/同包分配控制。必须保留部分prefix、no-rd/alias、同包RAW/WAW、旧token
拒绝和同拍异常kill；先独立证明等价。如果仍需加拍再分别预算依赖IPC，不能把所有
简单ALU不加区分改两拍，也不能用false-path、多周期例外隐藏该链。

本批必要短测一次全部PASS：22项Scala；独立RAS20000拍、6406push/4784pop、
1594覆盖/228空pop/809有序混合动作、4reset及40000随机完成payload/负向oracle；
NEMU282程序/185224解码/18000随机整数3seed、M/B/Zicond/负向oracle；紧凑VM与
同BIN CoreMark/DDR。ASan/UBSan开启，未重跑不受影响的credits/range/burst/ROM全组。
CoreMark仍707697ticks，VM首异常2261拍/675retired，DDR5030/7642/12567/3786，
均与上一批相同；两个板级应用只生成/编译一个模型。本批没有新增已观察周期损失，
原访存流水成本仍存在，净收支仍须以真实频率计算。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-execute：rtl/soc/27项focused-logs/
execute-query/results.json。107SV的文件名/SHA清单整体SHA256：
28bcc3ae5d79804c776acbc60a1afde906e581b71498971810fb001ab28a4399。
没有新bit/物理UART/更高板频/Linux新增验收。

现板已有CPU/SoC50MHz↔MIG UI250MHz两域，经异步AXI IP连接，复位各自同步释放。
本批不拆CPU异步域；已有结构、约束及未来第三域条件见
[时钟域计划](../fpga/zu15eg/clock-domain-plan.md)。代码核对不等于新增整板CDC签核。

## 2026-10-02：staged-rename 三条关联链联合候选

本批10月1日开始，沿用目录tag `20261001`，综合及检查点查询于10月2日完成。
继承staged-execute，一次合并三项：fresh目的寄存器候选脱离前lane的accepted、
PRF ready逐寄存器并行wake/reserve译码、AUIPC/预测nextPc载荷脱离前端valid。
仍双发射/ROB16/PRF48/LSU2/SB2，没有新增流水拍。实际分配/完成/异常/恢复/状态更新
授权保留；新fresh候选显式拒绝moveAlias组合，旧alias路径不变。默认early-issue和发布bit不变。

| 同20ns/真实ROM/xczu15eg-ffvb1156-2-i SoC OOC | 最差路径data delay | levels | WNS | LUT | FF |
| --- | ---: | ---: | ---: | ---: | ---: |
| staged-execute | 12.382ns | 45 | +7.600ns | 119473 | 61454 |
| staged-rename | 12.409ns | 43 | +7.487ns | 117161 | 61452 |

LUT减少2312（1.94%）、FF减少2；RAMB36=37/DSP=19不变。但全局data delay回退
0.027ns（0.22%）、WNS回退0.113ns，不能声称本批已提频。路径终点由ready.D变为
RAS.CE，setup要求也不同，不能只比较data delay解释全部WNS差值。
00:02:02至00:07:38共336秒（含ROM导入/报告），synth_design自身239秒，8线程/
最多7helper。仅一次综合，clock在综合后施加；真实初始化ROM导入，最终功能blackbox=0。
logic/estimated route=2.860/9.549ns（route76.95%）；未place/route/bit，不是实际Fmax。

复用两个完整clock-free checkpoint的只读查询，两项确证baseline=1、candidate=0：

- 前端 `io_instructions_0_valid` → rename lane1目的寄存器payload。
- 前端 `io_instructions_0_valid` → lane1预测nextPc payload。

最初经过 `io_renamed_0_valid` 的边界查询得到0/0，不能证明切链；保留该原始log，
补充上游valid边界查询才获得1/0。首查询的递归 `io_next*` 计数1048含内部LUT引脚，
不是端口数；补查询按模块直接输出核对readyUpdate恰为48位，脚本已修正。
这些查询未使用false-path/多周期约束，也没有重新综合。

| 类别/限定终点（非模块内部Fmax） | staged-execute delay | staged-rename delay |
| --- | ---: | ---: |
| PRF ready.D | 12.382ns | 11.703ns |
| RAS entries.D | 11.963ns | 12.180ns |
| PRF values.D | 11.650ns | 11.528ns |
| ROB ledger registers.D | 12.123ns | 12.011ns |
| reservation queue.D | 11.911ns | 11.553ns |
| frontend PC.D | 11.879ns | 11.501ns |
| selected owner queue.CE | 8.520ns | 8.792ns |

ready链缩短0.679ns（5.48%），但RAS.D回退0.217ns、owner.CE回退0.272ns。
同网表重加10ns clock：WNS=-2.513ns、TNS=-38615.492ns、34542/135627 setup
endpoints失败，WHS=+0.006ns。前版-2.400/-41926.617、34367/135632；TNS改善但
最差slack变差，endpoint总数亦变化。仍未达10ns/100MHz，不据倒数承诺板频。

新最差 `backend/ready_38_reg/C` → `returnStack/entries_0_reg[10]/CE`：
ready/排序选择→PRF分支操作数→分支比较/目标与misaligned→completion.exception→
同拍退休条件→commit.valid→双lane RAS动作/index/write-enable。43levels含4CARRY8。
下一批成组处理分支完成判定、同拍退休旁路授权、RAS并行控制更新；先保留精确异常和
有序动作做等价重构，若需寄存branch选择/操作数则单独预算依赖和redirect周期，
不能用无区分的全ALU两拍或异步CPU时钟域代替优化。

必要短测7组最终全部通过：22项Scala，131072个payload/ready向量（2/4/6端口模块，
不是宽CPU验收），独立紧凑ledger 3seed/18000拍，预测packet20程序/110退休，
NEMU282程序/185224编码/18000随机整数，精确VM及同BIN CoreMark/DDR。
首次批次在前三组PASS后因共享GSIM wrapper要求predictor64而继承了board32失败；
只修测试wrapper为predictor64/LSU4，再续跑prediction/core/VM/board，最后subset
JSON仍partial-pass，聚合逐项记录，不宣称一次不间断全绿。未修改独立oracle，保留
ASan/UBSan/负向检查；两个板级应用共用一个模型。周期均与上一批相同，详见性能台账。

证据 `E:/VM/Share/Valence-rtl/ddr-opt-20261001/staged-rename/`：rtl/soc、36项
focused-logs、rename-query、两份query log及results.json。109SV文件名/SHA清单整体
SHA256=5da9f2490900983d99b87d164a16b5039637cc91974698bb65fdcb15187921d8。
该清单沿用PowerShell Sort-Object Name排序；为避免跨平台标点排序差异，results.json
同时记录Ordinal排序清单SHA256=8825895dd38ce061a521282964aa05690ba228677b2355562dfad506ea417517。
发布bit SHA256仍fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c。
没有新bit/上板/物理UART/更高板频/Linux用户态或整板CDC新增验收，动态功耗未测。

## 2026-10-02：staged-retire 分支/退休/RAS 整批结果（未推广）

继承staged-rename，一次合并分段XLEN分支比较、独立同拍退休fault、双lane有序RAS
并行控制。保持双发射/ROB16/PRF48/LSU2/SB2，无新增流水拍。完整exception仍用于
ROB/PRF/trap；快速fault只省略已禁止同拍退休的分支对齐判定，并保留合同断言。
该组合功能短测通过，但整体时序回退，**不升为默认配置**；现板bit与early-issue不变。

| 同20ns/真实ROM/xczu15eg-ffvb1156-2-i SoC OOC | 最差data delay | levels | WNS | LUT | FF |
| --- | ---: | ---: | ---: | ---: | ---: |
| staged-rename | 12.409ns | 43 | +7.487ns | 117161 | 61452 |
| staged-retire | 12.883ns | 44 | +7.099ns | 117317 | 61448 |

整机data delay回退0.474ns（3.82%）、WNS回退0.388ns；终点CE/D的setup要求不同。
LUT增加156（0.13%）、FF减少4，RAMB36=37/DSP=19不变。00:52:05至00:57:56
共351秒（含ROM导入/报告），synth_design251秒，8线程/最多7helper，仅一次综合。
clock在综合后施加，与前批口径一致；真实ROM导入，最终功能blackbox=0。
logic/estimated route=3.399/9.484ns（route73.62%）。未place/route/bit，不是Fmax。

只读检查点查询确认branch.io_misaligned→ledger.commit.valid：baseline=1、candidate=0；
没有用false-path/多周期例外。两路比较器均存在：REF_NAME为BalancedBranchCompare及
BalancedBranchCompare__1。最初严格引用名计数仅得到1而停止报告；保留原始失败log，
修正报告匹配后只续跑candidate，不重跑基线或任何综合。这个失败不是缺硬件模块。

| 限定终点类别（非模块内部Fmax） | staged-rename | staged-retire |
| --- | ---: | ---: |
| PRF ready.D | 11.703ns | 12.001ns |
| RAS entries.D | 12.180ns | 10.795ns |
| RAS entries.CE | 12.409ns | 11.054ns |
| RAS count.D | 12.110ns | 10.447ns |
| PRF values.D | 11.528ns | 11.669ns |
| ROB ledger registers.D | 12.011ns | 12.341ns |
| reservation queue.D | 11.553ns | 11.799ns |
| frontend PC.D | 11.501ns | 11.831ns |
| selected owner queue.CE | 8.792ns | 9.364ns |

RAS data/CE/count分别改善11.37%/10.92%/13.73%，但其它列均有回退，不能把局部
收益等同整机正优化。一次联合映射不能独立归因三项改动；分段比较在新路径上有额外
LUT组合层，是需与原carry方案对照的实验选项，不能断言全部回退只由该单项造成。
10ns重约束同一netlist：WNS=-2.901ns、TNS=-48056.309ns，36808/135682 setup
endpoints失败，WHS=+0.006ns；前版-2.513/-38615.492、34542/135627。
仍未达10ns/100MHz，不能据12.883ns倒数报告实际板频。

新最差ready_22_reg/C→pending_1_reg/D：ready/排序→分支PRF操作数→分段signed比较→
nextPc/预测失配→重定向捕获选择/index与killed资格→动态pending清除。44levels含4CARRY8。
源码边界是captureFlags/captureRedirect/captureIndex及killed(captureIndex)，不要根据
优化后的branchRedirect_token_tag网名就断言是64位tag减法；未做单项独立归因。
下一批成组提前计算每lane捕获资格，按静态slot更新pending，并对照原carry比较。
必须保留原oldest-flag优先级，不能把killed旗标先过滤而意外退选更年轻redirect；恢复/
token/精确异常合同不放宽。若最终需寄存issue/operand仍须预算频率×IPC收支。

8组必要短测最终通过：24项Scala；262144分支数学/结果向量，6种conditional均双向
taken/not-taken；RAS20000拍、6406push/4784pop、1594满覆盖/228空pop、809混合
动作/4reset/40000故意完成data；原ledger3seed/18000拍；预测20程序/110退休；
NEMU282程序/185224编码/18000随机整数，含4个control对齐异常；精确VM与同BIN
CoreMark/DDR。独立oracle、ASan/UBSan、负向注入及快速fault合同断言保留。
首次只在Scala集合类型推断编译失败，显式Seq修复后整批通过；之后审查新激励发现
stimulus/opcode相关，增强双向覆盖，仅复用小比较模型补查（没有再生成板级模型）。
两项应用共用一个板级模型；CoreMark707697、VM2261/675、DDR5030/7642/12567/3786
均不变。不是正式CoreMark分数、上板带宽、四发射或完整Linux验收。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-retire：rtl/soc、45项focused-logs、
retire-query、两份query log、results.json。110SV的Ordinal文件名/SHA清单整体SHA256：
610a1ad8ae2fc9bf251adedd3a27747ce2e5d4a1c7daa31e9aad48c4c54ab7e2。
发布bit SHA256仍fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c。
没有新bit/上板/更高物理频率/UART/Linux/整板CDC新增验收，动态功耗未测。
## 2026-10-02：staged-redirect 成组捕获优化与100/150 MHz目标

用户目标为CPU稳定100 MHz，达标后150 MHz，并为固定外设域做准备。不是降级成
“时钟IP能输出100 MHz”或“OOC无明显异常”就算完成；整板setup/hold/CDC/RDC与
实际程序/DDR/中断运行仍是待取得的证据。外设域接口、复位、IRQ、timebase准备合同
见 [板级时钟域规划](../fpga/zu15eg/clock-domain-plan.md)，尚未启用第三域或动态调频。

本批保留staged-retire的fault/RAS切割，恢复native carry分支比较，同时以
EarlyRedirectCapture提前译码issue index/kill资格、按静态ROB槽清pending。
优先级仍来自原始resolution旗标：最老winner被杀后不退选年轻live分支。Mux1H只
选原winner，token/index归属与快速fault合同断言进入实际GSIM模型。没有新增流水拍，
默认early-issue、双发射/ROB16/PRF48/LSU2/SB2及已发布bit均不变。

| 同20ns/真实ROM/SoC OOC映射口径 | 最差data delay | levels | WNS | LUT | FF |
| --- | ---: | ---: | ---: | ---: | ---: |
| staged-rename | 12.409ns | 43 | +7.487ns | 117161 | 61452 |
| staged-retire | 12.883ns | 44 | +7.099ns | 117317 | 61448 |
| staged-redirect | 12.249ns | 49 | +7.734ns | 117814 | 61449 |

相对staged-retire改善0.634ns（4.92%），相对staged-rename改善0.160ns（1.29%）。
资源+497 LUT（0.42%）/+1 FF，相对staged-rename为+653 LUT/-3 FF；RAMB36=37、
DSP=19不变。logic/estimated route=2.472/9.777ns（route79.82%）。只做一次综合：
01:35:45–01:41:34共349秒，synth_design248秒，8线程/最多7helper。仍在综合后
施加20ns以保留历史映射比较口径；不是10ns约束驱动的综合或真实布局布线结果。
真实初始化ROM导入，最终功能blackbox=0；HD.CLK_SRC等OOC边界警告不能当整板签核。

复用同一clock-free DCP查询，未重新综合；candidate=1个EarlyRedirectCapture、
0个BalancedBranchCompare，baseline=0/2。两版alignment→commit.valid均0路径。

| 限定终点类别（不是模块内部Fmax） | staged-retire | staged-redirect |
| --- | ---: | ---: |
| pending.D | 12.883ns | 11.598ns |
| branchRedirect.D | 12.075ns | 10.219ns |
| PRF ready.D | 12.001ns | 11.685ns |
| RAS entries.D | 10.795ns | 10.478ns |
| RAS entries.CE | 11.054ns | 10.739ns |
| RAS count.D | 10.447ns | 10.132ns |
| PRF values.D | 11.669ns | 11.636ns |
| ROB registers.D | 12.341ns | 12.025ns |
| issue queue.D | 11.799ns | 11.567ns |
| frontend PC.D | 11.831ns | 11.515ns |
| selected owner queue.CE | 9.364ns | 9.900ns |

pending/redirect分别改善约9.97%/15.37%；owner.CE回退0.536ns，必须保留。一次
联合映射不提供三个改动的独立归因；不能把本表局部收益当作净板频/功耗/IPC收益。
10ns：WNS=-2.266ns、TNS=-38282.883ns，34819/135642 setup endpoints失败；
前版-2.901/-48056.309、36808/135682。约150MHz：Vivado把6.666666667ns请求
舍入为6.667ns，WNS=-5.599ns、TNS=-213947.891ns、66088/135642失败（前版
-6.234/-229423.203、64703/135682）。WHS均+0.006ns；两个目标都未满足。

新最差LSU slot0.state_reg[1]/C→stagedMemoryAddress_reg[63]/D，49levels含8CARRY8：
完成/forwarding与恢复/issue仲裁→memory prechoice/源操作数选择→XLEN有效地址。
另有ledger.head_reg[1]_rep__16/C→frontend.lockedMask_reg[1]/D为12.244ns/50levels。
下一批成组解耦访存准备payload与晚到的授权，以及前端fetch/PMP请求mask链；不能
简化权限、越过head-only副作用或丢失locked/invalidation/context语义。若引入流水
边界须同镜像预算周期成本。下一次映射应显式加入综合前10ns约束，而非继续仅重约束
报告；本批不重复综合，也不添加false-path/multicycle例外。

9组必要短测一次通过：26项Scala；新capture66384向量/双优先级，包含3771次
最老被杀而年轻live、16619双旗标、33205blocked；负向注入PASS。原分支数学/
RAS/ledger/预测packet/NEMU/VM/板级应用oracle未改，ASan/UBSan保留。NEMU282
程序/380429commits及4对齐异常；预测20程序/110退休/14redirect。捕获planner宽1/2/4/6
仅是配置/无寄存器elaboration，不是宽CPU行为验收。NEMU压缩前端关闭；压缩路径由
packet/VM/实际紧凑板模型覆盖，不混用容量或宣称全部ISA一致性。
同BIN CoreMark仍707697ticks，VM仍2261拍/675退休，DDR仍5030/7642/12567/3786；
没有观察到新增周期成本。CoreMark/DDR共一个模型，未跑全量GSIM/Linux或生成bit。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-redirect：rtl/soc、46项focused-logs、
redirect-query及results.json。110SV Ordinal文件名/SHA清单整体SHA256：
61585f6de290783c62a0ec3bf56fc4b4b7db201242dd542fc27e3bf203a22314。
发布bit SHA256仍fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c。
此版作为后续优化候选保存，不切换默认/发布板级配置；100/150MHz稳定运行目标保持未完成。

## 2026-10-02：staged-preparation，访存准备达标但全局仍未达100MHz

本轮两条相关长链一起修改：访存准备先独立选择最老两项、并行计算完整地址/数据/
token/size，LSU start.fire最后只排除已发出的owner；压缩取指的对齐word地址和末字节
用拼接，未锁定请求的PMP不再经过locked-base mux。保持首重叠PMP优先级、完整65位
范围、权限/locked-M和head-only副作用顺序，未加流水拍或扩大双发射/ROB16/PRF48/LSU2/SB2。
默认early-issue、50MHz板级时钟、UART115200、DDR/CDC IP、真实BootROM及发布bit不变。

本次修正映射流程：synth_soc_partition.tcl第五参数10，在synth_design前read_xdc
加载10ns create_clock，日志与综合后get_clocks均确认生效；不是仅综合后重约束。
一次综合02:23:26–02:31:58，共512秒，synth_design412秒，8线程/7helper。
旧staged-redirect综合前没有时钟约束，因此以下包含结构及映射约束的联合影响，不能
将全部变化归因于单项RTL。本次未布线OOC，不是实际CPU最大频率/功耗签核。

| 限定终点（data delay，不是模块Fmax） | staged-redirect | staged-preparation |
| --- | ---: | ---: |
| memory preparation address.D | 12.249ns | 7.484ns |
| fetch locked mask.D | 12.244ns | 11.171ns |
| PRF values.D | 11.636ns | 12.291ns |
| branch redirect.D | 10.219ns | 11.032ns |
| PRF ready.D | 11.685ns | 10.982ns |
| ROB registers.D | 12.025ns | 11.163ns |
| issue queue.D | 11.567ns | 11.229ns |
| frontend PC.D | 11.515ns | 10.812ns |
| pending.D | 11.598ns | 11.523ns |
| RAS entries.D / CE / count.D | 10.478 / 10.739 / 10.132ns | 10.804 / 11.074 / 10.467ns |
| selected owner queue.CE | 9.900ns | 9.519ns |

目标地址链改善4.765ns（38.90%），掩码改善1.073ns（8.76%）。独立through-planner.io_issued
查询同LSU state→地址链6.710ns/22levels，0CARRY8，10ns slack+3.273ns；晚到仲裁确实
不再进入地址加法。完整地址终点最差7.484ns仍含8CARRY8，由早期源选择/操作数计算
驱动，而非晚到issue授权。掩码仍11.171ns/44levels/10CARRY8，不能宣称前端已达标。

全局12.249→12.291ns（回退0.042ns），43levels，logic/estimated route=2.478/9.813ns，
路由估算79.84%。10ns WNS=-2.309ns（前-2.266），TNS=-26443.410ns（前-38282.883），
34423/135649 setup endpoints失败（前34819/135642）；WHS+0.006ns。20ns重约束
WNS+7.691ns；约150MHz周期被Vivado舍入6.667ns，WNS=-5.642ns、TNS=-199140.562ns，
65176失败。TNS变好不等于WNS达标；两个CPU目标均未达成，不用延迟倒数报告板频。
LUT117814→127145（+9331/+7.92%），FF61449→61443，RAMB36/DSP仍37/19；包含10ns
映射成本和双候选预计算的成本，未做独立面积归因。故不推广/发布此实验候选。

8组必要短测通过，共29项Scala；ROB16/32独立循环年龄扫描41024/185952向量，含
已发出的唯一候选/最老候选被排除和环回。原128位PMP数学oracle未改，30840边界、
6000随机表，专用对齐word路径7183向量。取指宽2/4原mixed-length/fault/backpressure
测试与新PMP mask测试通过；后者1936向量均检查背压期间context/PC/权限变化不改
held address/mask、invalidate后旧回复不输出指令。72项全56位地址边界补充只重编译
C++ driver，复用原GSIM模型。新/原packet/NEMU oracle负向注入及ASan/UBSan保留。
NEMU282程序/380429退休；压缩packet20程序/110退休/14redirect。VM仍2261拍/675退休，
同BIN CoreMark707697ticks，DDR4KiB仍5030/7642/12567/3786，未观察到新增周期成本。
两个应用共一个板模型，不是正式CoreMark分数或实板带宽；无全量GSIM/Linux/bit生成。

下一批按新报告成组处理：ready→恢复/issue选择→ALU bitManip→PRF数据写回12.291ns；
以及head→pendingException/trap/recovery/invalidation→packet present/wanted→PMP掩码11.171ns。
特别要把grant/kill的有效性与payload预计算分离，但不允许陈旧指令、错误权限、重复副作用
或越过精确异常；若必须加寄存级，继续用同镜像测周期成本。评估访存预计算面积代价，
不因为局部7.484ns就忽略全局PRF、redirect和RAS回退。整板setup/hold/CDC/RDC和
100/150MHz实板压力运行仍待验收，多时钟域/启动选频合同继续保留，当前未启用第三域。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-preparation：57项focused-logs、
soc/soc_candidate.dcp（真实初始化ROM、功能blackbox=0）、preparation-query及results.json。
112SV的Ordinal文件名/SHA清单整体SHA256：
63152f42bbfe080091d4adc1a7c3ffe62d4128c3b2c636e72ad4840f70cd0007。
已发布bit SHA256仍fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c。

## 2026-10-02：staged-payload，取指掩码切断，瓶颈转至回复直通链

本批三项相关payload切割：环形最老两项one-hot选序与显式masked OR、completion owner
提前保留不受晚到grant限制、压缩取指raw packet presence不受同拍invalidate限制。
空one-hot产生全零payload；实际grant/kill/token、精确异常、head-only副作用及locked
请求地址/mask/context、陈旧回复排空均保持。无新增流水拍，双发射ROB16/PRF48/LSU2/SB2
容量、默认early-issue、50MHz时钟/UART115200、真实ROM和已发布bit不变。

7组必要短测通过，32项Scala。独立循环年龄扫描与真实masked-OR payload检查ROB16/32
各28736/87648向量，包含empty/环回/双候选及负向注入。mixed-length fetch宽2/4、
1936项PMP held-context/invalidation、原压缩packet/NEMU/VM和同BIN板级应用通过。
NEMU282程序/380429退休，全部26条完整IPC指标记录与staged-preparation逐字一致。
VM仍2261拍/675退休，CoreMark707697ticks，DDR4KiB5030/7642/12567/3786，两个应用
共一个板模型；不作为正式CoreMark分数或实板DDR带宽。ASan/UBSan与原数学/架构oracle
保留。新增raw presence witness仅重编译C++，复用模型检查invalid request payload、
指令kill和cache清空后的fresh refetch；也通过。补测最初两次命令分别缺GSIM_CXX、
误用compiler()返回tuple，修正调用后通过，未改DUT或测试判据。

两版均在综合前read_xdc加载10ns，比较不再混用后约束映射。唯一综合03:13:06–03:22:47，
581秒，synth_design482秒，8线程/7helper。真实初始化BMG导入，最终功能blackbox=0。
首次新checkpoint检查的端口名io_instruction0_valid错误，原日志/脚本/报告保留；
只修为真实io_instructions_0_valid，复用同DCP补查并加入LSU data终点，未重新综合。
成功查询03:30:31完成：CircularIssueSelector/MemoryPreparationSelector各1；invalidate
到PMP address路径0，到instruction-valid路径1；branch alignment到commit.valid路径仍0。

| 限定终点data delay（不是模块Fmax） | staged-preparation | staged-payload |
| --- | ---: | ---: |
| PRF values.D | 12.291ns | 10.503ns |
| fetch locked mask.D | 11.171ns | 5.318ns |
| branch redirect.D | 11.032ns | 9.369ns |
| pending.D | 11.523ns | 10.446ns |
| PRF ready.D | 10.982ns | 10.596ns |
| ROB registers.D | 11.163ns | 10.883ns |
| issue queue.D | 11.229ns | 10.387ns |
| frontend PC.D | 10.812ns | 10.394ns |
| RAS entries.D / CE / count.D | 10.804 / 11.074 / 10.467ns | 10.086 / 10.347 / 9.740ns |
| selected owner queue.CE | 9.519ns | 8.562ns |
| memory preparation address.D | 7.484ns | 7.333ns |
| LSU result data.D | 11.818ns | 11.818ns |

掩码减少5.853ns（52.39%），44→22levels；PRF减少1.788ns（14.55%），43→36levels。
原晚到LSU issued-owner到地址仍无CARRY8，5.959ns/19levels，slack+4.024ns。各已追踪
family均改善或不变，但不是每个终点达10ns。新最差ROM metadata→总线回复仲裁→
shared/cache→两层MMIO回复shift/mux→translation response FIFO flow-through→store buffer
回复→LSU load formatting，共11.818ns/42levels，logic/estimated route=1.978/9.840ns。
原有DataResponseBuffer容量2、flow=true仅隔离ready信用，空时仍直通payload，不是寄存边界。

全局12.291→11.818ns（-3.85%）；10ns WNS -2.309→-1.836ns，TNS -26443.410→-7870.557ns，
失败29161/135614 endpoints，WHS+0.006ns。20ns WNS+8.164ns；约150MHz被舍入6.667ns，
WNS -5.169ns、TNS -168270.078ns、失败64094。100/150MHz仍未达标。LUT127145→129714
（+2569/+2.02%），FF61443→61439，RAMB36/DSP仍37/19。保持作为下一实验基线，不推广
默认/板级release；未place/route，不能以OOC倒数或固定IPC推断实板频率×IPC净收益。

下一批成组处理真正registered translated response边界、memory回复避开无意义MMIO移位、
以及PRF源ID选择后动态operand选择，测额外回复延迟/周期成本。仍有ROB、ready、PC、
RAS等略超10ns终点，不因为取指5.318ns便宣称CPU整体稳定100MHz。后续实际100MHz
需真实板级RTL参数/BootROM/timebase、setup/hold、CDC/RDC和实板压力运行；动态选频
及第三域不会代替关键链收敛。未运行全量GSIM/Linux、未生成bit。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-payload：55项focused-logs、
short-tests.json、真实ROM soc/soc_candidate.dcp、payload-query-retry和results.json。
113SV Ordinal文件名/SHA清单整体SHA256：
8455614de3672621bcd0ff6f4614e02022f66f6fde3b166a29560a9a6c0d4519。
已发布bit哈希已复核，仍fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c。

## 2026-10-02：staged-return，真实回复寄存级与操作数选择的收支

保持2issue/ROB16/PRF48/LSU2/SB2，同批三项：DataResponseBuffer深度2改flow=false，
两层ParallelRegisterRouter让memory reply绕过本地lane shift，IssuePhysicalOperands
并行解码queued source IDs、ranked owner到physical mask再masked OR取值。无新ALU拍，
无新容量/请求所有权；回复最少+1拍。默认early-issue、50MHz/UART115200和发布bit不变。

37项Scala；operand ROB16/48与32/64分别56897/151137向量；legacy flow23669请求及
registered23786请求、1000流式回复、200孤立寄存见证；原fabric11081请求/974原子bypass；
packet20程序110提交；原NEMU282程序380429提交；VM和相同BIN板CoreMark/DDR均通过。
两种operand/两种credits/fabric/packet/NEMU负向注入均被拒绝，ASan/UBSan保持开启。
前期顶层Vec setter生成失败，用scalar Record wrapper接回未改DUT Vec；cloneType交给
Chisel插件。饱和流的空回复覆盖不足，保留>100阈值增200合法孤立见证，复用模型。
VM UBSan发现无效owner导致本地移位指数160，源码改固定8种移位/零默认值；不是改
生成C++或关闭检查。只补跑fabric/VM/board，其余已通过组复用。失败日志/原始JSON保留，
恢复JSONpartial-pass，short-tests.json明确是分组汇总而非一次不间断pass。

CoreMark同18140B/hash ae05e5be6d30bb8ec111e4734d41407ac31e9de200dd25ac7fef3ee92739e821，
707697→731130ticks（+3.31%）。DDR 4KiB四项5030/7642/12567/3786→5295/7714/12987/3847。
VM首个固定trap里程碑2261→2525cycles、均675retired（+11.68%），walk5/PTE7/physical263
不变。总commit1271→1007因固定3000拍总窗口的trap后循环预算不同，不能据此比较工作量。
26条完整bare-core IPC记录相同；它不经过SoC回复级。仍一个生成/编译板模型，单轮CRC
不是正式CoreMark分数，模拟DDR不是实板带宽。

10ns XDC在综合前加载，04:29:08–04:38:10一次综合542秒，synth_design442秒；8线程，
工具允许最多7个synthesis helper。ROM stub阶段Project1-486告警在真实初始化BMG导入
后解除，最终functional blackbox=0。clock-free DCP只供实际板级时钟重新约束，未route。
04:38:57–04:41:27只查同DCP：operand/issue/preparation模块各1；旧alignment→commit.valid
仍0；invalidate→PMP address0、→instruction-valid1。回复data/error/pageFault/valid共67
输入到67输出直通组合路径0，证明确为寄存边界，不只隔离ready。

| 限定终点data delay（不是模块Fmax） | staged-payload | staged-return |
| --- | ---: | ---: |
| LSU result data.D | 11.818ns | 8.995ns |
| PRF values.D | 10.503ns | 10.516ns |
| pending.D | 10.446ns | 10.485ns |
| PRF ready.D | 10.596ns | 10.635ns |
| ROB registers.D | 10.883ns | 10.875ns |
| issue queue.D | 10.387ns | 10.262ns |
| frontend PC.D | 10.394ns | 10.433ns |
| branch redirect.D | 9.369ns | 9.331ns |
| RAS entries.D / CE / count.D | 10.086 / 10.347 / 9.740ns | 9.704 / 9.965 / 9.358ns |
| selected owner queue.CE | 8.562ns | 8.731ns |
| memory preparation address.D | 7.333ns | 7.092ns |
| fetch locked mask.D | 5.318ns | 5.318ns |

LSU少2.823ns（23.89%）、42→29levels、10ns slack+0.987ns。新reply storage输入8.153ns/
28levels/slack+1.771ns（终点为LUTRAM写口），credit state8.609ns/slack+1.373ns。晚issued
到地址6.128ns/20levels、0CARRY8、slack+3.855ns。RAS data/count slack+0.278/+0.624ns，
但RAS CE slack-0.069ns，不能把9.965ns data<10当成完整setup达标。PRF新的最差是pending13
到values0，10.516ns/36levels/slack-0.534ns；改换source-ID选择结构并不代表所有PRF路径达标。

全局ROM metadata→TL返回仲裁→fallback回复到下一请求地址（64位carry）→TL地址译码/
request ready返回→fetchAdapter.state.CE，11.425ns/44levels，logic/estimated route=
2.267/9.158ns。全局data11.818→11.425ns（-3.33%），但CE setup不同，WNS只改善0.307ns：
20ns +8.164→+8.471；10ns -1.836→-1.529，TNS -7870.557→-7456.943，失败27754/135620，
WHS+0.006ns。约150MHz有效6.667ns，WNS-4.862、TNS-164010.578，失败62538。
OOC HD.CLK_SRC未设，物理时钟skew/布线不作为签核；100/150MHz都未达标。

LUT129714→136165（+6451/+4.97%），FF61439→61448（+9），RAMB36/DSP37/19。operand
独立模块10064LUT不等于整批净增，三项变化未独立隔离归因。PRF最差时序未改善，需
继续控制operand选择面积/fanout；不默认推广。CoreMark和VM频率盈亏点相对即时前版
分别>1.0331116×和>1.1167625×实际频率；当前未布线不能宣称频率×IPC正收益。

下一批优先关联的取指回复/下一请求payload与握手、frontend decode→allocation控制，
并复查pending/issue→PRF及one-hot面积。第三域/启动选频/运行态DFS均未实现；可调clk
不会提高Fmax，也不能替代timebase、CDC/RDC、setup/hold及实板压力验收。未全量GSIM/
Linux、未生成bit；用户GUI未操作。证据在E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-return：
58个focused-logs、分组short-tests.json及原始subset/失败JSON、return-query、真实ROM DCP。
115SV清单SHA256 ac1b29563e83cc72823a39ebb16eca10f082a1ddcacf5afbfaffcca93ddd5d7b；DCP
7d10d857821b952669fd6199d94054a8cca2eee402a88f9c8f85c28e353f9673；发布bit哈希再次复核不变。

## 2026-10-02：staged-fetch-address，取指地址反馈减短、回收面积，仍未达100MHz

以staged-return为即时基线，同批三项相关改造：fallback Get的old+8/start+8/partial+4先
计算再由晚到cache-hit选择；对齐ROM端点用65位拼接而非晚到加法；两个物理TL router
的静态半开区间用精确prefix并集译码。同时恢复前版binary PRF读操作数，关闭而不删除
高面积one-hot实验。仍双发射ROB16/PRF48/LSU2/SB2，无新增state/credits/流水拍。
start-address译码不替代manager的大小、对齐、完整传输跨度合法性检查。真实寄存回复
和direct memory payload保留；其相对staged-payload的CoreMark+3.31%、VM+11.68%成本仍在。

十组受影响短测汇总通过，23项Scala；5组32/64小窗口、非对齐DDR、高地址译码各56565/
62805向量及反例，软件oracle是128位普通区间数学而非DUT的prefix算法。原router、crossbar、
fetch协议/错误/背压oracles未改，错owner/source和数据反例仍失败。line-cache demand/
prefetch的2/4word均通过；生产两发射是2word，不启用4word-only预取。4word预取驱动
首次64位契约编译失败、随后wide-ROM已接单而驱动重复等待失败，均仅修wrapper/握手
跟踪。分开比较low/high软件beat，4word反例只破坏high半；ASan/UBSan、oracle和DUT
不改。失败日志及原始failed/partial-pass JSON保留，不声称一次全跑通过。

NEMU282程序/380429提交/18000随机指令3seeds、prediction20程序通过；26条完整配置
IPC记录及cycles/retired与staged-return相同。虚拟取指baseline/cross-page均walks3/PTE5/
TLBhits19；data-VM固定首个里程碑仍2525拍/675退休。复用一个板模型：同BIN CoreMark
731130ticks、DDR4KiB5295/7714/12987/3847均不变。不是正式CoreMark分数或实板带宽。

05:30:06–05:39:42一次联合综合576秒（synth_design475秒）；综合前10ns，真实初始化
ROM导入后functional blackbox=0。05:40:07–05:42:37复用两个DCP查42份报告，无再次综合。
capture/preparation/issue selector各1，one-hot physical module0、prefix decoder2。
alignment→commit.valid0、invalidate→PMP address0但→instruction-valid1；CPU回复67输入
到67输出data/error/pageFault/valid组合直通0，前批切断保持。

| 限定终点data delay（不是模块Fmax） | staged-return | staged-fetch-address |
| --- | ---: | ---: |
| fetchAdapter state.CE | 11.425ns | 10.890ns |
| ROB/RAT registers.D | 10.875ns | 10.867ns |
| PRF ready.D | 10.635ns | 10.596ns |
| PRF values.D | 10.516ns | 10.503ns |
| pending.D | 10.485ns | 10.446ns |
| frontend PC.D | 10.433ns | 10.394ns |
| issue queue.D | 10.262ns | 10.355ns |
| RAS entries.D / CE / count.D | 9.704 / 9.965 / 9.358ns | 10.054 / 10.315 / 9.708ns |
| branch redirect.D | 9.331ns | 9.369ns |
| LSU result data.D | 8.995ns | 8.826ns |
| selected owner queue.CE | 8.731ns | 8.562ns |
| memory preparation address.D | 7.092ns | 7.333ns |
| fetch locked mask.D | 5.318ns | 5.318ns |

取指through fallback D.valid→A.address的限定链10.338ns/36levels/0CARRY8，slack-0.442ns；
去掉晚到carry不等于完整链达标。全局换成ROM metadata→TL D仲裁→coherent line writer
D.ready选择→ROM响应ready→ROM请求信用→TL A.ready→fetchAdapter.state.CE，10.890ns/
38levels/0CARRY8（前44levels/7CARRY8）。logic1.889、estimated route9.001ns（82.65%）；
是ready/信用反馈新瓶颈，不再是地址加法。新reply storage7.662ns/slack+2.262、credit
8.440ns/+1.542；late issued→memory address5.959ns/19levels/0CARRY8/+4.024。

全局data减少0.535ns/4.68%；WNS20ns+8.471→+9.006，10ns-1.529→-0.994，TNS-7456.943→
-6773.861，失败27754/135620→25817/135614，WHS均+0.006ns。约150MHz有效6.667ns的
WNS-4.862→-4.327、TNS-164010.578→-161665.844，但失败端点62538→63397增加，亦保留。
RAS D/CE回退0.350ns到slack-0.072/-0.419，issue queue与memory preparation也回退；
不能只留改善结果。OOC未布线且HD.CLK_SRC未设，不作为物理setup/hold/CDC/RDC签核。

LUT136165→129570（-6595/-4.84%）、FF61448→61439（-9），RAMB36/DSP仍37/19；三项
联合变化不做独立归因。相比staged-payload面积略低144LUT，但继承的回复周期成本不消失。
同周期且OOC更好是候选收益，尚不能宣称实板频率×IPC正收益。不推广默认、IP/clock/
reset/已发布bit不变；未全量GSIM/Linux、未route/bit，用户GUI未操作。

下一批优先共同缩短前端链：ROM/network D-ready→request-credit反馈、相邻取指cache
地址命中串行运算，以及prediction资格→rename/PC控制；全程保留source/owner/burst/
held-A、精确异常与回滚合同。PRF写回10.503ns和RAS回退继续监测，后续不能漏掉。
第三外设域、启动选频及运行态DFS仍待实施；100MHz真实整板/实板稳定运行后再冲击150MHz。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-fetch-address：results.json及short-tests.json，
96份focused-logs、42份fetch-address-query报告、32份相关源码快照、同BIN固件和真实ROM。
115SV清单SHA256 4532d07baa8d6152d4130ce591cdccfe273e9e057aa7be9dfa1993a672bdc9aa；DCP
c0c72921496c1087bbfd4b41a0575dc5193b7af1756a22218b4fdca1cd7043c6。发布bitSHA256仍
fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c。

### 2026-10-02 staged-fetch-control：三条取指控制链，单次综合完成

继承fetch-address（2issue、ROB16/PRF48/LSU2/SB2），组合处理ROM外部D.ready→A.ready
信用反馈、TL回复valid→source/owner串行lookup、PC-relative预测alignment/successor
资格。ROM两个完整D回复项采用flow=true/pipe=false：空时旁路、满时不借当拍dequeue
空间；这是ready信用切断，不是假称payload被寄存。既有CPU回复67位真正寄存仍保留。

最终完整九组必要短测通过，27项Scala；ROM原120边界事务、独立容量3/排序/持有/复位
与II=1；full64预测50360向量、原路由/packet/NEMU/VM/同BIN板级短测和8个反例均通过。
初次两次新结构检查的层级名假设失败已留档，未修改行为oracle来迎合DUT。
26条完整IPC、VM2525拍/675退休、CoreMark731130与DDR5295/7714/12987/3847保持不变。
已测不到新增周期成本，不抹掉从staged-payload继承的回复寄存成本。

118SV及相同真实初始化ROM只做一次真正综合前10ns约束的分区综合：06:29:46→06:39:26，
580秒，synth_design479秒；查询06:41:26→06:43:53，147秒，只读两个已有DCP，无再次综合。
46份报告保留15个既有终点族，新增被显露的branch-predictor更新终点。最终功能黑盒0。
结构：ROM外部D.ready→A.ready组合路径1→0；四个仲裁器D.valid→reply source路径4→0；
两个prediction guard及一项两深度ROM reply queue存在，既有CPU67位回复寄存切断保留。
queue flow=true的空回复payload仍可旁路，不将ready切断混同payload寄存。

全局10.890→10.590ns（-2.75%），WNS-0.994→-0.608；TNS-6773.861→-1400.467，失败
25817→12079/135864。逐级审计最差路径后修正：ROB head→pendingException→恢复仲裁，
再次检查选中token→trap/重定向token匹配→completion/退休资格→预测器更新，
40逻辑层/6CARRY8，logic2.291ns、estimated route8.299ns（78.37%）。仍不是物理Fmax。

| 10ns终点族 | 旧→新数据延迟(ns) | 新slack(ns) |
| --- | --- | --- |
| branch predictor | 10.590→10.590 | -0.608 |
| PRF | 10.503→10.503 | -0.521 |
| RAS CE | 10.315→10.315 | -0.419 |
| issue queue | 10.355→10.359 | -0.377 |
| ROB/rename | 10.867→10.289 | -0.307 |
| ready scoreboard | 10.596→10.165 | -0.183 |
| frontend PC | 10.394→10.133 | -0.151 |
| RAS data | 10.054→10.054 | -0.072 |
| fetch adapter CE | 10.890→9.938 | -0.042 |
| pending | 10.446→9.957 | +0.025 |

不能因fetch-adapter数据延迟<10ns就称达标：CE setup仍负；issue queue有4ps回退。
其它已记录：redirect9.369/+0.613，RAS count9.708/+0.274，owner CE8.560/+1.336，
访存地址7.333/+2.650，fetch mask5.318/+4.664，LSU data8.824/+1.158，均见完整16族JSON。
20ns WNS+9.392/TNS0；约150MHz WNS-3.941/TNS-147038.219，失败59936（旧63397）；
未布线WHS+0.006，不能代替整板hold/CDC/RDC。所有范围均未100/150MHz实板验收。

LUT129570→129718（+148/+0.114%），FF61439→61440（+1），RAMB36/DSP37/19不变。
同镜像周期不变是本批代价证据，继承的reply成本仍在；三项组合不作独立因果归因。
下一批沿恢复候选授权、逐槽杀除/保留与重定向token匹配三条相关控制链，保留排序/有效性合同；
PRF bit-manip/writeback单独继续跟踪。不通过抬时钟或放宽约束宣称达标。没有整板route/
bit、full GSIM/Linux、第三域/选频实现；默认/release/IP/clock/reset保持，用户GUI未操作。
导出UART/timebase参数仍50MHz/115200，后续真实100MHz集成必须同步更新与验收。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-fetch-control：results.json/short-tests.json、
61份focused-logs、46份fetch-control-query报告、53份源码快照与同BIN固件。DCP SHA256
880581805e3cb74272b113678ca2f34ffd9ac0f2e455c1e4c5cc8bb705fc5ed4。旧bit不变。

### 2026-10-02 staged-recovery-control：局部控制链改善，全局回退，不推广

继承staged-fetch-control双发射/ROB16/PRF48/LSU2/SB2/tag64。完整路径审计纠正原先
顺序PC推测后，三条相关恢复控制链合批：原始候选并行授权、逐槽kill/completion保留
预计算、local/trap完整token提前匹配。无新增流水周期，默认early-issue不变。
30项Scala、810304恢复/重定向独立向量、8/64位ledger、packet/NEMU/VM、同BIN板模型
CoreMark/DDR通过。26条23字段IPC记录完全相同；VM2525/675、CoreMark731130、
DDR5295/7714/12987/3847也未变。两个helper均纯组合，64位tag与原同龄/陈旧候选
优先级保留；反例与ASan/UBSan不放宽。初次局部变量名称冲突已记录，未进入综合。
补充system验证原固定32/direct-IRQ oracle，全部原断言和两种反例通过。带一拍IMSIC
寄存器的新旧固定32封装都触发相同零延迟eligibility断言，两次日志/FIR保留；直接IRQ
通过不冒充生产注册IRQ时序验收，该合同仍需单独验证。
120SV只做一次真实综合前10ns约束的分区综合：07:34:26→07:48:54，868秒，
synth_design768秒（旧479秒）；最终功能黑盒0。07:50:06→07:52:37仅查询已有DCP，
151秒、49份报告，保留全部16终点族并新增3种恢复链through-path查询，无再次综合。
结构确认并行准入/匹配各1项、16槽kill、2路match；原67位CPU回复寄存、ROM信用和
4层TL元数据切断均保留。恢复准入和token匹配through-path最差7.914ns/slack+1.982，
kill路径5.954ns/+3.942；这不是与旧全局10.590ns相同端点的直接减法比较。

全局10.590→10.931ns（回退0.341ns），10ns WNS-0.608→-0.949；TNS-1400.467→
-2339.994，失败端点12079→4945/135795。失败数下降不代表最差裕量或TNS改善。
新最差ready_30→issue eligible→first/second选择→物理操作数→bit-manip结果选择→
主ALU结果选择→completion/PRF写回，39逻辑层/0CARRY8；logic2.450ns、estimated
route8.481ns（77.59%）。综合共享网名不直接证明某个源码模块就是整条瓶颈。

| 10ns终点族 | staged-fetch-control→本候选数据延迟(ns) | 本候选slack(ns) |
| --- | --- | --- |
| pending | 9.957→10.689 | -0.707 |
| redirect | 9.369→10.228 | -0.246 |
| ready scoreboard | 10.165→9.922 | +0.060 |
| RAS data | 10.054→9.636 | +0.346 |
| RAS CE | 10.315→9.897 | -0.001 |
| RAS count | 9.708→9.290 | +0.692 |
| PRF | 10.503→10.931 | -0.949 |
| ROB/rename | 10.289→9.938 | +0.044 |
| issue queue | 10.359→10.094 | -0.112 |
| frontend PC | 10.133→10.136 | -0.154 |
| fabric owner CE | 8.560→8.784 | +1.112 |
| memory preparation address | 7.333→7.415 | +2.568 |
| fetch mask | 5.318→4.653 | +5.329 |
| LSU data | 8.824→9.048 | +0.934 |
| fetch adapter CE | 9.938→9.938 | -0.042 |
| branch predictor | 10.590→10.172 | -0.190 |

RAS CE和fetch adapter CE仍负，不能仅凭数据延迟<10ns称达标。原head恢复链不再是
predictor最差源，当前ready→退休链仍使其失败；pending/redirect/PRF明显回退完整记录。
20ns WNS+9.051/TNS0；约150MHz WNS-3.941→-4.282，TNS-147038.219→-109791.664，
失败59936→45592。未布线WHS+0.006/hold失败0，不构成物理setup/hold/CDC/RDC签核。

LUT129718→128031（-1687/-1.30%），FF61440→61426（-14），LUTRAM1346、RAMB36/DSP
37/19保持。三条链一起变化不作单项因果归因。26完整IPC与同BIN周期无新成本，但
继承CPU回复寄存的CoreMark+3.31%/VM+11.68%成本仍在；不是实板频率×IPC正收益证明。
本候选不推广，较好全局参考仍staged-fetch-control。下一批联合处理ready/eligible→
双发射选择/操作数、bit-manip→主ALU双层结果选择、completion→PRF写回；不能简单
重启已测过资源/时序不佳的one-hot物理读端方案。继续必要短测后一次联合综合。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-recovery-control：results.json、
short-tests.json、49份DCP报告、62源码快照、同BIN固件及四组范围明确的日志目录。
120SV清单SHA256 776fea04542bc7b6928fb4428ab41585fbb5c6644bcd94cf95359a710be2df13；
DCP349d6672a8fac61a51a45c5726e4f1c67bf4b8f74694e7d51370b809f2eb2ba5。参数仍
50MHz/115200；无route/bit/IP/clock/reset/默认修改，发布bit不变。生产注册IRQ时间合同、
真实100/150MHz整板setup/hold/CDC/RDC与运行均未验收，第三域/选频/DFS未实现。

### 2026-10-02 staged-execute-select：三条执行/写回链完成短测，单次综合中

继承recovery-control双发射/ROB16/PRF48/LSU2/SB2/full64tag，组合改造first→second
发射依赖、B结果→主ALU的双层priority选择、completion来源→PRF的payload优先链。
循环前二名用关联(any,atLeastTwo)前缀并行计算；base/B互斥结果合并，共用address/
rotate aliases；写回保持LSU>divider>multiplier>system>held branch>ALU，包含未授权
来源的原payload选择行为，全部字段一起选择。所有valid/完整token/exception授权、
排序和状态修改条件仍保留；不加拍/容量、不重启one-hot物理PRF读端、不改默认/release。

必要范围汇总通过：33项Scala；16/32槽独立扫描28736/87648向量；1087008算术向量
（含653861非法控制/word组合）；20384完整payload向量/16590重叠来源，8个反例。
原packet/NEMU（282程序、380429提交、185224 decoder）、fixed32/direct-IRQ system、
VM和一个共用板模型通过，ASan/UBSan保持。初次展开.pad要求失败、随后新驱动缺少
Memory/dataBase header依赖均留档，只修宽度边界/驱动上下文，未改ISA/NEMU oracle。
33项Scala复用通过记录后只补七组行为检查，raw runtime JSON是partial-pass，不能
伪称一次全跑通过。生产注册IMSIC时间合同仍未验收，不借direct-IRQ补测抹掉缺口。

26条完整23字段IPC完全相同；VM2525/675、CoreMark731130、DDR5295/7714/12987/3847
均保持。CoreMark单轮是CRC/周期回归，不是正式分数；合成AXI不是实板带宽。继承的
CPU回复寄存成本仍在，周期不变不代替频率×IPC实板证明。

121SV于08:31:43启动唯一一次综合，synth_design之前已加载真实10ns XDC，8线程。
当前仍在运行，时序/面积结果待测；只在同DCP上增加第二issue rank、ALU result和
completion payload报告，保留原16终点族及3种恢复查询，不删回退项或放宽约束。
证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-execute-select：72份源码/oracle
快照、48份focused日志、前置失败日志、同BIN固件、short-tests.json与results.json。
RTL清单SHA256 d09a5bf9609be9b7788171943977afb490f374bc55ad714a23890fad42d3652d；
源码清单665b9c894e8a38f377f2688c98892da6b425825bc201971281c32e71da62ada5。
没有route/bit，IP/clock/reset/released bit不变，UART/timebase导出参数仍50MHz/115200。
100/150MHz整板/实板、第三外设域、启动选频与DFS仍未验收/实施。

### 2026-10-02 staged-frontend-select：三条相邻前端链，必要短测通过，时序待测

在staged-execute-select上同批改造：静态set全64位地址/context tag命中；
独立canonical控制流class/immediate预译码；同包AUIPC/JALR的对齐及非顺序预测资格。
三个开关默认false，不改变缓存数据/fault选择、精确后端decode、完整target值或
恢复所有权。固定双发射，无新增寄存器/流水周期，板级50MHz/115200及IP/reset/bit不变。

36项Scala、九组必要短测一次通过，277728独立向量与10个负注入拒绝保留。
26条各23字段IPC逐行完全相同；VM2525/675、同BIN CoreMark731130及DDR
5295/7714/12987/3847不变。一个板模型复用；CoreMark一迭代不是正式分数，
DDR为合成AXI模型而非实板带宽。direct-IRQ system不关闭生产注册IRQ时间合同缺口。

证据E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-frontend-select：
196份冻结源码（含全部main Scala）、78份逐字节校验的日志/FIR/固件、
short-tests.json/results.json/archive-index.json。当前工作树已前进；上一候选的
72份源码快照和121SV仍按原清单一致，运行中综合不是这个新候选。为避免争用，不启动
第二次综合。新候选尚未导出/SYN，时序/面积未知，不推广默认、不宣称100/150MHz达标。

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

### 2026-10-02 清理、局部定位及一次有界综合：10ns仍未过

本节覆盖上文“新候选未导出/综合”的历史状态。按用户本次授权，旧九批GSIM的
278个可再生模型/对象/可执行文件移除（932954165字节），日志/FIR/固件保留。
旧失败.Xil的155文件先压缩、逐项核对并验证最大tim解压哈希，再删除原目录；
failed-synthesis-xil.zip保留46123576字节，整体净释放1466325915字节（约1.37GiB）。
不删源码、用户改动、旧RTL输入、DCP、bit或时序/面积报告；当前GSIM输出未清理。
详单E:/VM/Share/Valence-rtl/ddr-opt-20261002/cleanup-20261002.json。

旧execute候选的rank/ALU/completion独立synth_design分别42/61/28秒完成，LUT
203/2264/849；总3分钟保护在completion后续时序报告阶段触发，不是其综合失败。
局部成功不能排除整图优化异常，未证明唯一模块/工具缺陷/死锁。

已短测的新staged-frontend-select一次导出124SV（50MHz/115200，双发射），
195个此前测试输入在导出前核对不变；综合流程单独冻结。采用预映射10ns约束、
RuntimeOptimized和debug_log，25分钟进程树保护；11:18启动、11:25正常结束，
保护总430.5秒，synth_design308秒，exit0，无残留CLI任务。未用no_timing_driven；
未改变CPU时钟IP/复位/发布bit，也未重复GSIM/Linux/整板route或生成bit。

导入相同初始化ROM后无功能黑盒，UART两级同步单元保留ASYNC_REG。候选DCP
SHA256=89b084f2088b1d64e377952af900791aafe71a0d17d46c94e916170cf1c80861。
一次全查询173.3秒输出50报告后因错误期待3个综合网表lookup而停止；只读检查
确认RTL有3个、板级DCP保留2个，predecode/guard分别2/1仍在。查询修正版固定
实际综合网表数量，73.7秒仅补7个缺失报告，总57份；未重综合或覆盖原失败日志。
返回寄存器67输入/67输出无flow-through、PMP地址不受晚invalidate影响但valid受控、
ROM外部ready和TL晚valid到source均无组合反馈；first-rank→second-rank为0路径。

全局10ns：CPD10.295ns、WNS-0.313ns、TNS-68.758ns、2062/139350失败端点；
hold WNS0.006ns、0失败。20ns WNS9.687ns；约150MHz（周期舍入6.667ns）
WNS-3.646ns。此前最佳fetch为10.590/-0.608，最近recovery为10.931/-0.949；
本轮度量更好，但仍未通过10ns，而且Default→RuntimeOptimized策略同时变化，
不得将全部改善归因于RTL，或由CPD倒数宣称实板稳定Fmax。

| 终点族（完整路径） | recovery DCP ns | 本轮 DCP ns | 本轮 WNS ns |
| --- | ---: | ---: | ---: |
| rob | 9.938 | 10.295 | -0.313 |
| prf | 10.931 | 10.181 | -0.199 |
| pending | 10.689 | 9.786 | 0.196 |
| redirect | 10.228 | 8.741 | 1.241 |
| scoreboard | 9.922 | 9.712 | 0.270 |
| issue_queue | 10.094 | 10.008 | -0.026 |
| frontend_pc | 10.136 | 10.005 | -0.023 |
| ras_data | 9.636 | 9.285 | 0.697 |
| ras_enable | 9.897 | 9.546 | 0.350 |
| ras_control | 9.290 | 8.939 | 1.043 |
| fabric | 8.784 | 8.773 | 1.123 |
| preparation_address | 7.415 | 7.583 | 2.400 |
| fetch_mask | 4.653 | 4.876 | 5.106 |
| lsu_data | 9.048 | 9.030 | 0.952 |
| fetch_adapter_state | 9.938 | 9.871 | 0.025 |
| branch_predictor | 10.172 | 9.821 | 0.161 |

新增through报告是完整寄存器路径而非模块固有延迟：tag/control到PC均10.005ns，
AUIPC资格到PC8.851ns；second-rank、ALU、completion到PRF均10.181ns。
当前最差PC[4]→tag命中/指令选择→控制资格/后端准入→RAT[31][0]为10.295ns，
39级逻辑，逻辑2.603ns、未布局估算连线7.692ns（74.7%）。
下一批优先联合优化取指到RAT/ROB、操作数/ALU到PRF写回及预测PC/队列输入；
保护fetch state CE仅0.025ns的余量，不再仅盯已转正的redirect/RAS。

BoardSocTop OOC资源LUT130936、FF63205、RAMB36/DSP37/19；比此前最佳LUT+1218、
FF+1765，比recovery+2905/+1779。此范围不含整板MIG/MMCM/异步AXI转换器；
不是免费优化，也不做默认晋级。注册IMSIC时间合同、实际100/150MHz的MMCM/
UART/timebase/固件及整板setup/hold/CDC/RDC/板测仍待验收。第三域/DFS未实现。
完整结果、57报告哈希、流程快照和原始日志在staged-frontend-select/results.json、
checkpoint-query/reports与synthesis-flow-snapshot；旧异常现场迁移信息已补记诊断JSON。

### 2026-10-02 staged-sensitive-paths：三组合并验收，仍未达10ns

按用户要求，本轮将剩余超标及薄裕量链一并纳入三组结构修改，再跑必要短测、
一次导出和一次全SoC综合。基线为上一轮staged-frontend-select，二发射/ROB16/
PRF48/tag64/LSU2/SB2和cache/predictor容量不变，仅新增三个默认关闭的选项：

- parallelPredictionSources：已知间接/返回/间接表/PC-relative各自做对齐和
  successor比较，再合并原存在优先级。高优先级赢家不合格不能退到低优先级；
  full64目标/精确异常/kill合同不变，组合逻辑不加拍。
- parallelAddressSums：七种Zba固定移位/unsigned-word加法并行，最终按opcode选择；
  消除opcode及UW选择后才启动公共加法器的串行链，保留full64 carry/wrap及原非法W
  数值语义，无新execute寄存器，付出加法器面积。
- bufferedFetchRequests：翻译后物理取指接两项非flow、非pipe请求队列；
  occupancy-only ready断开cache/TL ready到翻译状态CE。64位地址与2/4字mask原子保存，
  response/data/error/pageFault及其反压直通原边界，不提前释放响应owner/TL source。
  容量2、II1，物理取指请求延迟增加1拍；不是所有指令固定增加1拍。

必要验收：39 Scala/8 suites，4096预测优先级向量（735 blocked-winner）；
2/4字请求各14337笔全部完成、峰值2、1000笔流、4386 ready-isolation，
覆盖零mask、精确fault、立即回复、满队列复位；1087008独立ISA算术向量和20384
completion竞争向量通过。九个负向oracle日志均保留，注入错误必须被拒绝。
20个prediction程序、core/system NEMU、VM data及跨页取指通过；
26条bare-core IPC记录全部23字段逐项一致。首次测试夹具漏Cat import而编译失败，
修复后r1整批通过；保留原contracts.log，不称为无错误首轮构建。

板级模型只生成一次复用两个原BIN。VM首trap2525→2530拍，均675退休（+0.20%）；
固定窗口commits1007→1002不能当作功能失败。CoreMark单次731130→761601拍
（+4.17%，同频模型吞吐约-4.00%），DDR read/write/copy/chase：
5295/7714/12987/3847→5323/7733/13006/3849（+0.53/+0.25/+0.15/+0.05%）。
BIN SHA与基线相同；CoreMark仅1次且原始短运行/Errors detected警告保留，
harness检查既定3项CRC和退出。不是合规CoreMark得分或实板DDR带宽。
bare-core不经过新增物理请求队列，IPC一致不代表板级周期零损失。

一次导出127 SV，实际配置仍50MHz/115200/DDR/双发射/2-way/prefetch1。
冻结203源码/流程输入；同RuntimeOptimized、预映射10ns、flatten none、debug_log、
maxThreads8，与直接基线的策略相同。单次有界综合正常完成：总484.5秒，
synth_design376秒；初始化ROM已导入，功能黑盒0，UART ASYNC_REG两级。
一次只读DCP查询178.6秒，59报告全部齐全，未重综合/route/生成bit。

10ns全局CPD10.295→10.291ns，WNS-0.313→-0.309ns，
TNS-68.758→-5.783ns，setup失败2062→244/139507；hold WHS+0.006、失败0。
20ns WNS+9.691；150MHz（6.667ns）WNS-3.642。以下为完整寄存器路径，
不是模块固有组合延迟，不能因CPD略低于10就忽略WNS。

| 终点族 | 同策略基线 ns | 本轮 ns | 本轮WNS ns |
| --- | ---: | ---: | ---: |
| rob | 10.295 | 10.291 | -0.309 |
| prf | 10.181 | 9.934 | 0.048 |
| frontend_pc | 10.005 | 10.014 | -0.032 |
| issue_queue | 10.008 | 9.538 | 0.444 |
| fetch_adapter_state | 9.871 | 6.562 | 3.334 |
| pending | 9.786 | 9.782 | 0.200 |
| scoreboard | 9.712 | 9.708 | 0.274 |
| branch_predictor | 9.821 | 9.557 | 0.425 |
| ras_data | 9.285 | 9.021 | 0.961 |
| ras_enable | 9.546 | 9.282 | 0.614 |
| ras_control | 8.939 | 8.675 | 1.307 |
| fabric | 8.773 | 8.773 | 1.123 |
| preparation_address | 7.583 | 7.583 | 2.400 |
| fetch_mask | 4.876 | 4.876 | 5.106 |
| lsu_data | 9.030 | 9.030 | 0.952 |
| redirect | 8.741 | 8.741 | 1.241 |

second-rank/ALU/completion均10.181→9.934ns（WNS+0.048，仅48ps，仍脆弱）。
reply→fetch9.869→9.651；request credit1.228（+8.754）；预测源/control到PC
9.531（+0.451）。但tag→PC10.005→10.014，AUIPC资格through8.851→9.232、
response storage6.383→6.452有回退；不把全部改动都描述为改善。
综合网表保留预测源助手2、请求缓冲1，downstream ready→upstream ready路径0；
响应67字段组合流通0、first→second rank0、invalidate→PMP地址0且valid kill路径1、
ROM外部D.ready反馈0、晚D.valid→source0、完整completion selected-data64均通过。

最坏路径仍PC[4]→tag命中/压缩指令选择→lane1合法性译码/rd资格→rename准入→
RAT31[0]，逻辑39→35级/2.603→2.185ns，但估算连线7.692→8.106ns（78.8%）
抵消收益。剩两族RAT和PC负裕量；PRF刚转正也不等价于route后安全。
下一批应切取指/预译码元数据到rename的依赖和tag到PC反馈，并保护PRF48ps，
不要继续只加速已经转正的预测资格，或只加拍而不测周期代价。

OOC LUT130936→131750（+814），FF63205→63204（-1），RAMB36/DSP37/19不变；
不含整板MIG/MMCM/AXI CDC。约0.04%的OOC周期估算改善不足以抵消CoreMark+4.17%
周期成本，按周期归一投影约-3.96%，且投影不是实际frequency×IPC证明。
候选保留但不晋级默认/发布bit，不能宣称100MHz或整体正优化；
注册IMSIC时间合同、整板setup/hold/CDC/RDC及板测未验，第三域/DFS未实现。

证据：E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-sensitive-paths/
results.json、short-tests.json、short-raw（86原始文件）、timing-comparison.json、
checkpoint-query/reports（59份），source/rtl-manifest.sha256与源码/流程快照。
DCP SHA256：99f867ea6284e1afdd7d727bbb3217961e0ce48e65a989e51c780f7903d3aca7。
本轮不再次清理历史资料；原GUI、默认配置、时钟IP及已发布bit不变。

### 2026-10-02 staged-decode-align：一轮合并完成，PC转正、周期回收，10ns尚未达标

直接基线staged-sensitive-paths，继续二发射/ROB16/PRF48/tag64/LSU2/SB2及原
cache/predictor容量；四个默认关闭选项分成三组，一次修改完成后才跑必要短测和
一次综合。没有新增execute或fetch流水级，不改ISA/例外/owner/默认/IP/板级约束。

- 前端/RAT/PC：parallelFetchAlignment在原三包窗口预备固定半字起点，
  lane1的+2/+4两种位置先并行对齐，再由lane0长度选；不让presence参与raw指令
  payload。parallelDecodeLegality按独立指令类合并合法性，原B合法性输入、
  operation优先级及完整IntegerRequest数值/字段保留。两个助手均容量/延迟0、II1；
  精确access/page fault偏移和kill语义不变。宽4只是助手/取指覆盖，不是四发射CPU验收。
- 请求隔离/周期回收：flowThroughFetchRequests在已有两项队列启用空队列直通；
  pipe=false、enqueue-ready仍只由占用决定，满队列不借dequeue credit。
  容量2/II1，空且下游ready时请求延迟0，入队后注册；response/error/pageFault、
  response backpressure和TL source/owner规则不变。不是CDC或加一套响应缓冲。
- PRF薄裕量：parallelMinMaxResults以MIN/MAX/MINU/MAXU及full64比较直接资格化
  左/右operand，再接共享result网络；保留有符号/无符号比较和外层W截断/符号扩展，
  不加寄存器或算术周期。此次综合网表未带来最坏PRF路径改善，见回退项。

短测合并覆盖12个范围：42 Scala/9 suites；655552译码向量、四种system/atomic配置、
192 privileged及完整request等价；2/4宽各131072对齐向量（混合长度/跨包/fault）；
2/4字各14337请求、峰值2、4386 ready-isolation、1000流/立即回复、零mask、
满/复位；1087008独立算术/20384竞争向量；prediction、core/system NEMU、
VM data/跨页取指及单个板级模型复用两个BIN。14份负向oracle日志保留，注入必须拒绝。
首次夹具getter少一个$导致C++编译失败；仅修夹具后续跑未完成9范围。
首次raw JSON仍failed，续跑raw JSON仍partial-pass；汇总passed不是伪造一次无失败整批。

26条bare-core IPC的23字段与直接基线逐项一致。原BIN SHA不变：
CoreMark单次761601→731130拍（周期-4.00%，同频模型吞吐+4.17%）；
DDR read/write/copy/chase5323/7733/13006/3849→5295/7714/12987/3847；
VM首trap2530→2525拍，均675退休，固定窗口commits1002→1007。
这些数恰好恢复更早staged-frontend-select，不称作比该基线提升4.17%。
CoreMark仅1次，原ERROR<10s/Errors detected文字保留，既定CRC/退出PASS；
不是官方得分/实板DDR带宽/完整Linux启动。

209份源码/测试/流程输入冻结；一次导出129 SV（另1资源列表），实际仍
50MHz/115200/DDR/二发射/2-way/prefetch1。同RuntimeOptimized、预映射10ns、
flatten none、debug_log、maxThreads8，唯一综合425.4秒（synth_design314秒）。
真实初始化ROM导入、功能黑盒0、UART同步级ASYNC_REG两项，无第二次综合或route/bit。

报告查询首次152.6秒生成54份后因旧tag助手计数2而中止；新固定对齐DCP保留3个。
只修可复用查询的profile专属计数，再用同DCP补7份（79.3秒），共61份。
原失败日志/冻结查询不覆盖；修复源码、补充脚本在report-query-fixes独立留SHA。
所有硬件/夹具冻结输入不变；此报告计数修复不是DUT或oracle放宽。

全局10ns CPD10.291→10.178、WNS-0.309→-0.196，失败244→106/139494。
TNS-5.783→-12.991反而变差：失败更少不代表总负裕量改善。
20ns WNS+9.804/失败0；150MHz（实际6.667ns）WNS-3.529/失败45267。
hold WHS+0.006、失败0只是无物理时钟网络的OOC估计，不是整板hold验收。

| 终点族 | 同策略基线 ns | 本轮 ns | 本轮 WNS ns |
| --- | ---: | ---: | ---: |
| rob | 10.291 | 10.178 | -0.196 |
| prf | 9.934 | 9.941 | 0.041 |
| frontend_pc | 10.014 | 9.795 | 0.187 |
| issue_queue | 9.538 | 9.634 | 0.348 |
| fetch_adapter_state | 6.562 | 6.574 | 3.322 |
| pending | 9.782 | 9.564 | 0.418 |
| scoreboard | 9.708 | 9.921 | 0.061 |
| branch_predictor | 9.557 | 9.555 | 0.427 |
| ras_data | 9.021 | 9.019 | 0.963 |
| ras_enable | 9.282 | 9.280 | 0.616 |
| ras_control | 8.675 | 8.673 | 1.309 |
| fabric | 8.773 | 8.773 | 1.123 |
| preparation_address | 7.583 | 7.583 | 2.400 |
| fetch_mask | 4.876 | 4.876 | 5.106 |
| lsu_data | 9.030 | 9.030 | 0.952 |
| redirect | 8.741 | 8.724 | 1.258 |

ALU/second-rank/completion同PRF9.941/WNS+0.041。PC/tag反馈10.014→9.795已转正；
pending9.782→9.564。但PRF9.934→9.941（48ps缩至41ps），scoreboard9.708→9.921
（274ps缩至61ps），issue queue9.538→9.634，fetch state6.562→6.574、reply→fetch
9.651→9.683也有回退。不能描述为“所有路径改善”。
qualification/control到PC分别8.751/9.310；request credit1.238；response storage/credit
6.452/8.587。预测源through最坏终点转到RAT，9.588不是子模块固有延迟。
以上全部为完整寄存器路径；WNS使用原报告，不以10-CPD代替setup/CE/时钟项。

残留主链为PC[4]→tag/raw instruction alignment→lane0 B-operation-derived合法性→
writesRd/fresh→第二物理destination选择→free16；RAT对应10.174/WNS-0.192。
逻辑35级/2.449ns，估算连线7.729ns（75.9%）；旧lane1串行位置选择不再是唯一问题。
最靠近10ns的正族PRF仅41ps，其次scoreboard61ps，不足以证明布局布线后稳定。
下一批重点独立B合法性与operation优先编码、缩短第二destination/free/RAT准入依赖，
同时处理signed-less→MIN/MAX/W结果→PRF及晚destination→scoreboard；先保持二发射。

综合网表：aligner1/legality助手2/64 aligned bits/192 RAT pins、tag3/control2/AUIPC1；
预测源2/请求缓冲1且downstream-ready→upstream-ready路径0，first→second rank0，
响应67字段组合流通0、invalidate→PMP地址0且valid kill1、ROM外部D.ready反馈0、
晚D.valid→source0、完整completion selected-data64等既有隔离检查保持。
未用false path/multicycle/更改约束遮盖负裕量。

OOC LUT131750→132330（+580，+0.44%），FF63204→63206（+2），
RAMB36/DSP37/19不变，LUTRAM1386/URAM0；不含整板MIG/MMCM/AXI CDC。
本轮同频周期回收成立；若按未布局CPD归一，相对直接基线吞吐投影约+5.32%，
相对更早frontend-select约+1.15%。这不是实板frequency×IPC收益，10ns仍负且
PRF/scoreboard薄，故不晋级默认、不发布新bit；实际100/150MHz、注册IMSIC时间、
整板setup/hold/CDC/RDC仍未验收，第三域/DFS未实现。

证据：E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-decode-align/
results.json、short-tests.json、short-raw（122原始文件）、timing-comparison.json、
checkpoint-query/reports（61份）、query修复快照及source/rtl-manifest.sha256。
DCP SHA256：5f10d020945559c70cba20d8c0c00c308a5719f194b993daed6a396249511967。
未删除文件；原GUI、旧bit、默认配置、MMCM/MIG及独立用户改动不变。

## 2026-10-02：重命名/ALU批量收尾与回退修正

staged-word-destination（两发射，ROB16/PRF48）完成48项Scala检查、8类受影响短测和一次修正批综合；本次OOC 10ns setup仍未满足。 未route或上板，不能据此宣称实板100MHz稳定。

首批staged-rank-legality同时处理B固定字段合法性、独立free-list ranks和MIN/MAX早W载荷。MIN/MAX路径降至9.604ns、scoreboard降至9.427ns，但统一结果汇合暴露Zba路径10.253ns（WNS -0.271，TNS -130.564，996端点），不能按局部改善晋级；ROB/RAT仍10.042ns。失败综合/DCP/64份查询和96原始短测文件完整保留。该批单次综合499.5s，synth_design380s，查询178.3s。

修正候选在原批上只启用parallelArchitecturalDestinations与parallelAluWordResults：

- 原始expanded rd仅用于早选择、fresh准入和RAT索引；合法性/writesRd/accepted/rollback仍控制实际状态，公开译码、ROB与退休payload不变。每个合法writer断言raw rd与公开rd相同；独立ledger夹具故意给非writer不同raw rd，验证它不会产生写入。
- Zba固定移位加法独立通过addressResult，不再经过计数/rotate/逻辑操作的结果树；基础ALU、其余B和Zba逐类准备W结果后汇合。完整64位MIN/MAX比较、非法W数值兼容、x0、精确异常和backpressure不变。
- 无新寄存器/执行周期、II仍1；没有扩发射或增大ROB/PRF/cache。

| 路径家族 | decode-align基线 ns | 首批 rank-legality ns | 修正候选 ns | 修正候选WNS ns |
|---|---:|---:|---:|---:|
| alu_result | 9.941 | 10.253 | 9.449 | +0.533 |
| branch_predictor | 9.555 | 9.558 | 8.560 | +1.422 |
| fabric | 8.773 | 8.773 | 8.555 | +1.341 |
| fetch_adapter_state | 6.574 | 6.574 | 6.793 | +3.103 |
| fetch_mask | 4.876 | 4.876 | 4.876 | +5.106 |
| frontend_pc | 9.795 | 9.764 | 9.429 | +0.553 |
| issue_queue | 9.634 | 9.289 | 9.357 | +0.625 |
| lsu_data | 9.030 | 9.030 | 8.812 | +1.170 |
| pending | 9.564 | 9.533 | 8.822 | +1.160 |
| preparation_address | 7.583 | 7.583 | 7.380 | +2.603 |
| prf | 9.941 | 10.253 | 9.449 | +0.533 |
| ras_control | 8.673 | 8.676 | 7.678 | +2.304 |
| ras_data | 9.019 | 9.022 | 8.024 | +1.958 |
| ras_enable | 9.280 | 9.283 | 8.285 | +1.611 |
| redirect | 8.724 | 8.741 | 8.104 | +1.878 |
| rob | 10.178 | 10.042 | 9.451 | +0.531 |
| rom_request_credit | 3.782 | 3.782 | 3.782 | +6.018 |
| scoreboard | 9.921 | 9.427 | 9.125 | +0.857 |
| second_issue_rank | 9.941 | 10.253 | 9.449 | +0.533 |

全局：CPD 9.915ns，WNS -0.115ns，TNS -9.228ns；setup失败80/139476，WHS +0.006ns，hold失败0。20ns WNS +9.885；6.667ns WNS -3.448，不宣称150MHz。

最差起点：`platform/physicalRequests/requests/deq_ptr_value_reg/C`；终点：`platform/physicalFetch_requests/requests/ram_ext/Memory_reg_0_1_0_13/RAMA/WE`。所有新through-path、旧模块家族及回退见timing-comparison.json；没有false_path/multicycle/改变DUT的报告技巧。

资源：LUT 133607（相对直接decode-align +1277个），FF 63196，RAMB36 37，RAMB18 0，URAM 0，DSP 19。这是SoC OOC分区，不含MIG/MMCM/AXI CDC。

必要短测：48 tests/11 suites；ALU arithmetic1087008/illegal653861/arbitration20384，ledger两个tag宽度各18000随机周期、prediction20程序、NEMU282程序、system34程序、coherent VM及共用单个board模型的两个固件均PASS；6个负向oracle被正确拒绝。26个IPC场景各23字段与decode-align原始日志完全一致。CoreMark同BIN仍731130ticks（1次CRC/exit短回归，原始小于10秒ERROR保留，绝不是正式分数）；DDR同BIN四项5295/7714/12987/3847，VM2525cycles/675retired，均无周期回退。

源码/构建/夹具228个输入、131SV+1resource、70原始日志/固件文件及66份DCP查询分别有SHA256索引。首批C++覆盖循环误置和修正批require参数名笔误的失败日志/最初manifest/单文件overlay都保留；修复未改独立ISA/NEMU/ledger oracle。原始failed/partial-pass/passed JSON未篡改，聚合结果另记。

综合流程：预映射10ns XDC、RuntimeOptimized、flatten none、debug_log、maxThreads8；修正批仅1次全综合，synth_design 597s，总725.7s；随后同DCP查询267.7s。ROM stub阶段Project 1-486警告通过真实初始化ROM导入后消除，最终BB=0；UART两级ASYNC_REG=2。RAM collision/pipeline及OOC HD.CLK_SRC警告保留，物理存储/时钟边界不视为已验收。

默认/发布保持50MHz、115200，未改MMCM/MIG/ROM内容、未生成bit、未跑全量GSIM/长Linux；注册IMSIC temporal、真实DDR/CPU频率变化下IPC、整板setup/hold/CDC/RDC、第三域/DFS及实板高频仍未验收。

证据：E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-word-destination/；results.json、short-tests.json、short-raw-index.json、timing-comparison.json、timing-report-index.json、source/rtl-manifest.sha256和final-verification.json。修正DCP SHA256：bcc0ca9dc97dc39addac4fefa1baa262b16e74f8bd04d68e1fc65751fc6d0017。

补充：CPD9.915ns只含数据路径，不能忽略RAM setup与时钟项，因此WNS仍-0.115ns。当前CPU三项目标已经满足OOC10ns，下一批集中physicalRequests.dequeue→physicalFetch_requests.RAM WE的请求/credit/grant链，而非再次给CPU增加执行流水级。

一次opt_design Explore复用DCP（21s逻辑优化、总94.6s）省3435 LUT/1267 FF，但WNS退到-0.147，80端点仍失败；未选为时序主候选，未重新综合。主候选66报告来自保留的57份初次查询+9份补充；过宽NAME筛选误含11036个内部LUT引脚，修正为模块boundary REF_PIN_NAME后10/128接口断言通过。原始两次查询失败日志、源脚本、补充日志及优化DCP都保留；补充在未选优化DCP上失败的helper计数不影响已完成的主候选66报告，也未放松DUT合同。live仅report_redirect_stage.tcl查询修正不同于冻结228输入；227其余输入与RTL仍一致。

最终只读负端点审计：get_timing_paths逐一检查全部80个负setup端点，80个都位于physicalFetch_requests/requests/ram_ext的WE，其他模块负端点0；审计58.0s、exit0，原始列表见negative-endpoint-audit/synth.log。这是全负端点核对，不是仅根据前30条路径推断。

## 2026-10-02：staged-request-capture 通过综合阶段10ns，仍保留薄裕量风险

本批保持两发射/ROB16/PRF48，继承staged-word-destination，仅新增默认false的
independentFetchCapture和parallelHomeQualification。三组相关修改一次合并：

- 深度2的取指请求队列保持flow=true/pipe=false、满队列不借dequeue credit。
  每次upstream fire均捕获地址/mask，即使该请求已空队列直通；未入队的数据不可见。
  RAM WE只依赖valid与本地occupancy，指针仅在真实push/pop更新；空直通仍0拍、
  排队后1拍、II1，响应/精确fault/backpressure与旧队列相同。
- 一致性目录两路完整物理tag先并行比较，再做owner选择，移除
  selected-index→selected-tag→再比较的反馈。owned位仍是命中授权，目录容量/状态不变。
- 静态RAM窗口以精确半开区间的aligned-prefix集合译码，替代65位大小比较carry；
  非对齐0x80200000起始512MiB以及高64位地址均保持，不截断XLEN。

必要短测一批通过：51 Scala/12 suites、2/4字各14337随机请求、三个窗口各120000
独立地址/tag向量、5个注入反例、虚拟取指/跨页、coherent VM，以及一个板级模型
复用跑CoreMark和DDR。独立旧FIFO/oracle/固件未修改。相同BIN CoreMark731130ticks、
cyclesWithUart3621582；DDR5295/7714/12987/3847ticks、cycles3679633；
VM2525cycles/675retired，均与上一版相同。本次未重跑未改的bare-core NEMU/26项IPC，
旧验收保留但不能称本次重新验证。CoreMark小于10秒的原始ERROR仍保留，非正式分数；
AXI模型不是实板DDR带宽。

一次预映射10ns、RuntimeOptimized、flatten none、debug_log、8线程OOC：
synth_design574s、整流程700.7s；真实初始化ROM导入后功能BB=0，UART ASYNC_REG=2。
复用两个原DCP189.1s完成71份数值非空报告（exit0），无重综合/route/bit，
无新增false_path或multicycle。完整负端点查询0，与全局TNS失败0一致。
downstream ready→native RAM WE路径0，ready→enqueue ready路径0，WE引脚85个。

| 路径家族 | word-destination ns | request-capture ns | 新WNS ns |
|---|---:|---:|---:|
| alu_result | 9.449 | 9.449 | +0.533 |
| branch_predictor | 8.560 | 8.560 | +1.422 |
| fabric | 8.555 | 8.555 | +1.341 |
| fetch_adapter_state | 6.793 | 6.793 | +3.103 |
| fetch_mask | 4.876 | 4.876 | +5.106 |
| frontend_pc | 9.429 | 9.429 | +0.553 |
| instruction_capture_state | 9.692 | 9.516 | +0.466 |
| instruction_capture_we | 9.915 | 1.011 | +8.789 |
| issue_queue | 9.357 | 9.357 | +0.625 |
| lsu_data | 8.812 | 8.812 | +1.170 |
| pending | 8.822 | 8.822 | +1.160 |
| preparation_address | 7.380 | 7.380 | +2.603 |
| prf | 9.449 | 9.449 | +0.533 |
| ras_control | 7.678 | 7.678 | +2.304 |
| ras_data | 8.024 | 8.024 | +1.958 |
| ras_enable | 8.285 | 8.285 | +1.611 |
| redirect | 8.104 | 8.104 | +1.878 |
| rob | 9.451 | 9.451 | +0.531 |
| rom_request_credit | 3.782 | 3.784 | +6.198 |
| scoreboard | 9.125 | 9.125 | +0.857 |
| second_issue_rank | 9.449 | 9.449 | +0.533 |

全局CPD9.915→9.748ns，WNS-0.115→+0.234ns，TNS-9.228→0，setup失败80→0/
139478；WHS+0.006、hold失败0。20ns WNS+10.234；6.667ns WNS-3.099，仍不满足150MHz。
最差起点为platform/romManager/produced_replies/deq_ptr_value_reg/C，
终点platform/fetchCache/fallback/beats_0_reg[0]/D。32级组合中logic2.040ns、
未布局route估计7.708ns（约79%）；综合正裕量不构成整板/实板100MHz证明。

相邻ROM reply→next fetch address的through报告CPD9.683→9.685ns、WNS+0.117→+0.297；
数据延迟没有下降，slack改善部分来自RAM WE换成FDRE D的终点setup预算，不能冒充
同终点组合链全面缩短。全局ROM反馈仍仅+0.234，取指指针+0.466，
ROB+0.531、ALU/PRF+0.533，也需布局布线核对。所有旧CPU家族保持上一版结果；
ROM request credit CPD微增0.002ns，完整增减/新through路径见timing-comparison.json。

资源LUT133607→133576（-31），FF63196→63197（+1），LUTRAM1386、
RAMB36/RAMB18/URAM/DSP为37/0/0/19；不含MIG/MMCM/AXI CDC。
空bypass多一次不可见RAM写，动态功耗未测，不能宣称功耗零成本。

本批完成合并修改/短验收/一次综合及DCP审计，但不能声称边缘风险全部消除：
下一结构目标是ROM reply/source→D ownership→d1Fire→下次请求decode/grant/ready→
active1/beat写回的同周期回环，需增加真实裕量。整板setup/hold/CDC/RDC、
时钟/IP/IO约束与实板高频仍未验收；不晋级默认/发布，不改50MHz/115200稳定bit或GUI。
第三固定外设域、启动选频和运行态DFS均未实现，DRP保持关闭。

证据：E:/VM/Share/Valence-rtl/ddr-opt-20261002/staged-request-capture/，
232个输入、131SV+1resource、66原始文件及71报告均有哈希索引。
DCP SHA256：e2b10b941f6b399c041e131edbe38f9f4253cfdc1b078abafd833d1aa79fdf4e。

## 2026-10-02：request-capture 整板 DDR100 / UART460800，未交付 bit

用户明确选择 CPU 100 MHz，并要求整板时序通过才交付。本次沿用两发射
staged-request-capture，生成真实 100 MHz MMCM、128 KiB 初始化 ROM、异步 AXI
clock converter；复用复制到独立候选目录的原 MIG，不改用户工程/IP/GUI。
CPU 时钟实际 10 ns、MIG UI 4 ns；DRP 仍关闭，不是动态频率实现。

与本次 RTL 匹配的 BootROM/UART 短回归通过：连续 8N1、下载校验/重传/边界、
RAM sample 执行等，16,775,778 cycles。原短测在 100 MHz 下用固定 300 万周期
等不足 50 ms 的坏帧排空，误报超时；按 CPU_HZ/UART 帧长度修正等待预算后通过，
未改变 RTL、独立功能 oracle 或下载协议。失败日志和修正后 PASS 均保留。
主机侧 24 项镜像/loader/ROM 单元检查通过。未跑全量 GSIM 或长 Linux 仿真。

本次真实 ROM 导入后的 SoC OOC 仍是 WNS +0.234 ns、TNS 0、WHS +0.006 ns、
BB=0，但不能作为整板 100 MHz 验收。整板实现在真实 MMCM/MIG/CDC/XDC 下：

| 阶段 | 结果 | 证据性质 |
| --- | --- | --- |
| 第一次整板实现 | pre-route phys_opt Explore 反复搜索，3601.2 s 限时停止 | 无已保存 placed/routed DCP |
| 复用 assembled DCP 的恢复流程 | 重新 place，并立即保存 placed.dcp，未重做 RTL/SoC 综合 | 可恢复布局，非签核 |
| 恢复流程布局 | WNS -0.932 ns，TNS -10395.943 ns，setup 失败 31815；WHS -0.143 ns，hold 失败 645 | placed_timing.rpt，非最终布线 |
| 布线中间结果 | Global Iteration 2：WNS -5.475 ns、TNS -147917.418 ns、WHS -0.024 ns | 仅 router 中间估计，不能用于计算可靠 Fmax |
| 恢复流程结束 | 5352.7 s 后外部有界 watchdog 停止；Global Iteration 3 最后打印 overlaps=83 | 没有 routed checkpoint、完整 route/CDC/bus-skew/DRC 签核或 bit |

日志显示全局/短程及 timing congestion 均为 level 6（64×64）。这些是拥塞区域
尺度，不是“资源已用六成”。未调整 false path/multicycle/CPU 周期来掩盖失败。
初始恢复 guardian 的 timed_out=False 是因外部延长 watchdog 先停止 CAD；该次
运行仍应记为 external watchdog timeout，不可误记成正常完成。

布局阶段最差 CPU 路径是
`u_soc/platform/physicalRequests/requests/deq_ptr_value_reg/C` →
ROM port B `ENBWREN`：数据延迟 10.418 ns，logic 2.362 ns、route 8.056 ns
（77.328%），29 级逻辑。下一结构优化重点是请求资格/译码/grant → ROM enable
回环及互连范围；不得简单将 ROM enable 常开而破坏背压下输出稳定性。
更深执行流水线不能单独解决这一存储控制路径。没有最终布线结果，不能宣称
100 MHz 稳定，也不据中间 slack 给出实板最大频率。

证据目录：
`E:/VM/Share/Valence-rtl/ddr-opt-20261002/request-capture-board-u460800/`。
`board-recovery/placed_timing.rpt`、`board-recovery-log/synth.log` 和
`build-inputs.json` 记录阶段、参数与哈希；assembled/placed checkpoint 均保留。
placed DCP SHA256：
`8ea2963102eebc2471f8bba8b9817f9c08163a898a030e55f5bf1cc48f6657d8`。
整板早期 reset 审计检查两条 3 级 ASYNC_REG 链、仅 6 个 PRE false paths，
功能 D/Q 路径仍计时；这不是最终 routed CDC/reset/时序签核。

匹配 100 MHz/460800 的 OpenSBI+Linux+BusyBox+fastfetch 镜像已在 linux-final
准备好，未上板、未完成新 Linux GSIM 启动；不得与旧 50 MHz/115200 bit 混用。
稳定 bit 哈希仍为
`fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c`。
只停止本次批处理并恢复其 watchdog，原 GUI 和旧发布均保持。

## 2026-10-02: ROM/fabric registered boundary, affected short checks passed

`staged-rom-boundary` inherits request-capture, with two-issue/ROB16/PRF48 and
cache geometry unchanged. The only new opt-in flag is registeredFabricBoundary.
The combined batch replaces the physical request FIFO read mux with head/tail
registers, registers A/D before both crossbar masters, and uses raw source
metadata before valid. State updates still require valid/fire. Queues have two
slots, latency 1, II=1, no empty bypass and no full-credit borrowing. The fabric
adds one request and one reply cycle, not a CPU execution or warm-cache stage.

23 Scala checks and necessary short GSIM checks passed: independent 50,000-cycle
A/D FIFO oracle, MMIO/routing and negative controls, coherent data/precise faults,
virtual fetch/cross-page, and one 100MHz/460800 board model reused for firmware
and download checks. Same-BIN CoreMark ticks 731130 -> 743778 (+1.73%); DDR
read/write/copy/chase 5295/7714/12987/3847 -> 5406/7970/13369/3997. These are cycle
costs, not formal scores or physical bandwidth. The old DDR BIN still reports
50MHz; independent APP_TIMEBASE_HZ=50000000 checks the known reporting constants
and banner. VM 2525 -> 2585 cycles, first trap still at retirement 675. UART
loader passed in 16778721 cycles. No full GSIM, long Linux or new CPU ISA rerun.

Two original driver/config failures remain archived: producers not quiesced
during reset, and the old DDR BIN reporting-timebase mismatch. Only driver/config
was corrected; independent FIFO/DDR oracles were not relaxed. Resumed PASS logs
are separate from the original failed aggregate results.

Frozen root: E:/VM/Share/Valence-rtl/ddr-opt-20261002/rom-boundary-board100-u460800/.
source-inputs.json captures 500 files, SHA256
efbbe3c2292742f7e914d7d01a449174bb14706bc2a131b69a2bc586a10fc9db.
rtl-inputs.json captures 133 SV + 1 resource, SHA256
c763a6a28a4444c6a278667e7715f33a7deb7880ca1ab82cc9dafe23fb9fb9fb.
short-tests.json indexes 64 raw evidence files and the corrected acceptance.
Subsequent docs/README/release-runner edits are tool/document overlays, not new RTL.

Default/rebuilt pre-map 10ns synthesis was externally stopped after 3383.8s:
about 50 minutes in Timing Optimization without log advancement or a DCP. The
guardian reports exit=7/timed_out=False; this is an external early stop, not a
successful synthesis. Only validated job descendants were stopped; original GUI
was preserved. A fresh RuntimeOptimized/rebuilt run started at 21:19 with a 25min
guard, identical frozen RTL and pre-map 10ns constraints. Short tests are reused.
RuntimeOptimized/rebuilt completed exit0 in 644.8s (synth_design 517s), with the
real ROM linked and no remaining black boxes. Pre-map10ns clock was verified.
SoC OOC WNS+0.539/TNS0/WHS+0.006; worst data path9.443ns, ready_22_reg to predictor
counter, 38 levels. This is not real board Fmax. LUT134769/FF64238/RAMB36=37/DSP19,
versus prior133573/63197/37/19; mapping changed none->rebuilt, so the +1196LUT/
+1041FF delta is not isolated architectural area. Candidate DCP SHA256
43c4eb9b96e65cfea5b40552fe7c04e1bfdd0a06af78d56fc44699c20b4e28b1.
Board assembly/implementation has started. No new routed signoff or bit yet. Stage checkpoints preserve
assembled/optimized/placed/routed results.
Release requires setup/hold/pulse width, all 14 bus-skew checks, reset/CDC, complete
route, bitstream DRC and BootROM initialization to pass at real 100MHz/460800.
Peripheral third domain and runtime DFS remain unimplemented; MMCM DRP is disabled.

Board assembly completed in136.3s, real CPU10ns/MIG UI4ns. Pre-route assembly
WNS+0.356/WHS-0.464 is not signoff. Reset audits passed two3-stage chains and only
six PRE exceptions. AltSpreadLogic_high placement completed in907s and saved DCP.
Placed WNS-1.494/TNS-24826.859,39523 failing setup endpoints; WHS-0.121,428 hold
failures. CPU worst path checked/deq_ptr -> physicalData_walkers_0 result address
CE:11.324ns, logic1.142/route10.182 (89.915%). Earlier ROM path is not the current
worst. AlternateCLBRouting is running, global/short congestion6/timing congestion7;
router intermediate WNS-1.026 is not final Fmax. No bit/routed-pass claim yet.

The combined 60-minute implementation guard expired at 2026-10-02 22:33:15
(3602.9s), during Leaf Clock Prog Delay Opt, after route verification. The last
intermediate WNS was -2.996ns. No routed checkpoint or bit was produced. Preserve
the placed checkpoint; this candidate is not a 100MHz signoff. Placement, routing,
and post-route optimization now run as separate guarded stages with checkpoints.

The saved placement was audited without re-synthesis in 79s. Reports are under
rom-boundary-board100-u460800/long-chain-audit. Besides the checked FIFO path,
the audit found memory operand selection -> stagedMemoryAddress (11.319ns,
WNS-1.482), pending -> predictor (11.246ns, -1.478), PC -> frontend hit -> lane
PC -> PMP -> rename admission -> PC (11.215ns, -1.451), and memory address ->
response queue occupancy (10.938ns, -1.057). Frontend CE margin was only +0.028ns.
These are placed estimates, not routed Fmax.

The next opt-in staged-control-heads batch groups the related control/selection
work: dedicated head/tail registers for checked requests and translated responses;
raw retirement packet capture before predictor training decode/next-PC comparison;
parallel first/second memory ranks and one-hot ROB/physical payload selection;
parallel PMP checks for possible packet lane addresses before late length selection.
The queues preserve capacity two, minimum latency one and II=1. Memory selection
and packet PMP add no cycle. Predictor updates are delayed one cycle with ordered
lanes and reset cancellation; architectural retirement, redirects and RAS are not
delayed. Issue2/ROB16/PRF48/cache geometry are unchanged. Area, cycle cost and
100MHz routed timing remain unverified until this batch completes acceptance/CAD.

At 23:18 the batch passed 30 Scala checks; independent prediction training
(40k cycles each, direct/delayed two-lane and a four-lane helper), 23,786 response
transactions, parallel memory ranking, 56,897 physical-operand vectors, and PMP
6,000 random plus 30,840 boundary cases. Negative controls rejected corruption.
Short NEMU control/memory execution passed 50 programs/20,986 commits, 2,310 loads,
2,622 stores and 146 redirects at ROB16/PRF48/2 slots/32 BHT with delayed training.
VM data passed 950 commits and unchanged first-trap 2585 cycles/675 instructions;
ordinary/cross-page VM fetch passed. Same CoreMark BIN SHA256
ae05e5be6d30bb8ec111e4734d41407ac31e9de200dd25ac7fef3ee92739e821:
743778 -> 743697 cycles (-0.011%). DDR read/write/copy/chase:
5406/7970/13369/3997 -> 5406/7975/13369/3997 cycles. These are one-iteration/4KiB
synthetic GSIM comparisons; old BIN reporting constants remain 50MHz and are not
physical bandwidth or a valid formal CoreMark score. UART download acceptance
is still running. Initial failures were test configuration/naming/GSIM-port
compatibility, not an accepted hardware failure; original logs remain preserved.

UART acceptance subsequently passed: 16,778,667 cycles, 936 output bytes,
continuous 8N1/CRC retry/bounds/large-header checks/program execution/rewrite
fence.i/stale-image rejection, AXI bursts and backpressure. All affected short
checks are aggregated without overwriting the failed original test-driver runs.
Frozen root: E:/VM/Share/Valence-rtl/ddr-opt-20261002/control-heads-board100-u460800/.
510 source files, source manifest SHA256
b464bbf2ebf701018db733a4c9ff62eee17cd98c558b56a0a4488f4dc82f031c;
136 RTL/resources, RTL manifest SHA256
dac33a6f06e740b5dd3a4e2957837021cbad59551eb7379af5eb6930e3a77759;
81 raw short-test evidence files. RuntimeOptimized/rebuilt synthesis started at
23:23:33 with the actual 10ns constraint loaded before mapping. Board stages
are now separately checkpointed/guarded. Routed 100MHz signoff is pending.

Control-heads RuntimeOptimized/rebuilt synthesis completed in 493.0s including
ROM linking/reports (synth_design 369s), with no remaining black boxes. OOC at
the actual 10ns constraint: WNS+0.994/TNS0/WHS+0.006, worst data8.902ns/29 levels
from backend pending_1 to retirement return-stack entry CE. Logic1.813ns,
estimated route7.089ns. LUT147333/FF64988/RAMB36=37/DSP19: relative to the prior
same-directive candidate, +12564 LUT (+9.32%) and +750 FF (+1.17%); WNS improves
0.455ns. This area cost and synthesized improvement are not proof of routed
100MHz closure. SoC DCP SHA256
78509929099299558d5df4e323c167b73da01d7788a695c57fefcc96c3e9b9b9.
Board assembly completed in141.4s; placement started at 23:34:08 on October2.

Board placement completed at23:55:56 in1310.8s including opt/import/reports;
place_design itself took1018s. Compared with the previous fully placed candidate:
WNS -1.494 -> -0.230ns, TNS -24826.859 -> -226.172ns, failing setup endpoints
39523 -> 3533. New global WHS-0.267ns remains a pre-route estimate. Worst CPU
path is queue_5_request_rename_instruction -> systemUnit/state, data10.110ns,
23 levels (logic1.665/route8.445ns). Other near-limit families include translated
fetch permission errors, PRF result/issue control, frontend admission and RAS.
This is significant placed improvement, not routed signoff. AlternateCLBRouting
started23:55:59 with a separate90min stage guard and the saved placed DCP.

The read-only grouped placement audit completed in95.3s without re-synthesis.
These are worst paths **to each register family**, so start/end bits can differ;
the deltas include the complete structural batch and the new placement, not an
isolated attribution to a single source edit. All values below are placed WNS,
not routed signoff or measured board Fmax.

| Endpoint family | Previous placed WNS (ns) | Control-heads placed WNS (ns) |
| --- | ---: | ---: |
| Checked request queue | -0.365 | +0.711 |
| CPU translated response queue | -1.057 | -0.146 |
| Branch predictor counters | -1.478 | +6.191 |
| Page-walker result/control | -1.494 | -0.168 |
| Fetch frontend registers | +0.028 | +0.445 |
| CPU PC registers | -1.451 | -0.221 |
| Whole backend | -1.482 | -0.230 |

New predictor packet registers have +0.336ns margin; memory address staging is
-0.197ns and return-stack entries -0.214ns. The old predictor sink no longer
contains its upstream retirement logic, but the packet boundary still measures
that upstream path. Remaining near-limit families therefore stay in the audit.
Initial router congestion is global/short6 and timing6 (previous timing7).

On October3, route_design completed in2194s (36m34s); the guarded routing stage
including import/checkpoint/reports took2290.3s. Leaf clock initialization and
skew optimization completed normally; no stage timeout or kill. The saved initial
routed DCP SHA256 is
a56ddbbe5bd480e0cf482cab8f71a8fd108f0626057a2adb0fb9c68045729069.
Formal report_timing_summary: WNS-1.105/TNS-14428.090,34514 failing setup endpoints;
WHS+0.010/THS0,WPWS+0.081,all14 bus-skew checks met. The worst CPU path is
ready_22 -> pending_0, data10.979ns,33 levels, logic2.833/route8.146ns; PRF
writeback and translated-response CE paths are also critical. This candidate
does NOT yet pass100MHz. Post-route critical-cell/rewire optimization began
00:34:09; RTL and clock constraints remain frozen while Vivado completes it.

### 2026-10-03: control-heads final routed result — 100 MHz not closed

The requested wait is complete. Post-route physical optimization finished normally:
phys_opt_design took 515s, and the guarded import/optimization/report stage took
687.9s, exit0, no timeout. RTL and clock constraints were unchanged throughout.

| Metric | Initial routed | After physical optimization |
| --- | ---: | ---: |
| WNS (ns) | -1.105 | -1.032 |
| TNS (ns) | -14428.090 | -14047.930 |
| Failing setup endpoints | 34514 | 34374 |
| WHS / WPWS (ns) | +0.010 / +0.081 | +0.010 / +0.081 |
| Bus-skew checks met | 14 / 14 | 14 / 14 |

WNS improves by only 0.073ns; TNS magnitude improves 2.63%. The final report
still explicitly says timing constraints are not met. All 187343 routable nets
are fully routed, with zero routing errors. CDC has zero unsafe/unknown/missing
ASYNC_REG endpoints. Bitstream DRC reports warnings/advisories but no errors or
critical warnings. Internal missing clocks/unconstrained endpoints/loops remain
zero; the three asynchronous input and three output delay omissions are still
listed in check_timing.rpt, not silently treated as synchronous I/O signoff.
Final whole-board utilization is 156583 LUT / 79178 FF / 62 RAMB36 / 1 RAMB18 /
22 DSP / 0 URAM; these board totals are not comparable to SoC-only OOC totals.

The worst final CPU path is ready_22 -> issue/operand selection -> ALU/completion
-> values_36[33]: data10.889ns, 31 logic levels, logic2.959ns/route7.930ns.
Of the reported top30 CPU paths, 27 originate at PRF-ready state (26 terminate
at PRF/pending, one at stagedMemoryAddress); three originate at frontend cache
bases and terminate at CPU PC or rename-ready state. These are shared long
combinational chains, not evidence that one remaining PMP module is the cause.

Read-only source mapping identifies two possible next structural batches:
issue/PRF operand -> execute/writeback/branch-pending; and I-cache reply ->
compressed decode/prediction/rename/PC feedback. Actual register boundaries
would require token/epoch ownership, redirect cancellation, precise fault and
backpressure checks while retaining two-wide II=1. Any dependency/branch-cycle
cost must be measured with short affected GSIM, not assumed free. No such RTL
change or extra implementation was started during this wait.

The final routed checkpoint is implementation/post-route/routed.dcp, SHA256
bb44e72714c7fb341920f605988f23a315844efd99644c83d4ac13429fceb3c9.
Mandatory release checks finished at 00:47:43 (+08:00), elapsed125.7s, exit1,
timed_out=false, rejecting the negative setup slack. No new bitstream was
written, and this candidate is not a signed 100MHz release. Reports and all
checkpoints are retained; the user's GUI and old working bit are untouched.

### 2026-10-03: throughput pipeline batch in progress

The opt-in staged-throughput profile inherits staged-control-heads with
registeredIssueExecute and registeredFetchPacket. ROB16/PRF48/LSU2, two-wide
rename/execute/commit and the previous published default are unchanged.
IssueExecuteStage adds two independent capacity-one operand registers, latency1,
II1 each, with cancellation and LSU/M/CSR port-0 backpressure. Live legal ordinary
ALU results forward into the next operand register, sustaining dependent ALU
II1 without chaining two ALUs in a cycle. Memory/M consumers keep the original
ready file. Actual ROB age selects simultaneous branch recovery across elastic
lanes. Store preparation has its own grant and does not need ALU-slot credit.
RegisteredFetchPacket uses four direct register slots, raw fault metadata and
an independent supply PC; the architectural admission PC still supplies empty
ROB interrupt EPC. Compacting partial packets preserves two-wide admission.

Initial affected checks passed: 34 Scala contracts, 20000-cycle independent
execution-slot oracle and 30000-cycle plain/compressed raw-packet oracles, with
negative controls. These are preserved under throughput-20261003-batch1.
The first 12-program same-code, same-geometry ISA/NEMU A/B and 50-program control
smoke passed under throughput-perf-ddr100-20261003-batch1, but performance was
not accepted: mandatory taken-prediction reservoir flush introduced a bubble.

| Workload | Control-heads cycles | Initial throughput cycles |
| --- | ---: | ---: |
| Independent ALU, 1024 retired | 513 | 515 |
| Single ALU dependency chain, 1024 retired | 1025 | 1027 |
| Two independent dependency chains, 1024 retired | 513 | 515 |
| Direct JAL chain, 128 retired | 130 | 259 |
| Two-instruction taken loop, 258 retired | 139 | 270 |
| Compiled sum, RAM latency1 | 1388 | 1462 |
| Compiled sum, RAM latency12 | 1812 | 1848 |
| Same-BIN short board CoreMark | 743697 | 805706 |

The first candidate preserved ALU steady-state II but degraded the two branch
microbenchmarks almost twofold and short CoreMark by8.34%; it was not synthesized
or promoted. VM first trap was2721 cycles/675 retired vs2585/675; ordinary and
cross-page instruction translation passed. Initial DDR read/write/copy/chase was
5365/8006/13363/3979 cycles. All are GSIM comparisons, not formal CoreMark or
physical bandwidth/frequency claims. Old failed/partial evidence is retained.

The same batch is being refined before its combined CAD run: small raw JAL/C.J
prediction and an accepted-successor hint table steer supply early; real PC
metadata and decode successor checks retain correctly prefetched targets. Full
decode/rename/PMP remain behind the register boundary. A signed21 low addition
with independently precomputed high carry candidates avoids a raw-triggered
64-bit target carry chain. Test-only taps additionally require actual port-0
hold/port-1 progress, older-lane0 simultaneous redirects and ALU forwarding;
independent ISA/NEMU validation remains authoritative. These refinements have
not yet completed acceptance or synthesis; 100MHz and net performance remain
unverified. No extra UART protocol/full GSIM/Linux/board programming is performed.

### 2026-10-03: throughput pipeline short acceptance completed

The refined batch is frozen at the hardware-source level. All five affected
scopes passed in `build/gsim/throughput-20261003-batch3`: 34 Scala contracts,
20000 execution-slot oracle cycles, plain/compressed fetch-packet positive and
negative controls, virtual data and ordinary/cross-page virtual instruction
translation, and one reused board model for CoreMark/DDR. Fetch directed tests
include 511 first-time JAL admissions in 512 ticks and 1022 learned-loop
admissions in 512 ticks. These are helper throughput checks, not whole-core IPC.

The final A/B evidence is `throughput-perf-ddr100-20261003-batch2`. Both profiles
passed 12 independent ISA/NEMU workloads and 50 control/memory smoke programs,
with oracle-rejecting negative controls. Actual pipeline recovery witnesses
passed on 11 short programs/336 commits: two port-0-hold/port-1-progress events,
one simultaneous redirect with older lane0, and 127 ALU forwarding captures.
The harness uses test-only taps; production profile geometry remains two-wide,
ROB16/PRF48/LSU2/BHT32. Issue histograms count store preparation and LSU starts
as grants, not necessarily unique architectural instructions; commit IPC is the
architectural throughput metric.

| Workload | Control-heads cycles | Refined throughput cycles |
| --- | ---: | ---: |
| Independent ALU, 1024 retired | 513 | 515 |
| Single ALU dependency chain, 1024 retired | 1025 | 1027 |
| Two independent dependency chains, 1024 retired | 513 | 515 |
| Direct JAL chain, 128 retired | 130 | 132 |
| Two-instruction taken loop, 258 retired | 139 | 147 |
| Compiled sum, RAM latency1 | 1388 | 1459 |
| Compiled sum, RAM latency12 | 1812 | 1848 |
| Same-BIN short board CoreMark | 743697 | 799934 |

The almost-twofold jump/loop regression is removed before the first CAD run.
Independent and two-chain ALU retain steady-state two instructions/cycle; the
short 1024-instruction samples include two extra startup cycles. However, the
12-case same-clock geometric mean speedup is 0.98373676, not an IPC improvement.
CoreMark is still +7.5619% cycles, so this workload requires a measured usable
clock increase above 1.075619x to break even. VM first trap remains 2721 cycles /
675 retired (+5.2611% cycles). The final DDR read/write/copy/chase ticks are
5369/8010/13361/3975 versus 5406/7975/13369/3997 in control-heads: mixed, not
universal improvement. Single-iteration CRC/tick checks are neither a valid
CoreMark score nor FPGA bandwidth measurements.

Both runners record complete `src/main/scala` SHA256 manifests and reject live
hardware changes during execution. The acceptance collector cross-checks raw
logs, histograms, model/program/NEMU hashes and the manifests before candidate
staging. Correctness/performance measurement verification does not claim net
speedup. No full GSIM, Linux boot or unchanged UART protocol repetition ran.
One combined actual-100MHz synthesis is the next step; routed setup/hold/CDC,
bitstream and physical board results remain unverified. Clock constraints and
the stable 50MHz bit are unchanged; dynamic clock control is not implemented.

### 2026-10-03: first throughput CAD result rejected; recovery feedback repair

The accepted hardware was frozen under
`E:/VM/Share/Valence-rtl/ddr-opt-20261003/throughput-board100-u460800`.
Source manifest SHA256: 28b87352a5dc2ebb577998c9ab88193e830334de1ef6cd490c096584b989f40d.
138 RTL/resource files were exported once. RuntimeOptimized/rebuilt synthesis
with the clock XDC loaded before mapping completed normally in487.3s, exit0,
no timeout, zero synthesis errors/critical warnings. Real BMG ROM was linked;
the clock-free SoC DCP and original raw reports are retained.

Despite functional acceptance, 10ns OOC setup failed: WNS-2.195ns,
TNS-5673.473ns,7557 failing setup endpoints. WHS+0.006ns/THS0,WPWS+4.458ns.
SoC-only totals are150980 LUT/68009 FF/37 RAMB36/19 DSP (not whole-board totals).
The worst path is ledger head -> pending exception/interrupt -> recovery kill ->
execution slot cancellation -> early forwarding eligibility -> shared circular
issue selector -> PRF operand read -> store address/range state. It is12.177ns,
49 logic levels, logic2.931/estimated route9.246ns. This is worse than the old
same-constraint SoC estimate, not progress or a usable-frequency measurement.

The data-register cut exists, but using cancel-qualified `deq.fire` for early
wake creates a new control bypass around it. Merely changing store forwarding
cannot fix the shared selector dependency. No board placement/routing/bit was
started. The next coherent repair removes cancel-only credit borrowing, registers
ordinary-ALU forwarding qualification and separates store preparation grants
from execution-slot credit. Actual enqueue/completion keep same-cycle recovery
authorization; global kill must not be delayed. The changed helper protocol and
ownership/RAW/port-contention behavior require fresh independent short checks.
This repair is in progress, not yet validated or synthesized.

Checkpoint-only queries completed normally in157.3s, using two unchanged
clock-free real-ROM checkpoints and an independent10ns query clock. Exact path
sets and families are in `throughput-cuts/{comparisons,endpoint_families,pipeline_cuts}.tsv`.
An initial command-line array quoting failure is retained separately; no extra
synthesis ran. The successful query confirms both beneficial data cuts and
the new recovery-control regression:

| Endpoint family | Old OOC slack ns | First throughput OOC slack ns |
| --- | ---: | ---: |
| PRF value state | +1.010 | +2.599 |
| CPU admission PC | +1.276 | +2.976 |
| Rename/ledger | +1.135 | +2.126 |
| Pending issue state | +1.465 | -0.908 |
| Store/LSU address state | +1.203 | -2.195 |

New ready-to-operand-register, operand-to-PRF and operand-to-operand paths are
5.760ns/4.158ns/7.378ns respectively; raw-slot-to-PC is6.436ns. The direct old
ready-to-PRF group has no matched candidate path, which alone is not a timing
claim; the nonempty before/after register families above provide the evidence.
New raw cursor and fabric families are positive but still only OOC estimates
(+1.739/+1.164ns), not whole-board margin or proof of100MHz.

The three recovery-feedback repairs are now implemented. A full stalled
execution slot no longer accepts on cancel-only credit; it is empty next cycle.
Normal consume/refill remains II1, and cancel+consumer-ready can replace. The
forwardable bit is computed from the same ALU legality rules and registered with
the owner; speculative operand selection uses occupied/port-ready/forwardable,
not late cancel-qualified fire. Actual producer completion and consumer capture
retain kill/token/exception authorization. Store preparation uses the raw rank
grant independently of ALU slot credit and never uses same-cycle ALU-to-AGU data.
Owner invariants, forwardable equivalence and no-live-dependent-on-cancelled-
producer assertions are added; architectural ISA/NEMU gold is unchanged.

Fresh `throughput-20261003-credit-batch4` passed all five required short scopes;
`throughput-perf-ddr100-20261003-credit-batch3` passed the12 A/B,50 timing and11
actual recovery programs with positive/negative controls. The independent helper
adds blocked-cancel refusal/next-cycle refill plus ready-cancel replacement:
964 ready-cancel replacements and two directed refills; cancelled-stalled cases
are explicitly covered. All12 workload cycles, VM first-trap2721/675, short
CoreMark799934 and DDR5369/8010/13361/3975 are identical to the pre-repair refined
pipeline evidence. Thus the feedback cut introduces no additional cycle cost in
these measured cases; the earlier7.56% CoreMark cost is not removed or hidden.
154 hardware source hashes bind the two fresh runs. A new frozen candidate and
one combined synthesis are required; the old negative DCP is not overwritten.

### 2026-10-03: repaired throughput synthesis passed; real board placement running

Frozen repair candidate:
`E:/VM/Share/Valence-rtl/ddr-opt-20261003/throughput-credit-board100-u460800`.
Source manifest SHA256253abddc943ceccc73eb0be7e313e7793bd6d2fcfc43f69d78fe5231761793ac;
real-ROM SoC DCP SHA256f53e257fb33ba1dabfb2cf3928f5ac4f60634d4ca76231ac566eb3d462719d12.
One RuntimeOptimized/rebuilt actual10ns synthesis finished normally in528.7s,
exit0, no timeout. The temporary BMG black-box import warning is preserved in
the log; final real-ROM linking requires functional black-box count0.

| OOC metric | First throughput | Repaired throughput | Prior control-heads |
| --- | ---: | ---: | ---: |
| WNS ns | -2.195 | +1.542 | +0.994 |
| TNS ns | -5673.473 | 0 | 0 |
| Failing setup endpoints | 7557 | 0 | 0 |
| LUT | 150980 | 149626 | 147333 |
| FF | 68009 | 68010 | 64988 |

RAMB36=37/DSP=19 unchanged; WHS+0.006/THS0,WPWS+4.458. Versus prior control-heads,
SoC LUT grows1.56% and FF4.65%; these are OOC SoC, not whole-board totals.
Worst current path is ledger/head control -> returnStack entry CE,8.354ns,
33 levels, logic1.754/estimated route6.600ns. It is not the previous PRF/ALU chain.

The repair-versus-first-pipeline query reused DCPs, completed in163.4s and
preserved all matched groups. Store/LSU address worst12.177->8.018ns
(slack-2.195->+1.964); pending10.890->7.336ns; operand-register10.496->6.118ns;
occupancy10.434->5.815ns. Operand-to-operand forwarding/replacement drops
7.378->5.335ns, with16 rather than27 levels. Some already-positive families
move slightly backwards (PRF slack2.599->2.148,ready2.978->2.559); they are not
hidden. All queried nonempty endpoint families are positive at this OOC stage.
These estimates do not qualify routed100MHz, actual Fmax or net CPU performance.

Board assembly completed in147.8s, exit0, using the original board/DDR XDC and
existing DDR/ROM/clock-converter products. Real CPU MMCM clock is10ns (100MHz),
DDR UI clock4ns (250MHz), not merely a renamed50MHz netlist. A single fresh
checkpoint continuation (`AltSpreadLogic_high`,place-only) began11:23:51(+08),
with60min abnormal-stall guard. No SoC resynthesis, frequency reduction or timing
exception relaxation. Routed setup/hold/bus skew/CDC/DRC and signed bit remain
pending; the working50MHz release and user's Vivado GUI are untouched.

### 2026-10-03: throughput-credit whole-board placement complete; routing started

The frozen candidate's checkpoint-only placement completed normally at11:40:47
(+08),1015.7s including import/optimization/reports,exit0,no timeout. place_design
itself took732s. All140 frozen RTL input hashes and the real-ROM SoC DCP hash
were rechecked unchanged. The real CPU remains100MHz and MIG UI250MHz.

Placed setup is WNS+0.505ns/TNS0 with0/201068 failing endpoints. This is NOT full
signoff: estimated hold is WHS-0.189ns/THS-9.502 with410 failures; CPU-only hold
is-0.108ns/207 failures. Routing must resolve them. Pulse width is+0.081ns.
Worst placed CPU setup moved to PMP address/NAPOT qualification -> packet PMP ->
rename queue source2:9.202ns,24 levels,7CARRY8,logic1.830/estimated route7.372ns,
clock skew-0.237ns. The earlier OOC RAS endpoint is not the placed worst.

One fresh routing continuation began11:41:24(+08),using placed.dcp,
AlternateCLBRouting and tns_cleanup,with90min abnormal-stall guard. It does not
repeat synthesis/place, lower frequency, relax exceptions, touch the GUI or
program hardware. Initial routed checkpoint is saved before optional targeted
post-route optimization. Final routed setup/hold,all14 bus-skew checks,CDC/DRC
and BootROM identity remain mandatory before generating any100MHz bitstream.

The performance acceptance is measurement verification,not a speedup claim.
Steady dual issue/commit and single-chain forwarding are preserved; the CoreMark
same-BIN short case still has7.5618% cycle cost. If a new100MHz implementation
passes,that case breaks even only against an old actual frequency<=92.970MHz.
No old verified frequency is inferred from its negative-WNS estimate.

For the saved prior control-heads whole-board placed report,the same-stage
comparison is WNS-0.230/TNS-226.172/3533 setup failures -> +0.505/0/0; global
estimated hold-0.267/533 failures -> -0.189/410. The0.735ns placed setup gain
is real report evidence,but not a routed result or an achieved clock increase.
Other close placed families remain: virtualPc->fetchAdapter.errors+0.516ns,
queue source1->stagedMemoryAddress+0.516ns,and raw supplyPc->packet slot CE
+0.521ns. Future changes must follow final routed clusters,not only the OOC RAS.

Read-only fallback audit (NOT implemented): PMP still decodes shared raw CSR
state combinationally. Publishing decoded low/end/active together with filtered
CSR next-state could remove the NAPOT carry from ordinary permission checks
without another instruction cycle. It must update the TOR following entry,
preserve locking/first-overlap/full-address/overflow/MPRV rules,and retain PMP
head draining plus permission-change redirect/VM invalidation. For a routed
retirement bottleneck,the alternatives are parallel retirement qualification,
head-inclusive-trap specialization and prefix-qualified local RAS enables.
These are proposals only; current frozen hardware and passed tests stay unchanged.

### 2026-10-03: final throughput-credit routing fails 100 MHz; no bit generated

The same immutable `throughput-credit-board100-u460800` candidate completed
routing at12:12:29(+08),1864.9s, and post-route physical optimization at12:23:09,
574.9s. Both exited normally without their90/45min guards firing. This is final
whole-board evidence with the original XDC, actual100MHz CPU and250MHz MIG UI,
not an OOC estimate, a timeout or an unfinished automatic optimization.

| Whole-board metric | Prior control-heads final | Throughput initial route | Throughput final post-route |
| --- | ---: | ---: | ---: |
| Setup WNS ns | -1.032 | -0.614 | -0.515 |
| Setup TNS ns | -14047.930 | -2037.013 | -1400.868 |
| Failing setup endpoints | 34374 | 8959 | 7123 |
| Hold WHS ns | +0.010 | +0.010 | +0.010 |
| Pulse-width slack ns | +0.081 | +0.081 | +0.081 |

Final routed nets191860/191860, routing errors0; all14 bus-skew checks MET;
CDC unsafe/unknown/missing-ASYNC_REG counts all0 and no bitstream DRC Error or
Critical Warning (vendor/debug warnings remain). Whole-board LUT158980/FF82355,
RAMB36=62/RAMB18=1/DSP22/URAM0. Versus the prior routed baseline, LUT+2397(+1.53%),
FF+3177(+4.01%), WNS+0.517ns; TNS falls90.03% and failing endpoints79.28%.
These gains do not establish100MHz stability or cancel the measured7.56% short
CoreMark cycle cost.

Worst final path is `systemUnit/mtie -> head recovery -> fetchPacket/supplyPc[22]`:
10.406ns,28 levels/6CARRY8, logic2.666ns and actual route7.740ns. The strict release
gate ran12:24:28–12:26:40,verified all4176 BootROM INIT properties, clocks/reset
CDC/DRC,then rejected negative WNS (exit1,timed_out=False). No bit or signed release
DCP was written; the working50MHz release and GUI remain untouched. Final routed
DCP SHA256`e6f864c5750fce82a221ee2563ed197598a2fcbc97e5377b2cead1c36cbda158`.
The matching100MHz/460800 OpenSBI+Linux image is prepared,not a physical boot claim.

A fresh read-only CPU-register family query also exposes independent near-worst
chains: PRF-ready -> memory-preparation rank -> operand mux -> AGU, WNS-0.511ns,
10.315ns/19levels (route8.020ns); virtualPc -> cached translation -> physical
address -> permission check -> fetchAdapter.errors, WNS-0.506ns,10.200ns/27levels
(route7.518ns). The first diagnostic run failed at its catch-all DSP family due
to Vivado's collection-to-list display limit; its already-written matched family
reports are partial evidence, not a completed query. The corrected read-only
query uses explicit pin-name iteration and a separate fresh output directory.

Next source batch, NOT yet functional/timing acceptance: opt-in trusted current-
head inclusive recovery bypasses unnecessary general token/age arbitration;
raw relative jumps use immediate/low-bit qualification and registered successor
hint qualification; adjacent fetch tags use fill/request-time full64 shifted
keys rather than late query-address carries. All remain two-issue16ROB/48PRF;
default profile is unchanged. Cross-review found no concrete production blocker,
but independent short ledger/machine/fetch/NEMU tests are mandatory. The additional
LSU/translation chains are being analyzed before another combined CAD run; no
changed source is relabeled as the already-passed frozen candidate.

Read-only next-cut proposals (not implemented, not measured): memory scheduling
can use owner-local ready mirrors updated on the same wake/reserve edge, rather
than a dynamic PRF-ready mux before ranking; reserve priority and same-packet RAW
initialization must be exact and asserted against real PRF ready. Store-only
oldest-two payload preparation with original shared issue/kill authorization at
the write boundary could remove unrelated ALU early-wake from the store AGU
chain without another issue cycle, at extra selection/read-network cost.
InstructionTranslationAdapter can capture translated PA first and perform PMP
in its existing send cycle, preserving normal request launch latency; a fully
denied fault may take one extra cycle. It must never launch before permission,
must preserve cross-page second translation and fault/tval priority, and must
hold request/mask under backpressure and retain permission/SFENCE draining.
These are distinct from the three already-edited source cuts and need final
implementation review plus the same unified short batch, not another old-RTL CAD.

The corrected diagnostic query completed normally12:52:40(+08),316.0s,exit0/no
timeout: `throughput-credit-board100-u460800/board-path-cuts-v2/`,27 endpoint
families and40 source/sink cuts,69,579 actual CPU-clocked registers. It reused
the final DCP exactly once without changing constraints or implementation; DCP
SHA256 was rechecked unchanged. Tool SHA256
`70f4608ada3d89f3aa082ceb2f565af0d288e33e56ac7b79879d82ca7b0042fa`.
Groups overlap and return at most five paths, so negative-returned counts are
not total failures. Catch-all coverage additionally exposes `pending[12] ->
multiplier/partial11 DSP input` WNS-0.420ns/data10.209ns: this must be analyzed,
not hidden by an FF-only family query or declared already fixed. Remaining
positive-but-close groups include RAS control+0.083,frontend cache+0.154 and
operand-register+0.202ns. No new synthesis/GSIM/bit was run for these prepared
source changes during this diagnostic update; only Python/PowerShell parsing,
diff checks and independent source review have passed.

### 2026-10-03: final-path structural batch, unified acceptance in progress

The next batch now includes the already-prepared trusted head-trap/raw-hint/
adjacent-tag cuts plus the additional routed-negative LSU and M/I-fetch paths.
It remains two-issue, ROB16/PRF48/memory2; all new backend flags default false.
`ownerLocalOperandReady` publishes each queued owner's two ready bits on the
same accepted wake/reserve edge as the physical scoreboard, with reserve taking
priority and new allocation initialized from exact same-edge state. Active-owner
assertions compare this mirror with real PRF readiness. `earlyStorePreparation`
selects the oldest two stores and their operands independently, then uses the
original shared issue/kill/token grants at the write boundary. A shared top-two
store grant must be in the store-only top two. `parallelMulDivDispatch` prepares
oldest multiply and divide operands separately before unit-available/age/budget
authorization. MULW2/full-MUL6/II1 and single M start are unchanged; no normal
execution cycle is added. Extra local operand networks have unmeasured area cost.
Opt-in store and M paths forbid late load/MUL preview bypass rather than reading
an old PRF payload under a newly asserted preview-ready signal.

With existing `registeredTranslationHeads`, instruction translation captures PA
before PMP, using the original send cycle to authorize the first physical offer.
Aligned packets use static lane offsets; generic cross-page packets capture
second VA at initial request and retain two independent PAs. First-offer mask/
fault state is held even under backpressure. Successful launch stays translation
reply+1; an entirely PMP-denied packet returns one cycle later. Production CSR
PMP/SFENCE/return/fence.I draining includes frontend quiescence, fetch-adapter idle
and line-fetch idle, so software permission updates do not race this later sample.
Default/historical adapter logic is retained. No permission-before-check request,
fault-priority weakening or timing exception change is permitted.

Fresh unified short run: `throughput-20261003-finalpaths-batch1`; separate pinned
ISA/NEMU A/B: `throughput-perf-ddr100-20261003-finalpaths-batch1`. Nine Scala suites
passed. New independent side-issue oracle passed6000cycles/62264ready checks,
750same-packet RAW/750alias init/912wake-reserve collisions,8064store grants and
399wrapped ages; injected mismatch exits1 through its oracle. Four permission
models (2word generic/2word aligned/4word aligned retimed,2word generic historical)
passed44/28/100/44cases and negative controls, including noncontiguous cross-page
PA, second translation faults, locked-M, held permissions and explicit launch/
all-denied latency. Eight original independent SystemModel/direct-IRQ machine
cases passed:10traps/8IRQs/10mret,6trusted-head/4empty-trap events; this is not
production IMSIC or NEMU IRQ verification. VM and reused-board scopes are still
running at this entry; current source is not yet frozen/synthesized/routed.

The new12-case NEMU A/B,50timing cases and11pipeline-recovery cases passed; measured
cycles match the prior throughput-credit pipeline exactly. Thus these new cuts
have no additional measured execution cost, but do not remove its existing
7.5618% same-BIN CoreMark cost. Short proofs bind all156 hardware files and42
explicitly listed affected test inputs before/after execution. That input list
is not claimed as the complete transitive compiler dependency closure; frozen
source export also retains all test/simulator sources. Fixture scope limitations:
the permission helper does not exercise an early offered physical response,
simultaneous next virtual request at reply completion, or nonzero physical
page-fault/second physical-fault bit relocation. Integration VM/board checks stay
mandatory. No CAD gain, Fmax, performance improvement or new bit is claimed yet.

Unified acceptance subsequently completed normally, exit0. VM data passed813
commits/5walks, first trap2721cycles/675retired, unchanged; compressed baseline
and cross-page virtual fetch both passed. One reused board model passed exact-
BIN CoreMark799934ticks and DDR5369/8010/13361/3975ticks, all identical to the
throughput-credit batch. CoreMark ran one iteration only and is not a valid score;
synthetic AXI timings are not physical bandwidth. Collector independently verified
raw positive/negative logs, all156 live hardware hashes,42 listed input hashes,
12 A/B rows/histograms,50timing and actual pipeline recovery witnesses, then
wrote `build/gsim/throughput-ddr100-20261003-finalpaths-accepted/` (exit0).
`PERFORMANCE_REVIEW_REQUIRED=True` honestly retains the pre-existing pipeline
cycle regressions versus the saved control-heads baseline; it is not a functional
failure or performance-improvement claim. Combined candidate target is
`E:/VM/Share/Valence-rtl/ddr-opt-20261003/finalpaths-board100-u460800`.
Fresh actual10ns synthesis is next; whole-board100MHz/460800 signoff remains
required before any bit is delivered. No full GSIM, UART upload, Linux simulation,
new clock domain/DFS or hardware programming was performed.

The saved-SoC read-only comparison tool was expanded to31families/39cuts including
all CPU-clocked DSP/RAMB/URAM inputs, owner-ready/store/M and translated PA/PMP/
RAS data-vs-enable. Missing old groups remain0/NA; capped counts are not total
failures. Tool SHA256`5dd4eea0e11d62d811519dd52e72a41039492a0f2bb40f7306f5b1ee26074e52`;
static Tcl fixtures passed, actual Vivado query has not yet run for this batch.

### 2026-10-03: final-path combined synthesis passed; one board continuation started

Frozen candidate `finalpaths-board100-u460800` contains532source files,144RTL/
resource files,48build files and116short-evidence files; recorded bytes/SHA values
were independently rechecked. Source manifest SHA256
`69adad3c4e22b8d66b5c54f997bc2d1bcab2123bfb94195077330ab87c983695`;
RTL manifest`b20b5e705807ca57f8ed6e7e2800d9f0da9a11c588bb8c136f4e21e943605c09`;
short receipt`0d88c9c5b555f57735016e63885c4e6b102374d81b4451c044cf179c6cbab6b9`.
The single RuntimeOptimized/rebuilt pre-map10ns synthesis completed13:42:22(+08),
532.7s, exit0/no timeout, real-ROM linked/no black boxes. Mapped logic reports
0errors/0critical warnings/14warnings; logs retain initial OOC import messages.
Final linked SoC DCP SHA256
`16b528f2c07bb5ca90e4b690bb3b00326b4e253dd8ce45ee8624f3048d44937f`.

| Same-stage SoC OOC metric | Throughput-credit | Final-path batch |
| --- | ---: | ---: |
| 10ns setup WNS ns | +1.542 | +1.162 |
| Setup TNS / failing endpoints | 0 / 0 | 0 / 0 |
| Hold WHS ns | +0.006 | +0.006 |
| Pulse-width slack ns | +4.458 | +4.458 |
| LUT | 149626 | 172839 |
| FF | 68010 | 70197 |
| RAMB36 / DSP | 37 / 19 | 37 / 19 |

Thus LUT rises23213(+15.51%) and FF2187(+3.22%); the new global OOC worst margin
is0.380ns smaller. Do not characterize this as an unconditional timing/area gain.
New worst is system CSR/recovery control -> ownerReady initialization,8.820ns,
33levels/3CARRY8, logic1.856/estimated route6.964ns. It is not directly comparable
with the old whole-board routed-0.515ns result. Short measured cycles remain
identical; actual frequency-times-IPC benefit and routed clock remain unverified.

One checkpoint-only whole-board continuation began13:44:25(+08),from this DCP,
using original board+DDR XDC and the existing exact100MHz MMCM/250MHz MIG UI
products. It will assemble/place/route/targeted-post-route once and run strict
setup/hold/pulse/bus-skew/reset/CDC/DRC/BootROM signoff before any bit write. No
frequency reduction, timing exception relaxation, source resynthesis, GUI change
or board programming. A concurrent read-only saved-SoC comparison began13:45:21
for31families/39cuts; original old/new DCPs are never modified.

Independent firmware/IP review passed all15firmware files, Linux manifest+6
products and366IP files versus the previous candidate. All32768ROM words match
the3061-byte boot image padded to128KiB, retaining prompt-free Bootrom V0.1 and
download mode, not the old CPU OK/test menu. Linux internal payload/DTB bytes,
RV64IMAC soft-float entry/address layout and100MHz/460800 DTB agree. Final ROM
INIT and generated clocks still require board assembly/signoff; physical Linux
boot and runtime DRP/third clock domain remain unverified/not implemented.

The read-only saved-SoC comparison completed13:54:47(+08),569.8s,exit0/no timeout,
31families/39cuts, both inputs10ns/BB0/29real-ROM RAMB primitives. Old/new DCP and
frozen tool SHA values remain unchanged. New owner-ready/PA-stage groups have
real paths; old absent groups explicitly remain0/NA. DSP-family133diagnostic
nodes are the19physical DSPs split into tool subcells, not133DSP resources.

| Same-stage source/sink cut | Data ns old -> new | Levels old -> new |
| --- | ---: | ---: |
| Virtual PC -> fetch permission | 7.283 -> 3.143 | 33 -> 11 |
| TLB state -> fetch permission | 6.567 -> 3.144 | 24 -> 11 |
| Physical ready -> multiply payload | 6.391 -> 3.983 | 22 -> 12 |
| Physical ready -> divide payload | 5.787 -> 3.481 | 27 -> 11 |
| Ledger -> store preparation | 8.002 -> 6.847 | 33 -> 24 |
| Frontend -> raw slots | 6.846 -> 5.520 | 27 -> 20 |
| Raw cursor self-feedback | 6.874 -> 5.398 | 32 -> 22 |
| Ledger -> RAS entry CE | 8.354 -> 6.679 | 33 -> 22 |

New registered-PA->permission is3.210ns/12levels, owner-ready->M/D4.889/4.244ns.
However complete raw-cursor family worsens7.822->8.498ns,store8.018->8.375ns;
complete RAS only8.354->8.207ns. CSR/system completion -> generic recovery ->
rename/reserve authorization now drives those worst paths and new mirror8.820ns.
Operand-to-operand forwarding estimate5.335->5.882ns; ready->pending5.133->6.160ns.
DSP family6.391->6.487ns/slack3.604->3.275 because CEP authorization, not the
already-shortened PRF operand path. Those regressions and area cost are retained.
No routed/Fmax/performance claim follows from these post-synthesis estimates.

Actual board assembly completed13:47:35(+08),195.4s,exit0/no timeout, confirming
the real100MHz generated clock. One checkpoint-only placement started13:47:40;
it has advanced to global placement while the query ran. Normal phase progress
is not an abnormal stall. Final routing and strict release remain pending.

Read-only contingency, NOT implemented: a trusted current-head EXCLUSIVE
system-redirect recovery (retain1, unlike inclusive-trap retain0), tentative
rename source/alias data before final accepted write enables, and shared pure
source->physical one-hot decode/one-time allocation-ready initialization could
reduce the new accepted/reserve chain and duplicate operand area without adding
normal cycles. System owner/head protection, external/synchronous priority,
rollback boundary shrink, same-packet RAW/WAW/alias and precise accepted events
must be proven. Do not share actual store/M read ports after late authorization,
as this recreates rank->PRF->AGU/DSP feedback or reduces throughput. The ongoing
board result decides whether another batch is required; frozen source is unchanged.

Final placement completed14:12:38(+08),1502.3s,exit0/no timeout. Post-placement
optimization improved its intermediate WNS-1.275/TNS-3520.720 to the formal
placed WNS-0.397/TNS-583.013,4052/206115setup failures. Whole-board hold is
-0.172/THS-13.463,561failures; CPU-only hold-0.104/THS-8.348,314failures. Pulse
width+0.081/no failures. Compared with credit's formal placed+0.505/0/0, setup
margin is0.902ns worse; this is not hidden by the improved individual OOC cuts.
First three CPU setup paths all start at systemUnit/state_reg[1] and terminate
at PRF values_31 CE bits3/40/52:10.070ns,29levels/2CARRY8,logic1.582ns and
estimated route8.488ns (84.29%). Actual generated CPU clock is10ns. Setup and
hold still fail; no100MHz qualification or bit is claimed.
Formal placed timing SHA256
`8491c58384c2ab6872e26b413e4e9eded0d60fbdd19306ee3c89d6d41a8556a7`;
CPU paths`4cc0c2f74ee6c120a9dcc1eb6b3413e8119d0eb7c08cd2c71ef2ee63e6ed9d7e`.
One routing continuation began14:12:43 from placed.dcp with original constraints,
AlternateCLBRouting/tns_cleanup and the90min abnormal guard. Initial routing and
global reroute iterations are progressing. Only actual routed/post-route
setup/hold/skew/CDC/DRC/ROM signoff can authorize delivery. If this remains
negative, the prepared head-exclusive/tentative-rename/shared-decode batch must
address the new common authorization bottleneck, not repeat unchanged CAD.

Contingency drafts reviewed while that sole route continues (NOT APPLIED):
`build/analysis/finalpaths-authorization.patch` SHA256
`eca07fc9c57b19ce18f57594e835a14ea0a30d7b24f1d74460b3343c175e92bc`
contains trusted head-exclusive system retain1 and tentative rename source/alias
payloads. All three candidate flags default false. Authoritative allocation
prefix, RAT/free writes, full-token completion and recovery shrink stay intact.
Protected system identity is a proof/assertion, not a new late tag-qualified
valid path. Duplicate keep1 recovery still does not acknowledge/consume a held
system completion; LSU/M result collisions must be tested with legal external
FENCE.I flush backpressure and independent models, never manufactured internals.

`build/analysis/finalpaths-shared-decode.patch` SHA256
`10884aac485f96bc21b8adf0e07eb4182993fb182b382ede1f1c344f6c1662fa`
shares only queued source equality masks. Three independent two-owner/four-value
early-read networks remain for LSU/store/M-D; owners/grants/ready/kill/values do
not enter shared decode. Allocation-ready initialization is factored once per
incoming lane/source, preserving reserve>wake and allocation-last priority.
Its standalone three-client oracle covers six distinct owners/64 active-empty
combinations. Draft applicability/static review passed, but no compile/GSIM/
area/placed/routed gain is claimed. Current source and frozen candidate remain
unchanged; a draft getter naming issue was corrected against actual archived
GSIM `$$` symbols before application.

`build/analysis/finalpaths-validation-inputs.patch` is also NOT APPLIED. For the
next batch it adds six previously omitted unchanged dependencies plus the
physical-read harness/new sharing contract: 41->49 listed inputs, plus manifest
itself (50). This is still a precisely enumerated scope, not an automatic full
dependency closure. Existing accepted42-input receipts are not retroactively
rewritten. Root will merge/review all drafts only if final board signoff fails,
finish the coherent batch, then one necessary short+NEMU acceptance and one CAD
run; no parallel second implementation or unchanged resynthesis is authorized.

### Final routed outcome and next coherent batch (2026-10-03)

The sole finalpaths-board100-u460800 route finished normally at15:09:41(+08),
3418.0s/exit0. Post-route physical optimization finished at15:18:48,547.5s.
Final setup WNS-0.885ns/TNS-5393.550,15262/206135 failing endpoints; hold+0.010ns
(CPU+0.011), pulse+0.081ns, no hold/pulse failures. MIG UI250MHz setup+0.009ns.
All216952 routable nets are routed with0 errors; all14 bus-skew checks met
(minimum+3.738ns). CDC has no unsafe/unknown/unmarked asynchronous crossings;
DRC has0 errors (63 warnings/2 advisories). Existing asynchronous UART/reset
I/O delay limitations remain; these checks are not complete external I/O timing.
Whole-board resources:182288 LUT/84769 FF/62 BRAM36/1 BRAM18/22 DSP/0 URAM.
Compared with credit's routed-0.515ns/158980 LUT/82355 FF, this batch is worse
by0.370ns and23308 LUT. Functional/local-cut progress is not a global timing win.

Strict release finished exit1 after136.5s, rejecting setup failure at
release_soc_partition.tcl:117. No bit or signed-off checkpoint was generated.
The preserved candidate's post-route timing SHA256 is
`d2181e6d86daa60394506e4067dcbf907ad30d6348931517d59d2c47d0c7a457`;
CPU paths `e36f3a270c0e205bcde70ba29536308a9a26d6eca4f64d79b6f68e7ba3741995`;
routed.dcp `cb6e71768c0da8c7dfe0c5fd37b91be7b1b31ed4e8db6856b9c68d51b70b8e02`.
All CAD for this candidate has ended; the user GUI and working50MHz bit are intact.

Actual final paths, rather than the earlier placed worst, identify two remaining
cuts: M-completion/dequeue-ready -> generic issue eligibility -> early-store PRF/
address end (10.661ns/23 levels,8.345ns route), and PacketFetchPmp denied -> faultized
rename request -> capacity or same-packet source mapping (10.682ns/26 levels and
10.606ns/29 levels). There are15262 failing endpoints, not just three paths.

The reviewed head-exclusive/tentative-source/shared-pure-decode drafts and their
tests/runner/collector were subsequently APPLIED to the live source, not to this
frozen failed candidate. They remain uncompiled/unverified. Trusted system retain1
must not acknowledge duplicate recovery or bypass final token/retirement checks.
Shared decode retains separate early read ports. This next batch also separates
exact store eligibility from ALU/M completion promises, and precomputes raw decoded
rename/ready candidates before the authoritative PMP-fault selection. No relaxed
PMP checks, conservative register reservation, extra normal pipeline cycle, frequency
reduction or timing exceptions are authorized. Finish all related changes, then one
fresh necessary short/NEMU acceptance and one combined synthesis/board continuation.
Earlier receipts do not accept new live sources. The enumerated test-input manifest
has expanded to50 entries including itself, but is still not full dependency closure;
new fixtures/helpers must be added before the new acceptance begins.

The complete second batch now has159 main Scala sources and53 precisely bound
test inputs. First short tag finalpaths-batch2 compiled and passed all10 selected
contract suites (48 tests), plus the6000-cycle store/readiness oracle and both
strict negative controls. Store invariance4500 pairs, real ALU changes4500 and
late authorized store-grant changes2250 were observed. It then stopped before
raw-fault model generation: the alias fixture accidentally enabled the existing
non-aliased-only early destination/rank options. Production guards/hardware were
not changed to admit it; only fixture flags are corrected, including the later
alias ledger case. Original failed results/logs remain preserved. A fresh tag
must bind the corrected test inputs; no acceptance or CAD gain is yet claimed.

Fresh finalpaths-batch2b passed all five affected short scopes and the separate
byte-pinned NEMU A/B; the strict collector passed at
`build/gsim/throughput-ddr100-20261003-finalpaths-batch2-accepted/`.
Both raw-fault fixtures passed288 cases (40regs:2880cycles/92160ready checks;
48regs:5184/165888), all four masks, RAW/WAW/x0/valid holes/pressure/alias and
wake-reserve collision, with strict source-oracle negatives. The40reg fixture
observed72 no-free fault accepts and32 no-free alias accepts; the48reg full-ROB
fixture rejected88 no-free fault offers. It does not independently prove commit,
rollback/refcount release or trap delivery; the original ledger/core scopes remain.
All three six-owner physical-read configurations and both negatives per model
passed; shared equality decode never shares actual owner/grant/read ports.

Candidate and alias head-system ledgers each observed20 head redirects,1 active
shrink,53 duplicate retain1 offers,2 external-head ties,1 trap-priority event and
76 owner checks; both strict system/source negatives passed. Legal external
FENCE.I-backpressure MachineCore A/B each passed24 cases/1663cycles:156 offers,
60 blocked cycles,2 LSU/13 M-completion collisions,45 repeated rollback cycles,
120 commit holds,96 protected releases and39 acknowledgements. All per-case cycles
are identical. This is DIRECT-IRQ/independent SystemModel, not registered IMSIC
or NEMU IRQ co-simulation. The eight original head-trap cases/negative still passed.

The12 NEMU comparison records are identical to finalpaths-batch1; steady
two-issue/forwarding/held-port/older-branch witnesses remain2/127/2/1 as applicable.
VM data813commits/5walks and first trap2721cycles/675retired remain unchanged;
ordinary/cross-page VM fetch passed. Reused100MHz/460800 board-model same-BIN
CoreMark799934ticks and DDR5369/8010/13361/3975ticks are unchanged. These are short
CRC/cycle tests, not an official score or FPGA bandwidth. Original pipeline costs
versus control-heads remain (same-clock geomean0.9837367597 and CoreMark+7.56%);
collector engineering_review_required=True is deliberately retained. No extra
measured cycle cost is added by this batch. Long UART protocol/full Linux GSIM
were not repeated. Whole-board100MHz timing, area, bit and physical Linux results
still require one new frozen candidate and actual routed release gates.

New frozen candidate:
`E:/VM/Share/Valence-rtl/ddr-opt-20261003/authorization-board100-u460800`.
It binds538source files,146RTL/resource files and160 raw short evidence files;
source-inputs SHA256 `ff56cc06898e7988e7d50127d2314dce872dc50d28f35fd3d6d3be5801bb7a4c`.
One RuntimeOptimized/rebuilt pre-map10ns synthesis started16:33:20(+08) and
finished16:41:24,484.6s/exit0/no timeout. Real ROM import/BB0 passed. OOC setup
WNS+2.059ns/TNS0/0failures, hold+0.006ns, pulse+4.458ns. LUT170991/FF70205/
37BRAM36/19DSP/0URAM. Versus finalpaths-batch1: setup margin+0.897ns,1848 fewer
LUT(-1.07%) and8 more mapped FF. It remains21365LUT above the older credit OOC
149626; this batch does not erase that earlier area cost. Worst is now registered
branch redirect -> generic recovery/completion -> RAS entry CE:7.837ns/29levels,
logic1.540ns/estimated route6.297ns, not the former CSR mirror path.

OOC timing SHA256 `7dd61c4a2b158ab0b1ce00d17ffd4e5bf1bb66545f4c51f64b969e988d0dfef8`;
utilization `1c28736e2fc82eb29247cabeeB1948415876b62729ddb443e574bbfc73380c21`;
soc_candidate.dcp `53eb35b6e33747c7fba6cca342fc8a2cf708169bc98ff618ac8c390ce07448fe`.
One frozen checkpoint-only board continuation started16:44:33. It preserves the
real100MHz/MMCM/ROM/MIG/constraints and existing working bit/GUI; assembly,
placement, routing/post-route and strict release gates are required. Positive OOC
does not establish routed100MHz, external I/O timing, bit or physical Linux boot.

The new assembly completed normally in147.4s and confirmed the actual100MHz
generated CPU clock. Placement completed17:05:51(+08),1135.3s/exit0/no timeout.
Its formal report is setup WNS+0.488ns/TNS0/0 failing endpoints of206446, not the
intermediate log estimate+0.501ns. CPU setup+0.488ns; global hold-0.182ns/THS-16.154/
626 failures (CPU-0.119ns/392 failures), pulse+0.081ns. Placement is NOT signoff;
the sole checkpoint-only route started17:05:56, with normal hold fixing and the
existing post-route/signoff gates still required. No second synthesis or CAD job
was started. Previous finalpaths placement was-0.397ns; old credit placement was
+0.505ns, so this result does not establish a universal placement improvement.
Worst placed CPU path is PC -> packet PMP -> exact fault-mask rename capacity ->
fetch supplyPc CE:9.335ns/27levels, logic2.437ns/estimated route6.898ns. It retains
authoritative PMP fault selection; no unverified permissions/timing bypass is used.
Placed timing SHA256 `b4c6dbef26fa45824859a620934b613d7bdcd7046ae4f56326b1c7b201bd352d`;
CPU paths `f59c5a281970f8d304cd0718dec21313007cc59ffa3b0f3103877304cffc9206`;
placed DCP `008046e3bc148c41f4431f315cb6f2a7ad3f8d8d0c8296c2ee3ab05ff22eb24e`.

### Authorization batch: actual routed100MHz release completed

The sole route completed normally17:26:15(+08),1218.9s/exit0/no timeout;
route_design itself took1126s. Intermediate WNS-0.986 -> -0.230 -> -0.056 ->
+0.067 was NOT release evidence. Final actual routed setup+0.101ns/TNS0/
0failures of206446, hold+0.010ns/THS0/0failures of205896, pulse+0.081ns/TPWS0/
0failures of89102. CPU setup+0.101ns/hold+0.011ns; MIG UI250MHz setup+0.205ns/
hold+0.010ns. All14 skew checks met, minimum+3.859ns.216367 routable nets all
fully routed, routing errors0. The post-route stage completed162.9s and explicitly
skipped redundant physical optimization because routed setup/hold/skew already met.

| Frozen100MHz candidate | Final WNS(ns) | TNS(ns) / setup failures | Routed LUT / FF | Strict release |
| --- | ---: | ---: | ---: | --- |
| throughput-credit | -0.515 | -1400.868 / 7123 | 158980 / 82355 | rejected, no bit |
| finalpaths-batch1 | -0.885 | -5393.550 / 15262 | 182288 / 84769 | rejected, no bit |
| authorization-batch2 | +0.101 | 0 / 0 | 180264 / 84769 | PASS, bit generated |

Compared with the previous finalpaths candidate, routed margin improves0.986ns
and LUT decreases2024(-1.11%), FF unchanged. It still costs21284 more LUT than
the older credit candidate; retain that area tradeoff. Current LUT breakdown:
178069logic/1804LUTRAM/391SRL;62BRAM36/1BRAM18/22DSP/0URAM. Worst CPU path is now
branchRedirectValid -> store preparation/recovery -> storeEnd_12[63]:9.743ns/
21levels(9CARRY8), logic1.875ns/route7.868ns(80.755%). This remains a low-margin
physical-control/data-selection path for future improvement, not permission bypass.

Strict release completed17:32:54(+08),236.4s/exit0/no timeout. All mandatory
gates passed: real100MHz generated clock, MIG UI250MHz, setup/hold/pulse,
zero no-clock/unconstrained-internal/loop endpoints,14 skew constraints,
clean routing, bitstream DRC errors/critical warnings0, CDC unsafe/unknown/
missing ASYNC_REG/Critical0 on analyzed paths, audited two3-stage reset chains
with only six asynchronous PRE exceptions, AXI REGION grounded, two UART ASYNC_REG
stages. ROM4176 INIT/INITP values matched selected firmware IP/candidate/routed
design and all32768MIF words matched the3061-byte prompt-free V0.1 BootROM.
DRC retains63warnings/5advisories, mainly DSP pipeline advisories; warnings were
not waived to gain setup. External button_n/sys_rst_n/uart_rxd and
c0_ddr4_reset_n/led/uart_txd retain the three input/output-delay omissions;
this is not a timed external synchronous-I/O claim or physical stress acceptance.

Release bit is28700913bytes, SHA256
`1c738377c33883bb1710f3ffa21c42aa02f0e45babee475d5da054614e616509`.
Signed routed DCP `1445a9d673bbc98e6476653157116dcd31f3a4bdaccd19293d9c76f9543fe036`;
release timing `308cf88cbf7a10610058637fedb94c59dd6df6b9ef2864ad50117082cdfdae5d`;
signoff `0723cbd50f15289014d0e8dff4ec1a00c603ec970e7aa8cc6562374aafba4b68`.
Post-route timing `4b3a056018c07f9856a00e1eb94f9af95243802c88d799587b99395fdab49207`,
CPU paths `538ace23094684776a23e89636ec4bc1ac7130dcdd1ea3a7271c6b3c36e3a9bd`,
routed DCP `f6111d229df80d435e6cf115d9314d36e3d7949f6922573a83caf1cbea6ae995`.

Matched100MHz/460800 OpenSBI+Linux image5394424bytes SHA256
`ee6acac8ea584092014129bad3ff8f4c52466aba34afc5b8a0a1612f4d6f84ca`, DTB1595bytes
`6acfe9d05679e8f12fd04175757c35d40e4df72d5c96b5fb5b8d16d00c29588f`, and loader
`b39203e9b71731927aeff322c70f95b1017fd0faab730e5475f5cb8572400b55` copied to release.
Firmware includes BusyBox/fastfetch and uses SBI DBCN hvc0 polling, not a validated
Linux external AIA/UART IRQ driver. Linux manifest remains on_board_verified=False/
gsim_verified=False: no long Linux GSIM or physical board test was added. Necessary
short GSIM/NEMU and strict negatives passed with no additional measured cycles;
the earlier same-clock performance cost remains, not an official score or2x speedup.

After programming the new bit and resetting the board, run from the release directory:

```powershell
python .\uart_load.py COM4 .\opensbi_linux_ddr100_uart460800.bin --memory ddr --baud 460800 --run --console
```

Physical programming, UART/DDR stress and Linux boot are user-operated next steps.
Old working50MHz bit SHA256 remains
`fbadd8f0ca86ba847a86f42db93105c6f4193db8458e884f9f184f2d04c9277c`.
User GUI PID37688 was untouched; no candidate CAD process remains after release.
Dynamic frequency and a third peripheral clock domain are still not implemented.

## 2026-10-03 晚：原 WSL 工程 F/D 合入与模块 100 MHz 批次

原 `/home/openion/Valence` 已按明确授权保留脏工作区并增量合入 38 个 F/D 文件，
实验默认关闭，misa/DT F/D 不宣告。合入备份/凭据在 WSL，旧独立分支与旧整数版
100 MHz bit 均保留；GUI PID37688 未关闭或重置。本轮不是整板重综合或新 bit。
用户已报告旧整数版实际 Linux 启动与 CoreMark CRC 成功，这不扩展为 F/D 或压力验收。

两条相关结构改动后只跑一次必要短 GSIM 批次，再一次导出/综合/布局/布线对比：
HardFloat raw/round 切级，浮点访存 AGU/PMP 地址边界切级。供应商源码没有新改动；
端到端完整 token、背压、权限检查与精确异常不变。加减 producer 延迟 1→2 拍、
最小 II 2→3、容量 1；访存多一拍，没有宣称浮点 IPC 改善。默认关闭时不启用
这些浮点硬件。整数最紧路径与现有整板 +0.101 ns 签核数值均未修改。

### 独立模块布线结果

Vivado 2025.1，`xczu15eg-ffvb1156-2-i`、10 ns、双发射 staged-throughput 的
ROB16/PRF48、PMP16/Sv39 参数。直接导出三个生产模块，无测量专用流水寄存器；
`synth_design -mode out_of_context -flatten_hierarchy none` 后 opt/place/route。
maxThreads=8；基线和候选各一个三模块 batch，基线内部路径从保存的 DCP 只读提取。
候选于 22:39:11(+08) 正常退出 0，三个 routed DCP 保存完毕。

| 模块 | 旧 WNS ns | 新 WNS ns | 最长数据路径 ns，旧→新 | LUT，旧→新 | FF，旧→新 | 新内部 hold ns |
|---|---:|---:|---:|---:|---:|---:|
| FloatingPointAdd | +0.156 | +3.339 | 9.756→6.671 | 1143→1042 | 139→186 | +0.110 |
| FloatingPointState | +5.712 | +5.712 | 4.183→4.183 | 1971→1971 | 2657→2657 | +0.048 |
| FloatingPointSystem | +0.480 | +2.526 | 9.401→7.357 | 5432→5314 | 3140→3252 | +0.028 |

FloatingPointSystem **包含**状态、加减、LSU/PMP，不能再与另外两行相加当作
整板新增资源。各模块无 BRAM/DSP 使用。加减原 40 级逻辑降为首段 23 级；
第二段内部 register→register 最坏数据 5.659 ns、WNS +4.320 ns。
整桥最紧内部路径现为 `fp/pending_command_instruction_reg[1]/C` →
`memory/result_data_reg[41]/R`，23 级，数据 7.357 ns、WNS +2.526 ns。
状态单元未改 RTL，重测数值完全一致；没有为凑优化数量添加无关改动。

**重要验收界限：**零 input/output delay 是现有 OOC 比较约定，外部 reset 没有
板级时序预算；三个模块的边界 hold 都为 -0.080 ns，最短为输入直接到 D pin。
这些违规如实保留，没有用 false-path 或修改 delay 隐藏。另行报告的
register→register hold 都为正，表示内部路径满足当前约束；不能据此称整个
OOC 含边界“全时序通过”，更不能代替有 CPU/fabric/CDC/reset/IP 约束的整板签核。
带 F/D 的整板布线、时钟/复位签核、物理上板、Linux FP context 仍未完成。
现有整数整板最紧 storeEnd 路径 9.743 ns/约 81% 布线，仍是下一整数批次首要目标。

### 证据与复现

证据全部在原 WSL 工程，不再向 Windows task 目录散放：

- `build/fd-handoff/integration-20261003.json`：38 个合入文件哈希及备份位置。
- `build/gsim/floating-point-memory-main-timing-20261003/receipt.json`：111 个输入、
  32 个模型/二进制哈希；新 SoftFloat 34840/状态500/真实 CPU 访存双配置双 seed、
  整数 off/on 和 11 个新负例通过，ASan/UBSan。不是长 Linux 或全量 GSIM。
- `build/fpga/fd-100mhz-20261003/{baseline,candidate}-rtl`：独立导出 SV。
- 同根下 `{baseline,candidate}-reports/<module>`：综合/布局/布线报告与 DCP。
  新 `path_metrics.tsv`、`internal_{setup,hold}_paths.rpt` 给出内部时序。
  基线同类细节在 `baseline-reports/<module>/cached-details`。
- `comparison.json`：源/RTL/报告/DCP 哈希和本表机器可读对照；不声称整板通过。

先选择新输出目录，在 WSL 导出：

```sh
cd /home/openion/Valence
mill -i IonSoC.test.runMain ooo.FloatingPointTimingMain /home/openion/Valence/build/fpga/fp-repeat-1
```

Windows 使用 native Vivado，仅路径指向 WSL，不改变 GUI 工程：

```powershell
$socRoot = '//wsl.localhost/Ubuntu-24.04/home/openion/Valence'
& 'E:\Xilinx\2025.1\Vivado\bin\vivado.bat' -mode batch `
  -source "$socRoot/fpga/vivado-fp-modules.tcl" `
  -log "$socRoot/build/fpga/fp-repeat-1/vivado.log" `
  -journal "$socRoot/build/fpga/fp-repeat-1/vivado.jou" `
  -tclargs "$socRoot/build/fpga/fp-repeat-1" "$socRoot/build/fpga/fp-repeat-1-reports"
```

只看旧路径时用 `fpga/vivado-fp-cached-paths.tcl REPORT_ROOT` 读保存的 DCP，
不重新综合。模块 batch 的报告目录已存在时主动报错，避免覆盖旧验收。

## 2026-10-04 接续：完整 F/D 功能候选与新时序边界

主工程已接入完整基础 RV64 F/D 和四种压缩双精度访存，可配置纯整数、F、
F+D 或实验裁剪子集，默认关闭。最终短 GSIM 凭据
`build/gsim/floating-point-full-20261003-r4/receipt.json` 为
`PASS_FUNCTIONAL_CANDIDATE`，133 个源码和 36 个模型/可执行文件哈希重新匹配；
数值、真实 CPU、精确访存异常及整数开关对比通过，见 OoO 阶段记录。

本批**没有运行 Vivado，也没有生成新 bit**。上节 S 加减子集的 add/state/system
布局布线数据只对应已封存的旧快照，不能外推给新完整 F/D 桥。新加减/乘法为
raw/round 两级，FMA 四级；D 乘积、FMA 乘加、整数转换及舍入链需重新按模块
测量 10 ns。除法/开方采取一位/周期迭代以控制资源，迭代并不自动证明高频。

`FloatingPointTimingMain` 当前实例化参数的兼容开关已映射完整 F/D，因此现在
导出的 system 会包含完整候选；旧 DCP 和 comparison.json 内容不变。后续应
为 S/D 运算组导出新的独立模块，在同一批 OOC 中测资源及关键路径，再集中修改。
零 I/O 边界 hold、实际接口时序、FP 长链和整数原顽疾都仍需明确区分；
在完成完整配置的布线、时钟/复位及接口签核前不承诺 F/D 整板 100 MHz。

## 2026-10-04 完整 FPU 的 13 模块新基线与 NaN 输出适配候选

旧三模块加减子集之外，新基线已独立测量全部 S/D add、multiply、fused、
div/sqrt、misc，及 State、Execute、System。根目录
`build/fpga/fpu-rv64gc-20261004`，`baseline-measurements.json` 包含
每个模块的 all/internal setup/hold、起终点、级数、LUT/FF/DSP 和 RTL/报告/DCP 哈希。
13/13 内部 setup/hold 满足 10 ns；完整 System 的结果是
WNS +1.454 ns、data 8.428 ns、29 级、内部 hold +0.025 ns；
LUT 23,272 / FF 6,127 / DSP 22。最紧链为 D→S 转换，不是单纯大乘法。
所有模块的零预算边界 hold 仍 -0.080 ns；IO/复位边界未签核，整板资格仍空缺。

候选一次修改共享 NaN 输出适配、整数转换冗余检查、min/max 和精度转换的
迟到 NaN 检测，不改 HardFloat、不增加数值级延迟或 II。短集中验收
`floating-point-full-20261004-nan-cut-r1` 与真实 SoC 的
`rv64gc-board-20261004-nan-cut-r1` 均通过；见 OoO 记录。
`pre-opt-source` 保存已验证优化前快照，`baseline-source` 保存原完整 F/D 基线。
优化后统一 Native Vivado batch 已启动，完成前不得引用本节基线 WNS 当候选结果。

导出与统一测试（均选择新目录）：

```sh
mill -i IonSoC.test.runMain ooo.FloatingPointFullTimingMain /home/openion/Valence/build/fpga/fp-full-repeat/rtl
mill -i IonSoC.test.runMain ooo.RV64GcTimingMain /home/openion/Valence/build/fpga/fp-full-repeat/core-rtl
```

```powershell
$socRoot = '//wsl.localhost/Ubuntu-24.04/home/openion/Valence'
& 'E:\Xilinx\2025.1\Vivado\bin\vivado.bat' -mode batch `
  -source "$socRoot/fpga/vivado-fp-full-modules.tcl" `
  -log "$socRoot/build/fpga/fp-full-repeat/vivado.log" `
  -journal "$socRoot/build/fpga/fp-full-repeat/vivado.jou" `
  -tclargs "$socRoot/build/fpga/fp-full-repeat/rtl" `
    "$socRoot/build/fpga/fp-full-repeat/reports" "$socRoot/build/fpga/fp-full-repeat/core-rtl"
```

第三个 core RTL 参数可省略，此时只测 13 个 FP 模块。实际 CPU OOC 包含 IRQ/CSR/
ROB/整数和 FPU 接入，但不包含外围 cache/fabric、MIG/Clock Wizard/板级 XDC。
默认不生成 bit。完成后 `fpga/collect-fp-module-results.py REPORTS RTL --out NEW.json`
汇总 13 模块；Core 的单独 path_metrics.tsv 和报告须另外审查，不能被漏计成已通过。

### 完整 FPU 候选已布线的对照（2026-10-04）

同根 `candidate-measurements.json` 的 13/13 内部 setup/hold 满足 10 ns；
本表只列关键变化，完整 13 模块/四类路径/资源对照见 `audit-progress-01.json`。

| 模块 | 内部 data(ns) 前→后 | 内部 WNS(ns) 前→后 | LUT 前→后 |
| --- | --- | --- | --- |
| AddS | 5.274→5.287 | +4.707→+4.694 | 1043→1010 |
| MultiplyD | 7.550→6.425 | +2.332→+3.557 | 1340→1358 |
| FusedD | 7.380→6.518 | +2.503→+3.463 | 3249→3338 |
| DivSqrtD | 7.451→6.478 | +2.432→+3.503 | 1569→1628 |
| Execute | 7.593→7.234 | +2.291→+2.745 | 18494→18329 |
| System | 8.428→8.379 | +1.454→+1.603 | 23272→23114 |

System FF 6127/DSP22 不变，内部 hold +0.025→+0.036 ns。
没有新增 producer 级或 II，实际 CPU 用例仍 77,748 周期。
Execute 的 all-scope/input setup +2.143→+2.038 ns，小幅回退不隐藏；所有模块
all-scope 边界 hold 仍 -0.080 ns，不是完整时序通过。
实际 CPU Core 正在同批布局布线，不因此称 100MHz RV64GC 整板可用；
旧整数版 bit、GUI 工程与约束未修改。

新增审计（不运行 GSIM/CAD，使用新输出路径）：

```sh
python3 fpga/audit-rv64gc-evidence.py --out build/fpga/fpu-rv64gc-20261004/audit-new.json
```

状态 `PENDING_CORE_ROUTE` 表示整核未完成，而不是 FPU 失败或整核通过。
审计锁定当前功能、Sv39 非同址上下文、RTL、所有报告/DCP；唯一历史输入差异
是 runner 的过时资格说明文字，逐字验证且单独记录，不追改原始测试 receipt。

### 最终：真实 RV64GC MachineCore 内部 10 ns 通过

同批 Native Vivado 已正常退出 0；最终审计 `audit-final.json` 为
`FUNCTIONAL_AND_INTERNAL_10NS_MET_BOUNDARY_UNQUALIFIED`，不是 pending。
Core route 内部 WNS +0.090 ns / TNS 0 / hold +0.023 ns / pulse +4.468 ns；
资源 138743 LUT / 38532 FF / 41 DSP。最紧 PC→fetchPacket.supplyPc.CE：
32 级、9.806 ns，裕量仍薄。13 FPU、数值/真实 CPU/BoardSoC/软件 ISA 与
247 CAD RTL 和全部 DCP 哈希一致。没有重跑完整综合，也没有新 bit。

Core all-scope hold -0.046 ns / THS -5.374 ns / 454 失败端点；最紧为
memory.response.pageFault→FP.memory.result.exception。零预算 IO 及未预算 reset
不代表实际 SoC 接口已经通过。报告仍明确写 `Timing constraints are not met`，
不能隐藏成全时序 PASS；内部判据与边界失败分开记录。
Core 不含外围 cache/fabric、MIG、Clock Wizard 或板级 XDC，后续整板验收才
决定新 F/D 实体板 100 MHz。旧已启动 Linux 的整数 bit 与用户 GUI 未改动。
