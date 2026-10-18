# Orbital-I1 FPGA 入口

本目录只保留板级源码/工具，不存放导出的 RTL、Vivado 工程、DCP 或 bit。
完整架构、每批性能/时序和未完成门禁见 [工程记录](../../docs/orbital-i1.md)。

## batch44：300MHz整板约束STA通过，bit已生成，用户确认JTAG小程序运行

I-cache返回先写入已有word寄存器，次拍reply在寄存数据上完成对齐；firstHalf利用已有
secondSend拍准备，不能继续把BRAM返回和半字选择挤在同一拍。保留原完整指令作为逐拍断言，
不增加响应边沿或parcel owner。Home前后两个原有两槽边界开启已有空槽准备功能；
晚到的目录/握手只改变valid，不能再使能每个64位数据位。异常向量分别准备M/S目标，
晚到cause只参与4位低部相加，BASE高位进位提前准备，委托不再位于XLEN加法之前。
CPU300/UI250/AON50/UART50、I/D32KiB、原槽位、原乱序核与共享IP均保持。

`bandwidth44_acceptance.py`新增192位两槽独立字节/容量oracle（并与旧队列逐拍对照）、
768组M/S/U异常向量进位/溢出/委托检查。原parcel边界、精确异常、C/A/F/D、
O3 CoreMark及六项实际CPU Bare/Sv39流量全部保留。

`build/gsim/i1-bandwidth44-20261018-r2/receipt.json`通过全部37项受影响检查、13项性能门。
六项流量含80拍实际服务延迟，与batch43逐项相同；CoreMark ROI646056拍、345517条指令、
轨迹与CRC相同，非正式长跑分数。395个源文件、136个产物已重新核验；寄存器声明6999项、
存储89项和4个目录写口与batch43逐项相同，净增控制位/载荷RAM均为0。
52项轻量工具单测通过。首次queue fixture因GSIM顶层Vec接口生成限制失败，
已改用等价标量测试接口，保留失败收据r1，不修改DUT或软件oracle的判据。
新BootROM模型正例、空ROM/错banner负控通过；216722拍、30898条退休指令、
33字节UART输出、460800解码、JTAG等待点0x10068。单CPU时钟GSIM不替代物理UART50 CDC验证。

一次新整板实现和一次限次postroute优化完成，保持全部原RTL/时钟约束，未重新综合。
首轮路由WNS−0.066ns、TNS−0.298ns/29端点；postroute最终 **WNS0.000ns、TNS0、
hold+0.007ns、脉宽+0.081ns**，报告明确`All user specified timing constraints are met.`。
Setup压线通过，不应说成300MHz裕量宽裕或已验证上板稳定。

| 同口径最终报告 | batch43 postroute | batch44 postroute |
| --- | ---: | ---: |
| CPU300 WNS | −0.059ns | 0.000ns |
| TNS | −5.477ns | 0 |
| LUT | 92756 | 92908（+152） |
| FF | 55090 | 55016（−74） |

BRAM36等效63.5、DSP31保持。DDR UI250 setup/hold+0.454/+0.010ns，AON/UART50
+2.478/+0.024ns；136473条可布线网络全部完成、0错误；20项bus-skew全部通过，
最差+2.512ns。同9处reset CDC Critical未新增，3级释放结构检查通过，不宣称完整CDC签核。
综合网表及布线后完整512×64 ROM内容、映射、禁写检查均通过；写bit前第三次复检通过。

新路径另外用最终DCP做只读STA，不修改实现或约束：
RAM返回→实际word寄存器+0.107ns、word→IF指令寄存器+1.678ns、
word→firstHalf+1.828ns，见`retimed-path-audit/`。旧result.instruction shadow只用于
GSIM逐拍断言，实际综合已删去，不能只盯着旧端点宣称对齐路径通过。
其他目标最终裕量：Home状态+0.198、PC+0.006、JTAG+0.045、probe+1.047、metadata WE+1.994ns。

