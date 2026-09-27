# 在 Windows Vivado 检查当前 SoC 的内部时序

Linux 虚拟机中运行 `make fpga-current-soc-rtl`。命令导出
`build/fpga-current-soc/` 目录，其中包含生成的 SystemVerilog、
`vivado-ooc.tcl` 和 Windows 批处理入口。通过共享文件夹或直接复制整个目录到
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
当前虚拟机没有 Vivado，Vivado 端执行结果需要在 Windows 上取得。
