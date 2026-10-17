# Orbital-I1 FPGA 入口

本目录只保留板级源码/工具，不存放导出的 RTL、Vivado 工程、DCP 或 bit。
完整架构、每批性能/时序和未完成门禁见 [工程记录](../../docs/orbital-i1.md)。

当前 no-MAC 候选保留真实 MIG DDR4（2GiB）、AXI 时钟转换 IP、Clock Wizard、
UART/AON50MHz、I/D 各32KiB、F/D、Sv39、PLIC、CMU 与 USER2/65位扫描。
CPU300MHz / DDR UI250MHz / UART50MHz 保持现有独立时钟域，不合并、不降频。
通用 DMA、网络 DMA 均不在当前 no-MAC 板级候选内。

## 当前严格入口

~~~sh
python3 fpga/inorder/export_board_cpu.py \
  --receipt build/gsim/i1-bandwidth37-20261017-r8/receipt.json \
  --output /mnt/e/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-dev2-r1 \
  --ip-reference /mnt/e/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-r11
~~~

该入口检查源码/产物哈希、batch37 的29项检查/13项性能门和最终审计、
固定 HardFloat、真实双 TAP/CDC 证明；完整透传测试开关，整理 RAM 注解、
BootROM、USER2 黑盒、XDC 与 IP。仅复用已完成的 MIG/时钟/AXI CDC IP，
不复用旧 CPU 检查点。收据和 IP 参考须先存在；输出目录必须全新。

只综合一次（Windows Vivado batch）：

~~~powershell
& E:\Xilinx\2025.1\Vivado\bin\vivado.bat -mode batch -notrace -source E:\VM\Share\Valence-rtl\orbital-i1-cpu300-board-20261017-dev2-r1\scripts\synth_board_cpu.tcl -tclargs E:\VM\Share\Valence-rtl\orbital-i1-cpu300-board-20261017-dev2-r1
~~~

输出 synthesis-reports/：整板及分域 setup/hold、资源、实际时钟、CDC、约束覆盖、DCP。
综合估计不是布局布线签核，正 WNS 也不能直接生成 bit。
build_board_cpu.tcl 是另一条会继续布局布线的入口，仅在明确要求完整实现时使用。

## 其余文件

- export*.py、stage_board.py：历史 OOC/SoC/网络及当前整板导出，验收范围不同。
- board*constraints.tcl、bscan_timing_i1.tcl：真实板时钟/CDC/引脚/共享 JTAG。
- bootrom/：BootROM 可复现源码；文本初始化资产在 src/main/resources/inorder/。
- check*.py、audit*.py、test*.py：独立证明与工具单元测试。
- report*.tcl、review*.tcl、collect*.py：复用检查点查询/归档，不自动验证新版。
- resume*、repair*、retime*、revise_board_scripts.py：历史受限续跑工具，
  不能替代当前严格入口。network32-profile.json 不是当前 no-MAC 配置。

本地小证据归档：/home/openion/Valence-inorder-evidence/pre-dev2-20261017-r1。
完整产物保留在 Git 忽略的 build/ 或 Windows 共享输出目录。