交付目录`E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261018-batch44-r1/`。
Bit为`bitstream/orbital_i1_rv64gc_cpu300_i32k_d32k_uart460800_jtag65_nomac_bootrom.bit`，
SHA256 `bb974f17ec03bd5d51eb5df56bc858beb7a5e9051cffedcce4b4c95fe2c0aea7`。
冻结结论`batch44-result.json`、交付收据`bitstream/delivery.json`、实际报告`postroute-r1/`。
源码与工具快照`source-batch44-frozen.tar.gz`（SHA256
`9b141c70765378fc060502a66f8cfe14d911d3ba5f9bc0271880e4d040841fb4`）。
源快照含冻结时的文档，最终物理结论以本节及JSON为准。原乱序核和共享IP未修改；
源码、工具与工程记录提交到dev2，生成的RTL、bit、DCP和编译缓存不进入Git。
上板用460800/8N1/无流控，复位应打印`Valence Orbital-I1 BootROM V0.1`后等待JTAG。
修复版65位USER2、F/D、Sv39、TL-C启用；MAC不接。

用户随后报告实际板卡CAP=0x564c0101、STATUS=0x00000021；109字节JTAG小程序
读回校验通过（CRC32=0xe2925e20），COMMIT接受，UART已打印程序输出。
这是用户报告的JTAG→DDR→ROM校验→程序执行冒烟通过，不等于Linux、长期稳定性或完整CDC签核。
冻结交付JSON保留生成时的“尚未上板”状态，不回写历史证据。

### 当前I1板级镜像的JTAG下载要求

在已经连接的OpenOCD telnet控制台，按板上复位键使BootROM重新进入等待，再执行：

```tcl
valence_ram::start
valence_download_and_run {/mnt/e/path/to/app.bin} 0x80200000
```

文件路径属于运行OpenOCD的系统；当前从WSL运行时使用`/mnt/e/...`。
本版BootROM自动等待JTAG，不需要UART输入`j`，COMMIT接受后自动校验并启动，不需要额外RUN。

- 文件必须是平坦二进制，无自定义头；不能直接使用ELF、bit或网络下载的VLD包。
- 加载基址固定`0x80200000`，窗口为`[0x80200000,0x84200000)`，最多64MiB，包含末尾4字节补齐。
  第二个参数仅指定入口，必须4字节对齐，并落在实际文件长度内；并不改变加载地址。
- 程序须按实际运行地址链接，转换成bin不会重定位。常用转换为
  `riscv64-unknown-elf-objcopy -O binary app.elf app.bin`，先核对ELF段地址及入口。
- 当前硬件启用RV64GC。BootROM以M-mode、裸地址、关中断进入，`a0=0`、`a1=0`；
  程序自行初始化栈、gp、BSS、异常和需要的浮点FS状态，不能假定BootROM提供C运行时。
- 每次已启动后换镜像先复位；无需重新综合或生成bit。旧乱序核的OpenSBI/Linux镜像不能直接视为兼容：
  应使用本I1的PLIC、时钟及无MAC设备树，并正确打包OpenSBI、DTB和载荷；不能将Linux Image直接当M-mode裸机入口。

现有外部OpenOCD工具包的`valence_wait_claimed`在用户环境报`committed_generation`变量缺失，
尚未修复该主机脚本，不能宣称此辅助命令通过。它不负责启动，COMMIT及已出现的UART输出才是本次执行证据。
可只读查询`format "STATUS=0x%08x GEN=%u" [valence_ram::rd 0x41] [valence_ram::rd 0x46]`；
STATUS位6表示CLAIMED，不要为查询状态重复提交或下载。

## batch43：短验证通过，最终WNS−0.059ns，未生成bit

针对batch42真实路由退步重构，而不是继续扩大one-hot归约：预测器采用各bank独立的
XOR校正，默认PC不再等待“所有bank均未取目标”的反向归约；PC载荷准备与真实IT/Cache
握手分离，后者只授权原寄存器写入。Home所有权位恢复原生索引选择，13个phase各自计算
保持/退出条件，原完整优先级表达式保留为逐拍等价断言。Cache只读返回直接选择匹配way，
授权valid不再重复遮罩整条数据总线；对齐器使用已有one-hot parcel位置，独立选择高/低半字。
JTAG已转正的修改原样保留，原乱序核、时钟/复位边界、I/D32KiB和事务/队列容量不动。

