# Orbital-I1 FPGA 入口

本目录只保留板级源码/工具，不存放导出的 RTL、Vivado 工程、DCP 或 bit。
完整架构、每批性能/时序和未完成门禁见 [工程记录](../../docs/orbital-i1.md)。

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
  --output /mnt/e/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-dev2-r4 \
  --ip-reference /mnt/e/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-dev2-r3
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