`build/gsim/i1-bandwidth43-20261018-r3/receipt.json`完成33项受影响检查与13项性能门。
RV32原始、RV64原始/预译码parcel独立oracle和负控通过；RV32缓存预译码不属于现有合法配置。
Home双事务/探测/脏回写/背压均通过。六项实际CPU Bare/Sv39（含80拍延迟）流量、
O3 CoreMark ROI646056拍、345517条提交指令、轨迹和CRC逐项不变。
392个源文件、115个产物已回读核验。寄存器声明6999项、存储89项；仅Home寄存器重命名，
净增控制位和载荷RAM均为0，目录仍4个单写口。49项轻量工具单测通过。
新BootROM/UART正例及空ROM/错banner负控通过，216722拍、33字节、460800解码。
这不代表物理UART50跨时钟仿真或300MHz实现通过。
新整板目录`E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261018-batch43-r1/`，
136份RTL中130份与batch42字节相同，仅6份目标模块变化；MIG/ClockWizard/AXI CDC及XDC不变。
**仅综合阶段**资源92971 LUT、54500 FF、63.5 BRAM36等效、31 DSP；相较batch42同阶段
95903 LUT、54507 FF，减少2932 LUT（3.06%）、7 FF。综合0 Error/Critical，
512×64实际RAMB内容/映射/禁写检查通过。

一次完整整板实现及一次受限postroute优化已完成：最终WNS−0.059ns、TNS−5.477ns、
hold+0.009ns，仍不满足300MHz，不生成bit。最终资源92756 LUT、55090 FF、
63.5 BRAM36等效、31 DSP；20项bus-skew通过，DDR250与AON/UART50通过。
同9处reset CDC Critical结构检查通过，不宣称完整CDC签核。实际综合网表与布线后
4096字节ROM均一致。最终6组目标裕量为Home状态−0.036、PC−0.041、对齐−0.059、
JTAG+0.076、probe+0.932、metadata WE+2.218ns。
冻结结论`batch43-result.json`，报告`postroute-r1/`，源码包`source-batch43-pre44.tar.gz`。

## batch42：短验收和ROM通过，整板时序退步，不交付bit（2026-10-18）

沿用batch41的CPU300/UI250/AON50/UART50、I/D各32KiB和原有事务/响应槽位。
Home采用显式13位one-hot状态及恢复编码，所有权位按小组并行读取；目录仍为原来的
四个256×20单写口LUTRAM。BTB容量、训练和预测规则不变，互斥候选与前端恢复一起做数据选择；
退休重定向也改成互斥选择。Cache probe恢复直接读取已有one-hot位，缩短返回数据到对齐器的选择链。
JTAG错误码由原有本地状态和DMI载荷预先解码，实际握手只授权标量写使能；
link-down立即拒绝新请求、W1C优先级、超时及已呈现存储请求的排空规则不变。

短入口为`bandwidth42_acceptance.py`，只覆盖受影响的JTAG、预测器、Home双读、
256B/32KiB双Cache一致性及真实CPU权限/C/A/F/D、六项Bare/Sv39流量和相同O3 CoreMark。
27项检查/13项性能门包含独立负控；六项流量用三个独立GSIM进程并行执行，收据由主线程保存。
固定版GSIM不能为顶层Vec输出生成正确C++ getter，因此预测候选使用相同含义的标量Bundle字段。
这不是改变算法、仿真器或跳过检查。新源码冻结后统一验证，再做一次真实整板实现。
`audit_batch42_short.py`只允许Home现有state/resume各由4位变13位，净增18个控制位；
寄存器声明6999项、存储89项和原有全部载荷/槽位须保持。BootROM启动及实际RAMB内容门禁继续保留。

2026-10-18收据`build/gsim/i1-bandwidth42-20261018-r2/receipt.json`已通过全部27项检查及
13项性能门。391个源文件、91个产物已回读哈希核验；六项Bare/Sv39结果逐项相同，
短O3 CoreMark ROI仍为646056拍，提交轨迹`7b173819116883a2`和CRC相同，非正式分数。
状态/容量核对见同目录`batch42-final-audit.json`。ROI提交345517条指令，
IPC=345517/646056≈0.5348；不是整个程序或所有负载的固定IPC。

一次新整板综合、布局、物理优化和布线已完成，实际RAMB INIT、地址/数据连接及禁写门禁通过。
CPU300最终WNS **−0.379ns**、TNS **−163.774ns /1695个失败端点**；hold +0.009ns、
脉宽 +0.081ns。相较batch41最终WNS −0.103ns，这次是物理退步，不能将逻辑级数减少
或JTAG局部转正当作整板优化成功。没有继续不受限的物理循环，也没有生成bit。

| 定点端点组 | batch42最差setup裕量 |
| --- | ---: |
| Home状态机 | −0.277ns |
| PC请求寄存器 | −0.376ns |
| I-cache返回/指令对齐 | −0.253ns |
| JTAG sbError控制 | +0.025ns |
| Home probeAddress | +0.458ns |
| D-cache元数据RAM写使能 | +1.701ns |

全局最差为offerPc[3]→BTB RAM/标签与候选选择→desiredPc[56]，数据延迟3.605ns，
10级逻辑，布线占68.8%。Home owned[234]→state[1]为9级、布线占75.4%；
取指pending_address[23]→aligner result_instruction[27]为9级、布线占71.5%。
这轮one-hot/并行译码及候选扇出未带来更好的最终放置布线，后续不能继续沿用“更平坦一定更快”的假设。

最终资源95004 LUT、55299 FF、63.5 BRAM36等效、31 DSP，较batch41增加916 LUT和174 FF。
DDR UI250 setup/hold +0.366/+0.010ns，AON/UART50 +2.892/+0.016ns；
140200条可路由网络全部完成、0路由错误，DRC无Error/Critical。
20项bus-skew全部满足，最小裕量1.499ns；既有9个复位CDC Critical端点与基线一致，
结构/释放检查通过，但不代表完整CDC签核，也未做新实板验证。

证据目录`E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261018-batch42-r1/`：
`batch42-result.json`绑定冻结输入、短收据、精确ROM及报告哈希；`reports/target_timing.tsv`
及六份`target_*.rpt`与全局报告来自同一个最终路由DCP。
该候选保留作失败证据，不将它替换为已通过300MHz的版本。原乱序核和现有多时钟域未改。

## batch41：两条主链转正，整板 CPU300 仍未通过（2026-10-18）

在修复版 BootROM 的真实整板 WNS −0.116ns 基础上，保持 CPU300/UI250/AON50/UART50、
I/D各32KiB、原有事务/队列槽位和 no-MAC 配置。原乱序核及共享 IP 源码不改。

- Home：仅在 idle 时预准备尚未被占用的 probe/access 数据；真正准入、probe 授权和
  双读/写回重叠的条件及周期不变，不把宽地址判定串进 payload 寄存器使能。
- DT→缓存：4项原子返回格式元数据 FIFO 仅预写空闲行，真实握手才推进指针；
  不在满队列借 dequeue 信用、不覆盖已占用条目、不改变回复时序。
- 相邻负链：PMP NAPOT/NA4 边界增量用既有分段进位；I1 JTAG 常量窗口用紧凑译码。
  均受已有 timing-cuts 参数控制，默认/关闭配置保留原行为。
- BootROM 初始化宏、512×64 实际 RAMB INIT/地址/数据/禁写检查继续保留。

短验证入口 `simulator/gsim/inorder/bandwidth41_acceptance.py`，完整通过后用
`audit_batch41_short.py` 核对源哈希、存储容量、六项实际 CPU 流量和 CoreMark逐周期不退步。
新增 metadata 2/4/8 项独立队列检查及 JTAG/CSR direct/cuts 对照与负控。
旧 CSR 驱动直接用于 timing-cuts 时未考虑既有 IRQ 快照的一拍；新编译宏明确验证
“CSR 写入当拍清旧快照、下一拍才报告新 IRQ”，不是改变硬件 IRQ 延迟或跳过检查。

2026-10-18 短收据 `build/gsim/i1-bandwidth41-20261018-r3/receipt.json` 已通过
63项检查/13项性能门；390个源码及279个产物已回读哈希核验。
六项 Bare/Sv39（含80拍内存响应）流量结果逐项相同，短 O3 CoreMark ROI 保持646056拍，
提交轨迹和 CRC 相同；这不是满足10秒规则的正式 CoreMark 分数。
FIR寄存器声明6999项、存储声明89项不变；FIFO内部命名规范化后状态结构相同，
Home目录保持4个单写口，无新增槽位或数据RAM。物理资源和300MHz结论仍以新整板报告为准。

BootROM 验证使用 `check_bootrom_boot.py --board-manifest <旧板清单> --short-receipt <新短收据>`；
旧清单只提供保持不变的配置，新 CPU 源码哈希必须来自已完成的新收据。
导出后使用 `audit_board41_stage.py`，不使用“RTL完全不变”的初始化专用审计冒充本轮结果。
只有新整板 setup/hold/脉宽、路由、DRC及既有 CDC 边界复核通过后才允许生成 bit。
旧 BootROM 缺失的 dev2-r4 bit 不能作为本轮通过证据。

本轮已完成一次完整整板综合实现，以及一次基于已路由DCP的有界物理优化；不再追加循环。
最终状态 `BATCH41_SHORT_BOOTROM_PASS_CPU300_SETUP_FAIL_NO_BIT`，CPU300 WNS −0.103ns、
TNS −4.219ns/137个失败端点，hold +0.010ns、脉宽 +0.081ns。上一版修复BootROM后的最终值
为 WNS −0.116ns、TNS −12.386ns/251端点；最坏裕量仅改善13ps，仍不能交付300MHz bit。
DDR UI250 setup/hold +0.224/+0.011ns，AON/UART50 +1.982/+0.019ns。
资源94088 LUT、55125 FF、63.5 BRAM36等效、31 DSP，比上一版最终减少662 LUT、493 FF。
137145条可路由网络全部完成；DRC无Error/Critical，20项总线偏斜约束全部满足，最小裕量2.381ns。
既有9个复位CDC Critical端点不变，结构/释放检查保留；仍不声称完整CDC签核。

直接从最终DCP另取定点报告，确认不是单纯换了一条最差路径而未处理原链：

| 目标端点组 | 最差 setup 裕量 |
| --- | ---: |
| Home probeAddress 数据/使能/复位输入 | +0.995ns |
| D-cache原子元数据FIFO RAM写使能 | +1.986ns |
| PMP effectiveUpper边界寄存器 | +0.177ns |
| JTAG sbError控制寄存器 | −0.041ns |

剩余最差路径为 ownershipCut地址→Home状态机 −0.103ns；I-cache probeResume→对齐器
firstHalf −0.101ns、PC预测回环 −0.101ns也仍需处理。不能把本轮目标端点转正等同于整板通过。
真实CPU BootROM/UART再次通过（216722拍、33字节、460800解码、空ROM/错banner负控）；
综合及最终路由RAMB内容均逐字核对4096字节。**无新bit，未做新一轮实板测试。**

产物目录 `E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261018-batch41-r1/`：
`reports/`保留初次路由（WNS −0.120ns），`postroute-r1/`为最终报告，`target-audit/`为定点报告，
`batch41-result.json`保存结果及输入/报告哈希。综合子进程约5分16秒；随后布局/物理优化约23分钟、
初次路由约7分32秒；没有在此期间追加RTL修改或GSIM范围。

## 2026-10-17 BootROM 交付缺陷与修复门禁

**dev2-r4 的旧 bit 不可作为正常启动版本使用。** 实板无 UART 输出后，回读最终 DCP
发现 BootROM 内无 RAMB，64 位数据输出未连接；综合日志明确警告 `Memory ... does not have driver`。
整板入口缺少 `ENABLE_INITIAL_MEM_`，导致 CIRCT 包装的 `$readmemh` 被综合预处理排除。
此前“已拷贝 hex、ROM 已固化”和旧物理时序 PASS 均不能证明正确 ROM 的整板通过；
旧 bit/DCP 保留为缺陷证据，修复后必须重新综合实现，不沿用旧时序作为新版结论。

修复仅改变综合初始化和验证入口，不改变 CPU RTL、槽位、缓存容量或多时钟域。
`configure_board_mem.tcl` 显式启用该宏，pre-synth 检查宏及 512×64 hex。
`audit_board_bootrom.tcl` 在综合后和路由后读取实际 RAMB36E2 的全部 INIT/INITP，
校验地址/数据映射、读延迟和禁写连接，再逐字比较 4096 字节；无 ROM、错内容或错映射均拒绝。
短验证 `check_bootrom_boot.py` 执行真实 CPU BootROM、独立解码 460800 UART TX，
并检查空 ROM/错 banner 负控。GSIM 使用单 CPU300 时钟，不冒充物理 UART50 CDC 仿真。
新增 `--bootrom-receipt` 为整板导出必需项；最终 bit 仍须重新检查实际时钟、setup/hold、
DRC、路由状态和既有 CDC 边界。尚未通过修复后物理/实板验收时不得宣称修复 bit 可用。

本轮最终状态为 `BOOTROM_FIX_PASS_CPU300_TIMING_FAIL_NO_BIT`：真实 CPU 短 GSIM
解码出全部33字节启动消息；空 ROM/错误消息负控通过；实际 RAMB 网表2正例/7负控通过。
新的综合及最终路由网表均已逐字核对4096字节 ROM。完整整板实现及一次有界后路由优化
已结束，CPU300 WNS −0.116ns、TNS −12.386ns、251个 setup 失败端点；hold +0.010ns、
脉宽裕量 +0.081ns。DDR UI250 setup/hold +0.228/+0.011ns，AON/UART50 +2.644/+0.015ns。
资源为94750 LUT、55618 FF、63.5 BRAM36等效、31 DSP；138348条可路由网络全部完成。
最差链为 ownershipCut 请求地址→Home probeAddress 控制，DT→D-cache 元数据写使能仍有负裕量。
既有9项复位 CDC Critical 端点与旧版一致，不新增豁免、不声称完整 CDC 签核。
**未生成新 bit；旧 dev2-r4 的时序通过结果不能代替修复版。**

本轮产物：`E:/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-bootrom-r1/`，
最终报告在 `postroute-r1/`，状态/哈希见 `repair-result.json`。
冻结的综合检查器实际比较全部64位，但 Tcl 的 `%016x` 打印仅显示低32位；只修正了显示器，
未修改已运行的综合输入。重新回读实际 DCP 的完整字值见
`release-audit/bootrom_post_synth_full64.txt` 和 `postroute-r1/bootrom_post_route.txt`。
低32位、奇偶存储区及高28位分别做错误注入，均被门禁拒绝。

当前 no-MAC 候选保留真实 MIG DDR4（2GiB）、AXI 时钟转换 IP、Clock Wizard、
UART/AON50MHz、I/D 各32KiB、F/D、Sv39、PLIC、CMU 与 USER2/65位扫描。
CPU300MHz / DDR UI250MHz / UART50MHz 保持现有独立时钟域，不合并、不降频。
通用 DMA、网络 DMA 均不在当前 no-MAC 板级候选内。

最新batch40入口：bandwidth40完整短收据（49检查/13性能门）→
audit_batch40_short.py→export_board_cpu.py。dev2-r4已通过短验收/状态与哈希审计，
CPU hold保护加严至80ps。一次真实整板实现及一次后路由优化已完成，最终报告在
dev2-r4/postroute-r1/：CPU300 setup 0.000ns（MET）、hold +0.010ns，TNS/THS/脉宽失败均为0。
DDR250 +0.358/+0.010ns，AON/UART50 +0.619/+0.040ns；93788 LUT/55189寄存器/BRAM62.5/DSP31。
setup贴线通过，不宣称充足裕量；原9项复位CDC Critical和边界例外仍需单列，不算全CDC签核。
2026-10-17 20:14按用户要求已从上述路由DCP生成bit，没有重复综合或实现。
文件为`dev2-r4/bitstream/orbital_i1_rv64gc_cpu300_i32k_d32k_uart460800_jtag65_nomac.bit`，
交付记录为`dev2-r4/bitstream/delivery.json`；旧清单中的bit_generated=false保留历史阶段含义。
USER2精确65位接受、66位拒绝已做真实双TAP RTL仿真；实板JTAG下载尚待测试。
本版无MAC/网络启动，UART为460800。原始reports/保留失败基线，postroute-r1/才是最终结果。
上一批候选dev2-r3已完成一次真实整板实现
和一次有界后路由优化；旧dev2-r2报告不是新版结果。
当前采用Explore放置/物理优化并保存DCP，再按原约束做时序驱动-no_psir路由，
与batch38最终可完成策略一致；并非Quick，不重做已完成阶段。
audit_board_reset_cdc.tcl逐端点核查复位链和功能释放恢复/移除时序，
不添加豁免；同步器复位端的既有例外单列，不能把无穷裕量当作通过。
上一批最终报告在dev2-r3/postroute-r1/：CPU300 setup −0.017ns、hold +0.003ns，
TNS −0.418ns/70端点，仍未满足300MHz。DDR UI250 +0.165/+0.010ns；
AON/UART50 +2.477/+0.019ns。整板93624 LUT、55121寄存器、BRAM62.5、DSP31。
137383条可路由网络全部完成；DRC40条Warning、无Error/Critical。
9项复位CDC Critical与旧版端点一致，无新豁免；不宣称完整CDC签核。
保留初次路由reports/和后路由postroute-r1/，不生成bit、不追加实现轮次。
Vivado工程impl_1止于保存的phys_opt；最终route在同一DCP的非工程上下文完成，
应读取上述Routed报告，不因GUI未显示route完成而重置或重跑。

## batch38 目录叶模块检查

本轮短验收见 build/gsim/i1-bandwidth38-20261017-r1/receipt.json。
check_directory_writer.py 仅接受完整且源码哈希匹配的 batch38 PASS；从该 CPU FIR
提取256x20、六读口/单写口叶模块。已实测700 LUT（576 LUTRAM）、0 FF，
证据在 E:/VM/Share/Valence-rtl/orbital-i1-directory38-20261017-r1/。
这不是 CPU/整板时序验证，不能以此宣称300MHz或报告新版整板资源。

## 已登记的严格整板入口（当前 batch40）

batch38/39/40 已注册独立验收 schema：同参数/同流量/同 CoreMark、零新增状态/槽位、
单写口且保留六读口的实际 LUTRAM 证明、原乱序核/共享 IP 不变、真实 USER2 证明。
整板生成的目录原始叶模块必须与已单独验证的叶模块逐字节一致。
新版源码不能套旧收据；所有源码/产物与 RAM/JTAG 检查保留。

~~~sh
python3 fpga/inorder/export_board_cpu.py \
  --receipt build/gsim/i1-bandwidth40-20261017-r1/receipt.json \
  --bootrom-receipt build/gsim/i1-bootrom-uart-20261017-r1/receipt.json \
  --output /mnt/e/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-bootrom-r1 \
  --ip-reference /mnt/e/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-dev2-r4
~~~

该入口检查源码/产物哈希、batch40 的49项检查/13项性能门和最终审计、
固定 HardFloat、真实双 TAP/CDC 证明；完整透传测试开关，整理 RAM 注解、
BootROM、USER2 黑盒、XDC 与 IP。仅复用已完成的 MIG/时钟/AXI CDC IP，
不复用旧 CPU 检查点。收据和 IP 参考须先存在；输出目录必须全新。

dev2-r4已完成完整build_board_cpu.tcl及一次后路由优化，不要再运行下面的历史综合入口。
Vivado命令的-log/-journal等工具参数必须在-tclargs之前，后者后面仅传候选根目录。
本轮reports/为初次路由WNS−0.100ns，最终postroute-r1/才是setup/hold通过结果。

历史batch38命令（Windows Vivado batch；旧dev2-r2目录已归档，勿直接运行）：

~~~powershell
& E:\Xilinx\2025.1\Vivado\bin\vivado.bat -mode batch -notrace -source E:\VM\Share\Valence-rtl\orbital-i1-cpu300-board-20261017-dev2-r2\scripts\synth_board_cpu.tcl -tclargs E:\VM\Share\Valence-rtl\orbital-i1-cpu300-board-20261017-dev2-r2
~~~

输出 synthesis-reports/：整板及分域 setup/hold、资源、实际时钟、CDC、约束覆盖、DCP。
综合估计不是布局布线签核，正 WNS 也不能直接生成 bit。
build_board_cpu.tcl 是另一条会继续布局布线的入口，仅在明确要求完整实现时使用。
2026-10-17 15:39（北京时间）用户要求继续后，dev2-r2 已启动一次完整整板实现，
不生成 bit。上述单独综合命令不能同时启动，也不能重置正在运行的 dev2-r2。
结果以 dev2-r2/reports/ 的实际报告为准，不以 batch37 的旧 WNS 替代。

### 2026-10-17 batch38 历史结果（当时未生成 bit，不代表当前 batch40）

Home单写口已恢复LUTRAM推断。同综合口径LUT156094→93883；
最终整板路由为92982 LUT /55150寄存器 /BRAM62.5 /DSP31。
CPU300 setup WNS−0.316ns、hold+0.010ns，尚未达标；
DDR UI250 +0.244/+0.011ns，AON/UART50 +1.798/+0.027ns。
9项原有复位CDC Critical、外部复位/UART边界提示仍需审计，不是整板签核。

原Explore流程在末尾Leaf ClockOpt Init崩溃，失败日志和空转储保留。
最终报告来自已完成物理优化DCP的一次时序驱动恢复：
`route_design -no_psir -timing_summary`。未修改RTL/频率/时序约束，
未重复综合或放置；该恢复策略与Explore不同，不能混淆。
恢复脚本、最终复核清单、报告路径见候选reports/implementation-review.json；
不要重启build_board_cpu.tcl或覆盖现有证据，后续查询使用real_board_routed.dcp。

## 其余文件

- export*.py、stage_board.py：历史 OOC/SoC/网络及当前整板导出，验收范围不同。
- board*constraints.tcl、bscan_timing_i1.tcl：真实板时钟/CDC/引脚/共享 JTAG。
- bootrom/：BootROM 可复现源码；文本初始化资产在 src/main/resources/inorder/。
- check*.py、audit*.py、test*.py：独立证明与工具单元测试。
- report*.tcl、review*.tcl、collect*.py：复用检查点查询/归档，不自动验证新版。
- resume*、repair*、retime*、revise_board_scripts.py：历史受限续跑工具，
  不能替代当前严格入口。network32-profile.json 不是当前 no-MAC 配置。

本地小证据归档：/home/openion/Valence-inorder-evidence/pre-dev2-20261017-r1。
当前完整产物保留在 Git 忽略的 build/ 与 Windows dev2-r4 输出目录；
直接引用的dev2-r3和directory38证明也保留。18个旧I1输出和31个WSL旧目录已清理，
有用文件与恢复说明见`/home/openion/Valence-inorder-evidence/cleanup-20261017-bit40-r1`。
旧Windows DCP/仿真缓存未归档，不能从该备份恢复；原乱序工程及当前I1改动未丢弃。
